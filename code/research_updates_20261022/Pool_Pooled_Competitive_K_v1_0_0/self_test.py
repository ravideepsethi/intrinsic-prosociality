#!/usr/bin/env python3
"""Synthetic numerical checks; no scientific estimates or conclusions imposed."""
import os
for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS'):os.environ[k]='1'
import tempfile
from pathlib import Path
import unittest
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from pooled_engine import (states,absorption,retain_units,design,PooledMoments,
  fit_models,score_block,finish,INTERACTED)
from fe_engine import iter_blocks,bin_axis,axis_definition

def synthetic(seed=7123,accounts=82):
    r=np.random.default_rng(seed);ids=[];board=[]
    for i in range(accounts):
        for s in range(3):
            n=1 if (i<2 or (i%7==0 and s==2)) else int(r.integers(11,23))
            ids.extend([i]*n)
            board.extend(r.integers(*[(-100,101),(101,300),(300,801)][s],n))
    chooser=np.array(ids);board=np.array(board,dtype=float);n=len(ids);st=states(board)
    gap=r.normal(0,230,n);K=np.exp(r.uniform(np.log(9),np.log(80),n));K[r.random(n)<.25]=11.36
    payoff=K*(.5-1/(1+np.exp(gap/170)))
    rate=.10+.035*(chooser%4)+.035*st+.055*(gap>100)+.045*((st==2)&(gap>100))
    y=(r.random(n)<rate).astype(int);y[chooser==3]=0
    f=dict(chooser=chooser,board=board,y=y,gap=gap,payoff=payoff,K=K,ply=r.integers(2,160,n).astype(float),
      crd=r.uniform(45,220,n),drd=r.uniform(45,220,n),cvol=r.uniform(.035,.09,n),dvol=r.uniform(.035,.09,n),
      month=r.integers(0,24,n),speed=r.integers(0,5,n))
    edges={k:sorted(set(np.quantile(K,np.arange(1,q)/q).tolist())) for k,q in [('k20',20),('k50',50)]}
    return f,edges

class Checks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original,cls.edges=synthetic();cls.m=PooledMoments(cls.edges);cls.m.add(cls.original)
        cls.models=fit_models(cls.m);score_block(cls.original,cls.edges,cls.models)
        cls.rows,cls.shapes,cls.tests,cls.diag,cls.arrays=finish(cls.m,cls.models,min_n=1,min_choosers=1,min_months=1)

    def test_absorption_and_chooser_cluster_covariance_against_dense_dummies(self):
        f=retain_units(self.original);a=absorption(f);X=design(f,self.edges).toarray();y=f['y'].astype(float)
        self.assertGreater(a['H'],a['G'])
        checked=0;wrong_diff=0
        for key,model in self.models.items():
            if model['spec']=='raw':continue
            # Full dummy regression independently solves both the intercepts and slopes.
            B=np.column_stack([a['A'].T.toarray(),X[:,model['indices']]])
            pinv=np.linalg.pinv(B,rcond=1e-10);beta=pinv@y;e=y-B@beta
            C=np.column_stack([np.zeros((len(model['C']),a['H'])),model['C']])
            valid=model['identified'];self.assertGreater(valid.sum(),5)
            np.testing.assert_allclose(model['estimates'][valid],(C@beta)[valid],atol=4e-7,rtol=4e-7)
            influence=(pinv.T@C.T)*e[:,None]
            scores=a['B']@influence
            rank=np.linalg.matrix_rank(B,tol=1e-8)
            factor=a['G']/(a['G']-1)*(len(y)-1)/(len(y)-rank)
            V=scores.T@scores*factor;actual=self.arrays[key+'__covariance']
            np.testing.assert_allclose(actual[np.ix_(valid,valid)],V[np.ix_(valid,valid)],atol=4e-7,rtol=5e-5)
            wrong=(a['A']@influence).T@(a['A']@influence)*factor
            wrong_diff=max(wrong_diff,float(np.max(np.abs(wrong-V))))
            checked+=1
        self.assertEqual(checked,8)
        self.assertGreater(wrong_diff,1e-5,'Fixture must expose the error of clustering by absorbed unit')

    def test_raw_covariance_and_no_outcome_selection(self):
        f=retain_units(self.original);a=absorption(f);y=f['y'].astype(float)
        self.assertTrue((f['chooser']==3).any());self.assertEqual(y[f['chooser']==3].sum(),0)
        for axis in ('gap','payoff'):
            model=self.models[axis+'__raw'];J=len(model['rates']);code=bin_axis(f[axis],axis)
            X=np.eye(J)[code];P=np.linalg.pinv(X);beta=P@y;e=y-X@beta
            C=np.eye(J);C[:,model['reference']]-=1
            score=a['B']@((P.T@C.T)*e[:,None]);factor=a['G']/(a['G']-1)*(len(y)-1)/(len(y)-np.linalg.matrix_rank(X))
            valid=model['identified'];V=score.T@score*factor
            np.testing.assert_allclose(self.arrays[axis+'__raw__covariance'][np.ix_(valid,valid)],V[np.ix_(valid,valid)],atol=1e-10)

    def test_shards_and_record_boundaries_preserve_complete_choosers(self):
        merged=PooledMoments(self.edges)
        with tempfile.TemporaryDirectory() as tmp:
            for shard in range(3):
                keep=self.original['chooser']%3==shard
                f={k:v[keep] for k,v in self.original.items()};p=Path(tmp)/f'{shard}.parquet'
                pq.write_table(pa.table(f),p,row_group_size=47)
                local=PooledMoments(self.edges);seen=[]
                for frame in iter_blocks(p,batch_rows=31):
                    seen.extend(np.unique(frame['chooser']));local.add(frame)
                self.assertEqual(len(seen),len(set(seen)))
                q=Path(tmp)/f'{shard}.npz';local.save(q);merged.merge(PooledMoments.load(q))
        np.testing.assert_allclose(merged.S,self.m.S,atol=5e-10)
        np.testing.assert_allclose(merged.b,self.m.b,atol=2e-11)
        self.assertEqual((merged.G,merged.H,merged.N),(self.m.G,self.m.H,self.m.N))
        for axis in ('gap','payoff'):
            for k in self.m.counts[axis]:np.testing.assert_array_equal(merged.counts[axis][k],self.m.counts[axis][k])

    def test_joint_test_uses_cross_state_covariance(self):
        from scipy.stats import f as fdist
        for test in self.tests:
            self.assertEqual(test['status'],'estimated')
            axis=test['axis'];model=self.models[axis+'__'+INTERACTED];labels=axis_definition(axis)[1];J=len(labels)
            bins=[i for i,x in enumerate(labels) if x['mid'] in test['tested_bin_centres']]
            R=np.zeros((2*len(bins),3*J))
            for z,s in enumerate([1,2]):
                for i,b in enumerate(bins):R[z*len(bins)+i,s*J+b]=1;R[z*len(bins)+i,b]=-1
            V=R@self.arrays[axis+'__'+INTERACTED+'__covariance']@R.T;d=R@model['estimates']
            # Ordinary inverse on this nonsingular fixture is independent of scaled eigensolve.
            self.assertEqual(test['restriction_rank'],len(d))
            W=float(d@np.linalg.solve(V,d));F=W/len(d)
            self.assertAlmostEqual(F,test['F_statistic'],places=7)
            self.assertAlmostEqual(float(fdist.sf(F,len(d),self.m.G-1)),test['p_cluster_F'],places=9)

    def test_state_boundaries_and_singleton_units(self):
        np.testing.assert_array_equal(states(np.array([-100,100,101,299,300,900])),[0,0,1,1,2,2])
        with self.assertRaises(ValueError):states(np.array([-101]))
        self.assertEqual(self.m.G,len(np.unique(retain_units(self.original)['chooser'])))
        self.assertLess(self.m.G,self.m.all_G)
        self.assertEqual(self.m.N,int(self.m.state_N.sum()))
        self.assertEqual(self.m.H,int(self.m.state_H.sum()))

if __name__=='__main__':unittest.main(verbosity=2)
