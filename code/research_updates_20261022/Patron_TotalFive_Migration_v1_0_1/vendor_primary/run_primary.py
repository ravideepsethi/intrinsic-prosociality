#!/usr/bin/env python3
"""One locked namespace; isolated stages; read-only upstream caches."""
import os, sys, argparse, fcntl, subprocess, signal, traceback, shutil, platform
from pathlib import Path
for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[name]='1'
from primary_common import *

STAGES=('primary','wider','scores','features','diagnostics','comparisons')

def parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--result-dir',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--r12-root',type=Path);p.add_argument('--r9-root',type=Path);p.add_argument('--comparison-root',type=Path)
    p.add_argument('--workers',type=int,default=10);p.add_argument('--memory-gb',type=float,default=11.)
    p.add_argument('--preflight-only',action='store_true');p.add_argument('--only-primary',action='store_true')
    p.add_argument('--self-test',action='store_true');p.add_argument('--_stage',choices=STAGES,help=argparse.SUPPRESS)
    return p

def execute_stage(a,run,conf):
    import primary_inputs as pi, primary_models as pm
    if a._stage=='primary':
        b=pi.bind(a,run,conf);pm.initial(a,run,conf,b);return
    b=load(run/'PRIVATE/BOUND.json')
    if a._stage=='wider':pi.wider(a,run,conf,b)
    elif a._stage=='scores':
        import primary_scores
        primary_scores.prepare(a,run,conf,b)
    elif a._stage=='features':
        import primary_features
        primary_features.prepare(a,run,conf,b)
    elif a._stage=='diagnostics':
        w=load(run/'PRIVATE/WIDER.json');s=load(run/'PRIVATE/DIAGNOSTIC_SCORES.json');f=load(run/'PRIVATE/POSITION_FEATURES.json')
        jobs=pm.diagnostic_plan(a,run,conf,b,(w['source'],w['scores']),s['scores'],s['flags'],f['act'],f['material'])
        # Model-level receipts preserve completed work even within this stage.
        for label,part in [('hours_and_exposure_variants',[j for j in jobs if not j['name'].startswith(('subgroup_','donor_','calibration'))]),
                           ('subgroups_and_score_regions',[j for j in jobs if j['name'].startswith(('subgroup_','donor_'))]),
                           ('history_calibration',[j for j in jobs if j['name'].startswith('calibration')])]:
            pm.execute(a,run,conf,part,label)
        pm.timing_contrasts(a,run,conf)
    elif a._stage=='comparisons':pm.comparison100(a,run,conf)

def main():
    a=parser().parse_args()
    if a.self_test:
        return subprocess.call([sys.executable,'-m','unittest','discover','-s',str(PACKAGE/'tests'),'-v'],cwd=PACKAGE)
    package_sha=verify_package();a.project=a.project.expanduser().resolve();a.result_dir=a.result_dir.expanduser().resolve()
    a.r12_root=(a.r12_root or a.project/'derived/replication/r12_r13_followups_v100_PRIVATE'/R12_PREFIX).expanduser().resolve()
    require(a.project.is_dir(),'Project drive is not mounted: '+str(a.project))
    require(1<=a.workers<=10 and 10.5<=a.memory_gb<=11,'Use 1–10 workers and 10.5–11 GiB')
    require(a.r12_root.is_dir(),'Completed R12 cache is missing: '+str(a.r12_root))
    config=dict(version=VERSION,definition=DEFINITION,package_manifest_sha256=package_sha,project=str(a.project),
                r12_root=str(a.r12_root),r9_root=str(a.r9_root) if a.r9_root else None,
                comparison_root=str(a.comparison_root) if a.comparison_root else None)
    conf=key(config);run=a.project/'derived/replication/alltime_iv_primary_v100_PRIVATE'/conf[:12]
    require(not run.is_relative_to(a.r12_root),'New outputs cannot be written into R12')
    run.mkdir(parents=True,exist_ok=True);(run/'PRIVATE').mkdir(exist_ok=True);(run/'report').mkdir(exist_ok=True);a.result_dir.mkdir(parents=True,exist_ok=True)
    frozen.u.no_network()
    if a._stage:
        with heartbeat('Stage '+a._stage):execute_stage(a,run,conf)
        return 0
    require(shutil.disk_usage(run).free>=40*2**30,'Need at least 40 GiB free for new wider-frame features and temporary spill')
    import importlib.metadata
    versions={m:importlib.metadata.version(m) for m in ('numpy','pandas','pyarrow','duckdb','scipy','python-chess','matplotlib')}
    if (run/'config.json').exists():require(load(run/'config.json')==config,'Run configuration changed')
    else:save(run/'config.json',config)
    save(run/'report/runtime.json',dict(python=platform.python_version(),platform=platform.platform(),packages=versions,
         workers_cap=a.workers,memory_planning_budget_GiB=a.memory_gb,one_BLAS_thread=True,OS_memory_limit_enforced=False))
    if a.preflight_only:
        import primary_inputs
        with (run/'RUN.lock').open('a+') as lock:
            fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            primary_inputs.bind(a,run,conf)
        log('PREFLIGHT_OK: completed R12, R9, and available R9b caches authenticated; no production model fitted.');return 0
    from primary_report import export
    statepath=run/'PRIVATE/STATE.json';state=load(statepath) if statepath.exists() else {}
    progress=0;stages=('primary',) if a.only_primary else STAGES
    with (run/'RUN.lock').open('a+') as lock:
        try:fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('This configuration is already running; do not start a second writer')
        save(a.result_dir/'ALLTIME_IV_PRIMARY_LATEST_PRIVATE.json',dict(root=str(run),configuration_sha256=conf))
        log('All-time-five primary migration starts. Planning estimate 6–12 hours for all stages; cached reruns can be shorter. No API calls or new engine evaluations.')
        for stage in stages:
            # Always invoke the stage: its receipts verify dependencies before reuse.
            state[stage]=dict(status='RUNNING');save(statepath,state)
            log('Starting '+stage)
            with (run/'run.log').open('a',buffering=1) as output:
                output.write(time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())+' STAGE '+stage+'\n')
                child=subprocess.Popen([sys.executable,str(PACKAGE/'run_primary.py'),*sys.argv[1:],'--_stage',stage],
                     stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1,start_new_session=True)
                try:
                    for line in child.stdout:print(line,end='',flush=True);output.write(line)
                    code=child.wait()
                except KeyboardInterrupt:
                    os.killpg(child.pid,signal.SIGTERM)
                    try:child.wait(timeout=20)
                    except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
                    state[stage]=dict(status='INTERRUPTED');save(statepath,state);export(a,run,conf,state,progress);raise
            state[stage]=dict(status='COMPLETE' if code==0 else 'FAILED',exit_code=code);save(statepath,state)
            if code:
                export(a,run,conf,state,progress);log('STOPPED. Return the latest checkpoint and log; completed work is preserved.');return code
            progress={'primary':25,'wider':50,'scores':60,'features':75,'diagnostics':90,'comparisons':100}[stage]
            export(a,run,conf,state,progress)
        if a.only_primary:log('Primary checkpoint complete. Run the same command without --only-primary to complete receipt diagnostics.')
        else:log('FINISHED: return ALLTIME_IV_PRIMARY_'+conf[:12]+'_100.zip, its .sha256, and the log. See migration_status.csv for separately retained comparison/Patron populations.')
    return 0

if __name__=='__main__':
    try:sys.exit(main())
    except Exception as e:log(type(e).__name__+': '+str(e));traceback.print_exc();sys.exit(1)
