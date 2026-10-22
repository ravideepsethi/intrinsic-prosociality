#!/usr/bin/env python3
"""Pull missing source metadata with no fixed pauses after successful requests."""
import argparse, fcntl, resource, shutil, sys, time, traceback, zipfile
from collections import Counter
from common import *
import prepare,collect,finalize
from api_client import Client,PullStopped

def package_report(folder,desktop):
    files=sorted(folder.iterdir())
    write_json(folder/'RESULT_MANIFEST.json',dict(files=[receipt(p,folder) for p in files]))
    archive=desktop/(folder.name+'.zip')
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(folder.iterdir()):z.write(p,folder.name+'/'+p.name)
    archive.with_suffix('.zip.sha256').write_text(sha(archive)+'  '+archive.name+'\n')
    return archive

def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project-root',type=Path,default=PROJECT)
    ap.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    ap.add_argument('--threads',type=int,default=4)
    ap.add_argument('--max-new-batches',type=int,default=0,help='Optional stopping budget; 0 runs all remaining batches')
    a=ap.parse_args(argv)
    if not 1<=a.threads<=10 or a.max_new_batches<0:ap.error('Invalid threads or batch budget')
    project=a.project_root.expanduser().resolve();desktop=a.desktop.expanduser().resolve()
    if not project.is_dir() or not desktop.is_dir():ap.error('Mount XT_Pro and locate Lichess_Desktop first')
    verify_package();pa.set_cpu_count(1);pa.set_io_thread_count(1)
    soft,hard=resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE,(max(soft,min(4096,hard if hard!=resource.RLIM_INFINITY else 4096)),hard))
    work=project/'derived/replication_36m/receipt_iv_source_api_v100_PRIVATE';work.mkdir(parents=True,exist_ok=True)
    lock=(work/'run.lock').open('a+')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('This API pull is already running')
    started=time.monotonic();runid=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    report=project/'output/receipt_iv_source_api_v100'/('RECEIPT_IV_SOURCE_API_RESULT_'+runid)
    report.mkdir(parents=True,exist_ok=False)
    status='STARTING';errors=[];batches=[];counts=Counter();phase='prepare';plan=None;result=None
    new_batches=0;new_rows=0;reused=0;last_log=0;pull_started=None
    client=Client(cooldown_path=work/'API_COOLDOWN_PRIVATE.json')
    config=dict(version=VERSION,code_signature=code_signature(),endpoint=ENDPOINT,params=PARAMS,
        batch_size=BATCH_SIZE,http_concurrency=1,fixed_success_pause_seconds=0,threads=a.threads,
        optional_token_present=bool(client.token),max_new_batches=a.max_new_batches,
        api_scope='Reviewed unresolved active-opportunity IDs only',
        rating_replays=0,stockfish_searches=0,chronology_rebuilds=0,instrument_scores_recomputed=0)
    write_json(report/'RUN_CONFIGURATION.json',config)
    try:
        with heartbeat('Verifying existing source targets'):
            planroot,plan,contract=prepare.prepare(project,work,a.threads)
        phase='collection';pull_started=time.monotonic()
        log(f"Pull target: {plan['total_ids']:,} games; {plan['total_batches']:,} initial batches; successful requests continue immediately")
        budget_stop=False
        for month in MONTHS:
            for index,targets in prepare.target_batches(planroot/(month+'.parquet')):
                root=work/'batches'/('month='+month)/f'batch-{index:06d}'
                if a.max_new_batches and new_batches>=a.max_new_batches and not (root/'_DONE.json').is_file():
                    budget_stop=True;break
                if not (root/'_DONE.json').is_file() and shutil.disk_usage(work).free<8*1024**3:
                    raise PullStopped('Less than 8 GiB free on the output volume; free space and resume')
                if new_batches==0 and not (root/'_DONE.json').is_file():pull_started=time.monotonic()
                with heartbeat('API request or batch checkpoint'):
                    done,was_new=collect.collect_batch(root,targets,plan['binding'],client,work/'authentication')
                batches.append(dict(root=str(root),done=done));counts.update(done['status_counts'])
                if was_new:new_batches+=1;new_rows+=len(targets)
                else:reused+=1
                # Automatic validation, without a user approval stop. A large
                # mismatch rate is a contract problem, not a usable source fill.
                rejected=counts['returned_metadata_mismatch']+counts['returned_unrecognized_source']
                processed=sum(counts.values())
                if processed>=300 and rejected>max(30,processed*0.10):
                    raise PullStopped('Systematic API metadata mismatches; preserved results require review')
                if processed>=300 and counts['returned_source_missing']>processed*0.90:
                    raise PullStopped('API source field is systematically absent; preserved results require review')
                now=time.monotonic()
                if now-last_log>=20 or len(batches)==plan['total_batches']:
                    rate=new_rows/max(0.001,now-pull_started)
                    remaining=plan['total_ids']-processed
                    eta=f'{remaining/rate/3600:.1f} h' if new_batches>=10 and rate>0 else 'measuring'
                    log(f"Batches {len(batches):,}/{plan['total_batches']:,}; rows {processed:,}; validated {counts['validated_source']:,}; reused {reused:,}; ETA {eta}")
                    write_json(work/'PROGRESS_PRIVATE.json',dict(phase=phase,completed_batches=len(batches),
                        total_batches=plan['total_batches'],completed_rows=processed,total_rows=plan['total_ids'],
                        status_counts=dict(counts),new_requests_this_run=client.requests,eta=eta))
                    last_log=now
            if budget_stop:break
        if len(batches)!=plan['total_batches']:
            status='PAUSED_AT_REQUESTED_BATCH_BUDGET'
        else:
            phase='consolidation'
            with heartbeat('Consolidating metadata and applying cached adjacency'):
                result=finalize.finish(work,plan,contract,batches,a.threads)
            status=result['summary']['status']
    except KeyboardInterrupt:
        status='INTERRUPTED_RESUMABLE';errors.append(dict(stage=phase,exception='KeyboardInterrupt',message='Run the same command to resume'))
    except Exception as e:
        status='STOPPED_RESUMABLE'
        message=str(e) if isinstance(e,(RuntimeError,PullStopped)) else 'See private error details'
        errors.append(dict(stage=phase,exception=type(e).__name__,message=message))
        write_json(work/'errors'/runid/'error_PRIVATE.json',dict(error=str(e),traceback=traceback.format_exc()))
        log('Stopped: '+message)
    summary=dict(status=status,elapsed_seconds=time.monotonic()-started,completed_batches=len(batches),
        reused_batches=reused,new_batches=new_batches,new_requests_this_run=client.requests,
        rate_limits_this_run=client.throttles,status_counts=dict(counts),
        target_rows=plan['total_ids'] if plan else None,total_batches=plan['total_batches'] if plan else None,
        private_work_root=str(work),errors=errors,final_iv_eligible_n=None,new_IV_estimate=None)
    if result:summary.update(result['summary'])
    write_json(report/'SUMMARY.json',summary);write_json(report/'ERRORS.json',errors)
    if result:
        for name,key in [('SOURCE_COVERAGE','coverage'),('SOURCE_COUNTS','source_counts'),
                         ('METADATA_COVERAGE','field_coverage'),('MEMBERSHIP_DELTA','membership_delta')]:
            rows=result['summary'][key];write_json(report/(name+'.json'),rows)
            if rows:pq.write_table(pa.Table.from_pylist(rows),report/(name+'.parquet'),compression='zstd')
    (report/'READ_ME_FIRST.md').write_text(
        'Source and metadata collection for the reviewed unresolved game IDs.\n\n'
        'Native responses, identifiers and row-level Parquets remain on XT_Pro. '
        'This ZIP contains aggregate coverage and cached-adjacency membership counts. '
        'Missing/unreturned or mismatching records stay unresolved. They are never non-pool observations or nonresponders.\n\n'
        'Rerun the same command after interruption; committed requests are reused. '
        'After three successful-response omissions an ID remains explicitly unresolved. '
        'These terminal omissions need review rather than silent exclusion.\n\n'
        'This run does not reconstruct the broader incident denominator, a mechanics censor, '
        'hidden RD, fractional ratings, a final IV cohort or an IV coefficient.\n\n'
        'Upload this ZIP and its SHA-256 sidecar.\n')
    archive=package_report(report,desktop)
    log(status);print('UPLOAD: '+str(archive),flush=True);print('UPLOAD: '+str(archive)+'.sha256',flush=True)
    if status=='INTERRUPTED_RESUMABLE':return 130
    return 2 if status=='STOPPED_RESUMABLE' else 0

if __name__=='__main__':raise SystemExit(main())
