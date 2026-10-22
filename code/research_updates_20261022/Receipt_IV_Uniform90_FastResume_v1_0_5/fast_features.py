"""Exact half-open history queries; unchanged deterministic later outcomes."""
from fast_bootstrap import *
import concurrent.futures as cf
import multiprocessing as mp

def moments(person,t):
    k=np.empty(len(person),dtype=[('person','<i8'),('time','<i8')]);k['person']=person;k['time']=t
    return k

def history90(person,t,values,query_person,query_start):
    keys=moments(person,t)
    lo=np.searchsorted(keys,moments(query_person,query_start-90*DAY),'left')
    hi=np.searchsorted(keys,moments(query_person,query_start),'left')
    total=np.r_[np.int64(0),np.cumsum(values,dtype=np.int64)]
    return total[hi]-total[lo]

def behavior_job(job):
    def build(tmp):
        q={k:pq.read_table(job['queries'],columns=[k]).column(0).to_numpy() for k in
           ('row_id','game_id','recipient_id','opponent_id','archive_start_ms','anchor_ms')}
        n=len(q['row_id']);result={'row_id':q['row_id']};c=conn(tmp,3.)
        try:
            view(c,'q',job['queries'])
            if n:
                lower=int(q['archive_start_ms'].min())-90*DAY;upper=int(q['archive_start_ms'].max())
                h=c.execute('SELECT e.person,e.t,'+','.join('e.clean_'+x for x in ('fair','kind','disconnect','receipt','claim'))+
                    ' FROM '+parq(job['histories'])+f' e SEMI JOIN (SELECT DISTINCT recipient_id FROM q) q ON e.person=q.recipient_id WHERE e.t>={lower} AND e.t<{upper} ORDER BY person,t').fetchnumpy()
                for name in ('fair','kind','disconnect','receipt','claim'):
                    result[name+'_90']=history90(h['person'],h['t'],h['clean_'+name],q['recipient_id'],q['archive_start_ms'])
                del h;gc.collect()
                lower=int(q['anchor_ms'].min());upper=int(q['anchor_ms'].max())+90*DAY
                ids=','.join(map(str,job['authors']))
                h=c.execute('SELECT e.* FROM '+parq(job['futures'])+f' e SEMI JOIN (SELECT DISTINCT recipient_id FROM q) q ON e.j=q.recipient_id WHERE e.t>{lower} AND e.t<={upper} AND e.j NOT IN ({ids}) AND e.i NOT IN ({ids}) ORDER BY j,t,ord,gid').fetchnumpy()
            else:
                for name in COUNTS90:result[name]=np.empty(0,np.int64)
                h={k:np.empty(0,'U8' if k=='gid' else bool if k=='y' else np.int64) for k in ('gid','j','i','t','start','ord','y')}
            result.update(fast.sorted_later_outcomes(h,q))
            result['history_window_complete']=q['archive_start_ms']-90*DAY>=int(phase_inputs.core.STARTS[0])
            pq.write_table(pa.table(result),tmp/'outcomes.parquet',compression='zstd')
            return dict(rows=n,history_days=90,gap_days=0)
        finally:c.close()
    return stage(job['output'],job['conf'],build,[job['queries']]+job['histories']+job['futures'])[1]

def behavior(a,run,conf,bound,source):
    def prep(tmp):
        c=conn(tmp)
        try:
            for s in range(16):copy_query(c,'SELECT * FROM '+parq([source])+f' WHERE recipient_id%16={s} ORDER BY row_id',tmp/f'outcome_{s:02}.parquet')
            return dict(rows=pq.ParquetFile(source).metadata.num_rows)
        finally:c.close()
    queries,_=stage(run/'PRIVATE/behavior_queries90',conf,prep,[source])
    jobs=inputs.outcome_jobs(bound,queries,run/'PRIVATE/behavior90',conf)
    mapped(behavior_job,jobs,min(a.workers,max(1,int((a.memory_gb-2)//3.5))),'90-day histories and later outcomes')
    parts=[str(Path(j['output'])/'outcomes.parquet') for j in jobs]
    def combine(tmp):
        c=conn(tmp,a.memory_gb-2)
        try:
            view(c,'q',source);view(c,'h',parts);assert_coverage(c,'q','h')
            remove=[f'{x}_{d}' for x in ('fair','kind','disconnect','receipt','claim') for d in (30,90)]+OUTCOME_COLS+['history_window_complete']
            remove += [x for x in columns(source) if x.startswith('original_')]
            copy_query(c,'SELECT '+except_fields('q',source,remove)+',h.* EXCLUDE(row_id) FROM q JOIN h USING(row_id) ORDER BY row_id',tmp/'features.parquet')
            view(c,'f',tmp/'features.parquet')
            ensure(c,'SELECT count(*) FROM f WHERE NOT history_window_complete OR (y AND NOT reached)','Invalid history coverage or zero-coded outcome')
            ensure(c,f'SELECT count(*) FROM f WHERE reached AND (outcome_t<=anchor_ms OR outcome_t>anchor_ms+{90*DAY} OR outcome_start<=anchor_ms OR outcome_opponent=opponent_id OR outcome_gid=game_id)','Later outcome violates temporal or pair rules')
            return dict(rows=pq.ParquetFile(source).metadata.num_rows)
        finally:c.close()
    out,_=stage(run/'PRIVATE/behavior_combined90',conf,combine,[source]+parts)
    return out/'features.parquet'

def accumulate90(t,w,b,keys,people,delta):
    # A start at t belongs to query times in (t,t+90d]. Each query has its
    # own entry even when multiple exposure games share a recipient/start.
    for p in (w,b):
        at=np.searchsorted(people,p);good=at<len(people)
        good[good] &= people[at[good]]==p[good]
        pp=p[good];tt=t[good]
        lo=np.searchsorted(keys,moments(pp,tt),'right')
        hi=np.searchsorted(keys,moments(pp,tt+90*DAY),'right')
        use=lo<hi
        np.add.at(delta,lo[use],1);np.add.at(delta,hi[use],-1)


def prepare_packed(query,conf):
    """Order-preserving uint64 encoding of existing (person,time) query keys."""
    query=Path(query)
    deps=[query/(name+'.npy') for name in ('keys','people')]+[query/'meta.json']
    def build(tmp):
        q=np.load(query/'keys.npy',mmap_mode='r');people=np.load(query/'people.npy',mmap_mode='r')
        meta=load(query/'meta.json');base=int(meta['minimum'])-90*DAY
        bits=max(1,(int(meta['maximum'])+90*DAY-base).bit_length())
        supported=(max(1,len(people))-1).bit_length()+bits<=64
        save(tmp/'meta.json',dict(base=base,bits=bits,supported=supported,rows=len(q),people=len(people)))
        if supported:
            out=np.lib.format.open_memmap(tmp/'packed.npy',mode='w+',dtype=np.uint64,shape=(len(q),))
            for lo in range(0,len(q),262144):
                hi=min(len(q),lo+262144);rank=np.searchsorted(people,q['person'][lo:hi]).astype(np.uint64)
                out[lo:hi]=(rank<<np.uint64(bits))|(q['time'][lo:hi]-base).astype(np.uint64)
            out.flush();del out
        return dict(rows=len(q),supported=supported,execution_version=EXECUTION_VERSION)
    out,_=stage(query.parent/'packed_v101',key([conf,'order_preserving_uint64_v101']),build,deps)
    return out

def accumulate_packed(t,w,b,keys,people,delta,meta):
    base=int(meta['base']);bits=int(meta['bits'])
    require(np.all(t>=base) and np.all(t+90*DAY-base<(1<<bits)), 'Packed time bounds exceeded')
    for person in (w,b):
        rank=np.searchsorted(people,person);good=rank<len(people)
        good[good] &= people[rank[good]]==person[good]
        prefix=rank[good].astype(np.uint64)<<np.uint64(bits)
        low=prefix|(t[good]-base).astype(np.uint64)
        high=prefix|(t[good]+90*DAY-base).astype(np.uint64)
        lo=np.searchsorted(keys,low,side='right');hi=np.searchsorted(keys,high,side='right')
        use=lo<hi
        np.add.at(delta,lo[use],1);np.add.at(delta,hi[use],-1)

def volume_job(job):
    p=Path(job['record']['path']);out=Path(job['out']);ck=job['key']
    require(frozen.r.io.sig(p)==job['record']['signature'],'Chronology signature changed: '+str(p))
    if cached(out,ck):return str(out)
    q=Path(job['query']);keys=np.load(q/'keys.npy',mmap_mode='r');people=np.load(q/'people.npy',mmap_mode='r')
    order=np.load(q/'order.npy',mmap_mode='r');meta=load(q/'meta.json');delta=np.zeros(len(order)+1,np.int64)
    packed=None;packmeta=None
    if job.get('packed'):
        packmeta=load(Path(job['packed'])/'meta.json')
        if packmeta['supported']:packed=np.load(Path(job['packed'])/'packed.npy',mmap_mode='r')
    pf=pq.ParquetFile(p);require(pf.metadata.num_rows==job['record']['rows'],'Chronology row count changed')
    idx=pf.schema_arrow.get_field_index('utc_ms');require(idx>=0,'Chronology lacks game-start time')
    for g in range(pf.metadata.num_row_groups):
        stat=pf.metadata.row_group(g).column(idx).statistics
        if stat is not None and stat.has_min_max and (stat.max<meta['minimum']-90*DAY or stat.min>=meta['maximum']):continue
        for batch in pf.iter_batches(row_groups=[g],columns=['utc_ms','white_id','black_id'],batch_size=131072,use_threads=False):
            t,w,b=[batch.column(j).fill_null(-1).to_numpy(zero_copy_only=False).astype(np.int64,copy=False) for j in range(3)]
            use=(t>=meta['minimum']-90*DAY)&(t<meta['maximum'])
            if use.any():
                if packed is None:accumulate90(t[use],w[use],b[use],keys,people,delta)
                else:accumulate_packed(t[use],w[use],b[use],packed,people,delta,packmeta)
    value=np.empty(len(order),np.int64);value[order]=np.cumsum(delta[:-1],dtype=np.int64)
    require(frozen.r.io.sig(p)==job['record']['signature'],'Chronology changed during scan')
    out.parent.mkdir(parents=True,exist_ok=True);temp=out.with_suffix('.partial')
    with temp.open('wb') as f:np.savez_compressed(f,value=value)
    os.replace(temp,out);seal(out,ck);return str(out)

def volume(a,run,conf,bound,source):
    root=run/'PRIVATE/volume90';root.mkdir(parents=True,exist_ok=True)
    out=root/'with_volume.parquet';ck=key([conf,'volume90',sha(source),bound['binding']['source']['chron']])
    if cached(out,ck):return out
    def plan(tmp):
        c=conn(tmp)
        try:q=c.execute('SELECT row_id,recipient_id,archive_start_ms FROM '+parq([source])+' ORDER BY row_id').fetchnumpy()
        finally:c.close()
        require(len(q['row_id'])>0,'No eligible volume queries')
        keys=moments(q['recipient_id'],q['archive_start_ms']);order=np.argsort(keys,kind='stable');keys=keys[order]
        for name,v in [('keys',keys),('order',order),('people',np.unique(q['recipient_id'])),('row_id',q['row_id'])]:np.save(tmp/(name+'.npy'),v,allow_pickle=False)
        save(tmp/'meta.json',dict(minimum=int(q['archive_start_ms'].min()),maximum=int(q['archive_start_ms'].max())))
        return dict(rows=len(order))
    query,_=stage(root/'query',conf,plan,[source]);packed=prepare_packed(query,conf);ids=np.load(query/'row_id.npy',mmap_mode='r');total=np.zeros(len(ids),np.int64)
    jobs=[dict(record=r,query=str(query),packed=str(packed),out=str(root/'parts'/f'{k:04}.npz'),key=key([ck,r])) for k,r in enumerate(bound['binding']['source']['chron'])]
    log(f'Volume resume: {sum(Path(j["out"]).exists() and Path(j["out"]+".ok.json").exists() for j in jobs)}/{len(jobs)} completed part receipts found; each will be checksum-verified')
    started=time.monotonic();fresh_seconds=0.;done=0
    volume_workers=min(a.workers,max(1,int((a.memory_gb-2)/(1.+64*len(ids)/2**30))))
    log(f'Volume scan: {volume_workers} workers, {a.memory_gb:.1f} GiB total compute allowance')
    with heartbeat('90-day all-game volume'),cf.ProcessPoolExecutor(max_workers=volume_workers,mp_context=mp.get_context('spawn')) as pool:
        pending={pool.submit(volume_job,j):j for j in jobs}
        for f in cf.as_completed(pending):
            with np.load(f.result(),allow_pickle=False) as z:total+=z['value']
            done+=1
            if done%16==0 or done==len(jobs):
                elapsed=time.monotonic()-started;log(f'Volume files {done}/{len(jobs)}; elapsed {elapsed/60:.1f} min; rough remaining stage ETA {elapsed/done*(len(jobs)-done)/60:.1f} min (cache hits can distort ETA)')
    c=conn(root,a.memory_gb-2)
    try:
        c.register('v',pa.table(dict(row_id=ids,pre_games_90d=total)));view(c,'q',source)
        copy_query(c,'SELECT '+except_fields('q',source,['pre_games_30d','pre_games_90d'])+',v.pre_games_90d FROM q JOIN v USING(row_id) ORDER BY row_id',out)
        ensure(c,'SELECT count(*) FROM '+parq([out])+' WHERE pre_games_90d IS NULL OR pre_games_90d<0','Missing or negative game volume')
        require(pq.ParquetFile(out).metadata.num_rows==len(ids),'Volume merge lost rows');seal(out,ck)
    finally:c.close()
    return out

def receipt_frames(a,run,conf,b):
    src=run/'PRIVATE/selection90/source.parquet'
    src=behavior(a,run,conf,b['bound'],src)
    src=volume(a,run,conf,b['bound'],src)
    src=primary.environment(a,run,conf,b,src)
    def build(tmp):
        c=conn(tmp,a.memory_gb-2)
        try:
            view(c,'q',src);view(c,'s',b['all_scores']);view(c,'old',b['primary'])
            bridge(c,'q','old',['game_id','recipient_id','opponent_id','received','archive_start_ms','anchor_ms','y','reached'],'Legacy rows retain identities and outcomes',EXPECTED_N)
            copy_query(c,'SELECT s.* FROM s JOIN q USING(row_id) ORDER BY row_id',tmp/'scores.parquet')
            view(c,'scores',tmp/'scores.parquet');assert_coverage(c,'q','scores')
            # Report the retained-row history change separately from sample growth.
            changes=[]
            for name in COUNTS90:
                n,d=c.execute(f'SELECT count(*) FILTER(WHERE q.{name}<>old.{name}),avg(q.{name}-old.{name}) FROM q JOIN old USING(row_id)').fetchone()
                changes.append(dict(field=name,changed_rows=n,mean_change=d))
            n,d=c.execute('SELECT count(*) FILTER(WHERE q.pre_games_90d<>old.pre_games_30d),avg(q.pre_games_90d-old.pre_games_30d) FROM q JOIN old USING(row_id)').fetchone()
            changes.append(dict(field='volume90_minus_old_volume30',changed_rows=n,mean_change=d));save(tmp/'changes.json',changes)
            save(tmp/'frames.json',dict(source=str(src),scores=str(run/'PRIVATE/receipt_frames90/scores.parquet')))
            return dict(rows=pq.ParquetFile(src).metadata.num_rows,legacy_outcomes_reproduced=True)
        finally:c.close()
    out,_=stage(run/'PRIVATE/receipt_frames90',conf,build,[src,b['primary']]+b['all_scores'])
    csv_out(run/'report/retained_row_feature_changes.csv',load(out/'changes.json'))
    save(run/'PRIVATE/FRAMES90.json',load(out/'frames.json'))
