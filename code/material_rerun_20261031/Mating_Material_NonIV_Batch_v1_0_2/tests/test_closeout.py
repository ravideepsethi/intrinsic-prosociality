import sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'code'))
import engine,families,worker,batch


class NativeResponsibility(unittest.TestCase):
    def test_native_private_outputs_are_bound_to_outer_receipt(self):
        with tempfile.TemporaryDirectory() as t:
            base=Path(t);run=base/'native';out=base/'stage'
            report=run/'report/fit.csv';report.parent.mkdir(parents=True);report.write_text('estimate\n1\n')
            private=run/'PRIVATE/fit.npz';private.parent.mkdir();private.write_bytes(b'cached moments')
            records=[]
            for p in [report,private]:
                r=engine.record(p);r['path']=str(p.relative_to(run));records.append(r)
            engine.write(run/'_SUCCESS.json',dict(parent_run_id='p',run_id='key',files=records))
            engine.write(out/'PRIVATE/native_return/MATERIAL_RESPONSIBILITY_LATEST_PRIVATE.json',dict(root=str(run)))
            args=SimpleNamespace(project=base,workers=1,memory_gb=5)
            with patch.object(families.subprocess,'run'):
                r=families.responsibility(args,dict(parent_run_id='p'),out)
            self.assertEqual(r['models'],53);self.assertEqual(len(r['_external_file_records']),3)
            self.assertIn(str(private),[f['path'] for f in r['_external_file_records']])

    def test_worker_keeps_external_paths_private_and_verifies_on_resume(self):
        with tempfile.TemporaryDirectory() as t:
            run=Path(t);native=run/'native.npz';native.write_bytes(b'authenticated state')
            engine.write(run/'PRIVATE/AUTH.json',dict(fingerprint='f'))
            def execute(args,auth,out):
                (out/'report/table.csv').write_text('estimate\n2\n')
                return dict(status='COMPLETE',_external_file_records=[engine.record(native)])
            args=['--stage','responsibility','--batch-root',str(run),'--project',str(run),
                  '--workers','1','--memory-gb','5']
            with patch.object(worker.sources,'guard'),patch.object(families,'responsibility',execute):
                self.assertEqual(worker.main(args),0)
            stage=run/'PRIVATE/stages/responsibility'
            self.assertNotIn('_external_file_records',engine.read(stage/'report/STAGE_RESULT.json'))
            self.assertIsNotNone(batch.verified_done(stage/'DONE.json','f'))
            native.write_bytes(b'corrupt')
            with self.assertRaisesRegex(RuntimeError,'Changed'):
                batch.verified_done(stage/'DONE.json','f')


if __name__=='__main__':unittest.main()
