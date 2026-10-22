import sys
import unittest
import warnings
from pathlib import Path
from unittest import mock
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
import env_numerics as solver
from env_common import num


class NumericalTests(unittest.TestCase):
    def test_direct_dummy_regression_unbalanced_nested_and_disconnected_groups(self):
        rng=np.random.default_rng(614)
        n=460
        block=np.repeat([0,1],n//2)
        day=block*20+rng.integers(0,14,n)
        cell=block*100+rng.choice(24,n,p=np.arange(1,25)/sum(range(1,25)))
        hour=block*50+rng.integers(0,13,n)
        cell[-1]=99999  # A singleton stays in the model and absorbs to zero.
        groups=[cell,day,hour,day.copy()]
        matrix=rng.normal(size=(n,12));matrix[:,0]=1.;matrix[:,1]=day
        matrix[:,2]=matrix[:,3]+matrix[:,4]
        matrix[:,5]=rng.binomial(1,.015,n)
        before=matrix.copy()
        fe=np.column_stack([(g[:,None]==np.unique(g)).astype(float) for g in groups])
        want=matrix-fe@np.linalg.lstsq(fe,matrix,rcond=None)[0]
        got,audit=solver.absorb(matrix,groups)
        np.testing.assert_allclose(got,want,atol=3e-8,rtol=3e-8)
        np.testing.assert_array_equal(matrix,before)
        self.assertLess(np.abs(got[-1]).max(),2e-8)
        self.assertTrue(got.flags.f_contiguous)
        self.assertEqual(audit['status'],'CONVERGED')
        self.assertLessEqual(max(audit['final_max_group_mean_original_units']),audit['absolute_tolerance_original_units'])
        legacy,_=num.absorb(matrix,groups)
        np.testing.assert_allclose(got,legacy,atol=2e-9,rtol=2e-8)

    def test_old_false_convergence_after_overflow_is_not_accepted(self):
        # Reproduces the error-handling defect, not a claim that the Mac input
        # contained numbers this large. The private matrix is unavailable here.
        a=np.full((32,2),1e308);groups=[np.zeros(32,dtype=np.int64)]
        with warnings.catch_warnings(),np.errstate(all='ignore'):
            warnings.simplefilter('ignore')
            old,_=num.absorb(a,groups)
        self.assertFalse(np.isfinite(old).all())
        got,check=solver.absorb(a,groups)
        np.testing.assert_array_equal(got,0.)
        self.assertEqual(check['status'],'CONVERGED')

    def test_nonfinite_mean_cannot_reach_regression_and_diagnostic_survives(self):
        published=[]
        with mock.patch.object(solver,'_group_means',return_value=np.array([np.nan])):
            with self.assertRaisesRegex(solver.AbsorptionError,'NONFINITE_GROUP_MEAN'):
                solver.absorb(np.ones((20,2)),[np.zeros(20,dtype=np.int64)],publish=published.append)
        self.assertEqual(published[-1]['status'],'FAILED')
        self.assertEqual(published[-1]['iteration'],1)

    def test_wrong_finite_projection_caught_by_energy_check(self):
        published=[]
        with mock.patch.object(solver,'_group_means',return_value=np.array([-10.])):
            with self.assertRaisesRegex(solver.AbsorptionError,'PROJECTION_INCREASED'):
                solver.absorb(np.ones((20,2)),[np.zeros(20,dtype=np.int64)],publish=published.append)
        self.assertEqual(published[-1]['status'],'FAILED')

    def test_exhausted_iterations_never_return_unconverged_values(self):
        rng=np.random.default_rng(20);n=100
        with self.assertRaisesRegex(solver.AbsorptionError,'ITERATION_LIMIT'):
            solver.absorb(rng.normal(size=(n,3)),[rng.integers(0,15,n),rng.integers(0,7,n)],max_iter=1)

    def test_one_and_multi_column_results_and_row_permutation_agree(self):
        rng=np.random.default_rng(543);n=1800
        a=rng.normal(size=(n,37));groups=[rng.integers(0,31,n),rng.integers(0,16,n)]
        got,_=solver.absorb(a,groups)
        for k in [0,18,36]:
            one,_=solver.absorb(a[:,k:k+1],groups)
            np.testing.assert_allclose(one[:,0],got[:,k],atol=5e-9)
        order=rng.permutation(n);rev=np.argsort(order)
        perm,_=solver.absorb(a[order], [g[order] for g in groups])
        np.testing.assert_allclose(perm[rev],got,atol=5e-9)

if __name__=='__main__':unittest.main()
