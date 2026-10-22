#!/usr/bin/env python3
from __future__ import annotations
import argparse, concurrent.futures, fcntl, json, os, platform, shutil, sys, time, zipfile
from pathlib import Path
import duckdb, numpy as np, pandas as pd, pyarrow, scipy
from source import pool_wave1_common as authority
from util import *
from prepare import source_view,audit_source,support_census,pilot_sample
from model import fit_encoder,encode,arrays,save_arrays,fit_once,choose_fit,predict,eb_baseline,score_models

PACKAGE=Path(__file__).resolve().parent

def package_hashes():
    expected={}
    for line in (PACKAGE/'PACKAGE_MANIFEST.sha256').read_text().splitlines():
        h,name=line.split('  ',1);p=PACKAGE/name
        require(p.is_file() and sha256_file(p)==h,'Package checksum failed: '+name);expected[name]=h
    return expected

def run_models(path,private,report,identity,args):
    train_np=private/'training_arrays.npz';specpath=private/'encoder.json'
    log('Reading the capped pilot, constructing training-only nuisance controls')
    df=pd.read_parquet(path);train_df=df[df.period==0].copy();test_df=df[df.period==1].copy();del df
    require(len(test_df)>0,'No year-two opportunities in pilot')
    accounts=np.sort(train_df.chooser.unique())
    spec=fit_encoder(train_df);X,names,_=encode(train_df,spec);TX,_,unknown=encode(test_df,spec)
    tr=arrays(train_df,X,accounts);te=arrays(test_df,TX,accounts)
    atomic_json(specpath,dict(spec=spec,feature_names=names,test_unseen_category_opportunities=unknown))
    atomic_json(report/'MODEL_DESIGN.json',dict(K=3,features=names,training_accounts=len(accounts),
       nuisance_categories_from='year one only',test_unseen_category_opportunities=unknown,
       shared_index='alpha_k + theta_k * competitive + X beta',
       fitted_states='competitive (cp>=-100) or clearly worse (cp<=-300); middle excluded',
       state_controls='Common board-by-eight-stage cell effects, with two baseline cells removed',
       reference_cells=['clearly worse, plies 21–40','roughly equal, plies 21–40'],
       prior='Constant finite-mixture probabilities; conditional on observed opportunity histories. No pre-panel claims.',
       seasonal_controls='Month of year, shared between years; no year-two intercept fitting.',
       penalty='Same weak L2 penalty on common nuisance coefficients in both models: '+str(args.ridge)))
    if not ready(train_np,identity):save_arrays(train_np,tr);certify(train_np,identity)
    best={};allfits=[]
    for model in ['level_only','selectivity']:
        tasks=[]
        for start in range(args.starts):
            output=private/f'{model}_start_{start}.json'
            warm=best['level_only']['parameters'] if model=='selectivity' else None
            tasks.append((str(train_np),str(output),model=='selectivity',3,args.seed+start*101,args.maxiter,warm,args.ridge,identity))
        with concurrent.futures.ProcessPoolExecutor(max_workers=min(args.workers,args.starts)) as executor:
            futures=[executor.submit(fit_once,t) for t in tasks]
            paths=[]
            for f in concurrent.futures.as_completed(futures): paths.append(f.result())
        chosen,attempts=choose_fit(paths);best[model]=chosen
        for fit in attempts:
            allfits.append(dict(model=model,seed=fit['seed'],converged=fit['success'],iterations=fit['iterations'],
              objective=fit['objective'],train_log_likelihood=fit['train_log_likelihood'],
              boundary_parameters=len(fit['boundary_parameters']),gradient_max_abs=fit['gradient_max_abs']))
    csv_write(report/'optimizer_attempts.csv',allfits)
    # Parameters are selected solely by the training objective before any scoring below.
    atomic_json(report/'PILOT_FITS.json',best)
    predictions={};joint={};posterior={}
    for name,fit in best.items(): predictions[name],joint[name],posterior[name]=predict(fit,tr,te)
    predictions['smoothed_state_rates'],priors=eb_baseline(train_df,test_df)
    atomic_json(report/'SMOOTHED_BASELINE.json',priors)
    comparisons=score_models(predictions,test_df,accounts,report,joint)
    support=pd.read_parquet(private/'account_support.parquet')
    support=support[support.chooser.isin(accounts)]
    subgroup=[]
    for threshold in [1,3,8]:
        eligible=support[(support.f_train>=threshold)&(support.l_train>=threshold)].chooser.to_numpy()
        mask=test_df.chooser.isin(eligible).to_numpy();n=test_df.n.to_numpy()[mask];g=test_df.g.to_numpy()[mask]
        for name,p in predictions.items():
            pp=p[mask]
            subgroup.append(dict(min_train_per_region=threshold,model=name,test_accounts=int(test_df.loc[mask,'chooser'].nunique()),
             test_opportunities=int(n.sum()),log_loss_per_opportunity=float(-(g*np.log(pp)+(n-g)*np.log1p(-pp)).sum()/n.sum()) if n.sum() else None))
    csv_write(report/'heldout_by_training_support.csv',subgroup)
    # Private posterior file allows a later authenticated Patron join without refitting.
    posterior_frame=pd.DataFrame({'chooser':accounts})
    for name,q in posterior.items():
        for k in range(3):posterior_frame[f'{name}_posterior_{k}']=q[:,k]
    pp=private/'first_year_posteriors_PRIVATE.parquet';posterior_frame.to_parquet(pp,index=False,compression='zstd');certify(pp,identity)
    warnings=[]
    for name,fit in best.items():
        if not fit['success']:warnings.append(name+': no converged optimizer attempt; diagnostic scores only')
        if fit['boundary_parameters']:warnings.append(name+': at least one parameter reached a numerical bound')
        if min(fit['weights'])<0.001:warnings.append(name+': a mixture class has <0.1% estimated weight')
    if best['selectivity']['objective']>best['level_only']['objective']+1e-6:
        warnings.append('Richer model has a worse training objective than its nested benchmark: optimizer failure suspected')
    if sum(unknown.values()):warnings.append('Some year-two nuisance categories were unseen in training; zero-effect fallback counts are in MODEL_DESIGN.json')
    return dict(comparisons=comparisons,warnings=warnings,selected_fits_converged=all(v['success'] for v in best.values()))

def write_summary(report,result,args,run_id):
    lines=['# Selectivity pilot — exploratory','',f'Run: {run_id}',
      '', 'Population: certified 41,534,331 pool / observed-nonadjacent active timeout choices, November 2023–October 2025.',
      'This observed-adjacency screen is not a certification of literal immediate-rematch timing.',
      '', '## What ran',
      '- Full-census support tables across all five board bins and eight game stages.',
      f'- Pilot capped at {args.pilot_accounts:,} first-year accounts, chosen by a fixed hash without outcome or year-two selection.',
      '- K=3 finite-mixture comparison: persistent level only versus persistent level and competitive-state slope.',
      '- Shared board/stage and observed rating, cost, clock, speed, color, volatility and seasonal controls.',
      '- Frozen year-one parameters and posteriors; year-two outcomes only score predictions.',
      '- Train-only beta-binomial smoothed state-rate benchmark.',
      '', '## Read first',
      '1. support_in_both_regions.csv and support_by_history_length.csv: how much within-account information exists?',
      '2. optimizer_attempts.csv: convergence, local solutions, and boundaries.',
      '3. heldout_comparisons.csv: positive log-score gain favors heterogeneous selectivity.',
      '4. heldout_scores.csv and heldout_calibration.csv: region-specific prediction and calibration.',
      '5. heldout_by_training_support.csv: whether gains survive among accounts with richer first-year support.',
      '', '## Interpretation',
      'The pilot is a feasibility and prediction exercise. It does not estimate the full common warrant surface, identify independent moral traits, prove identification, establish causal receipt effects, or estimate Patron relationships.',
      'A positive gain is a reason to develop the model, not a paper-ready structural finding. A failure can reflect limited support, misspecification, or optimization.',
      'Reported score standard errors condition on fitted models. They exclude uncertainty from refitting, class selection, and model development.',
      'The mixture assumes its prior distribution is suitable conditional on the observed histories. It does not solve informative opportunity arrival or serially correlated states.',
      'Year-two evaluation is conditional on observed year-two opportunities; accounts with no such opportunity remain in cohort/support counts.',
      '', '## Run warnings']
    if args.audit_only:
        lines[lines.index('## What ran')]='## Configured analysis (only the census audit ran in this invocation)'
    lines += ['- '+x for x in result.get('warnings',[])] or ['None from the numerical gates. Economic identification is not certified.']
    atomic_text(report/'SUMMARY.md','\n'.join(lines)+'\n')

def package_report(report,transfer,run_id):
    records_out=[]
    for p in sorted(report.rglob('*')):
        if p.is_file() and p.name!='REPORT_MANIFEST.sha256': records_out.append(f'{sha256_file(p)}  {p.relative_to(report)}')
    atomic_text(report/'REPORT_MANIFEST.sha256','\n'.join(records_out)+'\n')
    output=transfer/f'POOL_SELECTIVITY_PILOT_RESULTS_v100_{run_id}.zip'
    partial=Path(str(output)+'.partial')
    with zipfile.ZipFile(partial,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(report.rglob('*')):
            if p.is_file():z.write(p,'report/'+str(p.relative_to(report)))
    os.replace(partial,output)
    atomic_text(Path(str(output)+'.sha256'),sha256_file(output)+'  '+output.name+'\n')
    return output

def main():
    p=argparse.ArgumentParser(description='Full-census support audit plus an exploratory selectivity pilot')
    p.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--sample-root',type=Path)
    p.add_argument('--transfer-root',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--workers',type=int,default=2);p.add_argument('--hash-workers',type=int,default=1)
    p.add_argument('--memory-limit',default='4GB');p.add_argument('--pilot-accounts',type=int,default=100000)
    p.add_argument('--starts',type=int,default=3);p.add_argument('--maxiter',type=int,default=700)
    p.add_argument('--seed',type=int,default=20260920);p.add_argument('--ridge',type=float,default=1e-6)
    p.add_argument('--audit-only',action='store_true')
    args=p.parse_args();require(1<=args.workers<=10 and 1<=args.hash_workers<=10,'Workers must be 1–10')
    require(args.pilot_accounts>=100 and args.starts>=2 and args.maxiter>=20 and args.ridge>=0,'Invalid pilot settings')
    hashes=package_hashes();args.project_root=args.project_root.expanduser().resolve();args.transfer_root=args.transfer_root.expanduser().resolve()
    require(args.project_root.is_dir(),'Project drive not found: '+str(args.project_root))
    require(shutil.disk_usage(args.project_root).free>10*1024**3,'At least 10 GiB free disk space is required for caches and spill files')
    sample=args.sample_root or args.project_root/'derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE'
    config=dict(version=VERSION,package=hashes,sample_fingerprint=authority.verify_report_package()[0]['sample_fingerprint'],
        pilot_accounts=args.pilot_accounts,seed=args.seed,starts=args.starts,maxiter=args.maxiter,ridge=args.ridge,
        model='fixed-three-class-competitive-slope-pilot',dependencies={m.__name__:m.__version__ for m in [duckdb,np,pd,pyarrow,scipy]})
    identity=binding(config);run_id=identity[:16]
    root=args.project_root/'output'/('pool_selectivity_pilot_v100_'+run_id)
    root.mkdir(parents=True,exist_ok=True);private=root/'PRIVATE';private.mkdir(exist_ok=True)
    lock=(root/'.run.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError: raise RuntimeError('This configuration is already running: '+str(root))
    args.transfer_root.mkdir(parents=True,exist_ok=True)
    report=root/('audit_report' if args.audit_only else 'report');report.mkdir(exist_ok=True)
    complete=report/'_SUCCESS.json'
    if complete.exists():
        log('Completed configuration already exists; verifying report checksums and repackaging')
        for line in (report/'REPORT_MANIFEST.sha256').read_text().splitlines():
            h,n=line.split('  ',1);require(sha256_file(report/n)==h,'Existing report checksum mismatch')
        output=package_report(report,args.transfer_root,run_id+('_audit' if args.audit_only else ''))
        log('REPORT: '+str(output));return
    atomic_json(private/'RUN_CONFIG.json',config)
    atomic_json(private/'COMMAND.json',dict(argv=sys.argv,python=sys.executable,platform=platform.platform()))
    log('Full-byte authentication of the 24 certified monthly inputs')
    auth=authority.authenticate_sample(sample,verify_hashes=True,hash_workers=args.hash_workers)
    paths=[r['path'] for r in auth['month_records']]
    # Public lineage intentionally omits user names, machine paths, and private account data.
    atomic_json(report/'LINEAGE.json',dict(sample_fingerprint=auth['fingerprint'],report_sha256=auth['authority']['report_sha256'],
      panel_sha256_verified=True,months=[dict(month=r['month'],rows=r['rows'],sha256=r['actual_sha256']) for r in auth['month_records']],
      code_sha256=hashes,dependencies=config['dependencies'],run_id=run_id))
    spill=private/'duckdb_spill';spill.mkdir(exist_ok=True)
    db=duckdb.connect();db.execute(f'SET threads={args.workers}');db.execute('SET memory_limit='+qs(args.memory_limit))
    db.execute('SET temp_directory='+qs(spill));db.execute('SET preserve_insertion_order=false')
    source_view(db,paths);audit_source(db,report)
    support_census(db,private,report,identity)
    if args.audit_only:
        result=dict(warnings=['Audit-only run: no models were fitted'],selected_fits_converged=False)
    else:
        pilot=pilot_sample(db,private,report,identity,args.pilot_accounts,args.seed);db.close();db=None
        result=run_models(pilot,private,report,identity,args)
    if db is not None:db.close()
    write_summary(report,result,args,run_id)
    atomic_json(complete,dict(status='AUDIT_COMPLETE' if args.audit_only else 'PILOT_COMPUTATION_COMPLETE',
      identity=identity,completed_utc=authority.utc_now(),model_identification_certified=False,**result))
    output=package_report(report,args.transfer_root,run_id+('_audit' if args.audit_only else ''))
    log('POOL_SELECTIVITY_PILOT_COMPUTATION_COMPLETE')
    log('REPORT: '+str(output));log('Upload only the report ZIP and its SHA-256 sidecar; private account files stay on your drive.')

if __name__=='__main__':
    try:main()
    except Exception as exc:
        log('STOPPED: '+str(exc));raise
