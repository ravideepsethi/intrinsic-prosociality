"""Read-only, disk-backed construction from the certified main panel.

API lastMoveAt is an ordering proxy, never a decision-onset or termination time.
Receipt coefficients are predictive for recorded, well-separated main-panel acts.
"""
from pathlib import Path
import json
import numpy as np
from util import *

DAY=86400000
START=1698796800000   # 2023-11-01 UTC
SPLIT=1730419200000   # 2024-11-01 UTC
END=1761955200000     # 2025-11-01 UTC


def source_view(db,paths):
    files='['+','.join(qs(p) for p in paths)+']'
    db.execute(f'''CREATE OR REPLACE VIEW source AS SELECT *,
      outcome_kind_draw::INTEGER AS y,
      CASE WHEN engine_eval_cp_disconnected<=-300 THEN 0
           WHEN engine_eval_cp_disconnected< -100 THEN 1
           WHEN engine_eval_cp_disconnected<=100 THEN 2
           WHEN engine_eval_cp_disconnected<300 THEN 3 ELSE 4 END AS board,
      CASE WHEN ply_count=2 THEN 0 WHEN ply_count<=10 THEN 1
           WHEN ply_count<=40 THEN 2 ELSE 3 END AS stage
      FROM read_parquet({files},hive_partitioning=false)''')


def prepare(db,private,report,identity,dev_accounts,eval_accounts,seed,guard_seconds,expected=None):
    guard=int(guard_seconds*1000)
    audit=records(db,'''SELECT count(*) AS "rows",sum(y)::BIGINT grants,
      count(DISTINCT chooser_user_id) accounts,
      count(*) FILTER(WHERE api_status IS DISTINCT FROM 'timeout' OR five_second_rule_passed IS DISTINCT FROM true
        OR sf100k_nodes_requested IS DISTINCT FROM 100000 OR chooser_user_id IS NULL
        OR disconnected_user_id IS NULL OR chooser_user_id=disconnected_user_id
        OR y IS NULL OR y NOT IN (0,1) OR engine_eval_cp_disconnected IS NULL
        OR ply_count IS NULL OR ply_count<0 OR month<'2023-11' OR month>'2025-10') invalid
      FROM source''')[0]
    require(audit['invalid']==0,'Invalid certified source definitions')
    if expected:
        for k,v in expected.items():require(audit[k]==v,f'Source count mismatch: {k}')
    atomic_json(report/'SOURCE_AUDIT.json',audit)
    accounts=private/'accounts.parquet'
    if not ready(accounts,identity):
        copy_query(db,f'''WITH classified AS (SELECT *,
          api_last_move_at_ms>={START} AND api_last_move_at_ms<{SPLIT} AS in_train,
          api_last_move_at_ms>={SPLIT} AND api_last_move_at_ms<{END} AS in_test FROM source)
          SELECT chooser_user_id AS chooser,
          count(*) FILTER(WHERE month<'2024-11' AND (board>=2 OR board=0))::BIGINT pilot_eligible_n,
          count(*) FILTER(WHERE in_train)::BIGINT n_train,
          count(*) FILTER(WHERE in_test)::BIGINT n_test,
          coalesce(sum(y) FILTER(WHERE in_train),0)::BIGINT g_train,
          count(*) FILTER(WHERE in_train AND board>=2)::BIGINT f_train,
          count(*) FILTER(WHERE in_train AND board=0)::BIGINT l_train,
          coalesce(sum(y) FILTER(WHERE in_train AND board>=2),0)::BIGINT fg_train,
          coalesce(sum(y) FILTER(WHERE in_train AND board=0),0)::BIGINT lg_train,
          count(*) FILTER(WHERE in_train AND ply_count<>2)::BIGINT other_n_train,
          coalesce(sum(y) FILTER(WHERE in_train AND ply_count<>2),0)::BIGINT other_g_train,
          avg(chooser_elo) FILTER(WHERE in_train) AS rating_train,
          arg_min(chooser_username_norm,api_last_move_at_ms) AS username_norm
          FROM classified GROUP BY chooser_user_id''',accounts,identity)
    db.execute(f'CREATE OR REPLACE VIEW accounts AS SELECT * FROM read_parquet({qs(accounts)})')
    cohort=private/'cohort.parquet'
    if not ready(cohort,identity):
        # Reproduce the original pilot eligibility and hash exactly before selecting disjoint accounts.
        pilot_cap=100000 if expected else max(dev_accounts,2)
        copy_query(db,f'''WITH ordered AS (
          SELECT *,row_number() OVER(ORDER BY md5(chooser::VARCHAR || ':20260920'),chooser) AS pilot_rank
          FROM accounts WHERE pilot_eligible_n>0),
          dev AS (SELECT *,'development' AS cohort FROM ordered WHERE pilot_rank<={int(dev_accounts)}),
          evaluation AS (SELECT *,'evaluation' AS cohort FROM ordered WHERE pilot_rank>{pilot_cap}
            ORDER BY md5(chooser::VARCHAR || {qs(':'+str(seed))}),chooser LIMIT {int(eval_accounts)})
          SELECT * FROM dev UNION ALL SELECT * FROM evaluation''',cohort,identity)
    db.execute(f'CREATE OR REPLACE VIEW cohort AS SELECT * FROM read_parquet({qs(cohort)})')
    support=records(db,'''SELECT cohort,count(*) accounts,sum(n_train)::BIGINT train_opportunities,
      sum(n_test)::BIGINT test_opportunities,count(*) FILTER(WHERE n_test=0) no_second_year_opportunity,
      count(*) FILTER(WHERE g_train=0) first_year_zero_granters FROM cohort GROUP BY cohort ORDER BY cohort''')
    require(len(support)==2 and min(r['accounts'] for r in support)>0,'Insufficient distinct accounts for development and evaluation')
    csv_write(report/'cohort_support.csv',support)
    csv_write(report/'census_board_stage.csv',records(db,'''SELECT month,board,stage,count(*) opportunities,
      sum(y)::BIGINT grants,avg(y) grant_rate FROM source GROUP BY ALL ORDER BY month,board,stage'''))
    seq=private/'sequences.parquet'
    if not ready(seq,identity):
        raw=private/'chosen_rows.parquet'
        if not ready(raw,identity):
            log('Staging ordered chooser histories; no binomial aggregation')
            copy_query(db,f'''SELECT s.chooser_user_id AS chooser,s.game_id,s.api_created_at_ms AS start_ms,
              s.api_last_move_at_ms AS t,s.month,s.y,s.board,s.stage,s.ply_count AS ply,
              s.api_speed AS speed,
              CASE WHEN s.chooser_color IN ('white','w') THEN 1 WHEN s.chooser_color IN ('black','b') THEN 0 ELSE -1 END AS color,
              (s.disconnected_elo-s.chooser_elo)::DOUBLE AS gap,s.chooser_elo::DOUBLE AS rating,
              CASE WHEN s.chooser_draw_payoff_v2 IS NULL THEN NULL ELSE greatest(0.,-s.chooser_draw_payoff_v2) END AS loss,
              CASE WHEN s.chooser_draw_payoff_v2 IS NULL THEN NULL ELSE greatest(0.,s.chooser_draw_payoff_v2) END AS gain,
              s.chooser_win_premium_v2 AS premium,s.chooser_pre_rd_v2 AS crd,s.disconnected_pre_rd_v2 AS drd,
              s.chooser_pre_sigma_v2 AS cvol,s.disconnected_pre_sigma_v2 AS dvol,
              s.chooser_clock_last_obs_s AS cclock,s.disconnected_clock_last_obs_s AS dclock,
              c.cohort,c.n_train,c.g_train,c.f_train,c.l_train,c.fg_train,c.lg_train,
              c.other_n_train,c.other_g_train
              FROM source s JOIN cohort c ON s.chooser_user_id=c.chooser''',raw,identity)
        db.execute(f'CREATE OR REPLACE VIEW raw AS SELECT * FROM read_parquet({qs(raw)})')
        db.execute(f'''CREATE OR REPLACE TEMP VIEW timed AS SELECT *,
          coalesce(t>={START} AND t<{END} AND start_ms>0 AND start_ms<=t AND speed<>'correspondence',false) AS time_valid
          FROM raw''')
        db.execute(f'''CREATE OR REPLACE TEMP TABLE timing AS SELECT *,
          (count(*) OVER(PARTITION BY chooser,t)>1 OR
           coalesce(max(t) OVER(PARTITION BY chooser ORDER BY t,game_id ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)+{guard}>=start_ms,false) OR
           coalesce(min(start_ms) OVER(PARTITION BY chooser ORDER BY t,game_id ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING)<=t+{guard},false)) AS overlapping
          FROM timed WHERE time_valid''')
        qa=records(db,'''SELECT (SELECT count(*) FROM raw) selected_rows,
          (SELECT count(*) FROM timed WHERE NOT time_valid) invalid_time_rows,
          count(*) FILTER(WHERE overlapping) overlap_or_guard_rows,
          count(*) FILTER(WHERE NOT overlapping) retained_rows FROM timing''')[0]
        qa.update(guard_seconds=guard_seconds,clock='api_last_move_at_ms; recorded proxy, NOT decision timestamp',
          rule='Exclude both sides of observed overlapping/guarded game intervals; exact decision order remains unverified',
          selection='Timing exclusions may depend on subsequent opportunity arrival; all model comparisons use the same retained sample')
        atomic_json(report/'TIMING_AUDIT.json',qa)
        atomic_json(private/'TIMING_AUDIT_PRIVATE.json',qa)
        db.execute('''CREATE OR REPLACE TEMP TABLE choices AS SELECT *,
          lag(t) OVER(PARTITION BY chooser ORDER BY t,game_id) AS prev_t
          FROM timing WHERE NOT overlapping''')
        rx=private/'recipient_events.parquet'
        if not ready(rx,identity):
            copy_query(db,'''SELECT s.disconnected_user_id AS chooser,s.game_id,
              s.api_last_move_at_ms AS t,s.api_created_at_ms AS start_ms,s.y
              FROM source s SEMI JOIN cohort c ON s.disconnected_user_id=c.chooser
              WHERE s.api_last_move_at_ms>0 AND s.api_created_at_ms>0
                AND s.api_created_at_ms<=s.api_last_move_at_ms''',rx,identity)
        db.execute(f'CREATE OR REPLACE VIEW rx AS SELECT * FROM read_parquet({qs(rx)})')
        # Each recorded recipient event can enter at most one open chooser interval.
        log('Assigning observed receipt opportunities to nonoverlapping chooser intervals')
        copy_query(db,f'''WITH intervals AS (
          SELECT c.chooser,c.game_id,count(r.game_id)::BIGINT receipt_risks,
           count(r.game_id) FILTER(WHERE r.start_ms>c.prev_t+{guard} AND r.t+{guard}<c.start_ms)::BIGINT separated_risks,
           count(r.game_id) FILTER(WHERE r.y=1 AND r.start_ms>c.prev_t+{guard} AND r.t+{guard}<c.start_ms)::BIGINT qualifying_receipts,
           count(r.game_id) FILTER(WHERE r.y=1 AND NOT (r.start_ms>c.prev_t+{guard} AND r.t+{guard}<c.start_ms))::BIGINT ambiguous_receipts
          FROM choices c LEFT JOIN rx r ON r.chooser=c.chooser AND r.t>c.prev_t AND r.t<c.t
            AND r.game_id<>c.game_id GROUP BY c.chooser,c.game_id)
          SELECT c.* EXCLUDE(time_valid,overlapping),
            CASE WHEN c.t<{SPLIT} THEN 0 ELSE 1 END::INTEGER AS period,
            coalesce((c.t-c.prev_t)/{DAY}.0,0.) AS gap_days,
            i.receipt_risks,i.separated_risks,i.qualifying_receipts,i.ambiguous_receipts,
            (i.qualifying_receipts>0)::INTEGER AS received
          FROM choices c JOIN intervals i USING(chooser,game_id) ORDER BY c.chooser,c.t,c.game_id''',seq,identity)
    db.execute(f'CREATE OR REPLACE VIEW seq AS SELECT * FROM read_parquet({qs(seq)})')
    atomic_json(report/'TIMING_AUDIT.json',json.loads((private/'TIMING_AUDIT_PRIVATE.json').read_text()))
    csv_write(report/'sequence_support.csv',records(db,'''SELECT cohort,period,count(*) opportunities,
      count(DISTINCT chooser) accounts,sum(y)::BIGINT grants,sum(received)::BIGINT receipt_intervals,
      sum(qualifying_receipts)::BIGINT qualifying_receipts,sum(ambiguous_receipts)::BIGINT ambiguous_receipts,
      sum(receipt_risks)::BIGINT observed_receipt_opportunities FROM seq GROUP BY ALL ORDER BY cohort,period'''))
    atomic_json(report/'LATENCY_FEASIBILITY.json',dict(status='NOT_TESTABLE_FROM_CURRENT_PANEL',
      last_move_proxy_available=True,action_available_at_timestamp=False,verified_click_timestamp=False,
      result='No latency variable is constructed; no proxy validation or moral-state identification is claimed.',
      needed=['Timestamp when claim/draw first became available','Timestamp and identity of chooser action','Interface/countdown and missingness audit','Joint measurement model']))
    return seq,cohort


def ply2_tables(db,report):
    # Prior history is fixed in year one; outcomes are year two on disjoint evaluation accounts.
    csv_write(report/'ply2_prior_history.csv',records(db,f'''SELECT
      CASE WHEN s.ply_count=2 THEN 'ply_2' WHEN s.ply_count=20 THEN 'ply_20' ELSE 'other' END AS target_ply,
      s.board,
      CASE WHEN c.other_n_train=0 THEN 'no_other_history' WHEN c.other_n_train<5 THEN '1_to_4_other'
           WHEN c.other_n_train<20 THEN '5_to_19_other' ELSE '20_plus_other' END exposure,
      (c.other_g_train=0) AS no_prior_nonply2_grant,
      count(*) opportunities,count(DISTINCT c.chooser) accounts,sum(s.y)::BIGINT grants,
      avg(s.y) grant_rate
      FROM source s JOIN cohort c ON s.chooser_user_id=c.chooser
      WHERE c.cohort='evaluation' AND s.api_last_move_at_ms>={SPLIT} AND s.api_last_move_at_ms<{END} AND s.ply_count IN (2,20)
      GROUP BY ALL ORDER BY target_ply,board,exposure,no_prior_nonply2_grant'''))
    csv_write(report/'ply2_same_year_composition_descriptive.csv',records(db,f'''WITH g AS (
      SELECT chooser_user_id chooser,sum(y)::BIGINT all_grants,
      coalesce(sum(y) FILTER(WHERE ply_count=2),0)::BIGINT ply2_grants,
      coalesce(sum(y) FILTER(WHERE ply_count=20),0)::BIGINT ply20_grants,
      count(*)::BIGINT all_opportunities FROM source WHERE api_last_move_at_ms>={SPLIT} AND api_last_move_at_ms<{END} GROUP BY chooser_user_id)
      SELECT CASE WHEN s.ply_count=2 THEN 'ply_2' ELSE 'ply_20' END AS target_ply,
       count(*) grants,count(*) FILTER(WHERE g.all_grants=CASE WHEN s.ply_count=2 THEN g.ply2_grants ELSE g.ply20_grants END) grants_by_target_only_granters
      FROM source s JOIN g ON s.chooser_user_id=g.chooser JOIN cohort c ON g.chooser=c.chooser
      WHERE c.cohort='evaluation' AND s.api_last_move_at_ms>={SPLIT} AND s.api_last_move_at_ms<{END} AND s.y=1 AND s.ply_count IN (2,20) GROUP BY 1'''))
