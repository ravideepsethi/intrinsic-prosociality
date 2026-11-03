import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

import read_remaining_counts as c


class CountTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def file(self, name, values):
        p = self.root/name
        p.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.table(values), p, row_group_size=2)
        return p

    def test_sorted_row_hash_and_duplicates(self):
        ids = np.array([1, 2, 4], dtype=np.int64)
        self.assertEqual(c.row_hash(ids), c.hashlib.sha256(ids.astype('<i8').tobytes()).hexdigest())
        for bad in ([1, 1], [2, 1], []):
            with self.assertRaises(RuntimeError):
                c.row_hash(bad)

    def test_missing_null_float_and_rowcount_rejected(self):
        p = self.file('bad.parquet', {'x': [1, None], 'y': [1., 2.]})
        for names, n in [(['missing'], 2), (['x'], 2), (['y'], 2), (['x'], 3)]:
            with self.assertRaises(RuntimeError):
                c.columns(p, names, n)

    def test_after_join_accepts_different_global_order(self):
        p = self.file('s.parquet', {'row_id': [9, 4, 1, 2], 'n_A': [3, 8, 5, 6], 'n_C': [0, 4, 1, 3]})
        result, _ = c.selected_after_counts(p, np.array([1, 2, 4]), np.array([5, 6, 8]))
        np.testing.assert_array_equal(result, [1, 3, 4])

    def test_after_join_duplicate_missing_mismatch_outofrange_rejected(self):
        for k, (ids, a, after) in enumerate([
            ([1, 1, 2], [5, 5, 6], [1, 1, 2]),
            ([1, 3], [5, 6], [1, 2]),
            ([1, 2], [5, 7], [1, 2]),
            ([1, 2], [5, 6], [1, 7]),
            ([1, 2], [5, 6], [1, -1]),
        ]):
            p = self.file(f'bad{k}.parquet', {'row_id': ids, 'n_A': a, 'n_C': after})
            with self.assertRaises(RuntimeError):
                c.selected_after_counts(p, np.array([1, 2]), np.array([5, 6]))

    def test_pair_count_deduplicates_unordered_keys(self):
        p = self.file('pairs.parquet', {'pair_key': np.array([(1 << 32) | 2, (1 << 32) | 2, (2 << 32) | 7], dtype=np.uint64)})
        count, _ = c.pair_count(p, 3)
        self.assertEqual(count, 2)
        p = self.file('badpairs.parquet', {'pair_key': np.array([(2 << 32) | 1], dtype=np.uint64)})
        with self.assertRaises(RuntimeError):
            c.pair_count(p, 1)

    def test_spaced_values_and_hash_gate(self):
        iv = self.root/'iv'
        ids = np.array([1, 2, 3], dtype=np.int64)
        src = 'iv/PRIVATE/model_inputs/legacy_spaced/'
        self.file(src+'source.parquet', {'row_id': ids, 'environment_supported': [True, False, True]})
        self.file(src+'scores.parquet', {'row_id': ids, 'n_A': [5, 6, 9]})
        with patch.object(c, 'SPACED_N', 3), patch.object(c, 'SPACED_SHA', c.row_hash(ids)):
            d, s, _ = c.spaced_inputs(iv)
            self.assertEqual(int((d['environment_supported'] == 0).sum()), 1)
            self.assertEqual(float(np.median(s['n_A'])), 6.)
        with patch.object(c, 'SPACED_N', 3), patch.object(c, 'SPACED_SHA', 'bad'):
            with self.assertRaises(RuntimeError):
                c.spaced_inputs(iv)

    def test_missing_private_files_make_partial_aggregate_report(self):
        project = self.root/'private'; project.mkdir()
        dest = self.root/'reports'
        with patch('sys.argv', ['counts', '--project-root', str(project), '--output-dir', str(dest)]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(c.main(), 2)
        report = json.loads(next(dest.glob('*/COUNT_RESULTS.json')).read_text())
        self.assertEqual(report['status'], 'PARTIAL')
        self.assertEqual(report['results'], [])
        self.assertFalse(list(project.iterdir()))
        self.assertEqual(len(list(dest.glob('*.zip'))), 1)

    def reputation_fixture(self):
        project = self.root/'project'
        old = project/'v100'
        current = project/'v102'
        rel = 'PRIVATE/stages/reputation'
        keys = np.array([(1 << 32) | 2, (1 << 32) | 2, (2 << 32) | 7], dtype=np.uint64)
        path = self.file('project/v100/'+rel+'/PRIVATE/features/analysis.parquet', {'pair_key': keys})
        record = dict(path=str(path), bytes=path.stat().st_size, sha256=c.digest(path))
        for root in (old, current):
            folder = root/rel
            folder.mkdir(parents=True, exist_ok=True)
            (folder/'DONE.json').write_text(json.dumps(dict(status='COMPLETE', input_fingerprint='corrected-frame', files=[record])))
        return project, old, current, path

    def test_adopted_record_resolves_v100_without_v102_parquet(self):
        project, old, current, path = self.reputation_fixture()
        resolved, evidence = c.reputation_source(current, project)
        self.assertEqual(resolved, path.resolve())
        self.assertEqual(evidence['resolved_file']['sha256'], c.digest(path))
        self.assertFalse((current/'PRIVATE/stages/reputation/PRIVATE/features/analysis.parquet').exists())

    def test_adopted_from_link_and_cycle(self):
        project, old, current, path = self.reputation_fixture()
        receipt=current/'PRIVATE/stages/reputation/DONE.json'
        receipt.write_text(json.dumps(dict(status='COMPLETE', input_fingerprint='corrected-frame', files=[], adopted_from=str(old/'PRIVATE/stages/reputation'))))
        resolved, evidence = c.reputation_source(current, project)
        self.assertEqual(resolved, path.resolve())
        self.assertEqual(len(evidence['receipts']), 2)
        receipt.write_text(json.dumps(dict(status='COMPLETE', input_fingerprint='corrected-frame', files=[], adopted_from=str(receipt.parent))))
        with self.assertRaisesRegex(RuntimeError, 'Cycle'):
            c.reputation_source(current, project)

    def test_changed_reputation_cache_is_rejected(self):
        project, old, current, path = self.reputation_fixture()
        raw=bytearray(path.read_bytes());raw[-5] ^= 1;path.write_bytes(raw)
        with self.assertRaisesRegex(RuntimeError, 'checksum differs'):
            c.reputation_source(current, project)

    def test_reputation_only_main_skips_iv_and_tenure(self):
        project, old, current, path = self.reputation_fixture()
        dest=self.root/'outputs'
        argv=['counts','--project-root',str(project),'--noniv-root',str(current),'--output-dir',str(dest),'--only-reputation']
        with patch('sys.argv',argv),patch.object(c,'PAIR_ROWS',3),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(c.main(),0)
        report=json.loads(next(dest.glob('*/COUNT_RESULTS.json')).read_text())
        self.assertEqual(report['status'],'COMPLETE')
        self.assertEqual(report['requested_scope'],'reputation_pairs_only')
        self.assertEqual(len(report['results']),1)
        self.assertEqual(report['results'][0]['value'],2)
        self.assertEqual(report['results'][0]['source_file'],str(path.resolve()))

    def test_symlinked_project_root_resolves_the_same_authenticated_file(self):
        project, old, current, path = self.reputation_fixture()
        alias = self.root/'project_alias'
        alias.symlink_to(project.resolve(), target_is_directory=True)
        resolved, evidence = c.reputation_source(alias/'v102', alias)
        self.assertTrue(resolved.samefile(path))
        self.assertEqual(resolved, path.resolve())
        self.assertEqual(evidence['resolved_file']['sha256'], c.digest(path))


if __name__ == '__main__':
    unittest.main()
