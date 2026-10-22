from __future__ import annotations
import json
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
from utils import *

SNAPSHOT_REL='derived/replication/patron_profile_snapshot_24m_v100_FINAL_CERTIFIED/profile_snapshot_24m_private_lossless.parquet'
SNAPSHOT_SHA='f42f28a6540a65c0a83f0da488663b4adddf60d1001daeed556f1ffbb961e238'
SUPPLEMENT_GLOB='derived/replication/pool_main_reanalysis_v100_PRIVATE/patron_gap_fill_v100/*/current_profile_gap_supplement_private.parquet'
SUPPLEMENT_SHA='39a9c911bb0030d2dacc7c73f77d0bb94bc27981be347dd3e03f30af8b0482aa'

def classification(code):
    if not code: return ('missing',None,None)
    c=code.upper(); iso=read(ROOT/'iso_countries.json'); catalog=read(ROOT/'flag_catalog.json')
    if c in {'AQ','BV','HM','TF','GS','UM'}: return ('geographic_exception',None,c)
    if c in iso: return ('iso_country_or_territory',c,c)
    if c=='EU': return ('supranational',None,None)
    if code.startswith('_'): return ('symbolic_or_identity',None,None)
    if c in catalog and '-' in c:
        parent=c.split('-')[0] if c.startswith(('GB-','CA-','ES-','PT-','RU-')) else None
        return ('subnational_or_regional',None,parent)
    if c in catalog: return ('other_geographic_or_legacy',None,None)
    return ('unrecognized',None,None)

def normalize_profiles(db,sources,run):
    queries=[]
    for label,path in sources:
        cols=set(pq.ParquetFile(path).schema_arrow.names)
        require({'username_norm','returned','raw_user_json','profile_flag','profile_country'}<=cols,'Required profile columns missing: '+str(path))
        def col(name,default='NULL'): return qi(name) if name in cols else default
        role=col('acquisition_role',col('new_role'))
        cell=col('match_cell',col('new_match_cell'))
        queries.append(f'''SELECT {qs(label)} profile_source,
          lower(trim(username_norm)) username, returned::BOOLEAN returned,
          CAST({role} AS VARCHAR) acquisition_role, CAST({cell} AS VARCHAR) match_cell,
          CAST({col('queried_at_utc')} AS VARCHAR) observed_at,
          try_cast(raw_user_json AS JSON) j,
          nullif(trim(CAST(profile_flag AS VARCHAR)),'') normalized_flag,
          nullif(trim(CAST(profile_country AS VARCHAR)),'') normalized_country,
          try_cast({col('profile_present')} AS BOOLEAN) extracted_profile_present,
          try_cast({col('play_time_tv_seconds')} AS DOUBLE) normalized_tv
          FROM read_parquet({qs(path)})''')
    db.execute('CREATE OR REPLACE TEMP TABLE raw_profiles AS '+' UNION ALL '.join(queries))
    bad=db.execute("SELECT count(*) FROM raw_profiles WHERE returned IS NULL OR username IS NULL OR username='' OR (returned AND coalesce(json_type(j)<>'OBJECT',true))").fetchone()[0]
    require(bad==0,'Unknown return status, invalid ID, or missing raw object in profile inputs')
    export(db,run/'report'/'01_return_status_by_source_role.csv',"SELECT profile_source,acquisition_role,returned,count(*) row_count,count(DISTINCT username) accounts FROM raw_profiles GROUP BY ALL ORDER BY ALL")
    db.execute('''CREATE OR REPLACE TEMP TABLE parsed_profiles AS SELECT *,
      nullif(trim(json_extract_string(j,'$.profile.flag')),'') raw_flag,
      nullif(trim(json_extract_string(j,'$.profile.country')),'') raw_country,
      coalesce(json_type(j,'$.profile')='OBJECT',false) profile_object,
      coalesce(try_cast(json_extract_string(j,'$.disabled') AS BOOLEAN),false) disabled,
      try_cast(json_extract_string(j,'$.tosViolation') AS BOOLEAN) tos_raw,
      coalesce(normalized_tv,try_cast(json_extract_string(j,'$.playTime.tv') AS DOUBLE)) tv_seconds
      FROM raw_profiles''')
    require(db.execute('SELECT count(*) FROM parsed_profiles WHERE returned AND tv_seconds IS NOT NULL AND (tv_seconds<0 OR NOT isfinite(tv_seconds))').fetchone()[0]==0,'Invalid TV-time value')
    # Audit disagreements before applying any fallback or geographic classification.
    comparisons=[('normalized_flag_vs_country','normalized_flag','normalized_country'),('raw_flag_vs_country','raw_flag','raw_country'),
                 ('raw_vs_normalized_flag','raw_flag','normalized_flag'),('raw_vs_normalized_country','raw_country','normalized_country')]
    sql=[]
    for label,a,b in comparisons:
        sql.append(f'''SELECT {qs(label)} comparison,profile_source,acquisition_role,count(*) returned_rows,
          count(*) FILTER(WHERE {a} IS NOT NULL AND {b} IS NOT NULL) both_nonempty,
          count(*) FILTER(WHERE {a} IS NOT NULL AND {b} IS NOT NULL AND lower({a})<>lower({b})) disagreements
          FROM parsed_profiles WHERE returned GROUP BY ALL''')
    export(db,run/'report'/'00_flag_field_disagreements.csv',' UNION ALL '.join(sql))
    export(db,run/'report'/'00_conflicting_code_pairs.csv',"SELECT raw_flag,raw_country,normalized_flag,normalized_country,count(*) row_count FROM parsed_profiles WHERE returned AND list_unique(list_filter([lower(raw_flag),lower(raw_country),lower(normalized_flag),lower(normalized_country)],x->x IS NOT NULL))>1 GROUP BY ALL ORDER BY row_count DESC")
    db.execute('''CREATE OR REPLACE TEMP TABLE profiles AS SELECT * EXCLUDE(j,normalized_tv,tos_raw),
       coalesce(raw_flag,normalized_flag,raw_country,normalized_country) original_code,
       upper(coalesce(raw_flag,normalized_flag,raw_country,normalized_country)) flag_code,
       coalesce(raw_flag,normalized_flag,raw_country,normalized_country) IS NOT NULL flag_present,
       list_unique(list_filter([lower(raw_flag),lower(raw_country),lower(normalized_flag),lower(normalized_country)],x->x IS NOT NULL))>1 flag_conflict,
       CASE WHEN returned AND NOT disabled THEN coalesce(tos_raw,false) ELSE NULL END tos_mark
       FROM parsed_profiles
       QUALIFY row_number() OVER(PARTITION BY username ORDER BY returned DESC,profile_source='august' DESC,observed_at)=1''')
    # Multiple returned snapshots are not silently combined.
    require(db.execute('SELECT count(*) FROM (SELECT username FROM raw_profiles WHERE returned GROUP BY username HAVING count(*)>1)').fetchone()[0]==0,'Multiple returned snapshots for an account; resolve source dates explicitly')
    codes=[r[0] for r in db.execute('SELECT DISTINCT original_code FROM profiles').fetchall()]
    rows=[dict(flag_code=(c.upper() if c else None),flag_class=classification(c)[0],iso_code=classification(c)[1],parent_code=classification(c)[2]) for c in codes]
    # Case variants have already been audited; classify one row per canonical code.
    rows=list({r['flag_code']:r for r in rows}.values())
    db.register('cleaning_rows',pa.Table.from_pylist(rows,schema=pa.schema([('flag_code',pa.string()),('flag_class',pa.string()),('iso_code',pa.string()),('parent_code',pa.string())])))
    db.execute('''CREATE OR REPLACE TEMP TABLE profile_lookup AS SELECT p.*,
      coalesce(c.flag_class,'missing') flag_class,
      CASE WHEN NOT flag_conflict THEN c.iso_code END iso_code,
      CASE WHEN NOT flag_conflict THEN c.parent_code END parent_code,
      CASE WHEN NOT returned THEN 'unreturned' WHEN disabled THEN 'closed_profile_unavailable'
           WHEN flag_conflict THEN 'conflicting_fields' WHEN flag_present THEN 'flag_present' ELSE 'active_no_flag' END flag_status
      FROM profiles p LEFT JOIN cleaning_rows c USING(flag_code)''')
    export(db,run/'report'/'01_flag_coverage_by_source_role.csv','''SELECT profile_source,acquisition_role,count(*) accounts,
      count(*) FILTER(WHERE profile_object) with_profile,count(*) FILTER(WHERE extracted_profile_present) extracted_profile_present,
      count(*) FILTER(WHERE flag_present) with_flag,count(DISTINCT flag_code) distinct_flags,
      count(*) FILTER(WHERE flag_conflict) conflicting_flags,count(*) FILTER(WHERE iso_code IS NOT NULL) usable_iso_flags,
      count(*) FILTER(WHERE disabled) disabled FROM profile_lookup WHERE returned GROUP BY ALL ORDER BY ALL''')
    export(db,run/'report'/'03_flag_codes_and_cleaning.csv',"SELECT profile_source,acquisition_role,original_code,flag_code,flag_class,iso_code,parent_code,flag_conflict,count(*) accounts FROM profile_lookup WHERE returned GROUP BY ALL ORDER BY accounts DESC")
    export(db,run/'report'/'00_profile_structure_check.csv',"SELECT returned,disabled,profile_object,extracted_profile_present,count(*) row_count FROM parsed_profiles GROUP BY ALL ORDER BY ALL")
    parquet(db,run/'PRIVATE'/'profiles.parquet','SELECT * FROM profile_lookup')
    db.execute('DROP TABLE raw_profiles'); db.execute('DROP TABLE parsed_profiles')

def slim_query(path):
    return f'''SELECT
      chooser_user_id::BIGINT chooser, disconnected_user_id::BIGINT recipient,
      lower(trim(chooser_username_norm)) chooser_name, lower(trim(disconnected_username_norm)) recipient_name,
      outcome_kind_draw::INTEGER y, engine_eval_cp_disconnected::DOUBLE board,
      CASE WHEN engine_eval_cp_disconnected>=300 THEN '5_better_300plus'
           WHEN engine_eval_cp_disconnected>100 THEN '4_better_101_299'
           WHEN engine_eval_cp_disconnected>=-100 THEN '3_equal'
           WHEN engine_eval_cp_disconnected>-300 THEN '2_worse_101_299' ELSE '1_worse_300minus' END board_bin,
      CASE WHEN engine_eval_cp_disconnected>=-100 THEN 'competitive'
           WHEN engine_eval_cp_disconnected<=-300 THEN 'clearly_worse' ELSE 'middle' END state,
      CASE WHEN chooser_elo<1600 THEN '1_under1600' WHEN chooser_elo<2000 THEN '2_1600_1999'
           WHEN chooser_elo<2400 THEN '3_2000_2399' ELSE '4_2400plus' END rating_tier,
      CASE WHEN ply_count<=4 THEN '1_0_4' WHEN ply_count<=10 THEN '2_5_10' WHEN ply_count<=20 THEN '3_11_20'
           WHEN ply_count<=40 THEN '4_21_40' WHEN ply_count<=80 THEN '5_41_80' ELSE '6_81plus' END ply_bin,
      CASE WHEN disconnected_elo-chooser_elo < -400 THEN '1_lt_m400'
           WHEN disconnected_elo-chooser_elo < -200 THEN '2_m400_m201'
           WHEN disconnected_elo-chooser_elo < -50 THEN '3_m200_m51'
           WHEN disconnected_elo-chooser_elo <= 50 THEN '4_m50_p50'
           WHEN disconnected_elo-chooser_elo <= 200 THEN '5_p51_p200'
           WHEN disconnected_elo-chooser_elo <= 400 THEN '6_p201_p400' ELSE '7_gt_p400' END gap_bin,
      month::VARCHAR AS month,api_speed::VARCHAR AS speed,utc_ms::BIGINT AS utc_ms,
      chooser_draw_payoff_v2/10. payoff10,chooser_win_premium_v2/10. premium10,
      chooser_pre_rd_v2/100. crd100,disconnected_pre_rd_v2/100. drd100,
      CASE WHEN chooser_clock_last_obs_s IS NULL OR NOT isfinite(chooser_clock_last_obs_s) OR chooser_clock_last_obs_s<0
           THEN 0 ELSE ln(1+chooser_clock_last_obs_s) END log_cc,
      CASE WHEN disconnected_clock_last_obs_s IS NULL OR NOT isfinite(disconnected_clock_last_obs_s) OR disconnected_clock_last_obs_s<0
           THEN 0 ELSE ln(1+disconnected_clock_last_obs_s) END log_dc,
      (chooser_clock_last_obs_s IS NULL OR NOT isfinite(chooser_clock_last_obs_s) OR chooser_clock_last_obs_s<0)::INTEGER cc_missing,
      (disconnected_clock_last_obs_s IS NULL OR NOT isfinite(disconnected_clock_last_obs_s) OR disconnected_clock_last_obs_s<0)::INTEGER dc_missing,
      chooser_elo::DOUBLE chooser_rating
      FROM read_parquet({qs(path)},hive_partitioning=false)'''

def prepare_panel(db,run,auth,identity):
    paths=[]
    for r in auth['month_records']:
        out=run/'PRIVATE'/'panel'/f'{r["month"]}.parquet'; paths.append(out)
        if not valid(out,identity):
            log('PROJECT_PANEL '+r['month'])
            parquet(db,out,slim_query(r['path'])); certify(out,identity)
    files='['+','.join(qs(p) for p in paths)+']'
    db.execute(f'CREATE OR REPLACE TEMP VIEW panel AS SELECT * FROM read_parquet({files})')
    counts=records(db,'''SELECT count(*) AS "rows",sum(y)::BIGINT kind_draws,count(*) FILTER(WHERE board>=-100) fair_rows,
      sum(y) FILTER(WHERE board>=-100)::BIGINT fair_kind_draws,count(DISTINCT chooser) choosers,
      count(*) FILTER(WHERE chooser IS NULL OR recipient IS NULL OR chooser=recipient OR chooser_name IS NULL OR recipient_name IS NULL
       OR y NOT IN(0,1) OR y IS NULL OR board IS NULL OR NOT isfinite(board)) invalid FROM panel''')[0]
    require(counts['invalid']==0,'Invalid IDs/outcomes in current panel')
    for k,v in auth['authority'].items():
        if k in counts: require(counts[k]==v,'Panel count mismatch: '+k)
    dump(run/'report'/'CURRENT_PANEL_COUNTS.json',counts)
    db.execute('''CREATE OR REPLACE TEMP TABLE user_map AS
       SELECT chooser uid,chooser_name username FROM panel GROUP BY ALL
       UNION SELECT recipient uid,recipient_name username FROM panel GROUP BY ALL''')
    require(db.execute('SELECT count(*) FROM (SELECT uid FROM user_map GROUP BY uid HAVING count(*)>1)').fetchone()[0]==0,'User ID has multiple names')
    require(db.execute('SELECT count(*) FROM (SELECT username FROM user_map GROUP BY username HAVING count(*)>1)').fetchone()[0]==0,'Username has multiple numeric IDs')
    db.execute('''CREATE OR REPLACE TEMP TABLE accounts AS SELECT chooser,any_value(chooser_name) username,count(*) n,
       sum(y)::BIGINT grants,count(*) FILTER(WHERE board>=-100) fair_n,
       coalesce(sum(y) FILTER(WHERE board>=-100),0)::BIGINT fair_grants,
       count(*) FILTER(WHERE board<=-300) lost_n,coalesce(sum(y) FILTER(WHERE board<=-300),0)::BIGINT lost_grants,
       avg(chooser_rating) mean_rating,count(DISTINCT month) active_months FROM panel GROUP BY chooser''')
    parquet(db,run/'PRIVATE'/'accounts.parquet','SELECT * FROM accounts')
    parquet(db,run/'PRIVATE'/'user_map.parquet','SELECT * FROM user_map')
    attach_views(db)
    return paths

def attach_views(db):
    db.execute('''CREATE OR REPLACE TEMP VIEW joined AS SELECT p.*,c.profile_source,c.returned,c.disabled,c.match_cell,
      c.acquisition_role,c.flag_present,c.flag_code,c.flag_conflict,c.iso_code,c.parent_code,
      coalesce(c.flag_status,'not_acquired') flag_status,c.tv_seconds,c.tv_seconds>0 tv_positive,
      CASE WHEN c.tv_seconds IS NULL THEN 'unavailable' WHEN c.tv_seconds>0 THEN 'positive_recorded_tv' ELSE 'zero_recorded_tv' END tv_group,
      r.returned recipient_returned,coalesce(r.flag_status,'not_acquired') recipient_flag_status,r.flag_code recipient_flag,
      r.flag_conflict recipient_conflict,r.iso_code recipient_iso,r.parent_code recipient_parent,r.tos_mark recipient_tos,
      coalesce(c.flag_present AND r.flag_present,false) both_flags,
      coalesce(c.iso_code IS NOT NULL AND r.iso_code IS NOT NULL,false) both_iso
      FROM panel p LEFT JOIN profile_lookup c ON p.chooser_name=c.username
      LEFT JOIN profile_lookup r ON p.recipient_name=r.username''')
    db.execute('''CREATE OR REPLACE TEMP VIEW model_data AS SELECT j.*,ln(1+a.n) log_volume FROM joined j JOIN accounts a USING(chooser)''')
    db.execute('''CREATE OR REPLACE TEMP VIEW accounts_model AS SELECT a.*,p.profile_source,p.returned,p.disabled,p.match_cell,
      p.acquisition_role,p.flag_present,coalesce(p.flag_status,'not_acquired') flag_status,
      p.iso_code,p.flag_code,p.flag_conflict,(fair_grants>0)::INTEGER ever_fair
      FROM accounts a LEFT JOIN profile_lookup p USING(username)''')

def rate_table(db,path,group,where='true',source='joined'):
    # Sampling uncertainty for an opportunity-weighted mean, clustered on chooser.
    sql=f'''WITH a AS (SELECT {group},chooser,count(*) n,sum(y)::DOUBLE k FROM {source} WHERE {where} GROUP BY ALL),
      t AS (SELECT {group},sum(n)::BIGINT opportunities,sum(k)::BIGINT grants,count(*) choosers,
        sum(k)/sum(n) rate,sum(k*k) kk,sum(k*n) kn,sum(n*n) nn FROM a GROUP BY ALL)
      SELECT {group},opportunities,grants,choosers,100*rate grant_rate_pct,
       CASE WHEN choosers>1 THEN 100*sqrt(greatest(0,kk-2*rate*kn+rate*rate*nn)*choosers/(choosers-1))/opportunities END chooser_cluster_se_pp
       FROM t ORDER BY {group}'''
    export(db,path,sql)

def gradient_table(db,path,group,where='true',source='joined'):
    sql=f'''WITH a AS (SELECT {group},chooser,
       count(*) FILTER(WHERE board>=-100)::DOUBLE nf,coalesce(sum(y) FILTER(WHERE board>=-100),0)::DOUBLE kf,
       count(*) FILTER(WHERE board<=-300)::DOUBLE nl,coalesce(sum(y) FILTER(WHERE board<=-300),0)::DOUBLE kl
       FROM {source} WHERE {where} GROUP BY ALL),
      t AS (SELECT {group},sum(nf) nf,sum(kf) kf,sum(nl) nl,sum(kl) kl,count(*) FILTER(WHERE nf+nl>0) g FROM a GROUP BY ALL),
      s AS (SELECT {group},sum(pow((a.kf-t.kf/t.nf*a.nf)/t.nf-(a.kl-t.kl/t.nl*a.nl)/t.nl,2)) meat
        FROM a JOIN t USING({group}) WHERE t.nf>0 AND t.nl>0 GROUP BY {group})
      SELECT {','.join('t.'+g.strip() for g in group.split(','))},t.nf competitive_opportunities,t.kf competitive_grants,
       t.nl losing_opportunities,t.kl losing_grants,100*t.kf/nullif(t.nf,0) competitive_rate_pct,
       100*t.kl/nullif(t.nl,0) losing_rate_pct,100*(t.kf/nullif(t.nf,0)-t.kl/nullif(t.nl,0)) gradient_pp,
       CASE WHEN t.g>1 THEN 100*sqrt(greatest(0,s.meat)*t.g/(t.g-1)) END chooser_cluster_se_pp
       FROM t LEFT JOIN s USING({group}) ORDER BY {','.join('t.'+g.strip() for g in group.split(','))}'''
    export(db,path,sql)

def core_tables(db,run):
    r=run/'report'
    export(db,r/'02_current_chooser_flag_selection.csv','''SELECT flag_status,profile_source,acquisition_role,count(*) accounts,
      count(*) FILTER(WHERE fair_n>0) accounts_with_competitive_opportunity,
      count(*) FILTER(WHERE fair_grants>0) ever_competitive_granters,
      100.*count(*) FILTER(WHERE fair_grants>0)/nullif(count(*) FILTER(WHERE fair_n>0),0) ever_competitive_pct,
      sum(fair_n) competitive_opportunities,sum(fair_grants) competitive_grants,
      100.*sum(fair_grants)/nullif(sum(fair_n),0) competitive_grant_rate_pct FROM accounts_model GROUP BY ALL ORDER BY ALL''')
    export(db,r/'02_match_cell_flag_selection.csv','''SELECT profile_source,match_cell,flag_present,count(*) accounts,
      sum(ever_fair) ever_competitive_granters,avg(ever_fair)*100 ever_competitive_pct,
      sum(fair_n) opportunities,sum(fair_grants) grants FROM accounts_model
      WHERE returned AND NOT disabled AND fair_n>0 GROUP BY ALL ORDER BY ALL''')
    rate_table(db,r/'02_flag_state_rates.csv','flag_status,state')
    gradient_table(db,r/'02_flag_board_gradient.csv','flag_status')
    rate_table(db,r/'03_country_state_rates_selected_sample.csv','iso_code,state','iso_code IS NOT NULL')
    export(db,r/'04_both_player_coverage.csv','''SELECT flag_status,recipient_flag_status,state,count(*) opportunities,sum(y) grants,
      count(DISTINCT chooser) choosers,count(DISTINCT recipient) recipients FROM joined GROUP BY ALL ORDER BY ALL''')
    db.execute('''CREATE OR REPLACE TEMP VIEW supported_pairs AS SELECT *,
      CASE WHEN both_iso THEN CASE WHEN iso_code=recipient_iso THEN 'same_iso' ELSE 'different_iso' END ELSE 'not_both_usable_iso' END iso_pair,
      CASE WHEN both_flags AND NOT flag_conflict AND NOT recipient_conflict THEN CASE WHEN flag_code=recipient_flag THEN 'same_exact_flag' ELSE 'different_exact_flag' END ELSE 'not_both_unconflicted_flags' END exact_pair,
      CASE WHEN parent_code IS NOT NULL AND recipient_parent IS NOT NULL THEN CASE WHEN parent_code=recipient_parent THEN 'same_parent_mapping' ELSE 'different_parent_mapping' END ELSE 'not_both_parent_mapped' END parent_pair
      FROM joined''')
    for label in ['iso_pair','exact_pair','parent_pair']:
        rate_table(db,r/f'04_{label}_support_rates.csv',label+',state',source='supported_pairs')
    export(db,r/'04_country_pair_support.csv','''SELECT iso_code chooser_country,recipient_iso recipient_country,state,
      count(*) opportunities,sum(y) grants,count(DISTINCT chooser) choosers,count(DISTINCT recipient) recipients
      FROM joined WHERE both_iso GROUP BY ALL ORDER BY opportunities DESC''')
    export(db,r/'04_within_chooser_same_different_support.csv','''WITH a AS (SELECT chooser,
      count(*) FILTER(WHERE iso_code=recipient_iso) same_n,count(*) FILTER(WHERE iso_code<>recipient_iso) different_n,
      sum(y) FILTER(WHERE iso_code=recipient_iso) same_grants,sum(y) FILTER(WHERE iso_code<>recipient_iso) different_grants
      FROM joined WHERE both_iso AND board>=-100 GROUP BY chooser)
      SELECT same_n>0 has_same,different_n>0 has_different,count(*) choosers,sum(same_n) same_opportunities,
      sum(different_n) different_opportunities,sum(same_grants) same_grants,sum(different_grants) different_grants FROM a GROUP BY ALL''')
    inventory=records(db,'''WITH u AS (SELECT uid,username,coalesce(p.returned,false) returned,
      coalesce(p.flag_present,false) flag_present,p.iso_code,
      EXISTS(SELECT 1 FROM accounts a WHERE a.chooser=m.uid) chooser_role,
      EXISTS(SELECT 1 FROM panel x WHERE x.recipient=m.uid) recipient_role
      FROM user_map m LEFT JOIN profile_lookup p USING(username))
      SELECT chooser_role,recipient_role,count(*) accounts,count(*) FILTER(WHERE returned) returned_profiles,
      count(*) FILTER(WHERE flag_present) with_any_flag,count(*) FILTER(WHERE iso_code IS NOT NULL) usable_iso,
      count(*) FILTER(WHERE NOT returned) missing_returned_profile FROM u GROUP BY ALL''')
    dump(r/'04_account_union_inventory.json',inventory)
    rate_table(db,r/'05_tv_by_rating_and_state.csv','rating_tier,tv_group,state')
    gradient_table(db,r/'05_tv_board_gradient_by_rating.csv','rating_tier,tv_group')
    rate_table(db,r/'05_tv_rating_volume_sensitivity.csv','rating_tier,volume_bin,tv_group,state',source='''(SELECT *,CASE WHEN n<10 THEN 'under10' WHEN n<50 THEN '10_49' WHEN n<200 THEN '50_199' ELSE '200plus' END volume_bin FROM joined JOIN accounts USING(chooser))''')
    rate_table(db,r/'05_recipient_moderation_descriptive.csv','recipient_mark,state',source="(SELECT *,CASE WHEN recipient_tos IS NULL THEN 'unavailable' WHEN recipient_tos THEN 'engine_or_boost_mark' ELSE 'no_public_mark' END recipient_mark FROM joined)")
    dump(r/'WEIGHTING_STATUS.json',dict(status='NO_POPULATION_WEIGHTS_APPLIED',
      reason='August acquisition came from the older full panel. Current panel alone does not recreate its original eligible reservoir.',
      required='Original complete eligible frame, cell construction, seed/hash ordering, allocation and selected-account ledger; validate before weighting.',
      exhausted_reservoir='If every eligible control in a cell was acquired, control inclusion probability is 1, not 0.',
      zero_support='An eligible cell with no acquired controls has zero control inclusion probability; weights cannot recover it.',
      flag_reporting='Acquisition weights do not correct endogenous flag reporting or closed-profile censoring.'))

def restore_views(db,run):
    db.execute(f'CREATE TEMP VIEW profile_lookup AS SELECT * FROM read_parquet({qs(run/"PRIVATE/profiles.parquet")})')
    db.execute(f'CREATE TEMP VIEW accounts AS SELECT * FROM read_parquet({qs(run/"PRIVATE/accounts.parquet")})')
    db.execute(f'CREATE TEMP VIEW user_map AS SELECT * FROM read_parquet({qs(run/"PRIVATE/user_map.parquet")})')
    db.execute(f'CREATE TEMP VIEW panel AS SELECT * FROM read_parquet({qs(run/"PRIVATE/panel/*.parquet")})')
    attach_views(db)
