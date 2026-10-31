"""Bounded, checkpointed metadata audit and reconciliation.

All copies of a game go to the same stable MD5 bucket, including copies with
conflicting dates. No global metadata GROUP BY or full-width FULL JOIN runs.
The original field-conflict, readiness, quarantine and pool rules are retained.
"""
from rebuild_common import *
from repair_chronology import partition
import duckdb, math

BUCKETS=128
MAX_ROWS=250000
MEMORY_GB=4.
BUFFER_BYTES=64*1024*1024


def bucket_sql(modulus=BUCKETS):
    # Stable across DuckDB releases, unlike its general-purpose hash().
    return f'md5_number_lower(game_id)%{int(modulus)}'


def normalized_source(path):
    import rebuild_metadata as md
    names=pq.ParquetFile(path).schema_arrow.names
    require(set(md.expansion.META_FIELDS+['game_id'])<=set(names),'Metadata schema incomplete: '+str(path))
    if 'cached_conflict_or_prior_flag' in names:flag='coalesce(cached_conflict_or_prior_flag,FALSE)'
    else:
        require('record_errors' in names,'Missing metadata error flag: '+str(path))
        flag="coalesce(record_errors,'')<>''"
    return 'SELECT game_id,'+','.join(md.expansion.META_FIELDS)+','+flag+' cached_conflict_or_prior_flag FROM '+parq([path])+' WHERE game_id IS NOT NULL'


def partition_input(root,conf,sql,deps,label):
    def build(tmp):
        c=connection(tmp,MEMORY_GB)
        try:
            c.execute('CREATE VIEW source AS '+sql)
            copy_query(c,'SELECT * FROM source LIMIT 0',tmp/'empty.parquet')
            n=c.execute('SELECT count(*) FROM source').fetchone()[0]
            stats=partition(c,'SELECT *,'+bucket_sql(BUCKETS)+' bucket FROM source',tmp/'parts',
                buckets=BUCKETS,label=label,expected_rows=n,buffer_bytes=BUFFER_BYTES)
            return dict(rows=n,partition_stats=stats,algorithm='md5_number_lower_mod_v1')
        finally:c.close()
    return stage(root,conf,build,deps)[0]


def bucket_paths(root,k):
    found=sorted((root/'parts'/f'bucket={k}').glob('*.parquet'))
    return found or [root/'empty.parquet']


def append_parquets(paths,dest):
    """One typed writer; never load or concatenate whole population tables."""
    require(bool(paths),'No typed inputs for assembly')
    schema=pq.ParquetFile(paths[0]).schema_arrow;rows=0
    with pq.ParquetWriter(dest,schema,compression='zstd',use_dictionary=False) as writer:
        for p in paths:
            pf=pq.ParquetFile(p)
            require(pf.schema_arrow.equals(schema,check_metadata=False),'Metadata assembly schema changed: '+str(p))
            for batch in pf.iter_batches(batch_size=65536,use_threads=False):
                writer.write_batch(batch,row_group_size=65536);rows+=batch.num_rows
    return rows


def disposition_sql():
    import rebuild_metadata as md
    return 'SELECT f.row_id,f.game_id,'+md.ready_sql()+''' disposition,
        (q.game_id IS NOT NULL) inherited_quarantine
        FROM f LEFT JOIN m USING(game_id) LEFT JOIN quarantine q ON f.game_id=q.game_id'''


def check_quarantine(c,paths):
    c.execute('CREATE VIEW quarantine AS SELECT game_id FROM '+parq(paths))
    require(c.execute('SELECT count(*),count(DISTINCT game_id) FROM quarantine').fetchone()==(3,3),
            'Inherited metadata quarantine changed')


def unique_queries(c,name='f'):
    n,u,g,bad=c.execute(f'SELECT count(*),count(DISTINCT row_id),count(DISTINCT game_id),'
                       f'count(*) FILTER(WHERE row_id IS NULL OR game_id IS NULL) FROM {name}').fetchone()
    require(n==u==g and bad==0,'Duplicate or null eligible row/game ID')
    return n


def audit_leaf(tmp,qp,mp,quarantine,modulus,residue):
    import rebuild_metadata as md
    c=connection(tmp,MEMORY_GB)
    try:
        copy_query(c,'SELECT * FROM '+parq(qp)+f' WHERE {bucket_sql(modulus)}={residue}',tmp/'query.parquet')
        c.execute('CREATE VIEW f AS SELECT * FROM '+parq([tmp/'query.parquet']))
        n=unique_queries(c)
        copy_query(c,md.metadata_union(c,mp,tmp/'query.parquet'),tmp/'known.parquet')
        c.execute('CREATE VIEW m AS SELECT * FROM '+parq([tmp/'known.parquet']))
        check_quarantine(c,quarantine)
        copy_query(c,disposition_sql(),tmp/'dispositions.parquet')
        require(pq.ParquetFile(tmp/'dispositions.parquet').metadata.num_rows==n,'Metadata audit multiplied query rows')
        c.execute('CREATE VIEW d AS SELECT * FROM '+parq([tmp/'dispositions.parquet']))
        copy_query(c,"SELECT f.game_id,f.utc_ms,f.speed_partition FROM f JOIN d USING(row_id,game_id) "
                   "WHERE d.disposition NOT IN ('CACHED_POOL_METADATA','CACHED_NONPOOL') AND NOT inherited_quarantine",
                   tmp/'targets.parquet')
        info=dict(rows=n,missing=pq.ParquetFile(tmp/'targets.parquet').metadata.num_rows,
             counts=dict(c.execute('SELECT disposition,count(*) FROM d GROUP BY 1').fetchall()),
             quarantine_rows=c.execute('SELECT count(*) FROM d WHERE inherited_quarantine').fetchone()[0],
             modulus=modulus,residue=residue)
        save(tmp/'summary.json',info);return info
    finally:c.close()


def audit_parts(run,conf,query,metadata,quarantine):
    work=run/'PRIVATE/metadata_work'
    qroot=partition_input(work/'inputs/queries',conf,'SELECT * FROM '+parq([query]),[query],'Partitioning eligible metadata queries')
    roots=[partition_input(work/'inputs'/f'cache_{i:02}',conf,normalized_source(p),[p],f'Partitioning cached metadata {i+1}/{len(metadata)}')
           for i,p in enumerate(metadata)]
    leaves=[];completed_rows=0;missing=0;fresh_seconds=0.;fresh_buckets=0
    for k in range(BUCKETS):
        began=time.monotonic();qp=bucket_paths(qroot,k)
        mp=[p for root in roots for p in bucket_paths(root,k)]
        initial_q=sum(pq.ParquetFile(p).metadata.num_rows for p in qp)
        if not initial_q:continue
        before=len(leaves);made=[]
        def leaf(modulus,residue):
            c=connection(work/'counts',MEMORY_GB)
            try:
                where=f' WHERE {bucket_sql(modulus)}={residue}'
                qn=c.execute('SELECT count(*) FROM '+parq(qp)+where).fetchone()[0]
                mn=c.execute('SELECT count(*) FROM '+parq(mp)+where).fetchone()[0]
            finally:c.close()
            if not qn:return
            deps=qp+mp+list(map(Path,quarantine));split_path=work/'audit_splits'/f'{modulus:05}_{residue:05}'
            def split():
                require(modulus<131072,'Metadata group cannot fit the bounded row cap; completed groups retained')
                stage(split_path,conf,lambda tmp:dict(modulus=modulus,residue=residue,split=True),deps)
                leaf(modulus*2,residue);leaf(modulus*2,residue+modulus)
            if qn>MAX_ROWS or mn>MAX_ROWS or (split_path/'_DONE.json').exists():split();return
            target=work/'audit'/f'{modulus:05}_{residue:05}';reused=(target/'_DONE.json').exists()
            try:
                out,info=stage(target,conf,lambda tmp:audit_leaf(tmp,qp,mp,quarantine,modulus,residue),deps)
            except duckdb.OutOfMemoryException:
                log(f'Metadata memory retry: splitting {residue}/{modulus}; completed buckets retained')
                split();return
            if not reused:made.append(1)
            leaves.append(dict(path=str(out),modulus=modulus,residue=residue,bucket=k))
        leaf(BUCKETS,k)
        for record in leaves[before:]:
            info=load(Path(record['path'])/'summary.json');completed_rows+=info['rows'];missing+=info['missing']
        if made:fresh_seconds+=time.monotonic()-began;fresh_buckets+=1
        eta=f'~{fresh_seconds/fresh_buckets*(BUCKETS-k-1)/60:.1f} min' if fresh_buckets else 'pending new bucket timing'
        log(f'Metadata audit buckets {k+1}/{BUCKETS}; {completed_rows:,} eligible rows checked; '
            f'{missing:,} lookups identified; remaining audit ETA {eta} (excludes downloads)')
    if not leaves:
        qp=[qroot/'empty.parquet'];mp=[root/'empty.parquet' for root in roots]
        out,_=stage(work/'audit/empty',conf,lambda tmp:audit_leaf(tmp,qp,mp,quarantine,BUCKETS,0),qp+mp+list(map(Path,quarantine)))
        leaves=[dict(path=str(out),modulus=BUCKETS,residue=0,bucket=0)]
    return leaves


def plan(a,run,conf,b):
    query=run/'PRIVATE/locally_eligible/queries.parquet';target=run/'PRIVATE/metadata_plan'
    dependencies=[query]+list(map(Path,b['metadata']+b['quarantine']))
    def build(tmp):
        leaves=audit_parts(run,conf,query,b['metadata'],b['quarantine'])
        folders=[Path(x['path']) for x in leaves];counts={};n=0;qn=0;rows=0
        for folder in folders:
            info=load(folder/'summary.json');n+=info['missing'];qn+=info['quarantine_rows'];rows+=info['rows']
            for label,count in info['counts'].items():counts[label]=counts.get(label,0)+count
        require(rows==pq.ParquetFile(query).metadata.num_rows==sum(counts.values()),'Metadata audit lost query rows')
        append_parquets([p/'known.parquet' for p in folders],tmp/'known.parquet')
        c=connection(tmp,MEMORY_GB)
        try:
            for name,keycol in [('dispositions','row_id'),('targets','game_id')]:
                copy_query(c,'SELECT * FROM '+parq([p/(name+'.parquet') for p in folders])+f' ORDER BY {keycol}',tmp/(name+'.parquet'))
        finally:c.close()
        require(pq.ParquetFile(tmp/'targets.parquet').metadata.num_rows==n,'Metadata target coverage changed')
        info=dict(locally_eligible=rows,metadata_counts=counts,missing_metadata_targets=n,
            known_quarantine_candidates=qn,API_requests_at_most_initial=math.ceil(n/300),
            estimated_hours_at_25_games_per_second=n/25/3600,estimate_is_scenario_not_benchmark=True,
            first_pair_and_cooldown_applied_before_requests=True,bounded_metadata=True,
            leaf_groups=len(leaves),max_input_rows_per_leaf=MAX_ROWS,duckdb_decimal_gb=MEMORY_GB,
            game_partition='stable_MD5_all_copies_of_a_game_together',workers=1)
        save(tmp/'leaves_PRIVATE.json',leaves);save(tmp/'summary.json',info);return info
    path,info=stage(target,conf,build,dependencies)
    save(run/'report/metadata_plan.json',load(path/'summary.json'))
    log(f'Metadata audit complete: {info["missing_metadata_targets"]:,} eligible games require lookup; existing records reused.')
    return path


def reconcile_leaf(tmp,query,known,fresh,quarantine,modulus,residue):
    import rebuild_metadata as md
    c=connection(tmp,MEMORY_GB)
    try:
        c.execute('CREATE VIEW f AS SELECT * FROM '+parq([query]));n=unique_queries(c)
        c.execute('CREATE VIEW oldmeta AS SELECT * FROM '+parq([known]))
        c.execute('CREATE VIEW newmeta AS SELECT n.* FROM '+parq(fresh)+' n SEMI JOIN f USING(game_id)')
        nn,nu=c.execute('SELECT count(*),count(DISTINCT game_id) FROM newmeta').fetchone()
        require(nn==nu,'Duplicate downloaded metadata game IDs')
        tests=['(o.'+k+' IS NOT NULL AND n.'+k+' IS NOT NULL AND o.'+k+' IS DISTINCT FROM n.'+k+')' for k in md.expansion.META_FIELDS]
        bad=c.execute('SELECT count(*) FROM oldmeta o JOIN newmeta n USING(game_id) WHERE '+' OR '.join(tests)).fetchone()[0]
        require(bad==0,'New metadata conflicts with cached nonmissing fields; reconciliation required')
        fields=['coalesce(o.game_id,n.game_id) game_id']+['coalesce(n.'+k+',o.'+k+') AS '+k for k in md.expansion.META_FIELDS]
        fields+=["(coalesce(o.cached_conflict_or_prior_flag,FALSE) OR coalesce(n.record_errors,'')<>'') cached_conflict_or_prior_flag"]
        copy_query(c,'SELECT '+','.join(fields)+' FROM oldmeta o FULL JOIN newmeta n USING(game_id)',tmp/'metadata.parquet')
        c.execute('CREATE VIEW m AS SELECT * FROM '+parq([tmp/'metadata.parquet']));check_quarantine(c,quarantine)
        copy_query(c,disposition_sql(),tmp/'dispositions.parquet')
        require(pq.ParquetFile(tmp/'dispositions.parquet').metadata.num_rows==n,'Metadata completion multiplied query rows')
        c.execute('CREATE VIEW d AS SELECT * FROM '+parq([tmp/'dispositions.parquet']))
        unresolved=c.execute("SELECT count(*) FROM d WHERE disposition NOT IN ('CACHED_POOL_METADATA','CACHED_NONPOOL') AND NOT inherited_quarantine").fetchone()[0]
        info=dict(rows=n,new_unresolved_rows=unresolved,
            existing_quarantine_rows=c.execute('SELECT count(*) FROM d WHERE inherited_quarantine').fetchone()[0],
            dispositions=dict(c.execute('SELECT disposition,count(*) FROM d GROUP BY 1').fetchall()))
        sql='''SELECT f.*,m.anchor_ms,m.tc_base_s,m.tc_inc_s,m.status,
            CASE WHEN f.recipient_color='white' THEN m.white_rating ELSE m.black_rating END recipient_rating,
            CASE WHEN f.recipient_color='white' THEN m.black_rating ELSE m.white_rating END opponent_rating,
            CASE WHEN f.recipient_color='white' THEN m.white_username ELSE m.black_username END recipient_username,
            CASE WHEN f.recipient_color='white' THEN m.black_username ELSE m.white_username END opponent_username,
            m.status IN ('mate','resign','stalemate') ordinary_narrow,m.status='timeout' active_timeout
            FROM f JOIN m USING(game_id) JOIN d USING(row_id,game_id)
            WHERE d.disposition='CACHED_POOL_METADATA' AND NOT d.inherited_quarantine'''
        copy_query(c,sql,tmp/'queries.parquet')
        info['pool_rows']=pq.ParquetFile(tmp/'queries.parquet').metadata.num_rows
        save(tmp/'summary.json',info);return info
    finally:c.close()


def complete(a,run,conf,b,root,fresh):
    query=run/'PRIVATE/locally_eligible/queries.parquet';known=root/'known.parquet'
    def build(tmp):
        work=run/'PRIVATE/metadata_work'
        fresh_root=partition_input(work/'inputs/fresh',conf,'SELECT * FROM '+parq([fresh]),[fresh],'Partitioning downloaded metadata')
        leaves=load(root/'leaves_PRIVATE.json');folders=[];began=time.monotonic()
        info=dict(new_unresolved_rows=0,existing_quarantine_rows=0,pool_rows=0,dispositions={},bounded_metadata=True)
        rows=0
        for i,record in enumerate(leaves):
            folder=Path(record['path']);modulus=record['modulus'];residue=record['residue']
            # Verify every leaf before relying on its bounded query/known tables.
            require(frozen.r.io.complete(folder,conf) is not None,'Metadata audit leaf is incomplete')
            fp=bucket_paths(fresh_root,record['bucket'])
            dest,part=stage(work/'reconciled'/folder.name,conf,
                lambda out:reconcile_leaf(out,folder/'query.parquet',folder/'known.parquet',fp,b['quarantine'],modulus,residue),
                [folder/'query.parquet',folder/'known.parquet']+fp+list(map(Path,b['quarantine'])))
            folders.append(dest);rows+=part['rows']
            for name in ('new_unresolved_rows','existing_quarantine_rows','pool_rows'):info[name]+=part[name]
            for name,count in part['dispositions'].items():info['dispositions'][name]=info['dispositions'].get(name,0)+count
            log(f'Metadata reconciliation: {i+1}/{len(leaves)} groups complete; {rows:,} rows; '
                f'{info["new_unresolved_rows"]:,} unresolved; elapsed {(time.monotonic()-began)/60:.1f} min')
        require(rows==pq.ParquetFile(query).metadata.num_rows==sum(info['dispositions'].values()),'Metadata completion lost query rows')
        save(run/'report/metadata_completion.json',info)
        require(info['new_unresolved_rows']==0,f'{info["new_unresolved_rows"]:,} additional metadata rows remain unresolved. Frames are blocked; no available-case exclusion was invented. Return the checkpoint report.')
        append_parquets([p/'metadata.parquet' for p in folders],tmp/'metadata.parquet')
        c=connection(tmp,MEMORY_GB)
        try:
            for name in ('dispositions','queries'):
                copy_query(c,'SELECT * FROM '+parq([p/(name+'.parquet') for p in folders])+' ORDER BY row_id',tmp/(name+'.parquet'))
        finally:c.close()
        require(pq.ParquetFile(tmp/'queries.parquet').metadata.num_rows==info['pool_rows'],'Pool query coverage changed')
        save(tmp/'summary.json',info);return info
    dest,_=stage(run/'PRIVATE/metadata_complete',conf,build,[query,known,fresh,root/'leaves_PRIVATE.json']+list(map(Path,b['quarantine'])))
    save(run/'report/metadata_completion.json',load(dest/'summary.json'))
    cached_inputs.identity_check(dest/'queries.parquet',b['source'],run/'PRIVATE/identity',conf,a.memory_gb-2,min(2,a.workers))
    return dest
