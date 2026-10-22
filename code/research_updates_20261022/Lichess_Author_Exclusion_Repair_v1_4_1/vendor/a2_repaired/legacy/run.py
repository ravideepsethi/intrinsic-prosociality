#!/usr/bin/env python3
from __future__ import annotations
import os
for k in ['OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS']:os.environ[k]='1'
import argparse, fcntl, importlib.metadata, platform, shutil, sys, traceback
from common import *
import prepare,network,tenure,trajectory

def main():
    p=argparse.ArgumentParser(description='Frozen probability-sample tenure and final-ply responsibility checks')
    p.add_argument('--project',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--sample-root',type=Path);p.add_argument('--output',type=Path)
    p.add_argument('--phase',choices=['prepare','tenure','responsibility','all'],default='all')
    p.add_argument('--tenure-accounts',type=int,default=100000);p.add_argument('--responsibility-accounts',type=int,default=20000)
    p.add_argument('--seed',type=int,default=2026092301);p.add_argument('--threads',type=int,default=8)
    p.add_argument('--workers',type=int,default=10);p.add_argument('--memory',default='6GB')
    p.add_argument('--stockfish',type=Path);p.add_argument('--fetch-profiles',action='store_true');p.add_argument('--fetch-games',action='store_true')
    p.add_argument('--no-reuse-a1',dest='reuse_a1',action='store_false',default=True)
    args=p.parse_args();require(1<=args.workers<=10 and 1<=args.threads<=10,'Use 1–10 threads/workers')
    require(1<=args.responsibility_accounts<=args.tenure_accounts<=3224173,'Invalid sample sizes')
    project=args.project.expanduser().resolve();require(project.is_dir(),'Project drive is not mounted: '+str(project))
    package=read(ROOT/'PACKAGE_HASHES.json')
    for name,digest in package.items():require(sha(ROOT/name)==digest,'Package file changed: '+name)
    ids=dict(version=VERSION,package=signature(package),seed=args.seed,tenure_accounts=args.tenure_accounts,
      responsibility_accounts=args.responsibility_accounts,sample=read(ROOT/'authority/SAMPLE_AUTHORITY.json')['sample_fingerprint'])
    key=signature(ids)
    run=(args.output or project/'output/tenure_responsibility_v100'/key[:16]).expanduser().resolve()
    run.mkdir(parents=True,exist_ok=True);(run/'PRIVATE').mkdir(exist_ok=True);(run/'report').mkdir(exist_ok=True)
    lock=open(run/'RUN.lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    api_lock=None
    if args.fetch_profiles or args.fetch_games:
        # Shared by all invocations of this package. Other existing API clients cannot be locked here.
        api_lock=open(project/'output/TENURE_RESPONSIBILITY_API.lock','a');fcntl.flock(api_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if (run/'IDENTITY.json').exists():require(read(run/'IDENTITY.json')['key']==key,'Output has another identity; choose a new output directory')
    else:dump(run/'IDENTITY.json',dict(key=key,inputs=ids))
    (run/'report/RUN_INCOMPLETE.json').unlink(missing_ok=True)
    shutil.copyfile(ROOT/'METHODS.md',run/'report/METHODS.md')
    dump(run/'report/ENVIRONMENT.json',dict(python=sys.version,platform=platform.platform(),
      packages={s:importlib.metadata.version(s) for s in ['duckdb','pyarrow','numpy','scipy','python-chess','requests']},
      threads=args.threads,engine_workers=args.workers,memory=args.memory,argv_without_secrets=sys.argv))
    db=connect(run,args.threads,args.memory)
    try:
        with heartbeat('Loading profile cache'):prepare.cached_profiles(db,project,run)
        prepare.prepare(db,project,run,args,key)
        if args.phase=='prepare':
            package_report(run,'PREPARE');log('PREPARE_OK — frozen samples and cost plan ready');return
        with heartbeat('Completing creation-date coverage'):network.profiles(db,run,args,key)
        prepare.attach_age(db)
        if args.phase in ['tenure','all']:
            tenure.run_tenure(db,run);package_report(run,'TENURE');log('TENURE_READY — this report can be reviewed while the engine runs')
        if args.phase in ['responsibility','all']:
            trajectory.build(db,project,run,args,key);trajectory.analyze(db,run,args);package_report(run,'COMPLETE')
        log('TENURE_RESPONSIBILITY_OK '+str(run))
    except Exception as e:
        # Paths/tracebacks and raw diagnostics stay private.
        dump(run/'PRIVATE/ERROR.json',dict(error=str(e),traceback=traceback.format_exc()))
        dump(run/'report/RUN_INCOMPLETE.json',dict(status='INCOMPLETE',phase=args.phase,action='Inspect the terminal error and private ERROR.json; completed checkpoints are retained'))
        package_report(run,'PARTIAL');raise
    finally:
        db.close();lock.close()
        if api_lock:api_lock.close()

if __name__=='__main__':main()
