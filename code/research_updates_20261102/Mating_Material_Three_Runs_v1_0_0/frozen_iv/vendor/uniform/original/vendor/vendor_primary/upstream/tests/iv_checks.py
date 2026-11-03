import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import tempfile
from local_common import *
import iv_followups as iv
from cutoffs import spacing

rng=np.random.default_rng(31);n=1200;g=[rng.integers(0,15,n),rng.integers(0,8,n)]
controls=rng.normal(size=(n,4));targets=rng.normal(size=(n,3))+controls@rng.normal(size=(4,3))
work=np.array(np.column_stack([targets,controls]),order='F')
actual,rank,diag=iv.models.project(work,g,3)
Z=np.column_stack([np.ones(n),np.eye(15)[g[0],1:],np.eye(8)[g[1],1:],controls])
expected=targets-Z@np.linalg.lstsq(Z,targets,rcond=None)[0]
np.testing.assert_allclose(actual,expected,atol=2e-7)
feonly,rank,diag=iv.project_targets(np.array(targets,order='F'),g,3)
F=Z[:,:-4];expected_fe=targets-F@np.linalg.lstsq(F,targets,rcond=None)[0]
np.testing.assert_allclose(feonly,expected_fe,atol=2e-7);assert rank==0

# Verify the OR covariance against the pairwise dependence definition, not a
# one-way or naive sum of account and date cluster variances.
n=45;recipient=rng.integers(0,12,n);opponent=rng.integers(12,24,n);opponent[:20]=rng.integers(0,12,20)
opponent=np.where(opponent==recipient,opponent+24,opponent);dates=rng.integers(0,7,n);score=rng.normal(size=(n,4))
actors=dict(recipient_id=recipient,opponent_id=opponent,date=dates)
actual=iv.meat_for(actors)(score);dense=np.zeros((4,4))
for i in range(n):
    for j in range(n):
        if dates[i]==dates[j] or set([recipient[i],opponent[i]])&set([recipient[j],opponent[j]]):dense+=np.outer(score[i],score[j])
np.testing.assert_allclose(actual,dense,atol=1e-10)

person=np.array([1,1,1,2]);start=np.array([0,10,100,0])*DAY;anchor=start+DAY
# The minimum-three row can start a window; do not recover it by filtering S0.
low=spacing(person,start,anchor,np.array([True,True,True,True]));high=spacing(person,start,anchor,np.array([False,True,True,True]))
np.testing.assert_array_equal(low,[1,0,1,1]);np.testing.assert_array_equal(high,[0,1,0,1])

# Published reference fields differ for IV versus FS/RF; exercise all six gates.
for column,level in [(3,'X0'),(4,'X0_ENV_indicator')]:
    refs=[r for r in load(ROOT/'vendor/r9b/evidence/A_receipt.json') if r['control_level']==level and r['cohort']=='full']
    row={}
    for kind,k1,k2 in [('first_stage','first_stage','first_stage_se'),('reduced_form','reduced_form','reduced_form_se'),('2SLS','iv','iv_se')]:
        r=next(r for r in refs if r['estimator']==kind and r.get('outcome') in ['received','y'])
        row[k1]=r['iv_coefficient_pp' if kind=='2SLS' else 'coefficient_pp'];row[k2]=r['iv_standard_error_pp' if kind=='2SLS' else 'standard_error_pp']
    iv.reproduce(row,column)
print('IV projection, shared-account-OR-date covariance, spacing, and reference gates passed')
