#!/usr/bin/env python3
"""Test A1 only: August 2026 Patron flag inventory on prebuilt account cohorts.

Requires the ORIGINAL exact matched state cohort from the Patron pipeline.
No adjusted regression: reproducing Panels A/B requires original design matrix,
matched-slot eligibility, controls and covariance producer, not a guessed refit.
"""
import argparse,json,traceback
from pathlib import Path
import duckdb

def lit(x):return "'"+str(x).replace("'","''")+"'"
def ident(x):return '"'+str(x).replace('"','""')+'"'
def source(path):
 p=Path(path)
 if not p.exists():raise FileNotFoundError(str(p))
 if p.is_dir():return 'read_parquet('+lit(str(p/'**'/'*.parquet'))+',union_by_name=true)'
 if p.suffix=='.parquet':return 'read_parquet('+lit(str(p))+')'
 raise ValueError('Only verified Parquet source files/directories accepted')
def fields(cn,q):
 return {a[0].lower():a[0] for a in cn.execute('DESCRIBE SELECT * FROM '+q+' LIMIT 0').fetchall()}

def main():
 ap=argparse.ArgumentParser(description=__doc__)
 ap.add_argument('--state',required=True,help='Exact original 599,045-account Panel B/C cohort, with state-specific grant flags')
 ap.add_argument('--profiles',required=True,help='Original August 2026 profile snapshot with status flags')
 ap.add_argument('--out',required=True,help='New output directory; only aggregated A1 summaries become public')
 ap.add_argument('--state-user-col',default='chooser_user_id')
 ap.add_argument('--state-comp-col',default='ever_competitive_grant')
 ap.add_argument('--state-lost-col',default='ever_clearly_worse_grant')
 ap.add_argument('--profile-user-col',default='id')
 ap.add_argument('--profile-disabled-col',default='disabled')
 ap.add_argument('--profile-tos-col',default='tosViolation')
 ap.add_argument('--profile-patron-col',default='patron')
 ap.add_argument('--expect-state',type=int,default=599045)
 ap.add_argument('--workers',type=int,default=10)
 ap.add_argument('--memory-gb',type=int,default=11)
 a=ap.parse_args()
 out=Path(a.out);out.mkdir(parents=True,exist_ok=False);(out/'public').mkdir();(out/'private').mkdir()
 cn=duckdb.connect()
 cn.execute(f'SET threads={int(a.workers)}')
 cn.execute('SET memory_limit='+lit(str(a.memory_gb)+'GB'))
 try:
  s=source(a.state);p=source(a.profiles)
  fs=fields(cn,s);fp=fields(cn,p)
  for key in [a.state_user_col,a.state_comp_col,a.state_lost_col]:
   if key.lower() not in fs:raise ValueError(f'State cohort missing {key}; cols: {list(fs)}')
  for key in [a.profile_user_col,a.profile_patron_col]:
   if key.lower() not in fp:raise ValueError(f'August profile table missing {key}; cols: {list(fp)}')
  def ix(z,f):return ident(f[z.lower()])
  # Missing flag property in a RETURNED PROFILE is false, but absence of the
  # entire profile row is null/missing outcome rather than false.
  disabled=(f'COALESCE(TRY_CAST({ix(a.profile_disabled_col,fp)} AS BOOLEAN),FALSE)' if a.profile_disabled_col.lower() in fp else 'FALSE')
  tos=(f'COALESCE(TRY_CAST({ix(a.profile_tos_col,fp)} AS BOOLEAN),FALSE)' if a.profile_tos_col.lower() in fp else 'FALSE')
  sn='''SELECT LOWER(TRIM(CAST('''+ix(a.state_user_col,fs)+''' AS VARCHAR))) AS account,
 TRY_CAST('''+ix(a.state_comp_col,fs)+''' AS INTEGER) AS g_comp,
 TRY_CAST('''+ix(a.state_lost_col,fs)+''' AS INTEGER) AS g_lost FROM '''+s
  pn='''SELECT LOWER(TRIM(CAST('''+ix(a.profile_user_col,fp)+''' AS VARCHAR))) AS account,
 '''+disabled+''' AS disabled_flag, '''+tos+''' AS tos_flag,
 TRY_CAST('''+ix(a.profile_patron_col,fp)+''' AS BOOLEAN) AS patron FROM '''+p
  cn.execute('CREATE OR REPLACE VIEW state AS '+sn)
  cn.execute('CREATE OR REPLACE VIEW profiles AS '+pn)
  qty=cn.execute('SELECT COUNT(*), COUNT(DISTINCT account), SUM(CASE WHEN g_comp NOT IN(0,1) OR g_lost NOT IN(0,1) THEN 1 ELSE 0 END) FROM state').fetchone()
  if qty!=(a.expect_state,a.expect_state,0):raise ValueError('State B/C sample identity or flags wrong: '+str(qty))
  dupe=cn.execute('SELECT COUNT(*)-COUNT(DISTINCT account) FROM profiles').fetchone()[0]
  if dupe:raise ValueError(f'August profile table has {dupe} duplicate normalized accounts')
  cn.execute('''CREATE OR REPLACE VIEW linked AS
 SELECT s.account, CASE WHEN s.g_comp=1 AND s.g_lost=0 THEN 'CO'
 WHEN s.g_comp=1 AND s.g_lost=1 THEN 'BOTH'
 WHEN s.g_comp=0 AND s.g_lost=1 THEN 'LO' ELSE 'NEI' END AS grp,
 p.account IS NOT NULL AS available, p.disabled_flag, p.tos_flag, p.patron
 FROM state s LEFT JOIN profiles p ON s.account=p.account''')
  # A1 only, preserving null distinctions. No row-level account export.
  agg=cn.execute('''SELECT grp,COUNT(*) AS accounts,
 100.0*AVG(CAST(NOT available AS INTEGER)) AS unavailable_percent,
 100.0*AVG(CAST(disabled_flag AS INTEGER)) FILTER(WHERE available) AS disabled_percent,
 100.0*AVG(CAST(tos_flag AS INTEGER)) FILTER(WHERE available) AS tos_percent,
 100.0*AVG(CAST((disabled_flag OR tos_flag) AS INTEGER)) FILTER(WHERE available) AS either_percent,
 100.0*AVG(CAST(patron AS INTEGER)) FILTER(WHERE available) AS patron_all_available_percent,
 100.0*AVG(CAST(patron AS INTEGER)) FILTER(WHERE available AND NOT(disabled_flag OR tos_flag)) AS patron_unflagged_percent,
  100.0*AVG(CAST(patron AS INTEGER)) FILTER(WHERE available AND (disabled_flag OR tos_flag)) AS patron_flagged_percent,
  COUNT(*) FILTER(WHERE available AND (disabled_flag OR tos_flag)) AS flagged_accounts
 FROM linked GROUP BY grp ORDER BY grp''').fetchdf()
  agg.to_csv(out/'public'/'tabA1_flags_by_state_history.csv',index=False)
  (out/'public'/'SUCCESS.json').write_text(json.dumps({'status':'A1_COUNTS_ONLY',
   'state_accounts':qty[0],'notice':'A2/A3 adjusted regressions REQUIRE exact original matching groups, controls, and covariance producer; NOT run'},indent=2)+'\n')
  print('A1 COMPLETE. Aggregate outputs: '+str(out/'public'),flush=True)
 except Exception:
  (out/'private'/'FAILED.txt').write_text(traceback.format_exc())
  raise
 finally:cn.close()
if __name__=='__main__':main()
