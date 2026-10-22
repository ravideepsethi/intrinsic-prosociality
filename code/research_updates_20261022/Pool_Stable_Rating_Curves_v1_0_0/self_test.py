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
from stable_specs import add_normalized,select

def synthetic(seed=7123,accounts=82):
    r=np.random.default_rng(seed);ids=[];board=[]
    for i in range(accounts):
        for s in range(3):
            n=1 if (i<2 or (i%7==0 and s==2)) else int(r.integers(11,23))
            ids.extend([i]*n)
            board.extend(r.integers(*[(-100,101),(101,300),(300,801)][s],n))
    chooser=np.array(ids);board=np.array(board,dtype=float);n=len(ids);st=states(board)
    gap=r.normal(0,230,n);K=np.exp(r.uniform(np.log(9),np.log(80),n));K[r.random(n)<.50]=11.36
    payoff=K*(.5-1/(1+np.exp(gap/170)))
    rate=.10+.035*(chooser%4)+.035*st+.055*(gap>100)+.045*((st==2)&(gap>100))
    y=(r.random(n)<rate).astype(int);y[chooser==3]=0
    f=dict(chooser=chooser,board=board,y=y,gap=gap,payoff=payoff,K=K,ply=r.integers(2,160,n).astype(float),
      crd=np.where(r.random(n)<.75,r.uniform(50,74,n),r.uniform(76,220,n)),drd=np.where(r.random(n)<.75,r.uniform(50,74,n),r.uniform(76,220,n)),cvol=r.uniform(.035,.09,n),dvol=r.uniform(.035,.09,n),
      month=r.integers(0,24,n),speed=r.integers(0,5,n))
    edges={k:sorted(set(np.quantile(K,np.arange(1,q)/q).tolist())) for k,q in [('k20',20),('k50',50)]}
    return add_normalized(f),edges

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
        self.assertEqual(checked,6)
        self.assertGreater(wrong_diff,1e-5,'Fixture must expose the error of clustering by absorbed unit')

    def test_raw_covariance_and_no_outcome_selection(self):
        f=retain_units(self.original);a=absorption(f);y=f['y'].astype(float)
        self.assertTrue((f['chooser']==3).any());self.assertEqual(y[f['chooser']==3].sum(),0)
        for axis in ('gap','payoff','normalized'):
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
        for axis in ('gap','payoff','normalized'):
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



class LocalChecks(unittest.TestCase):
    def test_local_coefficients_and_cluster_covariance_against_dummy_regression(self):
        import zero_engine as z
        f,edges=synthetic(seed=19021,accounts=64)
        r=np.random.default_rng(991);n=len(f['y'])
        f['normalized']=r.uniform(-.095,.095,n);f['normalized'][::17]=0
        f['K'][:]=11.36;f['payoff']=f['normalized']*f['K']
        f['gap']=173.7178*np.log((.5+f['normalized'])/(.5-f['normalized']))
        f['crd'][:]=60.;f['drd'][:]=62.
        y=(r.random(n)<(.12+.5*f['normalized']+.08*(f['normalized']>0))).astype(int)
        y[f['chooser']==3]=0;f['y']=y
        m=z.LocalMoments(edges,'normalized',.1);m.add(f);model=z.fit(m);z.score(f,edges,model)
        rows,V=z.finish(m,model,min_n=1,min_choosers=1,min_months=1)
        ff=z.local_frame(f,'normalized',.1);a=absorption(ff);X,side=z.local_design(ff,edges,'normalized',.1)
        B=np.column_stack([a['A'].T.toarray(),X.toarray()]);pinv=np.linalg.pinv(B,rcond=1e-10)
        beta=pinv@ff['y'];e=ff['y']-B@beta
        C=np.column_stack([np.zeros((5,a['H'])),model['C']]);valid=model['identified']
        self.assertTrue(valid.all())
        np.testing.assert_allclose(C@beta,model['estimates'],atol=2e-5,rtol=2e-5)
        scores=a['B']@((pinv.T@C.T)*e[:,None]);rank=np.linalg.matrix_rank(B,tol=1e-8)
        factor=a['G']/(a['G']-1)*(len(e)-1)/(len(e)-rank)
        np.testing.assert_allclose(scores.T@scores*factor,V,atol=2e-5,rtol=2e-4)
        self.assertGreater(m.cross,20);self.assertGreater(m.zero_cross,20)
        # Singleton removal is recomputed inside each window.
        tiny=z.LocalMoments(edges,'normalized',.001);tiny.add(f)
        self.assertLess(tiny.N,m.N)
        self.assertEqual(m.N,int(m.n.sum()))
        self.assertGreater(m.n[1],0)
        # Complete-account block partition gives identical moments and counts.
        merged=z.LocalMoments(edges,'normalized',.1)
        for k in range(3):
            mask=f['chooser']%3==k;part={name:v[mask] for name,v in f.items()}
            mm=z.LocalMoments(edges,'normalized',.1);mm.add(part);merged.merge(mm)
        np.testing.assert_allclose(m.S,merged.S,atol=1e-10)
        np.testing.assert_allclose(m.b,merged.b,atol=1e-10)
        self.assertEqual((m.N,m.H,m.G,m.cross,m.zero_cross),(merged.N,merged.H,merged.G,merged.cross,merged.zero_cross))
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'local.npz';m.save(path);saved=z.LocalMoments.load(path)
            np.testing.assert_array_equal(m.S,saved.S)
            self.assertEqual(m.cross,saved.cross)

    def test_sample_cutoffs_and_normalization(self):
        f,edges=synthetic();n=len(f['y'])
        for sample,cut in [('rd60',60),('rd75',75),('rd100',100)]:
            sub=select(f,sample)
            self.assertTrue((sub['crd']<=cut).all() and (sub['drd']<=cut).all())
            self.assertEqual(len(sub['y']),int(((f['crd']<=cut)&(f['drd']<=cut)).sum()))
        sub=select(f,'rd75_k11_12')
        self.assertTrue(((sub['K']>=11)&(sub['K']<=12)).all())
        np.testing.assert_allclose(f['normalized'],f['payoff']/f['K'])
        # Explicit inclusive thresholds.
        cut={k:v[:4].copy() for k,v in f.items()}
        cut['crd'][:]=[75,75.0001,60,60];cut['drd'][:]=[75,60,75.0001,60];cut['K'][:]=[11,11,12,12.0001]
        self.assertEqual(len(select(cut,'rd75')['y']),2)
        self.assertEqual(len(select(cut,'rd75_k11_12')['y']),1)

    def test_normalized_endpoints_and_empty_window(self):
        import zero_engine as z
        edges,labels=axis_definition('normalized');code=bin_axis(np.array([-.5,-.025,0,.025,.5]),'normalized')
        self.assertEqual(code[0],1);self.assertEqual(code[-1],len(edges)-1)
        ref=next(x['bin'] for x in labels if x['reference'])
        self.assertEqual(code[1],ref);self.assertEqual(code[2],ref);self.assertNotEqual(code[3],ref)
        f,edges=synthetic();f['normalized'][:]=.4
        m=z.LocalMoments(edges,'normalized',.05);m.add(f);model=z.fit(m);z.score(f,edges,model)
        rows,V=z.finish(m,model)
        self.assertTrue(all(r['status']=='unidentified' for r in rows))

if __name__=='__main__':unittest.main(verbosity=2)
