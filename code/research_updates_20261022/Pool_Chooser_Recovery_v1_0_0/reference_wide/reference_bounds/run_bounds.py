#!/usr/bin/env python3
"""Audit v1.1.2 bootstrap caps and compare point fits at nested numerical bounds."""
from __future__ import annotations
import os
for _key in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS',
             'VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS','NUMBA_NUM_THREADS']:
    os.environ[_key]='1'
import argparse, fcntl, json, sys, zipfile
from pathlib import Path
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

PKG=Path(__file__).resolve().parent
sys.path.insert(0,str(PKG/'engine_v112'))
import bootstrap_path
import numpy as np
import pandas as pd
import scipy, numba, duckdb, pyarrow
import pyarrow.parquet as pq
import runtime
import followup_analysis as analysis
from engine import Model, predict
from followup_diagnostics import summaries, pairs_for
from diagnostics import paired
from io_utils import binding,digest,json_read,json_write,atomic_text,require,log,heartbeat
from parent_audit import manifest
from table_io import csv_write


def authenticate(root,allow_fixture=False):
    record=json_read(root/'PRIVATE/CONFIG.json');config=record['config']
    require(config['version']=='1.1.2','Source must be the completed v1.1.2 follow-up')
    code=manifest(PKG/'engine_v112','PACKAGE_MANIFEST.sha256')
    require(config['code']==code,'Source producer differs from bundled v1.1.2')
    identity=binding(config)
    synthetic=bool(config['settings'].get('allow_fixture'))
    require(not synthetic or allow_fixture,'Synthetic source requires --allow-fixture')
    expected='pool_chooser_followup_v112_'+identity[:16]+('_fixture' if synthetic else '')
    require(root.name==expected,'Source directory does not match its configuration identity')
    lineage=json_read(root/'report/LINEAGE.json')
    authority=json_read(PKG/'engine_v112/base/authority/SAMPLE_AUTHORITY.json')
    require(synthetic or lineage['parent_sample_fingerprint']==authority['sample_fingerprint'],
            'Unrecognized source sample authority')
    for key in ['code','settings','dependencies']:
        require(lineage[key]==config[key],'Source lineage mismatch: '+key)
    deps={m.__name__:m.__version__ for m in [np,pd,scipy,numba,duckdb,pyarrow]}
    require(deps==config['dependencies'],
            'Use the same Python environment as v1.1.2; dependency versions differ')
    hashes=manifest(root/'report','REPORT_MANIFEST.sha256')
    status=json_read(root/'report/RUN_STATUS.json')
    require(status.get('last_run')=='COMPUTATION_OK','Source run is not complete')
    for stage in ['repair','repair-bootstrap']:
        require(status.get(stage)=='COMPUTED_REQUIRES_DIAGNOSTIC_REVIEW',
                'Source stage missing: '+stage)
    design=root/'PRIVATE/repair/design'
    for name,h in config['design'].items():
        require(digest(design/name)==h,'Source design checksum mismatch: '+name)
    require((design/'MAPPED/READY.json').is_file(),'Completed v1.1.2 numeric map is missing')
    # READY exists: ensure_mapped takes its verification-only path.
    mapped=runtime.ensure_mapped(design)
    fits=json_read(root/'PRIVATE/repair/core/SELECTED_FITS.json')
    require(set(fits)=={'level','desert','cost','both','free_index','type_cells',
                       'no_cost','premium_only','separate_costs','signed_costs'},
            'Unexpected source model inventory')
    require(all(f['success'] for f in fits.values()),'Unconverged source point fit')
    analysis.initialize(design);_,ev,meta=analysis.data_for('core')
    source_scores=pd.read_parquet(root/'report/repair/scores.parquet')
    checks=[]
    for name,f in fits.items():
        public=source_scores[(source_scores.model==name)&(source_scores.group=='all')]
        require(len(public)==1,'Missing source score: '+name)
        score=float(predict(f,ev,meta)[1][ev['period']==2].mean())
        error=abs(score-float(public.iloc[0].mean_log_score))
        require(error<1e-10,'Private fit does not reproduce public score: '+name)
        checks.append(dict(model=name,absolute_score_difference=error))
    return dict(config=config,identity=identity,synthetic=synthetic,design=design,
                mapped=mapped,fits=fits,checks=checks,report_hashes=hashes,
                fits_sha256=digest(root/'PRIVATE/repair/core/SELECTED_FITS.json'))


def inspect_bootstrap(root,source,report):
    """Read all small checkpoints in parallel; never filter capped draws from inference."""
    status=json_read(root/'report/repair/BOOTSTRAP_STATUS.json')
    count=int(status['requested'])
    folder=root/'PRIVATE/repair/core/bootstrap'
    paths=sorted(folder.glob('rep_*.json'))
    require({p.name for p in paths}=={f'rep_{r:04d}.json' for r in range(count)},
            'Bootstrap checkpoint inventory differs from completed report')
    settings=source['config']['settings']
    options=dict(seed=settings['seed']+913,starts=settings['refit_starts'],maxiter=settings['maxiter'])
    def read(path):
        rep=int(path.stem.split('_')[-1]);envelope=json_read(path)
        sig=binding(dict(stage='core',rep=rep,fits=source['fits'],options=options))
        require(envelope.get('signature')==sig,'Bootstrap signature mismatch: '+path.name)
        return rep,envelope['result'],digest(path)
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(read,paths))
    rows=[];pair_rows=[];check_hashes={};any_cap=any_failure=0
    for rep,value,h in results:
        check_hashes[f'rep_{rep:04d}.json']=h
        capped=set(value.get('bound_models',[]));failed=value.get('failures',{})
        any_cap+=bool(capped);any_failure+=bool(failed)
        for name in source['fits']:
            grad=value.get('projected_gradients',{}).get(name)
            require(grad is None or np.isfinite(grad),'Nonfinite checkpoint gradient')
            rows.append(dict(rep=rep,model=name,capped=name in capped,failed=name in failed,
                             projected_gradient=grad))
        for a,b in pairs_for(source['fits']):
            match=[x for x in value['rows'] if x['candidate']==a and x['baseline']==b]
            require(len(match)==1,'Missing/duplicate checkpoint pair')
            pair_rows.append(dict(rep=rep,candidate=a,baseline=b,
              candidate_capped=a in capped,baseline_capped=b in capped,
              either_capped=bool({a,b}&capped),successful=match[0]['gain'] is not None))
    require(any_cap==status['numerical_bound_replications'] and any_failure==status['failed_replications'],
            'Checkpoint totals disagree with exported bootstrap status')
    frame=pd.DataFrame(rows);pair_frame=pd.DataFrame(pair_rows)
    model_rows=[]
    for name,g in frame.groupby('model',sort=True):
        model_rows.append(dict(model=name,draws=len(g),capped=int(g.capped.sum()),
          failed=int(g.failed.sum()),max_projected_gradient=float(g.projected_gradient.max())))
    pairs=[]
    for (a,b),g in pair_frame.groupby(['candidate','baseline'],sort=True):
        pairs.append(dict(candidate=a,baseline=b,draws=len(g),successful=int(g.successful.sum()),
          candidate_capped=int(g.candidate_capped.sum()),baseline_capped=int(g.baseline_capped.sum()),
          either_capped=int(g.either_capped.sum())))
    for name,data in [('bootstrap_caps_by_model',model_rows),('bootstrap_caps_by_pair',pairs),
                      ('bootstrap_caps_by_draw',rows)]:csv_write(report/(name+'.csv'),data)
    json_write(report/'BOOTSTRAP_CAP_STATUS.json',dict(draws=count,any_cap=any_cap,any_failure=any_failure,
      note='All draws retained. This audits flags; it does not refit bootstrap models or change intervals.'))
    return check_hashes


def point_ladder(source,private,report,args):
    analysis.initialize(source['design']);_,ev,meta=analysis.data_for('core')
    train=analysis.training_for('core');original=source['fits']
    original_dir=report/'original';original_dir.mkdir(exist_ok=True)
    original_ll,original_comparisons=summaries(original,ev,meta,original_dir)
    reference_scores={n:float(ll[ev['period']==2].mean()) for n,ll in original_ll.items()}
    training_rows=[];attempt_rows=[];cap_rows=[];effect_rows=[];comparison_rows=[]
    previous=original;previous_label='original'
    labels=[('polish',1.),('bounds_x2',2.),('bounds_x4',4.)]
    for row in original_comparisons:comparison_rows.append(dict(step='original',**row))
    for label,factor in labels:
        log(f'{label}: same support, penalties and observations; numerical bound factor {factor:g}')
        selected={};step_dir=private/label;step_dir.mkdir(exist_ok=True)
        for name in analysis.fit_order(original):
            template=original[name];nested=analysis.compatible_sources(name,template,selected)
            # Preserve each source model's actual domain in the polish control.
            # Compatible-source transfer projects into this domain when needed;
            # evaluate that feasible start here, not the source model's objective.
            target=factor*template['bound']
            model=Model(template['spec'],template['J'],meta,target)
            warm=[('previous',np.asarray(previous[name]['parameters']))]
            if label!='polish':warm.append(('original',np.asarray(template['parameters'])))
            # Identical cold-start seeds across bound steps; no test-score selection.
            warm += [('independent_'+str(s),model.start(args.seed+91000+s)) for s in range(1,args.starts)]
            warm += [('from_'+n,analysis.transfer(r,model,meta,args.seed)) for n,r in nested]
            jobs=[];witness=[];lo,hi=np.array(model.bounds).T
            for j,(origin,v) in enumerate(warm):
                require(np.all(v>=lo-1e-10) and np.all(v<=hi+1e-10),
                        'A nested or preceding fit is outside the expanded bounds')
                objective=float(model.objective(v,train,template['ridge'])[0]);witness.append((origin,objective))
                jobs.append(('core',template['spec'],template['J'],args.seed+91000+j,
                  dict(phase='full',maxiter=args.maxiter,ridge=template['ridge']),
                  str(step_dir/f'{name}_{origin}.json'),v.tolist(),target))
            values=analysis.execute(jobs,analysis.fit_one,source['design'],args.workers,label+' '+name)
            winner=analysis.best(values)
            require(winner['objective']<=min(v for _,v in witness)+1e-8,
                    f'{label}/{name}: fit worse than a feasible start; no completed result released')
            selected[name]=winner
            for origin,obj in witness:
                training_rows.append(dict(step=label,model=name,start=origin,J=template['J'],ridge=template['ridge'],
                  original_bound=template['bound'],target_bound=target,feasible_objective=obj,
                  selected_objective=winner['objective'],after_minus_feasible=winner['objective']-obj,
                  violation=winner['objective']>obj+1e-8))
            for value in values:
                attempt_rows.append(dict(step=label,model=name,seed=value['seed'],success=value['success'],
                  objective=value['objective'],projected_gradient=value['projected_gradient'],
                  iterations=value['iterations'],seconds=value['elapsed_seconds'],bound=value['bound'],
                  numerical_bounds=';'.join(value['numerical_bounds'])))
            v=np.array(winner['parameters']);decoded=model.decode(v)
            for parameter in winner['numerical_bounds']:
                j=model.names.index(parameter);key=parameter.split(':')[0];k=int(parameter.split(':')[1])
                cap_rows.append(dict(step=label,model=name,parameter=parameter,raw_value=float(v[j]),
                  lower=float(lo[j]),upper=float(hi[j]),index_offset=decoded['index_offset'],
                  reported_theta=float(decoded['theta'][k]) if key=='theta' else None))
        json_write(step_dir/'SELECTED_FITS.json',selected)
        sub=report/label;sub.mkdir(exist_ok=True)
        ll,comparisons=summaries(selected,ev,meta,sub)
        for row in comparisons:comparison_rows.append(dict(step=label,**row))
        for name,result in selected.items():
            change=paired(ev,ll[name],original_ll[name],ev['period']==2)
            effect_rows.append(dict(step=label,model=name,J=result['J'],ridge=result['ridge'],
              original_objective=original[name]['objective'],previous_step=previous_label,
              previous_objective=previous[name]['objective'],objective=result['objective'],
              bound=result['bound'],numerical_bounds=';'.join(result['numerical_bounds']),
              source_mean_log_score=reference_scores[name],mean_log_score=float(ll[name][ev['period']==2].mean()),
              gain_vs_original=change['gain'],conditional_se_vs_original=change['conditional_se'],
              equal_account_gain_vs_original=change['equal_account_gain']))
        csv_write(report/'point_training_checks.csv',training_rows)
        csv_write(report/'point_optimizer_attempts.csv',attempt_rows)
        csv_write(report/'point_numerical_parameters.csv',cap_rows)
        csv_write(report/'point_fit_changes.csv',effect_rows)
        csv_write(report/'point_model_comparisons.csv',comparison_rows)
        previous=selected;previous_label=label
    json_write(report/'POINT_STATUS.json',dict(status='COMPUTED_REQUIRES_DIAGNOSTIC_REVIEW',
      bounds=[1,2,4],numerical_bound_models_final=[n for n,r in previous.items() if r['numerical_bounds']],
      source_complexity_unchanged=True,bootstrap_refitted=False,
      note='Polish controls for further optimization at existing bounds. Wider-bound results are sensitivity estimates; source bootstrap intervals cannot be attached to new estimates.'))


def export(report,desktop,runid):
    desktop.mkdir(parents=True,exist_ok=True)
    forbidden={'chooser','chooser_user_id','recipient_id','opponent_id','game_id','username','account_id'}
    for path in report.rglob('*.parquet'):
        require(not forbidden.intersection(pq.read_schema(path).names),'Identifier in aggregate export')
    atomic_text(report/'REPORT_MANIFEST.sha256',''.join(digest(p)+'  '+str(p.relative_to(report))+'\n'
      for p in sorted(report.rglob('*')) if p.is_file() and p.name!='REPORT_MANIFEST.sha256'))
    output=desktop/f'POOL_CHOOSER_BOUND_SENSITIVITY_RESULTS_v100_{runid}.zip'
    part=output.with_suffix('.zip.partial')
    with zipfile.ZipFile(part,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(report.rglob('*')):
            if path.is_file():archive.write(path,'report/'+str(path.relative_to(report)))
    os.replace(part,output);atomic_text(str(output)+'.sha256',digest(output)+'  '+output.name+'\n')
    log('UPLOAD: '+str(output));log('UPLOAD: '+str(output)+'.sha256')


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source-run',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness/output/pool_chooser_followup_v112_1e5c35a1309c0258'))
    ap.add_argument('--output-root',type=Path)
    ap.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    ap.add_argument('--stages',default='audit,point')
    ap.add_argument('--workers',default='auto')
    ap.add_argument('--starts',type=int,default=4)
    ap.add_argument('--maxiter',type=int,default=1200)
    ap.add_argument('--seed',type=int,default=20260923)
    ap.add_argument('--allow-fixture',action='store_true')
    args=ap.parse_args(argv);args.stages=args.stages.split(',')
    require(set(args.stages)<={'audit','point'},'Stages must be audit and/or point')
    require(args.starts>=2 and args.maxiter>=50,'Multiple starts and maxiter>=50 required')
    require(args.workers=='auto' or (args.workers.isdigit() and 1<=int(args.workers)<=10),'Workers must be auto or 1..10')
    code=manifest(PKG,'PACKAGE_MANIFEST.sha256')
    root=args.source_run.expanduser().resolve();lock_path=root/'RUN.lock'
    require(lock_path.is_file(),'Source run lock missing; check mounted drive')
    source_lock=lock_path.open('r')
    try:fcntl.flock(source_lock,fcntl.LOCK_SH|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('Source follow-up is writing; finish it before this sensitivity')
    out_lock=None;report=None;runid=None;owns_output=False
    try:
        with heartbeat('Authenticate completed v1.1.2 and shared arrays'):
            source=authenticate(root,args.allow_fixture)
        config=dict(version='1.0.0',code=code,source_identity=source['identity'],
          source_fits_sha256=source['fits_sha256'],source_report_sha256=digest(root/'report/REPORT_MANIFEST.sha256'),
          seed=args.seed,starts=args.starts,maxiter=args.maxiter,bound_factors=[1,2,4])
        identity=binding(config);runid=identity[:16]+('_fixture' if source['synthetic'] else '')
        out=(args.output_root or root.parent).expanduser().resolve()/('pool_chooser_bounds_v100_'+runid)
        private=out/'PRIVATE';report=out/'report';private.mkdir(parents=True,exist_ok=True);report.mkdir(exist_ok=True)
        out_lock=(out/'RUN.lock').open('a');fcntl.flock(out_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        owns_output=True
        json_write(private/'CONFIG.json',config)
        json_write(report/'LINEAGE.json',dict(config=config,source_run=root.name,
          numerical_threads_per_worker=1,bootstrap_refitted=False,
          note='Source is read only. Only aggregate outputs are exported.'))
        csv_write(report/'source_score_reproduction.csv',source['checks'])
        status=json_read(report/'RUN_STATUS.json') if (report/'RUN_STATUS.json').exists() else {}
        with heartbeat('Audit saved bootstrap flags'):
            checkpoint_hashes=inspect_bootstrap(root,source,report)
        json_write(private/'SOURCE_CHECKPOINT_HASHES.json',checkpoint_hashes)
        status['audit']='COMPLETE_AUTHENTICATED';json_write(report/'RUN_STATUS.json',status)
        export(report,args.desktop,runid)
        if 'point' in args.stages:
            plan=runtime.choose_workers(args.workers,source['mapped'],max(r['J'] for r in source['fits'].values()))
            args.workers=plan['workers'];json_write(report/'WORKER_PLAN.json',plan)
            log('Planning ETA: 15–30 minutes at about three workers; task-based estimates follow')
            status['point']='RUNNING';json_write(report/'RUN_STATUS.json',status)
            with heartbeat('Point estimates: polish, 2x bounds, 4x bounds'):
                point_ladder(source,private,report,args)
            status['point']='COMPUTED_REQUIRES_DIAGNOSTIC_REVIEW'
        status['last_run']='COMPUTATION_OK';json_write(report/'RUN_STATUS.json',status)
        export(report,args.desktop,runid)
        log('COMPUTATION_OK — review cap persistence and prediction stability before further refits')
        return 0
    except Exception as exc:
        if owns_output and report is not None and runid is not None:
            json_write(report/'ERROR.json',dict(error=repr(exc)))
            json_write(report/'RUN_STATUS.json',dict(last_run='FAILED',error=str(exc)))
            export(report,args.desktop,runid)
        log('STOPPED: '+str(exc));return 2
    finally:
        runtime.close_pool()
        if out_lock is not None:out_lock.close()
        source_lock.close()


if __name__=='__main__':sys.exit(main())
