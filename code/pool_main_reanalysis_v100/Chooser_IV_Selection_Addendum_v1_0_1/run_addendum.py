#!/usr/bin/env python3
"""Exact active-given-time-forfeit-candidate selection addendum.

This reads only the authenticated aggregate-analysis comparison frame created by
Chooser IV main rebuild v1.0.1. It does not rebuild histories or access a network.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
import platform
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq


VERSION = "1.0.1"
DAY = 86_400_000
PKG = Path(__file__).resolve().parent
DEFAULT_PROJECT = Path("/Volumes/XT_Pro/lichess_kindness")
SOURCE_CONFIG_SHA256 = "ccbc4331487512b8b7ce41b620a8699ed056f6961a25b49c65ad52c2c0da013c"
SOURCE_RUN = "ccbc43314875"
SOURCE_ROWS = 1_661_563
SOURCE_COMPARISON_BYTES = 173_517_733
SOURCE_COMPARISON_SHA256 = "8bc92d15b9a63e4cc1191ab8342aedd918a36bd341d9a8ddc427e93bb9f156ae"
CURRENT_IV_SD = 0.059411690344000595
SPECS = (
    {"name": "primary", "lag": 7, "floor": 5},
    {"name": "lag30", "lag": 30, "floor": 5},
    {"name": "floor1", "lag": 7, "floor": 1},
    {"name": "floor10", "lag": 7, "floor": 10},
)


def log(message):
    stamp = dt.datetime.now(dt.timezone.utc).strftime("[%Y-%m-%d %H:%M:%SZ]")
    print(stamp + " " + message, flush=True)


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [clean(v) for v in value]
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def write_json(path, value):
    Path(path).write_text(json.dumps(clean(value), sort_keys=True, indent=2, allow_nan=False) + "\n")


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def config_sha(value):
    payload = json.dumps(clean(value), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def factor(*columns):
    if not columns:
        raise ValueError("No factor columns")
    n = len(columns[0])
    structured = np.empty(n, dtype=[(f"v{k}", "<i8") for k in range(len(columns))])
    for k, values in enumerate(columns):
        if len(values) != n:
            raise ValueError("Unequal factor lengths")
        structured[f"v{k}"] = values
    keys, codes = np.unique(structured, return_inverse=True)
    return keys, codes.astype(np.int64)


def absorb(matrix, groups, tolerance=1e-10, max_iterations=1000):
    matrix = np.asarray(matrix, float).copy()
    if matrix.ndim != 2 or not np.isfinite(matrix).all():
        raise ValueError("Invalid absorb matrix")
    codes = [np.unique(group, return_inverse=True)[1] for group in groups]
    counts = [np.bincount(group).astype(float) for group in codes]
    scale = max(1.0, float(np.max(np.abs(matrix))))
    for iteration in range(max_iterations):
        biggest = 0.0
        for group, count in zip(codes, counts):
            for column in range(matrix.shape[1]):
                mean = np.bincount(group, weights=matrix[:, column], minlength=len(count)) / count
                biggest = max(biggest, float(np.max(np.abs(mean))))
                matrix[:, column] -= mean[group]
        if biggest <= tolerance * scale:
            return matrix, iteration + 1
    raise RuntimeError(f"FE absorption did not converge in {max_iterations} iterations")


def partial_out(matrix, groups, control_count):
    matrix, iterations = absorb(matrix, groups)
    if control_count:
        controls, values = matrix[:, :control_count], matrix[:, control_count:]
        gram = controls.T @ controls
        eigenvalues, vectors = np.linalg.eigh(gram)
        cutoff = max(float(np.max(eigenvalues)), 1.0) * 1e-11
        keep = eigenvalues > cutoff
        inverse = (vectors[:, keep] / eigenvalues[keep]) @ vectors[:, keep].T
        values = values - controls @ (inverse @ (controls.T @ values))
        rank = int(keep.sum())
    else:
        values, rank = matrix, 0
    return values, {"absorb_iterations": iterations, "continuous_control_rank": rank}


def history_supported(data, lag, floor):
    return (
        (data[f"n_{lag}d"] >= floor)
        & np.isfinite(data[f"expected_{lag}d"])
        & np.isfinite(data[f"adjusted_{lag}d"])
    )


def residualize(data, mask, lag, outcomes):
    names = (
        "recipient_rating",
        "opponent_rating",
        "month_code",
        "tc_base_s",
        "tc_inc_s",
        "archive_start_ms",
        f"n_{lag}d",
        f"counterparts_{lag}d",
        f"expected_{lag}d",
        f"adjusted_{lag}d",
    )
    take = {name: np.asarray(data[name])[mask] for name in names}
    controls = []
    control_names = []

    def add(name, values):
        values = np.asarray(values, float)
        if not np.isfinite(values).all():
            raise RuntimeError("Unavailable model control: " + name)
        sd = float(values.std())
        controls.append((values - values.mean()) / (sd if sd > 1e-12 else 1.0))
        control_names.append(name)

    recipient_rating = take["recipient_rating"]
    opponent_rating = take["opponent_rating"]
    gap = (opponent_rating - recipient_rating) / 100.0
    add("recipient_rating", recipient_rating)
    add("rating_gap", gap)
    add("rating_gap_square", gap * gap)
    add("abs_rating_gap", abs(gap))
    add("log_opponent_prior_decisions", np.log1p(take[f"n_{lag}d"]))
    add("log_opponent_prior_counterparts", np.log1p(take[f"counterparts_{lag}d"]))
    add("opponent_history_expected_rate", take[f"expected_{lag}d"])

    _, cells = factor(
        take["month_code"],
        take["tc_base_s"],
        take["tc_inc_s"],
        np.floor((recipient_rating + opponent_rating) / 200).astype(np.int64),
    )
    dates = take["archive_start_ms"] // DAY
    hours = (take["archive_start_ms"] // 3_600_000) % 168
    matrix = np.column_stack(
        controls
        + [take[f"adjusted_{lag}d"]]
        + [np.asarray(outcome, float)[mask] for outcome in outcomes]
    )
    result, diagnostics = partial_out(matrix, [cells, dates, hours], len(controls))
    return result, {
        "assignment_cells": len(np.unique(cells)),
        "continuous_controls": control_names,
        "controls": "pregame_export_W_common",
        "unavailable_controls": ["pregame_RD", "all_game_prior_30d_volume", "internal_conduct_category"],
        **diagnostics,
    }


def covariance_codes(recipient, opponent, date):
    recipient = np.asarray(recipient, np.int64)
    opponent = np.asarray(opponent, np.int64)
    date = np.asarray(date, np.int64)
    if np.any(recipient == opponent):
        raise RuntimeError("Self pair in covariance calculation")
    low, high = np.minimum(recipient, opponent), np.maximum(recipient, opponent)
    return {
        "accounts": np.unique(np.r_[recipient, opponent], return_inverse=True)[1],
        "pairs": factor(low, high)[1],
        "dates": np.unique(date, return_inverse=True)[1],
        "account_dates": factor(np.r_[recipient, opponent], np.r_[date, date])[1],
        "pair_dates": factor(low, high, date)[1],
    }


def covariance_meat(score, codes, include_date):
    def squared_sums(values, key):
        sums = np.bincount(codes[key], weights=values)
        return float(sums @ sums)

    doubled = np.r_[score, score]
    meat = squared_sums(doubled, "accounts") - squared_sums(score, "pairs")
    if include_date:
        meat += (
            squared_sums(score, "dates")
            - squared_sums(doubled, "account_dates")
            + squared_sums(score, "pair_dates")
        )
    return meat


def fit(y, score, codes, include_date, outcome_mean):
    if not np.isfinite(y).all() or not np.isfinite(score).all():
        raise RuntimeError("Nonfinite regression residuals")
    denominator = float(score @ score)
    native_sd = math.sqrt(denominator / len(score))
    if native_sd < 1e-8:
        return {"supported": False, "reason": "NO_RESIDUAL_SCORE_VARIATION"}
    coefficient = float(score @ y) / denominator
    residual = y - coefficient * score
    variance = covariance_meat(score * residual, codes, include_date) / denominator**2
    scale = 100.0 * CURRENT_IV_SD
    answer = {
        "coefficient_per_unit_score": coefficient,
        "coefficient_pp_per_current_IV_SD": scale * coefficient,
        "coefficient_pp_per_native_SD": 100.0 * native_sd * coefficient,
        "native_residual_score_sd": native_sd,
        "current_IV_score_sd": CURRENT_IV_SD,
        "outcome_mean": outcome_mean,
        "outcome_mean_pp": 100.0 * outcome_mean,
        "variance_correction": "CR0",
        "inference": "normal_approximation_conditional_on_recorded_history",
        "historical_scores_treated_as_fixed": True,
        "causal_identification_certified": False,
    }
    if not math.isfinite(variance) or variance <= 0:
        return {**answer, "supported": False, "reason": "NONPOSITIVE_COVARIANCE_NOT_REPAIRED"}
    se = math.sqrt(variance)
    critical = 1.959963984540054
    answer.update(
        supported=True,
        standard_error_pp_per_current_IV_SD=scale * se,
        ci95_low_pp_per_current_IV_SD=scale * (coefficient - critical * se),
        ci95_high_pp_per_current_IV_SD=scale * (coefficient + critical * se),
        p_value_asymptotic=math.erfc(abs(coefficient / se) / math.sqrt(2.0)),
    )
    return answer


def load_data(comparison_path):
    columns = [
        "recipient_id",
        "opponent_id",
        "recipient_rating",
        "opponent_rating",
        "month_code",
        "tc_base_s",
        "tc_inc_s",
        "archive_start_ms",
        "eligible_main",
        "active_timeout",
        "passive_outoftime",
    ]
    for lag in (7, 30):
        columns.extend(
            [f"n_{lag}d", f"counterparts_{lag}d", f"expected_{lag}d", f"adjusted_{lag}d"]
        )
    table = pq.ParquetFile(comparison_path).read(columns=columns, use_threads=False)
    if len(table) != SOURCE_ROWS:
        raise RuntimeError(f"Wrong comparison row count: {len(table)}")
    data = {}
    for name in table.column_names:
        column = table[name].combine_chunks()
        data[name] = column.to_numpy(zero_copy_only=False)
    return data


def compare_reference(specification, outcome, clustering, result, authority):
    key = "|".join((specification, outcome, clustering))
    expected = authority["reference_estimates"].get(key)
    if expected is None:
        raise RuntimeError("Missing reproduction authority: " + key)
    if result.get("supported") is not True:
        raise RuntimeError("Existing result did not reproduce as supported: " + key)
    if int(result["n"]) != int(expected["n"]):
        raise RuntimeError("Existing sample size did not reproduce: " + key)
    checks = {}
    for name in (
        "outcome_mean",
        "coefficient_per_unit_score",
        "coefficient_pp_per_current_IV_SD",
        "standard_error_pp_per_current_IV_SD",
        "native_residual_score_sd",
    ):
        actual = float(result[name])
        target = float(expected[name])
        error = abs(actual - target)
        tolerance = 5e-11 * max(1.0, abs(target))
        checks[name] = {"actual": actual, "expected": target, "absolute_error": error}
        if error > tolerance:
            raise RuntimeError(f"Existing estimate failed reproduction for {key}: {name}")
    return {"key": key, "checks": checks}


def estimate(data, authority):
    eligible = data["eligible_main"].astype(bool)
    active = data["active_timeout"].astype(bool)
    passive = data["passive_outoftime"].astype(bool)
    overlap = active & passive
    if np.any(overlap):
        raise RuntimeError("active_timeout and passive_outoftime overlap; candidate definition is not exclusive")
    candidate = active | passive
    rows = []
    reproductions = []
    flows = []

    for spec in SPECS:
        log("Estimating " + spec["name"])
        supported = history_supported(data, spec["lag"], spec["floor"])
        base_mask = eligible & supported
        conditional_mask = base_mask & candidate
        n_base = int(base_mask.sum())
        n_candidate = int(conditional_mask.sum())
        n_active = int((base_mask & active).sum())
        n_passive = int((base_mask & passive).sum())
        if n_candidate != n_active + n_passive:
            raise RuntimeError("Candidate decomposition does not add exactly")
        if min(n_active, n_passive) < 10:
            raise RuntimeError("Insufficient active/passive support")
        flows.append(
            {
                "specification": spec["name"],
                "lag": spec["lag"],
                "floor": spec["floor"],
                "eligible_history_supported_n": n_base,
                "timeforfeit_candidate_n": n_candidate,
                "active_timeout_n": n_active,
                "passive_outoftime_n": n_passive,
                "candidate_share": n_candidate / n_base,
                "active_given_candidate_share": n_active / n_candidate,
            }
        )

        full_residuals, full_diagnostics = residualize(
            data, base_mask, spec["lag"], [active, passive, candidate]
        )
        full_codes = covariance_codes(
            data["recipient_id"][base_mask],
            data["opponent_id"][base_mask],
            data["archive_start_ms"][base_mask] // DAY,
        )
        for outcome_index, outcome_name in enumerate(
            ("active_timeout", "passive_outoftime", "timeforfeit_candidate")
        ):
            outcome_values = (active, passive, candidate)[outcome_index]
            mean = float(outcome_values[base_mask].mean())
            for include_date in (False, True):
                clustering = "shared_account_OR_date_CR0" if include_date else "shared_account_CR0"
                fit_result = fit(
                    full_residuals[:, outcome_index + 1],
                    full_residuals[:, 0],
                    full_codes,
                    include_date,
                    mean,
                )
                row = {
                    "family": "selection_decomposition_posthoc",
                    "specification": spec["name"],
                    "lag": spec["lag"],
                    "floor": spec["floor"],
                    "sample": "eligible_main_and_history_supported",
                    "n": n_base,
                    "outcome": outcome_name,
                    "positive": int(outcome_values[base_mask].sum()),
                    "clustering": clustering,
                    "estimand": "probability_point_change_per_current_primary_IV_score_SD",
                    **full_diagnostics,
                    **fit_result,
                }
                if outcome_name in ("active_timeout", "passive_outoftime"):
                    reproductions.append(
                        compare_reference(spec["name"], outcome_name, clustering, row, authority)
                    )
                else:
                    rows.append(row)

        conditional_residuals, conditional_diagnostics = residualize(
            data, conditional_mask, spec["lag"], [active]
        )
        conditional_codes = covariance_codes(
            data["recipient_id"][conditional_mask],
            data["opponent_id"][conditional_mask],
            data["archive_start_ms"][conditional_mask] // DAY,
        )
        mean = float(active[conditional_mask].mean())
        for include_date in (False, True):
            clustering = "shared_account_OR_date_CR0" if include_date else "shared_account_CR0"
            fit_result = fit(
                conditional_residuals[:, 1],
                conditional_residuals[:, 0],
                conditional_codes,
                include_date,
                mean,
            )
            rows.append(
                {
                    "family": "selection_decomposition_posthoc",
                    "specification": spec["name"],
                    "lag": spec["lag"],
                    "floor": spec["floor"],
                    "sample": "eligible_main_history_supported_and_timeforfeit_candidate",
                    "n": n_candidate,
                    "outcome": "active_given_timeforfeit_candidate",
                    "positive": n_active,
                    "clustering": clustering,
                    "estimand": "probability_point_change_per_current_primary_IV_score_SD",
                    **conditional_diagnostics,
                    **fit_result,
                }
            )

    return rows, flows, reproductions


def write_csv(path, rows):
    names = list(dict.fromkeys(key for row in rows for key in row))
    with Path(path).open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, separators=(",", ":"))
                    if isinstance(value, (list, dict))
                    else value
                    for key, value in clean(row).items()
                }
            )


def verify_source(project_root):
    authority = json.loads((PKG / "evidence/source_authority.json").read_text())
    source_root = (
        project_root
        / "derived/replication/chooser_iv_main_rebuild_v100_PRIVATE"
        / SOURCE_RUN
    )
    config_path = source_root / "config.json"
    done_path = source_root / "analysis/_DONE.json"
    comparison_path = source_root / "analysis/comparison.parquet"
    for path in (config_path, done_path, comparison_path):
        if not path.is_file():
            raise RuntimeError("Missing authenticated source input: " + str(path))
    source_config = json.loads(config_path.read_text())
    if config_sha(source_config) != SOURCE_CONFIG_SHA256:
        raise RuntimeError("Source configuration fingerprint changed")
    done = json.loads(done_path.read_text())
    if done.get("config_sha256") != SOURCE_CONFIG_SHA256:
        raise RuntimeError("Source analysis receipt has the wrong configuration")
    records = [item for item in done.get("files", []) if item.get("path") == "comparison.parquet"]
    if len(records) != 1:
        raise RuntimeError("Source analysis receipt lacks one comparison.parquet record")
    record = records[0]
    if int(record.get("bytes", -1)) != SOURCE_COMPARISON_BYTES or record.get("sha256") != SOURCE_COMPARISON_SHA256:
        raise RuntimeError("Source analysis receipt does not match the returned report authority")
    if comparison_path.stat().st_size != SOURCE_COMPARISON_BYTES:
        raise RuntimeError("Source comparison.parquet size changed")
    log("Hashing the 174 MB source comparison frame")
    if sha256(comparison_path) != SOURCE_COMPARISON_SHA256:
        raise RuntimeError("Source comparison.parquet checksum changed")
    return source_root, comparison_path, authority


def make_report(public_dir, rows, flows, reproductions, configuration, verification):
    # tempfile.mkdtemp() creates the staging directory before handing it to us.
    # exist_ok=True also makes this helper safe to exercise directly in tests.
    public_dir.mkdir(parents=True, exist_ok=True)
    primary = [
        row
        for row in rows
        if row["specification"] == "primary"
        and row["clustering"] == "shared_account_OR_date_CR0"
    ]
    summary = {
        "status": "CHOOSER_IV_SELECTION_ADDENDUM_COMPLETE",
        "version": VERSION,
        "config_sha256": config_sha(configuration),
        "source_IV_config_sha256": SOURCE_CONFIG_SHA256,
        "source_report_zip_sha256": verification["source_report_zip_sha256"],
        "existing_selection_estimates_reproduced": True,
        "reproduction_checks": len(reproductions),
        "active_and_passive_mutually_exclusive": True,
        "candidate_definition": "active_timeout OR passive_outoftime",
        "primary": primary,
        "causal_identification_certified": False,
        "interpretation": "Post-hoc selection decomposition. The candidate-incidence model is fit on the full eligible comparison sample. The active-given-candidate model is refit within time-forfeit candidates and is descriptive, not a causal effect.",
        "network_requests": 0,
    }
    write_json(public_dir / "summary.json", summary)
    write_json(public_dir / "results.json", rows)
    write_csv(public_dir / "estimates.csv", rows)
    write_csv(public_dir / "sample_flow.csv", flows)
    write_json(public_dir / "source_verification.json", verification)
    write_json(public_dir / "reproduction_checks.json", reproductions)
    write_json(public_dir / "config.json", configuration)
    (public_dir / "REPORT.md").write_text(
        "# Chooser-IV selection addendum\n\n"
        "This report supplies the previously omitted active-given-time-forfeit-candidate check. "
        "It also estimates whether the historical chooser score predicts entry into the candidate set itself.\n\n"
        "The time-forfeit candidate set is exactly `active_timeout OR passive_outoftime`; the runner "
        "requires those categories to be mutually exclusive. Candidate incidence is estimated in the "
        "full eligible, history-supported comparison frame. Active-given-candidate is separately "
        "residualized and estimated only within candidates. Both use the same pregame controls, fixed "
        "effects, score definitions, current-IV scaling, and shared-account/date CR0 covariance as the "
        "returned main IV report.\n\n"
        "This is a requested post-hoc selection diagnostic. It is not part of a confirmatory family and "
        "does not certify exclusion, random assignment, or a causal effect. Read `summary.json`, "
        "`estimates.csv`, and `sample_flow.csv` together.\n"
    )
    listed = []
    for path in sorted(public_dir.iterdir()):
        if path.is_file():
            listed.append({"file": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)})
    with (public_dir / "REPORT_FILE_HASHES.tsv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("sha256", "bytes", "file"), delimiter="\t")
        writer.writeheader()
        writer.writerows(listed)
    listed.append(
        {
            "file": "REPORT_FILE_HASHES.tsv",
            "bytes": (public_dir / "REPORT_FILE_HASHES.tsv").stat().st_size,
            "sha256": sha256(public_dir / "REPORT_FILE_HASHES.tsv"),
        }
    )
    write_json(
        public_dir / "_DONE.json",
        {
            "status": summary["status"],
            "config_sha256": summary["config_sha256"],
            "files": listed,
        },
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT)
    parser.add_argument("--desktop", type=Path, default=Path.home() / "Desktop/Lichess_Desktop")
    args = parser.parse_args()
    if not args.project_root.is_dir():
        raise SystemExit("Project drive is not mounted: " + str(args.project_root))
    args.desktop.mkdir(parents=True, exist_ok=True)

    manifest_sha = sha256(PKG / "PACKAGE_MANIFEST.sha256")
    configuration = {
        "version": VERSION,
        "package_manifest_sha256": manifest_sha,
        "source_IV_config_sha256": SOURCE_CONFIG_SHA256,
        "source_comparison_sha256": SOURCE_COMPARISON_SHA256,
        "candidate_definition": "active_timeout OR passive_outoftime",
        "primary_specification": "adjusted_7d_floor5",
        "families": ["candidate_incidence", "active_given_candidate"],
        "posthoc_selection_diagnostic": True,
        "versions": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pyarrow": pq.__version__ if hasattr(pq, "__version__") else __import__("pyarrow").__version__,
        },
    }
    run_hash = config_sha(configuration)
    output_root = (
        args.project_root
        / "derived/replication/chooser_iv_selection_addendum_v100_PRIVATE"
        / run_hash[:12]
    )
    output_root.mkdir(parents=True, exist_ok=True)
    with (output_root / ".run.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("This addendum is already running")

        source_root, comparison_path, authority = verify_source(args.project_root)
        log("Loading the authenticated comparison columns")
        data = load_data(comparison_path)
        rows, flows, reproductions = estimate(data, authority)
        verification = {
            "source_private_root": str(source_root),
            "source_config_sha256": SOURCE_CONFIG_SHA256,
            "source_comparison_path": str(comparison_path),
            "source_comparison_bytes": SOURCE_COMPARISON_BYTES,
            "source_comparison_sha256": SOURCE_COMPARISON_SHA256,
            "source_report_zip_sha256": authority["source_report_zip_sha256"],
            "source_rows": SOURCE_ROWS,
            "existing_estimate_reproduction_checks": len(reproductions),
            "existing_estimate_reproduction_passed": True,
            "network_requests": 0,
        }
        temporary = Path(tempfile.mkdtemp(prefix="report.partial_", dir=output_root))
        try:
            make_report(temporary, rows, flows, reproductions, configuration, verification)
            report_dir = output_root / "report"
            if report_dir.exists():
                shutil.rmtree(report_dir)
            os.replace(temporary, report_dir)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    destination = args.desktop / f"CHOOSER_IV_SELECTION_ADDENDUM_REPORT_{run_hash[:12]}.zip"
    partial = destination.with_suffix(".zip.partial")
    with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((output_root / "report").iterdir()):
            if path.is_file():
                archive.write(path, path.name)
    os.replace(partial, destination)
    sidecar = Path(str(destination) + ".sha256")
    sidecar.write_text(sha256(destination) + "  " + destination.name + "\n")
    log("CHOOSER_IV_SELECTION_ADDENDUM_COMPLETE")
    print("UPLOAD: " + str(destination))
    print("UPLOAD: " + str(sidecar))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Stopped by user; no source data were changed")
        raise SystemExit(130)
    except Exception as error:
        import traceback

        traceback.print_exc()
        log("STOPPED: " + str(error))
        raise SystemExit(2)
