#!/usr/bin/env python3
"""Shared helpers for the Patron Stage 10 post-certification addendum."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import platform
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import duckdb
import numpy as np
import pandas as pd
import pyarrow


VERSION = "1.0.0"
ROOT_SEED = "20260826"

EXPECTED_SOFTWARE = {
    "duckdb": "1.5.2",
    "numpy": "2.4.4",
    "pandas": "3.0.3",
    "pyarrow": "24.0.0",
}

EXPECTED = {
    "stage07_status": "STAGE07_24M_CERTIFIED_OK",
    "stage07_rows": 47_587_020,
    "stage07_months": 24,
    "stage07_kind_draws": 669_503,
    "stage07_producer_sha256": "0411d4061ea9831c20449208a9782aaf668e160139918d106a2b7d63aaa56e6e",
    "stage07_success_sha256": "8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7",
    "snapshot_status": "PROFILE_SNAPSHOT_24M_CERTIFIED_OK",
    "snapshot_rows": 1_305_872,
    "snapshot_columns": 81,
    "kind_role_users": 326_468,
    "control_role_users": 979_404,
    "returned_profiles": 1_305_683,
    "unreturned_profiles": 189,
    "patrons": 4_896,
    "kind_role_returned": 326_427,
    "control_role_returned": 979_256,
    "kind_role_patrons": 1_743,
    "control_role_patrons": 3_153,
    "snapshot_sha256": "f42f28a6540a65c0a83f0da488663b4adddf60d1001daeed556f1ffbb961e238",
    "plan_success_sha256": "2838aa942e20027561763855c387a454d74bb0a92d0a8b62ca47343511897e57",
    "audit_file_hashes_sha256": "be1b69ac46d2a0e44180868e0ccead43ad0043299cffeb0203346c6c0c28aa3e",
}

SNAPSHOT_REQUIRED_COLUMNS = {
    "query_index",
    "canonical_batch_index",
    "username_norm",
    "acquisition_role",
    "matched_kind_chooser_id",
    "control_slot",
    "selected_controls",
    "nested_1to1_available",
    "exact_1to3_group",
    "total_opps",
    "total_kind_count",
    "fair_opps",
    "fair_kind_count",
    "clearly_worse_opps",
    "clearly_worse_kind_count",
    "excluded_middle_opps",
    "excluded_middle_kind_count",
    "mean_chooser_elo",
    "sd_chooser_elo",
    "chooser_elo_n",
    "mean_draw_payoff_fair",
    "mean_win_premium_fair",
    "share_tournament",
    "first_opportunity_utc_ms",
    "last_opportunity_utc_ms",
    "active_months",
    "modal_speed_group",
    "modal_speed_opps",
    "ever_kind_any_state",
    "ever_kind_fair_state",
    "ever_kind_clearly_worse_state",
    "fair_opp_bin",
    "total_opp_bin",
    "historical_common_support_2_20",
    "match_cell",
    "batch_id",
    "batch_index",
    "request_position",
    "username_requested",
    "returned",
    "username_returned",
    "queried_at_utc",
    "http_status",
    "patron",
    "patron_field_present",
    "patron_color",
    "title",
    "disabled",
    "tos_violation",
    "created_at_ms",
    "seen_at_ms",
    "play_time_total_seconds",
    "count_all",
    "count_rated",
    "count_win",
    "count_loss",
    "count_draw",
    "perfs_json",
}

STAGE07_REQUIRED_COLUMNS = {
    "month",
    "chooser_username_norm",
    "kind_draw",
    "engine_eval_cp_disconnected",
    "engine_eval_cp_disconnected_capped600",
    "engine_fairness_bin",
    "fair_competitive",
    "clearly_worse",
    "excluded_middle",
    "chooser_draw_payoff_v2",
    "chooser_win_premium_v2",
    "draw_nonnegative",
    "draw_costly",
    "api_speed",
    "tournament_like_event",
    "chooser_elo",
    "disconnected_elo",
    "chooser_clock_last_obs_s",
    "disconnected_clock_last_obs_s",
    "rating_gap",
    "avg_rating",
}

PUBLIC_FORBIDDEN_COLUMN_TOKENS = (
    "username",
    "account_id",
    "game_id",
    "raw_json",
    "profile_bio",
    "profile_location",
    "real_name",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path, block_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            block = stream.read(block_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _strict_json_value(value: Any) -> Any:
    """Recursively convert NumPy/Pandas values and reject JSON non-finites."""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _strict_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_strict_json_value(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        _strict_json_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(
        path,
        json.dumps(
            _strict_json_value(value),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
    )


def json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    raise TypeError(f"Cannot serialize {type(value)!r}")


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    frame.to_csv(temporary, index=False, lineterminator="\n")
    temporary.replace(path)


def sql_string(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def normalize_username(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip().lower()


def verify_software_exact(fixture: bool = False) -> dict[str, str]:
    observed = {
        "duckdb": duckdb.__version__,
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "pyarrow": pyarrow.__version__,
    }
    if not fixture and observed != EXPECTED_SOFTWARE:
        raise RuntimeError(
            "Canonical numerical environment mismatch. "
            f"Observed={observed}; expected={EXPECTED_SOFTWARE}. "
            "This package never installs or changes dependencies."
        )
    return observed


def runtime_record() -> dict[str, Any]:
    return {
        "created_utc": utc_now(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "software": {
            "duckdb": duckdb.__version__,
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "pyarrow": pyarrow.__version__,
        },
    }


def connect_database(path: Path | None, threads: int, memory_limit: str) -> duckdb.DuckDBPyConnection:
    database = duckdb.connect(str(path) if path else ":memory:")
    database.execute(f"SET threads={max(1, int(threads))}")
    database.execute(f"SET memory_limit={sql_string(memory_limit)}")
    database.execute("SET preserve_insertion_order=false")
    database.execute("SET enable_progress_bar=false")
    return database


def parquet_schema(path_or_glob: Path | str) -> list[str]:
    connection = duckdb.connect(":memory:")
    try:
        rows = connection.execute(
            f"DESCRIBE SELECT * FROM read_parquet({sql_string(path_or_glob)}, union_by_name=true)"
        ).fetchall()
        return [str(row[0]) for row in rows]
    finally:
        connection.close()


def normal_two_sided_p(statistic: float) -> float:
    if not math.isfinite(statistic):
        return math.nan
    return math.erfc(abs(float(statistic)) / math.sqrt(2.0))


def two_proportion_contrast(
    treated_successes: int,
    treated_n: int,
    control_successes: int,
    control_n: int,
) -> dict[str, Any]:
    if treated_n <= 0 or control_n <= 0:
        return {
            "treated_n": int(treated_n),
            "control_n": int(control_n),
            "treated_successes": int(treated_successes),
            "control_successes": int(control_successes),
            "status": "not_estimable",
        }
    treated_rate = treated_successes / treated_n
    control_rate = control_successes / control_n
    gap = treated_rate - control_rate
    unpooled_se = math.sqrt(
        treated_rate * (1.0 - treated_rate) / treated_n
        + control_rate * (1.0 - control_rate) / control_n
    )
    pooled = (treated_successes + control_successes) / (treated_n + control_n)
    pooled_se = math.sqrt(pooled * (1.0 - pooled) * (1.0 / treated_n + 1.0 / control_n))
    z = gap / pooled_se if pooled_se > 0 else math.nan
    return {
        "status": "estimated",
        "treated_n": int(treated_n),
        "control_n": int(control_n),
        "treated_successes": int(treated_successes),
        "control_successes": int(control_successes),
        "treated_rate_pct": 100.0 * treated_rate,
        "control_rate_pct": 100.0 * control_rate,
        "gap_pp": 100.0 * gap,
        "unpooled_se_pp": 100.0 * unpooled_se,
        "ci95_low_pp": 100.0 * (gap - 1.959963984540054 * unpooled_se),
        "ci95_high_pp": 100.0 * (gap + 1.959963984540054 * unpooled_se),
        "pooled_z": z,
        "pooled_p_two_sided": normal_two_sided_p(z),
        "relative_ratio": treated_rate / control_rate if control_rate > 0 else math.nan,
        "relative_lift_pct": 100.0 * (treated_rate / control_rate - 1.0) if control_rate > 0 else math.nan,
    }


def contrast_from_frame(
    frame: pd.DataFrame,
    treated_col: str,
    outcome_col: str = "patron",
) -> dict[str, Any]:
    treated = frame[frame[treated_col].astype(bool)]
    control = frame[~frame[treated_col].astype(bool)]
    return two_proportion_contrast(
        int(pd.to_numeric(treated[outcome_col], errors="coerce").sum()),
        int(len(treated)),
        int(pd.to_numeric(control[outcome_col], errors="coerce").sum()),
        int(len(control)),
    )


def deterministic_control_slot(group_id: str, replicate: int, root_seed: str = ROOT_SEED) -> int:
    payload = f"{root_seed}|rematch|{replicate}|{group_id}"
    digest = hashlib.sha256(payload.encode("utf-8")).digest()
    return 1 + (int.from_bytes(digest[:8], "big") % 3)


def impute_within_cell(
    frame: pd.DataFrame,
    columns: Sequence[str],
    cell_col: str,
) -> tuple[pd.DataFrame, list[str], dict[str, Any]]:
    """Median-impute without reading the outcome and add deterministic indicators."""
    out = frame.copy()
    indicator_columns: list[str] = []
    diagnostics: dict[str, Any] = {}
    groups = out.groupby(cell_col, observed=True, sort=False)
    for column in columns:
        # DuckDB/Pandas represents integer Parquet columns containing nulls as
        # nullable Int64. A within-cell median can legitimately be fractional,
        # and Pandas 3 correctly refuses to insert that float into Int64. Cast
        # both the source and medians to ordinary float64 before filling so the
        # estimator preserves the exact median rather than truncating it.
        numeric = (
            pd.to_numeric(out[column], errors="coerce").astype(np.float64)
            if column in out
            else pd.Series(np.nan, index=out.index, dtype=np.float64)
        )
        missing = ~np.isfinite(numeric.to_numpy(dtype=float, na_value=np.nan))
        indicator = f"{column}__missing"
        out[indicator] = missing.astype(np.int8)
        indicator_columns.append(indicator)
        cell_median = (
            pd.to_numeric(groups[column].transform("median"), errors="coerce").astype(np.float64)
            if column in out
            else pd.Series(np.nan, index=out.index, dtype=np.float64)
        )
        global_median = float(numeric.median()) if numeric.notna().any() else 0.0
        filled = numeric.fillna(pd.to_numeric(cell_median, errors="coerce")).fillna(global_median)
        out[column] = filled.astype(float)
        diagnostics[column] = {
            "missing": int(missing.sum()),
            "missing_share": float(missing.mean()),
            "global_fallback_median": global_median,
            "cells_all_missing": int(
                pd.DataFrame({cell_col: out[cell_col], "missing": missing})
                .groupby(cell_col, observed=True)["missing"]
                .all()
                .sum()
            ),
        }
    return out, indicator_columns, diagnostics


@dataclass
class OLSResult:
    model: dict[str, Any]
    coefficients: pd.DataFrame
    covariance: np.ndarray
    kept_names: list[str]


def _demean_by_codes(values: np.ndarray, codes: np.ndarray, groups: int) -> np.ndarray:
    counts = np.bincount(codes, minlength=groups).astype(float)
    sums = np.bincount(codes, weights=values, minlength=groups)
    means = np.divide(sums, counts, out=np.zeros_like(sums), where=counts > 0)
    return values - means[codes]


def _deterministic_rank_keep(gram: np.ndarray, names: Sequence[str], tolerance: float = 1e-10) -> tuple[list[int], dict[str, str]]:
    kept: list[int] = []
    dropped: dict[str, str] = {}
    scale = max(float(np.max(np.diag(gram))) if gram.size else 0.0, 1.0)
    for index, name in enumerate(names):
        own = float(gram[index, index])
        if own <= tolerance * scale:
            dropped[name] = "zero_after_fixed_effect_absorption"
            continue
        if not kept:
            kept.append(index)
            continue
        cross = gram[np.ix_(kept, [index])].reshape(-1)
        base = gram[np.ix_(kept, kept)]
        residual_ss = own - float(cross @ np.linalg.pinv(base, rcond=tolerance) @ cross)
        if residual_ss <= tolerance * max(own, scale):
            dropped[name] = "deterministically_collinear"
        else:
            kept.append(index)
    return kept, dropped


def fit_absorbed_ols(
    frame: pd.DataFrame,
    *,
    model_name: str,
    y_col: str,
    regressors: Sequence[str],
    fe_col: str,
    covariance: str,
    cluster_col: str | None = None,
    standardize: Iterable[str] = (),
    estimand_class: str = "secondary",
) -> OLSResult:
    """OLS after absorbing one categorical FE, with exact HC1 or CR1 covariance."""
    standardize_set = set(standardize)
    required = list(dict.fromkeys([y_col, fe_col] + list(regressors) + ([cluster_col] if cluster_col else [])))
    missing_columns = [column for column in required if column not in frame.columns]
    if missing_columns:
        raise RuntimeError(f"{model_name}: missing columns {missing_columns}")

    work = frame[required].copy()
    y = pd.to_numeric(work[y_col], errors="coerce").to_numpy(dtype=float)
    valid = np.isfinite(y) & work[fe_col].notna().to_numpy()
    numeric_columns: list[np.ndarray] = []
    standardization: dict[str, Any] = {}
    for name in regressors:
        values = pd.to_numeric(work[name], errors="coerce").to_numpy(dtype=float)
        valid &= np.isfinite(values)
        numeric_columns.append(values)
    if cluster_col:
        valid &= work[cluster_col].notna().to_numpy()

    y = y[valid]
    work = work.loc[valid].reset_index(drop=True)
    raw_x = [values[valid] for values in numeric_columns]
    if len(y) == 0:
        raise RuntimeError(f"{model_name}: empty estimation sample")

    x_columns: list[np.ndarray] = []
    for name, values in zip(regressors, raw_x):
        if name in standardize_set:
            mean = float(values.mean())
            sd = float(values.std(ddof=0))
            if not math.isfinite(sd) or sd <= 0:
                transformed = np.zeros_like(values)
                sd = 0.0
            else:
                transformed = (values - mean) / sd
            standardization[name] = {"mean": mean, "sd_population": sd}
            x_columns.append(transformed)
        else:
            x_columns.append(values)

    fe_codes, fe_levels = pd.factorize(work[fe_col].astype(str), sort=True)
    fe_codes = fe_codes.astype(np.int64)
    n_fe = len(fe_levels)
    y_within = _demean_by_codes(y, fe_codes, n_fe)
    x_within = np.column_stack(
        [_demean_by_codes(column, fe_codes, n_fe) for column in x_columns]
    )

    gram_all = x_within.T @ x_within
    keep_indices, dropped = _deterministic_rank_keep(gram_all, list(regressors))
    if not keep_indices:
        raise RuntimeError(f"{model_name}: no regressors survive FE absorption")
    kept_names = [str(regressors[index]) for index in keep_indices]
    x = x_within[:, keep_indices]
    gram = x.T @ x
    x_y = x.T @ y_within
    gram_inverse = np.linalg.pinv(gram, rcond=1e-12)
    beta = gram_inverse @ x_y
    residual = y_within - x @ beta
    n = int(len(y))
    k = int(len(kept_names))

    meat = np.zeros((k, k), dtype=float)
    n_clusters = 0
    if covariance.upper() == "HC1":
        chunk = 250_000
        for start in range(0, n, chunk):
            stop = min(n, start + chunk)
            xb = x[start:stop]
            ub = residual[start:stop]
            meat += xb.T @ (xb * (ub * ub)[:, None])
        scale = n / max(n - k, 1)
        vcov = scale * gram_inverse @ meat @ gram_inverse
        covariance_label = "HC1"
    elif covariance.upper() == "CR1":
        if cluster_col is None:
            raise RuntimeError(f"{model_name}: CR1 requires cluster_col")
        cluster_codes, cluster_levels = pd.factorize(work[cluster_col].astype(str), sort=True)
        cluster_codes = cluster_codes.astype(np.int64)
        n_clusters = int(len(cluster_levels))
        if n_clusters < 2:
            raise RuntimeError(f"{model_name}: fewer than two clusters")
        scores = np.column_stack(
            [
                np.bincount(cluster_codes, weights=x[:, index] * residual, minlength=n_clusters)
                for index in range(k)
            ]
        )
        meat = scores.T @ scores
        scale = (n_clusters / (n_clusters - 1.0)) * ((n - 1.0) / max(n - k, 1))
        vcov = scale * gram_inverse @ meat @ gram_inverse
        covariance_label = "CR1"
    else:
        raise RuntimeError(f"Unknown covariance: {covariance}")

    diagonal = np.maximum(np.diag(vcov), 0.0)
    standard_errors = np.sqrt(diagonal)
    rows: list[dict[str, Any]] = []
    for index, name in enumerate(kept_names):
        coefficient = float(beta[index])
        se = float(standard_errors[index])
        statistic = coefficient / se if se > 0 else math.nan
        rows.append(
            {
                "model": model_name,
                "estimand_class": estimand_class,
                "variable": name,
                "status": "estimated",
                "coefficient_pp": coefficient,
                "se_pp": se,
                "statistic": statistic,
                "p_two_sided_approx": normal_two_sided_p(statistic),
                "ci95_low_pp": coefficient - 1.959963984540054 * se,
                "ci95_high_pp": coefficient + 1.959963984540054 * se,
                "covariance": covariance_label,
                "n": n,
                "rank": k,
                "fixed_effects": fe_col,
                "clusters": n_clusters if covariance_label == "CR1" else None,
            }
        )
    for name, reason in dropped.items():
        rows.append(
            {
                "model": model_name,
                "estimand_class": estimand_class,
                "variable": name,
                "status": "dropped",
                "drop_reason": reason,
                "coefficient_pp": math.nan,
                "se_pp": math.nan,
                "statistic": math.nan,
                "p_two_sided_approx": math.nan,
                "ci95_low_pp": math.nan,
                "ci95_high_pp": math.nan,
                "covariance": covariance_label,
                "n": n,
                "rank": k,
                "fixed_effects": fe_col,
                "clusters": n_clusters if covariance_label == "CR1" else None,
            }
        )

    model = {
        "model": model_name,
        "estimand_class": estimand_class,
        "status": "estimated",
        "outcome": y_col,
        "requested_regressors": list(regressors),
        "kept_regressors": kept_names,
        "dropped_regressors": dropped,
        "standardization": standardization,
        "fixed_effects": fe_col,
        "covariance": covariance_label,
        "cluster": cluster_col if covariance_label == "CR1" else None,
        "n": n,
        "rank": k,
        "fixed_effect_levels": n_fe,
        "clusters": n_clusters if covariance_label == "CR1" else None,
    }
    return OLSResult(model=model, coefficients=pd.DataFrame(rows), covariance=vcov, kept_names=kept_names)


def coefficient_difference(result: OLSResult, first: str, second: str, label: str) -> dict[str, Any]:
    if first not in result.kept_names or second not in result.kept_names:
        return {
            "model": result.model["model"],
            "contrast": label,
            "status": "not_estimable",
            "reason": "one_or_both_terms_dropped",
        }
    rows = result.coefficients.set_index("variable")
    i = result.kept_names.index(first)
    j = result.kept_names.index(second)
    difference = float(rows.loc[first, "coefficient_pp"] - rows.loc[second, "coefficient_pp"])
    variance = float(result.covariance[i, i] + result.covariance[j, j] - 2.0 * result.covariance[i, j])
    se = math.sqrt(max(variance, 0.0))
    statistic = difference / se if se > 0 else math.nan
    return {
        "model": result.model["model"],
        "contrast": label,
        "status": "estimated",
        "first": first,
        "second": second,
        "difference_pp": difference,
        "se_pp": se,
        "statistic": statistic,
        "p_two_sided_approx": normal_two_sided_p(statistic),
        "ci95_low_pp": difference - 1.959963984540054 * se,
        "ci95_high_pp": difference + 1.959963984540054 * se,
        "covariance": result.model["covariance"],
        "n": result.model["n"],
    }


def manifest_directory(root: Path, *, excluded_names: Iterable[str] = ()) -> list[dict[str, Any]]:
    excluded = set(excluded_names)
    rows: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if path.name in excluded or relative in excluded:
            continue
        rows.append(
            {
                "relative_path": relative,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return rows


def write_manifest_tsv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    lines = ["relative_path\tbytes\tsha256"]
    lines.extend(f"{row['relative_path']}\t{row['bytes']}\t{row['sha256']}" for row in rows)
    atomic_write_text(path, "\n".join(lines) + "\n")


def read_manifest_tsv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def verify_manifest(root: Path, manifest_path: Path) -> None:
    for row in read_manifest_tsv(manifest_path):
        target = root / row["relative_path"]
        if not target.is_file():
            raise RuntimeError(f"Manifested file is missing: {target}")
        if target.stat().st_size != int(row["bytes"]):
            raise RuntimeError(f"Manifested byte count differs: {target}")
        if sha256_file(target) != row["sha256"]:
            raise RuntimeError(f"Manifested SHA-256 differs: {target}")


def safe_slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")
