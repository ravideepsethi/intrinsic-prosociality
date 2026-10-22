from pathlib import Path
from common import *
from source import pool_wave1_common as authority

SNAPSHOT='derived/replication/patron_profile_snapshot_24m_v100_FINAL_CERTIFIED/profile_snapshot_24m_private_lossless.parquet'
SNAPSHOT_SHA='f42f28a6540a65c0a83f0da488663b4adddf60d1001daeed556f1ffbb961e238'
SUPPLEMENT='derived/replication/pool_main_reanalysis_v100_PRIVATE/patron_gap_fill_v100/*/current_profile_gap_supplement_private.parquet'
SUPPLEMENT_SHA='39a9c911bb0030d2dacc7c73f77d0bb94bc27981be347dd3e03f30af8b0482aa'

def cached_profiles(db,project,run):
    p=project/SNAPSHOT;require(p.is_file(),'Missing certified profile snapshot: '+str(p))
    require(sha(p)==SNAPSHOT_SHA,'Certified August snapshot checksum changed')
    src=[('august',p)]
    for p in sorted(project.glob(SUPPLEMENT)):
        if sha(p)==SUPPLEMENT_SHA:src.append(('september',p));break
    queries=[]
    for label,p in src:
        cols=set(pq.ParquetFile(p).schema_arrow.names)
        require({'username_norm','returned','raw_user_json'}<=cols,'Profile fields missing')
        cell='match_cell' if 'match_cell' in cols else ('new_match_cell' if 'new_match_cell' in cols else None)
        created='try_cast(created_at_ms AS BIGINT)' if 'created_at_ms' in cols else 'NULL::BIGINT'
        queries.append(f'''SELECT lower(trim(username_norm)) username,returned::BOOLEAN returned,
          {qs(label)} profile_source,{qi(cell) if cell else 'NULL::VARCHAR'}::VARCHAR match_cell,
          {created} normalized_created,try_cast(raw_user_json AS JSON) j FROM read_parquet({qs(p)})''')
    db.execute('CREATE TEMP TABLE raw_profiles AS '+' UNION ALL '.join(queries))
    require(db.execute("SELECT count(*) FROM raw_profiles WHERE username IS NULL OR username='' OR returned IS NULL OR (returned AND coalesce(json_type(j)<>'OBJECT',true))").fetchone()[0]==0,'Malformed returned profile')
    db.execute('''CREATE TEMP TABLE parsed_profiles AS SELECT * EXCLUDE(j),
      try_cast(json_extract_string(j,'$.createdAt') AS BIGINT) raw_created,
      coalesce(try_cast(json_extract_string(j,'$.disabled') AS BOOLEAN),false) disabled,
      try_cast(json_extract_string(j,'$.patron') AS BOOLEAN) patron_raw FROM raw_profiles''')
    require(db.execute('SELECT count(*) FROM parsed_profiles WHERE normalized_created IS NOT NULL AND raw_created IS NOT NULL AND normalized_created<>raw_created').fetchone()[0]==0,'Creation-date fields disagree')
    require(db.execute('SELECT count(*) FROM (SELECT username FROM parsed_profiles WHERE returned GROUP BY username HAVING count(*)>1)').fetchone()[0]==0,'Duplicate returned snapshots; resolve dates before merging')
    db.execute('''CREATE TEMP TABLE profiles_cache AS SELECT username,returned,profile_source,match_cell,disabled,
      CASE WHEN returned AND coalesce(raw_created,normalized_created) BETWEEN 946684800000 AND epoch_ms(current_timestamp)
           THEN coalesce(raw_created,normalized_created) END created_ms,
      CASE WHEN returned AND NOT disabled THEN coalesce(patron_raw,false)::INTEGER END patron
      FROM parsed_profiles QUALIFY row_number() OVER(PARTITION BY username ORDER BY returned DESC,profile_source='august' DESC)=1''')
    export(db,run/'report/PROFILE_CACHE_COVERAGE.csv','''SELECT profile_source,returned,disabled,count(*) accounts,
      count(created_ms) known_creation,count(patron) known_patron FROM profiles_cache GROUP BY ALL ORDER BY ALL''')
    db.execute('DROP TABLE parsed_profiles');db.execute('DROP TABLE raw_profiles')
    return [{'label':x,'sha256':sha(p)} for x,p in src]

def project_query(path):
    return f'''SELECT game_id,chooser_user_id::BIGINT chooser,disconnected_user_id::BIGINT recipient,
      lower(trim(chooser_username_norm)) username,lower(trim(disconnected_username_norm)) recipient_name,
      outcome_kind_draw::INTEGER y,engine_eval_cp_disconnected::DOUBLE board,
      (engine_eval_cp_disconnected>=-100)::INTEGER competitive,
      CASE WHEN engine_eval_cp_disconnected<=-300 THEN '0_clearly_worse' WHEN engine_eval_cp_disconnected< -100 THEN '1_modestly_worse'
           WHEN engine_eval_cp_disconnected<=100 THEN '2_equal' WHEN engine_eval_cp_disconnected<300 THEN '3_better' ELSE '4_clearly_better' END board_bin,
      CASE WHEN ply_count<=4 THEN '0_0_4' WHEN ply_count<=6 THEN '1_5_6' WHEN ply_count<=8 THEN '2_7_8' WHEN ply_count<=10 THEN '3_9_10'
           WHEN ply_count<=20 THEN '4_11_20' WHEN ply_count<=40 THEN '5_21_40' WHEN ply_count<=80 THEN '6_41_80' ELSE '7_81plus' END stage,
      (ply_count>10 AND ply_count<=40)::INTEGER stage_mid,(ply_count>40)::INTEGER stage_late,
      month::VARCHAR AS "month",api_speed::VARCHAR AS speed,time_control::VARCHAR AS time_control,ply_count,
      chooser_elo::DOUBLE rating, (disconnected_elo-chooser_elo)/100. gap100,
      CASE WHEN chooser_elo<1600 THEN '0_under1600' WHEN chooser_elo<2000 THEN '1_1600_1999' WHEN chooser_elo<2400 THEN '2_2000_2399' ELSE '3_2400plus' END rating_tier,
      floor((disconnected_elo-chooser_elo)/200)::INTEGER gap_bin,
      chooser_draw_payoff_v2/10. payoff10,chooser_win_premium_v2/10. premium10,
      chooser_pre_rd_v2/100. crd100,disconnected_pre_rd_v2/100. drd100,
      ln(1+greatest(0,coalesce(chooser_clock_last_obs_s,0))) log_cc,
      ln(1+greatest(0,coalesce(disconnected_clock_last_obs_s,0))) log_dc,
      (chooser_clock_last_obs_s IS NULL)::INTEGER cc_missing,(disconnected_clock_last_obs_s IS NULL)::INTEGER dc_missing,
      api_created_at_ms::BIGINT game_ms,api_last_move_at_ms::BIGINT last_ms,fen_after_last_move,
      disconnected_color,chooser_color,api_winner,api_variant,api_status,api_rated,
      sf100k_stockfish_sha256,engine_eval_is_mate,
      CASE WHEN month<'2024-11' THEN 1 ELSE 2 END yr
      FROM read_parquet({qs(path)},hive_partitioning=false)'''

def prepare(db,project,run,args,key):
    with heartbeat('Authenticating current sample'):
        auth=authority.authenticate_sample(args.sample_root or project/'derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE',verify_hashes=True,hash_workers=min(4,args.threads))
    dump(run/'report/SAMPLE_LINEAGE.json',authority.compact_sample_lineage(auth))
    paths=[r['path'] for r in auth['month_records']]
    db.execute('CREATE TEMP VIEW src AS SELECT * FROM '+parq(paths))
    with heartbeat('Census account inventory'):
        copy(db,run/'PRIVATE/accounts.parquet','''SELECT chooser_user_id::BIGINT chooser,any_value(lower(trim(chooser_username_norm))) username,
          count(*) n,sum(outcome_kind_draw)::BIGINT grants,min(api_created_at_ms)::BIGINT first_ms,
          count(DISTINCT lower(trim(chooser_username_norm))) AS username_count FROM src GROUP BY chooser_user_id''',key)
    db.execute(f'CREATE TEMP VIEW accounts AS SELECT * FROM read_parquet({qs(run/"PRIVATE/accounts.parquet")})')
    expected_census=(auth['authority']['choosers'],auth['authority']['rows'],auth['authority']['kind_draws'],1)
    require(db.execute('SELECT count(*),sum(n),sum(grants),max(username_count) FROM accounts').fetchone()==expected_census,'Census account inventory failed')
    require(db.execute('SELECT count(*) FROM (SELECT username FROM accounts GROUP BY username HAVING count(*)>1)').fetchone()[0]==0,'Account name has multiple numeric IDs')
    copy(db,run/'PRIVATE/selected_accounts.parquet',f'''SELECT *,row_number() OVER(ORDER BY md5(chooser::VARCHAR || {qs(':'+str(args.seed))}),chooser)::BIGINT draw_rank
      FROM accounts QUALIFY draw_rank<={int(args.tenure_accounts)}''',key)
    db.execute(f'CREATE TEMP VIEW selected AS SELECT * FROM read_parquet({qs(run/"PRIVATE/selected_accounts.parquet")})')
    projected=[]
    for spec in auth['month_records']:
        dest=run/'PRIVATE/panel'/f'{spec["month"]}.parquet';projected.append(dest)
        if not checkpoint(dest,key):
            log('Projecting selected histories '+spec['month'])
            copy(db,dest,'SELECT p.*,s.draw_rank FROM ('+project_query(spec['path'])+') p JOIN selected s USING(chooser)',key)
    db.execute('CREATE TEMP VIEW panel AS SELECT * FROM '+parq(projected))
    expected=db.execute('SELECT sum(n),sum(grants) FROM selected').fetchone()
    require(db.execute('SELECT count(*),sum(y) FROM panel').fetchone()==expected,'Selected history totals changed')
    require(db.execute("SELECT count(*) FROM panel WHERE chooser=recipient OR game_ms IS NULL OR game_ms<946684800000 OR board IS NULL OR y NOT IN(0,1) OR y IS NULL").fetchone()[0]==0,'Invalid selected rows')
    copy(db,run/'PRIVATE/trajectory_targets.parquet',f'SELECT * FROM panel WHERE draw_rank<={args.responsibility_accounts} ORDER BY month,game_id',key)
    counts=records(db,f'''SELECT count(*) opportunities,sum(y) grants,count(DISTINCT chooser) accounts,
      sum(least(ply_count+1,5)) requested_positions FROM panel WHERE draw_rank<={args.responsibility_accounts}''')[0]
    dump(run/'report/DESIGN.json',dict(version=VERSION,seed=args.seed,tenure_accounts=args.tenure_accounts,
      responsibility_accounts=args.responsibility_accounts,selection='Uniform deterministic MD5 order over 3,224,173 chooser IDs; full histories; no outcomes in selection',
      tenure_inclusion_probability=args.tenure_accounts/3224173,responsibility_inclusion_probability=args.responsibility_accounts/3224173,
      trajectory_plan=counts,age_anchor='game start api_created_at_ms minus account createdAt; milliseconds / 86400000',
      repeated_opportunity_weights='Equal inclusion probability per chooser implies equal inclusion probability per opportunity; use ordinary opportunity means with chooser clusters',
      population='Certified pool / observed-nonadjacent 24-month sample',network_enabled=dict(profiles=args.fetch_profiles,games=args.fetch_games)))
    return auth

def attach_age(db):
    # Never overwrite a valid immutable cached creation date with a recent profile field.
    db.execute('''CREATE OR REPLACE TEMP VIEW joined_age AS SELECT p.*,c.profile_source,c.patron,c.match_cell,
      coalesce(c.created_ms,f.created_ms) created_ms,
      (p.game_ms-coalesce(c.created_ms,f.created_ms))/86400000. raw_age,
      (a.first_ms-coalesce(c.created_ms,f.created_ms))/86400000. raw_first_age,
      CASE WHEN c.created_ms IS NOT NULL THEN 'cached' WHEN f.created_ms IS NOT NULL THEN 'fetched' ELSE 'unknown' END age_source
      FROM panel p JOIN accounts a USING(chooser)
      LEFT JOIN profiles_cache c ON p.username=c.username LEFT JOIN profiles_fetch f ON p.username=f.username''')
    db.execute('''CREATE OR REPLACE TEMP VIEW aged0 AS SELECT *,CASE WHEN raw_age>=0 AND raw_first_age>=0 THEN raw_age END age_days,
      CASE WHEN raw_first_age>=0 THEN raw_first_age END first_age FROM joined_age''')
    db.execute(f'CREATE OR REPLACE TEMP VIEW aged AS SELECT *,{age_bin("age_days")} tenure,{age_bin("first_age")} cohort FROM aged0')
