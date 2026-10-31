"""Disk-backed FWL, byte-frozen FE projection, and exact shared-account/date CR0."""
from fast_bootstrap import *
import rebuild_models as disk
from fast_covariance import covariance
import fast_projection as parallel_projection
import math
from scipy.stats import norm,chi2


def allocate_design(path,n,p):
    use_ram,estimate=ram_fits(n,p,'design')
    log(f'Model design: {n:,} rows x {p} columns; reservation {estimate:.2f} GiB; '+('R9 owned RAM buffer' if use_ram else 'bounded disk buffer'))
    if use_ram:return np.empty((n,p),dtype=np.float64,order='F')
    return disk.disk_matrix(path,n,p)

def project(v,groups,width,root):
    started=time.monotonic()
    if isinstance(v,np.memmap):
        result,rank,diag=parallel_projection.project(v,groups,width,root);engine='parallel_disk_FWL'
    else:
        result,rank,diag=parallel_projection.project(v,groups,width);engine='R9_parallel_columns_FWL'
    diag.update(execution_version=EXECUTION_VERSION,storage_engine=engine,seconds=time.monotonic()-started)
    log(f'Projection complete: {engine}, {diag["seconds"]/60:.2f} min')
    return result,rank,diag

def inference90(beta,var,scale=1.):
    out=dict(coefficient=float(beta)*scale,standard_error=None,p_value=None,ci95_low=None,ci95_high=None)
    if not np.isfinite(var) or var<=0:return dict(out,supported=False,reason='NONPOSITIVE_OR_NONFINITE_CR0_VARIANCE_NOT_REPAIRED')
    se=math.sqrt(var)*abs(scale);out.update(standard_error=se,p_value=float(2*norm.sf(abs(out['coefficient']/se))),
        ci95_low=out['coefficient']-1.959963984540054*se,ci95_high=out['coefficient']+1.959963984540054*se,supported=True)
    return out

def build_buffer(job,root):
    src=job['input'];scores=job['scores'];ids=frozen.col(src,'row_id')
    require(np.array_equal(ids,frozen.col(scores,'row_id')),'Model source/score IDs or order differ')
    n=len(ids);require(n>=2000,'Model has fewer than 2,000 rows')
    read=lambda k,p=src:frozen.col(p,k)
    uniform=not job.get('legacy',False);rich=not job.get('balance',False)
    controls=list(frozen.r.X0 if rich else frozen.r.NH)
    if uniform:controls=[x.replace('log_volume_30','log_volume_90') for x in controls]
    if job['level']=='X0_ENV_indicator':controls+=frozen.r.ENV+['env_supported']
    traits=TRAITS90 if job.get('balance') else []
    require(not set(traits)&set(controls),'Balance trait also included as nuisance control')
    outs=job['outcomes'];targets=['z']+outs+traits;names=targets+controls
    v=allocate_design(root/'design.dat',n,len(names));filled=set()
    def fill(name,a,standard=True):
        if name not in names:return
        a=np.asarray(a,float);require(np.isfinite(a).all(),'Nonfinite model field '+name)
        if standard:a=(a-a.mean())/max(float(a.std()),1e-12)
        v[:,names.index(name)]=a;filled.add(name);disk.release_pages(v)
    count=read('n_A',scores);score=read('adjusted_A',scores)
    require(np.all(count>=5) and np.isfinite(score).all(),'Unsupported score on fixed model rows')
    fill('z',score,False);del score,count
    events={}
    for name in outs:
        val=read(name);require(np.isin(val,[0,1]).all(),'Nonbinary/missing outcome '+name);fill(name,val,False)
        events[name]=dict(events=int(val.sum()),mean_pp=float(val.mean()*100))
    ir=read('recipient_rating');jr=read('opponent_rating');gap=(jr-ir)/100
    for name,x in [('recipient_rating',ir),('rating_gap',gap),('rating_gap_square',gap*gap),('abs_rating_gap',abs(gap))]:fill(name,x)
    _,cells=frozen.r.num.factor(read('month_code'),read('tc_base_s'),read('tc_inc_s'),np.floor((ir+jr)/200).astype(np.int64))
    del ir,jr,gap
    dates=read('archive_start_ms');groups=[cells,dates//DAY,(dates//3600000)%168]
    actors=dict(row_id=ids,recipient_id=read('recipient_id'),opponent_id=read('opponent_id'),date=dates//DAY)
    for name,source,logarithm in [('log_opponent_prior_decisions','n_A',True),('log_opponent_prior_counterparts','counterparts_A',True),('opponent_history_expected_rate','expected_A',False)]:
        x=read(source,scores);fill(name,np.log1p(x) if logarithm else x)
    fair=read('fair_90');kind=read('kind_90')
    for name,x in [('fair_history_present_90',fair>0),('log_fair_90',np.log1p(fair)),('kind_ever_90',kind>0),('kind_rate_90',np.divide(kind,fair,out=np.zeros(n),where=fair>0))]:fill(name,x)
    for name in ('disconnect','receipt','claim'):fill('log_'+name+'_90',np.log1p(read(name+'_90')))
    fill('log_volume_90' if uniform else 'log_volume_30',np.log1p(read('pre_games_90d' if uniform else 'pre_games_30d')))
    if job['level']=='X0_ENV_indicator':
        supported=read('environment_supported').astype(bool)
        for name in frozen.r.ENV:
            x=np.array(read(name),float,copy=True);require(np.isfinite(x[supported]).all(),'Missing supported ENV value');x[~supported]=0;fill(name,x)
        fill('env_supported',supported,False)
    require(filled==set(names),'Unfilled design columns: '+str(set(names)-filled))
    meta=dict(sample=job['name'],n=n,recipients=len(np.unique(actors['recipient_id'])),control_level=job['level'],controls=controls,
        history='legacy_gap7' if not uniform else 'uniform90_gap0',balance_without_recipient_history_controls=bool(traits),
        row_set_sha256=frozen.r.design.row_digest(ids),score_sd=SD,covariance='shared_account_OR_exposure_date_CR0',
        fixed_effects=['month_exact_TC_mean_rating_100bin','exposure_date','hour_of_week'])
    return v,groups,actors,targets,meta,events

def fit(job):
    def build(tmp):
        v,groups,actors,targets,meta,events=build_buffer(job,tmp)
        res,rank,diag=project(v,groups,len(targets),tmp);del v,groups;gc.collect()
        n=len(res);z=res[:,0];zz=float(z@z);require(zz>1e-14,'No residual score variation')
        native=math.sqrt(zz/n);meta.update(control_rank=rank,native_residual_score_sd=native,absorb_iterations=diag['iterations'])
        terms=[]
        for name in job['outcomes']:
            y=res[:,targets.index(name)];beta=float(z@y)/zz
            terms.append(dict(term='first_stage' if name=='received' else 'rf_'+name,outcome=name,beta=beta,den=zz,
                error_y=targets.index(name),error_x=0,scale=100*SD,units='percentage points per fixed reference Score A SD'))
        if job.get('iv'):
            d=res[:,targets.index('received')];y=res[:,targets.index('y')];zd=float(z@d)
            require(abs(zd)>1e-12,'No first stage for IV')
            terms.append(dict(term='iv_y',outcome='y',beta=float(z@y)/zd,den=zd,error_y=targets.index('y'),error_x=targets.index('received'),scale=100.,units='percentage points per receipt'))
        for name in (TRAITS90 if job.get('balance') else []):
            beta=float(z@res[:,targets.index(name)])/zz
            terms.append(dict(term='balance_'+name,outcome=name,beta=beta,den=zz,error_y=targets.index(name),error_x=0,scale=native,units='trait SD per native residual-score SD'))
        influence=tmp/'influence_PRIVATE.parquet';writer=None
        try:
            for lo in range(0,n,65536):
                hi=min(n,lo+65536);data={k:a[lo:hi] for k,a in actors.items()}
                for t in terms:data[t['term']]=np.asarray(z[lo:hi])*(res[lo:hi,t['error_y']]-t['beta']*res[lo:hi,t['error_x']])/t['den']
                table=pa.table(data)
                if writer is None:writer=pq.ParquetWriter(influence,table.schema,compression='zstd')
                writer.write_table(table)
        finally:
            if writer:writer.close()
        del actors,z,res;gc.collect()
        for p in (tmp/'design.dat',tmp/'residual.dat'):p.unlink(missing_ok=True)
        V=covariance(influence,[t['term'] for t in terms],Path(job['work']),4.)
        estimates=[]
        for k,t in enumerate(terms):
            row=dict(meta,term=t['term'],outcome=t['outcome'],units=t['units'],**inference90(t['beta'],float(V[k,k]),t['scale']))
            if t['outcome'] in events:row.update(events[t['outcome']])
            if t['term']=='first_stage':row['wald_F']=t['beta']**2/V[k,k] if V[k,k]>0 else None
            estimates.append(row)
        balance=[r for r in estimates if r['term'].startswith('balance_')]
        if balance:
            valid=sorted([r for r in balance if r['p_value'] is not None],key=lambda r:r['p_value']);prev=0.
            for k,r in enumerate(valid):prev=max(prev,min(1.,(len(balance)-k)*r['p_value']));r['p_Holm_8']=prev
        joint=[]
        if balance:
            k0=len(terms)-len(balance);W=V[k0:,k0:]*native**2;points=np.array([r['coefficient'] for r in balance])
            ev,U=np.linalg.eigh(W);cut=max(float(abs(ev).max()),1e-30)*1e-9;use=ev>cut
            if ev.min() < -cut:result=dict(supported=False,reason='NON_PSD_COVARIANCE_NOT_REPAIRED')
            elif not use.any():result=dict(supported=False,reason='ZERO_RANK')
            else:
                statistic=float(np.sum((U[:,use].T@points)**2/ev[use]));df=int(use.sum())
                result=dict(supported=True,chi2=statistic,df=df,p_value=float(chi2.sf(statistic,df)))
            joint=[dict(meta,traits=TRAITS90,**result)]
        save(tmp/'result.json',dict(estimates=estimates,joint_balance=joint));save(tmp/'numerical_diagnostics.json',diag)
        return dict(n=n,models=1)
    return stage(job['output'],job['conf'],build,[job['input'],job['scores']])[1]

def subset(a,run,conf,source,scores,label,where):
    def build(tmp):
        c=conn(tmp,a.memory_gb-2)
        try:
            view(c,'q',source);view(c,'s',scores)
            copy_query(c,'SELECT * FROM q WHERE '+where+' ORDER BY row_id',tmp/'source.parquet')
            copy_query(c,'SELECT s.* FROM s JOIN q USING(row_id) WHERE '+where+' ORDER BY row_id',tmp/'scores.parquet')
            return dict(rows=pq.ParquetFile(tmp/'source.parquet').metadata.num_rows)
        finally:c.close()
    folder,_=stage(run/'PRIVATE/model_subsets'/label,conf,build,[source,scores]);return folder/'source.parquet',folder/'scores.parquet'

def job_for(run,conf,label,source,scores,**kw):
    return dict(name=label,input=str(source),scores=str(scores),level='X0_ENV_indicator',outcomes=['received','y','reached'],iv=True,
        output=str(run/'PRIVATE/models'/label),work=str(run/'PRIVATE/covariance'/label),conf=conf,**kw)

def contrast(run,conf,left,right,label,terms):
    deps=[Path(j['output'])/name for j in (left,right) for name in ('result.json','influence_PRIVATE.parquet')]
    def build(tmp):
        c=conn(tmp)
        try:
            queries=[]
            for side,j in [('left',left),('right',right)]:
                fields=['recipient_id','opponent_id','date']
                for t in terms:fields += [(t if side=='left' else '0.0')+' left_'+t,(t if side=='right' else '0.0')+' right_'+t]
                queries.append('SELECT '+','.join(fields)+' FROM '+parq([Path(j['output'])/'influence_PRIVATE.parquet']))
            copy_query(c,' UNION ALL '.join(queries),tmp/'stack.parquet')
        finally:c.close()
        cols=[side+'_'+t for t in terms for side in ('left','right')]
        V=covariance(tmp/'stack.parquet',cols,run/'PRIVATE/contrast_covariance'/label,4.)
        l={r['term']:r for r in load(Path(left['output'])/'result.json')['estimates']};r={r['term']:r for r in load(Path(right['output'])/'result.json')['estimates']};rows=[]
        for k,t in enumerate(terms):
            scale=100 if t=='iv_y' else 100*SD
            variance=float(V[2*k,2*k]+V[2*k+1,2*k+1]-2*V[2*k,2*k+1])
            rows.append(dict(contrast=label,term=t,units=l[t]['units'],left_n=l[t]['n'],right_n=r[t]['n'],
                **inference90((l[t]['coefficient']-r[t]['coefficient'])/scale,variance,scale)))
        save(tmp/'result.json',rows);(tmp/'stack.parquet').unlink();return dict(contrasts=len(rows))
    out,_=stage(run/'PRIVATE/contrasts'/label,conf,build,deps)
    return load(out/'result.json')

def receipt_models(a,run,conf,b):
    f=load(run/'PRIVATE/FRAMES90.json');plan=[]
    plan.append(job_for(run,conf,'legacy_spaced',b['primary'],b['primary_scores'],legacy=True))
    for label,where in [('uniform_same_rows','legacy_primary'),('uniform_spaced','spaced90'),('uniform_unspaced_old_calendar','legacy_windows')]:
        src,sc=subset(a,run,conf,f['source'],f['scores'],label,where);plan.append(job_for(run,conf,label,src,sc))
    plan.append(job_for(run,conf,'uniform_unspaced',f['source'],f['scores']))
    plan.append(job_for(run,conf,'uniform_unspaced_balance',f['source'],f['scores'],balance=True))
    save(run/'PRIVATE/MODEL_PLAN90.json',plan)
    for completed,i in enumerate((0,4),1):
        job=plan[i]
        with heartbeat('Model '+job['name']):fit(job)
        if i==0:
            rows={r['term']:r for r in load(Path(job['output'])/'result.json')['estimates']}
            for term,field in [('first_stage','first_stage'),('rf_y','reduced_form'),('iv_y','iv')]:
                require(np.isclose(rows[term]['coefficient'],b['baseline'][field],atol=2e-7,rtol=2e-7),'Legacy coefficient replay failed: '+term)
                require(np.isclose(rows[term]['standard_error'],b['baseline'][field+'_se'],atol=2e-7,rtol=2e-7),'Legacy covariance replay failed: '+term)
            save(run/'report/legacy_reproduction.json',dict(passed=True,rows=EXPECTED_N,reference=b['baseline']))
        log(f'Receipt models {completed}/{len(plan)} complete')
        if i==4:
            result=next(x for x in load(Path(job['output'])/'result.json')['estimates'] if x['term']=='iv_y')
            log('MAIN_IV_READY: '+json.dumps({k:result[k] for k in ('n','coefficient','standard_error','ci95_low','ci95_high')}))
        export_models(run)
    from fast_scheduler import fits as schedule_fits
    for job in schedule_fits([plan[i] for i in (5,1,2,3)]):export_models(run)
    rows=[]
    for left,right,label in [(1,0,'history_change_same_rows'),(2,1,'calendar_change_spaced'),(3,1,'spacing_change_same_calendar'),(4,3,'calendar_change_unspaced'),(4,2,'spacing_change_uniform_calendar')]:
        rows+=contrast(run,conf,plan[left],plan[right],label,['first_stage','rf_y','iv_y'])
        csv_out(run/'report/model_contrasts.csv',rows)

def export_models(run):
    rows=[];joint=[]
    for p in sorted((run/'PRIVATE/models').glob('*/result.json')):
        if '.partial_' in p.parent.name or not (p.parent/'_DONE.json').is_file():continue
        r=load(p);rows+=r['estimates'];joint+=r.get('joint_balance',[])
    if rows:csv_out(run/'report/model_estimates.csv',rows)
    if joint:csv_out(run/'report/balance_joint.csv',joint)

def overlap_audit(a,run,conf):
    f=load(run/'PRIVATE/FRAMES90.json')
    def build(tmp):
        c=conn(tmp,a.memory_gb-2)
        try:
            view(c,'q',f['source']);n=pq.ParquetFile(f['source']).metadata.num_rows
            recipient=c.execute('SELECT count(*),sum(n),max(n),avg(n) FROM (SELECT recipient_id,count(*) n FROM q GROUP BY 1) WHERE n>1').fetchone()
            reused=c.execute('SELECT count(*),coalesce(sum(n),0),coalesce(sum(n-1),0),coalesce(max(n),0) FROM (SELECT recipient_id,outcome_gid,count(*) n FROM q WHERE reached GROUP BY 1,2) WHERE n>1').fetchone()
            overlaps=c.execute(f'''SELECT count(*) FILTER(WHERE archive_start_ms<=prior_max_end),count(*) FROM
                (SELECT archive_start_ms,max(anchor_ms+{90*DAY}) OVER(PARTITION BY recipient_id ORDER BY archive_start_ms,row_id ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) prior_max_end FROM q)''').fetchone()
            later=c.execute('''SELECT count(*) FILTER(WHERE next_start<outcome_start),count(*) FILTER(WHERE next_start<=outcome_t) FROM
                (SELECT *,lead(archive_start_ms) OVER(PARTITION BY recipient_id ORDER BY archive_start_ms,row_id) next_start FROM q) WHERE reached''').fetchone()
            result=dict(exposures=n,repeat_recipients=recipient[0],rows_from_repeat_recipients=recipient[1],max_exposures_per_repeat_recipient=recipient[2],
                shared_future_choice_groups=reused[0],rows_sharing_a_future_choice=reused[1],extra_uses_of_shared_choices=reused[2],max_uses_of_one_choice=reused[3],
                exposures_with_overlapping_prior_90day_window=overlaps[0],next_retained_exposure_starts_before_outcome_game=later[0],next_retained_exposure_starts_by_outcome_decision=later[1],
                interpretation='Exposure weighted; repeated rows and shared outcomes retained; these counts do not enumerate unsupported intervening receipts')
            save(tmp/'audit.json',result);return dict(rows=n)
        finally:c.close()
    out,_=stage(run/'PRIVATE/overlap90',conf,build,[f['source']]);save(run/'report/overlap_audit.json',load(out/'audit.json'))
