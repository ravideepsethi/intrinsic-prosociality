"""Replay the actual HTTP 524 failure without network calls or real sleeping."""
import sys, tempfile, unittest, json, urllib.error, ssl, email.utils, datetime
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'code'))
from bootstrap import *
import fast_comparisons
import resilient_metadata_http as fixed
import metadata_http as original
import resume_guard

IDS = [f'g{k:07}' for k in range(15)]
RAW = b'\n'.join(json.dumps({'id': g}).encode() for g in IDS)


class Clock:
    def __init__(self): self.now = 1800000000.; self.sleeps = []
    def __call__(self): return self.now
    def sleep(self, seconds): self.sleeps.append(seconds); self.now += seconds


class Response:
    status = 200
    headers = {'Content-Type': 'application/x-ndjson'}
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, limit): return RAW


class Opener:
    def __init__(self, events, clock): self.events = list(events); self.calls = []; self.clock = clock
    def __call__(self, request, timeout, context):
        assert request.full_url == original.URL
        assert request.data.decode('ascii').split(',') == IDS
        assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
        self.calls.append(self.clock())
        event = self.events.pop(0)
        if isinstance(event, BaseException): raise event
        if event != 200:
            code, headers = event if isinstance(event, tuple) else (event, {})
            raise urllib.error.HTTPError(request.full_url, code, 'synthetic', headers, None)
        return Response()


class HTTPRecoveryTests(unittest.TestCase):
    def setUp(self): self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def client(self, events, name='cooldown.json', clock=None):
        clock = clock or Clock(); opener = Opener(events, clock)
        client = fixed.Client(self.root/name, opener=opener, sleeper=clock.sleep, clock=clock)
        return client, clock, opener

    def test_reproduce_original_524_failure_and_recover_same_request(self):
        clock = Clock(); opener = Opener([524, 200], clock)
        old = original.Client(self.root/'old.json', opener=opener, sleeper=clock.sleep, clock=clock)
        with self.assertRaisesRegex(RuntimeError, 'HTTP 524'): old.get(IDS)
        self.assertEqual(old.requests, 1)
        client, clock, opener = self.client([524, 200])
        self.assertEqual(client.get(IDS), RAW)
        self.assertEqual(client.requests, 2)
        self.assertEqual(opener.calls[1] - opener.calls[0], 120.)
        self.assertEqual(client.failure_history, [dict(http_status=524, attempt=1, wait_seconds=120)])
        self.assertTrue(all(s <= 45 for s in clock.sleeps))

    def test_all_named_transient_errors_recover_with_minimum_waits(self):
        for code in sorted(fixed.RETRYABLE):
            with self.subTest(code=code):
                client, clock, opener = self.client([code, 200], f'{code}.json')
                self.assertEqual(client.get(IDS), RAW)
                self.assertEqual(client.requests, 2)
                self.assertGreaterEqual(opener.calls[1] - opener.calls[0], fixed.MINIMUM_DELAY.get(code, 5))

    def test_longer_numeric_and_date_retry_after_take_precedence(self):
        for code, value in [(524, '420'), (429, '180'), (503, '300')]:
            client, clock, opener = self.client([(code, {'Retry-After': value}), 200], f'{code}.json')
            client.get(IDS)
            self.assertEqual(opener.calls[1] - opener.calls[0], float(value))
        clock = Clock()
        header = email.utils.format_datetime(datetime.datetime.fromtimestamp(clock()+600, datetime.timezone.utc), usegmt=True)
        client, _, opener = self.client([(524, {'Retry-After': header}), 200], 'date.json', clock)
        client.get(IDS)
        self.assertEqual(opener.calls[1]-opener.calls[0], 600.)

    def test_malformed_retry_after_does_not_remove_safe_floor(self):
        for value in ['nonsense', 'NaN', '-1', '0']:
            self.assertEqual(fixed.retry_delay(524, {'Retry-After': value}, 0, 1000.), 120.)

    def test_authentication_and_tls_statuses_stop_without_retry(self):
        for code in (400, 401, 403, 404, 501, 525, 526):
            with self.subTest(code=code):
                client, clock, opener = self.client([code, 200], f'fatal{code}.json')
                with self.assertRaisesRegex(RuntimeError, 'HTTP '+str(code)): client.get(IDS)
                self.assertEqual(len(opener.calls), 1)
                self.assertEqual(clock.sleeps, [])

    def test_certificate_errors_never_disable_verification_or_retry(self):
        for i, error in enumerate([ssl.SSLCertVerificationError('synthetic'),
                urllib.error.URLError(ssl.SSLCertVerificationError('synthetic'))]):
            client, clock, opener = self.client([error, 200], f'cert{i}.json')
            with self.assertRaisesRegex(RuntimeError, 'TLS verification failed'): client.get(IDS)
            self.assertEqual(len(opener.calls), 1)
            self.assertTrue(client.context.check_hostname)

    def test_connection_timeout_recovers_and_retains_exact_id_request(self):
        client, clock, opener = self.client([TimeoutError('synthetic'), 200])
        self.assertEqual(client.get(IDS), RAW)
        self.assertEqual(client.requests, 2)
        self.assertEqual(client.failure_history[0]['http_status'], None)

    def test_finite_retry_budget_and_persisted_cooldown_on_next_launch(self):
        client, clock, opener = self.client([524]*12)
        with self.assertRaisesRegex(RuntimeError, '12 attempts'): client.get(IDS)
        self.assertEqual(client.requests, 12)
        self.assertEqual(len(client.failure_history), 12)
        until = read(self.root/'cooldown.json')['until']
        self.assertGreater(until, clock())
        following, _, next_opener = self.client([200], clock=clock)
        following.get(IDS)
        self.assertGreaterEqual(next_opener.calls[0], until)

    def test_interrupted_wait_keeps_server_deadline_for_resume(self):
        client, clock, opener = self.client([524, 200])
        def stop(_): raise KeyboardInterrupt()
        client.sleeper = stop
        with self.assertRaises(KeyboardInterrupt): client.get(IDS)
        self.assertEqual(client.requests, 1)
        until = read(self.root/'cooldown.json')['until']
        following, _, next_opener = self.client([200], clock=clock)
        following.get(IDS)
        self.assertEqual(next_opener.calls[0], until)

    def test_reviewed_failure_history_is_preserved_but_new_attempts_allowed(self):
        baseline = read(ROOT/'authority/iv_batch_partial/METADATA_CACHE_COMPLETION_V103.json')
        current = json.loads(json.dumps(baseline))
        current['execution_repair'] = '1.0.4'
        current['status'] = 'CACHE_READY'
        current['attempts'].append(dict(status='COMPLETE', http_attempts=2))
        resume_guard.verify_cache_history(current, baseline)
        for mode in ('changed_target', 'changed_old_attempt', 'removed_old_attempt'):
            changed = json.loads(json.dumps(current))
            if mode == 'changed_target': changed['target_sha256'] = 'different'
            elif mode == 'changed_old_attempt': changed['attempts'][0]['http_attempts'] = 0
            else: changed['attempts'].pop(0)
            with self.subTest(mode=mode), self.assertRaises(RuntimeError):
                resume_guard.verify_cache_history(changed, baseline)


if __name__ == '__main__': unittest.main()
