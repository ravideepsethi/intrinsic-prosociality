"""Small synthetic checks; no production data or reported estimates generated."""
from __future__ import annotations
import concurrent.futures as cf
import multiprocessing as mp
from pathlib import Path
import tempfile
import unittest
import hashlib
import zipfile
import numpy as np
import pandas as pd
from .audit import (FIELDS,calculate,month_census,merge_census,distribution,
                    verify_reference,export,report)
from .common import sha256_file,load_json,atomic_json,verify_report_package


def fixture():
    # Unequal state counts, zero-outcome state switchers, singletons, same-state
    # repeat choosers and middle-only choosers all occur in this fixture.
    specifications={
        'a':[(-100,1),(-300,0)],
        'b':[(-100,1)]*3+[(-300,0)]*5,
        'c':[(-100,0)]*5+[(-300,0)]*5,
        'd':[(-100,1)], 'e':[(-300,0)],
        'f':[(-100,1),(-100,0)], 'g':[(-200,0)],
        'h':[(-100,0),(-300,1),(-200,0)],
    }
    rows=[]
    for chooser,opportunities in enumerate(specifications.values(),start=1):
        for j,(cp,y) in enumerate(opportunities):
            rows.append(dict(chooser_user_id=chooser,month='2024-01' if j%2==0 else '2024-02',
                             outcome_kind_draw=y,kind_draw=y,engine_eval_cp_disconnected=cp,
                             fair_competitive=cp>=-100,clearly_worse=cp<=-300,api_status='timeout'))
    return pd.DataFrame(rows).astype({'outcome_kind_draw':'bool','kind_draw':'bool',
                                     'engine_eval_cp_disconnected':'int32'})


def direct_groups(raw):
    rows=[]
    for chooser,group in raw.groupby('chooser_user_id',sort=True):
        fair=group.engine_eval_cp_disconnected>=-100
        worse=group.engine_eval_cp_disconnected<=-300
        y=group.outcome_kind_draw
        rows.append(dict(chooser=chooser,n=len(group),f=int(fair.sum()),l=int(worse.sum()),
                         k=int(y.sum()),a=int(y[fair].sum()),b=int(y[worse].sum())))
    return pd.DataFrame(rows)


class AuditTests(unittest.TestCase):
    def test_literal_demeaning_and_cluster_scores(self):
        raw=fixture()
        raw=raw[(raw.engine_eval_cp_disconnected>=-100)|(raw.engine_eval_cp_disconnected<=-300)].copy()
        raw['x']=(raw.engine_eval_cp_disconnected>=-100).astype(float)
        raw['y']=raw.outcome_kind_draw.astype(float)
        demeaned=raw[['x','y']]-raw.groupby('chooser_user_id')[['x','y']].transform('mean')
        x,y=demeaned.x.to_numpy(),demeaned.y.to_numpy()
        beta=np.linalg.lstsq(x[:,None],y,rcond=None)[0][0]
        scores=pd.Series(x*(y-x*beta)).groupby(raw.chooser_user_id.to_numpy()).sum()
        N,G=len(raw),raw.chooser_user_id.nunique()
        se=np.sqrt((scores@scores)/(x@x)**2*G/(G-1)*(N-1)/(N-G-1))
        summaries,pmf,support,results=calculate(direct_groups(fixture()))
        row=results[(results['sample']=='all_contrast_accounts')&(results.covariance=='C7R_reported_CR1')].iloc[0]
        self.assertAlmostEqual(row.estimate_pp,100*beta,places=12)
        self.assertAlmostEqual(row.se_pp,100*se,places=12)
        self.assertTrue(support['coefficient_same_at_4_decimal_pp'])
        self.assertFalse(support['reported_C7R_se_same_at_4_decimal_pp'])
        self.assertEqual(support['choosers_seen_in_both_states'],4)
        self.assertEqual(support['contrast_singleton_choosers'],2)
        self.assertEqual(support['full_panel_accounts_absent_from_binary_contrast'],1)
        # Observed switcher gaps are [1,1,0,-1]; OLS is not their equal-weight mean.
        self.assertGreater(abs(beta-.25),.05)
        self.assertAlmostEqual(support['share_identifying_weight_no_grant_in_contrast'],2.5/5.375)
        main=summaries.iloc[0]
        self.assertEqual(int(main.choosers_more_than_one),5)
        self.assertEqual(main['median'],2)
        self.assertEqual(int(main.opportunities),28)

    def test_reference_reproduction_and_rejection(self):
        _,_,support,results=calculate(direct_groups(fixture()))
        row=results[(results['sample']=='all_contrast_accounts')&(results.covariance=='C7R_reported_CR1')].iloc[0].to_dict()
        row['se_cr1_pp']=row['se_pp']
        authority={'current_minimal_desert_model':row}
        self.assertEqual(verify_reference(results,support,authority)['status'],'CURRENT_C7R_REFERENCE_REPRODUCED')
        row['rows']+=1
        with self.assertRaisesRegex(RuntimeError,'count mismatch'):verify_reference(results,support,authority)

    def test_month_census_spawn_merge_resume_and_corruption(self):
        raw=fixture()
        with tempfile.TemporaryDirectory(prefix='chooser_support_test_') as directory:
            private=Path(directory)
            tasks=[]
            for month,frame in raw.groupby('month'):
                source=private/(month+'_source.parquet');frame.to_parquet(source,index=False)
                tasks.append(dict(month=month,path=str(source),rows=len(frame),expected_sha256=sha256_file(source),
                                  cache=str(private/'monthly'),memory='128MB',contract='synthetic'))
            with cf.ProcessPoolExecutor(max_workers=2,mp_context=mp.get_context('spawn')) as pool:
                outcomes=list(pool.map(month_census,tasks))
            self.assertTrue(all(not r['resumed'] for r in outcomes))
            output=merge_census(private,'synthetic',threads=1,memory='128MB')
            observed=pd.read_parquet(output).sort_values('chooser').reset_index(drop=True)
            pd.testing.assert_frame_equal(observed,direct_groups(raw),check_dtype=False)
            self.assertEqual(merge_census(private,'synthetic'),output)
            self.assertTrue(month_census(tasks[0])['resumed'])
            cached=private/'monthly'/(tasks[0]['month']+'.parquet')
            cached.write_bytes(cached.read_bytes()+b'corruption')
            with self.assertRaisesRegex(RuntimeError,'checksum mismatch'):month_census(tasks[0])
            wrong=dict(tasks[1],contract='wrong')
            with self.assertRaisesRegex(RuntimeError,'authority mismatch'):month_census(wrong)

    def test_source_alias_failure(self):
        with tempfile.TemporaryDirectory(prefix='chooser_support_test_') as directory:
            root=Path(directory);raw=fixture();raw=raw[raw.month=='2024-01'].copy()
            raw.loc[raw.index[0],'fair_competitive']=False
            source=root/'bad.parquet';raw.to_parquet(source,index=False)
            task=dict(month='2024-01',path=str(source),rows=len(raw),expected_sha256=sha256_file(source),
                      cache=str(root/'cache'),memory='128MB',contract='synthetic')
            with self.assertRaisesRegex(RuntimeError,'Source QA failed'):month_census(task)

    def test_distribution_conservation(self):
        summary,pmf=distribution([1,1,2,4,20],'synthetic')
        self.assertEqual(summary['median'],2)
        self.assertEqual(summary['choosers_more_than_one'],3)
        self.assertEqual(int(pmf.choosers.sum()),5)
        self.assertEqual(int(pmf.opportunities.sum()),28)

    def test_report_and_export_inventory(self):
        summaries,pmf,support,results=calculate(direct_groups(fixture()))
        with tempfile.TemporaryDirectory(prefix='chooser_support_test_') as directory:
            root=Path(directory);public=root/'public'
            report(public,summaries,pmf,support,results,{'fingerprint':'SYNTHETIC'},
                   {'sha256':'SYNTHETIC'},0,{'status':'SYNTHETIC'},synthetic=True)
            atomic_json(public/'ENVIRONMENT.json',{'status':'SYNTHETIC'})
            # Even a CSV in the public directory must not enter the archive unless named explicitly.
            (public/'private_chooser_ids.csv').write_text('chooser_id\nSECRET_ID\n')
            output=export(public,root/'transfer')
            self.assertFalse(load_json(public/'RUN_STATUS.json')['production_data_computed'])
            self.assertIn('median of 2;', (public/'DESIGN_I_COUNT_PARAGRAPH.txt').read_text())
            with zipfile.ZipFile(output) as z:
                self.assertIsNone(z.testzip())
                self.assertFalse(any('private' in name or name.endswith('.parquet') for name in z.namelist()))
                manifest_name=next(name for name in z.namelist() if name.endswith('/SHA256SUMS.txt'))
                prefix=manifest_name.rsplit('/',1)[0]+'/'
                for line in z.read(manifest_name).decode().splitlines():
                    digest,name=line.split('  ',1)
                    self.assertEqual(hashlib.sha256(z.read(prefix+name)).hexdigest(),digest)
            digest=output.with_suffix('.zip.sha256').read_text().split()[0]
            self.assertEqual(sha256_file(output),digest)

    def test_current_authority_and_projection_fields(self):
        authority,reference=verify_report_package()
        self.assertEqual(authority['rows'],41534331)
        required=set(fixture().columns)
        for month in reference['panel_outputs']:
            schema={field['name']:field['type'] for field in month['schema']}
            self.assertTrue(required.issubset(schema))
            self.assertEqual(schema['chooser_user_id'],'int64')
            self.assertEqual(schema['outcome_kind_draw'],'bool')


if __name__=='__main__':
    unittest.main(verbosity=2)
