"""Memory-weighted scheduling; fresh workers release allocation high-water marks."""
from r7_common import *
from performance_runtime import invoke
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
import multiprocessing as mp

def fit_map(fn,jobs,runtime,workers,memory,label,report):
    # Small physical model tables and contiguous FE arrays avoid loading the wide feature tables.
    import gc
    gc.collect();pa.default_memory_pool().release_unused()
    jobs=sorted(jobs,key=lambda j:j['memory_estimate_gb'],reverse=True);budget=memory-1.5
    if jobs and max(j['memory_estimate_gb'] for j in jobs)>budget:
        need=max(j['memory_estimate_gb'] for j in jobs)+1.5
        raise RuntimeError(f'{label} needs an estimated {need:.1f} GiB total budget. Current budget {memory:g}; checkpoints retained. Do not exceed physical RAM; return the log if the automatic budget cannot fit this version.')
    start=time.monotonic();pending={};metrics=[];error=None
    pool_options={'max_tasks_per_child':1} if sys.version_info>=(3,11) else {}
    with ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn'),**pool_options) as pool:
        while jobs or pending:
            used=sum(j['memory_estimate_gb'] for j in pending.values())
            while jobs and len(pending)<workers:
                k=next((k for k,j in enumerate(jobs) if used+j['memory_estimate_gb']<=budget),None)
                if k is None:break
                job=jobs.pop(k);pending[pool.submit(invoke,fn,job)]=job;used+=job['memory_estimate_gb']
            done,_=wait(pending,timeout=30,return_when=FIRST_COMPLETED)
            for f in done:
                pending.pop(f)
                try:_,metric=f.result();metrics.append(metric)
                except Exception as exc:
                    if error is None:error=exc
                    jobs=[]
                report()
            io.log(f'{label}: {len(metrics)} completed; {len(pending)} active; {len(jobs)} queued; reserved {sum(j["memory_estimate_gb"] for j in pending.values()):.1f} GiB')
    runtime.save(dict(stage=label,kind='memory_weighted_models',seconds=time.monotonic()-start,completed_jobs=len(metrics),workers=workers,
        max_worker_lifetime_peak_rss_gib=max((x['worker_lifetime_peak_rss_gib'] for x in metrics),default=0)))
    if error:raise error

