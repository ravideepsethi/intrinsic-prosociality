"""One source pass for pair encounters and predetermined activity features."""
from core import *
_Q={}

def make_queries(panel_paths,folder,threads,memory):
    folder=Path(folder);old=cached(folder)
    if old:return old
    folder.mkdir(parents=True,exist_ok=True);c=conn(folder/'spill',threads,memory)
    try:
        c.execute('CREATE VIEW p AS SELECT * FROM '+scan(panel_paths))
        n,u=c.execute('SELECT count(*),count(DISTINCT gid) FROM p').fetchone()
        if n!=u:raise RuntimeError('Duplicated focal games')
        copy(c,'SELECT *,row_number() OVER(ORDER BY month,gid)-1 qid FROM p ORDER BY month,gid',folder/'targets.parquet')
        keys=c.execute('SELECT DISTINCT pair_key FROM p ORDER BY pair_key').fetchnumpy()['pair_key'];np.save(folder/'pair_keys.npy',keys)
        tab=c.execute('SELECT j,i,start FROM '+scan(folder/'targets.parquet')+' ORDER BY qid').to_arrow_table()
        people=np.r_[array(tab,'j',np.int64),array(tab,'i',np.int64)];times=np.tile(array(tab,'start',np.int64),2)
        slots=(times//14400000)%6
        for name,ids in [('volume',people),('slot',people*6+slots)]:
            mk=moments(ids,times);order=np.argsort(mk,kind='stable');np.save(folder/(name+'_keys.npy'),mk[order]);np.save(folder/(name+'_order.npy'),order)
        np.save(folder/'people.npy',np.unique(people));result=dict(rows=n,pairs=len(keys),min_start=int(times.min()),max_start=int(times.max()))
        dump(folder/'metadata.json',result);finish(folder,result);return result
    finally:c.close()

def init_queries(folder):
    global _Q
    if _Q.get('folder')==str(folder):return _Q
    folder=Path(folder);_Q=dict(folder=str(folder),meta=load(folder/'metadata.json'))
    for name in ['pair_keys','volume_keys','volume_order','slot_keys','slot_order','people']:
        _Q[name]=np.load(folder/(name+'.npy'),mmap_mode='r',allow_pickle=False)
    return _Q

def chronology_job(job):
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    folder=Path(job['folder']);done=cached(folder)
    if done:return dict(**done,folder=str(folder),reused=True)
    folder.mkdir(parents=True,exist_ok=True);q=init_queries(job['queries']);keys=q['pair_keys'];r=job['record'];p=Path(r['path'])
    if stamp(p)!=r['fingerprint']:raise RuntimeError('Chronology input changed')
    started=time.monotonic();earliest=np.full(len(keys),np.iinfo(np.int64).max,np.int64)
    recent=r['month']>='2023-08';needs=keys;cacheused=False;auth=folder/'authentication'
    if not recent and job.get('old_cache'):
        oc=job['old_cache'];cp=Path(oc['root'])/'pairs'/f"file_{r['index']:04d}";dp=cp/'_DONE.json'
        if dp.exists():
            d=load(dp);matches=[x for x in d.get('files',[]) if x.get('path',x.get('relative_path'))=='pairs.parquet']
            if d.get('config_sha256')==oc['config'] and d.get('input_signature')==r['fingerprint'][1:] and len(matches)==1:
                verify(cp/'pairs.parquet',matches[0]['sha256'],auth)
                table=pq.ParquetFile(cp/'pairs.parquet').read(columns=['pair_key','first_pair_start']);at=lookup(keys,array(table,'pair_key',np.uint64));ok=at>=0
                np.minimum.at(earliest,at[ok],array(table,'first_pair_start',np.int64)[ok])
                oldkeys=np.load(oc['keys'],mmap_mode='r');needs=keys[lookup(oldkeys,keys)<0];cacheused=True
    deltas=[np.zeros(len(q['volume_keys'])+1,np.int64),np.zeros(len(q['slot_keys'])+1,np.int64)] if recent else None
    writer=None;matched=0;read=0;invalid=0;activity={};needs_at=lookup(keys,needs)
    try:
        if recent or len(needs):
            cols=['utc_ms','white_id','black_id']+(['game_id'] if recent else [])
            for b in pq.ParquetFile(p).iter_batches(columns=cols,batch_size=262144,use_threads=False):
                read+=len(b);t,w,bl=[np.asarray(b.column(k).fill_null(-1).to_numpy(zero_copy_only=False),np.int64) for k in range(3)]
                valid=(t>0)&(w>=0)&(bl>=0)&(w<2**32)&(bl<2**32)&(w!=bl);invalid+=int((~valid).sum())
                t,w,bl=t[valid],w[valid],bl[valid];pk=pairs(w,bl);at=lookup(needs,pk);ok=at>=0
                np.minimum.at(earliest,needs_at[at[ok]],t[ok])
                if recent:
                    at=lookup(keys,pk);keep=(at>=0)&(t>=START-90*DAY)&(t<END)
                    gids=pa.array(b.column(3)).filter(pa.array(valid)).filter(pa.array(keep))
                    tt=pa.table(dict(gid=gids,pair_key=pk[keep],t=t[keep],white=w[keep],black=bl[keep],speed=np.full(int(keep.sum()),SPEEDS.index(r['speed']),np.int8)))
                    if writer is None:writer=pq.ParquetWriter(folder/'events.parquet',tt.schema,compression='zstd')
                    writer.write_table(tt);matched+=len(tt)
                    use=(t>=q['meta']['min_start']-30*DAY)&(t<q['meta']['max_start'])
                    tt0=t[use]
                    for ids in (w[use],bl[use]):
                        usep=lookup(q['people'],ids)>=0;ii=ids[usep];tt1=tt0[usep]
                        volume_increment(ii,tt1,q['volume_keys'],deltas[0])
                        volume_increment(ii*6+(tt1//14400000)%6,tt1,q['slot_keys'],deltas[1])
                    use=(t>=START-30*DAY)&(t<END)
                    hours,cts=np.unique(t[use]//3600000,return_counts=True)
                    for h,n in zip(hours,cts):activity[int(h)]=activity.get(int(h),0)+int(n)
    finally:
        if writer:writer.close()
    keep=earliest<np.iinfo(np.int64).max
    pq.write_table(pa.table(dict(pair_key=keys[keep],first_t=earliest[keep])),folder/'first.parquet',compression='zstd')
    if deltas is not None:
        v=volume_finish(deltas[0],q['volume_order']);s=volume_finish(deltas[1],q['slot_order']);ix=np.flatnonzero((v>0)|(s>0))
        if np.any(s>v):raise RuntimeError('Slot activity exceeds overall activity')
        pq.write_table(pa.table(dict(role_row=ix,volume=v[ix],same_slot=s[ix])),folder/'volume.parquet',compression='zstd')
        pq.write_table(pa.table(dict(hour=np.array(list(activity),np.int64),games=np.array(list(activity.values()),np.int64),speed=np.full(len(activity),SPEEDS.index(r['speed']),np.int8))),folder/'activity.parquet',compression='zstd')
    if stamp(p)!=r['fingerprint']:raise RuntimeError('Chronology changed during read')
    result=dict(read_rows=read,invalid_source_rows=invalid,matched_events=matched,old_first_pair_cache_reused=cacheused,elapsed_seconds=time.monotonic()-started,recent=recent)
    finish(folder,result);return dict(**result,folder=str(folder),reused=False)

def merge_history(products,queries,folder,threads,memory):
    folder=Path(folder);old=cached(folder)
    if old:return old
    folder.mkdir(parents=True,exist_ok=True);c=conn(folder/'spill',threads,memory);queries=Path(queries)
    try:
        c.execute('CREATE VIEW q AS SELECT * FROM '+scan(queries/'targets.parquet'))
        c.execute('CREATE VIEW f AS SELECT pair_key,min(first_t) first_t FROM '+scan([Path(p['folder'])/'first.parquet' for p in products])+' GROUP BY pair_key')
        eps=[Path(p['folder'])/'events.parquet' for p in products if (Path(p['folder'])/'events.parquet').exists()]
        c.execute('CREATE VIEW e0 AS SELECT * FROM '+scan(eps))
        bad=c.execute('''SELECT count(*) FROM (SELECT gid FROM e0 GROUP BY gid HAVING count(DISTINCT (pair_key,t,white,black,speed))>1)''').fetchone()[0]
        if bad:raise RuntimeError('Conflicting same-game chronology records')
        dup=c.execute('SELECT count(*)-count(DISTINCT gid) FROM e0').fetchone()[0]
        if dup:raise RuntimeError('Duplicate chronology games would double-count activity; input repair required')
        copy(c,'SELECT DISTINCT * FROM e0 ORDER BY pair_key,t,gid',folder/'events.parquet')
        c.execute('CREATE VIEW e AS SELECT * FROM '+scan(folder/'events.parquet'))
        bad=c.execute('''SELECT count(*) FROM q LEFT JOIN e USING(gid) WHERE e.gid IS NULL OR q.pair_key<>e.pair_key OR q.start<>e.t OR q.speed<>e.speed OR NOT ((q.j=e.white AND q.i=e.black) OR (q.i=e.white AND q.j=e.black))''').fetchone()[0]
        if bad:raise RuntimeError(f'{bad} focal chronology identity/time mismatches; no imputation applied')
        bad=c.execute('SELECT count(*) FROM q LEFT JOIN f USING(pair_key) WHERE first_t IS NULL OR first_t>start').fetchone()[0]
        if bad:raise RuntimeError('Historical first-meeting answers incomplete')
        c.execute('CREATE VIEW v AS SELECT role_row,sum(volume)::BIGINT volume,sum(same_slot)::BIGINT same_slot FROM '+scan([Path(p['folder'])/'volume.parquet' for p in products if p['recent']])+' GROUP BY role_row')
        n=load(queries/'metadata.json')['rows']
        # Pool-size proxy uses only activity before the focal game, never same-hour future games.
        c.execute('CREATE VIEW a AS SELECT hour,speed,sum(games) games FROM '+scan([Path(p['folder'])/'activity.parquet' for p in products if p['recent']])+' GROUP BY hour,speed')
        copy(c,'''SELECT q.*,first_t,(first_t<start) repeat,coalesce(vj.volume,0)::BIGINT jvolume,coalesce(vi.volume,0)::BIGINT ivolume,
            coalesce(vj.same_slot,0)::BIGINT jslot,coalesce(vi.same_slot,0)::BIGINT islot,
            coalesce(a.games,0)::BIGINT previous_hour_pool_games
            FROM q JOIN f USING(pair_key) LEFT JOIN v vj ON vj.role_row=q.qid
            LEFT JOIN v vi ON vi.role_row=q.qid+'''+str(n)+'''
            LEFT JOIN a ON a.speed=q.speed AND a.hour=cast(floor(q.start/3600000.0) as BIGINT)-1
            ORDER BY qid''',folder/'features.parquet')
        result=dict(rows=n,deduplicated_identical_chronology_rows=dup,identity_timestamp_mismatches=bad)
        finish(folder,result);return result
    finally:c.close()
