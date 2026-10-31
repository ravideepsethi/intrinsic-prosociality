"""Memory-bounded chronology merge; read the 798 authenticated scans, never rescan games."""
from rebuild_common import *
import duckdb,contextlib,fcntl
import numpy as np
import phase_chronology as previous
io=frozen.r.io
BUCKETS=128
MAX_QUERIES=100000
MAX_CANDIDATES=4000000
FIELDS=['row_id','previous_classification_status','eligible_main','first_observed_pair','pre_games_30d']
PARTITION_BATCH_ROWS=65536
PARTITION_GROUP_ROWS=32768
PARTITION_BUFFER_BYTES=128*1024*1024

def partition(c,sql,path,*,buckets=BUCKETS,label='Partitioning',expected_rows=None,
              batch_rows=PARTITION_BATCH_ROWS,group_rows=PARTITION_GROUP_ROWS,
              buffer_bytes=PARTITION_BUFFER_BYTES):
    """Stream to ONE Parquet file per bucket, with an explicit Arrow buffer cap.

    v1.0.1's eight-open-file DuckDB COPY repeatedly evicted writers across 128
    interleaved buckets. This writer never reopens an output file. Per-bucket
    take() copies prevent a tiny slice from retaining an entire input batch.
    The byte cap covers buffered Arrow tables; the current input batch and
    bounded Parquet encoder workspaces are additional.
    """
    path=Path(path);path.mkdir(parents=True,exist_ok=False)
    reader=c.execute(sql).fetch_record_batch(rows_per_batch=batch_rows)
    index=reader.schema.get_field_index('bucket')
    require(index>=0,'Partition query has no bucket column')
    schema=reader.schema.remove(index)
    writers={};pending={};counts={};sizes={};output_rows={};buffered=0;peak=0;done=0
    began=time.monotonic();reported=began
    def flush(k):
        nonlocal buffered
        if not pending.get(k):return
        table=pa.concat_tables(pending[k])
        if k not in writers:
            folder=path/('bucket='+str(k));folder.mkdir()
            writers[k]=pq.ParquetWriter(folder/'data.parquet',schema,compression='zstd',
                use_dictionary=False,write_statistics=True,write_batch_size=1024)
        writers[k].write_table(table,row_group_size=group_rows)
        output_rows[k]=output_rows.get(k,0)+table.num_rows
        buffered-=sizes[k];pending[k]=[];counts[k]=0;sizes[k]=0
    try:
        for batch in reader:
            arr=batch.column(index)
            require(arr.null_count==0,'Null chronology partition bucket')
            ids=arr.to_numpy(zero_copy_only=False)
            require(np.issubdtype(ids.dtype,np.integer),'Noninteger chronology partition bucket')
            require(not len(ids) or (ids.min()>=0 and ids.max()<buckets),'Chronology partition bucket out of range')
            table=pa.Table.from_batches([batch]).drop(['bucket'])
            order=np.argsort(ids,kind='stable');sorted_ids=ids[order]
            boundaries=np.r_[0,np.flatnonzero(sorted_ids[1:]!=sorted_ids[:-1])+1,len(ids)]
            for lo,hi in zip(boundaries[:-1],boundaries[1:]):
                if lo==hi:continue
                k=int(sorted_ids[lo]);piece=table.take(pa.array(order[lo:hi],type=pa.int64()))
                pending.setdefault(k,[]).append(piece);counts[k]=counts.get(k,0)+piece.num_rows
                sizes[k]=sizes.get(k,0)+piece.nbytes;buffered+=piece.nbytes;peak=max(peak,buffered)
                if counts[k]>=group_rows:flush(k)
                while buffered>buffer_bytes:flush(max(sizes,key=sizes.get))
            done+=batch.num_rows
            if time.monotonic()-reported>=15:
                seconds=time.monotonic()-began;rate=done/max(seconds,.001)
                tail=(f'; remaining write ETA ~{max(0,expected_rows-done)/rate/60:.1f} min'
                      if expected_rows is not None and rate else '')
                log(f'{label}: {done:,}'+(f'/{expected_rows:,}' if expected_rows is not None else '')+
                    f' rows; {rate:,.0f} rows/s; {len(writers)} output files'+tail)
                reported=time.monotonic()
        for k in list(pending):flush(k)
    finally:
        # Failed output stays inside the stage's .partial directory, never sealed.
        for writer in writers.values():writer.close()
        reader.close()
    require(sum(output_rows.values())==done,'Partition writer row coverage changed')
    require(expected_rows is None or done==expected_rows,'Partition input row count changed')
    require(len(writers)<=buckets,'Partition file cap exceeded')
    info=dict(rows=done,output_files=len(writers),bucket_rows={str(k):n for k,n in sorted(output_rows.items())},
              seconds=time.monotonic()-began,peak_buffered_arrow_bytes=peak,
              buffer_limit_bytes=buffer_bytes,one_file_per_bucket=True)
    log(f'{label}: complete; {done:,} rows; {len(writers)} files; {info["seconds"]/60:.1f} min')
    return info

def paths_for(roots,name,k):
    return [p for root in roots for p in sorted((Path(root)/name/('bucket='+str(k))).glob('*.parquet'))]

def elapsed_message(label,done,total,began):
    elapsed=time.monotonic()-began
    remaining=elapsed/done*(total-done) if done else 0
    log(f'{label}: {done}/{total}; elapsed {elapsed/60:.1f} min; remaining phase ETA ~{remaining/60:.1f} min')

def cache_plan(a,run,conf,b):
    parent=candidate_root(run,b);query=parent/'PRIVATE/supported/queries.parquet'
    oldkey=load(Path(b['frame_root'])/'chronology/_DONE.json')['cache_definition_sha256']
    cache_root=parent/'PRIVATE/feature_cache/chronology'/oldkey/'all';definition=load(cache_root/'definition.json')
    require(io.cfgsha(definition)==oldkey,'Chronology cache definition changed')
    require(definition['kind']=='first_pair_predecessor_volume_v1' and definition['source']['files']==b['source']['chron'],'Chronology source binding differs')
    import phase_chronology,cached_chronology
    modules={Path(m.__file__).name:Path(m.__file__) for m in (chron,phase_chronology,cached_chronology,cache,cached_chronology.rebuild)}
    for name,digest in definition['code'].items():require(name in modules and sha(modules[name])==digest,'Frozen chronology producer changed: '+name)
    blocks=[]
    for p in sorted((cache_root/'blocks').glob('*')):
        if '.partial_' in p.name or not p.is_dir():continue
        require(io.complete(p,oldkey) is not None,'Incomplete prior chronology block');blocks.append(p/'records.parquet')
    def build(tmp):
        c=connection(tmp,4.)
        try:
            c.execute('CREATE VIEW q AS SELECT * FROM '+parq([query]));n=pq.ParquetFile(query).metadata.num_rows
            keys=','.join(cache.CHRON_KEYS);hitn=0
            if blocks:
                c.execute('CREATE VIEW known AS SELECT * FROM '+parq(blocks))
                ensure(c,'SELECT count(*) FROM (SELECT '+keys+' FROM known GROUP BY '+keys+' HAVING count(*)>1)','Duplicate immutable chronology keys')
                hitn=io.copy(c,'SELECT q.row_id,known.* EXCLUDE('+keys+') FROM q JOIN known USING('+keys+')',tmp/'hits.parquet')
                missing='SELECT q.* FROM q ANTI JOIN known USING('+keys+')'
            else:
                empty=pa.schema([('row_id',pa.int64()),('previous_classification_status',pa.string()),('eligible_main',pa.bool_()),('first_observed_pair',pa.bool_()),('pre_games_30d',pa.int64())])
                pq.write_table(pa.Table.from_pylist([],schema=empty),tmp/'hits.parquet');missing='SELECT * FROM q'
            miss=io.copy(c,missing+' ORDER BY q.row_id',tmp/'missing.parquet')
            require(hitn+miss==n,'Chronology reuse changed candidate coverage')
            return dict(rows=n,cache_hits=hitn,computed_rows=miss,old_cache_definition_sha256=oldkey)
        finally:c.close()
    plan,info=stage(run/'PRIVATE/chronology_repair_plan',conf,build,[query,cache_root/'definition.json']+blocks)
    return plan,info,oldkey

def choose_scan_set(parent,missing,oldkey,source,work):
    """Bind scan receipts to the exact original missing-query bytes or an exact row bridge."""
    c=connection(work,4.)
    try:latest=c.execute('SELECT max(archive_start_ms) FROM '+parq([missing])).fetchone()[0]
    finally:c.close()
    relevant=[r for r in source if r['minimum'] is None or r['minimum']<=latest]
    expected=io.cfgsha([oldkey,sha(missing)]);folder=parent/'PRIVATE/chron_parts'/expected[:16];bridge=False
    if not folder.is_dir():
        # Different Parquet writer versions may emit different bytes for identical rows.
        # No scan is accepted merely because it sits in the parent directory.
        matches=[]
        for oldquery in sorted((parent/'PRIVATE').glob('chronology.partial_*/missing.parquet')):
            ck=io.cfgsha([oldkey,sha(oldquery)]);candidate=parent/'PRIVATE/chron_parts'/ck[:16]
            if not candidate.is_dir():continue
            c=connection(work,4.)
            try:
                fields=','.join(['row_id','previous_frame']+cache.CHRON_KEYS)
                x='SELECT '+fields+' FROM '+parq([missing]);y='SELECT '+fields+' FROM '+parq([oldquery])
                same=c.execute('SELECT count(*) FROM (('+x+' EXCEPT ALL '+y+') UNION ALL ('+y+' EXCEPT ALL '+x+'))').fetchone()[0]==0
            finally:c.close()
            if same:matches.append((candidate,ck))
        require(bool(matches),'No completed scan set matches these exact chronology queries; stopped before any raw-game rescan')
        folder,expected=matches[0];bridge=True
    paths=[];records=[];began=time.monotonic()
    for k,r in enumerate(sorted(relevant,key=lambda v:v['file_index']),1):
        p=folder/f"{r['file_index']:04}"
        receipt=io.complete(p,expected)
        require(receipt is not None,'Missing completed scan '+str(p)+'; no raw-game rescan was started')
        require(receipt['file_index']==r['file_index'] and receipt['input_rows']==r['rows'],'Scan source row/index mismatch')
        paths.append(p);records.append(dict(index=r['file_index'],receipt_sha256=sha(p/'_DONE.json')))
        if k%50==0 or k==len(relevant):elapsed_message('Verifying completed chronology scans',k,len(relevant),began)
    require(bool(paths),'No chronology scan parts')
    return paths,dict(scan_configuration=expected,completed_scans_reused=len(paths),raw_game_scans_started=0,
      exact_query_row_bridge_used=bridge,source_receipts=records)

def bounded_merge(queries,parts,root,conf,memory=4.,buckets=BUCKETS,max_queries=MAX_QUERIES,max_candidates=MAX_CANDIDATES):
    """Classify independent row-ID groups with the unchanged adjacency SQL."""
    root=Path(root);parts=list(map(Path,parts));query_n=pq.ParquetFile(queries).metadata.num_rows
    pair_expr='least(recipient_id,opponent_id)::UBIGINT*4294967296+greatest(recipient_id,opponent_id)::UBIGINT'
    def qbuild(tmp):
        c=connection(tmp,memory)
        try:
            c.execute('CREATE VIEW q AS SELECT *,('+pair_expr+') pair_key FROM '+parq([queries])+' WHERE NOT previous_frame')
            row_info=partition(c,f'SELECT *,row_id%{buckets} bucket FROM q',tmp/'by_row',
                buckets=buckets,label='Query rows',expected_rows=query_n)
            pair_info=partition(c,f'SELECT row_id,pair_key,archive_start_ms,pair_key%{buckets} bucket FROM q',tmp/'by_pair',
                buckets=buckets,label='Query pairs',expected_rows=query_n)
            return dict(rows=query_n,buckets=buckets,row_partition=row_info,pair_partition=pair_info)
        finally:c.close()
    qroot,_=stage(root/'queries',conf,qbuild,[queries]);groups=[];began=time.monotonic()
    total_bytes=sum((p/n).stat().st_size for p in parts for n in ('candidates.parquet','pairs.parquet'))
    written_bytes=0;partition_files=0;partition_rows=0;fresh_bytes=0;fresh_seconds=0.
    for batch,start in enumerate(range(0,len(parts),16)):
        group=parts[start:start+16];deps=[p/n for p in group for n in ('candidates.parquet','pairs.parquet')]
        def build(tmp,group=group):
            c=connection(tmp,memory)
            try:
                counts={n:sum(pq.ParquetFile(p/(n+'.parquet')).metadata.num_rows for p in group) for n in ('candidates','pairs')}
                log(f'Partition batch {batch+1}/{(len(parts)+15)//16}: {counts["candidates"]:,} candidate rows and {counts["pairs"]:,} pair rows')
                ci=partition(c,f'SELECT *,sample_row%{buckets} bucket FROM '+parq([p/'candidates.parquet' for p in group]),tmp/'candidates',
                    buckets=buckets,label=f'Batch {batch+1} candidates',expected_rows=counts['candidates'])
                pi=partition(c,f'SELECT *,pair_key%{buckets} bucket FROM '+parq([p/'pairs.parquet' for p in group]),tmp/'pairs',
                    buckets=buckets,label=f'Batch {batch+1} pairs',expected_rows=counts['pairs'])
                return dict(input_parts=len(group),candidates=ci,pairs=pi)
            finally:c.close()
        target=root/'partitioned'/f'{batch:03}';reused=(target/'_DONE.json').exists();batch_began=time.monotonic()
        out,record=stage(target,conf,build,deps);groups.append(out)
        size=sum(p.stat().st_size for p in deps);written_bytes+=size
        if not reused:fresh_bytes+=size;fresh_seconds+=time.monotonic()-batch_began
        partition_files+=record['candidates']['output_files']+record['pairs']['output_files']
        partition_rows+=record['candidates']['rows']+record['pairs']['rows']
        estimate=(f'~{fresh_seconds/fresh_bytes*(total_bytes-written_bytes)/60:.1f} min'
                  if fresh_bytes else 'pending new batch timing')
        log(f'Partitioning saved chronology summaries: {batch+1}/{(len(parts)+15)//16}; '
            f'{100*written_bytes/max(total_bytes,1):.1f}% of source bytes; {partition_files:,} files; '
            f'remaining partition estimate {estimate} (byte-weighted, excludes later stages)')
    pair_features=[];began=time.monotonic()
    for k in range(buckets):
        qp=paths_for([qroot],'by_pair',k)
        if not qp:continue
        pp=paths_for(groups,'pairs',k);require(bool(pp),'No canonical pairs for a nonempty query partition')
        def build(tmp,qp=qp,pp=pp):
            c=connection(tmp,memory)
            try:
                c.execute('CREATE TEMP TABLE pair_min AS SELECT pair_key,min(first_t)::BIGINT first_t FROM '+parq(pp)+' GROUP BY pair_key')
                sql='SELECT q.row_id,(p.first_t=q.archive_start_ms) first_observed_pair FROM '+parq(qp)+' q LEFT JOIN pair_min p USING(pair_key)'
                ensure(c,'SELECT count(*) FROM ('+sql+') WHERE first_observed_pair IS NULL','Focal game absent from canonical pair chronology')
                copy_query(c,sql,tmp/'features.parquet');n=pq.ParquetFile(tmp/'features.parquet').metadata.num_rows
                local=partition(c,f'SELECT *,row_id%{buckets} bucket FROM '+parq([tmp/'features.parquet']),tmp/'by_row',
                    buckets=buckets,label=f'First-pair group {k+1}',expected_rows=n)
                return dict(rows=n,row_partition=local)
            finally:c.close()
        out,_=stage(root/'first_pair'/f'{k:03}',conf,build,qp+pp);pair_features.append(out)
        if (k+1)%8==0 or k+1==buckets:elapsed_message('Merging first-pair summaries',k+1,buckets,began)
    leaves=[];began=time.monotonic()
    for k in range(buckets):
        qp=paths_for([qroot],'by_row',k)
        if not qp:continue
        cp=paths_for(groups,'candidates',k)
        if not cp:cp=[parts[0]/'candidates.parquet']
        pf=paths_for(pair_features,'by_row',k)
        require(bool(pf),'No first-pair features for a nonempty row group')
        def leaf(modulus,residue):
            c=connection(root/'counts',memory)
            try:
                qn=c.execute('SELECT count(*) FROM '+parq(qp)+f' WHERE row_id%{modulus}={residue}').fetchone()[0]
                cn=c.execute('SELECT count(*) FROM '+parq(cp)+f' WHERE sample_row%{modulus}={residue}').fetchone()[0]
            finally:c.close()
            if not qn:return
            def split():
                require(modulus<32768,'Chronology leaf remains too large; stopped with saved partitions intact')
                leaf(modulus*2,residue);leaf(modulus*2,residue+modulus)
            if qn>max_queries or cn>max_candidates:split();return
            def build(tmp):
                c=connection(tmp,memory)
                try:
                    c.execute('CREATE VIEW q AS SELECT * FROM '+parq(qp)+f' WHERE row_id%{modulus}={residue}')
                    c.execute('CREATE VIEW candidates AS SELECT * FROM '+parq(cp)+f' WHERE sample_row%{modulus}={residue}')
                    c.execute('CREATE VIEW focal AS SELECT row_id sample_row,recipient_id,opponent_id FROM q')
                    c.execute('CREATE TEMP TABLE classifications AS '+previous.rebuild.adjacency_final_sql('candidates','focal'))
                    c.execute('CREATE TEMP TABLE volume AS SELECT sample_row,sum(pre_games_30d)::BIGINT pre_games_30d FROM candidates WHERE role=0 GROUP BY sample_row')
                    c.execute('CREATE TEMP TABLE pair_features AS SELECT * FROM '+parq(pf)+f' WHERE row_id%{modulus}={residue}')
                    sql='''SELECT q.row_id,s.previous_classification_status,s.previous_classification_status='''+quote(previous.rebuild.NONADJ)+''' eligible_main,
                      p.first_observed_pair,coalesce(v.pre_games_30d,0)::BIGINT pre_games_30d FROM q
                      JOIN classifications s ON q.row_id=s.sample_row LEFT JOIN pair_features p USING(row_id) LEFT JOIN volume v ON q.row_id=v.sample_row'''
                    copy_query(c,sql+' ORDER BY q.row_id',tmp/'features.parquet')
                    c.execute('CREATE VIEW result AS SELECT * FROM '+parq([tmp/'features.parquet']));ensure_unique(c,'result',qn)
                    ensure(c,'SELECT count(*) FROM result WHERE first_observed_pair IS NULL OR pre_games_30d<0','Invalid bounded chronology feature')
                    return dict(rows=qn,candidate_summary_rows=cn,modulus=modulus,residue=residue)
                finally:c.close()
            try:out,_=stage(root/'classified'/f'{modulus:05}_{residue:05}',conf,build,qp+cp+pf)
            except duckdb.OutOfMemoryException:
                log(f'Memory retry: splitting chronology group {residue}/{modulus} into two smaller groups');split();return
            leaves.append(out/'features.parquet')
        leaf(buckets,k)
        elapsed_message('Classifying bounded chronology groups',k+1,buckets,began)
    def finish(tmp):
        c=connection(tmp,memory)
        try:
            copy_query(c,'SELECT '+','.join(FIELDS)+' FROM '+parq(leaves)+' ORDER BY row_id',tmp/'features.parquet')
            c.execute('CREATE VIEW f AS SELECT * FROM '+parq([tmp/'features.parquet']));ensure_unique(c,'f',query_n)
            counts=[dict(classification=x,rows=n) for x,n in c.execute('SELECT previous_classification_status,count(*) FROM f GROUP BY 1').fetchall()]
            return dict(rows=query_n,classifications=counts,bounded_merge=True,leaf_groups=len(leaves),max_queries_per_leaf=max_queries,
              max_candidate_rows_per_leaf=max_candidates,duckdb_memory_gb=memory,workers=1,factual_author_games_preserved=True,
              partition_writer='bounded_arrow_single_file_per_bucket_v102',partition_files=partition_files,
              partition_rows=partition_rows,partition_file_cap_per_batch=2*buckets,
              first_pair_reads_restricted_to_current_row_bucket=True)
        finally:c.close()
    return stage(root/'complete',conf,finish,[queries]+leaves)

def run_chronology(a,run,conf,b):
    parent=candidate_root(run,b);plan,info,oldkey=cache_plan(a,run,conf,b);missing=plan/'missing.parquet';outputs=[plan/'hits.parquet']
    if info['computed_rows']:
        with (parent/'RUN.lock').open('r') as lock:
            try:fcntl.flock(lock.fileno(),fcntl.LOCK_SH|fcntl.LOCK_NB)
            except BlockingIOError:raise RuntimeError('The original run is active; stop that terminal before resuming the repair')
            parts,reuse=choose_scan_set(parent,missing,oldkey,b['source']['chron'],run/'PRIVATE/scan_identity')
            save(run/'report/chronology_scan_reuse.json',reuse)
            log(f'Reusing all {len(parts)} completed scans. Starting bounded merge; no raw-game scan is scheduled.')
            out,merge=bounded_merge(missing,parts,run/'PRIVATE/chronology_merge',conf,4.)
        outputs.append(out/'features.parquet');save(run/'report/chronology_merge.json',frozen.public(merge))
    query=parent/'PRIVATE/supported/queries.parquet'
    def combine(tmp):
        c=connection(tmp,4.)
        try:
            copy_query(c,' UNION ALL '.join('SELECT '+','.join(FIELDS)+' FROM '+parq([p]) for p in outputs)+' ORDER BY row_id',tmp/'features.parquet')
            c.execute('CREATE VIEW f AS SELECT * FROM '+parq([tmp/'features.parquet']));ensure_unique(c,'f',info['rows'])
            ensure(c,'SELECT count(*) FROM f FULL JOIN '+parq([query])+' q USING(row_id) WHERE f.row_id IS NULL OR q.row_id IS NULL','Chronology assembly row IDs changed')
            return dict(rows=info['rows'],cache_hits=info['cache_hits'],computed_rows=info['computed_rows'],execution='v102_bounded_files_merge_of_v100_scans')
        finally:c.close()
    final,summary=stage(run/'PRIVATE/chronology',conf,combine,[query]+outputs)
    save(run/'report/chronology_reuse.json',frozen.public(summary))
    def choose(tmp):
        c=connection(tmp,a.memory_gb-2)
        try:
            sql='SELECT q.*,x.* EXCLUDE(row_id) FROM '+parq([query])+' q JOIN '+parq([final/'features.parquet'])+' x USING(row_id) WHERE x.eligible_main AND x.first_observed_pair ORDER BY row_id'
            copy_query(c,sql,tmp/'queries.parquet');return dict(rows=pq.ParquetFile(tmp/'queries.parquet').metadata.num_rows)
        finally:c.close()
    _,eligible=stage(run/'PRIVATE/locally_eligible',conf,choose,[query,final/'features.parquet'])
    save(run/'report/local_eligibility.json',frozen.public(eligible))
