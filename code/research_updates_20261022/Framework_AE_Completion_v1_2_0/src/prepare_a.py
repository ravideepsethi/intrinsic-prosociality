#!/usr/bin/env python3
"""Reconstruct the paper's Patron Panel A/B from August snapshot and frozen features.

Strict row/count/response/group checks. Never query Lichess. Private Parquets only.
Do not silently substitute the later supplemented profiles for August observations.
"""
import argparse, hashlib, json, math, traceback
from pathlib import Path
import numpy as np
import pandas as pd

EXPECTED_B = {'CO':100671,'BOTH':18098,'NEI':454045,'LO':26231}

def lit(s):return "'"+str(s).replace("'","''")+"'"
def log(s):print('[A preflight]',s,flush=True)

def main():
 ap=argparse.ArgumentParser()
 ap.add_argument('--features',required=True)
 ap.add_argument('--snapshot',required=True)
 ap.add_argument('--out',required=True)
 ap.add_argument('--workers',type=int,default=10)
 ap.add_argument('--memory-gb',type=int,default=11)
 a=ap.parse_args()
 import duckdb
 root=Path(a.out);root.mkdir(parents=True,exist_ok=False)
 (root/'private').mkdir();(root/'public').mkdir()
 c=duckdb.connect(':memory:');c.execute(f'SET threads={a.workers}');c.execute('SET memory_limit='+lit(str(a.memory_gb)+'GB'))
 try:
  for tag,p,expected in [('features',a.features,1105919),('snapshot',a.snapshot,1305872)]:
   if not Path(p).is_file():raise FileNotFoundError(p)
   row=c.execute('SELECT COUNT(*),COUNT(DISTINCT username_norm) FROM read_parquet('+lit(p)+')').fetchone()
   if row!=(expected,expected):raise ValueError(f'{tag} has wrong row count / repeated usernames: {row}, expected {expected} distinct')
  fcols={r[0] for r in c.execute('DESCRIBE SELECT * FROM read_parquet('+lit(a.features)+')').fetchall()}
  pcols={r[0] for r in c.execute('DESCRIBE SELECT * FROM read_parquet('+lit(a.snapshot)+')').fetchall()}
  frequired={'username_norm','is_kind_role','matched_kind_chooser_id','match_cell','fair_opps',
             'clearly_worse_opps','fair_kind_count','clearly_worse_kind_count'}
  prequired={'username_norm','returned','patron','disabled','tos_violation'}
  if frequired-fcols or prequired-pcols:raise ValueError('Missing frozen fields: '+str((frequired-fcols,prequired-pcols)))
  # Return status is from the August-certified full snapshot; later profile gap fills are prohibited.
  c.execute(f"""CREATE TEMP VIEW base AS SELECT f.*,
   p.returned AS _august_returned, p.patron AS _august_patron,
   p.disabled AS _august_disabled, p.tos_violation AS _august_tos,
   CASE WHEN CAST(f.is_kind_role AS BOOLEAN) THEN LOWER(TRIM(CAST(f.username_norm AS VARCHAR)))
        ELSE LOWER(TRIM(CAST(f.matched_kind_chooser_id AS VARCHAR))) END AS _matched_group
   FROM read_parquet({lit(a.features)}) f LEFT JOIN read_parquet({lit(a.snapshot)}) p
   ON f.username_norm=p.username_norm""")
  counts=c.execute('''SELECT COUNT(*),COUNT(*) FILTER(WHERE _august_returned AND _august_patron IS NOT NULL),
   COUNT(*) FILTER(WHERE _august_returned IS NULL),
   COUNT(*) FILTER(WHERE _august_returned AND _august_patron IS NULL)
   FROM base''').fetchone()
  (root/'public'/'A_availability_preflight.json').write_text(json.dumps(dict(all_accounts=counts[0],
   available_with_outcome=counts[1],unmatched_snapshot=counts[2],returned_without_patron=counts[3]),indent=2)+'\n')
  log(f'Acquisition {counts[0]:,}; observed August profiles with Patron status {counts[1]:,}')
  if counts[1]!=1105634:
   raise ValueError(f'August profile restriction differs from paper: {counts[1]:,} vs 1,105,634. Check original cohort lineage; no date substitution.')
  # Before conditioning on profile availability, report missing outcomes by granting history.
  miss=c.execute("""SELECT CASE WHEN fair_kind_count>0 AND clearly_worse_kind_count=0 THEN 'CO'
       WHEN fair_kind_count>0 AND clearly_worse_kind_count>0 THEN 'BOTH'
       WHEN fair_kind_count=0 AND clearly_worse_kind_count>0 THEN 'LO'
       ELSE 'NEI' END AS grp,
       COUNT(*) AS acquisition_accounts,
       COUNT(*) FILTER(WHERE _august_returned AND _august_patron IS NOT NULL) AS august_available,
       COUNT(*) FILTER(WHERE _august_returned IS NULL OR NOT _august_returned OR _august_patron IS NULL) AS august_unavailable
       FROM base WHERE fair_opps>=4 AND clearly_worse_opps>=4 GROUP BY 1 ORDER BY 1""").fetchdf()
  miss['unavailable_percent']=100*miss.august_unavailable/miss.acquisition_accounts
  miss.to_csv(root/'public'/'A_profile_missingness_by_grant_group.csv',index=False)
  c.execute('CREATE TEMP VIEW usable AS SELECT * FROM base WHERE _august_returned AND _august_patron IS NOT NULL')
  c.execute('''CREATE TEMP VIEW pb AS SELECT *,
   CASE WHEN fair_kind_count>0 AND clearly_worse_kind_count=0 THEN 'CO'
        WHEN fair_kind_count>0 AND clearly_worse_kind_count>0 THEN 'BOTH'
        WHEN fair_kind_count=0 AND clearly_worse_kind_count>0 THEN 'LO'
        ELSE 'NEI' END AS grant_group
   FROM usable WHERE fair_opps>=4 AND clearly_worse_opps>=4''')
  bc=c.execute('SELECT grant_group,COUNT(*) FROM pb GROUP BY 1').fetchall()
  found={str(x):int(y) for x,y in bc}
  (root/'public'/'A_panel_B_group_preflight.json').write_text(json.dumps(found,indent=2)+'\n')
  log('Panel B states '+str(found))
  if found!=EXPECTED_B:raise ValueError('Panel B counts do not match the published 599,045 exact four groups')
  n_b_cells=c.execute('SELECT COUNT(DISTINCT match_cell) FROM pb').fetchone()[0]
  if n_b_cells!=24:raise ValueError(f'Panel B matching cells {n_b_cells} != 24')
  # Panel A original focal accounts: competitive-position grant; their selected, observed matched controls.
  # No replacement matching. Entire group's controls exit if focal later excluded.
  c.execute('''CREATE TEMP VIEW focal AS SELECT _matched_group FROM usable
   WHERE CAST(is_kind_role AS BOOLEAN) AND fair_kind_count>=1''')
  dup=c.execute('SELECT COUNT(*)-COUNT(DISTINCT _matched_group) FROM focal').fetchone()[0]
  if dup:raise ValueError('Duplicate focal groups in original matching')
  c.execute('''CREATE TEMP VIEW pa AS SELECT b.* FROM usable b
   WHERE EXISTS(SELECT 1 FROM focal t WHERE t._matched_group=b._matched_group)''')
  ac=c.execute('''SELECT COUNT(*),COUNT(*) FILTER(WHERE CAST(is_kind_role AS BOOLEAN)),
       COUNT(*) FILTER(WHERE NOT CAST(is_kind_role AS BOOLEAN)),COUNT(DISTINCT _matched_group),
       COUNT(*) FILTER(WHERE _matched_group IS NULL) FROM pa''').fetchone()
  (root/'public'/'A_panel_A_preflight.json').write_text(json.dumps(dict(total=ac[0],focal=ac[1],controls=ac[2],
    matched_groups=ac[3],null_group=ac[4]),indent=2)+'\n')
  log('Panel A '+str(ac))
  n_a_cells=c.execute('SELECT COUNT(DISTINCT match_cell) FROM pa').fetchone()[0]
  if ac[:3]!=(851131,212829,638302) or ac[4]!=0 or n_a_cells!=36:
   raise ValueError('Panel A count/group mismatch with paper. No rematching or inferred panel used.')
  # Original model includes panel and August-profile characteristics. The preprocessed design
  # contains all raw building blocks; this sensitivity refit uses a fixed, documented set.
  vars={
   'log_total_opps':'panel_total_opps', 'log_fair_opps':'panel_fair_opps',
   'log_lost_opps':'panel_clearly_worse_opps', 'log_active_months':'panel_active_months',
   'share_fair':'share_fair','share_lost':'share_clearly_worse',
   'mean_eval':'mean_eval_capped600','mean_rating':'panel_mean_chooser_elo',
   'sd_rating':'panel_sd_chooser_elo',
   'draw_payoff':'panel_mean_draw_payoff_fair', 'premium':'panel_mean_win_premium_fair',
   'speed_bullet':'share_speed_bullet','speed_blitz':'share_speed_blitz',
   'speed_rapid':'share_speed_rapid','speed_classical':'share_speed_classical_long',
   'share_equal':'share_eval_roughly_equal','share_better':'share_eval_disconnected_better',
   'share_clearlybetter':'share_eval_disconnected_clearly_better',
   'account_age':'account_age_days_at_query','recency':'days_since_seen_at_query',
   'log_playtime':'play_time_total_seconds','log_all_games':'count_all',
   'log_rated_games':'count_rated','log_current_bullet':'current_bullet_games',
   'log_current_blitz':'current_blitz_games','log_current_rapid':'current_rapid_games',
   'curr_bullet_rating':'current_bullet_rating','curr_blitz_rating':'current_blitz_rating',
   'curr_rapid_rating':'current_rapid_rating','curr_classical_rating':'current_classical_rating',
   'curr_correspondence_rating':'current_correspondence_rating'}
  absent=[k for k in vars.values() if k not in fcols]
  if absent:raise ValueError('Original features missing required regression control ingredients: '+str(absent))
  fields=['username_norm','match_cell','_matched_group','is_kind_role',
         'fair_kind_count','clearly_worse_kind_count','fair_opps','clearly_worse_opps']+list(set(vars.values()))
  select=','.join('"'+q+'"' for q in fields)
  control_names=[]
  for panel,view in [('A','pa'),('B','pb')]:
   log('Extract '+panel+' account and control columns')
   df=c.execute('SELECT '+select+' FROM '+view).fetchdf()
   for key,source in vars.items():
    s=pd.to_numeric(df[source],errors='coerce').astype(float)
    if key.startswith('log_'):
     s=np.log1p(np.maximum(s,0))
    elif key in ('account_age','recency'):
     s=np.log1p(np.maximum(s,0))
    new='ctrl_'+key
    # Missing values: same principle as the original appendix, within matching cell medians,
    # with global fallback and a missingness indicator where supported.
    null=~np.isfinite(s)
    if null.any():
     med=pd.Series(s).groupby(df.match_cell).transform('median')
     global_med=float(np.nanmedian(s)) if np.isfinite(s).any() else 0.
     s=np.where(null,np.where(np.isfinite(med),med,global_med),s)
    df[new]=np.asarray(s,dtype=np.float64)
    miss=new+'_missing'
    df[miss]=null.astype(np.float64)
    if panel=='A':
     control_names.append(new)
     if null.any():control_names.append(miss)
    elif null.any() and miss not in control_names:
     # Separate panels may have different observed missingness; keep complete control set.
     control_names.append(miss)
   df['focal_competitive_granter']=df['is_kind_role'].astype(int)
   df['ever_competitive_grant']=(df['fair_kind_count']>0).astype(int)
   df['ever_lost_grant']=(df['clearly_worse_kind_count']>0).astype(int)
   df['matched_group_id']=df['_matched_group'].astype(str)
   # Keep identical control list across both datasets: fill omitted missingness indicators with zero.
   for k in control_names:
    if k not in df:df[k]=0.
   dest=root/'private'/f'panel_{panel}_source_compatible.parquet'
   df[['username_norm','match_cell','matched_group_id','focal_competitive_granter','ever_competitive_grant','ever_lost_grant']+
       [k for k in control_names if k in df]].to_parquet(dest,index=False,compression='zstd')
  # Ensure two files share exactly the same covariates; Panel B may introduce missingness indicators.
  for panel in 'AB':
   dest=root/'private'/f'panel_{panel}_source_compatible.parquet'
   df=pd.read_parquet(dest)
   for k in control_names:
    if k not in df:df[k]=0.
   df.to_parquet(dest,index=False,compression='zstd')
  (root/'public'/'A_model_controls.json').write_text(json.dumps({'controls':control_names,
    'status':'DOCUMENTED_RECONSTRUCTION_OF_FULL_CONTROL_FAMILY; verify baseline estimates against paper',
    'baseline_targets':{'Panel_A':0.277,'Panel_B_competitive':0.388,'Panel_B_lost':-0.195}},indent=2)+'\n')
  (root/'public'/'_PREFLIGHT_OK.json').write_text(json.dumps({'status':'EXACT_PAPER_COHORTS_RECONSTRUCTED',
   'panel_A':851131,'panel_B':599045,'source':'August-certified snapshot + frozen wave3b1 design',
   'warning':'Regressor transformations are transparent reconstruction, not claimed exact original execution'},indent=2)+'\n')
  log('A preflight complete; private panel files ready')
 except Exception:
  (root/'private'/'FAILED.txt').write_text(traceback.format_exc());raise
 finally:c.close()
if __name__=='__main__':main()
