"""Read only the certified main panel. All account-level outputs stay PRIVATE."""
from __future__ import annotations
import json
from pathlib import Path
from util import *

EXPECTED=dict(rows=41534331,kind_draws=570091,fair_rows=15207423,fair_kind_draws=419463,choosers=3224173)

def source_view(db, paths):
    files='['+','.join(qs(p) for p in paths)+']'
    db.execute(f'''CREATE OR REPLACE TEMP VIEW src AS SELECT *,
      CASE WHEN month < '2024-11' THEN 0 ELSE 1 END AS period,
      CASE WHEN engine_eval_cp_disconnected<=-300 THEN 0
           WHEN engine_eval_cp_disconnected< -100 THEN 1
           WHEN engine_eval_cp_disconnected<=100 THEN 2
           WHEN engine_eval_cp_disconnected<300 THEN 3 ELSE 4 END AS board,
      CASE WHEN ply_count<=4 THEN 0 WHEN ply_count<=6 THEN 1 WHEN ply_count<=8 THEN 2
           WHEN ply_count<=10 THEN 3 WHEN ply_count<=20 THEN 4 WHEN ply_count<=40 THEN 5
           WHEN ply_count<=80 THEN 6 ELSE 7 END AS stage,
      outcome_kind_draw::INTEGER AS y
      FROM read_parquet({files},hive_partitioning=false)''')

def audit_source(db, report, expected=EXPECTED):
    log('Checking census counts and required source semantics')
    result=records(db,'''SELECT count(*) AS rows,sum(y)::BIGINT kind_draws,
       count(*) FILTER(WHERE engine_eval_cp_disconnected>=-100) fair_rows,
       sum(y) FILTER(WHERE engine_eval_cp_disconnected>=-100)::BIGINT fair_kind_draws,
       count(DISTINCT chooser_user_id) choosers,
       count(*) FILTER(WHERE chooser_user_id IS NULL OR chooser_user_id<0 OR y IS NULL
          OR y NOT IN (0,1) OR engine_eval_cp_disconnected IS NULL OR ply_count IS NULL OR ply_count<0
          OR api_status IS DISTINCT FROM 'timeout' OR five_second_rule_passed IS DISTINCT FROM true
          OR sf100k_nodes_requested IS DISTINCT FROM 100000
          OR fair_competitive IS DISTINCT FROM (engine_eval_cp_disconnected>=-100)
          OR month IS NULL OR month<'2023-11' OR month>'2025-10') invalid_rows
       FROM src''')[0]
    for k,v in expected.items(): require(result[k]==v, f'Certified count mismatch {k}: {result[k]} != {v}')
    require(result['invalid_rows']==0,'Invalid required rows; no silent dropping')
    monthly=records(db,'SELECT month,count(*) n,sum(y)::BIGINT grants FROM src GROUP BY month ORDER BY month')
    require([r['month'] for r in monthly]==MONTHS,'Incomplete 24-month window')
    csv_write(report/'monthly_counts.csv',monthly); atomic_json(report/'SOURCE_AUDIT.json',result)
    return result

def support_census(db, private, report, identity):
    cells=private/'account_year_cells.parquet'
    if not ready(cells,identity):
        log('Aggregating census account × year × 40 board/stage cells')
        copy_query(db,'''SELECT chooser_user_id AS chooser,period,board,stage,
          count(*)::BIGINT n,sum(y)::BIGINT g FROM src GROUP BY ALL''',cells,identity)
    db.execute(f'CREATE OR REPLACE TEMP VIEW cells AS SELECT * FROM read_parquet({qs(cells)})')
    certified=json.loads((report/'SOURCE_AUDIT.json').read_text())
    totals=records(db,'SELECT sum(n)::BIGINT n,sum(g)::BIGINT g FROM cells')[0]
    require(totals['n']==certified['rows'] and totals['g']==certified['kind_draws'],'Census aggregation failed to conserve observations/outcomes')
    accounts=private/'account_support.parquet'
    if not ready(accounts,identity):
        copy_query(db,'''SELECT chooser,
          sum(n) FILTER(WHERE period=0)::BIGINT n_train,
          coalesce(sum(n) FILTER(WHERE period=1),0)::BIGINT n_test,
          coalesce(sum(g) FILTER(WHERE period=0),0)::BIGINT g_train,
          coalesce(sum(n) FILTER(WHERE period=0 AND board>=2),0)::BIGINT f_train,
          coalesce(sum(n) FILTER(WHERE period=0 AND board=0),0)::BIGINT l_train,
          coalesce(sum(g) FILTER(WHERE period=0 AND board>=2),0)::BIGINT fg_train,
          coalesce(sum(g) FILTER(WHERE period=0 AND board=0),0)::BIGINT lg_train,
          coalesce(sum(n) FILTER(WHERE period=1 AND board>=2),0)::BIGINT f_test,
          coalesce(sum(n) FILTER(WHERE period=1 AND board=0),0)::BIGINT l_test,
          count(*) FILTER(WHERE period=0)::INTEGER cells_train
          FROM cells GROUP BY chooser''',accounts,identity)
    db.execute(f'CREATE OR REPLACE TEMP VIEW accounts AS SELECT * FROM read_parquet({qs(accounts)})')
    require(db.execute('SELECT count(*) FROM accounts').fetchone()[0]==certified['choosers'],'Account aggregation failed to conserve chooser count')
    rows=[]
    for threshold in [1,3,8,20,50,100]:
        r=records(db,f'''SELECT count(*) accounts,coalesce(sum(n_train),0)::BIGINT train_opportunities,
          count(*) FILTER(WHERE g_train=0) zero_grant_histories,
          count(*) FILTER(WHERE f_train>0 AND l_train>0) both_regions,
          count(*) FILTER(WHERE n_test>0) reached_year_two,
          count(*) FILTER(WHERE f_test>0 AND l_test>0) both_regions_year_two
          FROM accounts WHERE n_train>={threshold}''')[0]
        rows.append(dict(min_train_opportunities=threshold,**r))
    csv_write(report/'support_by_history_length.csv',rows)
    rows=[]
    for threshold in [1,2,3,5,8,10,20]:
        r=records(db,f'''SELECT count(*) accounts,count(*) FILTER(WHERE g_train=0) zero_grant_histories,
           count(*) FILTER(WHERE n_test>0) reached_year_two,
           count(*) FILTER(WHERE f_test>0 AND l_test>0) both_regions_year_two
           FROM accounts WHERE f_train>={threshold} AND l_train>={threshold}''')[0]
        rows.append(dict(min_train_opportunities_in_each_region=threshold,**r))
    csv_write(report/'support_in_both_regions.csv',rows)
    csv_write(report/'board_stage_year_counts.csv',records(db,'''SELECT period,board,stage,
      count(*) accounts,sum(n)::BIGINT opportunities,sum(g)::BIGINT grants,
      100.*sum(g)/sum(n) kind_rate_percent FROM cells GROUP BY ALL ORDER BY period,board,stage'''))
    csv_write(report/'account_cohorts.csv',records(db,'''SELECT
      CASE WHEN n_train IS NULL THEN 'first_seen_year_two'
           WHEN n_test=0 THEN 'year_one_only' ELSE 'both_years' END cohort,
      count(*) accounts FROM accounts GROUP BY 1 ORDER BY 1'''))
    return cells,accounts

def bin_sql(expr, edges, missing=-1):
    return f'CASE WHEN {expr} IS NULL OR NOT isfinite({expr}) THEN {missing} '+ ' '.join(
      f'WHEN {expr}<{v} THEN {j}' for j,v in enumerate(edges))+f' ELSE {len(edges)} END'

def pilot_sample(db, private, report, identity, sample_accounts, seed):
    selected=private/'pilot_accounts.parquet'
    if not ready(selected,identity):
        copy_query(db,f'''SELECT chooser FROM accounts WHERE f_train+l_train>0
          ORDER BY md5(chooser::VARCHAR || {qs(':'+str(seed))}),chooser LIMIT {int(sample_accounts)}''',selected,identity)
    destination=private/'pilot_counts.parquet'
    if not ready(destination,identity):
        features={
         'gap':bin_sql('(disconnected_elo-chooser_elo)::DOUBLE',[-400,-200,-100,-50,0,1,51,101,201,401]),
         'rating':bin_sql('chooser_elo::DOUBLE',[1200,1600,2000,2400]),
         'crd':bin_sql('chooser_pre_rd_v2',[40,60,100,200]),
         'drd':bin_sql('disconnected_pre_rd_v2',[40,60,100,200]),
         'premium':bin_sql('chooser_win_premium_v2',[6,10,20,40]),
         'loss':bin_sql('(CASE WHEN chooser_draw_payoff_v2 IS NULL THEN NULL ELSE greatest(0.,-chooser_draw_payoff_v2) END)',[0.000001,5,10,20]),
         'cclock':bin_sql('chooser_clock_last_obs_s',[0,10,30,60,180,600]),
         'dclock':bin_sql('disconnected_clock_last_obs_s',[0,10,30,60,180,600]),
         'cvol':bin_sql('chooser_pre_sigma_v2',[0.04,0.06,0.08]),
         'dvol':bin_sql('disconnected_pre_sigma_v2',[0.04,0.06,0.08])}
        query=f'''WITH selected AS (SELECT * FROM read_parquet({qs(selected)})), slim AS (
          SELECT s.chooser_user_id AS chooser,s.period,(s.board>=2)::INTEGER AS competitive,
          s.board*8+s.stage AS cell,coalesce(api_speed,'__MISSING__') AS speed,
          substr(month,6,2)::INTEGER AS season,
          CASE WHEN chooser_color IN ('white','w') THEN 1 WHEN chooser_color IN ('black','b') THEN 0 ELSE -1 END color,
          {','.join(expr+' AS '+name for name,expr in features.items())},s.y
          FROM src s INNER JOIN selected a ON a.chooser=s.chooser_user_id WHERE s.board!=1)
          SELECT * EXCLUDE(y),count(*)::BIGINT n,sum(y)::BIGINT g FROM slim GROUP BY ALL
          ORDER BY chooser,period,cell'''
        log(f'Staging complete histories for up to {sample_accounts:,} first-year accounts; selection ignores year two and outcomes')
        copy_query(db,query,destination,identity)
    r=records(db,f'''SELECT period,count(DISTINCT chooser) accounts,sum(n)::BIGINT opportunities,
      sum(g)::BIGINT grants,count(*) grouped_rows FROM read_parquet({qs(destination)}) GROUP BY period ORDER BY period''')
    expected=records(db,f'''SELECT s.period,count(*)::BIGINT opportunities,sum(s.y)::BIGINT grants
      FROM src s INNER JOIN read_parquet({qs(selected)}) a ON a.chooser=s.chooser_user_id
      WHERE s.board!=1 GROUP BY s.period ORDER BY s.period''')
    require([(x['period'],x['opportunities'],x['grants']) for x in r]==
            [(x['period'],x['opportunities'],x['grants']) for x in expected],
            'Grouped pilot counts do not conserve raw selected opportunities/outcomes')
    csv_write(report/'pilot_sample_counts.csv',r)
    return destination
