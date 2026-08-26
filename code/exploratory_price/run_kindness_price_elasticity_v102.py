#!/usr/bin/env python3
"""Estimate the conditional price elasticity of kind-draw demand.

The economic price is the reconstructed rating-point premium forgone by drawing
instead of claiming a win.  Every new result is exploratory (X), associational,
and retained regardless of sign or significance.  Certified Stage07 and Stage08
models are reproduced before any new elasticity is interpreted.
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import os
from pathlib import Path
import shutil
import sys
import time
import traceback
from typing import Any, Mapping, Sequence
import uuid

import kindness_price_elasticity_common_v102 as common


SCRIPT_VERSION = "1.0.2"
PROJECT_AUTHORITY = Path("/Volumes/XT_Pro/lichess_kindness")
STATE_NAME = "kindness_price_elasticity_v102_PRIVATE"
OUTPUT_NAME = "kindness_price_elasticity_v102"
MINIMUM_FREE_BYTES = 20 * 1024**3
STRICT_AUDIT_TOLERANCE_PP = 5e-10
APPENDIX_A11_EXPECTED = {
    "positive_draw_payoff": 0.03966,
    "negative_draw_payoff": -0.00586,
    "price": 0.01023,
}
PRIMARY_MODEL = "X_primary_lpm_log_price_chooser_fe_draw50_fe_adjusted"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_AUTHORITY)
    parser.add_argument("--run-id")
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--memory-limit", default="16GB")
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--state-root", type=Path)
    parser.add_argument("--execution-pointer", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def package_root() -> Path:
    return Path(__file__).resolve().parents[2]


def retained_error(error: BaseException) -> bool:
    return isinstance(error, (RuntimeError, MemoryError, ValueError)) or type(error).__name__ == "LinAlgError"


def finite(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: finite(item) for key, item in value.items()}
    if isinstance(value, list):
        return [finite(item) for item in value]
    return value


def authenticate_checkpoint(
    output: Path, receipt: Path, *, config_sha256: str, expected_rows: int | None = None
) -> dict[str, Any] | None:
    _, _, _, pq = common.import_dependencies()
    if not output.exists() and not receipt.exists():
        return None
    if not output.is_file() or not receipt.is_file():
        raise RuntimeError(f"Partial private checkpoint: {output}")
    saved = common.load_json(receipt)
    actual_rows = int(pq.ParquetFile(output).metadata.num_rows)
    if (
        saved.get("config_sha256") != config_sha256
        or saved.get("output_sha256") != common.sha256_file(output)
        or int(saved.get("rows", -1)) != actual_rows
        or (expected_rows is not None and actual_rows != expected_rows)
    ):
        raise RuntimeError(f"Private checkpoint authentication failed: {output}")
    return saved


def month_case(field: str) -> str:
    clauses = " ".join(
        f"WHEN {common.sql_literal(month)} THEN {index}"
        for index, month in enumerate(common.MAIN_MONTHS)
    )
    return f"CASE CAST({field} AS VARCHAR) {clauses} ELSE -1 END"


def build_fair_base(
    *, paths: Sequence[Path], state: Path, threads: int, memory_limit: str,
    config_sha256: str,
) -> tuple[Path, dict[str, Any]]:
    duckdb, _, _, _ = common.import_dependencies()
    output = state / "fair_price_base_private.parquet"
    receipt = state / "fair_price_base_receipt.json"
    saved = authenticate_checkpoint(
        output, receipt, config_sha256=config_sha256, expected_rows=common.EXPECTED_FAIR_ROWS
    )
    if saved:
        print("ELASTICITY_FAIR_BASE_CHECKPOINT_AUTHENTICATED_OK", flush=True)
        return output, saved
    if output.exists() or receipt.exists():
        raise RuntimeError("Partial fair-base checkpoint exists")
    print("ELASTICITY_FAIR_BASE_BUILD_BEGIN", flush=True)
    connection = duckdb.connect()
    temp_root = state / "duckdb_temp/fair_base"
    common.configure_duckdb(
        connection, threads=threads, memory_limit=memory_limit, temp_directory=temp_root
    )
    source = f"read_parquet({common.path_list_literal(paths)}, union_by_name=true)"
    physical_month = month_case("month")
    source_qa = connection.execute(
        f"""
        SELECT
          COUNT(*)::BIGINT,
          COUNT(DISTINCT game_id)::BIGINT,
          SUM(CASE WHEN kind_draw THEN 1 ELSE 0 END)::BIGINT,
          COUNT(DISTINCT chooser_username_norm)::BIGINT,
          COUNT(*) FILTER (WHERE game_id IS NULL)::BIGINT,
          COUNT(*) FILTER (WHERE chooser_username_norm IS NULL)::BIGINT,
          COUNT(*) FILTER (
            WHERE chooser_win_premium_v2 IS NULL
               OR NOT isfinite(CAST(chooser_win_premium_v2 AS DOUBLE))
               OR chooser_draw_payoff_v2 IS NULL
               OR NOT isfinite(CAST(chooser_draw_payoff_v2 AS DOUBLE))
          )::BIGINT,
          COUNT(*) FILTER (WHERE CAST(chooser_win_premium_v2 AS DOUBLE) <= 0)::BIGINT,
          COUNT(*) FILTER (WHERE CAST(chooser_win_premium_v2 AS DOUBLE) = 0)::BIGINT,
          COUNT(*) FILTER (WHERE CAST(chooser_win_premium_v2 AS DOUBLE) < 0)::BIGINT,
          COUNT(*) FILTER (WHERE ({physical_month}) < 12)::BIGINT,
          COUNT(DISTINCT chooser_username_norm)
            FILTER (WHERE ({physical_month}) < 12)::BIGINT,
          MIN(CAST(chooser_win_premium_v2 AS DOUBLE))::DOUBLE
        FROM {source}
        WHERE CAST(fair_competitive AS BOOLEAN)
        """
    ).fetchone()
    expected_source_qa = (
        common.EXPECTED_FAIR_ROWS,
        common.EXPECTED_FAIR_ROWS,
        common.EXPECTED_FAIR_KIND_DRAWS,
        common.EXPECTED_FAIR_CHOOSERS,
        0,
        0,
        0,
        common.EXPECTED_NONPOSITIVE_PRICE_ROWS,
        common.EXPECTED_NONPOSITIVE_PRICE_ROWS,
        0,
        common.EXPECTED_FIRST12_FAIR_ROWS,
        common.EXPECTED_FIRST12_FAIR_CHOOSERS,
    )
    if (
        source_qa[:12] != expected_source_qa
        or not math.isfinite(source_qa[12])
        or (
            common.EXPECTED_NONPOSITIVE_PRICE_ROWS == 0
            and source_qa[12] <= 0
        )
    ):
        raise RuntimeError(
            f"Physical fair-source preflight failed: qa={source_qa} "
            f"expected_prefix={expected_source_qa}"
        )
    connection.execute(
        f"""
        CREATE TEMP TABLE chooser_dimension AS
        WITH counts AS (
          SELECT
            chooser_username_norm AS chooser_key,
            COUNT(*)::BIGINT AS fair_opportunities,
            SUM(CASE WHEN kind_draw THEN 1 ELSE 0 END)::BIGINT AS fair_kind_draws
          FROM {source}
          WHERE CAST(fair_competitive AS BOOLEAN)
          GROUP BY chooser_username_norm
        )
        SELECT
          chooser_key,
          ROW_NUMBER() OVER (ORDER BY chooser_key)::BIGINT - 1 AS chooser_index,
          fair_opportunities,
          fair_kind_draws,
          NTILE(4) OVER (ORDER BY fair_opportunities, chooser_key)::TINYINT - 1
            AS activity_quartile
        FROM counts
        """
    )
    chooser_qa = connection.execute(
        """
        SELECT COUNT(*), SUM(fair_opportunities), SUM(fair_kind_draws),
               MIN(activity_quartile), MAX(activity_quartile)
        FROM chooser_dimension
        """
    ).fetchone()
    if chooser_qa != (
        common.EXPECTED_FAIR_CHOOSERS,
        common.EXPECTED_FAIR_ROWS,
        common.EXPECTED_FAIR_KIND_DRAWS,
        0,
        3,
    ):
        raise RuntimeError(f"Fair chooser dimension changed: {chooser_qa}")

    # v1.0.0 cast the join key to VARCHAR after grouping on the physical key.
    # Four key identities were consequently collapsed in the selected cache,
    # while compensating duplicate joins happened to leave the total row count
    # unchanged. Authenticate the exact-key join against the separately frozen
    # physical-source marginals before writing any checkpoint.
    join_qa = connection.execute(
        f"""
        SELECT
          COUNT(*)::BIGINT,
          COUNT(DISTINCT p.game_id)::BIGINT,
          SUM(CASE WHEN p.kind_draw THEN 1 ELSE 0 END)::BIGINT,
          COUNT(DISTINCT d.chooser_index)::BIGINT,
          COUNT(*) FILTER (WHERE p.game_id IS NULL)::BIGINT,
          COUNT(*) FILTER (WHERE ({month_case('p.month')}) < 12)::BIGINT,
          COUNT(DISTINCT d.chooser_index)
            FILTER (WHERE ({month_case('p.month')}) < 12)::BIGINT,
          COUNT(*) FILTER (
            WHERE CAST(p.chooser_win_premium_v2 AS DOUBLE) <= 0
          )::BIGINT
        FROM {source} p
        INNER JOIN chooser_dimension d
          ON p.chooser_username_norm = d.chooser_key
        WHERE CAST(p.fair_competitive AS BOOLEAN)
        """
    ).fetchone()
    expected_join_qa = (
        common.EXPECTED_FAIR_ROWS,
        common.EXPECTED_FAIR_ROWS,
        common.EXPECTED_FAIR_KIND_DRAWS,
        common.EXPECTED_FAIR_CHOOSERS,
        0,
        common.EXPECTED_FIRST12_FAIR_ROWS,
        common.EXPECTED_FIRST12_FAIR_CHOOSERS,
        common.EXPECTED_NONPOSITIVE_PRICE_ROWS,
    )
    if join_qa != expected_join_qa:
        raise RuntimeError(
            f"Exact-key fair join conservation failed: qa={join_qa} "
            f"expected={expected_join_qa}"
        )

    speed = common.speed_code_sql("p.api_speed")
    rating_band = common.rating_band_sql("p.chooser_elo")
    eval_band = common.eval_band_sql("p.engine_eval_cp_disconnected")
    hour_week = common.hour_of_week_sql("COALESCE(p.api_last_move_at_ms, p.utc_ms)")
    month = month_case("p.month")
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    connection.execute(
        f"""
        COPY (
          WITH selected AS (
            SELECT
              d.chooser_index,
              d.activity_quartile,
              d.fair_opportunities AS chooser_total_fair_opportunities,
              d.fair_kind_draws AS chooser_total_fair_kind_draws,
              CAST(p.game_id AS VARCHAR) AS game_id,
              COALESCE(CAST(p.api_last_move_at_ms AS BIGINT), CAST(p.utc_ms AS BIGINT))
                AS decision_ms,
              CAST(p.archive_ordinal AS BIGINT) AS archive_ordinal,
              CASE WHEN p.kind_draw THEN 1 ELSE 0 END::TINYINT AS kind,
              CAST(p.chooser_win_premium_v2 AS DOUBLE) AS price,
              CASE
                WHEN CAST(p.chooser_win_premium_v2 AS DOUBLE) > 0
                  AND isfinite(CAST(p.chooser_win_premium_v2 AS DOUBLE))
                THEN LN(CAST(p.chooser_win_premium_v2 AS DOUBLE))
                ELSE NULL
              END::DOUBLE AS log_price,
              CAST(p.chooser_draw_payoff_v2 AS DOUBLE) AS draw_payoff,
              CAST(p.engine_eval_cp_disconnected AS FLOAT) AS engine_eval_cp,
              CAST(p.chooser_elo AS FLOAT) AS chooser_elo,
              CAST(p.disconnected_elo AS FLOAT) AS opponent_elo,
              CAST(p.chooser_pre_rd_v2 AS FLOAT) AS chooser_rd,
              CAST(p.disconnected_pre_rd_v2 AS FLOAT) AS opponent_rd,
              CAST(
                CASE WHEN p.chooser_clock_last_obs_s IS NULL THEN NULL
                     ELSE LN(1.0 + GREATEST(CAST(p.chooser_clock_last_obs_s AS DOUBLE), 0.0))
                END AS FLOAT
              ) AS log_chooser_clock,
              CAST(
                CASE WHEN p.disconnected_clock_last_obs_s IS NULL THEN NULL
                     ELSE LN(1.0 + GREATEST(CAST(p.disconnected_clock_last_obs_s AS DOUBLE), 0.0))
                END AS FLOAT
              ) AS log_opponent_clock,
              CAST(COALESCE(p.tournament_like_event, FALSE) AS TINYINT) AS tournament,
              CAST({month} AS TINYINT) AS month_code,
              CAST({speed} AS TINYINT) AS speed_code,
              CAST({rating_band} AS TINYINT) AS rating_band,
              CAST({eval_band} AS TINYINT) AS eval_band,
              CAST({hour_week} AS SMALLINT) AS hour_of_week,
              CAST(
                p.chooser_pre_rd_v2 <= 110 AND p.disconnected_pre_rd_v2 <= 110
                AS TINYINT
              ) AS both_rd_le_110
            FROM {source} p
            INNER JOIN chooser_dimension d
              ON p.chooser_username_norm = d.chooser_key
            WHERE CAST(p.fair_competitive AS BOOLEAN)
          ), ordered AS (
            SELECT
              *,
              ROW_NUMBER() OVER (
                PARTITION BY chooser_index
                ORDER BY decision_ms, archive_ordinal, game_id
              )::BIGINT - 1 AS chooser_sequence,
              COALESCE(
                SUM(CAST(kind AS BIGINT)) OVER (
                  PARTITION BY chooser_index
                  ORDER BY decision_ms, archive_ordinal, game_id
                  ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                ), 0
              )::BIGINT AS prior_kind_draws
            FROM selected
          )
          SELECT
            ROW_NUMBER() OVER (
              ORDER BY chooser_index, chooser_sequence
            )::BIGINT - 1 AS row_id,
            chooser_index, chooser_sequence, activity_quartile,
            chooser_total_fair_opportunities, chooser_total_fair_kind_draws,
            CASE WHEN prior_kind_draws = 0 THEN 0
                 WHEN prior_kind_draws = 1 THEN 1 ELSE 2 END::TINYINT
              AS prior_kind_stratum,
            kind, price, log_price, draw_payoff, engine_eval_cp,
            chooser_elo, opponent_elo, chooser_rd, opponent_rd,
            log_chooser_clock, log_opponent_clock, tournament, month_code,
            speed_code, rating_band, eval_band, hour_of_week, both_rd_le_110,
            ROW_NUMBER() OVER (
              ORDER BY chooser_index, chooser_sequence
            )::BIGINT - 1 AS row_hash
          FROM ordered
          ORDER BY chooser_index, chooser_sequence
        ) TO {common.sql_literal(temporary)}
          (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
        """
    )
    qa = connection.execute(
        f"""
        SELECT
          COUNT(*)::BIGINT,
          SUM(kind)::BIGINT,
          COUNT(DISTINCT chooser_index)::BIGINT,
          MIN(row_id)::BIGINT, MAX(row_id)::BIGINT,
          COUNT(*) FILTER (
            WHERE price IS NULL OR NOT isfinite(price)
               OR draw_payoff IS NULL OR NOT isfinite(draw_payoff)
          )::BIGINT,
          COUNT(*) FILTER (WHERE price <= 0)::BIGINT,
          COUNT(*) FILTER (WHERE price = 0)::BIGINT,
          COUNT(*) FILTER (WHERE price < 0)::BIGINT,
          COUNT(*) FILTER (WHERE log_price IS NULL)::BIGINT,
          COUNT(*) FILTER (
            WHERE price > 0 AND (log_price IS NULL OR NOT isfinite(log_price))
          )::BIGINT,
          COUNT(*) FILTER (
            WHERE month_code NOT BETWEEN 0 AND 23 OR speed_code NOT BETWEEN 0 AND 5
               OR rating_band NOT BETWEEN 0 AND 3 OR eval_band NOT BETWEEN 0 AND 4
               OR activity_quartile NOT BETWEEN 0 AND 3
               OR prior_kind_stratum NOT BETWEEN 0 AND 2
          )::BIGINT,
          COUNT(*) FILTER (WHERE row_hash IS NULL)::BIGINT,
          COUNT(DISTINCT row_hash)::BIGINT,
          COUNT(*) FILTER (WHERE month_code < 12)::BIGINT,
          COUNT(DISTINCT chooser_index) FILTER (WHERE month_code < 12)::BIGINT,
          MIN(price)::DOUBLE, MAX(price)::DOUBLE, AVG(price)::DOUBLE,
          quantile_cont(price, 0.5)::DOUBLE,
          STDDEV_POP(price)::DOUBLE,
          AVG(kind)::DOUBLE
        FROM read_parquet({common.sql_literal(temporary)})
        """
    ).fetchone()
    connection.close()
    expected_prefix = (
        common.EXPECTED_FAIR_ROWS,
        common.EXPECTED_FAIR_KIND_DRAWS,
        common.EXPECTED_FAIR_CHOOSERS,
        0,
        common.EXPECTED_FAIR_ROWS - 1,
        0,
        common.EXPECTED_NONPOSITIVE_PRICE_ROWS,
        common.EXPECTED_NONPOSITIVE_PRICE_ROWS,
        0,
        common.EXPECTED_NONPOSITIVE_PRICE_ROWS,
        0,
        0,
        0,
        common.EXPECTED_FAIR_ROWS,
        common.EXPECTED_FIRST12_FAIR_ROWS,
        common.EXPECTED_FIRST12_FAIR_CHOOSERS,
    )
    if qa[:16] != expected_prefix:
        raise RuntimeError(f"Fair price-base row conservation failed: {qa}")
    os.replace(temporary, output)
    saved = {
        "status": "KINDNESS_PRICE_FAIR_BASE_PRIVATE_OK",
        "created_utc": common.utc_now(),
        "config_sha256": config_sha256,
        "rows": int(qa[0]),
        "kind_draws": int(qa[1]),
        "choosers": int(qa[2]),
        "first12_rows": int(qa[14]),
        "first12_choosers": int(qa[15]),
        "physical_source_preflight": {
            "rows": int(source_qa[0]),
            "distinct_game_ids": int(source_qa[1]),
            "kind_draws": int(source_qa[2]),
            "choosers": int(source_qa[3]),
            "null_game_ids": int(source_qa[4]),
            "null_chooser_keys": int(source_qa[5]),
            "invalid_price_or_draw_payoff_rows": int(source_qa[6]),
            "nonpositive_price_rows": int(source_qa[7]),
            "zero_price_rows": int(source_qa[8]),
            "negative_price_rows": int(source_qa[9]),
            "first12_rows": int(source_qa[10]),
            "first12_choosers": int(source_qa[11]),
            "minimum_price": float(source_qa[12]),
        },
        "nonpositive_price_rows": int(qa[6]),
        "zero_price_rows": int(qa[7]),
        "negative_price_rows": int(qa[8]),
        "log_price_null_rows": int(qa[9]),
        "positive_price_bad_log_rows": int(qa[10]),
        "price_minimum": float(qa[16]),
        "price_maximum": float(qa[17]),
        "price_mean": float(qa[18]),
        "price_median": float(qa[19]),
        "price_standard_deviation": float(qa[20]),
        "kind_rate": float(qa[21]),
        "nonpositive_price_policy": (
            "The authenticated exact-key fair source contains no nonpositive premium "
            "rows. Level- and log-price estimators therefore use identical full support; "
            "no value is imputed, clipped, or rewritten."
        ),
        "output_sha256": common.sha256_file(output),
        "output_bytes": output.stat().st_size,
        "privacy": "PRIVATE ROW-LEVEL CHECKPOINT; DO NOT PUBLISH",
    }
    common.atomic_json(receipt, saved)
    shutil.rmtree(temp_root, ignore_errors=True)
    print(
        "ELASTICITY_FAIR_BASE_BUILD_OK "
        f"rows={qa[0]:,} choosers={qa[2]:,} kind_draws={qa[1]:,}",
        flush=True,
    )
    return output, saved


def quantile_list(connection: Any, path: Path, field: str, probabilities: list[float]) -> list[float]:
    probability_sql = "[" + ",".join(f"{value:.12g}" for value in probabilities) + "]"
    values = connection.execute(
        f"SELECT quantile_cont({field}, {probability_sql}) FROM read_parquet({common.sql_literal(path)})"
    ).fetchone()[0]
    return [float(value) for value in values]


def unique_edges(values: Sequence[float]) -> list[float]:
    edges: list[float] = []
    for value in values:
        if not edges or value > edges[-1]:
            edges.append(float(value))
    if len(edges) < 3:
        raise RuntimeError("Quantile support collapsed to fewer than two bins")
    return edges


def bin_case(field: str, edges: Sequence[float]) -> str:
    clauses = " ".join(
        f"WHEN CAST({field} AS DOUBLE) < {value:.17g} THEN {index}"
        for index, value in enumerate(edges[1:-1])
    )
    return f"CASE {clauses} ELSE {len(edges) - 2} END"


def build_model_cache(
    *, base: Path, state: Path, threads: int, memory_limit: str,
    config_sha256: str,
) -> tuple[Path, dict[str, Any]]:
    duckdb, _, _, _ = common.import_dependencies()
    output = state / "fair_price_model_private.parquet"
    receipt = state / "fair_price_model_receipt.json"
    saved = authenticate_checkpoint(
        output, receipt, config_sha256=config_sha256, expected_rows=common.EXPECTED_FAIR_ROWS
    )
    if saved:
        print("ELASTICITY_MODEL_CACHE_CHECKPOINT_AUTHENTICATED_OK", flush=True)
        return output, saved
    if output.exists() or receipt.exists():
        raise RuntimeError("Partial price model-cache checkpoint exists")
    print("ELASTICITY_OUTCOME_BLIND_PRICE_BINNING_BEGIN", flush=True)
    connection = duckdb.connect()
    temp_root = state / "duckdb_temp/model_cache"
    common.configure_duckdb(
        connection, threads=threads, memory_limit=memory_limit, temp_directory=temp_root
    )
    price_edges20 = unique_edges(
        quantile_list(connection, base, "price", [index / 20 for index in range(21)])
    )
    draw_edges20 = unique_edges(
        quantile_list(connection, base, "draw_payoff", [index / 20 for index in range(21)])
    )
    draw_edges50 = unique_edges(
        quantile_list(connection, base, "draw_payoff", [index / 50 for index in range(51)])
    )
    price_diagnostics = quantile_list(
        connection, base, "price", [0.0, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99, 0.995, 1.0]
    )
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    connection.execute(
        f"""
        COPY (
          SELECT *,
                 CAST({bin_case('price', price_edges20)} AS TINYINT) AS price_bin20,
                 CAST({bin_case('draw_payoff', draw_edges20)} AS TINYINT) AS draw_bin20,
                 CAST({bin_case('draw_payoff', draw_edges50)} AS TINYINT) AS draw_bin50
          FROM read_parquet({common.sql_literal(base)})
          ORDER BY chooser_index, chooser_sequence
        ) TO {common.sql_literal(temporary)}
          (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
        """
    )
    qa = connection.execute(
        f"""
        SELECT COUNT(*), SUM(kind), COUNT(DISTINCT chooser_index),
               MIN(price_bin20), MAX(price_bin20),
               MIN(draw_bin20), MAX(draw_bin20),
               MIN(draw_bin50), MAX(draw_bin50),
               COUNT(*) FILTER (WHERE price_bin20 IS NULL OR draw_bin20 IS NULL OR draw_bin50 IS NULL)
        FROM read_parquet({common.sql_literal(temporary)})
        """
    ).fetchone()
    connection.close()
    expected = (
        common.EXPECTED_FAIR_ROWS,
        common.EXPECTED_FAIR_KIND_DRAWS,
        common.EXPECTED_FAIR_CHOOSERS,
        0,
        len(price_edges20) - 2,
        0,
        len(draw_edges20) - 2,
        0,
        len(draw_edges50) - 2,
        0,
    )
    if qa != expected:
        raise RuntimeError(f"Price model-cache QA changed: qa={qa} expected={expected}")
    os.replace(temporary, output)
    saved = {
        "status": "KINDNESS_PRICE_MODEL_CACHE_PRIVATE_OK",
        "created_utc": common.utc_now(),
        "config_sha256": config_sha256,
        "rows": int(qa[0]),
        "kind_draws": int(qa[1]),
        "choosers": int(qa[2]),
        "price_edges20": price_edges20,
        "draw_payoff_edges20": draw_edges20,
        "draw_payoff_edges50": draw_edges50,
        "price_quantile_probabilities": [0.0, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99, 0.995, 1.0],
        "price_quantile_values": price_diagnostics,
        "price_p01": price_diagnostics[2],
        "price_p99": price_diagnostics[10],
        "output_sha256": common.sha256_file(output),
        "output_bytes": output.stat().st_size,
        "bin_construction": "outcome-blind empirical quantiles over all certified fair opportunities",
        "privacy": "PRIVATE ROW-LEVEL CHECKPOINT; DO NOT PUBLISH",
    }
    common.atomic_json(receipt, saved)
    shutil.rmtree(temp_root, ignore_errors=True)
    print("ELASTICITY_OUTCOME_BLIND_PRICE_BINNING_OK", flush=True)
    return output, saved


MODEL_COLUMNS = (
    "row_id", "chooser_index", "kind", "price", "log_price", "draw_payoff",
    "engine_eval_cp", "chooser_elo", "opponent_elo", "chooser_rd", "opponent_rd",
    "log_chooser_clock", "log_opponent_clock", "tournament", "month_code",
    "speed_code", "rating_band", "eval_band", "hour_of_week", "both_rd_le_110",
    "activity_quartile", "prior_kind_stratum", "price_bin20", "draw_bin20",
    "draw_bin50", "row_hash",
)


def load_arrays(path: Path) -> dict[str, Any]:
    _, _, _, pq = common.import_dependencies()
    print("ELASTICITY_ARRAY_LOAD_BEGIN", flush=True)
    table = pq.read_table(path, columns=list(MODEL_COLUMNS))
    # Keep log_price nullable so the same kernels fail safely if a future or
    # synthetic authority contains a nonpositive price. The authenticated
    # production authority has no such row, so level and log support coincide.
    nullable = {"log_price", "log_chooser_clock", "log_opponent_clock"}
    arrays = {
        name: common.arrow_numpy(table, name, nullable_float=name in nullable)
        for name in MODEL_COLUMNS
    }
    del table
    gc.collect()
    print("ELASTICITY_ARRAY_LOAD_OK", flush=True)
    return arrays


def standardized(values: Any) -> tuple[Any, Any | None]:
    _, np, _, _ = common.import_dependencies()
    raw = np.asarray(values, dtype=np.float64)
    observed = raw[np.isfinite(raw)]
    if observed.size == 0:
        raise RuntimeError("Control contains no finite observations")
    median = float(np.median(observed))
    missing = ~np.isfinite(raw)
    filled = raw.copy()
    filled[missing] = median
    scale = float(np.std(filled))
    if not math.isfinite(scale) or scale <= 1e-12:
        raise RuntimeError("Control has no variation")
    result = (filled - float(np.mean(filled))) / scale
    return result, missing.astype(np.float64) if np.any(missing) else None


def add_dummies(regressors: dict[str, Any], values: Any, prefix: str) -> None:
    _, np, _, _ = common.import_dependencies()
    codes = np.asarray(values, dtype=np.int64)
    levels = sorted(int(value) for value in np.unique(codes))
    if len(levels) < 2:
        return
    for level in levels[1:]:
        regressors[f"{prefix}_{level}"] = (codes == level).astype(np.float64)


def reference_piecewise(draw: Any) -> dict[str, Any]:
    _, np, _, _ = common.import_dependencies()
    draw = np.asarray(draw, dtype=np.float64)
    return {
        "positive_draw_payoff": np.maximum(draw, 0.0),
        "negative_draw_payoff": np.maximum(-draw, 0.0),
        "draw_nonnegative": (draw >= 0).astype(np.float64),
    }


def reference_cubic(draw: Any) -> dict[str, Any]:
    _, np, _, _ = common.import_dependencies()
    z, _ = standardized(draw)
    return {
        "draw_z": z,
        "draw_z2": z * z,
        "draw_z3": z * z * z,
        "draw_nonnegative": (np.asarray(draw) >= 0).astype(np.float64),
    }


def adjusted_controls(data: Mapping[str, Any], indices: Any) -> dict[str, Any]:
    controls: dict[str, Any] = {}
    for name in (
        "engine_eval_cp", "chooser_rd", "opponent_rd", "log_chooser_clock",
        "log_opponent_clock",
    ):
        z, missing = standardized(data[name][indices])
        controls[f"z_{name}"] = z
        if missing is not None:
            controls[f"{name}_missing"] = missing
    controls["engine_eval_z2"] = controls["z_engine_eval_cp"] ** 2
    controls["tournament"] = data["tournament"][indices].astype(float)
    month_z, _ = standardized(data["month_code"][indices])
    controls["month_trend_z"] = month_z
    controls["month_trend_z2"] = month_z * month_z
    add_dummies(controls, data["speed_code"][indices], "speed")
    return controls


def lpm_specification(model: str, role: str, sample: str) -> dict[str, Any]:
    return {
        "model": model,
        "epistemic_label": "X" if role != "validation" else "V",
        "analysis_role": role,
        "sample": sample,
        "outcome": "indicator for kind draw",
        "economic_price": "chooser_win_premium_v2: rating points forgone by draw versus win",
        "cluster": "chooser_username_norm mapped losslessly to chooser_index",
        "causal_claim": False,
        "multiple_testing_family": "outside Campaign 1 confirmatory Holm family",
    }


def fit_lpm_model(
    *, data: Mapping[str, Any], mask: Any, model: str, role: str,
    exposure: str, exposure_values: Any, reference: str,
    adjusted: bool = False, fixed_reference_bins: int | None = None,
    winsor_values: Any | None = None,
) -> dict[str, Any]:
    _, np, _, _ = common.import_dependencies()
    indices = np.flatnonzero(mask)
    if indices.size < 1_000:
        raise RuntimeError(f"{model}: fewer than 1,000 rows")
    regressors: dict[str, Any] = {}
    values = exposure_values[indices] if winsor_values is None else winsor_values[indices]
    regressors[exposure] = values
    if reference == "piecewise":
        regressors.update(reference_piecewise(data["draw_payoff"][indices]))
    elif reference == "cubic":
        regressors.update(reference_cubic(data["draw_payoff"][indices]))
    elif reference not in {"none", "bins"}:
        raise ValueError(f"Unknown reference control: {reference}")
    if adjusted:
        regressors.update(adjusted_controls(data, indices))
    fixed_effects: list[Any] = [data["chooser_index"][indices]]
    if fixed_reference_bins == 20:
        fixed_effects.append(data["draw_bin20"][indices])
    elif fixed_reference_bins == 50:
        fixed_effects.append(data["draw_bin50"][indices])
    result = common.fit_lpm_cluster(
        outcome=data["kind"][indices],
        regressors=regressors,
        clusters=data["chooser_index"][indices],
        fixed_effects=fixed_effects,
        exposure_names=(exposure,),
        row_ids=data["row_hash"][indices],
        specification=lpm_specification(model, role, f"rows_selected={indices.size}"),
    )
    result["price_mean"] = float(np.mean(data["price"][indices]))
    result["price_median"] = float(np.median(data["price"][indices]))
    result["reference_control"] = reference
    result["reference_quantile_fixed_effect_bins"] = fixed_reference_bins
    result["adjusted_controls"] = adjusted
    if exposure == "log_price":
        common.add_lpm_elasticity(result, term=exposure, price_scale=None)
    elif exposure == "price":
        common.add_lpm_elasticity(
            result, term=exposure, price_scale=float(result["price_mean"])
        )
        price_mean_elasticity = dict(result["elasticity"])
        common.add_lpm_elasticity(
            result, term=exposure, price_scale=float(result["price_median"])
        )
        result["elasticity_at_median_price"] = result.pop("elasticity")
        result["elasticity"] = price_mean_elasticity
    return finite(result)


def model_checkpoint_path(state: Path, model: str) -> Path:
    safe = "".join(character if character.isalnum() or character in "_-" else "_" for character in model)
    return state / "model_checkpoints" / f"{safe}.json"


def attempt_lpm(
    *, state: Path, config_sha256: str, attempts: list[dict[str, Any]],
    results: list[dict[str, Any]], model: str, fit: Any,
) -> None:
    checkpoint = model_checkpoint_path(state, model)
    if checkpoint.is_file():
        saved = common.load_json(checkpoint)
        if saved.get("config_sha256") != config_sha256 or saved.get("model") != model:
            raise RuntimeError(f"Model checkpoint configuration changed: {model}")
        attempts.append(dict(saved["attempt"]))
        if saved.get("result") is not None:
            results.append(dict(saved["result"]))
        print(f"ELASTICITY_MODEL_CHECKPOINT_AUTHENTICATED model={model}", flush=True)
        return
    print(f"ELASTICITY_MODEL_BEGIN model={model}", flush=True)
    started = time.time()
    attempt = {
        "model": model,
        "status": None,
        "error": None,
        "runtime_seconds": None,
    }
    result = None
    try:
        result = fit()
        attempt["status"] = "ESTIMATED"
        results.append(result)
        print(f"ELASTICITY_MODEL_OK model={model}", flush=True)
    except BaseException as error:
        if not retained_error(error):
            raise
        attempt["status"] = "FAILED_RETAINED"
        attempt["error"] = f"{type(error).__name__}: {error}"
        print(f"ELASTICITY_MODEL_FAILED_RETAINED model={model} error={error}", flush=True)
    attempt["runtime_seconds"] = time.time() - started
    attempts.append(attempt)
    common.atomic_json(
        checkpoint,
        finite(
            {
                "status": "KINDNESS_PRICE_MODEL_CHECKPOINT_OK",
                "created_utc": common.utc_now(),
                "config_sha256": config_sha256,
                "model": model,
                "attempt": attempt,
                "result": result,
            }
        ),
    )
    gc.collect()


def find_result(results: Sequence[Mapping[str, Any]], model: str) -> dict[str, Any]:
    matches = [dict(row) for row in results if row.get("model") == model]
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one result for {model}; found {len(matches)}")
    return matches[0]


def run_replication_audits(
    *, data: Mapping[str, Any], state: Path, config_sha256: str,
    attempts: list[dict[str, Any]], results: list[dict[str, Any]],
) -> dict[str, Any]:
    _, np, _, _ = common.import_dependencies()
    all_rows = np.ones(data["kind"].size, dtype=bool)
    first12 = data["month_code"] < 12
    if int(np.count_nonzero(first12)) != common.EXPECTED_FIRST12_FAIR_ROWS:
        raise RuntimeError("First-12-month replication rows changed")
    if int(np.unique(data["chooser_index"][first12]).size) != common.EXPECTED_FIRST12_FAIR_CHOOSERS:
        raise RuntimeError("First-12-month replication choosers changed")

    model24 = "V_certified_stage08_full24_piecewise_reproduction"
    attempt_lpm(
        state=state, config_sha256=config_sha256, attempts=attempts, results=results,
        model=model24,
        fit=lambda: fit_lpm_model(
            data=data, mask=all_rows, model=model24, role="validation",
            exposure="price", exposure_values=data["price"], reference="piecewise",
        ),
    )
    audit24 = find_result(results, model24)
    terms24 = {row["term"]: row for row in audit24["terms"]}
    observed24 = {
        "beta_plus_pp_per_rating_point": terms24["positive_draw_payoff"]["coefficient_percentage_points"],
        "beta_minus_pp_per_rating_point": terms24["negative_draw_payoff"]["coefficient_percentage_points"],
        "threshold_jump_pp": terms24["draw_nonnegative"]["coefficient_percentage_points"],
    }
    differences24 = {
        key: float(observed24[key] - common.EXPECTED_STAGE08_FULL_PIECEWISE[key])
        for key in observed24
    }
    if any(abs(value) > STRICT_AUDIT_TOLERANCE_PP for value in differences24.values()):
        raise RuntimeError(
            f"Certified Stage08 piecewise reproduction failed: {differences24}"
        )

    model12 = "X_current_temporal_first_half_piecewise_price_bridge"
    def fit_a11() -> dict[str, Any]:
        indices = np.flatnonzero(first12)
        regressors = {
            "positive_draw_payoff": np.maximum(data["draw_payoff"][indices], 0.0),
            "negative_draw_payoff": np.maximum(-data["draw_payoff"][indices], 0.0),
            "price": data["price"][indices],
        }
        result = common.fit_lpm_cluster(
            outcome=data["kind"][indices], regressors=regressors,
            clusters=data["chooser_index"][indices],
            fixed_effects=(data["chooser_index"][indices],),
            exposure_names=("price",), row_ids=data["row_hash"][indices],
            specification=lpm_specification(
                model12,
                "historical_cross_window_bridge",
                "current temporal first half: 2023-11 through 2024-10",
            ),
        )
        result["price_mean"] = float(np.mean(data["price"][indices]))
        result["price_median"] = float(np.median(data["price"][indices]))
        common.add_lpm_elasticity(result, term="price", price_scale=result["price_mean"])
        return finite(result)
    attempt_lpm(
        state=state, config_sha256=config_sha256, attempts=attempts, results=results,
        model=model12, fit=fit_a11,
    )
    audit12 = find_result(results, model12)
    terms12 = {row["term"]: row for row in audit12["terms"]}
    observed12 = {
        key: float(terms12[key]["coefficient_percentage_points"])
        for key in APPENDIX_A11_EXPECTED
    }
    differences12 = {
        key: observed12[key] - APPENDIX_A11_EXPECTED[key]
        for key in observed12
    }
    receipt = {
        "status": "KINDNESS_PRICE_REPLICATION_AUDITS_OK",
        "stage08_full24_expected": common.EXPECTED_STAGE08_FULL_PIECEWISE,
        "stage08_full24_observed": observed24,
        "stage08_full24_differences": differences24,
        "stage08_tolerance_pp": STRICT_AUDIT_TOLERANCE_PP,
        "appendix_A11_historical_10k_expected_rounded": APPENDIX_A11_EXPECTED,
        "current_temporal_first_half_observed": observed12,
        "current_temporal_first_half_minus_historical_A11_differences": differences12,
        "appendix_A11_comparison_status": (
            "NONIDENTICAL_ENGINE_AND_CALENDAR_WINDOW_NO_PASS_FAIL"
        ),
        "appendix_A11_note": (
            "The displayed draft A11 coefficients came from the predecessor 10k-node "
            "2023-10 through 2024-09 window (8,648,684 fair rows). The current "
            "certified Stage07 authority begins in 2023-11, so this bridge instead "
            "estimates its actual first temporal half, 2023-11 through 2024-10 "
            f"({common.EXPECTED_FIRST12_FAIR_ROWS:,} fair rows). It is an openly "
            "reported cross-window comparison, not a reproduction test."
        ),
    }
    common.atomic_json(state / "replication_audits.json", finite(receipt))
    print("ELASTICITY_REPLICATION_AUDITS_OK", flush=True)
    return receipt


def run_main_models(
    *, data: Mapping[str, Any], cache_receipt: Mapping[str, Any], state: Path,
    config_sha256: str, attempts: list[dict[str, Any]], results: list[dict[str, Any]],
) -> None:
    _, np, _, _ = common.import_dependencies()
    all_rows = np.ones(data["kind"].size, dtype=bool)
    price = data["price"]
    log_price = data["log_price"]
    p01 = float(cache_receipt["price_p01"])
    p99 = float(cache_receipt["price_p99"])
    trimmed = (price >= p01) & (price <= p99)
    winsor = np.log(np.clip(price, p01, p99))

    definitions = [
        (
            "X_lpm_level_price_chooser_fe_piecewise_reference", "price", price,
            "piecewise", False, None, all_rows, None,
        ),
        (
            "X_lpm_log_price_chooser_fe_no_reference", "log_price", log_price,
            "none", False, None, all_rows, None,
        ),
        (
            "X_lpm_log_price_chooser_fe_piecewise_reference", "log_price", log_price,
            "piecewise", False, None, all_rows, None,
        ),
        (
            "X_lpm_log_price_chooser_fe_cubic_reference", "log_price", log_price,
            "cubic", False, None, all_rows, None,
        ),
        (
            "X_lpm_log_price_chooser_fe_draw20_fe", "log_price", log_price,
            "bins", False, 20, all_rows, None,
        ),
        (
            "X_lpm_log_price_chooser_fe_draw50_fe", "log_price", log_price,
            "bins", False, 50, all_rows, None,
        ),
        (
            PRIMARY_MODEL, "log_price", log_price,
            "bins", True, 50, all_rows, None,
        ),
        (
            "X_lpm_level_price_chooser_fe_draw50_fe_adjusted", "price", price,
            "bins", True, 50, all_rows, None,
        ),
        (
            "X_lpm_log_price_trim_p01_p99_draw50_fe_adjusted", "log_price", log_price,
            "bins", True, 50, trimmed, None,
        ),
        (
            "X_lpm_log_price_winsor_p01_p99_draw50_fe_adjusted", "log_price", log_price,
            "bins", True, 50, all_rows, winsor,
        ),
    ]
    for model, exposure, values, reference, adjusted, bins, mask, winsor_values in definitions:
        attempt_lpm(
            state=state, config_sha256=config_sha256, attempts=attempts, results=results,
            model=model,
            fit=lambda model=model, exposure=exposure, values=values, reference=reference,
                       adjusted=adjusted, bins=bins, mask=mask,
                       winsor_values=winsor_values: fit_lpm_model(
                data=data, mask=mask, model=model, role="exploratory_main_or_sensitivity",
                exposure=exposure, exposure_values=values, reference=reference,
                adjusted=adjusted, fixed_reference_bins=bins,
                winsor_values=winsor_values,
            ),
        )

    pooled_model = "X_pooled_lpm_log_price_piecewise_reference_controls"
    def fit_pooled() -> dict[str, Any]:
        indices = np.flatnonzero(all_rows)
        regressors: dict[str, Any] = {
            "intercept": np.ones(indices.size),
            "log_price": log_price[indices],
        }
        regressors.update(reference_piecewise(data["draw_payoff"][indices]))
        regressors.update(adjusted_controls(data, indices))
        result = common.fit_lpm_cluster(
            outcome=data["kind"][indices], regressors=regressors,
            clusters=data["chooser_index"][indices], fixed_effects=(),
            exposure_names=("log_price",), row_ids=data["row_hash"][indices],
            specification=lpm_specification(pooled_model, "exploratory_between_within_comparison", "all fair rows"),
        )
        result["price_mean"] = float(np.mean(price))
        result["price_median"] = float(np.median(price))
        common.add_lpm_elasticity(result, term="log_price", price_scale=None)
        return finite(result)
    attempt_lpm(
        state=state, config_sha256=config_sha256, attempts=attempts, results=results,
        model=pooled_model, fit=fit_pooled,
    )


def run_heterogeneity(
    *, data: Mapping[str, Any], state: Path, config_sha256: str,
    attempts: list[dict[str, Any]], results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    _, np, _, _ = common.import_dependencies()
    grids: list[tuple[str, Any, Sequence[int], Sequence[str]]] = [
        ("rating_band", data["rating_band"], range(4), ("below_1600", "1600_1999", "2000_2399", "2400_plus")),
        ("speed", data["speed_code"], range(6), ("ultrabullet", "bullet", "blitz", "rapid", "classical", "correspondence")),
        ("eval_band", data["eval_band"], range(5), ("below_0cp", "0_100cp", "101_300cp", "301_600cp", "above_600cp")),
        ("temporal_half", (data["month_code"] >= 12).astype(int), range(2), ("first12", "second12")),
        ("rating_certainty", data["both_rd_le_110"], range(2), ("either_rd_above_110", "both_rd_le_110")),
        ("activity_quartile", data["activity_quartile"], range(4), ("q1", "q2", "q3", "q4")),
        ("lagged_kindness", data["prior_kind_stratum"], range(3), ("none_prior", "one_prior", "two_plus_prior")),
    ]
    metadata: list[dict[str, Any]] = []
    for dimension, values, levels, labels in grids:
        for level, label in zip(levels, labels, strict=True):
            mask = np.asarray(values) == level
            model = f"X_heterogeneity_{dimension}_{label}_log_price_draw20_fe"
            metadata.append(
                {
                    "model": model,
                    "dimension": dimension,
                    "level": int(level),
                    "label": label,
                    "requested_rows": int(np.count_nonzero(mask)),
                    "requested_choosers": int(np.unique(data["chooser_index"][mask]).size),
                }
            )
            attempt_lpm(
                state=state, config_sha256=config_sha256, attempts=attempts, results=results,
                model=model,
                fit=lambda mask=mask, model=model: fit_lpm_model(
                    data=data, mask=mask, model=model, role="exploratory_heterogeneity",
                    exposure="log_price", exposure_values=data["log_price"],
                    reference="bins", adjusted=False, fixed_reference_bins=20,
                ),
            )
    return metadata


def run_nonparametric_price_bins(
    *, data: Mapping[str, Any], state: Path, config_sha256: str,
    attempts: list[dict[str, Any]], results: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    _, np, _, _ = common.import_dependencies()
    model = "X_nonparametric_price20_chooser_fe_piecewise_reference"
    all_rows = np.ones(data["kind"].size, dtype=bool)
    def fit_bins() -> dict[str, Any]:
        indices = np.flatnonzero(all_rows)
        bin_code = data["price_bin20"][indices]
        realized = sorted(int(value) for value in np.unique(bin_code))
        regressors: dict[str, Any] = {
            f"price_bin_{level}": (bin_code == level).astype(float)
            for level in realized[1:]
        }
        regressors.update(reference_piecewise(data["draw_payoff"][indices]))
        result = common.fit_lpm_cluster(
            outcome=data["kind"][indices], regressors=regressors,
            clusters=data["chooser_index"][indices],
            fixed_effects=(data["chooser_index"][indices],),
            exposure_names=tuple(f"price_bin_{level}" for level in realized[1:]),
            row_ids=data["row_hash"][indices],
            specification=lpm_specification(model, "exploratory_nonparametric", "all fair rows"),
        )
        result["price_bin_reference"] = realized[0]
        return finite(result)
    attempt_lpm(
        state=state, config_sha256=config_sha256, attempts=attempts, results=results,
        model=model, fit=fit_bins,
    )
    matches = [dict(row) for row in results if row.get("model") == model]
    if not matches:
        failure = next(row for row in attempts if row.get("model") == model)
        placeholder = {
            "model": model,
            "status": "FAILED_RETAINED",
            "error": failure.get("error"),
        }
        return [placeholder], [placeholder]
    fitted = matches[0]
    term_map = {row["term"]: row for row in fitted["terms"]}
    bin_code = data["price_bin20"]
    quantity_mean = float(np.mean(data["kind"]))
    rows: list[dict[str, Any]] = []
    coefficients: dict[int, float] = {0: 0.0}
    for level in range(int(np.max(bin_code)) + 1):
        if level > 0:
            coefficients[level] = float(term_map[f"price_bin_{level}"]["coefficient_probability_units"])
    shares = {level: float(np.mean(bin_code == level)) for level in coefficients}
    weighted_effect = sum(shares[level] * coefficients[level] for level in coefficients)
    for level in coefficients:
        mask = bin_code == level
        n = int(np.count_nonzero(mask))
        raw_q = float(np.mean(data["kind"][mask]))
        adjusted_q = quantity_mean + coefficients[level] - weighted_effect
        rows.append(
            {
                "price_bin": level,
                "rows": n,
                "choosers": int(np.unique(data["chooser_index"][mask]).size),
                "kind_draws": int(np.sum(data["kind"][mask])),
                "price_mean": float(np.mean(data["price"][mask])),
                "price_median": float(np.median(data["price"][mask])),
                "price_minimum": float(np.min(data["price"][mask])),
                "price_maximum": float(np.max(data["price"][mask])),
                "raw_kind_rate": raw_q,
                "raw_kind_rate_pct": 100.0 * raw_q,
                "adjusted_kind_rate_centered_to_overall_mean": adjusted_q,
                "adjusted_kind_rate_pct": 100.0 * adjusted_q,
                "bin_effect_relative_to_bin0_probability_units": coefficients[level],
                "bin_effect_relative_to_bin0_pp": 100.0 * coefficients[level],
            }
        )
    arcs: list[dict[str, Any]] = []
    for left, right in zip(rows[:-1], rows[1:], strict=True):
        p0, p1 = float(left["price_mean"]), float(right["price_mean"])
        for rate_name, label in (
            ("raw_kind_rate", "raw"),
            ("adjusted_kind_rate_centered_to_overall_mean", "chooser_fe_piecewise_adjusted"),
        ):
            q0, q1 = float(left[rate_name]), float(right[rate_name])
            price_change = (p1 - p0) / ((p1 + p0) / 2.0)
            quantity_change = (q1 - q0) / ((q1 + q0) / 2.0) if (q1 + q0) > 0 else math.nan
            arcs.append(
                finite(
                    {
                        "left_price_bin": left["price_bin"],
                        "right_price_bin": right["price_bin"],
                        "rate_series": label,
                        "left_price_mean": p0,
                        "right_price_mean": p1,
                        "left_kind_rate": q0,
                        "right_kind_rate": q1,
                        "midpoint_arc_elasticity": quantity_change / price_change
                        if price_change != 0 else math.nan,
                    }
                )
            )
    return rows, arcs


def run_conditional_ppml(
    *, data: Mapping[str, Any], state: Path, config_sha256: str,
    attempts: list[dict[str, Any]], results: list[dict[str, Any]],
) -> None:
    _, np, _, _ = common.import_dependencies()
    model = "X_conditional_chooser_fe_poisson_log_price_piecewise_controls"
    checkpoint = model_checkpoint_path(state, model)
    if checkpoint.is_file():
        saved = common.load_json(checkpoint)
        if saved.get("config_sha256") != config_sha256:
            raise RuntimeError("Conditional PPML checkpoint config changed")
        attempts.append(saved["attempt"])
        if saved.get("result") is not None:
            results.append(saved["result"])
        print("ELASTICITY_CONDITIONAL_PPML_CHECKPOINT_AUTHENTICATED_OK", flush=True)
        return
    print("ELASTICITY_CONDITIONAL_PPML_BEGIN", flush=True)
    started = time.time()
    attempt = {"model": model, "status": None, "error": None, "runtime_seconds": None}
    result = None
    try:
        regressors: dict[str, Any] = {"log_price": data["log_price"]}
        draw = data["draw_payoff"]
        for name, values in reference_piecewise(draw).items():
            z, _ = standardized(values)
            regressors[name + "_z"] = z
        eval_z, _ = standardized(data["engine_eval_cp"])
        regressors["engine_eval_z"] = eval_z
        regressors["engine_eval_z2"] = eval_z * eval_z
        for name in ("chooser_rd", "opponent_rd", "log_chooser_clock", "log_opponent_clock"):
            z, missing = standardized(data[name])
            regressors["z_" + name] = z
            if missing is not None:
                regressors[name + "_missing"] = missing
        regressors["tournament"] = data["tournament"].astype(float)
        month_z, _ = standardized(data["month_code"])
        regressors["month_trend_z"] = month_z
        regressors["month_trend_z2"] = month_z * month_z
        add_dummies(regressors, data["speed_code"], "speed")
        result = common.conditional_fe_poisson(
            outcome=data["kind"], regressors=regressors,
            chooser_codes=data["chooser_index"], exposure_name="log_price",
            specification={
                **lpm_specification(model, "exploratory_log_link_sensitivity", "all fair rows"),
                "estimator": "conditional chooser-fixed-effect Poisson QMLE",
                "support_note": "all-zero chooser groups are excluded by the conditional likelihood",
            },
        )
        result = finite(result)
        results.append(result)
        attempt["status"] = "ESTIMATED"
        print("ELASTICITY_CONDITIONAL_PPML_OK", flush=True)
    except BaseException as error:
        if not retained_error(error):
            raise
        attempt["status"] = "FAILED_RETAINED"
        attempt["error"] = f"{type(error).__name__}: {error}"
        print(f"ELASTICITY_CONDITIONAL_PPML_FAILED_RETAINED error={error}", flush=True)
    attempt["runtime_seconds"] = time.time() - started
    attempts.append(attempt)
    common.atomic_json(
        checkpoint,
        finite(
            {
                "status": "KINDNESS_PRICE_MODEL_CHECKPOINT_OK",
                "created_utc": common.utc_now(),
                "config_sha256": config_sha256,
                "model": model,
                "attempt": attempt,
                "result": result,
            }
        ),
    )
    gc.collect()


def flatten_models(results: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for model in results:
        elasticity = model.get("elasticity") or {}
        for term in model.get("terms", []):
            rows.append(
                finite(
                    {
                        "model": model.get("model"),
                        "epistemic_label": model.get("epistemic_label"),
                        "analysis_role": model.get("analysis_role"),
                        "status": model.get("status"),
                        "term": term.get("term"),
                        "coefficient_probability_units": term.get("coefficient_probability_units", term.get("coefficient")),
                        "coefficient_percentage_points": term.get("coefficient_percentage_points"),
                        "standard_error_probability_units": term.get("standard_error_probability_units", term.get("standard_error_clustered")),
                        "standard_error_percentage_points": term.get("standard_error_percentage_points"),
                        "t_cluster": term.get("t_cluster"),
                        "p_value_two_sided": term.get("p_value_two_sided"),
                        "rows_raw": model.get("rows_raw", model.get("rows_informative_positive_total")),
                        "rows_identifying": model.get("rows_identifying"),
                        "chooser_clusters": model.get("chooser_clusters", model.get("chooser_groups_informative_positive_total")),
                        "outcome_mean": model.get("outcome_mean"),
                        "price_mean": model.get("price_mean"),
                        "elasticity_estimate": elasticity.get("estimate") if term.get("term") == elasticity.get("term") else None,
                        "elasticity_se": elasticity.get("standard_error_delta_quantity_fixed", elasticity.get("standard_error")) if term.get("term") == elasticity.get("term") else None,
                        "elasticity_ci95_low": elasticity.get("ci95_low") if term.get("term") == elasticity.get("term") else None,
                        "elasticity_ci95_high": elasticity.get("ci95_high") if term.get("term") == elasticity.get("term") else None,
                        "causal_claim": model.get("causal_claim", False),
                    }
                )
            )
    return rows


def interpretation(primary: Mapping[str, Any]) -> dict[str, Any]:
    elasticity = primary["elasticity"]
    estimate = float(elasticity["estimate"])
    low = float(elasticity["ci95_low"])
    high = float(elasticity["ci95_high"])
    if estimate < 0:
        direction = "negative: conditionally consistent with downward-sloping demand"
    elif estimate > 0:
        direction = "positive: conditionally upward-sloping; not a causal demand curve"
    else:
        direction = "zero at displayed precision"
    if low <= 0 <= high:
        precision = "95% interval includes zero"
    elif high < 0:
        precision = "95% interval is negative"
    else:
        precision = "95% interval is positive"
    magnitude = abs(estimate)
    if magnitude < 0.1:
        magnitude_label = "very inelastic in magnitude"
    elif magnitude < 1.0:
        magnitude_label = "inelastic in magnitude"
    else:
        magnitude_label = "elastic in magnitude"
    return {
        "primary_model": primary["model"],
        "elasticity_estimate": estimate,
        "elasticity_ci95_low": low,
        "elasticity_ci95_high": high,
        "direction": direction,
        "precision": precision,
        "magnitude_label": magnitude_label,
        "claim_boundary": (
            "functional-form-sensitive conditional association with a premium "
            "deterministically generated by rating state; not a causal price elasticity"
        ),
        "price_unit": "rating-point premium forgone by drawing instead of claiming",
        "quantity": "probability of a kind draw within certified fair states",
    }


def unavailable_analyses() -> list[dict[str, Any]]:
    return [
        {
            "analysis": "November 18 2025 color-advantage rule-change event study",
            "status": "NOT_ESTIMABLE_IN_CURRENT_AUTHORITY_PRIOR_BRANCH_EXISTS",
            "reason": (
                "Certified Stage07 ends in October 2025 and contains no post-change "
                "observations. A separate Aug-Dec 2025 branch already estimated this "
                "reference-location design; it is not being concealed or reserved here."
            ),
            "saved_for_later": False,
        },
        {
            "analysis": "Alternative fixed-RD and local-RD price elasticities",
            "status": "ATTEMPTED_UNESTIMABLE_CURRENT_AUTHORITY",
            "reason": "The certified Stage07 schema contains only the v2 reconstructed payoff and premium fields; predecessor price fields are not row-level members of this authority.",
            "saved_for_later": False,
        },
        {
            "analysis": "Causal demand elasticity",
            "status": "NOT_IDENTIFIED",
            "reason": (
                "The premium is a deterministic nonlinear function of chooser RD, "
                "opponent RD, and expected score. These rating states and matchmaking "
                "are not randomly assigned and may directly proxy activity, provisional "
                "status, tenure, rustiness, and opponent selection."
            ),
            "saved_for_later": False,
        },
        {
            "analysis": "Dollar-price elasticity",
            "status": "NOT_DEFINED",
            "reason": "The decision price is denominated in rating points and cannot be converted to money without an unsupported cardinal exchange rate.",
            "saved_for_later": False,
        },
    ]


def report_hashes(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name == "report_file_hashes.tsv":
            continue
        rows.append(
            {
                "file": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": common.sha256_file(path),
            }
        )
    return rows


def write_report_manifest(root: Path) -> None:
    rows = report_hashes(root)
    lines = ["file\tbytes\tsha256"] + [
        f"{row['file']}\t{row['bytes']}\t{row['sha256']}" for row in rows
    ]
    common.atomic_text(root / "report_file_hashes.tsv", "\n".join(lines) + "\n")


def execute(args: argparse.Namespace) -> Path:
    started = time.time()
    root = package_root()
    package_rows = common.package_manifest(root)
    project = args.project_root.expanduser().resolve()
    if project != PROJECT_AUTHORITY:
        raise RuntimeError(f"Project authority path changed: {project}")
    if args.threads < 1 or args.threads > 16:
        raise RuntimeError("Threads must be between 1 and 16")
    state = (
        args.state_root.expanduser().resolve()
        if args.state_root else project / "derived/private" / STATE_NAME
    )
    state.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(state).free < MINIMUM_FREE_BYTES:
        raise RuntimeError("Fewer than 20 GiB free on the private-checkpoint volume")
    run_id = args.run_id or common.utc_run_id()
    output_parent = (
        args.output_root.expanduser().resolve()
        if args.output_root else project / "output" / OUTPUT_NAME
    )
    output = output_parent / run_id
    if output.exists():
        raise RuntimeError(f"Output run already exists: {output}")
    output.mkdir(parents=True)
    pointer = args.execution_pointer
    if pointer:
        common.atomic_json(
            pointer,
            {
                "status": "KINDNESS_PRICE_ELASTICITY_EXECUTION_POINTER",
                "created_utc": common.utc_now(),
                "run_id": run_id,
                "output_root": str(output),
                "state_root": str(state),
                "package_root": str(root),
            },
        )
    try:
        print("KINDNESS_PRICE_ELASTICITY_AUTHENTICATION_BEGIN", flush=True)
        stage_root = project / common.STAGE07_RELATIVE
        stage_auth = common.authenticate_stage07(stage_root)
        paths = common.stage07_paths(stage_root)
        plan_path = root / "payload/docs/kindness_price_elasticity_exploratory_plan_v1_0_2_2026-08-25.md"
        config = {
            "script_version": SCRIPT_VERSION,
            "script_sha256": common.sha256_file(Path(__file__)),
            "common_sha256": common.sha256_file(Path(common.__file__)),
            "plan_sha256": common.sha256_file(plan_path),
            "stage07_success_sha256": common.EXPECTED_STAGE07_SUCCESS_SHA256,
            "package_manifest_sha256": common.sha256_json(package_rows),
            "threads": args.threads,
            "memory_limit": args.memory_limit,
            "primary_model": PRIMARY_MODEL,
            "all_new_models_epistemic_label": "X",
        }
        config_sha256 = common.sha256_json(config)
        state_config = state / "configuration.json"
        if state_config.is_file():
            saved_config = common.load_json(state_config)
            if saved_config.get("config_sha256") != config_sha256:
                raise RuntimeError("Private state belongs to a different elasticity configuration")
        else:
            common.atomic_json(
                state_config,
                {
                    "status": "KINDNESS_PRICE_ELASTICITY_PRIVATE_STATE_CREATED",
                    "created_utc": common.utc_now(),
                    "config_sha256": config_sha256,
                    "config": config,
                    "privacy": "PRIVATE; DO NOT PUBLISH ROW-LEVEL CHECKPOINTS",
                },
            )
        common.atomic_json(output / "input_authorities.json", {"config": config, "config_sha256": config_sha256, "stage07": stage_auth})
        print("KINDNESS_PRICE_ELASTICITY_AUTHENTICATION_OK", flush=True)

        base, base_receipt = build_fair_base(
            paths=paths, state=state, threads=args.threads,
            memory_limit=args.memory_limit, config_sha256=config_sha256,
        )
        cache, cache_receipt = build_model_cache(
            base=base, state=state, threads=args.threads,
            memory_limit=args.memory_limit, config_sha256=config_sha256,
        )
        common.atomic_json(output / "price_support.json", finite({"base": base_receipt, "model_cache": cache_receipt}))
        data = load_arrays(cache)
        if data["kind"].size != common.EXPECTED_FAIR_ROWS or int(data["kind"].sum()) != common.EXPECTED_FAIR_KIND_DRAWS:
            raise RuntimeError("Loaded elasticity arrays lost certified support")

        attempts: list[dict[str, Any]] = []
        results: list[dict[str, Any]] = []
        audits = run_replication_audits(
            data=data, state=state, config_sha256=config_sha256,
            attempts=attempts, results=results,
        )
        run_main_models(
            data=data, cache_receipt=cache_receipt, state=state,
            config_sha256=config_sha256, attempts=attempts, results=results,
        )
        nonparametric, arcs = run_nonparametric_price_bins(
            data=data, state=state, config_sha256=config_sha256,
            attempts=attempts, results=results,
        )
        heterogeneity = run_heterogeneity(
            data=data, state=state, config_sha256=config_sha256,
            attempts=attempts, results=results,
        )
        run_conditional_ppml(
            data=data, state=state, config_sha256=config_sha256,
            attempts=attempts, results=results,
        )
        primary = find_result(results, PRIMARY_MODEL)
        primary_interpretation = interpretation(primary)

        common.atomic_json(output / "replication_audits.json", finite(audits))
        common.atomic_json(output / "model_attempts.json", finite(attempts))
        common.write_csv(output / "model_attempts.csv", [finite(row) for row in attempts])
        common.atomic_json(output / "elasticity_models.json", finite(results))
        common.write_csv(output / "elasticity_models.csv", flatten_models(results))
        common.write_csv(output / "nonparametric_price_bins.csv", nonparametric)
        common.write_csv(output / "adjacent_arc_elasticities.csv", arcs)
        common.write_csv(output / "heterogeneity_support.csv", heterogeneity)
        unavailable = unavailable_analyses()
        common.atomic_json(output / "attempted_unestimable_or_unidentified.json", unavailable)
        common.atomic_json(output / "primary_interpretation.json", finite(primary_interpretation))

        success = {
            "status": "KINDNESS_PRICE_ELASTICITY_V102_OK",
            "created_utc": common.utc_now(),
            "runtime_seconds": time.time() - started,
            "config_sha256": config_sha256,
            "rows": common.EXPECTED_FAIR_ROWS,
            "kind_draws": common.EXPECTED_FAIR_KIND_DRAWS,
            "choosers": common.EXPECTED_FAIR_CHOOSERS,
            "models_attempted": len(attempts),
            "models_estimated": sum(row["status"] == "ESTIMATED" for row in attempts),
            "models_failed_retained": sum(row["status"] != "ESTIMATED" for row in attempts),
            "primary": primary_interpretation,
            "epistemic_label": "X",
            "causal_claim": False,
            "holm_family": "not included; exploratory post-plan module",
            "private_state_root": str(state),
            "public_output_root": str(output),
        }
        common.atomic_json(output / "_SUCCESS.json", finite(success))
        write_report_manifest(output)
        print(
            "KINDNESS_PRICE_ELASTICITY_V102_OK: " + str(output),
            flush=True,
        )
        print(
            "PRIMARY_ELASTICITY "
            f"estimate={primary_interpretation['elasticity_estimate']:.9g} "
            f"ci95=[{primary_interpretation['elasticity_ci95_low']:.9g},"
            f"{primary_interpretation['elasticity_ci95_high']:.9g}]",
            flush=True,
        )
        return output
    except BaseException as error:
        diagnostic = {
            "status": "KINDNESS_PRICE_ELASTICITY_V102_FAILED_CLOSED",
            "created_utc": common.utc_now(),
            "runtime_seconds": time.time() - started,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "traceback": traceback.format_exc(),
            "favorable_null_and_adverse_outputs_retained": True,
            "private_checkpoints_resumable": True,
        }
        common.atomic_json(output / "FAILURE_DIAGNOSTIC.json", diagnostic)
        write_report_manifest(output)
        raise


def run_self_test() -> None:
    common.run_self_test()
    if PRIMARY_MODEL != "X_primary_lpm_log_price_chooser_fe_draw50_fe_adjusted":
        raise RuntimeError("Primary elasticity model label changed")
    if common.EXPECTED_FAIR_ROWS != 17_328_130 or common.EXPECTED_FAIR_KIND_DRAWS != 487_170:
        raise RuntimeError("Certified fair support constants changed")
    if (
        common.EXPECTED_FAIR_CHOOSERS != 2_685_525
        or common.EXPECTED_FIRST12_FAIR_ROWS != 8_575_710
        or common.EXPECTED_FIRST12_FAIR_CHOOSERS != 1_744_924
        or common.EXPECTED_NONPOSITIVE_PRICE_ROWS != 0
    ):
        raise RuntimeError("v1.0.2 recovery support constants changed")
    if len(unavailable_analyses()) != 4:
        raise RuntimeError("Attempted-unestimable disclosure inventory changed")
    print("KINDNESS_PRICE_ELASTICITY_MAIN_SELF_TEST_OK", flush=True)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    if args.self_test:
        run_self_test()
        return
    if not args.execute:
        print("Dry run only. Pass --execute to authenticate data and estimate.")
        return
    execute(args)


if __name__ == "__main__":
    main()
