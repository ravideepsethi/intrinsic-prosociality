import sys,tempfile,unittest
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'code'))
from design_support import certify,exact_zero_indices,canonical_covariance_comparison
from reporting import covariance_comparison
from util import read


class ExactDesignSupport(unittest.TestCase):
    def record(self):
        return dict(model='one',terms=['x','absent','aliased'],within_sum_squares=[4.,0.,4.],
                    exact_zero_terms=['absent'],row_set_sha256='rows',numerical_zero_threshold=0)

    def statuses(self):
        return {'x':'ESTIMATED','absent':'NOT_ESTIMABLE','aliased':'NOT_ESTIMABLE'}

    def test_certification_uses_all_shards_and_exact_zero_only(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);paths=[]
            for j,xx in enumerate([np.diag([2.,0.,1e-30]),np.diag([3.,0.,0.])]):
                p=d/f'{j}.npz';np.savez(p,m0_xx=xx);paths.append(p)
            r=certify(paths,[{'name':'one'}],[{'names':['x','absent','tiny']}],
                [{'model':'one','row_set_sha256':'rows'}],d/'support.json')
            self.assertEqual(r[0]['exact_zero_terms'],['absent'])
            self.assertEqual(r[0]['within_sum_squares'],[5.,0.,1e-30])

    def test_inconsistent_zero_cross_products_are_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'moments.npz';np.savez(p,m0_xx=np.array([[1.,.1],[.1,0.]]))
            with self.assertRaisesRegex(RuntimeError,'cross products'):
                certify([p],[{'name':'one'}],[{'names':['x','absent']}],
                    [{'model':'one','row_set_sha256':'r'}],Path(t)/'proof.json')

    def test_nonzero_aliased_terms_are_retained(self):
        r=self.record();s=self.statuses()
        self.assertEqual(exact_zero_indices(r,r['terms'],'rows',s,s).tolist(),[1])
        a=np.diag([1.,0.,1.]);b=a.copy();b[0,2]=b[2,0]=.01
        check=canonical_covariance_comparison(a,b,r['terms'],[1],covariance_comparison)
        self.assertFalse(check['passed'])

    def test_support_requires_order_sample_and_exact_threshold(self):
        r=self.record();s=self.statuses()
        for key,value in [('terms',['aliased','absent','x']),('row_set_sha256','other'),
                          ('numerical_zero_threshold',1e-8),('exact_zero_terms',['absent','aliased'])]:
            changed=dict(r);changed[key]=value
            with self.subTest(key=key),self.assertRaises(RuntimeError):
                exact_zero_indices(changed,r['terms'],'rows',s,s)

    def test_estimable_reported_term_cannot_be_exempted(self):
        r=self.record();s=self.statuses();other=dict(s,absent='ESTIMATED')
        with self.assertRaisesRegex(RuntimeError,'estimable term'):
            exact_zero_indices(r,r['terms'],'rows',s,other)

    def test_null_direction_roundoff_canonicalizes_without_mutating_raw_matrix(self):
        # Tiny eigensolver leakage into an exactly absent column, next to a
        # coefficient with a large variance; both matrices are PSD.
        a=np.outer([26.,1e-9,0.],[26.,1e-9,0.])+np.diag([0,0,1.])
        b=np.outer([26.,-2e-9,0.],[26.,-2e-9,0.])+np.diag([0,0,1.])
        before=a.copy();r=canonical_covariance_comparison(a,b,['x','absent','z'],[1],covariance_comparison)
        self.assertFalse(r['raw_passed']);self.assertTrue(r['passed'])
        np.testing.assert_array_equal(a,before)
        r=canonical_covariance_comparison(a,b,['x','absent','z'],[],covariance_comparison)
        self.assertFalse(r['passed'])

    def test_gross_error_in_null_direction_is_rejected(self):
        a=np.diag([1.,.1,1.]);b=np.diag([1.,0.,1.])
        with self.assertRaisesRegex(RuntimeError,'Gross covariance'):
            canonical_covariance_comparison(a,b,['x','absent','z'],[1],covariance_comparison)


if __name__=='__main__':unittest.main()
