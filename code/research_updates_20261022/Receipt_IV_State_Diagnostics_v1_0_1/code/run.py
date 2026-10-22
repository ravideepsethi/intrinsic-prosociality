#!/usr/bin/env python3
"""Attach receipt-IV rating states and produce cutoff/calibration diagnostics."""
import os
for _k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[_k]='1'
import argparse,concurrent.futures as cf,fcntl,multiprocessing as mp,platform,shutil,time,traceback,zipfile
from common import *
import contracts,states,diagnostics,evidence

def signature():
    return digest({str(p.relative_to(PACKAGE)):sha(p) for p in sorted(PACKAGE.rglob('*'))
                   if p.is_file() and p.suffix in ('.py','.json','.scala') and '__pycache__' not in p.parts})

def jobs_run(jobs,workers):
    results={};pending={};at=0;start=time.monotonic()
    with heartbeat('Attaching saved rating states'),cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn')) as ex:
        while pending or at<len(jobs):
            while len(pending)<workers and at<len(jobs):pending[ex.submit(states.enrich_job,jobs[at])]=at;at+=1
            done,_=cf.wait(pending,return_when=cf.FIRST_COMPLETED)
            for f in done:
                k=pending.pop(f);results[k]=f.result();n=len(results)
                eta=(time.monotonic()-start)/n*(len(jobs)-n)/60
                log(f'State attachment: {n}/{len(jobs)} shards; approximate remaining attachment time {eta:.1f} min')
    return [results[k] for k in range(len(jobs))]

def export_report(report,desktop):
    # Public export is a positive allowlist. Never recursively zip private work.
    allowed={'RUN_CONFIGURATION.json','ACCOUNT_POLICY.json','DIAGNOSTIC_SPECIFICATION.json','MECHANICS_SOURCE_EVIDENCE.json',
             'FEBRUARY_LINEAGE_STATUS.json','SUMMARY.json','ERRORS.json','GATES.json','READ_ME_FIRST.txt','CALIBRATION_DEFINITIONS.json'}
    for n in ('CUTOFF_SAMPLE_COUNTS','LATER_CHOICE_AVAILABILITY','CALIBRATION_CELLS','CALIBRATION_MATCHED_CELLS',
              'CALIBRATION_MATCHED_SUMMARY','NEAR_ZERO_DRAW_DISTRIBUTIONS','IV_SAMPLE_MECHANICAL_DOSE','RD_ATTACHMENT_COUNTS',
              'FEBRUARY_SOURCE_AVAILABILITY'):
        allowed.update({n+'.csv',n+'.parquet'})
    files=[p for p in sorted(report.iterdir()) if p.is_file()]
    if any(p.name not in allowed for p in files):raise RuntimeError('Unexpected public output file')
    write_json(report/'RESULT_MANIFEST.json',dict(files=[dict(path=p.name,sha256=sha(p),bytes=p.stat().st_size) for p in files]))
    dest=desktop/(report.name+'.zip')
    with zipfile.ZipFile(dest,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for p in files+[report/'RESULT_MANIFEST.json']:z.write(p,report.name+'/'+p.name)
    dest.with_suffix('.zip.sha256').write_text(sha(dest)+'  '+dest.name+'\n')
    return dest

def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project-root',type=Path,default=ORIGINAL_PROJECT)
    ap.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    ap.add_argument('--workers',type=int,default=10);ap.add_argument('--memory-gb',type=int,default=8)
    a=ap.parse_args(argv)
    if not 1<=a.workers<=10:ap.error('workers must be 1–10')
    if not 4<=a.memory_gb<=64:ap.error('memory-gb must be 4–64')
    project=a.project_root.expanduser().resolve();desktop=a.desktop.expanduser().resolve()
    if not project.is_dir() or not desktop.is_dir():ap.error('Project drive and Lichess_Desktop must exist')
    contracts.verify_package();pa.set_cpu_count(1);pa.set_io_thread_count(1)
    work=project/'derived/replication_36m/receipt_iv_state_diagnostics_v100_PRIVATE';work.mkdir(parents=True,exist_ok=True)
    lock=(work/'run.lock').open('a+')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('This state-diagnostics package is already running')
    code=signature();started=time.monotonic();auth=work/'authentication'
    runid=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    public=project/'output/receipt_iv_state_diagnostics_v100'/('RECEIPT_IV_STATE_DIAGNOSTICS_'+runid);public.mkdir(parents=True)
    write_json(public/'RUN_CONFIGURATION.json',dict(version=VERSION,code_signature=code,workers_limit=a.workers,
        memory_budget_gb=a.memory_gb,python=platform.python_version(),duckdb=duckdb.__version__,pyarrow=pa.__version__,numpy=np.__version__,
        author_exclusion_applied=False,mechanics_censor=None,behavioral_estimation=False))
    write_json(public/'ACCOUNT_POLICY.json',contracts.ACCOUNT_POLICY)
    # Written before inspecting any newly enriched rows. No option selects a
    # cutoff by significance, data fit, or an observed behavioral coefficient.
    spec=load(PACKAGE/'DIAGNOSTIC_SPECIFICATION.json');write_json(public/'DIAGNOSTIC_SPECIFICATION.json',spec)
    write_json(public/'MECHANICS_SOURCE_EVIDENCE.json',evidence.source_evidence())
    errors=[];phase='authenticate';summary=None
    try:
        with heartbeat('Authenticating the completed cohort and replay targets'):
            assembly=contracts.authenticate_assembly(project,work);state=contracts.authenticate_states(project,work)
        binding=digest(dict(code=code,assembly=assembly['snapshots'],states=state['snapshots']))
        root=work/'runs'/binding;root.mkdir(parents=True,exist_ok=True)
        write_json(root/'INPUT_CONTRACT_PRIVATE.json',dict(assembly=assembly,states=state,account_policy=contracts.ACCOUNT_POLICY))
        if shutil.disk_usage(work).free<16*1024**3:raise RuntimeError('At least 16 GiB free working space is required')
        phase='prepare_state_inputs'
        with heartbeat('Preparing the already-replayed target states and fixed history cohort'):
            prepared=states.prepare(state,root,code,a.workers,a.memory_gb*1024-1536,auth)
        pd=load(prepared/'_DONE.json')
        prepared_inputs=[contracts.snap(prepared/'_DONE.json')]+[
            dict(path=str(prepared/r['path']),sha256=r['sha256'],bytes=r['bytes'],fingerprint=stamp(prepared/r['path']))
            for r in pd['files']]
        authenticated_analysis={r['path']:r for r in assembly['snapshots']}
        phase='attach_states';jobs=[];heavy=min(2,a.workers)
        for i,p in enumerate(assembly['paths']):
            jobs.append(dict(path=p,index=i,prepared=str(prepared),code=code,work=str(root),auth=str(auth),
                threads=max(1,a.workers//heavy),memory_mb=(a.memory_gb*1024-1536)//heavy,
                inputs=[authenticated_analysis[p],*prepared_inputs]))
        products=jobs_run(jobs,heavy)
        phase='calibration_and_cutoff_diagnostics'
        with heartbeat('Checking calibration, 90-day endpoint counts and later-choice availability'):
            out,done=diagnostics.build(products,root,code,a.workers,a.memory_gb*1024-1536,auth)
        phase='bounded_existing_lineage'
        lin=evidence.lineage(project);write_json(root/'FEBRUARY_LINEAGE_PRIVATE.json',lin)
        table([dict(project_relative_path=str(Path(r['path']).relative_to(project)),role=r['role'],exists=r['exists'],
            rows=r['rows'],bytes=r.get('bytes'),completion_marker=json.dumps(r.get('completion_marker'),sort_keys=True),
            has_status_column=bool(set(r.get('columns') or []) & {'api_status','lookup_status','status'}),
            has_disconnected_clock='disconnected_clock_last_obs_s' in (r.get('columns') or []),
            frame_certified=False) for r in lin['files']],public/'FEBRUARY_SOURCE_AVAILABILITY')
        write_json(public/'FEBRUARY_LINEAGE_STATUS.json',dict(status=lin['status'],files_checked=len(lin['files']),
            files_present=sum(r['exists'] for r in lin['files']),full_candidate_api_frame_certified=False,
            interpretation=lin['interpretation'],next_evidence_needed=lin['next_evidence_needed'],source_requests=0))
        phase='finish';unchanged(assembly['snapshots']);unchanged(state['snapshots'])
        for p in out.iterdir():
            if p.suffix in ('.csv','.parquet') or p.name=='CALIBRATION_DEFINITIONS.json':shutil.copy2(p,public/p.name)
        summary=done['result']
        manifest=dict(status=summary['status'],code_signature=code,account_policy=contracts.ACCOUNT_POLICY,
            analysis_paths=[p['path'] for p in products],receipts=[contracts.snap(Path(p['root'])/'_DONE.json') for p in products],
            parent_assembly_manifest=assembly['manifest'],parent_assembly_manifest_receipt=contracts.snap(assembly['manifest']),
            diagnostics_root=str(out),diagnostics_receipt=contracts.snap(out/'_DONE.json'),
            mechanics_censor=None,final_iv_eligible_n=None,new_IV_estimate=None,
            instruction='Preserve the selected streams and original y_calendar. The enriched shards replace only RD attachment fields and add diagnostic metadata.')
        mp_=root/'ENRICHED_MANIFEST_PRIVATE.json';write_json(mp_,manifest)
        write_json(work/'READY_FOR_IV_SPECIFICATION_PRIVATE.json',dict(status=summary['status'],manifest=str(mp_),
            manifest_receipt=contracts.snap(mp_),account_policy=contracts.ACCOUNT_POLICY,mechanics_censor=None,final_iv_eligible_n=None))
    except Exception as e:
        brief=str(e) if isinstance(e,RuntimeError) else (str(e).splitlines()[0] if isinstance(e,duckdb.Error) and str(e) else 'See private error details')
        errors.append(dict(stage=phase,exception=type(e).__name__,message=brief))
        write_json(work/'errors'/runid/'error_PRIVATE.json',dict(stage=phase,error=str(e),traceback=traceback.format_exc()))
        log('Stopped at '+phase+': '+errors[-1]['message'])
    gates=dict(rating_attachment='COMPLETE' if summary else 'CHECK_RESULT',mechanics_censor='UNFROZEN',
        later_choice_causal_control_specification='UNFROZEN_POSTTREATMENT_SELECTION_REQUIRES_EXPLICIT_ESTIMAND',
        announcement_timestamp='NOT_PINNED',broader_incident_denominator='NOT_CERTIFIED',
        behavioral_estimation='NOT_RUN',author_exclusion='DEFERRED_BY_EXPLICIT_USER_INSTRUCTION')
    write_json(public/'GATES.json',gates)
    summary=dict(summary or dict(status='PARTIAL_STATE_DIAGNOSTICS',mechanics_censor=None,final_iv_eligible_n=None,new_IV_estimate=None),
                 elapsed_seconds=time.monotonic()-started,errors=errors,author_accounts_retained=True,author_exclusion_applied=False)
    write_json(public/'SUMMARY.json',summary);write_json(public/'ERRORS.json',errors)
    (public/'READ_ME_FIRST.txt').write_text('Rating-state attachment and mechanical calibration, not a new IV estimate.\n'
        'Both author accounts remain included. All original exposure selection and spacing are preserved.\n'
        'Cutoff counts are sensitivity diagnostics; no deployment date or final IV denominator is adopted.\n'
        'Later-choice interaction remains NULL for nonreachers, ambiguous choices and the implementation bracket.\n'
        'Calibration strata overlap and only cover the calendar-primary November–January IV exposures.\n'
        'Upload this ZIP and its SHA-256 sidecar. Game/account rows and detailed lineage remain on XT_Pro.\n'
        'Re-running the same command verifies and reuses completed stages. No API requests, historical replay, chronology scan, instrument rebuild or Stockfish.\n')
    zp=export_report(public,desktop);log(summary['status']);print('UPLOAD: '+str(zp),flush=True);print('UPLOAD: '+str(zp)+'.sha256',flush=True)
    lock.close()
    return 1 if errors else 0

if __name__=='__main__':raise SystemExit(main())
