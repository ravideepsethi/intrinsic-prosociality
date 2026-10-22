import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'code'))
import r9_env_resume as repair

r, pa = repair.r, repair.c9.pa


def make_fixture(root, output='part'):
    req = root / 'queries'
    req.mkdir(exist_ok=True)
    games = [
        ('a', 100, 1, 2), ('b', 110, 1, 3), ('c', 120, 4, 2),
        ('d', 130, 2, 1), ('e', 140, 3, 1), ('f', 160, 1, 99),
        ('g', 170, 99, 2), ('h', 190, 2, 2), ('i', 99, 1, 5),
        ('j', 200, 1, 5), ('k', 150, 5, 6), ('l', 180, -1, 1),
        ('m', 150, 2, 4)]
    events = [('a', 100, 115, 2, 1), ('b', 110, 140, 1, 3),
              ('c', 120, 180, 2, 4), ('d', 130, 135, 1, 2),
              ('e', 140, 200, 3, 1)]
    requests = [(1, 2, 7), (1, 3, 7), (2, 1, 7), (2, 4, 7),
                (1, 2, 8), (2, 1, 8)]
    windows = [dict(month_code=7, lo=100, hi=200, complete=True),
               dict(month_code=8, lo=110, hi=140, complete=True)]
    def table(path, names, rows):
        r.io.table(path, pa.table({k: [v[i] for v in rows] for i, k in enumerate(names)}))
    table(root / 'chron.parquet', ['game_id', 'utc_ms', 'white_id', 'black_id'], games)
    table(root / 'events.parquet', ['game_id', 'start_ms', 'end_ms', 'i', 'j'], events)
    table(req / 'requests.parquet', ['person', 'partner', 'month_code'], requests)
    table(req / 'people.parquet', ['person'], [(1,), (2,)])
    table(req / 'pairs.parquet', ['person', 'partner'], [(1, 2), (1, 3), (2, 1), (2, 4)])
    r.io.table(req / 'windows.parquet', pa.Table.from_pylist(windows))
    path = root / 'chron.parquet'
    job = dict(record=dict(path=str(path), signature=r.io.sig(path), rows=len(games)),
               events=[str(root / 'events.parquet')], queries=str(req), lower=100, upper=200,
               memory=1., memory_gb=1.6, conf='test-repair', authors=[99],
               output=str(root / output))
    return job, games, events, requests, windows


def read_counts(root, label):
    values = r.io.read(Path(root) / (label + '.parquet')).to_pylist()
    return sorted(values, key=lambda x: tuple(x[k] for k in sorted(x)))


def expected_counts(games, events, windows, pair):
    ev = {v[0]: v for v in events}
    out = {}
    pairs = {(1, 2), (1, 3), (2, 1), (2, 4)}
    for game, start, white, black in games:
        if min(white, black) < 0 or white == black or 99 in (white, black):
            continue
        for person, partner in [(white, black), (black, white)]:
            if person not in (1, 2) or (pair and (person, partner) not in pairs):
                continue
            for w in windows:
                if not w['lo'] <= start < w['hi']:
                    continue
                keys = dict(person=person, month_code=w['month_code'])
                if pair:
                    keys['partner'] = partner
                key = tuple(sorted(keys.items()))
                v = out.setdefault(key, dict(keys, games=0, own=0, chooser=0))
                v['games'] += 1
                event = ev.get(game)
                if event and event[2] < w['hi']:
                    v['own'] += int(event[3] == person)
                    v['chooser'] += int(event[4] == person)
    return sorted(out.values(), key=lambda x: tuple(x[k] for k in sorted(x)))


class EnvironmentRepairTests(unittest.TestCase):
    def tearDown(self):
        r.io.conn = repair.ORIGINAL_CONN
        repair.inputs.replay_baseline = repair.ORIGINAL_REPLAY
        repair.runtime.mapped = repair.ORIGINAL_MAPPED
        repair.report.export = repair.ORIGINAL_EXPORT
        repair.run_r9.heartbeat = repair.ORIGINAL_HEARTBEAT

    def test_unmodified_producer_matches_independent_counts_at_all_memory_limits(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            job, games, events, _, windows = make_fixture(p)
            for memory in (1., 3., 8.):
                j = dict(job, memory=memory, output=str(p / ('part_' + str(memory))))
                result = repair.environment_attempt(j)
                self.assertTrue(result['ok'])
                for label in ('person', 'pair'):
                    self.assertEqual(read_counts(j['output'], label),
                                     expected_counts(games, events, windows, label == 'pair'))

    def test_completed_ENV_stage_reuses_output_without_reexecuting_SQL(self):
        with tempfile.TemporaryDirectory() as td:
            job, *_ = make_fixture(Path(td))
            repair.ORIGINAL_ENV_JOB(job)
            path = Path(job['output']) / 'person.parquet'
            stamp, digest = path.stat().st_mtime_ns, r.io.sha(path)
            with patch.object(repair, 'quiet_conn', side_effect=AssertionError('Producer should not run')):
                value = repair.environment_attempt(dict(job, memory=3.))
            self.assertTrue(value['ok'] and value['reused_checkpoint'])
            self.assertEqual((stamp, digest), (path.stat().st_mtime_ns, r.io.sha(path)))

    def test_changed_dependency_is_rejected_not_treated_as_memory_retry(self):
        with tempfile.TemporaryDirectory() as td:
            job, *_ = make_fixture(Path(td))
            repair.environment_attempt(job)
            path = Path(job['queries']) / 'windows.parquet'
            r.io.table(path, pa.Table.from_pylist([dict(month_code=7, lo=100, hi=201, complete=True)]))
            with self.assertRaisesRegex(RuntimeError, 'input changed'):
                repair.environment_attempt(job)

    def test_only_DuckDB_OOM_is_eligible_for_retry(self):
        with patch.object(repair, 'ORIGINAL_ENV_JOB', side_effect=repair.duckdb.OutOfMemoryException('synthetic OOM')):
            self.assertFalse(repair.environment_attempt(dict(output='synthetic', memory=3.))['ok'])
        with patch.object(repair, 'ORIGINAL_ENV_JOB', side_effect=RuntimeError('identity mismatch')):
            with self.assertRaisesRegex(RuntimeError, 'identity mismatch'):
                repair.environment_attempt(dict(output='synthetic', memory=3.))

    def test_scheduler_waits_for_first_pool_then_retries_only_failures_alone(self):
        calls = []
        def mapper(fn, jobs, workers, memory, label, forecast, tail):
            calls.append((copy.deepcopy(jobs), workers, memory))
            if len(calls) == 1:
                return [dict(ok=True, value='kept', reused_checkpoint=True),
                        dict(ok=False, message='OOM')]
            return [dict(ok=True, value='retried', reused_checkpoint=False)]
        jobs = [dict(output='0', memory=1., memory_gb=1.6),
                dict(output='1', memory=1., memory_gb=1.6)]
        original = copy.deepcopy(jobs)
        audit = {}
        values = repair.map_environment(jobs, 10, 11., 'test', 1., mapper=mapper, audit=audit)
        self.assertEqual(values, ['kept', 'retried'])
        self.assertEqual(jobs, original)
        self.assertEqual((calls[0][1], calls[1][1]), (2, 1))
        self.assertEqual([j['output'] for j in calls[1][0]], ['1'])
        for i, (planned, slots, total) in enumerate(calls):
            self.assertEqual(planned[0]['memory'], (3., 8.)[i])
            self.assertLessEqual(slots * planned[0]['memory_gb'], total - 1.5)
        self.assertEqual(audit['existing_parts_reused'], 1)
        self.assertEqual(audit['serial_retry_tasks'], 1)

    def test_serial_OOM_fails_closed(self):
        def mapper(*args):
            return [dict(ok=False, message='memory limit reached')]
        with self.assertRaisesRegex(RuntimeError, 'still exceeds the 8 GB'):
            repair.map_environment([dict(output='0')], 10, 11., 'test', 1., mapper=mapper)

    def test_spawn_workers_import_repair_and_return_exact_counts(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            job, games, events, _, windows = make_fixture(p)
            jobs = [dict(job, output=str(p / ('spawn_' + str(i)))) for i in range(2)]
            values = repair.map_environment(jobs, 10, 11., 'synthetic spawn', 1.)
            self.assertEqual(len(values), 2)
            for j in jobs:
                for label in ('person', 'pair'):
                    self.assertEqual(read_counts(j['output'], label),
                                     expected_counts(games, events, windows, label == 'pair'))

    def test_progress_bar_off_and_memory_setting_applied(self):
        with tempfile.TemporaryDirectory() as td:
            db = repair.quiet_conn(Path(td) / 'spill', 3., 1)
            try:
                self.assertFalse(db.execute("SELECT current_setting('enable_progress_bar')").fetchone()[0])
                # DuckDB displays its decimal GB limit as rounded GiB.
                limit = db.execute("SELECT current_setting('memory_limit')").fetchone()[0]
                self.assertEqual(limit.split()[1], 'GiB')
                self.assertGreaterEqual(float(limit.split()[0]), 2.5)
                self.assertLessEqual(float(limit.split()[0]), 3.)
                self.assertEqual(db.execute("SELECT current_setting('threads')").fetchone()[0], 1)
                self.assertFalse(db.execute("SELECT current_setting('preserve_insertion_order')").fetchone()[0])
            finally:
                db.close()

    def test_hook_preserves_prior_report_records_repair_and_keeps_normal_calls(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'run'
            desktop = Path(td) / 'desktop'
            (root / 'report').mkdir(parents=True)
            desktop.mkdir()
            (root / 'report/summary.json').write_text('{"status":"STOPPED_RETURN_LOG"}\n')
            prior = (root / 'report/summary.json').read_bytes()
            execution = dict(repair_version=repair.VERSION)
            with patch.object(repair, 'ORIGINAL_REPLAY', return_value='baseline-ok') as replay, \
                 patch.object(repair, 'ORIGINAL_MAPPED', return_value=['normal-ok']) as mapped, \
                 patch.object(repair, 'ORIGINAL_EXPORT', side_effect=lambda *args: args[5]) as export:
                repair.install_repair(root, desktop, execution)
                args = ({}, root / 'old', root / 'material', root / 'baseline',
                        repair.EXPECTED_CONF, 10, 11.)
                self.assertEqual(repair.inputs.replay_baseline(*args), 'baseline-ok')
                replay.assert_called_once_with(*args)
                fn = object()
                self.assertEqual(repair.runtime.mapped(fn, [], 10, 11., 'normal', 1), ['normal-ok'])
                mapped.assert_called_once_with(fn, [], 10, 11., 'normal', 1, 0, None)
                extra = dict(comparison_frame={'phase_percent': 75})
                repair.report.export(root, desktop, repair.EXPECTED_CONF, 25, 'CHECKED', extra)
                amended = export.call_args.args[5]
                self.assertEqual(amended['comparison_frame'], extra['comparison_frame'])
                self.assertEqual(amended['execution_repair']['repair_version'], repair.VERSION)
                self.assertNotIn('execution_repair', extra)
            snapshots = list((root / 'runtime_repairs').glob('*/report_before_resume/summary.json'))
            self.assertEqual(len(snapshots), 1)
            self.assertEqual(snapshots[0].read_bytes(), prior)
            self.assertTrue((snapshots[0].parent.parent / 'execution.json').exists())

    def test_resume_refuses_another_configuration(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            root = project / 'derived/replication/r9_certified_leave_pair_out_v100_PRIVATE' / repair.EXPECTED_CONF[:12]
            root.mkdir(parents=True)
            r.io.js(root / 'config.json', dict(version='changed'))
            with self.assertRaisesRegex(RuntimeError, 'configuration missing or changed'):
                repair.resume_inputs(project)


if __name__ == '__main__':
    unittest.main()
