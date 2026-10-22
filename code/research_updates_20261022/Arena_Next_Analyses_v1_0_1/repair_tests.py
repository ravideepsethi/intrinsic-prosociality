"""Regression checks for legacy hash formats and preservation of completed work."""
import ast
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from next_common import ROOT, read, js, stage_complete
from history_auth import config_hash_audit, require_config_hash


class RepairTests(unittest.TestCase):
    def test_hash_matches_original_producer_and_compact_variant(self):
        # Execute the cfgsha definition extracted from the unchanged repository
        # producer, rather than testing against another copy of our adapter.
        source=ROOT/'authority/hash_format_sources/run_preliminary.py'
        tree=ast.parse(source.read_text())
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='cfgsha')
        scope={'hashlib':hashlib,'json':json,'clean':lambda x:x}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),str(source),'exec'),scope)
        config={'months':['2023-11','2025-10'],'lag':7,'unicode':'caf\u00e9','enabled':True,'none':None}
        legacy=scope['cfgsha'](config)
        compact=hashlib.sha256(json.dumps(config,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        self.assertNotEqual(legacy,compact)  # Reproduces the incompatible v100 check.
        self.assertEqual(require_config_hash(config,legacy,'test')['matched_serializations'],
                         ['legacy_sorted_json_default_spaces'])
        self.assertEqual(require_config_hash(config,compact,'test')['matched_serializations'],
                         ['compact_sorted_json'])
        config['lag']=30
        self.assertFalse(config_hash_audit(config,legacy)['matched'])
        with self.assertRaisesRegex(RuntimeError,'neither upstream'):
            require_config_hash(config,legacy,'test')
        with self.assertRaises(ValueError):config_hash_audit({'x':float('nan')},legacy)

    def test_authentication_advances_legacy_config_and_records_real_mismatch(self):
        import iv_stage as iv
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);project=root/'project';config={'fixture_only':True,'lag':7}
            expected=hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()
            authority={'comparison_run':'fixture','comparison_config_sha256':expected,
              'comparison_report_sha256':'1'*64,'comparison_lineage_sha256':'0'*64}
            js(root/'source/iv/evidence/prior_authority.json',authority)
            old=project/'derived/replication/comparison_tests_v110_PRIVATE/fixture'
            js(old/'config.json',config)
            js(old/'_SUCCESS.json',{'status':'CHOOSER_COMPARISON_TESTS_COMPLETE',
                'config_sha256':expected,'report_sha256':'1'*64})
            js(old/'lineage_PRIVATE.json',{'fixture_only':True})
            audit=root/'audit.json'
            with patch.object(iv,'ROOT',root):
                with self.assertRaisesRegex(RuntimeError,'Input checksum changed'):
                    iv.authenticate_history(project,audit)
                result=read(audit)
                self.assertTrue(result['config_checks']['comparison']['matched'])
                self.assertEqual(result['phase'],'comparison_projection_lineage')
                self.assertEqual(result['status'],'FAILED')  # Lineage check still enforced.
                config['lag']=30;js(old/'config.json',config)
                with self.assertRaisesRegex(RuntimeError,'neither upstream'):
                    iv.authenticate_history(project,audit)
                result=read(audit)
                self.assertFalse(result['config_checks']['comparison']['matched'])
                self.assertEqual(result['phase'],'comparison_completion_and_configuration')
                self.assertNotIn('fixture_only',audit.read_text())

    def test_import_preserves_actual_completed_results_and_rejects_tampering(self):
        import reuse_completed as reuse
        authority=read(ROOT/'authority/V100_REUSE_AUTHORITY.json')
        blobs=reuse.checked_report(ROOT/'authority/V100_COMPLETED_RESULTS.zip',authority)
        sample={'authority':json.loads(blobs['INPUT_QA.json'])}
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'private').mkdir();(root/'public').mkdir()
            records=reuse.import_completed(root,'new_fixture_contract',sample)
            self.assertEqual(len(records),5)
            self.assertEqual(reuse.import_completed(root,'new_fixture_contract',sample),records)
            for stage in authority['stages']:
                dest=root/'public'/stage
                receipt=stage_complete(dest,'new_fixture_contract')
                self.assertFalse(receipt['summary']['analysis_rerun'])
                self.assertEqual((dest/'_V100_DONE.json').read_bytes(),blobs[stage+'/_DONE.json'])
                original=json.loads(blobs[stage+'/_DONE.json'])
                for r in original['files']:
                    self.assertEqual((dest/r['path']).read_bytes(),blobs[stage+'/'+r['path']])
            self.assertFalse((root/'public/receipt_iv').exists())
            with self.assertRaisesRegex(RuntimeError,'Stage configuration changed'):
                stage_complete(root/'public/core',authority['parent_contract'])
            (root/'public/core/tables/table01_fairness_bins.csv').write_text('changed')
            with self.assertRaisesRegex(RuntimeError,'checksum'):
                reuse.import_completed(root,'new_fixture_contract',sample)

    def test_report_authority_and_input_population_are_enforced(self):
        import reuse_completed as reuse
        authority=read(ROOT/'authority/V100_REUSE_AUTHORITY.json')
        wrong=dict(authority,parent_report_sha256='0'*64)
        with self.assertRaisesRegex(RuntimeError,'report checksum'):
            reuse.checked_report(ROOT/'authority/V100_COMPLETED_RESULTS.zip',wrong)
        blobs=reuse.checked_report(ROOT/'authority/V100_COMPLETED_RESULTS.zip',authority)
        sample={'authority':json.loads(blobs['INPUT_QA.json'])};sample['authority']['rows']+=1
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'private').mkdir();(root/'public').mkdir()
            with self.assertRaisesRegex(RuntimeError,'different arena inputs'):
                reuse.import_completed(root,'new_fixture_contract',sample)
            self.assertEqual(list((root/'public').iterdir()),[])
