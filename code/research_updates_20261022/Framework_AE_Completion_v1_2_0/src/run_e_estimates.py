#!/usr/bin/env python3
"""Test E prior-experience interactions on original cached receipt cohort.

Two modes:
  matched: original overlap weights, cell and month fixed effects, thirteen
           exposure-game controls and squares, opponent-clustered inference.
  iv: original score and pre-exposure controls, assignment-cell, UTC exposure
      date and hour-of-week FE, exact role-or-date CR0 score covariance.

The input MUST first be joined by build_e_groups.py to the 24-month chooser
history.  This script is unable to recover missing historical score/reference
construction or unmatched rows.  Fail closed until input columns and counts
match the original frozen cohort. Zero API requests.
"""
from __future__ import annotations
import argparse,datetime as dt,json,traceback,math,hashlib
from pathlib import Path
import numpy as np
import pandas as pd
from run_bc import announce,lit

GRPS=('PG','PC','NC')

def factor(s):
 if isinstance(s,pd.MultiIndex):
  return pd.factorize(s,sort=False)[0].astype(np.int64)
 return pd.factorize(pd.Series(s).astype('string').fillna('<MISSING>'),sort=False)[0].astype(np.int64)

def demean(array,group_codes,w):
 """Apply one exact weighted FE projection to a matrix (including y)."""
 g=np.asarray(group_codes,dtype=np.int64)
 if np.any(g<0):raise ValueError('invalid group FE code')
 v=np.asarray(array,dtype=np.float64)
 W=np.bincount(g,weights=w,minlength=g.max()+1)
 for j in range(v.shape[1]):
  sums=np.bincount(g,weights=w*v[:,j],minlength=len(W))
  v[:,j]-=(sums/W)[g]
 return v

def absorb_multi(mat,codes,weights,max_rounds=65,atol=1e-9):
 """Iterated weighted alternating projections for several categorical FE.

 Reuse the original matrix, stop if the maximum change in column norms is tiny.
 Check every FE mean at convergence and fail closed otherwise.
 """
 v=np.asarray(mat,dtype=np.float64).copy()
 for t in range(max_rounds):
  old=v.copy() if t>=1 else None
  for code in codes:demean(v,code,weights)
  if old is not None:
   delta=np.linalg.norm(v-old,axis=0)
   scale=np.maximum(1.,np.linalg.norm(mat,axis=0))
   if np.max(delta/scale)<atol:break
 else:raise ValueError('HDFE absorption did not converge; do not run IV on incompletely residualized covariates')
 # A direct weighted mean check catches incorrect convergence caused by large scale.
 for code in codes:
  cnt=np.bincount(code,weights=weights,minlength=code.max()+1)
  for col in range(v.shape[1]):
   s=np.bincount(code,weights=weights*v[:,col],minlength=len(cnt))
   if np.max(np.abs(s/cnt))>1e-7*np.maximum(1.,np.std(mat[:,col])):
    raise ValueError('HDFE residualization failed FE-mean diagnostic')
 return v

def moments(score, labels):
 codes=factor(labels);order=np.argsort(codes,kind='mergesort')
 st=np.r_[0,1+np.flatnonzero(codes[order][1:]!=codes[order][:-1])]
 sums=np.add.reduceat(score[order],st,axis=0)
 return sums.T@sums, len(st)

def moment_union_account_date(scores,rec,opp,date):
 """Exact union-of-either-role-account and UTC-date CR0 covariance.

 Pair intersections correct for shared BOTH roles; account+date is included
 with inclusion-exclusion, as required by the original instrument design.
 """
 # Group by account in either role using one concatenated ID array, but do not
 # materialize the scores twice. Accumulate sparse cluster sums in 2 passes.
 n,p=scores.shape
 ac1=factor(pd.Series(rec).astype(str)); ac2_raw=pd.Series(opp).astype(str)
 all_accounts=pd.Index(pd.Series(rec).astype(str)).append(pd.Index(ac2_raw))
 ac=pd.factorize(all_accounts,sort=False)[0]
 g1=ac[:n];g2=ac[n:]
 if np.any(g1==g2):raise ValueError('Self-paired exposure found')
 G=int(ac.max()+1);U=np.zeros((G,p))
 for j in range(p):
  U[:,j]=np.bincount(g1,weights=scores[:,j],minlength=G)+np.bincount(g2,weights=scores[:,j],minlength=G)
 MA=U.T@U
 # Unordered pair: here strings are account IDs; keeps exact dyadic overlap.
 r=np.asarray(rec,dtype=str);o=np.asarray(opp,dtype=str);d=np.asarray(date,dtype=str)
 low=np.where(r<o,r,o);high=np.where(r<o,o,r)
 pair=pd.MultiIndex.from_arrays([low,high])
 MP,npairs=moments(scores,pair)
 MD,ndates=moments(scores,d)
 # account x date, both roles; same date grouping across roles.
 aidx=pd.MultiIndex.from_arrays([np.r_[r,o],np.r_[d,d]])
 ad=pd.factorize(aidx,sort=False)[0]
 G=int(ad.max()+1);Uad=np.zeros((G,p))
 for j in range(p):
  Uad[:,j]=np.bincount(ad[:n],weights=scores[:,j],minlength=G)+np.bincount(ad[n:],weights=scores[:,j],minlength=G)
 MAD=Uad.T@Uad
 pdidx=pd.MultiIndex.from_arrays([low,high,d])
 MPD,npaird=moments(scores,pdidx)
 return MA-MP+MD-MAD+MPD, {'unique_accounts':len(U),'pairs':npairs,'dates':ndates,'account_dates':len(Uad),'pair_dates':npaird}

def features(df,mode,controls,monthcol,grpcol='experience_group'):
 n=len(df); grp=df[grpcol].astype(str).to_numpy()
 if set(grp)-set(GRPS):raise ValueError('Unexpected experience categories: '+str(set(grp)))
 cov=[(grp=='PG').astype(float),(grp=='PC').astype(float)]
 labels=['prior_PG','prior_PC']
 for key in controls:
  x=pd.to_numeric(df[key],errors='coerce').to_numpy(dtype=float)
  if not np.isfinite(x).all():raise ValueError('Missing/nonfinite original model control '+key)
  if mode=='matched':
   cov.extend([x,x*x]);labels.extend([key,key+'_sq'])
  else:
   cov.append(x);labels.append(key)
 if mode=='matched':
  month=df[monthcol].astype(str).to_numpy()
  levels=sorted(set(month))
  if len(levels)<2 or len(levels)>28:raise ValueError('Matched cohort month FE unsupported: '+str(levels))
  for m in levels[1:]:cov.append((month==m).astype(float));labels.append('month_'+m)
 return np.column_stack(cov),labels

def build_design(df,mode,receipt_col,controls,month_col):
 W,labels=features(df,mode,controls,month_col)
 g=df.experience_group.astype(str).to_numpy();rec=df[receipt_col].to_numpy(dtype=float)
 if np.any(~np.isin(rec,[0.,1.])):raise ValueError('Receipt must be 0/1 (not generic draw marker)')
 treats=np.column_stack([rec*(g==k) for k in GRPS])
 design=np.column_stack([treats,W]);names=['receipt_'+q for q in GRPS]+labels
 return design,names

def choose_predictors(x,cols,protected=3):
 from methods import choose_within_identified
 gram=x.T@x
 good,drop=choose_within_identified(gram,cols,protected=lambda s:s in cols[:protected],relative_tol=1e-10)
 return x[:,good],[cols[k] for k in good],drop,good

def matched_model(df,outcome,controls, args):
 # Caller has already trimmed to complete windows or to observed later choices.
 n=len(df)
 X,names=build_design(df,'matched',args.receipt_col,controls,args.month_col)
 y=100*pd.to_numeric(df[outcome]).to_numpy(dtype=float)
 if not np.isfinite(y).all() or np.any(~np.isin(y,[0.,100.])):
  raise ValueError('Matched later-grant outcome must be binary 0/1, missing only outside conditional support')
 w=pd.to_numeric(df[args.weight_col]).to_numpy(dtype=float)
 if not(np.isfinite(w).all() and np.all(w>0)):raise ValueError('Invalid original pre-followup matching weight')
 original=X.copy()
 cell=factor(df[args.cell_col]);z=np.column_stack([y,X])
 demean(z,cell,w);yy=z[:,0];xx=z[:,1:]
 # Selection is based on WITHIN-cell weighted variation (not full dataset variance).
 sw=np.sqrt(w)
 xx2=xx*sw[:,None]
 xxkeep,nameskeep,drop,good=choose_predictors(xx2,names,3)
 rawx=xx[:,good]
 # QR avoids loss of precision on squared controls with different scales.
 q,r=np.linalg.qr(xxkeep,mode='reduced')
 vals=np.linalg.svd(r,compute_uv=False)
 if vals[-1]<=vals[0]*1e-11:raise ValueError('Matched original design remains near-singular')
 beta=np.linalg.solve(r,q.T@(yy*sw))
 rinv=np.linalg.solve(r,np.eye(len(beta)));bread=rinv@rinv.T
 residual=yy-rawx@beta
 # Original matched design clusters by exposure opponent account.
 cluster=df[args.opponent_col].astype(str).to_numpy()
 scores=rawx*(w*residual)[:,None]
 M,G=moments(scores,cluster)
 cov=(G/(G-1))*bread@M@bread
 rows=[]
 for i,name in enumerate(nameskeep):
  if name not in names[:3]:continue
  se=math.sqrt(max(0,cov[i,i]));rows.append(dict(outcome=outcome,group=name.split('_')[-1],
    effect_pp=float(beta[i]),clustered_se_pp=se,CI95_low=float(beta[i]-1.96*se),CI95_high=float(beta[i]+1.96*se),
    n=n,clusters=G,n_cells=len(np.unique(cell)),omitted_nuisance=';'.join(x['regressor'] for x in drop)))
 return rows

def iv_model(df,args,controls):
 n=len(df);score=pd.to_numeric(df[args.score_col],errors='coerce').to_numpy(dtype=float)
 if not np.isfinite(score).all():raise ValueError('Original historical score missing or unsupported')
 X,names=build_design(df,'iv',args.receipt_col,controls,args.month_col)
 g=df.experience_group.astype(str).to_numpy()
 Z=X.copy()
 for j,group in enumerate(GRPS):Z[:,j]=score*(g==group)
 y=100*pd.to_numeric(df[args.zero_outcome_col],errors='coerce').to_numpy(dtype=float)
 if not np.isfinite(y).all() or np.any(~np.isin(y,[0.,100.])):
  raise ValueError('IV zero-coded later-grant outcome must be binary 0/1')
 w=np.ones(n)
 groups=[factor(df[args.cell_col]),factor(df[args.date_col]),factor(df[args.hour_col])]
 both=np.column_stack([y,X,Z[:,:3]])
 announce('E IV: partial out assignment cells, UTC exposure dates, hour-of-week, one joint projection')
 R=absorb_multi(both,groups,w)
 yy=R[:,0];Xr=R[:,1:1+X.shape[1]]
 # Exogenous regressors appear identically in X and Z: use their single residual.
 Zr=np.column_stack([R[:,1+X.shape[1]:],Xr[:,3:]])
 # Remove redundant nuisance terms but never rotate focal D or Z.
 design=np.column_stack([Xr[:,:3],Zr[:,:3],Xr[:,3:]])
 keep2,names2,drops,idx=choose_predictors(design,names[:3]+['Z_'+k for k in GRPS]+names[3:],6)
 kept_nuis=[k-6 for k in idx if k>=6]
 xx=np.column_stack([Xr[:,:3],Xr[:,3:][:,kept_nuis]])
 zz=np.column_stack([Zr[:,:3],Zr[:,3:][:,kept_nuis]])
 # REPRODUCTION GATE: the group interactions must nest the paper's original
 # pooled 2SLS specification on the exact same 2,682,330 exposure rows.
 # Verify score scaling, FE definitions and controls BEFORE estimating subgroup effects.
 # The paper's pooled specification has no PG/PC subgroup indicators.
 # Those appear only in the new heterogeneity model. Drop them during
 # calibration, retaining precisely the original pre-exposure controls.
 paper_nuis=[j for j,orig in enumerate(kept_nuis) if orig>=2]
 xp=np.column_stack([np.sum(xx[:,:3],axis=1),xx[:,3:][:,paper_nuis]])
 zp=np.column_stack([np.sum(zz[:,:3],axis=1),zz[:,3:][:,paper_nuis]])
 try:
  bp=np.linalg.solve(zp.T@xp,zp.T@yy)
  bo=np.linalg.solve(xp.T@xp,xp.T@yy)
  wr=xp[:,1:]
  if wr.shape[1]:
   gram=wr.T@wr
   dres=xp[:,0]-wr@np.linalg.solve(gram,wr.T@xp[:,0])
   zres=zp[:,0]-wr@np.linalg.solve(gram,wr.T@zp[:,0])
  else:
   dres=xp[:,0];zres=zp[:,0]
  firststage=100.0*float(np.dot(zres,dres)/np.dot(zres,zres))
  cal={'paper_2SLS_pp':0.295,'paper_OLS_pp':0.382,'paper_first_stage_pp_per_SD':6.912,
       'actual_2SLS_pp':float(bp[0]),'actual_OLS_pp':float(bo[0]),
       'actual_first_stage_pp_per_SD':firststage,
       'score_column':args.score_col,'n_exposures':n}
  cal['calibration_pass']=bool(abs(cal['actual_2SLS_pp']-0.295)<0.035 and
       abs(cal['actual_OLS_pp']-0.382)<0.055 and abs(firststage-6.912)<0.40)
 except (np.linalg.LinAlgError,ZeroDivisionError,ValueError) as err:
  cal={'calibration_pass':False,'error':str(err),'n_exposures':n}
 if not cal['calibration_pass'] and not getattr(args, 'synthetic_test', False):
  return [],{},cal
 # Both matrices are square-identified: Z'X is invertible under relevance.
 ZX=zz.T@xx
 ss=np.sqrt(np.maximum(1e-20,np.diag(zz.T@zz)))
 ssx=np.sqrt(np.maximum(1e-20,np.diag(xx.T@xx)))
 if np.linalg.matrix_rank(ZX/ss[:,None]/ssx[None,:],tol=1e-9)!=len(ZX):
  raise ValueError('IV cross-moment not full rank: weak/unsupported group first stage')
 beta=np.linalg.solve(ZX,zz.T@yy)
 residual=yy-xx@beta
 rawscores=zz*residual[:,None]
 if args.recipient_col not in df or args.opponent_col not in df:
  raise ValueError('Original IV role identifiers required for shared-account covariance')
 meat,clusters=moment_union_account_date(rawscores,
         df[args.recipient_col].astype(str).to_numpy(),
         df[args.opponent_col].astype(str).to_numpy(),
         df[args.date_col].astype(str).to_numpy())
 bread=np.linalg.inv(ZX)
 cov=bread@meat@bread.T
 # Check fitted covariance symmetry/numerical variance on focal effects.
 cov=(cov+cov.T)/2
 if min(np.diag(cov)[:3])<0:raise ValueError('IV covariance invalid for focal effects')
 # Joint group-specific first stages from the exactly same partialled data.
 fstage=np.linalg.lstsq(zz,Xr[:,:3],rcond=1e-12)[0]
 rows=[]
 for j,group in enumerate(GRPS):
  se=math.sqrt(max(0,cov[j,j]));p1=float(fstage[j,j]);
  rows.append(dict(group=group,estimate_2sls_pp=float(beta[j]),SE_shared_account_date_CR0_pp=se,
     CI95_low=float(beta[j]-1.96*se),CI95_high=float(beta[j]+1.96*se),
     score_first_stage_native_scale=p1,n_exposures=n,
     covariance='role-or-date CR0 including dyad and role-date intersections',
     caveat='No weak-IV robust group-specific AR inversion; left-censored prior history',
     omitted_nuisance=';'.join(x['regressor'] for x in drops)))
 return rows,clusters,cal

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--mode',choices=['matched','iv'],required=True)
 p.add_argument('--grouped-exposures',required=True,help='Private Parquet from build_e_groups.py')
 p.add_argument('--out',required=True)
 p.add_argument('--controls',required=True,help='Comma-separated original matched 13 vars or IV pre-exposure controls; original field names')
 p.add_argument('--receipt-col',default='receipt')
 p.add_argument('--zero-outcome-col',default='later_grant_zero')
 p.add_argument('--conditional-outcome-col',default='later_grant_conditional')
 p.add_argument('--month-col',default='exposure_month')
 p.add_argument('--cell-col',default='exposure_cell')
 p.add_argument('--weight-col',default='matching_weight')
 p.add_argument('--opponent-col',default='exposure_opponent_user_id')
 p.add_argument('--recipient-col',default='recipient_user_id')
 p.add_argument('--score-col',default='opponent_score')
 p.add_argument('--date-col',default='exposure_utc_date')
 p.add_argument('--hour-col',default='exposure_hour_of_week')
 p.add_argument('--expected',type=int,default=0,help='0 selects frozen 2110400 matched or 2682330 IV')
 a=p.parse_args();root=Path(a.out);root.mkdir(parents=True,exist_ok=False)
 pub=root/'public';priv=root/'private';pub.mkdir();priv.mkdir()
 controls=[x.strip() for x in a.controls.split(',') if x.strip()]
 if not controls:raise ValueError('Exact original controls must be supplied')
 try:
  import duckdb
  cn=duckdb.connect(':memory:')
  path=Path(a.grouped_exposures)
  if not path.is_file():raise FileNotFoundError(path)
  source="read_parquet("+"'"+str(path).replace("'","''")+"'"+")"
  cols=[x[0] for x in cn.execute('DESCRIBE SELECT * FROM '+source+' LIMIT 0').fetchall()]
  need=['experience_group',a.receipt_col,a.zero_outcome_col,a.cell_col,a.opponent_col]+controls
  if a.mode=='matched':need+=[a.conditional_outcome_col,a.weight_col,a.month_col]
  else:need+=[a.score_col,a.date_col,a.hour_col,a.recipient_col]
  missing=[x for x in need if x not in cols]
  if missing:raise ValueError(f'E mode {a.mode}: missing original cohort fields {missing}; available {cols[:140]}')
  needed_rows=a.expected or (2110400 if a.mode=='matched' else 2682330)
  count=cn.execute('SELECT COUNT(*) FROM '+source).fetchone()[0]
  if count!=needed_rows:raise ValueError(f'Wrong {a.mode} cohort: {count:,} rows; required {needed_rows:,}')
  # One and only one row per index exposure, verified upstream; output stays aggregate.
  if 'exposure_game_id' in cols:
   unique=cn.execute('SELECT COUNT(DISTINCT exposure_game_id) FROM '+source).fetchone()[0]
   if unique < count:
    # IV may include same game as exposure for different recipients? opposite role not in main
    raise ValueError('Duplicate exposure game_id in cohort; cannot infer original exposure identity')
  df=cn.execute('SELECT '+','.join('"'+x.replace('"','""')+'"' for x in dict.fromkeys(need))+' FROM '+source).fetchdf()
  for k in [a.cell_col,a.opponent_col] + ([a.recipient_col,a.date_col,a.hour_col] if a.mode=='iv' else []):
   if df[k].isna().any():raise ValueError('Missing identifying or fixed-effect key: '+k)
  counts=df.groupby('experience_group',observed=True).agg(n=(a.receipt_col,'size'),receipts=(a.receipt_col,'sum'),
      later_grants=(a.zero_outcome_col,'sum')).reset_index()
  if set(counts.experience_group)!=set(GRPS):
   raise ValueError('Not all 3 mutually exclusive prior-experience groups appear in verified cohort')
  counts.to_csv(pub/'tabE0_groups.csv',index=False)
  if a.mode=='matched':
   announce('E primary matched: interactions on complete 90-day windows')
   rows=matched_model(df,a.zero_outcome_col,controls,a)
   observed=df[a.conditional_outcome_col].notna()
   n=int(observed.sum())
   if n!=993762:raise ValueError(f'Conditional later-choice cohort mismatch: {n:,} vs 993,762')
   announce('E primary matched: interactions on later-choice subset')
   rows+=matched_model(df.loc[observed].copy(),a.conditional_outcome_col,controls,a)
   pd.DataFrame(rows).to_csv(pub/'tabE1_receipt_by_prior.csv',index=False)
   status='E_MATCHED_INTERACTIONS_COMPLETE'
  else:
   announce('E secondary IV: interacting original score and receipt by prior-experience group')
   rows,cov_info,cal=iv_model(df,a,controls)
   (pub/'tabE_primary_calibration.json').write_text(json.dumps(cal,indent=2)+'\n')
   if not cal['calibration_pass']:
    (pub/'_CALIBRATION_FAILED.json').write_text(json.dumps({'status':'E_POOLED_REPRODUCTION_FAILED',
       'reason':'Original pooled IV must reproduce before interpreting groups'},indent=2)+'\n')
    raise ValueError('Original IV pooled first stage/OLS/2SLS failed reproducibility gate; see public calibration JSON')
   pd.DataFrame(rows).to_csv(pub/'tabE2_iv_by_prior.csv',index=False)
   (pub/'tabE2_covariance_group_counts.json').write_text(json.dumps(cov_info,indent=2)+'\n')
   status='E_IV_GROUP_WALD_ONLY_CALIBRATED'
  (pub/'_SUCCESS.json').write_text(json.dumps({'status':status,'exposures':count,
     'input_signature':'original frozen cohort must be verified against original receipt/provenance before manuscript use',
     'model_controls':controls,'note':'Groups are left-censored by November 2023 start; E IV lacks group-specific AR robustness and requires assessment of weak support'},indent=2)+'\n')
  announce('E '+a.mode+' regression complete: '+str(pub))
 except Exception:
  (priv/'FAILED.txt').write_text(traceback.format_exc());raise
if __name__=='__main__':main()
