#!/usr/bin/env python3
"""Resume verified v1.0.0 histories; write a separate follow-up run and aggregate ZIP."""
from __future__ import annotations
import argparse,concurrent.futures as cf,fcntl,io,json,multiprocessing as mp,os,platform,shutil,sys,traceback,zipfile
from pathlib import Path
import duckdb,numpy as np,pandas as pd,pyarrow,scipy,numba
from util import *
from features import design,subset
from source import pool_wave1_common as authority
from run_construal import heartbeat
import model_analysis as legacy
import followup_models as models
import opportunity_followup as opportunities
import prepare_sequences as prep

PKG=Path(__file__).resolve().parent
PRIOR_ID='3035352b8b33d41dbed973d795454d85c7683494ac98af2987d0b59ceec0ff66'
PRIOR_SHA='036420ec7734858b1bbbf46a632738464e7a6398127ed7f53ad2b0982e8c5c33'
STAGES=('models','opportunities','bootstrap','recovery')


def hashes():
    out={}
    for line in (PKG/'PACKAGE_MANIFEST.sha256').read_text().splitlines():
        digest,name=line.split('  ',1)
        require(sha256_file(PKG/name)==digest,'Package checksum mismatch: '+name);out[name]=digest
    return out


def prior_reports(base):
    path=PKG/'evidence/prior_results.zip';require(sha256_file(path)==PRIOR_SHA,'Embedded prior result checksum changed')
    with zipfile.ZipFile(path) as z:
        manifest=z.read('report/REPORT_MANIFEST.sha256').decode();reports={}
        for line in manifest.splitlines():
            digest,name=line.split('  ',1);raw=z.read('report/'+name)
            require(__import__('hashlib').sha256(raw).hexdigest()==digest,'Embedded report checksum mismatch')
            if name.endswith('.json'):reports[name]=json.loads(raw)
            elif name.endswith('.csv'):reports[name]=pd.read_csv(io.BytesIO(raw))
        require(reports['_SUCCESS.json']['identity']==PRIOR_ID,'Wrong prior result identity')
        for name in ['SELECTED_FITS.json','_SUCCESS.json','LINEAGE.json']:
            require((base/'report'/name).is_file() and (base/'report'/name).read_bytes()==z.read('report/'+name),'Local prior report differs from reviewed return: '+name)
    config=json.loads((base/'PRIVATE/CONFIG.json').read_text())['config']
    require(binding(config)==PRIOR_ID,'Local prior configuration changed')
    return reports


def input_design(base,report):
    paths={k:base/'PRIVATE'/k for k in ['sequences.parquet','cohort.parquet','train_arrays.npz']}
    for p in paths.values():require(ready(p,PRIOR_ID),'Required verified v1.0.0 cache unavailable: '+str(p))
    df=pd.read_parquet(paths['sequences.parquet'])
    development=df[df.cohort=='development'];train=subset(design(development),development.period.to_numpy()==0)
    frame=df[df.cohort=='evaluation'].copy();ev=design(frame);del df
    old=legacy.load_data(paths['train_arrays.npz'])
    for key in ['H','y','ptr','period','ids','F','accounts','cost_indices']:np.testing.assert_array_equal(train[key],old[key])
    require(train['X'].shape==old['X'].shape and (train['X']!=old['X']).nnz==0,'Training feature matrix changed')
    require(len(train['accounts'])==19939 and len(train['y'])==188008 and train['y'].sum()==2477,'Training support differs from reviewed run')
    test=ev['period']==1
    require(int(test.sum())==344602 and int(ev['y'][test].sum())==4254 and len(np.unique(ev['ids'][test]))==26740,'Evaluation support differs from reviewed run')
    cohort=pd.read_parquet(paths['cohort.parquet']);eval_ids=cohort.loc[cohort.cohort=='evaluation','chooser']
    require(len(eval_ids)==50000 and (cohort.loc[cohort.cohort=='evaluation','pilot_rank']>100000).all(),'Original pilot exclusion changed')
    require(not np.intersect1d(train['accounts'],ev['accounts']).size,'Training and evaluation overlap')
    atomic_json(report/'INPUT_BRIDGE.json',dict(prior_identity=PRIOR_ID,prior_result_sha256=PRIOR_SHA,
      verified_cache_sha256={k:sha256_file(p) for k,p in paths.items()},training_array_equality=True,
      original_pilot_excluded=True,training_accounts=len(train['accounts']),training_opportunities=len(train['y']),training_grants=int(train['y'].sum()),
      evaluation_accounts_with_histories=len(ev['accounts']),evaluation_year_opportunities=int(test.sum()),evaluation_year_grants=int(ev['y'][test].sum())))
    return train,ev,frame


def settings_for_identity(args):
    excluded={'project_root','sample_root','base_run','desktop','workers','hash_workers','memory','bootstrap_refits','recovery_reps','stages'}
    return {k:v for k,v in vars(args).items() if k not in excluded}


def package_report(report,desktop,runid):
    forbidden={'chooser','recipient_id','opponent_id','game_id','username','row_id','recipient_name','opponent_name','white_id','black_id'}
    for p in report.glob('*.csv'):
        if p.stat().st_size:
            import csv
            with p.open() as f:require(not forbidden.intersection(next(csv.reader(f))),'Private identifier column in report: '+p.name)
    # Public JSON is built only from aggregates, model parameters and content digests.
    manifest=[f'{sha256_file(p)}  {p.relative_to(report)}' for p in sorted(report.rglob('*')) if p.is_file() and p.name!='REPORT_MANIFEST.sha256']
    atomic_text(report/'REPORT_MANIFEST.sha256','\n'.join(manifest)+'\n')
    out=desktop/f'POOL_CONSTRUAL_FOLLOWUP_RESULTS_v110_{runid}.zip';temp=Path(str(out)+'.partial')
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(report.rglob('*')):
            if p.is_file():z.write(p,'report/'+str(p.relative_to(report)))
    os.replace(temp,out);atomic_text(Path(str(out)+'.sha256'),sha256_file(out)+'  '+out.name+'\n')
    log('UPLOAD: '+str(out));log('UPLOAD: '+str(out)+'.sha256')
    return out


def write_summary(report,status,args):
    atomic_json(report/'RUN_STATUS.json',status)
    atomic_text(report/'READ_RESULTS.md','\n'.join([
      '# Construal follow-up v1.1.0','',
      'This is a follow-up to inspected results, using the same frozen training and evaluation accounts. It is not a new untouched confirmation sample.',
      '', 'Read in this order:',
      '1. INPUT_BRIDGE.json and legacy_numeric_bridge.csv: reproduce the original inputs and scores.',
      '2. NUMERICAL_STATUS.json, bound_sensitivity.csv, optimizer_attempts.csv: bounds, dispersed starts, convergence and unresolved optimization.',
      '3. primary_comparisons.csv and refit_bootstrap_summary.csv: predictive gains, conditional SEs, and frozen-complexity account-refit uncertainty.',
      '4. original_bootstrap_6_bridge.csv and bootstrap_6_reoptimization.csv: reproduce and diagnose the anomalous old draw.',
      '5. recovery_selection.csv and recovery_parameter_errors.csv: model discrimination and parameter recovery at actual training scale.',
      '6. refit_transition_summary.csv: entry, staying and their contrast; forecast decomposition uses filtered probabilities, not hard state assignments.',
      '7. OPPORTUNITY_DEFINITION.json, opportunity_IV_bridge.csv, opportunity_IV_estimates.csv: recipient-as-chooser versus recipient-as-disconnected and broader activity.',
      '', 'Interpretation limits:',
      '- Receipt transition coefficients are predictive associations conditional on this latent model. They do not identify causal retention or conversion.',
      '- Higher-intercept and lower-intercept states are labels at the reference configuration; covariate slopes can make their emissions cross elsewhere.',
      '- A flat lower emission may describe choices better without measuring moral construal. A null gain from unrestricted emissions is not equivalence.',
      '- Wider bounds and multiple starts are numerical checks, not proof of a global optimum. Read all boundary, gradient and nonconverged-start diagnostics.',
      '- Bootstrap draws refit training accounts and independently resample evaluation accounts. Complexity and previous specification search are held fixed; cross-account or calendar dependence is not covered.',
      '- Intervals require at least 100 converged paired refits; failed draws and boundary draws are counted. Selective nonconvergence can compromise these intervals.',
      '- Recovery fixes actual covariate/receipt histories and simulates separate development/evaluation outcomes. It does not simulate endogenous arrival or receipt feedback. Near-collapse is deliberately included.',
      '- n_lost counts later action-resolved choices by the recipient when the opponent left a losing position. It does not count the recipient disconnecting while losing.',
      '- The action panel, broader API candidate frame, and chronology corpus have different coverage and timing. No post-treatment counts enter IV controls or causal rate ratios.',
      '- Missing broad-source coverage is reported; API IV is restricted to complete covered 90-day windows with same-subset reference outcomes.',
      '- A receipt-mediated change in later activity is not by itself an exclusion violation; it can change selection into observed choices.',
      '',f'Requested budgets: {args.bootstrap_refits} refits; {args.recovery_reps} recovery replications per generating scenario.',
      '', 'Stage status:',*[f'- {k}: {v.get("status","UNKNOWN")}' for k,v in status.items()],'']))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    ap.add_argument('--sample-root',type=Path);ap.add_argument('--base-run',type=Path)
    ap.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    ap.add_argument('--workers',type=int,default=2);ap.add_argument('--hash-workers',type=int,default=1);ap.add_argument('--memory',default='4GB')
    ap.add_argument('--seed',type=int,default=20260921);ap.add_argument('--bound-grid',default='7,12,20')
    ap.add_argument('--starts',type=int,default=8);ap.add_argument('--refit-starts',type=int,default=4);ap.add_argument('--recovery-starts',type=int,default=4)
    ap.add_argument('--maxiter',type=int,default=1000);ap.add_argument('--ridge',type=float,default=1e-6)
    ap.add_argument('--bootstrap-refits',type=int,default=120);ap.add_argument('--recovery-reps',type=int,default=20)
    ap.add_argument('--stages',default=','.join(STAGES));args=ap.parse_args()
    args.bound_grid=sorted(set(float(x) for x in args.bound_grid.split(',')));args.stages=args.stages.split(',')
    require(args.bound_grid[0]==7 and args.bound_grid[-1]>7 and all(np.isfinite(args.bound_grid)),'Include original width 7 and at least one wider bound')
    require(1<=args.workers<=10 and 1<=args.hash_workers<=10,'Workers must be 1–10')
    require(min(args.starts,args.refit_starts,args.recovery_starts)>=2 and args.maxiter>=20,'Invalid optimization budget')
    require(args.ridge==1e-6 and args.seed==20260921,'Preserve reviewed ridge and bootstrap-six random stream')
    require(args.bootstrap_refits>=0 and args.recovery_reps>=1 and set(args.stages)<=set(STAGES),'Invalid stage or replication budget')
    code=hashes();project=args.project_root.expanduser().resolve();desktop=args.desktop.expanduser().resolve()
    require(project.is_dir(),'Project drive unavailable: '+str(project));require(shutil.disk_usage(project).free>20*1024**3,'Need 20 GiB free for private caches and spill')
    base=(args.base_run or project/'output'/('pool_construal_tests_v100_'+PRIOR_ID[:16])).expanduser().resolve()
    prior=prior_reports(base);deps={m.__name__:m.__version__ for m in [np,pd,duckdb,pyarrow,scipy,numba]}
    config=dict(version='1.1.0',code=code,settings=settings_for_identity(args),dependencies=deps,prior_identity=PRIOR_ID,prior_sha256=PRIOR_SHA)
    identity=binding(config);runid=identity[:16];root=project/'output'/('pool_construal_followup_v110_'+runid)
    private=root/'PRIVATE';report=root/'report';private.mkdir(parents=True,exist_ok=True);report.mkdir(parents=True,exist_ok=True);desktop.mkdir(parents=True,exist_ok=True)
    lock=(root/'RUN.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('This follow-up configuration is already running')
    status={};db=None
    if (report/'RUN_STATUS.json').exists():
        if (report/'_SUCCESS.json').exists() and (report/'REPORT_MANIFEST.sha256').exists():
            for line in (report/'REPORT_MANIFEST.sha256').read_text().splitlines():
                digest,name=line.split('  ',1);require(sha256_file(report/name)==digest,'Existing public report changed: '+name)
        status=json.loads((report/'RUN_STATUS.json').read_text())
    (report/'_SUCCESS.json').unlink(missing_ok=True)
    atomic_json(private/'CONFIG.json',dict(config=config,argv=sys.argv,python=sys.executable,platform=platform.platform()))
    atomic_json(report/'LINEAGE.json',config)
    try:
        with heartbeat('Verified history bridge'):
            train,ev,frame=input_design(base,report)
            fits0={k:prior['SELECTED_FITS.json'][k] for k in models.FAMILIES}
            require(len({f['J'] for f in fits0.values()})==1,'Nested warm starts require matched support counts')
            models.verify_legacy(train,ev,fits0,prior,report,args)
        status['input']=dict(status='ORIGINAL_INPUTS_AND_SCORES_REPRODUCED')
        with cf.ProcessPoolExecutor(max_workers=args.workers,mp_context=mp.get_context('spawn')) as pool:
            # Numerical fits are also needed by bootstrap and recovery; cached attempts are reused.
            if set(args.stages)&{'models','bootstrap','recovery'}:
                with heartbeat('Bound and start sensitivity'):
                    fits,grid,path,risk=models.numerical_grid(train,ev,frame,fits0,private,report,identity,args,pool)
                status['models']=json.loads((report/'NUMERICAL_STATUS.json').read_text())
                write_summary(report,status,args);package_report(report,desktop,runid)
            if 'opportunities' in args.stages:
                try:
                    with heartbeat('Opportunity source authentication and diagnostics'):
                        sample=args.sample_root or project/'derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE'
                        auth=authority.authenticate_sample(sample,verify_hashes=True,hash_workers=args.hash_workers)
                        db=duckdb.connect();db.execute(f'SET threads={args.workers}');db.execute('SET memory_limit='+qs(args.memory))
                        db.execute('SET temp_directory='+qs(private/'spill'));db.execute('SET preserve_insertion_order=false')
                        prep.source_view(db,[r['path'] for r in auth['month_records']])
                        status['opportunities']=dict(status='DIAGNOSTICS_REPORTED',sources=opportunities.run(db,project,base,PRIOR_ID,private,report,identity,prior))
                except Exception as exc:
                    atomic_json(private/'opportunities_ERROR.json',dict(error=repr(exc),traceback=traceback.format_exc()))
                    status['opportunities']=dict(status='FAILED_REVIEW_PRIVATE_ERROR_LOG',error_type=type(exc).__name__)
                    log('Opportunity diagnostics did not complete; numerical analyses can continue')
                finally:
                    if db is not None:db.close();db=None
                write_summary(report,status,args);package_report(report,desktop,runid)
            if 'bootstrap' in args.stages:
                with heartbeat('Refit bootstrap'):
                    six,_,_=models.old_replication_six(base,PRIOR_ID,train,ev,report,prior['refit_bootstrap_draws.csv'])
                    summary=models.bootstrap(train,path,ev,risk,fits,grid,private,report,identity,args,pool,six)
                status['bootstrap']=dict(status='REFITS_REPORTED',replications=args.bootstrap_refits,minimum_converged_pairs=min(x['converged'] for x in summary))
                write_summary(report,status,args);package_report(report,desktop,runid)
            if 'recovery' in args.stages:
                with heartbeat('Full training-scale recovery'):
                    models.recovery(train,path,ev,fits,private,report,identity,args,pool)
                status['recovery']=dict(status='RECOVERY_REPORTED',replications_per_scenario=args.recovery_reps)
        status.pop('run',None);write_summary(report,status,args)
        atomic_json(report/'_SUCCESS.json',dict(status='REQUESTED_COMPUTATIONS_FINISHED',identity=identity,requested_stages=args.stages,
          bootstrap_refits=args.bootstrap_refits,recovery_reps=args.recovery_reps,identification_certified=False,
          note='Read all stage and source statuses; optional sources may be unavailable or failed.'))
        package_report(report,desktop,runid);return 0
    except Exception as exc:
        atomic_json(private/'ERROR.json',dict(error=repr(exc),traceback=traceback.format_exc()))
        status['run']=dict(status='FAILED_REVIEW_PRIVATE_ERROR_LOG',error_type=type(exc).__name__)
        write_summary(report,status,args);package_report(report,desktop,runid);log('STOPPED: '+str(exc));return 2
    finally:
        if db is not None:db.close()
        fcntl.flock(lock,fcntl.LOCK_UN);lock.close()


if __name__=='__main__':sys.exit(main())
