"""Frozen numerical estimator with column-projected, single-buffer model input."""
from r9_common import *

def make_job(source,scores,output,conf,sample,kind,level,variant='A',cohort='full',material=None,flags=None,split=None,
             score_mode='new',control_mode='matched',figure=False):
    n=pq.ParquetFile(source).metadata.num_rows
    return dict(input=str(source),scores=str(scores),output=str(output),conf=conf,sample=sample,kind=kind,level=level,
        variant=variant,cohort=cohort,material=str(material) if material else None,flags=str(flags) if flags else None,split=split,
        score_mode=score_mode,control_mode=control_mode,figure=figure,
        memory_gb=1.1+n*540/1024**3)

def selection(job):
    ids=col(job['input'],'row_id');sid=col(job['scores'],'row_id')
    u.require(np.array_equal(ids,sid),'Score/source identity or order mismatch');del sid
    use=np.ones(len(ids),bool)
    if job['cohort']=='timing_common':
        for v in ('B','C'):
            use &= (col(job['scores'],'n_'+v)>=5)&np.isfinite(col(job['scores'],'adjusted_'+v))
    elif job['cohort']=='neutral':
        u.require(job['material'] is not None,'Material screen lacks frozen flags')
        m=r.arrays(r.io.read(job['material'],['row_id','material_valid','material_neutral']))
        u.require(np.array_equal(ids,m['row_id']),'Material identity mismatch')
        use &= m['material_valid'].astype(bool)&m['material_neutral'].astype(bool)
    if job.get('split'):
        key,value=job['split'];u.require(job.get('flags') is not None,'Learning split lacks chronology flags')
        f=r.arrays(r.io.read(job['flags'],['row_id',key]));u.require(np.array_equal(ids,f['row_id']),'Learning identity mismatch')
        use &= f[key].astype(bool)==value
    return ids,use

def build_buffer(job):
    """Only one source column is decoded at a time; no full-frame pandas copy.

    Transforms/standardization and FE labels exactly reproduce feature_design.
    Outcomes, seven traits, and controls share the owned Fortran FWL allocation.
    """
    ids,use=selection(job);n=int(use.sum());allrows=bool(use.all())
    def read(name,path=None):
        a=col(path or job['input'],name)
        return a if allrows else a[use]
    names=list(r.X0)+(r.ENV+['env_supported'] if job['level']=='X0_ENV_indicator' else [])
    outs=models.model_outcomes({},job['kind']);width=1+len(outs)+len(r.T30)
    meta=dict(sample=job['sample'],control_level=job['level'],score=job['variant'],cohort=job['cohort'],
        split=job.get('split'),n=n,row_set_sha256=r.design.row_digest(ids[use]),
        controls=names,clustering='shared_account_OR_date_CR0',generated_scores_treated_as_fixed=True,
        causal_identification_certified=False,score_mode=job['score_mode'],control_mode=job['control_mode'],
        post_focal_donors_allowed=job['variant'] in ('A','C'),history_count_transform='log1p',
        history_controls_donor_set=job['variant'] if job['control_mode']=='matched' else 'frozen old cutoff')
    count=read('n_'+job['variant'],job['scores'])
    rawscore=read('old_adjusted' if job['score_mode']=='old' else 'adjusted_'+job['variant'],job['scores'])
    invalid=(count<5)|~np.isfinite(rawscore)
    if invalid.any() or n<2000:
        meta.update(supported=False,reason='DONOR_SUPPORT_INCOMPLETE_FIXED_ROWS_RETAINED' if invalid.any() else 'FEWER_THAN_2000_ROWS',
                    unsupported_donor_rows=int(invalid.sum()),rows_removed_for_donor_support=0)
        return None,None,None,meta,None,None
    v=np.empty((n,width+len(names)),float,order='F');v[:,0]=rawscore;del count,rawscore
    ystats={}
    for j,k in enumerate(outs):
        a=read(k);u.require(np.isin(a,[0,1]).all(),'Nonbinary/missing frozen outcome: '+k)
        v[:,1+j]=a;ystats[k]=dict(events=int(a.sum()),outcome_mean_pp=float(a.mean()*100))
    del a
    control_index={k:width+j for j,k in enumerate(names)}
    trait_index={k:1+len(outs)+j for j,k in enumerate(r.T30)}
    def fill(name,a,standard=True):
        a=np.asarray(a,float)
        u.require(np.isfinite(a).all(),'Nonfinite control/trait: '+name)
        if standard:
            sd=float(a.std());a=(a-a.mean())/(sd if sd>1e-12 else 1.)
        if name in control_index:v[:,control_index[name]]=a
        if name in trait_index:v[:,trait_index[name]]=a
    ir=read('recipient_rating');jr=read('opponent_rating');gap=(jr-ir)/100.
    fill('recipient_rating',ir);fill('rating_gap',gap);fill('rating_gap_square',gap*gap);fill('abs_rating_gap',np.abs(gap));del gap
    _,cell=r.num.factor(read('month_code'),read('tc_base_s'),read('tc_inc_s'),np.floor((ir+jr)/200).astype(np.int64));del ir,jr
    dates=read('archive_start_ms');groups=[cell,dates//DAY,(dates//3600000)%168]
    idcols=dict(row_id=ids[use],recipient_id=read('recipient_id'),opponent_id=read('opponent_id'),date=dates//DAY)
    del ids,dates
    if job['control_mode']=='matched':
        cp=job['scores'];cn='n_'+job['variant'];cb='counterparts_'+job['variant'];ce='expected_'+job['variant']
    else:cp=job['input'];cn='n_7d';cb='counterparts_7d';ce='expected_7d'
    fill('log_opponent_prior_decisions',np.log1p(read(cn,cp)))
    fill('log_opponent_prior_counterparts',np.log1p(read(cb,cp)))
    fill('opponent_history_expected_rate',read(ce,cp))
    for days in (90,30):
        fair=read(f'fair_{days}');kind=read(f'kind_{days}')
        fill(f'fair_history_present_{days}',fair>0);fill(f'log_fair_{days}',np.log1p(fair))
        fill(f'kind_ever_{days}',kind>0)
        fill(f'kind_rate_{days}',np.divide(kind,fair,out=np.zeros(n),where=fair>0));del fair,kind
        for name in ('disconnect','receipt','claim'):fill(f'log_{name}_{days}',np.log1p(read(f'{name}_{days}')))
    fill('log_volume_30',np.log1p(read('pre_games_30d')))
    if 'ENV' in job['level']:
        supported=read('environment_supported').astype(bool)
        for name in r.ENV:
            a=np.asarray(read(name),float).copy();u.require(np.isfinite(a[supported]).all(),'Supported ENV rate missing')
            a[~supported]=0.;fill(name,a)
        fill('env_supported',supported.astype(float),False)
        meta['environment_unsupported_share']=float((~supported).mean())
    meta['recipients']=len(np.unique(idcols['recipient_id']))
    return v,groups,idcols,meta,outs,ystats

def project_buffer(v,groups,width):
    v,diag=absorb_owned(v,groups)
    x=v[:,width:];gram=x.T@x;inv=np.linalg.pinv(gram,rcond=1e-12)
    rank=int(np.linalg.matrix_rank(gram,tol=max(float(np.linalg.norm(gram,2)),1)*1e-12))
    beta=inv@(x.T@v[:,:width]);del x
    for lo in range(0,len(v),32768):v[lo:lo+32768,:width]-=v[lo:lo+32768,width:]@beta
    v.resize((len(v),width),refcheck=False)
    return v,rank,diag

def estimate(job):
    v,groups,ids,meta,outs,ystats=build_buffer(job)
    out=dict(estimates=[],balance=[],joint_balance=[],figure5=[])
    if v is None:
        out['estimates']=[meta];return out,None
    n=len(v);width=1+len(outs)+len(r.T30)
    r.io.log(f'R9 {job["sample"]} {job["variant"]} {job["cohort"]} {job["level"]}: FWL on {n:,} rows')
    res,rank,diag=project_buffer(v,groups,width);del groups,v
    z=res[:,0];ys=res[:,1:1+len(outs)];ts=res[:,1+len(outs):]
    zz=float(z@z);native=math.sqrt(zz/n);u.require(native>1e-10,'No residual score variation')
    meta.update(native_residual_score_SD=native,continuous_control_rank=rank,absorb_iterations=diag['iterations'])
    codes=r.stats.cmp.covariance_codes(ids['recipient_id'],ids['opponent_id'],ids['date'])
    meat=lambda s:shared_meat(s,codes,True)
    payload=dict(ids);fitmap={}
    for j,name in enumerate(outs):
        fit,inf=m7.scalar(ys[:,j],z,meat);fitmap[name]=fit
        if min(ystats[name]['events'],n-ystats[name]['events'])<10:fit.update(supported=False,reason='FEWER_THAN_TEN_EVENTS_OR_NONEVENTS')
        row=dict(meta,outcome=name,estimator='first_stage' if name=='received' else 'reduced_form',**ystats[name],**fit)
        if fit.get('standard_error') is not None:row['wald_F_one_df']=(fit['coefficient']/fit['standard_error'])**2
        out['estimates'].append(row);payload[name]=inf
    if job['kind']=='iv':
        iv=r.stats.iv_result(ys[:,1],ys[:,0],z,meat)
        fields={k:v for k,v in iv.items() if k not in ('first_stage','reduced_form')}
        for k in ('iv_coefficient','iv_standard_error','iv_ci_low','iv_ci_high'):
            if k in iv:fields[k+'_pp']=100*iv[k]
        first=fitmap['received']
        out['estimates'].append(dict(meta,outcome='y',estimator='2SLS',units='percentage points per receipt',
            first_stage_F=(first['coefficient']/first['standard_error'])**2 if first.get('standard_error') else None,**fields))
        beta=iv.get('iv_coefficient')
        if beta is not None:payload['iv_y']=100*z*(ys[:,1]-beta*ys[:,0])/float(z@ys[:,0])
    for j,trait in enumerate(r.T30):
        fit=r.stats.stats.ols(ts[:,j],z/native,meat)
        out['balance'].append(dict(meta,trait=trait,units='trait SD per native residual-score SD',**fit))
    r.stats.stats.holm(out['balance'],out='p_Holm_7_traits')
    out['joint_balance'].append(dict(meta,test_set='T30_stacked_trait_on_score',traits=r.T30,**r.stats.stats.joint(ts,z/native,meat)))
    if job.get('figure'):
        # The bin means are descriptive residual means; CR0 conditional on the fitted FE/controls.
        # One vector per bin avoids an n-by-20 covariance allocation.
        order=np.argsort(z,kind='stable');bins=np.array_split(order,20)
        for b,ix in enumerate(bins,1):
            mean=float(ys[ix,0].mean());inf=np.zeros(n);inf[ix]=(ys[ix,0]-mean)/len(ix)
            var=float(meat(inf)[0,0]);fit=m7.inference(mean,var,100)
            out['figure5'].append(dict(bin=b,rows=len(ix),mean_residual_score=float(z[ix].mean()),
                mean_residual_receipt_pp=100*mean,ci95_low_pp=fit.get('ci_low_pp'),ci95_high_pp=fit.get('ci_high_pp'),
                supported=fit['supported'],tie_rule='stable row_id order; exact equal counts differ by at most one',
                interval='shared-account-OR-date CR0 conditional on fitted residuals and bins',
                plot_x_units='native residual score',plot_y_units='residual receipt in percentage points',**meta))
        out['figure5'].append(dict(record_type='linear_first_stage',
            slope_receipt_pp_per_unit_residual_score=100*out['estimates'][0]['coefficient'],**out['estimates'][0]))
    return out,payload

def fit_job(job):
    r.threads_one();u.no_network()
    deps=[job['input'],job['scores']]+[job[k] for k in ('material','flags') if job.get(k)]
    def build(tmp):
        result,inf=estimate(job);r.io.js(tmp/'result.json',result)
        if inf is not None:r.io.table(tmp/'influence_PRIVATE.parquet',pa.table(inf))
        return dict(n=result['estimates'][0]['n'],sample=job['sample'],variant=job['variant'],cohort=job['cohort'],
            level=job['level'],supported=result['estimates'][0].get('supported',False),influence_saved=inf is not None)
    return r.stable_stage(Path(job['output']),job['conf'],build,deps)[1]

def contrast_job(job):
    r.threads_one();u.no_network()
    left,right=Path(job['left']),Path(job['right'])
    deps=[p/n for p in (left,right) for n in ('result.json','influence_PRIVATE.parquet')]
    def build(tmp):
        a=u.load(left/'result.json')['estimates'];b=u.load(right/'result.json')['estimates']
        l=r.arrays(r.io.read(left/'influence_PRIVATE.parquet'));rr=r.arrays(r.io.read(right/'influence_PRIVATE.parquet'))
        codes=r.stats.cmp.covariance_codes(np.r_[l['recipient_id'],rr['recipient_id']],np.r_[l['opponent_id'],rr['opponent_id']],np.r_[l['date'],rr['date']])
        rows=[]
        for name in job['outcomes']:
            iv=name=='iv_y';outcome='y' if iv else name;estimator='2SLS' if iv else 'reduced_form'
            aa=next(x for x in a if x.get('outcome')==outcome and x.get('estimator')==estimator)
            bb=next(x for x in b if x.get('outcome')==outcome and x.get('estimator')==estimator)
            field='iv_coefficient_pp' if iv else 'coefficient'
            # Two columns ensure the actual cross-equation covariance is recorded.
            influence=np.zeros((len(l[name])+len(rr[name]),2),order='F')
            influence[:len(l[name]),0]=l[name];influence[len(l[name]):,1]=rr[name]
            V=shared_meat(influence,codes,True);var=float(V[0,0]+V[1,1]-2*V[0,1])
            row=dict(contrast=job['label'],control_level=job['level'],outcome=outcome,estimator=estimator,
                left_coefficient=aa[field],right_coefficient=bb[field],left_n=aa['n'],right_n=bb['n'],
                left_row_set_sha256=aa['row_set_sha256'],right_row_set_sha256=bb['row_set_sha256'],
                covariance_matrix=V.tolist(),stacked_actual_accounts_and_dates=True,
                units='percentage points per receipt' if iv else 'native probability per unit score',
                **m7.inference(aa[field]-bb[field],var))
            rows.append(row)
        r.io.js(tmp/'result.json',rows);return dict(contrasts=len(rows))
    return r.stable_stage(Path(job['output']),job['conf'],build,deps)[1]

def calibration_job(job):
    r.threads_one();u.no_network()
    def build(tmp):
        d=r.load_fit_columns(job['input']);a=r.arrays(r.io.read(job['scores'],['row_id','n_A','counterparts_A','expected_A','adjusted_A']))
        u.require(np.array_equal(d['row_id'],a['row_id']),'Calibration row identity mismatch')
        for k,new in [('n_7d','n_A'),('counterparts_7d','counterparts_A'),('expected_7d','expected_A'),('adjusted_7d','adjusted_A')]:d[k]=a[new]
        xs,names,traits,groups=r.feature_design(d,job['level']);t=np.column_stack([traits[k] for k in r.T15]);del traits,a
        # User specifies X0-NH in stage one: the seven named X0 nonhistory controls, no ENV terms.
        xtrain=xs[:,[names.index(k) for k in r.NH]];meat=m7.covariance(d);rows=[]
        for name in ('y','received'):
            fit=m7.generated_index(t,np.asarray(d[name],float),xtrain,xs,np.asarray(d['adjusted_7d'],float),groups,meat)
            rows.append(dict(sample='S0',cohort='full',score='A',control_level=job['level'],outcome=name,
                analysis='R7_A3_trait_component',training_controls=r.NH,outer_controls=names,standardized_traits=r.T15,
                n=len(d['row_id']),row_set_sha256=r.design.row_digest(d['row_id']),**fit))
        r.io.js(tmp/'result.json',rows);return dict(rows=len(rows),observations=len(d['row_id']))
    return r.stable_stage(Path(job['output']),job['conf'],build,[job['input'],job['scores']])[1]
