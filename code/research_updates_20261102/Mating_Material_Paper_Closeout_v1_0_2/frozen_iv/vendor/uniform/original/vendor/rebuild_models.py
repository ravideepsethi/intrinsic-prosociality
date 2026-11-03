"""Frozen R9 column transforms with disk-backed FWL and SQL CR0 aggregation.

build_buffer is copied from the vendored R9 producer; the allocation and page
release are the only changes. All sample, score, FE and control transforms agree.
"""
from rebuild_common import *
import math,mmap
import r7_memory as memory_math
r=frozen.r
u=frozen.u
models=fits.models
m7=r9.m7
col=frozen.col
selection=fits.selection

def disk_matrix(path,n,p):
    path.parent.mkdir(parents=True,exist_ok=True)
    return np.memmap(path,dtype=np.float64,mode='w+',shape=(n,p),order='F')

def release_pages(value):
    if isinstance(value,np.memmap):
        value.flush()
        if hasattr(value._mmap,'madvise') and hasattr(mmap,'MADV_DONTNEED'):
            value._mmap.madvise(mmap.MADV_DONTNEED)

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
    v=disk_matrix(Path(job['_buffer_dir'])/'design.dat',n,width+len(names));v[:,0]=rawscore;del count,rawscore
    ystats={}
    for j,k in enumerate(outs):
        a=read(k);u.require(np.isin(a,[0,1]).all(),'Nonbinary/missing frozen outcome: '+k)
        v[:,1+j]=a;ystats[k]=dict(events=int(a.sum()),outcome_mean_pp=float(a.mean()*100));release_pages(v)
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
        release_pages(v)
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

def project(v,groups,width,root):
    n,p=v.shape;plans=[memory_math._plan(g,n) for g in groups]
    maximum=max(1.,max(float(np.max(np.abs(v[:,k]))) for k in range(p)));tolerance=1e-10*maximum
    work=np.empty(n);shift=np.empty(n);checks=[];iterations=[]
    for k in range(p):
        column=np.array(v[:,k],copy=True);energy0=float(column@column);previous=energy0
        for it in range(1,1001):
            largest=0.
            for plan in plans:
                means=memory_math._group_means(column,plan,work)
                require(np.isfinite(means).all(),'Nonfinite FE means')
                largest=max(largest,float(np.abs(means).max()));np.take(means,plan[0],out=shift);column-=shift
            energy=float(column@column)
            require(np.isfinite(energy) and energy<=previous+1e-10*max(energy0,np.finfo(float).tiny),'FE projection increased squared norm')
            previous=energy
            if largest<=tolerance:
                check=max(float(np.max(np.abs(memory_math._group_means(column,t,work)))) for t in plans)
                if check<=tolerance:break
        else:raise RuntimeError('FE orthogonality not attained in 1,000 iterations')
        v[:,k]=column;release_pages(v);checks.append(check);iterations.append(it)
        log(f'Comparison FE column {k+1}/{p}: {it} sweeps; max group mean {check:.3g}')
    del plans,column,work,shift;gc.collect()
    k=p-width;gram=np.zeros((k,k));cross=np.zeros((k,width))
    for lo in range(0,n,65536):
        x=np.asarray(v[lo:lo+65536,width:]);y=np.asarray(v[lo:lo+65536,:width]);gram+=x.T@x;cross+=x.T@y
    beta=np.linalg.pinv(gram,rcond=1e-12)@cross
    rank=int(np.linalg.matrix_rank(gram,tol=max(float(np.linalg.norm(gram,2)),1)*1e-12))
    result=disk_matrix(root/'residual.dat',n,width)
    for lo in range(0,n,65536):result[lo:lo+65536]=v[lo:lo+65536,:width]-v[lo:lo+65536,width:]@beta
    release_pages(result);release_pages(v)
    return result,rank,dict(iterations=max(iterations),column_iterations=iterations,orthogonality=checks,tolerance=tolerance)

def sql_covariance(path,columns,root,memory=4.):
    """Exactly accounts - pairs + dates - account/date + pair/date CR0."""
    c=connection(root,memory);p=len(columns);V=np.zeros((p,p))
    try:
        c.execute('CREATE VIEW d AS SELECT * FROM '+parq([path]))
        ensure(c,'SELECT count(*) FROM d WHERE recipient_id=opponent_id','Self-pair in covariance')
        exprs=','.join('sum("'+x+'") "'+x+'"' for x in columns)
        pair=[('accounts',1,True,['person']),('pairs',-1,False,['lo','hi']),('dates',1,False,['date']),
              ('account_dates',-1,True,['person','date']),('pair_dates',1,False,['lo','hi','date'])]
        terms=[(i,j) for i in range(p) for j in range(i,p)]
        outer=','.join('sum("'+columns[i]+'"*"'+columns[j]+'")' for i,j in terms)
        for name,sign,both,keys in pair:
            if both:
                src='SELECT recipient_id person,date,'+','.join('"'+x+'"' for x in columns)+' FROM d UNION ALL SELECT opponent_id,date,'+','.join('"'+x+'"' for x in columns)+' FROM d'
            else:src='SELECT *,least(recipient_id,opponent_id) lo,greatest(recipient_id,opponent_id) hi FROM d'
            row=c.execute('SELECT '+outer+' FROM (SELECT '+','.join(keys)+','+exprs+' FROM ('+src+') GROUP BY '+','.join(keys)+')').fetchone()
            for (i,j),value in zip(terms,row):
                require(value is not None and np.isfinite(value),'Invalid covariance term')
                V[i,j]+=sign*value
                if j!=i:V[j,i]+=sign*value
            log('Shared-account/date covariance: '+name+' complete')
        return V
    finally:c.close()

def fit_job(job):
    r.threads_one();u.no_network()
    def build(tmp):
        job0=dict(job,_buffer_dir=str(tmp));v,groups,ids,meta,outs,ystats=build_buffer(job0)
        require(v is not None,'Comparison model has insufficient rows or donor support')
        width=1+len(outs)+len(r.T30);res,rank,diag=project(v,groups,width,tmp)
        del v,groups;gc.collect()
        n=len(res);z=res[:,0];zz=float(z@z);native=math.sqrt(zz/n)
        require(native>1e-10,'No residual score variation')
        names=outs+['balance_'+x for x in r.T30]
        beta=np.array([float(z@res[:,k+1])/zz for k in range(len(names))])
        scale=np.r_[np.ones(len(outs)),np.full(len(r.T30),native)]
        covpath=tmp/'influence_all_PRIVATE.parquet';writer=None
        try:
            for lo in range(0,n,65536):
                hi=min(n,lo+65536);cols={k:a[lo:hi] for k,a in ids.items()};zs=np.asarray(z[lo:hi])
                for k,name in enumerate(names):cols[name]=scale[k]*zs*(res[lo:hi,k+1]-beta[k]*zs)/zz
                table=pa.table(cols)
                if writer is None:writer=pq.ParquetWriter(covpath,table.schema,compression='zstd')
                writer.write_table(table)
        finally:
            if writer:writer.close()
        # Release the disk-backed design before grouping millions of covariance keys.
        del ids,z,res;gc.collect()
        for path in (tmp/'design.dat',tmp/'residual.dat'):path.unlink()
        V=sql_covariance(covpath,names,tmp/'covariance',job.get('memory',4.))
        meta.update(native_residual_score_SD=native,continuous_control_rank=rank,absorb_iterations=diag['iterations'],
                    model_storage='disk_backed_FWL',covariance_aggregation='exact_SQL_inclusion_exclusion')
        estimates=[];balance=[]
        for k,name in enumerate(outs):
            fit=m7.inference(beta[k],float(V[k,k]))
            if min(ystats[name]['events'],n-ystats[name]['events'])<10:fit.update(supported=False,reason='FEWER_THAN_TEN_EVENTS_OR_NONEVENTS')
            row=dict(meta,outcome=name,estimator='first_stage' if name=='received' else 'reduced_form',**ystats[name],**fit)
            if fit.get('standard_error') is not None:row['wald_F_one_df']=(fit['coefficient']/fit['standard_error'])**2
            estimates.append(row)
        for k,trait in enumerate(r.T30,len(outs)):
            balance.append(dict(meta,trait=trait,units='trait SD per native residual-score SD',**m7.inference(beta[k]*native,float(V[k,k]))))
        r.stats.stats.holm(balance,out='p_Holm_7_traits')
        ev,U=np.linalg.eigh(V[len(outs):,len(outs):]);cut=max(float(abs(ev).max()),1e-30)*1e-9;use=ev>cut
        if ev.min() < -cut:joint=dict(supported=False,reason='NON_PSD_COVARIANCE_NOT_REPAIRED')
        elif not use.any():joint=dict(supported=False,reason='ZERO_RANK')
        else:
            stat=float(np.sum((U[:,use].T@(beta[len(outs):]*native))**2/ev[use]));df=int(use.sum())
            joint=dict(supported=True,wald_chi2=stat,rank=df,p_value_asymptotic=r.num.chi2_sf(stat,df))
        result=dict(estimates=estimates,balance=balance,joint_balance=[dict(meta,test_set='T30_stacked_trait_on_score',traits=r.T30,**joint)],figure5=[])
        save(tmp/'result.json',result);save(tmp/'numerical_diagnostics.json',diag)
        c=connection(tmp/'influence',job.get('memory',4.))
        try:copy_query(c,'SELECT row_id,recipient_id,opponent_id,date,'+','.join(outs)+' FROM '+parq([covpath]),tmp/'influence_PRIVATE.parquet')
        finally:c.close()
        covpath.unlink();return dict(n=n,sample=job['sample'],level=job['level'])
    return stage(job['output'],job['conf'],build,[job['input'],job['scores']])[1]

def contrast_job(job):
    left,right=Path(job['left']),Path(job['right']);deps=[p/n for p in (left,right) for n in ('result.json','influence_PRIVATE.parquet')]
    def build(tmp):
        a=load(left/'result.json')['estimates'];b=load(right/'result.json')['estimates'];cols=[]
        for name in job['outcomes']:cols+=['left_'+name,'right_'+name]
        c=connection(tmp,4.)
        try:
            terms=[]
            for side,folder in [('left',left),('right',right)]:
                fields=['recipient_id','opponent_id','date']
                for name in job['outcomes']:
                    fields += [(name if side=='left' else '0.0')+' AS left_'+name,(name if side=='right' else '0.0')+' AS right_'+name]
                terms.append('SELECT '+','.join(fields)+' FROM '+parq([folder/'influence_PRIVATE.parquet']))
            copy_query(c,' UNION ALL '.join(terms),tmp/'stack.parquet')
        finally:c.close()
        V=sql_covariance(tmp/'stack.parquet',cols,tmp/'covariance',4.);rows=[]
        for k,name in enumerate(job['outcomes']):
            aa=next(x for x in a if x.get('outcome')==name and x.get('estimator')=='reduced_form');bb=next(x for x in b if x.get('outcome')==name and x.get('estimator')=='reduced_form')
            sub=V[2*k:2*k+2,2*k:2*k+2];var=float(sub[0,0]+sub[1,1]-2*sub[0,1])
            rows.append(dict(contrast=job['label'],control_level=job['level'],outcome=name,estimator='reduced_form',
              left_n=aa['n'],right_n=bb['n'],left_coefficient=aa['coefficient'],right_coefficient=bb['coefficient'],
              covariance_matrix=sub.tolist(),stacked_actual_accounts_and_dates=True,**m7.inference(aa['coefficient']-bb['coefficient'],var)))
        save(tmp/'result.json',rows);(tmp/'stack.parquet').unlink();return dict(contrasts=len(rows))
    return stage(job['output'],job['conf'],build,deps)[1]

def replay_check(result,expected):
    for family in ('estimates','balance','joint_balance'):
        got=result[family];old=expected[family];require(len(got)==len(old),'Old model result lengths changed')
        for a,b in zip(got,old):
            for key0 in ('n','events','row_set_sha256','supported','outcome','trait','rank'):
                if key0 in b:require(a.get(key0)==b[key0],'Old model replay differs: '+key0)
            for key0 in ('coefficient','standard_error','wald_chi2','p_value_asymptotic'):
                if b.get(key0) is not None:require(np.isclose(a.get(key0,np.nan),b[key0],atol=2e-9,rtol=2e-7),'Old model numerical replay differs: '+key0)

def execute(a,run,conf,b):
    plan=[];root=run/'PRIVATE/models';frames=run/'PRIVATE/frames'
    for level in r9.LEVELS:
        for sample,kind in [('F','entry'),('O','ordinary')]:
            for legacy in (True,False):
                source=b['old_paths'][sample] if legacy else frames/(sample+'.parquet')
                scores=b['old_scores'][sample] if legacy else frames/(sample+'_scores.parquet')
                label=('legacy_' if legacy else 'totalfive_')+sample
                job=fits.make_job(source,scores,root/(label+'__'+level),conf,label,kind,level)
                job.update(memory=4.,memory_gb=9.);plan.append(job)
    save(run/'PRIVATE/MODEL_PLAN.json',plan)
    validation=dict(legacy_models_reproduced=[],corrected_primary_reproduced=False,comparison_models_complete=0,comparison_models_planned=len(plan),contrasts_complete=0)
    for k,job in enumerate(plan,1):
        with heartbeat('Comparison model '+job['sample']+' '+job['level']):fit_job(job)
        if job['sample'].startswith('legacy_'):
            sample=job['sample'][-1];old=Path(b['comparison_root'])/'fits'/(sample+'100__A__'+job['level'])/'result.json'
            replay_check(load(Path(job['output'])/'result.json'),load(old))
            validation['legacy_models_reproduced'].append(dict(sample=sample,control_level=job['level']))
        validation['comparison_models_complete']=k;save(run/'report/model_validation.json',validation)
        log(f'Comparison models {k}/{len(plan)} completed and checked')
    checks=[]
    # A receipt fit has only 3.1m rows; use the exact frozen producer and verify the accepted IV.
    for level in r9.LEVELS:
        job=fits.make_job(b['primary']['primary'],b['primary']['primary_scores'],root/('receipt__'+level),conf,'receipt_total5','iv',level)
        fits.fit_job(job)
        if level=='X0_ENV_indicator':
            ivrow=next(x for x in load(Path(job['output'])/'result.json')['estimates'] if x['estimator']=='2SLS')
            require(abs(ivrow['iv_coefficient_pp']-.36280640903671635)<2e-9 and abs(ivrow['iv_standard_error_pp']-.096407515226692)<2e-9,'Corrected main IV no longer reproduces')
            validation['corrected_primary_reproduced']=True
        comparisons=[dict(left=job['output'],right=str(root/('totalfive_O__'+level)),label='new_receipt_minus_new_ordinary',outcomes=['y','reached'])]
        for sample,outs in [('F',['analysis_entry_90','recipient_disconnect_main','active_timeout']),('O',['y','reached'])]:
            comparisons.append(dict(left=str(root/('totalfive_'+sample+'__'+level)),right=str(root/('legacy_'+sample+'__'+level)),label=sample+'_new_minus_old',outcomes=outs))
        for j in comparisons:
            j.update(level=level,conf=conf,output=str(run/'PRIVATE/contrasts'/(j['label']+'__'+level)))
            contrast_job(j);checks.append(j);validation['contrasts_complete']=len(checks);save(run/'report/model_validation.json',validation)
    save(run/'PRIVATE/CONTRAST_PLAN.json',checks)
