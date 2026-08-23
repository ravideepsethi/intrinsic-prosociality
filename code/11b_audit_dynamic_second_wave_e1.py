#!/usr/bin/env python3
"""Run the recovered independent numerical and specification audit of E1.

The audit reuses the authenticated E1 score Parquets and the locked Stage 07 panel.
It does not rebuild the all-game chronology.  It writes only aggregate diagnostics.
Version 1.0.1 excludes the Stage 08 exact two-way benchmark from the audit fits
because that solver deliberately accepts at most 512 levels in its smaller fixed
effect, whereas the E1 exact-cell specification has 671 levels.  Stage 08 remains
unchanged and is still used for its applicable source-result reproduction.
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
import subprocess
import time
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Sequence


PROJECT_ROOT = Path("/Volumes/XT_Pro/lichess_kindness")
SOURCE_RUN_ID = "20260822T150914Z"
POSTPRIMARY_RUN_ID = SOURCE_RUN_ID + "_postprimary_v100"
DEFAULT_RUN_ID = SOURCE_RUN_ID + "_e1_audit_v101"
SCRIPT_VERSION = "1.0.1"

EXPECTED_BASE_COMMIT = "6b494e94e015fcf3a253f4ee1580dd6f135a4d60"
EXPECTED_ADDITIONAL_SCRIPT_SHA = (
    "983e1f9ea4758aa3bb4ff22404c4a732ca993233f41ed1b7a52774a2caa5f5d2"
)
EXPECTED_SOURCE_ESTIMATOR_SHA = (
    "ae525dc989afa32bee49030feeaa86c37894448c121805fedc8a6f2fd31b15a4"
)
EXPECTED_STAGE08_SHA = (
    "e9dd80c52da5ffef3d406c3af25912bd924f6423f123ca535cf4077cb039c41f"
)
EXPECTED_SOURCE_RESULTS_SUCCESS_SHA = (
    "61f253c0ed8f8f64319f7d187c12ba53b1ba9fd331921e984ec47a88bead3d9f"
)
EXPECTED_SOURCE_RESULTS_SUMMARY_SHA = (
    "0bb71f639520fe21cd95a04eaab9afa3b78a6947126cf07c9e664d3f58616b73"
)
EXPECTED_POSTPRIMARY_SUCCESS_SHA = (
    "c6ca50a24958cf215249120552fb051ee43d5f4b13796983939a7d0b655a31a4"
)
EXPECTED_POSTPRIMARY_SUMMARY_SHA = (
    "013d218b8c6aecbc437bbb4488be6e4005035d05f71a93624da6a99b0e876749"
)

MAIN_MONTHS = (
    "2023-11", "2023-12", "2024-01", "2024-02", "2024-03", "2024-04",
    "2024-05", "2024-06", "2024-07", "2024-08", "2024-09", "2024-10",
    "2024-11", "2024-12", "2025-01", "2025-02", "2025-03", "2025-04",
    "2025-05", "2025-06", "2025-07", "2025-08", "2025-09", "2025-10",
)

AP_TOLERANCE = 1e-12
AP_MAXIMUM_ITERATIONS = 30_000
IDENTIFYING_ROW_TOLERANCE = 1e-10
SPECIFICATIONS = (
    "independent_schur_two_way",
    "tight_ap_same_spec_two_way",
    "assignment_unit_tight_ap_two_way",
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--workers", type=int, default=3)
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


def write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    if not rows:
        raise RuntimeError(f"Refusing to write empty CSV: {path}")
    fields = sorted({field for row in rows for field in row})
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{uuid.uuid4().hex}")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def write_tsv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    if not rows:
        raise RuntimeError(f"Refusing to write empty TSV: {path}")
    fields = list(rows[0])
    temporary = path.with_name(path.name + f".tmp.{uuid.uuid4().hex}")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=fields, delimiter="\t", lineterminator="\n"
        )
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


def load_module(path: Path, name: str, expected_sha: str) -> Any:
    if sha256_file(path) != expected_sha:
        raise RuntimeError(f"Module SHA mismatch: {path}")
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"Could not import module: {path}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def authenticate_git(repo: Path, script_path: Path) -> dict[str, str]:
    head = command_output(["git", "rev-parse", "HEAD"], cwd=repo)
    branch = command_output(["git", "branch", "--show-current"], cwd=repo)
    if branch != "main":
        raise RuntimeError("E1 audit requires the main branch")
    if command_output(["git", "status", "--porcelain=v1"], cwd=repo):
        raise RuntimeError("E1 audit requires a clean repository")
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", EXPECTED_BASE_COMMIT, head],
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
    producer = command_output(
        ["git", "log", "-1", "--format=%H", "--", relative], cwd=repo
    )
    if producer != head:
        raise RuntimeError("E1 audit script must be introduced by current HEAD")
    return {"git_head": head, "script_producer_commit": producer}


def authenticate_payload(args: argparse.Namespace, script_path: Path) -> dict[str, Any]:
    project = args.project_root.resolve()
    repo = project / "replication_package"
    source_estimator = repo / "code/10h_estimate_dynamic_second_wave.py"
    stage08 = repo / "code/08_make_core_paper_results.py"
    additional_script = repo / "code/11a_estimate_dynamic_second_wave_postprimary.py"
    source_results = project / "output/dynamic_second_wave_results_v100" / SOURCE_RUN_ID
    postprimary_results = (
        project / "output/dynamic_second_wave_postprimary_v100" / POSTPRIMARY_RUN_ID
    )
    estimation_state = (
        project / "derived/replication/dynamic_second_wave_estimation_v100_PRIVATE"
    )
    stage07 = project / "derived/replication/analysis_panel_24m_sf100k"
    state = project / "derived/replication/dynamic_second_wave_e1_audit_v101_PRIVATE"
    output = project / "output/dynamic_second_wave_e1_audit_v101"

    fixed = {
        source_estimator: EXPECTED_SOURCE_ESTIMATOR_SHA,
        stage08: EXPECTED_STAGE08_SHA,
        additional_script: EXPECTED_ADDITIONAL_SCRIPT_SHA,
        source_results / "_SUCCESS.json": EXPECTED_SOURCE_RESULTS_SUCCESS_SHA,
        source_results / "summary.json": EXPECTED_SOURCE_RESULTS_SUMMARY_SHA,
        postprimary_results / "_SUCCESS.json": EXPECTED_POSTPRIMARY_SUCCESS_SHA,
        postprimary_results / "summary.json": EXPECTED_POSTPRIMARY_SUMMARY_SHA,
    }
    for path, wanted in fixed.items():
        if not path.is_file():
            raise RuntimeError(f"Required source is missing: {path}")
        actual = sha256_file(path)
        if actual != wanted:
            raise RuntimeError(f"Source SHA mismatch: {path}: {actual}")
    if load_json(source_results / "_SUCCESS.json").get("status") != (
        "DYNAMIC_SECOND_WAVE_RESULTS_V100_OK"
    ):
        raise RuntimeError("Source second-wave result status mismatch")
    if load_json(postprimary_results / "_SUCCESS.json").get("status") != (
        "DYNAMIC_SECOND_WAVE_POSTPRIMARY_V100_OK"
    ):
        raise RuntimeError("Additional-analysis result status mismatch")

    stage07_paths = [
        stage07 / f"month={month}/analysis_panel.parquet" for month in MAIN_MONTHS
    ]
    if not all(path.is_file() for path in stage07_paths):
        raise RuntimeError("Stage 07 monthly Parquet panel is incomplete")
    original_config = estimation_state / "CONFIG.json"
    if not original_config.is_file():
        raise RuntimeError("Original E1 private-state configuration is missing")
    if load_json(original_config).get("status") != (
        "DYNAMIC_SECOND_WAVE_ESTIMATION_PRIVATE_STATE_OK"
    ):
        raise RuntimeError("Original E1 private-state status mismatch")

    git = authenticate_git(repo, script_path)
    authorities = {
        **git,
        "script_sha256": sha256_file(script_path),
        "source_estimator_sha256": sha256_file(source_estimator),
        "stage08_sha256": sha256_file(stage08),
        "additional_script_sha256": sha256_file(additional_script),
        "source_results_success_sha256": sha256_file(source_results / "_SUCCESS.json"),
        "source_results_summary_sha256": sha256_file(source_results / "summary.json"),
        "postprimary_success_sha256": sha256_file(postprimary_results / "_SUCCESS.json"),
        "postprimary_summary_sha256": sha256_file(postprimary_results / "summary.json"),
    }
    config = {
        "script_version": SCRIPT_VERSION,
        "source_run_id": SOURCE_RUN_ID,
        "postprimary_run_id": POSTPRIMARY_RUN_ID,
        "output_run_id": args.run_id,
        "workers": args.workers,
        "specifications": list(SPECIFICATIONS),
        "ap_tolerance": AP_TOLERANCE,
        "ap_maximum_iterations": AP_MAXIMUM_ITERATIONS,
        "identifying_row_tolerance": IDENTIFYING_ROW_TOLERANCE,
        "authorities": authorities,
    }
    return {
        "project": project,
        "repo": repo,
        "source_estimator": source_estimator,
        "stage08": stage08,
        "additional_script": additional_script,
        "source_results": source_results,
        "postprimary_results": postprimary_results,
        "estimation_state": estimation_state,
        "stage07_paths": stage07_paths,
        "state": state,
        "cache": state / "e1_audit_matrix.parquet",
        "cache_metadata": state / "e1_audit_matrix.json",
        "output": output,
        "run_id": args.run_id,
        "workers": args.workers,
        "authorities": authorities,
        "config": config,
        "config_sha256": sha256_json(config),
    }


def initialize_state(payload: dict[str, Any]) -> None:
    root = payload["state"]
    root.mkdir(parents=True, exist_ok=True)
    config_path = root / "CONFIG.json"
    if config_path.is_file():
        saved = load_json(config_path)
        if saved.get("config") != payload["config"] or saved.get(
            "config_sha256"
        ) != payload["config_sha256"]:
            raise RuntimeError("E1 audit private-state configuration mismatch")
        print("E1_AUDIT_PRIVATE_STATE_AUTHENTICATED_OK", flush=True)
        return
    if any(root.iterdir()):
        raise RuntimeError("Nonempty E1 audit private state lacks CONFIG.json")
    (root / "duckdb_temp").mkdir()
    atomic_json(
        config_path,
        {
            "status": "DYNAMIC_SECOND_WAVE_E1_AUDIT_PRIVATE_STATE_OK",
            "created_utc": utc_now(),
            "config": payload["config"],
            "config_sha256": payload["config_sha256"],
            "privacy": "PRIVATE CODES AND CACHE; DO NOT COMMIT OR PUBLISH",
        },
    )
    print("E1_AUDIT_PRIVATE_STATE_CREATED", flush=True)


def dense_codes(values: Any) -> tuple[Any, int]:
    import numpy as np
    import pandas as pd

    codes, levels = pd.factorize(values, sort=False)
    codes = np.asarray(codes, dtype=np.int64)
    if np.any(codes < 0):
        raise ValueError("Fixed effect or cluster contains missing values")
    return codes, int(len(levels))


def demean_once(matrix: Any, values: Any) -> Any:
    import numpy as np

    codes, levels = dense_codes(values)
    source = np.asarray(matrix, dtype=np.float64)
    result = source.copy()
    counts = np.bincount(codes, minlength=levels).astype(np.float64)
    for column in range(result.shape[1]):
        sums = np.bincount(codes, weights=result[:, column], minlength=levels)
        result[:, column] -= (sums / counts)[codes]
    return result


def demean_codes(matrix: Any, codes: Any, levels: int) -> Any:
    import numpy as np

    source = np.asarray(matrix, dtype=np.float64)
    result = source.copy()
    counts = np.bincount(codes, minlength=levels).astype(np.float64)
    for column in range(result.shape[1]):
        sums = np.bincount(codes, weights=result[:, column], minlength=levels)
        result[:, column] -= (sums / counts)[codes]
    return result


def maximum_group_mean(matrix: Any, fixed_effects: Sequence[Any]) -> float:
    import numpy as np

    values = np.asarray(matrix, dtype=np.float64)
    maximum = 0.0
    for effect in fixed_effects:
        codes, levels = dense_codes(effect)
        counts = np.bincount(codes, minlength=levels).astype(np.float64)
        for column in range(values.shape[1]):
            sums = np.bincount(codes, weights=values[:, column], minlength=levels)
            maximum = max(maximum, float(np.max(np.abs(sums / counts))))
    return maximum


def maximum_group_mean_codes(
    matrix: Any, effects: Sequence[tuple[Any, int]]
) -> float:
    import numpy as np

    values = np.asarray(matrix, dtype=np.float64)
    maximum = 0.0
    for codes, levels in effects:
        counts = np.bincount(codes, minlength=levels).astype(np.float64)
        for column in range(values.shape[1]):
            sums = np.bincount(codes, weights=values[:, column], minlength=levels)
            maximum = max(maximum, float(np.max(np.abs(sums / counts))))
    return maximum


def recursive_singleton_keep(
    fixed_effects: Sequence[Any],
) -> tuple[Any, int, list[int]]:
    import numpy as np

    arrays = [np.asarray(values) for values in fixed_effects]
    keep = np.ones(len(arrays[0]), dtype=bool)
    removed_by_round: list[int] = []
    while True:
        active = np.flatnonzero(keep)
        remove = np.zeros(active.size, dtype=bool)
        for values in arrays:
            codes, levels = dense_codes(values[active])
            counts = np.bincount(codes, minlength=levels)
            remove |= counts[codes] < 2
        count = int(remove.sum())
        if count == 0:
            break
        keep[active[remove]] = False
        removed_by_round.append(count)
    return keep, len(removed_by_round), removed_by_round


def absorb_tight(
    matrix: Any,
    fixed_effects: Sequence[Any],
    *,
    tolerance: float = AP_TOLERANCE,
    maximum_iterations: int = AP_MAXIMUM_ITERATIONS,
) -> tuple[Any, int, float]:
    import numpy as np

    result = np.asarray(matrix, dtype=np.float64).copy()
    effects = [dense_codes(values) for values in fixed_effects]
    orthogonality = math.inf
    for iteration in range(1, maximum_iterations + 1):
        for codes, levels in effects:
            result = demean_codes(result, codes, levels)
        if iteration <= 5 or iteration % 10 == 0:
            orthogonality = maximum_group_mean_codes(result, effects)
            if orthogonality <= tolerance:
                return result, iteration, orthogonality
    raise RuntimeError(
        f"Tight absorption failed to converge after {maximum_iterations} iterations; "
        f"maximum group mean={orthogonality:.3e}"
    )


def residualize_two_way_schur(
    matrix: Any, first_effect: Any, second_effect: Any
) -> tuple[Any, dict[str, Any]]:
    """Exactly residualize on two fixed effects using a dense small-side Schur system."""

    import numpy as np

    source = np.asarray(matrix, dtype=np.float64)
    first, first_levels = dense_codes(first_effect)
    second, second_levels = dense_codes(second_effect)
    counts_first = np.bincount(first, minlength=first_levels).astype(np.float64)
    counts_second = np.bincount(second, minlength=second_levels).astype(np.float64)

    first_demeaned = source.copy()
    for column in range(source.shape[1]):
        sums = np.bincount(
            first, weights=source[:, column], minlength=first_levels
        )
        first_demeaned[:, column] -= (sums / counts_first)[first]

    schur = np.diag(counts_second)
    order = np.argsort(first, kind="stable")
    sorted_first = first[order]
    starts = np.r_[0, np.flatnonzero(np.diff(sorted_first)) + 1, len(order)]
    for left, right in zip(starts[:-1], starts[1:], strict=True):
        rows = order[left:right]
        local, local_counts = np.unique(second[rows], return_counts=True)
        weights = local_counts.astype(np.float64)
        schur[np.ix_(local, local)] -= np.outer(weights, weights) / len(rows)

    right_hand = np.column_stack(
        [
            np.bincount(
                second, weights=first_demeaned[:, column], minlength=second_levels
            )
            for column in range(first_demeaned.shape[1])
        ]
    )
    eigenvalues, eigenvectors = np.linalg.eigh((schur + schur.T) / 2.0)
    largest = float(np.max(np.abs(eigenvalues))) if eigenvalues.size else 0.0
    threshold = max(schur.shape) * np.finfo(np.float64).eps * max(largest, 1.0)
    identified = eigenvalues > threshold
    coefficients = np.zeros_like(right_hand)
    if np.any(identified):
        vectors = eigenvectors[:, identified]
        coefficients = vectors @ (
            (vectors.T @ right_hand) / eigenvalues[identified, None]
        )
    fitted_second = coefficients[second]
    for column in range(fitted_second.shape[1]):
        sums = np.bincount(
            first, weights=fitted_second[:, column], minlength=first_levels
        )
        fitted_second[:, column] -= (sums / counts_first)[first]
    residual = first_demeaned - fitted_second
    orthogonality = maximum_group_mean(residual, (first, second))
    return residual, {
        "schur_levels": second_levels,
        "schur_rank": int(np.count_nonzero(identified)),
        "schur_nullity": int(second_levels - np.count_nonzero(identified)),
        "schur_smallest_identified_eigenvalue": (
            float(np.min(eigenvalues[identified])) if np.any(identified) else math.nan
        ),
        "absorption_iterations": 1,
        "absorption_max_group_mean": orthogonality,
    }


def cluster_meat(x: Any, residual: Any, values: Any) -> tuple[Any, int]:
    import numpy as np

    codes, groups = dense_codes(values)
    scores = np.column_stack(
        [
            np.bincount(
                codes, weights=x[:, column] * residual, minlength=groups
            )
            for column in range(x.shape[1])
        ]
    )
    return scores.T @ scores, groups


def fit_residualized(
    transformed: Any,
    x_names: Sequence[str],
    chooser: Any,
    assignment: Any,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    import numpy as np

    values = np.asarray(transformed, dtype=np.float64)
    y = values[:, 0]
    x = values[:, 1:]
    chooser = np.asarray(chooser)
    assignment = np.asarray(assignment)
    identifying = np.max(np.abs(x), axis=1) > IDENTIFYING_ROW_TOLERANCE
    y = y[identifying]
    x = x[identifying]
    chooser = chooser[identifying]
    assignment = assignment[identifying]
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

    if x.shape[1] > 1:
        controls = x[:, 1:]
        control_inverse = np.linalg.pinv(controls.T @ controls, hermitian=True)
        partial_risk = x[:, 0] - controls @ (
            control_inverse @ (controls.T @ x[:, 0])
        )
    else:
        partial_risk = x[:, 0]
    partial_ss = float(partial_risk @ partial_risk)
    risk_identified = bool(partial_ss > 1e-8)
    return {
        **metadata,
        "status": (
            "OK"
            if risk_identified
            else "NOT_IDENTIFIED_NO_WITHIN_FE_RISK_VARIATION"
        ),
        "rows_identifying": int(n),
        "matrix_rank": rank,
        "x_names": list(x_names),
        "beta": beta,
        "covariance_chooser": covariance_chooser,
        "covariance_two_way": covariance_two_way,
        "chooser_clusters": chooser_groups,
        "assignment_clusters": assignment_groups,
        "intersection_clusters": intersection_groups,
        "risk_after_fe_std": float(np.std(x[:, 0])),
        "risk_after_fe_and_controls_std": float(np.std(partial_risk)),
        "risk_after_fe_and_controls_ss": partial_ss,
        "risk_identification_threshold_ss": 1e-8,
        "risk_numerically_identified": risk_identified,
    }


def month_dummies(codes: Any) -> tuple[Any, list[str]]:
    import numpy as np

    values, levels = dense_codes(codes)
    if levels <= 1:
        return np.empty((len(values), 0), dtype=np.float64), []
    return (
        np.column_stack([(values == level).astype(np.float64) for level in range(1, levels)]),
        [f"month_{level:02d}" for level in range(1, levels)],
    )


def read_cache(cache_path: str, metadata_path: str) -> tuple[Any, dict[str, Any]]:
    import pandas as pd

    path = Path(cache_path)
    metadata = load_json(Path(metadata_path))
    if sha256_file(path) != metadata["parquet_sha256"]:
        raise RuntimeError("Private E1 audit cache SHA mismatch")
    frame = pd.read_parquet(path)
    if len(frame) != int(metadata["rows"]):
        raise RuntimeError("Private E1 audit cache row count mismatch")
    return frame, metadata


def scaled_row(
    fit: dict[str, Any], covariance_name: str, cache_metadata: dict[str, Any]
) -> dict[str, Any]:
    import numpy as np

    risk_identified = bool(fit.get("risk_numerically_identified", True))
    covariance = np.asarray(fit[covariance_name], dtype=np.float64)
    beta = float(np.asarray(fit["beta"])[0]) if risk_identified else None
    variance = float(covariance[0, 0]) if risk_identified else math.nan
    standard_error = (
        math.sqrt(variance) if risk_identified and variance >= 0 else None
    )
    span = float(cache_metadata["risk_p90_minus_p10"])
    coefficient = beta * span if beta is not None else None
    scaled_se = standard_error * span if standard_error is not None else None
    z_value = (
        coefficient / scaled_se
        if coefficient is not None and scaled_se is not None and scaled_se > 0
        else None
    )
    lower = coefficient - 1.96 * scaled_se if z_value is not None else None
    upper = coefficient + 1.96 * scaled_se if z_value is not None else None
    public = {
        key: value
        for key, value in fit.items()
        if key
        not in {
            "beta",
            "covariance_chooser",
            "covariance_two_way",
            "x_names",
        }
    }
    if not risk_identified:
        public["status"] = "NOT_IDENTIFIED_NO_WITHIN_FE_RISK_VARIATION"
    public.update(
        {
            "analysis": "E1_independent_audit",
            "covariance": covariance_name.removeprefix("covariance_"),
            "coefficient_per_unit_risk": beta,
            "standard_error_per_unit_risk": standard_error,
            "risk_p10": cache_metadata["risk_p10"],
            "risk_p90": cache_metadata["risk_p90"],
            "risk_p90_minus_p10": span,
            "coefficient": coefficient,
            "coefficient_percentage_points": (
                100 * coefficient if coefficient is not None else None
            ),
            "standard_error": scaled_se,
            "standard_error_percentage_points": (
                100 * scaled_se if scaled_se is not None else None
            ),
            "z_value": z_value,
            "p_value_two_sided": normal_p(z_value) if z_value is not None else None,
            "confidence_interval_95_low_pp": 100 * lower if lower is not None else None,
            "confidence_interval_95_high_pp": 100 * upper if upper is not None else None,
            "informative_null_upper_bound_pp": 100 * upper if upper is not None else None,
            "upper_bound_below_0_30pp": (
                bool(100 * upper < 0.30) if upper is not None else None
            ),
            "outcome_mean": cache_metadata["outcome_mean"],
        }
    )
    return public


def worker_independent_schur(
    frame: Any, cache_metadata: dict[str, Any]
) -> list[dict[str, Any]]:
    import numpy as np

    chooser_all = frame["chooser_code"].to_numpy(dtype=np.int64)
    chooser_codes, chooser_levels = dense_codes(chooser_all)
    chooser_counts = np.bincount(chooser_codes, minlength=chooser_levels)
    keep = chooser_counts[chooser_codes] >= 2
    selected = frame.loc[keep].reset_index(drop=True)
    controls = selected[cache_metadata["control_columns"]].to_numpy(dtype=np.float64)
    months, month_names = month_dummies(selected["month_code"].to_numpy())
    x = np.column_stack(
        [selected["re_pair_risk"].to_numpy(dtype=np.float64), controls, months]
    )
    names = ["re_pair_risk", *cache_metadata["control_names"], *month_names]
    chooser = selected["chooser_code"].to_numpy(dtype=np.int64)
    cell = selected["cell_code"].to_numpy(dtype=np.int64)
    assignment = selected["assignment_code"].to_numpy(dtype=np.int64)
    source = np.column_stack(
        [selected["kind_draw"].to_numpy(dtype=np.float64), x]
    )
    transformed, diagnostics = residualize_two_way_schur(source, chooser, cell)
    fit = fit_residualized(
        transformed,
        names,
        chooser,
        assignment,
        {
            "specification": "same_additive_month_and_exact_cell",
            "solver": "independent_dense_small_side_schur",
            "rows_raw": int(len(frame)),
            "rows_after_singleton_pruning": int(len(selected)),
            "singleton_pruning_rounds": 1,
            **diagnostics,
        },
    )
    return [
        scaled_row(fit, "covariance_chooser", cache_metadata),
        scaled_row(fit, "covariance_two_way", cache_metadata),
    ]


def worker_tight_ap(
    frame: Any,
    cache_metadata: dict[str, Any],
    *,
    assignment_unit: bool,
) -> list[dict[str, Any]]:
    import numpy as np

    controls = frame[cache_metadata["control_columns"]].to_numpy(dtype=np.float64)
    x = np.column_stack(
        [frame["re_pair_risk"].to_numpy(dtype=np.float64), controls]
    )
    names = ["re_pair_risk", *cache_metadata["control_names"]]
    chooser = frame["chooser_code"].to_numpy(dtype=np.int64)
    month = frame["month_code"].to_numpy(dtype=np.int64)
    cell = frame["cell_code"].to_numpy(dtype=np.int64)
    assignment = frame["assignment_code"].to_numpy(dtype=np.int64)
    fixed = (chooser, assignment) if assignment_unit else (chooser, month, cell)
    keep, rounds, removed = recursive_singleton_keep(fixed)
    selected_y = frame.loc[keep, "kind_draw"].to_numpy(dtype=np.float64)
    selected_x = x[keep]
    selected_fixed = tuple(values[keep] for values in fixed)
    selected_chooser = chooser[keep]
    selected_assignment = assignment[keep]
    source = np.column_stack([selected_y, selected_x])
    transformed, iterations, orthogonality = absorb_tight(source, selected_fixed)
    fit = fit_residualized(
        transformed,
        names,
        selected_chooser,
        selected_assignment,
        {
            "specification": (
                "chooser_and_month_by_score_assignment_unit"
                if assignment_unit
                else "same_additive_month_and_exact_cell"
            ),
            "solver": "tight_recursive_singleton_alternating_projection",
            "rows_raw": int(len(frame)),
            "rows_after_singleton_pruning": int(np.count_nonzero(keep)),
            "singleton_pruning_rounds": rounds,
            "singleton_rows_removed_by_round": json.dumps(removed),
            "absorption_method": "cyclic_multiway_to_1e-12_after_recursive_pruning",
            "absorption_iterations": iterations,
            "absorption_max_group_mean": orthogonality,
        },
    )
    return [
        scaled_row(fit, "covariance_chooser", cache_metadata),
        scaled_row(fit, "covariance_two_way", cache_metadata),
    ]


def run_worker(
    specification: str,
    cache_path: str,
    metadata_path: str,
) -> list[dict[str, Any]]:
    frame, metadata = read_cache(cache_path, metadata_path)
    if specification == "independent_schur_two_way":
        return worker_independent_schur(frame, metadata)
    if specification == "tight_ap_same_spec_two_way":
        return worker_tight_ap(frame, metadata, assignment_unit=False)
    if specification == "assignment_unit_tight_ap_two_way":
        return worker_tight_ap(frame, metadata, assignment_unit=True)
    raise ValueError(f"Unknown audit specification: {specification}")


def source_e1_result(payload: dict[str, Any]) -> dict[str, Any]:
    source = load_json(payload["source_results"] / "summary.json")
    return next(row for row in source["models"] if row["analysis"] == "E1")


def postprimary_e1_result(payload: dict[str, Any]) -> dict[str, Any]:
    summary = load_json(payload["postprimary_results"] / "summary.json")
    return summary["headline_additional"]["e1_exact_cell_two_way"]


def assert_source_reproduced(current: dict[str, Any], source: dict[str, Any]) -> None:
    for field in ("rows_raw", "rows_identifying", "chooser_clusters"):
        if current[field] != source[field]:
            raise RuntimeError(f"Source E1 replication mismatch: {field}")
    for field in ("coefficient", "standard_error"):
        if not math.isclose(
            float(current[field]), float(source[field]), rel_tol=1e-12, abs_tol=1e-12
        ):
            raise RuntimeError(f"Source E1 replication mismatch: {field}")


def build_or_authenticate_cache(
    payload: dict[str, Any], base: Any, stage08: Any
) -> dict[str, Any]:
    import numpy as np
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq

    cache = payload["cache"]
    metadata_path = payload["cache_metadata"]
    if cache.is_file() and metadata_path.is_file():
        metadata = load_json(metadata_path)
        if metadata.get("config_sha256") != payload["config_sha256"]:
            raise RuntimeError("Private E1 audit cache configuration mismatch")
        if sha256_file(cache) != metadata.get("parquet_sha256"):
            raise RuntimeError("Private E1 audit cache SHA mismatch")
        print(
            f"E1_AUDIT_PARQUET_CACHE_AUTHENTICATED_OK rows={metadata['rows']:,}",
            flush=True,
        )
        return metadata
    if cache.exists() or metadata_path.exists():
        raise RuntimeError("Partial E1 audit cache exists")

    original_config = load_json(payload["estimation_state"] / "CONFIG.json")
    original_config_sha = original_config["config_sha256"]
    e1_paths = []
    for month in base.MAIN_MONTHS:
        authenticated = base.authenticate_e1_month(
            payload["estimation_state"], month, original_config_sha
        )
        if authenticated is None:
            raise RuntimeError(f"Cached E1 score is missing: {month}")
        e1_paths.append(base.e1_score_paths(payload["estimation_state"], month)[0])

    print("E1_AUDIT_PARQUET_CACHE_BUILD_BEGIN", flush=True)
    frame = base.stage07_frame(
        {
            "stage07_paths": payload["stage07_paths"],
            "user_paths": [],
            "state": payload["state"],
        },
        "E1",
        e1_paths,
    )
    source_fit = base.fit_panel_branch(stage08, frame, "E1")
    assert_source_reproduced(source_fit, source_e1_result(payload))

    selected = frame.loc[frame["first_ever_pair"].astype(bool)].reset_index(drop=True)
    controls, control_names = base.control_matrix(selected, "E1")
    redundant_prefixes = ("speed_", "rating_band_100_", "utc_block_6h_", "weekend_")
    keep_controls = [
        index
        for index, name in enumerate(control_names)
        if not name.startswith(redundant_prefixes)
    ]
    controls = controls[:, keep_controls]
    kept_names = [control_names[index] for index in keep_controls]

    chooser_codes, chooser_levels = dense_codes(selected["chooser_user_id"])
    month_codes, month_levels = dense_codes(selected["month"])
    exact_cell = pd.MultiIndex.from_frame(
        selected[["speed", "rating_band_100", "utc_block_6h", "weekend"]]
    )
    cell_codes, cell_levels = dense_codes(exact_cell)
    level = selected["coarsening_level"].to_numpy(dtype=np.int64)
    rating_100 = selected["rating_band_100"].to_numpy(dtype=np.int64)
    rating_200 = (rating_100 // 200) * 200
    assignment_frame = pd.DataFrame(
        {
            "month": selected["month"].astype(str),
            "level": level,
            "speed": selected["speed"].astype(str),
            "rating": np.where(
                level <= 2, rating_100, np.where(level <= 4, rating_200, -1)
            ),
            "utc_block": np.where(level <= 3, selected["utc_block_6h"], -1),
            "weekend": np.where(level == 1, selected["weekend"], -1),
        }
    )
    assignment_codes, assignment_levels = dense_codes(
        pd.MultiIndex.from_frame(assignment_frame)
    )

    data: dict[str, Any] = {
        "kind_draw": selected["kind_draw"].to_numpy(dtype=np.float64),
        "re_pair_risk": selected["re_pair_risk"].to_numpy(dtype=np.float64),
        "chooser_code": chooser_codes,
        "month_code": month_codes.astype(np.int16),
        "cell_code": cell_codes.astype(np.int32),
        "assignment_code": assignment_codes.astype(np.int32),
        "coarsening_level": level.astype(np.int8),
        "leave_pair_out_n": selected["leave_pair_out_n"].to_numpy(dtype=np.int64),
    }
    control_columns = []
    for index, name in enumerate(kept_names):
        column = f"control_{index:03d}"
        control_columns.append(column)
        data[column] = controls[:, index]
    cached = pd.DataFrame(data)
    temporary = cache.with_name(cache.name + f".tmp.{uuid.uuid4().hex}")
    table = pa.Table.from_pandas(cached, preserve_index=False)
    pq.write_table(
        table,
        temporary,
        compression="zstd",
        compression_level=6,
        use_dictionary=[
            "chooser_code",
            "month_code",
            "cell_code",
            "assignment_code",
            "coarsening_level",
        ],
        write_statistics=True,
        row_group_size=65_536,
    )
    os.replace(temporary, cache)
    p10, p90 = np.quantile(cached["re_pair_risk"], [0.1, 0.9])
    chooser_counts = np.bincount(chooser_codes, minlength=chooser_levels)
    metadata = {
        "status": "DYNAMIC_SECOND_WAVE_E1_AUDIT_CACHE_OK",
        "created_utc": utc_now(),
        "config_sha256": payload["config_sha256"],
        "parquet_sha256": sha256_file(cache),
        "parquet_bytes": cache.stat().st_size,
        "rows": int(len(cached)),
        "control_columns": control_columns,
        "control_names": kept_names,
        "chooser_levels": chooser_levels,
        "month_levels": month_levels,
        "cell_levels": cell_levels,
        "assignment_levels": assignment_levels,
        "singleton_chooser_rows": int(np.count_nonzero(chooser_counts[chooser_codes] == 1)),
        "coarsening_level_counts": {
            str(int(key)): int(value)
            for key, value in selected["coarsening_level"].value_counts().sort_index().items()
        },
        "risk_p10": float(p10),
        "risk_p90": float(p90),
        "risk_p90_minus_p10": float(p90 - p10),
        "outcome_mean": float(cached["kind_draw"].mean()),
        "source_e1_reproduced": {
            key: source_fit[key]
            for key in (
                "rows_raw",
                "rows_identifying",
                "chooser_clusters",
                "coefficient",
                "standard_error",
                "p_value_two_sided",
            )
        },
        "privacy": "PRIVATE FACTOR CODES AND MODEL MATRIX; DO NOT PUBLISH",
    }
    atomic_json(metadata_path, metadata)
    print(
        f"E1_AUDIT_PARQUET_CACHE_BUILD_OK rows={len(cached):,} "
        f"bytes={cache.stat().st_size:,}",
        flush=True,
    )
    return metadata


def reference_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    source = source_e1_result(payload)
    additional = postprimary_e1_result(payload)
    return [
        {
            "analysis": "E1_reference",
            "specification": "source_additive_controls",
            "solver": "reported_source",
            "covariance": "chooser",
            "status": "REFERENCE_ONLY",
            **{
                key: source.get(key)
                for key in (
                    "rows_raw",
                    "rows_identifying",
                    "chooser_clusters",
                    "coefficient_per_unit_risk",
                    "standard_error_per_unit_risk",
                    "coefficient",
                    "coefficient_percentage_points",
                    "standard_error",
                    "standard_error_percentage_points",
                    "p_value_two_sided",
                    "confidence_interval_95_low_pp",
                    "confidence_interval_95_high_pp",
                    "upper_bound_below_0_30pp",
                )
            },
        },
        {
            "analysis": "E1_reference",
            "specification": "same_additive_month_and_exact_cell",
            "solver": "reported_additional_analysis",
            "covariance": "two_way",
            "status": "REFERENCE_ONLY",
            **{
                key: additional.get(key)
                for key in (
                    "rows_raw",
                    "rows_identifying",
                    "chooser_clusters",
                    "assignment_clusters",
                    "intersection_clusters",
                    "coefficient_per_unit_risk",
                    "standard_error_per_unit_risk",
                    "coefficient",
                    "coefficient_percentage_points",
                    "standard_error",
                    "standard_error_percentage_points",
                    "p_value_two_sided",
                    "confidence_interval_95_low_pp",
                    "confidence_interval_95_high_pp",
                    "upper_bound_below_0_30pp",
                )
            },
        },
    ]


def validate_cross_solver(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    schur = next(
        row
        for row in rows
        if row.get("solver") == "independent_dense_small_side_schur"
        and row.get("covariance") == "chooser"
    )
    tight = next(
        row
        for row in rows
        if row.get("solver") == "tight_recursive_singleton_alternating_projection"
        and row.get("specification") == "same_additive_month_and_exact_cell"
        and row.get("covariance") == "chooser"
    )
    differences = {
        "tight_ap_minus_independent_schur_per_unit": float(
            tight["coefficient_per_unit_risk"]
            - schur["coefficient_per_unit_risk"]
        ),
        "tight_ap_se_minus_independent_schur_chooser_per_unit": float(
            tight["standard_error_per_unit_risk"]
            - schur["standard_error_per_unit_risk"]
        ),
    }
    # These are independent implementations of the same coefficient.  The tight
    # AP fit absorbs month instead of representing it with nuisance columns, so
    # its finite-sample covariance correction can differ slightly.  Agreement of
    # the coefficient is the hard numerical invariant; the SE difference is
    # retained in the public diagnostic rather than used as a false equality test.
    if abs(differences["tight_ap_minus_independent_schur_per_unit"]) > 1e-8:
        raise RuntimeError(f"Independent E1 solver disagreement: {differences}")
    return {
        "status": "E1_INDEPENDENT_AND_TIGHT_SOLVER_AGREEMENT_OK",
        "coefficient_tolerance_per_unit": 1e-8,
        "standard_error_difference_is_diagnostic_only": True,
        **differences,
    }


def manifest_rows(root: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(item for item in root.iterdir() if item.is_file()):
        if path.name in {"_SUCCESS.json", "report_file_hashes.tsv"}:
            continue
        rows.append(
            {
                "path": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return rows


def write_results(
    payload: dict[str, Any],
    rows: Sequence[dict[str, Any]],
    cache_metadata: dict[str, Any],
    agreement: dict[str, Any],
) -> Path:
    final = payload["output"] / payload["run_id"]
    staging = payload["output"] / f".{payload['run_id']}.tmp.{uuid.uuid4().hex}"
    if staging.exists() or final.exists():
        raise RuntimeError("Unexpected E1 audit staging or final output already exists")
    staging.mkdir(parents=True)
    write_csv(staging / "e1_audit_models.csv", rows)
    support = {
        key: value
        for key, value in cache_metadata.items()
        if key
        not in {
            "control_columns",
            "control_names",
            "parquet_sha256",
            "privacy",
        }
    }
    atomic_json(staging / "e1_audit_support.json", support)
    atomic_json(staging / "e1_solver_agreement.json", agreement)
    atomic_json(
        staging / "source_authorities.json",
        {
            "source_run_id": SOURCE_RUN_ID,
            "postprimary_run_id": POSTPRIMARY_RUN_ID,
            "authorities": payload["authorities"],
            "config_sha256": payload["config_sha256"],
            "scope": "independent numerical and specification audit",
        },
    )

    independent = next(
        row
        for row in rows
        if row.get("solver") == "independent_dense_small_side_schur"
        and row.get("covariance") == "two_way"
    )
    assignment = next(
        row
        for row in rows
        if row.get("specification") == "chooser_and_month_by_score_assignment_unit"
        and row.get("covariance") == "two_way"
    )
    reported = next(
        row
        for row in rows
        if row.get("solver") == "reported_additional_analysis"
    )
    summary = {
        "status": "DYNAMIC_SECOND_WAVE_E1_AUDIT_V101_OK",
        "created_utc": utc_now(),
        "script_version": SCRIPT_VERSION,
        "source_run_id": SOURCE_RUN_ID,
        "postprimary_run_id": POSTPRIMARY_RUN_ID,
        "run_id": payload["run_id"],
        "scope": "independent numerical and specification audit",
        "authorities": payload["authorities"],
        "config_sha256": payload["config_sha256"],
        "solver_agreement": agreement,
        "headline": {
            "reported_exact_cell_two_way": reported,
            "independent_exact_cell_two_way": independent,
            "assignment_unit_two_way": assignment,
        },
        "privacy": "Aggregate output only; factor codes and private cache remain private.",
        "chronology_rebuilt": False,
        "patron_profile_input_read": False,
    }
    atomic_json(staging / "summary.json", summary)
    report = manifest_rows(staging)
    write_tsv(staging / "report_file_hashes.tsv", report)
    success = {
        "status": "DYNAMIC_SECOND_WAVE_E1_AUDIT_V101_OK",
        "created_utc": utc_now(),
        "run_id": payload["run_id"],
        "script_sha256": payload["authorities"]["script_sha256"],
        "git_head": payload["authorities"]["git_head"],
        "config_sha256": payload["config_sha256"],
        "summary_sha256": sha256_file(staging / "summary.json"),
        "report_manifest_sha256": sha256_file(staging / "report_file_hashes.tsv"),
        "report_files_hashed": len(report),
        "account_level_output": False,
        "private_cache_archived": False,
    }
    atomic_json(staging / "_SUCCESS.json", success)
    final.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging, final)
    return final


def execute(payload: dict[str, Any]) -> Path:
    started = time.time()
    final = payload["output"] / payload["run_id"]
    if final.is_dir() and (final / "_SUCCESS.json").is_file():
        status = load_json(final / "_SUCCESS.json").get("status")
        if status != "DYNAMIC_SECOND_WAVE_E1_AUDIT_V101_OK":
            raise RuntimeError("Existing E1 audit output has an invalid status")
        print(f"E1_AUDIT_RESULTS_ALREADY_COMPLETE: {final}", flush=True)
        return final
    initialize_state(payload)
    base = load_module(
        payload["source_estimator"],
        "e1_audit_source_estimator",
        EXPECTED_SOURCE_ESTIMATOR_SHA,
    )
    stage08 = load_module(
        payload["stage08"], "e1_audit_stage08", EXPECTED_STAGE08_SHA
    )
    stage08.run_numerical_self_test()
    print("E1_AUDIT_SOURCE_NUMERICAL_SELF_TEST_OK", flush=True)
    cache_metadata = build_or_authenticate_cache(payload, base, stage08)

    print(
        f"E1_AUDIT_PARALLEL_FITS_BEGIN specifications={len(SPECIFICATIONS)} "
        f"workers={payload['workers']}",
        flush=True,
    )
    worker_rows: list[dict[str, Any]] = []
    context = mp.get_context("spawn")
    with ProcessPoolExecutor(
        max_workers=payload["workers"], mp_context=context
    ) as executor:
        futures = {
            executor.submit(
                run_worker,
                specification,
                str(payload["cache"]),
                str(payload["cache_metadata"]),
            ): specification
            for specification in SPECIFICATIONS
        }
        for future in as_completed(futures):
            specification = futures[future]
            produced = future.result()
            worker_rows.extend(produced)
            print(
                f"E1_AUDIT_PARALLEL_FIT_OK specification={specification} "
                f"rows={len(produced)}",
                flush=True,
            )
    ordering = {name: index for index, name in enumerate(SPECIFICATIONS)}
    solver_to_spec = {
        "independent_dense_small_side_schur": "independent_schur_two_way",
        "tight_recursive_singleton_alternating_projection": "tight_ap_same_spec_two_way",
    }
    worker_rows.sort(
        key=lambda row: (
            ordering.get(
                (
                    "assignment_unit_tight_ap_two_way"
                    if row.get("specification")
                    == "chooser_and_month_by_score_assignment_unit"
                    else solver_to_spec.get(row.get("solver", ""), "")
                ),
                99,
            ),
            row.get("covariance", ""),
        )
    )
    agreement = validate_cross_solver(worker_rows)
    print("E1_INDEPENDENT_AND_TIGHT_SOLVER_AGREEMENT_OK", flush=True)
    all_rows = [*reference_rows(payload), *worker_rows]
    final = write_results(payload, all_rows, cache_metadata, agreement)
    print(f"DYNAMIC_SECOND_WAVE_E1_AUDIT_V101_OK: {final}", flush=True)
    print(f"runtime_seconds: {time.time() - started:.1f}", flush=True)
    return final


def self_test() -> None:
    import numpy as np

    rng = np.random.default_rng(20260823)
    rows = 1_200
    chooser = np.repeat(np.arange(60), 20)
    cell = (chooser + np.tile(np.arange(20), 60)) % 9
    month = np.tile(np.repeat(np.arange(5), 4), 60)
    risk = rng.normal(size=rows)
    control = rng.normal(size=rows)
    y = 0.2 * risk - 0.1 * control + rng.normal(scale=0.5, size=rows)
    months, month_names = month_dummies(month)
    x = np.column_stack([risk, control, months])
    names = ["risk", "control", *month_names]
    source = np.column_stack([y, x])
    schur, diagnostics = residualize_two_way_schur(source, chooser, cell)
    tight_source = np.column_stack([y, risk, control])
    tight, iterations, orthogonality = absorb_tight(
        tight_source, (chooser, month, cell), tolerance=1e-12
    )
    fit = fit_residualized(
        schur,
        names,
        chooser,
        month * 20 + cell,
        {
            "specification": "synthetic",
            "solver": "synthetic",
            "rows_raw": rows,
            "rows_after_singleton_pruning": rows,
            **diagnostics,
        },
    )
    tight_fit = fit_residualized(
        tight,
        ("risk", "control"),
        chooser,
        month * 20 + cell,
        {
            "specification": "synthetic_tight",
            "solver": "synthetic_tight",
            "rows_raw": rows,
            "rows_after_singleton_pruning": rows,
        },
    )
    if not np.allclose(
        np.asarray(fit["beta"][:2]),
        np.asarray(tight_fit["beta"][:2]),
        rtol=1e-9,
        atol=1e-9,
    ):
        raise AssertionError("Schur-with-month-controls and tight absorption disagree")
    if abs(float(fit["beta"][0]) - 0.2) > 0.05:
        raise AssertionError("Synthetic risk coefficient is implausible")
    if iterations < 1 or orthogonality > 1e-12:
        raise AssertionError("Tight absorption did not converge")

    fixed_a = np.array([0, 1, 1, 2, 2, 3, 3, 3])
    fixed_b = np.array([0, 0, 1, 1, 2, 2, 3, 3])
    keep, rounds, removed = recursive_singleton_keep((fixed_a, fixed_b))
    if rounds < 1 or int(keep.sum()) >= len(keep) or sum(removed) < 1:
        raise AssertionError("Recursive singleton pruning test failed")
    print("DYNAMIC_SECOND_WAVE_E1_AUDIT_V101_SELF_TEST_OK")


def print_plan(payload: dict[str, Any]) -> None:
    print("DYNAMIC_SECOND_WAVE_E1_AUDIT_V101_PLAN_OK")
    print("script_version:", SCRIPT_VERSION)
    print("script_sha256:", payload["authorities"]["script_sha256"])
    print("git_head:", payload["authorities"]["git_head"])
    print("source_run_id:", SOURCE_RUN_ID)
    print("postprimary_run_id:", POSTPRIMARY_RUN_ID)
    print("run_id:", payload["run_id"])
    print("scope: independent numerical and specification audit")
    print("workers:", payload["workers"])
    print("parquet_cache:", payload["cache"])
    print("ap_tolerance:", AP_TOLERANCE)
    print("chronology_rebuilt: false")
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
