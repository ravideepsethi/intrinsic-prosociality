"""Authenticate the existing sample; stage a slim, sorted competitive panel."""
from __future__ import annotations
import os
from pathlib import Path
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from source import pool_wave1_common as common
from pooled_utils import qs,require,log,records,checkpoint_ok,certify_checkpoint,write_csv
from milestone_model import MONTHS,SPEEDS

EXPECTED=dict(rows=41534331,kind_draws=570091,fair_rows=15207423,fair_kind_draws=419463,choosers=3224173)
COLUMNS=['chooser','y','rating','gap','payoff','win','K','board','ply','crd','drd','cvol','dvol',
         'cclock','dclock','base_s','increment_s','white','month','speed']


def empty_frame():
    return {k:np.array([],dtype=np.int64 if k in ('chooser','y','month','speed') else float) for k in COLUMNS}


def stage_base(db,paths,private,identity,expected=EXPECTED):
    private.mkdir(parents=True,exist_ok=True)
    base=private/'competitive_sorted.parquet';auditpath=private/'SOURCE_AUDIT.json'
    if checkpoint_ok(base,identity):
        audit=common.load_json(auditpath)
        require(audit['identity']==identity,'Cached source audit identity mismatch')
        for key,value in expected.items():require(audit['counts'][key]==value,'Cached count mismatch: '+key)
        log('REUSED authenticated competitive cache');return base,audit
    files='['+','.join(qs(p) for p in paths)+']'
    mc='CASE month '+' '.join(f'WHEN {qs(x)} THEN {i}' for i,x in enumerate(MONTHS))+' ELSE -1 END'
    sc='CASE api_speed '+' '.join(f'WHEN {qs(x)} THEN {i}' for i,x in enumerate(SPEEDS))+' ELSE -1 END'
    db.execute(f'''CREATE OR REPLACE TEMP VIEW milestone_source AS SELECT
        chooser_user_id::BIGINT chooser,outcome_kind_draw::INTEGER y,chooser_elo::DOUBLE rating,
        (disconnected_elo::DOUBLE-chooser_elo::DOUBLE) gap,
        chooser_draw_payoff_v2::DOUBLE payoff,chooser_win_payoff_v2::DOUBLE win,
        2*chooser_win_premium_v2::DOUBLE K,
        (chooser_win_payoff_v2-chooser_draw_payoff_v2-chooser_win_premium_v2)::DOUBLE identity_error,
        engine_eval_cp_disconnected::DOUBLE board,ply_count::DOUBLE ply,
        chooser_pre_rd_v2::DOUBLE crd,disconnected_pre_rd_v2::DOUBLE drd,
        chooser_pre_sigma_v2::DOUBLE cvol,disconnected_pre_sigma_v2::DOUBLE dvol,
        chooser_clock_last_obs_s::DOUBLE cclock,disconnected_clock_last_obs_s::DOUBLE dclock,
        tc_base_s::DOUBLE base_s,tc_inc_s::DOUBLE increment_s,
        CASE WHEN lower(chooser_color) IN ('white','w') THEN 1.
             WHEN lower(chooser_color) IN ('black','b') THEN 0. ELSE NULL END white,
        ({mc})::SMALLINT AS month,({sc})::SMALLINT AS speed,
        api_status,five_second_rule_passed,sf100k_nodes_requested,fair_competitive
        FROM read_parquet({files},hive_partitioning=false)''')
    numerics=['rating','gap','payoff','win','K','board','ply','crd','drd','cvol','dvol','identity_error','white']
    bad=' OR '.join([f'{x} IS NULL OR NOT isfinite({x})' for x in numerics]+[
        'chooser IS NULL','chooser<0','y IS NULL','y NOT IN (0,1)','month<0','speed<0',
        'K<=0','win < -1e-7','ply<0','crd<=0','drd<=0','cvol<=0','dvol<=0',
        'rating != floor(rating)','abs(identity_error)>1e-7*greatest(1.,K)',
        '(0.5-payoff/K)<-1e-7','(0.5-payoff/K)>1+1e-7'])
    log('AUDIT: scanning source counts, field validity, and payoff identities')
    counts=records(db,f'''SELECT count(*) AS "rows",sum(y)::BIGINT kind_draws,
        count(*) FILTER(WHERE board>=-100) fair_rows,
        sum(y) FILTER(WHERE board>=-100)::BIGINT fair_kind_draws,
        count(DISTINCT chooser) choosers,count(*) FILTER(WHERE {bad}) invalid_required_rows,
        count(*) FILTER(WHERE api_status IS DISTINCT FROM 'timeout') invalid_status_rows,
        count(*) FILTER(WHERE five_second_rule_passed IS DISTINCT FROM true) invalid_clock_rule_rows,
        count(*) FILTER(WHERE sf100k_nodes_requested IS DISTINCT FROM 100000) invalid_engine_rows,
        count(*) FILTER(WHERE fair_competitive IS DISTINCT FROM (board>=-100)) invalid_fair_flag_rows,
        count(*) FILTER(WHERE cclock IS NULL OR cclock<0 OR NOT isfinite(cclock)) missing_chooser_clock,
        count(*) FILTER(WHERE dclock IS NULL OR dclock<0 OR NOT isfinite(dclock)) missing_opponent_clock,
        min(rating) min_rating,max(rating) max_rating,max(abs(identity_error)) max_payoff_identity_error
        FROM milestone_source''')[0]
    for key,value in expected.items():require(counts[key]==value,f'Source mismatch {key}: {counts[key]} vs {value}')
    for key in ('invalid_required_rows','invalid_status_rows','invalid_clock_rule_rows','invalid_engine_rows','invalid_fair_flag_rows'):
        require(counts[key]==0,f'No silent dropping: {key}={counts[key]}')
    monthly=records(db,'''SELECT month,count(*) AS "rows",sum(y)::BIGINT grants,
        count(*) FILTER(WHERE board>=-100) fair_rows FROM milestone_source GROUP BY month ORDER BY month''')
    require([r['month'] for r in monthly]==list(range(24)),'Missing or unexpected month')
    log(f'SOURCE_OK {counts["rows"]:,} rows; staging {counts["fair_rows"]:,} competitive rows sorted by chooser')
    partial=base.with_suffix('.partial.parquet');partial.unlink(missing_ok=True)
    db.execute('SET preserve_insertion_order=true')
    db.execute(f'''COPY (SELECT {','.join(COLUMNS)} FROM milestone_source WHERE board>=-100
        ORDER BY chooser,month,rating,payoff,y) TO {qs(partial)}
        (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 65536)''')
    os.replace(partial,base)
    audit=dict(identity=identity,counts=counts,monthly=monthly,
        source_uniqueness='Inherited from the SHA256-authenticated certified monthly sample; no redefinition of source or rematch filters.',
        primary_population='Competitive board: engine_eval_cp_disconnected >= -100',
        rating_counterfactual='Displayed pre-game rating + reconstructed v2 payoff; not exact recovered display')
    common.atomic_json(auditpath,audit);certify_checkpoint(base,identity,rows=counts['fair_rows'])
    return base,audit


def stage_shards(base,private,identity,workers,expected_rows):
    paths=[private/f'chooser_shard_{j:02d}.parquet' for j in range(workers)]
    done=[checkpoint_ok(p,identity) for p in paths]
    if all(done):return paths
    writers={};totals=[0]*workers
    try:
        for block,batch in enumerate(pq.ParquetFile(base).iter_batches(batch_size=131072,use_threads=False)):
            table=pa.Table.from_batches([batch]);ids=table['chooser'].to_numpy()
            for j,p in enumerate(paths):
                if done[j]:continue
                if j not in writers:writers[j]=pq.ParquetWriter(p.with_suffix('.partial.parquet'),table.schema,compression='zstd')
                part=table.filter(pa.array(ids%workers==j))
                if len(part):writers[j].write_table(part);totals[j]+=len(part)
            if block and block%25==0:log(f'SHARDING read approximately {block*131072:,} competitive rows')
    finally:
        for writer in writers.values():writer.close()
    for j,p in enumerate(paths):
        if done[j]:totals[j]=common.load_json(p.with_suffix('.parquet.json'))['rows']
        else:
            os.replace(p.with_suffix('.partial.parquet'),p)
            certify_checkpoint(p,identity,rows=totals[j],partition=f'chooser_id modulo {workers} = {j}')
    require(sum(totals)==expected_rows,'Shard rows do not conserve source')
    return paths


def write_raw_tables(db,base,report):
    db.execute(f'''CREATE OR REPLACE TEMP VIEW raw_milestones AS WITH a AS (
       SELECT *,100*floor((rating+50)/100) AS target FROM read_parquet({qs(base)})
       ) SELECT *,rating-target AS d,
       (rating>=target AND rating+payoff<target AND rating+win>=target)::INTEGER AS lc,
       (rating<target AND rating+payoff<target AND rating+win>=target)::INTEGER AS gc
       FROM a WHERE target BETWEEN 500 AND 3000 AND abs(rating-target)<=25''')
    rows=records(db,'''SELECT target::INTEGER AS threshold,d::INTEGER AS distance, count(*) AS n,
         sum(y)::BIGINT grants,100*avg(y) kind_rate_percent,sum(lc)::BIGINT loss_crossings,
         sum(gc)::BIGINT gain_crossings,avg(crd) mean_chooser_RD,avg(drd) mean_opponent_RD,
         avg(ply) mean_ply,avg(payoff) mean_draw_payoff,avg(gap) mean_rating_gap
         FROM raw_milestones GROUP BY target,d ORDER BY target,d''')
    write_csv(report/'raw_by_threshold_and_distance.csv',rows)
    pooled=records(db,'''SELECT d::INTEGER AS distance,count(*) AS n,sum(y)::BIGINT grants,
         100*avg(y) kind_rate_percent,sum(lc)::BIGINT loss_crossings,sum(gc)::BIGINT gain_crossings
         FROM raw_milestones GROUP BY d ORDER BY d''')
    write_csv(report/'raw_pooled_distance.csv',pooled)
    crossing=records(db,'''SELECT target::INTEGER AS threshold,lc AS loss_crossing,gc AS gain_crossing,
         count(*) n,sum(y)::BIGINT grants,100*avg(y) kind_rate_percent,
         avg(payoff) mean_draw_payoff,avg(K) mean_K,avg(crd) mean_chooser_RD,avg(drd) mean_opponent_RD
         FROM raw_milestones GROUP BY target,lc,gc ORDER BY target,lc,gc''')
    write_csv(report/'raw_crossing_cells.csv',crossing)
