#!/usr/bin/env python3
"""Run additional robustness and mechanism analyses for the second wave.

This program consumes the authenticated source run and its private checkpoints.  It
does not overwrite the existing results. Public output is aggregate only.
"""

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
import shutil
import subprocess
import sys
import time
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Iterable, Sequence


PROJECT_ROOT = Path("/Volumes/XT_Pro/lichess_kindness")
SOURCE_RUN_ID = "20260822T150914Z"
DEFAULT_RUN_ID = SOURCE_RUN_ID + "_postprimary_v100"
SCRIPT_VERSION = "1.0.2"

PREVIOUS_SCRIPT_VERSION = "1.0.1"
PREVIOUS_SCRIPT_SHA = "ca12ba9e6a42702e3465ab450d9777db1c3004775abfb8dce124fe4cf1820875"
PREVIOUS_GIT_HEAD = "fdd1cda9ea8208e0fbccc79c988564625d49abff"

EXPECTED_RECOVERY_COMMIT = "f0342a60f77a19b4ac75ab14e0309bbccd5f7620"
EXPECTED_SOURCE_B2_SCRIPT_SHA = (
    "9696925b13a4b9d2c502eda64e21c96506ecd6b76162038ecc2fae312645f6e9"
)
EXPECTED_SOURCE_ESTIMATOR_SHA = (
    "ae525dc989afa32bee49030feeaa86c37894448c121805fedc8a6f2fd31b15a4"
)
EXPECTED_STAGE08_SHA = (
    "e9dd80c52da5ffef3d406c3af25912bd924f6423f123ca535cf4077cb039c41f"
)
EXPECTED_SOURCE_B2_SUCCESS_SHA = (
    "0e4a58c848bb18a2d7d5fcb2a13b4176679c59e60c86aca2161870e0751ba558"
)
EXPECTED_SOURCE_HISTORY_SUCCESS_SHA = (
    "62e4b8335b188f374f83bf1debedc19c62a91769f89a7c12368a628cb26d6de5"
)
EXPECTED_SOURCE_RESULTS_SUCCESS_SHA = (
    "61f253c0ed8f8f64319f7d187c12ba53b1ba9fd331921e984ec47a88bead3d9f"
)
EXPECTED_B1_SAMPLE_SHA = (
    "08429d99aa839c0fc087e3d4d4de270c322086287c3814886f2bcd3bf32e7d56"
)
EXPECTED_B1_PROPENSITY_SHA = (
    "0aebdbb279c52308140a819c940655e4341524b3160bcc385cfa8a92030b02df"
)
EXPECTED_POSTPRIMARY_PLAN_SHA = (
    "8de396d1520a6c11f5ed1f41d79ec24740d117755421631ff91422d78e0152f9"
)

EXPECTED_B2_CHOOSERS = 64_331
EXPECTED_B2_ROWS = 1_017_944
EXPECTED_B2_KIND_DRAWS = 273_483
RANDOMIZATIONS = 4_999
RANDOMIZATION_BATCH = 250
B2_SEED = 2026082201
HOUR_MS = 3_600_000
DAY_MS = 86_400_000
HORIZONS_HOURS = (1.0, 3.0, 6.0, 12.0, 24.0, 48.0, 72.0, 168.0, 336.0, 720.0)
PAYOFF_GROUPS = ("costly", "exact_zero", "favorable")
PERSONAL_OFFSETS = (-100, -75, -50, -37, -25, 0, 25, 37, 50, 75, 100)

_B2_BASE: Any | None = None
_B2_DATA: dict[str, Any] | None = None
_B2_PROBABILITY: Any | None = None
_B2_SLICES: list[tuple[int, int]] | None = None
_B2_SELECTIONS: list[Any] | None = None


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--worker-memory", default="3GB")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(chunk_size):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{uuid.uuid4().hex}")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def atomic_json(path: Path, value: Any) -> None:
    atomic_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def atomic_npz(path: Path, **arrays: Any) -> None:
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{uuid.uuid4().hex}")
    with temporary.open("wb") as stream:
        np.savez_compressed(stream, **arrays)
    os.replace(temporary, path)


def write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"Refusing to write empty CSV: {path}")
    fields = sorted({key for row in rows for key in row})
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{uuid.uuid4().hex}")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def command_output(args: Sequence[str], cwd: Path | None = None) -> str:
    return subprocess.run(
        list(args), cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def normal_p(z_value: float) -> float:
    if not math.isfinite(z_value):
        return math.nan
    return math.erfc(abs(z_value) / math.sqrt(2.0))


def assert_normal_p_consistent(row: dict[str, Any], label: str) -> None:
    """Validate a reported p-value from its coefficient and standard error."""

    coefficient = float(row["coefficient"])
    standard_error = float(row["standard_error"])
    observed = float(row["p_value_two_sided"])
    z_value = coefficient / standard_error if standard_error > 0 else math.nan
    expected = normal_p(z_value)
    if math.isnan(expected):
        if not math.isnan(observed):
            raise RuntimeError(f"{label} has a finite p-value with no finite z-value")
        return
    if not math.isclose(observed, expected, rel_tol=1e-12, abs_tol=1e-12):
        raise RuntimeError(
            f"{label} p-value is inconsistent with its coefficient and standard error: "
            f"observed={observed:.17g} expected={expected:.17g}"
        )


def assert_estimate_reproduced(
    current: dict[str, Any],
    source: dict[str, Any],
    label: str,
    *,
    exact_fields: Sequence[str] = (),
    rel_tol: float = 1e-11,
    abs_tol: float = 1e-11,
) -> None:
    """Compare primitive estimates; validate derived p-values within each result."""

    for field in exact_fields:
        if current[field] != source[field]:
            raise RuntimeError(
                f"{label} replication mismatch: {field}: "
                f"current={current[field]!r} source={source[field]!r}"
            )
    for field in ("coefficient", "standard_error"):
        left = float(current[field])
        right = float(source[field])
        if not math.isclose(left, right, rel_tol=rel_tol, abs_tol=abs_tol):
            raise RuntimeError(
                f"{label} replication mismatch: {field}: "
                f"current={left:.17g} source={right:.17g}"
            )
    assert_normal_p_consistent(current, f"{label} current result")
    assert_normal_p_consistent(source, f"{label} source result")


def quantile(values: Any, probability: float) -> float:
    import numpy as np

    return float(np.quantile(values, probability, method="linear"))


def plus_one_two_sided(observed: float, simulated: Any) -> float:
    import numpy as np

    values = np.asarray(simulated, dtype=np.float64)
    lower = (1.0 + int(np.count_nonzero(values <= observed))) / (len(values) + 1.0)
    upper = (1.0 + int(np.count_nonzero(values >= observed))) / (len(values) + 1.0)
    return min(1.0, 2.0 * min(lower, upper))


def holm_adjust(p_values: dict[Any, float]) -> dict[Any, float]:
    ordered = sorted(p_values, key=lambda key: (p_values[key], str(key)))
    running = 0.0
    adjusted: dict[Any, float] = {}
    m = len(ordered)
    for index, key in enumerate(ordered):
        running = max(running, min(1.0, (m - index) * p_values[key]))
        adjusted[key] = running
    return adjusted


def bh_adjust(p_values: dict[Any, float]) -> dict[Any, float]:
    ordered = sorted(p_values, key=lambda key: (p_values[key], str(key)))
    m = len(ordered)
    adjusted: dict[Any, float] = {}
    running = 1.0
    for reverse_index in range(m - 1, -1, -1):
        key = ordered[reverse_index]
        rank = reverse_index + 1
        running = min(running, min(1.0, p_values[key] * m / rank))
        adjusted[key] = running
    return adjusted


def load_module(path: Path, name: str, expected_sha: str) -> Any:
    if sha256_file(path) != expected_sha:
        raise RuntimeError(f"Authority SHA mismatch: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def authenticate_git(repo: Path, script_path: Path) -> dict[str, str]:
    head = command_output(["git", "rev-parse", "HEAD"], cwd=repo)
    branch = command_output(["git", "branch", "--show-current"], cwd=repo)
    if branch != "main":
        raise RuntimeError("Additional-analysis estimator requires branch main")
    if command_output(["git", "status", "--porcelain=v1"], cwd=repo):
        raise RuntimeError("Additional-analysis estimator requires a clean repository")
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", EXPECTED_RECOVERY_COMMIT, head],
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
        ["git", "diff", "--quiet", "HEAD", "--", relative], cwd=repo, check=True
    )
    producer = command_output(["git", "log", "-1", "--format=%H", "--", relative], cwd=repo)
    if producer != head:
        raise RuntimeError("Additional-analysis script is not authoritative at current HEAD")
    return {"git_head": head, "script_producer_commit": producer}


def authenticate_payload(args: argparse.Namespace, script_path: Path) -> dict[str, Any]:
    project = args.project_root.resolve()
    repo = project / "replication_package"
    source_b2_code = repo / "code/10f_estimate_b2_first_grant_dynamics.py"
    source_estimator = repo / "code/10h_estimate_dynamic_second_wave.py"
    stage08 = repo / "code/08_make_core_paper_results.py"
    plan = repo / "docs/dynamic_prosociality_second_wave_postprimary_analysis.md"
    source_b2 = project / "output/dynamic_second_wave_b2_v100" / SOURCE_RUN_ID
    source_history = project / "output/dynamic_second_wave_history_v100" / SOURCE_RUN_ID
    source_results = project / "output/dynamic_second_wave_results_v100" / SOURCE_RUN_ID
    history_state = project / "derived/replication/dynamic_second_wave_history_v100_PRIVATE"
    estimation_state = project / "derived/replication/dynamic_second_wave_estimation_v100_PRIVATE"
    stage07 = project / "derived/replication/analysis_panel_24m_sf100k"
    core_state = project / "derived/replication/dynamic_prosociality_core_v102_PRIVATE"
    b1_sample = core_state / "b1_repeat_granter_private.parquet"
    b1_propensity = core_state / "b1_crossfit_propensity_private.parquet"
    state = project / "derived/replication/dynamic_second_wave_postprimary_v100_PRIVATE"
    output = project / "output/dynamic_second_wave_postprimary_v100"

    fixed_files = {
        source_b2_code: EXPECTED_SOURCE_B2_SCRIPT_SHA,
        source_estimator: EXPECTED_SOURCE_ESTIMATOR_SHA,
        stage08: EXPECTED_STAGE08_SHA,
        plan: EXPECTED_POSTPRIMARY_PLAN_SHA,
        source_b2 / "_SUCCESS.json": EXPECTED_SOURCE_B2_SUCCESS_SHA,
        source_history / "_SUCCESS.json": EXPECTED_SOURCE_HISTORY_SUCCESS_SHA,
        source_results / "_SUCCESS.json": EXPECTED_SOURCE_RESULTS_SUCCESS_SHA,
        b1_sample: EXPECTED_B1_SAMPLE_SHA,
        b1_propensity: EXPECTED_B1_PROPENSITY_SHA,
    }
    for path, wanted in fixed_files.items():
        if not path.is_file():
            raise RuntimeError(f"Required authority is missing: {path}")
        actual = sha256_file(path)
        if actual != wanted:
            raise RuntimeError(f"Authority SHA mismatch: {path}: {actual}")

    statuses = (
        (source_b2, "DYNAMIC_SECOND_WAVE_B2_V100_OK"),
        (source_history, "DYNAMIC_SECOND_WAVE_HISTORY_V100_OK"),
        (source_results, "DYNAMIC_SECOND_WAVE_RESULTS_V100_OK"),
    )
    for root, status in statuses:
        if load_json(root / "_SUCCESS.json").get("status") != status:
            raise RuntimeError(f"Source status mismatch: {root}")

    source_history_success = load_json(source_history / "_SUCCESS.json")
    user_paths = [
        history_state / "user_history_processed" / f"bucket_{bucket:02d}.parquet"
        for bucket in range(16)
    ]
    pair_paths = [
        history_state / "pair_history_processed" / f"bucket_{bucket:02d}.parquet"
        for bucket in range(16)
    ]
    target = history_state / "stage07_sampled_targets_private.parquet"
    if not all(path.is_file() for path in [*user_paths, *pair_paths, target]):
        raise RuntimeError("Private history bundle is incomplete")
    if sha256_file(target) != source_history_success["private_target_sha256"]:
        raise RuntimeError("Private target SHA mismatch")
    if sha256_json([sha256_file(path) for path in user_paths]) != source_history_success[
        "private_user_bucket_bundle_sha256"
    ]:
        raise RuntimeError("Private user-history bundle SHA mismatch")
    if sha256_json([sha256_file(path) for path in pair_paths]) != source_history_success[
        "private_pair_bucket_bundle_sha256"
    ]:
        raise RuntimeError("Private pair-history bundle SHA mismatch")

    git = authenticate_git(repo, script_path)
    stage07_paths = [
        stage07 / f"month={month}/analysis_panel.parquet"
        for month in (
            "2023-11", "2023-12", "2024-01", "2024-02", "2024-03", "2024-04",
            "2024-05", "2024-06", "2024-07", "2024-08", "2024-09", "2024-10",
            "2024-11", "2024-12", "2025-01", "2025-02", "2025-03", "2025-04",
            "2025-05", "2025-06", "2025-07", "2025-08", "2025-09", "2025-10",
        )
    ]
    if not all(path.is_file() for path in stage07_paths):
        raise RuntimeError("Stage 07 monthly panel is incomplete")

    authorities = {
        **git,
        "script_sha256": sha256_file(script_path),
        "postprimary_plan_sha256": sha256_file(plan),
        "source_b2_script_sha256": sha256_file(source_b2_code),
        "source_estimator_sha256": sha256_file(source_estimator),
        "stage08_sha256": sha256_file(stage08),
        "source_b2_success_sha256": sha256_file(source_b2 / "_SUCCESS.json"),
        "source_history_success_sha256": sha256_file(source_history / "_SUCCESS.json"),
        "source_results_success_sha256": sha256_file(source_results / "_SUCCESS.json"),
        "b1_sample_sha256": sha256_file(b1_sample),
        "b1_propensity_sha256": sha256_file(b1_propensity),
    }
    config = {
        "script_version": SCRIPT_VERSION,
        "source_run_id": SOURCE_RUN_ID,
        "output_run_id": args.run_id,
        "authorities": authorities,
        "randomizations": RANDOMIZATIONS,
        "randomization_batch": RANDOMIZATION_BATCH,
        "b2_seed": B2_SEED,
        "horizons_hours": list(HORIZONS_HOURS),
        "personal_offsets": list(PERSONAL_OFFSETS),
        "epistemic_status": "additional robustness and exploratory analyses",
    }
    return {
        "project": project,
        "repo": repo,
        "source_b2_code": source_b2_code,
        "source_estimator": source_estimator,
        "stage08": stage08,
        "plan": plan,
        "source_b2": source_b2,
        "source_history": source_history,
        "source_results": source_results,
        "history_state": history_state,
        "estimation_state": estimation_state,
        "stage07": stage07,
        "stage07_paths": stage07_paths,
        "user_paths": user_paths,
        "pair_paths": pair_paths,
        "target": target,
        "b1_sample": b1_sample,
        "b1_propensity": b1_propensity,
        "state": state,
        "output": output,
        "run_id": args.run_id,
        "workers": args.workers,
        "worker_memory": args.worker_memory,
        "authorities": authorities,
        "config": config,
        "config_sha256": sha256_json(config),
    }


def migrate_v101_startup_state(
    root: Path, saved: dict[str, Any], payload: dict[str, Any]
) -> bool:
    """Migrate only the exact empty state left by the v1.0.1 startup failure."""

    previous_config = saved.get("config")
    if not isinstance(previous_config, dict):
        return False
    if saved.get("status") != "DYNAMIC_SECOND_WAVE_POSTPRIMARY_PRIVATE_STATE_OK":
        return False
    if saved.get("config_sha256") != sha256_json(previous_config):
        return False
    expected_previous = {
        **payload["config"],
        "script_version": PREVIOUS_SCRIPT_VERSION,
        "authorities": {
            **payload["config"]["authorities"],
            "git_head": PREVIOUS_GIT_HEAD,
            "script_producer_commit": PREVIOUS_GIT_HEAD,
            "script_sha256": PREVIOUS_SCRIPT_SHA,
        },
    }
    if previous_config != expected_previous:
        return False
    expected_entries = {"CONFIG.json", "b2_randomizations", "duckdb_temp"}
    if {path.name for path in root.iterdir()} != expected_entries:
        return False
    b2_directory = root / "b2_randomizations"
    if not b2_directory.is_dir() or any(b2_directory.iterdir()):
        return False
    duckdb_directory = root / "duckdb_temp"
    if not duckdb_directory.is_dir():
        return False
    duckdb_entries = list(duckdb_directory.iterdir())
    if any(path.name != "model_E1" or not path.is_dir() for path in duckdb_entries):
        return False
    if any(path.is_file() or path.is_symlink() for path in duckdb_directory.rglob("*")):
        return False
    atomic_json(
        root / "CONFIG.json",
        {
            "status": "DYNAMIC_SECOND_WAVE_POSTPRIMARY_PRIVATE_STATE_OK",
            "created_utc": saved.get("created_utc", utc_now()),
            "updated_utc": utc_now(),
            "config": payload["config"],
            "config_sha256": payload["config_sha256"],
            "migrated_from_script_version": PREVIOUS_SCRIPT_VERSION,
            "privacy": "PRIVATE CHECKPOINTS; DO NOT COMMIT OR PUBLISH",
        },
    )
    print("POSTPRIMARY_V101_EMPTY_STARTUP_STATE_MIGRATED_OK", flush=True)
    return True


def initialize_state(payload: dict[str, Any]) -> None:
    root = payload["state"]
    root.mkdir(parents=True, exist_ok=True)
    config_path = root / "CONFIG.json"
    if config_path.is_file():
        saved = load_json(config_path)
        if saved.get("config") == payload["config"] and saved.get(
            "config_sha256"
        ) == payload["config_sha256"]:
            print("POSTPRIMARY_PRIVATE_STATE_AUTHENTICATED_OK", flush=True)
            return
        if migrate_v101_startup_state(root, saved, payload):
            return
        raise RuntimeError("Additional-analysis private-state configuration mismatch")
    if any(root.iterdir()):
        raise RuntimeError("Nonempty additional-analysis state lacks CONFIG.json")
    (root / "b2_randomizations").mkdir()
    (root / "duckdb_temp").mkdir()
    atomic_json(
        config_path,
        {
            "status": "DYNAMIC_SECOND_WAVE_POSTPRIMARY_PRIVATE_STATE_OK",
            "created_utc": utc_now(),
            "config": payload["config"],
            "config_sha256": payload["config_sha256"],
            "privacy": "PRIVATE CHECKPOINTS; DO NOT COMMIT OR PUBLISH",
        },
    )
    print("POSTPRIMARY_PRIVATE_STATE_CREATED", flush=True)


def dense_codes(values: Any) -> tuple[Any, int]:
    import numpy as np
    import pandas as pd

    codes, levels = pd.factorize(values, sort=False)
    codes = np.asarray(codes, dtype=np.int64)
    if np.any(codes < 0):
        raise ValueError("Fixed effect or cluster contains missing values")
    return codes, int(len(levels))


def demean_once(matrix: Any, codes: Any, levels: int) -> Any:
    import numpy as np

    result = np.asarray(matrix, dtype=np.float64).copy()
    counts = np.bincount(codes, minlength=levels).astype(np.float64)
    if np.any(counts <= 0):
        raise ValueError("Fixed-effect codes are not dense")
    for column in range(result.shape[1]):
        sums = np.bincount(codes, weights=result[:, column], minlength=levels)
        result[:, column] -= (sums / counts)[codes]
    return result


def maximum_scaled_group_mean(
    matrix: Any, effects: Sequence[tuple[Any, int]], source: Any
) -> float:
    import numpy as np

    matrix = np.asarray(matrix, dtype=np.float64)
    source = np.asarray(source, dtype=np.float64)
    scales = np.maximum(np.sqrt(np.mean(np.square(source), axis=0)), 1.0)
    maximum = 0.0
    for codes, levels in effects:
        counts = np.bincount(codes, minlength=levels).astype(np.float64)
        valid = counts > 0
        for column in range(matrix.shape[1]):
            sums = np.bincount(codes, weights=matrix[:, column], minlength=levels)
            means = np.zeros(levels, dtype=np.float64)
            means[valid] = sums[valid] / counts[valid]
            maximum = max(maximum, float(np.max(np.abs(means[valid]))) / scales[column])
    return maximum


def absorb_multiway(
    matrix: Any,
    fixed_effect_codes: Sequence[Any],
    *,
    tolerance: float = 1e-9,
    maximum_iterations: int = 10_000,
) -> tuple[Any, int, float]:
    import numpy as np

    source = np.asarray(matrix, dtype=np.float64)
    result = source.copy()
    effects = []
    for values in fixed_effect_codes:
        codes, levels = dense_codes(values)
        effects.append((codes, levels))
    if len(effects) < 1:
        return result, 0, 0.0
    orthogonality = math.inf
    for iteration in range(1, maximum_iterations + 1):
        for codes, levels in effects:
            result = demean_once(result, codes, levels)
        if iteration <= 5 or iteration % 5 == 0:
            orthogonality = maximum_scaled_group_mean(result, effects, source)
            if orthogonality <= tolerance:
                return result, iteration, orthogonality
    raise RuntimeError(
        f"Multiway absorption failed to converge: iterations={maximum_iterations}, "
        f"orthogonality={orthogonality:.3e}"
    )


def cluster_meat(x: Any, residual: Any, values: Any) -> tuple[Any, int]:
    import numpy as np

    codes, groups = dense_codes(values)
    scores = np.column_stack(
        [
            np.bincount(codes, weights=x[:, column] * residual, minlength=groups)
            for column in range(x.shape[1])
        ]
    )
    return scores.T @ scores, groups


def fit_absorbed_lpm(
    y: Any,
    x: Any,
    x_names: Sequence[str],
    fixed_effect_codes: Sequence[Any],
    chooser_cluster: Any,
    assignment_cluster: Any,
) -> dict[str, Any]:
    import numpy as np

    y = np.asarray(y, dtype=np.float64)
    x = np.asarray(x, dtype=np.float64)
    chooser = np.asarray(chooser_cluster)
    assignment = np.asarray(assignment_cluster)
    finite = np.isfinite(y) & np.all(np.isfinite(x), axis=1)
    y, x, chooser, assignment = y[finite], x[finite], chooser[finite], assignment[finite]
    fixed = [np.asarray(values)[finite] for values in fixed_effect_codes]
    n_raw = len(y)
    transformed, iterations, orthogonality = absorb_multiway(
        np.column_stack([y, x]), fixed
    )
    y = transformed[:, 0]
    x = transformed[:, 1:]
    identifying = np.any(np.abs(x) > 1e-14, axis=1)
    y, x = y[identifying], x[identifying]
    chooser, assignment = chooser[identifying], assignment[identifying]
    n, k = x.shape
    if n <= k:
        raise RuntimeError(f"Too few identifying rows: n={n}, k={k}")
    xtx = x.T @ x
    rank = int(np.linalg.matrix_rank(xtx))
    inverse = np.linalg.pinv(xtx, hermitian=True)
    beta = inverse @ (x.T @ y)
    residual = y - x @ beta

    chooser_meat, chooser_groups = cluster_meat(x, residual, chooser)
    assignment_meat, assignment_groups = cluster_meat(x, residual, assignment)
    chooser_codes, _ = dense_codes(chooser)
    assignment_codes, assignment_levels = dense_codes(assignment)
    intersection = chooser_codes.astype(np.int64) * assignment_levels + assignment_codes
    intersection_meat, intersection_groups = cluster_meat(x, residual, intersection)

    def corrected(meat: Any, groups: int) -> Any:
        if groups <= 1:
            return meat
        return meat * (groups / (groups - 1.0)) * ((n - 1.0) / (n - k))

    covariance_chooser = inverse @ corrected(chooser_meat, chooser_groups) @ inverse
    covariance_two_way = inverse @ (
        corrected(chooser_meat, chooser_groups)
        + corrected(assignment_meat, assignment_groups)
        - corrected(intersection_meat, intersection_groups)
    ) @ inverse
    covariance_chooser = (covariance_chooser + covariance_chooser.T) / 2.0
    covariance_two_way = (covariance_two_way + covariance_two_way.T) / 2.0
    return {
        "rows_raw": int(n_raw),
        "rows_identifying": int(n),
        "matrix_rank": rank,
        "x_names": list(x_names),
        "beta": beta,
        "covariance_chooser": covariance_chooser,
        "covariance_two_way": covariance_two_way,
        "chooser_clusters": chooser_groups,
        "assignment_clusters": assignment_groups,
        "intersection_clusters": intersection_groups,
        "absorption_method": "multiway_cyclic_exact_to_tolerance",
        "absorption_iterations": iterations,
        "absorption_max_scaled_group_mean": orthogonality,
    }


def scaled_e1_row(
    fit: dict[str, Any],
    covariance_name: str,
    selected: Any,
    specification: str,
) -> dict[str, Any]:
    import numpy as np

    covariance = fit[covariance_name]
    beta = float(fit["beta"][0])
    variance = float(covariance[0, 0])
    standard_error = math.sqrt(variance) if variance >= 0 else math.nan
    p10, p90 = np.quantile(selected["re_pair_risk"], [0.1, 0.9])
    span = float(p90 - p10)
    coefficient = beta * span
    scaled_se = standard_error * span
    z_value = coefficient / scaled_se if scaled_se > 0 else math.nan
    lower = coefficient - 1.96 * scaled_se
    upper = coefficient + 1.96 * scaled_se
    return {
        "analysis": "E1_robustness",
        "specification": specification,
        "covariance": covariance_name.removeprefix("covariance_"),
        "rows_raw": fit["rows_raw"],
        "rows_identifying": fit["rows_identifying"],
        "chooser_clusters": fit["chooser_clusters"],
        "assignment_clusters": fit["assignment_clusters"],
        "intersection_clusters": fit["intersection_clusters"],
        "matrix_rank": fit["matrix_rank"],
        "coefficient_per_unit_risk": beta,
        "standard_error_per_unit_risk": standard_error,
        "risk_p10": float(p10),
        "risk_p90": float(p90),
        "risk_p90_minus_p10": span,
        "coefficient": coefficient,
        "coefficient_percentage_points": 100 * coefficient,
        "standard_error": scaled_se,
        "standard_error_percentage_points": 100 * scaled_se,
        "z_value": z_value,
        "p_value_two_sided": normal_p(z_value),
        "confidence_interval_95_low_pp": 100 * lower,
        "confidence_interval_95_high_pp": 100 * upper,
        "informative_null_upper_bound_pp": 100 * upper,
        "upper_bound_below_0_30pp": bool(100 * upper < 0.30),
        "outcome_mean": float(selected["kind_draw"].mean()),
        "relative_to_outcome_mean": coefficient / float(selected["kind_draw"].mean()),
        "absorption_method": fit["absorption_method"],
        "absorption_iterations": fit["absorption_iterations"],
        "absorption_max_scaled_group_mean": fit[
            "absorption_max_scaled_group_mean"
        ],
        "epistemic_status": "robustness",
    }


def e1_exact_fit(base: Any, frame: Any, selector: Any, specification: str) -> tuple[dict[str, Any], Any]:
    import numpy as np
    import pandas as pd

    selected = frame.loc[selector & frame["first_ever_pair"].astype(bool)].reset_index(drop=True)
    if len(selected) < 10_000:
        raise RuntimeError(f"E1 robustness subset is unexpectedly small: {specification}")
    controls, control_names = base.control_matrix(selected, "E1")
    redundant_prefixes = ("speed_", "rating_band_100_", "utc_block_6h_", "weekend_")
    keep = [
        index
        for index, name in enumerate(control_names)
        if not name.startswith(redundant_prefixes)
    ]
    controls = controls[:, keep]
    kept_names = [control_names[index] for index in keep]
    x = np.column_stack(
        [selected["re_pair_risk"].to_numpy(dtype=np.float64), controls]
    )
    chooser_codes, _ = dense_codes(selected["chooser_user_id"])
    month_codes, _ = dense_codes(selected["month"])
    cell_index = pd.MultiIndex.from_frame(
        selected[["speed", "rating_band_100", "utc_block_6h", "weekend"]]
    )
    cell_codes, _ = dense_codes(cell_index)
    # Cluster at the cell that actually assigned the score. Almost all rows are
    # level 1, but the few coarsened rows share scores over broader cells and must
    # not be treated as independent exact-cell assignments.
    level = selected["coarsening_level"].to_numpy(dtype=np.int64)
    rating_100 = selected["rating_band_100"].to_numpy(dtype=np.int64)
    rating_200 = (rating_100 // 200) * 200
    assigned = pd.DataFrame(
        {
            "month": selected["month"].astype(str),
            "level": level,
            "speed": selected["speed"].astype(str),
            "rating": np.where(level <= 2, rating_100, np.where(level <= 4, rating_200, -1)),
            "utc_block": np.where(level <= 3, selected["utc_block_6h"], -1),
            "weekend": np.where(level == 1, selected["weekend"], -1),
        }
    )
    assignment, _ = dense_codes(pd.MultiIndex.from_frame(assigned))
    fit = fit_absorbed_lpm(
        selected["kind_draw"].to_numpy(dtype=np.float64),
        x,
        ["re_pair_risk", *kept_names],
        (chooser_codes, month_codes, cell_codes),
        chooser_codes,
        assignment,
    )
    return fit, selected


def run_e1(payload: dict[str, Any], base: Any, stage08: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[Path]]:
    import numpy as np
    import pandas as pd

    original_state_config = load_json(payload["estimation_state"] / "CONFIG.json")
    original_config_sha = original_state_config.get("config_sha256")
    if original_state_config.get("status") != "DYNAMIC_SECOND_WAVE_ESTIMATION_PRIVATE_STATE_OK":
        raise RuntimeError("Original E1 private-state status mismatch")
    e1_paths: list[Path] = []
    for month in base.MAIN_MONTHS:
        authenticated = base.authenticate_e1_month(
            payload["estimation_state"], month, original_config_sha
        )
        if authenticated is None:
            raise RuntimeError(f"Cached E1 score is missing: {month}")
        e1_paths.append(base.e1_score_paths(payload["estimation_state"], month)[0])

    model_payload = {
        "stage07_paths": payload["stage07_paths"],
        "user_paths": payload["user_paths"],
        "state": payload["state"],
    }
    frame = base.stage07_frame(model_payload, "E1", e1_paths)
    source_fit = base.fit_panel_branch(stage08, frame, "E1")
    source_summary = load_json(payload["source_results"] / "summary.json")
    source_e1 = next(row for row in source_summary["models"] if row["analysis"] == "E1")
    assert_estimate_reproduced(
        source_fit,
        source_e1,
        "Source E1",
        exact_fields=("rows_raw", "rows_identifying", "chooser_clusters"),
        rel_tol=1e-12,
        abs_tol=1e-12,
    )

    rows: list[dict[str, Any]] = [
        {
            **{
                key: value
                for key, value in source_fit.items()
                if not isinstance(value, (dict, list))
            },
            "specification": "source_exact_replication",
            "covariance": "chooser",
            "epistemic_status": "source specification reproduced",
        }
    ]
    specifications = [
        ("exact_cell_full", np.ones(len(frame), dtype=bool)),
        ("exact_cell_coarsening_level_1", frame["coarsening_level"].to_numpy() == 1),
        ("exact_cell_leave_pair_out_n_ge_50", frame["leave_pair_out_n"].to_numpy() >= 50),
        ("exact_cell_leave_pair_out_n_ge_100", frame["leave_pair_out_n"].to_numpy() >= 100),
        ("exact_cell_leave_pair_out_n_ge_500", frame["leave_pair_out_n"].to_numpy() >= 500),
    ]
    for specification, selector in specifications:
        print(f"E1_ROBUSTNESS_BEGIN specification={specification}", flush=True)
        fit, selected = e1_exact_fit(base, frame, selector, specification)
        covariance_names = (
            ("covariance_chooser", "covariance_two_way")
            if specification == "exact_cell_full"
            else ("covariance_two_way",)
        )
        for covariance_name in covariance_names:
            rows.append(scaled_e1_row(fit, covariance_name, selected, specification))
        print(
            f"E1_ROBUSTNESS_OK specification={specification} "
            f"rows={fit['rows_raw']:,} iterations={fit['absorption_iterations']}",
            flush=True,
        )

    first = frame.loc[frame["first_ever_pair"].astype(bool)].copy()
    first["risk_decile"] = pd.qcut(
        first["re_pair_risk"], 10, labels=False, duplicates="drop"
    )
    deciles = []
    for decile, group in first.groupby("risk_decile", sort=True, observed=True):
        deciles.append(
            {
                "risk_decile": int(decile) + 1,
                "rows": int(len(group)),
                "choosers": int(group["chooser_user_id"].nunique()),
                "risk_mean": float(group["re_pair_risk"].mean()),
                "risk_min": float(group["re_pair_risk"].min()),
                "risk_max": float(group["re_pair_risk"].max()),
                "kind_rate": float(group["kind_draw"].mean()),
                "kind_rate_percentage_points": 100 * float(group["kind_draw"].mean()),
                "epistemic_status": "descriptive",
            }
        )
    return rows, deciles, e1_paths


def b2_event_metrics(times: Any, choices: Any, payoffs: Any) -> dict[str, Any]:
    import numpy as np

    choices = np.asarray(choices, dtype=bool)
    if choices.ndim == 1:
        choices = choices[None, :]
    simulations, n = choices.shape
    if n == 0 or np.any(np.count_nonzero(choices, axis=1) < 1):
        raise RuntimeError("Every B2 sequence must contain a kind draw")
    times = np.asarray(times, dtype=np.int64)
    payoffs = np.asarray(payoffs, dtype=np.float64)
    first = np.argmax(choices, axis=1)
    cumulative = np.cumsum(choices, axis=1, dtype=np.int32)
    row = np.arange(simulations, dtype=np.int64)
    shape = (simulations, len(HORIZONS_HOURS))
    pooled_num = np.zeros(shape, dtype=np.int64)
    pooled_den = np.zeros(shape, dtype=np.int64)
    chooser_rate_sum = np.zeros(shape, dtype=np.float64)
    chooser_contributors = np.zeros(shape, dtype=np.int64)
    chooser_any_sum = np.zeros(shape, dtype=np.int64)
    group_shape = (simulations, len(PAYOFF_GROUPS), len(HORIZONS_HOURS))
    group_num = np.zeros(group_shape, dtype=np.int64)
    group_den = np.zeros(group_shape, dtype=np.int64)
    group_rate_sum = np.zeros(group_shape, dtype=np.float64)
    group_contributors = np.zeros(group_shape, dtype=np.int64)
    group_any_sum = np.zeros(group_shape, dtype=np.int64)
    first_payoff = payoffs[first]
    payoff_group = np.where(first_payoff < 0, 0, np.where(first_payoff > 0, 2, 1))
    for horizon_index, hours in enumerate(HORIZONS_HOURS):
        end = np.searchsorted(
            times, times[first] + int(hours * HOUR_MS), side="right"
        ) - 1
        denominator = np.maximum(end - first, 0)
        numerator = np.where(
            denominator > 0, cumulative[row, end] - cumulative[row, first], 0
        )
        contributing = denominator > 0
        rates = np.divide(
            numerator,
            denominator,
            out=np.zeros(simulations, dtype=np.float64),
            where=contributing,
        )
        pooled_num[:, horizon_index] = numerator
        pooled_den[:, horizon_index] = denominator
        chooser_rate_sum[:, horizon_index] = rates
        chooser_contributors[:, horizon_index] = contributing
        chooser_any_sum[:, horizon_index] = contributing & (numerator > 0)
        for group_index in range(len(PAYOFF_GROUPS)):
            selected = payoff_group == group_index
            group_num[selected, group_index, horizon_index] = numerator[selected]
            group_den[selected, group_index, horizon_index] = denominator[selected]
            group_rate_sum[selected, group_index, horizon_index] = rates[selected]
            group_contributors[selected, group_index, horizon_index] = contributing[selected]
            group_any_sum[selected, group_index, horizon_index] = (
                contributing[selected] & (numerator[selected] > 0)
            )
    return {
        "pooled_num": pooled_num,
        "pooled_den": pooled_den,
        "chooser_rate_sum": chooser_rate_sum,
        "chooser_contributors": chooser_contributors,
        "chooser_any_sum": chooser_any_sum,
        "group_num": group_num,
        "group_den": group_den,
        "group_rate_sum": group_rate_sum,
        "group_contributors": group_contributors,
        "group_any_sum": group_any_sum,
    }


def initialize_b2_worker(base_path: str, sample: str, propensity: str) -> None:
    import numpy as np

    for variable in (
        "OPENBLAS_NUM_THREADS",
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        os.environ[variable] = "1"
    global _B2_BASE, _B2_DATA, _B2_PROBABILITY, _B2_SLICES, _B2_SELECTIONS
    _B2_BASE = load_module(
        Path(base_path), "source_b2_worker", EXPECTED_SOURCE_B2_SCRIPT_SHA
    )
    _B2_DATA, _B2_PROBABILITY = _B2_BASE.load_inputs(
        Path(sample), Path(propensity)
    )
    _B2_SLICES = _B2_BASE.chooser_slices(_B2_DATA["chooser_index"])
    _B2_SELECTIONS = []
    for start, stop in _B2_SLICES:
        observed = _B2_DATA["kind_draw"][start:stop]
        log_odds = np.log(_B2_PROBABILITY[start:stop]) - np.log1p(
            -_B2_PROBABILITY[start:stop]
        )
        _B2_SELECTIONS.append(
            _B2_BASE.conditional_selection_probabilities(
                log_odds, int(np.count_nonzero(observed))
            )
        )


def simulate_b2_batch(simulations: int, start_seed: int, stop_seed: int) -> dict[str, Any]:
    import numpy as np

    if any(
        value is None
        for value in (_B2_BASE, _B2_DATA, _B2_PROBABILITY, _B2_SLICES, _B2_SELECTIONS)
    ):
        raise RuntimeError("B2 worker is not initialized")
    rng = np.random.default_rng(
        np.random.SeedSequence([B2_SEED, start_seed, stop_seed])
    )
    totals: dict[str, Any] | None = None
    for chooser_number, (start, stop) in enumerate(_B2_SLICES):
        selection = _B2_SELECTIONS[chooser_number]
        observed = _B2_DATA["kind_draw"][start:stop]
        n = stop - start
        k = int(np.count_nonzero(observed))
        remaining = np.full(simulations, k, dtype=np.int32)
        choices = np.zeros((simulations, n), dtype=bool)
        for position in range(n):
            left = n - position
            forced = remaining == left
            probability_now = selection[position, remaining]
            chosen = forced | (
                (remaining > 0) & (rng.random(simulations) < probability_now)
            )
            choices[:, position] = chosen
            remaining -= chosen.astype(np.int32)
        if np.any(remaining != 0):
            raise RuntimeError("Conditional B2 sampler changed chooser totals")
        current = b2_event_metrics(
            _B2_DATA["utc_ms"][start:stop],
            choices,
            _B2_DATA["current_draw_payoff"][start:stop],
        )
        if totals is None:
            totals = {key: np.zeros_like(value) for key, value in current.items()}
        for key in totals:
            totals[key] += current[key]
        if (chooser_number + 1) % 10_000 == 0:
            print(
                f"B2_POSTPRIMARY_PROGRESS batch={start_seed + 1}-{stop_seed} "
                f"choosers={chooser_number + 1:,}/{len(_B2_SLICES):,}",
                flush=True,
            )
    if totals is None:
        raise RuntimeError("No B2 totals were generated")
    return totals


def b2_checkpoint_paths(state: Path, start: int, stop: int) -> tuple[Path, Path]:
    path = state / "b2_randomizations" / f"post_b2_{start:04d}_{stop - 1:04d}.npz"
    return path, path.with_suffix(".json")


def authenticate_b2_checkpoint(
    state: Path, start: int, stop: int, config_sha: str
) -> dict[str, Any] | None:
    import numpy as np

    path, receipt = b2_checkpoint_paths(state, start, stop)
    if not path.exists() and not receipt.exists():
        return None
    if not path.is_file() or not receipt.is_file():
        raise RuntimeError(f"Incomplete B2 additional-analysis checkpoint: {start}")
    saved = load_json(receipt)
    expected = {
        "status": "DYNAMIC_B2_POSTPRIMARY_BATCH_OK",
        "config_sha256": config_sha,
        "start": start,
        "stop_exclusive": stop,
        "seed_components": [B2_SEED, start, stop],
        "output_sha256": sha256_file(path),
        "output_bytes": path.stat().st_size,
    }
    for key, value in expected.items():
        if saved.get(key) != value:
            raise RuntimeError(f"B2 checkpoint mismatch {start}: {key}")
    loaded = np.load(path)
    expected_shapes = {
        "pooled_num": (stop - start, len(HORIZONS_HOURS)),
        "pooled_den": (stop - start, len(HORIZONS_HOURS)),
        "chooser_rate_sum": (stop - start, len(HORIZONS_HOURS)),
        "chooser_contributors": (stop - start, len(HORIZONS_HOURS)),
        "chooser_any_sum": (stop - start, len(HORIZONS_HOURS)),
        "group_num": (stop - start, len(PAYOFF_GROUPS), len(HORIZONS_HOURS)),
        "group_den": (stop - start, len(PAYOFF_GROUPS), len(HORIZONS_HOURS)),
        "group_rate_sum": (stop - start, len(PAYOFF_GROUPS), len(HORIZONS_HOURS)),
        "group_contributors": (stop - start, len(PAYOFF_GROUPS), len(HORIZONS_HOURS)),
        "group_any_sum": (stop - start, len(PAYOFF_GROUPS), len(HORIZONS_HOURS)),
    }
    for name, shape in expected_shapes.items():
        if loaded[name].shape != shape:
            raise RuntimeError(f"B2 checkpoint shape mismatch: {name}")
    return saved


def b2_worker(start: int, stop: int, state_text: str, config_sha: str) -> dict[str, Any]:
    state = Path(state_text)
    path, receipt = b2_checkpoint_paths(state, start, stop)
    if path.exists() or receipt.exists():
        raise RuntimeError(f"Worker received existing checkpoint: {start}")
    started = time.time()
    arrays = simulate_b2_batch(stop - start, start, stop)
    atomic_npz(path, **arrays)
    saved = {
        "status": "DYNAMIC_B2_POSTPRIMARY_BATCH_OK",
        "created_utc": utc_now(),
        "config_sha256": config_sha,
        "start": start,
        "stop_exclusive": stop,
        "seed_components": [B2_SEED, start, stop],
        "output_sha256": sha256_file(path),
        "output_bytes": path.stat().st_size,
        "runtime_seconds": time.time() - started,
    }
    atomic_json(receipt, saved)
    return saved


def aggregate_observed_b2(base_b2: Any, data: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    import numpy as np

    totals: dict[str, Any] | None = None
    follow_counts = {hours: [] for hours in HORIZONS_HOURS}
    follow_rates = {hours: [] for hours in HORIZONS_HOURS}
    for start, stop in base_b2.chooser_slices(data["chooser_index"]):
        choices = data["kind_draw"][start:stop]
        current = b2_event_metrics(
            data["utc_ms"][start:stop], choices, data["current_draw_payoff"][start:stop]
        )
        if totals is None:
            totals = {key: np.zeros_like(value) for key, value in current.items()}
        for key in totals:
            totals[key] += current[key]
        for horizon_index, hours in enumerate(HORIZONS_HOURS):
            denominator = int(current["pooled_den"][0, horizon_index])
            numerator = int(current["pooled_num"][0, horizon_index])
            if denominator > 0:
                follow_counts[hours].append(denominator)
                follow_rates[hours].append(numerator / denominator)
    if totals is None:
        raise RuntimeError("No observed B2 data")
    distribution = []
    for hours in HORIZONS_HOURS:
        counts = np.asarray(follow_counts[hours], dtype=np.float64)
        rates = np.asarray(follow_rates[hours], dtype=np.float64)
        for probability in (0.0, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99, 1.0):
            distribution.append(
                {
                    "horizon_hours": hours,
                    "quantile": probability,
                    "contributing_choosers": int(len(counts)),
                    "followup_opportunity_count": quantile(counts, probability),
                    "within_chooser_kind_share": quantile(rates, probability),
                    "epistemic_status": "descriptive",
                }
            )
    return totals, distribution


def summarize_metric(observed: float, simulated: Any) -> dict[str, Any]:
    import numpy as np

    simulated = np.asarray(simulated, dtype=np.float64)
    finite = simulated[np.isfinite(simulated)]
    if len(finite) != RANDOMIZATIONS:
        raise RuntimeError("A B2 randomization metric is nonfinite")
    mean = float(np.mean(finite))
    return {
        "observed": observed,
        "null_mean": mean,
        "excess": observed - mean,
        "null_p025": quantile(finite, 0.025),
        "null_p975": quantile(finite, 0.975),
        "randomization_p_two_sided": plus_one_two_sided(observed, finite),
        "randomizations": RANDOMIZATIONS,
    }


def run_b2(payload: dict[str, Any], base_b2: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    import numpy as np

    data, probability = base_b2.load_inputs(
        payload["b1_sample"], payload["b1_propensity"]
    )
    if len(data["kind_draw"]) != EXPECTED_B2_ROWS:
        raise RuntimeError("B2 input row total changed")
    observed, distribution = aggregate_observed_b2(base_b2, data)
    specs = [
        (start, min(start + RANDOMIZATION_BATCH, RANDOMIZATIONS))
        for start in range(0, RANDOMIZATIONS, RANDOMIZATION_BATCH)
    ]
    pending = [
        (start, stop)
        for start, stop in specs
        if authenticate_b2_checkpoint(
            payload["state"], start, stop, payload["config_sha256"]
        )
        is None
    ]
    print(
        f"B2_POSTPRIMARY_CHECKPOINTS existing={len(specs) - len(pending)} "
        f"pending={len(pending)} workers={payload['workers']}",
        flush=True,
    )
    if pending:
        context = mp.get_context("spawn")
        with ProcessPoolExecutor(
            max_workers=min(payload["workers"], len(pending)),
            mp_context=context,
            initializer=initialize_b2_worker,
            initargs=(
                str(payload["source_b2_code"]),
                str(payload["b1_sample"]),
                str(payload["b1_propensity"]),
            ),
        ) as executor:
            futures = {
                executor.submit(
                    b2_worker,
                    start,
                    stop,
                    str(payload["state"]),
                    payload["config_sha256"],
                ): (start, stop)
                for start, stop in pending
            }
            for future in as_completed(futures):
                saved = future.result()
                print(
                    f"B2_POSTPRIMARY_BATCH_OK start={saved['start']} "
                    f"stop={saved['stop_exclusive']} seconds={saved['runtime_seconds']:.1f}",
                    flush=True,
                )
    arrays: dict[str, list[Any]] = {}
    for start, stop in specs:
        authenticate_b2_checkpoint(
            payload["state"], start, stop, payload["config_sha256"]
        )
        path, _ = b2_checkpoint_paths(payload["state"], start, stop)
        loaded = np.load(path)
        for name in loaded.files:
            arrays.setdefault(name, []).append(np.asarray(loaded[name]))
    simulated = {name: np.concatenate(parts, axis=0) for name, parts in arrays.items()}

    horizon_rows: list[dict[str, Any]] = []
    for horizon_index, hours in enumerate(HORIZONS_HOURS):
        metrics = {
            "opportunity_weighted_kind_rate": (
                float(observed["pooled_num"][0, horizon_index] / observed["pooled_den"][0, horizon_index]),
                simulated["pooled_num"][:, horizon_index]
                / simulated["pooled_den"][:, horizon_index],
            ),
            "chooser_equal_kind_rate": (
                float(observed["chooser_rate_sum"][0, horizon_index] / observed["chooser_contributors"][0, horizon_index]),
                simulated["chooser_rate_sum"][:, horizon_index]
                / simulated["chooser_contributors"][:, horizon_index],
            ),
            "chooser_any_subsequent_kind_share": (
                float(observed["chooser_any_sum"][0, horizon_index] / observed["chooser_contributors"][0, horizon_index]),
                simulated["chooser_any_sum"][:, horizon_index]
                / simulated["chooser_contributors"][:, horizon_index],
            ),
            "distinct_contributing_choosers": (
                float(observed["chooser_contributors"][0, horizon_index]),
                simulated["chooser_contributors"][:, horizon_index].astype(np.float64),
            ),
        }
        for metric, (observed_value, simulated_values) in metrics.items():
            result = summarize_metric(observed_value, simulated_values)
            if "rate" in metric or "share" in metric:
                result.update(
                    {
                        "observed_percentage_points": 100 * result["observed"],
                        "null_mean_percentage_points": 100 * result["null_mean"],
                        "excess_percentage_points": 100 * result["excess"],
                    }
                )
            horizon_rows.append(
                {
                    "analysis": "B2_robustness",
                    "horizon_hours": hours,
                    "metric": metric,
                    **result,
                    "epistemic_status": "robustness",
                }
            )

    # Exact reproduction check for the three source pooled horizons.
    with (payload["source_b2"] / "b2_first_grant_horizons.csv").open(
        encoding="utf-8", newline=""
    ) as stream:
        source_rows = list(csv.DictReader(stream))
    for source in source_rows:
        hours = float(source["horizon_hours"])
        row = next(
            item
            for item in horizon_rows
            if item["horizon_hours"] == hours
            and item["metric"] == "opportunity_weighted_kind_rate"
        )
        if not math.isclose(row["observed"], float(source["observed_rate"]), abs_tol=1e-15):
            raise RuntimeError("B2 observed reproduction failed")
        if not math.isclose(row["null_mean"], float(source["null_mean_rate"]), abs_tol=1e-15):
            raise RuntimeError("B2 randomization reproduction failed")
        if row["randomization_p_two_sided"] != float(source["randomization_p_two_sided"]):
            raise RuntimeError("B2 p-value reproduction failed")

    horizon_24 = HORIZONS_HOURS.index(24.0)
    payoff_rows: list[dict[str, Any]] = []
    group_chooser_rates = observed["group_rate_sum"][0, :, horizon_24] / observed[
        "group_contributors"
    ][0, :, horizon_24]
    simulated_group_chooser_rates = simulated["group_rate_sum"][:, :, horizon_24] / simulated[
        "group_contributors"
    ][:, :, horizon_24]
    for group_index, group in enumerate(PAYOFF_GROUPS):
        metrics = {
            "opportunity_weighted_kind_rate": (
                float(observed["group_num"][0, group_index, horizon_24] / observed["group_den"][0, group_index, horizon_24]),
                simulated["group_num"][:, group_index, horizon_24]
                / simulated["group_den"][:, group_index, horizon_24],
            ),
            "chooser_equal_kind_rate": (
                float(group_chooser_rates[group_index]),
                simulated_group_chooser_rates[:, group_index],
            ),
            "chooser_any_subsequent_kind_share": (
                float(observed["group_any_sum"][0, group_index, horizon_24] / observed["group_contributors"][0, group_index, horizon_24]),
                simulated["group_any_sum"][:, group_index, horizon_24]
                / simulated["group_contributors"][:, group_index, horizon_24],
            ),
            "distinct_contributing_choosers": (
                float(observed["group_contributors"][0, group_index, horizon_24]),
                simulated["group_contributors"][:, group_index, horizon_24].astype(np.float64),
            ),
        }
        for metric, values in metrics.items():
            result = summarize_metric(*values)
            if "rate" in metric or "share" in metric:
                result.update(
                    {
                        "observed_percentage_points": 100 * result["observed"],
                        "null_mean_percentage_points": 100 * result["null_mean"],
                        "excess_percentage_points": 100 * result["excess"],
                    }
                )
            payoff_rows.append(
                {
                    "analysis": "B2_payoff_group_robustness",
                    "horizon_hours": 24.0,
                    "first_grant_payoff_group": group,
                    "metric": metric,
                    **result,
                    "epistemic_status": "robustness",
                }
            )
    observed_difference = float(group_chooser_rates[0] - group_chooser_rates[2])
    simulated_difference = (
        simulated_group_chooser_rates[:, 0] - simulated_group_chooser_rates[:, 2]
    )
    costly_vs_favorable = {
        "analysis": "B2_chooser_equal_costly_minus_favorable",
        "horizon_hours": 24.0,
        **summarize_metric(observed_difference, simulated_difference),
        "observed_difference_percentage_points": 100 * observed_difference,
        "epistemic_status": "robustness",
    }
    return horizon_rows, payoff_rows, costly_vs_favorable, distribution


def salience_public(result: dict[str, Any]) -> dict[str, Any]:
    excluded = {"coefficient_names", "cluster_levels", "coefficient_influence"}
    return {key: value for key, value in result.items() if key not in excluded}


def contrast_from_influences(base: Any, results: dict[int, dict[str, Any]], offsets: Sequence[int]) -> dict[str, Any]:
    true = results[0]
    comparator = list(offsets)
    weights = {0: 1.0, **{offset: -1.0 / len(comparator) for offset in comparator}}
    contrast = sum(weights[offset] * results[offset]["coefficient"] for offset in weights)
    variance = 0.0
    for left, left_weight in weights.items():
        for right, right_weight in weights.items():
            variance += (
                left_weight
                * right_weight
                * base.influence_covariance(results[left], results[right])
            )
    standard_error = math.sqrt(max(variance, 0.0))
    z_value = contrast / standard_error if standard_error > 0 else math.nan
    return {
        "analysis": "F2_personal_peak_offset_specificity",
        "true_offset": 0,
        "comparator_offsets": list(comparator),
        "comparator_rule": "nonzero offsets with primary rows between 0.5x and 2.0x zero-offset rows",
        "true_coefficient": true["coefficient"],
        "true_minus_comparator_average": contrast,
        "true_minus_comparator_average_percentage_points": 100 * contrast,
        "standard_error": standard_error,
        "standard_error_percentage_points": 100 * standard_error,
        "z_value": z_value,
        "p_value_two_sided": normal_p(z_value),
        "epistemic_status": "exploratory",
    }


def run_personal_salience(payload: dict[str, Any], base: Any) -> tuple[list[dict[str, Any]], dict[str, Any], list[int]]:
    import duckdb

    connection = duckdb.connect()
    base.configure(
        connection,
        payload["worker_memory"],
        payload["state"] / "duckdb_temp/personal_offset_grid",
        4,
    )
    source = base.path_list_literal(payload["user_paths"])
    connection.execute(
        f"CREATE VIEW user_history AS SELECT * FROM read_parquet({source}, union_by_name=true)"
    )
    results: dict[int, dict[str, Any]] = {}
    public_rows: list[dict[str, Any]] = []
    for offset in PERSONAL_OFFSETS:
        print(f"PERSONAL_OFFSET_SALIENCE_BEGIN offset={offset:+d}", flush=True)
        frame = connection.execute(
            f"""
            SELECT
              user_id, game_id, utc_ms, speed, pre_rating, rating_diff,
              prior_same_pool_games, next_any_utc_ms, next_same_speed_utc_ms,
              'offset_{offset:+d}' AS grid,
              prior_pool_peak + ({offset}) AS threshold,
              post_rating - (prior_pool_peak + ({offset})) AS running,
              EXTRACT('year' FROM TO_TIMESTAMP(utc_ms / 1000.0)) * 12
                + EXTRACT('month' FROM TO_TIMESTAMP(utc_ms / 1000.0)) AS month_code
            FROM user_history
            WHERE rating_diff > 0 AND post_rating IS NOT NULL
              AND prior_pool_peak IS NOT NULL
              AND prior_same_pool_games >= 25
              AND utc_ms - first_prior_pool_utc_ms >= {365 * DAY_MS}
              AND pre_rating < prior_pool_peak + ({offset})
              AND ABS(post_rating - (prior_pool_peak + ({offset}))) <= 20
            """
        ).fetchdf()
        label = f"offset_{offset:+d}"
        primary_support = int(
            (
                (frame["running"].abs() < 10)
                & (frame["prior_same_pool_games"] >= 50)
            ).sum()
        )
        if primary_support < 500:
            public_rows.append(
                {
                    "analysis": "F2_personal_peak_offset_salience",
                    "branch": "personal",
                    "grid": label,
                    "offset": offset,
                    "rows": primary_support,
                    "status": "NOT_ESTIMATED_INSUFFICIENT_SUPPORT",
                    "minimum_required_rows": 500,
                    "epistemic_status": "exploratory",
                }
            )
            print(
                f"PERSONAL_OFFSET_SALIENCE_INSUFFICIENT_SUPPORT "
                f"offset={offset:+d} rows={primary_support:,}",
                flush=True,
            )
            continue
        try:
            result = base.fit_salience_grid(
                frame,
                branch="personal",
                grid=label,
                bandwidth=10,
                prior_games=50,
                stop_minutes=30,
            )
        except RuntimeError as error:
            if offset in {0, 37, 50}:
                raise
            public_rows.append(
                {
                    "analysis": "F2_personal_peak_offset_salience",
                    "branch": "personal",
                    "grid": label,
                    "offset": offset,
                    "rows": primary_support,
                    "status": "NOT_ESTIMATED_MODEL_FAILURE",
                    "failure": str(error),
                    "epistemic_status": "exploratory",
                }
            )
            print(
                f"PERSONAL_OFFSET_SALIENCE_MODEL_FAILURE "
                f"offset={offset:+d} error={error}",
                flush=True,
            )
            continue
        result["offset"] = offset
        results[offset] = result
        public = salience_public(result)
        public.update(
            {
                "offset": offset,
                "epistemic_status": "exploratory",
            }
        )
        public_rows.append(public)
        print(
            f"PERSONAL_OFFSET_SALIENCE_OK offset={offset:+d} rows={result['rows']:,} "
            f"coefficient_pp={100 * result['coefficient']:.6f}",
            flush=True,
        )
    connection.close()

    # The offset 0/+37/+50 rows must exactly reproduce the corresponding source
    # all-game primary models before the wider grid is interpreted.
    with (payload["source_results"] / "f2_salience_models.csv").open(
        encoding="utf-8", newline=""
    ) as stream:
        source_rows = list(csv.DictReader(stream))
    mapping = {0: "true", 37: "placebo_37", 50: "placebo_50"}
    for offset, grid in mapping.items():
        source = next(
            row
            for row in source_rows
            if row["branch"] == "personal"
            and row["grid"] == grid
            and row.get("sensitivity", "") == ""
        )
        assert_estimate_reproduced(
            results[offset], source, f"Personal salience offset {offset:+d}"
        )

    valid_p = {
        offset: float(result["p_value_two_sided"])
        for offset, result in results.items()
        if math.isfinite(float(result["p_value_two_sided"]))
    }
    holm = holm_adjust(valid_p)
    bh = bh_adjust(valid_p)
    for row in public_rows:
        row["holm_adjusted_p_value_across_offsets"] = holm.get(
            row["offset"], math.nan
        )
        row["bh_adjusted_p_value_across_offsets"] = bh.get(
            row["offset"], math.nan
        )
    true_rows = int(results[0]["rows"])
    comparators = [
        offset
        for offset in results
        if offset != 0
        and 0.5 * true_rows <= int(results[offset]["rows"]) <= 2.0 * true_rows
    ]
    if comparators:
        contrast = contrast_from_influences(base, results, comparators)
    else:
        contrast = {
            "analysis": "F2_personal_peak_offset_specificity",
            "status": "NOT_ESTIMATED_NO_SUPPORT_COMPARABLE_OFFSET",
            "true_offset": 0,
            "comparator_offsets": [],
            "comparator_rule": "nonzero offsets with primary rows between 0.5x and 2.0x zero-offset rows",
            "epistemic_status": "exploratory",
        }
    return public_rows, contrast, comparators


def fit_stage08_joint(
    base: Any,
    stage08: Any,
    frame: Any,
    predictor_names: Sequence[str],
    maximum_rd: int,
) -> tuple[dict[str, Any], Any]:
    import numpy as np
    import pandas as pd

    sample = (
        frame["kind_draw"].notna()
        & frame["chooser_rd"].notna()
        & (frame["chooser_rd"] <= maximum_rd)
    )
    selected = frame.loc[sample].reset_index(drop=True)
    controls, control_names = base.control_matrix(selected, "F2-P")
    key = selected[list(predictor_names)].to_numpy(dtype=np.float64)
    x = np.column_stack([key, controls])
    names = [*predictor_names, *control_names]
    chooser_codes, _ = pd.factorize(selected["chooser_user_id"], sort=False)
    month_codes, _ = pd.factorize(selected["month"], sort=True)
    result = stage08.fit_lpm_cluster(
        selected["kind_draw"].to_numpy(dtype=np.float64),
        x,
        names,
        chooser_codes.astype(np.int64),
        fixed_effect_codes=(chooser_codes.astype(np.int64), month_codes.astype(np.int64)),
    )
    return result, selected


def coefficient_rows(
    result: dict[str, Any],
    predictor_names: Sequence[str],
    analysis: str,
    maximum_rd: int,
    support: dict[str, int],
) -> list[dict[str, Any]]:
    import numpy as np

    rows = []
    for index, name in enumerate(predictor_names):
        coefficient = float(result["beta"][index])
        variance = float(result["covariance"][index, index])
        standard_error = math.sqrt(max(variance, 0.0))
        z_value = coefficient / standard_error if standard_error > 0 else math.nan
        rows.append(
            {
                "analysis": analysis,
                "maximum_chooser_rd": maximum_rd,
                "predictor": name,
                "treated_support": support[name],
                "rows_raw": result["n_rows_raw"],
                "rows_identifying": result["n_rows_identifying"],
                "chooser_clusters": result["n_clusters"],
                "coefficient": coefficient,
                "coefficient_percentage_points": 100 * coefficient,
                "standard_error": standard_error,
                "standard_error_percentage_points": 100 * standard_error,
                "z_value": z_value,
                "p_value_two_sided": normal_p(z_value),
                "confidence_interval_95_low_pp": 100 * (coefficient - 1.96 * standard_error),
                "confidence_interval_95_high_pp": 100 * (coefficient + 1.96 * standard_error),
                "epistemic_status": "exploratory",
            }
        )
    p_values = {
        row["predictor"]: row["p_value_two_sided"]
        for row in rows
        if math.isfinite(row["p_value_two_sided"])
    }
    holm = holm_adjust(p_values)
    bh = bh_adjust(p_values)
    for row in rows:
        row["holm_adjusted_p_value_within_model_predictors"] = holm.get(
            row["predictor"], math.nan
        )
        row["bh_adjusted_p_value_within_model_predictors"] = bh.get(
            row["predictor"], math.nan
        )
    return rows


def linear_contrast(
    result: dict[str, Any], weights: Sequence[float], label: str, maximum_rd: int
) -> dict[str, Any]:
    import numpy as np

    vector = np.zeros(len(result["beta"]), dtype=np.float64)
    vector[: len(weights)] = np.asarray(weights, dtype=np.float64)
    coefficient = float(vector @ result["beta"])
    variance = float(vector @ result["covariance"] @ vector)
    standard_error = math.sqrt(max(variance, 0.0))
    z_value = coefficient / standard_error if standard_error > 0 else math.nan
    return {
        "analysis": label,
        "maximum_chooser_rd": maximum_rd,
        "coefficient": coefficient,
        "coefficient_percentage_points": 100 * coefficient,
        "standard_error": standard_error,
        "standard_error_percentage_points": 100 * standard_error,
        "z_value": z_value,
        "p_value_two_sided": normal_p(z_value),
        "confidence_interval_95_low_pp": 100 * (coefficient - 1.96 * standard_error),
        "confidence_interval_95_high_pp": 100 * (coefficient + 1.96 * standard_error),
        "rows_raw": result["n_rows_raw"],
        "rows_identifying": result["n_rows_identifying"],
        "chooser_clusters": result["n_clusters"],
        "epistemic_status": "exploratory",
    }


def run_f2_downstream(
    payload: dict[str, Any],
    base: Any,
    stage08: Any,
    e1_paths: Sequence[Path],
    comparable_offsets: Sequence[int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    import numpy as np

    model_payload = {
        "stage07_paths": payload["stage07_paths"],
        "user_paths": payload["user_paths"],
        "state": payload["state"],
    }
    frame = base.stage07_frame(model_payload, "F2-R", e1_paths)
    personal_original_rows = []
    personal_joint_rows: list[dict[str, Any]] = []
    personal_contrasts: list[dict[str, Any]] = []
    round_rows: list[dict[str, Any]] = []

    for maximum_rd in (110, 80):
        original_fit = base.fit_panel_branch(stage08, frame, "F2-P", maximum_rd)
        original_fit["analysis"] = "F2-P_original_contrast"
        original_fit["epistemic_status"] = "exploratory"
        personal_original_rows.append(
            {
                key: value
                for key, value in original_fit.items()
                if not isinstance(value, (dict, list))
            }
        )

        personal_predictors = []
        for offset in PERSONAL_OFFSETS:
            name = f"peak_offset_{offset:+d}"
            frame[name] = (
                frame["prior_pool_peak"].notna()
                & (frame["post_draw"] < frame["prior_pool_peak"] + offset)
                & (frame["prior_pool_peak"] + offset <= frame["post_win"])
            ).astype(float)
            personal_predictors.append(name)
        personal_frame = frame.loc[frame["prior_pool_peak"].notna()].reset_index(drop=True)
        joint, selected = fit_stage08_joint(
            base, stage08, personal_frame, personal_predictors, maximum_rd
        )
        support = {
            name: int(np.count_nonzero(selected[name])) for name in personal_predictors
        }
        personal_joint_rows.extend(
            coefficient_rows(
                joint,
                personal_predictors,
                "F2-P_offset_grid_joint",
                maximum_rd,
                support,
            )
        )
        if comparable_offsets:
            weights = []
            for offset in PERSONAL_OFFSETS:
                if offset == 0:
                    weights.append(1.0)
                elif offset in comparable_offsets:
                    weights.append(-1.0 / len(comparable_offsets))
                else:
                    weights.append(0.0)
            contrast = linear_contrast(
                joint,
                weights,
                "F2-P_true_minus_support_comparable_offset_average",
                maximum_rd,
            )
            contrast["comparator_offsets"] = list(comparable_offsets)
        else:
            contrast = {
                "analysis": "F2-P_true_minus_support_comparable_offset_average",
                "maximum_chooser_rd": maximum_rd,
                "status": "NOT_ESTIMATED_NO_SUPPORT_COMPARABLE_OFFSET",
                "comparator_offsets": [],
                "epistemic_status": "exploratory",
            }
        personal_contrasts.append(contrast)

        round_predictors = ["round_true", "round_37", "round_50"]
        round_joint, round_selected = fit_stage08_joint(
            base, stage08, frame, round_predictors, maximum_rd
        )
        round_support = {
            name: int(np.count_nonzero(round_selected[name])) for name in round_predictors
        }
        round_rows.extend(
            coefficient_rows(
                round_joint,
                round_predictors,
                "F2-R_individual_pivotal_coefficients",
                maximum_rd,
                round_support,
            )
        )
        round_contrast = linear_contrast(
            round_joint,
            (1.0, -0.5, -0.5),
            "F2-R_true_minus_average_placebo_replication",
            maximum_rd,
        )
        source_round = base.fit_panel_branch(
            stage08, frame, "F2-R", maximum_rd
        )
        assert_estimate_reproduced(
            round_contrast,
            source_round,
            f"F2-R downstream RD {maximum_rd}",
        )
        round_contrast["source_result_reproduced"] = True
        round_rows.append(round_contrast)

    threshold_rows = []
    for maximum_rd in (110, 80):
        selected = frame.loc[
            frame["kind_draw"].notna()
            & frame["chooser_rd"].notna()
            & (frame["chooser_rd"] <= maximum_rd)
            & (frame["round_true"] == 1)
        ].copy()
        selected["crossed_threshold"] = (
            np.floor(selected["post_draw"] / 100.0) + 1
        ) * 100
        for threshold, group in selected.groupby("crossed_threshold", sort=True):
            threshold_rows.append(
                {
                    "analysis": "F2-R_true_pivotal_threshold_descriptive",
                    "maximum_chooser_rd": maximum_rd,
                    "crossed_round_threshold": int(threshold),
                    "rows": int(len(group)),
                    "choosers": int(group["chooser_user_id"].nunique()),
                    "kind_draws": int(group["kind_draw"].sum()),
                    "kind_rate": float(group["kind_draw"].mean()),
                    "kind_rate_percentage_points": 100 * float(group["kind_draw"].mean()),
                    "epistemic_status": "descriptive",
                }
            )
    return personal_original_rows, personal_joint_rows, personal_contrasts, [*round_rows, *threshold_rows]


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


def write_tsv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    fields = ("sha256", "bytes", "path")
    temporary = path.with_name(path.name + f".tmp.{uuid.uuid4().hex}")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=fields, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def write_results(
    payload: dict[str, Any],
    *,
    e1_rows: list[dict[str, Any]],
    e1_deciles: list[dict[str, Any]],
    b2_horizons: list[dict[str, Any]],
    b2_payoffs: list[dict[str, Any]],
    b2_contrast: dict[str, Any],
    b2_distribution: list[dict[str, Any]],
    personal_salience: list[dict[str, Any]],
    personal_salience_contrast: dict[str, Any],
    personal_original: list[dict[str, Any]],
    personal_joint: list[dict[str, Any]],
    personal_kindness_contrasts: list[dict[str, Any]],
    round_output: list[dict[str, Any]],
) -> Path:
    final = payload["output"] / payload["run_id"]
    if final.exists():
        success = final / "_SUCCESS.json"
        if success.is_file() and load_json(success).get("status") == "DYNAMIC_SECOND_WAVE_POSTPRIMARY_V100_OK":
            print(f"POSTPRIMARY_RESULTS_ALREADY_COMPLETE: {final}", flush=True)
            return final
        raise RuntimeError(f"Partial additional-analysis output exists: {final}")
    staging = final.with_name("." + final.name + f".tmp.{uuid.uuid4().hex}")
    staging.mkdir(parents=True, exist_ok=False)
    atomic_json(
        staging / "source_authorities.json",
        {
            "source_run_id": SOURCE_RUN_ID,
            "authorities": payload["authorities"],
            "config_sha256": payload["config_sha256"],
            "epistemic_status": "additional robustness and exploratory analyses",
        },
    )
    write_csv(staging / "e1_robustness.csv", e1_rows)
    write_csv(staging / "e1_risk_deciles.csv", e1_deciles)
    write_csv(staging / "b2_horizon_robustness.csv", b2_horizons)
    write_csv(staging / "b2_payoff_group_robustness.csv", b2_payoffs)
    atomic_json(staging / "b2_costly_vs_favorable_chooser_equal.json", b2_contrast)
    write_csv(staging / "b2_chooser_distribution.csv", b2_distribution)
    write_csv(staging / "f2_personal_salience_offset_grid.csv", personal_salience)
    atomic_json(staging / "f2_personal_salience_offset_contrast.json", personal_salience_contrast)
    write_csv(staging / "f2_personal_original_contrast.csv", personal_original)
    write_csv(staging / "f2_personal_kindness_offset_grid.csv", personal_joint)
    write_csv(staging / "f2_personal_kindness_contrasts.csv", personal_kindness_contrasts)
    # round_output mixes coefficient and descriptive rows intentionally; the analysis
    # field/status makes the distinction explicit in a single audit table.
    write_csv(staging / "f2_round_decomposition.csv", round_output)
    for name in (
        "f2_salience_density_and_balance.csv",
        "f2_salience_integer_support.csv",
        "f2_salience_threshold_models.csv",
    ):
        shutil.copy2(payload["source_results"] / name, staging / f"source_{name}")

    exact_cell = next(
        row
        for row in e1_rows
        if row.get("specification") == "exact_cell_full" and row.get("covariance") == "two_way"
    )
    b2_24 = next(
        row
        for row in b2_horizons
        if row["horizon_hours"] == 24.0 and row["metric"] == "chooser_equal_kind_rate"
    )
    personal_110 = next(
        row for row in personal_original if int(row["maximum_chooser_rd"]) == 110
    )
    summary = {
        "status": "DYNAMIC_SECOND_WAVE_POSTPRIMARY_V100_OK",
        "created_utc": utc_now(),
        "script_version": SCRIPT_VERSION,
        "source_run_id": SOURCE_RUN_ID,
        "run_id": payload["run_id"],
        "authorities": payload["authorities"],
        "config_sha256": payload["config_sha256"],
        "epistemic_status": "additional robustness and exploratory analyses",
        "headline_additional": {
            "e1_exact_cell_two_way": exact_cell,
            "b2_24h_chooser_equal": b2_24,
            "personal_salience_offset_contrast": personal_salience_contrast,
            "personal_original_contrast_rd110": personal_110,
            "b2_costly_minus_favorable_chooser_equal": b2_contrast,
        },
        "privacy": "Aggregate output only; identifiers and histories remain private.",
        "patron_profile_input_read": False,
    }
    atomic_json(staging / "summary.json", summary)
    report = manifest_rows(staging)
    write_tsv(staging / "report_file_hashes.tsv", report)
    success = {
        "status": "DYNAMIC_SECOND_WAVE_POSTPRIMARY_V100_OK",
        "created_utc": utc_now(),
        "run_id": payload["run_id"],
        "source_run_id": SOURCE_RUN_ID,
        "script_sha256": payload["authorities"]["script_sha256"],
        "git_head": payload["authorities"]["git_head"],
        "postprimary_plan_sha256": payload["authorities"]["postprimary_plan_sha256"],
        "source_b2_success_sha256": payload["authorities"]["source_b2_success_sha256"],
        "source_history_success_sha256": payload["authorities"]["source_history_success_sha256"],
        "source_results_success_sha256": payload["authorities"]["source_results_success_sha256"],
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


def self_test() -> None:
    import numpy as np

    rng = np.random.default_rng(20260822)
    n = 1_200
    chooser = np.repeat(np.arange(60), 20)
    month = np.tile(np.repeat(np.arange(6), 2), 100)
    cell = (chooser % 5 + month) % 7
    source = rng.normal(size=(n, 4))
    absorbed, iterations, orthogonality = absorb_multiway(
        source, (chooser, month, cell)
    )
    assert absorbed.shape == source.shape
    assert iterations > 0
    assert orthogonality < 1e-8

    y = rng.binomial(1, 0.2, size=n)
    x = rng.normal(size=(n, 3))
    assignment = month * 10 + cell
    fit = fit_absorbed_lpm(
        y, x, ("x1", "x2", "x3"), (chooser, month, cell), chooser, assignment
    )
    assert fit["rows_identifying"] > 1_000
    assert np.all(np.isfinite(fit["beta"]))
    assert np.all(np.isfinite(fit["covariance_chooser"]))
    assert np.all(np.isfinite(fit["covariance_two_way"]))

    times = np.array([0, HOUR_MS, 2 * HOUR_MS, 25 * HOUR_MS], dtype=np.int64)
    choices = np.array([True, False, True, False])
    metrics = b2_event_metrics(times, choices, np.array([-1.0, 0.0, 0.0, 0.0]))
    h3 = HORIZONS_HOURS.index(3.0)
    h24 = HORIZONS_HOURS.index(24.0)
    assert metrics["pooled_den"][0, h3] == 2
    assert metrics["pooled_num"][0, h3] == 1
    assert metrics["pooled_den"][0, h24] == 2
    assert metrics["chooser_contributors"][0, h3] == 1

    p = {"a": 0.01, "b": 0.03, "c": 0.2}
    assert holm_adjust(p)["a"] == 0.03
    assert 0 <= bh_adjust(p)["a"] <= 1
    estimate = {
        "coefficient": -0.005,
        "standard_error": 0.004,
        "p_value_two_sided": normal_p(-0.005 / 0.004),
    }
    assert_normal_p_consistent(estimate, "self-test estimate")
    print("DYNAMIC_SECOND_WAVE_POSTPRIMARY_V100_SELF_TEST_OK")


def execute(payload: dict[str, Any]) -> Path:
    started = time.time()
    final = payload["output"] / payload["run_id"]
    if final.is_dir() and (final / "_SUCCESS.json").is_file():
        if load_json(final / "_SUCCESS.json").get("status") != "DYNAMIC_SECOND_WAVE_POSTPRIMARY_V100_OK":
            raise RuntimeError(f"Invalid existing additional-analysis output: {final}")
        print(f"POSTPRIMARY_RESULTS_ALREADY_COMPLETE: {final}", flush=True)
        return final
    initialize_state(payload)
    base = load_module(
        payload["source_estimator"], "source_second_wave", EXPECTED_SOURCE_ESTIMATOR_SHA
    )
    base_b2 = load_module(
        payload["source_b2_code"], "source_b2", EXPECTED_SOURCE_B2_SCRIPT_SHA
    )
    stage08 = load_module(payload["stage08"], "source_stage08", EXPECTED_STAGE08_SHA)
    stage08.run_numerical_self_test()
    print("SOURCE_NUMERICAL_KERNEL_SELF_TEST_OK", flush=True)

    print("E1_POSTPRIMARY_BEGIN", flush=True)
    e1_rows, e1_deciles, e1_paths = run_e1(payload, base, stage08)
    print("E1_POSTPRIMARY_OK", flush=True)

    print("PERSONAL_SALIENCE_OFFSET_GRID_BEGIN", flush=True)
    personal_salience, personal_salience_contrast, comparable_offsets = run_personal_salience(
        payload, base
    )
    print("PERSONAL_SALIENCE_OFFSET_GRID_OK", flush=True)

    print("F2_DOWNSTREAM_POSTPRIMARY_BEGIN", flush=True)
    personal_original, personal_joint, personal_kindness_contrasts, round_output = run_f2_downstream(
        payload, base, stage08, e1_paths, comparable_offsets
    )
    print("F2_DOWNSTREAM_POSTPRIMARY_OK", flush=True)

    print("B2_POSTPRIMARY_BEGIN", flush=True)
    b2_horizons, b2_payoffs, b2_contrast, b2_distribution = run_b2(payload, base_b2)
    print("B2_POSTPRIMARY_OK", flush=True)

    final = write_results(
        payload,
        e1_rows=e1_rows,
        e1_deciles=e1_deciles,
        b2_horizons=b2_horizons,
        b2_payoffs=b2_payoffs,
        b2_contrast=b2_contrast,
        b2_distribution=b2_distribution,
        personal_salience=personal_salience,
        personal_salience_contrast=personal_salience_contrast,
        personal_original=personal_original,
        personal_joint=personal_joint,
        personal_kindness_contrasts=personal_kindness_contrasts,
        round_output=round_output,
    )
    print(f"DYNAMIC_SECOND_WAVE_POSTPRIMARY_V100_OK: {final}", flush=True)
    print(f"runtime_seconds: {time.time() - started:.1f}", flush=True)
    return final


def print_plan(payload: dict[str, Any]) -> None:
    print("DYNAMIC_SECOND_WAVE_POSTPRIMARY_V100_PLAN_OK")
    print("script_version:", SCRIPT_VERSION)
    print("script_sha256:", payload["authorities"]["script_sha256"])
    print("git_head:", payload["authorities"]["git_head"])
    print("source_run_id:", SOURCE_RUN_ID)
    print("run_id:", payload["run_id"])
    print("analysis_scope: additional robustness and exploratory analyses")
    print("randomizations:", RANDOMIZATIONS)
    print("horizons_hours:", HORIZONS_HOURS)
    print("personal_offsets:", PERSONAL_OFFSETS)
    print("workers:", payload["workers"])
    print("private_state:", payload["state"])
    print("aggregate_output:", payload["output"])


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    if args.self_test:
        self_test()
        return
    if args.workers < 1 or args.workers > 8:
        raise ValueError("--workers must be between 1 and 8")
    script_path = Path(__file__).resolve()
    payload = authenticate_payload(args, script_path)
    print_plan(payload)
    if args.execute:
        execute(payload)


if __name__ == "__main__":
    main()
