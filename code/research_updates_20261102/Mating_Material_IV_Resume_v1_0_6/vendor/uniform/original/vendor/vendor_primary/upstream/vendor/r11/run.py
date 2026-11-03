#!/usr/bin/env python3
"""R11 local-only, resumable runner. No source mutation, API, or Stockfish."""
from common import *
import argparse,concurrent.futures as cf,multiprocessing as mp,fcntl,zipfile,sys,shutil,traceback
from source import pool_wave1_common as authority
from design import design,moments_design,dummy,COLS,specification
from prepare import project_month,partition,raw_summaries,reuse_r10
from estimate import task,fit_first,combine
from report import write_report
from r10_check import compare_archived_r10
import all_games

def mapped(fn,tasks,workers,label,next_checkpoint,finish_note):
    start=time.monotonic();out=[];new_seconds=[]
    with heartbeat(label),cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn')) as pool:
        futures=[pool.submit(fn,t) for t in tasks]
        try:
            for f in cf.as_completed(futures):
                r=f.result();out.append(r)
                if r.get('seconds',0)>0:new_seconds.append(r['seconds'])
                eta=(len(tasks)-len(out))*float(np.mean(new_seconds))/workers if new_seconds else 0
                log(f'{label}: {len(out)}/{len(tasks)}; '+('reused' if r.get('reused') else f'{r.get("seconds",0):.1f}s')+
                    f'; ETA remaining work to {next_checkpoint}: {eta/60:.1f} min; finish: {finish_note}')
        except BaseException:
            for f in futures:f.cancel()
            raise
    return out

def package_report(run,destination,key,percent,status):
    report=run/'report';report.mkdir(parents=True,exist_ok=True)
    dump(report/'CHECKPOINT.json',dict(run_id=key[:12],percent=percent,status=status,utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())))
    manifest=[dict(file=str(p.relative_to(report)),bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(report.rglob('*')) if p.is_file() and p.name!='REPORT_FILE_HASHES.json']
    dump(report/'REPORT_FILE_HASHES.json',manifest)
    destination.mkdir(parents=True,exist_ok=True);path=destination/f'R11_REPORT_{key[:12]}_{percent:03d}.zip';tmp=path.with_suffix('.zip.partial')
    # Report allowlist: no projection/chooser-level data or identifiers are exported.
    for p in report.rglob('*'):
        if p.suffix=='.parquet':
            require(not {'chooser','chooser_user_id','game_id','disconnected_user_id'}&set(pq.ParquetFile(p).schema_arrow.names),'Identifier column in report')
    with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(report.rglob('*')):
            if p.is_file():z.write(p,'report/'+str(p.relative_to(report)))
    os.replace(tmp,path);path.with_suffix('.zip.sha256').write_text(sha(path)+'  '+path.name+'\n')
    log(f'CHECKPOINT {percent}%: {status}; report saved: {path}')
    return path

def regression_seal(run,key):
    files=[dict(file=str(p.relative_to(run/'report')),sha256=sha(p)) for p in sorted((run/'report').rglob('*'))
      if p.is_file() and p.name not in ['REPORT_FILE_HASHES.json','CHECKPOINT.json','ALL_GAMES_STATUS.json','COMPLETION.json'] and not p.name.startswith('all_games_')]
    dump(run/'PRIVATE/REGRESSIONS_COMPLETE.json',dict(key=key,files=files))

def verified_regressions(run,key):
    p=run/'PRIVATE/REGRESSIONS_COMPLETE.json'
    if not p.is_file():return False
    r=load(p);require(r['key']==key,'Regression completion key differs')
    for f in r['files']:require(sha(run/'report'/f['file'])==f['sha256'],'Saved regression report changed: '+f['file'])
    return True

def estimate_models(args,run,key):
    sample=args.sample_root or args.project/'derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE'
    require(sample.exists(),'Original certified opportunity sample not found: '+str(sample))
    with heartbeat('Authenticate the 24 certified inputs; next checkpoint 25%'):
        auth=authority.authenticate_sample(sample,verify_hashes=True,hash_workers=min(args.workers,4))
    lineage=authority.compact_sample_lineage(auth);lineage.pop('panel_root_machine_specific',None);dump(run/'report/SAMPLE_LINEAGE.json',lineage)
    reuse_root=args.reuse_r10_root or args.project/'derived/replication/r10_two_questions_v100_PRIVATE/6bb9fb7c3d51'
    paths=None;bybucket=None
    if reuse_root.is_dir():
        try:
            with heartbeat('Verify R10 projections and chooser partitions; next checkpoint 25%'):
                paths,bybucket,reuse=reuse_r10(reuse_root,auth,args.shards)
            dump(run/'report/INPUT_REUSE.json',reuse);log('Verified R10 input partitions reused; fitting the new R11 model.')
        except Exception as e:
            log('R10 input reuse unavailable; rebuilding from authenticated inputs: '+str(e));paths=None;bybucket=None
    if paths is None:
        require(shutil.disk_usage(args.project).free>=16*2**30,'Need at least 16 GiB free to build R11 projections/partitions')
        paths=[];jobs=[];nw=min(4,args.workers)
        for r in auth['month_records']:
            out=run/'PRIVATE/projected'/f'{r["month"]}.parquet';paths.append(out)
            jobs.append(dict(source=str(r['path']),output=str(out),month=r['month'],rows=r['rows'],expected_sha256=r['expected_sha256'],key=key,memory=max(.3,min(1.5,(args.memory_gb-1)/nw))))
        mapped(project_month,jobs,nw,'Project monthly inputs','25%','regressions roughly 15-35 min; PGN time depends on available archives')
        dump(run/'report/INPUT_REUSE.json',dict(source='R11 projections from authenticated originals'))
    with heartbeat('Verify sample, forty cells and gap support; next checkpoint 25%'):
        census=raw_summaries(paths,run,args.workers,args.memory_gb-.5)
    dump(run/'report/CENSUS.json',census)
    if bybucket is None:
        with heartbeat('Partition complete chooser histories; next checkpoint 25%'):
            part=partition(paths,run,args.shards,args.workers,args.memory_gb-.5,key)
        bybucket={}
        for f in part['files']:
            b=int(Path(f['relative']).parts[0].split('=')[1]);bybucket.setdefault(b,[]).append(run/'PRIVATE/by_chooser'/f['relative'])
    package_report(run,args.result_dir,key,25,'SAMPLE_AND_GAP_SUPPORT_VERIFIED')
    _,names,indices=design(dummy());_,mnames=moments_design(dummy())
    largest=max(sum(pq.ParquetFile(p).metadata.num_rows for p in files) for files in bybucket.values())
    per_worker=(largest*8*(4*len(names)+4*len(mnames)+40)+200_000_000)/2**30
    require(per_worker<args.memory_gb-.75,'Largest shard exceeds budget; use --shards 512')
    nw=max(1,min(args.workers,int((args.memory_gb-.75)/max(.4,per_worker))))
    dump(run/'report/RESOURCE_PLAN.json',dict(workers_requested=args.workers,workers_used=nw,memory_gb=args.memory_gb,estimated_worker_gb=per_worker,shards=args.shards,largest_shard_rows=largest,union_design_columns=len(names),empirical_moments=len(mnames)))
    log(f'Estimation: {nw} workers; one BLAS thread each; estimated {per_worker:.2f} GiB per worker. All three columns share the two passes.')
    first=[];jobs=[]
    for b,files in sorted(bybucket.items()):
        out=run/f'PRIVATE/moments/first_{b:04d}.npz';first.append(out)
        jobs.append(dict(bucket=b,files=list(map(str,files)),out=str(out),key=fingerprint([key,'first',b]),phase=1))
    mapped(task,jobs,nw,'Regression crossproducts','50%','cluster covariance next; all-game scans can take hours')
    fit=fit_first(first,names,indices,mnames);require((fit['n'],fit['g'])==(41534331,3224173),'Regression census differs')
    table(run/'report/coefficients_pending_covariance',[dict(column=col,term=name,estimate=float(v),status='POINT_ESTIMATE_ONLY_COVARIANCE_PENDING') for col,f in fit['fits'].items() for name,v in zip(f['names'],f['beta'])])
    package_report(run,args.result_dir,key,50,'COEFFICIENTS_SOLVED_INFERENCE_PENDING')
    second=[];jobs=[];betakey=fingerprint({c:f['beta'].tolist() for c,f in fit['fits'].items()})
    for b,files in sorted(bybucket.items()):
        out=run/f'PRIVATE/moments/second_{b:04d}.npz';second.append(out)
        jobs.append(dict(bucket=b,files=list(map(str,files)),out=str(out),key=fingerprint([key,'second',b,betakey]),phase=2,fit=fit))
    mapped(task,jobs,nw,'Chooser-cluster covariance','75%','regression report next; available-month PGN census follows')
    write_report(run,fit,combine(second))
    compare_archived_r10(run)
    for suffix in ['.csv','.parquet']:(run/'report/coefficients_pending_covariance').with_suffix(suffix).unlink(missing_ok=True)
    regression_seal(run,key)

def run_analysis(args):
    require(1<=args.workers<=10,'Require 1..10 workers');require(args.memory_gb>=2,'Require memory budget >=2 GiB');require(args.shards>=32,'Require >=32 shards')
    args.project=args.project.expanduser().resolve();args.result_dir=args.result_dir.expanduser().resolve()
    import scipy,zstandard
    versions=authority.environment_record();versions['packages'].update(scipy=scipy.__version__,zstandard=zstandard.__version__)
    code={str(p.relative_to(ROOT)):sha(p) for p in sorted(ROOT.rglob('*.py'))}
    cfg=dict(code=code,sample_fingerprint=load(ROOT/'authority/SAMPLE_AUTHORITY.json')['sample_fingerprint'],shards=args.shards,versions=versions['packages'],specification=specification())
    key=fingerprint(cfg);run=args.project/'derived/replication/r11_region_gap_v100_PRIVATE'/key[:12]
    (run/'report').mkdir(parents=True,exist_ok=True);(run/'PRIVATE').mkdir(exist_ok=True)
    lock=open(run/'RUNNING.lock','a+')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('This R11 run is already active')
    start=time.monotonic()
    try:
        (run/'report/RUN_STATUS.json').unlink(missing_ok=True)
        dump(run/'PRIVATE/RUN_CONFIG.json',dict(key=key,args=vars(args),configuration=cfg))
        log('R11: original 41,534,331 opportunities; author accounts retained. No API, Stockfish, downloads or source edits.')
        log('Expected regressions: approximately 15-35 minutes based on the completed R10 20-minute run. PGN scans: hours, potentially overnight; ETAs update from observed throughput.')
        if verified_regressions(run,key):log('Completed R11 regression report verified and reused; proceeding directly to all-game descriptive.')
        else:
            require(not args.allgames_only,'No verified completed regression for this code/environment; run without --allgames-only first')
            dump(run/'report/ENVIRONMENT.json',versions);dump(run/'report/SPECIFICATION.json',specification())
            estimate_models(args,run,key)
        dump(run/'report/ALL_GAMES_STATUS.json',dict(status='PENDING',regressions_complete=True,population=all_games.population()))
        package_report(run,args.result_dir,key,75,'REGRESSIONS_COMPLETE_ALL_GAME_QUANTILES_PENDING')
        roots=list(args.pgn_dir or [])+[args.project/'raw/lichess_pgn_standard',args.project/'data/raw/lichess_standard_rated_pgn_zst']
        discovery,inventory=all_games.discover(roots)
        dump(run/'PRIVATE/ALL_GAME_SOURCE_INVENTORY.json',dict(roots=inventory,months=discovery))
        log(f'All games: {sum(bool(r["candidates"]) for r in discovery)}/24 monthly archives located. Available months will be pooled explicitly.')
        jobs=[dict(**r,out=str(run/'PRIVATE/allgames'/f'{r["month"]}.json'),key=fingerprint([sha(ROOT/'all_games.py'),'allgames',r['month']])) for r in discovery if r['candidates']]
        results=mapped(all_games.safe_month,jobs,args.workers,'Available-month all-game ply census','100%','ETA from completed monthly scans; month-level ETA from compressed bytes') if jobs else []
        status=all_games.finish(results,run,discovery,inventory)
        complete=bool(status['months_used']);label=('R11_COMPLETE_24_MONTHS' if len(status['months_used'])==24 else 'R11_COMPLETE_AVAILABLE_MONTHS') if complete else 'R11_REGRESSIONS_COMPLETE_ALL_GAME_QUANTILES_UNAVAILABLE'
        dump(run/'report/COMPLETION.json',dict(status=label,seconds=time.monotonic()-start,models=3,all_game_months=len(status['months_used']),no_api=True,no_engine=True,author_accounts_retained=True))
        final=package_report(run,args.result_dir,key,100 if complete else 75,label)
        log(('R11_OK: ' if complete else 'R11_REGRESSIONS_OK; no usable all-game source: ')+str(final))
        return 0 if complete else 2
    except Exception as e:
        dump(run/'PRIVATE/FAILURE.json',dict(error=str(e),traceback=traceback.format_exc()))
        regression_ok=verified_regressions(run,key)
        dump(run/'report/RUN_STATUS.json',dict(status='REGRESSIONS_COMPLETE_DESCRIPTIVE_FAILED' if regression_ok else 'BLOCKED',error=str(e),checkpoints_preserved=True))
        package_report(run,args.result_dir,key,75 if regression_ok else 0,'REGRESSIONS_COMPLETE_DESCRIPTIVE_FAILED' if regression_ok else 'R11_BLOCKED')
        log('R11 stopped; verified work preserved. Return the report, sidecar and log.');raise
    finally:lock.close()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'));p.add_argument('--sample-root',type=Path)
    p.add_argument('--workers',type=int,default=10);p.add_argument('--memory-gb',type=float,default=11);p.add_argument('--shards',type=int,default=256)
    p.add_argument('--result-dir',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--reuse-r10-root',type=Path,help='Default: project/derived/replication/r10_two_questions_v100_PRIVATE/6bb9fb7c3d51')
    p.add_argument('--pgn-dir',type=Path,action='append',help='Additional monthly PGN root; repeat for multiple locations. Both documented roots are always searched.')
    p.add_argument('--allgames-only',action='store_true',help='Require a verified completed R11 regression; only refresh the available-month descriptive')
    return run_analysis(p.parse_args())

if __name__=='__main__':sys.exit(main())

