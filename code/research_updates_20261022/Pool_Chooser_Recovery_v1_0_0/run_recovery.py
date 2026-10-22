#!/usr/bin/env python3
"""Recover four chooser model classes on full observed account histories."""
from __future__ import annotations
import argparse,fcntl,os,sys,time,zipfile
from pathlib import Path
from recovery_core import (wide,analysis,MODELS,SCENARIOS,clean_template,simulation_job,summarize)
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from engine import predict,parameters
from io_utils import binding,digest,json_read,json_write,atomic_text,require,log,heartbeat
from table_io import csv_write
import runtime

PKG=Path(__file__).resolve().parent


def authenticate(source_root,bounds_root,bootstrap_root,allow_fixture):
    source=wide.reference.authenticate(source_root,allow_fixture)
    wide.reference.manifest(bounds_root/'report','REPORT_MANIFEST.sha256')
    bc=json_read(bounds_root/'report/LINEAGE.json')['config']
    require(bc['code']==wide.reference.manifest(PKG/'reference_wide/reference_bounds','PACKAGE_MANIFEST.sha256'),'Wrong bound-run producer')
    require(bc['source_identity']==source['identity'] and bc['source_fits_sha256']==source['fits_sha256'],'Different bound-run source')
    require(bc['source_report_sha256']==digest(source_root/'report/REPORT_MANIFEST.sha256'),'Original report changed after bounds run')
    suffix='_fixture' if source['synthetic'] else ''
    require(bounds_root.name=='pool_chooser_bounds_v100_'+binding(bc)[:16]+suffix,'Bound-run identity mismatch')
    require(json_read(bounds_root/'report/RUN_STATUS.json')['last_run']=='COMPUTATION_OK','Bound run incomplete')
    fits=json_read(bounds_root/'PRIVATE/bounds_x4/SELECTED_FITS.json')
    for name in MODELS:
        f=fits[name];n=source['fits'][name]
        require(f['success'] and f['spec']==n['spec'] and f['J']==n['J'] and f['ridge']==n['ridge'] and f['bound']==4*n['bound'],
            'Unexpected wider-domain point template: '+name)
    wide.reference.manifest(bootstrap_root/'report','REPORT_MANIFEST.sha256')
    wc=json_read(bootstrap_root/'report/LINEAGE.json')
    require(wc['code']==wide.reference.manifest(PKG/'reference_wide','PACKAGE_MANIFEST.sha256'),'Wrong wider-bootstrap producer')
    require(bootstrap_root.name=='pool_chooser_wide_bootstrap_v100_'+binding(wc)[:16]+suffix,'Wider-bootstrap identity mismatch')
    require(wc['source_identity']==source['identity'] and wc['bounds_identity']==binding(bc),'Wider-bootstrap source mismatch')
    require(wc['source_report_sha256']==digest(source_root/'report/REPORT_MANIFEST.sha256'),'Wider-bootstrap original report mismatch')
    require(wc['bounds_report_sha256']==digest(bounds_root/'report/REPORT_MANIFEST.sha256'),'Bound report changed after bootstrap')
    require(wc['wide_fits_sha256']==digest(bounds_root/'PRIVATE/bounds_x4/SELECTED_FITS.json'),'Wider point vectors changed')
    require(json_read(bootstrap_root/'report/RUN_STATUS.json')['last_run']=='COMPUTATION_OK','Wider bootstrap incomplete')
    _,ev,meta=analysis.data_for('core');score_table=pd.read_parquet(bounds_root/'report/bounds_x4/scores.parquet')
    observed=pd.read_parquet(bootstrap_root/'report/wide_point_comparisons.parquet')
    source_pairs=pd.read_parquet(bounds_root/'report/bounds_x4/comparisons.parquet')
    checks=[]
    for name in MODELS:
        score=float(predict(fits[name],ev,meta)[1][ev['period']==2].mean())
        r=score_table[(score_table.model==name)&(score_table.group=='all')];require(len(r)==1,'Missing point score')
        error=abs(score-float(r.iloc[0].mean_log_score));require(error<1e-10,'Private wider point score mismatch')
        checks.append(dict(model=name,absolute_score_difference=error))
    obs={}
    for r in observed.itertuples():
        q=source_pairs[(source_pairs.candidate==r.candidate)&(source_pairs.baseline==r.baseline)]
        require(len(q)==1 and abs(float(q.iloc[0].gain)-r.gain)<1e-15,'Observed point comparison mismatch')
        obs[r.candidate+'|'+r.baseline]=dict(gain=r.gain,equal_account_gain=r.equal_account_gain)
    return source,fits,obs,checks,binding(bc),binding(wc)


def export(report,desktop,runid):
    desktop.mkdir(parents=True,exist_ok=True)
    forbidden={'chooser','chooser_user_id','recipient_id','opponent_id','game_id','username','account_id'}
    for p in report.rglob('*.parquet'):
        require(not forbidden.intersection(pq.read_schema(p).names),'Identifier in aggregate report')
    atomic_text(report/'REPORT_MANIFEST.sha256',''.join(digest(p)+'  '+str(p.relative_to(report))+'\n'
        for p in sorted(report.rglob('*')) if p.is_file() and p.name!='REPORT_MANIFEST.sha256'))
    path=desktop/f'POOL_CHOOSER_RECOVERY_RESULTS_v100_{runid}.zip';part=path.with_suffix('.zip.partial')
    with zipfile.ZipFile(part,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(report.rglob('*')):
            if p.is_file():z.write(p,'report/'+str(p.relative_to(report)))
    os.replace(part,path);atomic_text(str(path)+'.sha256',digest(path)+'  '+path.name+'\n')
    log('UPLOAD: '+str(path));log('UPLOAD: '+str(path)+'.sha256')


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    base=Path('/Volumes/XT_Pro/lichess_kindness/output')
    ap.add_argument('--source-run',type=Path,default=base/'pool_chooser_followup_v112_1e5c35a1309c0258')
    ap.add_argument('--bounds-run',type=Path,default=base/'pool_chooser_bounds_v100_f14e1be2f5314f2e')
    ap.add_argument('--bootstrap-run',type=Path,default=base/'pool_chooser_wide_bootstrap_v100_19717dce14d9dd9d')
    ap.add_argument('--output-root',type=Path);ap.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    ap.add_argument('--workers',default='auto');ap.add_argument('--recovery-reps',type=int,default=100)
    ap.add_argument('--starts',type=int,default=6);ap.add_argument('--maxiter',type=int,default=1200)
    ap.add_argument('--allow-fixture',action='store_true');args=ap.parse_args(argv)
    require(args.starts>=2 and args.maxiter>=50 and args.recovery_reps>=1,'Invalid fit budget')
    require(args.workers=='auto' or (args.workers.isdigit() and 1<=int(args.workers)<=10),'Workers must be auto or 1..10')
    code=wide.reference.manifest(PKG,'PACKAGE_MANIFEST.sha256')
    source_root=args.source_run.expanduser().resolve();bounds_root=args.bounds_run.expanduser().resolve();bootstrap_root=args.bootstrap_run.expanduser().resolve()
    locks=[];owns_output=False;runid=None;report=None;started=time.monotonic()
    try:
        for root in [source_root,bounds_root,bootstrap_root]:
            require((root/'RUN.lock').is_file(),'Completed source run missing: '+str(root))
            lock=(root/'RUN.lock').open('r');locks.append(lock);fcntl.flock(lock,fcntl.LOCK_SH|fcntl.LOCK_NB)
        with heartbeat('Authenticate completed runs and shared numeric maps'):
            source,fits,observed,checks,bid,wid=authenticate(source_root,bounds_root,bootstrap_root,args.allow_fixture)
        settings=dict(seed=source['config']['settings']['seed']+2719,starts=args.starts,maxiter=args.maxiter,
            starting_rule='three_generic_then_three_near_additive_repeat_v1',scenarios=SCENARIOS)
        templates={n:clean_template(fits[n]) for n in MODELS};generators={n:fits[n] for n in SCENARIOS}
        config=dict(version='1.0.0',code=code,source_identity=source['identity'],bounds_identity=bid,bootstrap_identity=wid,
            source_report_sha256=digest(source_root/'report/REPORT_MANIFEST.sha256'),
            bounds_report_sha256=digest(bounds_root/'report/REPORT_MANIFEST.sha256'),
            bootstrap_report_sha256=digest(bootstrap_root/'report/REPORT_MANIFEST.sha256'),
            generator_vectors_sha256=digest(bounds_root/'PRIVATE/bounds_x4/SELECTED_FITS.json'),
            templates=templates,settings=settings,observed_margins=observed)
        runid=binding(config)[:16]+('_fixture' if source['synthetic'] else '')
        root=(args.output_root or source_root.parent).expanduser().resolve()/('pool_chooser_recovery_v100_'+runid)
        private=root/'PRIVATE';report=root/'report';private.mkdir(parents=True,exist_ok=True);report.mkdir(exist_ok=True)
        lock=(root/'RUN.lock').open('a');locks.append(lock);fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);owns_output=True
        old_status=json_read(report/'RUN_STATUS.json') if (report/'RUN_STATUS.json').exists() else {}
        require(args.recovery_reps>=old_status.get('requested_per_scenario',0),'Do not shrink a completed recovery report; use its previous or a larger replication budget')
        json_write(private/'CONFIG.json',config);json_write(private/'GENERATORS.json',generators);json_write(report/'LINEAGE.json',config)
        csv_write(report/'source_score_reproduction.csv',checks)
        csv_write(report/'fixed_numerical_domains.csv',[dict(model=n,J=f['J'],ridge=f['ridge'],bound=f['bound']) for n,f in templates.items()])
        csv_write(report/'observed_comparisons.csv',[dict(candidate=k.split('|')[0],baseline=k.split('|')[1],**v) for k,v in observed.items()])
        _,ev,meta=analysis.data_for('core');train=analysis.training_for('core')
        truth=[]
        for name,g in generators.items():
            pr,_=parameters(g,meta);truth.extend(dict(scenario=name,**r) for r in pr)
        csv_write(report/'generating_types.csv',truth)
        json_write(report/'DESIGN_COUNTS.json',dict(development_accounts=len(train['ptr'])-1,development_opportunities=len(train['y']),
            observed_development_grants=int(train['y'].sum()),evaluation_accounts=len(ev['ptr'])-1,
            year_two_accounts=int(len(np.unique(ev['ids'][ev['period']==2]))),year_two_opportunities=int((ev['period']==2).sum()),
            observed_year_two_grants=int(ev['y'][ev['period']==2].sum()),z_names=meta['z_names'],
            note='All observed state/cost/control histories held fixed; only latent types and granting outcomes are simulated. No opportunity-arrival model.'))
        plan=runtime.choose_workers(args.workers,source['mapped'],max(f['J'] for f in templates.values()))
        json_write(report/'WORKER_PLAN.json',plan)
        attempts=pd.read_parquet(bootstrap_root/'report/refit_optimizer_attempts.parquet')
        per_start=attempts.groupby('model').seconds.mean()
        starts_count={n:args.starts+len(analysis.compatible_sources(n,templates[n],templates)) for n in MODELS}
        rough=sum(per_start[n]*starts_count[n] for n in MODELS)*len(SCENARIOS)*args.recovery_reps/plan['workers']
        json_write(report/'INITIAL_ETA.json',dict(lower_hours=rough*.9/3600,upper_hours=rough*1.8/3600,
            basis='Actual wider-bootstrap mean seconds per optimizer start, adjusted for starts and workers; recovery may converge differently.'))
        directory=private/'recovery';directory.mkdir(exist_ok=True)
        for s in SCENARIOS:(directory/s).mkdir(exist_ok=True)
        jobs=[(s,r,generators[s],templates,settings,observed,str(directory/s/f'rep_{r:04d}.json'))
            for r in range(args.recovery_reps) for s in SCENARIOS]
        json_write(report/'RUN_STATUS.json',dict(audit='COMPLETE_AUTHENTICATED',recovery='RUNNING',requested_per_scenario=args.recovery_reps))
        export(report,args.desktop,runid)
        log(f'Planning ETA: {rough*.9/3600:.1f}–{rough*1.8/3600:.1f} hours at {plan["workers"]} workers; updated from completed simulations')
        with heartbeat('Full-history model recovery'):
            results=runtime.execute(jobs,simulation_job,source['design'],plan['workers'],'recovery datasets',analysis.initialize)
        summarize(results,report);(report/'ERROR.json').unlink(missing_ok=True)
        json_write(report/'RUN_STATUS.json',dict(audit='COMPLETE_AUTHENTICATED',recovery='COMPUTED_REQUIRES_DIAGNOSTIC_REVIEW',
            requested_per_scenario=args.recovery_reps,last_run='COMPUTATION_OK',invocation_seconds=time.monotonic()-started))
        export(report,args.desktop,runid);log('COMPUTATION_OK — inspect recovery frequencies, event counts, failures, and oracle diagnostics')
        return 0
    except Exception as exc:
        if owns_output:
            json_write(report/'ERROR.json',dict(error=repr(exc)))
            json_write(report/'RUN_STATUS.json',dict(last_run='FAILED',error=str(exc),requested_per_scenario=args.recovery_reps))
            export(report,args.desktop,runid)
        log('STOPPED: '+str(exc));return 2
    finally:
        runtime.close_pool()
        for lock in reversed(locks):lock.close()


if __name__=='__main__':sys.exit(main())
