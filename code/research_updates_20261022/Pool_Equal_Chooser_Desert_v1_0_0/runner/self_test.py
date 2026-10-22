"""Numerical and synthetic integration checks; never produces production estimates."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest
import zipfile
import numpy as np
import pandas as pd
from .common import atomic_json,canonical_json,sha256_file,load_json,verify_report_package
from .source import load_census,verify_baseline
from .statistics import inputs,estimate,activity_distribution,activity_terciles,LABELS
from .run import analyze,report,export


def fixture():
    # n,f,l,k,a,b: varied activity, varied balance, zero grants, middle states,
    # singletons and same-state repeat accounts.
    values=[(4,2,2,1,1,0),(40,20,20,2,2,0),(105,100,1,22,20,1),
            (2,1,1,0,0,0),(4,3,1,3,3,0),(10,6,4,1,0,1),
            (1,1,0,1,1,0),(3,3,0,0,0,0),(2,0,0,1,0,0)]
    frame=pd.DataFrame(values,columns=['n','f','l','k','a','b'],dtype=np.int64)
    frame.insert(0,'chooser',np.arange(1,len(frame)+1,dtype=np.int64))
    return frame


def literal_wls(frame):
    selected=frame[(frame.f>0)&(frame.l>0)]
    records=[]
    for j,row in enumerate(selected.itertuples()):
        for i in range(row.f):records.append((j,1,float(i<row.a)))
        for i in range(row.l):records.append((j,0,float(i<row.b)))
    raw=np.array(records);chooser=raw[:,0].astype(int);x=raw[:,1];y=raw[:,2]
    G=len(selected);design=np.column_stack((np.eye(G)[chooser],x))
    n=selected.f.to_numpy()+selected.l.to_numpy()
    w=selected.f.to_numpy()*selected.l.to_numpy()/n
    coefficients=[];scores=[]
    for analytic in (np.ones(G),1/n,1/w):
        a=analytic[chooser];root=np.sqrt(a)
        fit=np.linalg.lstsq(design*root[:,None],y*root,rcond=None)[0]
        residual=y-design@fit
        within_x=x-(selected.f.to_numpy()/n)[chooser]
        cluster=np.bincount(chooser,weights=a*within_x*residual)/np.sum(a*within_x**2)
        coefficients.append(fit[-1]);scores.append(cluster)
    scores=np.column_stack(scores)
    covariance=G/(G-1)*(scores.T@scores)
    return np.array(coefficients),covariance


def fixture_reference(frame):
    n,both,w,_,d=inputs(frame)
    beta=float(np.average(d,weights=w[both]));G=int((n>0).sum());N=int(n.sum())
    q=G/(G-1)*(N-1)/(N-G-1)
    score=w[both]*(d-beta);se=float(np.sqrt(q*(score@score)/w.sum()**2))
    zero=((frame.a+frame.b).to_numpy()==0)&both
    payload=dict(version='SYNTHETIC',sample_fingerprint='SYNTHETIC')
    contract=dict(payload,sha256=hashlib.sha256(canonical_json(payload).encode()).hexdigest())
    authority=dict(rows=int(frame.n.sum()),choosers=len(frame),kind_draws=int(frame.k.sum()),
                   fair_rows=int(frame.f.sum()),fair_kind_draws=int(frame.a.sum()),
                   fair_choosers=int((frame.f>0).sum()),fair_kind_choosers=int((frame.a>0).sum()))
    support=dict(choosers_seen_in_both_states=int(both.sum()),contrast_choosers=G,contrast_rows=N,
                 contrast_singleton_choosers=int((n==1).sum()),opportunities_from_both_state_choosers=int(n[both].sum()),
                 state_varying_choosers_with_no_grant_in_contrast=int(zero.sum()),identifying_weight_sum=float(w.sum()),
                 share_identifying_weight_no_grant_in_contrast=float(w[zero].sum()/w.sum()))
    reference=dict(source_contract=contract,current_support=support,
                   current_minimal_reference=dict(reproduced_estimate_pp=100*beta,reproduced_se_pp=100*se),
                   upstream_return_archive='SYNTHETIC',upstream_return_sha256='SYNTHETIC')
    return authority,reference


class EqualChooserTests(unittest.TestCase):
    def test_three_weightings_and_joint_inference_against_literal_WLS(self):
        frame=fixture();n,both,w,balanced,d=inputs(frame)
        weights=np.column_stack((w[both],balanced[both],np.ones(int(both.sum()))))
        models,pairs,cov=estimate(d,weights)
        expected,expected_cov=literal_wls(frame)
        np.testing.assert_allclose(models.estimate_pp.to_numpy()/100,expected,atol=1e-12)
        np.testing.assert_allclose(cov,expected_cov,atol=1e-12)
        self.assertAlmostEqual(models.iloc[2].estimate_pp,100*d.mean(),places=12)
        self.assertAlmostEqual(models.iloc[2].se_pp,100*d.std(ddof=1)/np.sqrt(len(d)),places=12)
        self.assertGreater(abs(models.iloc[1].estimate_pp-models.iloc[2].estimate_pp),1)
        for row,(j,k) in zip(pairs.itertuples(),((1,0),(2,0),(2,1))):
            se=math.sqrt(expected_cov[j,j]+expected_cov[k,k]-2*expected_cov[j,k])*100
            self.assertAlmostEqual(row.se_pp,se,places=10)

    def test_zero_grant_accounts_are_retained(self):
        frame=fixture();result=analyze(frame)
        self.assertEqual(result['support']['choosers'],6)
        self.assertEqual(result['support']['observed_nongranters_retained'],1)
        self.assertTrue((result['models'].choosers==6).all())
        frame[['k','a','b']]=0
        result=analyze(frame)
        self.assertEqual(result['support']['observed_nongranters_retained'],6)
        self.assertTrue((result['models'].estimate_pp==0).all())
        self.assertTrue((result['models'].se_pp==0).all())

    def test_decile_ties_are_symmetric_and_shares_conserve(self):
        n=np.repeat(10,20)
        weights=np.column_stack((np.arange(1,21),np.arange(20,0,-1),np.ones(20)))
        deciles,top=activity_distribution(n,weights,'synthetic')
        for name in ('opportunity_share','original_FE_weight_share','inverse_count_FE_weight_share','equal_chooser_weight_share'):
            np.testing.assert_allclose(deciles[name],.1,atol=1e-12)
            np.testing.assert_allclose(top[name],top.top_fraction,atol=1e-12)
        shuffled=np.arange(19,-1,-1)
        again,_=activity_distribution(n[shuffled],weights[shuffled],'synthetic')
        pd.testing.assert_frame_equal(deciles,again)

    def test_terciles_keep_count_ties_and_all_support(self):
        n=np.array([2,2,2,3,3,5,5,5,9])
        d=np.arange(9)/10
        models,pairs,support,definition=activity_terciles(n,d,np.ones((9,3)))
        self.assertEqual(int(support.choosers.sum()),9)
        self.assertEqual(definition['lower_cutoff_inclusive'],2)
        self.assertEqual(definition['middle_cutoff_inclusive'],5)
        self.assertEqual(support.choosers.tolist(),[3,5,1])

    def test_source_integrity_and_reference_gates(self):
        frame=fixture();authority,reference=fixture_reference(frame)
        with tempfile.TemporaryDirectory(prefix='equal_chooser_test_') as folder:
            root=Path(folder);path=root/'chooser_counts_private.parquet'
            frame.to_parquet(path,index=False)
            atomic_json(root/'CONTRACT.json',reference['source_contract'])
            atomic_json(root/'chooser_counts_receipt.json',dict(contract=reference['source_contract']['sha256'],sha256=sha256_file(path)))
            read,lineage,_=load_census(root,reference,threads=2)
            pd.testing.assert_frame_equal(read,frame)
            result=verify_baseline(read,authority,reference)
            self.assertEqual(result['status'],'CURRENT_SUPPORT_AND_FE_REFERENCE_REPRODUCED')
            authority['rows']+=1
            with self.assertRaisesRegex(RuntimeError,'count mismatch'):verify_baseline(read,authority,reference)
            path.write_bytes(path.read_bytes()+b'corrupt')
            with self.assertRaisesRegex(RuntimeError,'checksum mismatch'):load_census(root,reference,threads=1)

    def test_bad_sufficient_statistics_are_rejected(self):
        frame=fixture();authority,reference=fixture_reference(frame)
        frame.loc[0,'a']=100
        with tempfile.TemporaryDirectory(prefix='equal_chooser_test_') as folder:
            root=Path(folder);path=root/'chooser_counts_private.parquet'
            frame.to_parquet(path,index=False)
            atomic_json(root/'CONTRACT.json',reference['source_contract'])
            atomic_json(root/'chooser_counts_receipt.json',dict(contract=reference['source_contract']['sha256'],sha256=sha256_file(path)))
            with self.assertRaisesRegex(RuntimeError,'Inconsistent source'):load_census(root,reference)

    def test_grant_denominators_report_export_and_privacy(self):
        frame=fixture();result=analyze(frame);authority,reference=fixture_reference(frame)
        baseline=verify_baseline(frame,authority,reference)
        rates=result['rates'].iloc[0]
        self.assertEqual(rates.choosers,9)
        self.assertEqual(rates.ever_grant_choosers,7)
        self.assertAlmostEqual(rates.equal_chooser_mean_grant_rate_pct,100*(frame.k/frame.n).mean())
        with tempfile.TemporaryDirectory(prefix='equal_chooser_test_') as folder:
            root=Path(folder);public=root/'run_SYNTHETIC'
            report(public,result,baseline,{'sample_fingerprint':'SYNTHETIC'},
                   {'sha256':'SYNTHETIC'},{'synthetic':True},0,synthetic=True)
            (public/'private_chooser_ids.csv').write_text('chooser\nPRIVATE_ID\n')
            output=export(public,root/'transfer')
            self.assertFalse(load_json(public/'RUN_STATUS.json')['production_data_computed'])
            self.assertIn('paired 95\\%',(public/'MANUSCRIPT_SNIPPET.tex').read_text())
            with zipfile.ZipFile(output) as z:
                self.assertIsNone(z.testzip())
                self.assertFalse(any('private' in p or p.endswith('.parquet') for p in z.namelist()))
                manifest=next(p for p in z.namelist() if p.endswith('/SHA256SUMS.txt'))
                prefix=manifest.rsplit('/',1)[0]+'/'
                for line in z.read(manifest).decode().splitlines():
                    digest,path=line.split('  ',1)
                    self.assertEqual(hashlib.sha256(z.read(prefix+path)).hexdigest(),digest)
            self.assertEqual(sha256_file(output),output.with_suffix('.zip.sha256').read_text().split()[0])

    def test_bundled_current_authority(self):
        authority,report=verify_report_package()
        self.assertEqual(authority['rows'],41534331)
        self.assertEqual(authority['choosers'],3224173)


if __name__=='__main__':
    unittest.main(verbosity=2)
