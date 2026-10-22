from __future__ import annotations
import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
import numpy as np
import pandas as pd
from .adjustment import analyze_adjustment,rating_bands,activity_labels
from .features import monthly_features,merge_features,join_features,build_features
from .rates import analyze as baseline_rates
from .report import write_report,export


def make_fixture(kind='rating'):
    rows=[]
    for g,(f,l) in enumerate([(2,2),(5,5),(20,20)]):
        amounts=[(900,100),(500,500),(100,900)][g]
        for level,count in enumerate(amounts):
            for j in range(count):
                comp=(j%5<2) if level==0 else (j%5==0)
                worse=(j%5==0) if level==0 else (j%50==0)
                rating=(1400. if level==0 else 2200.) if kind=='rating' else 1500.
                tc=('180+0' if level==0 else '300+0') if kind=='time_control' else '180+0'
                a=f*int(comp);b=l*int(worse)
                rows.append(dict(chooser=len(rows),f=f,l=l,a=a,b=b,n=f+l,k=a+b,n_binary=f+l,
                    mean_rating=rating,modal_speed='blitz',modal_time_control=tc,
                    modal_opportunities=f+l,modal_rating_n=f+l,all_rating_n=f+l,
                    modal_opportunity_share=1.,distinct_time_controls=1,modal_ties=1))
    return pd.DataFrame(rows)


def rr(table,method):
    r=table[(table.method==method)&(table.comparison=='heavy_versus_light')]
    return float(r.iloc[0].ratio_of_risk_ratios)


class ScientificTests(unittest.TestCase):
    def test_boundaries_and_missingness(self):
        self.assertEqual(rating_bands([999.9,1000,1199.9,1200,2600,np.nan,0]).tolist(),
            ['below_1000','1000_to_lt1200','1000_to_lt1200','1200_to_lt1400','2600_plus','missing_rating','missing_rating'])
        self.assertEqual(activity_labels([2,6,7,16,17,1378]).tolist(),
            ['light','light','medium','medium','heavy','heavy'])

    def test_pure_rating_composition_is_removed(self):
        frame=make_fixture()
        out=analyze_adjustment(frame)
        p=out['standardized_activity_comparisons.csv']
        self.assertGreater(rr(p,'unadjusted_common_support'),2)
        self.assertAlmostEqual(rr(p,'rating_standardized'),1,places=12)
        self.assertAlmostEqual(rr(p,'rating_time_control_standardized'),1,places=12)
        rates=out['standardized_state_rates.csv']
        adjusted=rates[rates.method=='rating_standardized']
        np.testing.assert_allclose(adjusted.competitive_rate_pct,30,atol=1e-12)
        np.testing.assert_allclose(adjusted.worse_rate_pct,11,atol=1e-12)
        self.assertEqual(int(adjusted.observed_nongranters.sum()),int(((frame.a+frame.b)==0).sum()))

    def test_rating_does_not_remove_time_control_composition(self):
        out=analyze_adjustment(make_fixture('time_control'))
        p=out['standardized_activity_comparisons.csv']
        self.assertAlmostEqual(rr(p,'unadjusted_common_support'),rr(p,'rating_standardized'),places=12)
        self.assertGreater(rr(p,'rating_standardized'),2)
        self.assertAlmostEqual(rr(p,'rating_time_control_standardized'),1,places=12)

    def test_residual_activity_difference_is_retained(self):
        frame=make_fixture()
        frame['mean_rating']=1500.
        for j,g in enumerate(['light','medium','heavy']):
            idx=np.flatnonzero(activity_labels(frame.n_binary)==g)
            frame.loc[idx,'a']=frame.loc[idx,'f'].to_numpy()*(np.arange(len(idx))%10 < j+2)
            frame.loc[idx,'b']=frame.loc[idx,'l'].to_numpy()*(np.arange(len(idx))%20==0)
        out=analyze_adjustment(frame)
        self.assertAlmostEqual(rr(out['standardized_activity_comparisons.csv'],'rating_time_control_standardized'),2,places=12)

    def test_single_cell_covariance_matches_direct_chooser_mean(self):
        frame=make_fixture();frame['mean_rating']=1500.
        out=analyze_adjustment(frame)
        rates=out['standardized_state_rates.csv']
        base,_,_=baseline_rates(frame)
        for g in ['light','medium','heavy']:
            b=base[(base.scope==g)&(base.weighting=='equal_chooser')].iloc[0]
            for method in rates.method.unique():
                a=rates[(rates.scope==g)&(rates.method==method)].iloc[0]
                for name in ['competitive_rate_pct','worse_rate_pct','gap_pp','gap_se_pp','risk_ratio','log_rr_se']:
                    self.assertAlmostEqual(float(a[name]),float(b[name]),places=10)
        changes=out['paired_adjustment_changes.csv']
        np.testing.assert_allclose(changes.adjusted_to_unadjusted_ror,1,atol=1e-12)
        np.testing.assert_allclose(changes.log_ror_change_se,0,atol=1e-9)

    def test_paired_covariance_not_independent_comparison(self):
        out=analyze_adjustment(make_fixture())
        c=out['paired_adjustment_changes.csv']
        row=c[(c.comparison=='heavy_versus_light')&(c.method=='rating_standardized')].iloc[0]
        p=out['standardized_activity_comparisons.csv']
        s=p[p.comparison=='heavy_versus_light'].set_index('method').log_ratio_se
        naive=np.hypot(s['unadjusted_common_support'],s['rating_standardized'])
        self.assertGreater(row.log_ror_change_se,0)
        self.assertLess(row.log_ror_change_se,naive)
        self.assertLess(row.adjusted_to_unadjusted_ror_ci_high,1)

    def test_covariate_support_and_zero_grant_missing_cells(self):
        frame=make_fixture()
        additions=[]
        for g,(f,l) in enumerate([(2,2),(5,5),(20,20)]):
            for _ in range(5):
                row=frame.iloc[0].to_dict()
                row.update(chooser=len(frame)+len(additions),f=f,l=l,n=f+l,n_binary=f+l,a=0,b=0,k=0,
                    mean_rating=np.nan,modal_opportunities=f+l,modal_rating_n=0,all_rating_n=0,
                    modal_speed='__missing__',modal_time_control='__missing__')
                additions.append(row)
        for _ in range(3):
            row=frame.iloc[0].to_dict()
            row.update(chooser=len(frame)+len(additions),mean_rating=2800.,modal_time_control='999+0')
            additions.append(row)
        out=analyze_adjustment(pd.concat([frame,pd.DataFrame(additions)],ignore_index=True))
        flow=out['common_support_flow.csv'].set_index('scope')
        self.assertEqual(int(flow.loc['all','excluded_choosers']),3)
        self.assertEqual(int(flow.loc['all','common_missing_rating_choosers']),15)
        cells=out['within_rating_time_control_rates.csv']
        zero=cells[cells.rating_band=='missing_rating']
        self.assertEqual(len(zero),3)
        self.assertTrue(zero.supported.all())
        self.assertTrue((zero.observed_nongranters==5).all())
        self.assertTrue(zero.risk_ratio.isna().all())

    def test_target_weights_conserve_and_balance(self):
        out=analyze_adjustment(make_fixture())
        w=out['standardization_weights.csv']
        np.testing.assert_allclose(w.groupby(['scope','method']).cell_weight.sum(),1,atol=1e-12)
        joint=w[w.method=='rating_time_control_standardized'].pivot(index='cell',columns='scope',values='cell_weight')
        np.testing.assert_allclose(joint.light,joint.heavy,atol=1e-12)
        raw=w[w.method=='unadjusted_common_support']
        for _,g in raw.groupby('scope'):
            np.testing.assert_allclose(g.per_chooser_weight,1/g.chooser_count.sum(),atol=1e-12)

    def test_report_export_contains_aggregates_and_valid_manifest(self):
        frame=make_fixture();tables=analyze_adjustment(frame)
        rates,cov,pairs=baseline_rates(frame)
        tables.update({'baseline_state_rates.csv':rates,'baseline_rate_covariance_pct2.csv':cov,
            'baseline_activity_comparisons.csv':pairs})
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);public=root/'public'
            write_report(public,tables,{'RUN_STATUS.json':{'status':'SYNTHETIC_TEST','production_data_computed':False}},synthetic=True)
            output=export(public,root/'transfer','SYNTHETIC',synthetic=True)
            self.assertTrue(output.name.startswith('SYNTHETIC_'))
            with zipfile.ZipFile(output) as z:
                self.assertIsNone(z.testzip())
                manifest=next(n for n in z.namelist() if n.endswith('SHA256SUMS.txt'))
                prefix=manifest.rsplit('/',1)[0]
                for line in z.read(manifest).decode().splitlines():
                    digest,name=line.split('  ',1)
                    self.assertEqual(hashlib.sha256(z.read(prefix+'/'+name)).hexdigest(),digest)
                for name in z.namelist():
                    if name.endswith('.csv'):
                        header=next(csv.reader(z.read(name).decode().splitlines()))
                        self.assertNotIn('chooser',header)
                        self.assertNotIn('chooser_user_id',header)
            tex=(public/'ACTIVITY_RATING_ADJUSTMENT_TABLE.tex').read_text()
            self.assertEqual(tex.count('{'),tex.count('}'))


def synthetic_panel(root):
    rows=[]
    # Chooser 1's modal clock spans months; chooser 2 has a deterministic tie;
    # chooser 3 has missing ratings and must survive; a middle-state row is excluded.
    specs=[(1,'2024-01','bullet','60+0',1300,0,0),(1,'2024-02','bullet','60+0',1500,-500,1),
        (1,'2024-01','blitz','180+0',1700,0,1),(1,'2024-01','blitz','180+0',1800,-500,0),
        (1,'2024-02','blitz','180+0',1900,0,0),(1,'2024-02','blitz','180+0',2000,-500,0),
        (1,'2024-02','rapid','600+0',3000,-200,0),
        (2,'2024-01','blitz','300+0',1800,0,0),(2,'2024-02','blitz','300+0',1900,-500,0),
        (2,'2024-01','bullet','60+0',1000,0,0),(2,'2024-02','bullet','60+0',1100,-500,0),
        (3,'2024-01','blitz','180+0',None,0,0),(3,'2024-02','blitz','180+0',0,-500,0)]
    for chooser,month,speed,tc,rating,e,y in specs:
        rows.append(dict(chooser_user_id=chooser,month=month,api_speed=speed,time_control=tc,chooser_elo=rating,
            engine_eval_cp_disconnected=e,outcome_kind_draw=y,kind_draw=y,fair_competitive=e>=-100,
            clearly_worse=e<=-300,api_status='timeout'))
    data=pd.DataFrame(rows)
    records=[]
    for month,part in data.groupby('month'):
        path=root/(month+'.parquet');part.to_parquet(path,index=False)
        records.append(dict(month=month,path=path,rows=len(part),expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    counts=[]
    for chooser,part in data.groupby('chooser_user_id'):
        fair=part.engine_eval_cp_disconnected>=-100;worse=part.engine_eval_cp_disconnected<=-300
        counts.append(dict(chooser=chooser,n=len(part),k=int(part.kind_draw.sum()),f=int(fair.sum()),l=int(worse.sum()),
            a=int(part.loc[fair,'kind_draw'].sum()),b=int(part.loc[worse,'kind_draw'].sum())))
    return records,pd.DataFrame(counts)


class SourceTests(unittest.TestCase):
    def test_scan_merge_join_resume_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);records,census=synthetic_panel(root)
            private=root/'private';private.mkdir()
            output,receipt,_=build_features({'month_records':records},private,'synthetic',workers=1,threads=1)
            joined,proof=join_features(census,output)
            f=joined.set_index('chooser')
            self.assertEqual(proof['both_state_choosers'],3)
            self.assertEqual(f.loc[1,'modal_time_control'],'180+0')
            self.assertEqual(f.loc[1,'mean_rating'],1850)
            self.assertEqual(f.loc[1,'n_binary'],6)
            self.assertEqual(f.loc[2,'modal_speed'],'blitz')
            self.assertEqual(f.loc[2,'modal_ties'],2)
            self.assertTrue(pd.isna(f.loc[3,'mean_rating']))
            _,_,resumed=build_features({'month_records':records},private,'synthetic',workers=1,threads=1)
            self.assertTrue(all(r['resumed'] for r in resumed))
            damaged=census.copy();damaged.loc[0,'a']+=1
            with self.assertRaisesRegex(RuntimeError,'counts/grants'):
                join_features(damaged,output)
            cache=private/'monthly'/(records[0]['month']+'.parquet')
            cache.write_bytes(b'tampered')
            task=dict(records[0],path=str(records[0]['path']),cache=str(private/'monthly'),contract='synthetic')
            with self.assertRaisesRegex(RuntimeError,'checksum'):
                monthly_features(task)

    def test_parallel_scan(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);records,census=synthetic_panel(root)
            private=root/'private';private.mkdir()
            output,_,_=build_features({'month_records':records},private,'synthetic_parallel',workers=2,threads=1)
            joined,_=join_features(census,output)
            self.assertEqual(len(joined),3)


if __name__=='__main__':unittest.main(verbosity=2)
