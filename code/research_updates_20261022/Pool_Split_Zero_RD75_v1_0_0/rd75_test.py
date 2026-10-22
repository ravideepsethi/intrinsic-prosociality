#!/usr/bin/env python3
"""Regression tests for the RD filter and within-sample estimation."""
import os
for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):os.environ[name]='1'
import unittest,json
from pathlib import Path
import numpy as np
from self_test import synthetic
from pooled_engine import PooledMoments,fit_models,score_block,finish,retain_units,absorption,design
from run_split import select_sample,count_record,verify_prior_counts

class RD75Checks(unittest.TestCase):
    def test_filter_inclusive_both_players_no_k_or_outcome_filter(self):
        f={'crd':np.array([75.,75.0001,60.,np.nan,20.,20.]),
           'drd':np.array([75.,50.,75.0001,20.,20.,np.nan]),
           'y':np.array([0,1,1,1,0,1]),'K':np.array([30.,11.5,11.5,11.5,100.,11.5])}
        r=select_sample(f,'rd75')
        np.testing.assert_array_equal(r['K'],[30.,100.])
        np.testing.assert_array_equal(r['y'],[0,0])
        self.assertIs(select_sample(f,'all'),f)

    def test_rd75_counts_reader_uses_correct_prior_sample(self):
        p=Path(__file__).resolve().parent/'evidence/PRIOR_STABLE_SAMPLE_COUNTS.json'
        r=next(r for r in json.loads(p.read_text()) if r['sample']=='rd75')
        r.pop('label')
        self.assertEqual(verify_prior_counts(r)['status'],'EXACT_COUNTS_MATCH')
        self.assertEqual(r['estimation_rows'],11114912)

    def test_filtered_fe_and_cluster_covariance_against_dense_dummy_ols(self):
        original,edges=synthetic(seed=833,accounts=62)
        f0=select_sample(original,'rd75');f=retain_units(f0)
        self.assertGreater(len(original['y']),len(f0['y']))
        self.assertGreater(len(f0['y']),len(f['y']))
        self.assertTrue((f['chooser']==3).any());self.assertEqual(f['y'][f['chooser']==3].sum(),0)
        m=PooledMoments(edges);m.add(f0)
        models=fit_models(m,interaction=False);score_block(f0,edges,models)
        _,_,_,_,arrays=finish(m,models,min_n=1,min_choosers=1,min_months=1)
        a=absorption(f);X=design(f,edges).toarray();y=f['y'].astype(float)
        self.assertEqual(count_record(m,'rd75')['sample'],'rd75')
        for key,model in models.items():
            if model['spec']=='raw':continue
            B=np.column_stack([a['A'].T.toarray(),X[:,model['indices']]])
            pinv=np.linalg.pinv(B,rcond=1e-10);beta=pinv@y;e=y-B@beta
            C=np.column_stack([np.zeros((len(model['C']),a['H'])),model['C']])
            valid=model['identified'];self.assertTrue(valid.any())
            np.testing.assert_allclose(model['estimates'][valid],(C@beta)[valid],atol=4e-7,rtol=4e-7)
            score=a['B']@((pinv.T@C.T)*e[:,None]);rank=np.linalg.matrix_rank(B,tol=1e-8)
            factor=a['G']/(a['G']-1)*(len(y)-1)/(len(y)-rank)
            V=score.T@score*factor
            np.testing.assert_allclose(arrays[key+'__covariance'][np.ix_(valid,valid)],V[np.ix_(valid,valid)],atol=4e-7,rtol=5e-5)

if __name__=='__main__':unittest.main(verbosity=2)
