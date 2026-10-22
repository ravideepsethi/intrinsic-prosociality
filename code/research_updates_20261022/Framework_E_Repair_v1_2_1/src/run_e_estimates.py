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

class _FECG:
 """Matrix-free preconditioned conjugate gradient for multiple categorical FEs.

 The normal equations F'F b = F'x are singular because categorical
 intercepts overlap. With a zero starting vector and RHS in range(F'),
 preconditioned CG recovers the unique fitted value F b. A direct check
 of weighted mean residuals in *every* FE level certifies the projection.
 No SciPy and no dense dummy matrix are needed.
 """
 def __init__(self, codes, weights):
  self.codes=[np.asarray(c,dtype=np.int64) for c in codes]
  self.weights=np.asarray(weights,dtype=np.float64)
  self.n=len(self.weights)
  if not np.allclose(self.weights,1.,rtol=0.,atol=0.):
   raise ValueError('IV repair CG implements the paper unweighted projection only')
  if any(len(c)!=self.n or np.any(c<0) for c in self.codes):
   raise ValueError('Invalid HDFE codes')
  self.sizes=[int(c.max()+1) for c in self.codes]
  self.offsets=np.cumsum([0]+self.sizes).tolist()
  self.diag=np.concatenate([np.bincount(c,minlength=g).astype(float)
                            for c,g in zip(self.codes,self.sizes)])
  if np.any(self.diag<=0):raise ValueError('HDFE has zero-count levels')
 def forward(self, b):
  out=np.zeros(self.n,dtype=np.float64)
  for code,start,end in zip(self.codes,self.offsets[:-1],self.offsets[1:]):
   out+=b[start:end][code]
  return out
 def adjoint(self,v):
  return np.concatenate([np.bincount(c,weights=v,minlength=g)
                         for c,g in zip(self.codes,self.sizes)])
 def max_fe_mean(self,v):
  return max(float(np.max(np.abs(np.bincount(c,weights=v,minlength=g)/
                                   self.diag[start:end])))
             for c,g,start,end in zip(self.codes,self.sizes,
                                      self.offsets[:-1],self.offsets[1:]))
 def solve_one(self,y,tol=2e-7,maxiter=700):
  # Center and scale to remove the catastrophic scale differences between
  # squared rating-gap controls, receipt indicators, and outcome in pp.
  mean=float(np.mean(y));scale=max(1.,float(np.std(y)))
  z=(np.asarray(y,dtype=np.float64)-mean)/scale
  rhs=self.adjoint(z)
  b=np.zeros(len(self.diag),dtype=np.float64)
  r=rhs.copy();pr=r/self.diag
  direction=pr.copy();rpr=float(r@pr)
  k=0
  if self.max_fe_mean(z)>tol:
   for k in range(1,maxiter+1):
    Ap=self.adjoint(self.forward(direction))
    den=float(direction@Ap)
    if not np.isfinite(den) or den<=0:
     raise ValueError(f'CG HDFE numerical breakdown at iteration {k}; normal-equation denominator={den}')
    alpha=rpr/den
    b+=alpha*direction
    r-=alpha*Ap
    if np.max(np.abs(r/self.diag))<tol*0.35:
     # Recursive conjugate-gradient residual can underestimate actual error.
     # Validate against F'(y-Fb) rather than relying only on the recurrence.
     trial=z-self.forward(b)
     actual=self.max_fe_mean(trial)
     if actual<tol:break
     r=self.adjoint(trial)
    newpr=r/self.diag;newrpr=float(r@newpr)
    if newrpr<=0 or not np.isfinite(newrpr):
     raise ValueError('CG HDFE lost positive residual norm')
    direction=newpr+(newrpr/rpr)*direction
    rpr=newrpr
   else:
    err=self.max_fe_mean(z-self.forward(b))
    raise ValueError(f'CG HDFE did not converge in {maxiter} iterations; maximal FE level mean={err:.3g} (standardized), tolerance={tol:.3g}')
  residual=(z-self.forward(b))*scale
  # Constant mean is in the span of each categorical FE. Never add it back.
  err=self.max_fe_mean(residual)/scale
  if err>tol:
   raise ValueError(f'CG HDFE failed direct residual mean check: {err:.3g}>{tol:.3g}')
  return residual,k,err

def absorb_multi(mat,codes,weights,max_rounds=700,atol=2e-7):
 """Convergence-verified unweighted FE projection, one column at a time.

 Returns the joint projection for y, all endogenous/exogenous controls, and
 instruments using the same FEs. Stores no dense dummy matrix. Unlike the
 earlier 65-sweep alternating projector, checks the actual FE level means.
 """
 raw=np.asarray(mat,dtype=np.float64)
 if raw.ndim!=2 or not np.isfinite(raw).all():
  raise ValueError('HDFE input must be a finite 2-dimensional matrix')
 fe=_FECG(codes,weights)
 out=np.empty_like(raw)
 for j in range(raw.shape[1]):
  out[:,j],iters,err=fe.solve_one(raw[:,j],tol=atol,maxiter=max_rounds)
  if (j+1)%4==0 or j+1==raw.shape[1]:
   announce(f'[E HDFE] {j+1}/{raw.shape[1]} columns; latest PCG iterations={iters}; maximal standardized FE mean={err:.2g}')
 return out

def moments(score, labels):
 codes=factor(labels);order=np.argsort(codes,kind='mergesort')
 st=np.r_[0,1+np.flatnonzero(codes[order][1:]!=codes[order][:-1])]
 sums=np.add.reduceat(score[order],st,axis=0)
 return sums.T@sums, len(st)

def moment_union_account_date(scores,rec,opp,date):
 """Exact role-or-date CR0 with compressed integer cluster identifiers.

 An observation pair belongs in the meat once if its two games share *any*
 account in either role OR the UTC exposure date. Inclusion-exclusion:
 account - unordered dyad + date - account/date + dyad/date.
 All integer pair encodings are checked for 64-bit overflow and used only
 inside this private computation, never exported.
 """
 n,p=scores.shape
 r=np.asarray(rec);o=np.asarray(opp);d=np.asarray(date)
 if not(len(r)==len(o)==len(d)==n):raise ValueError('Account/date arrays have inconsistent lengths')
 # One identity universe across both roles, and a separate date universe.
 a=pd.factorize(np.r_[r,o],sort=False)[0].astype(np.int64)
 ra=a[:n];oa=a[n:]
 if np.any(ra==oa):raise ValueError('Self-paired exposure found')
 dates=pd.factorize(d,sort=False)[0].astype(np.int64)
 A=int(a.max()+1);T=int(dates.max()+1)
 if int(A)*int(A)*int(T) >= np.iinfo(np.int64).max:
  raise OverflowError('Pair/date integer encoding cannot be formed without overflow')
 def gram_by_group(group, size, v):
  sums=np.column_stack([np.bincount(group,weights=v[:,j],minlength=size)
                        for j in range(p)])
  return sums.T@sums
 acc=np.column_stack([np.bincount(ra,weights=scores[:,j],minlength=A)+
                      np.bincount(oa,weights=scores[:,j],minlength=A)
                      for j in range(p)])
 MA=acc.T@acc
 lo=np.minimum(ra,oa);hi=np.maximum(ra,oa)
 pairkey=lo*A+hi
 pairs,npairs=pd.factorize(pairkey,sort=False);npairs=len(npairs)
 MP=gram_by_group(pairs,npairs,scores)
 MD=gram_by_group(dates,T,scores)
 # Each account can occupy either role on an account/date intersection.
 adkey=np.r_[ra*T+dates,oa*T+dates]
 ad,unq=pd.factorize(adkey,sort=False);nad=len(unq)
 AD=np.column_stack([np.bincount(ad[:n],weights=scores[:,j],minlength=nad)+
                     np.bincount(ad[n:],weights=scores[:,j],minlength=nad)
                     for j in range(p)])
 MAD=AD.T@AD
 pairdatekey=pairkey*T+dates
 pdgroup,unqpd=pd.factorize(pairdatekey,sort=False)
 MPD=gram_by_group(pdgroup,len(unqpd),scores)
 meat=MA-MP+MD-MAD+MPD
 return (meat+meat.T)/2, dict(unique_accounts=A,pairs=npairs,dates=T,
                                  account_dates=nad,pair_dates=len(unqpd))

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

def _partial_out(y,d,z,controls,names,protected=()):
 """Stable Frisch-Waugh-Lovell for a few residualized nuisance controls.

 Scale by L2 norm BEFORE rank selection; source columns include squared rating
 gap, which otherwise causes small binary controls to be pruned spuriously.
 Returns outcomes/endogenous/excluded instruments jointly partialled out of W.
 """
 from methods import choose_within_identified
 w=np.asarray(controls,dtype=np.float64)
 if w.ndim!=2:raise ValueError('Nuisance design must be a matrix')
 if w.shape[1]:
  norms=np.linalg.norm(w,axis=0)
  positive=norms>1e-11
  wscaled=w/np.maximum(norms,1e-20)[None,:]
  keep,drop=choose_within_identified(wscaled.T@wscaled,names,
                protected=lambda q:q in protected,relative_tol=1e-9)
  if any(i not in keep for i,name in enumerate(names) if name in protected):
   raise ValueError('Substantive group main effect was dropped')
  W=wscaled[:,keep]
 else:
  W=w;drop=[]
 B=np.column_stack([y,d,z])
 if W.shape[1]:
  gram=W.T@W;eig=np.linalg.eigvalsh((gram+gram.T)/2)
  if eig[0]<1e-11*eig[-1]:
   raise ValueError(f'FWL nuisance controls near-singular after rank selection; min eigenvalue {eig[0]}')
  fit=W@np.linalg.solve(gram,W.T@B)
  residual=B-fit
  # W moment condition, normalized by column and B magnitude.
  rel=np.linalg.norm(W.T@residual,axis=0)/np.maximum(1.,np.linalg.norm(B,axis=0))
  if max(rel)>3e-8:
   raise ValueError(f'FWL exogenous orthogonality failed: {max(rel):.2g}')
 else:residual=B
 n_d=d.shape[1];n_z=z.shape[1]
 return residual[:,0],residual[:,1:1+n_d],residual[:,1+n_d:1+n_d+n_z],drop

def _just_identified(y,d,z,check=True):
 ZX=z.T@d;Zy=z.T@y
 sd=np.sqrt(np.maximum(1e-30,np.diag(d.T@d)))
 sz=np.sqrt(np.maximum(1e-30,np.diag(z.T@z)))
 ZXunit=ZX/sz[:,None]/sd[None,:]
 singular=np.linalg.svd(ZXunit,compute_uv=False)
 if singular[-1]<max(1e-10,1e-6*singular[0]):
  raise ValueError(f'Weak/rank-deficient group IV cross moment: singular values={singular}')
 beta=np.linalg.solve(ZX,Zy)
 return beta, ZX, singular

def iv_model(df,args,controls):
 n=len(df)
 score=pd.to_numeric(df[args.score_col],errors='coerce').to_numpy(dtype=float)
 if not np.isfinite(score).all():raise ValueError('Original historical score missing or unsupported')
 X,names=build_design(df,'iv',args.receipt_col,controls,args.month_col)
 group=df.experience_group.astype(str).to_numpy()
 Z=X.copy()
 for j,grp in enumerate(GRPS): Z[:,j]=score*(group==grp)
 y=100*pd.to_numeric(df[args.zero_outcome_col],errors='coerce').to_numpy(dtype=float)
 if not np.isfinite(y).all() or not np.isin(y,[0.,100.]).all():
  raise ValueError('IV zero-coded later-grant outcome must be binary 0/1')
 codes=[factor(df[args.cell_col]),factor(df[args.date_col]),factor(df[args.hour_col])]
 source=np.column_stack([y,X,Z[:,:3]])
 announce('E IV: CG-based exact projection on 4,324 assignment cells, UTC dates, hour-of-week')
 width=X.shape[1]
 projected=absorb_multi(source,codes,np.ones(n))
 yy=projected[:,0];xx=projected[:,1:1+width]
 zz=projected[:,1+width:]
 del source,X,Z
 # Paper calibration uses ONE instrument and ONE treatment, no experience main
 # effects: these are introduced only for new heterogeneous IV estimates.
 y0,d0,z0,dropped0=_partial_out(yy,xx[:,:3].sum(axis=1).reshape(-1,1),
     zz.sum(axis=1).reshape(-1,1),xx[:,5:],names[5:])
 pooled_zd=float(z0[:,0]@d0[:,0]);pooled_zz=float(z0[:,0]@z0[:,0]);pooled_dd=float(d0[:,0]@d0[:,0])
 if min(abs(pooled_zd),pooled_zz,pooled_dd)<1e-12:
  raise ValueError('No identified pooled first stage after the original controls')
 pi=100*pooled_zd/pooled_zz
 iv=float((z0[:,0]@y0)/pooled_zd)
 ols=float((d0[:,0]@y0)/pooled_dd)
 cal={'paper_2SLS_pp':0.295,'paper_OLS_pp':0.382,'paper_first_stage_pp_per_SD':6.912,
      'actual_2SLS_pp':iv,'actual_OLS_pp':ols,'actual_first_stage_pp_per_SD':pi,
      'score_column':args.score_col,'n_exposures':n,
      'original_control_drops':dropped0,'HDFE_method':'matrix-free preconditioned CG; every level mean certified',
      'pooled_identification':{'Z_D':pooled_zd,'Z_Z':pooled_zz,'D_D':pooled_dd}}
 cal['calibration_pass']=bool(abs(iv-0.295)<0.035 and abs(ols-0.382)<0.055 and abs(pi-6.912)<0.40)
 announce('[E calibration] pooled first stage %.4f pp/SD, OLS %.4f pp, IV %.4f pp; pass=%s' %
          (pi,ols,iv,cal['calibration_pass']))
 if not cal['calibration_pass'] and not getattr(args,'synthetic_test',False):
  return [],{},cal
 # Retain group main effects and other controls for the new test, just as the
 # initial heterogeneity design prescribed. All three D/Z interactions protected.
 yh,dh,zh,drops=_partial_out(yy,xx[:,:3],zz,xx[:,3:],names[3:],protected=('prior_PG','prior_PC'))
 beta,ZX,sing=_just_identified(yh,dh,zh)
 residual=yh-dh@beta
 rawscores=zh*residual[:,None]
 if args.recipient_col not in df or args.opponent_col not in df:
  raise ValueError('Original IV role identifiers required for shared-account covariance')
 meat,clusters=moment_union_account_date(rawscores,
      df[args.recipient_col].astype(str).to_numpy(),
      df[args.opponent_col].astype(str).to_numpy(),
      df[args.date_col].astype(str).to_numpy())
 # Beta=(Z'D)^{-1} Z'y. Score meat is in instrument-equation order.
 bread=np.linalg.inv(ZX)
 cov=bread@meat@bread.T
 cov=(cov+cov.T)/2
 if np.min(np.diag(cov))<0:raise ValueError('IV covariance negative for focal effects')
 first=np.linalg.solve(zh.T@zh,zh.T@dh)
 rows=[]
 for j,grp in enumerate(GRPS):
  se=math.sqrt(max(0.,cov[j,j]))
  rows.append(dict(group=grp,estimate_2sls_pp=float(beta[j]),SE_shared_account_date_CR0_pp=se,
    CI95_low=float(beta[j]-1.96*se),CI95_high=float(beta[j]+1.96*se),
    first_stage_pp_per_reference_SD=float(100*first[j,j]),n_exposures=int(np.sum(group==grp)),
    group_receipts=int(np.sum((group==grp)&(df[args.receipt_col].to_numpy()==1))),
    covariance='role-or-date CR0 including dyad and role-date intersections',
    caveat='Wald-only; first stage is a joint-group partial slope; history left-censored',
    omitted_nuisance=';'.join(x['regressor'] for x in drops)))
 contrasts=[]
 for i,j in ((0,2),(0,1),(1,2)):
  diff=float(beta[i]-beta[j]);se=math.sqrt(max(0.,cov[i,i]+cov[j,j]-2*cov[i,j]))
  contrasts.append(dict(contrast=f'{GRPS[i]} minus {GRPS[j]}',estimate_pp=diff,SE_pp=se,
    CI95_low=diff-1.96*se,CI95_high=diff+1.96*se))
 # New subgroup comparisons need the JOINT covariance, not separate group SEs.
 cal['subgroup_contrasts']=contrasts
 cal['subgroup_first_stage_singular_values']=sing.tolist()
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
   pd.DataFrame(cal.get('subgroup_contrasts',[])).to_csv(pub/'tabE2_group_contrasts.csv',index=False)
   (pub/'tabE2_covariance_group_counts.json').write_text(json.dumps(cov_info,indent=2)+'\n')
   status='E_IV_GROUP_WALD_ONLY_CALIBRATED'
  (pub/'_SUCCESS.json').write_text(json.dumps({'status':status,'exposures':count,
     'input_signature':'original frozen cohort must be verified against original receipt/provenance before manuscript use',
     'model_controls':controls,'note':'Groups are left-censored by November 2023 start; E IV lacks group-specific AR robustness and requires assessment of weak support'},indent=2)+'\n')
  announce('E '+a.mode+' regression complete: '+str(pub))
 except Exception:
  (priv/'FAILED.txt').write_text(traceback.format_exc());raise
if __name__=='__main__':main()
