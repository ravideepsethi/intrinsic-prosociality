#!/usr/bin/env python3
"""Independent dummy-OLS, clustered covariance, joint-window and I/O checks."""
import os
for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
    os.environ[key] = '1'
import tempfile
import csv
import json
import copy
from pathlib import Path
import unittest
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from fe_engine import make_design, make_layout, iter_blocks
from pooled_engine import absorption, holm
from stable_specs import add_normalized
from followup_specs import Spec, definitions, PLACEBO_SPECS
import followup_engine as eng


def synthetic(seed=71513, accounts=28, rows_per_state=36):
    r = np.random.default_rng(seed); ids = []; board = []
    for i in range(accounts):
        for s, limits in enumerate([(-100, 101), (101, 300), (300, 701)]):
            n = 1 if i == 0 or (i == 1 and s == 2) else rows_per_state
            ids.extend([i]*n); board.extend(r.integers(*limits, n))
    chooser = np.array(ids); board = np.array(board, float); n = len(ids)
    gap = r.integers(-115, 116, n).astype(float); gap[::9] = 0
    K = np.full(n, 11.36); K[::13] = 13.2
    payoff = K*(.5-1/(1+np.exp(gap/170)))
    # Add some exact placebo-center atoms to stress the point-mass terms.
    payoff[::29] = .10*K[::29]; payoff[::31] = -.10*K[::31]
    # These three single-observation chooser-state units must enter the window
    # so the test actually exercises local singleton removal.
    gap[chooser == 0] = 0; payoff[chooser == 0] = 0
    group = np.where(board <= 100, 0, np.where(board < 300, 1, 2))
    chance = .10+.015*(chooser % 5)+.025*group+.035*(gap > 0)+.03*(group == 2)*(gap > 0)
    y = (r.random(n) < chance).astype(int); y[chooser == 3] = 0
    f = dict(chooser=chooser, board=board, gap=gap, payoff=payoff, K=K, y=y,
             ply=r.integers(2, 165, n).astype(float), crd=r.uniform(50, 74, n), drd=r.uniform(50, 74, n),
             cvol=r.uniform(.04, .08, n), dvol=r.uniform(.04, .08, n),
             month=r.integers(0, 24, n), speed=r.integers(0, 5, n))
    edges = {'k20': [11.2, 11.36, 11.8, 13., 20., 30.], 'k50': [11.1, 11.2, 11.36, 11.8, 13., 20., 30.]}
    return add_normalized(f), edges


def dummy_benchmark(original, edges, spec):
    # Build the polynomial and fixed-effect dummies independently of design().
    mask = np.abs(original[spec.axis]-spec.center) <= spec.h
    if spec.omit_ties: mask &= np.abs(original['gap']) > 1e-12
    f = {k: v[mask] for k, v in original.items()}
    labels, inverse, counts = np.unique(np.column_stack([f['chooser'], np.where(f['board'] <= 100, 0, np.where(f['board'] < 300, 1, 2))]), axis=0, return_inverse=True, return_counts=True)
    keep = counts[inverse] >= 2; f = {k: v[keep] for k, v in f.items()}
    labels, inverse = np.unique(np.column_stack([f['chooser'], np.where(f['board'] <= 100, 0, np.where(f['board'] < 300, 1, 2))]), axis=0, return_inverse=True)
    fixed = np.eye(len(labels))[inverse]
    dx = f[spec.axis]-spec.center; z = dx/spec.h
    center = np.abs(dx) <= 1e-12*max(1., spec.h); left = (dx < 0) & ~center; right = (dx > 0) & ~center
    pieces = [z*left, z*right, right, center]
    if spec.degree == 2: pieces += [z*z*left, z*z*right]
    core = np.column_stack(pieces)
    if spec.scope == 'by_state':
        state = np.where(f['board'] <= 100, 0, np.where(f['board'] < 300, 1, 2))
        core = np.concatenate([core*(state == j)[:, None] for j in range(3)], axis=1)
    _, sections = make_layout(edges)
    nuisance = make_design(f, edges)[:, np.concatenate([sections[k] for k in eng.NUISANCE_SECTIONS])].toarray()
    X = np.column_stack([fixed, core, nuisance]); P = np.linalg.pinv(X, rcond=1e-10)
    beta = P@f['y']; residual = f['y']-X@beta
    C = np.zeros((core.shape[1], X.shape[1])); C[:, len(labels):len(labels)+core.shape[1]] = np.eye(core.shape[1])
    values = C@beta
    users, user_code = np.unique(f['chooser'], return_inverse=True)
    influence = (P.T@C.T)*residual[:, None]
    score = np.zeros((len(users), core.shape[1])); np.add.at(score, user_code, influence)
    rank = np.linalg.matrix_rank(X, tol=1e-8)
    correction = len(users)/(len(users)-1)*(len(f['y'])-1)/(len(f['y'])-rank)
    return dict(values=values, covariance=score.T@score*correction, scores=score,
                users=users, correction=correction, n=len(f['y']), G=len(users), H=len(labels), f=f)


class Checks(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.frame, cls.edges = synthetic()

    def test_production_sample_evidence_reader_and_mismatch_guard(self):
        from run_followups import ROOT, SAMPLES, STATES, load_prior_sample_counts, verify_sample_counts
        # Use the actual prior-run artifact, independent of the new loader.
        records = json.loads((ROOT/'evidence/PRIOR_STABLE_SAMPLE_COUNTS.json').read_text())
        loaded = load_prior_sample_counts()
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp)
            for sample in SAMPLES:
                old = next(row for row in records if row['sample'] == sample)
                counts = {}
                for key, value in old.items():
                    if isinstance(value, dict):
                        for j, state in enumerate(STATES): counts[f'{key}__{j}'] = value[state]
                    elif type(value) is int: counts[key] = value
                self.assertEqual(loaded[sample], counts)
                verify_sample_counts(sample, counts, report)
                checks = json.loads((report/(sample+'_SAMPLE_REPLICATION.json')).read_text())
                self.assertEqual(len(checks), 23)
                self.assertTrue(all(row['matched'] for row in checks))
                wrong = dict(counts, estimation_rows=counts['estimation_rows']+1)
                with self.assertRaisesRegex(RuntimeError, 'count replication failed'):
                    verify_sample_counts(sample, wrong, report)
                missing = dict(counts); missing.pop('estimation_rows')
                with self.assertRaisesRegex(RuntimeError, 'count fields differ'):
                    verify_sample_counts(sample, missing, report)
            self.assertEqual(loaded['rd75']['estimation_rows'], 11114912)
            self.assertEqual(loaded['rd75_k11_12']['estimation_rows'], 9263266)
            malformed = report/'malformed.json'
            bad_state = copy.deepcopy(records); bad_state[0]['state_source_rows'].pop(STATES[0])
            for data in ({'samples': records}, [], records+[records[0]], records[:1], bad_state):
                malformed.write_text(json.dumps(data))
                with self.assertRaises(RuntimeError): load_prior_sample_counts(malformed)

    def test_production_prior_linear_evidence_and_failure_detection(self):
        from run_followups import ROOT, prior_replication
        with (ROOT/'evidence/PRIOR_ZERO_DIAGNOSTICS.csv').open() as stream:
            previous = list(csv.DictReader(stream))
        rows = []
        for old in previous:
            row = dict(old, degree=1, center=0, scope='pooled', omit_ties=False,
                       h=float(old['bandwidth']), term=('center_atom_minus_left_limit'
                         if old['term'] == 'zero_atom_minus_left_limit' else old['term']))
            for key in ('n', 'events', 'chooser_clusters', 'absorbed_units', 'left_n', 'right_n'):
                row[key] = int(old[key])
            for key in ('estimate_pp', 'cluster_se_pp'):
                row[key] = float(old[key]) if old[key] else None
            rows.append(row)
        checks = prior_replication(rows)
        self.assertEqual(len(checks), 90)
        self.assertTrue(all(row['matched'] for row in checks))
        rows[0]['cluster_se_pp'] += 0.01
        checks = prior_replication(rows)
        self.assertFalse(checks[0]['matched'])
        self.assertTrue(all(row['matched'] for row in checks[1:]))

    def test_nuisance_design_matches_inherited_controls(self):
        _, sections = make_layout(self.edges)
        old = make_design(self.frame, self.edges)[:, np.concatenate([sections[k] for k in eng.NUISANCE_SECTIONS])]
        np.testing.assert_allclose(old.toarray(), eng.nuisance_design(self.frame, self.edges).toarray(), atol=0, rtol=0)

    def test_pooled_and_state_polynomials_against_full_dummy_OLS(self):
        for spec in (Spec('normalized', .10), Spec('normalized', .10, scope='by_state'), Spec('gap', 100, omit_ties=True)):
            with self.subTest(spec=spec):
                m = eng.Moments(self.edges, spec); m.add(self.frame); model = eng.fit(m)
                eng.scores(self.frame, self.edges, model)
                rows, tests, V = eng.finish(m, model, min_n=1, min_choosers=1, min_months=1, min_gap_levels=1)
                bench = dummy_benchmark(self.frame, self.edges, spec)
                valid = model['identified']
                self.assertGreater(valid.sum(), 3)
                np.testing.assert_allclose(model['estimates'][valid], bench['values'][valid], atol=3e-6, rtol=3e-5)
                np.testing.assert_allclose(V[np.ix_(valid, valid)], bench['covariance'][np.ix_(valid, valid)], atol=3e-6, rtol=2e-4)
                self.assertEqual((m.N, m.G, m.H), (bench['n'], bench['G'], bench['H']))
                self.assertTrue((bench['f']['chooser'] == 3).any(), 'Zero-grant accounts must remain')
                if spec.scope == 'by_state':
                    joint = next(t for t in tests if t['test'] == 'equal_kinks_across_board_states')
                    R = np.zeros((2, model['core_size']))
                    for j in range(2):
                        R[j, 0:2] = [1/spec.h, -1/spec.h]
                        off = (j+1)*6; R[j, off:off+2] = [-1/spec.h, 1/spec.h]
                    d = R@bench['values']; cv = R@bench['covariance']@R.T
                    self.assertAlmostEqual(joint['Wald_statistic'], float(d@np.linalg.solve(cv, d)), places=5)

    def test_joint_window_covariance_matches_independent_cluster_scores(self):
        users = np.unique(self.frame['chooser']); joint = np.zeros((len(users), 3)); independent = np.zeros_like(joint)
        factors = []; independent_factors = []
        for j, spec in enumerate(PLACEBO_SPECS):
            m = eng.Moments(self.edges, spec); m.add(self.frame); model = eng.fit(m)
            ids, score = eng.scores(self.frame, self.edges, model)
            joint[np.searchsorted(users, ids), j] = (score[:, 1]-score[:, 0])/spec.h
            bench = dummy_benchmark(self.frame, self.edges, spec)
            independent[np.searchsorted(users, bench['users']), j] = (bench['scores'][:, 1]-bench['scores'][:, 0])/spec.h
            factors.append(eng.factor(m, model)); independent_factors.append(bench['correction'])
        V = joint.T@joint*np.sqrt(np.outer(factors, factors))
        Vb = independent.T@independent*np.sqrt(np.outer(independent_factors, independent_factors))
        np.testing.assert_allclose(V, Vb, atol=2e-5, rtol=3e-4)
        self.assertGreater(np.max(np.abs(V-np.diag(np.diag(V)))), 1e-5,
                           'Fixture must expose shared-chooser covariance across windows')

    def test_shards_boundaries_checkpoint_and_singletons(self):
        spec = Spec('normalized', .05); full = eng.Moments(self.edges, spec); full.add(self.frame)
        merged = eng.Moments(self.edges, spec)
        with tempfile.TemporaryDirectory() as tmp:
            for shard in range(3):
                keep = self.frame['chooser'] % 3 == shard; f = {k: v[keep] for k, v in self.frame.items()}
                path = Path(tmp)/f'{shard}.parquet'; pq.write_table(pa.table(f), path, row_group_size=37)
                part = eng.Moments(self.edges, spec); seen = []
                for block in iter_blocks(path, batch_rows=97):
                    seen.extend(np.unique(block['chooser'])); part.add(block)
                self.assertEqual(len(seen), len(set(seen)))
                saved = Path(tmp)/f'{shard}.npz'; part.save(saved); merged.merge(eng.Moments.load(saved))
        np.testing.assert_allclose(full.S, merged.S, atol=3e-10, rtol=1e-10)
        np.testing.assert_allclose(full.b, merged.b, atol=1e-10, rtol=1e-10)
        for field in full.scalar_fields(): self.assertEqual(getattr(full, field), getattr(merged, field))
        for field in ('n', 'month', 'cross', 'atom_cross', 'gap_hist'): np.testing.assert_array_equal(getattr(full, field), getattr(merged, field))
        self.assertLess(full.N, full.source_N)
        omitted = eng.Moments(self.edges, Spec('normalized', .05, omit_ties=True)); omitted.add(self.frame)
        self.assertEqual(omitted.source_N, omitted.source_before_omit-omitted.source_ties)
        self.assertLess(omitted.N, full.N)

    def test_empty_support_is_not_reported_as_zero_effect(self):
        f = {k: v.copy() for k, v in self.frame.items()}; f['normalized'][:] = .49
        m = eng.Moments(self.edges, Spec('normalized', .05)); m.add(f); model = eng.fit(m)
        eng.scores(f, self.edges, model); rows, _, _ = eng.finish(m, model)
        self.assertTrue(all(r['status'] == 'unidentified' and r['estimate_pp'] is None for r in rows))

    def test_design_families_and_missing_test_multiplicity(self):
        specs = definitions(); self.assertEqual(len(specs), 30)
        self.assertEqual(sum(s.degree == 1 for s in specs), 9)
        self.assertEqual(sum(s.scope == 'by_state' for s in specs), 5)
        self.assertEqual(sum(s.omit_ties for s in specs), 5)
        rows = [{'p': .01, 'status': 'estimated'}, {'p': None, 'status': 'unidentified'}, {'p': .04, 'status': 'estimated'}]
        holm(rows, lambda r: True, 'p', 'adjusted')
        self.assertAlmostEqual(rows[0]['adjusted'], .03); self.assertAlmostEqual(rows[2]['adjusted'], .08)


if __name__ == '__main__': unittest.main(verbosity=2)
