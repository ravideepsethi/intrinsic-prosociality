#!/usr/bin/env python3
"""Local, read-only analysis launcher. Exports aggregate reports only."""
from __future__ import annotations
import argparse,contextlib,fcntl,json,os,platform,shutil,sys,threading,time,traceback,zipfile
from pathlib import Path
import duckdb,numpy as np,pandas as pd,pyarrow,scipy,numba
from source import pool_wave1_common as authority
from util import *
import prepare_sequences as prep
import model_analysis as models
import auxiliary_tests as aux
import receipt_tests as receipt

PKG=Path(__file__).resolve().parent


@contextlib.contextmanager
def heartbeat(label):
    stop=threading.Event();begin=time.monotonic()
    def worker():
        while not stop.wait(45):log(f'{label}: working, {(time.monotonic()-begin)/60:.1f} min')
    t=threading.Thread(target=worker,daemon=True);t.start()
    try:yield
    finally:stop.set();t.join()


def hashes():
    values={}
    for line in (PKG/'PACKAGE_MANIFEST.sha256').read_text().splitlines():
        h,n=line.split('  ',1);require(sha256_file(PKG/n)==h,'Package checksum mismatch: '+n);values[n]=h
    return values


def package_report(report,desktop,runid):
    # Only the public report directory is exported, never the private caches.
    forbidden=('chooser','recipient_id','opponent_id','game_id','username','row_id')
    for p in report.glob('*.csv'):
        header=p.read_text().splitlines()[0] if p.stat().st_size else ''
        require(not any(name in header.split(',') for name in forbidden),'Private identifier column in public report: '+p.name)
    manifest=[f'{sha256_file(p)}  {p.relative_to(report)}' for p in sorted(report.rglob('*')) if p.is_file() and p.name!='REPORT_MANIFEST.sha256']
    atomic_text(report/'REPORT_MANIFEST.sha256','\n'.join(manifest)+'\n')
    out=desktop/f'POOL_CONSTRUAL_TESTS_RESULTS_v100_{runid}.zip';partial=Path(str(out)+'.partial')
    with zipfile.ZipFile(partial,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(report.rglob('*')):
            if p.is_file():z.write(p,'report/'+str(p.relative_to(report)))
    os.replace(partial,out);atomic_text(Path(str(out)+'.sha256'),sha256_file(out)+'  '+out.name+'\n')
    log('UPLOAD: '+str(out));log('UPLOAD: '+str(out)+'.sha256');return out


def summary(report,status,args):
    text=['# Construal tests: exploratory model comparison','',
      'Input: certified 41,534,331 pool / observed-nonadjacent opportunities, November 2023–October 2025.',
      'A completed computation does not establish a moral recognition mechanism.','',
      '## Read first',
      '1. RUN_STATUS.json, TIMING_AUDIT.json, sequence_support.csv: which analyses and recorded histories are supported?',
      '2. optimizer_attempts.csv and first_year_selection.csv: convergence and chronological complexity selection.',
      '3. primary_comparisons.csv and refit_bootstrap_summary.csv: the main predictive comparisons; positive gain favours the candidate.',
      '4. heldout_scores.csv and heldout_calibration.csv: board, cost, clocks, and first-year-history diagnostics.',
      '5. PLY2_INTERACTION.json and ply2_prior_history.csv: predetermined-history and opportunity-support checks.',
      '6. receipt_IV_estimates.csv and receipt_IV_contrasts.csv: subgroup differences and early/later responses.',
      '7. patron_incremental_gains.csv and LATENCY_FEASIBILITY.json: external prediction and missing measurement.',
      '', '## Interpretation',
      '- Gate versus willingness changes the emission restriction while allowing the same persistent random effects and transitions.',
      '- Gate-cost relaxes only the lower-state rating-payoff/cost coefficients. Unrestricted relaxes all lower-state coefficients.',
      '- The bivariate-normal sensitivity comparator is a specified continuous benchmark, not every possible continuous distribution.',
      '- Evaluation accounts exclude the original 100,000-account pilot. Aggregate evidence elsewhere has already been inspected: this is not preregistration or a claim that every outcome is untouched.',
      '- Every forecast is scored before its outcome updates beliefs. Static comparators update as well.',
      f'- The time variable is an API recording proxy. The {args.timing_guard_seconds}-second separation guard reduces ambiguity but does not validate exact decision times.',
      '- Switching receipt input counts well-separated observed main-panel receipts; it is not all-platform receipt exposure and its coefficient is not causal.',
      '- IV diagnostics retain the reviewed design and its assumptions; group and horizon patterns do not uniquely identify a gate.',
      '- Never-granted means not observed granting in the specified history. A future-self preference or moral state has not been measured.',
      '- The source panel has no verified decision-onset/click timestamps, so latency is not fabricated.',
      '',f'Bootstrap budget: {args.bootstrap_refits} population-refit replications. At least 100 converged draws are required before the package reports percentile intervals.',
      'Conditional score SEs omit population-refit uncertainty. Bootstrap complexity is frozen; it does not cover prior specification search. Account resampling does not capture all possible cross-account/calendar dependence.',
      '', '## Stage status']
    text += [f'- {k}: {v.get("status","UNKNOWN")}' for k,v in status.items()]
    atomic_text(report/'READ_RESULTS.md','\n'.join(text)+'\n')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    ap.add_argument('--sample-root',type=Path)
    ap.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    ap.add_argument('--workers',type=int,default=2);ap.add_argument('--hash-workers',type=int,default=1)
    ap.add_argument('--memory',default='4GB');ap.add_argument('--dev-accounts',type=int,default=20000)
    ap.add_argument('--eval-accounts',type=int,default=50000);ap.add_argument('--seed',type=int,default=20260921)
    ap.add_argument('--support-grid',default='2,3');ap.add_argument('--normal-grid',default='3,5')
    ap.add_argument('--starts',type=int,default=2);ap.add_argument('--maxiter',type=int,default=600)
    ap.add_argument('--ridge',type=float,default=1e-6);ap.add_argument('--timing-guard-seconds',type=int,default=300)
    ap.add_argument('--bootstrap-refits',type=int,default=20)
    ap.add_argument('--recovery-reps',type=int,default=2);ap.add_argument('--recovery-accounts',type=int,default=1500)
    ap.add_argument('--audit-only',action='store_true')
    args=ap.parse_args();args.support_grid=sorted(set(map(int,args.support_grid.split(','))));args.normal_grid=sorted(set(map(int,args.normal_grid.split(','))))
    require(1<=args.workers<=10 and 1<=args.hash_workers<=10,'Workers must be 1–10')
    require(100<=args.dev_accounts<=100000 and args.eval_accounts>=100,'Invalid account caps')
    require(args.starts>=2 and args.maxiter>=20 and args.ridge>=0,'Invalid optimisation settings')
    require(all(2<=j<=7 for j in args.support_grid) and all(3<=j<=11 for j in args.normal_grid),'Invalid support/quadrature grid')
    require(args.bootstrap_refits>=0 and args.recovery_reps>=1 and args.recovery_accounts>=30 and args.timing_guard_seconds>=0,'Invalid simulation or timing settings')
    code=hashes();project=args.project_root.expanduser().resolve();desktop=args.desktop.expanduser().resolve()
    require(project.is_dir(),'Project drive is unavailable: '+str(project))
    require(shutil.disk_usage(project).free>20*1024**3,'Need 20 GiB free for private caches and spill')
    deps={m.__name__:m.__version__ for m in [np,pd,duckdb,pyarrow,scipy,numba]}
    settings={k:v for k,v in vars(args).items() if k not in ['workers','hash_workers','memory','project_root','sample_root','desktop','audit_only']}
    config=dict(version='1.0.0',code=code,settings=settings,dependencies=deps,
        sample_fingerprint=authority.verify_report_package()[0]['sample_fingerprint'])
    identity=binding(config);runid=identity[:16];root=project/'output'/('pool_construal_tests_v100_'+runid)
    private=root/'PRIVATE';report=root/('audit_report' if args.audit_only else 'report')
    private.mkdir(parents=True,exist_ok=True);report.mkdir(parents=True,exist_ok=True);desktop.mkdir(parents=True,exist_ok=True)
    lock=(root/'RUN.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('This exact configuration is already running')
    if (report/'_SUCCESS.json').exists():
        for line in (report/'REPORT_MANIFEST.sha256').read_text().splitlines():
            h,n=line.split('  ',1);require(sha256_file(report/n)==h,'Existing report has changed')
        package_report(report,desktop,runid+('_audit' if args.audit_only else ''));return 0
    atomic_json(private/'CONFIG.json',dict(config=config,argv=sys.argv,python=sys.executable,platform=platform.platform()))
    status={};db=None
    try:
        sample=args.sample_root or project/'derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE'
        with heartbeat('Input authentication'):
            auth=authority.authenticate_sample(sample,verify_hashes=True,hash_workers=args.hash_workers)
        atomic_json(report/'LINEAGE.json',dict(sample_fingerprint=auth['fingerprint'],code_sha256=code,
          months=[dict(month=r['month'],rows=r['rows'],sha256=r['actual_sha256']) for r in auth['month_records']],dependencies=deps,settings=settings))
        db=duckdb.connect();db.execute(f'SET threads={args.workers}');db.execute('SET memory_limit='+qs(args.memory))
        db.execute('SET temp_directory='+qs(private/'spill'));db.execute('SET preserve_insertion_order=false')
        prep.source_view(db,[r['path'] for r in auth['month_records']])
        with heartbeat('Sequence preparation'):
            path,cohort=prep.prepare(db,private,report,identity,args.dev_accounts,args.eval_accounts,args.seed,args.timing_guard_seconds,
              expected=dict(rows=41534331,grants=570091,accounts=3224173))
            prep.ply2_tables(db,report);status['ply2']=aux.ply2_regression(db,report)
        status['prepare']=dict(status='COMPLETE_RECORDED_TIME_SEQUENCES');status['latency']=dict(status='NOT_AVAILABLE_IN_SOURCE_PANEL')
        if not args.audit_only:
            df=pd.read_parquet(path)
            with heartbeat('Recovery checks'):
                rec=models.recovery(df,private,report,identity,args)
                status['recovery']=dict(status='FIXED_DESIGN_RECOVERY_REPORTED',rows=len(rec))
            with heartbeat('Switching and static comparisons'):
                fits,full,path_full=models.select_fit(df,private,report,identity,args)
                ev,d,predictions,details,primary=models.score(df,fits,private,report,identity)
                status['models']=dict(status='COMPLETE' if all(f['converged'] for f in fits.values()) else 'COMPLETE_WITH_OPTIMIZER_WARNINGS',
                  all_selected_converged=all(f['converged'] for f in fits.values()),
                  boundary_models=[k for k,v in fits.items() if v['boundary_parameters']],causal_or_moral_identification=False)
            with heartbeat('Account refit bootstrap'):
                boot=models.bootstrap_refits(full,path_full,ev,d,fits,predictions,private,report,identity,args)
                status['bootstrap']=dict(status='REFITS_REPORTED' if args.bootstrap_refits else 'NOT_RUN',replications=args.bootstrap_refits)
            # Optional inputs do not prevent supported main-panel tests from finishing.
            for name in ['receipt','patron']:
                try:
                    with heartbeat(name):
                        if name=='receipt':status[name]=receipt.run(db,receipt.resolve_iv(project),private,report,identity,aux.resolve_profiles(project))
                        else:status[name]=aux.patron(db,aux.resolve_profiles(project),df,fits,private,report)
                except Exception as exc:
                    atomic_json(private/(name+'_ERROR.json'),dict(error=repr(exc),traceback=traceback.format_exc()))
                    status[name]=dict(status='FAILED_REVIEW_PRIVATE_ERROR_LOG',error_type=type(exc).__name__)
                    log(f'{name} did not complete: {exc}')
        failed=any(s['status'].startswith('FAILED') for s in status.values())
        atomic_json(report/'RUN_STATUS.json',status);summary(report,status,args)
        if not failed:atomic_json(report/'_SUCCESS.json',dict(status='AUDIT_COMPLETE' if args.audit_only else 'COMPUTATION_COMPLETE',identity=identity,model_identification_certified=False,stages=status))
        package_report(report,desktop,runid+('_audit' if args.audit_only else ''))
        return 2 if failed else 0
    except Exception as exc:
        atomic_json(private/'ERROR.json',dict(error=repr(exc),traceback=traceback.format_exc()))
        status['run']=dict(status='FAILED_REVIEW_PRIVATE_ERROR_LOG',error_type=type(exc).__name__)
        atomic_json(report/'RUN_STATUS.json',status);summary(report,status,args)
        package_report(report,desktop,runid+('_audit' if args.audit_only else ''))
        log('STOPPED: '+str(exc));return 2
    finally:
        if db is not None:db.close()
        fcntl.flock(lock,fcntl.LOCK_UN);lock.close()


if __name__=='__main__':sys.exit(main())
