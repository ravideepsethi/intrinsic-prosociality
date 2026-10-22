#!/usr/bin/env python3
import os,sys,fcntl,platform,subprocess,shutil,traceback
from pathlib import Path
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[k]='1'
import recovery_util as u

def main():
    p=u.parser();p.add_argument('--offline-only',action='store_true',help='Build the frozen target list and stop at 50%; default also downloads authorized game metadata.')
    a=p.parse_args();a.project=a.project.expanduser().resolve();a.desktop=a.desktop.expanduser().resolve()
    u.require(a.project.is_dir(),'Research drive unavailable: '+str(a.project));u.require(1<=a.workers<=10 and 10.5<=a.memory_gb<=11,'Use 1–10 workers, 10.5–11 GiB planning memory')
    digest=u.package_check()
    config=dict(version='1.0.0',package_manifest_sha256=digest,parent_configuration_sha256=u.PARENT_CONF,project=str(a.project),support='finite all-time pair-excluded Score A; n>=5',comparison_gap_days=90,profile_requests=0)
    a.conf=u.key(config);a.run=a.project/'derived/replication/comparison_totalfive_recovery_v100_PRIVATE'/a.conf[:12]
    a.run.mkdir(parents=True,exist_ok=True);(a.run/'PRIVATE').mkdir(exist_ok=True);(a.run/'report').mkdir(exist_ok=True);a.desktop.mkdir(parents=True,exist_ok=True)
    # Canonical chronology scanning can spill; this is a preflight floor, not a
    # promised peak bound. Existing source files are read only.
    reserve=20 if (a.run/'PRIVATE/requests/_DONE.json').is_file() else 150
    u.require(shutil.disk_usage(a.run).free>=reserve*2**30,f'Need at least {reserve} GiB free for remaining stages and temporary spill')
    with (a.run/'RUN.lock').open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('This recovery is already running')
        if (a.run/'config.json').exists():u.require(u.load(a.run/'config.json')==config,'Configuration changed')
        else:u.save(a.run/'config.json',config)
        import importlib.metadata,chess
        u.save(a.run/'report/runtime.json',dict(python=platform.python_version(),packages={k:importlib.metadata.version(k) for k in ('numpy','pandas','pyarrow','duckdb','scipy')},chess=chess.__version__,workers_ceiling=a.workers,large_data_workers=min(2,a.workers),memory_planning_GiB=a.memory_gb,OS_memory_cap=False,BLAS_threads=1))
        shutil.copyfile(u.PACKAGE/'METHODS.txt',a.run/'report/METHODS.txt')
        u.save(a.desktop/'COMPARISON_TOTALFIVE_RECOVERY_LATEST_PRIVATE.json',dict(root=str(a.run),configuration_sha256=a.conf))
        percent=0
        try:
            with u.pulse('Authenticating completed migration and metadata audit'):u.authenticate_report(a)
            steps=[('score_worker.py','scores',25),('metadata_worker.py','metadata',25),('metadata_worker.py','chronology',50)]
            if not a.offline_only:steps.append(('download_worker.py','download',100))
            for script,mode,mark in steps:
                u.log(f'{percent}% | {mode}. Initial total ETA unavailable; chronology and API throughput will determine it.')
                cmd=[sys.executable,'-u',str(u.PACKAGE/'code'/script),'--project',str(a.project),'--desktop',str(a.desktop),'--run',str(a.run),'--conf',a.conf,'--mode',mode,'--workers',str(a.workers),'--memory-gb',str(a.memory_gb)]
                subprocess.run(cmd,check=True);percent=mark
                if mark!=100:u.export(a,mark,'OFFLINE_TARGETS_READY' if mark==50 and a.offline_only else 'IN_PROGRESS')
            u.log('Requested recovery stages complete. Final comparison fits and the new profile snapshot remain pending.')
        except BaseException:
            traceback.print_exc()
            sp=a.run/'report/status.json'
            if sp.exists():percent=max(percent,u.load(sp).get('progress_percent',0))
            u.export(a,percent,'STOPPED');raise
if __name__=='__main__':main()
