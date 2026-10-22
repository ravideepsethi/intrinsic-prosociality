#!/usr/bin/env python3
"""Paired account bootstrap of four headline models at fixed 4x numerical bounds."""
from __future__ import annotations
import os
for _key in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS',
             'VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS','NUMBA_NUM_THREADS']:
    os.environ[_key]='1'
import argparse, fcntl, sys, time, zipfile
from pathlib import Path
PKG=Path(__file__).resolve().parent
sys.path.insert(0,str(PKG/'reference_bounds'))
import run_bounds as reference
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.optimize import linear_sum_assignment
from engine import Model,fit,predict,transfer,parameters,Spec
import followup_analysis as analysis
from followup_diagnostics import pairs_for
from diagnostics import paired
from io_utils import binding,digest,json_read,json_write,atomic_text,require,log,heartbeat
from table_io import csv_write
import runtime

MODELS=['level','desert','cost','both']


class RefitFailure(RuntimeError):
    def __init__(self,message,attempts,witness):
        super().__init__(message);self.attempts=attempts;self.witness=witness


def fixed_refit(train,template,narrow,auxiliary,meta,seed,starts,maxiter):
    """Fixed domain: never automatically double a bound because a template is capped."""
    model=Model(template['spec'],template['J'],meta,template['bound'])
    lo,hi=np.array(model.bounds).T
    warm=[('wide_point',np.array(template['parameters'])),('original_point',np.array(narrow['parameters']))]
    warm += [('independent_'+str(j),model.start(seed+j)) for j in range(1,starts)]
    warm += [(label,transfer(value,model,meta,seed)) for label,value in auxiliary]
    attempts=[];witness=[]
    for j,(label,value) in enumerate(warm):
        require(np.all(value>=lo-1e-10) and np.all(value<=hi+1e-10),'Warm point outside fixed numerical bounds')
        witness.append(dict(start=label,objective=float(model.objective(value,train,template['ridge'])[0])))
        estimate=fit(train,Spec(**template['spec']),template['J'],meta,seed+j,maxiter,
                     template['ridge'],template['bound'],value)
        estimate['start_label']=label;attempts.append(estimate)
    try:
        winner=analysis.best(attempts)
        require(winner['objective']<=min(x['objective'] for x in witness)+1e-8,
                'Best converged wider-bound refit is worse than a supplied feasible start')
    except RuntimeError as exc:
        raise RefitFailure(str(exc),attempts,witness) from exc
    return winner,attempts,witness


def bootstrap_one(task):
    rep,wide_all,narrow_all,settings,original_path,path=task
    signature=binding(dict(rep=rep,wide=wide_all,narrow=narrow_all,settings=settings,
                           original_checkpoint_sha256=digest(original_path)))
    def compute():
        started=time.monotonic();_,ev,meta=analysis.data_for('core')
        train=dict(analysis.training_for('core'))
        rng=np.random.default_rng(settings['seed']+99173*rep)
        n=len(train['ptr'])-1;m=len(ev['ptr'])-1
        train['aw']=rng.multinomial(n,np.ones(n)/n).astype(float)
        ew=rng.multinomial(m,np.ones(m)/m).astype(float)
        original=json_read(original_path)['result']
        old={(x['candidate'],x['baseline']):x for x in original['rows']}
        estimates={};attempts={};witness={};failures={};scores={};cap_rows=[];type_rows=[]
        source_order=analysis.fit_order(narrow_all)
        templates={name:wide_all[name] for name in MODELS}
        for name in analysis.fit_order(templates):
            template=templates[name];j=source_order.index(name)
            available=dict(wide_all);available.update(estimates)
            aux=[('from_'+source+('_refit' if source in estimates else '_fixed_point'),value)
                 for source,value in analysis.compatible_sources(name,template,available)]
            try:
                result,trials,feasible=fixed_refit(train,template,narrow_all[name],aux,meta,
                  settings['seed']+rep*1000+j*10,settings['starts'],settings['maxiter'])
                estimates[name]=result;attempts[name]=trials;witness[name]=feasible
                scores[name]=predict(result,ev,meta)[1]
                model=Model(result['spec'],result['J'],meta,result['bound'])
                vector=np.array(result['parameters']);decoded=model.decode(vector)
                for parameter in result['numerical_bounds']:
                    k=model.names.index(parameter);key=parameter.split(':')[0];type_id=int(parameter.split(':')[1])
                    cap_rows.append(dict(rep=rep,model=name,parameter=parameter,raw_value=float(vector[k]),
                      lower=model.bounds[k][0],upper=model.bounds[k][1],index_offset=decoded['index_offset'],
                      reported_theta=float(decoded['theta'][type_id]) if key=='theta' else None))
                tm=Model(template['spec'],template['J'],meta,template['bound'])
                target=tm.decode(np.array(template['parameters']))
                distance=((target['effect'][:,None,meta['support']]-decoded['effect'][None,:,meta['support']])**2).mean(axis=2)
                distance+=(target['alpha'][:,None]-decoded['alpha'][None,:])**2
                aa,bb=linear_sum_assignment(distance)
                for a,b in zip(aa,bb):
                    type_rows.append(dict(rep=rep,model=name,reference_type=int(a),
                      alpha=float(decoded['alpha'][b]),theta=float(decoded['theta'][b]),
                      raw_theta=float(decoded['raw_theta'][b]),index_offset=decoded['index_offset'],
                      share=float(np.exp(decoded['lp'][:,b]).mean()),premium=float(decoded['B'][b,0]/10),
                      loss=float(decoded['B'][b,1]/10)))
            except RuntimeError as exc:
                failures[name]=str(exc)
                estimates.pop(name,None);scores.pop(name,None)
                if isinstance(exc,RefitFailure):
                    attempts[name]=exc.attempts;witness[name]=exc.witness
        rows=[]
        for a,b in pairs_for(templates):
            previous=old[(a,b)];gain=equal=None
            if a in scores and b in scores:
                stat=paired(ev,scores[a],scores[b],ev['period']==2,ew)
                gain=stat['gain'];equal=stat['equal_account_gain']
            rows.append(dict(rep=rep,candidate=a,baseline=b,gain=gain,equal_account_gain=equal,
              original_gain=previous['gain'],original_equal_account_gain=previous['equal_account_gain'],
              change_vs_original=None if gain is None or previous['gain'] is None else gain-previous['gain'],
              candidate_capped=bool(estimates.get(a,{}).get('numerical_bounds')),
              baseline_capped=bool(estimates.get(b,{}).get('numerical_bounds'))))
        return dict(rep=rep,rows=rows,fits=estimates,attempts=attempts,feasible_starts=witness,
          failures=failures,numerical_parameters=cap_rows,parameter_draws=type_rows,
          resample_weights_sha256=binding(dict(development=train['aw'].astype(int).tolist(),evaluation=ew.astype(int).tolist())),
          elapsed_seconds=time.monotonic()-started)
    return analysis.safe_result(path,signature,compute)


def aggregate(results,point,report):
    rows=[row for value in results for row in value['rows']]
    summary=[]
    for a,b in sorted({(x['candidate'],x['baseline']) for x in rows}):
        all_pair=[x for x in rows if x['candidate']==a and x['baseline']==b]
        good=[x for x in all_pair if x['gain'] is not None]
        v=np.array([x['gain'] for x in good]);eq=np.array([x['equal_account_gain'] for x in good])
        paired_rows=[x for x in good if x['change_vs_original'] is not None]
        change=np.array([x['change_vs_original'] for x in paired_rows])
        initial=point[(point.candidate==a)&(point.baseline==b)].iloc[0]
        interval=lambda values,q:float(np.quantile(values,q)) if len(values)>=100 else None
        summary.append(dict(candidate=a,baseline=b,requested=len(all_pair),converged_pairs=len(v),
          failures=len(all_pair)-len(v),wide_point_gain=float(initial.gain),
          bootstrap_mean=float(v.mean()) if len(v) else None,
          bootstrap_se=float(v.std(ddof=1)) if len(v)>1 else None,
          percentile_low=interval(v,.025),percentile_high=interval(v,.975),
          equal_account_low=interval(eq,.025),equal_account_high=interval(eq,.975),
          positive_draws=int((v>0).sum()),capped_pairs=sum(x['candidate_capped'] or x['baseline_capped'] for x in good),
          paired_original_draws=len(change),mean_change_vs_original=float(change.mean()) if len(change) else None,
          change_low=interval(change,.025),change_high=interval(change,.975),
          interval_status='AVAILABLE_CONDITIONAL_ON_SUCCESSFUL_REFITS' if len(v)>=100 else 'WITHHELD_FEWER_THAN_100'))
    model_rows=[];guards=[];attempt_rows=[]
    for name in MODELS:
        valid=[r['fits'][name] for r in results if name in r['fits']]
        model_rows.append(dict(model=name,requested=len(results),successful=len(valid),failed=len(results)-len(valid),
          capped=sum(bool(f['numerical_bounds']) for f in valid),
          max_projected_gradient=max([f['projected_gradient'] for f in valid],default=None)))
    for r in results:
        for name,trials in r['attempts'].items():
            for t in trials:
                attempt_rows.append(dict(rep=r['rep'],model=name,start=t['start_label'],success=t['success'],
                  objective=t['objective'],bound=t['bound'],iterations=t['iterations'],seconds=t['elapsed_seconds'],
                  projected_gradient=t['projected_gradient'],numerical_bounds=';'.join(t['numerical_bounds'])))
            for f in r['feasible_starts'][name]:
                if name not in r['fits']:continue
                delta=r['fits'][name]['objective']-f['objective']
                guards.append(dict(rep=r['rep'],model=name,start=f['start'],after_minus_feasible=delta,violation=delta>1e-8))
    for filename,data in [('refit_bootstrap_draws',rows),('refit_bootstrap_summary',summary),
      ('refit_model_status',model_rows),('refit_training_checks',guards),('refit_optimizer_attempts',attempt_rows),
      ('refit_failures',[dict(rep=r['rep'],model=n,error=e) for r in results for n,e in r['failures'].items()]),
      ('refit_numerical_parameters',[x for r in results for x in r['numerical_parameters']]),
      ('refit_parameter_draws',[x for r in results for x in r['parameter_draws']])]:
        csv_write(report/(filename+'.csv'),data)
    json_write(report/'BOOTSTRAP_STATUS.json',dict(requested=len(results),
      failed_replications=sum(bool(r['failures']) for r in results),
      capped_replications=sum(any(f['numerical_bounds'] for f in r['fits'].values()) for r in results),
      fixed_bounds=True,all_draws_retained=True,point_models=MODELS,
      note='Same source account resamples. Four headline models refitted with fixed 4x bounds; numerical caps retained and reported. No automatic bound expansion. Intervals are marginal and conditional on successful fits and frozen model complexity.'))


def export(report,desktop,runid):
    desktop.mkdir(parents=True,exist_ok=True)
    forbidden={'chooser','chooser_user_id','recipient_id','opponent_id','game_id','username','account_id'}
    for p in report.rglob('*.parquet'):
        require(not forbidden.intersection(pq.read_schema(p).names),'Identifier in aggregate export')
    atomic_text(report/'REPORT_MANIFEST.sha256',''.join(digest(p)+'  '+str(p.relative_to(report))+'\n'
      for p in sorted(report.rglob('*')) if p.is_file() and p.name!='REPORT_MANIFEST.sha256'))
    path=desktop/f'POOL_CHOOSER_WIDE_BOOTSTRAP_RESULTS_v100_{runid}.zip';part=path.with_suffix('.zip.partial')
    with zipfile.ZipFile(part,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(report.rglob('*')):
            if p.is_file():z.write(p,'report/'+str(p.relative_to(report)))
    os.replace(part,path);atomic_text(str(path)+'.sha256',digest(path)+'  '+path.name+'\n')
    log('UPLOAD: '+str(path));log('UPLOAD: '+str(path)+'.sha256')


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source-run',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness/output/pool_chooser_followup_v112_1e5c35a1309c0258'))
    ap.add_argument('--bounds-run',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness/output/pool_chooser_bounds_v100_f14e1be2f5314f2e'))
    ap.add_argument('--output-root',type=Path)
    ap.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    ap.add_argument('--workers',default='auto');ap.add_argument('--bootstrap-refits',type=int,default=120)
    ap.add_argument('--starts',type=int,default=4);ap.add_argument('--maxiter',type=int,default=1200)
    ap.add_argument('--allow-fixture',action='store_true')
    args=ap.parse_args(argv)
    require(args.starts>=2 and args.maxiter>=50 and args.bootstrap_refits>=1,'Invalid fit budget')
    require(args.workers=='auto' or (args.workers.isdigit() and 1<=int(args.workers)<=10),'Workers must be auto or 1..10')
    code=reference.manifest(PKG,'PACKAGE_MANIFEST.sha256')
    source_root=args.source_run.expanduser().resolve();bounds_root=args.bounds_run.expanduser().resolve()
    locks=[];report=None;owns_output=False;runid=None
    try:
        for root in [source_root,bounds_root]:
            require((root/'RUN.lock').is_file(),'Source run missing: '+str(root))
            lock=(root/'RUN.lock').open('r');locks.append(lock)
            fcntl.flock(lock,fcntl.LOCK_SH|fcntl.LOCK_NB)
        with heartbeat('Authenticate completed runs and numeric maps'):
            source=reference.authenticate(source_root,args.allow_fixture)
            reference.manifest(bounds_root/'report','REPORT_MANIFEST.sha256')
            lineage=json_read(bounds_root/'report/LINEAGE.json');bc=lineage['config']
            require(bc['code']==reference.manifest(PKG/'reference_bounds','PACKAGE_MANIFEST.sha256'),
                    'Bound run producer differs from bundled reference')
            require(bc['source_identity']==source['identity'] and bc['source_fits_sha256']==source['fits_sha256'],
                    'Bound run uses a different source estimator')
            require(bc['source_report_sha256']==digest(source_root/'report/REPORT_MANIFEST.sha256'),
                    'Completed original report changed since the bound run')
            expected='pool_chooser_bounds_v100_'+binding(bc)[:16]+('_fixture' if source['synthetic'] else '')
            require(bounds_root.name==expected,'Bound run identity mismatch')
            require(json_read(bounds_root/'report/RUN_STATUS.json').get('last_run')=='COMPUTATION_OK','Bound run incomplete')
            wide=json_read(bounds_root/'PRIVATE/bounds_x4/SELECTED_FITS.json')
            require(set(wide)==set(source['fits']),'Wide point-fit inventory differs')
            _,ev,meta=analysis.data_for('core');public=pd.read_parquet(bounds_root/'report/bounds_x4/scores.parquet')
            checks=[]
            for name,r in wide.items():
                narrow=source['fits'][name]
                require(r['spec']==narrow['spec'] and r['J']==narrow['J'] and r['ridge']==narrow['ridge'],
                        'Model complexity changed in bound run')
                require(r['bound']==4*narrow['bound'] and r['success'],'Expected converged fixed 4x point fit')
                score=float(predict(r,ev,meta)[1][ev['period']==2].mean())
                tab=public[(public.model==name)&(public.group=='all')];require(len(tab)==1,'Missing wide public score')
                error=abs(score-float(tab.iloc[0].mean_log_score));require(error<1e-10,'Wide private/public score mismatch')
                checks.append(dict(model=name,absolute_difference=error,bound=r['bound']))
        original_status=json_read(source_root/'report/repair/BOOTSTRAP_STATUS.json')
        require(args.bootstrap_refits<=original_status['requested'],'Only existing paired source resamples are allowed')
        settings=dict(seed=source['config']['settings']['seed']+913,starts=args.starts,maxiter=args.maxiter)
        config=dict(version='1.0.0',code=code,source_identity=source['identity'],bounds_identity=binding(bc),
          source_report_sha256=digest(source_root/'report/REPORT_MANIFEST.sha256'),
          bounds_report_sha256=digest(bounds_root/'report/REPORT_MANIFEST.sha256'),
          wide_fits_sha256=digest(bounds_root/'PRIVATE/bounds_x4/SELECTED_FITS.json'),models=MODELS,settings=settings)
        runid=binding(config)[:16]+('_fixture' if source['synthetic'] else '')
        root=(args.output_root or source_root.parent).expanduser().resolve()/('pool_chooser_wide_bootstrap_v100_'+runid)
        private=root/'PRIVATE';report=root/'report';private.mkdir(parents=True,exist_ok=True);report.mkdir(exist_ok=True)
        lock=(root/'RUN.lock').open('a');locks.append(lock);fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);owns_output=True
        json_write(private/'CONFIG.json',config);json_write(report/'LINEAGE.json',config)
        with heartbeat('Authenticate original bootstrap checkpoints'):
            hashes=reference.inspect_bootstrap(source_root,source,report)
        json_write(private/'SOURCE_CHECKPOINT_HASHES.json',hashes)
        csv_write(report/'wide_point_score_reproduction.csv',checks)
        point=pd.read_parquet(bounds_root/'report/bounds_x4/comparisons.parquet')
        point=point[point.candidate.isin(MODELS)&point.baseline.isin(MODELS)]
        csv_write(report/'wide_point_comparisons.csv',point)
        source_boot=pd.read_parquet(source_root/'report/repair/refit_bootstrap_summary.parquet')
        csv_write(report/'original_bootstrap_summary.csv',source_boot[source_boot.candidate.isin(MODELS)&source_boot.baseline.isin(MODELS)])
        csv_write(report/'fixed_numerical_domains.csv',[dict(model=n,bound=wide[n]['bound'],J=wide[n]['J'],
          ridge=wide[n]['ridge'],point_cap=';'.join(wide[n]['numerical_bounds'])) for n in MODELS])
        plan=runtime.choose_workers(args.workers,source['mapped'],max(wide[n]['J'] for n in MODELS))
        json_write(report/'WORKER_PLAN.json',plan)
        folder=private/'bootstrap';folder.mkdir(exist_ok=True)
        jobs=[(r,wide,source['fits'],settings,str(source_root/f'PRIVATE/repair/core/bootstrap/rep_{r:04d}.json'),
               str(folder/f'rep_{r:04d}.json')) for r in range(args.bootstrap_refits)]
        json_write(report/'RUN_STATUS.json',dict(audit='COMPLETE_AUTHENTICATED',bootstrap='RUNNING'))
        export(report,args.desktop,runid)
        log('Planning ETA: 4–8 hours for 120 draws at three workers; wide-bound convergence may take longer')
        # The existing scheduler recognizes bootstrap_one by name but assumes its
        # old tuple layout for its initial timing heuristic. Use a wrapper name;
        # task-based ETAs and all cache checks remain unchanged.
        with heartbeat('Fixed wide-bound paired bootstrap'):
            results=runtime.execute(jobs,wide_task,source['design'],plan['workers'],'wide paired refits',analysis.initialize)
        aggregate(results,point,report)
        (report/'ERROR.json').unlink(missing_ok=True)
        json_write(report/'RUN_STATUS.json',dict(audit='COMPLETE_AUTHENTICATED',
          bootstrap='COMPUTED_REQUIRES_DIAGNOSTIC_REVIEW',last_run='COMPUTATION_OK'))
        export(report,args.desktop,runid);log('COMPUTATION_OK — review paired interval changes, failures and remaining caps')
        return 0
    except Exception as exc:
        if owns_output:
            json_write(report/'ERROR.json',dict(error=repr(exc)))
            json_write(report/'RUN_STATUS.json',dict(last_run='FAILED',error=str(exc)))
            export(report,args.desktop,runid)
        log('STOPPED: '+str(exc));return 2
    finally:
        runtime.close_pool()
        for lock in reversed(locks):lock.close()


def wide_task(task):
    return bootstrap_one(task)


if __name__=='__main__':sys.exit(main())
