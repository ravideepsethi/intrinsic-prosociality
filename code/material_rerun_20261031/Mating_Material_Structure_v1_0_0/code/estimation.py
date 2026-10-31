"""Shared two-pass regression moments; exact chooser absorption and CR1 meat."""
from util import *
from checkpoints import stage
from sources import producers,union_design
from panel import mapped
import numpy as np

def write_npz(path,**values):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.partial')
    with tmp.open('wb') as f:np.savez_compressed(f,**values)
    os.replace(tmp,path)

def moments(frame,phase,fits=None):
    _,_,engine,_,_=producers()
    X,names,indices=union_design(frame);y=100*frame.y.to_numpy(float)
    starts,counts=engine.grouped(frame.chooser.to_numpy())
    summary=dict(n=np.array(len(y)),g=np.array(len(counts)),grants=np.array(int(frame.y.sum())),
                 within_n=np.array(counts[counts>=2].sum()),within_g=np.array((counts>=2).sum()))
    engine.demean(X,y,starts,counts)
    if phase==1:return dict(summary,xx=X.T@X,xy=X.T@y)
    out=summary
    for model,ix in indices.items():
        f=fits[model];W=X[:,ix];residual=y-W@f['beta']
        score=np.empty((len(starts),len(ix)))
        # Avoid an N by K temporary for cluster scores.
        for a in range(0,len(starts),2048):
            b=min(a+2048,len(starts));lo=starts[a];hi=starts[b] if b<len(starts) else len(y)
            score[a:b]=np.add.reduceat(W[lo:hi]*residual[lo:hi,None],starts[a:b]-lo,axis=0)
        out[model]=score.T@score
    return out

def task(t):
    _,_,engine,_,_=producers();started=time.monotonic()
    def build(out):
        frame=engine.read_bucket(t['files'])
        require(len(frame)>0 and int(frame.chooser.isna().sum())==0,'Invalid chooser partition')
        # Partitioning is exact integer modulo and unchanged across passes.
        require(bool((((frame.chooser%t['shards'])+t['shards'])%t['shards']==t['bucket']).all()),'An account crosses chooser partitions')
        values=moments(frame,t['phase'],t.get('fits'))
        write_npz(out/'moments.npz',**values)
        return {k:int(values[k]) for k in ('n','g','grants','within_n','within_g')}
    path,result=stage(t['parent'],f"{t['bucket']:04d}",t['key'],build)
    return dict(bucket=t['bucket'],path=str(path/'moments.npz'),seconds=time.monotonic()-started,**result)

def combine(paths):
    total={}
    for p in paths:
        with np.load(p,allow_pickle=False) as z:
            for name in z.files:total[name]=total.get(name,0)+z[name]
    return total

def fit_models(by,run,key,workers,memory,shards,expected):
    import pyarrow.parquet as pq
    r11,_,engine,_,_=producers();_,names,indices=union_design(r11.dummy())
    largest=max(sum(pq.ParquetFile(p).metadata.num_rows for p in files) for files in by.values())
    # Covers simultaneous original matrices, the union copy, group means and
    # score workspace. A 160,000-row, 3-model synthetic benchmark peaks at
    # 0.79 GiB; this bound allocates >1.1 GiB at that size, plus the parent's
    # separately reserved overhead. Cap workers from the largest real shard.
    per=(largest*8*(4*len(names)+2*max(map(len,indices.values()))+70)+200_000_000)/2**30
    require(per<memory-.75,'A chooser partition exceeds memory; increase --shards')
    active=max(1,min(workers,int((memory-.75)/max(.5,per))))
    save(run/'report/RESOURCE_PLAN.json',dict(workers=active,requested_workers=workers,estimated_worker_gib=per,
          memory_budget_gb=memory,largest_partition_rows=largest,shards=shards,union_columns=len(names),single_blas_thread=True))
    log(f'Three models share regression passes; {active} workers, estimated {per:.2f} GiB per worker')
    fits=None;fitkey=None;first=None
    for phase in (1,2):
        tasks=[dict(bucket=b,files=list(map(str,paths)),shards=shards,phase=phase,fits=fits,
                    parent=str(run/f'PRIVATE/phase{phase}'),key=digest([key,phase,b,fitkey])) for b,paths in sorted(by.items())]
        results=mapped(task,tasks,active,'Regression moments' if phase==1 else 'Chooser covariance')
        totals=combine([r['path'] for r in sorted(results,key=lambda r:r['bucket'])])
        for k in ('n','g','grants'):
            require(int(totals[k])==expected[{'n':'opportunities','g':'choosers','grants':'grants'}[k]],'Regression count mismatch: '+k)
        if phase==1:
            first=totals;fits={}
            for model,ix in indices.items():
                f=engine.solve(totals['xx'][np.ix_(ix,ix)],totals['xy'][ix]);f['names']=[names[j] for j in ix];fits[model]=f
            fitkey=digest({m:f['beta'].tolist() for m,f in fits.items()})
        else:
            require(int(totals['g'])>1,'Need at least two chooser clusters')
            for model,f in fits.items():
                V=f['bread']@totals[model]@f['bread']*(int(totals['g'])/(int(totals['g'])-1))
                f['covariance']=(V+V.T)/2
                f.update({k:int(first[k]) for k in ('n','g','grants','within_n','within_g')})
                require(np.isfinite(f['covariance']).all(),'Nonfinite covariance')
    return fits
