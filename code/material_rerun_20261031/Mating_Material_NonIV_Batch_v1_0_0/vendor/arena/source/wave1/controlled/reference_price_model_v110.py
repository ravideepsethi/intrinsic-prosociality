#!/usr/bin/env python3
"""Build a controlled reference-price profile and local fit.

The public outputs contain aggregate bins, model summaries, figures, and
receipts only. Chooser/game identifiers remain in a separate private cache.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
import time
import zipfile

import duckdb
import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


VERSION = "1.1.0"
Z95 = 1.959963984540054
MONTHS = [
    f"{year}-{month:02d}"
    for year, months in [(2023, range(11, 13)), (2024, range(1, 13)), (2025, range(1, 11))]
    for month in months
]
POOLS = ["ultrabullet", "bullet", "blitz", "rapid", "classical", "correspondence"]
REQUIRED_STAGE07_FIELDS = [
    "game_id",
    "chooser_user_id",
    "api_speed",
    "month",
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
]
CONTROL_BLOCKS = [
    "displayed_rating_gap_spline",
    "expected_score_spline",
    "premium_spline",
    "ply",
    "opponent_rd",
    "chooser_rd",
    "evaluation",
    "context",
]
CORE_CONTROLS_REQUIRED = [
    "gap_linear",
    "expected_imbalance_linear",
    "log_kappa_centered",
    "log_opponent_rd",
    "log_chooser_rd",
    "eval_100cp",
    "chooser_rating_scaled",
    "log1p_chooser_clock",
    "log1p_opponent_clock",
]
AUTHORITY = {
    "opportunities": 47_587_020,
    "kind_draws": 669_503,
    "fair_rows": 17_328_130,
    "local_h1_n": 11_036_021,
    "local_h1_n_fe": 1_483_874,
    "local_h1_clusters": 1_290_329,
    "local_h1_kinds": 276_094,
    "left_slope": 0.3671334178310287,
    "left_slope_se": 0.0223962292094360,
    "right_slope": 0.1717066115831428,
    "right_slope_se": 0.0234324748787008,
    "left_minus_right": 0.1954268062478859,
    "left_minus_right_se": 0.0325440369500842,
}


class UnsupportedModel(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sql_quote(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def clean(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    return value


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(clean(value), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def connect(threads: int, memory: str, spill: Path) -> duckdb.DuckDBPyConnection:
    spill.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET threads={int(threads)}")
    con.execute("SET memory_limit=?", [memory])
    con.execute("SET temp_directory=?", [str(spill)])
    con.execute("SET preserve_insertion_order=true")
    return con


def export_frame(frame: pd.DataFrame, directory: Path, stem: str) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    csv_path = directory / f"{stem}.csv"
    parquet_path = directory / f"{stem}.parquet"
    frame.to_csv(csv_path, index=False)
    con = duckdb.connect()
    con.register("export_frame", frame)
    con.execute(
        f"COPY export_frame TO {sql_quote(parquet_path)} "
        "(FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    con.close()
    return [csv_path, parquet_path]


def source_inventory(panel: Path) -> tuple[list[Path], list[dict[str, object]]]:
    files = sorted(panel.glob("month=*/analysis_panel.parquet"))
    found_months = [path.parent.name.removeprefix("month=") for path in files]
    if found_months != MONTHS:
        raise RuntimeError(
            "Expected exactly the 24 certified month=*/analysis_panel.parquet files "
            f"for November 2023 through October 2025; found {found_months}."
        )
    inventory = [
        {
            "path": str(path.resolve()),
            "bytes": path.stat().st_size,
            "mtime_ns": path.stat().st_mtime_ns,
        }
        for path in files
    ]
    return files, inventory


def bin_spec(payoff_limit: float, bin_width: float) -> dict[str, object]:
    ratio = payoff_limit / bin_width
    if not np.isclose(ratio, round(ratio), atol=1e-10):
        raise ValueError("payoff-limit must be an exact multiple of bin-width")
    side_bins = int(round(ratio))
    zero_code = side_bins
    rows: list[dict[str, object]] = []
    for code in range(2 * side_bins + 1):
        if code < zero_code:
            center = -payoff_limit + (code + 0.5) * bin_width
            side = "loss"
            exact_zero = False
        elif code == zero_code:
            center = 0.0
            side = "zero"
            exact_zero = True
        else:
            center = (code - zero_code - 0.5) * bin_width
            side = "gain"
            exact_zero = False
        rows.append(
            {
                "payoff_bin_code": code,
                "payoff_center": center,
                "side": side,
                "exact_zero": exact_zero,
            }
        )
    return {
        "payoff_limit": payoff_limit,
        "bin_width": bin_width,
        "side_bins": side_bins,
        "zero_code": zero_code,
        "rows": rows,
    }


def stage_certified_panel(
    panel: Path,
    public_out: Path,
    private_out: Path,
    spec: dict[str, object],
    local_bandwidth: float,
    threads: int,
    memory: str,
    resume: bool,
    validate_source_authority: bool = True,
) -> tuple[Path, Path, dict[str, object]]:
    files, inventory = source_inventory(panel)
    broad_cache = private_out / "controlled_reference_price_broad_private.parquet"
    local_cache = private_out / "controlled_reference_price_local_h1_private.parquet"
    contract_path = private_out / "stage_contract.json"
    contract = {
        "version": VERSION,
        "panel_inventory": inventory,
        "payoff_limit": spec["payoff_limit"],
        "bin_width": spec["bin_width"],
        "local_bandwidth": local_bandwidth,
        "source_authority_validation": validate_source_authority,
    }
    if resume and broad_cache.is_file() and local_cache.is_file() and contract_path.is_file():
        if json.loads(contract_path.read_text(encoding="utf-8")) != contract:
            raise RuntimeError("Private staged-cache contract changed; use a fresh output/run ID.")
        con = connect(1, memory, private_out / "resume_check_spill")
        stats = con.execute(
            f"SELECT count(*) AS n, sum(y)/100 AS kinds "
            f"FROM read_parquet({sql_quote(broad_cache)})"
        ).fetchdf().iloc[0].to_dict()
        local_stats = con.execute(
            f"SELECT count(*) AS n, sum(y)/100 AS kinds "
            f"FROM read_parquet({sql_quote(local_cache)})"
        ).fetchdf().iloc[0].to_dict()
        con.close()
        return broad_cache, local_cache, {
            "cache_reused": True,
            "broad": stats,
            "local": local_stats,
            "source_inventory": inventory,
        }

    if broad_cache.exists() or local_cache.exists() or contract_path.exists():
        raise RuntimeError("Private cache already exists. Use --resume or a fresh run ID.")

    con = connect(threads, memory, private_out / "stage_spill")
    for path in files:
        fields = set(
            con.execute(f"DESCRIBE SELECT * FROM read_parquet({sql_quote(path)})")
            .fetchdf()["column_name"]
            .astype(str)
        )
        missing = sorted(set(REQUIRED_STAGE07_FIELDS) - fields)
        if missing:
            raise RuntimeError(f"Missing required Stage07 fields in {path}: {missing}")

    file_sql = ",".join(sql_quote(path) for path in files)
    con.execute(f"CREATE VIEW source_panel AS SELECT * FROM read_parquet([{file_sql}])")
    counts = con.execute(
        """SELECT cast("month" AS VARCHAR) AS source_month,
                  count(*) AS n,
                  sum(cast(outcome_kind_draw AS BIGINT)) AS kind,
                  count(*) FILTER (
                    WHERE outcome_kind_draw IS NULL
                       OR cast(outcome_kind_draw AS DOUBLE) NOT IN (0,1)
                  ) AS bad
           FROM source_panel
           GROUP BY source_month
           ORDER BY source_month"""
    ).fetchdf()
    if (
        counts["source_month"].tolist() != MONTHS
        or int(counts["bad"].sum()) != 0
    ):
        raise RuntimeError("Stage07 month/outcome-integrity check failed.")
    if validate_source_authority and (
        int(counts["n"].sum()) != AUTHORITY["opportunities"]
        or int(counts["kind"].sum()) != AUTHORITY["kind_draws"]
    ):
        raise RuntimeError("Certified Stage07 count/outcome authority check failed.")

    identity = con.execute(
        """SELECT count(*) AS n,
                  count(DISTINCT game_id) AS distinct_games,
                  count(*) FILTER (
                    WHERE game_id IS NULL OR trim(cast(game_id AS VARCHAR))=''
                  ) AS missing_game_id,
                  count(*) FILTER (
                    WHERE engine_eval_cp_disconnected>=-100
                  ) AS fair_rows
           FROM source_panel"""
    ).fetchdf().iloc[0].to_dict()
    if (
        int(identity["n"]) != int(identity["distinct_games"])
        or int(identity["missing_game_id"]) != 0
    ):
        raise RuntimeError("Stage07 identity-integrity check failed.")
    if (
        validate_source_authority
        and int(identity["fair_rows"]) != AUTHORITY["fair_rows"]
    ):
        raise RuntimeError("Certified Stage07 fair-row authority check failed.")

    pool_case = "CASE cast(api_speed AS VARCHAR) " + " ".join(
        f"WHEN {sql_quote(value)} THEN {index}" for index, value in enumerate(POOLS)
    ) + " ELSE -1 END"
    month_case = "CASE cast(\"month\" AS VARCHAR) " + " ".join(
        f"WHEN {sql_quote(value)} THEN {index}" for index, value in enumerate(MONTHS)
    ) + " ELSE -1 END"
    con.execute(
        f"""CREATE VIEW base AS
            SELECT cast(game_id AS VARCHAR) AS game_id,
                   cast(chooser_user_id AS VARCHAR) AS chooser,
                   {pool_case} AS pool_code,
                   {month_case} AS month_code,
                   cast(outcome_kind_draw AS DOUBLE)*100 AS y,
                   cast(chooser_draw_payoff_v2 AS DOUBLE) AS r,
                   cast(chooser_win_premium_v2 AS DOUBLE) AS kappa,
                   cast(chooser_win_payoff_v2 AS DOUBLE) AS claim_payoff,
                   cast(engine_eval_cp_disconnected AS DOUBLE) AS board_eval,
                   cast(chooser_pre_rd_v2 AS DOUBLE) AS chooser_rd,
                   cast(disconnected_pre_rd_v2 AS DOUBLE) AS opponent_rd,
                   cast(chooser_elo AS DOUBLE) AS chooser_rating,
                   cast(disconnected_elo AS DOUBLE)-cast(chooser_elo AS DOUBLE) AS gap,
                   cast(ply_count AS DOUBLE) AS ply,
                   cast(tournament_like_event AS DOUBLE) AS tournament,
                   cast(chooser_clock_last_obs_s AS DOUBLE) AS chooser_clock,
                   cast(disconnected_clock_last_obs_s AS DOUBLE) AS opponent_clock
            FROM source_panel"""
    )

    common = " AND ".join(
        [
            "chooser IS NOT NULL",
            "trim(chooser)!=''",
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
            "isfinite(tournament)",
            "tournament IN (0,1)",
            "pool_code>=0",
            "month_code>=0",
        ]
    )
    payoff_limit = float(spec["payoff_limit"])
    bin_width = float(spec["bin_width"])
    side_bins = int(spec["side_bins"])
    zero_code = int(spec["zero_code"])
    bin_expression = f"""CASE
        WHEN r=0 THEN {zero_code}
        WHEN r<0 THEN greatest(0, least({side_bins - 1},
             cast(floor((r+{payoff_limit})/{bin_width}) AS INTEGER)))
        ELSE {zero_code + 1}+least({side_bins - 1},
             cast(floor(r/{bin_width}) AS INTEGER)) END"""

    print("Staging fully eligible fair-position rows; private identifiers stay outside public output.", flush=True)
    con.execute(
        f"""COPY (
              WITH eligible AS (
                SELECT *, {bin_expression} AS payoff_bin_code
                FROM base
                WHERE {common} AND abs(r)<{payoff_limit}
              ), supported AS (
                SELECT *, count(*) OVER (
                  PARTITION BY chooser,pool_code
                ) AS broad_fe_n
                FROM eligible
              )
              SELECT * FROM supported WHERE broad_fe_n>=2
              ORDER BY chooser,pool_code
            ) TO {sql_quote(broad_cache)}
            (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 65536)"""
    )
    print("Staging the bandwidth-one common-support subset directly from Stage07.", flush=True)
    con.execute(
        f"""COPY (
              WITH eligible AS (
                SELECT *, {bin_expression} AS payoff_bin_code
                FROM base
                WHERE {common} AND abs(r)<{local_bandwidth}
              ), supported AS (
                SELECT *, count(*) OVER (
                  PARTITION BY chooser,pool_code
                ) AS local_fe_n
                FROM eligible
              )
              SELECT * FROM supported WHERE local_fe_n>=2
              ORDER BY chooser,pool_code
            ) TO {sql_quote(local_cache)}
            (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 65536)"""
    )

    broad_stats = con.execute(
        f"""SELECT count(*) AS n, sum(y)/100 AS kinds,
                   count(DISTINCT chooser) AS clusters,
                   count(DISTINCT (chooser,pool_code)) AS n_fe,
                   min(payoff_bin_code) AS min_bin,
                   max(payoff_bin_code) AS max_bin,
                   count(DISTINCT payoff_bin_code) AS bins
            FROM read_parquet({sql_quote(broad_cache)})"""
    ).fetchdf().iloc[0].to_dict()
    local_stats = con.execute(
        f"""SELECT count(*) AS n, sum(y)/100 AS kinds,
                   count(DISTINCT chooser) AS clusters,
                   count(DISTINCT (chooser,pool_code)) AS n_fe
            FROM read_parquet({sql_quote(local_cache)})"""
    ).fetchdf().iloc[0].to_dict()
    con.close()
    if int(broad_stats["bins"]) != 2 * side_bins + 1:
        raise RuntimeError(f"Expected {2 * side_bins + 1} populated payoff bins: {broad_stats}")

    write_json(contract_path, contract)
    export_frame(counts, public_out / "tables", "source_month_inventory")
    export_frame(pd.DataFrame([identity]), public_out / "tables", "source_identity_checks")
    export_frame(
        pd.DataFrame(
            [
                {"sample": "broad_adjusted_profile", **broad_stats},
                {"sample": "local_h1_fit", **local_stats},
            ]
        ),
        public_out / "tables",
        "sample_flow",
    )
    return broad_cache, local_cache, {
        "cache_reused": False,
        "broad": broad_stats,
        "local": local_stats,
        "source_inventory": inventory,
        "identity": identity,
    }


def make_smoke_caches(
    public_out: Path,
    private_out: Path,
    spec: dict[str, object],
    local_bandwidth: float,
) -> tuple[Path, Path, dict[str, object]]:
    rng = np.random.default_rng(20260906)
    choosers = 1_600
    rows_per = 36
    n = choosers * rows_per
    chooser = np.repeat([f"smoke_{i:05d}" for i in range(choosers)], rows_per)
    pool_code = rng.integers(0, 2, n)
    r = rng.uniform(-float(spec["payoff_limit"]) + 1e-4, float(spec["payoff_limit"]) - 1e-4, n)
    exact = rng.random(n) < 0.055
    r[exact] = 0.0
    kappa = np.clip(6.0 + 0.8 * rng.normal(size=n), 3.0, 12.0)
    chooser_rd = np.exp(rng.normal(np.log(55), 0.22, n))
    opponent_rd = np.exp(rng.normal(np.log(58), 0.23, n))
    board_eval = np.clip(rng.normal(120, 210, n), -100, 900)
    ply = rng.integers(2, 100, n)
    month_code = rng.integers(0, 24, n)
    chooser_rating = rng.normal(1650, 300, n)
    tournament = rng.integers(0, 2, n)
    chooser_clock = np.exp(rng.normal(4.0, 0.7, n))
    opponent_clock = np.exp(rng.normal(3.9, 0.7, n))
    expected_imbalance = np.clip(r / kappa, -0.95, 0.95)
    gap = 350.0 * np.arctanh(expected_imbalance) + rng.normal(0, 18, n)
    gap[exact] = 0.0
    latent_pp = (
        2.7
        + 0.31 * r * (r < 0)
        + 0.15 * r * (r > 0)
        + 0.08 * (r > 0)
        + 0.18 * (r == 0)
        + 0.000006 * gap * gap
        - 0.12 * (kappa - 6)
        + 0.0012 * board_eval
        - 0.005 * ply
    )
    probability = np.clip(latent_pp / 100, 0.002, 0.18)
    y = rng.binomial(1, probability, n) * 100.0
    side_bins = int(spec["side_bins"])
    zero_code = int(spec["zero_code"])
    width = float(spec["bin_width"])
    limit = float(spec["payoff_limit"])
    codes = np.where(
        r == 0,
        zero_code,
        np.where(
            r < 0,
            np.floor((r + limit) / width).astype(int),
            zero_code + 1 + np.floor(r / width).astype(int),
        ),
    )
    frame = pd.DataFrame(
        {
            "game_id": [f"g{i:08d}" for i in range(n)],
            "chooser": chooser,
            "pool_code": pool_code,
            "month_code": month_code,
            "y": y,
            "r": r,
            "kappa": kappa,
            "claim_payoff": r + kappa,
            "board_eval": board_eval,
            "chooser_rd": chooser_rd,
            "opponent_rd": opponent_rd,
            "chooser_rating": chooser_rating,
            "gap": gap,
            "ply": ply,
            "tournament": tournament,
            "chooser_clock": chooser_clock,
            "opponent_clock": opponent_clock,
            "payoff_bin_code": np.clip(codes, 0, 2 * side_bins),
        }
    )
    group_n = frame.groupby(["chooser", "pool_code"])["y"].transform("size")
    frame = frame.loc[group_n >= 2].sort_values(["chooser", "pool_code"]).reset_index(drop=True)
    frame["broad_fe_n"] = frame.groupby(["chooser", "pool_code"])["y"].transform("size")
    local = frame.loc[frame["r"].abs() < local_bandwidth].copy()
    local_n = local.groupby(["chooser", "pool_code"])["y"].transform("size")
    local = local.loc[local_n >= 2].sort_values(["chooser", "pool_code"]).reset_index(drop=True)
    local["local_fe_n"] = local.groupby(["chooser", "pool_code"])["y"].transform("size")
    broad_cache = private_out / "controlled_reference_price_broad_private.parquet"
    local_cache = private_out / "controlled_reference_price_local_h1_private.parquet"
    con = duckdb.connect()
    con.register("broad", frame)
    con.register("local", local)
    con.execute(f"COPY broad TO {sql_quote(broad_cache)} (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.execute(f"COPY local TO {sql_quote(local_cache)} (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.close()
    info = {
        "cache_reused": False,
        "synthetic_smoke_test": True,
        "broad": {"n": len(frame), "kinds": float(frame["y"].sum() / 100)},
        "local": {"n": len(local), "kinds": float(local["y"].sum() / 100)},
        "source_inventory": [],
    }
    export_frame(
        pd.DataFrame(
            [
                {"sample": "broad_adjusted_profile", **info["broad"]},
                {"sample": "local_h1_fit", **info["local"]},
            ]
        ),
        public_out / "tables",
        "sample_flow",
    )
    return broad_cache, local_cache, info


def frame_factory(cache: Path, batch_rows: int, memory: str, spill: Path):
    def factory():
        con = connect(1, memory, spill)
        cursor = con.execute(f"SELECT * FROM read_parquet({sql_quote(cache)})")
        reader = (
            cursor.to_arrow_reader(batch_rows)
            if hasattr(cursor, "to_arrow_reader")
            else cursor.fetch_record_batch(batch_rows)
        )
        carry: pd.DataFrame | None = None
        previous_chooser: str | None = None
        try:
            for record in reader:
                frame = record.to_pandas()
                if carry is not None:
                    frame = pd.concat([carry, frame], ignore_index=True)
                if frame.empty:
                    continue
                chooser_values = frame["chooser"].astype(str).to_numpy()
                if previous_chooser is not None and chooser_values[0] < previous_chooser:
                    raise RuntimeError("Private cache is not ordered by chooser.")
                last = chooser_values[-1]
                end = int(np.searchsorted(chooser_values, last, side="left"))
                carry = frame.iloc[end:].copy()
                if end:
                    complete = frame.iloc[:end].reset_index(drop=True)
                    previous_chooser = str(complete["chooser"].iloc[-1])
                    yield complete
            if carry is not None and not carry.empty:
                yield carry.reset_index(drop=True)
        finally:
            con.close()

    return factory


def add_column(
    columns: list[np.ndarray],
    names: list[str],
    values: object,
    name: str,
) -> None:
    columns.append(np.asarray(values, dtype=float))
    names.append(name)


def knot_label(value: float) -> str:
    sign = "m" if value < 0 else "p"
    magnitude = f"{abs(value):g}".replace(".", "p")
    return sign + magnitude


def add_linear_spline(
    columns: list[np.ndarray],
    names: list[str],
    values: np.ndarray,
    prefix: str,
    *,
    knots: list[float],
    lower: float,
    upper: float,
    scale: float,
) -> None:
    """Add a stable continuous piecewise-linear basis without an intercept."""
    raw = np.asarray(values, dtype=float)
    clipped = np.clip(raw, lower, upper)
    add_column(columns, names, clipped / scale, f"{prefix}_linear")
    for knot in knots:
        add_column(
            columns,
            names,
            np.maximum(clipped - knot, 0.0) / scale,
            f"{prefix}_hinge_{knot_label(knot)}",
        )
    add_column(columns, names, raw < lower, f"{prefix}_below_{knot_label(lower)}")
    add_column(columns, names, raw > upper, f"{prefix}_above_{knot_label(upper)}")


def legacy_control_design(frame: pd.DataFrame) -> tuple[list[np.ndarray], list[str]]:
    """Frozen v1.0.1 controls used only to authenticate the local data bridge."""
    columns: list[np.ndarray] = []
    names: list[str] = []
    kappa = frame["kappa"].to_numpy(float) / 10
    add_column(columns, names, kappa, "kappa_div10")
    ply_band = np.searchsorted(
        np.asarray([2, 4, 10, 20, 40, 80]), frame["ply"].to_numpy(float), side="left"
    )
    for index in range(1, 7):
        add_column(columns, names, ply_band == index, f"ply_band_{index}")
    add_column(columns, names, np.log(frame["opponent_rd"].to_numpy(float)), "log_opponent_rd")
    add_column(columns, names, np.log(frame["chooser_rd"].to_numpy(float)), "log_chooser_rd")
    board_eval = frame["board_eval"].to_numpy(float)
    clipped_eval = np.clip(board_eval, -600, 600) / 100
    add_column(columns, names, clipped_eval, "eval_100cp")
    add_column(columns, names, clipped_eval * clipped_eval, "eval_squared")
    add_column(columns, names, board_eval > 600, "eval_above600")
    add_column(columns, names, board_eval < -600, "eval_belowminus600")
    add_column(columns, names, frame["chooser_rating"].to_numpy(float) / 1000, "chooser_rating_1000")
    month_code = frame["month_code"].to_numpy(int)
    for index in range(1, 24):
        add_column(columns, names, month_code == index, f"month_{index}")
    add_column(columns, names, frame["tournament"].to_numpy(float), "tournament")
    for clock in ["chooser_clock", "opponent_clock"]:
        values = frame[clock].to_numpy(float)
        missing = ~np.isfinite(values) | (values < 0)
        add_column(columns, names, np.log1p(np.where(missing, 0, values)), f"log1p_{clock}")
        add_column(columns, names, missing, f"{clock}_missing")
    return columns, names


def control_design(frame: pd.DataFrame) -> tuple[list[np.ndarray], list[str]]:
    """Full reference-price controls, including flexible relative strength."""
    columns: list[np.ndarray] = []
    names: list[str] = []

    # Draw payoff is r_G = kappa * (1 - 2E).  Flexibly control both the
    # expected-score component and the displayed rating gap.  Neither spline
    # has a knot at zero: the maintained counterfactual is smooth through
    # parity, while the r_G terms are allowed to differ across the reference.
    kappa = frame["kappa"].to_numpy(float)
    r = frame["r"].to_numpy(float)
    expected_imbalance = np.clip(r / kappa, -1.0, 1.0)
    add_linear_spline(
        columns,
        names,
        frame["gap"].to_numpy(float),
        "gap",
        knots=[-600, -400, -250, -150, -100, -50, 50, 100, 150, 250, 400, 600],
        lower=-800,
        upper=800,
        scale=100,
    )
    add_linear_spline(
        columns,
        names,
        expected_imbalance,
        "expected_imbalance",
        knots=[-0.75, -0.50, -0.30, -0.15, -0.075, 0.075, 0.15, 0.30, 0.50, 0.75],
        lower=-0.90,
        upper=0.90,
        scale=0.10,
    )

    # The forgone-win premium/update scale is strongly heaped.  A spline in
    # log(kappa) is materially more flexible than the old single linear term.
    log_kappa = np.log(kappa / 6.0)
    add_column(columns, names, log_kappa, "log_kappa_centered")
    for premium_knot in [5.75, 6.0, 7.0, 9.0, 12.0, 20.0, 40.0]:
        knot = math.log(premium_knot / 6.0)
        add_column(
            columns,
            names,
            np.maximum(log_kappa - knot, 0.0),
            f"log_kappa_hinge_{str(premium_knot).replace('.', 'p')}",
        )

    ply_band = np.searchsorted(
        np.asarray([2, 4, 10, 20, 40, 80, 160]),
        frame["ply"].to_numpy(float),
        side="left",
    )
    for index in range(1, 8):
        add_column(columns, names, ply_band == index, f"ply_band_{index}")

    for role, field in [("opponent", "opponent_rd"), ("chooser", "chooser_rd")]:
        log_rd = np.log(frame[field].to_numpy(float) / 50.0)
        add_column(columns, names, log_rd, f"log_{role}_rd")
        add_column(columns, names, log_rd * log_rd, f"log_{role}_rd_squared")

    board_eval = frame["board_eval"].to_numpy(float)
    clipped_eval = np.clip(board_eval, -100, 600) / 100
    add_column(columns, names, clipped_eval, "eval_100cp")
    add_column(columns, names, clipped_eval * clipped_eval, "eval_squared")
    add_column(columns, names, np.maximum(board_eval - 600, 0.0) / 100, "eval_above600_slope")

    chooser_rating = (frame["chooser_rating"].to_numpy(float) - 1700.0) / 500.0
    add_column(columns, names, chooser_rating, "chooser_rating_scaled")
    add_column(columns, names, chooser_rating * chooser_rating, "chooser_rating_squared")

    month_code = frame["month_code"].to_numpy(int)
    for index in range(1, 24):
        add_column(columns, names, month_code == index, f"month_{index}")
    add_column(columns, names, frame["tournament"].to_numpy(float), "tournament")

    for clock in ["chooser_clock", "opponent_clock"]:
        values = frame[clock].to_numpy(float)
        missing = ~np.isfinite(values) | (values < 0)
        logged = np.log1p(np.where(missing, 0, values))
        add_column(columns, names, logged, f"log1p_{clock}")
        add_column(columns, names, logged * logged, f"log1p_{clock}_squared")
        add_column(columns, names, missing, f"{clock}_missing")
    return columns, names


def make_bin_design(frame: pd.DataFrame, spec: dict[str, object]) -> tuple[np.ndarray, list[str]]:
    zero_code = int(spec["zero_code"])
    total_bins = 2 * int(spec["side_bins"]) + 1
    codes = frame["payoff_bin_code"].to_numpy(int)
    columns: list[np.ndarray] = []
    names: list[str] = []
    for code in range(total_bins):
        if code == zero_code:
            continue
        add_column(columns, names, codes == code, f"bin_{code:03d}")
    controls, control_names = control_design(frame)
    columns.extend(controls)
    names.extend(control_names)
    return np.column_stack(columns), names


def make_local_design(frame: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    r = frame["r"].to_numpy(float)
    columns: list[np.ndarray] = [
        r * (r < 0),
        r * (r > 0),
        (r > 0).astype(float),
        (r == 0).astype(float),
    ]
    names = ["left", "right", "jump", "tie"]
    controls, control_names = control_design(frame)
    columns.extend(controls)
    names.extend(control_names)
    return np.column_stack(columns), names


def make_legacy_local_design(frame: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    r = frame["r"].to_numpy(float)
    columns: list[np.ndarray] = [
        r * (r < 0),
        r * (r > 0),
        (r > 0).astype(float),
        (r == 0).astype(float),
    ]
    names = ["left", "right", "jump", "tie"]
    controls, control_names = legacy_control_design(frame)
    columns.extend(controls)
    names.extend(control_names)
    return np.column_stack(columns), names


def within_transform(
    frame: pd.DataFrame, design: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, int]]:
    chooser = frame["chooser"].astype(str).to_numpy()
    pool = frame["pool_code"].to_numpy(int)
    group_change = np.r_[True, chooser[1:] != chooser[:-1]]
    group_change[1:] |= pool[1:] != pool[:-1]
    group_starts = np.flatnonzero(group_change)
    group_lengths = np.diff(np.r_[group_starts, len(frame)])
    if np.any(group_lengths < 2):
        raise RuntimeError("Singleton chooser-pool cell reached within transformation.")
    y = frame["y"].to_numpy(float)
    design_mean = np.add.reduceat(design, group_starts, axis=0) / group_lengths[:, None]
    y_mean = np.add.reduceat(y, group_starts) / group_lengths
    design_within = design - np.repeat(design_mean, group_lengths, axis=0)
    y_within = y - np.repeat(y_mean, group_lengths)
    cluster_starts = np.r_[0, np.flatnonzero(chooser[1:] != chooser[:-1]) + 1]
    return design_within, y_within, cluster_starts, {
        "n": len(frame),
        "n_fe": len(group_starts),
        "clusters": len(cluster_starts),
    }


def independent(matrix: np.ndarray, indices: list[int], scale: np.ndarray) -> bool:
    normalized = matrix / np.outer(scale, scale)
    values = np.linalg.eigvalsh(normalized[np.ix_(indices, indices)])
    return bool(values[0] > 1e-10 * max(1.0, float(values[-1])))


def solve_crossproducts(
    gram: np.ndarray,
    cross: np.ndarray,
    required: list[int],
    requested: list[int],
) -> tuple[np.ndarray, np.ndarray, list[int], float]:
    scale = np.sqrt(np.maximum(np.diag(gram), 0))
    safe_scale = np.where(scale > 1e-10, scale, 1.0)
    if any(scale[index] < 1e-10 for index in required):
        raise UnsupportedModel("A required payoff/control term has no within-FE variation.")
    if not independent(gram, required, safe_scale):
        raise UnsupportedModel("Required payoff/control terms are not jointly identified.")
    kept = list(required)
    for index in requested:
        if index in kept or scale[index] <= 1e-10:
            continue
        if independent(gram, kept + [index], safe_scale):
            kept.append(index)
    kept_array = np.asarray(kept, dtype=int)
    normalized = gram / np.outer(safe_scale, safe_scale)
    inverse = np.linalg.inv(normalized[np.ix_(kept_array, kept_array)]) / np.outer(
        safe_scale[kept_array], safe_scale[kept_array]
    )
    beta = np.zeros(len(gram))
    beta[kept_array] = inverse @ cross[kept_array]
    bread = np.zeros_like(gram)
    bread[np.ix_(kept_array, kept_array)] = inverse
    condition = float(np.linalg.cond(normalized[np.ix_(kept_array, kept_array)]))
    return beta, bread, kept, condition


def fit_within_model(
    factory,
    design_builder,
    required_names_builder,
    model_name: str,
    code_count: int | None = None,
    must_retain_names: list[str] | None = None,
) -> dict[str, object]:
    gram: np.ndarray | None = None
    cross: np.ndarray | None = None
    yy = 0.0
    names: list[str] | None = None
    totals = {"n": 0, "n_fe": 0, "clusters": 0, "kinds": 0.0, "sum_y": 0.0}
    bin_n = np.zeros(code_count or 0, dtype=np.int64)
    bin_sum_y = np.zeros(code_count or 0, dtype=float)
    for frame in factory():
        design, current_names = design_builder(frame)
        if names is None:
            names = current_names
            gram = np.zeros((design.shape[1], design.shape[1]))
            cross = np.zeros(design.shape[1])
        elif current_names != names:
            raise RuntimeError("Design column order changed between batches.")
        x_within, y_within, _, stats = within_transform(frame, design)
        gram += x_within.T @ x_within
        cross += x_within.T @ y_within
        yy += float(y_within @ y_within)
        for key in ["n", "n_fe", "clusters"]:
            totals[key] += int(stats[key])
        totals["kinds"] += float(frame["y"].sum() / 100)
        totals["sum_y"] += float(frame["y"].sum())
        if code_count is not None:
            codes = frame["payoff_bin_code"].to_numpy(int)
            bin_n += np.bincount(codes, minlength=code_count)
            bin_sum_y += np.bincount(codes, weights=frame["y"].to_numpy(float), minlength=code_count)
    if gram is None or cross is None or names is None:
        raise UnsupportedModel(f"No observations for {model_name}.")
    required_names = required_names_builder(names)
    missing_required = [name for name in required_names if name not in names]
    if missing_required:
        raise RuntimeError(f"Required design names absent: {missing_required}")
    required = [names.index(name) for name in required_names]
    beta, bread, kept, condition = solve_crossproducts(
        gram, cross, required, list(range(len(names)))
    )
    retained_names = {names[index] for index in kept}
    unexpectedly_dropped = [
        name for name in (must_retain_names or []) if name not in retained_names
    ]
    if unexpectedly_dropped:
        raise UnsupportedModel(
            "Required full-control terms were dropped: " + ", ".join(unexpectedly_dropped)
        )
    degrees_freedom = totals["n"] - totals["n_fe"] - len(kept)
    if degrees_freedom <= 0 or totals["clusters"] <= 1:
        raise UnsupportedModel("Insufficient residual degrees of freedom or chooser clusters.")
    cr1 = totals["clusters"] / (totals["clusters"] - 1) * (totals["n"] - 1) / degrees_freedom
    meat = np.zeros((len(kept), len(kept)))
    kept_array = np.asarray(kept, dtype=int)
    for frame in factory():
        design, _ = design_builder(frame)
        x_within, y_within, cluster_starts, _ = within_transform(frame, design)
        x_kept = x_within[:, kept_array]
        residual = y_within - x_kept @ beta[kept_array]
        scores = np.add.reduceat(x_kept * residual[:, None], cluster_starts, axis=0)
        meat += scores.T @ scores
    covariance = cr1 * (bread[:, kept_array] @ meat @ bread[kept_array, :])
    covariance = (covariance + covariance.T) / 2
    rss = float(yy - 2 * beta @ cross + beta @ gram @ beta)
    dropped = [names[index] for index in range(len(names)) if index not in kept]
    return {
        "model": model_name,
        "names": names,
        "beta": beta,
        "covariance": covariance,
        "kept": kept,
        "dropped": dropped,
        "condition": condition,
        "cr1": cr1,
        "rss": rss,
        "stats": totals,
        "bin_n": bin_n,
        "bin_sum_y": bin_sum_y,
    }


def contrast(model: dict[str, object], entries: dict[str, float]) -> dict[str, float]:
    names = model["names"]
    beta = model["beta"]
    covariance = model["covariance"]
    vector = np.zeros(len(names))
    for name, value in entries.items():
        vector[names.index(name)] = value
    estimate = float(vector @ beta)
    variance = float(vector @ covariance @ vector)
    if variance < -1e-8:
        raise ArithmeticError("Negative contrast variance.")
    se = math.sqrt(max(0.0, variance))
    t_value = estimate / se if se > 1e-14 else math.nan
    p_value = math.erfc(abs(t_value) / math.sqrt(2)) if math.isfinite(t_value) else math.nan
    return {
        "estimate": estimate,
        "se": se,
        "t": t_value,
        "p": p_value,
        "ci95_low": estimate - Z95 * se,
        "ci95_high": estimate + Z95 * se,
    }


def adjusted_bin_table(model: dict[str, object], spec: dict[str, object]) -> pd.DataFrame:
    names: list[str] = model["names"]
    beta: np.ndarray = model["beta"]
    covariance: np.ndarray = model["covariance"]
    counts: np.ndarray = model["bin_n"]
    sums: np.ndarray = model["bin_sum_y"]
    total_n = int(counts.sum())
    if total_n != int(model["stats"]["n"]):
        raise AssertionError("Bin counts do not sum to the fitted sample.")
    weights = counts / total_n
    zero_code = int(spec["zero_code"])
    coefficient_vectors: list[np.ndarray] = []
    for row in spec["rows"]:
        code = int(row["payoff_bin_code"])
        vector = np.zeros(len(names))
        if code != zero_code:
            vector[names.index(f"bin_{code:03d}")] = 1.0
        coefficient_vectors.append(vector)
    average_vector = sum(weight * vector for weight, vector in zip(weights, coefficient_vectors))
    grand_mean = float(model["stats"]["sum_y"]) / total_n
    rows = []
    for metadata, vector, n, sum_y in zip(spec["rows"], coefficient_vectors, counts, sums):
        centered = vector - average_vector
        estimate = grand_mean + float(centered @ beta)
        variance = float(centered @ covariance @ centered)
        se = math.sqrt(max(0.0, variance))
        rows.append(
            {
                **metadata,
                "n": int(n),
                "raw_rate_pct_diagnostic_only": float(sum_y / n) if n else math.nan,
                "adjusted_rate_pct": estimate,
                "clustered_se_pp": se,
                "ci95_low_pct": estimate - Z95 * se,
                "ci95_high_pct": estimate + Z95 * se,
                "normalization": "payoff-bin effects shifted so their frequency-weighted mean equals the fitted-sample mean",
            }
        )
    table = pd.DataFrame(rows)
    weighted_adjusted = float(np.average(table["adjusted_rate_pct"], weights=table["n"]))
    if not np.isclose(weighted_adjusted, grand_mean, atol=1e-9):
        raise AssertionError("Adjusted-bin normalization failed.")
    return table


def coefficient_table(model: dict[str, object]) -> pd.DataFrame:
    rows = []
    kept = set(model["kept"])
    for index, name in enumerate(model["names"]):
        if index not in kept:
            continue
        se = math.sqrt(max(0.0, float(model["covariance"][index, index])))
        rows.append({"term": name, "estimate": float(model["beta"][index]), "clustered_se": se})
    return pd.DataFrame(rows)


def local_summary(model: dict[str, object]) -> tuple[pd.DataFrame, dict[str, dict[str, float]]]:
    contrasts = {
        "loss_side_slope": contrast(model, {"left": 1.0}),
        "gain_side_slope": contrast(model, {"right": 1.0}),
        "loss_minus_gain_slope": contrast(model, {"left": 1.0, "right": -1.0}),
        "right_minus_left_level": contrast(model, {"jump": 1.0}),
        "exact_zero_minus_left_limit": contrast(model, {"tie": 1.0}),
        "exact_zero_minus_right_limit": contrast(model, {"tie": 1.0, "jump": -1.0}),
    }
    rows = []
    for estimand, result in contrasts.items():
        rows.append({"estimand": estimand, **result})
    return pd.DataFrame(rows), contrasts


def authenticate_local_result(
    model: dict[str, object], contrasts: dict[str, dict[str, float]]
) -> dict[str, object]:
    observed = {
        "n": int(model["stats"]["n"]),
        "n_fe": int(model["stats"]["n_fe"]),
        "clusters": int(model["stats"]["clusters"]),
        "kinds": int(round(float(model["stats"]["kinds"]))),
        "left_slope": contrasts["loss_side_slope"]["estimate"],
        "left_slope_se": contrasts["loss_side_slope"]["se"],
        "right_slope": contrasts["gain_side_slope"]["estimate"],
        "right_slope_se": contrasts["gain_side_slope"]["se"],
        "left_minus_right": contrasts["loss_minus_gain_slope"]["estimate"],
        "left_minus_right_se": contrasts["loss_minus_gain_slope"]["se"],
    }
    exact_keys = ["n", "n_fe", "clusters", "kinds"]
    numeric_keys = [
        "left_slope",
        "left_slope_se",
        "right_slope",
        "right_slope_se",
        "left_minus_right",
        "left_minus_right_se",
    ]
    failures = []
    for key in exact_keys:
        if observed[key] != AUTHORITY[f"local_h1_{key}" if key in ["n", "n_fe", "clusters", "kinds"] else key]:
            failures.append({"field": key, "expected": AUTHORITY.get(f"local_h1_{key}"), "observed": observed[key]})
    for key in numeric_keys:
        if not np.isclose(observed[key], AUTHORITY[key], atol=2e-5, rtol=0):
            failures.append({"field": key, "expected": AUTHORITY[key], "observed": observed[key]})
    if failures:
        raise RuntimeError(f"Local h=1 bridge authentication failed: {failures}")
    return {"status": "LOCAL_H1_BRIDGE_AUTHENTICATED", "observed": observed, "tolerance": 2e-5}


def local_fit_grid(
    bins: pd.DataFrame,
    model: dict[str, object],
    bandwidth: float,
) -> tuple[pd.DataFrame, float]:
    names = model["names"]
    beta = model["beta"]
    left = float(beta[names.index("left")])
    right = float(beta[names.index("right")])
    jump = float(beta[names.index("jump")])
    tie = float(beta[names.index("tie")])
    nearby = bins.loc[(bins["payoff_center"].abs() < bandwidth) & ~bins["exact_zero"]].copy()
    shape = np.where(
        nearby["payoff_center"] < 0,
        left * nearby["payoff_center"],
        jump + right * nearby["payoff_center"],
    )
    anchor = float(
        np.average(nearby["adjusted_rate_pct"].to_numpy(float) - shape, weights=nearby["n"])
    )
    left_x = np.linspace(-bandwidth, -1e-6, 120)
    right_x = np.linspace(1e-6, bandwidth, 120)
    grid = pd.DataFrame(
        {
            "r_G": np.r_[left_x, 0.0, right_x],
            "side": ["loss"] * len(left_x) + ["zero"] + ["gain"] * len(right_x),
            "fitted_rate_pct": np.r_[anchor + left * left_x, anchor + tie, anchor + jump + right * right_x],
            "display_anchor_pct": anchor,
        }
    )
    return grid, anchor


def configure_figure_style() -> None:
    preferred = "DejaVu Serif"
    mpl.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": [preferred, "Palatino", "DejaVu Serif"],
            "font.size": 7.4,
            "axes.titlesize": 8.4,
            "axes.titleweight": "bold",
            "axes.labelsize": 7.5,
            "xtick.labelsize": 6.8,
            "ytick.labelsize": 6.8,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.linewidth": 0.65,
            "axes.unicode_minus": False,
            "grid.color": "#D9DEE4",
            "grid.linewidth": 0.5,
            "legend.frameon": False,
            "legend.fontsize": 6.2,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "svg.fonttype": "path",
            "svg.hashsalt": "controlled-reference-price-figure-v1.1.0",
            "savefig.facecolor": "white",
            "figure.facecolor": "white",
        }
    )


def draw_figure(
    bins: pd.DataFrame,
    fit_grid: pd.DataFrame,
    contrasts: dict[str, dict[str, float]],
    spec: dict[str, object],
    bandwidth: float,
    figures: Path,
) -> list[Path]:
    configure_figure_style()
    ink = "#20252B"
    blue = "#0072B2"
    orange = "#D55E00"
    teal = "#009E73"
    gray = "#6E7781"
    pale = "#F1F3F5"
    figure, axes = plt.subplots(
        1,
        2,
        figsize=(5.90, 3.08),
        gridspec_kw={"width_ratios": [1.32, 0.88], "wspace": 0.22},
        layout="constrained",
    )
    broad, zoom = axes
    nonzero = bins.loc[~bins["exact_zero"]].sort_values("payoff_center")
    zero = bins.loc[bins["exact_zero"]].iloc[0]
    loss = nonzero.loc[nonzero["side"] == "loss"]
    gain = nonzero.loc[nonzero["side"] == "gain"]
    broad.axvspan(-bandwidth, bandwidth, color=pale, zorder=0)
    broad.axvline(0, color=ink, lw=0.75, ls=(0, (3, 2)))
    for part in [loss, gain]:
        broad.plot(part["payoff_center"], part["adjusted_rate_pct"], color=gray, lw=0.75, zorder=1)
    broad.errorbar(
        nonzero["payoff_center"],
        nonzero["adjusted_rate_pct"],
        yerr=Z95 * nonzero["clustered_se_pp"],
        fmt="o",
        ms=2.7,
        color=blue,
        ecolor=blue,
        elinewidth=0.55,
        capsize=1.2,
        markerfacecolor="white",
        markeredgewidth=0.65,
        label="Controlled bin estimates",
        zorder=3,
    )
    broad.errorbar(
        [zero["payoff_center"]],
        [zero["adjusted_rate_pct"]],
        yerr=[Z95 * zero["clustered_se_pp"]],
        fmt="D",
        ms=3.5,
        color=ink,
        ecolor=ink,
        markerfacecolor="white",
        markeredgewidth=0.75,
        label="Exact zero payoff",
        zorder=4,
    )
    broad.set_xlim(-float(spec["payoff_limit"]), float(spec["payoff_limit"]))
    broad.set_xticks(np.linspace(-float(spec["payoff_limit"]), float(spec["payoff_limit"]), 5))
    broad.set_xlabel(r"Chooser draw payoff, $r_G$ (rating points)")
    broad.set_ylabel("Adjusted kind-draw rate (%)")
    broad.set_title("A. Adjusted reference-price profile", loc="left", pad=5)
    broad.grid(axis="y")
    broad.legend(loc="upper left")
    broad.text(
        0.98,
        0.04,
        f"{len(spec['rows'])} bins; shaded: local $h={bandwidth:g}$ window",
        transform=broad.transAxes,
        ha="right",
        color=gray,
        fontsize=5.7,
    )

    local_bins = bins.loc[bins["payoff_center"].abs() <= bandwidth].copy()
    local_nonzero = local_bins.loc[~local_bins["exact_zero"]]
    local_zero = local_bins.loc[local_bins["exact_zero"]].iloc[0]
    zoom.axvline(0, color=ink, lw=0.75, ls=(0, (3, 2)))
    zoom.errorbar(
        local_nonzero["payoff_center"],
        local_nonzero["adjusted_rate_pct"],
        yerr=Z95 * local_nonzero["clustered_se_pp"],
        fmt="o",
        ms=3.0,
        color=blue,
        ecolor=blue,
        elinewidth=0.65,
        capsize=1.5,
        markerfacecolor="white",
        markeredgewidth=0.7,
        zorder=3,
    )
    zoom.errorbar(
        [0],
        [local_zero["adjusted_rate_pct"]],
        yerr=[Z95 * local_zero["clustered_se_pp"]],
        fmt="D",
        ms=3.8,
        color=ink,
        ecolor=ink,
        markerfacecolor="white",
        markeredgewidth=0.8,
        zorder=4,
    )
    for side, color, linestyle, label in [
        ("loss", orange, "-", "Loss-side local fit"),
        ("gain", teal, (0, (4, 1.5)), "Gain-side local fit"),
    ]:
        part = fit_grid.loc[fit_grid["side"] == side]
        zoom.plot(part["r_G"], part["fitted_rate_pct"], color=color, lw=1.55, ls=linestyle, label=label, zorder=2)
    exact_fit = fit_grid.loc[fit_grid["side"] == "zero"].iloc[0]
    zoom.scatter([0], [exact_fit["fitted_rate_pct"]], marker="x", s=18, color=ink, linewidth=0.9, zorder=5)
    zoom.set_xlim(-bandwidth * 1.04, bandwidth * 1.04)
    zoom.set_xticks([-bandwidth, -bandwidth / 2, 0, bandwidth / 2, bandwidth])
    zoom.set_xlabel(r"Draw payoff, $r_G$ (rating points)")
    zoom.set_title("B. Reference-point local fit", loc="left", pad=5)
    zoom.grid(axis="y")
    zoom.legend(loc="lower right", fontsize=5.7)
    slope_loss = contrasts["loss_side_slope"]
    slope_gain = contrasts["gain_side_slope"]
    slope_difference = contrasts["loss_minus_gain_slope"]
    zoom.text(
        0.04,
        0.96,
        "Loss slope  " + f"{slope_loss['estimate']:.3f} ({slope_loss['se']:.3f})\n"
        + "Gain slope  " + f"{slope_gain['estimate']:.3f} ({slope_gain['se']:.3f})\n"
        + "Difference  " + f"{slope_difference['estimate']:.3f} ({slope_difference['se']:.3f})",
        transform=zoom.transAxes,
        va="top",
        fontsize=5.85,
        color=ink,
        bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.82, "pad": 1.1},
    )

    all_low = np.r_[bins["ci95_low_pct"].to_numpy(float), fit_grid["fitted_rate_pct"].to_numpy(float)]
    all_high = np.r_[bins["ci95_high_pct"].to_numpy(float), fit_grid["fitted_rate_pct"].to_numpy(float)]
    low = float(np.nanmin(all_low))
    high = float(np.nanmax(all_high))
    padding = max(0.08, 0.08 * (high - low))
    broad.set_ylim(low - padding, high + padding)
    local_low = float(
        min(local_bins["ci95_low_pct"].min(), fit_grid["fitted_rate_pct"].min())
    )
    local_high = float(
        max(local_bins["ci95_high_pct"].max(), fit_grid["fitted_rate_pct"].max())
    )
    local_padding = max(0.04, 0.12 * (local_high - local_low))
    zoom.set_ylim(local_low - local_padding, local_high + local_padding)

    figures.mkdir(parents=True, exist_ok=True)
    paths = [
        figures / "figure_controlled_reference_price.pdf",
        figures / "figure_controlled_reference_price.png",
        figures / "figure_controlled_reference_price.svg",
    ]
    figure.savefig(
        paths[0],
        metadata={
            "Title": "Controlled draw-payoff reference-price profile and local fit",
            "Author": "Intrinsic Prosociality figure build",
            "Subject": "Aggregate figure from the certified 24-month panel",
            "Creator": f"controlled_reference_price_figure.py v{VERSION}",
        },
    )
    figure.savefig(paths[1], dpi=600, metadata={"Software": f"controlled_reference_price_figure.py v{VERSION}"})
    figure.savefig(paths[2], metadata={"Creator": f"controlled_reference_price_figure.py v{VERSION}"})
    plt.close(figure)
    return paths


def write_caption(path: Path, spec: dict[str, object], bandwidth: float) -> None:
    text = rf"""\caption{{\textbf{{Kindness and the reference-dependent price of drawing.}}
The horizontal axis is the chooser's draw payoff, $r_G=K(1/2-E)$, expressed in
rating points. Panel~A reports {float(spec['bin_width']):g}-point adjusted
payoff-bin estimates for competitive positions with
$|r_G|<{float(spec['payoff_limit']):g}$. The opportunity-level linear
probability model includes chooser-by-speed-pool fixed effects, flexible
continuous splines in the displayed rating gap and expected-score imbalance,
a flexible spline in the forgone-win premium $\kappa=K/2$, game-stage bands,
both players' rating deviations, board evaluation, chooser rating, both
clocks and missing-clock indicators, month, and tournament status. The
relative-strength splines are constrained to be smooth through parity, so
they control the broad strength gradient without mechanically absorbing the
reference-point comparison at zero. Bin effects are centered and shifted so
their frequency-weighted mean equals the fitted-sample outcome mean. Points
are estimates and bars are chooser-clustered 95~percent conditional-model
intervals; exact-zero observations are retained and estimated separately.
Panel~B magnifies $|r_G|<{bandwidth:g}$ and overlays separate loss- and
gain-side local-linear fits estimated on the underlying opportunities with
the same controls and fixed effects. These are finite-window conditional
associations under the smooth-relative-strength specification, not a
regression-discontinuity design or a causal price elasticity.}}
"""
    path.write_text(text, encoding="utf-8")


def write_manifest(root: Path) -> Path:
    manifest = root / "OUTPUT_MANIFEST.sha256"
    files = sorted(path for path in root.rglob("*") if path.is_file() and path != manifest)
    manifest.write_text(
        "".join(f"{sha256(path)}  {path.relative_to(root).as_posix()}\n" for path in files),
        encoding="utf-8",
    )
    return manifest


def package_output(root: Path) -> tuple[Path, Path]:
    archive = Path(str(root) + ".zip")
    sidecar = Path(str(archive) + ".sha256")
    temporary = Path(str(archive) + ".tmp")
    if temporary.exists():
        temporary.unlink()
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            handle.write(path, f"{root.name}/{path.relative_to(root).as_posix()}")
    temporary.replace(archive)
    sidecar.write_text(f"{sha256(archive)}  {archive.name}\n", encoding="utf-8")
    return archive, sidecar


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--memory", default="8GB")
    parser.add_argument("--batch-rows", type=int, default=32768)
    parser.add_argument("--payoff-limit", type=float, default=5.0)
    parser.add_argument("--bin-width", type=float, default=0.25)
    parser.add_argument("--local-bandwidth", type=float, default=1.0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--validate-authority", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 1 <= args.threads <= 10:
        raise SystemExit("--threads must be between 1 and 10")
    if args.batch_rows < 4096:
        raise SystemExit("--batch-rows must be at least 4096")
    if args.local_bandwidth <= 0 or args.local_bandwidth >= args.payoff_limit:
        raise SystemExit("Require 0 < local-bandwidth < payoff-limit")
    if not args.smoke_test and args.panel is None:
        raise SystemExit("--panel is required outside --smoke-test")
    spec = bin_spec(args.payoff_limit, args.bin_width)
    if args.out.exists() and not args.resume:
        raise SystemExit(f"Output exists: {args.out}; use --resume or a fresh run ID")
    if args.private.exists() and not args.resume:
        raise SystemExit(f"Private output exists: {args.private}; use --resume or a fresh run ID")
    args.out.mkdir(parents=True, exist_ok=True)
    args.private.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    started_at = utc_now()
    print(f"CONTROLLED_REFERENCE_PRICE_FIGURE_START version={VERSION} at {started_at}", flush=True)
    print(
        "Estimand: draw payoff r_G as the reference-dependent price, conditional on "
        "flexible relative-strength and state controls; chooser-by-pool FE and "
        "chooser-clustered inference.",
        flush=True,
    )

    if args.smoke_test:
        broad_cache, local_cache, stage_info = make_smoke_caches(
            args.out, args.private, spec, args.local_bandwidth
        )
    else:
        broad_cache, local_cache, stage_info = stage_certified_panel(
            args.panel,
            args.out,
            args.private,
            spec,
            args.local_bandwidth,
            args.threads,
            args.memory,
            args.resume,
            args.validate_authority,
        )

    total_bins = 2 * int(spec["side_bins"]) + 1
    broad_factory = frame_factory(
        broad_cache, args.batch_rows, args.memory, args.private / "broad_model_spill"
    )
    local_factory = frame_factory(
        local_cache, args.batch_rows, args.memory, args.private / "local_model_spill"
    )
    print(
        f"Fitting {total_bins} draw-payoff bins with flexible gap/expected-score controls.",
        flush=True,
    )
    bin_model = fit_within_model(
        broad_factory,
        lambda frame: make_bin_design(frame, spec),
        lambda names: [name for name in names if name.startswith("bin_")],
        "controlled_reference_price_bins",
        code_count=total_bins,
        must_retain_names=CORE_CONTROLS_REQUIRED,
    )
    bins = adjusted_bin_table(bin_model, spec)
    print("Fitting the frozen v1.0.1 local bridge for data-lineage authentication.", flush=True)
    bridge_model = fit_within_model(
        local_factory,
        make_legacy_local_design,
        lambda names: ["left", "right", "jump", "tie"],
        "legacy_v101_local_h1_bridge",
    )
    bridge_results, bridge_contrasts = local_summary(bridge_model)
    if args.validate_authority and not args.smoke_test:
        authentication = authenticate_local_result(bridge_model, bridge_contrasts)
    else:
        authentication = {"status": "NOT_REQUESTED_OR_SYNTHETIC"}

    print("Fitting controlled local reference-price slopes on the underlying h=1 observations.", flush=True)
    local_model = fit_within_model(
        local_factory,
        make_local_design,
        lambda names: ["left", "right", "jump", "tie"],
        "controlled_reference_price_local_h1",
        must_retain_names=CORE_CONTROLS_REQUIRED,
    )
    local_results, local_contrasts = local_summary(local_model)
    fit_grid, display_anchor = local_fit_grid(bins, local_model, args.local_bandwidth)

    table_dir = args.out / "tables"
    export_frame(bins, table_dir, "controlled_reference_price_bins")
    export_frame(local_results, table_dir, "controlled_local_h1_results")
    export_frame(fit_grid, table_dir, "controlled_local_h1_display_fit")
    export_frame(bridge_results, table_dir, "legacy_v101_bridge_h1_results")
    export_frame(coefficient_table(bin_model), table_dir, "controlled_reference_price_bin_coefficients")
    export_frame(coefficient_table(local_model), table_dir, "controlled_local_h1_coefficients")
    export_frame(coefficient_table(bridge_model), table_dir, "legacy_v101_bridge_h1_coefficients")
    outputs = draw_figure(
        bins,
        fit_grid,
        local_contrasts,
        spec,
        args.local_bandwidth,
        args.out / "figures",
    )
    write_caption(args.out / "CAPTION_DRAFT.tex", spec, args.local_bandwidth)
    receipt = {
        "status": "CONTROLLED_REFERENCE_PRICE_FIGURE_COMPLETE",
        "version": VERSION,
        "started_at": started_at,
        "completed_at": utc_now(),
        "elapsed_seconds": time.monotonic() - started,
        "synthetic_smoke_test": bool(args.smoke_test),
        "panel": None if args.smoke_test else str(args.panel.resolve()),
        "public_output": str(args.out.resolve()),
        "private_output": str(args.private.resolve()),
        "settings": {
            "threads": args.threads,
            "memory": args.memory,
            "batch_rows": args.batch_rows,
            "payoff_limit": args.payoff_limit,
            "bin_width": args.bin_width,
            "local_bandwidth": args.local_bandwidth,
        },
        "sample": stage_info,
        "estimand": {
            "horizontal_axis": "chooser draw payoff r_G in rating points",
            "interpretation": "reference-dependent draw price conditional on a smooth relative-strength counterfactual",
            "relative_strength_controls": "continuous piecewise-linear splines in displayed rating gap and expected-score imbalance; no zero knot",
            "control_blocks": CONTROL_BLOCKS,
        },
        "bin_model": {
            "stats": bin_model["stats"],
            "condition": bin_model["condition"],
            "dropped_terms": bin_model["dropped"],
            "normalization": "frequency-weighted adjusted bin mean equals fitted-sample outcome mean",
        },
        "local_model": {
            "stats": local_model["stats"],
            "condition": local_model["condition"],
            "dropped_terms": local_model["dropped"],
            "contrasts": local_contrasts,
            "display_anchor_pct": display_anchor,
        },
        "legacy_bridge_model": {
            "stats": bridge_model["stats"],
            "condition": bridge_model["condition"],
            "dropped_terms": bridge_model["dropped"],
            "contrasts": bridge_contrasts,
            "used_for_figure": False,
        },
        "authentication": authentication,
        "inference": "Chooser-clustered CR1 normal intervals conditional on the finite model; not CCT bias-corrected inference.",
        "privacy": {
            "public_output_is_aggregate_only": True,
            "private_cache_contains_chooser_and_game_ids": True,
            "private_cache_is_excluded_from_archive": True,
        },
        "figure_files": [str(path.relative_to(args.out)) for path in outputs],
        "code_sha256": sha256(Path(__file__)),
        "python": sys.version,
        "versions": {
            "duckdb": duckdb.__version__,
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "matplotlib": mpl.__version__,
        },
    }
    receipts = args.out / "receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    write_json(receipts / "completion_receipt.json", receipt)
    shutil.copy2(Path(__file__), receipts / "executed_controlled_reference_price_figure.py")
    write_manifest(args.out)
    archive, sidecar = package_output(args.out)
    print("CONTROLLED_REFERENCE_PRICE_FIGURE_COMPLETE", flush=True)
    print(f"OUTPUT: {args.out}", flush=True)
    print(f"ZIP: {archive}", flush=True)
    print(f"SHA256: {sidecar}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
