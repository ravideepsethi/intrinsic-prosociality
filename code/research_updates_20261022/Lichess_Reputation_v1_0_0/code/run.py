#!/usr/bin/env python3
"""Run on the user's existing XT_Pro files; exported reports are aggregate only."""
import argparse, concurrent.futures as cf, multiprocessing as mp, sys, shutil, platform, traceback, zipfile, fcntl
from core import *
import inputs, history, analysis

def parallel(jobs,fn,workers,label):
    start=time.monotonic();out=[];total=len(jobs);marks=set();log(f'{label}: {total} jobs, {workers} workers')
    with cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn')) as pool:
        pending={pool.submit(fn,j) for j in jobs}
        while pending:
            done,pending=cf.wait(pending,timeout=30,return_when=cf.FIRST_COMPLETED)
            for future in done:out.append(future.result())
            elapsed=time.monotonic()-start;rate=len(out)/elapsed if elapsed else 0;eta=(total-len(out))/rate if rate else None
            log(f'{label}: {len(out)}/{total}; reused {sum(bool(r.get("reused")) for r in out)}; elapsed {elapsed/60:.1f} min; stage ETA '+(f'{eta/60:.1f} min (approximate)' if eta is not None else 'estimating'))
            for mark in (25,50,75,100):
                if total and len(out)*100/total>=mark and mark not in marks:
                    log(f'{label}: {mark}% checkpoint; continuing automatically');marks.add(mark)
    return sorted(out,key=lambda r:r['folder'])

def release_check():
    manifest=PACKAGE/'PACKAGE_MANIFEST.sha256'
    for line in manifest.read_text().splitlines():
        h,name=line.split('  ',1);p=(PACKAGE/name).resolve()
        if not p.is_relative_to(PACKAGE.resolve()) or sha(p)!=h:raise RuntimeError('Package integrity failure: '+name)
    return sha(manifest)

def export(report,desktop,key,status):
    desktop=Path(desktop);desktop.mkdir(parents=True,exist_ok=True)
    stamp0=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    zp=desktop/f'LICHESS_REPUTATION_REPORT_{key[:12]}_{stamp0}.zip'
    allowed=[]
    for p in Path(report).iterdir():
        if p.is_file() and p.suffix in ('.json','.csv','.txt') and p.name!='REPORT_MANIFEST.json':allowed.append(p)
    dump(Path(report)/'REPORT_MANIFEST.json',[dict(file=p.name,sha256=sha(p),bytes=p.stat().st_size) for p in sorted(allowed)])
    allowed.append(Path(report)/'REPORT_MANIFEST.json')
    with zipfile.ZipFile(zp,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(allowed):z.write(p,p.name)
    Path(str(zp)+'.sha256').write_text(sha(zp)+'  '+zp.name+'\n')
    log(status);log('RETURN_ZIP: '+str(zp));log('RETURN_SHA256: '+str(zp)+'.sha256')

def execute(args):
    package_sha=release_check();project=Path(args.project_root);desktop=Path(args.desktop)
    config=dict(version='1.0.0',package_manifest_sha256=package_sha,pair_sample_denominator=args.pair_sample,
        pair_sample_rule='SplitMix64(unordered uint32 account pair) modulo denominator == 0',
        account_policy=dict(exclude=AUTHORS,scope='Focal and return opportunities; observed all-game chronology preserved'),
        start=START,end_exclusive=END,horizons=[30,90,180],workers=args.workers,memory_mb=args.memory_mb,
        training='Before 2024-05-01 folds 0/1; calibration 2024-08-01 to 2024-11-01 fold 2; evaluation later folds 3/4',
        claim='Descriptive evidence about possible strategic returns; no elimination of recipient approval or audience reputation')
    base=project/'derived/replication/reputation_v100_PRIVATE';base.mkdir(parents=True,exist_ok=True)
    key=digest({k:v for k,v in config.items() if k not in ('workers','memory_mb')});work=base/key[:16];work.mkdir(parents=True,exist_ok=True)
    lock=(work/'RUN.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('This exact reputation run is already active')
    report=work/'report';report.mkdir(exist_ok=True);start=time.monotonic()
    dump(work/'DESIGN_FREEZE.json',config);dump(report/'DESIGN.json',config)
    dump(report/'ENVIRONMENT.json',dict(python=sys.version,platform=platform.platform(),numpy=np.__version__,pyarrow=pa.__version__,duckdb=duckdb.__version__))
    try:
        with heartbeat('Authenticate existing inputs'):inp=inputs.discover(project,work)
        dump(report/'INPUT_SCOPE.json',dict(main_rows=sum(r['rows'] for r in inp['panels']),months=len(inp['panels']),chronology_files=len(inp['chronology']),historical_first_month=inp['historical_first_month'],broader_return_panel=inp['broad_status'],source_identity=inp['source_identity']))
        jobs=[]
        for k,r in enumerate(inp['panels']):
            f=work/'main_projection'/digest(dict(source=r,code=package_sha,sample=args.pair_sample))[:16]
            jobs.append(dict(source=r,folder=str(f),denominator=args.pair_sample,broad=False,month_code=k))
        products=parallel(jobs,inputs.projection_job,args.workers,'Main panel projection')
        # Reconcile the full census before any sampled estimation.
        census=[]
        for p in products:census+=load(Path(p['folder'])/'census.json')
        grouped={}
        for r in census:
            k=(r['month'],r['region']);a=grouped.setdefault(k,dict(month=k[0],region=k[1],n=0,grants=0));a['n']+=r['n'];a['grants']+=r['grants']
        for r in grouped.values():r['grant_pct']=100*r['grants']/r['n'] if r['n'] else None
        table_csv(list(grouped.values()),report/'full_panel_census.csv')
        dump(report/'ACCOUNT_EXCLUSION.json',dict(excluded_names=AUTHORS,removed_focal_rows=sum(p['author_rows'] for p in products),original_rows=sum(p['source_rows'] for p in products),sampled_rows=sum(p['sampled_rows'] for p in products)))
        ppaths=[Path(p['folder'])/'panel.parquet' for p in products]
        queries=work/'queries'/digest([stamp(p) for p in ppaths])[:16]
        with heartbeat('Prepare fixed pair sample'):qm=history.make_queries(ppaths,queries,args.workers,args.memory_mb)
        qsignature=sha(queries/'_DONE.json');dump(report/'SAMPLE.json',qm)
        jobs=[]
        for r in inp['chronology']:
            f=work/'chronology'/digest(dict(record=r,queries=qsignature,code=package_sha,old=inp['old_cache']))[:16]
            jobs.append(dict(record=r,folder=str(f),queries=str(queries),old_cache=inp['old_cache']))
        hp=parallel(jobs,history.chronology_job,args.workers,'Pair history and activity')
        dump(report/'HISTORY_WORK.json',dict(source_jobs=len(hp),reused_jobs=sum(p['reused'] for p in hp),old_first_pair_cache_jobs=sum(p['old_first_pair_cache_reused'] for p in hp),source_rows_read=sum(p['read_rows'] for p in hp),matched_events=sum(p['matched_events'] for p in hp),invalid_source_rows=sum(p['invalid_source_rows'] for p in hp)))
        merged=work/'merged_history'/digest([sha(Path(p['folder'])/'_DONE.json') for p in hp])[:16]
        with heartbeat('Merge histories and verify focal identities'):hm=history.merge_history(hp,queries,merged,args.workers,args.memory_mb)
        dump(report/'HISTORY_QA.json',hm)
        returns=ppaths;scope='MAIN_POOL_NONADJACENT_ONLY: restricted coverage, not an upper bound on all repayment'
        if inp['broad']:
            jobs=[]
            for r in inp['broad']:
                f=work/'broad_projection'/digest(dict(source=r,code=package_sha,sample=args.pair_sample))[:16]
                jobs.append(dict(source=r,folder=str(f),denominator=args.pair_sample,broad=True))
            bp=parallel(jobs,inputs.projection_job,args.workers,'All-source repayment opportunities')
            returns=[Path(p['folder'])/'panel.parquet' for p in bp];scope='ALL_SOURCE_STAGE07_24M: includes observed rematches/challenges; active decisions only'
        else:log('Broader repayment panel could not be authenticated from the pinned manifest; restricted-panel results will be labeled explicitly.')
        feature=work/'features'/digest(dict(history=sha(merged/'_DONE.json'),returns=[stamp(p) for p in returns]))[:16]
        with heartbeat('Construct encounter and repayment windows'):fm=analysis.make_features(merged,returns,feature,args.workers,args.memory_mb,scope)
        dump(report/'FEATURE_QA.json',fm)
        analysis_folder=work/'analyses'/sha(feature/'_DONE.json')[:16]
        with heartbeat('Analysis'):result=analysis.run_analyses(feature/'analysis.parquet',analysis_folder,scope)
        for p in analysis_folder.iterdir():
            if p.is_file() and p.suffix in ('.json','.csv','.txt'):shutil.copyfile(p,report/p.name)
        if (report/'ERROR.json').exists():(report/'ERROR.json').unlink()
        status='REPUTATION_ANALYSIS_COMPLETE'
        if any(r['status']!='COMPLETE' for r in result['module_status']):status='REPUTATION_ANALYSIS_COMPLETE_WITH_UNSUPPORTED_MODULE'
        dump(report/'SUMMARY.json',dict(status=status,**result,elapsed_seconds=time.monotonic()-start,api_requests=0,stockfish_searches=0,rating_replays=0,existing_outputs_modified=False))
        (report/'READ_RESULTS.txt').write_text('Read full_panel_census.csv, reencounters_and_repayment.csv, prediction_calibration.csv (if supported), low_risk_grant_rates.csv and estimates.csv.\n'
          'All inference is descriptive and conditional on the sampling/prediction design. Check module_status.json and covariance support.\n'
          'Focal sample is a fixed unordered-pair sample; full-panel rates are reported separately. No pair is selected using future meetings or granting.\n'
          'Actual return opportunities can be affected by the initial action. Monetary sums are observed-path finite-horizon capacities, not ex ante expected benefits or lifetime bounds.\n'
          'The anchor is lastMoveAt, not a button-click timestamp. The one-hour encounter sensitivity is reported separately.\n'
          'Absence of recorded meetings does not imply anonymity. Spectators, chat, off-platform contact, and recipient approval remain unobserved.\n'
          'Prediction labels depend on observed behavior; low predicted risk must be assessed against realized evaluation calibration.\n')
        export(report,desktop,key,status)
    except Exception as e:
        (work/'ERROR_PRIVATE.txt').write_text(traceback.format_exc())
        text=str(e).replace(str(project),'[PROJECT]').replace(str(work),'[RUN]')
        dump(report/'ERROR.json',dict(status='STOPPED_WITH_CHECKPOINTS_PRESERVED',error_type=type(e).__name__,message=text,elapsed_seconds=time.monotonic()-start))
        export(report,desktop,key,'STOPPED_WITH_CHECKPOINTS_PRESERVED');raise
    finally:lock.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--project-root',default='/Volumes/XT_Pro/lichess_kindness');p.add_argument('--desktop',default=str(Path.home()/'Desktop/Lichess_Desktop'))
    p.add_argument('--workers',type=int,default=4);p.add_argument('--memory-mb',type=int,default=4096);p.add_argument('--pair-sample',type=int,default=5)
    a=p.parse_args()
    if not 1<=a.workers<=10 or a.pair_sample<1 or a.memory_mb<512:p.error('workers 1..10, positive pair sample, memory >=512 MB required')
    execute(a)
