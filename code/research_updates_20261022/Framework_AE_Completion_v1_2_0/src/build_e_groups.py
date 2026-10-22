#!/usr/bin/env python3
"""Attach mutually exclusive BEFORE-exposure experience groups to existing IV/matched cohorts.

No outcome estimation or change to instrument construction. Cached, historical
main choices and pre-existing receipt-exposure files only; zero API requests.
"""
import argparse,datetime as dt,json,sys,traceback,hashlib
from pathlib import Path
import duckdb

def lit(x):return "'"+str(x).replace("'","''")+"'"
def ident(x):return '"'+str(x).replace('"','""')+'"'
def source(path):
 p=Path(path)
 if not p.exists():raise FileNotFoundError(p)
 if p.is_dir():return 'read_parquet('+lit(str(p/'**'/'*.parquet'))+', union_by_name=true, hive_partitioning=true)'
 if p.suffix=='.parquet':return 'read_parquet('+lit(p)+')'
 raise ValueError('Expected a Parquet file/directory')

def check_col(cn,sql,columns):
 names=[r[0].lower() for r in cn.execute('DESCRIBE SELECT * FROM '+sql+' LIMIT 0').fetchall()]
 for col in columns:
  if col.lower() not in names:raise ValueError(f'Missing {col} in {sql}; available fields: {names}')

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--main',required=True,help='Exact 41.5m-row main sample (with decision timestamps)')
 p.add_argument('--exposures',required=True,help='Existing, verified IV/matched exposure cohort Parquet')
 p.add_argument('--out',required=True,help='Fresh output root, PRIVATE account-level join')
 p.add_argument('--chooser-col',default='chooser_user_id')
 p.add_argument('--decision-ms-col',default='api_last_move_at_ms')
 p.add_argument('--grant-col',default='outcome_kind_draw')
 p.add_argument('--evaluation-col',default='engine_eval_cp_disconnected')
 p.add_argument('--recipient-col',default='recipient_user_id')
 p.add_argument('--start-ms-col',default='exposure_start_ms')
 p.add_argument('--exposure-id-col',default='exposure_game_id')
 p.add_argument('--expect-main',type=int,default=41534331)
 p.add_argument('--expect-exposures',type=int,default=2682330)
 p.add_argument('--workers',type=int,default=10)
 p.add_argument('--memory-gb',type=int,default=11)
 a=p.parse_args()
 o=Path(a.out);o.mkdir(parents=True,exist_ok=False)
 (o/'private').mkdir();(o/'public').mkdir();(o/'private'/'spill').mkdir()
 cn=duckdb.connect()
 cn.execute(f'SET threads={int(a.workers)}')
 cn.execute('SET memory_limit='+lit(str(a.memory_gb)+'GB'))
 cn.execute('SET temp_directory='+lit(o/'private'/'spill'))
 try:
  mm,ee=source(a.main),source(a.exposures)
  check_col(cn,mm,[a.chooser_col,a.decision_ms_col,a.grant_col,a.evaluation_col])
  check_col(cn,ee,[a.recipient_col,a.start_ms_col,a.exposure_id_col])
  if cn.execute('SELECT COUNT(*) FROM '+mm).fetchone()[0]!=a.expect_main:
   raise ValueError('Main sample identity mismatch (requires 41.5m pool/nonadjacent)')
  if cn.execute('SELECT COUNT(*) FROM '+ee).fetchone()[0]!=a.expect_exposures:
   raise ValueError('Exposure sample count mismatch. Do not blend other IV cohorts.')
  print('Building chooser history summaries, grouped at decision milliseconds',flush=True)
  # Collapse equal timestamps first; no arbitrary same-ms ordering.
  hsql='''SELECT LOWER(TRIM(CAST('''+ident(a.chooser_col)+''' AS VARCHAR))) AS chooser,
 TRY_CAST('''+ident(a.decision_ms_col)+''' AS BIGINT) AS decision_ms,
 SUM(TRY_CAST('''+ident(a.grant_col)+''' AS INTEGER)) AS grants_at_ms,
 SUM(CASE WHEN TRY_CAST('''+ident(a.evaluation_col)+''' AS DOUBLE)>=-100 THEN 1 ELSE 0 END) AS comp_at_ms
 FROM '''+mm+''' GROUP BY 1,2'''
  cn.execute('CREATE OR REPLACE VIEW h0 AS '+hsql)
  nh=cn.execute('SELECT COUNT(*) FROM h0 WHERE chooser IS NULL OR decision_ms IS NULL').fetchone()[0]
  if nh:raise ValueError(f'Missing chooser or timestamps on {nh} grouped main records')
  cn.execute('''CREATE OR REPLACE VIEW h AS SELECT chooser,decision_ms,
   SUM(grants_at_ms) OVER(PARTITION BY chooser ORDER BY decision_ms ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS prior_grants,
   SUM(comp_at_ms) OVER(PARTITION BY chooser ORDER BY decision_ms ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS prior_comp
   FROM h0''')
  cn.execute('''CREATE OR REPLACE VIEW ex AS SELECT *,
   LOWER(TRIM(CAST('''+ident(a.recipient_col)+''' AS VARCHAR))) AS _recipient,
   TRY_CAST('''+ident(a.start_ms_col)+''' AS BIGINT) AS _start_ms
   FROM '''+ee)
  nulls=cn.execute('SELECT COUNT(*) FROM ex WHERE _recipient IS NULL OR _start_ms IS NULL').fetchone()[0]
  if nulls:raise ValueError(f'Exposure missing recipient or start timestamp on {nulls} rows')
  dst=o/'private'/'E_exposures_with_PG_PC_NC_PRIVATE.parquet'
  q='''SELECT ex.* EXCLUDE(_recipient,_start_ms),
 COALESCE(h.prior_grants,0) AS prior_grants_any,
 COALESCE(h.prior_comp,0) AS prior_competitive_choices,
 CASE WHEN COALESCE(h.prior_grants,0)>0 THEN 'PG'
      WHEN COALESCE(h.prior_comp,0)>0 THEN 'PC'
      ELSE 'NC' END AS experience_group
 FROM ex ASOF LEFT JOIN h ON ex._recipient=h.chooser AND ex._start_ms>h.decision_ms'''
  print('Joining events strictly before exposure game start; no future leakage',flush=True)
  cn.execute('COPY ('+q+') TO '+lit(dst)+' (FORMAT PARQUET, COMPRESSION ZSTD)')
  r=cn.execute('''SELECT experience_group, COUNT(*) AS exposures,
 COUNT(DISTINCT '''+ident(a.recipient_col)+''') AS recipients,
 AVG(CASE WHEN prior_grants_any>0 THEN 1 ELSE 0 END) AS previous_any_grant
 FROM read_parquet('''+lit(dst)+''') GROUP BY 1 ORDER BY 1''').fetchdf()
  r.to_csv(o/'public'/'tabE0_prior_groups.csv',index=False)
  checks=cn.execute('SELECT COUNT(*), SUM(CASE WHEN experience_group IS NULL THEN 1 ELSE 0 END) FROM read_parquet('+lit(dst)+')').fetchone()
  if checks[0]!=a.expect_exposures or checks[1]:raise ValueError('Unexpected join multiplication or missing group')
  (o/'public'/'SUCCESS.json').write_text(json.dumps({'status':'E_GROUPS_BUILT_ONLY','exposures':checks[0],
    'warning':'Experience is left-censored at panel start; THIS FILE CONTAINS PRIVATE ACCOUNT AND EXPOSURE HISTORY. No effect estimates or claims.'},indent=2)+'\n')
  print('COMPLETE. Private rows at '+str(dst)+'; public-safe group counts at '+str(o/'public'),flush=True)
 except Exception:
  (o/'private'/'FAILED.txt').write_text(traceback.format_exc())
  raise
 finally:cn.close()
if __name__=='__main__':main()
