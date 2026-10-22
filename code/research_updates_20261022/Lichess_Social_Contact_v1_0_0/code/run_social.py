#!/usr/bin/env python3
from core import *
import argparse,fcntl,platform,traceback,zipfile,collections,math,sys
import prepare,acquire,contact

def verify_release():
    p=PACKAGE/'PACKAGE_MANIFEST.sha256'
    for line in p.read_text().splitlines():
        h,name=line.split('  ',1);q=(PACKAGE/name).resolve()
        if not q.is_relative_to(PACKAGE.resolve()) or sha(q)!=h:raise RuntimeError('Package integrity failure')
    return sha(p)

def export(report,desktop,key,status):
    desktop=Path(desktop);desktop.mkdir(parents=True,exist_ok=True);report=Path(report)
    files=sorted(p for p in report.iterdir() if p.is_file() and p.suffix in ('.json','.csv','.txt') and p.name!='REPORT_MANIFEST.json')
    dump(report/'REPORT_MANIFEST.json',[dict(file=p.name,bytes=p.stat().st_size,sha256=sha(p)) for p in files])
    stamp0=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    path=desktop/f'LICHESS_SOCIAL_CONTACT_REPORT_{key[:12]}_{stamp0}.zip'
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        for p in files+[report/'REPORT_MANIFEST.json']:z.write(p,p.name)
    Path(str(path)+'.sha256').write_text(sha(path)+'  '+path.name+'\n')
    log(status);log('RETURN_ZIP: '+str(path));log('RETURN_SHA256: '+str(path)+'.sha256')

def local_summary(targets,report):
    out=[]
    for h in (30,90,180):
        for arm in (False,True):
            rr=[r for r in targets if r['y']==arm]
            out.append(dict(horizon=h,initial_action='grant' if arm else 'claim',n=len(rr),
                any_later_rated_pct=100*float(np.mean([r['meet'+str(h)]>0 for r in rr])),
                mean_later_rated_games=float(np.mean([r['meet'+str(h)] for r in rr]))))
    table_csv(out,Path(report)/'LOCAL_RATED_CONTACTS.csv')

def execute(args):
    package_sha=verify_release();project=Path(args.project_root);base=project/'derived/replication/social_contact_v100_PRIVATE';base.mkdir(parents=True,exist_ok=True)
    config=dict(version='1.0.0',package_manifest_sha256=package_sha,max_matched_sets=args.max_sets,selection='same chooser, quarter, speed, evaluation band; first recorded rated meeting; 180-day follow-up',
      targets='One grant and one claim per selected overlap cell, fixed hashes independent of later contact',
      history='Public pair-filtered game export, rated filter omitted, all speeds and variants, 90 days before and 180 after; completed games',
      friendship='Historical follow edges not observed; source friend is not evidence of a follow link',
      network='Sequential read-only public exports; no credentials, messages, follow actions, or challenge creation')
    key=digest(config);work=base/key[:16];work.mkdir(exist_ok=True);report=work/'report';report.mkdir(exist_ok=True)
    runlock=(work/'RUN.lock').open('a')
    try:fcntl.flock(runlock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('This exact social-contact run is already active')
    start=time.monotonic();dump(report/'DESIGN.json',config);dump(report/'ENVIRONMENT.json',dict(python=sys.version,platform=platform.platform(),numpy=np.__version__,pyarrow=pa.__version__,duckdb=duckdb.__version__))
    try:
        with heartbeat('Validate and reuse completed reputation cache'):parent=prepare.parent_run(project,work)
        with heartbeat('Select matched grant and claim encounters'):selection=prepare.matched_targets(parent['features'],work/'selection',args.max_sets,args.workers,args.memory_mb)
        dump(report/'SELECTION.json',selection)
        with heartbeat('Resolve account names and expected rated games'):prep=prepare.add_names_and_expected(parent,work/'selection/selected.parquet',work/'prepared',project,args.workers,args.memory_mb)
        dump(report/'PREPARATION.json',prep)
        targets=pq.ParquetFile(work/'prepared/targets.parquet').read().to_pylist();local_summary(targets,report)
        expected=collections.defaultdict(dict)
        for r in pq.ParquetFile(work/'prepared/expected_rated.parquet').read().to_pylist():expected[r['focal_gid']][r['gid']]=r['t']
        for t in targets:
            if t['gid'] not in expected[t['gid']]:raise RuntimeError('Focal ID absent from parent encounter cache')
        dump(report/'FORMAL_FRIENDSHIP.json',dict(status='NOT_OBSERVED',needed='Dated directed follow-edge additions/removals and pre-index relationship state; not supplied by the current project files',
          limitation='Repeated play and source=friend are behavioral proxies; no formal friendship formation estimate is produced'))
        (report/'READ_RESULTS.txt').write_text('Compare contact_rates_and_missing_bounds.csv and matched_estimates.csv.\n'
          'Matching holds the chooser, quarter, speed and evaluation band fixed. These are associations, not effects of randomly assigned gifts.\n'
          'Unknown API histories remain unknown, never zero. Bounds cover the full selected roster; regressions use matched sets with observed outcomes.\n'
          'Game source friend does not establish a follow relationship. Non-pool includes lobby and organized play; pool labels need not imply an accidental reunion.\n'
          'Direct-source categories, casual games, late contacts and repeated dates are reported separately. All source types enter total contact.\n'
          'No stockfish, rating replay, or historical-archive rescan. Parent outputs are read-only.\n')
        log(f"Selected {len(targets):,} pair histories ({selection['selected_sets']:,} matched sets).")
        log(f'At one request per second the spacing alone is {len(targets)/3600:.1f} hours; actual ETA follows measured API throughput. Cached pairs need no request.')
        api_lock=(base/'API.lock').open('a')
        try:fcntl.flock(api_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('Another social-contact downloader is active; no second network stream started')
        client=acquire.Client();rows=[];reused=0;counts=collections.Counter();source_counts=collections.Counter();last=time.monotonic();netstart=last;marks=set();success=0
        try:
            with heartbeat('Pair history acquisition'):
                for k,t in enumerate(targets,1):
                    games,qa=acquire.acquire_one(t,expected[t['gid']],base/'pair_api_cache',client,args.retry_unavailable)
                    reused+=int(qa['reused']);counts[qa['status']]+=1
                    if qa['status']=='UNAVAILABLE':counts['reason: '+qa['reason']]+=1
                    if games is not None:
                        success+=1
                        for g in games:source_counts[g['source'] or '[missing]']+=1
                    rows.append(dict(**t,**contact.outcomes(t,games)))
                    # Do not spend a full run on a broken export/identity contract.
                    if k==20 and success==0:raise RuntimeError('The first 20 histories all failed verification; report contains reasons. No missing history was coded as zero.')
                    if k%500==0 or k==len(targets):
                        part=work/'pair_metrics'/f'part_{(k-1)//500:05d}.parquet';part.parent.mkdir(exist_ok=True)
                        batch=rows[-(k%500 or 500):] if k%500 else rows[-500:]
                        pq.write_table(pa.Table.from_pylist(batch),part,compression='zstd')
                    now=time.monotonic()
                    if now-last>=30 or k==len(targets):
                        rate=(k-reused)/(now-netstart) if now>netstart else 0;eta=(len(targets)-k)/rate if rate>0 else None
                        nextmark=next((m for m in (25,50,75,100) if k*100/len(targets)<m),100)
                        to_next=max(0,(math.ceil(len(targets)*nextmark/100)-k))/rate if rate>0 else None
                        log(f'Pair histories {k:,}/{len(targets):,}; cached {reused:,}; verified {success:,}; unavailable {k-success:,}; '+
                          (f'ETA {nextmark}% {to_next/3600:.2f} h, finish {eta/3600:.2f} h' if eta is not None else 'ETA estimating'))
                        last=now
                    for mark in (25,50,75,100):
                        if k*100/len(targets)>=mark and mark not in marks:
                            marks.add(mark);dump(report/'DOWNLOAD_PROGRESS.json',dict(completed=k,total=len(targets),reused=reused,api_requests=client.requests,status_counts=counts,checkpoint_percent=mark))
                            log(f'{mark}% checkpoint saved; continuing automatically')
                dump(report/'DOWNLOAD_PROGRESS.json',dict(completed=len(targets),total=len(targets),reused=reused,api_requests=client.requests,status_counts=counts,checkpoint_percent=100))
        finally:
            dump(report/'DOWNLOAD_DIAGNOSTICS.json',dict(completed=len(rows),total=len(targets),reused=reused,api_requests=client.requests,status_counts=counts))
            api_lock.close()
        table_csv([dict(source=k,games=n) for k,n in sorted(source_counts.items())],report/'GAME_SOURCE_COUNTS.csv')
        with heartbeat('Matched contact analysis'):result=contact.analyze(rows,report)
        status='SOCIAL_CONTACT_COMPLETE' if result['failed_histories']==0 else 'SOCIAL_CONTACT_COMPLETE_WITH_MISSING_HISTORIES'
        dump(report/'SUMMARY.json',dict(status=status,**result,elapsed_seconds=time.monotonic()-start,api_requests=client.requests,parent_history_rescanned=False,parent_outputs_modified=False))
        if (report/'ERROR.json').exists():(report/'ERROR.json').unlink()
        export(report,args.desktop,key,status)
    except Exception as e:
        (work/'ERROR_PRIVATE.txt').write_text(traceback.format_exc())
        dump(report/'ERROR.json',dict(status='STOPPED_WITH_CHECKPOINTS_PRESERVED',error_type=type(e).__name__,message=str(e).replace(str(project),'[PROJECT]'),elapsed_seconds=time.monotonic()-start))
        export(report,args.desktop,key,'STOPPED_WITH_CHECKPOINTS_PRESERVED');raise
    finally:runlock.close()

if __name__=='__main__':
    import math
    p=argparse.ArgumentParser();p.add_argument('--project-root',default='/Volumes/XT_Pro/lichess_kindness');p.add_argument('--desktop',default=str(Path.home()/'Desktop/Lichess_Desktop'))
    p.add_argument('--max-sets',type=int,default=20000);p.add_argument('--workers',type=int,default=4);p.add_argument('--memory-mb',type=int,default=4096);p.add_argument('--retry-unavailable',action='store_true')
    args=p.parse_args()
    if not 1<=args.workers<=10 or args.max_sets<1 or args.memory_mb<512:p.error('workers 1..10, positive max-sets, memory at least 512 MB')
    execute(args)
