#!/usr/bin/env python3
"""Produce the fixed regular cohort and the matched conditional color comparison."""
from __future__ import annotations
import argparse,concurrent.futures as cf,multiprocessing as mp,platform,subprocess,sys,traceback,zipfile,shutil
from mc_io import *
import mc_inputs as inputs
import mc_history as history
from mc_sample import assemble
from mc_predict import predict_state
from mc_inference import run_comparison,windows

def parallel(fn,jobs,workers,label):
    result=[]
    with heartbeat(label),cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn')) as pool:
        futures=[pool.submit(fn,j) for j in jobs]
        for f in cf.as_completed(futures):
            result.append(f.result());log(f'{label}: {len(result)}/{len(jobs)} completed or reused')
    return result

def verify():
    p=ROOT/'PACKAGE_MANIFEST.sha256'
    for line in p.read_text().splitlines():
        expected,rel=line.split('  ',1);f=ROOT/rel
        if not f.resolve().is_relative_to(ROOT.resolve()) or sha(f)!=expected:raise RuntimeError('Package checksum mismatch: '+rel)
    return sha(p)

def bundle(report,desktop):
    files=[p for p in report.iterdir() if p.is_file()]
    write(report/'RESULT_MANIFEST.json',dict(files=[dict(name=p.name,sha256=sha(p),bytes=p.stat().st_size) for p in files]))
    dest=Path(desktop)/(report.name+'.zip')
    with zipfile.ZipFile(dest,'x',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(report.iterdir()):
            if p.is_file():z.write(p,report.name+'/'+p.name)
    dest.with_suffix('.zip.sha256').write_text(sha(dest)+'  '+dest.name+'\n')
    log('RESULT_TO_UPLOAD: '+str(dest));log('RESULT_TO_UPLOAD: '+str(dest)+'.sha256')

def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    ap.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    ap.add_argument('--workers',type=int,default=10);ap.add_argument('--memory-gb',type=int,default=8)
    a=ap.parse_args(argv)
    if not 1<=a.workers<=10 or not 4<=a.memory_gb<=64:ap.error('workers 1–10 and memory-gb 4–64 required')
    if not a.project.is_dir() or not a.desktop.is_dir():ap.error('Mounted project and Desktop folder must exist')
    os.environ['COLOR_DUCKDB_THREAD_LIMIT']=str(a.workers)
    package_sha=verify();started=time.monotonic();pa.set_cpu_count(1);pa.set_io_thread_count(1)
    project=a.project.resolve();work=project/'derived/replication_36m/color_matched_cohort_v100_PRIVATE'
    runid=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    report=project/'output/color_matched_cohort_v100'/('COLOR_MATCHED_RESULT_'+runid);report.mkdir(parents=True)
    for name in ('FROZEN_PLAN.json','METHODS.md','INPUT_CONTRACTS.md'):shutil.copy2(ROOT/name,report/name)
    status=dict(status='STARTED',version=VERSION,package_sha256=package_sha,phase='startup')
    heavy=min(2,a.workers);memory=(a.memory_gb*1024-1536)//heavy;serial=a.memory_gb*1024-1024
    try:
        with lock(work/'run.lock'):
            identity=dict(package_sha256=package_sha,project=str(project),scientific_plan=read(ROOT/'FROZEN_PLAN.json'))
            if (work/'RUN_IDENTITY.json').exists() and read(work/'RUN_IDENTITY.json')!=identity:raise RuntimeError('Existing color cache has a different scientific identity')
            write(work/'RUN_IDENTITY.json',identity)
            write(report/'ENVIRONMENT.json',dict(python=platform.python_version(),numpy=np.__version__,pandas=pd.__version__,duckdb=duckdb.__version__,pyarrow=pa.__version__,
                workers_limit=a.workers,heavy_processes=heavy,memory_gb=a.memory_gb,scipy_required=False))
            status['phase']='shared_membership'
            bridge_path=work/'SHARED_MEMBERSHIP_PRIVATE.json'
            subprocess.run([sys.executable,str(ROOT/'code/shared_membership.py'),'--project',str(project),'--desktop',str(a.desktop),
                '--output',str(bridge_path),'--workers',str(a.workers),'--memory-gb',str(a.memory_gb)],check=True)
            bridge=read(bridge_path);table(bridge['flow'],report/'shared_membership_flow')
            write(report/'SHARED_PRODUCER_STATUS.json',{k:bridge[k] for k in ('status','producer_code_signature','source_scan_issues','code_scope')})
            status['phase']='input_authentication'
            with heartbeat('Authenticating completed mechanism and chronology inputs'):cat=inputs.catalog(project,work)
            write(work/'INPUT_CATALOG_PRIVATE.json',cat)
            status['phase']='state_and_membership_join'
            post=parallel(inputs.prepare_post,[(str(project),str(work),m,bridge,memory) for m in POST_MONTHS],heavy,'Post-state joins');post.sort()
            status['phase']='preimplementation_activity_roster'
            with heartbeat('Building preimplementation activity candidates'):
                candidates=[history.activity_candidates(s,cat['chronology'],work,serial) for s in SPEEDS]
                needed,missing=history.needed_users(candidates,post,cat['old_needed'],work,serial)
            status['phase']='incremental_start_history'
            jobs=[(r,needed,missing,cat['old_needed'],str(work),memory) for r in cat['chronology']]
            parallel(history.summary_job,jobs,heavy,'Cached counts and missing-account counts')
            with heartbeat('Freezing regular-player roster'):
                rosters=[history.roster(s,cat['chronology'],candidate,work,serial) for s,candidate in zip(SPEEDS,candidates)]
            status['phase']='post_opportunity_history_features'
            jobs=[(s,m,cat['chronology'],str(work/'post_narrow'/(m+'.parquet')),str(work),memory) for m in POST_MONTHS for s in SPEEDS]
            parallel(history.feature_job,jobs,heavy,'Post-only history features')
            status['phase']='matched_sample_and_calibration'
            with heartbeat('Assembling matched samples and coverage audits'):
                target,gates=assemble(cat,post,rosters,work,report,serial)
            status['phase']='rated_start_exposure_diagnostic'
            exjobs=[(r,rosters,str(work),memory) for r in cat['chronology'] if '2025-09'<=r['month']<='2026-01']
            exposure=parallel(history.exposure_job,exjobs,heavy,'Rated-start denominators')
            # Monthly files can split a week: starts sum exactly; active account
            # counts remain speed-month-week cells and are never summed as people.
            ex=pd.concat([pd.read_parquet(p).assign(source_month=Path(p).stem.rsplit('_',1)[1]) for p in exposure],ignore_index=True)
            table(ex,report/'rated_start_exposure_cells')
            status['phase']='matched_fixed_fit_predictions'
            with heartbeat('Computing fixed-fit matched forecasts'):
                preds={s:predict_state(target,s,work,report,serial) for s in ('equal','losing')}
            status['phase']='matched_conditional_comparison'
            result=run_comparison(target,preds,gates,work,report);status.update(result)
            status.update(phase='finished',rating_replays=0,stockfish_searches=0,API_requests=0,candidate_model_refits=0,
                input_plan='Existing shared source/adjacency checkpoints plus incremental regularity histories',
                private_cohort_manifest_format='COLOR_MATCHED_COHORT_BUILD_V1',ready_for_causal_claim=False)
            write(work/'MATCHED_COHORT_MANIFEST_PRIVATE.json',dict(format='COLOR_MATCHED_COHORT_BUILD_V1',
                target=snapshot(target),roster_files=[snapshot(p) for p in rosters],plan_sha256=sha(ROOT/'FROZEN_PLAN.json'),
                membership_pointer=snapshot(bridge_path),pool_predicate="source='pool' AND previous_classification_status='not_mutually_adjacent_observed'",
                cutoff_ms=IMPLEMENTED,regularity_uses_post_activity=False,formal_mechanics_censor=None,causal_adjudication=False))
    except Exception as e:
        write(work/'errors'/(runid+'_PRIVATE.json'),dict(error=str(e),traceback=traceback.format_exc(),phase=status['phase']))
        status.update(status='PARTIAL_RUN_REVIEW_REQUIRED',error_type=type(e).__name__,error=str(e) if isinstance(e,RuntimeError) else 'See the private error record and terminal log')
        log('Stopped at '+status['phase']+': '+str(e))
    status['elapsed_seconds']=time.monotonic()-started;write(report/'SUMMARY.json',status)
    (report/'READ_ME_FIRST.md').write_text('Status: '+status['status']+'\n\nRead window_status, sample_selection and calibration_cells before model comparisons.\n'
        'Regularity is frozen using strictly preimplementation starts. Both RDs are restricted contemporaneously.\n'
        'unannounced is the bounded implementation-to-announcement comparison; January endpoints are named truncation sensitivities, not certified mechanics censors.\n'
        'Conditional point-fit comparisons hold model coefficients fixed and include predicted no-policy composition changes. They are not causal mechanism rejections or motive shares.\n'
        'A failed source/adjacency/clock gate withholds the affected window; no all-source or known-source-only substitute is used.\n'
        'Return this ZIP and its SHA-256 sidecar. The same launcher reuses completed checkpoints.\n')
    bundle(report,a.desktop)
    return 1 if status['status']=='PARTIAL_RUN_REVIEW_REQUIRED' else 0

if __name__=='__main__':raise SystemExit(main())
