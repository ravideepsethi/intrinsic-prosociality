#!/usr/bin/env python3
"""Synthetic checks only; never loads the user's production data."""
from __future__ import annotations
import concurrent.futures
import contextlib
import hashlib
import io
import json
import multiprocessing
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import validate_ratings as v


def fixture(month="2024-01", repeat=1):
    # Alternating colors, observed zeros, both/single missing updates, a failed
    # material screen, an unusual chooser loss, and exact bin boundaries.
    color = np.array(["white", "black"] * 6, dtype=object)
    outcome = np.array(["draw", "draw", "win", "win", "draw", "win",
                        "draw", "win", "loss", "draw", "win", "draw"])
    rg = np.array([-2.4, 1.2, -1, 0, 0, 0.2, 0.5, -0.4, 2, 3.5, 4, -0.5])
    premium = np.array([6, 7, 8, 6, 6, 8, 6, 7, 6, 10, 6, 5], dtype=float)
    rc = rg + premium
    pc = np.where(outcome == "draw", rg, np.where(outcome == "win", rc, rg-premium))
    pd = np.where(outcome == "draw", -rg*0.8, np.where(outcome == "win", -rc*1.2, 8.4))
    oc = np.array([-2, 1, 7, 6, 0, np.nan, 1, 7, -4, 3, 0, np.nan])
    od = np.array([2, -1, -8, -7, 0, -9, np.nan, -8, 8, -3, -12, np.nan])
    white = color == "white"
    pgn = np.where(outcome == "draw", "1/2-1/2", np.where(
        (outcome == "win") == white, "1-0", "0-1"))
    material = np.ones(12, dtype=bool)
    material[6] = False
    cp = np.array([-300, -299, -101, -100, 100, 101, 299, 300, 0, 500, -301, 150])
    data = {name: np.ones(12, dtype=bool) for name in v.BOOL_COLUMNS}
    data.update({
        "month": [month]*12, "api_status": ["timeout"]*12,
        "api_variant": ["standard"]*12, "pgn_result": pgn,
        "chooser_color": color, "disconnected_color": np.where(white, "black", "white"),
        "api_speed": ["blitz", "rapid", "bullet", "classical"]*3,
        "white_rating_diff_pgn": np.where(white, oc, od),
        "black_rating_diff_pgn": np.where(white, od, oc),
        "chooser_draw_payoff_v2": rg, "chooser_win_payoff_v2": rc,
        "chooser_win_premium_v2": premium,
        "white_realized_pred_ratingdiff_v2": np.where(white, pc, pd),
        "black_realized_pred_ratingdiff_v2": np.where(white, pd, pc),
        "chooser_pre_rd_v2": [45, 50, 51, 75, 76, 110, 111, 200, 201, 60, 45, 90],
        "disconnected_pre_rd_v2": [45, 200, 45, 45, 45, 110, 45, 60, 60, 80, 45, 70],
        "chooser_elo": [1200, 1599, 1600, 1800, 1999, 2000, 2100, 2399, 2400, 2600, 800, 1500],
        "ply_count": [2, 3, 10, 11, 20, 21, 40, 41, 80, 81, 8, 6],
        "engine_eval_cp_disconnected": cp, "utc_ms": [1704067200000]*12,
        "timeout_draw": outcome == "draw", "timeout_chooser_win": outcome == "win",
        "timeout_chooser_loss": outcome == "loss", "chooser_has_mating_material": material,
        "outcome_kind_draw": (outcome == "draw") & material,
        "both_ratingdiff_null": np.isnan(oc) & np.isnan(od),
        "hidden_state_update_applied": ~(np.isnan(oc) & np.isnan(od)),
        "color_adv_applied": np.zeros(12, dtype=bool),
    })
    arrays = {}
    for name in v.READ_COLUMNS:
        values = np.tile(data[name], repeat)
        if name in v.FLOAT_COLUMNS:
            arrays[name] = pa.array([None if np.isnan(float(x)) else float(x) for x in values], type=pa.float64())
        elif name in v.BOOL_COLUMNS:
            arrays[name] = pa.array(values, type=pa.bool_())
        else:
            arrays[name] = pa.array(values, type=pa.string())
    return pa.table(arrays), oc, rg, rc, outcome, material


def evaluate(table, month="2024-01", batch_size=5):
    agg = v.Aggregate()
    for batch in table.to_batches(max_chunksize=batch_size):
        v.consume(batch, month, agg)
    return agg


class ValidationTests(unittest.TestCase):
    def test_moments_against_independent_numpy(self):
        x = np.array([0, 1, -2, 5, np.nan, 20, -40.0])
        y = np.array([0.2, 1.4, -2.1, 4.8, 999, 25, -39.5])
        a, b = v.Moments(), v.Moments()
        a.add(x[:3], y[:3]); b.add(x[3:], y[3:]); a.merge(b)
        r = a.output(); valid = np.isfinite(x); e = y[valid] - x[valid]
        self.assertEqual(r["eligible_rows"], 7)
        self.assertEqual(r["observed_rows"], 6)
        self.assertEqual(r["observed_zero_rows"], 1)
        self.assertAlmostEqual(r["mae"], np.mean(np.abs(e)), places=12)
        self.assertAlmostEqual(r["rmse"], np.sqrt(np.mean(e**2)), places=12)
        self.assertAlmostEqual(r["correlation"], np.corrcoef(x[valid], y[valid])[0, 1], places=12)
        self.assertAlmostEqual(r["bias_pred_minus_observed"], e.mean(), places=12)
        self.assertAlmostEqual(r["within_1_point_percent"], 100*float((np.abs(e)<=1).mean()), places=12)
        constant = v.Moments()
        constant.add(np.arange(7), np.full(7, 2.4))
        constant.add(np.arange(13), np.full(13, 2.4))
        self.assertIsNone(constant.output()["correlation"])

    def test_color_mapping_missingness_and_primary_outcomes(self):
        table, oc, rg, rc, outcome, material = fixture()
        agg = evaluate(table)
        self.assertEqual(agg.counts["rows"], 12)
        self.assertEqual(agg.counts["kind_draws"], 5)
        self.assertEqual(agg.counts["actual_draws"], 6)
        self.assertEqual(agg.counts["draws_failing_material_screen"], 1)
        self.assertEqual(agg.counts["chooser_losses"], 1)
        self.assertEqual(agg.counts["both_updates_missing"], 1)
        self.assertEqual(agg.counts["one_update_missing"], 2)
        for series, mask, prediction in [
            ("chooser_kind_draw", (outcome=="draw") & material, rg),
            ("chooser_claimed_win", outcome=="win", rc)]:
            r = agg.groups[(series, "overall", "all")].output()
            valid = mask & np.isfinite(oc)
            self.assertEqual(r["eligible_rows"], int(mask.sum()))
            self.assertEqual(r["observed_rows"], int(valid.sum()))
            self.assertAlmostEqual(r["mae"], float(np.abs(prediction[valid]-oc[valid]).mean()))
            self.assertAlmostEqual(r["correlation"], float(np.corrcoef(prediction[valid],oc[valid])[0,1]))
        win = agg.groups[("chooser_claimed_win", "overall", "all")].output()
        self.assertEqual(win["observed_zero_rows"], 1)  # Zero must never become missing.

    def test_inclusive_board_and_rd_boundaries(self):
        agg = evaluate(fixture()[0])
        # Kind draws at -300, -299, +100, +500 and +150.
        for state in ["clearly_worse", "modestly_worse", "roughly_equal", "clearly_better", "better"]:
            self.assertEqual(agg.groups[("chooser_kind_draw", "board_state", state)].total, 1)
        self.assertEqual(agg.groups[("chooser_kind_draw", "chooser_rd_band", "at_most_50")].total, 2)

    def test_chunking_and_merging_preserve_statistics(self):
        table = fixture(repeat=7)[0]
        a, b = evaluate(table, batch_size=1), evaluate(table, batch_size=1000)
        self.assertEqual(a.counts, b.counts)
        for key in a.groups:
            for field in ("mae", "rmse", "correlation", "bias_pred_minus_observed"):
                x, y = a.groups[key].output()[field], b.groups[key].output()[field]
                if x is None or y is None:
                    self.assertEqual(x, y)
                else:
                    self.assertAlmostEqual(x, y, places=10)
        restored = v.Aggregate.restore(a.export())
        self.assertEqual(restored.export(), a.export())

    def test_invalid_role_and_prediction_fail(self):
        table = fixture()[0]
        col = table["chooser_color"].to_pylist(); col[0] = "black"
        bad = table.set_column(table.schema.get_field_index("chooser_color"), "chooser_color", pa.array(col))
        with self.assertRaisesRegex(RuntimeError, "role mismatch"):
            evaluate(bad)
        col = table["chooser_draw_payoff_v2"].to_pylist(); col[0] += 1
        bad = table.set_column(table.schema.get_field_index("chooser_draw_payoff_v2"),
                               "chooser_draw_payoff_v2", pa.array(col))
        with self.assertRaisesRegex(RuntimeError, "premium identity mismatch"):
            evaluate(bad)

    def test_unknown_result_and_missing_flag_fail(self):
        table = fixture()[0]
        col = table["pgn_result"].to_pylist(); col[0] = "*"
        bad = table.set_column(table.schema.get_field_index("pgn_result"), "pgn_result", pa.array(col))
        with self.assertRaisesRegex(RuntimeError, "Unknown PGN result"):
            evaluate(bad)
        col = table["both_ratingdiff_null"].to_pylist(); col[-1] = False
        bad = table.set_column(table.schema.get_field_index("both_ratingdiff_null"),
                               "both_ratingdiff_null", pa.array(col))
        with self.assertRaisesRegex(RuntimeError, "Missing-update flag mismatch"):
            evaluate(bad)

    def test_parquet_process_workers_checkpoint_and_archive(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); jobs = []
            for month in ["2024-01", "2024-02"]:
                path = root / f"{month}.parquet"
                pq.write_table(fixture(month)[0], path, compression="zstd")
                jobs.append({"path":str(path), "month":month, "rows":12,
                             "size_bytes":path.stat().st_size, "batch_rows":4,
                             "expected_sha256":v.authority.sha256_file(path), "analysis_fingerprint":"test"})
            with concurrent.futures.ProcessPoolExecutor(max_workers=2,
                    mp_context=multiprocessing.get_context("spawn")) as pool:
                results = list(pool.map(v.process_month, jobs))
            agg = v.Aggregate()
            for result in results:
                cp = root / (result["month"] + ".json")
                v.write_checkpoint(cp, result)
                saved = v.read_checkpoint(cp, "test", result["input_sha256"])
                agg.merge(v.Aggregate.restore(saved))
            self.assertEqual(agg.counts["rows"], 24)
            cp.write_text(cp.read_text()+" ")
            with self.assertRaisesRegex(RuntimeError, "checksum"):
                v.read_checkpoint(cp, "test", result["input_sha256"])
            report = root / "report"; report.mkdir()
            real_expected = v.EXPECTED
            try:
                v.EXPECTED = {k:agg.counts[k] for k in real_expected}
                v.make_report(report, agg, {"fingerprint":"synthetic"}, "test", {}, {}, [])
                v.validate_finished_report(report)
                archive = v.deliver(report, root/"transfer", "test")
                self.assertTrue(archive.is_file())
                self.assertTrue(Path(str(archive)+".sha256").is_file())
                self.assertTrue(pq.read_table(report/"validation_primary.parquet").num_rows == 2)
                (report/"SUMMARY.md").write_text("modified")
                with self.assertRaisesRegex(RuntimeError, "Report file changed"):
                    v.validate_finished_report(report)
            finally:
                v.EXPECTED = real_expected

    def test_frozen_sample_authority(self):
        auth, report = v.authority.verify_report_package()
        self.assertEqual(auth["rows"], 41534331)
        self.assertEqual(len(report["panel_outputs"]), 24)
        for rec in report["panel_outputs"]:
            self.assertTrue(set(v.READ_COLUMNS).issubset({x["name"] for x in rec["schema"]}))

    def test_complete_execution_and_partial_resume(self):
        # Mock only the external authority/input boundary. Exercise orchestration,
        # spawned workers, reports, partial resume and completed-run reuse.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            records, expected = [], {k: 0 for k in v.EXPECTED}
            for offset in range(24):
                ym = 2023 * 12 + 10 + offset
                month = f"{ym // 12:04d}-{ym % 12 + 1:02d}"
                table = fixture(month)[0]
                path = root / f"{month}.parquet"
                pq.write_table(table, path)
                digest = v.authority.sha256_file(path)
                records.append({"path": path, "month": month, "rows": 12,
                    "size_bytes": path.stat().st_size, "expected_sha256": digest,
                    "actual_sha256": digest})
                counts = evaluate(table, month).counts
                for key in expected:
                    expected[key] += counts[key]
            auth = {"fingerprint": "synthetic", "schema": v.READ_COLUMNS,
                    "month_records": records}
            args = SimpleNamespace(project_root=root, sample_root=root,
                output_root=root / "runs", transfer_root=root / "transfer",
                workers=2, hash_workers=1, batch_rows=4)
            log = io.StringIO()
            with mock.patch.object(v.authority, "authenticate_sample", return_value=auth), \
                 mock.patch.object(v, "package_hashes", return_value={"fixture": "test"}), \
                 mock.patch.object(v, "EXPECTED", expected), contextlib.redirect_stdout(log):
                self.assertEqual(v.execute(args), 0)
                run = next((root / "runs").glob("run_*"))
                cp_dir = run / "checkpoints"
                kept = cp_dir / "2023-11.json"
                kept_mtime = kept.stat().st_mtime_ns
                missing = cp_dir / "2023-12.json"
                missing.unlink()
                Path(str(missing) + ".sha256").unlink()
                (run / "report" / "_SUCCESS.json").unlink()
                log.seek(0); log.truncate(0)
                self.assertEqual(v.execute(args), 0)
                self.assertEqual(log.getvalue().count("REUSED_MONTH"), 23)
                self.assertEqual(log.getvalue().count("MONTH_OK"), 1)
                self.assertEqual(kept.stat().st_mtime_ns, kept_mtime)
                self.assertTrue(missing.is_file())
                v.validate_finished_report(run / "report")
                log.seek(0); log.truncate(0)
                self.assertEqual(v.execute(args), 0)
                self.assertIn("ALREADY_COMPUTED_OK", log.getvalue())
                self.assertNotIn("MONTH_OK", log.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
