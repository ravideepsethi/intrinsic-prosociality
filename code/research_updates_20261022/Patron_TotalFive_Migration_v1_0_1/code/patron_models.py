"""Weighted FWL with explicit FE orthogonality and exact shared-account OR date CR0."""
import math,time
import numpy as np
from patron_common import *
from patron_memory import absorb_owned,shared_meat

def factor(*values):
    arrays=[np.asarray(v) for v in values]
    keys=np.empty(len(arrays[0]),dtype=[('f'+str(k),v.dtype) for k,v in enumerate(arrays)])
    for k,v in enumerate(arrays):keys['f'+str(k)]=v
    return np.unique(keys,return_inverse=True)[1]

def covariance_codes(i,j,date):
    i=np.asarray(i,np.int64);j=np.asarray(j,np.int64);date=np.asarray(date,np.int64)
    require(not np.any(i==j),'Self-pair in model')
    lo,hi=np.minimum(i,j),np.maximum(i,j)
    return dict(accounts=np.unique(np.r_[i,j],return_inverse=True)[1],pairs=factor(lo,hi),
                dates=np.unique(date,return_inverse=True)[1],
                account_dates=factor(np.r_[i,j],np.r_[date,date]),pair_dates=factor(lo,hi,date))

def weighted_absorb(v,groups,w,tol=1e-10,max_iter=1000,publish=None):
    require(np.isfinite(v).all() and np.isfinite(w).all() and (w>0).all(),'Invalid weighted projection input')
    if np.all(w==w[0]):return absorb_owned(v,groups,tol,max_iter,publish=publish)
    scale=max(1.,float(np.abs(v).max()));exponent=max(0,int(np.frexp(scale)[1]));threshold=tol*np.ldexp(scale,-exponent)
    np.ldexp(v,-exponent,out=v)
    plans=[]
    for group in groups:
        code=np.unique(group,return_inverse=True)[1];den=np.bincount(code,weights=w);plans.append((code,den))
    initial=np.array([np.dot(w,v[:,k]**2) for k in range(v.shape[1])]);previous=initial.copy();last=time.monotonic()
    diag=dict(solver='weighted_alternating_group_means_v1',tolerance=tol,group_counts=[len(t[1]) for t in plans])
    def means(col,plan):return np.bincount(plan[0],weights=w*col,minlength=len(plan[1]))/plan[1]
    for iteration in range(1,max_iter+1):
        biggest=0.
        for plan in plans:
            for k in range(v.shape[1]):
                avg=means(v[:,k],plan);biggest=max(biggest,float(np.abs(avg).max()));v[:,k]-=avg[plan[0]]
        energy=np.array([np.dot(w,v[:,k]**2) for k in range(v.shape[1])])
        require(np.isfinite(energy).all() and np.all(energy<=previous+1e-10*np.maximum(initial,np.finfo(float).tiny)),
                'Weighted FE projection increased residual energy or became nonfinite')
        previous=energy
        if time.monotonic()-last>=25 and publish:
            publish(dict(diag,iteration=iteration,largest_removed_mean=float(np.ldexp(biggest,exponent))));last=time.monotonic()
        if biggest>threshold:continue
        checks=[max(float(np.abs(means(v[:,k],plan)).max()) for k in range(v.shape[1])) for plan in plans]
        if max(checks)>threshold:continue
        np.ldexp(v,exponent,out=v)
        return v,dict(diag,status='CONVERGED',iterations=iteration,
                      final_max_group_mean_original_units=[float(np.ldexp(x,exponent)) for x in checks])
    raise RuntimeError('Weighted FE solver did not meet all-group orthogonality tolerance; no estimates released')

def partial(v,groups,w,width,publish=None):
    v,diag=weighted_absorb(v,groups,w,publish=publish)
    x=v[:,width:];p=x.shape[1];gram=np.zeros((p,p));cross=np.zeros((p,width))
    for lo in range(0,len(v),65536):
        hi=min(len(v),lo+65536);root=np.sqrt(w[lo:hi]);xx=x[lo:hi]*root[:,None]
        gram+=xx.T@xx;cross+=xx.T@(v[lo:hi,:width]*root[:,None])
    inv=np.linalg.pinv(gram,rcond=1e-12);beta=inv@cross
    rank=int(np.linalg.matrix_rank(gram,tol=max(float(np.linalg.norm(gram,2)),1)*1e-12))
    for lo in range(0,len(v),65536):v[lo:lo+65536,:width]-=x[lo:lo+65536]@beta
    del x
    v.resize((len(v),width),refcheck=False)
    return v,rank,diag

def infer(beta,var,scale):
    result=dict(coefficient=float(beta),variance=float(var),supported=bool(np.isfinite(var) and var>=0))
    if not result['supported']:return dict(result,reason='NEGATIVE_OR_NONFINITE_CR0_VARIANCE')
    se=math.sqrt(var);p=math.erfc(abs(beta/se)/math.sqrt(2)) if se>0 else (1. if beta==0 else 0.)
    return dict(result,standard_error=se,p_value_two_sided=p,coefficient_pp=scale*beta,
                standard_error_pp=scale*se,ci95_low_pp=scale*(beta-1.959963984540054*se),
                ci95_high_pp=scale*(beta+1.959963984540054*se))

def fit_residuals(res,w,codes,outcomes,iv_outcome=None):
    z=res[:,0];den=float(np.dot(w*z,z));require(den>1e-20,'No residual score variation')
    result=[];influences={};by={}
    for k,name in enumerate(outcomes,1):
        y=res[:,k];beta=float(np.dot(w*z,y)/den);inf=w*z*(y-beta*z)/den
        row=dict(outcome=name,estimator='first_stage' if name=='received' else 'reduced_form',
                 units='percentage points per common Score A residual SD',**infer(beta,float(shared_meat(inf,codes,True)[0,0]),100*SD))
        if row.get('standard_error',0)>0:row['wald_F_one_df']=(beta/row['standard_error'])**2
        result.append(row);by[name]=row;influences[name]=inf
    if iv_outcome:
        d=res[:,1+outcomes.index('received')];y=res[:,1+outcomes.index(iv_outcome)];zd=float(np.dot(w*z,d))
        if abs(zd)<=1e-14*den:
            result.append(dict(outcome=iv_outcome,estimator='2SLS',supported=False,reason='ZERO_FIRST_STAGE'))
        else:
            beta=float(np.dot(w*z,y)/zd);inf=w*z*(y-beta*d)/zd
            result.append(dict(outcome=iv_outcome,estimator='2SLS',units='percentage points per receipt',
                          first_stage_F=by['received'].get('wald_F_one_df'),
                          **infer(beta,float(shared_meat(inf,codes,True)[0,0]),100)))
            influences['iv_'+iv_outcome]=inf
    return result,influences

def read_col(path,name,mask):
    arr=pq.ParquetFile(path).read(columns=[name],use_threads=False).column(0).to_numpy(zero_copy_only=False)
    return arr if mask is None else arr[mask]

def estimate(job,minimum_rows=2000,minimum_events=10):
    path=job['input'];nall=pq.ParquetFile(path).metadata.num_rows
    mask=np.ones(nall,bool)
    if job.get('before_support'):
        mask &= ((read_col(path,'n_B',None)>=5)&np.isfinite(read_col(path,'adjusted_B',None))&np.isfinite(read_col(path,'expected_B',None)))
    if job['family'] in ('patron','placebo'):mask &= read_col(path,'profile_returned',None).astype(bool)
    if job.get('preeligible'):mask &= read_col(path,'fair_90',None)>0
    if job.get('blocked_reason'):
        meta=dict(model=job['name'],family=job['family'],sample=job['sample'],control_level=job['level'],
                  score=job['variant'],weighted=job['weighted'],preeligible=job.get('preeligible',False),
                  supported=False,reason=job['blocked_reason'],causal_identification_certified=False)
        pairs=[('received','first_stage'),('patron','reduced_form'),('patron','2SLS')] if job['family']=='patron' else [('patron','reduced_form')]
        return dict(rows=[dict(meta,outcome=outcome,estimator=estimator) for outcome,estimator in pairs],diagnostics={})
    n=int(mask.sum())
    if n<minimum_rows:
        blocked=dict(job,blocked_reason='FEWER_THAN_'+str(minimum_rows)+'_DECLARED_SAMPLE_ROWS')
        return estimate(blocked,minimum_rows,minimum_events)
    if mask.all():mask=None
    read=lambda name:read_col(path,name,mask)
    variant=job['variant'];names=X0+(ENV+['env_supported'] if job['level']=='X0_ENV_indicator' else [])
    outcomes=job.get('outcomes') or (['received','y','reached'] if job['family']=='baseline' else (['received','patron'] if job['family']=='patron' else ['patron']))
    width=1+len(outcomes);v=np.empty((n,width+len(names)),float,order='F')
    rawscore=read('adjusted_'+variant);counts=read('n_'+variant)
    require(np.isfinite(rawscore).all() and (counts>=5).all(),'Score support incomplete on fixed model rows: '+job['name'])
    v[:,0]=rawscore;del rawscore,counts
    if job['weighted']:
        frac=np.asarray(read('sampling_fraction'),float);require(np.isfinite(frac).all() and (frac>0).all() and (frac<=1).all(),'Invalid design fraction')
        weights=1/frac;del frac
    else:weights=np.ones(n)
    original_sum=float(weights.sum());w=weights/weights.mean();weight_info=dict(sum_design_weights=original_sum,maximum_design_weight=float(weights.max()),kish_effective_rows=float(original_sum**2/np.dot(weights,weights)))
    del weights
    ystats={}
    for k,name in enumerate(outcomes,1):
        y=np.asarray(read(name),float);require(np.isin(y,[0,1]).all(),'Missing/nonbinary selected outcome: '+name)
        v[:,k]=y;ystats[name]=dict(events=int(y.sum()),outcome_mean_pp=float(100*np.dot(w,y)/w.sum()))
    del y
    def fill(name,values,standard=True):
        values=np.asarray(values,float);require(np.isfinite(values).all(),'Nonfinite control: '+name)
        if standard:
            sd=float(values.std());values=(values-values.mean())/(sd if sd>1e-12 else 1.)
        v[:,width+names.index(name)]=values
    ir=read('recipient_rating');jr=read('opponent_rating');gap=(jr-ir)/100
    fill('recipient_rating',ir);fill('rating_gap',gap);fill('rating_gap_square',gap*gap);fill('abs_rating_gap',abs(gap))
    cell=factor(read('month_code'),read('tc_base_s'),read('tc_inc_s'),np.floor((ir+jr)/200).astype(np.int64));del ir,jr,gap
    dates=read('archive_start_ms');groups=[cell,dates//DAY,(dates//3600000)%168]
    ids=dict(row_id=read('row_id'),recipient_id=read('recipient_id'),opponent_id=read('opponent_id'),date=dates//DAY);del dates
    fill('log_opponent_prior_decisions',np.log1p(read('n_'+variant)))
    fill('log_opponent_prior_counterparts',np.log1p(read('counterparts_'+variant)))
    fill('opponent_history_expected_rate',read('expected_'+variant))
    fair=read('fair_90');kind=read('kind_90')
    require((fair>=0).all() and (kind>=0).all() and (kind<=fair).all(),'Invalid pre-exposure history counts')
    fill('fair_history_present_90',fair>0);fill('log_fair_90',np.log1p(fair));fill('kind_ever_90',kind>0)
    fill('kind_rate_90',np.divide(kind,fair,out=np.zeros(n),where=fair>0));del fair,kind
    for name in ['disconnect','receipt','claim']:fill('log_'+name+'_90',np.log1p(read(name+'_90')))
    fill('log_volume_30',np.log1p(read('pre_games_30d')))
    if job['level']=='X0_ENV_indicator':
        supported=read('environment_supported').astype(bool)
        for name in ENV:
            x=np.asarray(read(name),float).copy();require(np.isfinite(x[supported]).all(),'Missing supported environment control');x[~supported]=0;fill(name,x)
        fill('env_supported',supported.astype(float),False)
    meta=dict(model=job['name'],family=job['family'],sample=job['sample'],control_level=job['level'],score=variant,
              history_controls_donor_set=variant,weighted=job['weighted'],preeligible=job.get('preeligible',False),
              n=n,recipients=int(len(np.unique(ids['recipient_id']))),row_set_sha256=row_digest(ids['row_id']),before_supported_subset=job.get('before_support',False),
              covariance='shared-account-OR-date CR0',common_score_SD=SD,generated_scores_treated_as_fixed=True,
              causal_identification_certified=False,controls=names,**weight_info)
    if job['family'] in ('patron','placebo'):
        patrons=read('patron').astype(bool);meta['unique_patrons']=int(len(np.unique(ids['recipient_id'][patrons])))
        meta['target']='declared exposure population intersected with positive-support original acquisition universe; original design-fraction weighting, no nonresponse adjustment' if job['weighted'] else 'observed profile sample'
        if job.get('preeligible'):meta['target']='declared '+job['sample']+' with fair_90>0 before exposure and verified positive acquisition support; no nonresponse adjustment'
        del patrons
    log(job['name']+f': FWL on {n:,} rows')
    publish=lambda d:log(job['name']+' FE iteration '+str(d.get('iteration',d.get('iterations'))))
    res,rank,diag=partial(v,groups,w,width,publish);del v,groups,cell
    meta.update(continuous_control_rank=rank,absorb_iterations=diag['iterations'],native_residual_score_SD=float(np.sqrt(np.dot(w,res[:,0]**2)/w.sum())))
    log(job['name']+': account/date covariance')
    codes=covariance_codes(ids['recipient_id'],ids['opponent_id'],ids['date'])
    fits,influences=fit_residuals(res,w,codes,outcomes,'patron' if job['family']=='patron' else ('y' if job['family']=='baseline' else None))
    if job.get('influence_output'):
        import pyarrow as pa
        keep={k:ids[k] for k in ('row_id','recipient_id','opponent_id','date')}
        keep['patron']=influences['patron']
        pq.write_table(pa.table(keep),job['influence_output'],compression='zstd')
    del ids
    result=[]
    for fit in fits:
        row=dict(meta,**ystats[fit['outcome']],**fit)
        if min(row['events'],n-row['events'])<minimum_events:row.update(supported=False,reason='FEWER_THAN_TEN_EVENTS_OR_NONEVENTS')
        if row['outcome']=='patron' and min(meta['unique_patrons'],meta['recipients']-meta['unique_patrons'])<minimum_events:
            row.update(supported=False,reason='FEWER_THAN_TEN_UNIQUE_PATRONS_OR_NONPATRONS')
        result.append(row)
    return dict(rows=result,diagnostics=diag)

def fit_job(job):
    started=time.monotonic()
    folder=stage(Path(job['output']).parent,Path(job['output']).name,job['conf'],
                 lambda tmp: _fit_save(job,tmp))
    return dict(name=job['name'],seconds=time.monotonic()-started,rows=load(folder/'result.json')['rows'])

def _fit_save(job,tmp):
    run=dict(job)
    if job['family'] in ('patron','placebo'):run['influence_output']=str(tmp/'influence_PRIVATE.parquet')
    result=estimate(run);save(tmp/'result.json',result)
    return dict(model=job['name'],rows=result['rows'][0].get('n'),supported=all(x.get('supported') for x in result['rows']))
