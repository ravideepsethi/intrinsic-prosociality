import contextlib,hashlib,io,json,subprocess,sys,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'code'))
import engine,batch,resume_previous
import numpy as np


class Recovery(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()

    def diagnostic(self,*,parent='p',corrupt=False,private=False):
        expected=self.root/'package.txt';expected.write_text('original responsibility package\n')
        buf=io.BytesIO();np.savez(buf,model=np.eye(2))
        payload={
            'report/INPUT_LINEAGE.json':json.dumps(dict(parent_run_id=parent,parent_manifest_sha256='m')).encode(),
            'report/REFERENCE_REPRODUCTION.csv':b'table,metric,passed\ncovariance,model,False\n',
            'report/reference_reproduction/model_covariances.npz':buf.getvalue(),
            'report/reference_reproduction/coefficient_order.json':b'{"model":["a","b"]}',
        }
        if private:payload['report/bad.csv']=b'game_id,value\nsecret,1\n'
        records=[dict(path=n,bytes=len(b),sha256=hashlib.sha256(b).hexdigest()) for n,b in payload.items()]
        if corrupt:payload['report/REFERENCE_REPRODUCTION.csv']+=b'changed'
        z=self.root/'failed.zip'
        with zipfile.ZipFile(z,'w') as a:
            for n,b in payload.items():a.writestr(n,b)
            a.writestr('REPORT_MANIFEST.json',json.dumps(records));a.writestr('SHA256SUMS.txt',expected.read_bytes())
        return z,expected

    def test_reference_diagnostics_include_covariance_and_remain_unresolved(self):
        z,p=self.diagnostic();out=self.root/'stage'
        result=resume_previous.collect_responsibility_zip(z,out,dict(parent_run_id='p',manifest_sha256='m'),p)
        self.assertEqual(result['status'],'REFERENCE_REVIEW_REQUIRED');self.assertEqual(result['failed_comparisons'],1)
        self.assertFalse(result['tolerances_changed'])
        self.assertTrue((out/'report/reference_diagnostics/reference_reproduction/model_covariances.npz').is_file())

    def test_wrong_diagnostic_parent_rejected(self):
        z,p=self.diagnostic(parent='wrong')
        with self.assertRaisesRegex(RuntimeError,'parent'):
            resume_previous.collect_responsibility_zip(z,self.root/'stage',dict(parent_run_id='p',manifest_sha256='m'),p)

    def test_changed_diagnostic_bytes_rejected(self):
        z,p=self.diagnostic(corrupt=True)
        with self.assertRaisesRegex(RuntimeError,'checksum'):
            resume_previous.collect_responsibility_zip(z,self.root/'stage',dict(parent_run_id='p',manifest_sha256='m'),p)

    def test_private_diagnostic_rows_rejected(self):
        z,p=self.diagnostic(private=True)
        with self.assertRaisesRegex(RuntimeError,'Private identifier'):
            resume_previous.collect_responsibility_zip(z,self.root/'stage',dict(parent_run_id='p',manifest_sha256='m'),p)

    def test_review_state_is_never_counted_as_complete_or_rerun(self):
        run=self.root/'run';stage=run/'PRIVATE/stages/responsibility';stage.mkdir(parents=True)
        data=stage/'result.json';engine.write(data,dict(passed=False))
        engine.write(stage/'DONE.json',dict(status='COMPLETE',input_fingerprint='f',
            result=dict(status='REFERENCE_REVIEW_REQUIRED'),files=[engine.record(data)]))
        with patch.object(batch,'STAGES',[('responsibility','diagnostics',[],0,1)]):
            states=batch.orchestrate(run,{},dict(fingerprint='f'),lambda n:self.fail('Must not rerun'))
        self.assertEqual(states['responsibility']['status'],'REVIEW_REQUIRED')

    def test_diagnostic_covariance_survives_final_export(self):
        run=self.root/'run';stage=run/'PRIVATE/stages/responsibility'
        z,p=self.diagnostic();resume_previous.collect_responsibility_zip(z,stage,dict(parent_run_id='p',manifest_sha256='m'),p)
        with patch.object(batch,'STAGES',[('responsibility','diagnostics',[],0,1)]):
            artifact=batch.export(run,self.root/'returns','b'*64)
        with zipfile.ZipFile(artifact) as a:
            self.assertIn('report/families/responsibility/reference_diagnostics/reference_reproduction/model_covariances.npz',a.namelist())

    def prior_fixture(self):
        authority=self.root/'authority';authority.mkdir();old=self.root/'old';old.mkdir();run=self.root/'new'
        engine.write(authority/'STATUS.json',dict(states={'one':{'status':'COMPLETE'},'bad':{'status':'FAILED'}},seconds_this_launch=9))
        engine.write(authority/'LOCATION.json',dict(run_id='oldrun'))
        source=old/'PRIVATE/stages/one';(source/'report').mkdir(parents=True)
        p=source/'report/fit.csv';p.write_text('estimate\n1.2\n')
        cache=source/'PRIVATE/cache.parquet';cache.parent.mkdir();cache.write_bytes(b'private cache')
        engine.write(source/'DONE.json',dict(status='COMPLETE',input_fingerprint='f',
            result=dict(status='COMPLETE',elapsed_seconds=9),files=[engine.record(p),engine.record(cache)]))
        r=engine.record(p);r['path']='families/one/fit.csv'
        engine.write(authority/'REPORT_MANIFEST.json',[r])
        return authority,old,run,source

    def test_completed_stage_adoption_does_not_copy_private_cache_or_refit(self):
        a,old,run,source=self.prior_fixture();stamp=(source/'PRIVATE/cache.parquet').stat().st_mtime_ns
        with patch.object(resume_previous,'AUTHORITY',a):
            self.assertEqual(resume_previous.adopt_complete(old,run,dict(fingerprint='f',parent_run_id='p')),['one'])
            self.assertEqual(resume_previous.adopt_complete(old,run,dict(fingerprint='f',parent_run_id='p')),[])
        self.assertFalse((run/'PRIVATE/stages/one/PRIVATE/cache.parquet').exists())
        batch.verified_done(run/'PRIVATE/stages/one/DONE.json','f')
        self.assertEqual(stamp,(source/'PRIVATE/cache.parquet').stat().st_mtime_ns)

    def test_changed_private_cache_blocks_adoption(self):
        a,old,run,source=self.prior_fixture();(source/'PRIVATE/cache.parquet').write_bytes(b'changed')
        with patch.object(resume_previous,'AUTHORITY',a),self.assertRaisesRegex(RuntimeError,'Changed'):
            resume_previous.adopt_complete(old,run,dict(fingerprint='f',parent_run_id='p'))

    def test_original_countdown_projector_bytes_preserved(self):
        self.assertEqual(engine.sha(ROOT/'vendor/countdown/code/feature_projection.py'),
                         '46e1908d6504ecdb571da258c3c7d91c3df91e80146521d993df5a7b93b1f160')


class ScientificRecovery(unittest.TestCase):
    def execute(self,script):
        cp=subprocess.run([sys.executable,str(ROOT/'tests'/script)],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(cp.returncode,0,cp.stdout+'\n'+cp.stderr)
    def test_patron_streaming_algebra_and_all_fifteen_models(self):self.execute('patron_recovery_fixture.py')
    def test_countdown_full_adapter_and_material_projection_resume(self):self.execute('countdown_recovery_fixture.py')

if __name__=='__main__':unittest.main()
