#!/usr/bin/env python3
"""Synthetic numerical, input-contract and checkpoint checks; no project rows."""
from __future__ import annotations

import hashlib
import contextlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import duckdb
import numpy as np
import analysis as a
import run_analysis as r


def synthetic(n=9000, seed=71203):
    rng = np.random.default_rng(seed)
    origin = a.inherited.PANEL_START
    day = rng.integers(110, 230, n)
    day[np.arange(n) % 10 == 0] -= 105
    t = origin + day * a.DAY + rng.integers(0, 180_000, n)
    focal = rng.integers(1, 701, n)
    opponent = rng.integers(1, 1101, n)
    opponent[opponent == focal] += 1101
    own = 1500 + rng.integers(0, 100, n)
    gap = rng.normal(0, 105, n).round()
    fair = rng.poisson(3, n)
    fair[rng.random(n) < .25] = 0
    kind = rng.binomial(fair, .04 + .015 * np.tanh(gap / 100))
    eligible = rng.random(n) < .93
    u = rng.random(n)
    active = u < (.06 + .01 * np.tanh(gap / 100))
    passive = (u >= .10) & (u < .29)
    role = rng.integers(0, 3, n)
    disc = active & eligible & (role == 0)
    chooser = active & eligible & (role == 1)
    fair_arm = disc & (rng.random(n) < .4)
    date_month = np.asarray(t, dtype='datetime64[ms]').astype('datetime64[M]').astype(int)
    start_month = np.datetime64('2023-11', 'M').astype(int)
    return a.derived(dict(sample_row=np.arange(n), archive_start_ms=t, month_code=date_month-start_month,
        recipient_id=focal, opponent_id=opponent, recipient_rating=own.astype(float),
        opponent_rating=(own+gap).astype(float), tc_base_s=rng.choice([60, 180, 300], n),
        tc_inc_s=np.zeros(n, dtype=int), own_fair90=fair, own_kind90=kind,
        own_fair_n=fair.copy(), own_kind_n=kind.copy(), own_history_complete=t-97*a.DAY >= origin,
        active_timeout=active, passive_outoftime=passive, eligible_main=eligible,
        recipient_disconnect_main=disc, recipient_chooser_main=chooser,
        recipient_fair_arm_main=fair_arm, actual_iv_exposure=fair_arm & (rng.random(n) < .8)))


def direct_union_meat(score, focal, opponent, date):
    result = np.zeros((score.shape[1], score.shape[1]))
    for j in range(len(score)):
        for k in range(len(score)):
            if date[j] == date[k] or {focal[j], opponent[j]} & {focal[k], opponent[k]}:
                result += np.outer(score[j], score[k])
    return result


class Tests(unittest.TestCase):
    def test_01_source_bindings(self):
        r.verify_sources()

    def test_02_shared_account_or_date_inclusion_exclusion(self):
        i = np.array([1, 2, 1, 5, 6, 8, 2, 9])
        j = np.array([2, 1, 3, 6, 7, 9, 3, 8])
        date = np.array([1, 1, 2, 2, 3, 4, 3, 5])
        score = np.random.default_rng(4).normal(size=(8, 3))
        codes = a.inherited.covariance_codes(i, j, date)
        got = a.shared_meat(score, codes)
        np.testing.assert_allclose(got, direct_union_meat(score, i, j, date), atol=1e-12)
        for k in range(3):
            self.assertAlmostEqual(got[k, k], a.inherited.covariance_meat(score[:, k], codes, True), places=11)

    def test_03_FWL_matches_explicit_dummy_fit_and_covariance(self):
        rng = np.random.default_rng(193)
        n = 160
        fe = [np.arange(n) % 4, np.arange(n) // 16]
        continuous = rng.normal(size=n)
        x = rng.normal(size=(n, 3))
        y = x @ np.array([.3, -.1, .2]) + .7*continuous + fe[0] + rng.normal(size=n)
        residual, info = a.residualize(np.column_stack([continuous, x, y]), fe, 1)
        i = np.arange(n) % 23
        j = (np.arange(n) * 3) % 29 + 30
        date = np.arange(n) % 37
        codes = a.inherited.covariance_codes(i, j, date)
        b, cov, _ = a.linear_fit(residual[:, :3], residual[:, 3], codes)
        nuisance = np.column_stack([np.ones(n), continuous,
            np.eye(4)[fe[0]][:, 1:], np.eye(10)[fe[1]][:, 1:]])
        design = np.column_stack([nuisance, x])
        inv = np.linalg.inv(design.T @ design)
        direct_b = inv @ design.T @ y
        direct_e = y - design @ direct_b
        influence = (design @ inv)[:, -3:] * direct_e[:, None]
        direct_cov = direct_union_meat(influence, i, j, date)
        np.testing.assert_allclose(b, direct_b[-3:], atol=2e-10)
        np.testing.assert_allclose(cov, direct_cov, atol=2e-10)
        v = np.array([1., 1., 1.])
        # The full off-diagonal covariance, not just diagonal variances, enters a contrast.
        self.assertGreater(abs(float(v @ cov @ v - np.trace(cov))), 1e-7)
        got = a.interval(float(v @ b), float(v @ cov @ v))
        self.assertAlmostEqual(got['standard_error']**2, float(v @ cov @ v), places=12)

    def test_04_history_window_excludes_leakage_and_has_exact_boundaries(self):
        start = a.inherited.PANEL_START + 200*a.DAY
        tt = np.array([start-97*a.DAY-1, start-97*a.DAY, start-8*a.DAY,
                       start-7*a.DAY-1, start-7*a.DAY, start, start+2*a.DAY])
        h = dict(j=np.ones(7, int), i=np.full(7, 3), t=tt, start=tt-1,
                 gid=np.array(['hist%04d'%i for i in range(7)]), ord=np.arange(7),
                 fair=np.ones(7, bool), y=np.array([1, 0, 1, 0, 1, 1, 1], bool))
        q = dict(sample_row=np.array([0]), archive_start_ms=np.array([start]),
                 anchor_ms=np.array([start+1000]), recipient_id=np.array([1]),
                 opponent_id=np.array([2]), game_id=np.array(['focal123']))
        got = a.inherited.later_outcomes(h, q)
        self.assertEqual(got['own_fair90'][0], 3)
        self.assertEqual(got['own_kind90'][0], 1)
        h['y'][[0, 4, 5, 6]] = False
        again = a.inherited.later_outcomes(h, q)
        np.testing.assert_array_equal(got['own_kind90'], again['own_kind90'])

    def test_05_full_synthetic_specs_and_exact_selection_decompositions(self):
        d = synthetic()
        for spec in a.SPECS:
            with self.subTest(spec=spec['name']):
                fit = a.fit_spec(d, spec)
                self.assertTrue(fit['supported'], fit)
                for err in fit['coefficient_identities'].values(): self.assertLess(err, 1e-10)
                if spec['name'] == 'local5_primary':
                    self.assertGreater(fit['rows_with_residual_gap_variation'], 500)
                    self.assertIn('joint_baseline_test', fit)
        self.assertEqual(len(a.support_inventory(d)), 27)
        for raw in a.raw_tables(d):
            self.assertEqual(raw['any_candidate_count'], raw['active_timeout_count']+raw['passive_outoftime_count'])

    def test_06_sparse_cells_and_indefinite_covariance_do_not_pass(self):
        d = synthetic(1100)
        d['archive_start_ms'] = a.inherited.PANEL_START + (110+np.arange(1100))*a.DAY
        self.assertFalse(a.fit_spec(d, a.SPECS[1])['supported'])
        self.assertFalse(a.wald(np.array([1., 1.]), np.array([[1., 2.], [2., 1.]]))['supported'])
        self.assertFalse(a.interval(.1, -1)['supported'])

    def test_07_parquet_schema_validation_and_flag_rejection(self):
        d = synthetic(600)
        n = len(d['sample_row'])
        d['game_id'] = np.array(['PRIVATE_SENTINEL_%07d'%i for i in range(n)])
        d['status'] = np.where(d['active_timeout'], 'timeout', np.where(d['passive_outoftime'], 'outoftime', 'mate'))
        d['previous_classification_status'] = np.where(d['eligible_main'], a.NONADJ, 'mutually_adjacent_observed')
        d['recipient_identity_state'] = np.full(n, 'MATCHED')
        d['opponent_identity_state'] = np.full(n, 'MATCHED')
        cols = r.NUMERIC_COLUMNS + r.STRING_COLUMNS
        types = ['VARCHAR' if c in r.STRING_COLUMNS else ('BOOLEAN' if d[c].dtype == bool else ('DOUBLE' if d[c].dtype.kind == 'f' else 'BIGINT')) for c in cols]
        with tempfile.TemporaryDirectory() as td:
            db = duckdb.connect()
            db.execute('CREATE TABLE fixture (' + ','.join('"'+c+'" '+t for c,t in zip(cols,types)) + ')')
            rows = [[d[c][i].item() for c in cols] for i in range(n)]
            db.executemany('INSERT INTO fixture VALUES ('+','.join('?' for c in cols)+')', rows)
            p = Path(td)/'fixture.parquet'
            db.execute('COPY fixture TO ? (FORMAT PARQUET)', [str(p)])
            loaded, qa = r.load_frame(p, n, int(d['eligible_main'].sum()))
            self.assertEqual(qa['rows'], n)
            self.assertNotIn('game_id', loaded)
            db.execute("UPDATE fixture SET status='timeout' WHERE sample_row=0")
            db.execute('UPDATE fixture SET active_timeout=false WHERE sample_row=0')
            db.execute('COPY fixture TO ? (FORMAT PARQUET)', [str(p)])
            with self.assertRaisesRegex(RuntimeError, 'ending flags'): r.load_frame(p, n, int(d['eligible_main'].sum()))
            db.close()

    def test_08_checkpoint_reuse_rejects_changed_results_and_public_whitelist(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); target = root/'not_yet_created'/'stage.json'
            answer, reused = r.checkpoint(target, 'test_config', lambda: {'a': 1.25})
            self.assertFalse(reused)
            answer, reused = r.checkpoint(target, 'test_config', lambda: self.fail('should reuse'))
            self.assertTrue(reused)
            altered = json.loads(target.read_text()); altered['result']['a'] = 3
            target.write_text(json.dumps(altered))
            with self.assertRaisesRegex(RuntimeError, 'integrity'): r.checkpoint(target, 'test_config', dict)
            payload = r.report_payload({'status':'SYNTHETIC_ONLY'}, {'rows':600}, [], [], [])
            with contextlib.redirect_stdout(io.StringIO()):
                out = r.export_report(root, payload, 'SYNTHETIC')
            self.assertEqual(r.digest(out), Path(str(out)+'.sha256').read_text().split()[0])
            with zipfile.ZipFile(out) as z:
                self.assertIsNone(z.testzip())
                self.assertEqual(set(z.namelist()), set(payload)|{'REPORT_MANIFEST.sha256'})
                for line in z.read('REPORT_MANIFEST.sha256').decode().splitlines():
                    digest, name = line.split('  ', 1)
                    self.assertEqual(hashlib.sha256(z.read(name)).hexdigest(), digest)
                for name in z.namelist(): self.assertNotIn(b'PRIVATE_SENTINEL', z.read(name))

    def test_09_input_requires_both_exact_configuration_and_file_digest(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td); base = project/'source_run'
            (base/'analysis').mkdir(parents=True)
            source = base/'analysis/comparison.parquet'
            source.write_bytes(b'synthetic source authentication fixture')
            config = {'synthetic':True, 'literal':'configuration identity'}
            conf = r.canonical(config)
            authority = dict(relative_root='source_run', config_sha256=conf,
                comparison_sha256=r.digest(source), comparison_bytes=source.stat().st_size)
            r.write_json(base/'config.json', config)
            r.write_json(base/'analysis/_DONE.json', {'config_sha256':conf,
                'files':[dict(path='comparison.parquet',sha256=authority['comparison_sha256'],bytes=authority['comparison_bytes'])]})
            with contextlib.redirect_stdout(io.StringIO()):
                _, receipt = r.verify_input(project, authority)
                self.assertTrue(receipt['comparison_fully_hashed'])
                source.write_bytes(b'x'*authority['comparison_bytes'])
                with self.assertRaisesRegex(RuntimeError, 'SHA-256 mismatch'): r.verify_input(project, authority)
            r.write_json(base/'config.json', {'synthetic':True,'literal':'changed'})
            with self.assertRaisesRegex(RuntimeError, 'configuration'): r.verify_input(project, authority)


if __name__ == '__main__': unittest.main(verbosity=2)
