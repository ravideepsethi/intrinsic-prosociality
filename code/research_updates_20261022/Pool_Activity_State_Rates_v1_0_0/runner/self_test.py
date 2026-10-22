from __future__ import annotations
import hashlib
import math
from pathlib import Path
import tempfile
import unittest
import zipfile
import numpy as np
import pandas as pd
from .common import load_json,sha256_file,verify_report_package
from .rates import group_rates,analyze,compare_activity,METHODS
from .statistics import inputs,estimate
from .run import report,export


def fixture():
    values=[(2,2,1,0),(2,2,0,1),(1,1,0,0),(4,4,2,1),(6,3,1,1),
            (5,5,0,0),(20,20,2,1),(40,10,1,1),(10,10,0,0)]
    frame=pd.DataFrame(values,columns=['f','l','a','b'],dtype=np.int64)
    frame['chooser']=np.arange(1,len(frame)+1);frame['n']=frame.f+frame.l;frame['k']=frame.a+frame.b
    return frame[['chooser','n','f','l','k','a','b']]


class StateRateTests(unittest.TestCase):
    def test_state_differences_and_covariance_match_previous_FE(self):
        frame=fixture();n,both,w,v,d=inputs(frame)
        previous,_,_=estimate(d,np.column_stack((w,v,np.ones(len(d)))))
        rates,cov=group_rates(frame,'all')
        for row in previous.itertuples():
            actual=rates[rates.weighting==row.estimator].iloc[0]
            self.assertAlmostEqual(actual.gap_pp,row.estimate_pp,places=11)
            self.assertAlmostEqual(actual.gap_se_pp,row.se_pp,places=11)
        raw=rates[rates.weighting=='pooled_opportunities'].iloc[0]
        self.assertAlmostEqual(raw.competitive_rate_pct,100*frame.a.sum()/frame.f.sum())
        self.assertAlmostEqual(raw.worse_rate_pct,100*frame.b.sum()/frame.l.sum())

    def test_log_ratio_delta_includes_within_chooser_covariance(self):
        frame=fixture();rates,cov=group_rates(frame,'all')
        f=(frame.a/frame.f).to_numpy();l=(frame.b/frame.l).to_numpy();G=len(f)
        pf=f.mean();pl=l.mean()
        direct=((f-pf)/pf-(l-pl)/pl)/G
        expected_se=np.sqrt(G/(G-1)*np.dot(direct,direct))
        row=rates[rates.weighting=='equal_chooser'].iloc[0]
        self.assertAlmostEqual(row.risk_ratio,pf/pl,places=12)
        self.assertAlmostEqual(row.log_rr_se,expected_se,places=12)
        self.assertAlmostEqual(row.risk_ratio_ci_low,math.exp(math.log(pf/pl)-1.959963984540054*expected_se),places=12)

    def test_zero_grant_accounts_and_zero_denominators(self):
        frame=fixture();table,_,_=analyze(frame)
        allrows=table[table.scope=='all']
        self.assertTrue((allrows.choosers==9).all())
        self.assertTrue((allrows.observed_nongranters_retained==3).all())
        frame[['a','b','k']]=0
        rates,_=group_rates(frame,'all')
        self.assertTrue(rates.risk_ratio.isna().all())
        self.assertTrue((rates.ratio_status=='undefined_both_state_rates_zero').all())
        self.assertTrue((rates.gap_pp==0).all())
        frame.loc[0,['a','k']]=1
        rates,_=group_rates(frame,'all')
        self.assertTrue((rates.ratio_status=='undefined_zero_worse_rate').all())
        self.assertTrue((rates.choosers==9).all())

    def test_smaller_baselines_can_have_the_same_ratio(self):
        light=pd.DataFrame(dict(f=[100]*3,l=[100]*3,a=[4]*3,b=[1]*3))
        heavy=pd.DataFrame(dict(f=[200]*3,l=[200]*3,a=[4]*3,b=[1]*3))
        first,_=group_rates(light,'light');second,_=group_rates(heavy,'heavy')
        for method in METHODS:
            a=first[first.weighting==method].iloc[0];b=second[second.weighting==method].iloc[0]
            self.assertAlmostEqual(a.risk_ratio,4)
            self.assertAlmostEqual(b.risk_ratio,4)
            self.assertAlmostEqual(a.gap_pp,3)
            self.assertAlmostEqual(b.gap_pp,1.5)
        comparisons=compare_activity(pd.concat([first,second],ignore_index=True))
        np.testing.assert_allclose(comparisons.ratio_of_risk_ratios,1,atol=1e-12)

    def test_activity_comparisons_and_fixed_groups(self):
        rates,_,comparisons=analyze(fixture())
        for scope in ('light','medium','heavy'):
            self.assertTrue((rates[rates.scope==scope].choosers==3).all())
        rows=rates[rates.weighting=='equal_chooser'].set_index('scope')
        expected=rows.loc['heavy'].risk_ratio/rows.loc['light'].risk_ratio
        result=comparisons[(comparisons.weighting=='equal_chooser')&(comparisons.comparison=='heavy_versus_light')].iloc[0]
        self.assertAlmostEqual(result.ratio_of_risk_ratios,expected,places=12)
        self.assertAlmostEqual(result.log_ratio_se,math.hypot(rows.loc['heavy'].log_rr_se,rows.loc['light'].log_rr_se),places=12)

    def test_report_format_and_aggregate_only_export(self):
        table,cov,comparisons=analyze(fixture())
        with tempfile.TemporaryDirectory(prefix='state_rate_test_') as directory:
            root=Path(directory);public=root/'run_SYNTHETIC'
            report(public,table,cov,comparisons,{'sample_fingerprint':'SYNTHETIC','source_census_sha256':'SYNTHETIC'},
                   {'sha256':'SYNTHETIC'},{},{},{},0,synthetic=True)
            (public/'private_ids.csv').write_text('chooser\nPRIVATE\n')
            output=export(public,root/'transfer')
            self.assertFalse(load_json(public/'RUN_STATUS.json')['production_data_computed'])
            tex=(public/'ACTIVITY_STATE_RATES_TABLE.tex').read_text()
            self.assertIn(r'Overall (\%)',tex)
            self.assertNotIn(r'\\%',tex)
            with zipfile.ZipFile(output) as z:
                self.assertIsNone(z.testzip())
                self.assertFalse(any('private' in n or n.endswith('.parquet') for n in z.namelist()))
                manifest=next(n for n in z.namelist() if n.endswith('/SHA256SUMS.txt'))
                prefix=manifest.rsplit('/',1)[0]+'/'
                for line in z.read(manifest).decode().splitlines():
                    digest,name=line.split('  ',1)
                    self.assertEqual(hashlib.sha256(z.read(prefix+name)).hexdigest(),digest)
            self.assertEqual(sha256_file(output),output.with_suffix('.zip.sha256').read_text().split()[0])

    def test_current_authority(self):
        authority,_=verify_report_package()
        self.assertEqual(authority['rows'],41534331)
        self.assertEqual(authority['choosers'],3224173)


if __name__=='__main__':unittest.main(verbosity=2)
