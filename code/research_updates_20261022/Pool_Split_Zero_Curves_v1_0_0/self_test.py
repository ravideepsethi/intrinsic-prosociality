#!/usr/bin/env python3
import os
for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS'):os.environ[key]='1'
import unittest,tempfile,json
from pathlib import Path
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from pooled_engine import states,absorption,retain_units,design,PooledMoments,fit_models,score_block,finish
from fe_engine import iter_blocks,bin_axis,axis_definition
from run_split import zero_audit,AUDIT_KEYS,verify_prior_counts
from split_report import near_zero_contrasts

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
    # Ensure exact zero and both small signed intervals are populated.
    pick=r.random(n)
    f['payoff'][pick<.12]=0.
    neg=(pick>=.12)&(pick<.26);pos=(pick>=.26)&(pick<.40)
    f['payoff'][neg]=r.uniform(-.399,-.001,neg.sum())
    f['payoff'][pos]=r.uniform(.001,.399,pos.sum())
    q=f['payoff']/f['K']
    f['gap']=170*np.log((.5+q)/(.5-q))
    return f,edges


class Checks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original,cls.edges=synthetic(accounts=85)
        cls.m=PooledMoments(cls.edges);cls.m.add(cls.original)
        cls.models=fit_models(cls.m,interaction=False);score_block(cls.original,cls.edges,cls.models)
        cls.rows,_,_,_,cls.arrays=finish(cls.m,cls.models,min_n=1,min_choosers=1,min_months=1)

    def test_exact_zero_signed_boundaries_and_closed_endpoint(self):
        labels=axis_definition('payoff')[1]
        self.assertEqual(len(labels),33)
        self.assertEqual(sum(r['reference'] for r in labels),1)
        x=np.array([-6.0001,-6.,-.4,-.2,-1e-15,0.,-0.,1e-15,.2,.4,6.,6.0001])
        c=bin_axis(x,'payoff')
        np.testing.assert_array_equal(c,[0,1,15,15,15,16,16,17,17,18,31,32])
        self.assertEqual(labels[16]['low'],labels[16]['high'])
        self.assertAlmostEqual(labels[15]['mid'],-.2)
        self.assertAlmostEqual(labels[17]['mid'],.2)
        self.assertEqual(bin_axis(np.array([np.nextafter(0.,-1),np.nextafter(0.,1)]),'payoff').tolist(),[15,17])
        gap=bin_axis(np.array([-625.,-25.,0.,25.,625.]),'gap')
        np.testing.assert_array_equal(gap,[1,13,13,14,26])

    def test_coefficients_and_chooser_covariance_against_full_dummy_ols(self):
        f=retain_units(self.original);a=absorption(f);X=design(f,self.edges).toarray();y=f['y'].astype(float)
        self.assertGreater(a['H'],a['G'])
        for key,model in self.models.items():
            if model['spec']=='raw':continue
            B=np.column_stack([a['A'].T.toarray(),X[:,model['indices']]])
            pinv=np.linalg.pinv(B,rcond=1e-10);beta=pinv@y;e=y-B@beta
            C=np.column_stack([np.zeros((len(model['C']),a['H'])),model['C']])
            valid=model['identified'];self.assertTrue(valid.all())
            np.testing.assert_allclose(model['estimates'],C@beta,atol=4e-7,rtol=4e-7)
            score=a['B']@((pinv.T@C.T)*e[:,None]);rank=np.linalg.matrix_rank(B,tol=1e-8)
            factor=a['G']/(a['G']-1)*(len(y)-1)/(len(y)-rank)
            np.testing.assert_allclose(self.arrays[key+'__covariance'],score.T@score*factor,atol=4e-7,rtol=5e-5)

    def test_raw_means_and_central_contrasts_use_full_covariance(self):
        f=retain_units(self.original);a=absorption(f);y=f['y'].astype(float)
        self.assertTrue((f['chooser']==3).any());self.assertEqual(y[f['chooser']==3].sum(),0)
        for axis in ('gap','payoff'):
            model=self.models[axis+'__raw'];J=len(model['rates']);code=bin_axis(f[axis],axis)
            X=np.eye(J)[code];P=np.linalg.pinv(X);beta=P@y;e=y-X@beta
            C=np.eye(J);C[:,model['reference']]-=1
            score=a['B']@((P.T@C.T)*e[:,None]);factor=a['G']/(a['G']-1)*(len(y)-1)/(len(y)-np.linalg.matrix_rank(X))
            valid=model['identified'];V=score.T@score*factor
            np.testing.assert_allclose(self.arrays[axis+'__raw__covariance'][np.ix_(valid,valid)],V[np.ix_(valid,valid)],atol=1e-10)
        results=near_zero_contrasts(self.rows,self.arrays,{'chooser_clusters':self.m.G})
        row=next(r for r in results if r['contrast']=='small_gain_minus_small_loss' and r['specification']=='chooser_state_controls_k20')
        V=self.arrays['payoff__chooser_state_controls_k20__covariance']
        expected=100*np.sqrt(V[17,17]+V[15,15]-2*V[17,15])
        self.assertAlmostEqual(row['cluster_se_pp'],expected,places=10)
        self.assertEqual(row['p_holm_three_adjusted_contrasts_family_size'],3)

    def test_shards_record_boundaries_and_serialization(self):
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
            for key in self.m.counts[axis]:np.testing.assert_array_equal(merged.counts[axis][key],self.m.counts[axis][key])

    def test_zero_audit_and_prior_array_reader(self):
        a=dict(zip(AUDIT_KEYS,zero_audit(self.original)))
        self.assertEqual(a['negative_payoff']+a['exact_zero_payoff']+a['positive_payoff'],self.m.N)
        self.assertEqual(a['old_central_bin'],sum(self.m.counts['payoff']['n'][0,15:18]))
        self.assertEqual(a['exact_zero_payoff'],self.m.counts['payoff']['n'][0,16])
        root=Path(__file__).resolve().parent
        prior=json.loads((root/'evidence/PRIOR_STABLE_SAMPLE_COUNTS.json').read_text())
        old=next(r for r in prior if r['sample']=='all');old.pop('label')
        self.assertEqual(verify_prior_counts(old)['status'],'EXACT_COUNTS_MATCH')

if __name__=='__main__':unittest.main(verbosity=2)
