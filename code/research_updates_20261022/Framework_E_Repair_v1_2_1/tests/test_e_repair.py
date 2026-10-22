"""Pure synthetic checks for the v1.2.1 E numerical repair (no private rows)."""
import math
from types import SimpleNamespace
import numpy as np
import pandas as pd
from run_e_estimates import absorb_multi,iv_model,moment_union_account_date

rng=np.random.default_rng(44021)
# Test exact FWL numerics against dense dummy least squares on small problem.
n=1200
codes=[rng.integers(0,19,n),rng.integers(0,27,n),rng.integers(0,7,n)]
a=np.column_stack([rng.normal(size=n),rng.normal(size=n),rng.normal(size=n)])
a[:,0]+=codes[0]*.15 + codes[1]*.02
out=absorb_multi(a,codes,np.ones(n),max_rounds=350,atol=1e-8)
fe=np.concatenate([(codes[j][:,None]==np.arange(g)[None,:]).astype(float)
                   for j,g in enumerate([19,27,7])],axis=1)
ref=a-fe@np.linalg.lstsq(fe,a,rcond=1e-12)[0]
err=np.max(np.abs(ref-out))
assert err<1e-5,err
for c in codes:
 assert np.max(np.abs(np.bincount(c,weights=out[:,0])/np.bincount(c)))<1e-6
print('PASS sparse CG residualization reproduces dense dummy projection',err)

# Month-nested assignment and dates, plus cross-month hour-of-week FE.
n=21000
month=rng.integers(0,10,n)
cell=month*21+rng.integers(0,21,n)
date=month*30+rng.integers(0,30,n)
how=rng.integers(0,168,n)
inputs=np.column_stack([rng.normal(size=n),100.*rng.binomial(1,.07,n),
                        rng.normal(size=n)*1e6+1e8,
                        rng.integers(0,2,n).astype(float)])
R=absorb_multi(inputs,[cell,date,how],np.ones(n),max_rounds=500,atol=2e-7)
for c in (cell,date,how):
 for j in range(inputs.shape[1]):
  err=np.max(np.abs(np.bincount(c,weights=R[:,j])/np.bincount(c)))
  assert err<=2e-7*max(1,float(np.std(inputs[:,j])))+1e-6, (j,err)
print('PASS nested-month fixed effects with multiscale controls')

# Verify overlap covariance against O(n^2) direct cluster-pair enumeration.
r=np.array(['a','a','b','e','a','e','g','c'])
o=np.array(['b','c','c','a','e','c','a','g'])
d=np.array(['d1','d2','d1','d3','d1','d2','d3','d1'])
scores=rng.normal(size=(8,3))
actual,_=moment_union_account_date(scores,r,o,d)
wanted=np.zeros((3,3))
for i in range(8):
 for j in range(8):
  if d[i]==d[j] or ({r[i],o[i]}&{r[j],o[j]}):
   wanted+=np.outer(scores[i],scores[j])
assert np.max(np.abs(actual-wanted))<1e-10
print('PASS role/date union CR0 covariance')

# Entire subgroup-IV algebra with simulation. Benchmark intentionally fails
# because these are not real-paper coefficients, so synthetic_test=True.
n=6600
GP=rng.choice(['PG','PC','NC'],n,p=[.12,.54,.34])
Z=rng.normal(size=n)
D=(rng.random(n)<1/(1+np.exp(-(-2.4+.8*Z)))).astype(int)
cell=rng.choice([f'cell{i}' for i in range(110)],n)
date=rng.choice([f'day{i}' for i in range(70)],n)
hour=rng.choice([f'h{i}' for i in range(60)],n)
pr=np.clip(.019+(.085*(GP=='PG'))+D*(.002+.004*(GP=='PG')),.001,.95)
y=rng.binomial(1,pr,size=n)
df=pd.DataFrame(dict(experience_group=GP,receipt=D,exposure_cell=cell,
 exposure_month='2024-08',later_grant_zero=y,exposure_utc_date=date,exposure_hour_of_week=hour,
 opponent_score=Z, exposure_opponent_user_id=[f'opp{i}' for i in rng.integers(0,3500,n)],
 recipient_user_id=[f'rec{i}' for i in rng.integers(0,4200,n)],env1=rng.normal(size=n)))
a=SimpleNamespace(receipt_col='receipt',month_col='exposure_month',
 cell_col='exposure_cell',opponent_col='exposure_opponent_user_id',score_col='opponent_score',
 zero_outcome_col='later_grant_zero',date_col='exposure_utc_date',hour_col='exposure_hour_of_week',
 recipient_col='recipient_user_id',synthetic_test=True)
rows,clusters,cal=iv_model(df,a,['env1'])
assert len(rows)==3,len(rows)
assert len(cal['subgroup_contrasts'])==3
assert all(np.isfinite([r['estimate_2sls_pp'],r['SE_shared_account_date_CR0_pp']]).all() for r in rows)
print('PASS E three-group IV, pooled calibration, joint contrasts and shared-role/date covariance')
