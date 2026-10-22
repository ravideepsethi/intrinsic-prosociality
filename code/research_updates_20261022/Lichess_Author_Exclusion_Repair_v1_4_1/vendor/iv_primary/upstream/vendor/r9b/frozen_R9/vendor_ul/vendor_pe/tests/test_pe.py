import sys,unittest,tempfile,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from pe_common import *
import pe_scores,pe_material,pe_models,pe_runtime,pe_report
from unittest.mock import patch
sys.path.insert(0,str(previous.ROOT/'vendor_r8/vendor_r7/tests'))
from test_r7 import fixture
import chess

def sample(n=2600):
    d=fixture(n);n=len(d['row_id']);order=np.argsort(d['row_id']);d={k:v[order] for k,v in d.items()}
    d['game_id']=np.array(['game'+str(k) for k in range(n)])
    d['anchor_ms']=d['archive_start_ms']+1000
    d['complete90']=np.ones(n,bool)
    return d

def score_file(p,d):
    r.io.table(p,pa.table(dict(row_id=d['row_id'],n_24h=np.full(len(d['row_id']),99),
        adjusted_24h=d['adjusted_7d']*1.07+.001)))

class BridgeTests(unittest.TestCase):
    def test_subset_reuses_scores_and_detects_outcome_or_role_change(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);d=sample();mask=np.arange(len(d['row_id']))%3!=0;o={k:v[mask] for k,v in d.items()}
            r.io.table(p/'e.parquet',pa.table(d));r.io.table(p/'o.parquet',pa.table(o));score_file(p/'s.parquet',d)
            got,info=pe_scores.subset_scores(p/'e.parquet',p/'o.parquet',p/'s.parquet',p/'ok','test',1)
            self.assertTrue(info['verified_subset']);np.testing.assert_array_equal(r.io.arr(r.io.read(got),'row_id'),o['row_id'])
            for field in ('recipient_id','y'):
                bad=copy.deepcopy(o);bad[field][0]=bad[field][0]+1
                r.io.table(p/'bad.parquet',pa.table(bad))
                with self.assertRaisesRegex(RuntimeError,'mismatch'):
                    pe_scores.subset_scores(p/'e.parquet',p/'bad.parquet',p/'s.parquet',p/field,'test',1)

    def test_duplicate_scores_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);d=sample();r.io.table(p/'e.parquet',pa.table(d));score_file(p/'s.parquet',d)
            s=r.io.read(p/'s.parquet');r.io.table(p/'bad.parquet',pa.concat_tables([s,s.slice(0,1)]))
            with self.assertRaisesRegex(RuntimeError,'Duplicate'):
                pe_scores.subset_scores(p/'e.parquet',p/'e.parquet',p/'bad.parquet',p/'out','test',1)

class NumericalTests(unittest.TestCase):
    def test_receipt_reconstruction_matches_frozen_estimator_both_controls(self):
        for level in LEVELS:
            d=sample();d['adjusted_7d']=d['adjusted_7d']*1.07+.001
            got,payload=pe_models.receipt_influence(d,'S0',level)
            old,oldinf=models.estimate(d,'iv','fixture',level,part_a=False,calibration=False)
            targets=[]
            for row in old['B_estimates']:
                if row['estimator']=='reduced_form':targets.append(dict(row,history_cutoff='lag24h',exposure_screen='all'))
            self.assertEqual(len(pe_models.verify_receipt(got,targets,level,'all')),2)
            for key in ('y','reached'):np.testing.assert_allclose(payload[key],oldinf[key],rtol=2e-7,atol=1e-11)
            targets[0]['coefficient_pp']+=.01
            with self.assertRaisesRegex(RuntimeError,'failed'):pe_models.verify_receipt(got,targets,level,'all')

    def test_receipt_gate_checks_row_set(self):
        d=sample();got,_=pe_models.receipt_influence(d,'S0','X0');targets=copy.deepcopy(got['B_estimates'])
        targets[0]['row_set_sha256']='changed'
        with self.assertRaisesRegex(RuntimeError,'rows changed'):pe_models.verify_receipt(got,targets,'X0','all')

    def test_shared_covariance_contrast_against_explicit_account_date_pairs(self):
        rng=np.random.default_rng(119)
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);all_data=[]
            for side,n in [('l',42),('r',55)]:
                folder=p/side;folder.mkdir();i=rng.integers(1,12,n);j=rng.integers(13,25,n)
                i[::3],j[::3]=j[::3].copy(),i[::3].copy()
                a=dict(recipient_id=i,opponent_id=j,date=rng.integers(1,8,n),y=rng.normal(size=n),reached=rng.normal(size=n))
                all_data.append(a);r.io.table(folder/'influence_PRIVATE.parquet',pa.table(a))
                r.io.js(folder/'result.json',dict(B_estimates=[dict(outcome=k,estimator='reduced_form',n=n,row_set_sha256=side,
                    coefficient_pp=.3 if side=='l' else .1) for k in ('y','reached')]))
            got=models.contrast(p/'l',p/'r',{})
            left,right=all_data;i=np.r_[left['recipient_id'],right['recipient_id']];j=np.r_[left['opponent_id'],right['opponent_id']]
            date=np.r_[left['date'],right['date']]
            H=(i[:,None]==i)|(i[:,None]==j)|(j[:,None]==i)|(j[:,None]==j)|(date[:,None]==date)
            for row in got:
                s=np.r_[left[row['outcome']],-right[row['outcome']]];var=float(s@H@s)
                self.assertAlmostEqual(row['coefficient_pp'],.2,12)
                if var>0:self.assertAlmostEqual(row['standard_error_pp']**2,var,9)
                else:self.assertFalse(row['supported'])

    def test_new_fit_preserves_controls_and_creates_resumable_influences(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);d=sample();r.io.table(p/'d.parquet',pa.table(d));score_file(p/'s.parquet',d)
            job=dict(input=str(p/'d.parquet'),scores=str(p/'s.parquet'),output=str(p/'fit'),conf='test',
                sample='O50',kind='ordinary',level='X0',selection='all',memory_gb=1)
            captured=[];real=models.estimate
            def inspect(values,*args,**kwargs):
                captured.append({k:v.copy() for k,v in values.items()});return real(values,*args,**kwargs)
            with patch('pe_models.models.estimate',side_effect=inspect):pe_models.fit_job(job)
            self.assertTrue((p/'fit/influence_PRIVATE.parquet').exists())
            for key in r.FIT_COLUMNS:
                if key in d and key!='adjusted_7d':np.testing.assert_array_equal(d[key],captured[0][key])
            pe_models.fit_job(job)
            d['y'][0]=1-d['y'][0];r.io.table(p/'d.parquet',pa.table(d))
            with self.assertRaisesRegex(RuntimeError,'input changed'):pe_models.fit_job(job)

class CoverageTests(unittest.TestCase):
    def test_no_source_is_unknown_not_zero_or_neutral(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);r.io.table(p/'o.parquet',pa.table(dict(row_id=[1,2])))
            out,info=pe_material.audit(p/'o.parquet',[],{},p/'audit','test',1)
            self.assertIsNone(out);self.assertIsNone(info['material_coverage_fraction'])
            self.assertEqual(info['imputed_rows'],0);self.assertFalse(info['restricted_placebo_run'])

    def test_final_fen_boundaries_missing_and_conflicts(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);o=dict(row_id=[1,2,3,4],game_id=['a','b','c','d'],recipient_id=[11,12,13,14],
                opponent_id=[21,22,23,24],archive_start_ms=[10,20,30,40],anchor_ms=[15,25,35,45])
            r.io.table(p/'o.parquet',pa.table(o));s={k:v for k,v in o.items() if k!='row_id'}
            s.update(ply_count=[0,0,0,0],fen_after_last_move=[chess.Board().fen(),'7k/8/8/8/8/8/Rp6/7K w - - 0 1',None,chess.Board().fen()])
            r.io.table(p/'s.parquet',pa.table(s));b={k:[v[-1]] for k,v in s.items()};b['fen_after_last_move']=['7k/8/8/8/8/8/Q7/7K w - - 0 1']
            r.io.table(p/'b.parquet',pa.table(b))
            _,info=pe_material.audit(p/'o.parquet',[str(p/'s.parquet'),str(p/'b.parquet')],{},p/'audit','test',1)
            self.assertEqual(info['valid_rows'],2);self.assertEqual(info['neutral_rows'],1)
            self.assertEqual(info['status_counts']['conflicting_cached_positions'],1)
            got=r.io.read(p/'audit/material.parquet').to_pylist()
            self.assertEqual([v['material_neutral'] for v in got],[True,False,False,False])

    def test_material_identity_mismatch_stops(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);o=dict(row_id=[1],game_id=['a'],recipient_id=[1],opponent_id=[2],archive_start_ms=[100],anchor_ms=[120])
            r.io.table(p/'o.parquet',pa.table(o));s={k:v for k,v in o.items() if k!='row_id'}
            s.update(anchor_ms=[125],ply_count=[0],fen_after_last_move=[chess.Board().fen()]);r.io.table(p/'s.parquet',pa.table(s))
            with self.assertRaisesRegex(RuntimeError,'identity'):pe_material.audit(p/'o.parquet',[str(p/'s.parquet')],{},p/'out','test',1)

class RuntimeReportTests(unittest.TestCase):
    def test_new_entry_receipt_and_contrast_stages_end_to_end(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);d=sample();r.io.table(p/'d.parquet',pa.table(d));score_file(p/'s.parquet',d)
            (p/'evidence/cutoff').mkdir(parents=True)
            ready=load_scored(p/'d.parquet',p/'s.parquet')
            targets=[]
            for level in LEVELS:targets+=pe_models.receipt_influence(ready,'S0',level)[0]['B_estimates']
            r.io.js(p/'evidence/cutoff/B_estimates.json',targets)
            for level in LEVELS:
                for sample_name,kind in [('F50','entry'),('O50','ordinary'),('S0','receipt_influence')]:
                    out=p/'fits'/f'{sample_name}_{level}'
                    job=dict(input=str(p/'d.parquet'),scores=str(p/'s.parquet'),output=str(out),conf='test',
                        sample=sample_name,kind=kind,level=level,selection='all',memory_gb=1)
                    with patch('pe_models.ROOT',p):pe_models.fit_job(job)
                    result=u.load(out/'result.json')
                    expected={'analysis_entry_90','recipient_disconnect_main','active_timeout'} if kind=='entry' else {'y','reached'}
                    self.assertEqual({v['outcome'] for v in result['B_estimates']},expected)
                cj=dict(left=str(p/'fits'/f'S0_{level}'),right=str(p/'fits'/f'O50_{level}'),
                    level=level,selection='all',conf='test',output=str(p/'contrasts'/level),memory_gb=1)
                pe_models.contrast_job(cj)
                for row in u.load(p/'contrasts'/level/'result.json'):
                    self.assertAlmostEqual(row['coefficient_pp'],0.,8)
            summary=pe_report.export(p,p/'desktop','synthetic',100,'SYNTHETIC_TEST_ONLY',dict(synthetic=True))
            self.assertEqual(summary['completed_new_jobs'],6)
            self.assertEqual(len(u.load(p/'report/receipt_reconstruction_checks.json')),4)

    def test_memory_reservations_reject_oversized_worker(self):
        self.assertEqual(pe_runtime.capacity([dict(memory_gb=2)]*16,10,11),(10,9.5))
        with self.assertRaisesRegex(RuntimeError,'exceeds'):pe_runtime.capacity([dict(memory_gb=10)],10,11)

    def test_spawned_fit_and_report_manifest_without_private_data(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);d=sample();r.io.table(p/'d.parquet',pa.table(d));score_file(p/'s.parquet',d)
            job=dict(input=str(p/'d.parquet'),scores=str(p/'s.parquet'),output=str(p/'fits/ordinary'),conf='test',
                sample='O50',kind='ordinary',level='X0',selection='all',memory_gb=1)
            got=pe_runtime.mapped(pe_models.fit_job,[job],1,4,'synthetic',1)
            self.assertEqual(got[0]['rows'],len(d['row_id']))
            summary=pe_report.export(p,p/'desktop','synthetic',75,'SYNTHETIC_TEST_ONLY',dict(synthetic=True))
            self.assertEqual(summary['completed_new_jobs'],1)
            self.assertFalse(summary['receipt_IV_refitted'])
            for rec in u.load(p/'report/REPORT_MANIFEST.json'):self.assertEqual(u.sha(p/'report'/rec['path']),rec['sha256'])
            text=''.join(f.read_text() for f in (p/'report').glob('*.json'))
            self.assertNotIn('game0',text);self.assertNotIn(str(p/'d.parquet'),text)

if __name__=='__main__':unittest.main()
