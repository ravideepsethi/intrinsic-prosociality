#!/usr/bin/env python3
"""Read-only structural comparisons for the certified pool/nonadjacent panel."""
from __future__ import annotations
import argparse,fcntl,json,os,platform,shutil,sys,traceback
from pathlib import Path
import duckdb,numpy as np,pandas as pd,pyarrow,scipy,numba
from source import pool_wave1_common as authority
from io_utils import *
from prepare import prepare,source_view,encode,subset,VALID
from model import CORE
from analysis import run_models,run_bootstrap,run_recovery
from diagnostics import support_diagnostics

PKG=Path(__file__).resolve().parent


def hashes():
    path=PKG/'PACKAGE_MANIFEST.sha256'
    require(path.is_file(),'Package manifest missing')
    code={}
    for line in path.read_text().splitlines():
        h,n=line.split('  ',1)
        require(digest(PKG/n)==h,'Package hash mismatch: '+n)
        code[n]=h
    return code


def read_results(report,args,status):
    lines=['# Chooser benchmark: read the restrictions, not only the winning score','',
      'SYNTHETIC SOFTWARE CHECK — NOT EMPIRICAL EVIDENCE' if args.fixture else 'Certified pool/nonadjacent panel; active resolutions only.',
      '', '## Primary results',
      '- comparisons.csv: positive mean log-score gain favors candidate; SE/p/Holm columns are conditional on the population fits.',
      '- refit_bootstrap_summary.csv: population-refit uncertainty; intervals withheld below 100 completed paired refits.',
      '- complexity_selection.csv and optimizer_attempts.csv: first-year chronological selection, convergence, and numerical boundaries.',
      '- types.csv: cost coefficients and normalized multipliers; a zero multiplier alone is not a flat type.',
      '- state_surfaces.csv and surface_singular_values.csv: the common-index restriction is tested by type_cells versus free_index.',
      '- scores.csv, calibration.csv, comparisons_by_state.csv: opportunity/equal-account performance and exploratory subgroup diagnostics.',
      '- recovery_results.csv: full-design simulated event counts, label-matched parameter errors and predictive comparisons.',
      '- perception_*: separately matched numeric/nonmate/nonboundary sample; exact normal-bin integration, not a proof of perception.',
      '', '## Interpretation limits',
      '- Baseline index is freely estimated multiplicative separability. No external board calibration is invented.',
      '- Optional calibrated factors are used only when supplied with training provenance; their sampling uncertainty is not resampled.',
      '- Zero/near-zero costs leave normalized cost heterogeneity weakly or wholly unidentified.',
      '- State coefficients and cost responses are conditional associations, not causal effects or identified moral motives.',
      '- Selecting two varying coefficients does not establish two independent psychological traits; finite support does not prove bimodality.',
      '- Perception counterfactual decomposition is interpretation under the model, not independent evidence for Jensen or perception.',
      '- Refit bootstrap freezes selected complexity/support/control scaling; does not correct prior specification search or all calendar dependence.',
      '- These new comparisons do not reuse the previous HMM scores: the static-vs-switching test with identical new emissions is NOT implemented in this release.',
      '- Verified disconnection cause, latency, and a separately identified reciprocity effect remain unavailable and are not manufactured.',
      '', '## Stage status']
    lines += [f'- {k}: {v}' for k,v in sorted(status.items())]
    atomic_text(report/'READ_RESULTS.md','\n'.join(lines)+'\n')


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    ap.add_argument('--sample-root',type=Path)
    ap.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    ap.add_argument('--workers',type=int,default=4);ap.add_argument('--hash-workers',type=int,default=2)
    ap.add_argument('--memory',default='6GB')
    ap.add_argument('--dev-accounts',type=int,default=25000);ap.add_argument('--eval-accounts',type=int,default=50000)
    ap.add_argument('--seed',type=int,default=20260923)
    ap.add_argument('--support-grid',default='1,2,3');ap.add_argument('--ridge-grid',default='0.000001,0.0001')
    ap.add_argument('--starts',type=int,default=4);ap.add_argument('--refit-starts',type=int,default=3)
    ap.add_argument('--maxiter',type=int,default=800);ap.add_argument('--bound',type=float,default=12.)
    ap.add_argument('--timing-guard-seconds',type=float,default=300)
    ap.add_argument('--min-cell-count',type=int,default=10)
    ap.add_argument('--bootstrap-refits',type=int,default=120);ap.add_argument('--recovery-reps',type=int,default=20)
    ap.add_argument('--models',default=','.join(s.name for s in CORE))
    ap.add_argument('--stages',default='audit,fit')
    ap.add_argument('--board-calibration',type=Path)
    ap.add_argument('--fixture',action='store_true',help='Synthetic software check; never a production result')
    args=ap.parse_args(argv)
    args.support_grid=sorted(set(map(int,args.support_grid.split(','))))
    args.ridge_grid=sorted(set(map(float,args.ridge_grid.split(','))))
    args.models=args.models.split(',');args.stages=args.stages.split(',')
    allowed={'audit','fit','recovery','bootstrap','perception','perception-recovery','perception-bootstrap'}
    require(set(args.stages)<=allowed,'Unknown stage')
    require(set(args.models)<={s.name for s in CORE},'Unknown model')
    require(1<=args.workers<=10 and 1<=args.hash_workers<=10,'Workers must be between 1 and 10')
    require(args.dev_accounts>=20 and args.eval_accounts>=20,'Need at least 20 accounts per cohort')
    require(args.starts>=2 and args.refit_starts>=2 and args.maxiter>=50,'Need multiple starts and maxiter>=50')
    require(args.bootstrap_refits>=0 and args.recovery_reps>=0,'Simulation budgets must be nonnegative')
    require(args.bound>=4 and args.min_cell_count>=1 and args.timing_guard_seconds>=0,'Invalid bounds/support/guard')
    require(all(1<=j<=6 for j in args.support_grid) and all(r>=0 for r in args.ridge_grid),'Invalid model grid')
    code=hashes()
    dependencies={m.__name__:m.__version__ for m in [np,pd,duckdb,pyarrow,scipy,numba]}
    settings={k:v for k,v in vars(args).items() if k not in ['workers','hash_workers','memory','project_root',
      'sample_root','desktop','stages','bootstrap_refits','recovery_reps','board_calibration']}
    calibration=None
    if args.board_calibration:
        calibration=json_read(args.board_calibration)
        r=np.asarray(calibration['board_factor'],float)
        require(r.shape==(5,) and np.all(np.isfinite(r)) and np.all(r>=0) and r[2]>r[0], 'Invalid board calibration')
        require(calibration['training_end_ms']<VALID and calibration['evaluation_accounts_excluded'] is True,
                'Calibration must precede validation and exclude evaluation accounts')
        require(bool(calibration.get('source_sha256')) and bool(calibration.get('description')),'Calibration provenance required')
    fingerprint='SYNTHETIC' if args.fixture else authority.verify_report_package()[0]['sample_fingerprint']
    config=dict(version='1.0.0',code=code,settings=settings,dependencies=dependencies,
                calibration=calibration,sample_fingerprint=fingerprint)
    identity=binding(config);runid=identity[:16]+('_fixture' if args.fixture else '')
    project=args.project_root.expanduser().resolve();desktop=args.desktop.expanduser().resolve()
    require(project.is_dir(),'Project drive is unavailable: '+str(project))
    require(args.fixture or shutil.disk_usage(project).free>15*1024**3,'Need at least 15 GiB free for private caches and temporary spill')
    root=project/'output'/('pool_chooser_benchmark_v100_'+runid)
    private=root/'PRIVATE';report=root/'report'
    private.mkdir(parents=True,exist_ok=True);report.mkdir(parents=True,exist_ok=True)
    lock=(root/'RUN.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('This exact analysis configuration is already running')
    status=json_read(report/'RUN_STATUS.json') if (report/'RUN_STATUS.json').exists() else {}
    json_write(private/'CONFIG.json',dict(config=config,argv=sys.argv,python=sys.executable,platform=platform.platform()))
    db=None
    try:
        design=private/'design';design.mkdir(exist_ok=True)
        if args.fixture:
            from fixture import fixture
            frame=fixture(args.dev_accounts,args.eval_accounts)
            json_write(report/'LINEAGE.json',dict(status='SYNTHETIC_FIXTURE',config=config))
        else:
            sample=args.sample_root or project/'derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE'
            with heartbeat('Input authentication'):
                auth=authority.authenticate_sample(sample,verify_hashes=True,hash_workers=args.hash_workers)
            json_write(report/'LINEAGE.json',dict(sample_fingerprint=auth['fingerprint'],code=code,
              settings=settings,dependencies=dependencies,
              months=[dict(month=r['month'],rows=r['rows'],sha256=r['actual_sha256']) for r in auth['month_records']]))
            db=duckdb.connect();db.execute(f'SET threads={args.workers}')
            db.execute('SET memory_limit='+qs(args.memory));db.execute('SET temp_directory='+qs(private/'spill'))
            source_view(db,[r['path'] for r in auth['month_records']])
            with heartbeat('Disjoint chronological cohort preparation'):
                path=prepare(db,private,report,args)
            db.close();db=None
            frame=pd.read_parquet(path) if not (design/'READY.json').exists() else None
        if not (design/'READY.json').exists():
            arrays,meta=encode(frame,args.min_cell_count)
            train=subset(arrays['development'],arrays['development']['period']<2)
            meta['reference_group_weights']=(np.bincount(train['group'],minlength=4)/len(train['group'])).tolist()
            if calibration:meta['board_factor']=calibration['board_factor']
            for name,d in arrays.items():
                out=design/(name+'.npz');tmp=design/(name+'.partial.npz')
                np.savez_compressed(tmp,**d);os.replace(tmp,out)
            json_write(design/'DESIGN.json',meta)
            json_write(design/'READY.json',dict(identity=identity,
              files={p.name:digest(p) for p in [design/'DESIGN.json',*design.glob('*.npz')]}))
        frame=None
        ready=json_read(design/'READY.json');require(ready['identity']==identity,'Design cache identity mismatch')
        for n,h in ready['files'].items():require(digest(design/n)==h,'Private design cache changed: '+n)
        meta=json_read(design/'DESIGN.json');json_write(report/'MODEL_DESIGN.json',meta)
        dev=dict(np.load(design/'development.npz',allow_pickle=False))
        support_diagnostics(dev,meta,report)
        json_write(report/'CALIBRATION_STATUS.json',dict(status='USER_SUPPLIED_TRAINING_CALIBRATION' if calibration else 'NOT_RUN_NO_EXTERNAL_CALIBRATION',
          default='Freely estimated board factor within multiplicative separability',provenance=calibration))
        status['audit']='COMPLETE_SYNTHETIC' if args.fixture else 'COMPLETE_AUTHENTICATED'
        operations={'fit':lambda:run_models(private,report,args),
          'recovery':lambda:run_recovery(private,report,args),
          'bootstrap':lambda:run_bootstrap(private,report,args),
          'perception':lambda:run_models(private,report,args,'perception'),
          'perception-recovery':lambda:run_recovery(private,report,args,'perception'),
          'perception-bootstrap':lambda:run_bootstrap(private,report,args,'perception')}
        for stage in args.stages:
            if stage=='audit':continue
            if stage in ['recovery','bootstrap']:
                require((private/'core'/'SELECTED_FITS.json').exists(),'Run --stages fit before '+stage)
            if stage in ['perception-recovery','perception-bootstrap']:
                require((private/'perception'/'SELECTED_FITS.json').exists(),'Run --stages perception first')
            status[stage]='RUNNING';json_write(report/'RUN_STATUS.json',status)
            with heartbeat(stage):operations[stage]()
            status[stage]='COMPUTED_REQUIRES_DIAGNOSTIC_REVIEW'
            json_write(report/'RUN_STATUS.json',status)
            read_results(report,args,status);export_report(report,desktop,runid)
        status['last_run']='COMPUTATION_OK'
        json_write(report/'RUN_STATUS.json',status);read_results(report,args,status)
        export_report(report,desktop,runid)
        log('COMPUTATION_OK — inspect convergence, support and recovery before interpreting estimates')
        return 0
    except Exception as exc:
        json_write(private/'ERROR.json',dict(error=repr(exc),traceback=traceback.format_exc()))
        status['last_run']='FAILED: '+type(exc).__name__
        json_write(report/'RUN_STATUS.json',status);read_results(report,args,status)
        export_report(report,desktop,runid);log('STOPPED: '+str(exc));return 2
    finally:
        if db is not None:db.close()
        fcntl.flock(lock,fcntl.LOCK_UN);lock.close()


if __name__=='__main__':sys.exit(main())
