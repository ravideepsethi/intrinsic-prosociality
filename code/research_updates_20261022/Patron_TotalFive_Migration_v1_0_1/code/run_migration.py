#!/usr/bin/env python3
"""Offline Patron receipt migration; a separate comparison metadata preflight."""
import fcntl,os,subprocess,sys,shutil,platform,time,traceback
from pathlib import Path
for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[name]='1'
import migration_util as mu

def runtime_versions():
    import importlib.metadata
    import chess
    versions={n:importlib.metadata.version(n) for n in ('numpy','pandas','pyarrow','duckdb','scipy')}
    versions['chess']=chess.__version__
    return versions

def main():
    p=mu.parser();p.add_argument('--primary-only',action='store_true',help='Stop after validated primary Patron results at 50%; rerun without this flag for remaining stages.')
    a=p.parse_args();a.project=a.project.expanduser().resolve();a.desktop=a.desktop.expanduser().resolve()
    mu.require(a.project.is_dir(),'Research drive is unavailable: '+str(a.project))
    mu.require(1<=a.workers<=10 and 10.5<=a.memory_gb<=11,'Use 1–10 workers and 10.5–11 GiB')
    digest=mu.package_check()
    config=dict(version='1.0.1',package_manifest_sha256=digest,project=str(a.project),receipt_source='R12_4df83f1178f3_cutoff5',profile_source='3432ba6ee3ae_original_snapshot',common_score_SD=.04979005187533171,comparison_task='full_acquisition_denominator_metadata_audit_only')
    conf=mu.key(config);run=a.project/'derived/replication/patron_totalfive_migration_v100_PRIVATE'/conf[:12]
    run.mkdir(parents=True,exist_ok=True);(run/'PRIVATE').mkdir(exist_ok=True);(run/'report').mkdir(exist_ok=True);a.desktop.mkdir(parents=True,exist_ok=True)
    mu.require(shutil.disk_usage(run).free>=40*2**30,'Need at least 40 GiB free for new features, audit ledgers and spill')
    with (run/'RUN.lock').open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('This migration is already running')
        if (run/'config.json').exists():mu.require(mu.load(run/'config.json')==config,'Run definition changed')
        else:mu.save(run/'config.json',config)
        versions=runtime_versions()
        mu.save(run/'report/runtime.json',dict(python=platform.python_version(),packages=versions,workers_ceiling=a.workers,memory_planning_GiB=a.memory_gb,BLAS_threads=1,OS_memory_cap=False,package_manifest_sha256=digest))
        shutil.copy2(mu.PACKAGE/'REPORT_METHODS.txt',run/'report/REPORT_METHODS.txt')
        mu.save(a.desktop/'PATRON_TOTALFIVE_LATEST_PRIVATE.json',dict(root=str(run),configuration_sha256=conf))
        steps=[('receipt_worker.py','bind',0),('patron_prepare.py','primary',25),('patron_fit.py','primary',50)]
        if not a.primary_only:steps += [('receipt_worker.py','variants',50),('patron_prepare.py','extended',50),('patron_fit.py','extended',75),('comparison_audit.py','audit',100)]
        percent=0;started=time.monotonic()
        try:
            forecasts=[5,5,15,120,5,10,45][:len(steps)]
            for step,(script,mode,mark) in enumerate(steps):
                mu.log(f'{percent}% | {script}: {mode} | elapsed {(time.monotonic()-started)/60:.1f} min')
                cmd=[sys.executable,'-u',str(mu.PACKAGE/'code'/script),'--project',str(a.project),'--desktop',str(a.desktop),'--run',str(run),'--conf',conf,'--mode',mode,'--workers',str(a.workers),'--memory-gb',str(a.memory_gb)]
                stage_started=time.monotonic()
                checkpoint=next((ix for ix in range(step,len(steps)) if steps[ix][2]>percent),len(steps)-1)
                def progress():
                    elapsed=(time.monotonic()-stage_started)/60
                    current=max(1.,forecasts[step]-elapsed)
                    return f'{percent}% | {mode} | rough ETA next checkpoint {current+sum(forecasts[step+1:checkpoint+1]):.0f} min; finish {current+sum(forecasts[step+1:]):.0f} min (provisional)'
                with mu.pulse(progress):
                    subprocess.run(cmd,check=True)
                percent=mark
                mu.save(run/'PRIVATE/STATE.json',dict(last_completed=script+':'+mode,progress_percent=percent,elapsed_seconds=time.monotonic()-started))
                if mark in (25,50,75,100):mu.export(run,a.desktop,conf,mark,'PRIMARY_READY_REMAINING_STAGES_PENDING' if a.primary_only and mark==50 else 'COMPLETE_PATRON_AND_COMPARISON_AUDIT' if mark==100 else 'IN_PROGRESS')
            mu.log('Finished requested stages. Corrected comparison fits and Patron placebo remain pending; see REPORT_METHODS.txt.')
        except BaseException:
            traceback.print_exc()
            mu.export(run,a.desktop,conf,percent,'STOPPED')
            raise

if __name__=='__main__':main()
