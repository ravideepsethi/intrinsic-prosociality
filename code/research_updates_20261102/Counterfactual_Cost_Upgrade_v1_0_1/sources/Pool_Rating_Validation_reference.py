#!/usr/bin/env python3
"""Observed-rating validation of the frozen 41,534,331-row pool panel.

Reads only the existing panel. Never replays ratings, fetches games, fits a
correction to observed updates, or changes sample membership.
"""
from __future__ import annotations

import argparse
import concurrent.futures as futures
import csv
import hashlib
import io
import json
import math
import multiprocessing
import os
from pathlib import Path
import platform
import sys
import time
import traceback
import zipfile

# Set before importing numerical libraries; each month worker has one BLAS thread.
for _env in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
             "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_env] = "1"

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from source import pool_wave1_common as authority

ROOT = Path(__file__).resolve().parent
VERSION = "1.0.0"
EXPECTED = {"rows": 41534331, "kind_draws": 570091,
            "fair_rows": 15207423, "fair_kind_draws": 419463}
PRIMARY = ("chooser_kind_draw", "chooser_claimed_win")
FLOAT_COLUMNS = (
    "white_rating_diff_pgn", "black_rating_diff_pgn",
    "chooser_draw_payoff_v2", "chooser_win_payoff_v2", "chooser_win_premium_v2",
    "white_realized_pred_ratingdiff_v2", "black_realized_pred_ratingdiff_v2",
    "chooser_pre_rd_v2", "disconnected_pre_rd_v2", "chooser_elo", "ply_count",
    "engine_eval_cp_disconnected", "utc_ms",
)
BOOL_COLUMNS = (
    "api_rated", "pgn_api_result_consistent", "timeout_draw", "timeout_chooser_win",
    "timeout_chooser_loss", "outcome_kind_draw", "chooser_has_mating_material",
    "both_ratingdiff_null", "hidden_state_update_applied", "color_adv_applied",
    "white_rating_source_match", "black_rating_source_match",
    "white_ratingdiff_source_match", "black_ratingdiff_source_match",
    "speed_source_match", "month_source_match",
)
STRING_COLUMNS = ("month", "api_status", "api_variant", "pgn_result",
                  "chooser_color", "disconnected_color", "api_speed")
READ_COLUMNS = sorted(set(FLOAT_COLUMNS + BOOL_COLUMNS + STRING_COLUMNS))


def log(message):
    print(f"[{authority.utc_now()}] {message}", flush=True)


def number_array(batch, name):
    return np.asarray(batch.column(batch.schema.get_field_index(name)).to_numpy(
        zero_copy_only=False), dtype=np.float64)


def required_array(batch, name, dtype=None):
    column = batch.column(batch.schema.get_field_index(name))
    if column.null_count:
        raise RuntimeError(f"Unexpected nulls in required field {name}: {column.null_count}")
    return np.asarray(column.to_numpy(zero_copy_only=False), dtype=dtype)


def require(condition, message):
    if not bool(condition):
        raise RuntimeError(message)


class Moments:
    """Mergeable, centered covariance plus coverage and error diagnostics."""
    def __init__(self):
        self.total = self.n = self.missing = self.observed_zero = 0
        self.mean_x = self.mean_y = self.m2_x = self.m2_y = self.cross = 0.0
        self.abs_sum = self.sq_sum = self.max_abs = 0.0
        self.within_half = self.within_one = self.within_two = self.over_five = 0
        self.opposite_nonzero_sign = 0

    def add(self, observed, predicted):
        observed = np.asarray(observed, dtype=float)
        predicted = np.asarray(predicted, dtype=float)
        require(np.isfinite(predicted).all(), "Nonfinite reconstructed prediction")
        require(not np.isinf(observed).any(), "Infinite observed rating change")
        finite = np.isfinite(observed)
        other = Moments()
        other.total = int(len(observed))
        other.n = int(finite.sum())
        other.missing = other.total - other.n
        if other.n:
            x, y = observed[finite], predicted[finite]
            other.mean_x, other.mean_y = float(x.mean()), float(y.mean())
            # Summing identical nonbinary floats can shift their mean by an
            # ulp and invent nonzero variance. Preserve exact constants.
            if np.all(x == x[0]):
                other.mean_x = float(x[0])
            if np.all(y == y[0]):
                other.mean_y = float(y[0])
            dx, dy = x - other.mean_x, y - other.mean_y
            other.m2_x, other.m2_y = float(np.dot(dx, dx)), float(np.dot(dy, dy))
            other.cross = float(np.dot(dx, dy))
            error = y - x
            absolute = np.abs(error)
            other.abs_sum = float(absolute.sum())
            other.sq_sum = float(np.dot(error, error))
            other.max_abs = float(absolute.max())
            other.within_half = int((absolute <= 0.5).sum())
            other.within_one = int((absolute <= 1.0).sum())
            other.within_two = int((absolute <= 2.0).sum())
            other.over_five = int((absolute > 5.0).sum())
            other.observed_zero = int((x == 0).sum())
            other.opposite_nonzero_sign = int(((x * y) < 0).sum())
        self.merge(other)

    def merge(self, other):
        n0, n1 = self.n, other.n
        if n1:
            if n0:
                n = n0 + n1
                dx, dy = other.mean_x - self.mean_x, other.mean_y - self.mean_y
                scale = n0 * n1 / n
                self.m2_x += other.m2_x + dx * dx * scale
                self.m2_y += other.m2_y + dy * dy * scale
                self.cross += other.cross + dx * dy * scale
                self.mean_x += dx * n1 / n
                self.mean_y += dy * n1 / n
            else:
                for key in ("mean_x", "mean_y", "m2_x", "m2_y", "cross"):
                    setattr(self, key, getattr(other, key))
        for key in ("total", "n", "missing", "observed_zero", "abs_sum", "sq_sum",
                    "within_half", "within_one", "within_two", "over_five",
                    "opposite_nonzero_sign"):
            setattr(self, key, getattr(self, key) + getattr(other, key))
        self.max_abs = max(self.max_abs, other.max_abs)

    @classmethod
    def restore(cls, values):
        obj = cls()
        require(set(values) == set(vars(obj)), "Checkpoint metric schema mismatch")
        vars(obj).update(values)
        return obj

    def output(self):
        corr = None
        if self.n > 1 and self.m2_x > 0 and self.m2_y > 0:
            corr = max(-1.0, min(1.0, self.cross / math.sqrt(self.m2_x * self.m2_y)))
        def rate(value):
            return 100.0 * value / self.n if self.n else None
        return {
            "eligible_rows": self.total, "observed_rows": self.n,
            "missing_observed_rows": self.missing,
            "coverage_percent": 100.0 * self.n / self.total if self.total else None,
            "correlation": corr,
            "mean_observed": self.mean_x if self.n else None,
            "mean_predicted": self.mean_y if self.n else None,
            "bias_pred_minus_observed": self.mean_y - self.mean_x if self.n else None,
            "mae": self.abs_sum / self.n if self.n else None,
            "rmse": math.sqrt(self.sq_sum / self.n) if self.n else None,
            "max_absolute_error": self.max_abs if self.n else None,
            "within_0_5_points_percent": rate(self.within_half),
            "within_1_point_percent": rate(self.within_one),
            "within_2_points_percent": rate(self.within_two),
            "over_5_points_percent": rate(self.over_five),
            "observed_zero_rows": self.observed_zero,
            "opposite_nonzero_sign_rows": self.opposite_nonzero_sign,
            "opposite_nonzero_sign_percent": rate(self.opposite_nonzero_sign),
        }


class Aggregate:
    def __init__(self):
        self.groups = {}
        self.counts = {}

    def count(self, key, value):
        self.counts[key] = self.counts.get(key, 0) + int(value)

    def add(self, series, dimension, level, observed, predicted):
        key = (series, dimension, str(level))
        self.groups.setdefault(key, Moments()).add(observed, predicted)

    def merge(self, other):
        for key, value in other.counts.items():
            self.count(key, value)
        for key, value in other.groups.items():
            self.groups.setdefault(key, Moments()).merge(value)

    def export(self):
        return {"counts": self.counts, "groups": [
            {"series": k[0], "dimension": k[1], "level": k[2], "moments": vars(v)}
            for k, v in sorted(self.groups.items())]}

    @classmethod
    def restore(cls, value):
        obj = cls()
        obj.counts = value["counts"]
        for row in value["groups"]:
            key = (row["series"], row["dimension"], row["level"])
            require(key not in obj.groups, "Duplicate group in checkpoint")
            obj.groups[key] = Moments.restore(row["moments"])
        return obj

    def table(self):
        return [{"series": k[0], "dimension": k[1], "level": k[2], **v.output()}
                for k, v in sorted(self.groups.items())]


def categorize(values, cuts, labels, *, right=False):
    require(len(labels) == len(cuts) + 1, "Invalid category definition")
    require(np.isfinite(values).all(), "Nonfinite value in diagnostic grouping")
    return np.asarray(labels, dtype=object)[np.digitize(values, cuts, right=right)]


def consume(batch, month, target):
    n = batch.num_rows
    if not n:
        return
    v = {name: number_array(batch, name) for name in FLOAT_COLUMNS}
    b = {name: required_array(batch, name, bool) for name in BOOL_COLUMNS}
    s = {name: required_array(batch, name) for name in STRING_COLUMNS}
    for name in FLOAT_COLUMNS:
        if name not in ("white_rating_diff_pgn", "black_rating_diff_pgn"):
            require(np.isfinite(v[name]).all(), f"Nonfinite required values: {name}")
    for name in ("white_rating_diff_pgn", "black_rating_diff_pgn"):
        obs = v[name]
        require(not np.isinf(obs).any(), f"Infinite recorded update: {name}")
        require(np.equal(obs[np.isfinite(obs)], np.trunc(obs[np.isfinite(obs)])).all(),
                f"Recorded updates are not integers: {name}")
    require((s["month"] == month).all(), "Month field disagrees with panel partition")
    require((s["api_status"] == "timeout").all(), "Non-timeout row in certified panel")
    require((s["api_variant"] == "standard").all(), "Non-standard variant")
    for key in ("api_rated", "pgn_api_result_consistent", "white_rating_source_match",
                "black_rating_source_match", "white_ratingdiff_source_match",
                "black_ratingdiff_source_match", "speed_source_match", "month_source_match"):
        require(b[key].all(), f"Source consistency check failed: {key}")
    require(not b["color_adv_applied"].any(), "Color adjustment in pre-November-2025 panel")
    require(np.isin(s["api_speed"], ["ultrabullet", "bullet", "blitz", "rapid", "classical"]).all(),
            "Unexpected speed category")
    require(np.isin(s["chooser_color"], ["white", "black"]).all(), "Invalid chooser color")
    white = s["chooser_color"] == "white"
    require((s["disconnected_color"] == np.where(white, "black", "white")).all(),
            "Chooser/disconnected role mismatch")
    result = s["pgn_result"]
    require(np.isin(result, ["1-0", "0-1", "1/2-1/2"]).all(), "Unknown PGN result")
    draw = result == "1/2-1/2"
    win = ((result == "1-0") & white) | ((result == "0-1") & ~white)
    loss = ~(draw | win)
    for flag, derived in (("timeout_draw", draw), ("timeout_chooser_win", win),
                          ("timeout_chooser_loss", loss)):
        require(np.array_equal(b[flag], derived), f"Outcome classification mismatch: {flag}")
    kind = b["outcome_kind_draw"]
    require(np.array_equal(kind, draw & b["chooser_has_mating_material"]),
            "Kind-draw indicator disagrees with draw and material screen")
    ow, ob = v["white_rating_diff_pgn"], v["black_rating_diff_pgn"]
    mw, mb = np.isnan(ow), np.isnan(ob)
    both_missing = mw & mb
    require(np.array_equal(b["both_ratingdiff_null"], both_missing), "Missing-update flag mismatch")
    require(np.array_equal(b["hidden_state_update_applied"], ~both_missing),
            "Hidden-state missing-update policy mismatch")
    oc, od = np.where(white, ow, ob), np.where(white, ob, ow)
    pw, pb = v["white_realized_pred_ratingdiff_v2"], v["black_realized_pred_ratingdiff_v2"]
    pc, pd = np.where(white, pw, pb), np.where(white, pb, pw)
    rg, rc, premium = (v["chooser_draw_payoff_v2"], v["chooser_win_payoff_v2"],
                       v["chooser_win_premium_v2"])
    require((premium > 0).all(), "Nonpositive win premium")
    require(np.allclose(rc - rg, premium, rtol=1e-12, atol=1e-8), "Win-premium identity mismatch")
    require(np.allclose(pc[draw], rg[draw], rtol=1e-12, atol=1e-8),
            "Stored realized draw prediction differs from manuscript payoff")
    require(np.allclose(pc[win], rc[win], rtol=1e-12, atol=1e-8),
            "Stored realized win prediction differs from manuscript payoff")
    cp = v["engine_eval_cp_disconnected"]
    fair = cp >= -100
    for key, value in {
        "rows": n, "kind_draws": kind.sum(), "fair_rows": fair.sum(),
        "fair_kind_draws": (fair & kind).sum(), "actual_draws": draw.sum(),
        "chooser_claimed_wins": win.sum(), "chooser_losses": loss.sum(),
        "draws_failing_material_screen": (draw & ~kind).sum(),
        "both_updates_missing": both_missing.sum(), "one_update_missing": (mw ^ mb).sum(),
        "white_update_missing": mw.sum(), "black_update_missing": mb.sum(),
        "chooser_update_missing": np.isnan(oc).sum(),
        "disconnected_update_missing": np.isnan(od).sum(),
        "kind_draw_chooser_update_missing": np.isnan(oc[kind]).sum(),
        "claimed_win_chooser_update_missing": np.isnan(oc[win]).sum(),
    }.items():
        target.count(key, value)
    # Labels exactly match the manuscript's inclusive integer centipawn boundaries.
    state = np.select([cp <= -300, cp < -100, cp <= 100, cp < 300],
                      ["clearly_worse", "modestly_worse", "roughly_equal", "better"],
                      default="clearly_better")
    dimensions = {
        "speed": s["api_speed"],
        "board_state": state,
        "competitive": np.where(fair, "competitive", "noncompetitive"),
        "ply_band": categorize(v["ply_count"], [2, 10, 20, 40, 80],
            ["up_to_2", "3_to_10", "11_to_20", "21_to_40", "41_to_80", "81_plus"], right=True),
        "chooser_rating_band": categorize(v["chooser_elo"], [1600, 2000, 2400],
            ["below_1600", "1600_to_1999", "2000_to_2399", "2400_plus"]),
        "chooser_rd_band": categorize(v["chooser_pre_rd_v2"], [50, 75, 110, 200],
            ["at_most_50", "50_to_75", "75_to_110", "110_to_200", "above_200"], right=True),
        "opponent_rd_band": categorize(v["disconnected_pre_rd_v2"], [50, 75, 110, 200],
            ["at_most_50", "50_to_75", "75_to_110", "110_to_200", "above_200"], right=True),
        "both_rd_at_most_110": np.where((v["chooser_pre_rd_v2"] <= 110) &
            (v["disconnected_pre_rd_v2"] <= 110), "yes", "no"),
        "draw_payoff_sign": np.where(rg < 0, "negative", np.where(rg > 0, "positive", "zero")),
        "absolute_draw_payoff_band": categorize(np.abs(rg), [0.25, 0.5, 1, 2, 5, 10, 25],
            ["below_0_25", "0_25_to_below_0_5", "0_5_to_below_1", "1_to_below_2",
             "2_to_below_5", "5_to_below_10", "10_to_below_25", "25_plus"]),
        "local_payoff_sample": np.where(fair & (np.abs(rg) < 1),
                                        "competitive_and_abs_payoff_below_1", "other"),
    }
    views = [
        ("chooser_kind_draw", kind, oc, rg),
        ("chooser_claimed_win", win, oc, rc),
        ("chooser_all_draws", draw, oc, rg),
        ("chooser_draw_failing_material", draw & ~kind, oc, rg),
        ("chooser_loss", loss, oc, pc),
        ("disconnected_draw", draw, od, pd),
        ("disconnected_loss", win, od, pd),
        ("disconnected_win", loss, od, pd),
    ]
    for series, mask, observed, predicted in views:
        if not mask.any():
            continue
        target.add(series, "overall", "all", observed[mask], predicted[mask])
        target.add(series, "month", month, observed[mask], predicted[mask])
        chosen_dimensions = dimensions if series in PRIMARY else {"speed": s["api_speed"]}
        for dimension, levels in chosen_dimensions.items():
            for level in np.unique(levels[mask]):
                selected = mask & (levels == level)
                target.add(series, dimension, level, observed[selected], predicted[selected])
                if dimension == "speed" and series in PRIMARY:
                    target.add(series, "month_by_speed", f"{month}|{level}",
                               observed[selected], predicted[selected])


def process_month(job):
    pa.set_cpu_count(1)
    pa.set_io_thread_count(1)
    start = time.monotonic()
    path, month = Path(job["path"]), job["month"]
    stat_before = (path.stat().st_size, path.stat().st_mtime_ns)
    aggregate = Aggregate()
    parquet = pq.ParquetFile(path)
    for batch in parquet.iter_batches(batch_size=job["batch_rows"], columns=READ_COLUMNS,
                                      use_threads=False):
        consume(batch, month, aggregate)
    require(aggregate.counts["rows"] == job["rows"], f"Row conservation failed: {month}")
    require((path.stat().st_size, path.stat().st_mtime_ns) == stat_before,
            f"Input file changed during scan: {month}")
    require(stat_before[0] == job["size_bytes"], f"Input size changed before scan: {month}")
    return {"month": month, "input_sha256": job["expected_sha256"],
            "analysis_fingerprint": job["analysis_fingerprint"],
            "elapsed_seconds": time.monotonic() - start, **aggregate.export()}


def write_checkpoint(path, result):
    authority.atomic_json(path, result)
    authority.atomic_text(Path(str(path) + ".sha256"), authority.sha256_file(path) + "\n")


def read_checkpoint(path, fingerprint, input_sha256):
    side = Path(str(path) + ".sha256")
    if not path.is_file() or not side.is_file():
        return None
    require(authority.sha256_file(path) == side.read_text().strip(),
            f"Checkpoint checksum failed: {path.name}")
    data = authority.load_json(path)
    require(data["analysis_fingerprint"] == fingerprint, "Checkpoint belongs to a different analysis")
    require(data["input_sha256"] == input_sha256, "Checkpoint belongs to different input bytes")
    return data


def write_csv(path, rows):
    if not rows:
        raise RuntimeError(f"Refusing empty result table: {path.name}")
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    authority.atomic_text(path, out.getvalue())


def write_parquet(path, rows):
    temporary = path.with_suffix(".tmp.parquet")
    pq.write_table(pa.Table.from_pylist(rows), temporary, compression="zstd")
    os.replace(temporary, path)


def package_hashes():
    manifest = ROOT / "PACKAGE_MANIFEST.sha256"
    require(manifest.is_file(), "Package manifest is missing")
    records = {}
    for line in manifest.read_text().splitlines():
        expected, name = line.split("  ", 1)
        path = (ROOT / name).resolve()
        require(path.is_relative_to(ROOT), "Unsafe package-manifest path")
        require(path.is_file() and authority.sha256_file(path) == expected,
                f"Package checksum failed: {name}")
        records[name] = expected
    require("validate_ratings.py" in records, "Runner absent from package manifest")
    return records


def make_report(result_dir, aggregate, auth, fingerprint, runtime, sources, input_records):
    rows = aggregate.table()
    primary = [r for r in rows if r["series"] in PRIMARY and r["dimension"] == "overall"]
    require(len(primary) == 2 and all(r["observed_rows"] > 1 for r in primary),
            "Cannot validate both primary arms: too few observed updates")
    for key, expected in EXPECTED.items():
        require(aggregate.counts.get(key) == expected, f"Current-sample count mismatch: {key}")
    require(sum(aggregate.counts[k] for k in ("actual_draws", "chooser_claimed_wins", "chooser_losses"))
            == EXPECTED["rows"], "Outcome counts fail to partition current sample")
    require(aggregate.counts["actual_draws"] == aggregate.counts["kind_draws"] +
            aggregate.counts["draws_failing_material_screen"], "Draw partition mismatch")
    write_csv(result_dir / "validation_all_groups.csv", rows)
    write_parquet(result_dir / "validation_all_groups.parquet", rows)
    write_csv(result_dir / "validation_primary.csv", primary)
    write_parquet(result_dir / "validation_primary.parquet", primary)
    for dimension in sorted({r["dimension"] for r in rows} - {"overall"}):
        write_csv(result_dir / f"validation_by_{dimension}.csv",
                  [r for r in rows if r["dimension"] == dimension])
    authority.atomic_json(result_dir / "OUTCOME_AND_MISSINGNESS_COUNTS.json", aggregate.counts)
    authority.atomic_json(result_dir / "INPUT_MANIFEST.json", input_records)
    authority.atomic_json(result_dir / "METHOD.json", {
        "version": VERSION, "unit_primary": "one chooser side per current-sample game",
        "primary_observed": "white_rating_diff_pgn or black_rating_diff_pgn selected by chooser_color",
        "primary_predicted": {"chooser_kind_draw": "chooser_draw_payoff_v2",
                              "chooser_claimed_win": "chooser_win_payoff_v2"},
        "supplemental_predictions": "color-specific realized_pred_ratingdiff_v2 selected by role",
        "missing_updates": "excluded only from observed/predicted metrics; retained in coverage",
        "one_sided_missing": "each player side evaluated independently",
        "rounding": "continuous prediction compared with recorded integer difference; no fitted rounding correction",
        "coefficient_fitting": False, "api_requests": 0, "rating_replay_recomputed": False,
        "counterfactual_warning": "Only the realized outcome is observed. The unchosen payoff and win premium are not directly validated.",
        "reconstruction_convention": "existing anchored_timeaware_glicko2_novol_noreg fields; no new regulator or rounding model",
        "subgroups": "one diagnostic dimension at a time; rows across subgroup tables must not be summed",
        "primary_series_overlap_with_supplement": True,
        "uncertainty": "Descriptive census error metrics; no iid confidence intervals or accuracy certification",
        "local_payoff_sample": "evaluation >= -100 and absolute chooser_draw_payoff_v2 < 1; all game stages; no regression-cell filter",
        "sample_fingerprint": auth["fingerprint"], "analysis_fingerprint": fingerprint,
        "source_code_hashes": sources, "runtime": runtime,
    })
    def fmt(value, places=4):
        return "undefined (zero variance)" if value is None else f"{value:.{places}f}"
    text = ["# Rating reconstruction validation on the current pool sample", "",
            f"Computed: {authority.utc_now()}", "",
            "Sample: 41,534,331 pool games with observed predecessor nonadjacency, November 2023 through October 2025.",
            "The input files were authenticated against the frozen sample report before estimation.", "",
            "| Realized chooser outcome | Eligible games | Observed updates | Coverage (%) | Correlation | MAE | RMSE | Bias |",
            "|---|---:|---:|---:|---:|---:|---:|---:|"]
    names = {"chooser_kind_draw": "Kind draw", "chooser_claimed_win": "Claimed win"}
    for r in primary:
        text.append(f"| {names[r['series']]} | {r['eligible_rows']:,} | {r['observed_rows']:,} | "
                    f"{fmt(r['coverage_percent'], 2)} | {fmt(r['correlation'])} | {fmt(r['mae'])} | "
                    f"{fmt(r['rmse'])} | {fmt(r['bias_pred_minus_observed'])} |")
    text += ["", "Errors are in rating points. Bias is predicted minus observed.", "",
             f"There are {aggregate.counts['draws_failing_material_screen']:,} raw draws failing the material screen and "
             f"{aggregate.counts['chooser_losses']:,} chooser losses. These are reported separately.",
             f"Both observed update fields are missing in {aggregate.counts['both_updates_missing']:,} games; "
             f"exactly one is missing in {aggregate.counts['one_update_missing']:,}.", "",
             "## Interpretation", "",
             "This checks the stored reconstruction against an independently recorded outcome for the same games. "
             "It does not validate the unchosen outcome or identify a causal price effect. Missing observed changes are not treated as zero. "
             "The recorded changes are integers; the predictions are continuous. The reconstruction's existing omission of a post-update "
             "regulator is retained, so this is an accuracy check of the paper's existing fields, not a replacement production formula.", "",
             "Inspect monthly, speed, rating-uncertainty and local-payoff tables before deciding which accuracy claims belong in the paper. "
             "A completion receipt certifies the computation and sample checks, not that predictive accuracy meets a chosen standard.", "",
             "The primary table's kind-draw arm uses only outcome_kind_draw=1. chooser_all_draws is a supplement and includes it. "
             "Disconnected-player rows are separate supplemental validation; they must not be added to chooser rows as independent games."]
    authority.atomic_text(result_dir / "SUMMARY.md", "\n".join(text) + "\n")
    manifest_lines = []
    for p in sorted(result_dir.iterdir()):
        if p.is_file() and p.name not in ("REPORT_FILE_HASHES.tsv", "_SUCCESS.json"):
            manifest_lines.append(f"{authority.sha256_file(p)}\t{p.stat().st_size}\t{p.name}")
    authority.atomic_text(result_dir / "REPORT_FILE_HASHES.tsv", "sha256\tbytes\tfile\n" + "\n".join(manifest_lines) + "\n")
    authority.atomic_json(result_dir / "_SUCCESS.json", {
        "status": "POOL_RATING_VALIDATION_COMPUTED_OK", "version": VERSION,
        "sample_fingerprint": auth["fingerprint"], "analysis_fingerprint": fingerprint,
        "rows": EXPECTED["rows"], "months": 24, "api_requests": 0,
        "rating_replay_recomputed": False, "created_at_utc": authority.utc_now(),
        "report_manifest_sha256": authority.sha256_file(result_dir / "REPORT_FILE_HASHES.tsv"),
        "meaning": "Computation completed; accuracy requires scientific review",
    })
    return primary


def validate_finished_report(result_dir):
    success = authority.load_json(result_dir / "_SUCCESS.json")
    manifest = result_dir / "REPORT_FILE_HASHES.tsv"
    require(authority.sha256_file(manifest) == success["report_manifest_sha256"], "Report manifest changed")
    with manifest.open(newline="") as stream:
        for row in csv.DictReader(stream, delimiter="\t"):
            p = result_dir / row["file"]
            require(p.is_file() and p.stat().st_size == int(row["bytes"]) and
                    authority.sha256_file(p) == row["sha256"], f"Report file changed: {p.name}")


def deliver(result_dir, transfer_root, fingerprint):
    validate_finished_report(result_dir)
    transfer_root.mkdir(parents=True, exist_ok=True)
    name = f"POOL_RATING_VALIDATION_RESULTS_v100_{fingerprint[:16]}.zip"
    dest = transfer_root / name
    temporary = transfer_root / (name + ".tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(result_dir.iterdir()):
            if p.is_file():
                z.write(p, f"POOL_RATING_VALIDATION_RESULTS/{p.name}")
    with zipfile.ZipFile(temporary) as z:
        require(z.testzip() is None, "Report ZIP CRC failed")
    os.replace(temporary, dest)
    authority.atomic_text(Path(str(dest) + ".sha256"), authority.sha256_file(dest) + "  " + dest.name + "\n")
    return dest


def execute(args):
    sources = package_hashes()
    runtime = {"python": platform.python_version(), "numpy": np.__version__, "pyarrow": pa.__version__,
               "platform": platform.platform()}
    sample_root = args.sample_root or args.project_root / "derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE"
    auth = authority.authenticate_sample(sample_root, verify_hashes=True, hash_workers=args.hash_workers)
    missing = sorted(set(READ_COLUMNS) - set(auth["schema"]))
    require(not missing, f"Required panel columns missing: {missing}")
    core = {"version": VERSION, "sample_fingerprint": auth["fingerprint"],
            "source_code_hashes": sources, "numpy": np.__version__, "pyarrow": pa.__version__,
            "python": platform.python_version(), "batch_rows": args.batch_rows}
    fingerprint = hashlib.sha256(authority.canonical_json(core).encode()).hexdigest()
    base = args.output_root or args.project_root / "output/pool_rating_validation_v100"
    run = base / f"run_{fingerprint[:16]}"
    run.mkdir(parents=True, exist_ok=True)
    result_dir = run / "report"
    result_dir.mkdir(exist_ok=True)
    checkpoint_dir = run / "checkpoints"
    checkpoint_dir.mkdir(exist_ok=True)
    log(f"RUN_DIRECTORY {run}")
    # POSIX advisory lock is released automatically on interruption; never delete another process's lock.
    import fcntl
    lock = (run / "RUN.lock").open("a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError(f"This validation run is already active: {run}")
    authority.atomic_json(run / "RUN_CONFIG.json", {**core, "runtime": runtime,
        "analysis_fingerprint": fingerprint, "workers": args.workers, "hash_workers": args.hash_workers})
    input_records = [{"month": r["month"], "relative_path": f"panel/month={r['month']}/analysis_panel.parquet",
                      "rows": r["rows"], "bytes": r["size_bytes"], "sha256": r["actual_sha256"]}
                     for r in auth["month_records"]]
    before = {r["month"]: (r["path"].stat().st_size, r["path"].stat().st_mtime_ns)
              for r in auth["month_records"]}
    try:
        if (result_dir / "_SUCCESS.json").is_file():
            success = authority.load_json(result_dir / "_SUCCESS.json")
            require(success["analysis_fingerprint"] == fingerprint, "Completed run signature mismatch")
            dest = deliver(result_dir, args.transfer_root, fingerprint)
            log(f"ALREADY_COMPUTED_OK {dest}")
            return 0
        completed = {}
        jobs = []
        for row in auth["month_records"]:
            cp = checkpoint_dir / f"{row['month']}.json"
            saved = read_checkpoint(cp, fingerprint, row["expected_sha256"])
            if saved:
                require(saved["counts"]["rows"] == row["rows"], "Checkpoint row count mismatch")
                completed[row["month"]] = saved
                log(f"REUSED_MONTH {row['month']}")
            else:
                jobs.append({**row, "path": str(row["path"]), "analysis_fingerprint": fingerprint,
                             "batch_rows": args.batch_rows})
        log(f"SCAN months_remaining={len(jobs)} workers={args.workers} batch_rows={args.batch_rows}")
        with futures.ProcessPoolExecutor(max_workers=args.workers,
                mp_context=multiprocessing.get_context("spawn")) as pool:
            active = {pool.submit(process_month, job): job["month"] for job in jobs}
            for future in futures.as_completed(active):
                result = future.result()
                month = result["month"]
                write_checkpoint(checkpoint_dir / f"{month}.json", result)
                completed[month] = result
                log(f"MONTH_OK {month} rows={result['counts']['rows']:,} completed={len(completed)}/24 "
                    f"seconds={result['elapsed_seconds']:.1f}")
        require(len(completed) == 24, "Incomplete monthly computation")
        total = Aggregate()
        # Merge in chronological order, independent of worker completion order.
        for month in sorted(completed):
            total.merge(Aggregate.restore(completed[month]))
        for row in auth["month_records"]:
            p = row["path"]
            require((p.stat().st_size, p.stat().st_mtime_ns) == before[row["month"]],
                    f"Input changed after authentication: {row['month']}")
        primary = make_report(result_dir, total, auth, fingerprint, runtime, sources, input_records)
        dest = deliver(result_dir, args.transfer_root, fingerprint)
        for row in primary:
            log(f"{row['series']}: observed={row['observed_rows']:,} correlation={row['correlation']} "
                f"MAE={row['mae']:.6f} RMSE={row['rmse']:.6f}")
        authority.atomic_json(run / "RUN_STATUS.json", {"status": "COMPLETED", "archive": str(dest)})
        log(f"POOL_RATING_VALIDATION_COMPUTED_OK {dest}")
        return 0
    except BaseException as exc:
        authority.atomic_json(run / "RUN_STATUS.json", {"status": "INTERRUPTED" if isinstance(exc, KeyboardInterrupt)
            else "FAILED", "message": str(exc), "created_at_utc": authority.utc_now()})
        raise
    finally:
        lock.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project-root", type=Path, default=Path("/Volumes/XT_Pro/lichess_kindness"))
    p.add_argument("--sample-root", type=Path)
    p.add_argument("--output-root", type=Path)
    p.add_argument("--transfer-root", type=Path, default=Path.home() / "Desktop/Lichess_Desktop")
    p.add_argument("--workers", type=int, default=10)
    p.add_argument("--hash-workers", type=int, default=2)
    p.add_argument("--batch-rows", type=int, default=65536)
    a = p.parse_args()
    require(1 <= a.workers <= 10 and 1 <= a.hash_workers <= 10, "Worker counts must be between 1 and 10")
    require(1024 <= a.batch_rows <= 262144, "batch-rows must be 1024..262144")
    return execute(a)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("INTERRUPTED: rerun the same launcher to resume completed months")
        sys.exit(130)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
