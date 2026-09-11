#!/usr/bin/env python3
"""Estimate frozen F2/E1, combine B2, and certify the four-slot Holm family."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import importlib.util
import json
import math
import multiprocessing as mp
import os
import subprocess
import sys
import time
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Iterable, Sequence


SCRIPT_VERSION = "1.0.0"
PROJECT_ROOT = Path("/Volumes/XT_Pro/lichess_kindness")
EXPECTED_GIT_BASE = "55124c10f746a6de6e5c186c8ddf7796fef5fb2a"
EXPECTED_PLAN_SHA256 = (
    "4f572bb8da7531bfa1b894cfde92da280a936d695bdee72d9bbde6ca4545f039"
)
EXPECTED_SOURCE_AMENDMENT_SHA256 = (
    "79d300c3b1b7b6272b26452c016820b31df8430887fa17a3fc669c69fb92a6bf"
)
EXPECTED_IMPLEMENTATION_AMENDMENT_SHA256 = (
    "1ec12b336344f46a2dc9f4429366bbe526d36202b7949293fac55da32eec9b8b"
)
EXPECTED_STAGE07_SUCCESS_SHA256 = (
    "8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7"
)
EXPECTED_STAGE08_SHA256 = (
    "e9dd80c52da5ffef3d406c3af25912bd924f6423f123ca535cf4077cb039c41f"
)
EXPECTED_CORE_SUCCESS_SHA256 = (
    "bd64005162bf8f37f9488d47e95c2ea4dd946d1227e909930a42dd8e4904f009"
)
EXPECTED_FEASIBILITY_SUCCESS_SHA256 = (
    "944380e1f8f8d56ab2bcdb15a2461ac9bf6332e1e6d39d3207511dcc535a34cc"
)

USER_SEED = 2026082202
PAIR_SEED = 2026082203
SAMPLE_DENOMINATOR = 50
IDENTIFIER_BUCKETS = 16
DAY_MS = 86_400_000
MINUTE_MS = 60_000
MAIN_MONTHS = tuple(
    f"{absolute // 12:04d}-{absolute % 12 + 1:02d}"
    for absolute in range(2023 * 12 + 10, 2023 * 12 + 34)
)
GRID_LABELS = ("true", "placebo_50", "placebo_37")
PERSONAL_GRID_LABELS = ("true", "placebo_37", "placebo_50")
NUMERIC_CONTROLS = (
    "chooser_elo",
    "opponent_elo",
    "chooser_rd",
    "opponent_rd",
    "eval_cp",
    "draw_payoff",
    "win_premium",
    "chooser_clock_s",
    "opponent_clock_s",
    "ply_count",
    "material_advantage",
    "tc_base_s",
    "tc_inc_s",
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--analysis-plan", type=Path)
    parser.add_argument("--source-amendment", type=Path)
    parser.add_argument("--implementation-amendment", type=Path)
    parser.add_argument("--history-root", type=Path, required=False)
    parser.add_argument("--history-state", type=Path)
    parser.add_argument("--b2-root", type=Path, required=False)
    parser.add_argument("--stage07-root", type=Path)
    parser.add_argument("--state-root", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--worker-memory", default="3GB")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def default_run_id() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(chunk_size):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{uuid.uuid4().hex}")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def atomic_json(path: Path, value: Any) -> None:
    atomic_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def write_delimited(
    path: Path,
    rows: Iterable[dict[str, Any]],
    fields: Sequence[str],
    delimiter: str = ",",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{uuid.uuid4().hex}")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=list(fields),
            delimiter=delimiter,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def command_output(args: Sequence[str], cwd: Path | None = None) -> str:
    return subprocess.run(
        list(args), cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def sql_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def path_list_literal(paths: Sequence[Path]) -> str:
    return "[" + ",".join(sql_literal(path) for path in paths) + "]"


def normal_p(z: float) -> float:
    return math.erfc(abs(float(z)) / math.sqrt(2.0)) if math.isfinite(z) else math.nan


def month_start_ms(month: str) -> int:
    value = dt.datetime.strptime(month + "-01", "%Y-%m-%d").replace(
        tzinfo=dt.timezone.utc
    )
    return int(value.timestamp() * 1000)


def configure(connection: Any, memory: str, temp: Path, threads: int = 1) -> None:
    temp.mkdir(parents=True, exist_ok=True)
    connection.execute(f"SET threads={int(threads)}")
    connection.execute(f"SET memory_limit={sql_literal(memory)}")
    connection.execute(f"SET temp_directory={sql_literal(temp)}")
    connection.execute("SET preserve_insertion_order=false")


def authenticate_git(repo: Path, script_path: Path) -> str:
    head = command_output(["git", "rev-parse", "HEAD"], cwd=repo)
    if command_output(["git", "branch", "--show-current"], cwd=repo) != "main":
        raise RuntimeError("Second-wave estimator requires branch main")
    if command_output(["git", "status", "--porcelain=v1"], cwd=repo):
        raise RuntimeError("Second-wave estimator requires a clean repository")
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", EXPECTED_GIT_BASE, head],
        cwd=repo,
        check=True,
    )
    relative = script_path.resolve().relative_to(repo.resolve()).as_posix()
    subprocess.run(
        ["git", "ls-files", "--error-unmatch", relative],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", relative],
        cwd=repo,
        check=True,
    )
    producer_commit = command_output(
        ["git", "log", "-1", "--format=%H", "--", relative], cwd=repo
    )
    if not producer_commit:
        raise RuntimeError("Second-wave estimator has no committed Git authority")
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", producer_commit, head],
        cwd=repo,
        check=True,
    )
    return producer_commit


def latest_success(base: Path, status: str) -> Path:
    candidates = []
    for success in sorted(base.glob("*/_SUCCESS.json"), reverse=True):
        try:
            if load_json(success).get("status") == status:
                candidates.append(success.parent)
        except (OSError, json.JSONDecodeError):
            continue
    if not candidates:
        raise RuntimeError(f"No {status} run found below {base}")
    return candidates[0]


def load_stage08(path: Path) -> Any:
    if sha256_file(path) != EXPECTED_STAGE08_SHA256:
        raise RuntimeError("Certified Stage 08 numerical kernel SHA mismatch")
    spec = importlib.util.spec_from_file_location("certified_stage08", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not import certified Stage 08 numerical kernel")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_payload(args: argparse.Namespace, script_path: Path) -> dict[str, Any]:
    project = args.project_root.resolve()
    repo = project / "replication_package"
    plan = (
        args.analysis_plan
        or repo / "docs/dynamic_prosociality_second_wave_analysis_plan.md"
    ).resolve()
    source_amendment = (
        args.source_amendment
        or repo / "docs/dynamic_prosociality_second_wave_source_contract_amendment.md"
    ).resolve()
    implementation = (
        args.implementation_amendment
        or repo / "docs/dynamic_prosociality_second_wave_implementation_amendment.md"
    ).resolve()
    history_state = (
        args.history_state
        or project / "derived/replication/dynamic_second_wave_history_v100_PRIVATE"
    ).resolve()
    history = (
        args.history_root.resolve()
        if args.history_root
        else latest_success(
            project / "output/dynamic_second_wave_history_v100",
            "DYNAMIC_SECOND_WAVE_HISTORY_V100_OK",
        )
    )
    b2 = (
        args.b2_root.resolve()
        if args.b2_root
        else latest_success(
            project / "output/dynamic_second_wave_b2_v100",
            "DYNAMIC_SECOND_WAVE_B2_V100_OK",
        )
    )
    stage07 = (
        args.stage07_root
        or project / "derived/replication/analysis_panel_24m_sf100k"
    ).resolve()
    state = (
        args.state_root
        or project / "derived/replication/dynamic_second_wave_estimation_v100_PRIVATE"
    ).resolve()
    output = (
        args.output_root or project / "output/dynamic_second_wave_results_v100"
    ).resolve()
    stage08 = (repo / "code/08_make_core_paper_results.py").resolve()
    core = latest_success(
        project / "output/dynamic_prosociality_core_v102",
        "DYNAMIC_PROSOCIALITY_CORE_V102_OK",
    )
    feasibility = latest_success(
        project / "output/dynamic_second_wave_feasibility_v100",
        "DYNAMIC_SECOND_WAVE_FEASIBILITY_V100_OK",
    )
    authorities = {
        "script_sha256": sha256_file(script_path),
        "git_head": authenticate_git(repo, script_path),
        "analysis_plan_sha256": sha256_file(plan),
        "source_amendment_sha256": sha256_file(source_amendment),
        "implementation_amendment_sha256": sha256_file(implementation),
        "stage07_success_sha256": sha256_file(stage07 / "_SUCCESS.json"),
        "stage08_kernel_sha256": sha256_file(stage08),
        "core_success_sha256": sha256_file(core / "_SUCCESS.json"),
        "feasibility_success_sha256": sha256_file(feasibility / "_SUCCESS.json"),
        "history_success_sha256": sha256_file(history / "_SUCCESS.json"),
        "b2_success_sha256": sha256_file(b2 / "_SUCCESS.json"),
    }
    expected = {
        "analysis_plan_sha256": EXPECTED_PLAN_SHA256,
        "source_amendment_sha256": EXPECTED_SOURCE_AMENDMENT_SHA256,
        "implementation_amendment_sha256": EXPECTED_IMPLEMENTATION_AMENDMENT_SHA256,
        "stage07_success_sha256": EXPECTED_STAGE07_SUCCESS_SHA256,
        "stage08_kernel_sha256": EXPECTED_STAGE08_SHA256,
        "core_success_sha256": EXPECTED_CORE_SUCCESS_SHA256,
        "feasibility_success_sha256": EXPECTED_FEASIBILITY_SUCCESS_SHA256,
    }
    for key, value in expected.items():
        if authorities[key] != value:
            raise RuntimeError(f"Second-wave estimation authority mismatch: {key}")
    if load_json(history / "_SUCCESS.json").get("status") != "DYNAMIC_SECOND_WAVE_HISTORY_V100_OK":
        raise RuntimeError("History success status mismatch")
    if load_json(b2 / "_SUCCESS.json").get("status") != "DYNAMIC_SECOND_WAVE_B2_V100_OK":
        raise RuntimeError("B2 success status mismatch")
    stage07_paths = [
        stage07 / f"month={month}/analysis_panel.parquet" for month in MAIN_MONTHS
    ]
    if not all(path.is_file() for path in stage07_paths):
        raise RuntimeError("Stage 07 monthly inputs are incomplete")
    user_paths = [
        history_state / "user_history_processed" / f"bucket_{b:02d}.parquet"
        for b in range(IDENTIFIER_BUCKETS)
    ]
    pair_paths = [
        history_state / "pair_history_processed" / f"bucket_{b:02d}.parquet"
        for b in range(IDENTIFIER_BUCKETS)
    ]
    target = history_state / "stage07_sampled_targets_private.parquet"
    if not all(path.is_file() for path in (*user_paths, *pair_paths, target)):
        raise RuntimeError("Private history bundle is incomplete")
    history_success = load_json(history / "_SUCCESS.json")
    if history_success.get("private_target_sha256") != sha256_file(target):
        raise RuntimeError("Private Stage 07 target bundle SHA mismatch")
    if history_success.get("private_user_bucket_bundle_sha256") != sha256_json(
        [sha256_file(path) for path in user_paths]
    ):
        raise RuntimeError("Private user-history bundle SHA mismatch")
    if history_success.get("private_pair_bucket_bundle_sha256") != sha256_json(
        [sha256_file(path) for path in pair_paths]
    ):
        raise RuntimeError("Private pair-history bundle SHA mismatch")
    config = {
        "script_version": SCRIPT_VERSION,
        **authorities,
        "user_seed": USER_SEED,
        "pair_seed": PAIR_SEED,
        "sample_denominator": SAMPLE_DENOMINATOR,
        "salience_primary_bandwidth": 10,
        "salience_primary_prior_games": 50,
        "salience_primary_stop_minutes": 30,
        "salience_sensitivity_bandwidths": [5, 15, 20],
        "salience_sensitivity_prior_games": [25, 100],
        "salience_sensitivity_stop_minutes": [15, 60],
        "e1_cell_minimum_sampled": 20,
        "e1_population_scale": 50,
        "holm_slots": ["B2", "E1", "F2-R", "F2-P"],
    }
    return {
        "project": project,
        "repo": repo,
        "plan": plan,
        "source_amendment": source_amendment,
        "implementation": implementation,
        "history": history,
        "history_state": history_state,
        "b2": b2,
        "stage07": stage07,
        "stage07_paths": stage07_paths,
        "stage08": stage08,
        "user_paths": user_paths,
        "pair_paths": pair_paths,
        "target": target,
        "state": state,
        "output": output,
        "run_id": args.run_id or default_run_id(),
        "workers": args.workers,
        "worker_memory": args.worker_memory,
        "authorities": authorities,
        "config": config,
        "config_sha256": sha256_json(config),
    }


def initialize_state(payload: dict[str, Any]) -> None:
    state = payload["state"]
    state.mkdir(parents=True, exist_ok=True)
    config = state / "CONFIG.json"
    if config.is_file():
        saved = load_json(config)
        if saved.get("config_sha256") != payload["config_sha256"]:
            raise RuntimeError("Estimation private state configuration mismatch")
        print("SECOND_WAVE_ESTIMATION_STATE_AUTHENTICATED_OK", flush=True)
        return
    if any(state.iterdir()):
        raise RuntimeError("Nonempty estimation state lacks CONFIG.json")
    (state / "e1_month_scores").mkdir(parents=True)
    (state / "e1_month_receipts").mkdir(parents=True)
    (state / "duckdb_temp").mkdir(parents=True)
    atomic_json(
        config,
        {
            "status": "DYNAMIC_SECOND_WAVE_ESTIMATION_PRIVATE_STATE_OK",
            "created_utc": utc_now(),
            "config": payload["config"],
            "config_sha256": payload["config_sha256"],
            "privacy": "PRIVATE; DO NOT COMMIT OR PUBLISH",
        },
    )
    print("SECOND_WAVE_ESTIMATION_STATE_CREATED", flush=True)


def factor_dummies(values: Any, prefix: str) -> tuple[Any, list[str]]:
    import numpy as np
    import pandas as pd

    codes, levels = pd.factorize(values, sort=True)
    columns = []
    names = []
    for code in range(1, len(levels)):
        columns.append((codes == code).astype(np.float64))
        names.append(f"{prefix}_{levels[code]}")
    if not columns:
        return np.empty((len(codes), 0), dtype=np.float64), []
    return np.column_stack(columns), names


def wls_cluster(
    y: Any,
    x: Any,
    names: Sequence[str],
    weights: Any,
    clusters: Any,
    coefficient_index: int,
) -> dict[str, Any]:
    import numpy as np
    import pandas as pd

    y = np.asarray(y, dtype=np.float64)
    x = np.asarray(x, dtype=np.float64)
    weights = np.asarray(weights, dtype=np.float64)
    cluster_codes, cluster_levels = pd.factorize(clusters, sort=True)
    finite = (
        np.isfinite(y)
        & np.all(np.isfinite(x), axis=1)
        & np.isfinite(weights)
        & (weights > 0)
        & (cluster_codes >= 0)
    )
    y = y[finite]
    x = x[finite]
    weights = weights[finite]
    cluster_codes = cluster_codes[finite]
    root_weight = np.sqrt(weights)
    weighted_x = x * root_weight[:, None]
    weighted_y = y * root_weight
    beta, _, rank, singular = np.linalg.lstsq(weighted_x, weighted_y, rcond=None)
    if int(rank) != x.shape[1]:
        raise RuntimeError(f"Salience model rank changed: {rank}/{x.shape[1]}")
    residual = y - x @ beta
    bread = np.linalg.inv(weighted_x.T @ weighted_x)
    groups = len(cluster_levels)
    score = np.column_stack(
        [
            np.bincount(
                cluster_codes,
                weights=weights * x[:, column] * residual,
                minlength=groups,
            )
            for column in range(x.shape[1])
        ]
    )
    correction = 1.0
    if groups > 1 and y.size > x.shape[1]:
        correction = (groups / (groups - 1)) * (
            (y.size - 1) / (y.size - x.shape[1])
        )
    covariance = bread @ (score.T @ score) @ bread * correction
    se = np.sqrt(np.maximum(np.diag(covariance), 0.0))
    influence = score @ bread[coefficient_index, :] * math.sqrt(correction)
    coefficient = float(beta[coefficient_index])
    standard_error = float(se[coefficient_index])
    z_value = coefficient / standard_error if standard_error > 0 else math.nan
    return {
        "rows": int(y.size),
        "clusters": groups,
        "rank": int(rank),
        "smallest_singular_value": float(singular[-1]),
        "coefficient": coefficient,
        "standard_error": standard_error,
        "z_value": z_value,
        "p_value_two_sided": normal_p(z_value),
        "coefficient_names": list(names),
        "cluster_levels": cluster_levels.tolist(),
        "coefficient_influence": influence.tolist(),
    }


def salience_frame(payload: dict[str, Any], branch: str) -> Any:
    import duckdb

    sources = path_list_literal(payload["user_paths"])
    connection = duckdb.connect()
    configure(
        connection,
        "10GB",
        payload["state"] / "duckdb_temp" / f"salience_{branch}",
        8,
    )
    if branch == "round":
        thresholds = """
          ('true', 0.0), ('placebo_50', 50.0), ('placebo_37', 37.0)
        """
        query = f"""
          WITH base AS (
            SELECT *
            FROM read_parquet({sources}, union_by_name=true)
            WHERE rating_diff > 0 AND post_rating IS NOT NULL
              AND prior_same_pool_games >= 25
              AND utc_ms - first_prior_pool_utc_ms >= {365 * DAY_MS}
          ), expanded AS (
            SELECT b.*, grid,
              ROUND((post_rating - offset_value) / 100.0) * 100.0 + offset_value
                AS threshold
            FROM base b
            CROSS JOIN (VALUES {thresholds}) g(grid, offset_value)
          )
          SELECT
            user_id, game_id, utc_ms, speed, pre_rating, rating_diff,
            prior_same_pool_games,
            next_any_utc_ms, next_same_speed_utc_ms, grid, threshold,
            post_rating - threshold AS running,
            EXTRACT('year' FROM TO_TIMESTAMP(utc_ms / 1000.0)) * 12
              + EXTRACT('month' FROM TO_TIMESTAMP(utc_ms / 1000.0)) AS month_code
          FROM expanded
          WHERE pre_rating < threshold
            AND ABS(post_rating - threshold) <= 20
            AND threshold BETWEEN 1000 AND 2600
        """
    elif branch == "personal":
        thresholds = """
          ('true', 0.0), ('placebo_37', 37.0), ('placebo_50', 50.0)
        """
        query = f"""
          WITH base AS (
            SELECT *
            FROM read_parquet({sources}, union_by_name=true)
            WHERE rating_diff > 0 AND post_rating IS NOT NULL
              AND prior_pool_peak IS NOT NULL
              AND prior_same_pool_games >= 25
              AND utc_ms - first_prior_pool_utc_ms >= {365 * DAY_MS}
          ), expanded AS (
            SELECT b.*, grid, prior_pool_peak + offset_value AS threshold
            FROM base b
            CROSS JOIN (VALUES {thresholds}) g(grid, offset_value)
          )
          SELECT
            user_id, game_id, utc_ms, speed, pre_rating, rating_diff,
            prior_same_pool_games,
            next_any_utc_ms, next_same_speed_utc_ms, grid, threshold,
            post_rating - threshold AS running,
            EXTRACT('year' FROM TO_TIMESTAMP(utc_ms / 1000.0)) * 12
              + EXTRACT('month' FROM TO_TIMESTAMP(utc_ms / 1000.0)) AS month_code
          FROM expanded
          WHERE pre_rating < threshold
            AND ABS(post_rating - threshold) <= 20
        """
    else:
        raise ValueError(branch)
    frame = connection.execute(query).fetchdf()
    connection.close()
    if frame.empty:
        raise RuntimeError(f"No {branch} salience candidates were constructed")
    return frame


def fit_salience_grid(
    frame: Any,
    *,
    branch: str,
    grid: str,
    bandwidth: int,
    prior_games: int,
    stop_minutes: int,
    next_game_field: str = "next_any_utc_ms",
    stopping_scope: str = "any_rated_standard",
) -> dict[str, Any]:
    import numpy as np

    selected = frame.loc[
        (frame["grid"] == grid)
        & (frame["running"].abs() <= bandwidth)
        & (frame["prior_same_pool_games"] >= prior_games)
    ].copy()
    if len(selected) < 500:
        raise RuntimeError(
            f"Insufficient {branch}/{grid} salience support: {len(selected)}"
        )
    running = selected["running"].to_numpy(dtype=np.float64)
    above = (running >= 0).astype(np.float64)
    weights = 1.0 - np.abs(running) / bandwidth
    positive = weights > 0
    selected = selected.loc[positive].reset_index(drop=True)
    running = running[positive]
    above = above[positive]
    weights = weights[positive]
    if next_game_field not in {"next_any_utc_ms", "next_same_speed_utc_ms"}:
        raise ValueError(next_game_field)
    next_utc = selected[next_game_field].to_numpy(dtype=np.float64)
    focal = selected["utc_ms"].to_numpy(dtype=np.float64)
    y = (~np.isfinite(next_utc) | (next_utc - focal > stop_minutes * MINUTE_MS)).astype(
        np.float64
    )
    columns = [np.ones(len(selected)), above, running, above * running]
    names = ["intercept", "above", "running", "above_x_running"]
    if branch == "round":
        dummies, dummy_names = factor_dummies(selected["threshold"], "boundary")
        columns.extend(dummies[:, index] for index in range(dummies.shape[1]))
        names.extend(dummy_names)
    else:
        speed, speed_names = factor_dummies(selected["speed"], "speed")
        month, month_names = factor_dummies(selected["month_code"], "month")
        columns.extend(speed[:, index] for index in range(speed.shape[1]))
        columns.extend(month[:, index] for index in range(month.shape[1]))
        names.extend([*speed_names, *month_names])
    result = wls_cluster(
        y,
        np.column_stack(columns),
        names,
        weights,
        selected["user_id"],
        coefficient_index=1,
    )
    discrete_columns = [np.ones(len(selected)), above]
    discrete_names = ["intercept", "above"]
    if branch == "round":
        dummies, dummy_names = factor_dummies(selected["threshold"], "boundary")
        discrete_columns.extend(
            dummies[:, index] for index in range(dummies.shape[1])
        )
        discrete_names.extend(dummy_names)
    else:
        speed, speed_names = factor_dummies(selected["speed"], "speed")
        month, month_names = factor_dummies(selected["month_code"], "month")
        discrete_columns.extend(speed[:, index] for index in range(speed.shape[1]))
        discrete_columns.extend(month[:, index] for index in range(month.shape[1]))
        discrete_names.extend([*speed_names, *month_names])
    discrete = wls_cluster(
        y,
        np.column_stack(discrete_columns),
        discrete_names,
        np.ones(len(selected)),
        selected["user_id"],
        coefficient_index=1,
    )
    result.update(
        {
            "branch": branch,
            "grid": grid,
            "bandwidth": bandwidth,
            "minimum_prior_same_pool_games": prior_games,
            "stop_minutes": stop_minutes,
            "stopping_scope": stopping_scope,
            "integer_running_min": int(np.min(running)),
            "integer_running_max": int(np.max(running)),
            "integer_bins": int(np.unique(running).size),
            "above_rows": int(np.count_nonzero(above)),
            "below_rows": int(np.count_nonzero(~above.astype(bool))),
            "coefficient_percentage_points": result["coefficient"] * 100,
            "standard_error_percentage_points": result["standard_error"] * 100,
            "discrete_window_coefficient": discrete["coefficient"],
            "discrete_window_standard_error": discrete["standard_error"],
            "discrete_window_p_two_sided": discrete["p_value_two_sided"],
            "discrete_window_description": (
                "integer-window above-minus-below comparison with branch fixed effects; "
                "uniform weights; chooser-clustered"
            ),
        }
    )
    return result


def influence_covariance(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_map = dict(
        zip(left["cluster_levels"], left["coefficient_influence"], strict=True)
    )
    right_map = dict(
        zip(right["cluster_levels"], right["coefficient_influence"], strict=True)
    )
    shared = left_map.keys() & right_map.keys()
    return float(sum(left_map[key] * right_map[key] for key in shared))


def evaluate_salience_gate(frame: Any, branch: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    labels = GRID_LABELS if branch == "round" else PERSONAL_GRID_LABELS
    primary = {
        label: fit_salience_grid(
            frame,
            branch=branch,
            grid=label,
            bandwidth=10,
            prior_games=50,
            stop_minutes=30,
        )
        for label in labels
    }
    true = primary["true"]
    placebo_a = primary[labels[1]]
    placebo_b = primary[labels[2]]
    contrast = true["coefficient"] - 0.5 * (
        placebo_a["coefficient"] + placebo_b["coefficient"]
    )
    covariance = {
        (a, b): influence_covariance(primary[a], primary[b])
        for a in labels
        for b in labels
    }
    contrast_weights = {"true": 1.0, labels[1]: -0.5, labels[2]: -0.5}
    variance = sum(
        contrast_weights[a] * contrast_weights[b] * covariance[(a, b)]
        for a in labels
        for b in labels
    )
    contrast_se = math.sqrt(max(variance, 0.0))
    contrast_z = contrast / contrast_se if contrast_se > 0 else math.nan
    passed = bool(
        true["coefficient"] > 0
        and true["p_value_two_sided"] < 0.05
        and contrast > 0
        and normal_p(contrast_z) < 0.05
    )
    gate = {
        "branch": branch,
        "status": "PASSED" if passed else "FAILED",
        "passed": passed,
        "true_coefficient": true["coefficient"],
        "true_standard_error": true["standard_error"],
        "true_p_two_sided": true["p_value_two_sided"],
        "true_minus_average_placebo": contrast,
        "contrast_standard_error": contrast_se,
        "contrast_z": contrast_z,
        "contrast_p_two_sided": normal_p(contrast_z),
        "rule": "true positive p<0.05 and true-minus-average-placebo positive p<0.05",
    }
    sensitivity_specs = [
        (bandwidth, 50, 30) for bandwidth in (5, 15, 20)
    ] + [(10, prior, 30) for prior in (25, 100)] + [
        (10, 50, minutes) for minutes in (15, 60)
    ]
    sensitivity: list[dict[str, Any]] = []
    for bandwidth, prior, minutes in sensitivity_specs:
        for label in labels:
            result = fit_salience_grid(
                frame,
                branch=branch,
                grid=label,
                bandwidth=bandwidth,
                prior_games=prior,
                stop_minutes=minutes,
            )
            result["sensitivity"] = True
            sensitivity.append(
                {
                    key: value
                    for key, value in result.items()
                    if key not in {"cluster_levels", "coefficient_influence"}
                }
            )
    for label in labels:
        result = fit_salience_grid(
            frame,
            branch=branch,
            grid=label,
            bandwidth=10,
            prior_games=50,
            stop_minutes=30,
            next_game_field="next_same_speed_utc_ms",
            stopping_scope="same_speed_rated_standard_secondary",
        )
        result["sensitivity"] = True
        sensitivity.append(
            {
                key: value
                for key, value in result.items()
                if key not in {"cluster_levels", "coefficient_influence"}
            }
        )
    public_primary = []
    for result in primary.values():
        public_primary.append(
            {
                key: value
                for key, value in result.items()
                if key not in {"cluster_levels", "coefficient_influence"}
            }
        )
    return gate, [*public_primary, *sensitivity]


def salience_diagnostics(frame: Any, branch: str) -> dict[str, list[dict[str, Any]]]:
    """Build mandatory discrete support, density, balance, and threshold diagnostics."""
    import numpy as np

    labels = GRID_LABELS if branch == "round" else PERSONAL_GRID_LABELS
    support_rows: list[dict[str, Any]] = []
    balance_rows: list[dict[str, Any]] = []
    threshold_rows: list[dict[str, Any]] = []
    for label in labels:
        selected = frame.loc[
            (frame["grid"] == label)
            & (frame["running"].abs() <= 20)
            & (frame["prior_same_pool_games"] >= 50)
        ].copy()
        selected["running_integer"] = selected["running"].astype(int)
        focal = selected["utc_ms"].to_numpy(dtype=np.float64)
        for scope, field in (
            ("any_rated_standard", "next_any_utc_ms"),
            ("same_speed_rated_standard", "next_same_speed_utc_ms"),
        ):
            next_utc = selected[field].to_numpy(dtype=np.float64)
            selected["stopped_30m"] = (
                ~np.isfinite(next_utc) | (next_utc - focal > 30 * MINUTE_MS)
            ).astype(np.int8)
            grouped = (
                selected.groupby("running_integer", sort=True, observed=True)
                .agg(rows=("game_id", "size"), stopped_30m=("stopped_30m", "sum"))
                .reset_index()
            )
            for row in grouped.itertuples(index=False):
                support_rows.append(
                    {
                        "branch": branch,
                        "grid": label,
                        "stopping_scope": scope,
                        "running_integer": int(row.running_integer),
                        "rows": int(row.rows),
                        "stopped_30m": int(row.stopped_30m),
                        "stopping_rate": float(row.stopped_30m / row.rows),
                    }
                )
        primary = selected.loc[selected["running"].abs() < 10].copy()
        below = primary.loc[primary["running"] < 0]
        above = primary.loc[primary["running"] >= 0]
        total = len(below) + len(above)
        density_z = (
            (len(above) - len(below)) / math.sqrt(total) if total > 0 else math.nan
        )
        balance_rows.append(
            {
                "branch": branch,
                "grid": label,
                "bandwidth": 10,
                "below_rows": int(len(below)),
                "above_rows": int(len(above)),
                "above_below_density_ratio": (
                    float(len(above) / len(below)) if len(below) else math.nan
                ),
                "density_equal_mass_z": float(density_z),
                "density_equal_mass_p_two_sided": normal_p(density_z),
                "below_mean_pre_distance": (
                    float((below["pre_rating"] - below["threshold"]).mean())
                    if len(below)
                    else math.nan
                ),
                "above_mean_pre_distance": (
                    float((above["pre_rating"] - above["threshold"]).mean())
                    if len(above)
                    else math.nan
                ),
                "above_minus_below_mean_pre_distance": (
                    float(
                        (above["pre_rating"] - above["threshold"]).mean()
                        - (below["pre_rating"] - below["threshold"]).mean()
                    )
                    if len(above) and len(below)
                    else math.nan
                ),
                "below_mean_positive_rating_change": (
                    float(below["rating_diff"].mean()) if len(below) else math.nan
                ),
                "above_mean_positive_rating_change": (
                    float(above["rating_diff"].mean()) if len(above) else math.nan
                ),
            }
        )

    true_frame = frame.loc[
        (frame["grid"] == "true")
        & (frame["running"].abs() <= 10)
        & (frame["prior_same_pool_games"] >= 50)
    ].copy()
    if branch == "round":
        groups = ((str(int(key)), part) for key, part in true_frame.groupby("threshold"))
        group_label = "threshold"
    else:
        true_frame["threshold_band_100"] = (
            np.floor(true_frame["threshold"] / 100.0) * 100
        ).astype(int)
        groups = (
            (str(int(key)), part)
            for key, part in true_frame.groupby("threshold_band_100")
        )
        group_label = "threshold_band_100"
    for key, part in groups:
        below_rows = int(np.count_nonzero(part["running"] < 0))
        above_rows = int(np.count_nonzero(part["running"] >= 0))
        row: dict[str, Any] = {
            "branch": branch,
            "group_type": group_label,
            "group_value": key,
            "rows": int(len(part)),
            "below_rows": below_rows,
            "above_rows": above_rows,
            "model_status": "SUPPORT_ONLY",
        }
        if len(part) >= 500 and below_rows >= 100 and above_rows >= 100:
            try:
                result = fit_salience_grid(
                    part,
                    branch=branch,
                    grid="true",
                    bandwidth=10,
                    prior_games=50,
                    stop_minutes=30,
                )
                row.update(
                    {
                        "model_status": "ESTIMATED",
                        "coefficient": result["coefficient"],
                        "standard_error": result["standard_error"],
                        "p_value_two_sided": result["p_value_two_sided"],
                    }
                )
            except RuntimeError as exc:
                row["model_status"] = "NOT_ESTIMABLE"
                row["model_note"] = str(exc)
        threshold_rows.append(row)
    return {
        "integer_support": support_rows,
        "density_and_balance": balance_rows,
        "threshold_models": threshold_rows,
    }


def e1_score_paths(state: Path, month: str) -> tuple[Path, Path]:
    output = state / "e1_month_scores" / f"month_{month}.parquet"
    receipt = state / "e1_month_receipts" / f"month_{month}.json"
    return output, receipt


def authenticate_e1_month(
    state: Path, month: str, config_sha: str
) -> dict[str, Any] | None:
    import pyarrow.parquet as pq

    output, receipt = e1_score_paths(state, month)
    if not output.exists() and not receipt.exists():
        return None
    if not output.is_file() or not receipt.is_file():
        raise RuntimeError(f"Partial E1 month checkpoint {month}")
    saved = load_json(receipt)
    expected = {
        "status": "DYNAMIC_SECOND_WAVE_E1_MONTH_SCORE_OK",
        "config_sha256": config_sha,
        "month": month,
        "output_path": str(output),
        "output_rows": int(pq.ParquetFile(output).metadata.num_rows),
        "output_bytes": output.stat().st_size,
        "output_sha256": sha256_file(output),
    }
    for key, value in expected.items():
        if saved.get(key) != value:
            raise RuntimeError(f"E1 month mismatch {month}: {key}")
    return saved


def e1_month_worker(
    month: str,
    pair_paths_text: list[str],
    target_text: str,
    state_text: str,
    config_sha: str,
    memory: str,
) -> dict[str, Any]:
    import duckdb
    import pyarrow.parquet as pq

    state = Path(state_text)
    output, receipt = e1_score_paths(state, month)
    if output.exists() or receipt.exists():
        raise RuntimeError(f"Worker received existing E1 month {month}")
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}.parquet")
    focal_start = month_start_ms(month)
    train_start = focal_start - 395 * DAY_MS
    train_stop = focal_start - 30 * DAY_MS
    pair_paths = [Path(path) for path in pair_paths_text]
    connection = duckdb.connect()
    configure(connection, memory, state / "duckdb_temp" / f"e1_{month}", 1)
    pair_source = path_list_literal(pair_paths)
    target_source = sql_literal(target_text)
    query = f"""
      COPY (
        WITH train AS (
          SELECT *
          FROM read_parquet({pair_source}, union_by_name=true)
          WHERE utc_ms >= {train_start} AND utc_ms < {train_stop}
        ), train_expanded AS (
          SELECT low_id, high_id, CAST(repeat_within_30d AS BIGINT) AS success,
                 level, cell_key
          FROM train
          CROSS JOIN LATERAL (
            SELECT 1 AS level,
              speed || '|' || rating_band_100 || '|' || utc_block_6h || '|'
                || CAST(weekend AS INTEGER) AS cell_key
            UNION ALL SELECT 2,
              speed || '|' || rating_band_100 || '|' || utc_block_6h
            UNION ALL SELECT 3,
              speed || '|' || rating_band_200 || '|' || utc_block_6h
            UNION ALL SELECT 4,
              speed || '|' || rating_band_200
            UNION ALL SELECT 5, speed
          ) levels
        ), cells AS (
          SELECT level, cell_key, COUNT(*)::BIGINT AS n, SUM(success)::BIGINT AS k
          FROM train_expanded GROUP BY level, cell_key
        ), pairs AS (
          SELECT low_id, high_id, level, cell_key,
                 COUNT(*)::BIGINT AS n, SUM(success)::BIGINT AS k
          FROM train_expanded GROUP BY low_id, high_id, level, cell_key
        ), pair_state AS (
          SELECT low_id, high_id, game_id, pair_sequence
          FROM read_parquet({pair_source}, union_by_name=true)
          WHERE is_stage07_target
        ), targets AS (
          SELECT t.*, p.pair_sequence,
            CAST(FLOOR((t.chooser_elo + t.opponent_elo) / 200.0) * 100 AS INTEGER)
              AS average_rating,
            CAST(FLOOR((t.chooser_elo + t.opponent_elo) / 200.0) * 100 AS INTEGER)
              AS rating_band_100,
            CAST(FLOOR((t.chooser_elo + t.opponent_elo) / 400.0) * 200 AS INTEGER)
              AS rating_band_200,
            CAST(FLOOR(EXTRACT('hour' FROM TO_TIMESTAMP(t.utc_ms / 1000.0)) / 6)
              AS INTEGER) AS utc_block_6h,
            EXTRACT('isodow' FROM TO_TIMESTAMP(t.utc_ms / 1000.0)) IN (6, 7)
              AS weekend
          FROM read_parquet({target_source}) t
          INNER JOIN pair_state p
            ON t.low_id = p.low_id AND t.high_id = p.high_id AND t.game_id = p.game_id
          WHERE CAST(t.pair_sample AS BOOLEAN) AND t.month = {sql_literal(month)}
        ), target_expanded AS (
          SELECT t.*, level, cell_key
          FROM targets t
          CROSS JOIN LATERAL (
            SELECT 1 AS level,
              speed || '|' || rating_band_100 || '|' || utc_block_6h || '|'
                || CAST(weekend AS INTEGER) AS cell_key
            UNION ALL SELECT 2,
              speed || '|' || rating_band_100 || '|' || utc_block_6h
            UNION ALL SELECT 3,
              speed || '|' || rating_band_200 || '|' || utc_block_6h
            UNION ALL SELECT 4,
              speed || '|' || rating_band_200
            UNION ALL SELECT 5, speed
          ) levels
        ), candidates AS (
          SELECT t.*,
            c.n - COALESCE(p.n, 0) AS leave_pair_out_n,
            c.k - COALESCE(p.k, 0) AS leave_pair_out_k
          FROM target_expanded t
          INNER JOIN cells c USING (level, cell_key)
          LEFT JOIN pairs p USING (low_id, high_id, level, cell_key)
        ), eligible AS (
          SELECT *, ROW_NUMBER() OVER (
            PARTITION BY game_id, chooser_user_id ORDER BY level
          ) AS eligibility_rank
          FROM candidates
          WHERE leave_pair_out_n >= 20
        )
        SELECT * EXCLUDE (eligibility_rank, cell_key),
          pair_sequence = 1 AS first_ever_pair,
          (50.0 * leave_pair_out_k + 0.5)
            / (50.0 * leave_pair_out_n + 1.0) AS re_pair_risk
        FROM eligible WHERE eligibility_rank = 1
      ) TO {sql_literal(temporary)}
        (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
    """
    started = time.time()
    connection.execute(query)
    connection.close()
    os.replace(temporary, output)
    rows = int(pq.ParquetFile(output).metadata.num_rows)
    saved = {
        "status": "DYNAMIC_SECOND_WAVE_E1_MONTH_SCORE_OK",
        "created_utc": utc_now(),
        "config_sha256": config_sha,
        "month": month,
        "training_start_ms": train_start,
        "training_stop_exclusive_ms": train_stop,
        "output_path": str(output),
        "output_rows": rows,
        "output_bytes": output.stat().st_size,
        "output_sha256": sha256_file(output),
        "runtime_seconds": time.time() - started,
    }
    atomic_json(receipt, saved)
    return saved


def build_e1_scores(payload: dict[str, Any]) -> list[Path]:
    pending = [
        month
        for month in MAIN_MONTHS
        if authenticate_e1_month(
            payload["state"], month, payload["config_sha256"]
        )
        is None
    ]
    print(
        f"E1_MONTH_CHECKPOINTS existing={len(MAIN_MONTHS) - len(pending)} "
        f"pending={len(pending)} workers={payload['workers']}",
        flush=True,
    )
    if pending:
        context = mp.get_context("spawn")
        with ProcessPoolExecutor(
            max_workers=min(payload["workers"], len(pending)), mp_context=context
        ) as executor:
            futures = {
                executor.submit(
                    e1_month_worker,
                    month,
                    [str(path) for path in payload["pair_paths"]],
                    str(payload["target"]),
                    str(payload["state"]),
                    payload["config_sha256"],
                    payload["worker_memory"],
                ): month
                for month in pending
            }
            for future in as_completed(futures):
                saved = future.result()
                print(
                    f"E1_MONTH_SCORE_OK month={saved['month']} "
                    f"rows={saved['output_rows']:,} seconds={saved['runtime_seconds']:.1f}",
                    flush=True,
                )
    paths = []
    for month in MAIN_MONTHS:
        authenticate_e1_month(payload["state"], month, payload["config_sha256"])
        paths.append(e1_score_paths(payload["state"], month)[0])
    return paths


def panel_support(payload: dict[str, Any]) -> list[dict[str, Any]]:
    import duckdb

    paths = path_list_literal(payload["stage07_paths"])
    connection = duckdb.connect()
    configure(connection, "8GB", payload["state"] / "duckdb_temp/panel_support", 8)
    result = connection.execute(
        f"""
        SELECT CAST(month AS VARCHAR) AS month, CAST(api_speed AS VARCHAR) AS speed,
          COUNT(*)::BIGINT AS full_fair_rows,
          COUNT(*) FILTER (
            WHERE hash(CAST(chooser_user_id AS BIGINT), {USER_SEED})
              % {SAMPLE_DENOMINATOR} = 0
          )::BIGINT AS user_sample_rows,
          COUNT(*) FILTER (
            WHERE hash(
              LEAST(CAST(chooser_user_id AS BIGINT), CAST(disconnected_user_id AS BIGINT)),
              GREATEST(CAST(chooser_user_id AS BIGINT), CAST(disconnected_user_id AS BIGINT)),
              {PAIR_SEED}
            ) % {SAMPLE_DENOMINATOR} = 0
          )::BIGINT AS pair_sample_rows
        FROM read_parquet({paths}, union_by_name=true)
        WHERE CAST(fair_competitive AS BOOLEAN)
        GROUP BY month, speed ORDER BY month, speed
        """
    )
    fields = [item[0] for item in result.description]
    rows = [dict(zip(fields, row, strict=True)) for row in result.fetchall()]
    connection.close()
    for row in rows:
        row["user_sample_share"] = row["user_sample_rows"] / row["full_fair_rows"]
        row["pair_sample_share"] = row["pair_sample_rows"] / row["full_fair_rows"]
    return rows


def stage07_frame(payload: dict[str, Any], branch: str, e1_paths: Sequence[Path]) -> Any:
    import duckdb

    paths = path_list_literal(payload["stage07_paths"])
    user_state = path_list_literal(payload["user_paths"])
    connection = duckdb.connect()
    configure(
        connection,
        "10GB",
        payload["state"] / "duckdb_temp" / f"model_{branch}",
        8,
    )
    common = f"""
      SELECT
        CAST(p.game_id AS VARCHAR) AS game_id,
        CAST(p.archive_ordinal AS BIGINT) AS archive_ordinal,
        CAST(p.month AS VARCHAR) AS month,
        CAST(p.utc_ms AS BIGINT) AS utc_ms,
        CAST(p.chooser_user_id AS BIGINT) AS chooser_user_id,
        CAST(p.disconnected_user_id AS BIGINT) AS opponent_user_id,
        CAST(p.kind_draw AS DOUBLE) AS kind_draw,
        CAST(p.chooser_elo AS DOUBLE) AS chooser_elo,
        CAST(p.disconnected_elo AS DOUBLE) AS opponent_elo,
        CAST(p.chooser_pre_rd_v2 AS DOUBLE) AS chooser_rd,
        CAST(p.disconnected_pre_rd_v2 AS DOUBLE) AS opponent_rd,
        CAST(p.engine_eval_cp_disconnected AS DOUBLE) AS eval_cp,
        CAST(p.chooser_draw_payoff_v2 AS DOUBLE) AS draw_payoff,
        CAST(p.chooser_win_premium_v2 AS DOUBLE) AS win_premium,
        CAST(p.chooser_clock_last_obs_s AS DOUBLE) AS chooser_clock_s,
        CAST(p.disconnected_clock_last_obs_s AS DOUBLE) AS opponent_clock_s,
        CAST(p.ply_count AS DOUBLE) AS ply_count,
        CAST(p.material_advantage_chooser AS DOUBLE) AS material_advantage,
        CAST(p.tc_base_s AS DOUBLE) AS tc_base_s,
        CAST(p.tc_inc_s AS DOUBLE) AS tc_inc_s,
        CAST(p.api_speed AS VARCHAR) AS speed,
        CAST(p.tournament_like_event AS INTEGER) AS tournament_like,
        CAST(FLOOR((CAST(p.chooser_elo AS DOUBLE) + CAST(p.disconnected_elo AS DOUBLE))
          / 200.0) * 100 AS INTEGER) AS rating_band_100,
        CAST(FLOOR(EXTRACT('hour' FROM TO_TIMESTAMP(CAST(p.utc_ms AS BIGINT) / 1000.0))
          / 6) AS INTEGER) AS utc_block_6h,
        CAST(EXTRACT('isodow' FROM TO_TIMESTAMP(CAST(p.utc_ms AS BIGINT) / 1000.0))
          IN (6, 7) AS INTEGER) AS weekend
      FROM read_parquet({paths}, union_by_name=true) p
      WHERE CAST(p.fair_competitive AS BOOLEAN)
    """
    if branch in {"F2-R", "F2-P"}:
        query = f"""
          WITH panel AS ({common}), state AS (
            SELECT user_id, game_id, prior_pool_peak
            FROM read_parquet({user_state}, union_by_name=true)
            WHERE is_stage07_target
          ), joined AS (
            SELECT p.*, s.prior_pool_peak,
              p.chooser_elo + p.draw_payoff AS post_draw,
              p.chooser_elo + p.draw_payoff + p.win_premium AS post_win
            FROM panel p
            INNER JOIN state s
              ON p.chooser_user_id = s.user_id AND p.game_id = s.game_id
            WHERE hash(p.chooser_user_id, {USER_SEED}) % {SAMPLE_DENOMINATOR} = 0
              AND p.chooser_rd <= 110
          )
          SELECT *,
            CASE WHEN FLOOR(post_win / 100.0) > FLOOR(post_draw / 100.0)
                  AND (FLOOR(post_draw / 100.0) + 1) * 100 BETWEEN 1000 AND 2600
                 THEN 1.0 ELSE 0.0 END AS round_true,
            CASE WHEN FLOOR((post_win - 50) / 100.0) > FLOOR((post_draw - 50) / 100.0)
                  AND (FLOOR((post_draw - 50) / 100.0) + 1) * 100 + 50
                    BETWEEN 1000 AND 2600
                 THEN 1.0 ELSE 0.0 END AS round_50,
            CASE WHEN FLOOR((post_win - 37) / 100.0) > FLOOR((post_draw - 37) / 100.0)
                  AND (FLOOR((post_draw - 37) / 100.0) + 1) * 100 + 37
                    BETWEEN 1000 AND 2600
                 THEN 1.0 ELSE 0.0 END AS round_37,
            CASE WHEN prior_pool_peak IS NOT NULL
                       AND post_draw < prior_pool_peak AND prior_pool_peak <= post_win
                 THEN 1.0 ELSE 0.0 END AS peak_true,
            CASE WHEN prior_pool_peak IS NOT NULL
                       AND post_draw < prior_pool_peak + 37 AND prior_pool_peak + 37 <= post_win
                 THEN 1.0 ELSE 0.0 END AS peak_37,
            CASE WHEN prior_pool_peak IS NOT NULL
                       AND post_draw < prior_pool_peak + 50 AND prior_pool_peak + 50 <= post_win
                 THEN 1.0 ELSE 0.0 END AS peak_50,
            CASE WHEN FLOOR((chooser_elo + ROUND(draw_payoff + win_premium)) / 100.0)
                         > FLOOR((chooser_elo + ROUND(draw_payoff)) / 100.0)
                 THEN 1 ELSE 0 END AS visible_round_true
          FROM joined
        """
    elif branch == "E1":
        scores = path_list_literal(e1_paths)
        query = f"""
          WITH panel AS ({common}), scores AS (
            SELECT * FROM read_parquet({scores}, union_by_name=true)
          )
          SELECT p.*, s.re_pair_risk, s.first_ever_pair, s.level AS coarsening_level,
                 s.leave_pair_out_n, s.leave_pair_out_k
          FROM panel p
          INNER JOIN scores s
            ON p.game_id = s.game_id AND p.chooser_user_id = s.chooser_user_id
          WHERE hash(
            LEAST(p.chooser_user_id, p.opponent_user_id),
            GREATEST(p.chooser_user_id, p.opponent_user_id),
            {PAIR_SEED}
          ) % {SAMPLE_DENOMINATOR} = 0
        """
    else:
        raise ValueError(branch)
    frame = connection.execute(query).fetchdf()
    connection.close()
    if frame.empty:
        raise RuntimeError(f"No {branch} Stage 07 model rows were constructed")
    return frame


def control_matrix(frame: Any, branch: str) -> tuple[Any, list[str]]:
    import numpy as np

    columns = []
    names = []
    for field in NUMERIC_CONTROLS:
        values = frame[field].to_numpy(dtype=np.float64)
        missing = ~np.isfinite(values)
        finite = values[~missing]
        median = float(np.median(finite)) if finite.size else 0.0
        filled = np.where(missing, median, values)
        mean = float(np.mean(filled))
        scale = float(np.std(filled))
        z = (filled - mean) / scale if scale > 1e-12 else np.zeros_like(filled)
        columns.extend((z, z * z - float(np.mean(z * z))))
        names.extend((field + "_z", field + "_z2"))
        if np.any(missing):
            columns.append(missing.astype(np.float64))
            names.append(field + "_missing")
    speed, speed_names = factor_dummies(frame["speed"], "speed")
    tournament, tournament_names = factor_dummies(
        frame["tournament_like"], "tournament"
    )
    columns.extend(speed[:, index] for index in range(speed.shape[1]))
    columns.extend(tournament[:, index] for index in range(tournament.shape[1]))
    names.extend([*speed_names, *tournament_names])
    if branch == "E1":
        for field in ("rating_band_100", "utc_block_6h", "weekend"):
            dummy, dummy_names = factor_dummies(frame[field], field)
            columns.extend(dummy[:, index] for index in range(dummy.shape[1]))
            names.extend(dummy_names)
    return np.column_stack(columns), names


def contrast_result(
    result: dict[str, Any], weights: Sequence[float], label: str
) -> dict[str, Any]:
    import numpy as np

    vector = np.zeros(len(result["x_names"]), dtype=np.float64)
    vector[: len(weights)] = np.asarray(weights, dtype=np.float64)
    beta = np.asarray(result["beta"], dtype=np.float64)
    covariance = np.asarray(result["covariance"], dtype=np.float64)
    coefficient = float(vector @ beta)
    variance = float(vector @ covariance @ vector)
    standard_error = math.sqrt(max(variance, 0.0))
    z_value = coefficient / standard_error if standard_error > 0 else math.nan
    return {
        "analysis": label,
        "rows_raw": result["n_rows_raw"],
        "rows_identifying": result["n_rows_identifying"],
        "chooser_clusters": result["n_clusters"],
        "coefficient": coefficient,
        "standard_error": standard_error,
        "coefficient_percentage_points": coefficient * 100,
        "standard_error_percentage_points": standard_error * 100,
        "z_value": z_value,
        "p_value_two_sided": normal_p(z_value),
        "absorption_method": result["absorption_method"],
        "absorption_max_scaled_group_mean": result["absorption_last_adjustment"],
        "matrix_rank": result["rank"],
    }


def fit_panel_branch(
    stage08: Any, frame: Any, branch: str, maximum_rd: int = 110
) -> dict[str, Any]:
    import numpy as np
    import pandas as pd

    sample = frame["kind_draw"].notna()
    if branch == "F2-P":
        sample &= (
            frame["chooser_rd"].notna()
            & (frame["chooser_rd"] <= maximum_rd)
            & frame["prior_pool_peak"].notna()
        )
        predictors = ("peak_true", "peak_37", "peak_50")
        contrast = (1.0, -0.5, -0.5)
    elif branch == "F2-R":
        sample &= frame["chooser_rd"].notna() & (frame["chooser_rd"] <= maximum_rd)
        predictors = ("round_true", "round_50", "round_37")
        contrast = (1.0, -0.5, -0.5)
    elif branch == "E1":
        sample &= frame["first_ever_pair"].astype(bool)
        predictors = ("re_pair_risk",)
        contrast = (1.0,)
    else:
        raise ValueError(branch)
    selected = frame.loc[sample].reset_index(drop=True)
    controls, control_names = control_matrix(selected, branch)
    key = selected[list(predictors)].to_numpy(dtype=np.float64)
    x = np.column_stack([key, controls])
    names = [*predictors, *control_names]
    chooser_codes, _ = pd.factorize(selected["chooser_user_id"], sort=False)
    month_codes, _ = pd.factorize(selected["month"], sort=True)
    result = stage08.fit_lpm_cluster(
        selected["kind_draw"].to_numpy(dtype=np.float64),
        x,
        names,
        chooser_codes.astype(np.int64),
        fixed_effect_codes=(
            chooser_codes.astype(np.int64),
            month_codes.astype(np.int64),
        ),
    )
    public = contrast_result(result, contrast, branch)
    public["maximum_chooser_rd"] = maximum_rd if branch.startswith("F2") else None
    public["confirmatory"] = maximum_rd == 110 or branch == "E1"
    public["predictors"] = list(predictors)
    public["control_names"] = control_names
    public["outcome_mean"] = float(selected["kind_draw"].mean())
    if branch == "E1":
        p10, p90 = np.quantile(selected["re_pair_risk"], [0.1, 0.9])
        span = float(p90 - p10)
        public["risk_p10"] = float(p10)
        public["risk_p90"] = float(p90)
        public["risk_p90_minus_p10"] = span
        public["coefficient_per_unit_risk"] = public["coefficient"]
        public["standard_error_per_unit_risk"] = public["standard_error"]
        public["coefficient"] *= span
        public["standard_error"] *= span
        public["coefficient_percentage_points"] *= span
        public["standard_error_percentage_points"] *= span
        public["z_value"] = (
            public["coefficient"] / public["standard_error"]
            if public["standard_error"] > 0
            else math.nan
        )
        public["p_value_two_sided"] = normal_p(public["z_value"])
        public["estimand"] = "fitted p90-minus-p10 re-pair-risk difference"
        public["informative_null_upper_bound_pp"] = (
            public["coefficient"] + 1.96 * public["standard_error"]
        ) * 100
        public["upper_bound_below_0_30pp"] = (
            public["informative_null_upper_bound_pp"] < 0.30
        )
    else:
        public["estimand"] = "true pivotal minus average placebo pivotal"
        public["treated_support"] = {
            predictor: int(np.count_nonzero(selected[predictor]))
            for predictor in predictors
        }
    public["confidence_interval_95_low"] = (
        public["coefficient"] - 1.96 * public["standard_error"]
    )
    public["confidence_interval_95_high"] = (
        public["coefficient"] + 1.96 * public["standard_error"]
    )
    public["confidence_interval_95_low_pp"] = (
        public["confidence_interval_95_low"] * 100
    )
    public["confidence_interval_95_high_pp"] = (
        public["confidence_interval_95_high"] * 100
    )
    public["relative_to_outcome_mean"] = (
        public["coefficient"] / public["outcome_mean"]
        if public["outcome_mean"] > 0
        else math.nan
    )
    return public


def holm_rows(raw: dict[str, float]) -> list[dict[str, Any]]:
    ordered = sorted(raw.items(), key=lambda item: (item[1], item[0]))
    running = 0.0
    adjusted: dict[str, float] = {}
    m = len(ordered)
    for rank, (name, p_value) in enumerate(ordered, start=1):
        candidate = min(1.0, (m - rank + 1) * float(p_value))
        running = max(running, candidate)
        adjusted[name] = running
    return [
        {
            "slot": name,
            "raw_p_value": float(raw[name]),
            "holm_adjusted_p_value": float(adjusted[name]),
            "reject_at_0_05": adjusted[name] < 0.05,
        }
        for name in ("B2", "E1", "F2-R", "F2-P")
    ]


def public_salience_rows(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    excluded = {"coefficient_names", "cluster_levels", "coefficient_influence"}
    return [{key: value for key, value in row.items() if key not in excluded} for row in rows]


def manifest_rows(root: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name not in {"_SUCCESS.json", "report_file_hashes.tsv"}:
            rows.append(
                {
                    "sha256": sha256_file(path),
                    "bytes": path.stat().st_size,
                    "path": path.relative_to(root).as_posix(),
                }
            )
    return rows


def write_results(
    payload: dict[str, Any],
    *,
    support: list[dict[str, Any]],
    round_gate: dict[str, Any],
    personal_gate: dict[str, Any],
    salience: list[dict[str, Any]],
    salience_diagnostics_rows: dict[str, list[dict[str, Any]]],
    models: list[dict[str, Any]],
    diagnostics: dict[str, Any],
    holm: list[dict[str, Any]],
) -> Path:
    final = payload["output"] / payload["run_id"]
    if final.exists():
        raise RuntimeError(f"Second-wave result run already exists: {final}")
    staging = final.with_name("." + final.name + f".tmp.{uuid.uuid4().hex}")
    staging.mkdir(parents=True, exist_ok=False)
    write_delimited(
        staging / "stage07_sample_support.csv",
        support,
        list(support[0]),
    )
    clean_salience = public_salience_rows(salience)
    write_delimited(
        staging / "f2_salience_models.csv",
        clean_salience,
        sorted({key for row in clean_salience for key in row}),
    )
    for name, rows in salience_diagnostics_rows.items():
        if rows:
            write_delimited(
                staging / f"f2_salience_{name}.csv",
                rows,
                sorted({key for row in rows for key in row}),
            )
    model_csv = [
        {
            key: value
            for key, value in row.items()
            if not isinstance(value, (dict, list))
        }
        for row in models
    ]
    write_delimited(
        staging / "second_wave_kindness_models.csv",
        model_csv,
        sorted({key for row in model_csv for key in row}),
    )
    write_delimited(staging / "holm_four_slot_family.csv", holm, list(holm[0]))
    atomic_json(
        staging / "f2_salience_gates.json",
        {"round_number": round_gate, "personal_best": personal_gate},
    )
    atomic_json(staging / "diagnostics.json", diagnostics)
    summary = {
        "status": "DYNAMIC_SECOND_WAVE_RESULTS_V100_OK",
        "created_utc": utc_now(),
        "script_version": SCRIPT_VERSION,
        "authorities": payload["authorities"],
        "config_sha256": payload["config_sha256"],
        "salience_gates": {
            "F2-R": round_gate["status"],
            "F2-P": personal_gate["status"],
        },
        "models": models,
        "holm_family": holm,
        "privacy": "Aggregate output only; identifiers and histories remain private.",
        "patron_profile_input_read": False,
    }
    atomic_json(staging / "summary.json", summary)
    report = manifest_rows(staging)
    write_delimited(
        staging / "report_file_hashes.tsv",
        report,
        ("sha256", "bytes", "path"),
        delimiter="\t",
    )
    success = {
        "status": "DYNAMIC_SECOND_WAVE_RESULTS_V100_OK",
        "created_utc": utc_now(),
        "run_id": payload["run_id"],
        "script_sha256": payload["authorities"]["script_sha256"],
        "git_head": payload["authorities"]["git_head"],
        "analysis_plan_sha256": payload["authorities"]["analysis_plan_sha256"],
        "implementation_amendment_sha256": payload["authorities"][
            "implementation_amendment_sha256"
        ],
        "history_success_sha256": payload["authorities"]["history_success_sha256"],
        "b2_success_sha256": payload["authorities"]["b2_success_sha256"],
        "config_sha256": payload["config_sha256"],
        "summary_sha256": sha256_file(staging / "summary.json"),
        "report_manifest_sha256": sha256_file(staging / "report_file_hashes.tsv"),
        "report_files_hashed": len(report),
        "account_level_output": False,
        "patron_profile_input_read": False,
    }
    atomic_json(staging / "_SUCCESS.json", success)
    final.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging, final)
    return final


def execute(payload: dict[str, Any]) -> Path:
    import numpy as np

    started = time.time()
    initialize_state(payload)
    stage08 = load_stage08(payload["stage08"])
    print("STAGE07_SAMPLE_SUPPORT_BEGIN", flush=True)
    support = panel_support(payload)
    print("STAGE07_SAMPLE_SUPPORT_OK", flush=True)

    print("F2_ROUND_SALIENCE_GATE_BEGIN", flush=True)
    round_frame = salience_frame(payload, "round")
    round_diagnostics = salience_diagnostics(round_frame, "round")
    round_gate, round_rows = evaluate_salience_gate(round_frame, "round")
    del round_frame
    print(f"F2_ROUND_SALIENCE_GATE_{round_gate['status']}", flush=True)

    print("F2_PERSONAL_SALIENCE_GATE_BEGIN", flush=True)
    personal_frame = salience_frame(payload, "personal")
    personal_diagnostics = salience_diagnostics(personal_frame, "personal")
    personal_gate, personal_rows = evaluate_salience_gate(personal_frame, "personal")
    del personal_frame
    print(f"F2_PERSONAL_SALIENCE_GATE_{personal_gate['status']}", flush=True)

    print("E1_PAST_ONLY_SCORE_BUILD_BEGIN", flush=True)
    e1_paths = build_e1_scores(payload)
    print("E1_PAST_ONLY_SCORE_BUILD_OK", flush=True)

    models: list[dict[str, Any]] = []
    diagnostics: dict[str, Any] = {
        "round_gate_passed": round_gate["passed"],
        "personal_gate_passed": personal_gate["passed"],
    }
    f2_frame = (
        stage07_frame(payload, "F2-R", e1_paths)
        if round_gate["passed"] or personal_gate["passed"]
        else None
    )
    if round_gate["passed"]:
        print("F2_R_DOWNSTREAM_KINDNESS_BEGIN", flush=True)
        frame = f2_frame
        if frame is None:
            raise RuntimeError("Shared F2 frame was not built")
        diagnostics["f2_round_exact_visible_disagreement"] = int(
            np.count_nonzero(frame["round_true"] != frame["visible_round_true"])
        )
        diagnostics["f2_round_model_rows_loaded"] = int(len(frame))
        models.append(fit_panel_branch(stage08, frame, "F2-R", 110))
        sensitivity = fit_panel_branch(stage08, frame, "F2-R", 80)
        sensitivity["confirmatory"] = False
        sensitivity["analysis"] = "F2-R_RD80_sensitivity"
        models.append(sensitivity)
        print("F2_R_DOWNSTREAM_KINDNESS_OK", flush=True)
    else:
        models.append(
            {
                "analysis": "F2-R",
                "status": "NOT_ESTIMATED_FAILED_SALIENCE_GATE",
                "p_value_two_sided": 1.0,
                "confirmatory": True,
            }
        )

    if personal_gate["passed"]:
        print("F2_P_DOWNSTREAM_KINDNESS_BEGIN", flush=True)
        frame = f2_frame
        if frame is None:
            raise RuntimeError("Shared F2 frame was not built")
        diagnostics["f2_personal_model_rows_loaded"] = int(len(frame))
        diagnostics["f2_personal_peak_nonmissing"] = int(
            frame["prior_pool_peak"].notna().sum()
        )
        models.append(fit_panel_branch(stage08, frame, "F2-P", 110))
        sensitivity = fit_panel_branch(stage08, frame, "F2-P", 80)
        sensitivity["confirmatory"] = False
        sensitivity["analysis"] = "F2-P_RD80_sensitivity"
        models.append(sensitivity)
        print("F2_P_DOWNSTREAM_KINDNESS_OK", flush=True)
    else:
        models.append(
            {
                "analysis": "F2-P",
                "status": "NOT_ESTIMATED_FAILED_SALIENCE_GATE",
                "p_value_two_sided": 1.0,
                "confirmatory": True,
            }
        )
    del f2_frame

    print("E1_DOWNSTREAM_KINDNESS_BEGIN", flush=True)
    frame = stage07_frame(payload, "E1", e1_paths)
    diagnostics["e1_scored_rows_loaded"] = int(len(frame))
    diagnostics["e1_first_ever_share"] = float(frame["first_ever_pair"].mean())
    diagnostics["e1_coarsening_level_counts"] = {
        str(key): int(value)
        for key, value in frame["coarsening_level"].value_counts().sort_index().items()
    }
    e1_model = fit_panel_branch(stage08, frame, "E1")
    models.append(e1_model)
    del frame
    print("E1_DOWNSTREAM_KINDNESS_OK", flush=True)

    b2_summary = load_json(payload["b2"] / "summary.json")
    b2_p = float(b2_summary["primary_raw_p_value"])
    f2r = next(row for row in models if row["analysis"] == "F2-R")
    f2p = next(row for row in models if row["analysis"] == "F2-P")
    raw = {
        "B2": b2_p,
        "E1": float(e1_model["p_value_two_sided"]),
        "F2-R": float(f2r["p_value_two_sided"]),
        "F2-P": float(f2p["p_value_two_sided"]),
    }
    holm = holm_rows(raw)
    final = write_results(
        payload,
        support=support,
        round_gate=round_gate,
        personal_gate=personal_gate,
        salience=[*round_rows, *personal_rows],
        salience_diagnostics_rows={
            name: [*round_diagnostics[name], *personal_diagnostics[name]]
            for name in round_diagnostics
        },
        models=models,
        diagnostics=diagnostics,
        holm=holm,
    )
    print(f"DYNAMIC_SECOND_WAVE_RESULTS_V100_OK: {final}", flush=True)
    print(f"runtime_seconds: {time.time() - started:.1f}", flush=True)
    return final


def self_test() -> None:
    import numpy as np

    rows = holm_rows({"B2": 0.01, "E1": 0.04, "F2-R": 1.0, "F2-P": 0.02})
    saved = {row["slot"]: row["holm_adjusted_p_value"] for row in rows}
    assert abs(saved["B2"] - 0.04) < 1e-12
    assert abs(saved["F2-P"] - 0.06) < 1e-12
    assert abs(saved["E1"] - 0.08) < 1e-12
    assert saved["F2-R"] == 1.0
    rng = np.random.default_rng(20260822)
    n = 2_000
    running = rng.integers(-9, 10, size=n).astype(float)
    above = running >= 0
    user = rng.integers(0, 200, size=n)
    y = 0.1 + 0.04 * above + 0.002 * running + rng.normal(scale=0.1, size=n)
    x = np.column_stack([np.ones(n), above, running, above * running])
    result = wls_cluster(y, x, ("i", "above", "r", "ar"), np.ones(n), user, 1)
    assert abs(result["coefficient"] - 0.04) < 0.02
    assert result["standard_error"] > 0
    print("DYNAMIC_SECOND_WAVE_RESULTS_V100_SELF_TEST_OK")


def print_plan(payload: dict[str, Any]) -> None:
    print("DYNAMIC_SECOND_WAVE_RESULTS_V100_PLAN_OK")
    print("script_version:", SCRIPT_VERSION)
    print("script_sha256:", payload["authorities"]["script_sha256"])
    print("git_head:", payload["authorities"]["git_head"])
    print("analysis_plan_sha256:", payload["authorities"]["analysis_plan_sha256"])
    print(
        "implementation_amendment_sha256:",
        payload["authorities"]["implementation_amendment_sha256"],
    )
    print("history_success_sha256:", payload["authorities"]["history_success_sha256"])
    print("b2_success_sha256:", payload["authorities"]["b2_success_sha256"])
    print("private_state:", payload["state"])
    print("aggregate_output:", payload["output"])
    print("four_slot_family: B2, E1, F2-R, F2-P")
    print("failed_salience_gate_policy: downstream branch not read; p=1")


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    if args.self_test:
        self_test()
        return
    if not 1 <= args.workers <= 8:
        raise SystemExit("--workers must be between 1 and 8")
    payload = make_payload(args, Path(__file__).resolve())
    print_plan(payload)
    if not args.execute:
        print("No salience or kindness outcome was estimated. Re-run with --execute.")
        return
    execute(payload)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            f"DYNAMIC_SECOND_WAVE_RESULTS_FAIL_CLOSED: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        raise
