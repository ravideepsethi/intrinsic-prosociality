"""The production 15-game cache gap, using synthetic API responses only."""
import sys, tempfile, unittest, contextlib, json, sqlite3, gzip, hashlib
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'code'))
from bootstrap import *
import metadata_cache as cache
import metadata_batches as mb
import comparisons

sys.path.insert(0, str(ROOT/'vendor/uniform/original/vendor/tests'))
from test_metadata_batches import fixture, rows as sorted_rows


def api_object(row):
    return dict(id=row['game_id'], source=row['source'], status=row['status'],
                winner=row['winner'], createdAt=row['api_start_ms'], lastMoveAt=row['anchor_ms'],
                rated=row['rated'], variant=row['variant'], speed=row['speed'],
                clock=dict(initial=row['tc_base_s'], increment=row['tc_inc_s']),
                players={color:dict(user=dict(id=row[color+'_username']), rating=row[color+'_rating'])
                         for color in ('white', 'black')})


class Transport:
    def __init__(self, objects):
        self.objects = objects
        self.requests = []
        self.handler = lambda ids: [self.objects[g] for g in ids]

    def __call__(self, request, timeout, context):
        ids = request.data.decode('ascii').split(',')
        self.requests.append(ids)
        if request.get_method() != 'POST' or request.full_url != cache.ENDPOINT:
            raise AssertionError('Unexpected network destination or method')
        result = self.handler(ids)
        raw = b'\n'.join(json.dumps(obj).encode() for obj in result)
        class Response:
            status = 200
            headers = {'Content-Type': 'application/x-ndjson'}
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, limit): return raw
        return Response()


class MetadataCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.run = self.base/'run'
        self.b, fresh = fixture(self.run, 34)  # 15 missing/incomplete records; 3 inherited quarantines.
        self.a = SimpleNamespace(workers=1, memory_gb=6., project=self.base)
        with patch.object(mb, 'BUCKETS', 4), patch.object(mb, 'MAX_ROWS', 8):
            self.plan = cache.md.plan(self.a, self.run, 'unit', self.b)
        self.authority = self.base/'authority.json'
        save(self.authority, read(self.plan/'summary.json'))
        save(self.run/'report/OFFLINE_HOLD.json', dict(status='BLOCKED_MISSING_CACHED_METADATA', games=15))
        self.audit_before = {p: (sha(p), p.stat().st_mtime_ns)
                             for folder in (self.plan, self.run/'PRIVATE/metadata_work')
                             for p in folder.rglob('*') if p.is_file()}
        self.public_before = {p: p.read_bytes() for p in (self.run/'report').iterdir()}
        self.transport = Transport({r['game_id']: api_object(r) for r in pq.read_table(fresh).to_pylist()})
        self.real_client = cache.resilient_metadata_http.Client
        self.patches = contextlib.ExitStack()
        self.patches.enter_context(patch.object(mb, 'BUCKETS', 4))
        self.patches.enter_context(patch.object(mb, 'MAX_ROWS', 8))
        self.patches.enter_context(patch.object(cache, 'AUTHORITY', self.authority))
        self.patches.enter_context(patch.object(Path, 'home', return_value=self.base/'home'))
        self.patches.enter_context(patch.object(cache.md.download, 'check_other_api_jobs'))
        self.client_mock = self.patches.enter_context(patch.object(cache.resilient_metadata_http, 'Client',
            side_effect=lambda path: self.real_client(path, opener=self.transport)))

    def tearDown(self):
        self.patches.close()
        self.tmp.cleanup()

    def assert_audit_unchanged(self):
        for p, value in self.audit_before.items():
            self.assertEqual((sha(p), p.stat().st_mtime_ns), value, p)
        for p, value in self.public_before.items():
            self.assertEqual(p.read_bytes(), value, p)

    def prepare(self):
        with patch.object(mb, 'audit_parts', side_effect=AssertionError('Repeated full audit')):
            return cache.prepare(self.a, self.run, 'unit', self.b)

    def test_single_request_then_offline_reconciliation_matches_full_reference(self):
        report = self.prepare()
        self.assertEqual(report['status'], 'CACHE_READY')
        self.assertEqual(report['attempts'][0]['http_attempts'], 1)
        self.assertEqual(len(self.transport.requests), 1)
        self.assertEqual(len(self.transport.requests[0]), 15)
        with patch.object(mb, 'audit_parts', side_effect=AssertionError('Repeated full audit')), \
             patch.object(cache.resilient_metadata_http, 'Client', side_effect=AssertionError('Offline HTTP client')), \
             patch.object(mb.cached_inputs, 'identity_check') as identity:
            actual = comparisons.metadata(self.a, self.run, 'unit', self.b)
            identity.assert_called_once()
            stamp = (actual/'queries.parquet').stat().st_mtime_ns
            comparisons.metadata(self.a, self.run, 'unit', self.b)
            self.assertEqual(stamp, (actual/'queries.parquet').stat().st_mtime_ns)
        # Independent original SQL reconciliation with the same full metadata.
        import metadata_reference_v102 as reference
        other = self.base/'reference'
        b, fresh = fixture(other, 34)
        def exported(sql, target, folder, conf):
            import shutil
            folder.mkdir(parents=True)
            shutil.copyfile(fresh, folder/'downloaded_metadata.parquet')
            save(folder/'SUMMARY.json', dict(requested=15))
        with patch.object(reference.download, 'exclusive', return_value=contextlib.nullcontext()), \
             patch.object(reference.download, 'check_other_api_jobs'), \
             patch.object(reference.metadata_http, 'Client'), \
             patch.object(reference.download, 'process_batch', return_value=([], [], 0, False)), \
             patch.object(reference.download, 'export_saved', side_effect=exported), \
             patch.object(reference.cached_inputs, 'identity_check'):
            reference.retrieve(self.a, other, 'unit', b)
        for name in ('metadata', 'queries', 'dispositions'):
            self.assertEqual(sorted_rows(actual/(name+'.parquet')),
                             sorted_rows(other/'PRIVATE/metadata_complete'/(name+'.parquet')))
        self.assertEqual(read(self.run/'report/METADATA_HOLD_RESOLUTION.json')['status'], 'RESOLVED')
        self.assert_audit_unchanged()

    def test_interrupt_after_partial_response_resumes_only_missing_ids(self):
        def interrupted(ids):
            if len(self.transport.requests) == 1:
                return [self.transport.objects[g] for g in ids[:-1]]
            raise KeyboardInterrupt()
        self.transport.handler = interrupted
        with self.assertRaises(KeyboardInterrupt): self.prepare()
        self.assertEqual(list(map(len, self.transport.requests)), [15, 1])
        self.transport.handler = lambda ids: [self.transport.objects[g] for g in ids]
        self.prepare()
        self.assertEqual(list(map(len, self.transport.requests)), [15, 1, 1])
        self.assertEqual(self.transport.requests[1], self.transport.requests[2])
        self.client_mock.reset_mock()
        final = self.prepare()
        self.client_mock.assert_not_called()
        self.assertEqual(final['attempts'][-1]['http_attempts'], 0)
        self.assertEqual(len(self.transport.requests), 3)
        self.assert_audit_unchanged()

    def test_unreturned_records_block_without_dropping_rows(self):
        self.transport.handler = lambda ids: []
        with self.assertRaisesRegex(RuntimeError, 'not returned'): self.prepare()
        self.assertEqual(len(self.transport.requests), 3)
        self.assertFalse((self.run/'PRIVATE/metadata_complete/_DONE.json').exists())
        self.assertEqual(read(self.run/'report/METADATA_CACHE_COMPLETION.json')['status'], 'BLOCKED_CACHE_COMPLETION')
        self.assert_audit_unchanged()

    def test_invalid_metadata_blocks_before_frames(self):
        first = next(iter(self.transport.objects))
        self.transport.objects[first]['createdAt'] += DAY
        with self.assertRaisesRegex(RuntimeError, 'validation flags'): self.prepare()
        self.assertFalse((self.run/'PRIVATE/download/finished/_DONE.json').exists())
        self.assertFalse((self.run/'PRIVATE/metadata_complete/_DONE.json').exists())
        self.assert_audit_unchanged()

    def test_unrequested_response_id_is_not_committed(self):
        wrong = dict(next(iter(self.transport.objects.values())), id='BAD00000')
        self.transport.handler = lambda ids: [wrong]
        with self.assertRaisesRegex(RuntimeError, 'unrequested'): self.prepare()
        with sqlite3.connect(self.run/'PRIVATE/download/checkpoint.sqlite3') as sql:
            self.assertEqual(sql.execute('SELECT count(*) FROM responses').fetchone()[0], 0)

    def test_changed_target_and_missing_audit_stop_before_any_request(self):
        target = self.plan/'targets.parquet'
        target.write_bytes(b'changed')
        with self.assertRaises(RuntimeError): self.prepare()
        self.client_mock.assert_not_called()
        (self.plan/'_DONE.json').rename(self.plan/'saved_receipt.json')
        with self.assertRaisesRegex(RuntimeError, 'completed metadata audit is missing'): self.prepare()
        self.client_mock.assert_not_called()

    def test_changed_input_and_wrong_review_are_not_rebuilt(self):
        review = read(self.authority)
        review['locally_eligible'] += 1
        save(self.authority, review)
        with self.assertRaisesRegex(RuntimeError, 'reviewed metadata plan'): self.prepare()
        save(self.authority, read(self.plan/'summary.json'))
        Path(self.b['metadata'][0]).touch()
        with self.assertRaisesRegex(RuntimeError, 'input changed'): self.prepare()
        self.client_mock.assert_not_called()

    def test_scope_rejects_extra_duplicate_and_excess_requests(self):
        _, records = cache.cached_plan(self.a, self.run, 'unit', self.b)
        ids = [r['game_id'] for r in records]
        client = cache.ScopedClient(ids, self.base/'cooldown.json')
        for bad in ([], [ids[0], ids[0]], ['BAD00000'], ids+['BAD00000']):
            with self.assertRaisesRegex(RuntimeError, 'scope'): client.get(bad)
        self.client_mock.assert_not_called()
        for _ in range(3): client.get([ids[0]])
        with self.assertRaisesRegex(RuntimeError, 'pass limit'): client.get([ids[0]])
        self.assertEqual(len(self.transport.requests), 3)

    def test_corrupt_saved_raw_response_is_rejected_without_download(self):
        self.prepare()
        with sqlite3.connect(self.run/'PRIVATE/download/checkpoint.sqlite3') as sql:
            sql.execute('UPDATE responses SET raw_gzip=?', (gzip.compress(b'wrong'),))
        self.client_mock.reset_mock()
        with self.assertRaisesRegex(RuntimeError, 'response checksum'): self.prepare()
        self.client_mock.assert_not_called()
        self.assertEqual(len(self.transport.requests), 1)

    def test_offline_path_cannot_fetch_a_missing_response(self):
        self.prepare()
        with sqlite3.connect(self.run/'PRIVATE/download/checkpoint.sqlite3') as sql:
            sql.execute('DELETE FROM responses')
        self.client_mock.reset_mock()
        with self.assertRaisesRegex(RuntimeError, 'Missing saved response'):
            comparisons.metadata(self.a, self.run, 'unit', self.b)
        self.client_mock.assert_not_called()

    def test_reconciliation_interrupt_preserves_audit_and_cached_download(self):
        self.prepare()
        with patch.object(mb, 'complete', side_effect=RuntimeError('injected interruption')):
            with self.assertRaisesRegex(RuntimeError, 'injected interruption'):
                comparisons.metadata(self.a, self.run, 'unit', self.b)
        self.assert_audit_unchanged()
        self.client_mock.reset_mock()
        self.prepare()
        self.client_mock.assert_not_called()
        with patch.object(mb.cached_inputs, 'identity_check'):
            comparisons.metadata(self.a, self.run, 'unit', self.b)
        self.assert_audit_unchanged()

    def test_pipeline_blocks_network_and_only_runs_unfinished_stages(self):
        import pipeline
        run = self.base/'parent'
        save(run/'comparisons/PRIVATE/BINDING90.json', self.b)
        a = SimpleNamespace(_stage='comparison_metadata')
        events = []
        with patch.object(pipeline, 'arguments', return_value=a), patch.object(pipeline, 'verify_package'), \
             patch.object(pipeline, 'setup', return_value=(run, 'unit')), \
             patch.object(cache, 'prepare', side_effect=lambda *args: events.append('cache')), \
             patch.object(pipeline, 'no_network', side_effect=lambda: events.append('block')), \
             patch.object(pipeline, 'execute', side_effect=lambda *args: events.append('analysis')):
            with self.assertRaisesRegex(RuntimeError,'two unfinished'):pipeline.main()
            self.assertEqual(events, ['block'])
            for name in ('comparison_frames','comparison_models'):
                a._stage = name
                events.clear()
                self.assertEqual(pipeline.main(), 0)
                self.assertEqual(events, ['block', 'analysis'])

    def test_524_recovery_is_cached_and_offline_resume_does_not_fetch_again(self):
        import urllib.error
        from test_http_recovery import Clock
        clock = Clock()
        self.client_mock.side_effect = lambda path: self.real_client(
            path, opener=self.transport, sleeper=clock.sleep, clock=clock)
        def first_timeout(ids):
            if len(self.transport.requests) == 1:
                raise urllib.error.HTTPError(cache.ENDPOINT, 524, 'synthetic', {}, None)
            return [self.transport.objects[g] for g in ids]
        self.transport.handler = first_timeout
        result = self.prepare()
        self.assertEqual(result['status'], 'CACHE_READY')
        self.assertEqual(result['attempts'][-1]['http_attempts'], 2)
        self.assertEqual(result['attempts'][-1]['server_wait_seconds'], 120.)
        self.assertEqual(result['attempts'][-1]['transient_errors'][0]['http_status'], 524)
        with patch.object(mb.cached_inputs, 'identity_check'):
            comparisons.metadata(self.a, self.run, 'unit', self.b)
        self.prepare()
        self.assertEqual(len(self.transport.requests), 2)
        self.assert_audit_unchanged()


if __name__ == '__main__': unittest.main()
