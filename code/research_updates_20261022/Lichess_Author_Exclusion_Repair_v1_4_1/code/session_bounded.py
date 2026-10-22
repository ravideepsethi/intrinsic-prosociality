"""Finish the failed descriptive summary with whole-account disk partitions.
No session reconstruction and no regression refits. Exact quantiles are recovered
from integer-length frequency tables, including linear interpolation.
"""
from engine import *
import concurrent.futures as cf,multiprocessing as mp

def checked_link(src,dst):
    src=Path(src).resolve();dst=Path(dst);dst.parent.mkdir(parents=True,exist_ok=True)
    if dst.is_symlink():require(dst.resolve()==src,'Session reference points elsewhere')
    elif dst.exists():raise RuntimeError('Refusing to replace an existing output: '+str(dst))
    else:dst.symlink_to(src,target_is_directory=src.is_dir())

def quantile_hist(lengths,counts,p):
    lengths=np.asarray(lengths,float);counts=np.asarray(counts,np.int64)
    n=int(counts.sum());require(n>0,'Empty session-length distribution')
    pos=(n-1)*p;lo=int(math.floor(pos));hi=int(math.ceil(pos));cum=np.cumsum(counts)
    x=lengths[np.searchsorted(cum,lo,side='right')];y=lengths[np.searchsorted(cum,hi,side='right')]
    return float(x+(y-x)*(pos-lo))

def length_bucket(task):
    source,rates,out,key,memory=task;out=Path(out);done=out/'DONE.json'
    if done.exists():
        r=read(done);require(r['key']==key,'Session bucket identity changed')
        for f in r['files']:verify(f)
        return str(out)
    c=db(out/'spill',memory,1)
    try:
        merged=out/'sessions_PRIVATE.parquet'
        # Each chooser and start30 pair occurs in exactly one bucket, even if
        # the same ongoing session was recorded in several monthly caches.
        copy(c,'SELECT chooser,start30,max(observed_session_length) length,bool_or(left_censored) left_censored,max(last_t) last_t FROM '+scan(source)+' GROUP BY chooser,start30',merged)
        cutoff=int(pd.Timestamp('2025-11-01',tz='UTC').timestamp()*1000)-3600000
        start=int(pd.Timestamp('2023-11-01',tz='UTC').timestamp()*1000)
        c.execute('CREATE VIEW completed AS SELECT s.*,r.account_grant_percent FROM '+scan(merged)+' s JOIN '+scan(rates)+f' r USING(chooser) WHERE NOT left_censored AND last_t<{cutoff} AND start30>={start}')
        hist=c.execute('SELECT account_grant_percent,length,count(*) sessions FROM completed GROUP BY ALL ORDER BY ALL').fetchdf()
        accounts=c.execute('SELECT account_grant_percent,count(DISTINCT chooser) accounts FROM completed GROUP BY ALL').fetchdf()
        table(out/'histogram',hist);table(out/'accounts',accounts)
        write(done,{'key':key,'files':[record(out/(n+'.parquet')) for n in ('histogram','accounts')]})
    finally:c.close()
    return str(out)

def bounded_lengths(files,run,budget,memory):
    run=Path(run);work=run/'PRIVATE/bounded_lengths';report=run/'report/repetition'
    sessions=[run/'PRIVATE/history'/m/'sessions30.parquet' for m in ['2023-10']+MONTHS]
    records=[record(p) for p in files+sessions];key=digest([records,sha(__file__)])
    receipt=work/'PARTITIONS.json';rates=work/'rates_PRIVATE.parquet';parts=work/'by_chooser'
    if receipt.exists():
        r=read(receipt);require(r['key']==key,'Session descriptive inputs changed')
        for f in r['files']:verify(f)
    else:
        c=db(work/'spill_partition',max(2,memory-3),min(budget,4))
        try:
            copy(c,"SELECT chooser,CASE WHEN grant_rate=0 THEN '0' WHEN grant_rate<=1 THEN '(0,1]' WHEN grant_rate<=5 THEN '(1,5]' WHEN grant_rate<=20 THEN '(5,20]' ELSE '>20' END account_grant_percent FROM (SELECT chooser,100.*avg(y) grant_rate FROM "+scan(files)+' WHERE board>=-100 GROUP BY chooser)',rates)
            temp=work/'by_chooser.partial'
            if temp.exists():shutil.rmtree(temp)
            # Project only the five fields needed for this summary. Restrict to
            # the same eligible chooser set used by the original rates join.
            sql='SELECT s.chooser,s.start30,s.observed_session_length,s.left_censored,s.last_t,((s.chooser%256+256)%256)::INTEGER bucket FROM '+scan(sessions)+' s SEMI JOIN '+scan(rates)+' r USING(chooser)'
            with heartbeat('Partition saved session lengths to disk'):
                c.execute('COPY ('+sql+') TO '+q(temp)+' (FORMAT PARQUET,COMPRESSION ZSTD,PARTITION_BY(bucket),ROW_GROUP_SIZE 32768)')
            if parts.exists():shutil.rmtree(parts)
            temp.rename(parts)
            write(receipt,{'key':key,'files':[record(p) for p in [rates]+sorted(parts.rglob('*.parquet'))]})
        finally:c.close()
    folders=sorted(parts.glob('bucket=*'));tasks=[([str(p) for p in d.glob('*.parquet')],str(rates),str(work/'buckets'/d.name),digest([key,d.name]),1.5) for d in folders]
    workers=max(1,min(budget,4,int((memory-2)/1.5)));outputs=[];start=time.monotonic()
    with cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn')) as pool,heartbeat('Session length summaries'):
        for i,p in enumerate(pool.map(length_bucket,tasks),1):
            outputs.append(Path(p))
            if i%32==0 or i==len(tasks):log(f'Session buckets {i}/{len(tasks)}; remaining about {(time.monotonic()-start)/i*(len(tasks)-i)/60:.1f} minutes')
    h=pd.concat([pd.read_parquet(p/'histogram.parquet') for p in outputs],ignore_index=True).groupby(['account_grant_percent','length'],as_index=False).sessions.sum()
    a=pd.concat([pd.read_parquet(p/'accounts.parquet') for p in outputs],ignore_index=True).groupby('account_grant_percent').accounts.sum()
    rows=[]
    for category,d in h.groupby('account_grant_percent'):
        d=d.sort_values('length');n=int(d.sessions.sum())
        rows.append(dict(account_grant_percent=category,sessions=n,accounts=int(a.loc[category]),mean_length=float((d.length*d.sessions).sum()/n),median_length=quantile_hist(d.length,d.sessions,.5),p90_length=quantile_hist(d.length,d.sessions,.9),share_16plus=float(d.loc[d.length>=16,'sessions'].sum()/n)))
    table(report/'session_length_by_account_grant_rate',rows)
    write(report/'BOUNDED_SUMMARY.json',{'exact_length_quantiles':True,'chooser_buckets':256,'workers':workers,'factual_session_histories_preserved':True,'new_regression_fits':0,'new_history_reconstruction':False})
    for r in records:require(signature(r['path'])==r['verified_signature'],'Session input changed during summary')

def saved_moment_worker(task):
    # Reused parent moments may only be read, including in spawned workers.
    sys.path.insert(0,str(ROOT/'vendor/session'))
    import util
    _,out,key,*_=task
    require(util.cached(Path(out),key),'Completed session moment checkpoint missing')
    return Path(out)/'moments.npz'

def finish(args,auth,out,parent):
    sys.path.insert(0,str(ROOT/'vendor/session'))
    import repetition,util
    shared=parent/'PRIVATE/session_history_reuse/DONE.json';z=read(shared)
    with cf.ThreadPoolExecutor(max_workers=min(4,args.workers)) as pool,heartbeat('Verify completed session history'):
        list(pool.map(verify,z['files']))
    util.sha=sha
    old=parent/'PRIVATE/results/excluded/session';key=digest([auth['fingerprint'],z['key']]);conf=util.digest([key,repetition.specs()])
    target=old/'PRIVATE/repetition';require(util.cached(target/'partitions',conf),'Session partition checkpoint not complete')
    buckets=sorted((target/'partitions/rows').glob('bucket=*'))
    for phase in (1,2):
        for i in range(len(buckets)):
            require(util.cached(target/f'phase{phase}'/f'{i:03d}',util.digest([conf,phase,i])),'Session regression moments incomplete')
    for name in ('partitions','phase1','phase2'):checked_link(target/name,out/'PRIVATE/repetition'/name)
    checked_link(old/'PRIVATE/history',out/'PRIVATE/history')
    (out/'report').mkdir(parents=True,exist_ok=True)
    shutil.copy2(old/'report/history_reuse_audit.csv',out/'report/history_reuse_audit.csv')
    # Derive a checked implementation-only variant of the original function.
    # Its likelihood, design, covariance and cached moment keys are unchanged.
    source=(ROOT/'vendor/session/repetition.py').read_text();a=source.index('        sessions=[Path(run)');b=source.index("        exclusions=c.execute",a)
    patched=source[:a]+'        bounded_lengths(files,Path(run),budget,memory)\n'+source[b:]
    namespace=dict(repetition.__dict__);namespace['bounded_lengths']=bounded_lengths
    original_db=util.db
    exec(compile(patched,str(ROOT/'code/session_bounded.py')+'::repetition','exec'),namespace)
    namespace['db']=lambda folder,mem=2,threads=1:original_db(folder,min(mem,2) if Path(folder).name=='spill_summary' else mem,min(threads,2))
    repetition.worker=saved_moment_worker
    # run() resolves worker in its own globals; bind the same read-only worker.
    namespace['worker']=saved_moment_worker
    paths=[out/'PRIVATE/history'/m/'focal_history.parquet' for m in MONTHS]
    result=namespace['run'](paths,out,key,args.workers,args.memory_gb)
    note=out/'report/repetition/INTERPRETATION.md';note.write_text(note.read_text().replace('retain the same focal observations and all accounts','retain the same author-excluded focal observations in both count scenarios'))
    write(out/'report/REPAIR.json',{'status':'COMPLETED_FROM_VERIFIED_MOMENTS','new_regression_fits':0,'history_reconstructed':False,'parent':parent.name,'derived_function_sha256':hashlib.sha256(patched.encode()).hexdigest()})
    return result
