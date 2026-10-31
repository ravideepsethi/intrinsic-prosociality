"""Certified input -> one narrow projection -> chooser-complete partitions."""
from common import *
from design import MONTHS,SPEEDS

def material_sql(role):
    return '+'.join(f'{w}*{role}_{piece}' for piece,w in [('pawns',1),('knights',3),('bishops',3),('rooks',5),('queens',9)])

def projection_sql(source,month):
    speed="CASE api_speed WHEN 'ultraBullet' THEN 0 WHEN 'ultrabullet' THEN 0 WHEN 'bullet' THEN 1 WHEN 'blitz' THEN 2 WHEN 'rapid' THEN 3 WHEN 'classical' THEN 4 ELSE NULL END"
    return f'''SELECT chooser_user_id::BIGINT chooser, outcome_kind_draw::TINYINT y,
        engine_eval_cp_disconnected_raw::DOUBLE cp,engine_eval_cp_disconnected::DOUBLE board,
        engine_eval_is_mate::BOOLEAN mate,ply_count::INTEGER ply,
        ({material_sql('disconnected')})-({material_sql('chooser')}) AS material,
        chooser_elo::DOUBLE rating,(disconnected_elo-chooser_elo)::DOUBLE gap,
        CASE WHEN chooser_elo<1600 THEN 0 WHEN chooser_elo<2000 THEN 1 WHEN chooser_elo<2400 THEN 2 ELSE 3 END::TINYINT tier,
        chooser_clock_last_obs_s::DOUBLE clock_c,disconnected_clock_last_obs_s::DOUBLE clock_d,
        chooser_win_premium_v2::DOUBLE premium,chooser_pre_rd_v2::DOUBLE rd_c,disconnected_pre_rd_v2::DOUBLE rd_d,
        {MONTHS.index(month)}::TINYINT month_code,({speed})::TINYINT speed_code,
        CASE WHEN ply_count<2 THEN 0 WHEN ply_count=2 THEN 1 WHEN ply_count<=4 THEN 2 WHEN ply_count<=6 THEN 3
          WHEN ply_count<=8 THEN 4 WHEN ply_count<=10 THEN 5 WHEN ply_count<=20 THEN 6
          WHEN ply_count<=40 THEN 7 WHEN ply_count<=80 THEN 8 ELSE 9 END::TINYINT stage
        FROM {source}'''

def fen_material(fen,color):
    parts=fen.split();require(len(parts)==6,'Invalid FEN length')
    require(parts[1]==('w' if color=='white' else 'b'),'FEN turn disagrees with disconnected color')
    white=sum({'P':1,'N':3,'B':3,'R':5,'Q':9}.get(c,0) for c in parts[0])
    black=sum({'p':1,'n':3,'b':3,'r':5,'q':9}.get(c,0) for c in parts[0])
    return white-black if color=='white' else black-white

def project_month(task):
    src=Path(task['source']);out=Path(task['output']);t0=time.monotonic()
    key=fingerprint([task['key'],task['month'],task['expected_sha256'],stamp(src)])
    if valid(out,key):return dict(month=task['month'],seconds=0,reused=True,**load(str(out)+'.ok.json')['counts'])
    require(sha(src)==task['expected_sha256'],'Certified input SHA256 mismatch: '+str(src))
    d=dbopen(out.parent/'spill'/task['month'],1,task['memory_gb'])
    try:
        d.execute('CREATE VIEW src AS SELECT * FROM '+parq([src]))
        # Explicit semantics checked on every row. No rebuilding of the outcome/membership.
        bad=d.execute(f'''SELECT count(*) FROM src WHERE
          month IS DISTINCT FROM {qs(task['month'])} OR outcome_kind_draw IS NULL OR chooser_user_id IS NULL
          OR engine_eval_cp_disconnected IS NULL OR engine_eval_is_mate IS NULL OR ply_count IS NULL OR ply_count<0
          OR chooser_elo IS NULL OR disconnected_elo IS NULL
          OR NOT coalesce(sf100k_nodes_requested=100000,false)
          OR NOT coalesce(sf100k_fen_turn_matches_disconnected_color,false)
          OR NOT coalesce(disconnected_color=sf100k_disconnected_color_for_perspective,false)
          OR NOT coalesce(side_to_move_after_last=disconnected_color,false)
          OR NOT coalesce(api_status='timeout' AND five_second_rule_passed AND api_rated AND api_variant='standard',false)
          OR (NOT engine_eval_is_mate AND (engine_eval_cp_disconnected_raw IS NULL
              OR engine_eval_cp_disconnected_raw IS DISTINCT FROM engine_eval_cp_disconnected))
          OR (engine_eval_is_mate AND abs(engine_eval_cp_disconnected)<>10000)
          OR ({material_sql('disconnected')})-({material_sql('chooser')}) IS DISTINCT FROM disconnected_minus_chooser_material
          OR api_speed NOT IN ('ultraBullet','ultrabullet','bullet','blitz','rapid','classical') OR api_speed IS NULL
          ''').fetchone()[0]
        require(bad==0,f'{task["month"]}: {bad} rows failed field semantics; see private error receipt')
        for fen,color,material in d.execute('SELECT fen_after_last_move,disconnected_color,disconnected_minus_chooser_material FROM src LIMIT 32').fetchall():
            require(fen_material(fen,color)==material,'FEN/material orientation mismatch')
        out.parent.mkdir(parents=True,exist_ok=True);tmp=out.with_suffix('.partial.parquet')
        d.execute(f'COPY ({projection_sql("src",task["month"])}) TO {qs(tmp)} (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 122880)')
        counts=d.execute(f'''SELECT count(*) n,sum(y)::BIGINT grants,count(*) FILTER(WHERE board>=-100) competitive,
             sum(y) FILTER(WHERE board>=-100)::BIGINT competitive_grants,count(*) FILTER(WHERE board>=-100 AND ply>10) competitive_late,
             count(*) FILTER(WHERE mate) mates,count(*) FILTER(WHERE NOT mate AND cp>=600) upper_finite,
             count(*) FILTER(WHERE chooser IS NULL OR y IS NULL OR board IS NULL OR material IS NULL OR speed_code IS NULL) invalid
             FROM {parq([tmp])}''').fetchdf().iloc[0].to_dict()
        counts={k:int(v) for k,v in counts.items()};require(counts['n']==task['rows'] and counts['invalid']==0,'Projection row/count gate failed')
        os.replace(tmp,out);certify(out,key,dict(counts=counts,source_sha256=task['expected_sha256']))
        return dict(month=task['month'],seconds=time.monotonic()-t0,reused=False,**counts)
    finally:d.close()

def partition(projections,run,shards,threads,memory,key):
    target=Path(run)/'PRIVATE/by_chooser';receipt=Path(run)/'PRIVATE/PARTITIONS.json'
    if receipt.exists():
        r=load(receipt);require(r['key']==key,'Partition configuration differs')
        for x in r['files']:
            p=target/x['relative'];require(p.is_file() and sha(p)==x['sha256'],'Partition checkpoint changed')
        return r
    tmp=Path(run)/'PRIVATE/by_chooser.partial'
    if tmp.exists():
        # Preserve an interrupted generation for diagnosis; never mix partial and new files.
        tmp.rename(tmp.with_name('by_chooser.interrupted.'+str(time.time_ns())))
    d=dbopen(Path(run)/'PRIVATE/spill_partition',threads,memory)
    try:
        d.execute(f'''COPY (SELECT *,((chooser%{shards}+{shards})%{shards})::INTEGER bucket
            FROM {parq(projections)}) TO {qs(tmp)} (FORMAT PARQUET,COMPRESSION ZSTD,PARTITION_BY(bucket),ROW_GROUP_SIZE 122880)''')
    finally:d.close()
    files=[]
    for p in sorted(tmp.glob('bucket=*/*.parquet')):
        files.append(dict(relative=str(p.relative_to(tmp)),sha256=sha(p),rows=pq.ParquetFile(p).metadata.num_rows,bytes=p.stat().st_size))
    require(sum(x['rows'] for x in files)==sum(pq.ParquetFile(p).metadata.num_rows for p in projections),'Partition row conservation failed')
    tmp.rename(target);r=dict(key=key,shards=shards,files=files);dump(receipt,r);return r

def raw_summaries(projections,run,threads,memory):
    d=dbopen(Path(run)/'PRIVATE/spill_raw',threads,memory)
    try:
        d.execute('CREATE VIEW p AS SELECT *,CASE WHEN board>=300 THEN 4 WHEN board>100 THEN 3 WHEN board>=-100 THEN 2 WHEN board> -300 THEN 1 ELSE 0 END board_bin FROM '+parq(projections))
        for name,group,where in [
            ('raw_board_stage_rating','board_bin,stage,tier','true'),
            ('raw_month_speed','month_code,speed_code','true'),
            ('raw_continuous_support',"CASE WHEN mate THEN CASE WHEN board>0 THEN 'positive_mate' ELSE 'negative_mate' END WHEN cp< -600 THEN 'finite_lt_-600' WHEN cp>=600 THEN 'finite_ge600' ELSE cast(50*floor(cp/50) AS VARCHAR) END eval50,stage,tier",'true'),
            ('raw_material','material,stage,tier','true')]:
            q=f'SELECT {group},count(*) n,sum(y)::BIGINT grants,100.*avg(y) rate_percent FROM p WHERE {where} GROUP BY ALL ORDER BY ALL'
            table(Path(run)/'report'/name,d.execute(q).fetchdf())
        census=d.execute('SELECT count(*) n,sum(y)::BIGINT grants,count(DISTINCT chooser) choosers,count(*) FILTER(WHERE board>=-100) competitive,sum(y) FILTER(WHERE board>=-100)::BIGINT competitive_grants FROM p').fetchdf().iloc[0].to_dict()
        return {k:int(v) for k,v in census.items()}
    finally:d.close()
