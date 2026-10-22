#!/usr/bin/env python3
"""Synthetic regression, partition, support, and corruption checks. No study results."""
import os
for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[name] = "1"
import tempfile
import unittest
from pathlib import Path
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from surface_model import (Settings, Moments, controls, cell_ids, axis_bins,
    consume, estimate, make_grid, CONTROL_COLUMNS, X, D, Y)
from render_surfaces import grids, supported_triangles
from run_surfaces import save_checkpoint, load_checkpoint, month_job


def fixture(n=12000, seed=73, *, constant_volatility=False):
    rng = np.random.default_rng(seed)
    x = rng.uniform(-3, 3, n)
    d = rng.uniform(-300, 300, n)
    rd = np.exp(rng.uniform(np.log(20), np.log(400), n) + 0.1*x)
    values = {X: x, D: d.astype(np.int32),
        "ply_count": np.rint(np.exp(rng.uniform(0, np.log(501), n))-1).astype(np.int32),
        "chooser_pre_rd_v2": rd,
        "disconnected_pre_rd_v2": np.exp(rng.uniform(np.log(20), np.log(400), n)),
        "chooser_pre_sigma_v2": np.full(n, .06) if constant_volatility else np.exp(rng.uniform(np.log(.015), np.log(.15), n)),
        "disconnected_pre_sigma_v2": np.exp(rng.uniform(np.log(.015), np.log(.15), n)),
        "month": np.full(n, "2023-11", dtype=object)}
    probability = .19 + .03*x + .045*np.tanh(d/150) + .03*np.log(rd/100)
    values[Y] = rng.random(n) < probability
    return values


def stats_for(values, settings):
    stats = Moments(settings)
    z = controls(values)
    ids = cell_ids(values[X], values[D], settings)
    originals = np.column_stack([values[name] for name in CONTROL_COLUMNS])
    stats.add(ids, values[Y].astype(float), z, originals, values[D])
    return stats, ids, z


class SurfaceChecks(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(payoff_min=-2, payoff_max=2, payoff_step=1,
            desert_min=-200, desert_max=200, desert_step=100,
            min_cell_n=10, min_cell_months=1, batch_rows=2048)
        self.settings.validate()

    def test_fwl_standardization_agrees_with_dense_joint_regression(self):
        values = fixture()
        stats, ids, z = stats_for(values, self.settings)
        raw, adjusted, info = estimate(stats)
        occupied = np.flatnonzero(stats.n)
        # Independent direct dummy-variable OLS, rather than the streaming moments formula.
        dummy = (ids[:, None] == occupied).astype(float)
        scale = z.std(axis=0)
        keep = scale > 1e-10
        centered = (z[:, keep] - z[:, keep].mean(axis=0)) / scale[keep]
        design = np.column_stack([dummy, centered])
        coef = np.linalg.lstsq(design, values[Y].astype(float), rcond=1e-9)[0]
        np.testing.assert_allclose(adjusted[occupied], 100*coef[:len(occupied)], atol=2e-7, rtol=2e-7)
        np.testing.assert_allclose(raw[occupied], 100*stats.events[occupied]/stats.n[occupied])
        self.assertGreater(float(np.max(np.abs(adjusted[occupied]-raw[occupied]))), .05)
        self.assertAlmostEqual(info["raw_overall_percent"], info["weighted_adjusted_overall_percent"], places=10)

    def test_constant_volatility_and_redundant_splines_are_identified(self):
        values = fixture(constant_volatility=True)
        stats, _, _ = stats_for(values, self.settings)
        _, adjusted, info = estimate(stats)
        self.assertTrue(np.isfinite(adjusted[stats.n > 0]).all())
        self.assertLess(info["identified_control_rank"], info["control_terms"])

    def test_edge_and_tail_observations_are_never_clamped(self):
        e = self.settings.xedges
        v = np.array([-99, -2, -1, 0, 1, 2, 99.0])
        np.testing.assert_array_equal(axis_bins(v, e), [0, 1, 2, 3, 4, 4, 5])

    def test_partition_merging_agrees_with_single_scan(self):
        values = fixture()
        all_stats, _, _ = stats_for(values, self.settings)
        merged = Moments(self.settings)
        for index in np.array_split(np.arange(len(values[X])), 7):
            part, _, _ = stats_for({k:v[index] for k,v in values.items()}, self.settings)
            merged.merge(part)
        self.assertEqual(merged.counts, all_stats.counts)
        for name in all_stats.arrays():
            np.testing.assert_allclose(merged.arrays()[name], all_stats.arrays()[name], rtol=1e-10, atol=2e-8)
        np.testing.assert_allclose(estimate(merged)[1], estimate(all_stats)[1], atol=2e-7, rtol=2e-7)

    def test_arrow_scan_resume_and_checkpoint_corruption(self):
        values = fixture(4000)
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            parquet, checkpoint = temp / "panel.parquet", temp / "checkpoint.npz"
            pq.write_table(pa.table(values), parquet)
            job = {"month":"2023-11", "path":str(parquet), "checkpoint":str(checkpoint),
                   "settings":self.settings.dictionary(), "rows":4000, "size_bytes":parquet.stat().st_size,
                   "input_sha256":"synthetic", "run_fingerprint":"synthetic"}
            a = month_job(job)
            b = month_job(job)
            self.assertFalse(a["resumed"])
            self.assertTrue(b["resumed"])
            expected, _, _ = stats_for(values, self.settings)
            self.assertEqual(a["counts"], expected.counts)
            loaded = load_checkpoint(checkpoint, self.settings, {"run_fingerprint":"synthetic"})
            np.testing.assert_allclose(estimate(loaded)[1], estimate(expected)[1], atol=2e-7)
            with checkpoint.open("ab") as f: f.write(b"bad")
            with self.assertRaisesRegex(RuntimeError, "Corrupt checkpoint"):
                month_job(job)

    def test_invalid_covariate_never_silently_drops_rows(self):
        values = fixture(100)
        values["chooser_pre_rd_v2"][7] = np.nan
        batch = pa.table(values).to_batches()[0]
        with self.assertRaisesRegex(RuntimeError, "Nonfinite|nonfinite"):
            consume(batch, "2023-11", self.settings, Moments(self.settings))

    def test_support_is_identical_and_does_not_depend_on_events(self):
        stats = Moments(self.settings)
        stats.n[:] = 20
        raw = np.zeros(self.settings.cells)
        adjusted = np.full(self.settings.cells, -.1)  # preserve LPM out-of-range values
        month_counts = stats.n[None, :]
        rows = make_grid(stats, self.settings, raw, adjusted, month_counts)
        r, a, _ = grids(rows, self.settings)
        self.assertEqual(np.isfinite(r).sum(), 16)
        np.testing.assert_array_equal(np.isfinite(r), np.isfinite(a))
        self.assertEqual(a[0,0], -.1)
        mask = np.ones((4,4), dtype=bool)
        mask[1,1] = False
        triangles = supported_triangles(mask)
        self.assertNotIn(5, triangles.ravel())
        self.assertEqual(len(triangles), 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
