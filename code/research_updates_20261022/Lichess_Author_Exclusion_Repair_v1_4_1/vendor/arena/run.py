#!/usr/bin/env python3
"""Run the complete first arena replication wave against the user's XT_Pro data."""
from __future__ import annotations

import argparse
import fcntl
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import traceback
import zipfile

from common import *

STAGES=['suppression','structural','persistence','support','krd','nonparametric','controlled']
PREFIXES={'suppression':['suppression','descriptive'],'structural':['arena_structural'],
 'persistence':['persistence'],'support':['support'],'krd':['rating_gap_krd'],
 'nonparametric':['rating_gap_nonparametric'],'controlled':['controlled_payoff']}

def stage_files(run,name):
    result=[]
    for prefix in PREFIXES[name]:
        base=Path(run)/'public'/prefix
        for r in manifest(base):
            result.append({**r,'path':prefix+'/'+r['path']})
    return result

def stage_done(run,name,contract):
    path=Path(run)/'private/stages'/(name+'.json')
    if not path.exists():return False
    saved=read_json(path)
    require(saved['contract']==contract,'Stage result belongs to different input bytes')
    for r in saved['files']:
        p=Path(run)/'public'/r['path']
        require(p.is_file() and p.stat().st_size==r['bytes'] and sha(p)==r['sha256'],
                'Completed stage result changed: '+r['path'])
    return True

def do_stage(name,args):
    from analysis import suppression, structural, persistence
    from support import run_support
    from legacy_structural import krd, nonparametric, controlled
    b=read_json(args.run_root/'private/BUILD.json')
    require(b['status']=='ARENA_INPUTS_BUILT_AND_CHECKED','Stage requires the authenticated production arena build')
    verify_package()
    if stage_done(args.run_root,name,b['contract']):
        log('Verified completed stage '+name);return
    if name=='support':run_support(args.run_root,args.project,args.memory,args.threads)
    elif name=='nonparametric':nonparametric(args.run_root,args.memory,args.threads,args.workers)
    else:{'suppression':suppression,'structural':structural,'persistence':persistence,
          'krd':krd,'controlled':controlled}[name](args.run_root,args.memory,args.threads)
    files=stage_files(args.run_root,name)
    require(files,'Stage produced no public output: '+name)
    json_write(args.run_root/'private/stages'/(name+'.json'),
               {'status':'COMPLETE','contract':b['contract'],'files':files})

def package_report(run,report_dir,status,stages,elapsed,error=None):
    public=run/'public';public.mkdir(parents=True,exist_ok=True)
    json_write(public/'RUN_STATUS.json',{'status':status,'version':VERSION,'stages':stages,
      'elapsed_seconds':elapsed,'error':error,'environment':versions(),
      'production_data_available_to_package_author':False,'new_game_downloads':0,'stockfish_recomputed':False,
      'main_pool_sample_changed':False,'causal_identification_certified':False,
      'limitations':['This wave estimates structural comparisons and persistence. Receipt/IV, episode randomization, and Patron are support checks only.',
                    'Observed adjacency is the same screen used for the pool main sample; literal end-to-start rematch timing is not certified.',
                    'Tournament participation and active resolution are selected; adjusted arena effects remain observational.',
                    'Lichess arena points/streaks and the historical claim/draw interface are not audited by this package.']})
    (public/'READ_FIRST.md').write_text('''# Arena replication report

Read RUN_STATUS.json first. COMPLETE means every stage in this first wave completed;
it does not mean every dynamics/IV/Patron result in the paper was re-estimated.

validation/source_month_timezone.json compares inherited-timezone and UTC month
assignments. validation/source_validation.json records the unchanged original
validator's result, including failure-condition counts if validation fails.
validation/opportunities_YYYY-MM.json records every monthly opportunity check.
The certified sample retains missing disconnected clocks. Complete-case model
restrictions are applied separately and reported in covariate coverage tables.

SAMPLE_COUNTS.json contains both unscreened and screened source counts.
suppression/competitive_full.json is the primary arena–pool comparison, with
chooser, exact time-control × month, board × stage, own-rating-bin and rating-gap-bin
fixed effects plus both clocks, rating deviations, and the win premium.
competitive_within_player_tc_month.json restricts to cells where the same chooser
played both formats in the same exact time control and month.
All ladder estimates within a region share complete-case, dual-format rows.
Standardized arena/pool rates are additive-LPM point estimates; their ratio has
no confidence interval here. The reported clustered interval is for the difference.

arena_structural/ and the rating-gap/controlled-payoff folders contain arena-only
estimates. The broad raw merit/stage tables are in descriptive/. The inherited
gap curves use the original 50-Elo bins, K controls, bands and robustness families.
The separate five-bin merit tables preserve the paper's exact -100/+100 boundaries.
Rating payoff excludes tournament-point and streak costs.

persistence/ uses fixed calendar halves and displays several minimum-opportunity
thresholds. support/ reports episode, receipt-transition and Patron support.
Receipt-transition timing uses lastMoveAt as a proxy; it is not a certified A1 risk set.
The next fair opportunity is selected across all sources before classifying its format.
No next-pool opportunity is skipped to manufacture an arena-to-arena transition.

No manuscript numbers or figures should be replaced until this report is reviewed.
Missing, unsupported, or failed models are not zero effects.
''')
    json_write(public/'MANIFEST.json',{'files':manifest(public)})
    report_dir.mkdir(parents=True,exist_ok=True)
    name='ARENA_REPLICATION_RESULTS_v102_'+run.name+'.zip'
    archive=report_dir/name
    temp=archive.with_name(archive.name+'.tmp')
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(public.rglob('*')):
            if p.is_file():z.write(p,p.relative_to(public))
    os.replace(temp,archive)
    side=archive.with_name(archive.name+'.sha256')
    side.write_text(sha(archive)+'  '+archive.name+'\n')
    log('Report: '+str(archive));log('Checksum: '+str(side))
    return archive

def parse_args():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    parser.add_argument('--report-dir',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    parser.add_argument('--run-root',type=Path)
    parser.add_argument('--workers',type=int,default=10)
    parser.add_argument('--threads',type=int,default=10)
    parser.add_argument('--memory',default='6GB')
    parser.add_argument('--fresh',action='store_true')
    parser.add_argument('--self-test',action='store_true')
    parser.add_argument('--stage',choices=STAGES,help=argparse.SUPPRESS)
    return parser.parse_args()

def main():
    args=parse_args()
    if args.self_test:
        import tests
        return tests.run()
    require(1<=args.workers<=10 and 1<=args.threads<=10,'Workers and threads must be 1–10')
    if args.stage:
        require(args.run_root is not None,'Internal stage needs its run root')
        do_stage(args.stage,args);return 0
    package_sha=verify_package()
    args.project=args.project.expanduser().resolve()
    require(args.project.is_dir(),'XT_Pro project is not mounted: '+str(args.project))
    base=args.project/'output/arena_replication_v102';base.mkdir(parents=True,exist_ok=True)
    lockfile=(base/'RUNNING.lock').open('a+')
    try:fcntl.flock(lockfile,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('Another arena replication is running')
    pointer=base/'ACTIVE_RUN.json'
    if args.run_root is None:
        if pointer.exists() and not args.fresh:
            saved=read_json(pointer)
            require(saved['package_sha256']==package_sha,'Saved run uses another package; use --fresh to preserve it and start anew')
            args.run_root=Path(saved['run_root'])
        else:args.run_root=base/(time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'_'+str(os.getpid()))
    args.run_root=args.run_root.resolve()
    require(args.run_root.is_relative_to(base),'Run root must be under output/arena_replication_v102')
    args.run_root.mkdir(parents=True,exist_ok=True)
    json_write(pointer,{'package_sha256':package_sha,'run_root':str(args.run_root)})
    log('Arena replication '+VERSION+'; run='+str(args.run_root))
    log('Planning estimate: 1–4 hours on an 18 GB Mac with XT_Pro. Not benchmarked on production data; first-stage timings will refine this.')
    log(f'Ceiling: {args.workers} workers / {args.threads} DuckDB threads; memory-heavy models run sequentially.')
    started=time.time();states={};process=None
    try:
        from build import build
        b=build(args.project,args.run_root,args.workers,args.threads,args.memory)
        for name in STAGES:
            if name=='nonparametric' and states.get('krd')!='COMPLETE':
                states[name]='BLOCKED_BY_KRD';continue
            if stage_done(args.run_root,name,b['contract']):
                states[name]='COMPLETE';log('Reusing verified '+name);continue
            log('START '+name)
            stage_start=time.time()
            cmd=[sys.executable,str(ROOT/'run.py'),'--stage',name,'--run-root',str(args.run_root),
                 '--project',str(args.project),'--workers',str(args.workers),'--threads',str(args.threads),
                 '--memory',args.memory]
            process=subprocess.Popen(cmd,start_new_session=True)
            while process.poll() is None:
                try:process.wait(timeout=30)
                except subprocess.TimeoutExpired:log(f'{name} running; {int(time.time()-stage_start)} seconds')
            states[name]='COMPLETE' if process.returncode==0 else 'FAILED'
            json_write(args.run_root/'public/STAGE_PROGRESS.json',states)
            log(f'{name}: {states[name]}; elapsed {time.time()-stage_start:.1f}s')
        auth=load_source('source/auth/build_main_sample.py','arena_final_input_check')
        auth.unchanged(read_json(args.run_root/'private/INPUT_SIGNATURES.json'))
        status='ARENA_REPLICATION_WAVE1_COMPLETE' if all(x=='COMPLETE' for x in states.values()) else 'ARENA_REPLICATION_WAVE1_PARTIAL'
        package_report(args.run_root,args.report_dir,status,states,time.time()-started)
        if status.endswith('_COMPLETE'):
            json_write(args.run_root/'_SUCCESS.json',{'status':status,'input_contract':b['contract'],'stages':states})
            log(status);return 0
        log(status+' — upload the report and log for diagnosis. Completed stages are reusable.');return 1
    except BaseException as exc:
        if process is not None and process.poll() is None:
            os.killpg(process.pid,signal.SIGTERM)
            try:process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGKILL);process.wait()
        traceback.print_exc()
        package_report(args.run_root,args.report_dir,'ARENA_REPLICATION_FAILED',states,time.time()-started,
                       type(exc).__name__+': '+str(exc))
        return 1
    finally:
        fcntl.flock(lockfile,fcntl.LOCK_UN);lockfile.close()

if __name__=='__main__':
    raise SystemExit(main())
