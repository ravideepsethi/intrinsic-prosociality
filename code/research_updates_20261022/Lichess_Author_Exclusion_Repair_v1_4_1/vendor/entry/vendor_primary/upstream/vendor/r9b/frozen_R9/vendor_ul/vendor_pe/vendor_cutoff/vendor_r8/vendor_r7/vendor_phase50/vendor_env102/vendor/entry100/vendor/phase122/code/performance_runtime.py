"""Bounded spawned workers, measured stage durations and stage-only ETAs."""
from cached_common import *
import concurrent.futures as cf,multiprocessing as mp,time,resource,platform,datetime

def invoke(fn,job):
    began=time.monotonic();existed=(Path(job['output'])/'_DONE.json').exists()
    result=fn(job)
    peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if platform.system()!='Darwin':peak*=1024
    return result,dict(seconds=time.monotonic()-began,reused_checkpoint=existed or bool(result.get('adopted_v102',False)),
                       worker_lifetime_peak_rss_gib=peak/1024**3)

class Runtime:
    def __init__(self,root):
        self.root=Path(root);self.path=self.root/'performance.json'
        self.rows=io.load(self.path) if self.path.exists() else []
        self.run_id=datetime.datetime.now(datetime.timezone.utc).isoformat()

    def save(self,row):
        row=dict(row,execution_id=self.run_id)
        self.rows.append(row);io.js(self.path,self.rows)
        io.log(f"{row['stage']}: finished in {row['seconds']/60:.1f} minutes")

    @contextlib.contextmanager
    def stage(self,label):
        begin=time.monotonic()
        io.log(label+' — starting')
        with io.heartbeat(label):yield
        self.save(dict(stage=label,seconds=time.monotonic()-begin,kind='serial_or_DuckDB'))

    def mapped(self,fn,jobs,workers,label):
        jobs=list(jobs);began=time.monotonic();results=[];metrics=[]
        if not jobs:return []
        weights=[float(j.get('rows',1)) for j in jobs];total=sum(weights);done=fresh=0.
        pending={};next_job=0
        with cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn')) as pool:
            while pending or next_job<len(jobs):
                while next_job<len(jobs) and len(pending)<workers:
                    pending[pool.submit(invoke,fn,jobs[next_job])]=next_job;next_job+=1
                ready,_=cf.wait(pending,timeout=30,return_when=cf.FIRST_COMPLETED)
                for future in ready:
                    k=pending.pop(future);value,metric=future.result();results.append(value);metrics.append(metric)
                    done+=weights[k]
                    if not metric['reused_checkpoint']:fresh+=weights[k]
                elapsed=time.monotonic()-began
                remaining=(total-done)*elapsed/fresh if fresh and len(metrics)>=min(3,len(jobs)) else None
                eta='0.00 h' if not pending and next_job==len(jobs) else f'{remaining/3600:.2f} h' if remaining is not None else 'measuring / reusing checkpoints'
                io.log(f'{label}: {len(results)}/{len(jobs)} complete; stage ETA {eta}; {len(pending)} workers active')
        self.save(dict(stage=label,kind='spawned_workers',seconds=time.monotonic()-began,workers=workers,
            completed_jobs=len(results),reused_checkpoints=sum(r['reused_checkpoint'] for r in metrics),
            max_worker_lifetime_peak_rss_gib=max(r['worker_lifetime_peak_rss_gib'] for r in metrics),
            job_seconds=[r['seconds'] for r in metrics],ETA_scope='current stage only; heterogeneous files make ETA approximate'))
        return results
