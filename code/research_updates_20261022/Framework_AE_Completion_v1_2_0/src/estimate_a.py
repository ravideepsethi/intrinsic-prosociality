#!/usr/bin/env python3
"""Test A on authenticated August Patron cohorts, requiring original match cells and model controls.

Does not fabricate missing August flags, replace unmatched controls, or use a
new matching design.  Panel A and B can run separately if the source files
contain the required columns.  All individual-level rows stay PRIVATE.
"""
from __future__ import annotations
import argparse,json,datetime as dt,hashlib,traceback
from pathlib import Path
import numpy as np
import pandas as pd
from run_bc import ident,lit,announce

def source(path):
 p=Path(path)
 if not p.exists():raise FileNotFoundError(p)
 if p.suffix=='.parquet':return 'read_parquet('+lit(str(p))+')'
 if p.is_dir():
  return 'read_parquet('+lit(str(p/'**'/'*.parquet'))+',union_by_name=true)'
 raise ValueError('Require Parquet file or leaf directory')

def find_col(fields, aliases, name):
 low={k.lower():k for k in fields}
 for a in aliases:
  if a.lower() in low:return low[a.lower()]
 raise ValueError('Missing '+name+', needed one of '+str(aliases)+'; cols: '+str(fields[:130]))

def fit_cell_fe(df, terms, control_cols, cell_col, outcome_col='patron'):
 """Unweighted LPM, exact within-cell linear projection, HC1 + cell CR1.

 No arbitrary regularization: dependent terms require explicit nuisance pruning;
 treatment must remain identified.  Terms are binary 0/1; outcome in pp.
 """
 cell, ids=pd.factorize(df[cell_col].astype(str),sort=True)
 n=len(df); groups=int(np.max(cell)+1)
 focal=df[terms].to_numpy(dtype=float)
 controls=df[control_cols].to_numpy(dtype=float) if control_cols else np.empty((n,0))
 if not(np.isfinite(focal).all() and np.isfinite(controls).all()):
  raise ValueError('Missing or nonfinite design columns: use exact original imputed covariates')
 names=terms+control_cols
 X=np.column_stack([focal,controls]);y=100*df[outcome_col].to_numpy(dtype=float)
 if not np.isfinite(y).all():raise ValueError('Missing Patron outcome in available original cohort')
 counts=np.bincount(cell,minlength=groups)
 wy=np.bincount(cell,weights=y,minlength=groups)/counts
 yy=y-wy[cell]
 XX=X.copy()
 for j in range(X.shape[1]):
  mu=np.bincount(cell,weights=XX[:,j],minlength=groups)/counts
  XX[:,j]-=mu[cell]
 # Treat/account clusters are individual accounts, one record each.  For cell
 # cluster variance we sum score by matching-cell, not arbitrary match sets.
 from methods import choose_within_identified
 gram=XX.T@XX
 good,omitted=choose_within_identified(gram,names,
    protected=lambda name:name in terms,relative_tol=1e-10)
 Xt=XX[:,good]
 w,V=np.linalg.eigh(Xt.T@Xt)
 if min(w)<=max(w)*1e-11:
  raise ValueError('Cell-FE regression unidentified, despite nuisance pruning')
 bread=V@np.diag(1/w)@V.T
 coef=bread@(Xt.T@yy)
 resid=yy-Xt@coef
 meat=Xt.T@(Xt*resid[:,None]**2)
 vc_hc1=(n/(n-Xt.shape[1]-groups))*bread@meat@bread
 sc=np.column_stack([np.bincount(cell,weights=Xt[:,j]*resid,minlength=groups) for j in range(Xt.shape[1])])
 vc_cell=(groups/(groups-1))*((n-1)/(n-Xt.shape[1]-groups))*bread@(sc.T@sc)@bread
 rows=[]
 for t in terms:
  j=names.index(t)
  if j not in good:raise ValueError('Focal dropped unexpectedly: '+t)
  k=good.index(j)
  hc=float(np.sqrt(max(0,vc_hc1[k,k])));cl=float(np.sqrt(max(0,vc_cell[k,k])))
  rows.append(dict(estimand=t,estimate_pp=float(coef[k]),SE_HC1_pp=hc,SE_matching_cell_pp=cl,
   ci95_HC1_low=float(coef[k]-1.96*hc),ci95_HC1_high=float(coef[k]+1.96*hc),
   accounts=n,matching_cells=groups,covariates_used=';'.join(names[i] for i in good),
   dropped_covariates=';'.join(d['regressor'] for d in omitted)))
 return rows

def fetch(cn,sql, account, columns):
 cs=[ident(account)]+[ident(x) for x in columns if x!=account]
 return cn.execute('SELECT '+','.join(cs)+' FROM '+sql).fetchdf()

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--panel-b',help='exact 599045-account state-specific matched cohort')
 p.add_argument('--panel-a',help='exact 851131-account focal-granter matched cohort')
 p.add_argument('--profiles',required=True,help='exact August 2026 profile snapshot with disabled and tosViolation')
 p.add_argument('--out',required=True)
 p.add_argument('--controls',required=True,help='Comma-separated *original Stage 10* control columns present in both cohorts; no guessed adjustments')
 p.add_argument('--account-col',default='chooser_user_id')
 p.add_argument('--profile-account-col',default='id')
 p.add_argument('--patron-col',default='patron')
 p.add_argument('--disabled-col',default='disabled')
 p.add_argument('--tos-col',default='tosViolation')
 p.add_argument('--cell-col',default='matching_cell')
 p.add_argument('--competitive-col',default='ever_competitive_grant')
 p.add_argument('--lost-col',default='ever_clearly_worse_grant')
 p.add_argument('--focal-col',default='focal_competitive_granter')
 p.add_argument('--matched-group-col',default='matched_group_id')
 p.add_argument('--expect-panel-b',type=int,default=599045)
 p.add_argument('--expect-panel-a',type=int,default=851131)
 p.add_argument('--workers',type=int,default=10);p.add_argument('--memory-gb',type=int,default=11)
 a=p.parse_args()
 if not a.panel_a and not a.panel_b:p.error('At least --panel-b or --panel-a needed')
 import duckdb
 root=Path(a.out);root.mkdir(parents=True,exist_ok=False);pub=root/'public';priv=root/'private';pub.mkdir();priv.mkdir()
 cn=duckdb.connect(':memory:');cn.execute(f'SET threads={a.workers}');cn.execute('SET memory_limit='+lit(str(a.memory_gb)+'GB'))
 controls=[s.strip() for s in a.controls.split(',') if s.strip()]
 if not controls:raise ValueError('Original control list required, never estimate unadjusted model as original')
 try:
  pp=source(a.profiles)
  pfields=[z[0] for z in cn.execute('DESCRIBE SELECT * FROM '+pp+' LIMIT 0').fetchall()]
  for c in (a.profile_account_col,a.patron_col,a.disabled_col,a.tos_col):
   if c not in pfields:raise ValueError(f'August profile snapshot missing REQUIRED field {c}: {pfields[:100]}; do not treat whole-column absence as false')
  qry='''SELECT LOWER(TRIM(CAST('''+ident(a.profile_account_col)+''' AS VARCHAR))) AS _account,
     TRY_CAST('''+ident(a.patron_col)+''' AS BOOLEAN) AS _patron,
     COALESCE(TRY_CAST('''+ident(a.disabled_col)+''' AS BOOLEAN),FALSE) AS _disabled,
     COALESCE(TRY_CAST('''+ident(a.tos_col)+''' AS BOOLEAN),FALSE) AS _tos
     FROM '''+pp
  cn.execute('CREATE OR REPLACE VIEW profiles_norm AS '+qry)
  dupe=cn.execute('SELECT COUNT(*)-COUNT(DISTINCT _account) FROM profiles_norm').fetchone()[0]
  if dupe:raise ValueError(f'Duplicate normalized August profiles: {dupe}')
  results=[];inventories=[]
  for panel,path,expected in [('B',a.panel_b,a.expect_panel_b),('A',a.panel_a,a.expect_panel_a)]:
   if not path:continue
   sql=source(path)
   fields=[r[0] for r in cn.execute('DESCRIBE SELECT * FROM '+sql+' LIMIT 0').fetchall()]
   required=[a.account_col,a.cell_col,a.competitive_col]+controls
   if panel=='B':required+=[a.lost_col]
   if panel=='A':required+=[a.focal_col,a.matched_group_col]
   missing=[k for k in required if k not in fields]
   if missing:raise ValueError(f'Original Panel {panel} missing fields {missing}; has {fields[:100]}')
   q='''SELECT a.*,p._patron AS patron,p._disabled,p._tos, p._account IS NOT NULL AS _available
   FROM '''+sql+''' a LEFT JOIN profiles_norm p
     ON LOWER(TRIM(CAST(a.'''+ident(a.account_col)+''' AS VARCHAR)))=p._account'''
   cn.execute('CREATE OR REPLACE TEMP VIEW joined AS '+q)
   n0=cn.execute('SELECT COUNT(*) FROM joined').fetchone()[0]
   if n0!=expected:raise ValueError(f'Wrong Panel {panel} cohort: {n0:,} vs {expected:,}')
   missing_profiles=cn.execute('SELECT COUNT(*) FROM joined WHERE NOT _available OR patron IS NULL').fetchone()[0]
   if missing_profiles:raise ValueError(f'{missing_profiles} Panel {panel} profiles unavailable; require the original available-profile cohort')
   df=cn.execute('SELECT * FROM joined').fetchdf()
   df['_either']=df['_disabled']|df['_tos']
   if panel=='B':
    cc=(df[a.competitive_col].to_numpy(dtype=float)>0)
    ll=(df[a.lost_col].to_numpy(dtype=float)>0)
    df['_group']=np.select([cc&~ll,cc&ll,~cc&ll],['CO','BOTH','LO'],default='NEI')
   else:df['_group']=np.where(df[a.focal_col].astype(int)==1,'COMP_GRANTER','CONTROL')
   for label,g in df.groupby('_group',observed=True):
    row=dict(panel=panel,group=label,accounts=len(g),disabled_share=float(g._disabled.mean()),
       tos_share=float(g._tos.mean()),either_share=float(g._either.mean()),
       patron_all_pp=100*float(g.patron.mean()),
       patron_unflagged_pp=100*float(g.loc[~g._either,'patron'].mean()) if (~g._either).any() else None,
       patron_flagged_pp=100*float(g.loc[g._either,'patron'].mean()) if g._either.any() else None)
    inventories.append(row)
   for label,flag in [('all',np.ones(len(df),bool)),('exclude_tos',~df._tos.to_numpy()),
                      ('exclude_disabled',~df._disabled.to_numpy()),('exclude_either',~df._either.to_numpy())]:
    sub=df.loc[flag].copy()
    if panel=='A':
     # Stop on missing original matched group rather than silently re-matching.
     grp=a.matched_group_col
     active=sub.loc[sub[a.focal_col].astype(int)==1,grp].unique()
     sub=sub[sub[grp].isin(active)].copy()
     treated=sub[a.focal_col].to_numpy(dtype=float)
     terms=[a.focal_col]
     if treated.min()!=0 or treated.max()!=1:raise ValueError('Panel A has no treatment variation after exclusion')
    else:terms=[a.competitive_col,a.lost_col]
    res=fit_cell_fe(sub,terms,controls,a.cell_col)
    for row in res:row.update(panel=panel,restriction=label)
    results+=res
    if panel=='B':
     for gp,g in sub.groupby('_group'):
      results.append(dict(panel='B',restriction=label,estimand='raw_patron_'+gp,
             estimate_pp=100*float(g.patron.mean()),accounts=len(g),matching_cells=g[a.cell_col].nunique(),
             notice='Descriptive Panel C raw rate, no regression'))
  pd.DataFrame(inventories).to_csv(pub/'tabA1_flags_by_group.csv',index=False)
  pd.DataFrame(results).to_csv(pub/'tabA2_patron_excluding_flags.csv',index=False)
  report={'status':'A_PANEL_AB_COMPLETE_IF_ORIGINAL_COHORT_AND_CONTROLS_AUTHENTICATED',
     'panel_B_has_original_covariates':bool(a.panel_b),'panel_A_has_original_covariates':bool(a.panel_a),
     'note':'A3 recipient-side opportunity regression is NOT included in this run. Must reuse original 22.5m dyadic model and flags.'}
  (pub/'_SUCCESS.json').write_text(json.dumps(report,indent=2)+'\n')
  announce('Test A available Panel A/B analyses complete. A3 explicitly remains separate.')
 except Exception:
  (priv/'FAILED.txt').write_text(traceback.format_exc());raise
 finally:cn.close()
if __name__=='__main__':main()
