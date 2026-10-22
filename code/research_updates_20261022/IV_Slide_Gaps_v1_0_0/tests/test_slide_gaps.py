"""Meaningful offline tests; these never certify real-data results."""
from __future__ import annotations
import sys, tempfile, unittest, hashlib, json, zipfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'code'))
from common import *
import common
import diagnostics as diag
import cache_audit as audit
import run_slide_gaps as runner
import expanded_stats as design
import comparison_core as cmp
import followup_stats as stats
import iv_numerics as num

def fixture(n=1400, seed=2718):
    rng = np.random.default_rng(seed)
    recipient = rng.integers(0, 170, n)
    opponent = rng.integers(0, 210, n)
    opponent[opponent == recipient] += 300
    history_n = rng.integers(5, 100, n)
    taste = rng.beta(.8, 6, n)
    grants = rng.binomial(history_n, taste)
    expected = rng.uniform(.01, .06, n)
    z = grants/history_n - expected
    D = rng.random(n) < np.clip(.04+.65*(z+.04), .003, .7)
    R = rng.random(n) < .6
    Y = R & (rng.random(n) < .04)
    d = dict(row_id=np.arange(n), recipient_id=recipient, opponent_id=opponent,
             received=D, y=Y, reached=R,
             recipient_rating=rng.integers(1300, 1500, n).astype(float),
             opponent_rating=rng.integers(1300, 1500, n).astype(float),
             archive_start_ms=(20000+rng.integers(0, 12, n))*86400000+rng.integers(0, 4, n)*3600000,
             month_code=np.zeros(n, int), tc_base_s=np.full(n, 180), tc_inc_s=np.zeros(n, int),
             n_7d=history_n, adjusted_7d=z, expected_7d=expected,
             counterparts_7d=np.maximum(1, history_n-rng.integers(0, 4, n)),
             pre_games_30d=rng.poisson(50, n))
    for days in (90, 30):
        fair = rng.poisson(3, n)
        d[f'fair_{days}'] = fair
        d[f'kind_{days}'] = rng.binomial(fair, .12)
        d[f'disconnect_{days}'] = rng.poisson(2, n)
        d[f'receipt_{days}'] = rng.poisson(.1, n)
        d[f'claim_{days}'] = rng.poisson(4, n)
    return d

class NumericalTests(unittest.TestCase):
    def test_outcomes_exact_denominators_and_zero_reach(self):
        d = dict(received=np.array([0,0,0,1,1]), y=np.array([1,0,0,0,1]), reached=np.array([1,1,0,0,1]))
        rows = diag.outcome_levels(d)
        self.assertEqual((rows[1]['N'], rows[1]['Y_ones'], rows[1]['R_ones']), (3,1,2))
        self.assertAlmostEqual(rows[1]['mean_Y'], 1/3)
        self.assertAlmostEqual(rows[1]['mean_Y_given_R'], .5)
        for row in rows:
            self.assertAlmostEqual(row['mean_Y'], row['mean_R']*row['mean_Y_given_R'])
        self.assertIsNone(diag.outcome_levels(dict(received=[0], y=[0], reached=[0]))[0]['mean_Y_given_R'])
        with self.assertRaises(RuntimeError):
            diag.outcome_levels(dict(received=[0], y=[1], reached=[0]))

    def test_integer_history_and_population_denominators(self):
        d = dict(opponent_id=np.array([2,1,1,1]), row_id=np.array([7,5,4,3]),
                 archive_start_ms=np.array([0,10,0,0]), n_7d=np.array([10,10,10,10]),
                 adjusted_7d=np.array([.15,.05,-.05,-.05]), expected_7d=np.full(4,.05))
        counts, raw = diag.historical_grants(d)
        np.testing.assert_array_equal(counts, [2,1,0,0])
        rows, histogram, info = diag.score_distribution(d)
        summaries = {r['population']:r for r in rows if r['variable']=='adjusted_score_Z'}
        self.assertAlmostEqual(summaries['exposure_weighted']['zero_grant_history_share'], .5)
        self.assertAlmostEqual(summaries['equal_opponent_weight_across_exposures']['zero_grant_history_share'], 1/3)
        self.assertAlmostEqual(summaries['one_snapshot_per_opponent']['zero_grant_history_share'], .5)
        self.assertEqual(summaries['one_snapshot_per_opponent']['observations'], 2)
        for pop in summaries:
            self.assertAlmostEqual(sum(h['share'] for h in histogram if h['population']==pop and h['variable']=='adjusted_score_Z'), 1)
        d['adjusted_7d'][0] += .001
        with self.assertRaises(RuntimeError):
            diag.historical_grants(d)

    def test_quantile_ties_and_weighted_quantiles(self):
        z = np.array([0]*90 + [1]*10, float)
        bands, meta = diag.quantile_bands(z, 10)
        self.assertEqual(len(np.unique(bands[:90])), 1)
        self.assertEqual(meta['actual_bands'], 2)
        np.testing.assert_array_equal(diag.weighted_quantiles([0,10,20],[8,1,1]),[0,0,10])

    def test_shared_account_or_date_against_explicit_adjacency(self):
        i=np.array([1,2,3,4,1,2,6,7,8,9])
        j=np.array([2,1,4,5,5,6,7,8,9,1])
        date=np.array([0,0,1,2,3,4,3,5,6,7])
        score=np.random.default_rng(10).normal(size=(len(i),3))
        adjacency=np.array([[bool({i[a],j[a]} & {i[b],j[b]}) or date[a]==date[b]
                             for b in range(len(i))] for a in range(len(i))],float)
        expected=score.T@adjacency@score
        actual=stats.shared_meat(score,cmp.covariance_codes(i,j,date),True)
        np.testing.assert_allclose(actual,expected,rtol=1e-12,atol=1e-12)

    def test_adjusted_bands_and_variance_against_full_dummy_ols(self):
        d=fixture()
        # Distinct accounts leave date clustering, whose band covariance is PSD.
        # A separate adjacency test covers overlapping accounts across both roles.
        d['recipient_id']=2*np.arange(len(d['row_id']))
        d['opponent_id']=d['recipient_id']+1
        rows, model=diag.first_stage_bands(d,5)
        xs,names,_,_,groups,_=design.controls(d,True)
        band,_=diag.quantile_bands(d['adjusted_7d'],5)
        K=int(band.max()+1)
        fe=[]
        for g in groups:
            fe.extend([(g==v).astype(float) for v in np.unique(g)[1:]])
        B=np.column_stack([(band==k).astype(float) for k in range(1,K)])
        W=np.column_stack([np.ones(len(band))]+xs+fe+[B[:,k] for k in range(K-1)])
        D=d['received'].astype(float)
        Wplus=np.linalg.pinv(W,rcond=1e-11)
        beta=Wplus@D
        predictions=np.tile(W.mean(axis=0),(K,1))
        predictions[:,-(K-1):]=np.vstack([np.zeros(K-1),np.eye(K-1)])
        np.testing.assert_allclose([r['adjusted_receipt_percent'] for r in rows],100*predictions@beta,rtol=1e-7,atol=2e-7)
        scores=(predictions@Wplus).T*(D-W@beta)[:,None]
        vcov=stats.shared_meat(scores,cmp.covariance_codes(d['recipient_id'],d['opponent_id'],groups[1]),True)
        self.assertTrue(model['band_covariance_psd'])
        np.testing.assert_allclose([r['adjusted_SE_pp'] for r in rows],100*np.sqrt(np.diag(vcov)),rtol=2e-7,atol=2e-7)
        Z=np.column_stack([np.ones(len(band))]+xs+fe+[d['adjusted_7d']])
        linear=np.linalg.lstsq(Z,D,rcond=1e-11)[0][-1]
        self.assertAlmostEqual(model['linear_first_stage']['coefficient'],linear,places=7)
        expected=dict(model['linear_first_stage'])
        expected['coefficient'] += .01
        with self.assertRaisesRegex(RuntimeError,'reproduction failed'):
            diag.first_stage_bands(d,5,expected)

    def test_nonlinearity_flags_signal_and_does_not_repair_bad_covariance(self):
        self.assertFalse(diag.joint_zero(np.array([1.,1.]),np.array([[1.,2.],[2.,1.]]))['supported'])
        self.assertFalse(diag.joint_zero(np.array([1.,0.]),np.diag([1.,0.]))['supported'])
        self.assertLess(diag.joint_zero(np.array([.2,.3]),np.diag([.001,.001]))['p_value_asymptotic'],1e-15)

class WorkflowTests(unittest.TestCase):
    def test_run2_process_snapshot_filters_and_does_not_export_argv(self):
        text=''' 123 01:02:03 92.0 /usr/bin/python code/run_optimized.py --project-root /Volumes/XT_Pro/lichess_kindness --private sensitive_value
456 00:01 0.0 /usr/bin/python /unrelated/code/run_optimized.py
789 02:00 3.0 /bin/bash run_phase_analysis.py
'''
        result=audit.parse_run2_processes(text,Path('/Volumes/XT_Pro/lichess_kindness'))
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['process_id'],123)
        self.assertEqual(result[0]['role'],'analysis')
        self.assertNotIn('sensitive_value',json.dumps(result))

    def test_cohort_checksum_and_schema_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); path=root/common.HEADLINE_REL; path.parent.mkdir(parents=True)
            d=fixture(150);pq.write_table(pa.table(d),path)
            digest=io.sha(path)
            with patch.object(common,'HEADLINE_SHA',digest),patch.object(common,'HEADLINE_BYTES',path.stat().st_size),patch.object(common,'HEADLINE_N',150):
                common.authenticate_headline(root)
                self.assertEqual(len(common.read_cohort(path,True)['row_id']),150)
                with path.open('ab') as f:f.write(b'x')
                with self.assertRaises(RuntimeError):common.authenticate_headline(root)
            pq.write_table(pa.table({'received':[True]}),path)
            with self.assertRaisesRegex(RuntimeError,'missing'):common.read_cohort(path,True)

    def test_profile_fields_no_values_exported(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);profiles=root/'profiles';profiles.mkdir()
            pq.write_table(pa.Table.from_pylist([{'id':'never_export_this_user','profile':{'country':'ZZ_PRIVATE','flag':'PRIVATE_FLAG'}}]),profiles/'snapshot.parquet')
            (profiles/'raw.jsonl').write_text(json.dumps({'id':'never_export_this_user','profile':{'country':'ZZ_PRIVATE'}})+'\n')
            (profiles/'flat.csv').write_text('id,profile.country\nnever_export_this_user,ZZ_PRIVATE\n')
            with pa.output_stream(profiles/'compressed.jsonl.zst',compression='zstd') as f:
                f.write((json.dumps({'profile':{'flag':'PRIVATE_FLAG'}})+'\n').encode())
            rows,summary=audit.audit_profiles(root,root)
            serialized=json.dumps(rows)
            self.assertEqual(summary['status'],'NONEMPTY_GEO_FIELD_FOUND')
            self.assertNotIn('never_export_this_user',serialized)
            self.assertNotIn('ZZ_PRIVATE',serialized)
            self.assertNotIn('PRIVATE_FLAG',serialized)
            self.assertIn('profile.country',serialized)
            self.assertFalse(summary['country_balance_run'])
            self.assertEqual(summary['files_with_sampled_nonempty_geo_values'],4)

    def test_end_to_end_package_and_checkpoint_reuse(self):
        import argparse
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'project';root.mkdir();desktop=Path(temp)/'desktop';desktop.mkdir()
            d=fixture(1100);source=root/'fixture.parquet';pq.write_table(pa.table(d),source)
            _,model=diag.first_stage_bands(d,5)
            expected=model['linear_first_stage']
            args=argparse.Namespace(project_root=root,desktop=desktop,bands=5,headline_only=True,profile_path=[])
            with patch.object(runner,'verify_release',return_value='synthetic_test'),\
                 patch.object(runner,'authenticate_headline',return_value=(source,dict(sha256=io.sha(source)))),\
                 patch.object(runner,'HEADLINE_FIT',expected):
                runner.execute(args)
            reports=list(desktop.glob('IV_SLIDE_GAPS_REPORT_*.zip'))
            self.assertEqual(len(reports),1)
            with zipfile.ZipFile(reports[0]) as z:
                names=z.namelist()
                self.assertIn('READ_RESULTS.txt',names)
                self.assertIn('headline_original/first_stage_bands.csv',names)
                self.assertIn('headline_original/outcome_levels.csv',names)
                self.assertTrue(all('PRIVATE' not in name for name in names))
                self.assertTrue(all(not name.endswith('.parquet') for name in names))
                done=json.loads(z.read('_DONE.json'))
                for rec in done['files']:
                    content=z.read(rec['path'])
                    self.assertEqual(hashlib.sha256(content).hexdigest(),rec['sha256'])
            checkpoint=next((root/'derived/replication/iv_slide_gaps_v100_PRIVATE').glob('*/headline_original'))
            done=io.load(checkpoint/'_DONE.json')
            with patch.object(runner,'read_cohort',side_effect=AssertionError('Should reuse completed stage')):
                runner.analyze_cohort(source,checkpoint,done['config_sha256'],'headline_original',5,True,expected)

if __name__=='__main__':
    unittest.main()
