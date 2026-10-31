"""New lost-position exposure frame; no API or engine calls."""
from position_common import *
import concurrent.futures as cf
import multiprocessing as mp
from audit_logic import pairs, accumulate_pairs

def candidates(a,run,conf,index):
    paths=[p/'events.parquet' for p in index]
    def build(tmp):
        con=sql(tmp,a.memory_gb-2)
        try:
            view(con,'e',paths)
            start=int(c.phase_inputs.core.STARTS[0]);end=int(c.phase_inputs.core.PANEL_END)
            copy(con,f'''SELECT row_number() OVER(ORDER BY i,start,ord,gid)-1 AS row_id,
                gid game_id,i recipient_id,j opponent_id,start archive_start_ms,t anchor_ms,ord archive_ordinal,
                y received,arm_eligible,speed,tc_base_s,tc_inc_s,recipient_rating,opponent_rating,recipient_rd,opponent_rd,
                date_diff('month',DATE '2023-11-01',strptime(month||'-01','%Y-%m-%d'))::BIGINT month_code,
                TRUE complete90,TRUE history90_complete
                FROM e WHERE "position"=2 AND arm_eligible AND speed IN ('ultrabullet','bullet','blitz','rapid','classical')
                AND tc_base_s>0 AND start-{90*DAY}>={start} AND t+{90*DAY}<{end} ORDER BY row_id''',tmp/'candidates.parquet')
            return dict(rows=pq.ParquetFile(tmp/'candidates.parquet').metadata.num_rows)
        finally:con.close()
    return stage(run/'PRIVATE/lost_candidates',conf,build,paths)/'candidates.parquet'

def score_candidates(a,run,conf,b,source):
    bound=b['bound'];queries=c.inputs.query_shards(source,run/'PRIVATE/lost_score_queries',conf)
    ref=Path(bound['reference']);require(ref.is_file(),'Missing certified donor state reference')
    jobs=[]
    for s in range(16):
        parts=[r for r in bound['parts'] if int(r['shard'])==s]
        require(parts,'Missing donor shard')
        query=queries/f'{s:02}.parquet'
        jobs.append(dict(parts=parts,reference=str(ref),authors=bound['binding']['author_ids'],query=str(query),
            out=str(run/'PRIVATE/lost_scores'/f'{s:02}.parquet'),key=c.key([conf,'lost_ScoreA',sha(query),sha(ref),parts])))
    c.mapped(c.cutoffs.donor_job,jobs,min(a.workers,max(1,int((a.memory_gb-2)//4.5))),'Lost-exposure competitive Score A')
    paths=[Path(j['out']) for j in jobs]
    def build(tmp):
        con=sql(tmp,a.memory_gb-2)
        try:
            view(con,'q',source);view(con,'s',paths);c.assert_coverage(con,'q','s')
            keep='n_A>=5 AND isfinite(adjusted_A) AND isfinite(expected_A)'
            copy(con,'SELECT q.* FROM q JOIN s USING(row_id) WHERE '+keep+' ORDER BY row_id',tmp/'source.parquet')
            copy(con,'SELECT s.* FROM q JOIN s USING(row_id) WHERE '+keep+' ORDER BY row_id',tmp/'scores.parquet')
            save(tmp/'counts.json',dict(candidates=pq.ParquetFile(source).metadata.num_rows,supported=pq.ParquetFile(tmp/'source.parquet').metadata.num_rows))
        finally:con.close()
    return stage(run/'PRIVATE/lost_supported',conf,build,[source]+paths)

def chronology_job(job):
    rec=job['record'];path=Path(rec['path']);out=Path(job['out']);ck=job['key']
    require(c.frozen.r.io.sig(path)==rec['signature'],'Chronology signature changed')
    if c.cached(out,ck):return str(out)
    root=Path(job['query']);keys=np.load(root/'keys.npy',mmap_mode='r');people=np.load(root/'people.npy',mmap_mode='r')
    pairkeys=np.load(root/'pairs.npy',mmap_mode='r');order=np.load(root/'order.npy',mmap_mode='r');meta=load(root/'meta.json')
    earliest=np.full(len(pairkeys),np.iinfo(np.int64).max,np.int64);delta=np.zeros(len(order)+1,np.int64)
    packedroot=Path(job['packed']);packmeta=load(packedroot/'meta.json')
    packed=np.load(packedroot/'packed.npy',mmap_mode='r') if packmeta['supported'] else None
    pf=pq.ParquetFile(path);require(pf.metadata.num_rows==rec['rows'],'Chronology count differs')
    ix=pf.schema_arrow.get_field_index('utc_ms')
    for g in range(pf.metadata.num_row_groups):
        st=pf.metadata.row_group(g).column(ix).statistics
        if st and st.has_min_max and st.min>meta['maximum']:continue
        for batch in pf.iter_batches(row_groups=[g],columns=['utc_ms','white_id','black_id'],batch_size=131072,use_threads=False):
            t,w,b=[batch.column(k).fill_null(-1).to_numpy(zero_copy_only=False).astype(np.int64,copy=False) for k in range(3)]
            # First pair uses ALL earlier factual chronology, including author games.
            use=t<=meta['maximum'];accumulate_pairs(t[use],w[use],b[use],pairkeys,earliest)
            use=(t>=meta['minimum']-90*DAY)&(t<meta['maximum'])
            if use.any():
                if packed is None:features.accumulate90(t[use],w[use],b[use],keys,people,delta)
                else:features.accumulate_packed(t[use],w[use],b[use],packed,people,delta,packmeta)
    value=np.empty(len(order),np.int64);value[order]=np.cumsum(delta[:-1])
    require(c.frozen.r.io.sig(path)==rec['signature'],'Chronology changed while scanning')
    out.parent.mkdir(parents=True,exist_ok=True);tmp=out.with_suffix('.partial')
    with tmp.open('wb') as f:np.savez_compressed(f,value=value,earliest=earliest)
    os.replace(tmp,out);c.seal(out,ck);return str(out)

def chronology(a,run,conf,b,supported):
    source=supported/'source.parquet';scores=supported/'scores.parquet';root=run/'PRIVATE/lost_chronology'
    def prep(tmp):
        rid=col(source,'row_id');person=col(source,'recipient_id');start=col(source,'archive_start_ms')
        pair= pairs(person,col(source,'opponent_id'));keys=features.moments(person,start);order=np.argsort(keys,kind='stable')
        require(len(rid)>0,'No supported lost exposures')
        for name,v in [('row_id',rid),('keys',keys[order]),('people',np.unique(person)),('order',order),('pairs',np.unique(pair)),('pair_query',pair)]:np.save(tmp/(name+'.npy'),v,allow_pickle=False)
        save(tmp/'meta.json',dict(minimum=int(start.min()),maximum=int(start.max()),rows=len(rid)))
    query=stage(root/'query',conf,prep,[source]);packed=features.prepare_packed(query,conf)
    n=load(query/'meta.json')['rows'];records=b['bound']['binding']['source']['chron']
    identity=c.key([conf,sha(query/'POSITION_DONE.json'),records])
    jobs=[dict(record=r,query=str(query),packed=str(packed),out=str(root/'parts'/f'{k:04}.npz'),key=c.key([identity,r])) for k,r in enumerate(records)]
    workers=min(2,a.workers,max(1,int((a.memory_gb-2)/(1.5+80*n/2**30))))
    log(f'Lost-exposure pair/volume scan: {len(jobs)} archive files; {workers} workers; resumable per file')
    total=np.zeros(n,np.int64);earliest=np.full(len(np.load(query/'pairs.npy',mmap_mode='r')),np.iinfo(np.int64).max,np.int64)
    started=time.monotonic()
    with cert.heartbeat('Lost-exposure factual chronology'),cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn')) as pool:
        pending={pool.submit(chronology_job,j):j for j in jobs}
        for done,f in enumerate(cf.as_completed(pending),1):
            with np.load(f.result(),allow_pickle=False) as part:
                total+=part['value'];np.minimum(earliest,part['earliest'],out=earliest)
            if done%8==0 or done==len(jobs):
                elapsed=time.monotonic()-started
                log(f'Chronology {done}/{len(jobs)}; elapsed {elapsed/60:.1f} min; stage ETA ~{elapsed/done*(len(jobs)-done)/60:.1f} min (resume hits distort early ETA)')
    def finish(tmp):
        row=col(source,'row_id');start=col(source,'archive_start_ms')
        first=earliest[np.searchsorted(np.load(query/'pairs.npy'),np.load(query/'pair_query.npy'))]
        require(np.all(first<=start),'Exposure absent from canonical chronology')
        use=first==start
        con=sql(tmp,a.memory_gb-2)
        try:
            con.register('v',pa.table(dict(row_id=row,first_pair=use,pre_games_90d=total)))
            view(con,'q',source);view(con,'s',scores)
            copy(con,'SELECT q.*,v.pre_games_90d FROM q JOIN v USING(row_id) WHERE first_pair ORDER BY row_id',tmp/'source.parquet')
            copy(con,'SELECT s.* FROM s JOIN v USING(row_id) WHERE first_pair ORDER BY row_id',tmp/'scores.parquet')
            save(tmp/'counts.json',dict(**load(supported/'counts.json'),first_pair=int(use.sum()),recipients=int(len(np.unique(col(source,'recipient_id')[use])))))
        finally:con.close()
    return stage(root/'combined',conf,finish,[source,scores]+[Path(j['out']) for j in jobs])

def build_lost(a,run,conf,b,index):
    source=candidates(a,run,conf,index);supported=score_candidates(a,run,conf,b,source)
    chron=chronology(a,run,conf,b,supported)
    local=run/'PRIVATE/lost_features';(local/'report').mkdir(parents=True,exist_ok=True)
    source=features.behavior(a,local,conf,b['bound'],chron/'source.parquet')
    # Same environment producer, same clean rate panels, same 30/90 definitions.
    # Reuse existing competitive-frame rate requests before constructing missing ones.
    env=Path(a.parent)/'PRIVATE/wider/environment/combined/rates.parquet'
    bb=dict(b)
    if env.is_file():
        c.check_stage(env,cert.CONF);bb['known_rates']=[str(env)]
    source=c.primary.environment(a,local,conf,bb,source)
    scores=chron/'scores.parquet'
    require(np.array_equal(col(source,'row_id'),col(scores,'row_id')),'Lost source/score row alignment differs')
    save(run/'report/lost_selection_counts.json',load(chron/'counts.json'))
    save(run/'report/lost_environment.json',load(local/'report/wider_environment.json'))
    return source,scores
