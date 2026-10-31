"""Bounded two-pass execution of the original 53 models, with atomic shards."""
from util import *
from sources import producers
from checkpoints import stage
import numpy as np,pandas as pd,pyarrow.parquet as pq
import multiprocessing as mp,concurrent.futures as cf

def partition(frame,run,key,shards):
    def build(folder):
        d=pq.ParquetFile(frame).read(use_threads=False).to_pandas(use_threads=False)
        buckets=d.chooser.to_numpy('int64')%shards;rows=[]
        for number in sorted(np.unique(buckets)):
            g=d.loc[buckets==number].sort_values('chooser',kind='stable')
            p=folder/f'{number:04d}.parquet';g.to_parquet(p,index=False,compression='zstd')
            rows.append(dict(file=p.name,rows=len(g),choosers=int(g.chooser.nunique())))
        return dict(shards=rows,rows=len(d),choosers=int(d.chooser.nunique()))
    return stage(run/'PRIVATE','partitions',digest([key,'partition',shards,record(frame)]),build)

def model_support(frame,run):
    legacy=producers();d=pq.ParquetFile(frame).read(use_threads=False).to_pandas(use_threads=False)
    specs=legacy['design'].specifications(False);require(len(specs)==53,'Original responsibility model inventory changed')
    rows=[]
    for s in specs:
        a=legacy['design'].select(d,s)
        require(len(a)>0 and a.chooser.nunique()>1,'No supported sample for original specification '+s['name'])
        rows.append(dict(model=s['name'],N=len(a),choosers=int(a.chooser.nunique()),row_set_sha256=legacy['common'].fingerprint(sorted(a.game_id.tolist()))))
    rows_by_name={r['model']:r for r in rows}
    for label in ('late','all'):
        require(rows_by_name['curve_'+label+'_common_baseline']['row_set_sha256']==rows_by_name['curve_'+label+'_common_proxies']['row_set_sha256'],'Curve comparison uses different observations')
    save(run/'report/model_definitions.json',specs);save(run/'report/unsupported_models.json',[])
    table(run/'report/model_row_support.csv',rows)
    legacy['coverage'](d,run/'report')
    return specs

_SPECS=None
_FITS=None
def initialize(specs,fits):
    global _SPECS,_FITS
    _SPECS=specs;_FITS=fits
    import pyarrow as pa
    pa.set_cpu_count(1);pa.set_io_thread_count(1);producers()

def run_bucket(task):
    parent,name,key,path,phase=task
    def build(folder):
        started=time.monotonic();engine=producers()['estimate']
        d=engine.read_bucket([path]);result={}
        for j,s in enumerate(_SPECS):
            if phase==1:
                m,_,_,_=engine.moments(d,s)
                for label,value in m.items():result[f'm{j}_{label}']=value
            else:result[f'm{j}_meat']=engine.meat(d,s,_FITS[j])
        with (folder/'moments.npz').open('wb') as f:np.savez_compressed(f,**result)
        return dict(rows=len(d),seconds=time.monotonic()-started,phase=phase)
    folder,meta=stage(parent,name,key,build)
    return str(folder/'moments.npz'),meta

def pass_jobs(tasks,workers,specs,fits,label):
    with heartbeat(label):
        if workers==1:
            initialize(specs,fits);return [run_bucket(t) for t in tasks]
        results=[]
        with cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn'),initializer=initialize,initargs=(specs,fits)) as pool:
            futures=[pool.submit(run_bucket,t) for t in tasks]
            for i,f in enumerate(futures):
                results.append(f.result())
                if (i+1)%8==0 or i+1==len(futures):log(f'{label}: {i+1}/{len(futures)} chooser shards complete')
        return results

def fit_models(frame,run,key,workers,memory,shards):
    (run/'PRIVATE').mkdir(parents=True,exist_ok=True);(run/'report').mkdir(parents=True,exist_ok=True)
    specs=model_support(frame,run);legacy=producers();engine=legacy['estimate']
    folder,info=partition(frame,run,key,shards)
    maxcols=max(legacy['design'].design(legacy['design'].dummy(),s)[0].shape[1] for s in specs)
    largest=max(r['rows'] for r in info['shards'])
    # X, demeaned X, grouped sums/temporary products plus the DataFrame and model state.
    per_worker=(largest*8*(maxcols*6+100)+250_000_000)/2**30
    active=min(workers,len(info['shards']),max(1,int(memory/max(per_worker,.1))))
    require(per_worker<=memory,'Largest chooser shard exceeds memory budget; increase --shards')
    plan=dict(workers=active,requested_workers=workers,memory_gb=memory,estimated_gib_per_worker=per_worker,largest_shard_rows=largest,maximum_design_columns=maxcols,shards=len(info['shards']))
    save(run/'report/RESOURCE_PLAN.json',plan)
    fits=None
    for phase in (1,2):
        tasks=[]
        fitkey=digest([f['beta'].tolist() for f in fits]) if fits is not None else None
        for row in info['shards']:
            path=folder/row['file'];name=path.stem
            jobkey=digest([key,'fit',phase,record(path),specs,fitkey])
            tasks.append((run/'PRIVATE'/f'pass{phase}',name,jobkey,str(path),phase))
        values=pass_jobs(tasks,active,specs,fits,f'{run.name}: regression pass {phase}')
        paths=[p for p,m in values]
        if phase==1:
            fits=engine.aggregate_first(paths,specs)
            from design_support import certify
            certify(paths,specs,fits,pd.read_csv(run/'report/model_row_support.csv').to_dict('records'),
                    run/'report/within_design_support.json')
        else:meats=engine.aggregate_meat(paths,specs)
    for s,f,M in zip(specs,fits,meats):
        V=engine.coefficient_cov(f,M)
        require(np.isfinite(f['beta']).all() and np.isfinite(M).all() and np.isfinite(V).all(),'Nonfinite regression result: '+s['name'])
        require(np.allclose(V,V.T,rtol=1e-7,atol=1e-8),'Asymmetric coefficient covariance: '+s['name'])
    # Include full model state and influence meat for independently checking profiles.
    arrays={};metadata=[]
    for i,(s,f,M) in enumerate(zip(specs,fits,meats)):
        scalars={k:v for k,v in f.items() if not isinstance(v,np.ndarray)}
        metadata.append(dict(model=s['name'],**scalars))
        for label,value in f.items():
            if isinstance(value,np.ndarray):arrays[f'm{i}_{label}']=value
        arrays[f'm{i}_meat']=M
    with (run/'report/model_state.npz').open('wb') as stream:np.savez_compressed(stream,**arrays)
    save(run/'report/model_state.json',metadata)
    history_status=dict(status='NOT_PART_OF_THE_53_ARCHIVED_SPECIFICATIONS',
        reason='The archived 53-model result used no prior-disconnection-history input. Those additional models are not claimed as completed.')
    save(run/'report/HISTORY_STATUS.json',history_status)
    legacy['report'].render(run/'report',specs,fits,meats,history_status)
    return dict(models=len(specs),rows=info['rows'],choosers=info['choosers'],resource_plan=plan)
