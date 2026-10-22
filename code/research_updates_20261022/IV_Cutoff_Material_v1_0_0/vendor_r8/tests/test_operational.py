import sys,unittest,tempfile,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
import run_r8 as m
from r8_util import *

class OperationalTests(unittest.TestCase):
    def test_checkpoint_input_mutation_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src=root/'source';src.write_text('first');folder=root/'fit';folder.mkdir();save(folder/'out.json',{'a':1})
            certify(folder,'fixture',[src]);self.assertTrue(verify_cached(folder,'fixture'))
            src.write_text('second')
            with self.assertRaisesRegex(RuntimeError,'Checkpoint input changed'):verify_cached(folder,'fixture')

    def test_nested_checkpoint_dependency_is_checked_on_parent_resume(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src=root/'source';src.write_text('first');parent=root/'module';child=parent/'stage';child.mkdir(parents=True)
            save(child/'out.json',{'a':1});certify(child,'child',[src]);certify(parent,'parent')
            self.assertTrue(verify_cached(parent,'parent'));src.write_text('second')
            with self.assertRaisesRegex(RuntimeError,'Checkpoint input changed'):verify_cached(parent,'parent')

    def test_result_zip_excludes_private_rows_and_keeps_open_ledger(self):
        import unittest.mock
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);run=root/'run';desktop=root/'desktop';desktop.mkdir();run.mkdir()
            (run/'receipt/report').mkdir(parents=True);save(run/'receipt/report/aggregate.json',{'n':17})
            (run/'receipt/private').mkdir();(run/'receipt/private/identities.parquet').write_text('must not export')
            fake=root/'package';fake.mkdir();(fake/'R8_SPEC.md').write_text('test specification');save(fake/'VALIDATION.json',{'synthetic_tests':True})
            states={'receipt':{'state':'COMPLETE'}}
            with unittest.mock.patch.object(m,'ROOT',fake):ok=m.export(run,desktop,'a'*64,['receipt'],states,time.monotonic())
            self.assertTrue(ok)
            p=next(desktop.glob('*.zip'))
            with zipfile.ZipFile(p) as z:
                self.assertFalse(any('identities' in n or 'private' in n for n in z.namelist()))
                summary=json.loads(z.read('R8_CURRENT_DATA_RESULT/SUMMARY.json'))
                self.assertNotEqual(summary['status'],'R8_COMPLETE');self.assertEqual(len(summary['open_work']),3)
            self.assertEqual((desktop/(p.name+'.sha256')).read_text().split()[0],sha(p))
            # Previously generated estimates must not leak from a newly blocked/tampered module.
            states={'receipt':{'state':'BLOCKED','reason':'input changed'}}
            with unittest.mock.patch.object(m,'ROOT',fake):ok=m.export(run,desktop,'b'*64,['receipt'],states,time.monotonic())
            self.assertFalse(ok)
            with zipfile.ZipFile(next(desktop.glob('*bbbbbbbbbbbb.zip'))) as z:
                self.assertFalse(any(n.endswith('/aggregate.json') for n in z.namelist()))

    def test_socket_requests_blocked(self):
        no_network()
        with self.assertRaisesRegex(RuntimeError,'network disabled'):socket.create_connection(('example.com',443))

if __name__=='__main__':unittest.main(verbosity=2)
