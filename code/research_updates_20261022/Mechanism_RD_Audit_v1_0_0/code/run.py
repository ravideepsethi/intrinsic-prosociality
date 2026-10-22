#!/usr/bin/env python3
"""Targeted RD influence check from the completed mechanism cache."""
import os
for _k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS','NUMBA_NUM_THREADS'):
    os.environ[_k]='1'
import argparse,fcntl,multiprocessing,platform,shutil,threading,traceback,zipfile
from datetime import datetime,timezone
from concurrent.futures import ProcessPoolExecutor,wait,FIRST_COMPLETED
from common import *
from inputs import authenticate_source,prepare_state,STATES
from analysis import run_model,unrestricted_task,MODELS
from reporting import assemble

def verify_package():
    p=ROOT/'PACKAGE_MANIFEST.sha256'
    for line in p.read_text().splitlines():
        expected,name=line.split('  ',1)
        if sha(ROOT/name)!=expected:raise RuntimeError('Package integrity failed: '+name)
    return sha(p)

def parallel(function,tasks,workers):
    if workers==1:return [function(t) for t in tasks]
    tasks=iter(tasks);results=[]
    executor=ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('spawn'))
    pending=set()
    try:
        for _ in range(workers):
            try:pending.add(executor.submit(function,next(tasks)))
            except StopIteration:break
        while pending:
            complete,pending=wait(pending,return_when=FIRST_COMPLETED)
            for f in complete:
                results.append(f.result())
                try:pending.add(executor.submit(function,next(tasks)))
                except StopIteration:pass
        return results
    finally:executor.shutdown(wait=True,cancel_futures=True)

def archive(report,desktop):
    desktop=Path(desktop);desktop.mkdir(parents=True,exist_ok=True)
    out=desktop/(report.name+'.zip');partial=out.with_suffix('.partial.zip')
    with zipfile.ZipFile(partial,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(report.rglob('*')):
            if p.is_file():z.write(p,report.name+'/'+p.relative_to(report).as_posix())
    os.replace(partial,out);text(Path(str(out)+'.sha256'),sha(out)+'  '+out.name+'\n')
    log('RESULT_TO_UPLOAD '+str(out));return out

def note(status):
    return f'''# RD influence audit\n\nStatus: **{status['status']}**.\n\nThis is the original regular-player definition, compared with the same definition plus both pregame RDs <=110. Roughly-equal positions are primary; clearly-losing positions are supporting.\n\nRead support and account-retention tables first. `model_comparisons` contains original-training/original-test, original-training/capped-test, and capped-training/capped-test comparisons. `same_test_refitting_summary` isolates how refitting changes predictions on the same capped validation rows. Conditional scores measure allocation within chooser-month groups, not marginal grant-rate forecasting.\n\n`conditional_score_diagnostics` reports exact centered scores and regressor sums of squares across retained/removed RD classes, not causal or Fisher-information shares. `common_index_profiles` uses identical standardization rows and index units. `heldout_gap_calibration` compares observed and predicted conditional allocation on identical rows; held-out group grant totals are conditioned on.\n\n`coefficients` marks constrained boundaries explicitly. No ordinary Wald inference is assigned to boundary models. `unrestricted` contains diagnostic sign-relaxed fits; these are excluded from the seven-candidate selection rule. Covariances and fit diagnostics are exported without account IDs.\n\nThe prior cost-table grant-count error is corrected in `prior_reporting_corrections`, leaving those coefficients unchanged. The prior M2 figure combines coincident curves without shifting their values. It is not an observed-LPM versus model comparison.\n\nThis run performs no history reconstruction, Glicko replay, identity recovery, API collection, Stockfish work, new recoverability simulation, historical-cue test, or post-policy behavioral estimate. It releases no mechanism shares or causal cost bounds. Existing caches are read only. New private fit files are saved separately for restart.\n'''

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    ap.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    ap.add_argument('--workers',type=int,default=10)
    ap.add_argument('--fit-workers',type=int,default=2)
    ap.add_argument('--memory-gb',type=float,default=6.)
    a=ap.parse_args()
    if not 1<=a.workers<=10 or not 1<=a.fit_workers<=2 or not 2<=a.memory_gb<=12:
        ap.error('Use 1-10 preparation threads, 1-2 fit workers, and 2-12 GB DuckDB memory')
    project=a.project_root.expanduser().resolve()
    if not project.is_dir():ap.error('XT_Pro project directory missing')
    code=verify_package();reference=read(ROOT/'authority/reference.json')
    source=project/'derived/replication/mechanism_separation_v100_PRIVATE'
    work=project/'derived/replication/mechanism_rd_audit_v100_PRIVATE';work.mkdir(parents=True,exist_ok=True)
    lock=open(work/'run.lock','a+')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit('This RD audit is already running')
    original_lock=None
    if (source/'run.lock').exists():
        original_lock=open(source/'run.lock','r')
        try:fcntl.flock(original_lock,fcntl.LOCK_SH|fcntl.LOCK_NB)
        except BlockingIOError:raise SystemExit('The original mechanism run is still writing; let it finish first')
    public=work/'public_results';public.mkdir(exist_ok=True)
    start=time.monotonic();stop=threading.Event()
    def heartbeat():
        while not stop.wait(45):log(f'RD audit working; elapsed {(time.monotonic()-start)/60:.1f} minutes')
    threading.Thread(target=heartbeat,daemon=True).start()
    status=dict(status='RUNNING',version='1.0.0',source_cache=str(source),new_cache=str(work),
        source_result_sha256=reference['source_result_sha256'],upstream_stages_rebuilt=False,
        new_simulations_run=False,mechanism_shares_released=False,post_policy_outcomes_used=False)
    error=None
    try:
        paths,ledger=authenticate_source(source,work,reference)
        # Freeze every legacy fit file as well as the monthly prepared rows.
        model_ledger=[]
        for state in STATES:
            for model in MODELS:
                for suffix in ('','_fold0','_fold1'):
                    p=source/'models'/('regular_'+state+'_'+model+suffix+'.json')
                    r=auth(p,work);model_ledger.append(dict(path=str(p),sha256=r['sha256']))
        identity=dict(package_sha256=code,source_prepared=ledger,source_models=model_ledger,
            source_result_sha256=reference['source_result_sha256'],states=list(STATES))
        if (work/'RUN_IDENTITY.json').exists() and read(work/'RUN_IDENTITY.json')!=identity:
            raise RuntimeError('Scientific inputs changed; do not mix this audit with its existing cache')
        write(work/'RUN_IDENTITY.json',identity);run_key=digest(identity)
        table(ledger+model_ledger,public/'input_checksums.parquet')
        prepared={}
        for state in STATES:
            k=digest(dict(run=run_key,state=state))
            prepared[state]=prepare_state(paths,state,work,public,k,min(a.workers,8),int(a.memory_gb*1024))
            actual=prepared[state]['cohorts']['original']['meta'];expected=reference['states'][state]
            for name in ('n','grants','accounts'):
                if actual[name]!=expected[name]:raise RuntimeError('Original sample does not match reviewed result: '+str((state,name)))
        tasks=[(s,m,prepared[s],str(source),str(work),str(public),reference,run_key) for s in STATES for m in MODELS]
        model_status=parallel(run_model,tasks,min(a.workers,a.fit_workers))
        write(public/'MODEL_JOB_STATUS.json',model_status)
        tasks=[]
        for state in STATES:
            # Diagnose constrained-zero cost/framing only in the primary state;
            # allow signed gap responses in both states.
            diagnostic_models=('cost','framing','strength') if state=='equal' else ('strength',)
            for model in diagnostic_models:
                for cohort in ('original','rd110'):
                    tasks.append((state,model,cohort,prepared[state],str(source),str(work),str(public),reference,run_key))
        diagnostic_status=parallel(unrestricted_task,tasks,min(a.workers,a.fit_workers))
        write(public/'UNRESTRICTED_STATUS.json',diagnostic_status)
        assemble(public)
        failures=[r for r in model_status if r['status']!='COMPLETE']+[r for r in diagnostic_status if r['status']!='ESTIMATED']
        status.update(status='RD_AUDIT_COMPLETE' if not failures else 'COMPLETE_WITH_FIT_FAILURES',fit_failures=failures)
    except Exception as exc:
        error=exc;status.update(status='PARTIAL_RESULTS_REVIEW_REQUIRED',error=str(exc),traceback=traceback.format_exc())
        log('STOPPED: '+str(exc))
    finally:
        stop.set();status['elapsed_seconds']=time.monotonic()-start
        write(public/'SUMMARY.json',status)
        write(public/'ENVIRONMENT.json',dict(python=platform.python_version(),platform=platform.platform(),
            numpy=np.__version__,pandas=pd.__version__,duckdb=duckdb.__version__,pyarrow=pa.__version__,package_sha256=code))
        for name in ('FROZEN_PLAN.json','METHODS.md'):shutil.copy2(ROOT/name,public/name)
        text(public/'READ_ME_FIRST.md',note(status))
        run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        report=project/'output/mechanism_rd_audit_v100'/('MECHANISM_RD_AUDIT_RESULT_'+run_id)
        shutil.copytree(public,report);archive(report,a.desktop)
        lock.close()
        if original_lock is not None:original_lock.close()
    if error:raise SystemExit(1)

if __name__=='__main__':main()
