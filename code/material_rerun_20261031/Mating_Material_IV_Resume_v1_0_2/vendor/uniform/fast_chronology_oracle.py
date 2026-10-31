"""Independent raw-game verification of every added or changed candidate row.

Reads physical Arrow batches once from the affected raw shard. Arrow grouped
counts and NumPy binary searches use ALL valid prior events, without ASOF,
SQL window functions, or the production scan's recent-history thinning.
Only private temporary files contain identifiers. The public audit has counts.
"""
from fast_bootstrap import *
import pyarrow.compute as pc
import repair_chronology as merge

FIELDS=['sample_row','role','prev_t','prev_count','prev_gid','prev_opponent',
        'focal_time_count','focal_matches','pre_games_30d']

def values(table,name):
    return table[name].combine_chunks().to_numpy(zero_copy_only=False)

def contains(sorted_values,query):
    if not len(sorted_values):return np.zeros(len(query),bool)
    at=np.searchsorted(sorted_values,query)
    return (at<len(sorted_values)) & (sorted_values[np.minimum(at,len(sorted_values)-1)]==query)

def stream_partition(schema,batches,path,buckets=64):
    class Source:
        def execute(self,sql):return self
        def fetch_record_batch(self,rows_per_batch):
            return pa.RecordBatchReader.from_batches(schema,batches)
    return merge.partition(Source(),'physical raw oracle',path,buckets=buckets,
                           label='Raw chronology oracle',buffer_bytes=32*1024*1024)

def focal_keys(job,gids):
    pieces=[]
    for b in pq.ParquetFile(job['focal']).iter_batches(batch_size=65536,use_threads=False):
        t=pa.Table.from_batches([b]);t=t.filter(pc.is_in(t['game_id'],value_set=gids))
        if not len(t):continue
        a=values(t,'recipient_id');b=values(t,'opponent_id')
        pieces.append(pa.table(dict(game_id=t['game_id'],utc_ms=t['archive_start_ms'],
                                   lo=np.minimum(a,b),hi=np.maximum(a,b))))
    schema=pa.schema([('game_id',pa.string()),('utc_ms',pa.int64()),('lo',pa.int64()),('hi',pa.int64())])
    t=pa.concat_tables(pieces).cast(schema) if pieces else pa.Table.from_batches([],schema)
    # Preserve duplicate focal queries: the frozen definition counts join rows.
    return t.group_by(['game_id','utc_ms','lo','hi'],use_threads=False).aggregate([('game_id','count')]).rename_columns(
        ['game_id','utc_ms','lo','hi','query_multiplicity'])

def raw_partitions(job,users,focal,path,buckets):
    schema=pa.schema([('user_id',pa.int64()),('utc_ms',pa.int64()),('game_id',pa.string()),
                      ('opponent_id',pa.int64()),('bucket',pa.int64())])
    matched=[];raw_rows=0;selected_events=0
    gids=pc.unique(focal['game_id'])
    def batches():
        nonlocal raw_rows,selected_events
        for b in pq.ParquetFile(job['path']).iter_batches(columns=['game_id','utc_ms','white_id','black_id'],
                                                         batch_size=65536,use_threads=False):
            t=pa.Table.from_batches([b]);raw_rows+=len(t)
            # NULLs fail the same validity comparisons as in the frozen producer.
            good=pc.and_kleene(pc.greater(t['utc_ms'],0),pc.less_equal(t['utc_ms'],job['latest']))
            for name in ('white_id','black_id'):
                good=pc.and_kleene(good,pc.and_kleene(pc.greater_equal(t[name],0),pc.less(t[name],2**32)))
            good=pc.and_kleene(good,pc.not_equal(t['white_id'],t['black_id']))
            t=t.filter(pc.fill_null(good,False))
            if not len(t):continue
            w=values(t,'white_id').astype(np.int64);b=values(t,'black_id').astype(np.int64)
            # Focal matches are an independent exact Arrow equijoin on raw games.
            pick=pc.is_in(t['game_id'],value_set=gids)
            raw_focal=pa.table(dict(game_id=t['game_id'],utc_ms=t['utc_ms'],lo=np.minimum(w,b),hi=np.maximum(w,b))).filter(pick).cast(
                focal.select(['game_id','utc_ms','lo','hi']).schema)
            if len(raw_focal) and len(focal):
                joined=raw_focal.join(focal,keys=['game_id','utc_ms','lo','hi'],join_type='inner',use_threads=False)
                if len(joined):matched.append(joined.select(['game_id','query_multiplicity']).group_by('game_id',use_threads=False).aggregate([('query_multiplicity','sum')]))
            for uid,opp in ((w,b),(b,w)):
                mask=contains(users,uid)
                if not mask.any():continue
                selected=t.filter(pa.array(mask));ids=uid[mask];selected_events+=len(ids)
                out=pa.table(dict(user_id=ids,utc_ms=selected['utc_ms'],game_id=selected['game_id'],
                                  opponent_id=opp[mask],bucket=ids%buckets),schema=schema)
                yield from out.to_batches()
    stream_partition(schema,batches(),path,buckets)
    if matched:
        counts=pa.concat_tables(matched).group_by('game_id',use_threads=False).aggregate([('query_multiplicity_sum','sum')])
        counts=counts.rename_columns(['game_id','matches'])
    else:counts=pa.table({'game_id':pa.array([],type=pa.string()),'matches':pa.array([],type=pa.int64())})
    return counts,dict(raw_rows_read=raw_rows,selected_raw_person_events=selected_events)

def reference_rows(events,queries,focal):
    """Direct strict predecessor and [t-30d,t) counts from all raw events."""
    grouped=events.group_by(['user_id','utc_ms'],use_threads=False).aggregate(
        [('utc_ms','count'),('game_id','min'),('opponent_id','min')])
    grouped=grouped.sort_by([('user_id','ascending'),('utc_ms','ascending')])
    n=len(queries);u=values(grouped,'user_id');t=values(grouped,'utc_ms')
    count=values(grouped,'utc_ms_count');qu=values(queries,'user_id');qt=values(queries,'archive_start_ms')
    dtype=np.dtype([('u','<i8'),('t','<i8')]);keys=np.empty(len(t),dtype=dtype)
    keys['u']=u;keys['t']=t;q=np.empty(n,dtype=dtype);q['u']=qu;q['t']=qt
    hi=np.searchsorted(keys,q,side='left');q['t']=qt-30*DAY;lo=np.searchsorted(keys,q,side='left')
    cumulative=np.r_[np.int64(0),np.cumsum(count,dtype=np.int64)]
    volume=cumulative[hi]-cumulative[lo]
    volume=np.where(values(queries,'role')==0,volume,0)
    if len(t):
        pos=np.maximum(hi-1,0);prior=(hi>0)&(u[pos]==qu)
        at=np.minimum(hi,len(t)-1);same=(hi<len(t))&(u[at]==qu)&(t[at]==qt)
        focal_time=np.where(same,count[at],0)
        ix=pa.array(pos,mask=~prior,type=pa.int64())
        prev={name:pc.take(grouped[col],ix) for name,col in
              [('prev_t','utc_ms'),('prev_count','utc_ms_count'),('prev_gid','game_id_min'),('prev_opponent','opponent_id_min')]}
    else:
        focal_time=np.zeros(n,np.int64)
        prev={k:pa.nulls(n,type=pa.string() if k=='prev_gid' else pa.int64()) for k in FIELDS[2:6]}
    index=pc.index_in(queries['game_id'],value_set=focal['game_id'])
    matches=pc.fill_null(pc.take(focal['matches'],index),0)
    return pa.table(dict(sample_row=queries['sample_row'],role=queries['role'],**prev,
                         focal_time_count=focal_time,focal_matches=matches,pre_games_30d=volume)).select(FIELDS)

def verify_raw(job,queries,expected,root,buckets=64):
    """Verify every selected row, never a sample; return public aggregate counts."""
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    q=pq.ParquetFile(queries).read();n=len(q)
    require(n==pq.ParquetFile(expected).metadata.num_rows,'Raw verification query coverage differs')
    require(all(q[x].null_count==0 for x in ('sample_row','role','user_id','archive_start_ms','game_id')),
            'Raw verification query keys are missing')
    users=np.unique(values(q,'user_id'));gids=pc.unique(q['game_id'])
    focal=focal_keys(job,gids)
    qs=q.schema.append(pa.field('bucket',pa.int64()))
    def qb():
        for b in q.to_batches(max_chunksize=65536):
            t=pa.Table.from_batches([b]);bucket=values(t,'user_id')%buckets
            yield pa.RecordBatch.from_arrays(list(b.columns)+[pa.array(bucket)],schema=qs)
    stream_partition(qs,qb(),root/'queries',buckets);del q
    counts,stats=raw_partitions(job,users,focal,root/'events',buckets);del focal,users,gids
    output=root/'reference_PRIVATE.parquet';writer=None;completed=0
    event_schema=pa.schema([('user_id',pa.int64()),('utc_ms',pa.int64()),('game_id',pa.string()),('opponent_id',pa.int64())])
    try:
        for k in range(buckets):
            qp=root/'queries'/f'bucket={k}'/'data.parquet'
            if not qp.exists():continue
            ep=root/'events'/f'bucket={k}'/'data.parquet'
            e=pq.ParquetFile(ep).read() if ep.exists() else pa.Table.from_batches([],event_schema)
            q=pq.ParquetFile(qp).read();result=reference_rows(e,q,counts)
            if writer is None:writer=pq.ParquetWriter(output,result.schema,compression='zstd')
            writer.write_table(result);completed+=len(result)
            del e,q,result
    finally:
        if writer:writer.close()
    require(completed==n,'Raw verification omitted query rows')
    c=conn(root/'compare',2.)
    try:
        cols=','.join(FIELDS);a='SELECT '+cols+' FROM '+parq([expected]);b='SELECT '+cols+' FROM '+parq([output])
        wrong=c.execute('SELECT count(*) FROM ('+a+' EXCEPT ALL '+b+')').fetchone()[0]
        absent=c.execute('SELECT count(*) FROM ('+b+' EXCEPT ALL '+a+')').fetchone()[0]
        audit=dict(method='physical_Arrow_raw_games_grouped_counts_NumPy_searchsorted_v104',
                   candidate_rows_checked=n,disagreements=wrong,missing_reference_rows=absent,passed=not(wrong or absent),
                   all_disputed_rows_checked=True,asof_used=False,sql_window_used=False,raw_history_thinned=False,**stats)
        save(root/'verification.json',audit)
        if wrong or absent:
            copy_query(c,a+' EXCEPT ALL '+b,root/'disagreement_PRIVATE.parquet')
            raise RuntimeError(f'Independent raw-game verification rejected reconstruction: {wrong} differing and {absent} missing rows; audit at {root}')
    finally:c.close()
    # Only scratch derived here is removed. Original scans/checkpoints are untouched.
    for folder in ('events','queries','compare'):shutil.rmtree(root/folder)
    return audit

def audit_candidates(c,job,original,tmp):
    columns=','.join(FIELDS);old=parq([original/'candidates.parquet']);new=parq([tmp/'candidates.parquet'])
    ensure(c,'SELECT count(*) FROM (SELECT sample_row,role FROM '+old+' WHERE sample_row IS NOT NULL AND role IS NOT NULL GROUP BY 1,2 HAVING count(*)<>1)',
           'Original identified query-role keys are duplicated; separate diagnosis required')
    # An old identified key outside the complete rebuilt query-role frame cannot
    # be silently discarded. It requires a separate diagnosis.
    ensure(c,'SELECT count(*) FROM '+old+' o ANTI JOIN '+new+' n USING(sample_row,role) WHERE o.sample_row IS NOT NULL AND o.role IS NOT NULL',
           'An identified original key is outside the reconstructed query-role frame')
    left='SELECT '+columns+' FROM '+old;right='SELECT '+columns+' FROM '+new
    changed=c.execute('SELECT count(*) FROM ('+left+' EXCEPT ALL '+right+') WHERE sample_row IS NOT NULL AND role IS NOT NULL').fetchone()[0]
    delta=tmp/'candidate_differences_PRIVATE.parquet';copy_query(c,right+' EXCEPT ALL '+left,delta)
    n=pq.ParquetFile(delta).metadata.num_rows
    field_counts=c.execute('SELECT '+','.join('count(*) FILTER(WHERE o.'+x+' IS DISTINCT FROM n.'+x+')' for x in FIELDS[2:])+
                           ' FROM '+old+' o JOIN '+new+' n USING(sample_row,role)').fetchone()
    audit=dict(identified_original_rows_differing=changed,new_or_different_rows=n,
               differing_fields_on_identified_keys=dict(zip(FIELDS[2:],field_counts)),
               old_rows=pq.ParquetFile(original/'candidates.parquet').metadata.num_rows,
               new_rows=pq.ParquetFile(tmp/'candidates.parquet').metadata.num_rows)
    if not n:
        require(changed==0,'Original scan contains surplus identified rows')
        return dict(audit,raw_verification=None,all_identified_original_rows_preserved=True)
    queries=tmp/'verification_queries_PRIVATE.parquet'
    copy_query(c,'SELECT r.* FROM '+parq([job['roles']])+' r JOIN '+parq([delta])+' d USING(sample_row,role)',queries)
    log(f'Chronology scan {job["file_index"]}: {changed:,} identified old rows differ; independently checking all {n:,} new/different rows against raw games')
    verification=verify_raw(job,queries,delta,tmp/'raw_verification104')
    return dict(audit,raw_verification=verification,all_identified_original_rows_preserved=changed==0,
                corrected_values_accepted_only_after_independent_raw_agreement=True)
