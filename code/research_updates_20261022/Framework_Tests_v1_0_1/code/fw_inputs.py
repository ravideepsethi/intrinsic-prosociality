"""Authenticate the reviewed 24-month pool panel and retain source semantics."""
from fw_common import *
import importlib.util

def authority():
    p=ROOT/'vendor_r8/vendor_merit/source/pool_wave1_common.py'
    spec=importlib.util.spec_from_file_location('framework_sample_authority',p)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def project_month(job):
    out=Path(job['out']);key=job['key'];src=Path(job['path'])
    if completed(out,key):return dict(month=job['month'],path=str(out/'data.parquet'),**load(out/'summary.json'))
    out.mkdir(parents=True,exist_ok=True);before=stamp(src)
    require(sha(src)==job['expected_sha256'],'Source hash differs: '+str(src))
    c=conn(out/'spill',job['memory'],1)
    try:
        c.execute('CREATE VIEW src AS SELECT * FROM '+parq([src]))
        invalid=c.execute('''SELECT count(*) FROM src WHERE chooser_user_id IS NULL OR disconnected_user_id IS NULL
          OR chooser_username_norm IS NULL OR disconnected_username_norm IS NULL OR game_id IS NULL
          OR outcome_kind_draw IS NULL OR outcome_kind_draw NOT IN (0,1) OR engine_eval_cp_disconnected IS NULL
          OR NOT coalesce(isfinite(chooser_draw_payoff_v2) AND isfinite(chooser_win_premium_v2) AND chooser_win_premium_v2>0
            AND isfinite(chooser_elo) AND isfinite(disconnected_elo),false)
          OR NOT isfinite(engine_eval_cp_disconnected) OR engine_eval_is_mate IS NULL OR ply_count IS NULL OR ply_count<0
          OR NOT coalesce(api_status='timeout' AND five_second_rule_passed AND api_rated AND api_variant='standard',false)
          OR NOT coalesce(sf100k_nodes_requested=100000 AND sf100k_fen_turn_matches_disconnected_color,false)
          OR NOT coalesce(disconnected_color=sf100k_disconnected_color_for_perspective AND side_to_move_after_last=disconnected_color,false)
          OR (NOT engine_eval_is_mate AND engine_eval_cp_disconnected_raw IS DISTINCT FROM engine_eval_cp_disconnected)
          OR (engine_eval_is_mate AND abs(engine_eval_cp_disconnected)<>10000)
          OR api_speed IS NULL OR api_speed NOT IN ('ultraBullet','ultrabullet','bullet','blitz','rapid','classical')
          OR api_last_move_at_ms IS NULL OR archive_ordinal IS NULL''').fetchone()[0]
        require(invalid==0,f'{job["month"]}: {invalid} invalid source rows')
        require(c.execute('SELECT count(*),count(DISTINCT game_id) FROM src').fetchone()==(job['rows'],job['rows']),'Source row/uniqueness mismatch')
        require(c.execute('SELECT count(*) FROM src WHERE month IS DISTINCT FROM ?', [job['month']]).fetchone()[0]==0,'Source month mismatch')
        c.execute('CREATE VIEW clean AS SELECT * FROM src WHERE '+u.author_predicate())
        m=MONTHS.index(job['month'])
        sql=f'''SELECT chooser_user_id::BIGINT chooser,disconnected_user_id::BIGINT opponent,
          lower(trim(chooser_username_norm)) chooser_name,game_id,archive_ordinal::BIGINT archive_ordinal,api_last_move_at_ms::BIGINT event_ms,
          outcome_kind_draw::TINYINT y,engine_eval_cp_disconnected_raw::DOUBLE cp,
          engine_eval_cp_disconnected::DOUBLE board,engine_eval_is_mate::BOOLEAN mate,ply_count::INTEGER ply,
          chooser_draw_payoff_v2::DOUBLE rG,chooser_win_premium_v2::DOUBLE premium,
          chooser_elo::DOUBLE rating,(disconnected_elo-chooser_elo)::DOUBLE gap,
          chooser_pre_rd_v2::DOUBLE rd_c,disconnected_pre_rd_v2::DOUBLE rd_d,
          chooser_clock_last_obs_s::DOUBLE clock_c,disconnected_clock_last_obs_s::DOUBLE clock_d,
          {m}::TINYINT month_code,{1 if m<12 else 2}::TINYINT AS "year",
          CASE api_speed WHEN 'ultraBullet' THEN 0 WHEN 'ultrabullet' THEN 0 WHEN 'bullet' THEN 1
          WHEN 'blitz' THEN 2 WHEN 'rapid' THEN 3 WHEN 'classical' THEN 4 END::TINYINT speed_code,
          CASE WHEN ply_count<=2 THEN 0 WHEN ply_count<=10 THEN 1 WHEN ply_count<=20 THEN 2
          WHEN ply_count<=40 THEN 3 WHEN ply_count<=80 THEN 4 ELSE 5 END::TINYINT stage FROM clean'''
        tmp=out/'data.partial.parquet';c.execute(f'COPY ({sql}) TO {qs(tmp)} (FORMAT PARQUET, COMPRESSION ZSTD)')
        n=c.execute('SELECT count(*),sum(outcome_kind_draw),count(*) FILTER(WHERE engine_eval_cp_disconnected>=-100) FROM clean').fetchone()
        summary=dict(rows=int(n[0]),grants=int(n[1] or 0),competitive=int(n[2]),removed=int(job['rows']-n[0]),source_sha256=job['expected_sha256'])
        require(stamp(src)==before,'Source changed while projecting')
        os.replace(tmp,out/'data.parquet');save(out/'summary.json',summary);certify(out,key,[src],summary)
    finally:c.close()
    return dict(month=job['month'],path=str(out/'data.parquet'),**summary)

def prepare(a,run,key):
    with heartbeat('Bind reviewed pool/nonadjacent sample'):
        auth=authority().authenticate_sample(a.project_root/u.MAIN_REL,verify_hashes=False,hash_workers=1)
    save(run/'SOURCE_PRIVATE.json',u.clean(auth))
    jobs=[dict(r,path=str(r['path']),key=digest([key,r['month'],r['expected_sha256']]),
      out=str(run/'input'/r['month']),memory=max(.35,(a.memory_gb-2)/a.workers)) for r in auth['month_records']]
    records=run_pool(project_month,jobs,a.workers,'Main-panel projection');records.sort(key=lambda r:r['month'])
    save(run/'INPUTS_PRIVATE.json',records)
    require(len(records)==24 and [r['month'] for r in records]==MONTHS,'Incomplete source months')
    return [r['path'] for r in records]

def aggregate_accounts(paths,work,key,memory):
    if completed(work,key):return work/'accounts_F_state_year.parquet'
    work.mkdir(parents=True,exist_ok=True);c=conn(work/'spill',max(1,memory-2),2)
    try:
        c.execute('CREATE VIEW p AS SELECT * FROM '+parq(paths))
        q='''SELECT chooser,year,late,state,count(*)::BIGINT n,sum(y)::BIGINT y
          FROM p CROSS JOIN (VALUES(false),(true)) l(late)
          CROSS JOIN (VALUES('C'),('N'),('L')) s(state)
          WHERE (NOT late OR ply>10) AND ((state='C' AND board>=-100) OR (state='N' AND board< -100) OR (state='L' AND board<=-300))
          GROUP BY ALL ORDER BY chooser,year,late,state'''
        c.execute(f'COPY ({q}) TO {qs(work/"accounts_F_state_year.parquet")} (FORMAT PARQUET,COMPRESSION ZSTD)')
    finally:c.close()
    certify(work,key,paths);return work/'accounts_F_state_year.parquet'

def partitions(paths,work,key,memory,shards=128):
    if completed(work,key):return sorted(work.glob('accounts/bucket_*.parquet'))
    work.mkdir(parents=True,exist_ok=True);dest=work/'fragments'
    if not (work/'fragmented/_DONE.json').exists():
        if dest.exists():dest.rename(work/('interrupted_fragments_'+str(time.time_ns())))
        c=conn(work/'spill',max(1,memory-2),2)
        try:c.execute(f'COPY (SELECT *,((chooser%{shards}+{shards})%{shards})::INTEGER bucket FROM {parq(paths)}) TO {qs(dest)} (FORMAT PARQUET,COMPRESSION ZSTD,PARTITION_BY(bucket))')
        finally:c.close()
        fragments=sorted(dest.glob('bucket=*/*.parquet'))
        certify(work/'fragmented',digest([key,'fragments']),paths,outputs=fragments)
    else:require(completed(work/'fragmented',digest([key,'fragments'])),'Fragment checkpoint missing')
    fragments=sorted(dest.glob('bucket=*/*.parquet'))
    return consolidate_buckets(fragments,paths,work,key,memory,shards)

def consolidate_buckets(fragments,source_paths,work,key,memory,shards=128):
    """One physical file per chooser bucket, even when COPY emitted many fragments."""
    work=Path(work)
    if completed(work,key):return sorted(work.glob('accounts/bucket_*.parquet'))
    dest=work/'accounts';dest.mkdir(parents=True,exist_ok=True)
    by_bucket={}
    for path in map(Path,fragments):
        require(path.parent.name.startswith('bucket='),'Unrecognized account bucket: '+str(path))
        bucket=int(path.parent.name.split('=')[1]);require(0<=bucket<shards,'Invalid account bucket')
        by_bucket.setdefault(bucket,[]).append(path)
    require(by_bucket,'No account partition fragments')
    c=conn(work/'spill',max(1,memory-2),2)
    try:
        for i,(bucket,files) in enumerate(sorted(by_bucket.items())):
            output=dest/f'bucket_{bucket:03d}.parquet';receipt=work/'buckets'/str(bucket);bk=digest([key,bucket])
            if not completed(receipt,bk):
                invalid=c.execute(f'SELECT count(*) FROM {parq(files)} WHERE chooser IS NULL OR ((chooser%{shards}+{shards})%{shards})<>{bucket}').fetchone()[0]
                require(invalid==0,'Chooser stored in the wrong bucket')
                tmp=output.with_suffix('.partial.parquet')
                c.execute(f'COPY (SELECT * FROM {parq(files)} ORDER BY chooser,year,month_code,archive_ordinal,game_id) TO {qs(tmp)} (FORMAT PARQUET,COMPRESSION ZSTD)')
                require(pq.ParquetFile(tmp).metadata.num_rows==sum(pq.ParquetFile(p).metadata.num_rows for p in files),'Account-bucket row loss')
                os.replace(tmp,output);certify(receipt,bk,files,outputs=[output])
            log(f'Complete chooser buckets: {i+1}/{len(by_bucket)}')
    finally:c.close()
    outputs=sorted(dest.glob('bucket_*.parquet'))
    require(len(outputs)==len(by_bucket),'Unexpected completed account bucket')
    require(sum(pq.ParquetFile(p).metadata.num_rows for p in outputs)==sum(pq.ParquetFile(p).metadata.num_rows for p in source_paths),'Partition count mismatch')
    certify(work,key,source_paths);return outputs
