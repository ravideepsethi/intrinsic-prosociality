#!/usr/bin/env python3
"""Numerical tests use invented observations, never paper estimates."""
from __future__ import annotations
import os
for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS'):
    os.environ[key]='1'
import tempfile
from pathlib import Path
import unittest
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from fe_engine import (Moments,make_design,groups,fit_models,score_block,finalize_models,
    iter_blocks,bin_axis,axis_definition,context_mask,nonsingletons,solve)


def synthetic(seed=2718,accounts=70):
    r=np.random.default_rng(seed);sizes=r.integers(7,22,accounts);sizes[:5]=1
    chooser=np.repeat(np.arange(accounts),sizes);n=len(chooser)
    gap=r.normal(0,255,n);K=np.exp(r.uniform(np.log(11.36),np.log(45),n))
    # Include heaped K and broad support without constructing any target result.
    K[r.random(n)<.35]=11.36
    crd=r.uniform(40,210,n);drd=r.uniform(40,210,n)
    payoff=K*(.5-1/(1+np.exp(gap/170)))
    y=(r.random(n)<(.04+.018*(chooser%3)+.02*(gap>150))).astype(int)
    frame=dict(chooser=chooser,y=y,gap=gap,payoff=payoff,K=K,
       board=r.integers(-99,101,n).astype(float),ply=r.integers(2,110,n).astype(float),
       crd=crd,drd=drd,cvol=r.uniform(.03,.095,n),dvol=r.uniform(.03,.095,n),
       month=r.integers(0,24,n),speed=r.integers(0,5,n))
    edges={k:sorted(set(np.quantile(K,np.arange(1,q)/q).tolist())) for k,q in [('k20',20),('k50',50)]}
    return frame,edges


class Checks(unittest.TestCase):
    def test_exact_fe_and_clustered_covariance(self):
        frame,edges=synthetic();mom=Moments(edges);mom.add(frame);models=fit_models(mom)
        score_block(frame,edges,models)
        _,_,_,arrays=finalize_models(mom,models,'synthetic',min_n=1,min_choosers=1,min_months=1)
        f=nonsingletons(frame);X=make_design(f,edges).toarray();g,n,A=groups(f)
        chooser_dummies=A.T.toarray();y=f['y'].astype(float)
        for axis in ['gap','payoff']:
            for spec in ['chooser_controls','chooser_controls_k20','chooser_controls_k50']:
                key=axis+'__'+spec;model=models[key]
                B=np.column_stack([chooser_dummies,X[:,model['indices']]])
                pinv=np.linalg.pinv(B,rcond=1e-10);beta=pinv@y;e=y-B@beta
                C=np.column_stack([np.zeros((len(model['C']),len(n))),model['C']])
                direct=C@beta;valid=model['identified']
                self.assertTrue(valid.sum()>3)
                np.testing.assert_allclose(model['estimates'][valid],direct[valid],atol=2e-7,rtol=2e-7)
                influence=(pinv.T@C.T)*e[:,None];scores=A@influence
                rank=np.linalg.matrix_rank(B,tol=1e-8)
                correction=len(n)/(len(n)-1)*(len(y)-1)/(len(y)-rank)
                cov=(scores.T@scores)*correction
                np.testing.assert_allclose(arrays[key+'__covariance'][np.ix_(valid,valid)],
                                           cov[np.ix_(valid,valid)],atol=2e-7,rtol=2e-5)
        self.assertEqual(mom.all_N-mom.N,5)

    def test_streamed_complete_choosers_and_checkpoint(self):
        f,edges=synthetic();full=Moments(edges);full.add(f)
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'s.parquet';pq.write_table(pa.table(f),p,row_group_size=93)
            streamed=Moments(edges);seen=[]
            for b in iter_blocks(p,batch_rows=51):
                seen.extend(np.unique(b['chooser']).tolist());streamed.add(b)
            self.assertEqual(len(seen),len(set(seen)))
            np.testing.assert_allclose(streamed.S,full.S,atol=3e-11)
            np.testing.assert_allclose(streamed.b,full.b,atol=3e-12)
            self.assertEqual(streamed.G,full.G)
            q=Path(t)/'m.npz';streamed.save(q);restored=Moments.load(q)
            np.testing.assert_array_equal(restored.S,streamed.S)

    def test_unidentified_contrast_is_not_a_zero(self):
        S=np.array([[1.,-1.,0.,0.],[-1.,1.,0.,0.],[0.,0.,1.,-1.],[0.,0.,-1.,1.]])
        C=np.array([[1.,-1.,0.,0.],[1.,0.,-1.,0.]])
        result=solve(S,np.array([1.,-1.,2.,-2.]),C)
        self.assertEqual(result['identified'].tolist(),[True,False])

    def test_bin_edges_orientation_and_partition(self):
        x=np.array([-6.01,-6.,-.4,0.,.39999,.4,6.,6.01])
        codes=bin_axis(x,'payoff');labels=axis_definition('payoff')[1]
        ref=next(a['bin'] for a in labels if a['reference'])
        self.assertEqual(codes[2:5].tolist(),[ref,ref,ref])
        self.assertNotEqual(codes[-1],codes[-2]);self.assertNotEqual(codes[0],codes[1])
        z=np.array([-301,-300,-299,-101,-100,0,100,101,299,300,301])
        names=['clearly_worse','modestly_worse','roughly_equal','better','clearly_better']
        np.testing.assert_array_equal(sum(context_mask(z,k).astype(int) for k in names),np.ones(len(z)))
        gc=bin_axis(np.array([-26.,-25.,0.,24.,25.]),'gap')
        self.assertEqual(len(set(gc[1:4])),1);self.assertNotEqual(gc[0],gc[1]);self.assertNotEqual(gc[3],gc[4])


if __name__=='__main__':unittest.main(verbosity=2)
