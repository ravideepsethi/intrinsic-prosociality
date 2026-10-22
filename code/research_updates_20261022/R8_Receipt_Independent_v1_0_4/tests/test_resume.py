import sys,argparse,unittest,tempfile,json
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('--base-package',type=Path,required=True)
args,remaining=parser.parse_known_args()
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
import receipt_resume as fix
fix.initialize(args.base_package)
sys.path.insert(0,str(args.base_package/'tests'))
from test_receipt import fixture
import r7_models
import numpy as np
u=fix.u

def data():
    d=fixture(4500);n=len(d['row_id'])
    d.update(reached=np.ones(n,bool),environment_supported=np.ones(n,bool),active_timeout=np.ones(n,bool),
        analysis_entry_90=np.arange(n)%7==0,recipient_disconnect_main=np.arange(n)%11==0)
    d['month_code'][:]=0;d['tc_base_s'][:]=120;d['tc_inc_s'][:]=0
    d['archive_start_ms']=fix.m.r.DAY*(np.arange(n)%5)+3600000*(np.arange(n)%3)
    return d

class ResumeTests(unittest.TestCase):
    def test_exact_original_R7_A1_and_independent_dummy_R2(self):
        for sample,kind,outs in [('S0','iv',['received','y']),('F50','entry',['analysis_entry_90','recipient_disconnect_main','y'])]:
            d=data();ref,_=r7_models.estimate({k:v.copy() for k,v in d.items()},kind,sample,'X0',calibration=False,release_inputs=True)
            with tempfile.TemporaryDirectory() as td:
                rows=fix.matched_r_squared(d,sample,ref['A_joint_balance'],Path(td))
                audit=u.load(Path(td)/('receipt_reproduction_'+sample+'.json'))
                self.assertEqual(len(audit),15*len(outs));self.assertTrue(all(r['passed'] for r in audit))
                X,_,traits,groups=fix.m.r.feature_design(d,'X0');T=np.column_stack([traits[k] for k in fix.m.r.T15])
                dummy=np.column_stack([np.eye(len(np.unique(g)))[u.pd.factorize(g,sort=True)[0]] for g in groups])
                base=np.column_stack([dummy,X[:,:7]]);Z=np.column_stack([base,T])
                for row,outcome in zip(rows,outs):
                    y=d[outcome].astype(float);e=y-Z@np.linalg.lstsq(Z,y,rcond=1e-11)[0]
                    eb=y-base@np.linalg.lstsq(base,y,rcond=1e-11)[0]
                    expected=[1-float(e@e)/float(eb@eb),1-float(e@e)/float((y-y.mean())@(y-y.mean()))]
                    np.testing.assert_allclose([row['trait_incremental_partial_R2'],row['FE_plus_NH_plus_traits_R2']],expected,atol=2e-8)

    def test_failed_coefficient_check_writes_actual_numbers_and_keeps_tolerance(self):
        d=data();ref,_=r7_models.estimate(d.copy(),'iv','S0','X0',calibration=False)
        row=next(r for r in ref['A_joint_balance'] if r.get('analysis')=='A1' and r['dependent']=='y' and r['trait']=='fair_history_present_30')
        row['coefficient']+=.002
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)
            with self.assertRaisesRegex(RuntimeError,'Exact R7 A1 coefficients still differ'):
                fix.matched_r_squared(d,'S0',ref['A_joint_balance'],p)
            audit=u.load(p/'receipt_reproduction_S0.json');bad=[r for r in audit if not r['passed']]
            self.assertEqual(len(bad),1);self.assertAlmostEqual(bad[0]['difference'],-.002,9)
            diag=u.load(p/'receipt_fit_diagnostics_S0.json')
            self.assertFalse(diag['acceptance_tolerance_relaxed']);self.assertEqual(diag['coefficient_tolerance'],{'rtol':3e-6,'atol':2e-9})

    def test_duplicate_archive_block_and_wrong_row_digest_are_rejected(self):
        d=data();ref,_=r7_models.estimate(d.copy(),'iv','S0','X0',calibration=False)
        r=ref['A_joint_balance'];one=next(v for v in r if v.get('analysis')=='A1' and v['dependent']=='y')
        with self.assertRaisesRegex(RuntimeError,'Ambiguous'):fix.archive_rows(r+[one],'S0','y',len(d['row_id']),one['row_set_sha256'])
        with self.assertRaisesRegex(RuntimeError,'digest differs'):fix.archive_rows(r,'S0','y',len(d['row_id']),'changed')

    def test_completed_model_input_bytes_are_bound(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);r7=root/'r7';report=root/'report';paths={}
            for sample in ('S0','F50'):
                src=root/(sample+'.parquet');src.write_bytes(b'unchanged input bytes');paths[sample]=src
                folder=r7/'models'/(sample+'_X0_pooled_pooled');folder.mkdir(parents=True)
                u.save(folder/'result.json',{'aggregate':True})
                u.save(folder/'dependencies_PRIVATE.json',[dict(path=str(src),sha256=u.sha(src))])
                records=[dict(path=p.name,sha256=u.sha(p),bytes=p.stat().st_size) for p in folder.iterdir()]
                u.save(folder/'_DONE.json',dict(config_sha256=u.R7_CONF,files=records))
            fix.prove_model_inputs(r7,paths,report);paths['S0'].write_bytes(b'different input bytes')
            with self.assertRaisesRegex(RuntimeError,'input bytes differ'):fix.prove_model_inputs(r7,paths,report)

    def test_original_run_lock_guard(self):
        from unittest.mock import patch
        import fcntl
        with tempfile.TemporaryDirectory() as td:
            project=Path(td);config={'fixture':'base'};key=u.digest(config)
            old=project/'derived/replication/r8_current_data_v100_PRIVATE'/key[:12];old.mkdir(parents=True)
            lock=(old/'RUN.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with patch.object(fix,'runtime_config',return_value=config):
                with self.assertRaisesRegex(RuntimeError,'still active'):fix.guard_original_run(project)
            lock.close()
            with patch.object(fix,'runtime_config',return_value=config):
                root,actual,acquired=fix.guard_original_run(project);self.assertEqual(root,old);self.assertEqual(actual,key);acquired.close()

    def test_completed_reports_reused_without_refitting_and_failed_receipt_is_diagnostic_only(self):
        import zipfile
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);old=root/'old';run=root/'resume';desktop=root/'desktop';desktop.mkdir();old.mkdir();run.mkdir()
            basekey='fixture_original';states={}
            source=root/'input';source.write_text('source')
            for name in ('patron','clocks'):
                report=old/name/'report';report.mkdir(parents=True);u.save(report/'aggregate.json',{'coefficient_pp':.4})
                u.certify(old/name,u.digest([basekey,name]),[source]);states[name]={'state':'COMPLETE'}
            u.save(old/'STATE.json',{'modules':states})
            r=run/'receipt/report';r.mkdir(parents=True);u.save(r/'receipt_fit_diagnostics_S0.json',{'passed':False})
            u.save(r/'experience_IV.json',[{'stale':True}]);(run/'receipt/raw_accounts.parquet').write_text('do not export')
            before={str(p):u.sha(p) for p in old.rglob('*') if p.is_file()}
            fix.export(run,desktop,'c'*64,old,basekey,'BLOCKED','fixture mismatch')
            self.assertEqual(before,{str(p):u.sha(p) for p in old.rglob('*') if p.is_file()})
            with zipfile.ZipFile(next(desktop.glob('*.zip'))) as z:
                self.assertTrue(any(n.endswith('patron/aggregate.json') for n in z.namelist()))
                self.assertTrue(any(n.endswith('clocks/aggregate.json') for n in z.namelist()))
                self.assertTrue(any(n.endswith('receipt_fit_diagnostics_S0.json') for n in z.namelist()))
                self.assertFalse(any('experience_IV' in n or 'raw_accounts' in n for n in z.namelist()))
                summary=json.loads(z.read('R8_RECEIPT_RESUME_REPORT/SUMMARY.json'));self.assertEqual(summary['module_states']['receipt']['state'],'BLOCKED')
            # A failed copy must not leave a partial module in the report archive.
            from unittest.mock import patch
            original_copytree=fix.shutil.copytree
            def interrupted_copytree(src,dst,*args,**kwargs):
                result=original_copytree(src,dst,*args,**kwargs)
                if Path(src)==old/'patron/report':raise OSError('fixture interrupted report copy')
                return result
            with patch.object(fix.shutil,'copytree',side_effect=interrupted_copytree):
                fix.export(run,desktop,'c'*64,old,basekey,'BLOCKED','fixture mismatch')
            with zipfile.ZipFile(next(desktop.glob('*.zip'))) as z:
                self.assertFalse(any('/patron/' in n for n in z.namelist()))
                summary=json.loads(z.read('R8_RECEIPT_RESUME_REPORT/SUMMARY.json'))
                self.assertEqual(summary['module_states']['patron']['state'],'NOT_REUSED')

if __name__=='__main__':unittest.main(argv=[sys.argv[0]]+remaining,verbosity=2)
