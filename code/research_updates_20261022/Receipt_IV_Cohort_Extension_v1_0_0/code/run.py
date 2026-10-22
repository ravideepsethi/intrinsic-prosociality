#!/usr/bin/env python3
"""Complete offline source, adjacency, membership and IV score-input stages."""
from __future__ import annotations
import argparse,concurrent.futures as cf,fcntl,multiprocessing as mp,platform,resource,shutil,sys,time,traceback,zipfile
from common import *
import inputs as sources
import source_stage,adjacency_stage,membership_stage,score_stage

def code_signature():
    return digest({str(p.relative_to(PACKAGE)):sha(p) for folder in ('code','vendor') for p in sorted((PACKAGE/folder).glob('*.py'))})

def snapshot(path):return dict(**receipt(path),fingerprint=stamp(path))

def pool_jobs(jobs,fn,workers,label):
    results=[]
    # Keep submission bounded. On failure cancel queued work, while the few
    # already-running checkpoints finish safely under the active heartbeat.
    with heartbeat(label):
        ex=cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn'))
        pending={};at=0
        try:
            while pending or at<len(jobs):
                while len(pending)<workers and at<len(jobs):
                    j=jobs[at];at+=1;pending[ex.submit(fn,j)]=j
                ready,_=cf.wait(pending,return_when=cf.FIRST_COMPLETED)
                for f in ready:
                    pending.pop(f);results.append(f.result())
                    log(f'{label}: {len(results)}/{len(jobs)} completed or reused')
        finally:
            for f in pending:f.cancel()
            ex.shutdown(wait=True,cancel_futures=True)
    return results

def package_report(report,desktop):
    files=[p for p in sorted(report.iterdir()) if p.is_file()]
    allowed={'RUN_CONFIGURATION.json','SUMMARY.json','ERRORS.json','ADJACENCY_BRIDGE.json','SOURCE_BRIDGE.json',
        'SOURCE_SCAN.json','SOURCE_COUNTS.csv','SOURCE_COUNTS.parquet','CHRONOLOGY_COUNTS.csv','CHRONOLOGY_COUNTS.parquet',
        'ADJACENCY_COUNTS.csv','ADJACENCY_COUNTS.parquet','MEMBERSHIP_FLOW.csv','MEMBERSHIP_FLOW.parquet',
        'INSTRUMENT_SUPPORT.csv','INSTRUMENT_SUPPORT.parquet','ESTIMATION_GATES.json','READ_ME_FIRST.md'}
    if any(p.name not in allowed for p in files):raise RuntimeError('Unexpected file in public return directory')
    records=[]
    for p in files:
        r=receipt(p);r['path']=p.name;records.append(r)
    write_json(report/'RESULT_MANIFEST.json',dict(files=records))
    zp=Path(desktop)/(report.name+'.zip')
    with zipfile.ZipFile(zp,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for p in [*files,report/'RESULT_MANIFEST.json']:z.write(p,report.name+'/'+p.name)
    zp.with_suffix('.zip.sha256').write_text(sha(zp)+'  '+zp.name+'\n')
    return zp

def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project-root',type=Path,default=ORIGINAL_PROJECT)
    ap.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    ap.add_argument('--workers',type=int,default=10)
    ap.add_argument('--memory-gb',type=int,default=8)
    ap.add_argument('--extra-source-root',type=Path,action='append',default=[])
    a=ap.parse_args(argv)
    if not 1<=a.workers<=10:ap.error('workers must be 1–10')
    if not 4<=a.memory_gb<=64:ap.error('memory-gb must be 4–64')
    project=a.project_root.expanduser().resolve();desktop=a.desktop.expanduser().resolve()
    if not project.is_dir() or not desktop.is_dir():ap.error('Project volume and Lichess_Desktop must exist')
    sources.verify_package();code=code_signature();started=time.monotonic()
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    soft,hard=resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE,(max(soft,min(8192,hard if hard!=resource.RLIM_INFINITY else 8192)),hard))
    work=project/'derived/replication_36m/receipt_iv_cohort_extension_v100_PRIVATE';work.mkdir(parents=True,exist_ok=True)
    lock=(work/'run.lock').open('a+')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('This cohort extension is already running')
    runid=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    report=project/'output/receipt_iv_extension_v100'/('RECEIPT_IV_COHORT_EXTENSION_'+runid);report.mkdir(parents=True)
    auth=work/'authentication';errors=[];phase='startup';mr=sr=ar=ir=None
    processes=min(2,a.workers);per_mb=(a.memory_gb*1024-2048)//processes
    serial_mb=a.memory_gb*1024-1536
    config=dict(version=VERSION,code_signature=code,workers_limit=a.workers,memory_budget_gb=a.memory_gb,
        heavy_processes=processes,duckdb_threads_each=max(1,a.workers//processes),memory_mb_each=per_mb,
        api_requests=0,rating_replays=0,stockfish_searches=0,history_rebuilds=0,
        source_scan_mode='existing local files only',behavioral_estimation=False,final_censor=None,
        python=platform.python_version(),duckdb=duckdb.__version__,pyarrow=pa.__version__,numpy=np.__version__)
    write_json(report/'RUN_CONFIGURATION.json',config)
    try:
        phase='authenticate_completed_products'
        with heartbeat('Authenticating completed histories and original membership'):
            hist=sources.history(project,auth);old=sources.old_membership(project,auth)
            feats,fs=sources.feature_sources(project,auth);chron=sources.chronology(project,auth)
        phase='source_target_index'
        tr,td=source_stage.prepare_targets(hist['opportunities'],feats,work,auth,code,a.workers,serial_mb,[*hist['snapshots'],*fs])
        phase='recover_existing_source_labels'
        sr,sd=source_stage.recover(project,desktop,a.extra_source_root,tr,work,auth,code,a.workers,a.workers,serial_mb)
        table(sd['result']['counts'],report/'SOURCE_COUNTS')
        write_json(report/'SOURCE_SCAN.json',{k:v for k,v in sd['result'].items() if k!='counts'})
        phase='chronology_neighbor_projection'
        if shutil.disk_usage(work).free<32*1024**3:
            raise RuntimeError('At least 32 GiB free space is required before chronology projection; completed source work is preserved')
        target_inputs=[snapshot(tr/n) for n in ('targets_PRIVATE.parquet','target_user_months_PRIVATE.parquet','target_users_PRIVATE.parquet')]
        jobs=[dict(record=r,targets=str(tr),target_inputs=target_inputs,work=str(work),auth=str(auth),code=code,
            threads=max(1,a.workers//processes),memory_mb=per_mb) for r in chron]
        projected=pool_jobs(jobs,adjacency_stage.file_job,processes,'Chronology files')
        projected.sort(key=lambda x:(x['result']['month'],x['result']['speed'],x['root']))
        write_json(work/'CHRONOLOGY_COMPLETED_PRIVATE.json',projected)
        table([r['result'] for r in projected],report/'CHRONOLOGY_COUNTS')
        phase='previous_adjacency_sides'
        by_bucket={k:[] for k in range(adjacency_stage.BUCKETS)}
        for r in projected:
            for entry in r['files']:
                p=Path(entry['path'])
                ub=[x for x in p.parts if x.startswith('ub=')]
                if p.suffix=='.parquet' and len(ub)==1:by_bucket[int(ub[0][3:])].append(str(Path(r['root'])/p))
        proj_inputs=[dict(**r['receipt'],fingerprint=stamp(r['receipt']['path'])) for r in projected]
        side_jobs=[dict(bucket=b,paths=by_bucket[b],targets=str(tr),inputs=[*proj_inputs,*target_inputs],work=str(work),auth=str(auth),code=code,memory_mb=per_mb)
            for b in range(adjacency_stage.BUCKETS)]
        sides=pool_jobs(side_jobs,adjacency_stage.side_job,processes,'Adjacency user buckets')
        phase='adjacency_bridge_and_census'
        with heartbeat('Validating the original November adjacency bridge'):
            ar,ad=adjacency_stage.census(sides,tr,old,work,auth,code,a.workers,serial_mb)
        write_json(report/'ADJACENCY_BRIDGE.json',ad['result']['bridge'])
        table(ad['result']['counts'],report/'ADJACENCY_COUNTS')
        phase='extended_membership_and_choice_spine'
        with heartbeat('Assembling membership and choice inputs'):
            mr,md=membership_stage.build(sr,sd['result'],ar,hist['opportunities'],old,work,auth,code,a.workers,serial_mb,
                [snapshot(sr/'_DONE.json'),snapshot(ar/'_DONE.json'),*hist['snapshots'],*old['snapshots']])
        table(md['result']['flow'],report/'MEMBERSHIP_FLOW');write_json(report/'SOURCE_BRIDGE.json',md['result']['source_bridge'])
        phase='pair_excluded_instrument_scores'
        score_jobs=[]
        for shard in range(16):
            rr=[r for r in hist['records'] if r['shard']==shard]
            score_jobs.append(dict(shard=shard,paths=[r['path'] for r in rr],reference=hist['reference'],
                inputs=[snapshot(hist['reference']),*[dict(**r,fingerprint=stamp(r['path'])) for r in rr]],
                work=str(work),auth=str(auth),code=code,memory_mb=per_mb))
        scored=pool_jobs(score_jobs,score_stage.score_job,processes,'Instrument score shards')
        phase='support_summary'
        with heartbeat('Summarizing five- and ten-decision support'):
            ir,idone=score_stage.summarize(scored,mr,work,auth,code,a.workers,serial_mb,
                [snapshot(mr/'_DONE.json'),*[snapshot(Path(r['root'])/'_DONE.json') for r in scored]])
        table(idone['result']['support'],report/'INSTRUMENT_SUPPORT')
        phase='final_immutable_input_check'
        unchanged([*hist['snapshots'],*old['snapshots'],*fs])
        for r in chron:
            if stamp(r['path'])!=r['fingerprint']:raise RuntimeError('Chronology input changed during run')
        write_json(work/'READY_FOR_IV_COHORT_ASSEMBLY_PRIVATE.json',dict(status='MEMBERSHIP_AND_PAIR_EXCLUDED_SCORE_INPUTS_READY',
            code_signature=code,history_ready=str(project/sources.HISTORY/'READY_FOR_COHORT_EXTENSION.json'),
            source_root=str(sr),adjacency_root=str(ar),membership_root=str(mr),support_root=str(ir),
            receipts=[snapshot(x/'_DONE.json') for x in (sr,ar,mr,ir)],
            unknown_source_rows=sum(r['unresolved_source_rows'] for r in md['result']['flow']),
            source_scan_issues=sd['result']['scan_issues'],mechanics_censor=None,final_iv_eligible_n=None,
            next_required=['source gaps if present','rating-state calibration/attachment','first observed pair and exposure stream',
              'mechanics evidence and incident denominator','complete 90-day windows','later-choice color policy and exclusion sensitivity']))
    except Exception as e:
        # Potential individual identifiers in native exceptions stay private.
        errors.append(dict(stage=phase,exception=type(e).__name__,message=str(e) if isinstance(e,RuntimeError) else 'See private error details'))
        write_json(work/'errors'/runid/'error_PRIVATE.json',dict(stage=phase,error=str(e),traceback=traceback.format_exc()))
        log('Stopped at '+phase+': '+errors[-1]['message'])
    finished=ir is not None and not errors
    unresolved=sum(r['unresolved_source_rows'] for r in md['result']['flow']) if mr is not None else None
    gates=[dict(item='new_source_labels',status='COMPLETE' if unresolved==0 and sd['result']['scan_issues']==0 else 'GAPS_OR_SCAN_ISSUES',unresolved_rows=unresolved),
        dict(item='observed_adjacency_bridge',status='PASSED' if ar is not None else 'NOT_COMPLETE'),
        dict(item='pair_excluded_instrument_scores',status='BUILT' if finished else 'NOT_COMPLETE'),
        dict(item='targeted_rating_calibration_and_new_RD_attachment',status='OPEN'),
        dict(item='first_observed_pair_and_spacing_before_censor',status='NOT_BUILT'),
        dict(item='broader_incident_denominator_and_deployment_censor',status='UNRESOLVED'),
        dict(item='complete_90day_outcomes_before_frozen_censor',status='NOT_BUILT'),
        dict(item='later_choice_color_times_post_and_nonreacher_rule',status='NOT_FROZEN'),
        dict(item='reduced_form_2SLS_exclusion_sensitivity_and_MDE',status='NOT_RUN')]
    write_json(report/'ESTIMATION_GATES.json',gates);write_json(report/'ERRORS.json',errors)
    status=('INPUT_STAGES_COMPLETE_SOURCE_GAPS_REMAIN' if unresolved or (sr is not None and sd['result']['scan_issues']) else 'INPUT_STAGES_COMPLETE_ESTIMATION_GATES_REMAIN') if finished else 'PARTIAL_INPUT_STAGES'
    summary=dict(status=status,version=VERSION,elapsed_seconds=time.monotonic()-started,
        historical_history_rows_reused=63525555 if 'hist' in locals() else None,old_main_rows_preserved=41534331 if 'old' in locals() else None,
        new_membership_layer_built=mr is not None,instrument_support_built=finished,unresolved_new_source_rows=unresolved,
        known_main_rows=md['result']['known_main_rows'] if mr is not None else None,
        final_iv_eligible_n=None,new_IV_estimate=None,mechanics_censor=None,api_requests=0,rating_replays=0,stockfish_searches=0,
        errors=errors,private_work_root=str(work),output_is_aggregate_only=True)
    write_json(report/'SUMMARY.json',summary)
    (report/'READ_ME_FIRST.md').write_text('This result contains aggregate source, adjacency, membership and instrument-support diagnostics.\n\n'
        'Candidate counts are not an IV denominator. The 24-month membership is preserved. Source-missing games remain unresolved; '
        'boundary/ambiguous adjacency cases are not admitted to the known main sample. No behavioral coefficient, IV estimate, MDE or censor timestamp is produced.\n\n'
        'Upload this ZIP and its SHA-256 sidecar. Private IDs, API records, choice spines and scores remain on XT_Pro. '
        'Rerunning the same package resumes completed checkpoints.\n')
    zp=package_report(report,desktop)
    log(status);print('UPLOAD: '+str(zp),flush=True);print('UPLOAD: '+str(zp)+'.sha256',flush=True)
    return 0 if finished else 1

if __name__=='__main__':raise SystemExit(main())
