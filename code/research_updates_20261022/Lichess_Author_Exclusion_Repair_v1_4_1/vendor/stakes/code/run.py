#!/usr/bin/env python3
from __future__ import annotations
import argparse, concurrent.futures as cf, multiprocessing as mp, platform, sys, traceback, threading
from common import *
from prepare import sources,author_ids,prepare_month,needed
from history import catalog,speed_task
from report import summarize,bundle

def package_identity():
    p=ROOT/'PACKAGE_MANIFEST.sha256'
    for line in p.read_text().splitlines():
        h,rel=line.split('  ',1);path=ROOT/rel
        if not path.resolve().is_relative_to(ROOT.resolve()) or sha(path)!=h:raise RuntimeError('Package checksum differs: '+rel)
    return sha(p)

def parallel(fn,jobs,workers):
    if workers==1:return [fn(j) for j in jobs]
    result=[]
    with cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn')) as pool:
        pending=[pool.submit(fn,j) for j in jobs]
        for future in cf.as_completed(pending):result.append(future.result())
    return result

def main():
    p=argparse.ArgumentParser(description='Finite rating-stakes descriptives from existing local Parquet files')
    p.add_argument('--project-root',default='/Volumes/XT_Pro/lichess_kindness')
    p.add_argument('--desktop',default=str(Path.home()/'Desktop/Lichess_Desktop'))
    p.add_argument('--history-start',default='2023-08',help='Bounded warm-up, <=2023-10; incomplete windows remain unavailable')
    p.add_argument('--workers',type=int,default=5,help='1–10; at most five parallel speed histories')
    p.add_argument('--memory-mb',type=int,default=2048,help='DuckDB budget per worker; NumPy arrays need additional memory')
    p.add_argument('--buckets',type=int,default=64,help='More buckets reduce NumPy working memory')
    p.add_argument('--preflight-only',action='store_true')
    a=p.parse_args()
    if not 1<=a.workers<=10 or a.memory_mb<512 or a.buckets<8:p.error('workers 1–10, memory >=512 MB, buckets >=8 required')
    try:month=str(pd.Period(a.history_start,'M'))
    except ValueError:p.error('history-start must be YYYY-MM')
    if month!=a.history_start or not '2013-01'<=month<='2023-10':p.error('history-start must be between 2013-01 and 2023-10')
    code=package_identity();project=Path(a.project_root).resolve()
    run_key=digest(dict(code=code,project=str(project),history_start=month,buckets=a.buckets))
    work=project/'derived/replication/win_premium_stakes_v100_PRIVATE'/run_key[:12]
    report=project/'output/win_premium_stakes_v100'/run_key[:12]
    work.mkdir(parents=True,exist_ok=True);report.mkdir(parents=True,exist_ok=True)
    import fcntl
    lock=open(work/'RUN.lock','a+')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit('This same run is already active; no second writer started.')
    stop=threading.Event();started=time.monotonic()
    def heartbeat():
        while not stop.wait(45):log(f'Still working; elapsed {(time.monotonic()-started)/60:.1f} minutes. Completed speed/months are resumable.')
    threading.Thread(target=heartbeat,daemon=True).start()
    write(work/'RUN_CONFIG.json',dict(**vars(a),code=code,run_key=run_key,python=sys.version,platform=platform.platform(),duckdb=duckdb.__version__))
    try:
        inputs=sources(project);records=catalog(project,month);ids=author_ids(project,work)
        total=sum(r['rows'] for r in records)
        log(f'Inputs: {len(inputs)} main months, {len(records)} history files, {total:,} source games. No API, replay or engine work.')
        log('This is a multi-hour history scan on an external SSD; completed months are cached. Timing CSV records measured stage durations.')
        for r in records:history_evidence(r['path'],r['rows'],r['bytes'])
        write(report/'PREFLIGHT.json',dict(status='READY',history_files=len(records),history_source_games=total,
              history_start=month,author_accounts_excluded=list(ids),history_complete_win_gain='UNAVAILABLE_START_TIMES_ONLY'))
        if a.preflight_only:
            log('Preflight passed. Rerun without --preflight-only to calculate the tables.');return 0
        files=parallel(prepare_month,[(r,str(work),ids,a.memory_mb) for r in inputs],a.workers)
        needed(work,files,min(a.workers,4),a.memory_mb)
        jobs=[(s,records,str(work),ids,a.buckets,a.memory_mb,2,run_key) for s in SPEEDS]
        outputs=parallel(speed_task,jobs,min(a.workers,len(SPEEDS)))
        outputs=sorted(f for group in outputs for f in group)
        if len(outputs)!=len(MONTHS)*len(SPEEDS):raise RuntimeError('Missing speed/month output')
        n=summarize(work,report,outputs,max(4096,a.memory_mb))
        write(report/'RUN_TIME.json',dict(elapsed_seconds=time.monotonic()-started,opportunities=n))
        output=bundle(report,a.desktop);log('COMPLETE: '+str(output));return 0
    except Exception as e:
        write(work/'ERROR_PRIVATE.json',dict(error=str(e),traceback=traceback.format_exc()))
        write(report/'STATUS.json',dict(status='INCOMPLETE',error=str(e)))
        log('STOPPED: '+str(e));log('Inputs were not modified. Correct the reported issue and rerun the same command.');return 1
    finally:stop.set();lock.close()

if __name__=='__main__':sys.exit(main())
