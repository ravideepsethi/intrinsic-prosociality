"""Necessary eligibility checks. No granting outcomes or future-choice fields are read."""
from local_contract import *
import iv_numerics as num
import author_history
import concurrent.futures as cf

def authenticate(project, workers):
    # Reuse the already reviewed Run 3 lineage and exact dictionary-ID binding.
    h=author_history.authenticate(project,workers)
    prep=prep_root(project)
    if io.cfgsha(io.load(prep/'config.json'))!=PREP_CONF:raise RuntimeError('Run 2 preparation configuration changed')
    frame=io.complete(prep/'frame',PREP_CONF)
    cache=io.complete(prep/'cache_merged',PREP_CONF)
    requests=io.complete(prep/'requests',PREP_CONF)
    if not frame or not cache or not requests:raise RuntimeError('The completed Run 2 preparation is required')
    paths=[prep/'frame'/(m+'.parquet') for m in ex.MONTHS]
    if sum(pq.ParquetFile(p).metadata.num_rows for p in paths)!=FRAME_ROWS:raise RuntimeError('Fixed frame size differs')
    if pq.ParquetFile(prep/'requests/targets.parquet').metadata.num_rows!=ORIGINAL_TARGETS:raise RuntimeError('Original API target count differs')
    h.update(frame=[str(p) for p in paths],frame_receipt_sha=io.sha(prep/'frame/_DONE.json'),
             cache=str(prep/'cache_merged/metadata.parquet'),cache_receipt_sha=io.sha(prep/'cache_merged/_DONE.json'),
             original_targets=str(prep/'requests/targets.parquet'),original_inventory=str(prep/'CACHE_INVENTORY_PRIVATE.json'),
             requests_receipt_sha=io.sha(prep/'requests/_DONE.json'))
    return h

def partition_month(job):
    threads_one()
    def build(tmp):
        writers=[];n=old=0;counts=[0]*SHARDS
        try:
            pf=pq.ParquetFile(job['path']);schema=pf.schema_arrow
            for s in range(SHARDS):writers.append(pq.ParquetWriter(tmp/f'{s:02}.parquet',schema,compression='zstd'))
            month=int(np.flatnonzero(np.asarray(core.MONTHS)==job['month'])[0])
            for b in pf.iter_batches(batch_size=131072,use_threads=False):
                t=pa.Table.from_batches([b]);g=io.arr(t,'game_id');h=ex.bits(g.tolist())
                if np.any((h&np.uint64(31))!=0):raise RuntimeError('Expanded frame hash selection changed')
                isold=(h&np.uint64(1023))==0
                if not np.array_equal(isold,io.arr(t,'previous_frame')):raise RuntimeError('Old-frame membership changed')
                rw=((h>>np.uint64(32))&np.uint64(1))==0
                w=io.arr(t,'white_id');bl=io.arr(t,'black_id')
                if not np.array_equal(np.where(rw,w,bl),io.arr(t,'recipient_id')) or not np.array_equal(np.where(rw,bl,w),io.arr(t,'opponent_id')):
                    raise RuntimeError('Fixed focal orientation changed')
                if not np.array_equal(np.where(rw,'white','black'),io.arr(t,'recipient_color')):raise RuntimeError('Color orientation changed')
                times=io.arr(t,'utc_ms')
                if np.any((times<core.STARTS[month])|(times>=core.STARTS[month+1])):raise RuntimeError('Frame month/time mismatch')
                shards=num.user_hash(io.arr(t,'opponent_id'))%np.uint64(SHARDS)
                for s in range(SHARDS):
                    use=shards==s
                    if use.any():writers[s].write_table(t.filter(pa.array(use)));counts[s]+=int(use.sum())
                n+=len(t);old+=int(isold.sum())
        finally:
            for w in writers:w.close()
        return dict(rows=n,previous_frame_rows=old,shard_counts=counts)
    return stable_stage(Path(job['output']),job['conf'],build,[job['path']])[1]

def validation_queries(source, out, conf):
    def build(tmp):
        cols=['row_id','recipient_id','opponent_id','month_code','n_7d'];writers=[];n=0
        try:
            pf=pq.ParquetFile(source);schema=pa.schema([pf.schema_arrow.field(k) for k in cols])
            for s in range(SHARDS):writers.append(pq.ParquetWriter(tmp/f'{s:02}.parquet',schema,compression='zstd'))
            for b in pf.iter_batches(columns=cols,batch_size=131072,use_threads=False):
                t=pa.Table.from_batches([b]);sh=num.user_hash(io.arr(t,'opponent_id'))%np.uint64(SHARDS)
                for s in range(SHARDS):
                    use=sh==s
                    if use.any():writers[s].write_table(t.filter(pa.array(use)))
                n+=len(t)
        finally:
            for w in writers:w.close()
        return dict(rows=n,fields_read=cols,future_outcomes_read=False)
    return stable_stage(out,conf,build,[source])

def build_counts(c, histories, authors, shard=None):
    """Strict t < month-start - 7 days; arm histories; both author roles removed."""
    c.execute('CREATE TEMP TABLE history(j BIGINT,i BIGINT,em SMALLINT,clean BIGINT)')
    seen=removed=0
    for path in histories:
        for b in pq.ParquetFile(path).iter_batches(columns=['j','i','t','arm'],batch_size=262144,use_threads=False):
            t=pa.Table.from_batches([b]);d=arrays(t);arm=np.asarray(d['arm'],bool)
            if shard is not None and np.any(num.user_hash(d['j'])%np.uint64(SHARDS)!=shard):
                raise RuntimeError('Wrong chooser-history shard')
            j=np.asarray(d['j'])[arm];i=np.asarray(d['i'])[arm];tt=np.asarray(d['t'])[arm]
            em=np.searchsorted(core.STARTS,tt+7*core.DAY,side='right').astype(np.int16)
            clean=(~np.isin(j,authors)&~np.isin(i,authors)).astype(np.int64)
            seen+=len(j);removed+=int((clean==0).sum())
            c.register('batch_in',pa.table(dict(j=j,i=i,em=em,clean=clean)))
            c.execute('INSERT INTO history SELECT * FROM batch_in');c.unregister('batch_in')
    c.execute('''CREATE TEMP TABLE increments AS
        SELECT j,i,em,count(*)::BIGINT n_old,sum(clean)::BIGINT n_clean FROM history GROUP BY j,i,em''')
    c.execute('DROP TABLE history')
    c.execute('''CREATE TEMP TABLE pair_counts AS SELECT j,i,em,
        sum(n_old) OVER (PARTITION BY j,i ORDER BY em)::BIGINT n_old,
        sum(n_clean) OVER (PARTITION BY j,i ORDER BY em)::BIGINT n_clean FROM increments''')
    c.execute('''CREATE TEMP TABLE person_counts AS SELECT j,em,
        sum(n_old) OVER (PARTITION BY j ORDER BY em)::BIGINT n_old,
        sum(n_clean) OVER (PARTITION BY j ORDER BY em)::BIGINT n_clean
        FROM (SELECT j,em,sum(n_old) n_old,sum(n_clean) n_clean FROM increments GROUP BY j,em)''')
    c.execute('DROP TABLE increments')
    return dict(arm_history_rows=seen,author_arm_history_rows_removed=removed)

def count_query(query, month_expr):
    return f'''SELECT q.*,
        (coalesce(j.n_old,0)-coalesce(p.n_old,0))::BIGINT n7_original,
        (coalesce(j.n_clean,0)-coalesce(p.n_clean,0))::BIGINT n7_author_clean
        FROM ({query}) q
        ASOF LEFT JOIN person_counts j ON q.opponent_id=j.j AND {month_expr}>=j.em
        ASOF LEFT JOIN pair_counts p ON q.opponent_id=p.j AND q.recipient_id=p.i AND {month_expr}>=p.em'''

def score_shard(job):
    threads_one()
    def build(tmp):
        c=io.conn(tmp/'spill',job['memory'],1)
        try:
            info=build_counts(c,job['histories'],job['authors'],job['shard'])
            check=count_query('SELECT * FROM '+io.parq([job['validation']]),'q.month_code')
            n,bad=c.execute('SELECT count(*),count(*) FILTER(WHERE n7_original IS DISTINCT FROM n_7d) FROM ('+check+')').fetchone()
            if bad:raise RuntimeError(f'Cached lag-7 counts failed reproduction in shard {job["shard"]}: {bad} mismatches')
            info.update(cached_score_rows_checked=n,cached_score_count_mismatches=bad)
            author_ids=','.join(map(str,job['authors']));counts=[]
            for m,path in enumerate(job['queries']):
                query=count_query('SELECT *, '+str(m)+'::SMALLINT AS count_month FROM '+io.parq([path]),'q.count_month')
                statement=f'''SELECT *,
                   (white_id IN ({author_ids}) OR black_id IN ({author_ids})) AS author_game,
                   (utc_ms-{97*core.DAY} >= {int(core.STARTS[0])}) AS prior_97d_complete,
                   CASE WHEN white_id IN ({author_ids}) OR black_id IN ({author_ids}) THEN 'AUTHOR_GAME'
                        WHEN utc_ms-{97*core.DAY} < {int(core.STARTS[0])} THEN 'INCOMPLETE_97D_HISTORY'
                        WHEN n7_author_clean < 5 THEN 'FEWER_THAN_FIVE_PRIOR_DECISIONS'
                        ELSE 'POTENTIALLY_ELIGIBLE' END AS local_eligibility
                   FROM ({query})'''
                nr=io.copy(c,statement,tmp/(ex.MONTHS[m]+'.parquet'));counts.append(nr)
            info.update(rows=sum(counts),month_rows=counts,future_outcomes_read=False)
            return info
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(Path(job['output']),job['conf'],build,job['histories']+job['queries']+[job['validation']])[1]

def assemble_month(job):
    threads_one()
    def build(tmp):
        c=io.conn(tmp/'spill',job['memory'],1)
        try:
            view=io.parq(job['parts']);source=io.parq([job['frame']])
            counts=dict(c.execute('SELECT local_eligibility,count(*) FROM '+view+' GROUP BY 1').fetchall())
            n,distinct=c.execute('SELECT count(*),count(DISTINCT game_id) FROM '+view).fetchone()
            if n!=distinct or n!=pq.ParquetFile(job['frame']).metadata.num_rows:raise RuntimeError('Frame row preservation failed')
            # Every original frame field, not merely the number of rows, is checked.
            cols=ex.frame_schema().names
            mismatch=' OR '.join(f'a.{qident(k)} IS DISTINCT FROM b.{qident(k)}' for k in cols)
            bad=c.execute('SELECT count(*) FROM '+source+' a FULL JOIN '+view+' b USING(game_id) WHERE '+mismatch).fetchone()[0]
            if bad:raise RuntimeError('The reduction changed frozen frame fields')
            if c.execute('SELECT count(*) FROM '+view+' WHERE n7_original<0 OR n7_author_clean<0 OR n7_author_clean>n7_original').fetchone()[0]:
                raise RuntimeError('Invalid historical decision count')
            io.copy(c,'SELECT * FROM '+view+' ORDER BY game_id',tmp/'ledger.parquet')
            return dict(rows=n,counts=counts,frame_fields_changed=bad,
                        previous_frame_rows=int(c.execute('SELECT count(*) FROM '+view+' WHERE previous_frame').fetchone()[0]))
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(Path(job['output']),job['conf'],build,job['parts']+[job['frame']])[1]

def prepare(inputs,root,conf,workers,memory):
    part=root/'partitions';qjobs=[dict(path=p,month=m,output=str(part/m),conf=conf) for m,p in zip(ex.MONTHS,inputs['frame'])]
    io.mapped(partition_month,qjobs,workers,'Reusing fixed PGN-derived frame')
    validation,_=validation_queries(inputs['spaced'],root/'validation_queries',conf)
    jobs=[dict(histories=[p['path'] for p in inputs['parts'] if p['shard']==s],
               queries=[str(part/m/f'{s:02}.parquet') for m in ex.MONTHS],validation=str(validation/f'{s:02}.parquet'),
               authors=list(inputs['author_ids'].values()),shard=s,memory=memory/workers,
               output=str(root/'counts'/f'{s:02}'),conf=conf) for s in range(SHARDS)]
    checks=io.mapped(score_shard,jobs,workers,'Exact prior decision support')
    if sum(r['cached_score_rows_checked'] for r in checks)!=2682330:raise RuntimeError('Historical score validation did not cover the full frozen IV cohort')
    jobs=[dict(parts=[str(root/'counts'/f'{s:02}'/(m+'.parquet')) for s in range(SHARDS)],frame=p,
               memory=memory/workers,output=str(root/'eligibility'/m),conf=conf) for m,p in zip(ex.MONTHS,inputs['frame'])]
    results=io.mapped(assemble_month,jobs,workers,'Preserving every frame row')
    if sum(r['rows'] for r in results)!=FRAME_ROWS or sum(r['previous_frame_rows'] for r in results)!=ex.OLD_ROWS:
        raise RuntimeError('Frame totals changed')
    return [str(root/'eligibility'/m/'ledger.parquet') for m in ex.MONTHS],checks,results
