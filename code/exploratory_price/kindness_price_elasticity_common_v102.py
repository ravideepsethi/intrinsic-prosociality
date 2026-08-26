#!/usr/bin/env python3
"""Shared authenticated utilities for the kindness price-elasticity module."""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
import uuid


SCRIPT_VERSION = "1.0.2"
PROJECT_ROOT = Path("/Volumes/XT_Pro/lichess_kindness")
STAGE07_RELATIVE = Path("derived/replication/analysis_panel_24m_sf100k")
EXPECTED_STAGE07_SUCCESS_SHA256 = (
    "8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7"
)
EXPECTED_STAGE07_PRODUCER_SHA256 = (
    "0411d4061ea9831c20449208a9782aaf668e160139918d106a2b7d63aaa56e6e"
)
EXPECTED_STAGE07_ROWS = 47_587_020
EXPECTED_STAGE07_KIND_DRAWS = 669_503
EXPECTED_FAIR_ROWS = 17_328_130
EXPECTED_FAIR_KIND_DRAWS = 487_170
EXPECTED_FAIR_CHOOSERS = 2_685_525
EXPECTED_NONPOSITIVE_PRICE_ROWS = 0
# The current Stage07 authority begins in 2023-11. Its first temporal half is
# therefore 2023-11 through 2024-10. v1.0.0 incorrectly imported the
# 7,980,397-row count from the older 2023-10 through 2024-09 Appendix-A11
# window. Its lossy chooser-key join then produced a second incorrect anchor,
# 8,575,598. The exact-key v1.0.1 production scan conserved every certified
# row, outcome, game ID, and chooser and established the physical anchors below
# before any regression was estimated.
EXPECTED_FIRST12_FAIR_ROWS = 8_575_710
EXPECTED_FIRST12_FAIR_CHOOSERS = 1_744_924
EXPECTED_STAGE08_FULL_PIECEWISE = {
    "beta_plus_pp_per_rating_point": 0.00015756302027886832,
    "beta_minus_pp_per_rating_point": -0.006719576971106138,
    "threshold_jump_pp": 0.43947730757174397,
}
MAIN_MONTHS = (
    "2023-11", "2023-12", "2024-01", "2024-02", "2024-03", "2024-04",
    "2024-05", "2024-06", "2024-07", "2024-08", "2024-09", "2024-10",
    "2024-11", "2024-12", "2025-01", "2025-02", "2025-03", "2025-04",
    "2025-05", "2025-06", "2025-07", "2025-08", "2025-09", "2025-10",
)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def utc_run_id() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path, chunk_size: int = 16 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(chunk_size):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{uuid.uuid4().hex}")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def atomic_json(path: Path, value: Any) -> None:
    atomic_text(path, json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        raise RuntimeError(f"Refusing to write empty aggregate table: {path}")
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for field in row:
            if field not in seen:
                fields.append(field)
                seen.add(field)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{uuid.uuid4().hex}")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: canonical_json(value)
                    if isinstance(value, (dict, list, tuple))
                    else value
                    for key, value in row.items()
                }
            )
    os.replace(temporary, path)


def sql_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def path_list_literal(paths: Iterable[Path]) -> str:
    return "[" + ",".join(sql_literal(path) for path in paths) + "]"


def import_dependencies() -> tuple[Any, Any, Any, Any]:
    try:
        import duckdb  # type: ignore
        import numpy as np  # type: ignore
        import pyarrow as pa  # type: ignore
        import pyarrow.parquet as pq  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("duckdb, numpy, and pyarrow are required") from exc
    return duckdb, np, pa, pq


def configure_duckdb(
    connection: Any, *, threads: int, memory_limit: str, temp_directory: Path
) -> None:
    temp_directory.mkdir(parents=True, exist_ok=True)
    connection.execute(f"SET threads={int(threads)}")
    connection.execute(f"SET memory_limit={sql_literal(memory_limit)}")
    connection.execute(f"SET temp_directory={sql_literal(temp_directory)}")
    connection.execute("SET preserve_insertion_order=false")
    try:
        connection.execute("PRAGMA enable_progress_bar")
    except Exception:
        pass


def stage07_paths(root: Path) -> list[Path]:
    paths = [root / f"month={month}/analysis_panel.parquet" for month in MAIN_MONTHS]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise RuntimeError(f"Stage07 monthly inputs are incomplete: {missing[:4]}")
    return paths


def authenticate_stage07(root: Path) -> dict[str, Any]:
    """Authenticate the certified receipt and every physical Stage07 Parquet."""
    _, _, _, pq = import_dependencies()
    success_path = root / "_SUCCESS.json"
    if not success_path.is_file():
        raise RuntimeError(f"Stage07 success receipt is missing: {success_path}")
    actual_success_sha = sha256_file(success_path)
    if actual_success_sha != EXPECTED_STAGE07_SUCCESS_SHA256:
        raise RuntimeError("Stage07 success receipt hash changed")
    success = load_json(success_path)
    qa = success.get("global_qa", {})
    if (
        success.get("final_ok") is not True
        or success.get("script_sha256") != EXPECTED_STAGE07_PRODUCER_SHA256
        or int(qa.get("rows", -1)) != EXPECTED_STAGE07_ROWS
        or int(qa.get("kind_draws", -1)) != EXPECTED_STAGE07_KIND_DRAWS
        or int(qa.get("fair_rows", -1)) != EXPECTED_FAIR_ROWS
    ):
        raise RuntimeError("Stage07 certified support or producer changed")
    paths = stage07_paths(root)
    outputs = success.get("monthly_outputs")
    if not isinstance(outputs, list) or len(outputs) != len(paths):
        raise RuntimeError("Stage07 monthly inventory changed")
    expected = {str(row.get("month")): row for row in outputs}
    physical: list[dict[str, Any]] = []
    for month, path in zip(MAIN_MONTHS, paths, strict=True):
        row = expected.get(month)
        if row is None:
            raise RuntimeError(f"Stage07 monthly receipt is missing {month}")
        actual = {
            "month": month,
            "path": str(path),
            "rows": int(pq.ParquetFile(path).metadata.num_rows),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        comparison = {
            "path": row.get("path"),
            "rows": int(row.get("rows", -1)),
            "bytes": int(row.get("output_size_bytes", -1)),
            "sha256": row.get("output_sha256"),
        }
        for key in ("path", "rows", "bytes", "sha256"):
            if actual[key] != comparison[key]:
                raise RuntimeError(f"Stage07 physical month changed: {month} {key}")
        physical.append(actual)
    if sum(int(row["rows"]) for row in physical) != EXPECTED_STAGE07_ROWS:
        raise RuntimeError("Stage07 monthly rows do not conserve")
    return {
        "status": "STAGE07_PHYSICAL_AUTHENTICATION_OK",
        "success_sha256": actual_success_sha,
        "producer_sha256": EXPECTED_STAGE07_PRODUCER_SHA256,
        "rows": EXPECTED_STAGE07_ROWS,
        "fair_rows": EXPECTED_FAIR_ROWS,
        "monthly_files": len(physical),
        "selected_bytes": sum(int(row["bytes"]) for row in physical),
        "physical_manifest_sha256": sha256_json(physical),
        "monthly_inputs": physical,
    }


def package_manifest(root: Path) -> list[dict[str, Any]]:
    manifest_path = root / "PACKAGE_CONTENTS.sha256"
    if not manifest_path.is_file():
        raise RuntimeError("Package content manifest is missing")
    rows: list[dict[str, Any]] = []
    for raw in manifest_path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        digest, relative = raw.split(None, 1)
        relative = relative.lstrip("* ")
        path = root / relative
        if not path.is_file() or sha256_file(path) != digest:
            raise RuntimeError(f"Packaged-file authentication failed: {relative}")
        rows.append({"path": relative, "bytes": path.stat().st_size, "sha256": digest})
    return sorted(rows, key=lambda row: str(row["path"]))


def speed_code_sql(field: str) -> str:
    return f"""
      CASE lower(replace(CAST({field} AS VARCHAR), '_', ''))
        WHEN 'ultrabullet' THEN 0 WHEN 'bullet' THEN 1 WHEN 'blitz' THEN 2
        WHEN 'rapid' THEN 3 WHEN 'classical' THEN 4 WHEN 'correspondence' THEN 5
        ELSE -1 END
    """.strip()


def rating_band_sql(field: str) -> str:
    return f"""
      CASE WHEN CAST({field} AS DOUBLE) < 1600 THEN 0
           WHEN CAST({field} AS DOUBLE) < 2000 THEN 1
           WHEN CAST({field} AS DOUBLE) < 2400 THEN 2 ELSE 3 END
    """.strip()


def eval_band_sql(field: str) -> str:
    return f"""
      CASE WHEN CAST({field} AS DOUBLE) < 0 THEN 0
           WHEN CAST({field} AS DOUBLE) <= 100 THEN 1
           WHEN CAST({field} AS DOUBLE) <= 300 THEN 2
           WHEN CAST({field} AS DOUBLE) <= 600 THEN 3 ELSE 4 END
    """.strip()


def hour_of_week_sql(time_field: str) -> str:
    stamp = f"to_timestamp(CAST({time_field} AS DOUBLE) / 1000.0)"
    return (
        f"((extract('isodow' FROM {stamp})::INTEGER - 1) * 24 "
        f"+ extract('hour' FROM {stamp})::INTEGER)"
    )


def arrow_numpy(table: Any, name: str, *, nullable_float: bool = False) -> Any:
    _, np, pa, _ = import_dependencies()
    import pyarrow.compute as pc  # type: ignore

    column = table[name].combine_chunks()
    if nullable_float:
        column = pc.cast(column, pa.float64(), safe=True)
        column = pc.fill_null(column, pa.scalar(float("nan"), type=pa.float64()))
        return np.asarray(column.to_numpy(zero_copy_only=False), dtype=np.float64)
    if pa.types.is_boolean(column.type):
        column = pc.fill_null(column, pa.scalar(False, type=pa.bool_()))
        return np.asarray(column.to_numpy(zero_copy_only=False), dtype=np.bool_)
    if pa.types.is_integer(column.type):
        column = pc.cast(column, pa.int64(), safe=True)
        column = pc.fill_null(column, pa.scalar(-1, type=pa.int64()))
        return np.asarray(column.to_numpy(zero_copy_only=False), dtype=np.int64)
    column = pc.cast(column, pa.float64(), safe=True)
    column = pc.fill_null(column, pa.scalar(float("nan"), type=pa.float64()))
    return np.asarray(column.to_numpy(zero_copy_only=False), dtype=np.float64)


def normal_two_sided_p(t_value: float) -> float:
    return math.erfc(abs(t_value) / math.sqrt(2.0)) if math.isfinite(t_value) else math.nan


def dense_codes(values: Any) -> tuple[Any, int]:
    _, np, _, _ = import_dependencies()
    uniques, codes = np.unique(np.asarray(values), return_inverse=True)
    if codes.size and np.any(codes < 0):
        raise RuntimeError("Fixed-effect values contain missing codes")
    return codes.astype(np.int64, copy=False), int(uniques.size)


def demean_once(matrix: Any, codes: Any, levels: int) -> Any:
    _, np, _, _ = import_dependencies()
    residual = np.asarray(matrix, dtype=np.float64).copy()
    counts = np.bincount(codes, minlength=levels).astype(np.float64)
    valid = counts > 0
    for column in range(residual.shape[1]):
        sums = np.bincount(codes, weights=residual[:, column], minlength=levels)
        means = np.zeros(levels, dtype=np.float64)
        means[valid] = sums[valid] / counts[valid]
        residual[:, column] -= means[codes]
    return residual


def maximum_scaled_group_mean(
    matrix: Any, fixed_effects: Sequence[tuple[Any, int]], reference: Any
) -> float:
    _, np, _, _ = import_dependencies()
    scales = np.maximum(np.sqrt(np.mean(np.square(reference), axis=0)), 1.0)
    maximum = 0.0
    for codes, levels in fixed_effects:
        counts = np.bincount(codes, minlength=levels).astype(np.float64)
        valid = counts > 0
        for column in range(matrix.shape[1]):
            sums = np.bincount(codes, weights=matrix[:, column], minlength=levels)
            means = np.zeros(levels, dtype=np.float64)
            means[valid] = sums[valid] / counts[valid]
            if np.any(valid):
                maximum = max(
                    maximum,
                    float(np.max(np.abs(means[valid]))) / float(scales[column]),
                )
    return maximum


def absorb_two_way_exact(
    matrix: Any, first_codes: Any, second_codes: Any, *, tolerance: float = 1e-9
) -> tuple[Any, float]:
    """Project exactly off a large first FE and a small second FE."""
    _, np, _, _ = import_dependencies()
    source = np.asarray(matrix, dtype=np.float64)
    first, first_levels = dense_codes(first_codes)
    second, second_levels = dense_codes(second_codes)
    if first_levels < 1 or second_levels < 2:
        raise RuntimeError(
            f"Two-way absorption lacks support: first={first_levels} second={second_levels}"
        )
    if second_levels > 128:
        raise RuntimeError(f"Second fixed effect is too large: {second_levels}")
    cell_count = first_levels * second_levels
    if cell_count > 350_000_000:
        raise MemoryError(f"Chooser-by-bin incidence is too large: {cell_count:,}")

    within_first = demean_once(source, first, first_levels)
    first_counts = np.bincount(first, minlength=first_levels).astype(np.float64)
    second_counts = np.bincount(second, minlength=second_levels).astype(np.float64)
    incidence = np.zeros((first_levels, second_levels), dtype=np.int32)
    np.add.at(incidence, (first, second), 1)
    cross = np.diag(second_counts)
    block_rows = max(1, 2_000_000 // second_levels)
    for start in range(0, first_levels, block_rows):
        stop = min(start + block_rows, first_levels)
        block = incidence[start:stop].astype(np.float64)
        cross -= (block.T / first_counts[start:stop]) @ block
    del incidence
    cross = (cross + cross.T) / 2.0
    second_cross = np.column_stack(
        [
            np.bincount(second, weights=within_first[:, col], minlength=second_levels)
            for col in range(within_first.shape[1])
        ]
    )
    coefficients = np.linalg.pinv(cross, rcond=1e-12, hermitian=True) @ second_cross
    fitted = coefficients[second].copy()
    for column in range(fitted.shape[1]):
        chooser_sums = np.bincount(first, weights=fitted[:, column], minlength=first_levels)
        fitted[:, column] -= (chooser_sums / first_counts)[first]
    residual = within_first - fitted
    effects = ((first, first_levels), (second, second_levels))
    orthogonality = maximum_scaled_group_mean(residual, effects, source)
    if not math.isfinite(orthogonality) or orthogonality > tolerance:
        raise RuntimeError(
            "Exact two-way absorption failed orthogonality QA: "
            f"{orthogonality:.3e} > {tolerance:.3e}"
        )
    return residual, orthogonality


def absorb_matrix(
    matrix: Any, fixed_effect_codes: Sequence[Any], *, tolerance: float = 1e-9
) -> tuple[Any, int, float, str]:
    _, np, _, _ = import_dependencies()
    source = np.asarray(matrix, dtype=np.float64)
    if not fixed_effect_codes:
        return source.copy(), 0, 0.0, "none"
    if len(fixed_effect_codes) == 1:
        codes, levels = dense_codes(fixed_effect_codes[0])
        residual = demean_once(source, codes, levels)
        orthogonality = maximum_scaled_group_mean(
            residual, ((codes, levels),), source
        )
        if not math.isfinite(orthogonality) or orthogonality > tolerance:
            raise RuntimeError("One-way absorption failed orthogonality QA")
        return residual, 1, orthogonality, "one_way_exact"
    if len(fixed_effect_codes) == 2:
        residual, orthogonality = absorb_two_way_exact(
            source, fixed_effect_codes[0], fixed_effect_codes[1], tolerance=tolerance
        )
        return residual, 1, orthogonality, "two_way_schur_exact"
    raise RuntimeError("At most two high-dimensional fixed effects are supported")


def fit_lpm_cluster(
    *,
    outcome: Any,
    regressors: Mapping[str, Any],
    clusters: Any,
    fixed_effects: Sequence[Any],
    exposure_names: Sequence[str],
    row_ids: Any,
    specification: Mapping[str, Any],
) -> dict[str, Any]:
    _, np, _, _ = import_dependencies()
    names = list(regressors)
    y = np.asarray(outcome, dtype=np.float64)
    x = np.column_stack([np.asarray(regressors[name], dtype=np.float64) for name in names])
    cluster_raw = np.asarray(clusters)
    row_ids = np.asarray(row_ids)
    if y.size < 1_000 or x.shape[0] != y.size or cluster_raw.size != y.size:
        raise RuntimeError(f"{specification.get('model')}: insufficient or inconsistent rows")
    finite = np.isfinite(y) & np.all(np.isfinite(x), axis=1)
    finite &= np.isfinite(cluster_raw)
    for values in fixed_effects:
        finite &= np.isfinite(np.asarray(values))
    if not np.all(finite):
        y = y[finite]
        x = x[finite]
        cluster_raw = cluster_raw[finite]
        row_ids = row_ids[finite]
        fixed_effects = [np.asarray(values)[finite] for values in fixed_effects]
    transformed, iterations, last, method = absorb_matrix(
        np.column_stack([y, x]), fixed_effects
    )
    y_resid = transformed[:, 0]
    x_resid = transformed[:, 1:]
    norms = np.sqrt(np.sum(x_resid * x_resid, axis=0))
    for exposure in exposure_names:
        position = names.index(exposure)
        if norms[position] <= 1e-10:
            raise RuntimeError(f"Exposure has no residual variation: {exposure}")
    identifying = np.any(np.abs(x_resid) > 1e-14, axis=1)
    y_fit = y_resid[identifying]
    x_fit = x_resid[identifying]
    cluster_fit, groups = dense_codes(cluster_raw[identifying])
    n, k = x_fit.shape
    if n <= k or groups < 100:
        raise RuntimeError(f"Insufficient identifying support: n={n} k={k} clusters={groups}")
    xtx = x_fit.T @ x_fit
    rank = int(np.linalg.matrix_rank(xtx))
    inverse = np.linalg.pinv(xtx, rcond=1e-12, hermitian=True)
    beta = inverse @ (x_fit.T @ y_fit)
    residual = y_fit - x_fit @ beta
    scores = np.column_stack(
        [
            np.bincount(
                cluster_fit, weights=x_fit[:, column] * residual, minlength=groups
            )
            for column in range(k)
        ]
    )
    covariance = inverse @ (scores.T @ scores) @ inverse
    covariance *= (groups / (groups - 1.0)) * ((n - 1.0) / (n - k))
    se = np.sqrt(np.maximum(np.diag(covariance), 0.0))
    t_value = np.divide(beta, se, out=np.full_like(beta, np.nan), where=se > 0)
    terms = []
    for name, coefficient, standard_error, t_stat in zip(names, beta, se, t_value, strict=True):
        terms.append(
            {
                "term": name,
                "coefficient_probability_units": float(coefficient),
                "coefficient_percentage_points": float(100.0 * coefficient),
                "standard_error_probability_units": float(standard_error),
                "standard_error_percentage_points": float(100.0 * standard_error),
                "t_cluster": float(t_stat),
                "p_value_two_sided": normal_two_sided_p(float(t_stat)),
            }
        )
    return {
        **dict(specification),
        "status": "ESTIMATED",
        "rows_raw": int(y.size),
        "rows_identifying": int(n),
        "chooser_clusters": int(groups),
        "outcome_mean": float(np.mean(y)),
        "price_mean": float(np.mean(np.asarray(regressors.get("price", np.nan)))),
        "matrix_columns": int(k),
        "matrix_rank": rank,
        "fixed_effect_count": len(fixed_effects),
        "absorption_method": method,
        "absorption_iterations": iterations,
        "absorption_max_scaled_group_mean": last,
        "condition_number_xtx": float(np.linalg.cond(xtx)),
        "exposure_residual_norms": {
            name: float(norms[names.index(name)]) for name in exposure_names
        },
        "terms": terms,
        "sample_sha256": hashlib.sha256(
            np.asarray(row_ids, dtype="<i8").tobytes(order="C")
            + canonical_json(specification).encode("utf-8")
        ).hexdigest(),
    }


def model_term(result: Mapping[str, Any], term: str) -> dict[str, Any]:
    for row in result.get("terms", []):
        if row.get("term") == term:
            return dict(row)
    raise KeyError(f"Model has no term {term}: {result.get('model')}")


def add_lpm_elasticity(
    result: dict[str, Any], *, term: str, price_scale: float | None
) -> dict[str, Any]:
    """Attach elasticity and delta-method CI, treating the sample mean as fixed."""
    row = model_term(result, term)
    quantity = float(result["outcome_mean"])
    multiplier = 1.0 if price_scale is None else float(price_scale)
    elasticity = float(row["coefficient_probability_units"]) * multiplier / quantity
    se = float(row["standard_error_probability_units"]) * abs(multiplier) / quantity
    result["elasticity"] = {
        "term": term,
        "definition": (
            "d Pr(kind)/d log(price) divided by sample Pr(kind)"
            if price_scale is None
            else "d Pr(kind)/d price multiplied by price scale and divided by sample Pr(kind)"
        ),
        "price_scale": price_scale,
        "estimate": elasticity,
        "standard_error_delta_quantity_fixed": se,
        "ci95_low": elasticity - 1.959963984540054 * se,
        "ci95_high": elasticity + 1.959963984540054 * se,
        "causal": False,
    }
    return result


def conditional_fe_poisson(
    *,
    outcome: Any,
    regressors: Mapping[str, Any],
    chooser_codes: Any,
    exposure_name: str,
    specification: Mapping[str, Any],
    maximum_iterations: int = 100,
    tolerance: float = 1e-8,
) -> dict[str, Any]:
    """Conditional chooser-FE Poisson QMLE with chooser-clustered sandwich SEs.

    All-zero chooser groups are excluded by the conditional likelihood.  The input must
    be sorted by chooser so group reductions are exact and memory bounded.
    """
    _, np, _, _ = import_dependencies()
    names = list(regressors)
    y_all = np.asarray(outcome, dtype=np.float64)
    x_all = np.column_stack(
        [np.asarray(regressors[name], dtype=np.float64) for name in names]
    )
    chooser_all = np.asarray(chooser_codes, dtype=np.int64)
    finite = np.isfinite(y_all) & np.all(np.isfinite(x_all), axis=1) & (chooser_all >= 0)
    y_all = y_all[finite]
    x_all = x_all[finite]
    chooser_all = chooser_all[finite]
    if np.any(chooser_all[1:] < chooser_all[:-1]):
        raise RuntimeError("Conditional FE Poisson requires chooser-sorted input")
    starts_all = np.r_[0, np.flatnonzero(chooser_all[1:] != chooser_all[:-1]) + 1]
    ends_all = np.r_[starts_all[1:], y_all.size]
    totals_all = np.add.reduceat(y_all, starts_all)
    informative_group = totals_all > 0
    keep = np.repeat(informative_group, ends_all - starts_all)
    y = y_all[keep]
    x = x_all[keep]
    chooser = chooser_all[keep]
    starts = np.r_[0, np.flatnonzero(chooser[1:] != chooser[:-1]) + 1]
    lengths = np.diff(np.r_[starts, y.size])
    totals = np.add.reduceat(y, starts)
    groups = int(starts.size)
    if y.size < 1_000 or groups < 100:
        raise RuntimeError("Conditional FE Poisson has insufficient informative support")

    def components(beta: Any) -> tuple[float, Any, Any, Any, Any]:
        eta = np.clip(x @ beta, -50.0, 50.0)
        group_max = np.maximum.reduceat(eta, starts)
        exp_eta = np.exp(eta - np.repeat(group_max, lengths))
        denominator = np.add.reduceat(exp_eta, starts)
        probability = exp_eta / np.repeat(denominator, lengths)
        mu = probability * np.repeat(totals, lengths)
        objective = float(
            y @ eta
            - np.sum(totals * (group_max + np.log(denominator)))
        )
        score = x.T @ (y - mu)
        weighted_x_sums = np.column_stack(
            [np.add.reduceat(exp_eta * x[:, column], starts) for column in range(x.shape[1])]
        )
        group_mean_x = weighted_x_sums / denominator[:, None]
        information = x.T @ (mu[:, None] * x)
        centered_group = group_mean_x * np.sqrt(totals)[:, None]
        information -= centered_group.T @ centered_group
        information = (information + information.T) / 2.0
        return objective, score, information, mu, group_mean_x

    beta = np.zeros(x.shape[1], dtype=np.float64)
    objective, score, information, mu, group_mean_x = components(beta)
    converged = False
    last_step = math.inf
    for iteration in range(1, maximum_iterations + 1):
        step = np.linalg.pinv(information, rcond=1e-12, hermitian=True) @ score
        last_step = float(np.max(np.abs(step)))
        scale = 1.0
        accepted = False
        while scale >= 2.0 ** -20:
            candidate = beta + scale * step
            candidate_components = components(candidate)
            if candidate_components[0] >= objective - 1e-10:
                beta = candidate
                objective, score, information, mu, group_mean_x = candidate_components
                accepted = True
                break
            scale *= 0.5
        if not accepted:
            raise RuntimeError("Conditional FE Poisson line search failed")
        if last_step * scale <= tolerance:
            converged = True
            break
    if not converged:
        raise RuntimeError(
            f"Conditional FE Poisson did not converge in {maximum_iterations} iterations"
        )
    residual = y - mu
    group_scores = np.column_stack(
        [np.add.reduceat(residual * x[:, column], starts) for column in range(x.shape[1])]
    )
    bread = np.linalg.pinv(information, rcond=1e-12, hermitian=True)
    covariance = bread @ (group_scores.T @ group_scores) @ bread
    covariance *= groups / (groups - 1.0)
    se = np.sqrt(np.maximum(np.diag(covariance), 0.0))
    terms = []
    for name, coefficient, standard_error in zip(names, beta, se, strict=True):
        t_value = float(coefficient / standard_error) if standard_error > 0 else math.nan
        terms.append(
            {
                "term": name,
                "coefficient": float(coefficient),
                "standard_error_clustered": float(standard_error),
                "t_cluster": t_value,
                "p_value_two_sided": normal_two_sided_p(t_value),
            }
        )
    exposure = next(row for row in terms if row["term"] == exposure_name)
    return {
        **dict(specification),
        "status": "ESTIMATED",
        "rows_all_finite": int(y_all.size),
        "chooser_groups_all_finite": int(starts_all.size),
        "rows_informative_positive_total": int(y.size),
        "chooser_groups_informative_positive_total": groups,
        "all_zero_chooser_groups_excluded": int(np.count_nonzero(~informative_group)),
        "outcomes_in_informative_sample": int(np.sum(y)),
        "iterations": iteration,
        "last_maximum_newton_step": last_step,
        "conditional_log_likelihood_up_to_constant": objective,
        "matrix_rank_information": int(np.linalg.matrix_rank(information)),
        "terms": terms,
        "elasticity": {
            "term": exposure_name,
            "estimate": float(exposure["coefficient"]),
            "standard_error": float(exposure["standard_error_clustered"]),
            "ci95_low": float(exposure["coefficient"] - 1.959963984540054 * exposure["standard_error_clustered"]),
            "ci95_high": float(exposure["coefficient"] + 1.959963984540054 * exposure["standard_error_clustered"]),
            "interpretation": "direct elasticity under conditional Poisson log-link QMLE",
            "causal": False,
        },
    }


def run_self_test() -> None:
    _, np, _, _ = import_dependencies()
    rng = np.random.default_rng(20260825)
    chooser = np.repeat(np.arange(120, dtype=np.int64), 20)
    draw_bin = (chooser % 3) * 2 + rng.integers(0, 2, size=chooser.size)
    log_price = rng.normal(size=chooser.size)
    reference = rng.normal(size=chooser.size)
    latent = -0.12 * log_price + 0.08 * reference + rng.normal(scale=0.6, size=chooser.size)
    y = (latent > np.quantile(latent, 0.88)).astype(np.float64)
    row = np.arange(y.size, dtype=np.int64)
    fitted = fit_lpm_cluster(
        outcome=y,
        regressors={"log_price": log_price, "reference": reference},
        clusters=chooser,
        fixed_effects=(chooser, draw_bin),
        exposure_names=("log_price",),
        row_ids=row,
        specification={"model": "self_test_lpm"},
    )
    if fitted["absorption_method"] != "two_way_schur_exact":
        raise RuntimeError("LPM self-test did not exercise exact two-way absorption")
    ppml = conditional_fe_poisson(
        outcome=y,
        regressors={"log_price": log_price, "reference": reference},
        chooser_codes=chooser,
        exposure_name="log_price",
        specification={"model": "self_test_conditional_fe_poisson"},
    )
    if not math.isfinite(float(ppml["elasticity"]["estimate"])):
        raise RuntimeError("Conditional FE Poisson self-test produced a nonfinite elasticity")
    print("KINDNESS_PRICE_ELASTICITY_COMMON_SELF_TEST_OK", flush=True)


if __name__ == "__main__":
    run_self_test()
