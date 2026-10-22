"""Run from package root via PYTHONPATH=src python3 tests/test_ae_synthetic.py.
Covers rank pruning, closed-form overlap covariance, matched subgroup regression,
IV subgroup machinery. Synthetic only. Does NOT certify real input lineage.
"""
import math
from types import SimpleNamespace
import numpy as np
import pandas as pd
from estimate_a import fit_cell_fe
from run_e_estimates import matched_model,iv_model,moment_union_account_date
from methods import choose_within_identified

rng=np.random.default_rng(2011)
X=rng.normal(size=(500,3))
X=np.column_stack([X,X[:,2]])
keep,drop=choose_within_identified(X.T@X,['focal1','focal2','control','duplicate'],protected=lambda s:s.startswith('focal'))
assert keep==[0,1,2] and len(drop)==1
print('PASS A/B/D identified rank pruning')

n=2600
c=rng.integers(0,13,size=n); a=rng.binomial(1,.35,size=n);b=rng.binomial(1,.12,size=n)
x=rng.normal(size=n)
pr=1/(1+np.exp(-(-3+1.1*a-.5*b+.1*x)))
df=pd.DataFrame(dict(cell=c,flag1=a,flag2=b,x=x,duplicate=x,patron=rng.binomial(1,pr,size=n)))
rows=fit_cell_fe(df,['flag1','flag2'],['x','duplicate'],'cell')
assert len(rows)==2 and all(np.isfinite(r['SE_matching_cell_pp']) for r in rows)
assert 'duplicate' in rows[0]['dropped_covariates']
print('PASS A flags-exclusion regression with redundant nuisance')

r=np.array(['a','a','b','e','a','e','g','c']);o=np.array(['b','c','c','a','e','c','a','g']);d=np.array(['d1','d2','d1','d3','d1','d2','d3','d1'])
s=np.arange(8*4).reshape(8,4)*.01
M,_=moment_union_account_date(s,r,o,d)
B=np.zeros_like(M)
for i in range(len(s)):
 for j in range(len(s)):
  if d[i]==d[j] or bool({r[i],o[i]}&{r[j],o[j]}): B+=np.outer(s[i],s[j])
assert np.max(np.abs(M-B))<1e-10
print('PASS E IV shared-role-or-date covariance inclusion-exclusion')

n=4000
GP=rng.choice(['PG','PC','NC'],n)
Z=rng.normal(size=n)
D=(rng.random(n)<1/(1+np.exp(-(-.8+.7*Z)))).astype(int)
cell=rng.choice([f'cell{i}' for i in range(30)],n)
date=rng.choice([f'day{i}' for i in range(20)],n)
hour=rng.choice([f'h{i}' for i in range(7)],n)
y=rng.binomial(1, np.clip(.035+.018*D+.006*(GP=='PG'),.001,.99), size=n)
DF=pd.DataFrame(dict(experience_group=GP,receipt=D,exposure_cell=cell,
 exposure_month=rng.choice(['2024-08','2024-09','2024-10'],n),
 later_grant_zero=y,exposure_utc_date=date,exposure_hour_of_week=hour,opponent_score=Z,
 exposure_opponent_user_id=[f'opp{i}' for i in rng.integers(0,400,n)],
 recipient_user_id=[f'rec{i}' for i in rng.integers(0,500,n)],
 matching_weight=rng.uniform(.5,2.,n),env1=rng.normal(size=n)))
a=SimpleNamespace(receipt_col='receipt',month_col='exposure_month',weight_col='matching_weight',
 cell_col='exposure_cell',opponent_col='exposure_opponent_user_id',score_col='opponent_score',
 zero_outcome_col='later_grant_zero',date_col='exposure_utc_date',hour_col='exposure_hour_of_week',
 recipient_col='recipient_user_id',synthetic_test=True)
matched=matched_model(DF,'later_grant_zero',['env1'],a)
assert len(matched)==3 and all(math.isfinite(q['clustered_se_pp']) for q in matched)
print('PASS E weighted matched-model group interactions')
IV,_,cal=iv_model(DF,a,['env1'])
assert not cal['calibration_pass']
assert len(IV)==3 and all(math.isfinite(q['SE_shared_account_date_CR0_pp']) for q in IV)
print('PASS E instrumented interactions and role/date robust covariance')
