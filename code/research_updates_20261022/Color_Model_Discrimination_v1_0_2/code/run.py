#!/usr/bin/env python3
"""Expected runtime: 10–40 minutes for corrected planning; restart 2–8 minutes."""
from __future__ import annotations
import argparse,fcntl,os,platform,shutil,sys,threading,time,traceback,zipfile
from concurrent.futures import ProcessPoolExecutor,as_completed
from multiprocessing import get_context
from io_utils import *
from inputs import cache_tasks,prepare_month,combine_pre,dependencies,policy_input
from predict import prediction_job
from numeric import LOGISTIC_BACKEND
from inference import summaries,weekly_outcomes,analyze_power,observed_comparison,pre_diagnostics

def verify():
    p=ROOT/'PACKAGE_MANIFEST.sha256'
    for line in p.read_text().splitlines():
        expected,name=line.split('  ',1);f=ROOT/name
        if sha(f)!=expected:raise RuntimeError('Package checksum differs: '+name)
    return sha(p)

def run_jobs(fn,jobs,workers):
    out=[];failures=[]
    with ProcessPoolExecutor(max_workers=workers,mp_context=get_context('spawn')) as pool:
        fs={pool.submit(fn,j):j for j in jobs}
        for f in as_completed(fs):
            try:out.append(f.result())
            except Exception as e:failures.append(dict(job=fs[f],error=str(e),traceback=traceback.format_exc()))
    if failures:raise RuntimeError(json.dumps(clean(failures),indent=2))
    return out

def bundle(report,desktop):
    desktop=Path(desktop);desktop.mkdir(parents=True,exist_ok=True);p=desktop/(report.name+'.zip')
    tmp=p.with_suffix('.partial.zip')
    with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as z:
        for f in sorted(report.rglob('*')):
            if f.is_file():z.write(f,report.name+'/'+str(f.relative_to(report)))
    os.replace(tmp,p);text(Path(str(p)+'.sha256'),sha(p)+'  '+p.name+'\n')
    log('RESULT_TO_UPLOAD '+str(p));return p

def report_markdown(report,status,pred=None,power=None):
    lines=['# Corrected color-model prediction and power result','',f"Status: **{status['status']}**.",'',
      'The repaired RD audit is reused. No model refit, rating replay, identity recovery, API request, or engine evaluation was performed.','',
      'All figures below use probabilities after logistic conversion. The fitted parameters themselves are index coefficients. No mechanism shares or causal cost elasticities are released.','']
    if pred is not None and not pred.empty:
        z=pred[(pred.fit_stage=='full')&(pred.period=='unannounced')]
        lines+=['## Full fitted-model predictions','',
          '| Target | Model | White shift, pp | Black shift, pp | White-minus-Black shift, pp |',
          '|---|---|---:|---:|---:|']
        for r in z.to_dict('records'):
            lines.append(f"| {r['target']} | {r['model']} | {r['white_shift_pp']:.5f} | {r['black_shift_pp']:.5f} | {r['prediction_pp']:.5f} |")
        lines+=['','The pre-policy transport is a planning calculation on capped regular-player opportunities. It is not an estimate of behavior after November 18. Forward-fit ranges are sensitivity checks, not prediction confidence intervals.','']
    if power is not None and not power.empty:
        z=power[['actual_frozen_cohort','period','post_weeks','block_weeks','mde_negative_pp','mde_positive_pp']].drop_duplicates()
        lines+=['## Calendar-matched noise','',
          '| Actual target? | Window | Post weeks | Block weeks | Negative MDE, pp | Positive MDE, pp |',
          '|---|---|---:|---:|---:|---:|']
        for r in z.to_dict('records'):
            lines.append(f"| {r['actual_frozen_cohort']} | {r['period']} | {r['post_weeks']} | {r['block_weeks']} | {r['mde_negative_pp']:.5f} | {r['mde_positive_pp']:.5f} |")
        lines+=['','Power is conditional on the fitted parameters, baseline calibration and a stationary pre-period block process. The bootstrap preserves the omitted transition weeks and the announcement delay. The planning calendar ending before January 30 is a scenario, not a certified censor.','']
    lines+=['## Interpretation and remaining dependencies','',
       '- Effective updating is a scenario, not observed awareness.',
       '- Parameter uncertainty is not propagated. No automatic GO, unconditional mechanism rejection, or preference bound is issued.',
       '- Focus pairwise power on both_models_pre_policy_compatible=True; discrimination from already-disfavored benchmark models does not separate the surviving explanations.',
       '- Conditional grant rates also require an entry/denominator check before a causal reading.',
       '- Default auto mode stops after predictions and power, even with an accepted actual cohort. A descriptive post statistic requires an explicit --phase behavior run after reviewing that output.',
       '- If the actual policy adapter is absent or invalid, the runner completes corrected planning and records the exact dependency in POST_INPUT_STATUS.json. It never substitutes the earlier all-source cohort.',
       '- The existing zero-failure repaired audit needs no further numerical repair.',
       '',f"Actual post-policy statistic released: {status.get('actual_post_statistic_released',False)}.",
       f"Elapsed minutes: {status.get('elapsed_seconds',0)/60:.1f}."]
    text(report/'READ_ME_FIRST.md','\n'.join(lines)+'\n')

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    ap.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    ap.add_argument('--workers',type=int,default=10)
    ap.add_argument('--memory-gb',type=float,default=12.)
    ap.add_argument('--phase',choices=('auto','planning','behavior'),default='auto')
    ap.add_argument('--policy-manifest',type=Path)
    ap.add_argument('--bootstrap-reps',type=int,default=10000)
    a=ap.parse_args()
    if not 1<=a.workers<=10 or not 4<=a.memory_gb<=48:ap.error('Use 1–10 workers and 4–48 GB memory budget')
    if a.bootstrap_reps<2000:ap.error('At least 2000 block repetitions')
    project=a.project_root.expanduser().resolve()
    if not project.is_dir():ap.error('Mount the project volume first')
    package_hash=verify();work=project/'derived/replication_36m/color_model_discrimination_v100_PRIVATE'
    work.mkdir(parents=True,exist_ok=True);lock=open(work/'run.lock','a+')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit('A color-model run is already active; no second writer started')
    source_lock_path=project/'derived/replication/mechanism_separation_v100_PRIVATE/run.lock'
    source_lock=None
    if source_lock_path.exists():
        source_lock=open(source_lock_path,'r')
        try:fcntl.flock(source_lock,fcntl.LOCK_SH|fcntl.LOCK_NB)
        except BlockingIOError:raise SystemExit('The mechanism source cache is being written; retry after that job finishes')
    identity=dict(version=VERSION,package_sha256=package_hash,project=str(project),bootstrap_reps=a.bootstrap_reps)
    ip=work/'RUN_IDENTITY.json'
    if ip.exists() and read(ip)!=identity:raise RuntimeError('Existing color-model cache has different scientific settings')
    write(ip,identity);stamp_utc=pd.Timestamp.now(tz='UTC').strftime('%Y%m%dT%H%M%S%fZ')
    report=work/'reports'/('COLOR_MODEL_RESULT_'+stamp_utc);report.mkdir(parents=True)
    shutil.copyfile(ROOT/'FROZEN_PLAN.json',report/'FROZEN_PLAN.json')
    shutil.copyfile(ROOT/'authority/SUMMARY.json',report/'REPAIRED_AUDIT_STATUS.json')
    shutil.copyfile(ROOT/'authority/MODEL_COMPARISON_STATUS.json',report/'REPAIRED_MODEL_COMPATIBILITY.json')
    start=time.monotonic();stop=threading.Event();error=None;pred=None;power=None
    status=dict(status='RUNNING',version=VERSION,actual_post_statistic_released=False,
       mechanism_shares_released=False,upstream_rebuilt=False,refits_run=False,parameter_uncertainty_propagated=False)
    def heartbeat():
        while not stop.wait(45):log(f'Color-model run working; elapsed {(time.monotonic()-start)/60:.1f} minutes')
    threading.Thread(target=heartbeat,daemon=True).start()
    try:
        inventory=dependencies(project,work,a.policy_manifest);write(report/'INPUT_INVENTORY.json',inventory)
        # Independent monthly scans use ten processes; larger forecast jobs are RAM bounded.
        prep_workers=min(a.workers,10);memory=int(a.memory_gb*1024)
        records=run_jobs(prepare_month,cache_tasks(project,work,max(384,memory//prep_workers)),prep_workers)
        table([dict(month=r['month'],rows=r['rows'],grants=r['grants']) for r in records],report/'capped_monthly_counts.parquet')
        training=combine_pre(work,a.workers,memory)
        post=None;post_status=dict(status='MISSING_ACTUAL_TARGET_INPUTS',**inventory)
        if inventory['exists'] and a.phase!='planning':
            try:
                post=policy_input(inventory['manifest_path'],work,a.workers,memory)
                post_status=dict(status='ACTUAL_TARGET_INPUTS_ACCEPTED',**post)
            except Exception as exc:
                post_status=dict(status='ACTUAL_TARGET_NOT_ACCEPTED',reason=str(exc),manifest=inventory['manifest_path'])
                log('Actual target unresolved; corrected planning continues: '+str(exc))
        write(report/'POST_INPUT_STATUS.json',post_status)
        tasks=[];target_specs=[('planning',str(training),int(pd.Timestamp('2023-11-01',tz='UTC').timestamp()*1000),int(pd.Timestamp('2025-11-01',tz='UTC').timestamp()*1000),False)]
        if post:target_specs.append(('actual',post['path'],post['coverage_start_ms'],post['coverage_end_ms'],True))
        for label,target,lo,hi,actual in target_specs:
            for model in MODELS:
                stages=('full','fold0','fold1') if model in ('framing','curved','strength') else ('full',)
                for stage in stages:tasks.append((str(training),target,str(ROOT/'authority/fits'/f'{model}_{stage}.json'),model,stage,label,str(work),package_hash))
        pred_workers=min(a.workers,max(1,int(a.memory_gb/2.0)),len(tasks))
        log(f'Forecasts: {pred_workers} parallel workers, bounded by {a.memory_gb:g} GB budget; monthly reads used {prep_workers}')
        results=run_jobs(prediction_job,tasks,pred_workers)
        write(report/'PREDICTION_RECEIPTS.json',results)
        all_pred=[];all_power=[]
        for label,target,lo,hi,actual in target_specs:
            paths=[Path(r['output']['path']) for r in results if r['target']==label]
            pp,spec=summaries(paths,lo,hi,actual);all_pred.append(pp)
            table(pp,report/f'{label}_model_predictions.parquet')
            weekly=weekly_outcomes(target,work,min(hi,IMPLEMENTED));table(weekly,report/f'{label}_pre_weekly_rates.parquet')
            pr=report/label;pr.mkdir(exist_ok=True)
            pre_diagnostics(weekly,spec,lo,hi,pr)
            ppow,nulls,_=analyze_power(weekly,pp,spec,lo,hi,pr,a.bootstrap_reps);all_power.append(ppow)
            table(ppow,report/f'{label}_pairwise_power.parquet')
            write(report/f'{label}_SEALED_PREDICTIONS_AND_POWER.json',dict(predictions_sha256=sha(report/f'{label}_model_predictions.parquet'),
                power_sha256=sha(report/f'{label}_pairwise_power.parquet'),post_statistic_not_yet_computed=True))
            if actual and a.phase=='behavior':
                observed_comparison(target,work,spec,pp,nulls,report);status['actual_post_statistic_released']=True
        pred=pd.concat(all_pred,ignore_index=True);power=pd.concat(all_power,ignore_index=True)
        table(pred,report/'all_model_predictions.parquet');table(power,report/'all_pairwise_power.parquet')
        sensitivities=pred.pivot_table(index=['target','period','model'],columns='fit_stage',values='prediction_pp').reset_index()
        sensitivities['interpretation']='Training-fit sensitivity; NOT a confidence interval'
        table(sensitivities,report/'forward_fit_sensitivity.parquet')
        status['status']='CORRECTED_PLANNING_COMPLETE_WITH_OPEN_POST_DEPENDENCIES' if not post else ('CONDITIONAL_POLICY_COMPARISON_COMPLETE' if a.phase=='behavior' else 'ACTUAL_COHORT_PREDICTION_POWER_COMPLETE')
        if a.phase=='behavior' and not post:status['requested_behavior_unavailable']=True
    except Exception as exc:
        error=exc;status.update(status='FAILED_WITH_COMPLETED_STAGES_PRESERVED',error=str(exc))
        text(report/'ERROR.txt',traceback.format_exc())
    finally:
        status['elapsed_seconds']=time.monotonic()-start
        write(report/'SUMMARY.json',status);write(report/'ENVIRONMENT.json',dict(python=sys.version,python_executable=sys.executable,platform=platform.platform(),logistic_backend=LOGISTIC_BACKEND,
             numpy=np.__version__,pandas=pd.__version__,duckdb=duckdb.__version__,workers=a.workers,memory_gb=a.memory_gb,package_sha256=package_hash))
        report_markdown(report,status,pred,power)
        stop.set();bundle(report,a.desktop);fcntl.flock(lock,fcntl.LOCK_UN);lock.close()
        if source_lock:fcntl.flock(source_lock,fcntl.LOCK_UN);source_lock.close()
    if error:raise SystemExit('Run stopped; upload the result ZIP for the exact failure. Completed stages are preserved.')
    log('OK — '+status['status'])

if __name__=='__main__':main()
