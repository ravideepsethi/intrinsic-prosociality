import sys,argparse,unittest,tempfile,json
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('--base-package',type=Path,required=True)
args,remaining=parser.parse_known_args()
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'code'))
import run_independent as new
new.base.initialize(args.base_package)
sys.path.insert(0,str(args.base_package/'tests'))
from test_receipt import fixture
import r7_models
import numpy as np
u=new.base.u

def data(n=2800):
    d=fixture(n);d['reached']=np.ones(n,bool);d['environment_supported']=np.ones(n,bool)
    return d

class IndependentTests(unittest.TestCase):
    def test_nested_sparse_FE_and_NH_against_explicit_dummy_OLS(self):
        rng=np.random.default_rng(69012);n=1100
        # Month is nested in assignment cells and days; weekday is nested in hours.
        month=rng.integers(0,3,n);day=month*7+rng.integers(0,7,n);hour=(day%7)*4+rng.integers(0,4,n)
        cell=month*5+rng.integers(0,5,n);x=rng.normal(size=(n,7));y=rng.normal(size=(n,4))
        groups=[cell,day,hour];got,diag=new.independent.project(x,[y[:,j] for j in range(4)],groups)
        X=np.column_stack([np.eye(len(np.unique(g)))[np.unique(g,return_inverse=True)[1]] for g in groups]+[x])
        want=y-X@np.linalg.lstsq(X,y,rcond=1e-12)[0]
        np.testing.assert_allclose(got,want,atol=2e-11)
        self.assertGreater(diag['redundant_nuisance_directions'],2);self.assertTrue(diag['no_rows_removed'])
        self.assertTrue(diag['no_ridge'])

    def test_independent_A1_QR_covariance_and_candidate_R2(self):
        d=data();ref=r7_models.estimate({k:v.copy() for k,v in d.items()},'iv','S0','X0',calibration=True,release_inputs=True)[0]
        current=[dict(outcome=r['dependent'],trait=r['trait'],field=field,observed=r.get(field)) for r in ref['A_joint_balance'] if r['analysis']=='A1' for field in ('coefficient','standard_error')]
        x,_,traits,groups=new.base.m.r.feature_design(d,'X0');T=np.column_stack([traits[k] for k in new.base.m.r.T15])
        dummy=np.column_stack([np.eye(len(np.unique(g)))[np.unique(g,return_inverse=True)[1]] for g in groups]);full=np.column_stack([dummy,x[:,:7],T]);nh=np.column_stack([dummy,x[:,:7]])
        with tempfile.TemporaryDirectory() as td:
            diag=new.audit_a1(d,ref['A_joint_balance'],current,Path(td));self.assertTrue(diag['independent_matches_current_R7'])
            self.assertTrue(diag['archived_A1_reproduced'])
            (Path(td)/'report').mkdir();u.save(Path(td)/'report/A_predicted_outcome.json',ref['A_predicted_outcome'])
            new.calibration_point_archive_check(Path(td),Path(td))
            self.assertTrue(all(r['archived_point_reproduced'] for r in u.load(Path(td)/'A3_independent_point_checks.json')))
            rows=u.load(Path(td)/'A1_candidate_fit_statistics.json')
            for row in rows:
                y=d[row['outcome']].astype(float);e=y-full@np.linalg.lstsq(full,y,rcond=1e-12)[0];eb=y-nh@np.linalg.lstsq(nh,y,rcond=1e-12)[0]
                self.assertAlmostEqual(row['candidate_partial_R2'],1-float(e@e)/float(eb@eb),9)

    def test_historical_mismatch_remains_explicit_and_current_mismatch_blocks(self):
        d=data();ref=r7_models.estimate({k:v.copy() for k,v in d.items()},'iv','S0','X0',calibration=False)[0]
        current=[dict(outcome=r['dependent'],trait=r['trait'],field=field,observed=r.get(field)) for r in ref['A_joint_balance'] if r['analysis']=='A1' for field in ('coefficient','standard_error')]
        old=[r.copy() for r in ref['A_joint_balance']];bad=next(r for r in old if r['analysis']=='A1' and r['dependent']=='y' and r['trait']=='fair_history_present_30');bad['coefficient']+=.002
        with tempfile.TemporaryDirectory() as td:
            diag=new.audit_a1(d,old,current,Path(td))
            self.assertTrue(diag['independent_matches_current_R7']);self.assertFalse(diag['archived_A1_reproduced'])
            self.assertFalse(diag['tolerance_relaxed']);self.assertFalse(diag['historical_root_cause_identified'])
            next(r for r in current if r['outcome']=='y' and r['trait']=='fair_history_present_30' and r['field']=='coefficient')['observed']+=.002
            with self.assertRaisesRegex(RuntimeError,'Independent A1 QR'):new.audit_a1(d,old,current,Path(td))

    def test_core_IV_gate_uses_original_tolerances(self):
        d=data();ref=r7_models.estimate(d.copy(),'iv','S0','X0',part_a=False)[0]
        with tempfile.TemporaryDirectory() as td:
            r7=Path(td);(r7/'report').mkdir();u.save(r7/'report/B_estimates.json',ref['B_estimates'])
            new.core_gate(d,r7,r7/'report')
            ref['B_estimates'][0]['coefficient_pp']+=.02;u.save(r7/'report/B_estimates.json',ref['B_estimates'])
            with self.assertRaisesRegex(RuntimeError,'Core S0 IV'):new.core_gate(d,r7,r7/'report')

    def test_partial_export_keeps_A1_open_and_private_or_failed_fits_out(self):
        import zipfile
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);run=root/'run';report=run/'report';report.mkdir(parents=True);old=root/'old';old.mkdir();desktop=root/'desktop';desktop.mkdir()
            u.save(report/'A1_independent_diagnostics.json',{'archived_A1_reproduced':False})
            u.save(report/'experience_IV.json',[{'estimate':.3}]);(run/'raw_account_rows.parquet').write_text('private')
            new.export(run,desktop,'a'*64,old,'b'*64,'INDEPENDENT_CURRENT_FIT_VALIDATED_ARCHIVE_OPEN','BLOCKED','fixture failure')
            with zipfile.ZipFile(next(desktop.glob('*.zip'))) as z:
                self.assertFalse(any('experience_IV.json' in n or 'raw_account' in n for n in z.namelist()))
                s=json.loads(z.read('R8_RECEIPT_INDEPENDENT_REPORT/SUMMARY.json'))
                self.assertEqual(s['item2'],'BLOCKED_ARCHIVED_A1_NOT_REPRODUCED');self.assertEqual(s['item4'],'BLOCKED')
                self.assertTrue(s['no_headline_promotion']);self.assertFalse(s['coefficient_tolerance_relaxed'])
            new.export(run,desktop,'a'*64,old,'b'*64,'INDEPENDENT_CURRENT_FIT_VALIDATED_ARCHIVE_OPEN','COMPLETE',None)
            with zipfile.ZipFile(next(desktop.glob('*.zip'))) as z:
                self.assertTrue(any('experience_IV.json' in n for n in z.namelist()))
                s=json.loads(z.read('R8_RECEIPT_INDEPENDENT_REPORT/SUMMARY.json'))
                self.assertEqual(s['item2'],'BLOCKED_ARCHIVED_A1_NOT_REPRODUCED');self.assertEqual(s['item4'],'COMPLETE')

    def test_completed_Patron_clock_reuse_is_verified_and_read_only(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);run=root/'run';(run/'report').mkdir(parents=True);old=root/'old';old.mkdir();desktop=root/'desktop';desktop.mkdir()
            source=root/'input';source.write_text('frozen input');basekey='fixture';states={}
            for name in ('patron','clocks'):
                report=old/name/'report';report.mkdir(parents=True);u.save(report/'aggregate.json',{'coefficient':.4})
                u.certify(old/name,u.digest([basekey,name]),[source]);states[name]={'state':'COMPLETE'}
            u.save(old/'STATE.json',{'modules':states})
            before={str(p):u.sha(p) for p in old.rglob('*') if p.is_file()}
            new.export(run,desktop,'a'*64,old,basekey,'ARCHIVE_OPEN','COMPLETE',None)
            self.assertEqual(before,{str(p):u.sha(p) for p in old.rglob('*') if p.is_file()})
            s=u.load(run/'PUBLIC/SUMMARY.json');self.assertEqual(s['module_states']['patron']['state'],'COMPLETE');self.assertEqual(s['module_states']['clocks']['state'],'COMPLETE')
            source.write_text('changed dependency')
            new.export(run,desktop,'a'*64,old,basekey,'ARCHIVE_OPEN','BLOCKED','fixture')
            s=u.load(run/'PUBLIC/SUMMARY.json');self.assertEqual(s['module_states']['patron']['state'],'NOT_REUSED')
            self.assertFalse((run/'PUBLIC/patron').exists());self.assertFalse((run/'PUBLIC/clocks').exists())

if __name__=='__main__':unittest.main(argv=[sys.argv[0]]+remaining,verbosity=2)
