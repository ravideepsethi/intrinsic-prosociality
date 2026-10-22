"""Schedule independent fits against CPU and peak memory reservations."""
from fast_bootstrap import *
import concurrent.futures as cf
import multiprocessing as mp

def reservation(job):
    n=pq.ParquetFile(job['input']).metadata.num_rows
    controls=len(frozen.r.NH if job.get('balance') else frozen.r.X0)
    if job['level']=='X0_ENV_indicator':controls+=len(frozen.r.ENV)+1
    targets=1+len(job['outcomes'])+(8 if job.get('balance') else 0)
    terms=len(job['outcomes'])+bool(job.get('iv'))+(8 if job.get('balance') else 0)
    design_ram,design=ram_fits(n,controls+targets,'design');cov_ram,covar=ram_fits(n,terms,'covariance')
    return max(design if design_ram else disk_projection_reservation(n,projection_threads(n,True)),covar if cov_ram else 5.25)

def worker(job):
    # Spawned processes get an independent interpreter and one BLAS thread.
    import fast_models
    pa.set_cpu_count(1)
    os.environ['UNIFORM90_FE_THREADS']=str(job.get('_fe_threads',4))
    return fast_models.fit(job)

def fits(jobs):
    jobs=list(jobs)
    if not jobs:return
    budget=memory_budget()-1.;limit=max(1,min(worker_limit()//4,4))
    pending=[(dict(j),reservation(j)) for j in jobs];running={};used=0.;done=0;started=time.monotonic()
    context=mp.get_context('spawn')
    with cf.ProcessPoolExecutor(max_workers=limit,mp_context=context) as pool:
        while pending or running:
            for item in pending[:]:
                job,need=item
                if len(running)>=limit:break
                if used+need>budget and running:continue
                # A very large disk-backed job may exceed the heuristic; run
                # alone. Its SQL/grouping limits remain bounded internally.
                job['_fe_threads']=min(4,max(1,worker_limit()//limit))
                future=pool.submit(worker,job);running[future]=(job,need);used+=need;pending.remove(item)
                log(f'Model scheduled: {job["name"]}; {len(running)} active; reserved {used:.2f}/{memory_budget():.2f} GiB')
            completed,_=cf.wait(running,timeout=30,return_when=cf.FIRST_COMPLETED)
            if not completed:
                log(f'Models: {done}/{len(jobs)} complete, {len(running)} active; elapsed {(time.monotonic()-started)/60:.1f} min')
            for future in completed:
                job,need=running.pop(future);future.result();used-=need;done+=1
                log(f'Model complete: {job["name"]}; {done}/{len(jobs)}')
                yield job
