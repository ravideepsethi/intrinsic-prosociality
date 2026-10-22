#!/usr/bin/env python3
"""Resume from the verified v100 design; never change the parent run."""
import bootstrap_path
import argparse,fcntl,os,platform,sys,traceback,zipfile
from pathlib import Path
import numpy as np,pandas as pd,scipy,numba,duckdb,pyarrow
from io_utils import *
from parent_audit import inspect_parent,import_suite,audit_boundaries,manifest
from engine import CHALLENGE,SWITCHING
import followup_analysis as analysis
from followup_diagnostics import summaries

PKG=Path(__file__).resolve().parent


def export(report,desktop,runid):
    desktop.mkdir(parents=True,exist_ok=True)
    forbidden={'chooser','chooser_user_id','recipient_id','opponent_id','game_id','username','account_id'}
    for p in report.rglob('*.csv'):
        if p.stat().st_size:require(not(set(p.read_text().splitlines()[0].split(','))&forbidden),'Identifier in export: '+str(p))
    atomic_text(report/'REPORT_MANIFEST.sha256',''.join(digest(p)+'  '+str(p.relative_to(report))+'\n'
      for p in sorted(report.rglob('*')) if p.is_file() and p.name!='REPORT_MANIFEST.sha256'))
    out=desktop/f'POOL_CHOOSER_FOLLOWUP_RESULTS_v111_{runid}.zip';part=out.with_suffix('.zip.partial')
    with zipfile.ZipFile(part,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(report.rglob('*')):
            if p.is_file():z.write(p,'report/'+str(p.relative_to(report)))
    os.replace(part,out);atomic_text(str(out)+'.sha256',digest(out)+'  '+out.name+'\n')
    log('UPLOAD: '+str(out));log('UPLOAD: '+str(out)+'.sha256')


def readme(report,status,fixture):
    text=['# Follow-up status','',
      'SYNTHETIC SOFTWARE CHECK — NOT EMPIRICAL RESULTS' if fixture else 'Reuses the authenticated v100 account cohorts and chronology.',
      '', 'repair/: independent full-year starts and cross-starts from nested models; complexity fixed.',
      'original/: optional uncorrected parent-fit comparison; use repair/ for primary inference.',
      'challenge/: new index restrictions, reusing repaired expanded-grid model selections.',
      'switching/: matched static, independent-state and Markov-state models.',
      'perception/: optional matched numeric-score sample and fixed-type noise decomposition.',
      '', 'Only files actually computed appear. No inference is implied by a stage completing.',
      'Conditional score SEs hold population estimates fixed. Bootstrap intervals need at least 100 converged paired draws.',
      'Refits freeze model complexity/support/scaling; they do not repair model search, reuse of evaluation data, or calendar dependence.',
      'Worse prediction from a flexible estimator is not a population test accepting its restriction.',
      'Zero estimated cost response does not identify equal rating valuations. No latent state is observed construal.',
      'The switching cache has no receipt variable; transitions are per retained opportunity, with no receipt effect estimated.',
      '', '## Computed stages','']+[f'- {k}: {v}' for k,v in sorted(status.items())]
    atomic_text(report/'READ_RESULTS.md','\n'.join(text)+'\n')


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--parent-run',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness/output/pool_chooser_benchmark_v100_d6c2a5c0637024f1'))
    ap.add_argument('--output-root',type=Path)
    ap.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    ap.add_argument('--stages',default='audit,repair,repair-bootstrap')
    ap.add_argument('--workers',type=int,default=4)
    ap.add_argument('--support-grid',default='1,2,3,4,5,6')
    ap.add_argument('--ridge-grid',default='0.000001,0.0001,0.001,0.01')
    ap.add_argument('--challenge-models',default='board_only,no_stage,no_expected,desert_no_cost')
    ap.add_argument('--switching-models',default=','.join(s.name for s in SWITCHING))
    ap.add_argument('--starts',type=int,default=4);ap.add_argument('--refit-starts',type=int,default=4)
    ap.add_argument('--maxiter',type=int,default=1200);ap.add_argument('--bound',type=float,default=12.)
    ap.add_argument('--seed',type=int,default=20260923)
    ap.add_argument('--bootstrap-refits',type=int,default=120);ap.add_argument('--recovery-reps',type=int,default=20)
    ap.add_argument('--allow-fixture',action='store_true')
    args=ap.parse_args(argv)
    args.support_grid=sorted(set(map(int,args.support_grid.split(','))))
    args.ridge_grid=sorted(set(map(float,args.ridge_grid.split(','))))
    args.challenge_models=args.challenge_models.split(',');args.switching_models=args.switching_models.split(',')
    args.stages=args.stages.split(',')
    allowed={'audit','repair','repair-bootstrap','repair-recovery','original-bootstrap','original-recovery','challenge','challenge-bootstrap','challenge-recovery',
      'switching','switching-bootstrap','switching-recovery','perception','perception-bootstrap','perception-recovery'}
    require(set(args.stages)<=allowed,'Unknown stage')
    require(1<=args.workers<=10,'Workers must be 1..10')
    require(args.starts>=2 and args.refit_starts>=2 and args.maxiter>=50,'Multiple starts and maxiter>=50 required')
    require(args.support_grid and all(1<=j<=6 for j in args.support_grid),'Support grid must lie in 1..6')
    require(args.ridge_grid and all(np.isfinite(r) and r>=0 for r in args.ridge_grid),'Invalid ridge grid')
    require(args.bound>=4 and args.bootstrap_refits>=0 and args.recovery_reps>=0,'Invalid bounds or simulation budget')
    require(set(args.challenge_models)<={s.name for s in CHALLENGE},'Unknown challenge model')
    require(set(args.switching_models)<={s.name for s in SWITCHING},'Unknown switching model')
    code=manifest(PKG,'PACKAGE_MANIFEST.sha256')
    parent_path=args.parent_run.expanduser().resolve()
    require((parent_path/'RUN.lock').is_file(),'Parent run/lock file missing: '+str(parent_path))
    parent_lock=(parent_path/'RUN.lock').open('r')
    try:fcntl.flock(parent_lock,fcntl.LOCK_SH|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('Parent benchmark is currently writing; finish it before importing')
    with heartbeat('Authenticate parent cache and reproduce scores'):
        parent=inspect_parent(parent_path,args.allow_fixture)
    settings={k:v for k,v in vars(args).items() if k not in ['stages','workers','bootstrap_refits','recovery_reps',
      'output_root','desktop','parent_run']}
    deps={m.__name__:m.__version__ for m in [np,pd,scipy,numba,duckdb,pyarrow]}
    config=dict(version='1.1.1',code=code,settings=settings,dependencies=deps,
      parent_identity=parent['ready']['identity'],design=parent['design_sha256'],fits=parent['selected_fits_sha256'])
    identity=binding(config);runid=identity[:16]+('_fixture' if parent['synthetic'] else '')
    outroot=(args.output_root or parent_path.parent).expanduser().resolve()
    root=outroot/('pool_chooser_followup_v111_'+runid);private=root/'PRIVATE';report=root/'report'
    private.mkdir(parents=True,exist_ok=True);report.mkdir(exist_ok=True)
    lock=(root/'RUN.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('This follow-up configuration is already running')
    status=json_read(report/'RUN_STATUS.json') if (report/'RUN_STATUS.json').exists() else {}
    json_write(private/'CONFIG.json',dict(config=config,argv=sys.argv,python=sys.executable,platform=platform.platform()))
    json_write(report/'LINEAGE.json',dict(parent_identity=parent['ready']['identity'],
      parent_sample_fingerprint=parent['config']['sample_fingerprint'],parent_fit_hash=parent['selected_fits_sha256'],
      parent_design_hashes=parent['design_sha256'],code=code,settings=settings,dependencies=deps))
    try:
        audit_boundaries(parent,report);status['audit']='COMPLETE_SYNTHETIC' if parent['synthetic'] else 'COMPLETE_AUTHENTICATED'
        json_write(report/'RUN_STATUS.json',status);readme(report,status,parent['synthetic']);export(report,args.desktop,runid)
        for stage in args.stages:
            if stage=='audit':continue
            suite=stage.split('-')[0];target=private/suite;target.mkdir(exist_ok=True)
            sr=report/suite;sr.mkdir(exist_ok=True);import_suite(parent,target,suite)
            args.models=args.switching_models if suite=='switching' else args.challenge_models
            substage='perception' if suite=='perception' else 'core'
            status[stage]='RUNNING';json_write(report/'RUN_STATUS.json',status)
            with heartbeat(stage):
                if stage=='repair':
                    analysis.run_repair(target,sr,args)
                elif stage in ['challenge','switching','perception']:
                    inherited=None
                    if stage=='challenge':
                        rp=private/'repair'/'core'/'SELECTED_FITS.json'
                        require(rp.is_file(),'Run --stages repair before challenge')
                        inherited=json_read(rp)
                    analysis.run_models(target,sr,args,substage,inherited=inherited)
                else:
                    require((target/substage/'SELECTED_FITS.json').exists(),'Run '+suite+' first')
                    if stage.endswith('-bootstrap'):
                        analysis.run_bootstrap(target,sr,args,substage)
                    else:analysis.run_recovery(target,sr,args,substage)
                    if suite=='original':
                        analysis.initialize(target/'design');dev,ev,meta=analysis.data_for('core')
                        summaries(parent['fits'],ev,meta,sr)
            status[stage]='COMPUTED_REQUIRES_DIAGNOSTIC_REVIEW'
            json_write(report/'RUN_STATUS.json',status);readme(report,status,parent['synthetic']);export(report,args.desktop,runid)
        status['last_run']='COMPUTATION_OK';json_write(report/'RUN_STATUS.json',status)
        readme(report,status,parent['synthetic']);export(report,args.desktop,runid)
        log('COMPUTATION_OK — inspect failures, numerical bounds and recovery before interpretation')
        return 0
    except Exception as exc:
        status['last_run']='FAILED: '+type(exc).__name__
        json_write(private/'ERROR.json',dict(error=repr(exc),traceback=traceback.format_exc()))
        json_write(report/'RUN_STATUS.json',status);readme(report,status,parent['synthetic']);export(report,args.desktop,runid)
        log('STOPPED: '+str(exc));return 2
    finally:
        fcntl.flock(lock,fcntl.LOCK_UN);lock.close()
        fcntl.flock(parent_lock,fcntl.LOCK_UN);parent_lock.close()


if __name__=='__main__':sys.exit(main())
