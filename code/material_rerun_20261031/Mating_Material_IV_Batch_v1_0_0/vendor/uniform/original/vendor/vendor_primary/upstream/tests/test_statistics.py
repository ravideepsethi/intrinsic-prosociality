import unittest, tempfile
from pathlib import Path
import numpy as np
from local_common import *
from matched import censored_outcome,core_module,fit

class StatisticsTests(unittest.TestCase):
    def test_integer_inclusive_evaluation_boundaries(self):
        cp=[-100,-50,-1,0,49,50,100,101,200,201,299,300,599,600,100000]
        np.testing.assert_array_equal(eval_code(cp),[0,1,1,2,2,3,3,4,4,5,5,6,6,7,7])

    def test_hinges_uncentered_and_strict_tails(self):
        np.testing.assert_array_equal(gap_basis([0])[0],[0,3,1,0,0,0,0,0,0])
        np.testing.assert_array_equal(gap_basis([100])[0]-gap_basis([-100])[0],[2,2,2,1,0,0,0,0,0])
        np.testing.assert_array_equal(gap_basis([300])[0]-gap_basis([0])[0],[3,3,3,3,2,0,0,0,0])
        np.testing.assert_array_equal(gap_basis([-601,-600,600,601])[:,6:8],[[1,0],[0,0],[0,0],[0,1]])
        self.assertEqual(gap_basis([np.nan])[0,-1],1)

    def test_ratio_gradient_by_finite_difference(self):
        E=.37;R=-.12;V=np.array([[.002,.0003],[.0003,.004]])
        f=lambda x:x[1]/x[0];x=np.array([E,R]);h=1e-6
        grad=np.array([(f(x+np.eye(2)[j]*h)-f(x-np.eye(2)[j]*h))/(2*h) for j in range(2)])
        out=ratio_stats(E,R,V)
        self.assertAlmostEqual(out['se']**2,grad@V@grad,places=10)
        self.assertTrue(ratio_stats(.001,.2,np.eye(2))['weak_denominator'])
        self.assertIsNone(ratio_stats(0,.2,np.eye(2))['ratio'])

    def test_nonpositive_covariance_not_repaired(self):
        self.assertEqual(wald([1,2],[[1,2],[2,1]])['status'],'SINGULAR_OR_NONPOSITIVE_COVARIANCE')
        self.assertIsNone(inference(.5,-.001)['se'])

    def test_censoring_zero_coding_and_ties(self):
        y=censored_outcome(np.array([1,1,1,0],bool),np.array([1,1,0,np.nan]),
            np.array([100,100,100,100]),np.array([10,20,30,np.nan]),np.array([111,120,np.nan,115]))
        np.testing.assert_array_equal(y,[1,0,0,0])

    def test_weighted_matched_fit_against_full_dummy_ols(self):
        rng=np.random.default_rng(27);n=1800;cell=rng.integers(0,8,n);month=rng.integers(0,6,n);cluster=rng.integers(0,110,n)
        D=rng.binomial(1,.3,n).astype(float);X=rng.normal(size=(n,3));w=rng.uniform(.2,2,n)
        y=.02*D+X@np.array([.1,-.2,.3])+rng.normal(size=n)+cell*.1-month*.2
        core=core_module();out=fit(y,D,X,w,[cell,month],cluster,core)
        Z=np.column_stack([np.ones(n),D,X,np.eye(8)[cell,1:],np.eye(6)[month,1:]])
        bread=np.linalg.inv(Z.T@(Z*w[:,None]));b=bread@(Z.T@(w*y));u=y-Z@b
        S,G=cluster_sums(Z*(w*u)[:,None],cluster)
        # Frozen small-sample factor uses residualized continuous rank, as in the receipt producer.
        V=bread@(S.T@S)@bread*G/(G-1)*(n-1)/(n-4)
        self.assertAlmostEqual(out['estimate'],b[1]*100,places=7)
        self.assertAlmostEqual(out['se'],np.sqrt(V[1,1])*100,places=7)

    def test_checkpoint_rejects_corruption(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'x.json';save(p,{'x':3});seal(p,'key');self.assertTrue(cached(p,'key'))
            p.write_text('changed')
            with self.assertRaises(RuntimeError):cached(p,'key')

if __name__=='__main__':unittest.main()
