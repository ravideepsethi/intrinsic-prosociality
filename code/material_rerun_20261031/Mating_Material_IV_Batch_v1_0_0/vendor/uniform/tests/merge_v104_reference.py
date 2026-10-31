"""v1.0.3: unchanged bounded merge; compute scan bucket IDs from physical Arrow keys.

Completed partition stage identities and paths are unchanged. Only candidate/pair
partition readers are replaced. Classification, time boundaries and covariance
are not modified. Actual missing keys must be repaired, never filled or dropped.
"""
from repair_chronology import *
from fast_chronology_repair import partition_files as partition_scan_files

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
    written_bytes=0;partition_files=0;partition_rows=0;fresh_bytes=0;fresh_seconds=0.;replacement_batch=False
    for batch,start in enumerate(range(0,len(parts),16)):
        group=parts[start:start+16];deps=[p/n for p in group for n in ('candidates.parquet','pairs.parquet')]
        def build(tmp,group=group):
            c=connection(tmp,memory)
            try:
                counts={n:sum(pq.ParquetFile(p/(n+'.parquet')).metadata.num_rows for p in group) for n in ('candidates','pairs')}
                log(f'Partition batch {batch+1}/{(len(parts)+15)//16}: {counts["candidates"]:,} candidate rows and {counts["pairs"]:,} pair rows')
                ci=partition_scan_files([p/'candidates.parquet' for p in group],'sample_row',tmp/'candidates',
                    buckets=buckets,label=f'Batch {batch+1} candidates',expected_rows=counts['candidates'])
                pi=partition_scan_files([p/'pairs.parquet' for p in group],'pair_key',tmp/'pairs',
                    buckets=buckets,label=f'Batch {batch+1} pairs',expected_rows=counts['pairs'])
                return dict(input_parts=len(group),candidates=ci,pairs=pi)
            finally:c.close()
        target=root/'partitioned'/f'{batch:03}'
        if (target/'_DONE.json').exists():
            previous_deps=load(target/'dependencies_PRIVATE.json')
            current_deps=[dict(path=str(p.resolve()),signature=io.sig(p)) for p in deps]
            if [{k:r[k] for k in ('path','signature')} for r in previous_deps]!=current_deps:
                # A newly reconstructed source must not overwrite or reuse an old
                # partition made from the damaged summary. Preserve it and bind a
                # separate replacement branch to the explicit corrected inputs.
                target=root/'partitioned_repaired103'/(f'{batch:03}_'+key(current_deps)[:12]);replacement_batch=True
        reused=(target/'_DONE.json').exists();batch_began=time.monotonic()
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
    if replacement_batch:
        root=root/'downstream_repaired103'/key([str(p.resolve()) for p in groups])[:12]
        log('Corrected partition inputs: using separate downstream checkpoints; original checkpoints retained.')
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
