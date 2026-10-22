"""Unchanged preparation function from the validated within-chooser K runner.
The pooled runner requests no old separate contexts. Full-source K cutpoints
and the canonical source checks are intentionally retained.
"""
import os
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from fe_engine import MONTHS,SPEEDS,context_mask
from source import pool_wave1_common as common
from pooled_utils import log,qs,require,records,checkpoint_ok,certify_checkpoint

def prepare_data(db,paths,private,identity,expected,context_keys):
    """One sorted slim copy; context Parquets retain complete account ordering."""
    private.mkdir(parents=True,exist_ok=True)
    base=private/'sorted_base.parquet';meta=private/'PREPARATION.json'
    if checkpoint_ok(base,identity):
        preparation=common.load_json(meta);log('REUSED authenticated sorted base')
    else:
        files='['+','.join(qs(p) for p in paths)+']'
        month_case='CASE month '+' '.join(f'WHEN {qs(m)} THEN {i}' for i,m in enumerate(MONTHS))+' ELSE -1 END'
        speed_case='CASE api_speed '+' '.join(f'WHEN {qs(m)} THEN {i}' for i,m in enumerate(SPEEDS))+' ELSE -1 END'
        db.execute(f'''CREATE OR REPLACE TEMP VIEW source AS SELECT
          chooser_user_id::BIGINT AS chooser, outcome_kind_draw::INTEGER AS y,
          (disconnected_elo::DOUBLE-chooser_elo::DOUBLE) AS gap,
          chooser_draw_payoff_v2::DOUBLE AS payoff, 2*chooser_win_premium_v2 AS K,
          chooser_win_payoff_v2-chooser_draw_payoff_v2-chooser_win_premium_v2 AS identity_error,
          engine_eval_cp_disconnected::DOUBLE AS board, ply_count::DOUBLE AS ply,
          chooser_pre_rd_v2 AS crd, disconnected_pre_rd_v2 AS drd,
          chooser_pre_sigma_v2 AS cvol, disconnected_pre_sigma_v2 AS dvol,
          ({month_case})::SMALLINT AS month, ({speed_case})::SMALLINT AS speed
          FROM read_parquet({files},hive_partitioning=false)''')
        numerics=['gap','payoff','K','board','ply','crd','drd','cvol','dvol','identity_error']
        invalid=' OR '.join([f'{x} IS NULL OR NOT isfinite({x})' for x in numerics]+
          ['chooser IS NULL','chooser<0','y IS NULL','y NOT IN(0,1)','month<0','speed<0',
           'K<=0','ply<0','crd<=0','drd<=0','cvol<=0','dvol<=0',
           'abs(identity_error)>1e-7*greatest(1.,K)',
           '(0.5-payoff/K)<-1e-7','(0.5-payoff/K)>1+1e-7'])
        counts=records(db,f'''SELECT count(*) AS "rows",sum(y)::BIGINT kind_draws,
          count(*) FILTER(WHERE board>=-100) fair_rows,
          sum(y) FILTER(WHERE board>=-100)::BIGINT fair_kind_draws,
          count(DISTINCT chooser) choosers, count(*) FILTER(WHERE {invalid}) invalid_rows,
          min(K) min_K,max(K) max_K,max(abs(identity_error)) max_identity_error FROM source''')[0]
        require(counts['invalid_rows']==0,f'Invalid required values; no silent row dropping: {counts}')
        for k,v in expected.items():require(counts[k]==v,f'Current-sample count mismatch: {k}: {counts[k]} vs {v}')
        quantiles={}
        for key,number in [('k20',20),('k50',50)]:
            probs='['+','.join(str(i/number) for i in range(1,number))+']'
            values=db.execute(f'SELECT quantile_cont(K,{probs}) FROM source').fetchone()[0]
            quantiles[key]=sorted(set(float(x) for x in values if x<counts['max_K']))
        log(f'SOURCE_OK rows={counts["rows"]:,}; sorting all rows by chooser (disk spill allowed)')
        temporary=base.with_suffix('.partial.parquet')
        temporary.unlink(missing_ok=True)
        db.execute('SET preserve_insertion_order=true')
        db.execute(f'''COPY (SELECT * EXCLUDE(identity_error) FROM source ORDER BY chooser,month,gap,payoff,y)
          TO {qs(temporary)} (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 65536)''')
        os.replace(temporary,base)
        preparation=dict(run_identity=identity,counts=counts,K_cutpoints=quantiles,
            quantile_scope='all frozen current-sample opportunities, before singleton exclusion',
            ties='duplicate cutpoints collapsed; equal K is never split by rank',
            K_definition='2 * chooser_win_premium_v2',
            gap_definition='disconnected_elo - chooser_elo; recomputed from displayed ratings',
            expected_score_check='0 <= 0.5 - chooser_draw_payoff_v2 / K <= 1')
        common.atomic_json(meta,preparation);certify_checkpoint(base,identity,rows=counts['rows'])
    todo=[key for key in context_keys if not checkpoint_ok(private/(key+'.parquet'),identity)]
    if todo:
        writers={};totals={key:0 for key in todo};blocks=0
        try:
            for batch in pq.ParquetFile(base).iter_batches(batch_size=131072,use_threads=False):
                table=pa.Table.from_batches([batch]);d=table['board'].to_numpy()
                for key in todo:
                    subset=table.filter(pa.array(context_mask(d,key)))
                    if key not in writers:
                        writers[key]=pq.ParquetWriter(private/(key+'.partial.parquet'),table.schema,compression='zstd')
                    if len(subset):writers[key].write_table(subset);totals[key]+=len(subset)
                blocks+=1
                if blocks%30==0:log(f'CONTEXT_STAGING rows_read≈{blocks*131072:,}')
        finally:
            for writer in writers.values():writer.close()
        for key in todo:
            p=private/(key+'.parquet');os.replace(private/(key+'.partial.parquet'),p)
            certify_checkpoint(p,identity,rows=totals[key]);log(f'CONTEXT_READY {key} rows={totals[key]:,}')
    # Support of the K approximation, including heaped floor and wide tail bins.
    bins=[]
    for key,edges in preparation['K_cutpoints'].items():
        expression='CASE '+' '.join(f'WHEN K<={repr(x)} THEN {i}' for i,x in enumerate(edges))+f' ELSE {len(edges)} END'
        rows=records(db,f'''SELECT {expression} AS bin,count(*) n,min(K) min_K,max(K) max_K,avg(K) mean_K
          FROM read_parquet({qs(base)}) GROUP BY bin ORDER BY bin''')
        bins.extend(dict(scheme=key,**r) for r in rows)
    preparation['K_bin_support']=bins
    return preparation
