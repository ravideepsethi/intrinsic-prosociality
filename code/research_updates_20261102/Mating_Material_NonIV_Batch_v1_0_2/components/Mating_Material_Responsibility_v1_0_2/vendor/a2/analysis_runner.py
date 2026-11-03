from common import *
import argparse,concurrent.futures as cf,fcntl,multiprocessing as mp,shutil,sys,traceback,zipfile
from lineage import verify,units,RUN_KEY,SAMPLE,ENGINE_SHA
from features import convert_unit,prepare_targets
import design,estimate,history,report,source_audit

def pool_map(fn,tasks,workers,label):
    results=[];tasks=list(tasks);start=time.monotonic()
    with heartbeat(label),cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn')) as ex:
        queue=iter(tasks);running={}
        def fill():
            while len(running)<workers*2:
                t=next(queue,None)
                if t is None:break
                running[ex.submit(fn,t)]=True
        fill()
        while running:
            done,_=cf.wait(running,return_when=cf.FIRST_COMPLETED)
            for f in done:running.pop(f);results.append(f.result())
            fill()
            if len(results)%32==0 or not running:
                elapsed=time.monotonic()-start
                log(f'{label}: {len(results)}/{len(tasks)}; elapsed {elapsed/60:.1f} min')
    return results
def archive(run,desktop,label):
    reportdir=run/'report'
    dump(reportdir/'REPORT_HASHES.json',{str(p.relative_to(reportdir)):sha(p) for p in reportdir.rglob('*') if p.is_file() and p.name!='REPORT_HASHES.json'})
    dest=desktop/f'KAC_A2_{label}_{run.name}.zip';temp=Path(str(dest)+'.partial')
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(reportdir.rglob('*')):
            if p.is_file():z.write(p,'report/'+str(p.relative_to(reportdir)))
    os.replace(temp,dest);Path(str(dest)+'.sha256').write_text(sha(dest)+'  '+dest.name+'\n')
    log('UPLOAD_RESULT '+str(dest));return dest
def coverage(d,out):
    d=d.copy();d['board_region']=np.select([d.board>=-100,d.board<=-300],['competitive','losing'],default='middle')
    d['after_ply10']=d.ply>10
    c=d.groupby(['board_region','after_ply10','replay_status','trajectory_ok'],dropna=False).agg(opportunities=('y','size'),grants=('y','sum'),choosers=('chooser','nunique')).reset_index()
    table(out/'coverage',c)
    rows=[]
    for name in ['own','net2','net4']:
        x=d.groupby(['board_region','after_ply10',name+'_kind'],dropna=False).agg(opportunities=('y','size'),grants=('y','sum')).reset_index().rename(columns={name+'_kind':'endpoint_kind'});x['proxy']=name;rows.extend(x.to_dict('records'))
    table(out/'proxy_endpoint_support',rows)
    compare=d.loc[d.recomputed_final_cp.notna()&~d.mate]
    dump(out/'RECOMPUTED_ENGINE_DIAGNOSTIC.json',dict(finite_pairs=len(compare),mean_absolute_cp_difference=float((compare.recomputed_final_cp-compare.cp).abs().mean()) if len(compare) else None,
         competitive_reclassifications=int(((compare.recomputed_final_cp>=-100)!=(compare.cp>=-100)).sum()),membership='Canonical final evaluations remain authoritative'))
    dump(out/'CLOCK_SUPPORT.json',{n:dict(observed=int(d[n].notna().sum()),missing=int(d[n].isna().sum()),maximum=float(d[n].max()) if d[n].notna().any() else None) for n in ['clock_c','clock_d','clock_ratio','clock_fraction']})
def partition(d,run,key):
    index=run/'PRIVATE/partition_index.json'
    if index.is_file():
        i=load(index)
        if i['key']==key and all(valid(run/p,key) for p in i['paths']):return [run/p for p in i['paths']]
    # Every chooser's complete history goes to one bucket. No month-level independent demeaning.
    d['bucket']=d.chooser.astype('int64')%256;paths=[]
    keep=[n for n in d.columns if n not in ['game_id','month','speed','time_control','bucket']]
    for b,g in d.groupby('bucket',sort=True):
        p=run/'PRIVATE/buckets'/f'{b:03d}.parquet';p.parent.mkdir(parents=True,exist_ok=True)
        t=Path(str(p)+'.partial');g[keep].sort_values('chooser',kind='stable').to_parquet(t,index=False,compression='zstd');os.replace(t,p);certify(p,key);paths.append(p)
    dump(index,dict(key=key,paths=[str(p.relative_to(run)) for p in paths]));return paths
def run_models(d,run,key,workers,history_available):
    requested=design.specifications(history_available);specs=[];unsupported=[];support=[]
    for s in requested:
        a=design.select(d,s);n=len(a);g=a.chooser.nunique()
        if n==0 or g<2:unsupported.append(dict(model=s['name'],status='NO_SUPPORTED_SAMPLE',N=n,choosers=g));continue
        specs.append(s);support.append(dict(model=s['name'],N=n,choosers=g,row_set_sha256=fingerprint(sorted(a.game_id.tolist()))))
    dump(run/'report/model_definitions.json',requested);dump(run/'report/unsupported_models.json',unsupported);table(run/'report/model_row_support',support)
    for stage in ['late','all']:
        rows={r['model']:r for r in support}
        a=rows.get('curve_'+stage+'_common_baseline');b=rows.get('curve_'+stage+'_common_proxies')
        if a and b:require(a['row_set_sha256']==b['row_set_sha256'],'Curve comparison support mismatch')
    paths=partition(d,run,key);del d
    fits=None
    for phase in [1,2]:
        tasks=[];outs=[]
        for p in paths:
            dest=run/'PRIVATE'/f'pass{phase}'/(p.stem+'.npz');outs.append(dest)
            task=dict(bucket=p.stem,out=str(dest),key=fingerprint([key,phase,p.stem,specs]),files=[str(p)],specs=specs,phase=phase)
            if phase==2:task['fits']=fits
            tasks.append(task)
        pool_map(estimate.run_bucket,tasks,workers,f'A2 regression pass {phase}')
        if phase==1:fits=estimate.aggregate_first(outs,specs)
        else:meats=estimate.aggregate_meat(outs,specs)
    return specs,fits,meats
def verify_package():
    for n,h in load(ROOT/'PACKAGE_HASHES.json').items():require(sha(ROOT/n)==h,'Package checksum mismatch: '+n)
def main():
    parser=argparse.ArgumentParser(description='Resume frozen A2 acquisition, fit continuous/proxy diagnostics, inventory next sources.')
    parser.add_argument('--project',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    parser.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    parser.add_argument('--workers',type=int,default=10);parser.add_argument('--stockfish')
    parser.add_argument('--history-manifest',type=Path);parser.add_argument('--check-only',action='store_true');parser.add_argument('--cache-only',action='store_true')
    args=parser.parse_args();start=time.monotonic();verify_package()
    require(1<=args.workers<=10,'Use 1–10 workers');workers=min(args.workers,os.cpu_count() or 1)
    project=args.project.expanduser().resolve();desktop=args.desktop.expanduser().resolve()
    require(project.is_dir(),'Project drive is not mounted: '+str(project));require(desktop.is_dir(),'Desktop staging folder absent: '+str(desktop))
    old=project/'output/tenure_responsibility_v100'/RUN_KEY[:16]
    # Check frozen target lineage without re-reading the 41.5M-row census or querying profiles.
    targets=verify(old,ROOT/'legacy');u=units(old,targets)
    hhash=sha(args.history_manifest) if args.history_manifest else None
    codehash=fingerprint(load(ROOT/'PACKAGE_HASHES.json'))
    key=fingerprint(dict(code=codehash,target_run=RUN_KEY,target_sha=sha(old/'PRIVATE/trajectory_targets.parquet'),history_manifest=hhash))
    run=project/'output/kac_next_analyses_v100'/key[:16]
    (run/'PRIVATE').mkdir(parents=True,exist_ok=True);(run/'report').mkdir(exist_ok=True)
    lock=open(run/'RUN.lock','a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('This A2 follow-up is already running. No duplicate job was started.')
    dump(run/'report/LINEAGE.json',dict(key=key,source_sample=SAMPLE,legacy_run=RUN_KEY,target_sha256=sha(old/'PRIVATE/trajectory_targets.parquet'),code_sha256=codehash,
         opportunities=260863,grants=3755,choosers=20000,requested_positions=1292336,engine_sha256=ENGINE_SHA))
    dump(run/'report/SOURCE_READINESS.json',source_audit.audit(project))
    pending=[x for x in u if not x['ready']]
    plan=dict(status='READY_FOR_A2_ACQUISITION_AND_FEASIBLE_DIAGNOSTICS',verified_engine_batches=len(u)-len(pending),pending_engine_batches=len(pending),workers=workers,
              prior_history='SUPPLIED' if args.history_manifest else 'BLOCKED_INPUT',recovery='Reuse frozen cached moves and SF18 scores; serial missing-game requests; no chooser recovery/sample rebuild',
              runtime='Cached: roughly 5–20 minutes. Uncached: allow several hours; 8–12 hours is a conservative planning range for all 1.29M positions, not a measured benchmark. Live engine ETA replaces this after batches finish.')
    dump(run/'report/RUN_PLAN.json',plan);shutil.copyfile(ROOT/'DESIGN.md',run/'report/DESIGN.md');shutil.copyfile(ROOT/'EXECUTION_LEDGER.md',run/'report/EXECUTION_LEDGER.md')
    dump(run/'report/COMPLETION.json',dict(status='READINESS_ONLY_NO_NEW_ESTIMATES',action='The result ZIP is written only after the new diagnostics finish.'))
    archive(run,desktop,'READINESS')
    log(f'{len(u)-len(pending)} engine batches reused; {len(pending)} pending; {workers} workers maximum.')
    if args.check_only:return
    try:
        cmd=[sys.executable,'-u',str(ROOT/'legacy_bridge.py'),'--project',str(project),'--run',str(old),'--desktop',str(desktop),'--workers',str(workers)]
        if args.stockfish:cmd+=['--stockfish',args.stockfish]
        if args.cache_only:cmd+=['--cache-only']
        if pending:subprocess.run(cmd,check=True)
        source_lock=open(old/'RUN.lock','a')
        try:
            try:fcntl.flock(source_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise RuntimeError('The earlier responsibility run is active; no concurrent projection was started.')
            if pending:u=units(old,targets)
            require(all(x['ready'] for x in u),'Acquisition incomplete; completed checkpoints remain reusable')
            jobs=[(x,str(run/'PRIVATE/converted'/(x['name']+'.parquet')),fingerprint([key,x['key']])) for x in u]
            files=pool_map(convert_unit,jobs,workers,'Projecting authenticated raw-score checkpoints')
        finally:source_lock.close()
        d=prepare_targets(old/'PRIVATE/trajectory_targets.parquet')
        f=pd.concat([pq.ParquetFile(p).read().to_pandas() for p in sorted(files)],ignore_index=True)
        require(len(f)==len(d) and f.game_id.nunique()==len(d),'Projected score support differs')
        d=d.merge(f,on='game_id',validate='one_to_one',sort=False);del f
        d,hstatus=history.attach(d,args.history_manifest);dump(run/'report/HISTORY_STATUS.json',hstatus)
        coverage(d,run/'report')
        specs,fits,meats=run_models(d,run,key,workers,args.history_manifest is not None)
        report.render(run/'report',specs,fits,meats,hstatus)
        unsupported=[r['model'] for r in load(run/'report/unsupported_models.json')]
        missing_tests=unsupported+([] if args.history_manifest else
                       ['prior-90-day disconnection rate','prepanel disconnection rate','no-prior-disconnection subset'])
        status=('A2_DIAGNOSTICS_WRITTEN_WITH_UNSUPPORTED_MODELS' if unsupported else 'A2_DIAGNOSTICS_COMPLETE_REVIEW_REQUIRED') if args.history_manifest else (
                'A2_OUTPUT_WITH_UNSUPPORTED_MODELS_HISTORY_PENDING' if unsupported else 'A2_TRAJECTORY_CLOCK_MATERIAL_COMPLETE_HISTORY_PENDING')
        dump(run/'report/COMPLETION.json',dict(status=status,seconds=time.monotonic()-start,models=len(specs),
             missing_tests=missing_tests,
             next='Review this aggregate report and source-readiness inventory before constructing arena/history/title analyses. No later result is fabricated.'))
        archive(run,desktop,'RESULT')
        log(status)
    except Exception:
        dump(run/'PRIVATE/ERROR.json',dict(traceback=traceback.format_exc()))
        dump(run/'report/COMPLETION.json',dict(status='INCOMPLETE_DO_NOT_INTERPRET',seconds=time.monotonic()-start,action='Review terminal/private error; rerun the same command to resume authenticated checkpoints.'))
        archive(run,desktop,'PARTIAL');raise
    finally:lock.close()
if __name__=='__main__':main()
