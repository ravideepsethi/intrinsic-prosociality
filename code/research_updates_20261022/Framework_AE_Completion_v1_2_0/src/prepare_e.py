#!/usr/bin/env python3
"""Attach paper IV pre-exposure controls, score normalization, cell/date/hour effects.

Requires 2,682,330-row verified spaced90 cohort with PG/PC/NC already attached.
No after-assignment board states or clocks are controls. No API or PGN work.
"""
import argparse,json,traceback
from pathlib import Path

def lit(s):return "'"+str(s).replace("'","''")+"'"
def log(s):print('[E IV preparation]',s,flush=True)

CTRL=['recipient_rating','rating_gap','rating_gap_sq','abs_rating_gap','hist_expected','log_hist_decisions',
      'log_hist_counterparts','any_fair_90','log_fair_90','ever_kind_90','competitive_rate_90',
      'log_disconnect_90','log_receipt_90','log_claim_90','log_pre_games_30d']

def main():
 ap=argparse.ArgumentParser()
 ap.add_argument('--grouped',required=True)
 ap.add_argument('--out',required=True)
 ap.add_argument('--workers',type=int,default=10)
 ap.add_argument('--memory-gb',type=int,default=11)
 a=ap.parse_args()
 import duckdb
 o=Path(a.out);o.mkdir(parents=True,exist_ok=False);(o/'public').mkdir();(o/'private').mkdir()
 c=duckdb.connect(':memory:');c.execute(f'SET threads={a.workers}');c.execute('SET memory_limit='+lit(str(a.memory_gb)+'GB'))
 try:
  sp=Path(a.grouped)
  if not sp.is_file():raise FileNotFoundError(sp)
  cols={r[0] for r in c.execute('DESCRIBE SELECT * FROM read_parquet('+lit(sp)+')').fetchall()}
  required={'row_id','recipient_id','opponent_id','game_id','archive_start_ms',
     'received','y','n_7d','adjusted_7d','expected_7d','counterparts_7d',
     'recipient_rating','opponent_rating','tc_base_s','tc_inc_s','month_code',
     'fair_90','kind_90','disconnect_90','receipt_90','claim_90','pre_games_30d',
     'experience_group'}
  if required-cols:raise ValueError('Missing frozen IV input fields: '+str(sorted(required-cols)))
  n,ids,recs=c.execute(f"SELECT COUNT(*),COUNT(DISTINCT row_id),COUNT(DISTINCT recipient_id) FROM read_parquet({lit(sp)})").fetchone()
  if (n,ids,recs)!=(2682330,2682330,1625389):
   raise ValueError(f'IV cohort mismatch n/row IDs/recipients={(n,ids,recs)}; required 2682330/2682330/1625389')
  if c.execute('SELECT COUNT(*) FROM read_parquet('+lit(sp)+') WHERE experience_group NOT IN (\'PG\',\'PC\',\'NC\')').fetchone()[0]:
   raise ValueError('E experience groups corrupted')
  # Build original 100-point bin of pair mean ratings, exact recorded time control and month.
  # UTC date and hour-of-week are from game-start timestamp, with no exposure outcomes used.
  # The original score is historical decision residuals; its reference SD is 0.0594.
  query=f"""SELECT
    row_id,recipient_id,opponent_id,game_id,archive_start_ms,experience_group,
    CAST(received AS INTEGER) AS received,CAST(y AS INTEGER) AS y,
    (CAST(adjusted_7d AS DOUBLE)/0.0594) AS score_ref,
    CONCAT(CAST(month_code AS VARCHAR),'|',CAST(tc_base_s AS VARCHAR),'|',
      CAST(tc_inc_s AS VARCHAR),'|',CAST(FLOOR((recipient_rating+opponent_rating)/200.0) AS VARCHAR)) AS assignment_cell,
    CAST(DATE_TRUNC('day',to_timestamp(archive_start_ms/1000.0)) AS DATE) AS exposure_date_utc,
    CAST(((EXTRACT(ISODOW FROM to_timestamp(archive_start_ms/1000.0))-1)*24+
                EXTRACT(HOUR FROM to_timestamp(archive_start_ms/1000.0))) AS INTEGER) AS exposure_hour_of_week,
    CAST(recipient_rating AS DOUBLE) AS recipient_rating,
    CAST(opponent_rating-recipient_rating AS DOUBLE) AS rating_gap,
    POW(CAST(opponent_rating-recipient_rating AS DOUBLE),2) AS rating_gap_sq,
    ABS(CAST(opponent_rating-recipient_rating AS DOUBLE)) AS abs_rating_gap,
    CAST(expected_7d AS DOUBLE) AS hist_expected,
    LN(1+CAST(n_7d AS DOUBLE)) AS log_hist_decisions,
    LN(1+CAST(counterparts_7d AS DOUBLE)) AS log_hist_counterparts,
    CAST(fair_90>0 AS DOUBLE) AS any_fair_90,
    LN(1+CAST(fair_90 AS DOUBLE)) AS log_fair_90,
    CAST(kind_90>0 AS DOUBLE) AS ever_kind_90,
    CASE WHEN fair_90>0 THEN CAST(kind_90 AS DOUBLE)/fair_90 ELSE 0.0 END AS competitive_rate_90,
    LN(1+CAST(disconnect_90 AS DOUBLE)) AS log_disconnect_90,
    LN(1+CAST(receipt_90 AS DOUBLE)) AS log_receipt_90,
    LN(1+CAST(claim_90 AS DOUBLE)) AS log_claim_90,
    LN(1+CAST(pre_games_30d AS DOUBLE)) AS log_pre_games_30d
   FROM read_parquet({lit(sp)})"""
  dest=o/'private'/'IV_E_MODEL_PRIVATE.parquet'
  c.execute(f'COPY ({query}) TO {lit(dest)} (FORMAT PARQUET,COMPRESSION ZSTD)')
  log('Prepared cached IV model rows (private)')
  checks=c.execute(f"""SELECT COUNT(*),COUNT(DISTINCT assignment_cell),COUNT(DISTINCT recipient_id),
    SUM(received),AVG(CAST(y AS DOUBLE)),MIN(score_ref),MAX(score_ref),
    COUNT(*) FILTER(WHERE score_ref IS NULL OR NOT isfinite(score_ref)),
    COUNT(*) FILTER(WHERE received NOT IN (0,1) OR y NOT IN (0,1)),
    COUNT(*) FILTER(WHERE exposure_date_utc IS NULL OR exposure_hour_of_week IS NULL)
    FROM read_parquet({lit(dest)})""").fetchone()
  n,cells,recipients,receipts,mean_y,scmin,scmax,miss_score,bad_binary,bad_time=checks
  grp=c.execute(f"""SELECT experience_group,COUNT(*) exposures,SUM(received) AS receipts,
    SUM(y) AS later_grants FROM read_parquet({lit(dest)}) GROUP BY 1 ORDER BY 1""").fetchdf()
  grp.to_csv(o/'public'/'tabE_groups.csv',index=False)
  audit=dict(n=int(n),assignment_cells=int(cells),recipients=int(recipients),receipts=int(receipts),
    later_grant_rate_percent=float(mean_y*100),score_min=float(scmin),score_max=float(scmax),
    missing_score=int(miss_score),invalid_binary=int(bad_binary),invalid_time=int(bad_time),
    score_formula='adjusted_7d / 0.0594; pending original pooled first-stage calibration',
    cell_formula='month_code x (tc_base_s, tc_inc_s) x floor(mean_rating/100)',controls=CTRL)
  (o/'public'/'E_iv_preflight.json').write_text(json.dumps(audit,indent=2)+'\n')
  log(f'IV cells {cells}; recipients {recipients}; mean later grant {mean_y:.5f}; historical score observed ({scmin:.2f},{scmax:.2f})')
  if n!=2682330 or recipients!=1625389 or cells!=4324 or miss_score or bad_binary or bad_time:
   raise ValueError('Paper IV exposure or assignment cell preflight failed; do not fit heterogeneity')
  if (grp.exposure_group if 'exposure_group' in grp else grp.experience_group).nunique()!=3:
   raise ValueError('No support for all three prior groups (check identifier semantics)')
  if min(grp.exposures)<1000:
   raise ValueError('Suspiciously few prior-experience exposures; possible numeric-ID versus username mismatch')
  if not(0.01<mean_y<0.03):raise ValueError('IV later-granting outcome mean not as published')
  (o/'public'/'_PREP_OK.json').write_text(json.dumps({'status':'EXACT_2682330_IV_EXPOSURES; AWAIT_POOLED_REPRODUCTION',
      'controls':CTRL,'no_API':True},indent=2)+'\n')
 except Exception:
  (o/'private'/'FAILED.txt').write_text(traceback.format_exc());raise
 finally:c.close()
if __name__=='__main__':main()
