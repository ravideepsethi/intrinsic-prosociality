"""Spawned workers with explicit estimated RAM reservations and checkpoint ETAs."""
from pe_common import *
import concurrent.futures as cf
import multiprocessing as mp

def capacity(jobs, workers, memory):
    budget=memory-1.5
    u.require(budget>0 and all(j['memory_gb']<=budget for j in jobs),
        'A job exceeds the RAM budget. Use --memory-gb 11; no oversized worker is launched.')
    return min(workers,len(jobs)),budget

def mapped(fn, jobs, workers, memory, label, forecast_minutes, tail_minutes=0, callback=None):
    if not jobs:return []
    slots,budget=capacity(jobs,workers,memory)
    pending=list(enumerate(jobs));running={};done={};started=time.monotonic();used=0.
    kw=dict(max_workers=slots,mp_context=mp.get_context('spawn'))
    if sys.version_info>=(3,11):kw['max_tasks_per_child']=1
    def progress():
        elapsed=(time.monotonic()-started)/60
        # Wall-clock throughput includes scheduling limits and disk contention.
        remain=elapsed/max(len(done),1)*(len(jobs)-len(done)) if done else max(1,forecast_minutes-elapsed)
        u.log(f'{label}: {len(done)}/{len(jobs)} complete, {len(running)} workers, estimated reserved RAM {used:.1f}/{budget:.1f} GiB; '
              f'next checkpoint ETA ~{max(0,remain):.1f} min; finish ETA ~{max(0,remain)+tail_minutes:.1f} min')
    with cf.ProcessPoolExecutor(**kw) as pool:
        while pending or running:
            for item in list(pending):
                index,job=item
                if len(running)<slots and used+job['memory_gb']<=budget+1e-9:
                    future=pool.submit(fn,job);running[future]=(index,job);pending.remove(item);used+=job['memory_gb']
            u.require(bool(running),'No job can be scheduled within memory budget')
            finished,_=cf.wait(running,timeout=30,return_when=cf.FIRST_COMPLETED)
            for future in finished:
                index,job=running.pop(future);used-=job['memory_gb'];done[index]=future.result()
                if callback:callback(len(done),len(jobs))
            progress()
    return [done[k] for k in range(len(jobs))]
