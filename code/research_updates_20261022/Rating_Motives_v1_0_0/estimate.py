"""Two-pass, disk-backed chooser-FE LPM; full-rank CR1 and joint state contrasts."""
import concurrent.futures, contextlib, json, multiprocessing, os
from pathlib import Path
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from scipy import sparse, stats
from common import *
from fe_core import iter_blocks,solve
from models import sample,subgroup,build

def cluster_matrix(ids):
    _,inv,count=np.unique(ids,axis=0,return_inverse=True,return_counts=True)
    return inv,count,sparse.csr_matrix((np.ones(len(ids)),(inv,np.arange(len(ids)))),shape=(len(count),len(ids)))

def blank(X,names,C,labels):
    p=X.shape[1]
    return dict(S=np.zeros((p,p)),b=np.zeros(p),yy=0.,N=0,G=0,F=0,grants=0,selected=0,
        treatment_switchers=0,outcome_switchers=0,joint_switchers=0,never_granters=0,
        raw_within_weight=0.,never_granter_weight=0.,positive_rows=0,positive_grants=0,
        log_k_sum=0.,clock_missing=0,opp_clock_missing=0,names=names,C=C,labels=labels,
        target_min=np.inf,target_max=-np.inf,k_min=np.inf,k_max=-np.inf,zero_max=0.,e_min=np.inf,e_max=-np.inf)

def moment_update(a,d,m,X,selected,z):
    y=d['y'].astype(float);g,n,A=subgroup(d,m['fe']);AX=(A@X).toarray();ay=A@y
    a['S']+=(X.T@X).toarray()-AX.T@(AX/n[:,None])
    a['b']+=np.asarray(X.T@y).ravel()-AX.T@(ay/n)
    a['yy']+=float(y@y-np.sum(ay**2/n))
    cg,cn,B=cluster_matrix(d['chooser']);sy=B@y;sz=B@z;sz2=B@(z*z)
    w=np.maximum(0,sz2-sz**2/cn);switch=w>1e-12;yswitch=(sy>0)&(sy<cn);never=sy==0
    a['N']+=len(y);a['G']+=len(cn);a['F']+=len(n);a['grants']+=int(y.sum());a['selected']+=selected
    a['treatment_switchers']+=int(switch.sum());a['outcome_switchers']+=int(yswitch.sum())
    a['joint_switchers']+=int((switch&yswitch).sum());a['never_granters']+=int(never.sum())
    a['raw_within_weight']+=float(w.sum());a['never_granter_weight']+=float(w[never].sum())
    a['positive_rows']+=int(np.sum(z>0));a['positive_grants']+=int(y[z>0].sum())
    a['log_k_sum']+=float(np.log(d['k']).sum())
    for c in ['clock','opp_clock']:a[c+'_missing']+=int(np.sum(~np.isfinite(d[c])|(d[c]<0)))
    a['target_min']=min(a['target_min'],float(z.min()));a['target_max']=max(a['target_max'],float(z.max()))
    a['k_min']=min(a['k_min'],float(d['k'].min()));a['k_max']=max(a['k_max'],float(d['k'].max()))
    a['e_min']=min(a['e_min'],float(d['e'].min()));a['e_max']=max(a['e_max'],float(d['e'].max()))
    a['zero_max']=max(a['zero_max'],float(np.abs(d['rg']).max()))

def save_arrays(path,values):
    # Numeric NPZ plus JSON metadata; no pickle loading or executable checkpoints.
    arrays={};meta={}
    for key,di in values.items():
        meta[key]={}
        for k,v in di.items():
            if isinstance(v,np.ndarray):arrays[key+'___'+k]=v
            else:meta[key][k]=v
    arrays['metadata_utf8']=np.frombuffer(json.dumps(clean_json(meta),sort_keys=True).encode(),dtype=np.uint8)
    tmp=Path(str(path)+'.tmp')
    with tmp.open('wb') as f:np.savez_compressed(f,**arrays)
    tmp.replace(path)

def load_arrays(path):
    with np.load(path,allow_pickle=False) as z:
        meta=json.loads(z['metadata_utf8'].tobytes().decode())
        for key in z.files:
            if key=='metadata_utf8':continue
            a,b=key.split('___');meta[a][b]=z[key].copy()
    return meta

def moment_worker(args):
    path,models,output,identity,batch=args;output=Path(output);receipt=output.with_suffix('.json')
    if checkpoint_ok(receipt,identity):return str(output)
    acc={};empty_counts={};flows={};writers={};ledgers={}
    output.parent.mkdir(parents=True,exist_ok=True)
    with contextlib.ExitStack() as stack:
      for block in iter_blocks(path,batch):
        for m in models:
            key=m['key'];scope=np.ones(len(block['y']),bool) if m['state']=='difference' else block['state']==(1 if m['state']=='competitive' else 0)
            if key not in flows:flows[key]=dict(input_rows=0,**{'missing_'+k:0 for k in ['opp_prior_count','dperf','peak','rd','opp_rd','opp_stake']})
            flows[key]['input_rows']+=int(scope.sum())
            for k in ['opp_prior_count','dperf','peak','rd','opp_rd','opp_stake']:flows[key]['missing_'+k]+=int(np.sum(scope&~np.isfinite(block[k])))
            d,selected=sample(block,m)
            if d is None:empty_counts[key]=empty_counts.get(key,0)+selected;continue
            X,names,C,labels,z,target=build(d,m)
            if key not in acc:acc[key]=blank(X,names,C,labels)
            moment_update(acc[key],d,m,X,selected,z)
            if key not in writers:
                lp=output.parent/(output.stem+'__'+key+'__support.parquet');ledgers[key]=str(lp)
                writers[key]=stack.enter_context(pq.ParquetWriter(str(lp)+'.tmp',pa.schema([('recipient',pa.int64()),('target',pa.float64())]),compression='zstd'))
            writers[key].write_table(pa.table(dict(recipient=np.asarray(d['recipient'],dtype=np.int64),target=np.asarray(z,float))))
    for key,n in empty_counts.items():
        if key in acc:acc[key]['selected']+=n
    uncounted={k:v for k,v in empty_counts.items() if k not in acc}
    for path in ledgers.values():Path(path+'.tmp').replace(path)
    save_arrays(output,acc);finish_checkpoint(receipt,identity,[output]+list(ledgers.values()),dict(uncounted_selected=uncounted,flows=flows,ledgers=ledgers));return str(output)

def merge_moments(paths):
    acc={};static={'names','C','labels'};mins={'target_min','k_min','e_min'};maxs={'target_max','k_max','zero_max','e_max'}
    for p in paths:
        for key,d in load_arrays(p).items():
            if key not in acc:acc[key]=d;continue
            a=acc[key]
            for k,v in d.items():
                if k in static:
                    if not np.array_equal(a[k],v):raise RuntimeError('Design columns changed across shards')
                elif k in mins:a[k]=min(a[k],v)
                elif k in maxs:a[k]=max(a[k],v)
                else:a[k]+=v
    for p in paths:
        extra=json.loads(Path(p).with_suffix('.json').read_text()).get('extra') or {}
        for key,n in extra.get('uncounted_selected',{}).items():
            if key in acc:acc[key]['selected']+=n
    return acc

def fit_moments(acc,models):
    fits={}
    for m in models:
        key=m['key']
        if key not in acc:continue
        a=acc[key];C=a['C'].copy()
        if m['test']=='T3' and m['variant']=='interaction':C[0,-1]=a['log_k_sum']/a['N']
        s=solve(a['S'],a['b'],C);df=a['N']-a['F']-s['rank']
        f=dict(beta=s['beta'],P=s['bread']@C.T,C=C,est=C@s['beta'],identified=s['identified'],
               rank=s['rank'],full_rank=a['F']+s['rank'],residual_df=df,condition=s['condition_number'],
               projection_error=s['projection_error'],labels=a['labels'],G=a['G'],N=a['N'],
               partial_information=np.diag(C@s['bread']@C.T))
        fits[key]=f
    return fits

def score_worker(args):
    path,models,fitpath,output,identity,batch=args;output=Path(output);receipt=output.with_suffix('.json')
    if checkpoint_ok(receipt,identity):return str(output)
    fits=load_arrays(fitpath);acc={};writers={};rpaths={}
    output.parent.mkdir(parents=True,exist_ok=True)
    try:
        for block in iter_blocks(path,batch):
            for m in models:
                key=m['key']
                if key not in fits:continue
                fit=fits[key];d,_=sample(block,m)
                if d is None:continue
                X,_,_,_,_,_=build(d,m);g,n,A=subgroup(d,m['fe'])
                err=d['y']-X@fit['beta'];err-=np.asarray(A@err/n)[g]
                influence=X@fit['P']
                mean=np.asarray(A@influence)/n[:,None];influence=(influence-mean[g])*err[:,None]
                _,cn,B=cluster_matrix(d['chooser']);score=B@influence;q=influence.shape[1]
                if key not in acc:acc[key]=dict(meat=np.zeros((q,q)),pair_meat=np.zeros((q,q)),pairs=0)
                acc[key]['meat']+=score.T@score
                if m['variant']=='primary' and m['state']!='difference':
                    _,rn,R=cluster_matrix(d['recipient']);rs=R@influence
                    unique=np.unique(d['recipient']);rp=output.parent/(output.stem+'__'+key+'__recipient.parquet')
                    if key not in writers:
                        schema=pa.schema([('recipient',pa.int64())]+[(f's{i}',pa.float64()) for i in range(q)])
                        writers[key]=pq.ParquetWriter(str(rp)+'.tmp',schema,compression='zstd');rpaths[key]=rp
                    writers[key].write_table(pa.table(dict(recipient=unique,**{f's{i}':rs[:,i] for i in range(q)})))
                    _,pn,BP=cluster_matrix(np.column_stack([d['chooser'],d['recipient']]));ps=BP@influence
                    acc[key]['pair_meat']+=ps.T@ps;acc[key]['pairs']+=len(pn)
    finally:
        for w in writers.values():w.close()
    for key,p in rpaths.items():Path(str(p)+'.tmp').replace(p);acc[key]['recipient_scores']=str(p)
    save_arrays(output,acc);finish_checkpoint(receipt,identity,[output]+list(rpaths.values()));return str(output)

def parallel_jobs(fn,jobs,workers,label):
    results=[]
    # Spawn gives identical execution semantics on macOS and Linux.
    ctx=multiprocessing.get_context('spawn')
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers,mp_context=ctx) as pool:
        pending={pool.submit(fn,j):j for j in jobs};done_n=0
        while pending:
            done,_=concurrent.futures.wait(pending,timeout=30,return_when=concurrent.futures.FIRST_COMPLETED)
            if not done:log(f'{label}: {done_n}/{len(jobs)} shards complete; workers running')
            for future in done:
                results.append(future.result());pending.pop(future);done_n+=1;log(f'{label}: {done_n}/{len(jobs)} shards complete')
    return sorted(results)

def inference(beta,var,df):
    if not np.isfinite(var) or var<0 or df<=0:return dict(status='UNSUPPORTED_COVARIANCE')
    se=float(np.sqrt(var));critical=stats.t.ppf(.975,df)
    if se==0:
        p=1. if beta==0 else 0.;peq=0. if abs(beta)<.001 else 1.
    else:
        p=2*stats.t.sf(abs(beta/se),df)
        peq=max(stats.t.sf((beta+.001)/se,df),stats.t.cdf((beta-.001)/se,df))
    return dict(status='ESTIMATED',estimate_pp=100*beta,se_pp=100*se,
                ci_low_pp=100*(beta-critical*se),ci_high_pp=100*(beta+critical*se),
                p_value=float(p),p_equiv=float(peq),ci95_inside_equivalence_margin=bool(abs(beta)+critical*se<.001),df_t=int(df))

def holm(ps):
    p=np.asarray(ps,float);order=np.argsort(p,kind='stable');out=np.empty(len(p))
    out[order]=np.minimum(1,np.maximum.accumulate((len(p)-np.arange(len(p)))*p[order]));return out

def run_models(con,paths,models,pending,work,report,identity,workers=4,batch=32768):
    work,report=Path(work),Path(report);work.mkdir(parents=True,exist_ok=True)
    momentpaths=parallel_jobs(moment_worker,[(str(p),models,str(work/f'moments_{i:03d}.npz'),identity,batch) for i,p in enumerate(paths)],workers,'Within-FE moments')
    acc=merge_moments(momentpaths);fits=fit_moments(acc,models)
    flows={};ledgers={}
    for path in momentpaths:
        extra=json.loads(Path(path).with_suffix('.json').read_text())['extra']
        for key,fields in extra['flows'].items():
            if key not in flows:flows[key]={k:0 for k in fields}
            for k,v in fields.items():flows[key][k]+=v
        for key,path in extra['ledgers'].items():ledgers.setdefault(key,[]).append(path)
    fitpath=work/'fits.npz';save_arrays(fitpath,fits)
    scorepaths=parallel_jobs(score_worker,[(str(p),models,str(fitpath),str(work/f'scores_{i:03d}.npz'),identity,batch) for i,p in enumerate(paths)],workers,'Cluster covariance')
    scores={}
    for p in scorepaths:
        for key,d in load_arrays(p).items():
            if key not in scores:scores[key]=dict(meat=d['meat']*0,pair_meat=d['pair_meat']*0,pairs=0,recipient_files=[])
            a=scores[key];a['meat']+=d['meat'];a['pair_meat']+=d['pair_meat'];a['pairs']+=d['pairs']
            if 'recipient_scores' in d:a['recipient_files'].append(d['recipient_scores'])
    rows=[];support=[];design=[]
    for m in models:
        key=m['key'];base=dict(test=m['test'],variant=m['variant'],state=m['state'],model=key)
        if key not in fits:
            rows.append(dict(**base,contrast='primary',covariance='chooser_CR1',status='NO_NONSINGLETON_SAMPLE'));continue
        f,a,s=fits[key],acc[key],scores[key];G=a['G'];df=f['residual_df'];den=(a['N']-1)/df if df>0 else np.nan
        factor=G/(G-1)*den if G>1 else np.nan;V=s['meat']*factor
        sup={k:a[k] for k in ['N','G','F','grants','selected','treatment_switchers','outcome_switchers','joint_switchers','never_granters','positive_rows','positive_grants','clock_missing','opp_clock_missing','target_min','target_max','k_min','k_max','e_min','e_max']}
        sup.update(singleton_rows_removed=a['selected']-a['N'],within_rank=f['rank'],full_rank=f['full_rank'],residual_df=df,
            condition_number=f['condition'],CR1_multiplier=factor,mean_log_k=a['log_k_sum']/a['N'],
            never_granter_simple_within_weight_share=a['never_granter_weight']/a['raw_within_weight'] if a['raw_within_weight']>0 else None,
            raw_target_within_variance=a['raw_within_weight'],max_abs_draw_payoff=a['zero_max'],
            diagnostic_label='Simple chooser-demeaned first target regressor weight; not adjusted identifying-weight decomposition')
        support_stats=records(con,f"SELECT count(*) retained,count(DISTINCT recipient) recipients,quantile_cont(target,[.01,.10,.25,.50,.75,.90,.99]) target_quantiles FROM {parquet(ledgers[key])}")[0]
        if support_stats['retained']!=a['N']:raise RuntimeError('Support ledger count does not match estimation sample')
        sup['recipients']=support_stats['recipients'];sup.update(flows[key])
        sup.update({f'target_q{q:02d}':v for q,v in zip([1,10,25,50,75,90,99],support_stats['target_quantiles'])})
        sup['nonpositive_rows']=a['N']-a['positive_rows'];sup['nonpositive_grants']=a['grants']-a['positive_grants']
        support.append(dict(**base,**sup))
        diagonal=np.diag(a['S']);inactive=diagonal<=max(float(diagonal.max(initial=0))*1e-13,1e-12)
        design.append(dict(model=key,names=a['names'],invariant_or_negligible_within_columns=[n for n,b in zip(a['names'],inactive) if b],
            within_diagonal=diagonal,projection_error=f['projection_error'],identified=f['identified']))
        for j,label in enumerate(f['labels']):
            r=dict(**base,contrast=label,covariance='chooser_CR1',N=a['N'],grants=a['grants'],choosers=G,
                   target_residual_information=1/f['partial_information'][j] if f['partial_information'][j]>0 else None)
            if m['test']=='T2' and m['variant']=='cubic':
                lo=[10,20,40][j];r['contrast_outside_observed_K_range']=bool(lo<a['k_min'] or 2*lo>a['k_max'])
            r.update(inference(float(f['est'][j]),V[j,j],G-1) if f['identified'][j] else dict(status='UNIDENTIFIED_TARGET'))
            rows.append(r)
            if m['test']=='T2' and m['variant']!='cubic' and m['state']!='difference':
                q=dict(r,contrast='doubling_K');q.update(inference(float(f['est'][j])*np.log(2),V[j,j]*np.log(2)**2,G-1) if f['identified'][j] else dict(status='UNIDENTIFIED_TARGET'));rows.append(q)
        if s['recipient_files']:
            # Only one primary target per non-joint model; aggregate recipient scores across all months/shards.
            rec=records(con,f"SELECT count(*) G,sum(s*s) meat FROM (SELECT recipient,sum(s0) s FROM {parquet(s['recipient_files'])} GROUP BY recipient)")[0]
            Gr=rec['G'];Gp=s['pairs']
            vr=(V[0,0]+den*Gr/(Gr-1)*rec['meat']-den*Gp/(Gp-1)*s['pair_meat'][0,0]) if min(G,Gr,Gp)>1 else np.nan
            r=dict(**base,contrast=f['labels'][0],covariance='chooser_recipient_two_way_CR1',recipient_clusters=Gr,pair_clusters=Gp,N=a['N'],grants=a['grants'],choosers=G)
            r.update(inference(float(f['est'][0]),vr,min(G,Gr)-1) if f['identified'][0] else dict(status='UNIDENTIFIED_TARGET'));rows.append(r)
    for p in pending:rows.append(dict(**p,variant='primary',state='competitive',contrast='primary',covariance='chooser_CR1'))
    # Point estimates of state-specific models must agree with the joint block-diagonal model.
    checks=[]
    for t in ['T1','T2','T3','T4','T5']:
        jk=t+'__primary__difference'
        if jk not in fits:continue
        for j,state in enumerate(['competitive','losing']):
            sk=t+'__primary__'+state
            if sk in fits and fits[jk]['identified'][j] and fits[sk]['identified'][0]:
                delta=abs(float(fits[jk]['est'][j]-fits[sk]['est'][0]));checks.append(dict(test=t,state=state,absolute_probability_difference=delta))
                if delta>1e-6:raise RuntimeError('Joint/separate point estimates disagree beyond tolerance: '+t+' '+state)
    # Three separate five-test families. Missing coefficients enter adjustment arithmetic as p=1.
    primary=[];differences=[]
    for t in ['T1','T2','T3','T4','T5']:
        rr=[r for r in rows if r['test']==t and r['variant']=='primary' and r['state']=='competitive' and r.get('covariance')=='chooser_CR1']
        r=dict(rr[0]) if rr else dict(test=t,variant='primary',state='competitive',status='UNSUPPORTED_INPUT')
        primary.append(r)
        rr=[r for r in rows if r['test']==t and r['variant']=='primary' and r['state']=='difference' and r.get('contrast')=='competitive_minus_losing']
        differences.append(dict(rr[0]) if rr else dict(test=t,state='difference',status='UNSUPPORTED_INPUT'))
    for family,pkey,outkey in [(primary,'p_value','p_holm_5'),(primary,'p_equiv','p_equiv_holm_5'),(differences,'p_value','p_holm_5')]:
        adj=holm([r.get(pkey,1.) for r in family])
        for r,p in zip(family,adj):r[outkey]=float(p);r['family_size']=5
    write_csv(report/'all_estimates.csv',rows);write_csv(report/'primary_family.csv',primary)
    write_csv(report/'status_ledger.csv',
       [{k:r.get(k) for k in ['test','variant','state','contrast','covariance','status','reason']} for r in rows]+
       [dict(test='T6_responsibility',status='SEPARATE_FROZEN_PLAN_PENDING'),dict(test='T6_recipient_Patron',status='PRIOR_EVIDENCE_COPIED_NOT_REESTIMATED'),dict(test='T7_casual',status='DEFERRED_ACQUISITION')])
    write_csv(report/'state_differences.csv',differences);write_csv(report/'support_diagnostics.csv',support)
    write_csv(report/'sample_flow.csv',[dict(model=k,**v) for k,v in flows.items()])
    save_json(report/'design_diagnostics.json',design);write_csv(report/'joint_fit_reproduction.csv',checks)
    for t in ['T1','T2','T3','T4','T5']:write_csv(report/(t+'_estimates.csv'),[r for r in rows if r['test']==t])
    return rows,primary,differences
