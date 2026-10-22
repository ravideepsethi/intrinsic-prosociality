#!/usr/bin/env python3
"""Extend original all-source IV histories. Final causal estimation is not run."""
from __future__ import annotations
import argparse,concurrent.futures as cf,fcntl,multiprocessing as mp,platform,sys,time,traceback,zipfile
from common import *
import sources
import comparison_checkpoint
from project_history import build_month,identity_check
from history_logic import assert_same_projection
from references import build_references

def code_signature():
    return digest({str(p.relative_to(PACKAGE)):sha(p) for folder in ['code','vendor'] for p in sorted((PACKAGE/folder).glob('*.py'))})

def make_zip(report,desktop):
    allowed={'RUN_CONFIGURATION.json','COMPARISON_CHECKPOINT_STATUS.json','HISTORICAL_IV_REUSE.json',
        'HISTORICAL_PROJECTION_BRIDGE.json','IDENTITY_NAMESPACE_CHECK.json','REFERENCE_BRIDGE.json',
        'HISTORY_COVERAGE.csv','HISTORY_COVERAGE.parquet','ADDED_MONTH_PROJECTION_COUNTS.csv',
        'ADDED_MONTH_PROJECTION_COUNTS.parquet','ESTIMATION_GATES.csv','ESTIMATION_GATES.parquet',
        'ERRORS.json','SUMMARY.json','READ_ME_FIRST.md'}
    paths=[p for p in sorted(Path(report).iterdir()) if p.is_file()]
    if any(p.name not in allowed for p in paths):raise RuntimeError('Unexpected file in aggregate return directory')
    files=[receipt(p) for p in paths]
    for r in files:r['path']=str(Path(r['path']).relative_to(report))
    write_json(Path(report)/'RESULT_MANIFEST.json',dict(files=files))
    zp=Path(desktop)/(Path(report).name+'.zip')
    if zp.exists():raise RuntimeError('Refusing to replace an existing result ZIP')
    with zipfile.ZipFile(zp,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for p in paths+[Path(report)/'RESULT_MANIFEST.json']:z.write(p,Path(report).name+'/'+p.name)
    zp.with_suffix('.zip.sha256').write_text(sha(zp)+'  '+zp.name+'\n')
    return zp

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root',type=Path,default=ORIGINAL_PROJECT)
    p.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--workers',type=int,default=10)
    p.add_argument('--memory-gb',type=int,default=8)
    a=p.parse_args(argv)
    if not 1<=a.workers<=10:p.error('workers must be 1–10')
    if not 4<=a.memory_gb<=64:p.error('memory-gb must be 4–64')
    project=a.project_root.expanduser().resolve();desktop=a.desktop.expanduser().resolve()
    if not project.is_dir():p.error('Project volume is not mounted')
    if not desktop.is_dir():p.error('Lichess_Desktop does not exist')
    sources.verify_package();code=code_signature();start=time.monotonic()
    work=project/'derived/replication_36m/receipt_iv_history_extension_v100_PRIVATE'
    work.mkdir(parents=True,exist_ok=True)
    lock=(work/'run.lock').open('a+')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('An IV history extension is already running')
    run_id=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    report=project/'output/receipt_iv_extension_v100'/('RECEIPT_IV_HISTORY_EXTENSION_'+run_id)
    report.mkdir(parents=True)
    auth=work/'authentication';errors=[];results=[];snapshots=[];reference_root=None
    jobs_count=min(4,a.workers)
    per_job_mb=max(512,(a.memory_gb*1024-1536)//jobs_count)
    config=dict(version=VERSION,code_signature=code,monthly_processes=jobs_count,threads_per_monthly_process=1,
        serial_duckdb_threads=a.workers,total_worker_limit=a.workers,memory_budget_gb=a.memory_gb,
        duckdb_mb_per_monthly_process=per_job_mb,python=platform.python_version(),duckdb=duckdb.__version__,pyarrow=pa.__version__,
        monthly_cache_producers_rerun=False,rating_replay=False,stockfish_searches=0,network_requests=0,
        historical_months_reprojected_for_bridge=1,added_months_to_project=8,old_history_shards_to_reuse=384,
        new_effect_estimates=False,final_censor=None,estimation_mode='DISABLED_PENDING_FROZEN_COHORT')
    write_json(report/'RUN_CONFIGURATION.json',config)
    def fail(stage,e):
        msg=str(e) if isinstance(e,RuntimeError) else 'Private error details retained; exception type '+type(e).__name__
        errors.append(dict(stage=stage,error=msg,exception=type(e).__name__))
        write_json(work/'errors'/run_id/(stage+'.json'),dict(error=str(e),traceback=traceback.format_exc()))
        log(stage+': '+msg)
    current='startup'
    try:
        current='comparison_checkpoint'
        try:write_json(report/'COMPARISON_CHECKPOINT_STATUS.json',comparison_checkpoint.inspect(desktop))
        except Exception as e:
            write_json(report/'COMPARISON_CHECKPOINT_STATUS.json',dict(status='READ_ONLY_CHECK_FAILED',exception=type(e).__name__,download_completion_certified=False))
            # A separately active or unavailable comparison download does not prevent history building.
            write_json(work/'errors'/run_id/'comparison_read.json',dict(error=str(e),traceback=traceback.format_exc()))
        current='authenticate_completed_inputs'
        with heartbeat('Authenticating original IV histories and finalized anchors'):
            pins=load(sources.AUTH/'pins.json')
            d=project/'derived/glicko2_replay/user_dictionary_v1/summary.json'
            snapshots.append(checked(d,pins['dictionary'],auth))
            if int(load(d)['total_global_users'])!=pins['n_users']:raise RuntimeError('Global account-ID namespace changed')
            benchmark,br=sources.historical_iv(project,auth);snapshots.append(br)
            write_json(report/'HISTORICAL_IV_REUSE.json',benchmark)
            old,osn=sources.old_histories(project,auth);snapshots+=osn
            deltas,dsn=sources.pilot_deltas(project,auth);snapshots+=dsn
            bridge_job=sources.month_job(project,'2023-11',auth,work,per_job_mb,bridge=True)
            bridge_job['code_sha']=code
            jobs=[]
            for month in NEW_MONTHS:
                j=sources.month_job(project,month,auth,work,per_job_mb);j['code_sha']=code;jobs.append(j)
            for j in [bridge_job,*jobs]:snapshots+=j['inputs']
        contract=dict(version=VERSION,code_signature=code,inputs=snapshots,
            history_boundaries=['2023-11-01','2023-09-01'],source_authority_sha256=sha(sources.AUTH/'pins.json'))
        cp=work/'INPUT_CONTRACT_PRIVATE.json'
        if cp.is_file() and load(cp)!=contract:raise RuntimeError('Saved input contract changed; preserve the completed work for review')
        if not cp.is_file():write_json(cp,contract)
        current='historical_projection_bridge'
        bridge=build_month(bridge_job)
        c=connection(work/'spill_bridge',a.workers,a.memory_gb*1024-1024)
        try:
            with heartbeat('Comparing original and reconstructed November 2023 history rows'):
                new=[Path(bridge['root'])/f'shard-{s:02d}.parquet' for s in range(16)]
                previous=[x['path'] for x in old if x['month']=='2023-11']
                b=assert_same_projection(c,new,previous)
                b.update(month='2023-11',rows=bridge['result']['rows'])
                write_json(report/'HISTORICAL_PROJECTION_BRIDGE.json',b)
        finally:c.close()
        current='added_month_histories'
        with cf.ProcessPoolExecutor(max_workers=jobs_count,mp_context=mp.get_context('spawn')) as ex:
            fs={ex.submit(build_month,j):j['month'] for j in jobs}
            with heartbeat('Building added-month history partitions'):
                for f in cf.as_completed(fs):
                    try:results.append(f.result())
                    except Exception as e:fail('month_'+fs[f],e)
                    write_json(work/'PROGRESS.json',dict(completed_months=sorted(r['month'] for r in results),errors=errors))
        results.sort(key=lambda x:x['month'])
        if len(results)!=8 or errors:raise RuntimeError('At least one added month did not complete; completed months are reusable')
        current='identity_namespace'
        _,ir=identity_check([bridge,*results],work,auth,a.workers,a.memory_gb*1024-1024,code)
        write_json(report/'IDENTITY_NAMESPACE_CHECK.json',ir['result'])
        current='extended_reference_models'
        reference_root,rr=build_references(old,results,deltas,work,auth,code)
        write_json(report/'REFERENCE_BRIDGE.json',rr['result']['bridge'])
        table(rr['result']['monthly_counts'],report/'HISTORY_COVERAGE')
        current='final_input_fingerprints'
        unchanged(snapshots)
        # Receipts for private products are referenced, never included in the return ZIP.
        write_json(work/'READY_FOR_COHORT_EXTENSION.json',dict(status='ALL_SOURCE_IV_HISTORIES_AND_REFERENCES_READY',
            historical_projection_bridge=b,reference_bridge=rr['result']['bridge'],identity_check=ir['result'],
            reference_root=str(reference_root),new_month_products=results,old_history_records=old,
            input_contract_sha256=sha(cp),final_iv_eligible_n=None))
    except Exception as e:fail(current,e)
    table([r['result'] for r in results],report/'ADDED_MONTH_PROJECTION_COUNTS')
    gates=[
        dict(item='extended_pool_and_observed_nonadjacency',status='NOT_BUILT',reason='Explicit source labels and predecessor evidence are required; no unknown row is classified as main-eligible.'),
        dict(item='first_observed_pair_and_exposure_stream',status='NOT_EXTENDED',reason='Reuse the original producer; spacing must precede later eligibility cuts.'),
        dict(item='February_candidate_denominator',status='UNRESOLVED',reason='An active-opportunity history is not the selected-candidate denominator.'),
        dict(item='mechanics_censor_and_policy_outcome_rule',status='UNRESOLVED',reason='No endpoint is adopted from file availability or the issue date.'),
        dict(item='new_IV_estimation',status='NOT_RUN',reason='Freeze the cohort, complete 90-day windows and outcome rules before estimating.')]
    table(gates,report/'ESTIMATION_GATES')
    write_json(report/'ERRORS.json',errors)
    success=not errors and len(results)==8 and reference_root is not None
    summary=dict(status='HISTORY_EXTENSION_COMPLETE_COHORT_GATES_REMAIN' if success else 'PARTIAL_HISTORY_EXTENSION',
        old_history_months_reused=24 if 'old' in locals() else 0,new_history_months_complete=len(results),
        new_history_rows=sum(r['result']['rows'] for r in results),expected_new_history_rows=15938535,
        all_source_history_rows=63525555 if success else None,reference_universes=['old_boundary','extended_boundary'] if success else [],
        final_iv_eligible_n=None,new_IV_estimate=None,mechanics_censor=None,network_requests=0,rating_replays=0,stockfish_searches=0,
        elapsed_seconds=time.monotonic()-start,errors=errors,private_work_root=str(work),
        interpretation='Reusable all-source history inputs and nuisance reference models, not a certified 32-month pool cohort or a new behavioral result.')
    write_json(report/'SUMMARY.json',summary)
    (report/'READ_ME_FIRST.md').write_text('This run extends all-source IV histories and cross-fit reference models. Read SUMMARY.json, the two historical bridge files, HISTORY_COVERAGE and ESTIMATION_GATES. The original IV benchmark is preserved. New pool eligibility, exposure streams, causal follow-up and IV estimation remain separate. Private data stay on XT_Pro. Return only this aggregate ZIP and checksum.\n')
    zp=make_zip(report,desktop);log('Result ZIP: '+str(zp))
    log('OK: HISTORY_EXTENSION_COMPLETE_COHORT_GATES_REMAIN' if success else 'PARTIAL: completed month caches retained')
    fcntl.flock(lock,fcntl.LOCK_UN);lock.close()
    return 0 if success else 2

if __name__=='__main__':raise SystemExit(main())
