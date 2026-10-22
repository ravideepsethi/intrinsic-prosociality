"""Chooser-partitioned Parquet workers; reduce sufficient statistics exactly."""
from __future__ import annotations
import concurrent.futures
import hashlib
import json
import multiprocessing
import os
import time
from pathlib import Path
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from threadpoolctl import threadpool_limits
import fe_suite as fe
import checked_math as checked
import recovery_math


def worker_init():
    # Spawn-safe on macOS; the launcher also sets these before NumPy is imported.
    for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS',
              'VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):
        os.environ[k]='1'
    global _thread_limit
    _thread_limit=threadpool_limits(limits=1)
    pa.set_cpu_count(1);pa.set_io_thread_count(1)


def shards(cache,out,workers):
    """Preserve chooser order and keep each entire cluster in exactly one file."""
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    writers={};counts=[0]*workers
    paths=[out/f'chooser_shard_{j:02d}_PRIVATE.parquet' for j in range(workers)]
    t0=time.monotonic();read=0;last=t0;schema=pq.ParquetFile(cache).schema_arrow
    try:
        for batch in pq.ParquetFile(cache).iter_batches(batch_size=131072,use_threads=False):
            table=pa.Table.from_batches([batch]);part=table['chooser'].to_numpy()%workers
            for j,path in enumerate(paths):
                if j not in writers:writers[j]=pq.ParquetWriter(path.with_suffix('.partial.parquet'),schema,compression='zstd')
                sub=table.filter(pa.array(part==j))
                if len(sub):writers[j].write_table(sub);counts[j]+=len(sub)
            read+=len(table)
            if time.monotonic()-last>25:
                fe.log(f'Parquet partitioning: {read:,} rows');last=time.monotonic()
    finally:
        for w in writers.values():w.close()
    for p in paths:os.replace(p.with_suffix('.partial.parquet'),p)
    if sum(counts)!=pq.ParquetFile(cache).metadata.num_rows:raise ValueError('Shard row conservation failed')
    receipt={'workers':workers,'rule':'chooser_id modulo workers',
      'rows':sum(counts),'seconds':time.monotonic()-t0,
      'shards':[{'file':p.name,'rows':n,'bytes':p.stat().st_size} for p,n in zip(paths,counts)]}
    return paths,receipt


def _progress(job,done,total,start,last,phase):
    now=time.monotonic()
    if now-last>30:
        remaining=(now-start)*max(total-done,0)/max(done,1)
        fe.log(f'{job["group"]} {Path(job["cache"]).stem}: {phase} {done:,}/{total:,}; '
               f'estimated remaining {remaining/60:.1f} min for this worker/pass')
        return now
    return last


def moment_job(job):
    union=job['union'];S=np.zeros((len(union)+1,len(union)+1));counts={}
    variation=np.zeros(len(union),dtype=np.int64)
    t0=time.monotonic();last=t0;seen=0;audit={}
    total=pq.ParquetFile(job['cache']).metadata.num_rows
    design_hash=hashlib.sha256();strict=job['group']=='exact_ply_recovery'
    for original in fe.blocks(job['cache'],job['batch_size']):
        seen+=len(original['y']);d=fe.selected(original,job['group'])
        if len(d['y']):
            X=np.ascontiguousarray(fe.matrix(d,job['meta'])[:,union])
            transform=recovery_math.transformed if strict else fe.transformed
            Z,w,cs,c=transform(d,X,job['fe'],job['weight'])
            if strict:recovery_math.hash_design(design_hash,Z,w,cs)
            checked.check_centering(Z,cs,audit)
            Q=Z*np.sqrt(w)[:,None];G=checked.gram(Q,audit)
            if strict:recovery_math.check_response_products(Q,G,audit)
            S+=G
            for k,v in c.items():counts[k]=counts.get(k,0)+v
            variation+=(np.add.reduceat(Z[:,1:]**2,cs,axis=0)>1e-14).sum(axis=0)
        last=_progress(job,seen,total,t0,last,'moments')
    if strict:audit['centered_design_sha256']=design_hash.hexdigest()
    return S,counts,variation,time.monotonic()-t0,audit


def score_job(job):
    fits=job['fits']
    results=[{'meat':np.zeros((len(f['ix']),len(f['ix']))),'score_sum':np.zeros(len(f['ix'])),'sse':0.} for f in fits]
    t0=time.monotonic();last=t0;seen=0;audit={}
    total=pq.ParquetFile(job['cache']).metadata.num_rows
    design_hash=hashlib.sha256();strict=job['group']=='exact_ply_recovery'
    for original in fe.blocks(job['cache'],job['batch_size']):
        seen+=len(original['y']);d=fe.selected(original,job['group'])
        if len(d['y']):
            X=np.ascontiguousarray(fe.matrix(d,job['meta'])[:,job['union']])
            transform=recovery_math.transformed if strict else fe.transformed
            Z,w,cs,c=transform(d,X,job['fe'],job['weight'])
            if strict:recovery_math.hash_design(design_hash,Z,w,cs)
            checked.check_centering(Z,cs,audit)
            for f,r in zip(fits,results):
                x=np.ascontiguousarray(Z[:,f['ix']+1])
                prediction=recovery_math.predict(x,f['beta'],audit) if strict else checked.matvec(x,f['beta'])
                e=Z[:,0]-prediction
                score=recovery_math.cluster_scores(x,w*e,cs,audit) if strict else np.add.reduceat(x*(w*e)[:,None],cs,axis=0)
                r['meat']+=checked.gram(score,audit);r['score_sum']+=score.sum(axis=0)
                r['sse']+=float(np.sum(w*e**2))
        last=_progress(job,seen,total,t0,last,'scores')
    if strict:audit['centered_design_sha256']=design_hash.hexdigest()
    return results,time.monotonic()-t0,audit


def fit_group(paths,meta,out,group,executor,batch_size=32768):
    out=Path(out);out.mkdir(parents=True,exist_ok=True);t0=time.monotonic()
    names,parts=fe.layout(meta);specs=fe.model_specs(parts)[group]
    union=np.unique(np.concatenate([i for _,i in specs]));local={int(v):i for i,v in enumerate(union)}
    specs=[(name,np.array([local[int(j)] for j in ix])) for name,ix in specs]
    names=[names[j] for j in union]
    unit='chooser_speed' if group=='speed_fe' else 'chooser'
    weight='inverse_count' if group=='weighting' else 'opportunity'
    jobs=[dict(cache=str(p),meta=meta,group=group,union=union,fe=unit,weight=weight,batch_size=batch_size) for p in paths]
    S=np.zeros((len(union)+1,len(union)+1));counts={};variation=np.zeros(len(union),dtype=np.int64)
    moment_seconds=[];moment_audits=[]
    # Ordered reduction is deterministic; no regression coefficients are averaged.
    for s,c,v,elapsed,audit in executor.map(moment_job,jobs):
        S+=s;variation+=v;moment_seconds.append(elapsed)
        moment_audits.append(audit)
        for k,n in c.items():counts[k]=counts.get(k,0)+n
    t_moments=time.monotonic()-t0
    if counts.get('choosers',0)<2:raise ValueError(f'{group}: insufficient chooser support')
    np.savez_compressed(out/'moments.npz',S=S,terms=np.array(names),variation=variation,counts=np.array(json.dumps(counts)))
    fe.symmetric_parquet(out/'moments.parquet',S,['within_y']+names,'sum_cross_product')
    if group=='weighting' and (out.parent/'states/moments.npz').is_file():
        with np.load(out.parent/'states/moments.npz') as reference:
            reference_terms=reference['terms'].tolist()
            indices=np.array([reference_terms.index(t)+1 for t in names])
            original=reference['S'][np.ix_(indices,indices)]
        receipt=checked.positive_weight_nullspace(original,S[1:,1:])
        fe.json_write(out/'POSITIVE_WEIGHT_NULLSPACE_CHECK.json',receipt)
    fits=[]
    for name,ix in specs:
        f=fe.solve(S[np.ix_(ix+1,ix+1)],S[ix+1,0])
        f.update(name=name,ix=ix,terms=[names[j] for j in ix],meat=np.zeros((len(ix),len(ix))),
                 sse=0.,score_sum=np.zeros(len(ix)))
        fits.append(f)
    scorejobs=[dict(j,fits=[dict(ix=f['ix'],beta=f['beta']) for f in fits]) for j in jobs]
    scores0=time.monotonic();score_seconds=[];score_audits=[]
    for rs,elapsed,audit in executor.map(score_job,scorejobs):
        score_seconds.append(elapsed)
        score_audits.append(audit)
        for f,r in zip(fits,rs):
            f['meat']+=r['meat'];f['score_sum']+=r['score_sum'];f['sse']+=r['sse']
    # Save diagnostics before any guard can stop table production.
    fe.json_write(out/'ARITHMETIC_AUDIT.json',{'moment_workers':moment_audits,'score_workers':score_audits,
      'backends':checked.backend(),'guard_threshold':1e-7})
    if group=='exact_ply_recovery':
        recovery_math.check_design_hashes(moment_audits,score_audits)
    diagnostics=[]
    for f in fits:
        expected_score=S[f['ix']+1,0]-checked.matvec(S[np.ix_(f['ix']+1,f['ix']+1)],f['beta'])
        denom=max(1.,np.max(np.abs(S[1:,0])))
        diagnostics.append({'model':f['name'],'score_error':float(np.max(np.abs(f['score_sum']))/denom),
          'score_vs_moments_error':float(np.max(np.abs(f['score_sum']-expected_score))/denom),
          'normal_equation_error':f['normal_error']})
        fe.symmetric_parquet(out/(f['name']+'_cluster_meat.parquet'),f['meat'],f['terms'],'meat')
        fe.csv_write(out/(f['name']+'_score_diagnostics.csv'),[{'term':t,'score_sum':float(s),'expected_from_moments':float(e)}
          for t,s,e in zip(f['terms'],f['score_sum'],expected_score)])
    fe.csv_write(out/'numerical_checks.csv',diagnostics)
    if any(d['score_vs_moments_error']>1e-7 for d in diagnostics):
        raise ValueError('Direct cluster scores disagree with saved moments; diagnostics saved')
    for f in fits:
        f['cov']=counts['choosers']/(counts['choosers']-1)*f['bread']@f['meat']@f['bread']
        f['cov']=(f['cov']+f['cov'].T)/2
        f['within_r2']=None if S[0,0]<=0 else float(1-f['sse']/S[0,0])
        f['score_error']=float(np.max(np.abs(f['score_sum']))/max(1.,np.max(np.abs(S[1:,0]))))
        if f['score_error']>1e-7:raise ValueError(f"Cluster-score conservation failed in {f['name']}: {f['score_error']:.6g}; diagnostics saved")
        f['counts']=counts;f['fe']=unit;f['weight']=weight
        np.savez_compressed(out/(f['name']+'_covariance.npz'),cov_pp2=f['cov']*10000,beta_pp=f['beta']*100,terms=np.array(f['terms']))
        fe.symmetric_parquet(out/(f['name']+'_covariance.parquet'),f['cov']*10000,f['terms'],'covariance_pp2')
    fe.csv_write(out/'within_variation_support.csv',[dict(term=t,choosers=int(n)) for t,n in zip(names,variation)])
    timing=dict(group=group,workers=len(paths),blas_threads_per_worker=1,
      moments_wall_seconds=t_moments,scores_wall_seconds=time.monotonic()-scores0,
      total_wall_seconds=time.monotonic()-t0,moment_worker_seconds=moment_seconds,score_worker_seconds=score_seconds)
    fe.json_write(out/'TIMING.json',timing)
    fe.csv_write(out/'timing.csv',[{k:v for k,v in timing.items() if not isinstance(v,list)}])
    fe.log(f'{group} complete in {timing["total_wall_seconds"]/60:.1f} min with {len(paths)} worker(s)')
    return fits


def pool(workers):
    return concurrent.futures.ProcessPoolExecutor(max_workers=workers,
      mp_context=multiprocessing.get_context('spawn'),initializer=worker_init)
