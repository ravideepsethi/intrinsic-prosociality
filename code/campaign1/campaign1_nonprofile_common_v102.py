#!/usr/bin/env python3
"""Shared authenticated utilities for Campaign 1 non-profile recovery v1.0.2."""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
import uuid


SCRIPT_VERSION = "1.0.2"
PROJECT_ROOT = Path("/Volumes/XT_Pro/lichess_kindness")
EXPECTED_STAGE07_ROWS = 47_587_020
EXPECTED_STAGE07_FAIR_ROWS = 17_328_130
EXPECTED_RECIPIENT_ROWS = 2_556_782
EXPECTED_USER_EVENT_ROWS = 309_961_276
EXPECTED_PAIR_EVENT_ROWS = 154_693_194
EXPECTED_CHRONOLOGY_FILES = 852
EXPECTED_CHRONOLOGY_ROWS = 7_763_847_245
DAY_MS = 86_400_000
PANEL_START_MS = 1_698_796_800_000
PANEL_END_EXCLUSIVE_MS = 1_761_955_200_000
MAIN_MONTHS = tuple(
    f"{absolute // 12:04d}-{absolute % 12 + 1:02d}"
    for absolute in range(2023 * 12 + 10, 2023 * 12 + 34)
)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def utc_run_id() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(chunk_size):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{uuid.uuid4().hex}")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def atomic_json(path: Path, value: Any) -> None:
    atomic_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        raise RuntimeError(f"Refusing to write empty aggregate table: {path}")
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for field in row:
            if field not in seen:
                seen.add(field)
                fields.append(field)
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


def import_numpy() -> Any:
    try:
        import numpy as np  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("numpy is required") from exc
    return np


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


def load_module(path: Path, name: str) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"Could not import module: {path}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def stage07_paths(root: Path) -> list[Path]:
    paths = [root / f"month={month}/analysis_panel.parquet" for month in MAIN_MONTHS]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise RuntimeError(f"Stage07 monthly inputs are incomplete: {missing[:4]}")
    return paths


def authenticate_stage07(root: Path, expected_success_sha256: str) -> dict[str, Any]:
    """Authenticate the success receipt and every physical monthly Stage 07 file."""
    _, _, _, pq = import_dependencies()
    success_path = root / "_SUCCESS.json"
    if sha256_file(success_path) != expected_success_sha256:
        raise RuntimeError("Stage 07 success receipt hash changed")
    success = load_json(success_path)
    global_qa = success.get("global_qa", {})
    if (
        success.get("final_ok") is not True
        or int(global_qa.get("rows", -1)) != EXPECTED_STAGE07_ROWS
        or int(global_qa.get("fair_rows", -1)) != EXPECTED_STAGE07_FAIR_ROWS
    ):
        raise RuntimeError("Stage 07 success receipt support changed")
    paths = stage07_paths(root)
    outputs = success.get("monthly_outputs")
    if not isinstance(outputs, list) or len(outputs) != len(paths):
        raise RuntimeError("Stage 07 monthly receipt inventory changed")
    by_month = {str(row.get("month")): row for row in outputs}
    authenticated: list[dict[str, Any]] = []
    for month, path in zip(MAIN_MONTHS, paths):
        row = by_month.get(month)
        if row is None:
            raise RuntimeError(f"Stage 07 monthly receipt is missing: {month}")
        actual = {
            "month": month,
            "path": str(path),
            "rows": int(pq.ParquetFile(path).metadata.num_rows),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        expected = {
            "path": row.get("path"),
            "rows": int(row.get("rows", -1)),
            "bytes": int(row.get("output_size_bytes", -1)),
            "sha256": row.get("output_sha256"),
        }
        for key in ("path", "rows", "bytes", "sha256"):
            if actual[key] != expected[key]:
                raise RuntimeError(f"Stage 07 physical month changed: {month} {key}")
        authenticated.append(actual)
    if sum(row["rows"] for row in authenticated) != EXPECTED_STAGE07_ROWS:
        raise RuntimeError("Stage 07 authenticated monthly rows do not conserve")
    return {
        "success_sha256": expected_success_sha256,
        "monthly_files": len(authenticated),
        "rows": EXPECTED_STAGE07_ROWS,
        "fair_rows": EXPECTED_STAGE07_FAIR_ROWS,
        "physical_month_manifest_sha256": sha256_json(authenticated),
    }


def parquet_rows(paths: Iterable[Path]) -> int:
    _, _, _, pq = import_dependencies()
    return sum(int(pq.ParquetFile(path).metadata.num_rows) for path in paths)


def directory_manifest(root: Path) -> list[dict[str, Any]]:
    _, _, _, pq = import_dependencies()
    rows: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*.parquet") if item.is_file()):
        rows.append(
            {
                "path": str(path.relative_to(root)),
                "rows": int(pq.ParquetFile(path).metadata.num_rows),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return rows


def speed_code_sql(field: str) -> str:
    return f"""
      CASE lower(replace(CAST({field} AS VARCHAR), '_', ''))
        WHEN 'ultrabullet' THEN 0
        WHEN 'bullet' THEN 1
        WHEN 'blitz' THEN 2
        WHEN 'rapid' THEN 3
        WHEN 'classical' THEN 4
        WHEN 'correspondence' THEN 5
        ELSE -1
      END
    """.strip()


def rating_band_sql(field: str) -> str:
    return f"""
      CASE
        WHEN CAST({field} AS DOUBLE) < 1600 THEN 0
        WHEN CAST({field} AS DOUBLE) < 2000 THEN 1
        WHEN CAST({field} AS DOUBLE) < 2400 THEN 2
        ELSE 3
      END
    """.strip()


def eval_bin_sql(field: str) -> str:
    return f"""
      CASE
        WHEN CAST({field} AS DOUBLE) < -300 THEN 0
        WHEN CAST({field} AS DOUBLE) < -100 THEN 1
        WHEN CAST({field} AS DOUBLE) < -50 THEN 2
        WHEN CAST({field} AS DOUBLE) < 0 THEN 3
        WHEN CAST({field} AS DOUBLE) <= 50 THEN 4
        WHEN CAST({field} AS DOUBLE) <= 100 THEN 5
        WHEN CAST({field} AS DOUBLE) <= 200 THEN 6
        WHEN CAST({field} AS DOUBLE) <= 400 THEN 7
        WHEN CAST({field} AS DOUBLE) <= 800 THEN 8
        ELSE 9
      END
    """.strip()


def hour_of_week_sql(time_field: str) -> str:
    timestamp = f"to_timestamp(CAST({time_field} AS DOUBLE) / 1000.0)"
    return (
        f"((extract('isodow' FROM {timestamp})::INTEGER - 1) * 24 "
        f"+ extract('hour' FROM {timestamp})::INTEGER)"
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


def factor_codes(values: Any) -> tuple[Any, int]:
    np = import_numpy()
    _, codes = np.unique(np.asarray(values), return_inverse=True)
    codes = codes.astype(np.int64, copy=False)
    return codes, int(codes.max()) + 1 if codes.size else 0


def _absorb_matrix(
    matrix: Any,
    weights: Any,
    fixed_effect_codes: Sequence[Any],
    *,
    tolerance: float = 1e-9,
    maximum_iterations: int = 2_000,
) -> tuple[Any, int, float]:
    """Weighted alternating projections without constructing dummy matrices."""
    np = import_numpy()
    transformed = np.asarray(matrix, dtype=np.float64).copy()
    weights = np.asarray(weights, dtype=np.float64)
    prepared: list[tuple[Any, int, Any]] = []
    for raw in fixed_effect_codes:
        codes, groups = factor_codes(raw)
        denominator = np.bincount(codes, weights=weights, minlength=groups)
        if np.any(denominator <= 0):
            raise RuntimeError("Empty fixed-effect cell reached absorption")
        prepared.append((codes, groups, denominator))
    last = math.inf
    for iteration in range(1, maximum_iterations + 1):
        last = 0.0
        for codes, groups, denominator in prepared:
            for column in range(transformed.shape[1]):
                numerator = np.bincount(
                    codes,
                    weights=weights * transformed[:, column],
                    minlength=groups,
                )
                adjustment = numerator / denominator
                last = max(last, float(np.max(np.abs(adjustment))))
                transformed[:, column] -= adjustment[codes]
        if last <= tolerance:
            return transformed, iteration, last
    raise RuntimeError(
        "HDFE absorption did not converge: "
        f"iterations={maximum_iterations} tolerance={tolerance:.3e} "
        f"last_adjustment={last:.3e}"
    )


def is_hdfe_absorption_nonconvergence(error: BaseException) -> bool:
    """Identify the one numerical failure eligible for an extended retry."""
    return isinstance(error, RuntimeError) and str(error).startswith(
        "HDFE absorption did not converge:"
    )


def normal_two_sided_p(t_value: float) -> float:
    return math.erfc(abs(t_value) / math.sqrt(2.0))


def sample_fingerprint(row_ids: Any, specification: Mapping[str, Any]) -> str:
    np = import_numpy()
    digest = hashlib.sha256()
    digest.update(np.asarray(row_ids, dtype="<i8").tobytes(order="C"))
    digest.update(canonical_json(specification).encode("utf-8"))
    return digest.hexdigest()


def fit_hdfe_cluster(
    *,
    outcome: Any,
    exposures: Mapping[str, Any],
    numeric_controls: Mapping[str, Any],
    fixed_effects: Mapping[str, Any],
    clusters: Any,
    row_ids: Any,
    specification: Mapping[str, Any],
    weights: Any | None = None,
    absorption_tolerance: float = 1e-9,
    absorption_maximum_iterations: int = 2_000,
) -> dict[str, Any]:
    """Linear model with absorbed fixed effects and one-way clustered covariance."""
    np = import_numpy()
    y = np.asarray(outcome, dtype=np.float64)
    n = y.size
    if n < 1_000:
        raise RuntimeError(f"{specification.get('model')}: fewer than 1,000 rows")
    if weights is None:
        weights = np.ones(n, dtype=np.float64)
    else:
        weights = np.asarray(weights, dtype=np.float64)
    columns: list[Any] = []
    names: list[str] = []
    exposure_names = list(exposures)
    for name, values in exposures.items():
        columns.append(np.asarray(values, dtype=np.float64))
        names.append(name)
    for name, values in numeric_controls.items():
        raw = np.asarray(values, dtype=np.float64)
        observed = raw[np.isfinite(raw)]
        if observed.size == 0:
            continue
        median = float(np.median(observed))
        missing = ~np.isfinite(raw)
        filled = raw.copy()
        filled[missing] = median
        scale = float(np.std(filled))
        if not math.isfinite(scale) or scale <= 1e-12:
            continue
        columns.append((filled - float(np.mean(filled))) / scale)
        names.append("z_" + name)
        if np.any(missing):
            columns.append(missing.astype(np.float64))
            names.append(name + "_missing")
    if not columns:
        raise RuntimeError("Model contains no regressors")
    x = np.column_stack(columns)
    finite = np.isfinite(y) & np.isfinite(weights) & (weights > 0)
    finite &= np.all(np.isfinite(x), axis=1)
    for values in fixed_effects.values():
        finite &= np.asarray(values).reshape(-1).shape[0] == n
    if not np.all(finite):
        y = y[finite]
        x = x[finite]
        weights = weights[finite]
        clusters = np.asarray(clusters)[finite]
        row_ids = np.asarray(row_ids)[finite]
        fixed_effects = {
            name: np.asarray(values)[finite] for name, values in fixed_effects.items()
        }
    else:
        clusters = np.asarray(clusters)
        row_ids = np.asarray(row_ids)
    if not math.isfinite(absorption_tolerance) or absorption_tolerance <= 0:
        raise ValueError("absorption_tolerance must be finite and positive")
    if absorption_maximum_iterations < 1:
        raise ValueError("absorption_maximum_iterations must be positive")
    transformed, iterations, last = _absorb_matrix(
        np.column_stack([y, x]),
        weights,
        list(fixed_effects.values()),
        tolerance=absorption_tolerance,
        maximum_iterations=absorption_maximum_iterations,
    )
    y_resid = transformed[:, 0]
    x_resid = transformed[:, 1:]
    norms = np.sqrt(np.sum(weights[:, None] * x_resid * x_resid, axis=0))
    retained = norms > 1e-10
    for exposure in exposure_names:
        index = names.index(exposure)
        if not retained[index]:
            raise RuntimeError(f"Exposure has no residual variation: {exposure}")
    x_resid = x_resid[:, retained]
    retained_names = [name for name, keep in zip(names, retained) if keep]
    root_weight = np.sqrt(weights)
    weighted_x = x_resid * root_weight[:, None]
    weighted_y = y_resid * root_weight
    beta, _, rank, singular = np.linalg.lstsq(weighted_x, weighted_y, rcond=None)
    if int(rank) != x_resid.shape[1]:
        raise RuntimeError(f"Rank-deficient HDFE model: {rank}/{x_resid.shape[1]}")
    residual = y_resid - x_resid @ beta
    bread = np.linalg.inv(weighted_x.T @ weighted_x)
    cluster_codes, groups = factor_codes(clusters)
    if groups < 100:
        raise RuntimeError(f"Too few clusters for inference: {groups}")
    scores = np.empty((groups, x_resid.shape[1]), dtype=np.float64)
    score_weight = weights * residual
    for column in range(x_resid.shape[1]):
        scores[:, column] = np.bincount(
            cluster_codes,
            weights=score_weight * x_resid[:, column],
            minlength=groups,
        )
    correction = (groups / (groups - 1)) * ((y.size - 1) / (y.size - rank))
    covariance = bread @ (scores.T @ scores) @ bread * correction
    standard_errors = np.sqrt(np.maximum(np.diag(covariance), 0.0))
    results: list[dict[str, Any]] = []
    for exposure in exposure_names:
        position = retained_names.index(exposure)
        coefficient = float(beta[position])
        standard_error = float(standard_errors[position])
        t_value = coefficient / standard_error if standard_error > 0 else math.nan
        results.append(
            {
                "term": exposure,
                "coefficient": coefficient,
                "standard_error": standard_error,
                "t_cluster": t_value,
                "p_value_two_sided": normal_two_sided_p(t_value),
            }
        )
    return {
        **dict(specification),
        "rows": int(y.size),
        "clusters": groups,
        "results": results,
        "outcome_mean": float(np.average(y, weights=weights)),
        "exposure_means": {
            name: float(np.average(np.asarray(values)[finite] if not np.all(finite) else values, weights=weights))
            for name, values in exposures.items()
        },
        "numeric_controls": retained_names[len(exposure_names):],
        "fixed_effects": list(fixed_effects),
        "matrix_rank": int(rank),
        "smallest_singular_value": float(singular[-1]),
        "absorption_iterations": iterations,
        "absorption_tolerance": absorption_tolerance,
        "absorption_maximum_iterations": absorption_maximum_iterations,
        "absorption_last_adjustment": last,
        "cluster_correction": correction,
        "sample_specification_sha256": sample_fingerprint(row_ids, specification),
    }


def clustered_weighted_mean(
    values: Any, weights: Any, clusters: Any, sample: Any | None = None
) -> dict[str, Any]:
    np = import_numpy()
    y = np.asarray(values, dtype=np.float64)
    w = np.asarray(weights, dtype=np.float64)
    g = np.asarray(clusters)
    valid = np.isfinite(y) & np.isfinite(w) & (w > 0)
    if sample is not None:
        valid &= np.asarray(sample, dtype=bool)
    y = y[valid]
    w = w[valid]
    g = g[valid]
    if y.size < 2:
        raise RuntimeError("Insufficient rows for weighted mean")
    mean = float(np.sum(w * y) / np.sum(w))
    codes, groups = factor_codes(g)
    scores = np.bincount(codes, weights=w * (y - mean), minlength=groups)
    correction = groups / (groups - 1) if groups > 1 else math.nan
    variance = correction * float(np.sum(scores * scores)) / float(np.sum(w) ** 2)
    standard_error = math.sqrt(max(variance, 0.0))
    t_value = mean / standard_error if standard_error > 0 else math.nan
    return {
        "mean": mean,
        "standard_error": standard_error,
        "t_value": t_value,
        "p_value_two_sided": normal_two_sided_p(t_value),
        "rows": int(y.size),
        "clusters": groups,
        "weight_sum": float(np.sum(w)),
    }


def rate_from_counts(numerator: Any, denominator: Any, *, scale: float = 1.0) -> Any:
    np = import_numpy()
    numerator = np.asarray(numerator, dtype=np.float64)
    denominator = np.asarray(denominator, dtype=np.float64)
    output = np.full(denominator.size, np.nan, dtype=np.float64)
    valid = denominator > 0
    output[valid] = scale * numerator[valid] / denominator[valid]
    return output


def self_test() -> None:
    np = import_numpy()
    rng = np.random.default_rng(20260825)
    choosers = np.repeat(np.arange(400), 10)
    n = choosers.size
    exposure = rng.normal(size=n)
    control = rng.normal(size=n)
    chooser_effect = rng.normal(scale=0.2, size=400)[choosers]
    outcome = 0.35 * exposure - 0.15 * control + chooser_effect + rng.normal(scale=0.05, size=n)
    fitted = fit_hdfe_cluster(
        outcome=outcome,
        exposures={"x": exposure},
        numeric_controls={"c": control},
        fixed_effects={"chooser": choosers, "period": np.tile(np.arange(10), 400)},
        clusters=choosers,
        row_ids=np.arange(n),
        specification={"model": "synthetic_hdfe"},
    )
    coefficient = fitted["results"][0]["coefficient"]
    if abs(coefficient - 0.35) > 0.02:
        raise RuntimeError(f"Synthetic HDFE coefficient mismatch: {coefficient}")
    if (
        fitted["absorption_tolerance"] != 1e-9
        or fitted["absorption_maximum_iterations"] != 2_000
        or not is_hdfe_absorption_nonconvergence(
            RuntimeError(
                "HDFE absorption did not converge: iterations=2000 "
                "tolerance=1.000e-09 last_adjustment=1.000e-06"
            )
        )
    ):
        raise RuntimeError("HDFE recovery-policy metadata self-test failed")
    rates = rate_from_counts(np.array([0, 2, 3]), np.array([0, 4, 6]), scale=1000)
    if not np.isnan(rates[0]) or not np.allclose(rates[1:], [500, 500]):
        raise RuntimeError("Rate construction self-test failed")
    print("CAMPAIGN1_NONPROFILE_COMMON_SELF_TEST_OK")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    arguments = parser.parse_args()
    if arguments.self_test:
        self_test()
