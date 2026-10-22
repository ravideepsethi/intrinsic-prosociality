import unittest, tempfile
from pathlib import Path
from unittest.mock import patch
import numpy as np
from primary_common import *
from test_primary import fixture
import primary_models as pm
from fast_hour_projection import absorb_last_move

class FastHours(unittest.TestCase):
    def test_scheduler_preserves_results_budget_and_reports_model_names(self):
        from concurrent.futures import ThreadPoolExecutor
        messages=[];jobs=[dict(name='model_'+str(i),memory_gb=3.) for i in range(3)]
        runtime=frozen.runtime
        with patch.object(runtime.cf,'ProcessPoolExecutor',side_effect=lambda **kw:ThreadPoolExecutor(max_workers=kw['max_workers'])), \
             patch.object(runtime.u,'log',side_effect=messages.append):
            got=runtime.mapped(lambda job:job['name'],jobs,2,11,'test_models',45,60)
        self.assertEqual(got,['model_0','model_1','model_2'])
        self.assertTrue(any('batch/finish ETA unavailable' in x for x in messages))
        self.assertFalse(any('finish ETA ~' in x for x in messages))
        for name in got:self.assertTrue(any('Completed '+name in x for x in messages))

    def test_nearly_nested_disconnected_months_and_singletons(self):
        rng=np.random.default_rng(115)
        n=1500;days=rng.integers(19723,19784,n);hours=days*24+rng.integers(0,24,n)
        # Few cross-hour and cross-day links; last-move hour almost nests date/week.
        anchor=hours+(rng.random(n)<.025)
        hours[:3]=np.array(['2024-01-31T23','2024-02-01T00','2024-02-29T23'],dtype='datetime64[h]').astype(int)
        days[:3]=hours[:3]//24;anchor[:3]=hours[:3]+2
        month=days.astype('datetime64[D]').astype('datetime64[M]').astype(int)
        cell=month*30+rng.integers(0,30,n);cell[0]=999999
        groups=[cell,days,hours%168,anchor]
        raw=rng.normal(size=(n,5));raw[:,0]+=days-days.min();raw[:,4]=1.
        got,diag=absorb_last_move(np.array(raw,order='F'),groups)
        D=np.column_stack([np.eye(len(np.unique(g)))[np.unique(g,return_inverse=True)[1]] for g in groups])
        expected=raw-D@np.linalg.lstsq(D,raw,rcond=1e-12)[0]
        np.testing.assert_allclose(got,expected,atol=2e-8)
        # A constant is absorbed exactly in theory. Test its residual directly;
        # do not interpret the sign of a roundoff-sized clustered variance.
        self.assertLess(np.max(np.abs(got[:,4])),1e-10)
        self.assertLessEqual(diag['maximum_group_mean'],diag['absolute_tolerance_original_units'])
        self.assertTrue(diag['original_FE_space_preserved'])

    def test_invalid_month_nesting_is_rejected(self):
        groups=[np.zeros(4,int),np.array([19723,19724,19755,19756]),np.arange(4),np.arange(4)]
        with self.assertRaisesRegex(ValueError,'crosses exposure months'):
            absorb_last_move(np.ones((4,2),order='F'),groups)

    def test_full_model_coefficients_and_CR0_match_dense_projection(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p,s,d,score=fixture(root,2500)
            d['month_code']=d['archive_start_ms'].astype('datetime64[ms]').astype('datetime64[M]').astype(np.int64)
            # Preserve the logical y <= reached relation while giving reached
            # real variation. The old fixture set reached=1 on every row.
            d['reached']=d['y'] | (np.random.default_rng(473).random(len(d['y']))<.65)
            self.assertEqual(np.unique(d['reached']).tolist(),[False,True])
            self.assertTrue(np.all(d['y']<=d['reached']))
            pq.write_table(pa.table(d),p)
            job=pm.r9bjob(p,s,root,'test','hour_last_move','X0_ENV_indicator',hour='last_move',ols=True)
            fast=models.estimate(job)
            def dense(v,groups,width,**kwargs):
                D=np.column_stack([np.eye(len(np.unique(g)))[np.unique(g,return_inverse=True)[1]] for g in groups])
                v-=D@np.linalg.lstsq(D,v,rcond=1e-12)[0]
                x=v[:,width:];gram=x.T@x;rank=int(np.linalg.matrix_rank(gram,tol=max(float(np.linalg.norm(gram,2)),1)*1e-12))
                result=v[:,:width]-x@(np.linalg.pinv(gram,rcond=1e-12)@(x.T@v[:,:width]))
                return result,rank,dict(iterations=1,solver='explicit_dummy_reference')
            with patch.object(models,'project',side_effect=dense):ref=models.estimate(job)
            for a,b in zip(fast['estimates'],ref['estimates']):
                label=(a['estimator'],a['outcome'])
                self.assertEqual(label,(b['estimator'],b['outcome']))
                self.assertEqual(a['row_set_sha256'],b['row_set_sha256'])
                self.assertTrue(a.get('supported'),(label,'fast',a))
                self.assertTrue(b.get('supported'),(label,'dense',b))
                for key in ['coefficient_pp','standard_error_pp']:
                    self.assertIn(key,a,(label,'fast',a))
                    self.assertIn(key,b,(label,'dense',b))
                    self.assertTrue(np.isfinite(a[key]) and np.isfinite(b[key]),(label,key))
                    self.assertAlmostEqual(a[key],b[key],places=7,msg=str((label,key)))

    def test_zero_and_negative_covariance_remain_explicitly_unsupported(self):
        for variance in (0.,-1e-24):
            result=models.clean_inference(.2,variance,100)
            self.assertFalse(result['supported'])
            self.assertEqual(result['reason'],'NONPOSITIVE_COVARIANCE_NOT_REPAIRED')
            self.assertNotIn('standard_error_pp',result)
            self.assertEqual(result['coefficient_pp'],20.)

if __name__=='__main__':unittest.main()
