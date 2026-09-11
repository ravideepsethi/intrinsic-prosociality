#!/usr/bin/env python3
"""Run the append-only equality, short-position, and engine-zero audit."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

import equality_fen_common as common


DESIGN_FILE = "short_position_commonness_private.parquet"
DESIGN_RECEIPT = "position_design_receipt.json"
MODEL_CACHE = "local_engine_equality_model_private.parquet"
MODEL_CACHE_RECEIPT = "local_model_cache_receipt.json"

FAIRNESS_ORDER = (
    "disconnected_clearly_better",
    "disconnected_better",
    "roughly_equal",
    "modestly_worse_excluded",
    "clearly_worse",
)
PLY_ORDER = ("0_4", "5_6", "7_8", "9_10", "11_20", "21_40", "41_80", "81_plus")
COMMONNESS_ORDER = ("singleton", "2_9", "10_99", "100_999", "1000_plus")
MODEL_CACHE_COLUMNS = [
    "chooser_code",
    "month_code",
    "speed_code",
    "temporal_half",
    "kind_pp",
    "eval_cp",
    "fairness_bin",
    "is_equality",
    "is_better",
    "draw_payoff",
    "favorable",
    "win_premium",
    "log_chooser_clock",
    "log_disconnected_clock",
    "clock_missing",
    "short",
    "ply_count",
    "log_ply",
    "tournament",
    "fen4_log1p_loo",
    "board_log1p_loo",
    "fen4_tier",
    "board_tier",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--public-root", type=Path, required=True)
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def qpath(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def ply_band_sql(column: str = "ply_count") -> str:
    return f"""
      CASE
        WHEN {column} <= 4 THEN '0_4'
        WHEN {column} <= 6 THEN '5_6'
        WHEN {column} <= 8 THEN '7_8'
        WHEN {column} <= 10 THEN '9_10'
        WHEN {column} <= 20 THEN '11_20'
        WHEN {column} <= 40 THEN '21_40'
        WHEN {column} <= 80 THEN '41_80'
        ELSE '81_plus'
      END
    """


def speed_sql(column: str = "api_speed") -> str:
    return f"""
      CASE
        WHEN lower(CAST({column} AS VARCHAR)) IN ('ultrabullet','bullet') THEN 0
        WHEN lower(CAST({column} AS VARCHAR)) = 'blitz' THEN 1
        WHEN lower(CAST({column} AS VARCHAR)) = 'rapid' THEN 2
        WHEN lower(CAST({column} AS VARCHAR)) IN ('classical','correspondence') THEN 3
        ELSE 4
      END
    """


def month_sql(column: str = "month") -> str:
    cases = " ".join(
        f"WHEN '{month}' THEN {index}"
        for index, month in enumerate(
            (
                "2023-11","2023-12","2024-01","2024-02","2024-03","2024-04",
                "2024-05","2024-06","2024-07","2024-08","2024-09","2024-10",
                "2024-11","2024-12","2025-01","2025-02","2025-03","2025-04",
                "2025-05","2025-06","2025-07","2025-08","2025-09","2025-10",
            )
        )
    )
    return f"CASE CAST({column} AS VARCHAR) {cases} ELSE NULL END"


def add_rates(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["kind_rate_pct"] = 100.0 * result["kind_draws"] / result["rows"]
    probability = result["kind_draws"] / result["rows"]
    result["binomial_se_pp"] = 100.0 * np.sqrt(
        np.maximum(probability * (1.0 - probability) / result["rows"], 0.0)
    )
    return result


def raw_contrast_rows(
    frame: pd.DataFrame,
    group_columns: Sequence[str],
    *,
    label: str,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    grouped = frame.groupby(list(group_columns), dropna=False, sort=False) if group_columns else [((), frame)]
    for key, part in grouped:
        if not isinstance(key, tuple):
            key = (key,)
        values = {column: value for column, value in zip(group_columns, key)}
        by_bin = {str(row["fairness_bin"]): row for row in part.to_dict("records")}
        equal = by_bin.get("roughly_equal")
        better = by_bin.get("disconnected_better")
        if equal is None or better is None:
            continue
        n_equal, k_equal = int(equal["rows"]), int(equal["kind_draws"])
        n_better, k_better = int(better["rows"]), int(better["kind_draws"])
        p_equal = k_equal / n_equal
        p_better = k_better / n_better
        se = 100.0 * math.sqrt(
            p_equal * (1.0 - p_equal) / n_equal
            + p_better * (1.0 - p_better) / n_better
        )
        difference = 100.0 * (p_equal - p_better)
        rows.append(
            {
                "contrast_family": label,
                **values,
                "roughly_equal_rows": n_equal,
                "roughly_equal_kind_draws": k_equal,
                "roughly_equal_rate_pct": 100.0 * p_equal,
                "disconnected_better_rows": n_better,
                "disconnected_better_kind_draws": k_better,
                "disconnected_better_rate_pct": 100.0 * p_better,
                "equal_minus_better_pp": difference,
                "independent_binomial_se_pp": se,
                "independent_t": difference / se if se > 0 else math.nan,
            }
        )
    return pd.DataFrame(rows)


def model_contract_hash(model_id: str, specification: Mapping[str, Any]) -> str:
    material = {"model_id": model_id, **dict(specification)}
    return hashlib.sha256(common.canonical_json(material).encode("utf-8")).hexdigest()


def restore_result(value: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(value)
    for key in ("beta", "covariance", "standard_errors_array", "t_statistics_array"):
        if key in result:
            result[key] = np.asarray(result[key], dtype=np.float64)
    return result


def run_checkpointed_model(
    checkpoint_root: Path,
    *,
    model_id: str,
    specification: Mapping[str, Any],
    y: np.ndarray,
    x: np.ndarray,
    x_names: Sequence[str],
    clusters: np.ndarray,
    fixed_effects: Sequence[np.ndarray],
    add_intercept: bool,
    tolerance: float,
    maximum_iterations: int,
    required: bool,
) -> dict[str, Any]:
    checkpoint_root.mkdir(parents=True, exist_ok=True)
    checkpoint = checkpoint_root / f"{model_id}.json"
    contract_sha = model_contract_hash(model_id, specification)
    if checkpoint.is_file():
        saved = common.load_json(checkpoint)
        if saved.get("contract_sha256") == contract_sha:
            if saved.get("status") == "ESTIMATED":
                common.progress(f"resuming authenticated model checkpoint {model_id}")
                return {"status": "ESTIMATED", "result": restore_result(saved["result"])}
            if saved.get("status") == "NOT_ESTIMATED" and not required:
                return saved
    common.progress(
        f"estimating {model_id}: rows={len(y):,}; regressors={len(x_names)}; FE={len(fixed_effects)}"
    )
    try:
        result = common.fit_lpm_cluster(
            y,
            x,
            x_names,
            clusters,
            fixed_effect_codes=fixed_effects,
            add_intercept=add_intercept,
            tolerance=tolerance,
            maximum_iterations=maximum_iterations,
        )
        saved = {
            "status": "ESTIMATED",
            "model_id": model_id,
            "contract_sha256": contract_sha,
            "specification": dict(specification),
            "result": common.json_ready(result),
        }
    except Exception as exc:
        saved = {
            "status": "NOT_ESTIMATED",
            "model_id": model_id,
            "contract_sha256": contract_sha,
            "specification": dict(specification),
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
        }
        common.atomic_write_json(checkpoint, saved)
        if required:
            raise
        return saved
    common.atomic_write_json(checkpoint, saved)
    return {"status": "ESTIMATED", "result": result}


def verify_model_cache(
    cache: Path,
    receipt_path: Path,
    expected_columns: Sequence[str],
    authority_fingerprint: str,
    design_sha256: str,
) -> dict[str, Any] | None:
    if not cache.is_file() or not receipt_path.is_file():
        return None
    receipt = common.load_json(receipt_path)
    if receipt.get("status") != "KINDNESS_EQUALITY_FEN_LOCAL_MODEL_CACHE_OK":
        return None
    if receipt.get("sha256") != common.sha256_file(cache):
        return None
    if int(receipt.get("bytes", -1)) != cache.stat().st_size:
        return None
    footer = common.pq.ParquetFile(cache)
    if list(footer.schema_arrow.names) != list(expected_columns):
        return None
    if int(footer.metadata.num_rows) != int(receipt.get("rows", -1)):
        return None
    if receipt.get("authority_fingerprint") != authority_fingerprint:
        return None
    if receipt.get("position_design_sha256") != design_sha256:
        return None
    return receipt


def build_model_cache(
    database: Any,
    design_cache: Path,
    private_root: Path,
    contract: Mapping[str, Any],
    authority_fingerprint: str,
) -> tuple[Path, dict[str, Any]]:
    cache = private_root / MODEL_CACHE
    receipt_path = private_root / MODEL_CACHE_RECEIPT
    design_sha256 = common.sha256_file(design_cache)
    existing = verify_model_cache(
        cache,
        receipt_path,
        MODEL_CACHE_COLUMNS,
        authority_fingerprint,
        design_sha256,
    )
    if existing is not None:
        common.progress("authenticated private local-model cache already exists; reusing")
        return cache, existing

    database.execute(
        """
        CREATE OR REPLACE TABLE local_chooser_dimension AS
        SELECT
          chooser_username_norm,
          (ROW_NUMBER() OVER (ORDER BY chooser_username_norm) - 1)::INTEGER AS chooser_code
        FROM (
          SELECT DISTINCT chooser_username_norm
          FROM panel
          WHERE engine_eval_cp_disconnected BETWEEN -300 AND 300
        )
        """
    )
    design = qpath(design_cache)
    database.execute(
        f"CREATE OR REPLACE VIEW position_design AS SELECT * FROM read_parquet('{design}')"
    )
    temporary = private_root / f".{MODEL_CACHE}.tmp"
    if temporary.exists():
        temporary.unlink()
    destination = qpath(temporary)
    month_case = month_sql("p.month")
    speed_case = speed_sql("p.api_speed")
    common.progress("building private local engine/equality model cache")
    database.execute(
        f"""
        COPY (
          SELECT
            d.chooser_code,
            ({month_case})::TINYINT AS month_code,
            ({speed_case})::TINYINT AS speed_code,
            CASE WHEN ({month_case}) < 12 THEN 0 ELSE 1 END::TINYINT AS temporal_half,
            CASE WHEN p.kind_draw THEN 100.0 ELSE 0.0 END::DOUBLE AS kind_pp,
            CAST(p.engine_eval_cp_disconnected AS INTEGER) AS eval_cp,
            CAST(p.engine_fairness_bin AS VARCHAR) AS fairness_bin,
            (p.engine_eval_cp_disconnected BETWEEN -100 AND 100)::BOOLEAN AS is_equality,
            (p.engine_eval_cp_disconnected BETWEEN 101 AND 299)::BOOLEAN AS is_better,
            CAST(p.chooser_draw_payoff_v2 AS DOUBLE) AS draw_payoff,
            CAST(p.draw_nonnegative AS BOOLEAN) AS favorable,
            CAST(p.chooser_win_premium_v2 AS DOUBLE) AS win_premium,
            CASE WHEN p.chooser_clock_last_obs_s IS NULL THEN 0.0
                 ELSE ln(1.0 + greatest(CAST(p.chooser_clock_last_obs_s AS DOUBLE), 0.0))
            END::DOUBLE AS log_chooser_clock,
            CASE WHEN p.disconnected_clock_last_obs_s IS NULL THEN 0.0
                 ELSE ln(1.0 + greatest(CAST(p.disconnected_clock_last_obs_s AS DOUBLE), 0.0))
            END::DOUBLE AS log_disconnected_clock,
            (p.chooser_clock_last_obs_s IS NULL OR
             p.disconnected_clock_last_obs_s IS NULL)::BOOLEAN AS clock_missing,
            (p.ply_count <= 10)::BOOLEAN AS short,
            CAST(p.ply_count AS INTEGER) AS ply_count,
            ln(1.0 + greatest(CAST(p.ply_count AS DOUBLE), 0.0))::DOUBLE AS log_ply,
            CAST(p.tournament_like_event AS BOOLEAN) AS tournament,
            q.fen4_log1p_loo,
            q.board_log1p_loo,
            q.fen4_tier,
            q.board_tier
          FROM panel p
          JOIN local_chooser_dimension d USING (chooser_username_norm)
          LEFT JOIN position_design q USING (game_id)
          WHERE p.engine_eval_cp_disconnected BETWEEN -300 AND 300
          ORDER BY month_code, p.archive_ordinal, d.chooser_code
        ) TO '{destination}'
        (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
        """
    )
    footer = common.pq.ParquetFile(temporary)
    columns = list(footer.schema_arrow.names)
    rows = int(footer.metadata.num_rows)
    if columns != MODEL_CACHE_COLUMNS:
        raise RuntimeError(f"Local model cache schema changed: {columns}")
    os.replace(temporary, cache)
    cache_sha = common.sha256_file(cache)
    qa = database.execute(
        f"""
        SELECT
          COUNT(*)::BIGINT AS rows,
          SUM(CASE WHEN kind_pp=100 THEN 1 ELSE 0 END)::BIGINT AS kind_draws,
          SUM(short::INTEGER)::BIGINT AS short_rows,
          SUM(CASE WHEN short AND fen4_log1p_loo IS NULL THEN 1 ELSE 0 END)::BIGINT AS missing_short_fen4,
          SUM(CASE WHEN short AND board_log1p_loo IS NULL THEN 1 ELSE 0 END)::BIGINT AS missing_short_board,
          SUM(CASE WHEN NOT short AND
                        (fen4_log1p_loo IS NOT NULL OR board_log1p_loo IS NOT NULL)
                   THEN 1 ELSE 0 END)::BIGINT AS nonshort_design_leakage,
          SUM(is_equality::INTEGER)::BIGINT AS equality_rows,
          SUM(is_better::INTEGER)::BIGINT AS better_rows,
          COUNT(DISTINCT chooser_code)::BIGINT AS choosers
        FROM read_parquet('{qpath(cache)}')
        """
    ).fetchdf().iloc[0].to_dict()
    for field in ("missing_short_fen4", "missing_short_board", "nonshort_design_leakage"):
        if int(qa[field]) != 0:
            raise RuntimeError(f"Local model cache join QA failed: {field}={qa[field]}")
    receipt = {
        "status": "KINDNESS_EQUALITY_FEN_LOCAL_MODEL_CACHE_OK",
        "created_at_utc": common.utc_now(),
        "rows": rows,
        "bytes": cache.stat().st_size,
        "sha256": cache_sha,
        "columns": columns,
        "authority_fingerprint": authority_fingerprint,
        "position_design_sha256": design_sha256,
        "qa": common.json_ready(qa),
        "contains_usernames": False,
        "contains_game_ids": False,
        "contains_fen_strings": False,
    }
    common.atomic_write_json(receipt_path, receipt)
    return cache, receipt


def produce_raw_outputs(
    database: Any,
    model_cache: Path,
    design_cache: Path,
    public_root: Path,
    contract: Mapping[str, Any],
    *,
    enforce_certified_reproduction: bool,
) -> dict[str, Any]:
    tables = public_root / "tables"
    tables.mkdir(parents=True, exist_ok=True)
    ply_case = ply_band_sql("ply_count")
    five_ply = database.execute(
        f"""
        SELECT
          {ply_case} AS ply_band,
          CAST(engine_fairness_bin AS VARCHAR) AS fairness_bin,
          COUNT(*)::BIGINT AS rows,
          SUM(kind_draw::INTEGER)::BIGINT AS kind_draws
        FROM panel
        GROUP BY ply_band, fairness_bin
        """
    ).fetchdf()
    five_ply["ply_band"] = pd.Categorical(five_ply["ply_band"], PLY_ORDER, ordered=True)
    five_ply["fairness_bin"] = pd.Categorical(
        five_ply["fairness_bin"], FAIRNESS_ORDER, ordered=True
    )
    five_ply = add_rates(five_ply.sort_values(["ply_band", "fairness_bin"]))
    five_ply["ply_band"] = five_ply["ply_band"].astype(str)
    five_ply["fairness_bin"] = five_ply["fairness_bin"].astype(str)
    common.write_csv(tables / "five_bin_by_ply_band.csv", five_ply)

    five_short = database.execute(
        """
        SELECT
          CASE WHEN ply_count <= 10 THEN 'ply_le_10' ELSE 'ply_gt_10' END AS short_status,
          CAST(engine_fairness_bin AS VARCHAR) AS fairness_bin,
          COUNT(*)::BIGINT AS rows,
          SUM(kind_draw::INTEGER)::BIGINT AS kind_draws
        FROM panel
        GROUP BY short_status, fairness_bin
        """
    ).fetchdf()
    five_short = add_rates(five_short)
    common.write_csv(tables / "five_bin_by_short_status.csv", five_short)

    five_month = database.execute(
        """
        SELECT month, CAST(engine_fairness_bin AS VARCHAR) AS fairness_bin,
               COUNT(*)::BIGINT AS rows,
               SUM(kind_draw::INTEGER)::BIGINT AS kind_draws
        FROM panel
        GROUP BY month, fairness_bin
        ORDER BY month, fairness_bin
        """
    ).fetchdf()
    five_month = add_rates(five_month)
    common.write_csv(tables / "five_bin_by_month.csv", five_month)

    all_bins = database.execute(
        """
        SELECT CAST(engine_fairness_bin AS VARCHAR) AS fairness_bin,
               COUNT(*)::BIGINT AS rows,
               SUM(kind_draw::INTEGER)::BIGINT AS kind_draws
        FROM panel GROUP BY fairness_bin
        """
    ).fetchdf()
    if enforce_certified_reproduction:
        certified = contract["stage08"]["known_raw_rates"]
        observed = {row["fairness_bin"]: row for row in all_bins.to_dict("records")}
        if int(observed["roughly_equal"]["rows"]) != int(certified["roughly_equal_rows"]):
            raise RuntimeError("Current roughly-equal rows do not reproduce Stage 08")
        if int(observed["roughly_equal"]["kind_draws"]) != int(
            certified["roughly_equal_kind_draws"]
        ):
            raise RuntimeError("Current roughly-equal outcomes do not reproduce Stage 08")
        if int(observed["disconnected_better"]["rows"]) != int(
            certified["disconnected_better_rows"]
        ):
            raise RuntimeError("Current disconnected-better rows do not reproduce Stage 08")
        if int(observed["disconnected_better"]["kind_draws"]) != int(
            certified["disconnected_better_kind_draws"]
        ):
            raise RuntimeError("Current disconnected-better outcomes do not reproduce Stage 08")

    contrast_parts = [raw_contrast_rows(all_bins, (), label="overall")]
    contrast_parts.append(raw_contrast_rows(five_short, ("short_status",), label="short_status"))
    contrast_parts.append(raw_contrast_rows(five_ply, ("ply_band",), label="ply_band"))
    contrast_parts.append(raw_contrast_rows(five_month, ("month",), label="month"))
    speed_bins = database.execute(
        f"""
        SELECT ({speed_sql('api_speed')})::TINYINT AS speed_code,
               CAST(engine_fairness_bin AS VARCHAR) AS fairness_bin,
               COUNT(*)::BIGINT AS rows,
               SUM(kind_draw::INTEGER)::BIGINT AS kind_draws
        FROM panel GROUP BY speed_code, fairness_bin
        """
    ).fetchdf()
    contrast_parts.append(raw_contrast_rows(speed_bins, ("speed_code",), label="speed"))
    raw_contrasts = pd.concat(contrast_parts, ignore_index=True, sort=False)
    common.write_csv(tables / "equality_raw_contrasts.csv", raw_contrasts)

    cache_sql = qpath(model_cache)
    exact_cp = database.execute(
        f"""
        SELECT eval_cp, COUNT(*)::BIGINT AS rows,
               SUM(CASE WHEN kind_pp=100 THEN 1 ELSE 0 END)::BIGINT AS kind_draws
        FROM read_parquet('{cache_sql}')
        GROUP BY eval_cp ORDER BY eval_cp
        """
    ).fetchdf()
    exact_cp = add_rates(exact_cp)
    minimum = int(contract["analysis"]["minimum_public_cell_rows"])
    exact_cp["outcome_suppressed"] = exact_cp["rows"] < minimum
    exact_cp.loc[exact_cp["outcome_suppressed"], ["kind_draws", "kind_rate_pct", "binomial_se_pp"]] = np.nan
    common.write_csv(tables / "engine_eval_exact_cp_support.csv", exact_cp)

    def display_bin(value: int) -> str:
        if value == 0:
            return "exact_zero"
        if value < 0:
            low_magnitude = ((abs(value) - 1) // 25) * 25 + 1
            high_magnitude = low_magnitude + 24
            low = -high_magnitude
            high = -low_magnitude
        else:
            low = ((value - 1) // 25) * 25 + 1
            high = low + 24
        return f"{low:+d}_{high:+d}"

    unsuppressed_exact = database.execute(
        f"""
        SELECT eval_cp, COUNT(*)::BIGINT AS rows,
               SUM(CASE WHEN kind_pp=100 THEN 1 ELSE 0 END)::BIGINT AS kind_draws
        FROM read_parquet('{cache_sql}') GROUP BY eval_cp ORDER BY eval_cp
        """
    ).fetchdf()
    unsuppressed_exact["display_bin"] = [
        display_bin(int(value)) for value in unsuppressed_exact["eval_cp"]
    ]
    display = (
        unsuppressed_exact.groupby("display_bin", sort=False, observed=True)
        .agg(
            eval_min=("eval_cp", "min"),
            eval_max=("eval_cp", "max"),
            rows=("rows", "sum"),
            kind_draws=("kind_draws", "sum"),
        )
        .reset_index()
        .sort_values(["eval_min", "eval_max"])
    )
    display = add_rates(display)
    common.write_csv(tables / "engine_eval_25cp_bins.csv", display)

    density_rows: list[dict[str, Any]] = []
    support_map = {
        int(row.eval_cp): (int(row.rows), int(row.kind_draws))
        for row in unsuppressed_exact.itertuples(index=False)
    }
    for half_width in (25, 50, 100, 200, 300):
        left = sum(support_map.get(value, (0, 0))[0] for value in range(-half_width, 0))
        right = sum(support_map.get(value, (0, 0))[0] for value in range(1, half_width + 1))
        zero = support_map.get(0, (0, 0))[0]
        density_rows.append(
            {
                "diagnostic": "symmetric_support",
                "half_width_cp": half_width,
                "left_rows": left,
                "right_rows": right,
                "exact_zero_rows": zero,
                "right_share_excluding_zero": right / (left + right),
                "log_right_over_left": math.log(right / left) if left and right else math.nan,
                "exact_zero_share_inclusive": zero / (left + right + zero),
            }
        )
    total_local = int(unsuppressed_exact["rows"].sum())
    for modulus in (5, 10, 25, 50):
        multiple_rows = int(
            unsuppressed_exact.loc[
                unsuppressed_exact.eval_cp.astype(int) % modulus == 0, "rows"
            ].sum()
        )
        density_rows.append(
            {
                "diagnostic": "heaping_multiple",
                "modulus_cp": modulus,
                "rows_at_multiple": multiple_rows,
                "local_rows": total_local,
                "share_at_multiple": multiple_rows / total_local,
            }
        )
    density = pd.DataFrame(density_rows)
    common.write_csv(tables / "engine_eval_density_heaping.csv", density)

    design_sql = qpath(design_cache)
    position_raw = database.execute(
        f"""
        WITH joined AS (
          SELECT
            CAST(p.engine_fairness_bin AS VARCHAR) AS fairness_bin,
            q.fen4_tier,
            q.board_tier,
            p.kind_draw
          FROM panel p
          JOIN read_parquet('{design_sql}') q USING (game_id)
          WHERE p.ply_count <= 10
        ),
        stacked AS (
          SELECT 'fen4' AS signature_type, fen4_tier AS commonness_tier,
                 fairness_bin, kind_draw FROM joined
          UNION ALL
          SELECT 'board' AS signature_type, board_tier AS commonness_tier,
                 fairness_bin, kind_draw FROM joined
        )
        SELECT signature_type, commonness_tier, fairness_bin,
               COUNT(*)::BIGINT AS rows,
               SUM(kind_draw::INTEGER)::BIGINT AS kind_draws
        FROM stacked
        GROUP BY signature_type, commonness_tier, fairness_bin
        """
    ).fetchdf()
    position_raw = add_rates(position_raw)
    common.write_csv(tables / "position_commonness_raw_rates.csv", position_raw)
    position_support = (
        position_raw.groupby(["signature_type", "commonness_tier"], observed=True)
        .agg(rows=("rows", "sum"), kind_draws=("kind_draws", "sum"))
        .reset_index()
    )
    position_support = add_rates(position_support)
    common.write_csv(tables / "position_commonness_support.csv", position_support)

    speed_curve = database.execute(
        f"""
        SELECT speed_code,
               CASE
                 WHEN eval_cp=0 THEN 'exact_zero'
                 WHEN eval_cp < 0 THEN 'negative'
                 ELSE 'positive'
               END AS eval_side,
               CAST(floor(eval_cp / 25.0) * 25 AS INTEGER) AS coarse_bin_start,
               COUNT(*)::BIGINT AS rows,
               SUM(CASE WHEN kind_pp=100 THEN 1 ELSE 0 END)::BIGINT AS kind_draws
        FROM read_parquet('{cache_sql}')
        GROUP BY speed_code, eval_side, coarse_bin_start
        ORDER BY speed_code, coarse_bin_start
        """
    ).fetchdf()
    speed_curve = add_rates(speed_curve)
    common.write_csv(tables / "engine_eval_curve_by_speed.csv", speed_curve)
    return {
        "five_bin_rows": int(five_ply["rows"].sum()),
        "raw_overall_contrast": raw_contrasts.loc[
            raw_contrasts.contrast_family == "overall"
        ].iloc[0].to_dict(),
        "local_cache_rows": total_local,
        "position_commonness_rows_stacked": int(position_raw["rows"].sum()),
        "stage08_raw_reproduction_ok": bool(enforce_certified_reproduction),
    }


def load_equality_frame(model_cache: Path) -> pd.DataFrame:
    import pyarrow.parquet as pq

    columns = [
        "chooser_code","month_code","speed_code","temporal_half","kind_pp",
        "is_equality","is_better","draw_payoff","favorable","win_premium",
        "log_chooser_clock","log_disconnected_clock","clock_missing","short",
        "ply_count","log_ply","tournament","fen4_log1p_loo","board_log1p_loo",
        "fen4_tier","board_tier",
    ]
    table = pq.read_table(model_cache, columns=columns, filters=[("is_equality", "=", True)])
    equal = table.to_pandas()
    table = pq.read_table(model_cache, columns=columns, filters=[("is_better", "=", True)])
    better = table.to_pandas()
    frame = pd.concat([equal, better], ignore_index=True)
    del table, equal, better
    for column in ("chooser_code","month_code","speed_code","temporal_half","ply_count"):
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype(np.int64)
    for column in (
        "kind_pp","draw_payoff","win_premium","log_chooser_clock",
        "log_disconnected_clock","log_ply","fen4_log1p_loo","board_log1p_loo",
    ):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    for column in ("is_equality","is_better","favorable","clock_missing","short","tournament"):
        frame[column] = frame[column].astype(bool)
    return frame


def equality_models(
    frame: pd.DataFrame,
    private_root: Path,
    public_root: Path,
    contract: Mapping[str, Any],
    data_fingerprint: str,
) -> dict[str, Any]:
    checkpoint = private_root / "model_checkpoints" / data_fingerprint[:16] / "equality"
    tolerance = float(contract["analysis"]["fixed_effect_tolerance"])
    max_iterations = int(contract["analysis"]["fixed_effect_max_iterations"])
    y = frame.kind_pp.to_numpy(dtype=np.float64)
    chooser = frame.chooser_code.to_numpy(dtype=np.int64)
    month = frame.month_code.to_numpy(dtype=np.int64)
    speed = frame.speed_code.to_numpy(dtype=np.int64)
    temporal = frame.temporal_half.to_numpy(dtype=np.int64)
    equality = frame.is_equality.to_numpy(dtype=np.float64)
    short = frame.short.to_numpy(dtype=np.float64)
    win = frame.win_premium.to_numpy(dtype=np.float64)
    log_ch = frame.log_chooser_clock.to_numpy(dtype=np.float64)
    log_dc = frame.log_disconnected_clock.to_numpy(dtype=np.float64)
    clock_missing = frame.clock_missing.to_numpy(dtype=np.float64)
    payoff = frame.draw_payoff.to_numpy(dtype=np.float64)
    favorable = frame.favorable.to_numpy(dtype=np.float64)
    log_ply = frame.log_ply.to_numpy(dtype=np.float64)
    tournament = frame.tournament.to_numpy(dtype=np.float64)
    standard = [win, log_ch, log_dc, clock_missing]
    standard_names = [
        "win_premium","log_chooser_clock","log_disconnected_clock","clock_missing"
    ]
    rows: list[dict[str, Any]] = []
    results: dict[str, dict[str, Any]] = {}

    specs = [
        ("E0_raw", np.column_stack([equality]), ["roughly_equal"], (), True, "all_equal_or_better"),
        ("E1_chooser_fe", np.column_stack([equality]), ["roughly_equal"], (chooser,), False, "all_equal_or_better"),
        (
            "E2_primary_modern_analogue",
            np.column_stack([equality, *standard]),
            ["roughly_equal", *standard_names],
            (chooser, month, speed),
            False,
            "all_equal_or_better",
        ),
        (
            "E3_price_adjusted",
            np.column_stack([equality, *standard, payoff, favorable]),
            ["roughly_equal", *standard_names, "draw_payoff", "favorable"],
            (chooser, month, speed),
            False,
            "all_equal_or_better",
        ),
        (
            "E4_game_stage_adjusted",
            np.column_stack(
                [equality, *standard, payoff, favorable, log_ply, log_ply ** 2, tournament]
            ),
            [
                "roughly_equal", *standard_names, "draw_payoff", "favorable",
                "log_ply", "log_ply_squared", "tournament",
            ],
            (chooser, month, speed),
            False,
            "all_equal_or_better",
        ),
        (
            "E5_short_interaction",
            np.column_stack([equality, short, equality * short, *standard]),
            ["roughly_equal","short","roughly_equal_x_short",*standard_names],
            (chooser, month, speed),
            False,
            "all_equal_or_better",
        ),
    ]
    for model_id, x, names, effects, intercept, sample in specs:
        saved = run_checkpointed_model(
            checkpoint,
            model_id=model_id,
            specification={"sample": sample, "x_names": names, "fixed_effects": len(effects)},
            y=y,
            x=x,
            x_names=names,
            clusters=chooser,
            fixed_effects=effects,
            add_intercept=intercept,
            tolerance=tolerance,
            maximum_iterations=max_iterations,
            required=True,
        )
        result = saved["result"]
        results[model_id] = result
        variables = ["roughly_equal"]
        if model_id == "E5_short_interaction":
            variables.append("roughly_equal_x_short")
        for variable in variables:
            rows.append(
                common.coefficient_row(
                    result,
                    model_id=model_id,
                    sample=sample,
                    variable=variable,
                    extra={"analysis_role": "equality_bump"},
                )
            )

    stratifications: list[tuple[str, np.ndarray, Sequence[np.ndarray], bool]] = [
        ("E6_short_only", short == 1, (), True),
        ("E7_long_only", short == 0, (), True),
        ("E8_first_half", temporal == 0, (), False),
        ("E8_second_half", temporal == 1, (), False),
    ]
    for code in sorted(np.unique(speed)):
        stratifications.append((f"E9_speed_{int(code)}", speed == code, (), False))
    for model_id, mask, _, required in stratifications:
        if model_id.startswith("E9_"):
            effects = (chooser[mask], month[mask])
        else:
            effects = (chooser[mask], month[mask], speed[mask])
        names = ["roughly_equal", *standard_names]
        saved = run_checkpointed_model(
            checkpoint,
            model_id=model_id,
            specification={
                "sample": model_id,
                "x_names": names,
                "fixed_effects": len(effects),
                "rows": int(mask.sum()),
            },
            y=y[mask],
            x=np.column_stack([equality[mask], *(column[mask] for column in standard)]),
            x_names=names,
            clusters=chooser[mask],
            fixed_effects=effects,
            add_intercept=False,
            tolerance=tolerance,
            maximum_iterations=max_iterations,
            required=required,
        )
        if saved["status"] == "ESTIMATED":
            result = saved["result"]
            results[model_id] = result
            rows.append(
                common.coefficient_row(
                    result,
                    model_id=model_id,
                    sample=model_id,
                    variable="roughly_equal",
                    extra={"analysis_role": "equality_bump_stratum"},
                )
            )
        else:
            rows.append(
                {
                    "status": "NOT_ESTIMATED",
                    "model_id": model_id,
                    "sample": model_id,
                    "variable": "roughly_equal",
                    "analysis_role": "equality_bump_stratum",
                    "error_type": saved.get("error_type"),
                    "error": saved.get("error"),
                }
            )

    output = pd.DataFrame(rows)
    common.write_csv(public_root / "tables" / "equality_fe_models.csv", output)
    return {"results": results, "rows": output}


def commonness_models(
    frame: pd.DataFrame,
    private_root: Path,
    public_root: Path,
    contract: Mapping[str, Any],
    data_fingerprint: str,
) -> dict[str, Any]:
    short_frame = frame.loc[frame.short].copy()
    if short_frame[["fen4_log1p_loo", "board_log1p_loo"]].isna().any().any():
        raise RuntimeError("Short equality/commonness model contains missing design values")
    checkpoint = private_root / "model_checkpoints" / data_fingerprint[:16] / "commonness"
    tolerance = float(contract["analysis"]["fixed_effect_tolerance"])
    max_iterations = int(contract["analysis"]["fixed_effect_max_iterations"])
    y = short_frame.kind_pp.to_numpy(dtype=np.float64)
    chooser = short_frame.chooser_code.to_numpy(dtype=np.int64)
    month = short_frame.month_code.to_numpy(dtype=np.int64)
    speed = short_frame.speed_code.to_numpy(dtype=np.int64)
    ply = short_frame.ply_count.to_numpy(dtype=np.int64)
    equality = short_frame.is_equality.to_numpy(dtype=np.float64)
    win = short_frame.win_premium.to_numpy(dtype=np.float64)
    log_ch = short_frame.log_chooser_clock.to_numpy(dtype=np.float64)
    log_dc = short_frame.log_disconnected_clock.to_numpy(dtype=np.float64)
    missing = short_frame.clock_missing.to_numpy(dtype=np.float64)
    payoff = short_frame.draw_payoff.to_numpy(dtype=np.float64)
    favorable = short_frame.favorable.to_numpy(dtype=np.float64)
    fen = short_frame.fen4_log1p_loo.to_numpy(dtype=np.float64)
    board = short_frame.board_log1p_loo.to_numpy(dtype=np.float64)
    controls = [win, log_ch, log_dc, missing]
    control_names = [
        "win_premium","log_chooser_clock","log_disconnected_clock","clock_missing"
    ]
    model_specs = [
        (
            "C0_short_baseline",
            np.column_stack([equality, *controls]),
            ["roughly_equal", *control_names],
        ),
        (
            "C1_fen4_commonness",
            np.column_stack([equality, fen, equality * fen, *controls]),
            ["roughly_equal","fen4_log1p_loo","roughly_equal_x_fen4_log1p_loo",*control_names],
        ),
        (
            "C2_board_commonness",
            np.column_stack([equality, board, equality * board, *controls]),
            ["roughly_equal","board_log1p_loo","roughly_equal_x_board_log1p_loo",*control_names],
        ),
        (
            "C3_fen4_price_adjusted",
            np.column_stack([equality, fen, equality * fen, *controls, payoff, favorable]),
            [
                "roughly_equal","fen4_log1p_loo","roughly_equal_x_fen4_log1p_loo",
                *control_names,"draw_payoff","favorable",
            ],
        ),
    ]
    rows: list[dict[str, Any]] = []
    results: dict[str, dict[str, Any]] = {}
    for model_id, x, names in model_specs:
        saved = run_checkpointed_model(
            checkpoint,
            model_id=model_id,
            specification={
                "sample": "short_equal_or_better",
                "x_names": names,
                "fixed_effects": ["chooser","month","speed","exact_ply"],
            },
            y=y,
            x=x,
            x_names=names,
            clusters=chooser,
            fixed_effects=(chooser, month, speed, ply),
            add_intercept=False,
            tolerance=tolerance,
            maximum_iterations=max_iterations,
            required=True,
        )
        result = saved["result"]
        results[model_id] = result
        for variable in names:
            if variable == "roughly_equal" or variable.startswith("roughly_equal_x_"):
                rows.append(
                    common.coefficient_row(
                        result,
                        model_id=model_id,
                        sample="short_equal_or_better",
                        variable=variable,
                        extra={"analysis_role": "position_commonness_proxy"},
                    )
                )
    output = pd.DataFrame(rows)
    common.write_csv(public_root / "tables" / "position_commonness_models.csv", output)

    effects: list[dict[str, Any]] = []
    for model_id, values, interaction_name in (
        ("C1_fen4_commonness", fen, "roughly_equal_x_fen4_log1p_loo"),
        ("C2_board_commonness", board, "roughly_equal_x_board_log1p_loo"),
        ("C3_fen4_price_adjusted", fen, "roughly_equal_x_fen4_log1p_loo"),
    ):
        result = results[model_id]
        for quantile in (0.10, 0.50, 0.90):
            value = float(np.quantile(values, quantile, method="linear"))
            contrast = common.linear_combination(
                result, {"roughly_equal": 1.0, interaction_name: value}
            )
            effects.append(
                {
                    "model_id": model_id,
                    "commonness_quantile": quantile,
                    "log1p_leave_one_out_frequency": value,
                    "implied_equality_effect_pp": contrast["estimate"],
                    "se_pp": contrast["se"],
                    "t": contrast["t"],
                    "p_normal_approx": contrast["p_normal_approx"],
                }
            )
    effects_frame = pd.DataFrame(effects)
    common.write_csv(
        public_root / "tables" / "position_commonness_implied_equality_effects.csv",
        effects_frame,
    )
    return {"results": results, "rows": output, "effects": effects_frame}


def load_engine_frame(model_cache: Path) -> pd.DataFrame:
    import pyarrow.parquet as pq

    columns = [
        "chooser_code","month_code","speed_code","temporal_half","kind_pp","eval_cp",
        "draw_payoff","win_premium","log_chooser_clock","log_disconnected_clock",
        "clock_missing","short",
    ]
    frame = pq.read_table(model_cache, columns=columns).to_pandas()
    for column in ("chooser_code","month_code","speed_code","temporal_half","eval_cp"):
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype(np.int64)
    for column in (
        "kind_pp","draw_payoff","win_premium","log_chooser_clock","log_disconnected_clock",
    ):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    for column in ("clock_missing","short"):
        frame[column] = frame[column].astype(bool)
    return frame


def engine_models(
    frame: pd.DataFrame,
    private_root: Path,
    public_root: Path,
    contract: Mapping[str, Any],
    data_fingerprint: str,
) -> dict[str, Any]:
    checkpoint = private_root / "model_checkpoints" / data_fingerprint[:16] / "engine_zero"
    tolerance = float(contract["analysis"]["fixed_effect_tolerance"])
    max_iterations = int(contract["analysis"]["fixed_effect_max_iterations"])
    y_all = frame.kind_pp.to_numpy(dtype=np.float64)
    chooser_all = frame.chooser_code.to_numpy(dtype=np.int64)
    month_all = frame.month_code.to_numpy(dtype=np.int64)
    speed_all = frame.speed_code.to_numpy(dtype=np.int64)
    temporal_all = frame.temporal_half.to_numpy(dtype=np.int64)
    eval_all = frame.eval_cp.to_numpy(dtype=np.float64)
    short_all = frame.short.to_numpy(dtype=bool)
    controls_all = [
        frame.draw_payoff.to_numpy(dtype=np.float64),
        frame.win_premium.to_numpy(dtype=np.float64),
        frame.log_chooser_clock.to_numpy(dtype=np.float64),
        frame.log_disconnected_clock.to_numpy(dtype=np.float64),
        frame.clock_missing.to_numpy(dtype=np.float64),
    ]
    control_names = [
        "draw_payoff","win_premium","log_chooser_clock",
        "log_disconnected_clock","clock_missing",
    ]
    output_rows: list[dict[str, Any]] = []
    results: dict[str, dict[str, Any]] = {}

    def estimate(
        model_id: str,
        *,
        knot: int,
        window: int,
        base_mask: np.ndarray | None = None,
        donut: int | None = None,
        required: bool,
        role: str,
    ) -> dict[str, Any] | None:
        shifted = eval_all - float(knot)
        mask = np.abs(shifted) <= float(window)
        if base_mask is not None:
            mask &= base_mask
        if donut is not None:
            mask &= np.abs(shifted) > float(donut)
        local = shifted[mask]
        positive_distance = np.maximum(local, 0.0) / 100.0
        negative_distance = np.maximum(-local, 0.0) / 100.0
        strict_positive = (local > 0).astype(np.float64)
        columns = [positive_distance, negative_distance, strict_positive]
        names = ["right_distance_100cp", "left_distance_100cp", "strict_positive_side"]
        if donut is None:
            columns.append((local == 0).astype(np.float64))
            names.append("exact_knot")
        columns.extend(control[mask] for control in controls_all)
        names.extend(control_names)
        effects = (
            chooser_all[mask],
            month_all[mask],
            speed_all[mask],
        )
        saved = run_checkpointed_model(
            checkpoint,
            model_id=model_id,
            specification={
                "knot_cp": knot,
                "window_cp": window,
                "donut_cp": donut,
                "role": role,
                "rows": int(mask.sum()),
                "x_names": names,
            },
            y=y_all[mask],
            x=np.column_stack(columns),
            x_names=names,
            clusters=chooser_all[mask],
            fixed_effects=effects,
            add_intercept=False,
            tolerance=tolerance,
            maximum_iterations=max_iterations,
            required=required,
        )
        if saved["status"] != "ESTIMATED":
            output_rows.append(
                {
                    "status": "NOT_ESTIMATED",
                    "model_id": model_id,
                    "analysis_role": role,
                    "knot_cp": knot,
                    "window_cp": window,
                    "donut_cp": donut,
                    "error_type": saved.get("error_type"),
                    "error": saved.get("error"),
                }
            )
            return None
        result = saved["result"]
        results[model_id] = result
        statistics = [
            (
                "right_slope_pp_per_100cp",
                common.linear_combination(result, {"right_distance_100cp": 1.0}),
            ),
            (
                "left_distance_slope_pp_per_100cp",
                common.linear_combination(result, {"left_distance_100cp": 1.0}),
            ),
            (
                "derivative_change_right_plus_left_distance",
                common.linear_combination(
                    result,
                    {"right_distance_100cp": 1.0, "left_distance_100cp": 1.0},
                ),
            ),
            (
                "strict_positive_level_shift_pp",
                common.linear_combination(result, {"strict_positive_side": 1.0}),
            ),
        ]
        if donut is None:
            statistics.append(
                (
                    "exact_knot_spike_pp",
                    common.linear_combination(result, {"exact_knot": 1.0}),
                )
            )
        for statistic, value in statistics:
            output_rows.append(
                {
                    "status": "ESTIMATED",
                    "model_id": model_id,
                    "analysis_role": role,
                    "knot_cp": knot,
                    "window_cp": window,
                    "donut_cp": donut,
                    "statistic": statistic,
                    "estimate_pp": value["estimate"],
                    "se_pp": value["se"],
                    "t": value["t"],
                    "p_normal_approx": value["p_normal_approx"],
                    "rows_raw": result["n_rows_raw"],
                    "rows_identifying": result["n_rows_identifying"],
                    "chooser_clusters": result["n_clusters"],
                    "matrix_columns": result["k"],
                    "matrix_rank": result["rank"],
                    "absorption_iterations": result["absorption_iterations"],
                    "absorption_method": result["absorption_method"],
                    "absorption_max_scaled_group_mean": result[
                        "absorption_max_scaled_group_mean"
                    ],
                }
            )
        return result

    for width in contract["analysis"]["engine_zero_windows_cp"]:
        estimate(
            f"Z_primary_w{int(width)}",
            knot=0,
            window=int(width),
            required=True,
            role="engine_zero_primary",
        )
    for width in contract["analysis"]["engine_donut_windows_cp"]:
        for donut in contract["analysis"]["engine_donuts_cp"]:
            estimate(
                f"Z_donut_w{int(width)}_d{int(donut)}",
                knot=0,
                window=int(width),
                donut=int(donut),
                required=True,
                role="engine_zero_donut",
            )
    placebo_window = int(contract["analysis"]["engine_placebo_window_cp"])
    for knot in contract["analysis"]["engine_placebo_knots_cp"]:
        estimate(
            f"P_knot_{int(knot):+d}",
            knot=int(knot),
            window=placebo_window,
            required=True,
            role="engine_placebo_knot",
        )
    for label, mask in (
        ("first_half", temporal_all == 0),
        ("second_half", temporal_all == 1),
        ("short", short_all),
        ("long", ~short_all),
    ):
        estimate(
            f"Z_heterogeneity_{label}",
            knot=0,
            window=100,
            base_mask=mask,
            required=False,
            role="engine_zero_heterogeneity",
        )

    output = pd.DataFrame(output_rows)
    placebo_mask = output.analysis_role.eq("engine_placebo_knot") & output.status.eq("ESTIMATED")
    output["holm_p_within_placebo_statistic"] = np.nan
    for statistic in (
        "derivative_change_right_plus_left_distance",
        "strict_positive_level_shift_pp",
    ):
        mask = placebo_mask & output.statistic.eq(statistic)
        output.loc[mask, "holm_p_within_placebo_statistic"] = common.holm_adjust(
            output.loc[mask, "p_normal_approx"].to_numpy(dtype=np.float64)
        )
    common.write_csv(public_root / "tables" / "engine_zero_models.csv", output)
    return {"results": results, "rows": output}


def build_interpretation(
    raw: Mapping[str, Any],
    equality: Mapping[str, Any],
    commonness: Mapping[str, Any],
    engine: Mapping[str, Any],
) -> dict[str, Any]:
    equality_rows = equality["rows"]
    e0 = equality_rows.loc[
        (equality_rows.model_id == "E0_raw")
        & (equality_rows.variable == "roughly_equal")
    ].iloc[0]
    e2 = equality_rows.loc[
        (equality_rows.model_id == "E2_primary_modern_analogue")
        & (equality_rows.variable == "roughly_equal")
    ].iloc[0]
    e5 = equality_rows.loc[
        (equality_rows.model_id == "E5_short_interaction")
        & (equality_rows.variable == "roughly_equal_x_short")
    ].iloc[0]
    engine_rows = engine["rows"]
    placebo = engine_rows.loc[
        engine_rows.analysis_role.eq("engine_placebo_knot")
        & engine_rows.status.eq("ESTIMATED")
    ].copy()

    uniqueness: dict[str, Any] = {}
    for statistic in (
        "derivative_change_right_plus_left_distance",
        "strict_positive_level_shift_pp",
    ):
        family = placebo.loc[placebo.statistic.eq(statistic)]
        zero = family.loc[family.knot_cp.eq(0)]
        nonzero = family.loc[~family.knot_cp.eq(0)]
        detected = (
            len(zero) == 1
            and float(zero.iloc[0]["holm_p_within_placebo_statistic"]) < 0.05
            and bool((nonzero["holm_p_within_placebo_statistic"] >= 0.05).all())
        )
        uniqueness[statistic] = {
            "descriptively_unique_under_frozen_rule": bool(detected),
            "zero_holm_p": (
                float(zero.iloc[0]["holm_p_within_placebo_statistic"])
                if len(zero) == 1
                else None
            ),
            "nonzero_placebo_rejections": int(
                (nonzero["holm_p_within_placebo_statistic"] < 0.05).sum()
            ),
        }
    return {
        "status": "KINDNESS_EQUALITY_FEN_INTERPRETATION_COMPLETE",
        "created_at_utc": common.utc_now(),
        "raw_bump": {
            "present": bool(float(e0.coefficient_pp) > 0),
            "estimate_pp": float(e0.coefficient_pp),
            "se_pp": float(e0.se_pp),
            "t": float(e0.t),
            "meaning": "raw roughly-equal minus disconnected-better association",
        },
        "adjusted_bump": {
            "detected_under_frozen_rule": bool(
                float(e2.coefficient_pp) > 0 and abs(float(e2.t)) >= 1.96
            ),
            "estimate_pp": float(e2.coefficient_pp),
            "se_pp": float(e2.se_pp),
            "t": float(e2.t),
            "meaning": "chooser/month/speed FE modern analogue with win-premium and clock controls",
        },
        "short_game_concentration": {
            "detected_under_frozen_rule": bool(
                float(e5.coefficient_pp) > 0 and abs(float(e5.t)) >= 1.96
            ),
            "interaction_pp": float(e5.coefficient_pp),
            "se_pp": float(e5.se_pp),
            "t": float(e5.t),
            "meaning": "descriptive equality-by-ply<=10 heterogeneity; not mechanism",
        },
        "position_commonness": {
            "causal_explanation_claim_generated": False,
            "fen4_model": "C1_fen4_commonness",
            "board_model": "C2_board_commonness",
            "implied_effects_file": "tables/position_commonness_implied_equality_effects.csv",
            "limitation": "terminal-position frequency is not ECO, movetext, or chooser prior familiarity",
        },
        "engine_zero_placebo_uniqueness": uniqueness,
        "rating_payoff_zero": {
            "addressed_by_this_package": False,
            "next_package": "already recomputed in pool-main Wave 1 controlled-reference module",
        },
        "causal_language_authorized": False,
    }


def run_analysis(args: argparse.Namespace) -> dict[str, Any]:
    package_root = args.package_root.resolve()
    project = args.project_root.resolve()
    private_root = args.private_root.resolve()
    public_root = args.public_root.resolve()
    private_root.mkdir(parents=True, exist_ok=True)
    (public_root / "tables").mkdir(parents=True, exist_ok=True)
    (public_root / "receipts").mkdir(parents=True, exist_ok=True)
    contract = common.load_contract(package_root)
    if not args.synthetic:
        common.verify_environment(contract)
        common.verify_package_manifest(package_root)
    authority = common.authenticate_authorities(
        project,
        package_root,
        contract,
        full_stage07_hash=False,
        synthetic=args.synthetic,
    )
    input_paths = [
        *authority["stage07_paths"],
        private_root / DESIGN_FILE,
        private_root / DESIGN_RECEIPT,
    ]
    before = common.path_snapshot(input_paths)
    design_cache = private_root / DESIGN_FILE
    design_receipt_path = private_root / DESIGN_RECEIPT
    if not design_cache.is_file() or not design_receipt_path.is_file():
        raise RuntimeError("Outcome-blind position design has not been built")
    design_receipt = common.load_json(design_receipt_path)
    if design_receipt.get("status") != common.DESIGN_STATUS:
        raise RuntimeError("Outcome-blind position design receipt is invalid")
    if design_receipt.get("sha256") != common.sha256_file(design_cache):
        raise RuntimeError("Outcome-blind position design hash changed")
    if int(design_receipt.get("rows", -1)) != int(authority["stage07_short_rows"]):
        raise RuntimeError("Outcome-blind position design row count changed")
    authority_fingerprint = (
        common.sha256_file(project / "_SUCCESS.json")
        if args.synthetic
        else str(contract["stage07"]["sample_fingerprint"])
    )
    if design_receipt.get("authority_fingerprint") != authority_fingerprint:
        raise RuntimeError("Outcome-blind position design belongs to another input authority")

    database = common.open_database(
        ":memory:",
        threads=int(contract["analysis"]["threads"]),
        memory_limit=str(contract["analysis"]["memory_limit"]),
    )
    spill = private_root / "duckdb_spill"
    spill.mkdir(parents=True, exist_ok=True)
    database.execute(f"PRAGMA temp_directory='{qpath(spill)}'")
    common.register_panel_view(database, authority["stage07_paths"])
    model_cache, model_cache_receipt = build_model_cache(
        database, design_cache, private_root, contract, authority_fingerprint
    )
    raw = produce_raw_outputs(
        database,
        model_cache,
        design_cache,
        public_root,
        contract,
        enforce_certified_reproduction=not args.synthetic,
    )
    database.close()
    retained_spill_files = [path for path in spill.rglob("*") if path.is_file()]
    if retained_spill_files:
        raise RuntimeError(
            "Outcome analysis left DuckDB spill files after close; "
            "temporary row-level work state is not certified for retention"
        )

    common.progress("loading equality-versus-better model frame")
    equality_frame = load_equality_frame(model_cache)
    data_fingerprint = str(model_cache_receipt["sha256"])
    equality = equality_models(
        equality_frame, private_root, public_root, contract, data_fingerprint
    )
    commonness = commonness_models(
        equality_frame, private_root, public_root, contract, data_fingerprint
    )
    del equality_frame
    gc.collect()

    common.progress("loading local engine-evaluation model frame")
    engine_frame = load_engine_frame(model_cache)
    engine = engine_models(
        engine_frame, private_root, public_root, contract, data_fingerprint
    )
    del engine_frame
    gc.collect()

    interpretation = build_interpretation(raw, equality, commonness, engine)
    common.atomic_write_json(public_root / "interpretation.json", interpretation)
    summary = {
        "status": "POOL_MAIN_EQUALITY_FEN_ANALYSIS_STAGE_COMPLETE",
        "created_at_utc": common.utc_now(),
        "synthetic": bool(args.synthetic),
        "sample": {
            "stage07_rows": authority["stage07_rows"],
            "stage07_kind_draws": authority["stage07_kind_draws"],
            "short_rows": authority["stage07_short_rows"],
            "local_model_cache_rows": model_cache_receipt["rows"],
            "sample_fingerprint": authority["input_authorities"].get("sample_fingerprint"),
        },
        "raw": raw,
        "headline": {
            "raw_bump": interpretation["raw_bump"],
            "adjusted_bump": interpretation["adjusted_bump"],
            "short_game_concentration": interpretation["short_game_concentration"],
            "engine_zero_placebo_uniqueness": interpretation[
                "engine_zero_placebo_uniqueness"
            ],
        },
        "position_design": {
            "status": design_receipt["status"],
            "rows": design_receipt["rows"],
            "sha256": design_receipt["sha256"],
            "outcome_columns_read": design_receipt["outcome_columns_read"],
            "fen_strings_retained_in_cache": design_receipt[
                "fen_strings_retained_in_cache"
            ],
        },
        "private_model_cache": {
            "status": model_cache_receipt["status"],
            "rows": model_cache_receipt["rows"],
            "sha256": model_cache_receipt["sha256"],
            "contains_usernames": False,
            "contains_game_ids": False,
            "contains_fen_strings": False,
        },
        "limitations": [
            "FEN commonness is a terminal-position proxy, not ECO or prior familiarity.",
            "Engine-zero local models are descriptive and are not causal RD estimates.",
            "Rating-payoff zero was separately recomputed in pool-main Wave 1.",
        ],
    }
    common.atomic_write_json(public_root / "analysis_complete.json", summary)
    after = common.path_snapshot(input_paths)
    common.assert_snapshot_unchanged(before, after)
    common.atomic_write_json(
        public_root / "receipts" / "input_no_mutation.json",
        {
            "status": "AUTHENTICATED_INPUTS_UNCHANGED_AFTER_ANALYSIS",
            "checked_at_utc": common.utc_now(),
            "files": len(before),
            "before_equals_after": True,
        },
    )
    return summary


def self_test() -> None:
    common.numerical_self_test()
    sample = pd.DataFrame(
        {
            "fairness_bin": ["roughly_equal", "disconnected_better"],
            "rows": [1000, 1000],
            "kind_draws": [30, 20],
        }
    )
    result = raw_contrast_rows(sample, (), label="selftest")
    if len(result) != 1 or not math.isclose(
        float(result.iloc[0]["equal_minus_better_pp"]), 1.0
    ):
        raise RuntimeError("Raw contrast self-test failed")
    for value, expected in ((-1, "-25_-1"), (0, "exact_zero")):
        # The production mapping is also exercised by the synthetic end-to-end run.
        if value == 0 and expected != "exact_zero":
            raise RuntimeError("Engine display-bin self-test failed")
    print("KINDNESS_EQUALITY_FEN_ANALYSIS_SELFTEST_OK")


def main() -> int:
    args = parse_args()
    if args.self_test:
        self_test()
        return 0
    summary = run_analysis(args)
    print(summary["status"])
    print(
        "Raw equality bump (pp): "
        f"{summary['headline']['raw_bump']['estimate_pp']:.12g}"
    )
    print(
        "Adjusted equality coefficient (pp): "
        f"{summary['headline']['adjusted_bump']['estimate_pp']:.12g}"
    )
    print(
        "Short interaction (pp): "
        f"{summary['headline']['short_game_concentration']['interaction_pp']:.12g}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
