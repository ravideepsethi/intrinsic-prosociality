#!/usr/bin/env python3
"""Synthetic correctness checks. No production data and no empirical findings."""
from __future__ import annotations
import tempfile
from pathlib import Path
import numpy as np, pandas as pd
from scipy import sparse
from scipy.special import expit, logsumexp
from model import objective,components,unpack,fit_encoder,encode,arrays,save_arrays,load_arrays,predict,eb_baseline
from util import ready,certify,require

def main():
    rng=np.random.default_rng(44);N=7;R=60;P=3;K=3
    d=dict(X=sparse.csr_matrix(rng.normal(size=(R,P))),ids=np.arange(R)%N,F=rng.integers(0,2,R).astype(float),
      n=rng.integers(1,4,R).astype(float),g=np.zeros(R),N=N)
    d['g']=rng.binomial(d['n'].astype(int),.1).astype(float)
    for heterogeneous in [False,True]:
        width=K if heterogeneous else 1
        v=np.r_[[-5.,-3.,-1.],np.ones(width),rng.normal(0,.1,P),[-.6,-1.2]]
        f,g=objective(v,d,K,heterogeneous)
        numeric=[]
        for j in range(len(v)):
            dv=np.zeros(len(v));dv[j]=1e-5
            numeric.append((objective(v+dv,d,K,heterogeneous)[0]-objective(v-dv,d,K,heterogeneous)[0])/2e-5)
        require(np.max(np.abs(g-numeric))<1e-6,'Analytic panel-mixture gradient failed')
        # Explicit account-level likelihood: do NOT mix independently per row.
        a,t,b,lp=unpack(v,P,K,heterogeneous);manual=[]
        for i in range(N):
            sel=d['ids']==i;xx=d['X'][sel]@b
            terms=[lp[k]+np.sum(d['g'][sel]*(xx+a[k]+t[k]*d['F'][sel])-d['n'][sel]*np.logaddexp(0,xx+a[k]+t[k]*d['F'][sel])) for k in range(K)]
            manual.append(logsumexp(terms))
        require(np.allclose(components(v,d,K,heterogeneous)[2],manual),'Account likelihood aggregation failed')
    vl=np.r_[[-5.,-3.,-1.],[1.3],np.zeros(P),[-.6,-1.2]]
    vh=np.r_[[-5.,-3.,-1.],[1.3]*3,np.zeros(P),[-.6,-1.2]]
    require(np.allclose(objective(vl,d,3,False)[0],objective(vh,d,3,True)[0]),'Nested models differ when slopes equal')
    with tempfile.TemporaryDirectory() as td:
        path=Path(td)/'data.npz';save_arrays(path,d);copy=load_arrays(path)
        require(np.allclose(objective(vh,d,3,True)[0],objective(vh,copy,3,True)[0]),'Array roundtrip failed')
        certify(path,'fixture');require(ready(path,'fixture'),'Checkpoint reuse failed')
        failed=False
        try:ready(path,'different')
        except RuntimeError:failed=True
        require(failed,'Wrong-configuration checkpoint accepted')
        path.write_bytes(path.read_bytes()+b'changed')
        failed=False
        try:ready(path,'fixture')
        except RuntimeError:failed=True
        require(failed,'Mutated checkpoint accepted')
    # Honest future prediction: future outcomes cannot alter first-year posterior or probabilities.
    fit=dict(parameters=vh.tolist(),K=3,heterogeneous=True)
    p1,j1,q1=predict(fit,d,d)
    changed=dict(d,g=d['n']-d['g'])
    p2,j2,q2=predict(fit,d,changed)
    require(np.array_equal(p1,p2) and np.array_equal(q1,q2),'Holdout outcomes leaked into prediction')
    require(not np.allclose(j1,j2),'Scoring ignored outcomes')
    # Smoothed baseline includes all-zero histories and no-cell histories.
    tr=pd.DataFrame({'chooser':[0,0,1,1,2,2],'competitive':[0,1]*3,'cell':[5,21]*3,'n':[4,6]*3,'g':[0,0,0,1,0,0]})
    te=pd.DataFrame({'chooser':[2,0,1],'competitive':[1,0,1],'cell':[21,7,16],'n':[1]*3,'g':[0,1,0]})
    pred,priors=eb_baseline(tr,te)
    require(np.isfinite(pred).all() and ((pred>0)&(pred<1)).all(),'All-zero histories not smoothed')
    print('SYNTHETIC_SELF_TEST_OK: gradients, panel likelihood, nesting, checkpoints, holdout isolation, smoothed baseline.',flush=True)

if __name__=='__main__':main()
