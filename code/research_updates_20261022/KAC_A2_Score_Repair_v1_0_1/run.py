"""Repair lost engine scores and rerun the unchanged A2 specifications."""
from common import *
import argparse, concurrent.futures as cf, fcntl, multiprocessing as mp
import shutil, sys, traceback, zipfile
from collections import Counter
from lineage import verify, units, RUN_KEY, SAMPLE, ENGINE_SHA
from features import prepare_targets
from analysis_runner import pool_map, archive, coverage, run_models, verify_package
import history, report, repair

PARENT_HASH = '9522a443e2ea761e409d0befdc761639460a748a017f0b71c72f660737011f90'
PARENT_KEY = '6147f8e2098bf8166821436c10fe99d7a6c1112d06a28698e051e609732f0e5a'
TARGET_SHA = 'a1b68dc9bdaf2d9a95494b9ec020ede0bcf75bd6fefcf340ba1e2b55ee5eba12'


def parent_file(name):
    p = ROOT/'original_evidence/KAC_A2_RESULT_6147f8e2098bf816.zip'
    require(sha(p)==PARENT_HASH,'Original result ZIP changed')
    with zipfile.ZipFile(p) as z:
        return z.read('report/'+name)


def engine_pool(jobs, workers):
    completed=[]; todo=[]
    for job in jobs:
        p=Path(job['out'])
        if valid(p,job['key']) and valid(p.with_suffix('.trace.json.gz'),job['key']):
            completed.append(dict(path=str(p),positions=len(job['fens']),cached=True))
        else: todo.append(job)
    pending=sum(len(j['fens']) for j in todo)
    log(f'Unique-FEN repair: {sum(x["positions"] for x in completed):,} cached; {pending:,} searches pending; {workers} workers.')
    start=time.monotonic(); done_positions=0
    with heartbeat('Repairing only unavailable scores'), cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn')) as ex:
        waiting=iter(todo); running={}; last_log=0.
        def fill():
            while len(running)<workers*2:
                job=next(waiting,None)
                if job is None:break
                running[ex.submit(repair.evaluate_batch,job)]=job
        fill()
        while running:
            done,_=cf.wait(running,return_when=cf.FIRST_COMPLETED)
            for future in done:
                job=running.pop(future)
                try:r=future.result()
                except Exception:
                    for f in running:f.cancel()
                    raise
                completed.append(r);done_positions+=len(job['fens'])
            fill();elapsed=time.monotonic()-start
            if elapsed-last_log>=30 or not running:
                speed=done_positions/max(elapsed,.001);eta=(pending-done_positions)/max(speed,.001)
                log(f'Repair {done_positions:,}/{pending:,} unique positions; {speed:.1f}/second; remaining about {eta/60:.1f} minutes.')
                last_log=elapsed
    return sorted(completed,key=lambda x:x['path'])


def check_invariants(out):
    import io
    old=pd.read_csv(io.BytesIO(parent_file('coefficients.csv')))
    new=pd.read_csv(out/'coefficients.csv')
    names=['curve_late_all_rows','curve_all_all_rows']+[
        f'proxy_{stage}_{region}_{p}' for stage in ['late','all']
        for region in ['competitive','losing'] for p in ['clock_log','clock_ratio','clock_trouble','material']]
    a=old[old.model.isin(names)].merge(new[new.model.isin(names)],on=['model','term'],suffixes=('_old','_new'),validate='one_to_one')
    require(len(a)==len(old[old.model.isin(names)]),'Unchanged-model coefficient support differs')
    require((a.status_old==a.status_new).all(),'Unchanged-model estimability differs')
    metrics={}
    for col in ['estimate','se']:
        x=a[col+'_old'].to_numpy(float);y=a[col+'_new'].to_numpy(float)
        require(np.allclose(x,y,rtol=1e-8,atol=1e-9,equal_nan=True),'Unaffected models changed: '+col)
        finite=np.isfinite(x)&np.isfinite(y)
        metrics[col+'_max_absolute_difference']=float(np.max(np.abs(x[finite]-y[finite])))
    dump(out/'UNCHANGED_MODEL_CHECK.json',dict(status='PASS',models=names,**metrics))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    parser.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    parser.add_argument('--workers',type=int,default=10)
    parser.add_argument('--stockfish');parser.add_argument('--audit-only',action='store_true')
    parser.add_argument('--history-manifest',type=Path)
    args=parser.parse_args();started=time.monotonic();verify_package()
    require(1<=args.workers<=10,'Use 1–10 workers')
    workers=min(args.workers,os.cpu_count() or 1)
    project=args.project.expanduser().resolve();desktop=args.desktop.expanduser().resolve()
    require(project.is_dir(),'Project drive is not mounted: '+str(project))
    require(desktop.is_dir(),'Desktop staging folder absent: '+str(desktop))
    old=project/'output/tenure_responsibility_v100'/RUN_KEY[:16]
    targets=verify(old,ROOT/'legacy')
    require(sha(old/'PRIVATE/trajectory_targets.parquet')==TARGET_SHA,'Different frozen responsibility targets')
    u=units(old,targets);require(all(x['ready'] for x in u),'Missing original engine checkpoints; repair never starts acquisition or API recovery')
    key=fingerprint(dict(contract='A2_SCORE_REPAIR_V101',code=fingerprint(load(ROOT/'PACKAGE_HASHES.json')),
                         parent=PARENT_HASH,target=TARGET_SHA,mode='audit' if args.audit_only else 'repair',
                         history=sha(args.history_manifest) if args.history_manifest else None))
    run=project/'output/kac_a2_score_repair_v101'/key[:16]
    (run/'PRIVATE').mkdir(parents=True,exist_ok=True);out=run/'report';out.mkdir(exist_ok=True)
    locks=[]
    try:
        for p in [run/'RUN.lock',old/'RUN.lock']:
            lock=open(p,'a');locks.append(lock)
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise RuntimeError('A conflicting A2 run is active; no duplicate engine job was started')
        dump(out/'LINEAGE.json',dict(key=key,parent_result_sha256=PARENT_HASH,parent_result_key=PARENT_KEY,
             source_sample=SAMPLE,legacy_run=RUN_KEY,target_sha256=TARGET_SHA,engine_sha256=ENGINE_SHA,
             code_sha256=fingerprint(load(ROOT/'PACKAGE_HASHES.json')),collector_sha256=sha(ROOT/'score_stream.py'),
             contract='A2_SCORE_REPAIR_V101',workers=workers,opportunities=260863,choosers=20000,grants=3755))
        import chess, chess.engine, pyarrow, scipy
        dependency=dict(python=sys.version,platform=platform.platform(),chess=chess.__version__,
                        chess_engine_source_sha256=sha(chess.engine.__file__),numpy=np.__version__,
                        pandas=pd.__version__,pyarrow=pyarrow.__version__,scipy=scipy.__version__,duckdb=duckdb.__version__)
        dump(out/'ENVIRONMENT.json',dependency)
        for name in ['DESIGN.md','REPAIR_NOTES.md']:shutil.copy2(ROOT/name,out/name)
        (out/'SOURCE_READINESS.json').write_bytes(parent_file('SOURCE_READINESS.json'))
        dump(out/'COMPLETION.json',dict(status='REPAIR_IN_PROGRESS_NOT_NEW_EVIDENCE'))
        invkey=fingerprint([key,'inventory'])
        jobs=[(x,str(run/'PRIVATE/inventory'),fingerprint([invkey,x['key']])) for x in u]
        inventory=pool_map(repair.inventory_unit,jobs,workers,'Auditing existing raw scores')
        invpaths=[p for p,m in inventory]
        counts=Counter()
        for p,m in inventory:
            for row in load(m)['rows']:
                counts[(row['status'],row['kind'],row['needs_repair'])]+=row['positions']
        rows=[dict(old_status=s,old_kind=k,needs_repair=b,positions=n) for (s,k,b),n in sorted(counts.items())]
        table(out/'original_score_status',rows)
        total=sum(counts.values());require(total==1292336,'Original raw-position count differs')
        db=dbopen(run/'PRIVATE/duckdb_tmp',threads=min(4,workers),memory_gb=2)
        try: fens=db.execute('SELECT DISTINCT fen FROM '+parq(invpaths)+' ORDER BY fen').fetchnumpy()['fen'].tolist()
        finally:db.close()
        affected=sum(n for (s,k,b),n in counts.items() if b)
        # Measured full-run throughput is a planning reference, not a forecast guarantee.
        historical_rate=1292336/31276.443417042028
        dump(out/'REPAIR_PLAN.json',dict(original_positions=total,affected_position_rows=affected,
             unique_fens_to_search=len(fens),duplicate_searches_avoided=affected-len(fens),
             preserved_position_rows=total-affected,workers=workers,nodes_per_search=100000,
             seconds_at_previous_full_run_throughput=len(fens)/historical_rate,
             runtime_note='The preceding 8h41m includes acquisition and regression overhead; current throughput and live ETA supersede this planning calculation.',
             network_calls=0,sample_rebuilt=False,prior_outputs_overwritten=False))
        log(f'{affected:,} unavailable score rows; {len(fens):,} unique FENs to repair; {total-affected:,} rows preserved.')
        log(f'At the prior complete-run throughput: about {len(fens)/historical_rate/60:.0f} minutes of repair, plus projection/regressions. Live ETA will replace this.')
        archive(run,desktop,'REPAIR_AUDIT')
        if args.audit_only:
            dump(out/'COMPLETION.json',dict(status='AUDIT_ONLY_REPAIR_NOT_RUN'))
            archive(run,desktop,'REPAIR_AUDIT');return
        cache=project/'output/kac_a2_engine_score_repair_cache_v101/PRIVATE/batches'
        if fens:
            engine=repair.find_engine(project,args.stockfish)
            reader_identity=fingerprint([sha(ROOT/'score_stream.py'),dependency['chess'],dependency['chess_engine_source_sha256']])
            ejobs=repair.score_jobs(fens,cache,engine,ENGINE_SHA,reader_identity)
            # Same cache lock across analysis identities prevents duplicate engine work.
            cache.parent.mkdir(parents=True,exist_ok=True)
            cachelock=open(cache.parent/'ENGINE.lock','a');locks.append(cachelock)
            try:fcntl.flock(cachelock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise RuntimeError('The shared score-repair cache is being written by another process')
            results=engine_pool(ejobs,workers)
            scorepaths=[r['path'] for r in results]
            scores=pd.concat([pq.ParquetFile(p).read().to_pandas() for p in scorepaths],ignore_index=True)
            require(len(scores)==len(fens) and not scores.fen.duplicated().any() and set(scores.fen)==set(fens),'Repaired score support differs')
            dump(run/'PRIVATE/repair_score_manifest.json',dict(contract=repair.CONTRACT,units=[dict(path=p,key=load(str(p)+'.ok.json')['key'],sha256=sha(p)) for p in scorepaths]))
            summary=scores.groupby(['status','stale_bound','merged_bound'],dropna=False).size().reset_index(name='unique_positions')
            table(out/'repaired_score_status',summary)
            def quantiles(values,levels):
                values=values.dropna()
                return {str(q):float(values.quantile(q)) if len(values) else None for q in levels}
            dump(out/'STREAM_DIAGNOSTIC.json',dict(unique_positions=len(scores),
                 searches_with_stale_merged_bound=int(scores.stale_bound.sum()),
                 searches_using_prior_unbounded_score=int(scores.used_prior_exact.sum()),
                 completed_searches=int(scores.complete.sum()),
                 finite_exact_at_budget=int(((scores.status=='SCORED')&scores.cp_white.notna()).sum()),
                 selected_score_nodes_quantiles=quantiles(scores.score_nodes,[0,.01,.1,.5,.9,.99,1]),
                 selected_depth_lag_quantiles=quantiles(scores.final_depth-scores.depth,[0,.5,.9,1]),
                 interpretation='The evaluation is the last unbounded score at completion of a fixed-budget search. A final bound is never used as a point. Selected-score nodes can precede total search nodes. Stale merged flags are diagnosed separately, using the same messages.'))
        else:
            scores=pd.DataFrame(columns=['fen','cp_white','mate_white','nodes','score_nodes','depth','status','final_lowerbound','final_upperbound','stale_bound'])
        overlays=repair.shard_overlays(invpaths,scores,run/'PRIVATE/overlay_shards',key)
        projected=pool_map(repair.project_unit,[(x,str(run/'PRIVATE/projected'/(x['name']+'.parquet')),
                            fingerprint([key,x['key'],'projection',sha(overlays[x['name']])]),overlays[x['name']]) for x in u],workers,'Rebuilding only A2 features')
        d=prepare_targets(old/'PRIVATE/trajectory_targets.parquet')
        feature=pd.concat([pq.ParquetFile(p).read().to_pandas() for p in sorted(projected)],ignore_index=True)
        require(len(feature)==len(d) and feature.game_id.nunique()==len(d),'Feature row support differs')
        d=d.merge(feature,on='game_id',validate='one_to_one',sort=False)
        d,hstatus=history.attach(d,args.history_manifest);dump(out/'HISTORY_STATUS.json',hstatus)
        coverage(d,out)
        import io
        before=pd.read_csv(io.BytesIO(parent_file('coverage.csv')));after=pd.read_csv(out/'coverage.csv')
        before['score_reader']='original';after['score_reader']='repaired'
        table(out/'before_after_coverage',pd.concat([before,after],ignore_index=True))
        specs,fits,meats=run_models(d,run,key,workers,args.history_manifest is not None)
        report.render(out,specs,fits,meats,hstatus)
        check_invariants(out)
        with open(out/'READ_ME_FIRST.md','r+') as f:
            text=f.read();f.seek(0)
            f.write('# Corrected A2 score reader — review required\n\nThe original reader discarded searches with a bounded final update and did not retain their preceding exact score; merged flags also have a reproducible stale-flag hazard. '
                    'Review original_score_status, repaired_score_status, before_after_coverage and UNCHANGED_MODEL_CHECK before interpreting these estimates. '
                    'Specification, outcome, sample and inference rules are unchanged. Prior disconnection histories remain pending unless an authenticated history manifest was supplied.\n\n'+text)
        dump(out/'COMPLETION.json',dict(status='A2_SCORE_REPAIR_COMPLETE_REVIEW_REQUIRED',models=len(specs),
             seconds=time.monotonic()-started,history=hstatus['status'],
             original_positions=total,unique_fens_researched=len(fens),
             missing_tests=[] if args.history_manifest else ['prior-90-day disconnection rate','prepanel disconnection rate','no-prior-disconnection subset']))
        archive(run,desktop,'REPAIRED_RESULT')
        log('A2_SCORE_REPAIR_COMPLETE_REVIEW_REQUIRED')
    except Exception:
        dump(run/'PRIVATE/ERROR.json',dict(traceback=traceback.format_exc()))
        dump(out/'COMPLETION.json',dict(status='REPAIR_INCOMPLETE_DO_NOT_INTERPRET',seconds=time.monotonic()-started))
        archive(run,desktop,'REPAIR_PARTIAL');raise
    finally:
        for lock in reversed(locks):lock.close()


if __name__=='__main__':main()
