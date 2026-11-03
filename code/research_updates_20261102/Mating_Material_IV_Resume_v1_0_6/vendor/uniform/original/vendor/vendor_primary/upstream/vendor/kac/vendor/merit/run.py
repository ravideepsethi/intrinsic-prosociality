#!/usr/bin/env python3
from common import *
import argparse, concurrent.futures as cf, multiprocessing as mp, fcntl, zipfile, traceback, sys
from source import pool_wave1_common as authority
from prepare import project_month,partition,raw_summaries
from design import specifications,design
from estimate import run_bucket,aggregate_first,aggregate_meat
from report import write_report

def workers_map(fn,tasks,workers,label):
    results=[];t0=time.monotonic();completed=0;durations=[]
    with heartbeat(label),cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn')) as pool:
        futures={pool.submit(fn,t):t for t in tasks}
        for future in cf.as_completed(futures):
            r=future.result();results.append(r);completed+=1
            if r['seconds']>0:durations.append(r['seconds'])
            eta=(len(tasks)-completed)*float(np.mean(durations))/workers/60 if durations else 0
            log(f'{label}: {completed}/{len(tasks)}; '+('checkpoint reused' if r['reused'] else f'{r["seconds"]:.1f}s')+f'; approximate remaining {eta:.1f} min')
    return results

def analyse(run,projections,specs,part,workers,memory,key,validation):
    run=Path(run);bybucket={}
    for x in part['files']:
        bucket=int(Path(x['relative']).parts[0].split('=')[1]);bybucket.setdefault(bucket,[]).append(run/'PRIVATE/by_chooser'/x['relative'])
    largest=max(sum(pq.ParquetFile(p).metadata.num_rows for p in files) for files in bybucket.values())
    # Conservative live arrays: original, demeaned, product, temporary, and group scores.
    per_worker_gb=(largest*8*(4*80+70)+200_000_000)/2**30
    require(per_worker_gb<=memory*.9,'A chooser partition exceeds the memory budget; rerun with --shards 512 (or a larger --memory-gb budget).')
    nw=max(1,min(workers,int(memory*.85/max(per_worker_gb,.5))))
    log(f'Estimation: {len(bybucket)} chooser partitions; {nw} processes × 1 numerical thread; estimated RAM per process <= {per_worker_gb:.1f} GiB')
    dump(run/'report/RESOURCE_PLAN.json',dict(cpu_worker_limit=workers,actual_estimation_workers=nw,memory_budget_gb=memory,
        largest_partition_rows=largest,estimated_worker_gb=per_worker_gb,shards=len(bybucket),models=len(specs)))
    paths=[];tasks=[]
    for b,files in sorted(bybucket.items()):
        out=run/f'PRIVATE/moments/first_{b:04d}.npz';paths.append(out)
        tasks.append(dict(bucket=b,files=list(map(str,files)),out=str(out),key=fingerprint([key,'first',b]),specs=specs,phase=1))
    t0=time.monotonic();res1=workers_map(run_bucket,tasks,nw,'Regression moments')
    fits=aggregate_first(paths,specs)
    log('All model coefficients solved; now computing chooser-cluster inference and baseline uncertainty.')
    second=[];tasks=[]
    for b,files in sorted(bybucket.items()):
        out=run/f'PRIVATE/moments/second_{b:04d}.npz';second.append(out)
        tasks.append(dict(bucket=b,files=list(map(str,files)),out=str(out),key=fingerprint([key,'second',b,[f['beta'].tolist() for f in fits]]),specs=specs,phase=2,fits=fits))
    res2=workers_map(run_bucket,tasks,nw,'Cluster inference')
    meats=aggregate_meat(second,specs)
    with heartbeat('Rendering aggregate report'):write_report(run,specs,fits,meats,validation)
    dump(run/'report/TIMINGS.json',dict(estimation_wall_seconds=time.monotonic()-t0,first=res1,second=res2))
    return fits

def package_result(run,destination):
    run=Path(run);destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    # Explicit report and code allowlist: never include PRIVATE/, raw frames, or account identifiers.
    stamp=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime());p=destination/f'KAC_CONTINUOUS_MERIT_RESULT_{stamp}.zip'
    with zipfile.ZipFile(p,'w',zipfile.ZIP_DEFLATED) as z:
        for f in sorted((run/'report').rglob('*')):
            if f.is_file():z.write(f,'report/'+str(f.relative_to(run/'report')))
        for f in sorted(ROOT.rglob('*')):
            if f.is_file() and (f.suffix in ['.py','.command','.md','.txt','.json'] or f.name.startswith('Pool_Main_Sample_24M_Report.zip')) and not any(x.startswith('.') or x=='__pycache__' for x in f.relative_to(ROOT).parts):
                z.write(f,'executed_code/'+str(f.relative_to(ROOT)))
    p.with_suffix('.zip.sha256').write_text(sha(p)+'  '+p.name+'\n');return p

def main():
    ap=argparse.ArgumentParser(description='A1 continuous merit; existing certified Parquets only')
    ap.add_argument('--project',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    ap.add_argument('--sample-root',type=Path)
    ap.add_argument('--workers',type=int,default=10)
    ap.add_argument('--memory-gb',type=float,default=None,help='Total numerical working-memory budget; default <= half physical RAM, capped at 12 GiB')
    ap.add_argument('--shards',type=int,default=256)
    ap.add_argument('--result-dir',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    args=ap.parse_args();require(1<=args.workers<=10,'workers must be 1..10');require(args.shards>=32,'At least 32 partitions required')
    memory=args.memory_gb or min(12.,max(2.,physical_gb()*.5));require(memory>=2,'At least 2 GiB memory budget required')
    # Reserve CPU slots for identifiable Stockfish engines already running on this machine.
    try:
        active=sum('stockfish' in Path(x.strip()).name.lower() for x in subprocess.check_output(['ps','-axo','comm='],text=True).splitlines())
    except Exception:active=0
    workers=max(1,args.workers-active)
    if active:log(f'{active} Stockfish processes detected; A1 uses at most {workers} of the requested {args.workers} CPU slots.')
    require(active<args.workers,'All requested CPU slots are occupied by Stockfish; rerun this same command after they finish.')
    specs=specifications();code={str(p.relative_to(ROOT)):sha(p) for p in sorted(ROOT.rglob('*.py')) if not any(x.startswith('.') for x in p.relative_to(ROOT).parts)}
    import scipy,pyarrow
    versions=dict(numpy=np.__version__,pandas=pd.__version__,scipy=scipy.__version__,duckdb=duckdb.__version__,pyarrow=pyarrow.__version__)
    sample=args.sample_root or args.project/'derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE'
    log('Checking certified current-sample authority and monthly Parquet footers.')
    auth=authority.authenticate_sample(sample,verify_hashes=False,hash_workers=1)
    key=fingerprint(dict(code=code,sample=auth['fingerprint'],specs=specs,shards=args.shards,versions=versions))
    run=args.project/'derived/replication/kac_merit_continuous_v100_PRIVATE'/key[:16]
    run.mkdir(parents=True,exist_ok=True);(run/'report').mkdir(exist_ok=True);(run/'PRIVATE').mkdir(exist_ok=True)
    lock=open(run/'RUNNING.lock','a+')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('This exact A1 run is already active. No duplicate job started.')
    success=run/'_SUCCESS.json'
    if success.exists():
        receipt=load(success)
        for item in receipt['report_files']:
            require(sha(run/'report'/item['name'])==item['sha256'],'Completed aggregate report was modified')
        artifact=Path(receipt['result_zip'])
        if not artifact.exists():artifact=package_result(run,args.result_dir)
        log('KAC_CONTINUOUS_MERIT_OK — completed checkpoint reused: '+str(artifact));return
    require(shutil_disk_free(args.project)>12*2**30,'Need at least 12 GiB free for narrow projections, partitions, and spill.')
    start=time.monotonic()
    dump(run/'PRIVATE/RUN_CONFIG.json',dict(key=key,args=vars(args),code=code,specs=specs,input_root=str(sample),created_utc=authority.utc_now()))
    lineage=authority.compact_sample_lineage(auth);lineage.pop('panel_root_machine_specific',None)
    dump(run/'report/SAMPLE_LINEAGE.json',lineage)
    dump(run/'report/ENVIRONMENT.json',dict(python=sys.version,platform=platform.platform(),numpy=np.__version__,pandas=pd.__version__,
          scipy=scipy.__version__,duckdb=duckdb.__version__,pyarrow=pyarrow.__version__,worker_limit=workers,memory_gb=memory,code_sha256=code))
    try:
        tasks=[];projections=[]
        for r in auth['month_records']:
            out=run/'PRIVATE/projected'/f'{r["month"]}.parquet';projections.append(out)
            tasks.append(dict(source=str(r['path']),expected_sha256=r['expected_sha256'],rows=r['rows'],month=r['month'],output=str(out),key=key,memory_gb=max(.5,min(1.5,memory/4))))
        times=workers_map(project_month,tasks,min(4,workers), 'Authenticate and project')
        require(sum(r['n'] for r in times)==41534331,'Main opportunity count differs')
        require(sum(r['grants'] for r in times)==570091,'Main grant count differs')
        require(sum(r['competitive'] for r in times)==15207423,'Competitive count differs')
        require(sum(r['competitive_grants'] for r in times)==419463,'Competitive grant count differs')
        require(sum(r['competitive_late'] for r in times)==11590459,'Competitive late count differs')
        table(run/'report/monthly_validation',times)
        with heartbeat('Raw support and census'):
            validation=raw_summaries(projections,run,workers,memory)
        require(validation['choosers']==3224173,'Chooser census differs');dump(run/'report/CENSUS.json',validation)
        log('CENSUS_OK: 41,534,331 opportunities; 570,091 grants. Building chooser-complete Parquet partitions.')
        with heartbeat('Chooser partitioning'):
            part=partition(projections,run,args.shards,workers,memory,key)
        fits=analyse(run,projections,specs,part,workers,memory,key,validation)
        dump(run/'report/COMPLETION.json',dict(status='KAC_CONTINUOUS_MERIT_OK',models=len(fits),total_wall_seconds=time.monotonic()-start,
            no_new_engine_evaluations=True,no_api_requests=True,sample_fingerprint=auth['fingerprint']))
        artifact=package_result(run,args.result_dir)
        files=[dict(name=str(p.relative_to(run/'report')),sha256=sha(p)) for p in sorted((run/'report').rglob('*')) if p.is_file()]
        dump(success,dict(status='KAC_CONTINUOUS_MERIT_OK',key=key,result_zip=str(artifact),report_files=files,seconds=time.monotonic()-start))
        log('KAC_CONTINUOUS_MERIT_OK');log('Result ZIP: '+str(artifact));log(f'Elapsed {(time.monotonic()-start)/60:.1f} minutes.')
    except Exception as e:
        dump(run/'PRIVATE/FAILURE.json',dict(error=str(e),traceback=traceback.format_exc(),utc=authority.utc_now()))
        log('Run stopped; completed checkpoints preserved. Private diagnostic: '+str(run/'PRIVATE/FAILURE.json'))
        raise
    finally:lock.close()

def shutil_disk_free(p):
    import shutil
    return shutil.disk_usage(p).free

if __name__=='__main__':main()
