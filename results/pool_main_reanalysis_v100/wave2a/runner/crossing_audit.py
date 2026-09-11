#!/usr/bin/env python3
"""Rebuild the displayed-gap crossing and decompose the exact-zero payoff mass.

The pre-existing displayed-gap specification is kept separate from the
post-Wave-1 diagnostic decomposition.  Public output is aggregate only; the
temporary caches containing chooser/game keys remain under the private root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterable

import duckdb
import numpy as np
import pandas as pd

from runner import common


VERSION = "1.0.1"
STATUS = "POOL_MAIN_CROSSING_DEFAULT_DECOMPOSITION_V101_OK"
VERIFY_STATUS = "POOL_MAIN_CROSSING_DEFAULT_DECOMPOSITION_V101_VERIFIED_OK"
ZERO_TOLERANCE = 1e-12
LOCAL_BANDWIDTH = 1.0
PROVISIONAL_RD_THRESHOLD = 110.0
REFERENCE_GAP = -1
DISPLAY_GAPS = tuple(range(-12, 13))
MONTHS = tuple(
    f"{year}-{month:02d}"
    for year, values in ((2023, range(11, 13)), (2024, range(1, 13)), (2025, range(1, 11)))
    for month in values
)
POOLS = ("ultrabullet", "bullet", "blitz", "rapid", "classical", "correspondence")

EXPECTED_WAVE1 = {
    "controlled_receipt": {
        "relative": "controlled_reference_model_v110/receipts/completion_receipt.json",
        "sha256": "654a509bb2c5e8025eb58b8bc904ec027ed3d18b08589483ee5dc29a3dbee450",
    },
    "controlled_results": {
        "relative": "controlled_reference_model_v110/tables/controlled_local_h1_results.csv",
        "sha256": "737eaf15822e260e5662373538d822c997c9e69bd00125f642ac20d2dbf57602",
    },
    "stage09_descriptives": {
        "relative": "panel_robustness_stage09/tables/tableR11_exact_zero_payoff_descriptives.csv",
        "sha256": "b721d2ffa3fccb82a40dbf920509e4455adb8b175ac561928fd8136ac43d9008",
    },
    "stage09_models": {
        "relative": "panel_robustness_stage09/tables/tableR12_exact_zero_payoff_models.csv",
        "sha256": "687f859c7c63c44acee20e5ea16f06384a66795f2e63d55e39db3665fa20e77c",
    },
}

REFERENCE_DEMAND_V105_AUTHORITY = {
    "01_run_reference_demand_v105.py": "5a2f822bc01c5ca7da7e5c3ae9724855c3fe10308e50cd3d1c851f4cbf90c1d0",
    "00_run_reference_demand_v104.py": "e0c9cca7d4c53a78f418c0e3a2da70a831c1ad48889e9b1af690b765bf360e1c",
    "reference_demand_v105_contract.json": "cae1359ed8e45b4c8836d169276f56def34145e7d70e1438ee2b840ac70db526",
    "REFERENCE_DEMAND_STAGE_AMENDMENT_v1_0_5.md": "150f69f4011d2eeceb49efc5523edbb0fcccd58689674eb4f880cebf43cc611f",
}

REQUIRED_PANEL_FIELDS = {
    "game_id",
    "chooser_user_id",
    "chooser_username_norm",
    "month",
    "api_speed",
    "outcome_kind_draw",
    "chooser_draw_payoff_v2",
    "chooser_win_payoff_v2",
    "chooser_win_premium_v2",
    "engine_eval_cp_disconnected",
    "chooser_pre_rd_v2",
    "disconnected_pre_rd_v2",
    "chooser_elo",
    "disconnected_elo",
    "ply_count",
    "tournament_like_event",
    "chooser_clock_last_obs_s",
    "disconnected_clock_last_obs_s",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-root", type=Path, required=True)
    parser.add_argument("--wave1-public", type=Path)
    parser.add_argument("--public-root", type=Path, required=True)
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--memory-limit", default="12GB")
    parser.add_argument("--batch-rows", type=int, default=32768)
    parser.add_argument("--synthetic", action="store_true")
    return parser.parse_args()


def source_module(path: Path, name: str) -> Any:
    return common.load_source_module(path, name)


def authenticate_reference_demand_source() -> dict[str, Any]:
    root = common.PACKAGE_ROOT / "source/crossing/reference_demand_v105_authority"
    files: dict[str, Any] = {}
    for name, expected in REFERENCE_DEMAND_V105_AUTHORITY.items():
        path = root / name
        if not path.is_file() or common.sha256_file(path) != expected:
            raise RuntimeError(f"Archived reference-demand v1.0.5 authority changed: {name}")
        files[name] = common.source_record(path, "archived_executed_source_authority")
    return {
        "status": "REFERENCE_DEMAND_V105_EXECUTED_SOURCE_AUTHENTICATED_OK",
        "files": files,
        "panel_a_port": (
            "The adapter ports run_gap_schedule/run_adjacent_gap and stage_controls: "
            "chooser and month fixed effects, chooser-clustered inference, current-state "
            "controls, and the frozen eight ply bands."
        ),
    }


def sql(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def sql_paths(paths: Iterable[Path]) -> str:
    return "[" + ",".join(sql(path) for path in paths) + "]"


def configure(connection: duckdb.DuckDBPyConnection, args: argparse.Namespace, spill: Path) -> None:
    spill.mkdir(parents=True, exist_ok=True)
    connection.execute(f"SET threads={int(args.threads)}")
    connection.execute(f"SET memory_limit={sql(args.memory_limit)}")
    connection.execute(f"SET temp_directory={sql(spill)}")
    connection.execute("SET preserve_insertion_order=false")


def synthetic_auth(root: Path) -> dict[str, Any]:
    paths = sorted(root.glob("*.parquet"))
    if not paths:
        raise RuntimeError(f"Synthetic fixture has no Parquet: {root}")
    return {
        "fingerprint": "synthetic-crossing-v101",
        "panel_root": root,
        "month_records": [
            {
                "month": "synthetic",
                "path": path,
                "rows": int(__import__("pyarrow.parquet", fromlist=["ParquetFile"]).ParquetFile(path).metadata.num_rows),
                "size_bytes": path.stat().st_size,
                "expected_sha256": common.sha256_file(path),
            }
            for path in paths
        ],
        "authority": {
            "rows": sum(
                int(__import__("pyarrow.parquet", fromlist=["ParquetFile"]).ParquetFile(path).metadata.num_rows)
                for path in paths
            ),
            "fair_rows": None,
        },
    }


def compact_lineage(auth: dict[str, Any], synthetic: bool) -> dict[str, Any]:
    if not synthetic:
        return common.compact_sample_lineage(auth)
    return {
        "status": "SYNTHETIC_FIXTURE",
        "fingerprint": auth["fingerprint"],
        "rows": auth["authority"]["rows"],
    }


def authenticate_wave1(wave1: Path | None, synthetic: bool) -> dict[str, Any]:
    if synthetic:
        return {"status": "SYNTHETIC_NOT_APPLICABLE", "exact_zero_rows": None}
    if wave1 is None:
        raise RuntimeError("--wave1-public is required outside --synthetic")
    root = wave1.expanduser().resolve()
    files: dict[str, Any] = {}
    for name, spec in EXPECTED_WAVE1.items():
        path = root / spec["relative"]
        if not path.is_file():
            raise RuntimeError(f"Wave-1 crossing authority is missing: {path}")
        observed = common.sha256_file(path)
        if observed != spec["sha256"]:
            raise RuntimeError(f"Wave-1 crossing authority changed: {name}")
        files[name] = {
            "path": str(path),
            "sha256": observed,
            "bytes": path.stat().st_size,
        }
    receipt = common.load_json(Path(files["controlled_receipt"]["path"]))
    if receipt.get("status") != "CONTROLLED_REFERENCE_PRICE_FIGURE_COMPLETE":
        raise RuntimeError("Wave-1 controlled-model completion status changed")
    stage09 = pd.read_csv(files["stage09_descriptives"]["path"])
    exact = stage09.loc[stage09["payoff_sign"].eq("exact_zero"), "rows"].unique()
    if exact.size != 1:
        raise RuntimeError("Wave-1 Stage-09 exact-zero authority is inconsistent across bandwidths")
    controlled = pd.read_csv(files["controlled_results"]["path"])
    return {
        "status": "POOL_MAIN_WAVE1_CROSSING_AUTHORITIES_AUTHENTICATED_OK",
        "root": str(root),
        "files": files,
        "exact_zero_rows": int(exact[0]),
        "controlled_local_rows": int(receipt["local_model"]["stats"]["n"]),
        "controlled_expected": controlled.to_dict(orient="records"),
    }


def cache_contract(auth: dict[str, Any], synthetic: bool) -> dict[str, Any]:
    return {
        "version": VERSION,
        "sample_fingerprint": auth["fingerprint"],
        "synthetic": synthetic,
        "zero_tolerance": ZERO_TOLERANCE,
        "local_bandwidth": LOCAL_BANDWIDTH,
        "provisional_proxy": f"pre-game RD > {PROVISIONAL_RD_THRESHOLD:g}",
        "sources": [
            {
                "month": row["month"],
                "path": str(row["path"]),
                "rows": int(row["rows"]),
                "bytes": int(row["size_bytes"]),
                "sha256": row.get("expected_sha256"),
            }
            for row in auth["month_records"]
        ],
    }


def exact_zero_breakdown(connection: duckdb.DuckDBPyConnection) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    connection.execute(
        f"""
        CREATE TEMP TABLE exact_zero_rows AS
        SELECT
          chooser,
          kind,
          chooser_rating,
          opponent_rating,
          chooser_rd,
          opponent_rd,
          abs(chooser_rating-1500.0)<1e-12 AS chooser_1500,
          abs(opponent_rating-1500.0)<1e-12 AS opponent_1500,
          chooser_rd>{PROVISIONAL_RD_THRESHOLD} AS chooser_high_rd,
          opponent_rd>{PROVISIONAL_RD_THRESHOLD} AS opponent_high_rd
        FROM base
        WHERE board_eval>=-100
          AND isfinite(r)
          AND abs(r)<{ZERO_TOLERANCE}
          AND isfinite(chooser_rating) AND isfinite(opponent_rating)
          AND isfinite(chooser_rd) AND chooser_rd>0
          AND isfinite(opponent_rd) AND opponent_rd>0
        """
    )
    definitions = {
        "rating_1500_status": [
            ("both_displayed_1500", "chooser_1500 AND opponent_1500"),
            ("exactly_one_displayed_1500", "chooser_1500 <> opponent_1500"),
            ("neither_displayed_1500", "NOT chooser_1500 AND NOT opponent_1500"),
        ],
        "rd_status": [
            ("both_high_rd", "chooser_high_rd AND opponent_high_rd"),
            ("exactly_one_high_rd", "chooser_high_rd <> opponent_high_rd"),
            ("neither_high_rd", "NOT chooser_high_rd AND NOT opponent_high_rd"),
        ],
        "rating_x_rd": [
            ("1500x1500_both_high_rd", "chooser_1500 AND opponent_1500 AND chooser_high_rd AND opponent_high_rd"),
            ("1500x1500_exactly_one_high_rd", "chooser_1500 AND opponent_1500 AND (chooser_high_rd <> opponent_high_rd)"),
            ("1500x1500_neither_high_rd", "chooser_1500 AND opponent_1500 AND NOT chooser_high_rd AND NOT opponent_high_rd"),
            ("other_zero_both_high_rd", "NOT (chooser_1500 AND opponent_1500) AND chooser_high_rd AND opponent_high_rd"),
            ("other_zero_exactly_one_high_rd", "NOT (chooser_1500 AND opponent_1500) AND (chooser_high_rd <> opponent_high_rd)"),
            ("other_zero_neither_high_rd", "NOT (chooser_1500 AND opponent_1500) AND NOT chooser_high_rd AND NOT opponent_high_rd"),
        ],
    }
    total = connection.execute(
        "SELECT COUNT(*), SUM(CAST(kind AS BIGINT)), COUNT(DISTINCT chooser) FROM exact_zero_rows"
    ).fetchone()
    total_rows = int(total[0])
    rows: list[dict[str, Any]] = [
        {
            "dimension": "all",
            "category": "all_exact_zero_fair_rows",
            "rows": total_rows,
            "kind_draws": int(total[1]),
            "chooser_count": int(total[2]),
            "kind_rate_pct": 100.0 * float(total[1]) / total_rows,
            "share_of_exact_zero_pct": 100.0,
        }
    ]
    for dimension, categories in definitions.items():
        for category, condition in categories:
            value = connection.execute(
                f"SELECT COUNT(*), SUM(CAST(kind AS BIGINT)), COUNT(DISTINCT chooser) "
                f"FROM exact_zero_rows WHERE {condition}"
            ).fetchone()
            n = int(value[0])
            kinds = int(value[1] or 0)
            rows.append(
                {
                    "dimension": dimension,
                    "category": category,
                    "rows": n,
                    "kind_draws": kinds,
                    "chooser_count": int(value[2]),
                    "kind_rate_pct": 100.0 * kinds / n if n else None,
                    "share_of_exact_zero_pct": 100.0 * n / total_rows if total_rows else None,
                }
            )
    identity = connection.execute(
        f"""
        SELECT
          COUNT(*) FILTER (WHERE board_eval>=-100 AND abs(r)<{ZERO_TOLERANCE}),
          COUNT(*) FILTER (WHERE board_eval>=-100 AND abs(opponent_rating-chooser_rating)<1e-12),
          COUNT(*) FILTER (
            WHERE board_eval>=-100
              AND ((abs(r)<{ZERO_TOLERANCE}) <> (abs(opponent_rating-chooser_rating)<1e-12))
          ),
          COUNT(*) FILTER (WHERE board_eval>=-100 AND r=0),
          COUNT(*) FILTER (WHERE board_eval>=-100 AND abs(r)<{ZERO_TOLERANCE} AND r<>0)
        FROM base
        """
    ).fetchone()
    qa = {
        "exact_zero_tolerance_rows": int(identity[0]),
        "displayed_equal_rating_rows": int(identity[1]),
        "payoff_zero_displayed_equality_disagreements": int(identity[2]),
        "literal_r_equals_zero_rows": int(identity[3]),
        "tolerance_zero_but_not_literal_zero_rows": int(identity[4]),
    }
    return rows, qa


def build_caches(
    args: argparse.Namespace,
    auth: dict[str, Any],
    wave1: dict[str, Any],
) -> tuple[Path, Path, dict[str, Any]]:
    private = args.private_root.resolve()
    private.mkdir(parents=True, exist_ok=True)
    controlled_cache = private / "controlled_local_h1_crossing_private.parquet"
    adjacent_cache = private / "displayed_gap_m12_p12_private.parquet"
    receipt_path = private / "cache_receipt.json"
    contract_path = private / "cache_contract.json"
    contract = cache_contract(auth, args.synthetic)
    if all(path.is_file() for path in (controlled_cache, adjacent_cache, receipt_path, contract_path)):
        if common.load_json(contract_path) != contract:
            raise RuntimeError("Crossing private-cache contract changed; use a fresh private root")
        receipt = common.load_json(receipt_path)
        for name, path in (("controlled", controlled_cache), ("adjacent", adjacent_cache)):
            spec = receipt["caches"][name]
            if path.stat().st_size != int(spec["bytes"]) or common.sha256_file(path) != spec["sha256"]:
                raise RuntimeError(f"Crossing private cache changed: {name}")
        return controlled_cache, adjacent_cache, receipt
    if any(path.exists() for path in (controlled_cache, adjacent_cache, receipt_path, contract_path)):
        raise RuntimeError("Partial crossing private cache exists; remove only this stage root and rerun")

    source = sql_paths([Path(row["path"]) for row in auth["month_records"]])
    connection = duckdb.connect()
    configure(connection, args, private / "duckdb_spill")
    schema = set(
        connection.execute(f"DESCRIBE SELECT * FROM read_parquet({source}, union_by_name=true)")
        .fetchdf()["column_name"]
        .astype(str)
    )
    missing = sorted(REQUIRED_PANEL_FIELDS - schema)
    if missing:
        raise RuntimeError(f"Selected panel lacks crossing fields: {missing}")
    connection.execute(f"CREATE VIEW source_panel AS SELECT * FROM read_parquet({source}, union_by_name=true)")
    pool_case = "CASE lower(cast(api_speed AS VARCHAR)) " + " ".join(
        f"WHEN {sql(value)} THEN {index}" for index, value in enumerate(POOLS)
    ) + " ELSE -1 END"
    month_case = "CASE cast(month AS VARCHAR) " + " ".join(
        f"WHEN {sql(value)} THEN {index}" for index, value in enumerate(MONTHS)
    ) + (" ELSE 0 END" if args.synthetic else " ELSE -1 END")
    connection.execute(
        f"""
        CREATE VIEW base AS
        SELECT
          cast(game_id AS VARCHAR) AS game_id,
          cast(chooser_user_id AS VARCHAR) AS chooser,
          cast(chooser_username_norm AS VARCHAR) AS chooser_name,
          {pool_case} AS pool_code,
          {month_case} AS month_code,
          cast(outcome_kind_draw AS DOUBLE) AS kind,
          cast(outcome_kind_draw AS DOUBLE)*100.0 AS y,
          cast(chooser_draw_payoff_v2 AS DOUBLE) AS r,
          cast(chooser_win_premium_v2 AS DOUBLE) AS kappa,
          cast(chooser_win_payoff_v2 AS DOUBLE) AS claim_payoff,
          cast(engine_eval_cp_disconnected AS DOUBLE) AS board_eval,
          cast(chooser_pre_rd_v2 AS DOUBLE) AS chooser_rd,
          cast(disconnected_pre_rd_v2 AS DOUBLE) AS opponent_rd,
          cast(chooser_elo AS DOUBLE) AS chooser_rating,
          cast(disconnected_elo AS DOUBLE) AS opponent_rating,
          cast(disconnected_elo AS DOUBLE)-cast(chooser_elo AS DOUBLE) AS gap,
          cast(ply_count AS DOUBLE) AS ply,
          cast(tournament_like_event AS DOUBLE) AS tournament,
          cast(chooser_clock_last_obs_s AS DOUBLE) AS chooser_clock,
          cast(disconnected_clock_last_obs_s AS DOUBLE) AS opponent_clock
        FROM source_panel
        """
    )
    rows, zero_qa = exact_zero_breakdown(connection)
    if not args.synthetic and int(zero_qa["exact_zero_tolerance_rows"]) != int(wave1["exact_zero_rows"]):
        raise RuntimeError("Exact-zero count does not reproduce authenticated Wave 1")
    if zero_qa["payoff_zero_displayed_equality_disagreements"] != 0:
        raise RuntimeError("Payoff zero and displayed equality no longer coincide in the selected fair sample")
    if zero_qa["tolerance_zero_but_not_literal_zero_rows"] != 0:
        raise RuntimeError("Tolerance-zero and literal-zero definitions differ")

    common_filter = " AND ".join(
        (
            "chooser IS NOT NULL",
            "trim(chooser)<>''",
            "kind IN (0,1)",
            "isfinite(r)",
            "isfinite(kappa)",
            "kappa>0",
            "isfinite(claim_payoff)",
            "abs(claim_payoff-r-kappa)<=1e-6",
            "abs(r)<=kappa+1e-6",
            "isfinite(board_eval)",
            "board_eval>=-100",
            "isfinite(gap)",
            "isfinite(ply)",
            "ply>=0",
            "isfinite(chooser_rd)",
            "chooser_rd>0",
            "isfinite(opponent_rd)",
            "opponent_rd>0",
            "isfinite(chooser_rating)",
            "isfinite(opponent_rating)",
            "isfinite(tournament)",
            "tournament IN (0,1)",
            "pool_code>=0",
            "month_code>=0",
        )
    )
    controlled_tmp = controlled_cache.with_suffix(".parquet.tmp")
    adjacent_tmp = adjacent_cache.with_suffix(".parquet.tmp")
    for path in (controlled_tmp, adjacent_tmp):
        if path.exists():
            path.unlink()
    print("CROSSING_CACHE_BUILD controlled local h=1", flush=True)
    connection.execute(
        f"""
        COPY (
          WITH eligible AS (
            SELECT *,
              abs(chooser_rating-1500.0)<1e-12 AS chooser_1500,
              abs(opponent_rating-1500.0)<1e-12 AS opponent_1500,
              chooser_rd>{PROVISIONAL_RD_THRESHOLD} AS chooser_high_rd,
              opponent_rd>{PROVISIONAL_RD_THRESHOLD} AS opponent_high_rd
            FROM base
            WHERE {common_filter} AND abs(r)<{LOCAL_BANDWIDTH}
          ), supported AS (
            SELECT *, count(*) OVER (PARTITION BY chooser,pool_code) AS local_fe_n
            FROM eligible
          )
          SELECT * FROM supported WHERE local_fe_n>=2
          ORDER BY chooser,pool_code
        ) TO {sql(controlled_tmp)}
        (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 65536)
        """
    )
    os.replace(controlled_tmp, controlled_cache)
    print("CROSSING_CACHE_BUILD displayed gaps -12...+12", flush=True)
    connection.execute(
        f"""
        COPY (
          SELECT
            game_id,
            chooser_name AS chooser,
            month_code,
            kind,
            cast(round(gap) AS INTEGER) AS displayed_gap,
            board_eval AS engine_eval_cp,
            CASE WHEN chooser_clock IS NULL OR NOT isfinite(chooser_clock) OR chooser_clock<0
                 THEN NULL ELSE ln(1+chooser_clock) END AS log_chooser_clock,
            CASE WHEN opponent_clock IS NULL OR NOT isfinite(opponent_clock) OR opponent_clock<0
                 THEN NULL ELSE ln(1+opponent_clock) END AS log_opponent_clock,
            tournament,
            pool_code AS speed_code,
            ply,
            chooser_rating,
            opponent_rating,
            chooser_rd,
            opponent_rd,
            abs(chooser_rating-1500.0)<1e-12 AS chooser_1500,
            abs(opponent_rating-1500.0)<1e-12 AS opponent_1500,
            chooser_rd>{PROVISIONAL_RD_THRESHOLD} AS chooser_high_rd,
            opponent_rd>{PROVISIONAL_RD_THRESHOLD} AS opponent_high_rd
          FROM base
          WHERE board_eval>=-100
            AND chooser_name IS NOT NULL AND trim(chooser_name)<>''
            AND kind IN (0,1)
            AND isfinite(gap) AND abs(gap-round(gap))<1e-12
            AND round(gap) BETWEEN -12 AND 12
            AND isfinite(board_eval)
            AND isfinite(ply) AND ply>=0
            AND isfinite(chooser_rating) AND isfinite(opponent_rating)
            AND isfinite(chooser_rd) AND chooser_rd>0
            AND isfinite(opponent_rd) AND opponent_rd>0
            AND isfinite(tournament) AND tournament IN (0,1)
            AND pool_code>=0 AND month_code>=0
          ORDER BY displayed_gap,chooser,month_code,game_id
        ) TO {sql(adjacent_tmp)}
        (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 65536)
        """
    )
    os.replace(adjacent_tmp, adjacent_cache)
    controlled_stats = connection.execute(
        f"SELECT COUNT(*), SUM(y)/100.0, COUNT(DISTINCT chooser), "
        f"COUNT(DISTINCT (chooser,pool_code)) FROM read_parquet({sql(controlled_cache)})"
    ).fetchone()
    adjacent_stats = connection.execute(
        f"SELECT COUNT(*), SUM(CAST(kind AS BIGINT)), COUNT(DISTINCT chooser) "
        f"FROM read_parquet({sql(adjacent_cache)})"
    ).fetchone()
    connection.close()
    shutil.rmtree(private / "duckdb_spill", ignore_errors=True)
    receipt = {
        "status": "POOL_MAIN_CROSSING_PRIVATE_CACHES_OK",
        "created_at_utc": common.utc_now(),
        "sample_fingerprint": auth["fingerprint"],
        "exact_zero_breakdown": rows,
        "zero_identity_qa": zero_qa,
        "caches": {
            "controlled": {
                "path": str(controlled_cache),
                "bytes": controlled_cache.stat().st_size,
                "sha256": common.sha256_file(controlled_cache),
                "rows": int(controlled_stats[0]),
                "kind_draws": int(controlled_stats[1]),
                "choosers": int(controlled_stats[2]),
                "chooser_pool_cells": int(controlled_stats[3]),
            },
            "adjacent": {
                "path": str(adjacent_cache),
                "bytes": adjacent_cache.stat().st_size,
                "sha256": common.sha256_file(adjacent_cache),
                "rows": int(adjacent_stats[0]),
                "kind_draws": int(adjacent_stats[1]),
                "choosers": int(adjacent_stats[2]),
            },
        },
        "privacy": "PRIVATE ROW-LEVEL CACHES; EXCLUDE FROM TRANSFER",
    }
    common.atomic_json(contract_path, contract)
    common.atomic_json(receipt_path, receipt)
    return controlled_cache, adjacent_cache, receipt


def standardize(values: np.ndarray) -> tuple[np.ndarray, np.ndarray | None]:
    raw = np.asarray(values, dtype=np.float64)
    observed = raw[np.isfinite(raw)]
    if observed.size == 0:
        raise RuntimeError("Control contains no observed values")
    missing = ~np.isfinite(raw)
    filled = raw.copy()
    filled[missing] = float(np.median(observed))
    scale = float(np.std(filled))
    if not math.isfinite(scale) or scale <= 1e-12:
        return np.zeros_like(filled), missing.astype(float) if np.any(missing) else None
    return (filled - float(np.mean(filled))) / scale, missing.astype(float) if np.any(missing) else None


def add_dummies(regressors: dict[str, np.ndarray], values: np.ndarray, prefix: str) -> None:
    levels = sorted(int(value) for value in np.unique(values))
    for level in levels[1:]:
        regressors[f"{prefix}_{level}"] = (values == level).astype(float)


def adjacent_controls(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    controls: dict[str, np.ndarray] = {}
    evaluation, _ = standardize(frame["engine_eval_cp"].to_numpy(float))
    controls["z_engine_eval_cp"] = evaluation
    controls["z_engine_eval_cp_sq"] = evaluation * evaluation
    chooser_clock, chooser_missing = standardize(frame["log_chooser_clock"].to_numpy(float))
    opponent_clock, opponent_missing = standardize(frame["log_opponent_clock"].to_numpy(float))
    controls["z_chooser_clock"] = chooser_clock
    controls["z_opponent_clock"] = opponent_clock
    if chooser_missing is not None:
        controls["chooser_clock_missing"] = chooser_missing
    if opponent_missing is not None:
        controls["opponent_clock_missing"] = opponent_missing
    controls["tournament"] = frame["tournament"].to_numpy(float)
    add_dummies(controls, frame["speed_code"].to_numpy(np.int64), "speed")
    ply_band = np.searchsorted(
        np.asarray([4, 6, 8, 10, 20, 40, 80]),
        frame["ply"].to_numpy(float),
        side="left",
    )
    add_dummies(controls, ply_band, "ply_band")
    return controls


def subset_sql(name: str) -> str:
    if name == "all":
        return "TRUE"
    if name == "exclude_both_1500":
        return "NOT (chooser_1500 AND opponent_1500)"
    if name == "both_established_nondefault":
        return (
            "NOT chooser_high_rd AND NOT opponent_high_rd "
            "AND NOT (chooser_1500 AND opponent_1500)"
        )
    raise ValueError(name)


def read_adjacent(
    cache: Path,
    gaps: tuple[int, ...],
    *,
    scope: str,
    subset: str,
) -> pd.DataFrame:
    gap_list = ",".join(str(int(value)) for value in gaps)
    scope_condition = "TRUE" if scope == "all" else "ply>10"
    connection = duckdb.connect()
    frame = connection.execute(
        f"SELECT * FROM read_parquet({sql(cache)}) "
        f"WHERE displayed_gap IN ({gap_list}) AND {scope_condition} AND {subset_sql(subset)}"
    ).fetchdf()
    connection.close()
    if len(frame) < 1_000:
        raise RuntimeError(f"Adjacent sample too small: gaps={gaps} scope={scope} subset={subset}")
    chooser_codes, _ = pd.factorize(frame["chooser"].astype(str), sort=True)
    frame["chooser_index"] = chooser_codes.astype(np.int64)
    frame["row_id"] = np.arange(len(frame), dtype=np.int64)
    return frame


def fit_adjacent(
    fit_common: Any,
    frame: pd.DataFrame,
    *,
    model: str,
    exposures: dict[str, np.ndarray],
    scope: str,
    subset: str,
) -> dict[str, Any]:
    regressors = dict(exposures)
    regressors.update(adjacent_controls(frame))
    return fit_common.fit_lpm_cluster(
        outcome=frame["kind"].to_numpy(float),
        regressors=regressors,
        clusters=frame["chooser_index"].to_numpy(np.int64),
        fixed_effects=(
            frame["chooser_index"].to_numpy(np.int64),
            frame["month_code"].to_numpy(np.int64),
        ),
        exposure_names=tuple(exposures),
        row_ids=frame["row_id"].to_numpy(np.int64),
        specification={
            "model": model,
            "analysis_role": "pre_existing_manuscript_specification_rebuild",
            "epistemic_label": "R",
            "scope": scope,
            "subset": subset,
            "outcome": "kind draw indicator",
            "fixed_effects": "chooser and month",
            "controls": "current engine state, clocks, tournament, speed, and eight ply bands",
            "cluster": "chooser",
            "causal": False,
        },
    )


def checkpoint(
    path: Path,
    contract_sha: str,
    producer: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    if path.is_file():
        saved = common.load_json(path)
        if saved.get("contract_sha256") != contract_sha:
            raise RuntimeError(f"Model checkpoint contract changed: {path.name}")
        return saved["result"]
    result = clean_json(producer())
    common.atomic_json(
        path,
        {
            "status": "POOL_MAIN_CROSSING_MODEL_CHECKPOINT_OK",
            "created_at_utc": common.utc_now(),
            "contract_sha256": contract_sha,
            "result": result,
        },
    )
    return result


def clean_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): clean_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def term(result: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [row for row in result["terms"] if row["term"] == name]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one term {name} in {result['model']}")
    return dict(matches[0])


def holm_adjust(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    adjusted = [0.0] * len(values)
    running = 0.0
    total = len(values)
    for rank, index in enumerate(order):
        running = max(running, (total - rank) * float(values[index]))
        adjusted[index] = min(1.0, running)
    return adjusted


def run_adjacent_models(
    args: argparse.Namespace,
    cache: Path,
    contract_sha: str,
    checkpoints: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    fit_common = source_module(
        common.PACKAGE_ROOT / "source/crossing/kindness_price_elasticity_common_v102.py",
        "wave2a_crossing_fit_common",
    )
    schedule: list[dict[str, Any]] = []
    pvalues: list[float] = []
    test_positions: list[int] = []
    reference_frame = read_adjacent(cache, (REFERENCE_GAP,), scope="all", subset="all")
    schedule.append(
        {
            "scope": "all",
            "displayed_gap": REFERENCE_GAP,
            "reference_gap": REFERENCE_GAP,
            "estimate_pp": 0.0,
            "se_pp": None,
            "t": None,
            "p_value_two_sided": None,
            "p_value_holm_24": None,
            "target_rows": len(reference_frame),
            "reference_rows": len(reference_frame),
            "rows": len(reference_frame),
            "chooser_clusters": int(reference_frame["chooser_index"].nunique()),
            "analysis_role": "omitted reference",
        }
    )
    del reference_frame
    for gap in DISPLAY_GAPS:
        if gap == REFERENCE_GAP:
            continue
        name = f"pairwise_gap_{gap:+d}_vs_m1_all".replace("+", "p").replace("-", "m")
        path = checkpoints / f"{name}.json"

        def produce(gap_value: int = gap, model_name: str = name) -> dict[str, Any]:
            print(f"CROSSING_MODEL_BEGIN {model_name}", flush=True)
            frame = read_adjacent(cache, (REFERENCE_GAP, gap_value), scope="all", subset="all")
            exposure = (frame["displayed_gap"].to_numpy(int) == gap_value).astype(float)
            result = fit_adjacent(
                fit_common,
                frame,
                model=model_name,
                exposures={"target_gap": exposure},
                scope="all",
                subset="all",
            )
            counts = frame.groupby("displayed_gap").size().to_dict()
            result["target_rows"] = int(counts[gap_value])
            result["reference_rows"] = int(counts[REFERENCE_GAP])
            print(f"CROSSING_MODEL_OK {model_name}", flush=True)
            return result

        result = checkpoint(path, contract_sha, produce)
        coefficient = term(result, "target_gap")
        schedule.append(
            {
                "scope": "all",
                "displayed_gap": gap,
                "reference_gap": REFERENCE_GAP,
                "estimate_pp": coefficient["coefficient_percentage_points"],
                "se_pp": coefficient["standard_error_percentage_points"],
                "t": coefficient["t_cluster"],
                "p_value_two_sided": coefficient["p_value_two_sided"],
                "p_value_holm_24": None,
                "target_rows": result["target_rows"],
                "reference_rows": result["reference_rows"],
                "rows": result["rows_raw"],
                "chooser_clusters": result["chooser_clusters"],
                "analysis_role": "pre-existing separate two-gap comparison",
            }
        )
        test_positions.append(len(schedule) - 1)
        pvalues.append(float(coefficient["p_value_two_sided"]))
    for position, adjusted in zip(test_positions, holm_adjust(pvalues), strict=True):
        schedule[position]["p_value_holm_24"] = adjusted
    schedule.sort(key=lambda row: int(row["displayed_gap"]))

    joint_rows: list[dict[str, Any]] = []
    model_receipts: list[dict[str, Any]] = []
    for subset in ("all", "exclude_both_1500", "both_established_nondefault"):
        for scope in ("all", "long_ply_gt_10"):
            name = f"joint_gap_m1_0_p1__{scope}__{subset}"
            path = checkpoints / f"{name}.json"

            def produce_joint(model_name: str = name, model_scope: str = scope, model_subset: str = subset) -> dict[str, Any]:
                print(f"CROSSING_MODEL_BEGIN {model_name}", flush=True)
                frame = read_adjacent(
                    cache,
                    (-1, 0, 1),
                    scope=model_scope,
                    subset=model_subset,
                )
                gap = frame["displayed_gap"].to_numpy(int)
                result = fit_adjacent(
                    fit_common,
                    frame,
                    model=model_name,
                    exposures={
                        "gap_0_minus_gap_m1": (gap == 0).astype(float),
                        "gap_p1_minus_gap_m1": (gap == 1).astype(float),
                    },
                    scope=model_scope,
                    subset=model_subset,
                )
                result["gap_counts"] = {str(k): int(v) for k, v in frame.groupby("displayed_gap").size().to_dict().items()}
                print(f"CROSSING_MODEL_OK {model_name}", flush=True)
                return result

            result = checkpoint(path, contract_sha, produce_joint)
            model_receipts.append(
                {
                    "model": result["model"],
                    "scope": scope,
                    "subset": subset,
                    "rows": result["rows_raw"],
                    "chooser_clusters": result["chooser_clusters"],
                    "matrix_rank": result["matrix_rank"],
                    "absorption_method": result["absorption_method"],
                    "gap_m1_rows": result["gap_counts"]["-1"],
                    "gap_0_rows": result["gap_counts"]["0"],
                    "gap_p1_rows": result["gap_counts"]["1"],
                }
            )
            for term_name in ("gap_0_minus_gap_m1", "gap_p1_minus_gap_m1"):
                value = term(result, term_name)
                joint_rows.append(
                    {
                        "model": result["model"],
                        "scope": scope,
                        "subset": subset,
                        "term": term_name,
                        "estimate_pp": value["coefficient_percentage_points"],
                        "se_pp": value["standard_error_percentage_points"],
                        "t": value["t_cluster"],
                        "p_value_two_sided": value["p_value_two_sided"],
                        "rows": result["rows_raw"],
                        "chooser_clusters": result["chooser_clusters"],
                        "causal": False,
                    }
                )
    return schedule, joint_rows, model_receipts


def subset_factory(
    reference: Any,
    cache: Path,
    batch_rows: int,
    memory: str,
    spill: Path,
    subset: str,
) -> Callable[[], Any]:
    base = reference.frame_factory(cache, batch_rows, memory, spill)

    def factory() -> Any:
        for frame in base():
            if subset == "all":
                filtered = frame
            elif subset == "exclude_both_1500":
                filtered = frame.loc[~(frame["chooser_1500"] & frame["opponent_1500"])].copy()
            elif subset == "both_established_nondefault":
                filtered = frame.loc[
                    ~(frame["chooser_high_rd"] | frame["opponent_high_rd"])
                    & ~(frame["chooser_1500"] & frame["opponent_1500"])
                ].copy()
            else:
                raise ValueError(subset)
            if filtered.empty:
                continue
            counts = filtered.groupby(["chooser", "pool_code"], sort=False)["chooser"].transform("size")
            filtered = filtered.loc[counts.ge(2)].reset_index(drop=True)
            if not filtered.empty:
                yield filtered

    return factory


def make_split_tie_design(reference: Any, frame: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    r = frame["r"].to_numpy(float)
    zero = r == 0
    both_1500 = frame["chooser_1500"].to_numpy(bool) & frame["opponent_1500"].to_numpy(bool)
    any_high = frame["chooser_high_rd"].to_numpy(bool) | frame["opponent_high_rd"].to_numpy(bool)
    columns: list[np.ndarray] = [
        r * (r < 0),
        r * (r > 0),
        (r > 0).astype(float),
        (zero & both_1500 & any_high).astype(float),
        (zero & both_1500 & ~any_high).astype(float),
        (zero & ~both_1500).astype(float),
    ]
    names = [
        "left",
        "right",
        "jump",
        "tie_1500_any_high_rd",
        "tie_1500_neither_high_rd",
        "tie_non1500",
    ]
    controls, control_names = reference.control_design(frame)
    columns.extend(controls)
    names.extend(control_names)
    return np.column_stack(columns), names


def contrast_row(
    reference: Any,
    model: dict[str, Any],
    specification: str,
    estimand: str,
    weights: dict[str, float],
) -> dict[str, Any]:
    value = reference.contrast(model, weights)
    return {
        "specification": specification,
        "estimand": estimand,
        "estimate_pp": value["estimate"],
        "se_pp": value["se"],
        "t": value["t"],
        "p_value_two_sided": value["p"],
        "ci95_low_pp": value["ci95_low"],
        "ci95_high_pp": value["ci95_high"],
        "rows": int(model["stats"]["n"]),
        "chooser_pool_fixed_effects": int(model["stats"]["n_fe"]),
        "chooser_clusters": int(model["stats"]["clusters"]),
        "causal": False,
    }


def summarize_controlled(reference: Any, model: dict[str, Any], specification: str) -> dict[str, Any]:
    names = set(model["names"])
    contrasts = [
        contrast_row(reference, model, specification, "loss_side_slope", {"left": 1.0}),
        contrast_row(reference, model, specification, "gain_side_slope", {"right": 1.0}),
        contrast_row(reference, model, specification, "loss_minus_gain_slope", {"left": 1.0, "right": -1.0}),
        contrast_row(reference, model, specification, "right_minus_left_level", {"jump": 1.0}),
    ]
    tie_terms = [name for name in model["names"] if name == "tie" or name.startswith("tie_")]
    for tie_name in tie_terms:
        label = tie_name.removeprefix("tie_") if tie_name != "tie" else "exact_zero"
        contrasts.extend(
            [
                contrast_row(reference, model, specification, f"{label}_minus_left_limit", {tie_name: 1.0}),
                contrast_row(reference, model, specification, f"{label}_minus_right_limit", {tie_name: 1.0, "jump": -1.0}),
            ]
        )
    if {"tie_1500_any_high_rd", "tie_non1500"}.issubset(names):
        contrasts.append(
            contrast_row(
                reference,
                model,
                specification,
                "1500_any_high_rd_minus_non1500_exact_zero",
                {"tie_1500_any_high_rd": 1.0, "tie_non1500": -1.0},
            )
        )
    if {"tie_1500_neither_high_rd", "tie_non1500"}.issubset(names):
        contrasts.append(
            contrast_row(
                reference,
                model,
                specification,
                "1500_neither_high_rd_minus_non1500_exact_zero",
                {"tie_1500_neither_high_rd": 1.0, "tie_non1500": -1.0},
            )
        )
    coefficients = []
    for row in reference.coefficient_table(model).to_dict(orient="records"):
        if row["term"] in {"left", "right", "jump", *tie_terms}:
            coefficients.append({"specification": specification, **row})
    return {
        "specification": specification,
        "contrasts": contrasts,
        "coefficients": coefficients,
        "model": {
            "rows": int(model["stats"]["n"]),
            "chooser_pool_fixed_effects": int(model["stats"]["n_fe"]),
            "chooser_clusters": int(model["stats"]["clusters"]),
            "kind_draws": int(round(float(model["stats"]["kinds"]))),
            "condition": float(model["condition"]),
            "dropped_terms": list(model["dropped"]),
        },
    }


def run_controlled_models(
    args: argparse.Namespace,
    cache: Path,
    wave1: dict[str, Any],
    contract_sha: str,
    checkpoints: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    reference = source_module(
        common.PACKAGE_ROOT / "source/crossing/reference_price_model_v110.py",
        "wave2a_crossing_controlled_reference",
    )
    outputs: list[dict[str, Any]] = []
    specifications = (
        ("baseline_all", "all", reference.make_local_design, ("left", "right", "jump", "tie")),
        (
            "split_exact_zero_1500_rd",
            "all",
            lambda frame: make_split_tie_design(reference, frame),
            ("left", "right", "jump", "tie_1500_any_high_rd", "tie_1500_neither_high_rd", "tie_non1500"),
        ),
        ("exclude_both_1500", "exclude_both_1500", reference.make_local_design, ("left", "right", "jump", "tie")),
        (
            "both_established_nondefault",
            "both_established_nondefault",
            reference.make_local_design,
            ("left", "right", "jump", "tie"),
        ),
    )
    for specification, subset, design, required in specifications:
        path = checkpoints / f"controlled_{specification}.json"

        def produce(
            current_spec: str = specification,
            current_subset: str = subset,
            current_design: Callable[[pd.DataFrame], tuple[np.ndarray, list[str]]] = design,
            current_required: tuple[str, ...] = required,
        ) -> dict[str, Any]:
            print(f"CROSSING_CONTROLLED_BEGIN {current_spec}", flush=True)
            factory = subset_factory(
                reference,
                cache,
                args.batch_rows,
                args.memory_limit,
                args.private_root / f"model_spill/{current_spec}",
                current_subset,
            )
            model = reference.fit_within_model(
                factory,
                current_design,
                lambda names: list(current_required),
                f"pool_main_crossing_{current_spec}",
                must_retain_names=None if args.synthetic else reference.CORE_CONTROLS_REQUIRED,
            )
            saved = summarize_controlled(reference, model, current_spec)
            print(f"CROSSING_CONTROLLED_OK {current_spec}", flush=True)
            return saved

        outputs.append(checkpoint(path, contract_sha, produce))
    contrasts = [row for output in outputs for row in output["contrasts"]]
    coefficients = [row for output in outputs for row in output["coefficients"]]
    models = [
        {"specification": output["specification"], **output["model"]} for output in outputs
    ]
    if args.synthetic:
        reproduction = {"status": "SYNTHETIC_NOT_APPLICABLE"}
    else:
        expected = {row["estimand"]: row for row in wave1["controlled_expected"]}
        observed = {
            row["estimand"]: row
            for row in contrasts
            if row["specification"] == "baseline_all"
        }
        failures = []
        for estimand, prior in expected.items():
            if estimand not in observed:
                failures.append(f"missing:{estimand}")
                continue
            current = observed[estimand]
            if abs(float(current["estimate_pp"]) - float(prior["estimate"])) > 1e-7:
                failures.append(f"estimate:{estimand}")
            if abs(float(current["se_pp"]) - float(prior["se"])) > 1e-7:
                failures.append(f"se:{estimand}")
        if failures:
            raise RuntimeError(f"Controlled local baseline failed Wave-1 reproduction: {failures}")
        reproduction = {
            "status": "WAVE1_CONTROLLED_LOCAL_BASELINE_EXACTLY_REPRODUCED_WITHIN_1E_7_PP",
            "estimands": len(expected),
            "failures": 0,
        }
    return contrasts, coefficients, models, reproduction


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    pd.DataFrame(rows).to_csv(temporary, index=False, lineterminator="\n", float_format="%.15g")
    os.replace(temporary, path)


def run(args: argparse.Namespace) -> dict[str, Any]:
    if not 1 <= args.threads <= 10:
        raise SystemExit("--threads must be between 1 and 10")
    if args.batch_rows < 4096:
        raise SystemExit("--batch-rows must be at least 4096")
    started = time.monotonic()
    public = args.public_root.expanduser().resolve()
    private = args.private_root.expanduser().resolve()
    public.mkdir(parents=True, exist_ok=True)
    private.mkdir(parents=True, exist_ok=True)
    reference_demand_source = authenticate_reference_demand_source()
    checkpoints = private / "model_checkpoints"
    checkpoints.mkdir(parents=True, exist_ok=True)
    auth = synthetic_auth(args.sample_root.resolve()) if args.synthetic else common.authenticate_sample(args.sample_root, verify_hashes=False)
    wave1 = authenticate_wave1(args.wave1_public, args.synthetic)
    contract = cache_contract(auth, args.synthetic)
    contract_sha = hashlib.sha256(common.canonical_json(contract).encode("utf-8")).hexdigest()
    controlled_cache, adjacent_cache, cache_receipt = build_caches(args, auth, wave1)
    schedule, joint, adjacent_receipts = run_adjacent_models(
        args, adjacent_cache, contract_sha, checkpoints
    )
    contrasts, coefficients, controlled_receipts, reproduction = run_controlled_models(
        args, controlled_cache, wave1, contract_sha, checkpoints
    )
    tables = public / "tables"
    receipts = public / "receipts"
    write_csv(tables / "exact_zero_1500_rd_decomposition.csv", cache_receipt["exact_zero_breakdown"])
    write_csv(tables / "displayed_gap_m12_p12_schedule.csv", schedule)
    write_csv(tables / "joint_adjacent_gap_models.csv", joint)
    write_csv(tables / "controlled_local_crossing_contrasts.csv", contrasts)
    write_csv(tables / "controlled_local_crossing_coefficients.csv", coefficients)
    write_csv(tables / "model_support.csv", [*adjacent_receipts, *controlled_receipts])
    receipts.mkdir(parents=True, exist_ok=True)
    common.atomic_json(
        receipts / "input_authorities.json",
        {
            "status": "POOL_MAIN_CROSSING_INPUT_AUTHORITIES_OK",
            "sample_authority": compact_lineage(auth, args.synthetic),
            "wave1": wave1,
            "cache_contract_sha256": contract_sha,
            "source": {
                "controlled_model_v110": common.source_record(
                    common.PACKAGE_ROOT / "source/crossing/reference_price_model_v110.py",
                    "authenticated Wave-1 controlled local estimator",
                ),
                "two_way_fit_v102": common.source_record(
                    common.PACKAGE_ROOT / "source/crossing/kindness_price_elasticity_common_v102.py",
                    "public exact two-way FE and chooser-clustered estimator",
                ),
                "reference_demand_v105_executed_authority": reference_demand_source,
                "adapter": common.source_record(Path(__file__), "pool-main crossing adapter"),
            },
        },
    )
    common.atomic_json(
        public / "INTERPRETATION_GATE.json",
        {
            "status": "POOL_MAIN_CROSSING_MANUSCRIPT_REVIEW_REQUIRED",
            "sample_fingerprint": auth["fingerprint"],
            "pre_existing_estimand": (
                "Displayed rating gap -12...+12 versus -1 and joint -1/0/+1 models; "
                "this directly rebuilds manuscript Figure 2 Panel A and the no-kink "
                "table's Panel A."
            ),
            "post_wave1_diagnostic": (
                "The 1500/high-RD decomposition and restricted controlled models were added "
                "after observing Wave-1 step/spike results; they are diagnostic and exploratory."
            ),
            "estimand_guardrail": (
                "Displayed rating equality and reconstructed draw-payoff zero coincide rowwise "
                "in this panel, but the adjacent-gap and controlled side-limit models remain "
                "different conditional estimands."
            ),
            "manuscript_authorization": (
                "No automatic levels-flat or tie-specific-effect sentence is authorized. "
                "Review estimates and confidence intervals after authenticated return."
            ),
            "provisional_measurement": (
                f"The certified panel has no historical API provisional boolean. High RD is "
                f"defined transparently as pre-game RD > {PROVISIONAL_RD_THRESHOLD:g}; "
                "1500 is never treated as synonymous with provisional status."
            ),
            "causal_claims_authorized": False,
        },
    )
    success = {
        "status": STATUS,
        "version": VERSION,
        "created_at_utc": common.utc_now(),
        "runtime_seconds": round(time.monotonic() - started, 3),
        "synthetic": args.synthetic,
        "sample_authority": compact_lineage(auth, args.synthetic),
        "wave1_authority_status": wave1["status"],
        "zero_identity_qa": cache_receipt["zero_identity_qa"],
        "controlled_baseline_reproduction": reproduction,
        "outputs": {
            "displayed_gap_schedule_rows": len(schedule),
            "joint_adjacent_terms": len(joint),
            "controlled_contrasts": len(contrasts),
            "exact_zero_decomposition_rows": len(cache_receipt["exact_zero_breakdown"]),
        },
        "privacy": {
            "public_output_aggregate_only": True,
            "private_caches_excluded_from_transfer": True,
            "network_requests": 0,
        },
    }
    common.atomic_json(public / "_SUCCESS.json", success)
    common.write_manifest_tsv(public)
    print(STATUS, flush=True)
    return success


def main() -> int:
    run(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
