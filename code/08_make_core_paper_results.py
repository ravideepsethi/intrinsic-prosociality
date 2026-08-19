#!/usr/bin/env python3
"""Build certified panel-only paper results from the frozen Stage 07 panel.

Stage 08 deliberately has a narrow authority boundary.  It reads only the
certified 24-month Stage 07 analysis panel and produces the paper displays that
can be identified from that panel alone.  Patron/profile, opening-familiarity,
reentry, post-sample holdout, and historical rating-rule analyses are excluded
because they require separately frozen inputs.

The script is dry-run by default.  Pass --execute to build into a new,
transactional output root.  It never overwrites an existing output root.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import time
import traceback
from collections import OrderedDict
from pathlib import Path
from typing import Any, Iterable, Sequence

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


SCRIPT_VERSION = "1.1.0"

PROJECT = Path("/Volumes/XT_Pro/lichess_kindness")
REPOSITORY = PROJECT / "replication_package"
PANEL_ROOT = PROJECT / "derived/replication/analysis_panel_24m_sf100k"
DEFAULT_OUTPUT_ROOT = PROJECT / "derived/replication/paper_results_core_24m_sf100k"

EXPECTED_STAGE07_SCRIPT_SHA256 = (
    "0411d4061ea9831c20449208a9782aaf668e160139918d106a2b7d63aaa56e6e"
)
EXPECTED_STAGE07_GIT_HEAD = "b73a7fbaf25ecd063d842bbc36f4efed7cd9ab24"
EXPECTED_STAGE07_FINAL_PROVENANCE_HEAD = "de308b272dc16f25bb64f18c6f8676ee59db221b"
EXPECTED_STAGE07_SUMMARY_SHA256 = (
    "8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7"
)
EXPECTED_STAGE07_STATUS = "STAGE07_24M_CERTIFIED_OK"
EXPECTED_STAGE07_ROWS = 47_587_020
EXPECTED_STAGE07_KIND_DRAWS = 669_503
EXPECTED_STAGE07_COLUMNS = 157

MONTH_ROWS = OrderedDict(
    [
        ("2023-11", 2_015_809),
        ("2023-12", 2_101_110),
        ("2024-01", 2_049_292),
        ("2024-02", 1_931_143),
        ("2024-03", 2_021_798),
        ("2024-04", 1_917_136),
        ("2024-05", 2_011_399),
        ("2024-06", 1_903_139),
        ("2024-07", 1_893_461),
        ("2024-08", 1_923_975),
        ("2024-09", 1_832_046),
        ("2024-10", 1_990_765),
        ("2024-11", 1_892_495),
        ("2024-12", 2_036_228),
        ("2025-01", 2_050_213),
        ("2025-02", 1_894_447),
        ("2025-03", 2_100_718),
        ("2025-04", 2_004_376),
        ("2025-05", 2_072_890),
        ("2025-06", 2_042_105),
        ("2025-07", 2_091_678),
        ("2025-08", 1_930_170),
        ("2025-09", 1_881_564),
        ("2025-10", 1_999_063),
    ]
)
ALL_MONTHS = tuple(MONTH_ROWS)

TABLE2_BANDWIDTHS = (0.5, 1.0, 2.0, 4.0, 6.0)
LOCAL_WINDOWS: tuple[float | None, ...] = (0.5, 1.0, 2.0, None)
PLACEBO_CUTOFFS = (-1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1.0)
PLACEBO_WINDOWS = (0.5, 1.0)
SPLIT_MIN_OPPORTUNITIES = (2, 4, 5, 10)

REQUIRED_COLUMNS = (
    "month",
    "game_id",
    "archive_ordinal",
    "chooser_username_norm",
    "kind_draw",
    "engine_eval_cp_disconnected",
    "engine_fairness_bin",
    "fair_competitive",
    "clearly_worse",
    "excluded_middle",
    "chooser_draw_payoff_v2",
    "chooser_win_premium_v2",
    "draw_nonnegative",
    "draw_strict_positive",
    "draw_costly",
    "api_speed",
    "chooser_elo",
    "disconnected_elo",
    "avg_rating",
    "rating_gap",
    "tournament_like_event",
    "chooser_clock_last_obs_s",
    "disconnected_clock_last_obs_s",
)

DISPLAY_ORDER = (
    "disconnected_clearly_better",
    "disconnected_better",
    "roughly_equal",
    "modestly_worse_excluded",
    "clearly_worse",
)

FINE_EVAL_ORDER = (
    "le_minus1000",
    "minus999_to_minus600",
    "minus599_to_minus300",
    "minus299_to_minus101",
    "minus100_to_minus1",
    "zero_to_100",
    "101_to_300",
    "301_to_600",
    "601_to_1000",
    "ge_1001",
)


def utc_now() -> str:
    return pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def progress(message: str) -> None:
    print(f"[{utc_now()}] {message}", flush=True)


def sha256_file(path: Path, chunk_size: int = 16 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(
        path,
        json.dumps(json_sanitize(value), indent=2, sort_keys=True, allow_nan=False) + "\n",
    )


def json_sanitize(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, dict):
        return {str(key): json_sanitize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_sanitize(item) for item in value]
    if isinstance(value, np.ndarray):
        return [json_sanitize(item) for item in value.tolist()]
    if hasattr(value, "item"):
        return json_sanitize(value.item())
    raise TypeError(f"Value is not JSON serializable: {type(value).__name__}")


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    frame.to_csv(
        temporary,
        index=False,
        lineterminator="\n",
        float_format="%.15g",
    )
    os.replace(temporary, path)


def run_git(*args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(REPOSITORY), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout.strip()


def git_state() -> dict[str, Any]:
    return {
        "head": run_git("rev-parse", "HEAD"),
        "branch": run_git("branch", "--show-current"),
        "status_porcelain": run_git("status", "--porcelain=v1"),
        "remote_url": run_git("remote", "get-url", "origin"),
    }


def parse_months(value: str) -> tuple[str, ...]:
    if value.strip().lower() in {"all", "24m", "full"}:
        return ALL_MONTHS
    months = tuple(part.strip() for part in value.split(",") if part.strip())
    if not months:
        raise ValueError("--months selected no months")
    unknown = [month for month in months if month not in MONTH_ROWS]
    if unknown:
        raise ValueError(f"Unknown month(s): {unknown}")
    if len(set(months)) != len(months):
        raise ValueError("--months contains duplicates")
    canonical = tuple(month for month in ALL_MONTHS if month in set(months))
    if months != canonical:
        raise ValueError("--months must be in canonical chronological order")
    return months


def safe_json_number(value: float | int | np.number | None) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, (int, np.integer)):
        return int(value)
    number = float(value)
    return number if math.isfinite(number) else None


def sql_path_list(paths: Sequence[Path]) -> str:
    quoted = ["'" + str(path).replace("'", "''") + "'" for path in paths]
    return "[" + ",".join(quoted) + "]"


def expected_output_schema_names(summary: dict[str, Any]) -> list[str]:
    schema = summary.get("output_schema")
    if isinstance(schema, list):
        names: list[str] = []
        for item in schema:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict) and "name" in item:
                names.append(str(item["name"]))
        return names
    return []


def authenticate_stage07(months: Sequence[str], verify_hashes: bool) -> dict[str, Any]:
    success = PANEL_ROOT / "_SUCCESS.json"
    month_status_path = PANEL_ROOT / "_manifests/month_status.csv"
    producer = REPOSITORY / "code/07_build_analysis_panel.py"

    for path in (PANEL_ROOT, success, month_status_path, producer):
        if not path.exists():
            raise RuntimeError(f"Required frozen Stage 07 artifact is missing: {path}")

    success_sha = sha256_file(success)
    if success_sha != EXPECTED_STAGE07_SUMMARY_SHA256:
        raise RuntimeError(
            "Stage 07 global summary SHA changed: "
            f"expected={EXPECTED_STAGE07_SUMMARY_SHA256} actual={success_sha}"
        )
    producer_sha = sha256_file(producer)
    if producer_sha != EXPECTED_STAGE07_SCRIPT_SHA256:
        raise RuntimeError(
            "Stage 07 producer SHA changed: "
            f"expected={EXPECTED_STAGE07_SCRIPT_SHA256} actual={producer_sha}"
        )

    summary = json.loads(success.read_text(encoding="utf-8"))
    if summary.get("status") != EXPECTED_STAGE07_STATUS:
        raise RuntimeError(f"Stage 07 status is not certified: {summary.get('status')}")
    if int(summary.get("global_qa", {}).get("rows", -1)) != EXPECTED_STAGE07_ROWS:
        raise RuntimeError("Stage 07 global row total changed")
    if int(summary.get("global_qa", {}).get("kind_draws", -1)) != EXPECTED_STAGE07_KIND_DRAWS:
        raise RuntimeError("Stage 07 global kind-draw total changed")
    if str(summary.get("script_sha256")) != EXPECTED_STAGE07_SCRIPT_SHA256:
        raise RuntimeError("Stage 07 summary references a different producer")
    if str(summary.get("git_head")) != EXPECTED_STAGE07_GIT_HEAD:
        raise RuntimeError("Stage 07 summary references an unexpected production Git HEAD")

    schema_names = expected_output_schema_names(summary)
    if schema_names and len(schema_names) != EXPECTED_STAGE07_COLUMNS:
        raise RuntimeError(
            f"Stage 07 summary schema count changed: {len(schema_names)} != {EXPECTED_STAGE07_COLUMNS}"
        )
    if schema_names:
        missing = [column for column in REQUIRED_COLUMNS if column not in schema_names]
        if missing:
            raise RuntimeError(f"Stage 07 summary schema lacks core columns: {missing}")

    status = pd.read_csv(month_status_path)
    required_status = {"month", "rows", "output_sha256", "output_size_bytes", "status"}
    if not required_status.issubset(status.columns):
        raise RuntimeError(
            f"Stage 07 month-status columns changed: missing={sorted(required_status - set(status.columns))}"
        )
    if len(status) != 24 or status["month"].astype(str).tolist() != list(ALL_MONTHS):
        raise RuntimeError("Stage 07 month-status does not contain the canonical 24 months in order")

    records: list[dict[str, Any]] = []
    for month in months:
        row = status.loc[status["month"].astype(str) == month]
        if len(row) != 1:
            raise RuntimeError(f"Stage 07 month-status has {len(row)} rows for {month}")
        item = row.iloc[0]
        path = PANEL_ROOT / f"month={month}/analysis_panel.parquet"
        if not path.is_file():
            raise RuntimeError(f"Stage 07 monthly panel missing: {path}")
        expected_rows = MONTH_ROWS[month]
        if int(item["rows"]) != expected_rows:
            raise RuntimeError(f"Stage 07 month-status row count changed for {month}")
        if str(item["status"]) != "STAGE07_MONTH_CERTIFIED_OK":
            raise RuntimeError(f"Stage 07 month is not certified: {month} status={item['status']}")
        if int(item["output_size_bytes"]) != path.stat().st_size:
            raise RuntimeError(f"Stage 07 file size changed for {month}")
        parquet = pq.ParquetFile(path)
        if parquet.metadata.num_rows != expected_rows:
            raise RuntimeError(f"Stage 07 Parquet metadata row count changed for {month}")
        names = parquet.schema_arrow.names
        missing = [column for column in REQUIRED_COLUMNS if column not in names]
        if missing:
            raise RuntimeError(f"{month} panel lacks core columns: {missing}")
        if len(names) != EXPECTED_STAGE07_COLUMNS:
            raise RuntimeError(f"{month} panel has {len(names)} columns, expected 157")
        records.append(
            {
                "month": month,
                "path": path,
                "rows": expected_rows,
                "size_bytes": path.stat().st_size,
                "expected_sha256": str(item["output_sha256"]),
            }
        )

    if verify_hashes:
        workers = min(4, len(records))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(sha256_file, record["path"]): record for record in records}
            for future in concurrent.futures.as_completed(futures):
                record = futures[future]
                actual = future.result()
                if actual != record["expected_sha256"]:
                    raise RuntimeError(
                        f"Stage 07 monthly SHA changed for {record['month']}: "
                        f"expected={record['expected_sha256']} actual={actual}"
                    )
                record["actual_sha256"] = actual

    return {
        "success_path": str(success),
        "success_sha256": success_sha,
        "producer_path": str(producer),
        "producer_sha256": producer_sha,
        "summary": summary,
        "month_records": records,
        "selected_rows": sum(record["rows"] for record in records),
        "selected_bytes": sum(record["size_bytes"] for record in records),
    }


def software_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "duckdb": duckdb.__version__,
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "pyarrow": pa.__version__,
    }


def month_index_case() -> str:
    clauses = [f"WHEN month = '{month}' THEN {index}" for index, month in enumerate(ALL_MONTHS)]
    return "CASE " + " ".join(clauses) + " ELSE NULL END"


def create_core_database(
    database_path: Path,
    paths: Sequence[Path],
    threads: int,
    memory_limit: str,
    temporary_directory: Path,
) -> tuple[duckdb.DuckDBPyConnection, dict[str, Any]]:
    temporary_directory.mkdir(parents=True, exist_ok=True)
    database = duckdb.connect(str(database_path))
    database.execute(f"PRAGMA threads={int(threads)}")
    database.execute(f"PRAGMA memory_limit='{memory_limit}'")
    database.execute(f"PRAGMA temp_directory='{str(temporary_directory).replace(chr(39), chr(39) * 2)}'")
    database.execute("PRAGMA preserve_insertion_order=false")

    paths_literal = sql_path_list(paths)
    database.execute(
        f"CREATE VIEW panel AS SELECT * FROM read_parquet({paths_literal}, union_by_name=false)"
    )

    base = database.execute(
        """
        SELECT
          COUNT(*)::BIGINT AS rows,
          COUNT(DISTINCT month)::BIGINT AS months,
          SUM(CASE WHEN kind_draw THEN 1 ELSE 0 END)::BIGINT AS kind_draws,
          SUM(CASE WHEN chooser_username_norm IS NULL OR trim(chooser_username_norm) = '' THEN 1 ELSE 0 END)::BIGINT AS missing_chooser,
          SUM(CASE WHEN engine_eval_cp_disconnected IS NULL THEN 1 ELSE 0 END)::BIGINT AS missing_eval,
          SUM(CASE WHEN chooser_draw_payoff_v2 IS NULL THEN 1 ELSE 0 END)::BIGINT AS missing_draw_payoff,
          SUM(CASE WHEN chooser_win_premium_v2 IS NULL THEN 1 ELSE 0 END)::BIGINT AS missing_win_premium
        FROM panel
        """
    ).fetchdf().iloc[0].to_dict()
    for field in ("missing_chooser", "missing_eval", "missing_draw_payoff", "missing_win_premium"):
        if int(base[field]) != 0:
            raise RuntimeError(f"Core Stage 08 input coverage failure: {field}={int(base[field]):,}")

    database.execute(
        """
        CREATE TABLE chooser_dimension AS
        SELECT
          chooser_username_norm,
          (ROW_NUMBER() OVER (ORDER BY chooser_username_norm) - 1)::INTEGER AS chooser_fe_id
        FROM (SELECT DISTINCT chooser_username_norm FROM panel)
        ORDER BY chooser_username_norm
        """
    )

    month_case = month_index_case()
    database.execute(
        f"""
        CREATE TABLE core AS
        SELECT
          p.month::VARCHAR AS month,
          ({month_case})::SMALLINT AS month_index,
          p.archive_ordinal::BIGINT AS archive_ordinal,
          d.chooser_fe_id,
          CASE WHEN lower(right(md5(p.game_id), 1)) IN ('1','3','5','7','9','b','d','f') THEN 1 ELSE 0 END::TINYINT AS game_hash_half,
          CASE WHEN ({month_case}) < 12 THEN 0 ELSE 1 END::TINYINT AS temporal_half,
          CASE WHEN p.kind_draw THEN 100.0 ELSE 0.0 END::DOUBLE AS kind_pp,
          p.engine_eval_cp_disconnected::DOUBLE AS eval_cp,
          (greatest(-100.0, least(600.0, p.engine_eval_cp_disconnected::DOUBLE)) / 100.0)::DOUBLE AS eval_100_capped,
          p.engine_fairness_bin::VARCHAR AS fairness_bin,
          p.fair_competitive::BOOLEAN AS fair,
          p.clearly_worse::BOOLEAN AS clearly_worse,
          p.excluded_middle::BOOLEAN AS excluded_middle,
          p.chooser_draw_payoff_v2::DOUBLE AS draw_payoff,
          abs(p.chooser_draw_payoff_v2::DOUBLE)::DOUBLE AS abs_draw_payoff,
          greatest(p.chooser_draw_payoff_v2::DOUBLE, 0.0)::DOUBLE AS pos_draw_payoff,
          greatest(-p.chooser_draw_payoff_v2::DOUBLE, 0.0)::DOUBLE AS neg_draw_payoff,
          p.chooser_win_premium_v2::DOUBLE AS win_premium,
          CASE WHEN p.draw_nonnegative THEN 1.0 ELSE 0.0 END::DOUBLE AS favorable,
          CASE WHEN p.draw_strict_positive THEN 1.0 ELSE 0.0 END::DOUBLE AS strict_positive,
          CASE WHEN p.draw_costly THEN 1.0 ELSE 0.0 END::DOUBLE AS costly,
          lower(p.api_speed::VARCHAR)::VARCHAR AS speed,
          CASE
            WHEN lower(p.api_speed::VARCHAR) IN ('ultrabullet','bullet') THEN 'bullet_ultra'
            WHEN lower(p.api_speed::VARCHAR) = 'blitz' THEN 'blitz'
            WHEN lower(p.api_speed::VARCHAR) = 'rapid' THEN 'rapid'
            WHEN lower(p.api_speed::VARCHAR) = 'classical' THEN 'classical_long'
            ELSE 'other'
          END::VARCHAR AS speed_tier,
          p.chooser_elo::DOUBLE AS chooser_elo,
          p.disconnected_elo::DOUBLE AS disconnected_elo,
          p.avg_rating::DOUBLE AS avg_rating,
          p.rating_gap::DOUBLE AS rating_gap,
          CASE
            WHEN p.chooser_elo IS NULL THEN 'missing'
            WHEN p.chooser_elo < 1600 THEN 'below_1600'
            WHEN p.chooser_elo < 2000 THEN '1600_1999'
            WHEN p.chooser_elo < 2400 THEN '2000_2399'
            ELSE '2400_plus'
          END::VARCHAR AS chooser_rating_tier,
          p.tournament_like_event::BOOLEAN AS tournament_like,
          p.chooser_clock_last_obs_s::DOUBLE AS chooser_clock_s,
          p.disconnected_clock_last_obs_s::DOUBLE AS disconnected_clock_s,
          CASE WHEN p.chooser_clock_last_obs_s IS NULL THEN NULL ELSE ln(1.0 + greatest(p.chooser_clock_last_obs_s::DOUBLE, 0.0)) END::DOUBLE AS log_chooser_clock,
          CASE WHEN p.disconnected_clock_last_obs_s IS NULL THEN NULL ELSE ln(1.0 + greatest(p.disconnected_clock_last_obs_s::DOUBLE, 0.0)) END::DOUBLE AS log_disconnected_clock,
          CASE
            WHEN p.chooser_clock_last_obs_s IS NULL OR p.disconnected_clock_last_obs_s IS NULL THEN NULL
            ELSE ln(1.0 + greatest(p.chooser_clock_last_obs_s::DOUBLE, 0.0))
               - ln(1.0 + greatest(p.disconnected_clock_last_obs_s::DOUBLE, 0.0))
          END::DOUBLE AS log_clock_ratio
        FROM panel p
        JOIN chooser_dimension d USING (chooser_username_norm)
        """
    )
    database.execute("ANALYZE core")

    core = database.execute(
        """
        SELECT
          COUNT(*)::BIGINT AS rows,
          COUNT(DISTINCT chooser_fe_id)::BIGINT AS choosers,
          SUM(CASE WHEN kind_pp = 100 THEN 1 ELSE 0 END)::BIGINT AS kind_draws,
          SUM(fair::INTEGER)::BIGINT AS fair_rows,
          SUM(clearly_worse::INTEGER)::BIGINT AS clearly_worse_rows,
          SUM(excluded_middle::INTEGER)::BIGINT AS excluded_middle_rows,
          SUM(CASE WHEN favorable = 1 THEN 1 ELSE 0 END)::BIGINT AS nonnegative_rows,
          SUM(CASE WHEN strict_positive = 1 THEN 1 ELSE 0 END)::BIGINT AS strict_positive_rows,
          SUM(CASE WHEN costly = 1 THEN 1 ELSE 0 END)::BIGINT AS costly_rows
        FROM core
        """
    ).fetchdf().iloc[0].to_dict()
    if int(core["rows"]) != int(base["rows"]) or int(core["kind_draws"]) != int(base["kind_draws"]):
        raise RuntimeError("Core cache changed Stage 07 row or outcome totals")
    if int(core["fair_rows"]) + int(core["clearly_worse_rows"]) + int(core["excluded_middle_rows"]) != int(core["rows"]):
        raise RuntimeError("Fairness regions do not partition the selected sample")
    if int(core["nonnegative_rows"]) + int(core["costly_rows"]) != int(core["rows"]):
        raise RuntimeError("Draw-payoff sign does not partition the selected sample")

    return database, {
        "source": {key: int(value) for key, value in base.items()},
        "core": {key: int(value) for key, value in core.items()},
    }


def binomial_se_pp(kind_draws: float, rows: float) -> float:
    if rows <= 0:
        return math.nan
    p = kind_draws / rows
    return 100.0 * math.sqrt(max(p * (1.0 - p) / rows, 0.0))


def add_rates(frame: pd.DataFrame, rows: str = "rows", kinds: str = "kind_draws") -> pd.DataFrame:
    result = frame.copy()
    result["kind_rate"] = result[kinds] / result[rows]
    result["kind_rate_pct"] = 100.0 * result["kind_rate"]
    result["binomial_se_pp"] = [
        binomial_se_pp(float(k), float(n)) for k, n in zip(result[kinds], result[rows])
    ]
    return result


def descriptive_outputs(database: duckdb.DuckDBPyConnection, root: Path) -> dict[str, Any]:
    tables = root / "tables"
    figure_data = root / "figure_data"

    overall = database.execute(
        """
        SELECT COUNT(*)::BIGINT AS rows,
               SUM(CASE WHEN kind_pp=100 THEN 1 ELSE 0 END)::BIGINT AS kind_draws,
               COUNT(DISTINCT chooser_fe_id)::BIGINT AS choosers
        FROM core
        """
    ).fetchdf()
    overall = add_rates(overall)
    write_csv(tables / "sample_overall.csv", overall)

    monthly = database.execute(
        """
        SELECT month, month_index, COUNT(*)::BIGINT AS rows,
               SUM(CASE WHEN kind_pp=100 THEN 1 ELSE 0 END)::BIGINT AS kind_draws,
               COUNT(DISTINCT chooser_fe_id)::BIGINT AS choosers
        FROM core GROUP BY month, month_index ORDER BY month_index
        """
    ).fetchdf()
    monthly = add_rates(monthly)
    write_csv(tables / "sample_by_month.csv", monthly)

    speed = database.execute(
        """
        SELECT speed, speed_tier, COUNT(*)::BIGINT AS rows,
               SUM(CASE WHEN kind_pp=100 THEN 1 ELSE 0 END)::BIGINT AS kind_draws,
               COUNT(DISTINCT chooser_fe_id)::BIGINT AS choosers
        FROM core GROUP BY speed, speed_tier ORDER BY speed_tier, speed
        """
    ).fetchdf()
    speed = add_rates(speed)
    write_csv(tables / "sample_by_speed.csv", speed)

    rating = database.execute(
        """
        SELECT chooser_rating_tier, COUNT(*)::BIGINT AS rows,
               SUM(CASE WHEN kind_pp=100 THEN 1 ELSE 0 END)::BIGINT AS kind_draws,
               COUNT(DISTINCT chooser_fe_id)::BIGINT AS choosers
        FROM core GROUP BY chooser_rating_tier
        ORDER BY CASE chooser_rating_tier WHEN 'below_1600' THEN 1 WHEN '1600_1999' THEN 2 WHEN '2000_2399' THEN 3 WHEN '2400_plus' THEN 4 ELSE 5 END
        """
    ).fetchdf()
    rating = add_rates(rating)
    write_csv(tables / "sample_by_chooser_rating_tier.csv", rating)

    table01 = database.execute(
        """
        SELECT fairness_bin, COUNT(*)::BIGINT AS rows,
               SUM(CASE WHEN kind_pp=100 THEN 1 ELSE 0 END)::BIGINT AS kind_draws
        FROM core GROUP BY fairness_bin
        ORDER BY CASE fairness_bin
          WHEN 'disconnected_clearly_better' THEN 1
          WHEN 'disconnected_better' THEN 2
          WHEN 'roughly_equal' THEN 3
          WHEN 'modestly_worse_excluded' THEN 4
          WHEN 'clearly_worse' THEN 5 ELSE 6 END
        """
    ).fetchdf()
    table01 = add_rates(table01)
    if table01["fairness_bin"].tolist() != list(DISPLAY_ORDER):
        raise RuntimeError("Table 1 fairness-bin labels/order changed")
    write_csv(tables / "table01_fairness_bins.csv", table01)

    regions = database.execute(
        """
        SELECT region, COUNT(*)::BIGINT AS rows,
               SUM(CASE WHEN kind_pp=100 THEN 1 ELSE 0 END)::BIGINT AS kind_draws
        FROM (
          SELECT *, CASE WHEN fair THEN 'fair_competitive' WHEN clearly_worse THEN 'clearly_worse' ELSE 'excluded_middle' END AS region
          FROM core
        ) q
        GROUP BY region
        ORDER BY CASE region WHEN 'fair_competitive' THEN 1 WHEN 'excluded_middle' THEN 2 ELSE 3 END
        """
    ).fetchdf()
    regions = add_rates(regions)
    fair_rate = float(regions.loc[regions.region == "fair_competitive", "kind_rate"].iloc[0])
    worse_rate = float(regions.loc[regions.region == "clearly_worse", "kind_rate"].iloc[0])
    regions["fair_over_clearly_worse_ratio"] = math.nan
    regions["fair_minus_clearly_worse_pp"] = math.nan
    regions.loc[regions.region == "fair_competitive", "fair_over_clearly_worse_ratio"] = fair_rate / worse_rate
    regions.loc[regions.region == "fair_competitive", "fair_minus_clearly_worse_pp"] = 100.0 * (fair_rate - worse_rate)
    write_csv(tables / "fair_vs_clearly_worse.csv", regions)

    table06 = database.execute(
        """
        SELECT
          CASE
            WHEN fair AND favorable=0 THEN 'A'
            WHEN clearly_worse AND favorable=1 THEN 'B'
            WHEN fair AND favorable=1 THEN 'C'
            WHEN clearly_worse AND favorable=0 THEN 'D'
          END AS cell,
          CASE
            WHEN fair AND favorable=0 THEN 'fair_competitive_costly'
            WHEN clearly_worse AND favorable=1 THEN 'clearly_worse_favorable'
            WHEN fair AND favorable=1 THEN 'fair_competitive_favorable'
            WHEN clearly_worse AND favorable=0 THEN 'clearly_worse_costly'
          END AS description,
          COUNT(*)::BIGINT AS rows,
          SUM(CASE WHEN kind_pp=100 THEN 1 ELSE 0 END)::BIGINT AS kind_draws
        FROM core WHERE fair OR clearly_worse
        GROUP BY cell, description ORDER BY cell
        """
    ).fetchdf()
    table06 = add_rates(table06)
    write_csv(tables / "table06_fairness_price_2x2.csv", table06)

    contrasts: list[dict[str, Any]] = []
    for region_name, costly_cell, favorable_cell in (
        ("fair_competitive", "A", "C"),
        ("clearly_worse", "D", "B"),
    ):
        costly = table06.loc[table06.cell == costly_cell].iloc[0]
        favorable = table06.loc[table06.cell == favorable_cell].iloc[0]
        p0, p1 = float(costly.kind_rate), float(favorable.kind_rate)
        n0, n1 = int(costly.rows), int(favorable.rows)
        se = math.sqrt(p0 * (1 - p0) / n0 + p1 * (1 - p1) / n1)
        contrasts.append(
            {
                "region": region_name,
                "costly_rows": n0,
                "favorable_rows": n1,
                "costly_rate_pct": 100 * p0,
                "favorable_rate_pct": 100 * p1,
                "favorable_minus_costly_pp": 100 * (p1 - p0),
                "se_pp": 100 * se,
                "t": (p1 - p0) / se,
            }
        )
    contrast_frame = pd.DataFrame(contrasts)
    write_csv(tables / "table06_fairness_price_contrasts.csv", contrast_frame)

    fine = database.execute(
        """
        WITH binned AS (
          SELECT *, CASE
            WHEN eval_cp <= -1000 THEN 'le_minus1000'
            WHEN eval_cp <= -600 THEN 'minus999_to_minus600'
            WHEN eval_cp <= -300 THEN 'minus599_to_minus300'
            WHEN eval_cp <= -101 THEN 'minus299_to_minus101'
            WHEN eval_cp <= -1 THEN 'minus100_to_minus1'
            WHEN eval_cp <= 100 THEN 'zero_to_100'
            WHEN eval_cp <= 300 THEN '101_to_300'
            WHEN eval_cp <= 600 THEN '301_to_600'
            WHEN eval_cp <= 1000 THEN '601_to_1000'
            ELSE 'ge_1001' END AS eval_bin
          FROM core
        )
        SELECT eval_bin, favorable::INTEGER AS favorable,
               COUNT(*)::BIGINT AS rows,
               SUM(CASE WHEN kind_pp=100 THEN 1 ELSE 0 END)::BIGINT AS kind_draws
        FROM binned GROUP BY eval_bin, favorable
        ORDER BY CASE eval_bin
          WHEN 'le_minus1000' THEN 1 WHEN 'minus999_to_minus600' THEN 2
          WHEN 'minus599_to_minus300' THEN 3 WHEN 'minus299_to_minus101' THEN 4
          WHEN 'minus100_to_minus1' THEN 5 WHEN 'zero_to_100' THEN 6
          WHEN '101_to_300' THEN 7 WHEN '301_to_600' THEN 8
          WHEN '601_to_1000' THEN 9 ELSE 10 END, favorable
        """
    ).fetchdf()
    fine = add_rates(fine)
    wide = fine.pivot(index="eval_bin", columns="favorable", values=["rows", "kind_draws", "kind_rate_pct", "binomial_se_pp"])
    wide.columns = [f"{name}_{'favorable' if int(side) == 1 else 'costly'}" for name, side in wide.columns]
    wide = wide.reindex(FINE_EVAL_ORDER).reset_index()
    wide["favorable_minus_costly_pp"] = wide["kind_rate_pct_favorable"] - wide["kind_rate_pct_costly"]
    wide["gap_se_pp"] = np.sqrt(wide["binomial_se_pp_favorable"] ** 2 + wide["binomial_se_pp_costly"] ** 2)
    write_csv(figure_data / "figure03_favorable_minus_costly_by_eval_bin.csv", wide)
    write_csv(tables / "tableA12_eval_bin_price_support.csv", wide)

    clock_case = """
      CASE
        WHEN disconnected_clock_s < 1 THEN '0_1s'
        WHEN disconnected_clock_s < 2 THEN '1_2s'
        WHEN disconnected_clock_s < 3 THEN '2_3s'
        WHEN disconnected_clock_s < 5 THEN '3_5s'
        WHEN disconnected_clock_s < 10 THEN '5_10s'
        WHEN disconnected_clock_s < 20 THEN '10_20s'
        WHEN disconnected_clock_s < 30 THEN '20_30s'
        WHEN disconnected_clock_s < 60 THEN '30_60s'
        WHEN disconnected_clock_s < 120 THEN '1_2m'
        WHEN disconnected_clock_s < 300 THEN '2_5m'
        WHEN disconnected_clock_s < 600 THEN '5_10m'
        ELSE '10m_plus' END
    """
    clock_heat = database.execute(
        f"""
        SELECT fairness_bin, {clock_case} AS clock_bin,
               COUNT(*)::BIGINT AS rows,
               SUM(CASE WHEN kind_pp=100 THEN 1 ELSE 0 END)::BIGINT AS kind_draws
        FROM core WHERE disconnected_clock_s IS NOT NULL
        GROUP BY fairness_bin, clock_bin
        """
    ).fetchdf()
    clock_heat = add_rates(clock_heat)
    write_csv(figure_data / "figureA01_clock_by_fairness_bin.csv", clock_heat)

    clock_region = database.execute(
        f"""
        SELECT CASE WHEN fair THEN 'fair_competitive' WHEN clearly_worse THEN 'clearly_worse' ELSE 'excluded_middle' END AS region,
               {clock_case} AS clock_bin,
               COUNT(*)::BIGINT AS rows,
               SUM(CASE WHEN kind_pp=100 THEN 1 ELSE 0 END)::BIGINT AS kind_draws
        FROM core WHERE disconnected_clock_s IS NOT NULL
        GROUP BY region, clock_bin
        """
    ).fetchdf()
    clock_region = add_rates(clock_region)
    write_csv(figure_data / "figureA02_clock_by_fairness_region.csv", clock_region)

    return {
        "overall": overall.iloc[0].to_dict(),
        "table01_rows": int(table01.rows.sum()),
        "table06_rows": int(table06.rows.sum()),
        "fair_rows": int(regions.loc[regions.region == "fair_competitive", "rows"].iloc[0]),
        "clearly_worse_rows": int(regions.loc[regions.region == "clearly_worse", "rows"].iloc[0]),
        "excluded_middle_rows": int(regions.loc[regions.region == "excluded_middle", "rows"].iloc[0]),
        "fine_eval_rows": int(fine.rows.sum()),
    }


def dense_codes(values: np.ndarray) -> tuple[np.ndarray, int]:
    codes, uniques = pd.factorize(values, sort=False)
    if np.any(codes < 0):
        raise ValueError("Fixed-effect values contain missing codes")
    return codes.astype(np.int64, copy=False), int(len(uniques))


def demean_once(matrix: np.ndarray, codes: np.ndarray, levels: int) -> np.ndarray:
    """Remove one categorical fixed effect exactly."""
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
    matrix: np.ndarray,
    fixed_effects: Sequence[tuple[np.ndarray, int]],
    reference: np.ndarray,
) -> float:
    """Return the largest FE-group mean relative to its source-column scale."""
    scales = np.maximum(np.sqrt(np.mean(np.square(reference), axis=0)), 1.0)
    maximum = 0.0
    for codes, levels in fixed_effects:
        counts = np.bincount(codes, minlength=levels).astype(np.float64)
        valid = counts > 0
        for column in range(matrix.shape[1]):
            sums = np.bincount(codes, weights=matrix[:, column], minlength=levels)
            means = np.zeros(levels, dtype=np.float64)
            means[valid] = sums[valid] / counts[valid]
            if valid.any():
                maximum = max(
                    maximum,
                    float(np.max(np.abs(means[valid]))) / float(scales[column]),
                )
    return maximum


def absorb_two_way_exact(
    matrix: np.ndarray,
    first_codes: np.ndarray,
    second_codes: np.ndarray,
    *,
    orthogonality_tolerance: float = 1e-9,
) -> tuple[np.ndarray, float]:
    """Exactly project a matrix off two categorical fixed effects.

    The first effect can have millions of levels (chooser identifiers), while
    the second is intentionally small (the 20- or 50-bin premium control used
    in Tables 4 and 5).  After demeaning by the first effect, the remaining
    projection is solved through the small second-effect Schur complement.
    This avoids the potentially very slow geometric convergence of alternating
    demeaning when the two categorical effects are nearly nested.
    """
    source = np.asarray(matrix, dtype=np.float64)
    first, first_levels = dense_codes(np.asarray(first_codes, dtype=np.int64))
    second, second_levels = dense_codes(np.asarray(second_codes, dtype=np.int64))
    if first_levels < 1 or second_levels < 2:
        raise ValueError(
            f"Two-way absorption requires populated effects; "
            f"first_levels={first_levels}, second_levels={second_levels}"
        )
    if second_levels > 512:
        raise ValueError(
            f"Exact two-way absorber requires a small second effect; "
            f"found {second_levels} levels"
        )

    cell_count = first_levels * second_levels
    if cell_count > 300_000_000:
        raise MemoryError(
            "Exact two-way absorber would require more than 300,000,000 "
            f"chooser-by-bin cells (requested {cell_count:,})"
        )

    within_first = demean_once(source, first, first_levels)
    first_counts = np.bincount(first, minlength=first_levels).astype(np.float64)
    second_counts = np.bincount(second, minlength=second_levels).astype(np.float64)

    # Build the sparse-in-spirit chooser-by-bin incidence counts in int32.
    # The matrix is temporary and is processed in bounded float64 chunks.
    incidence = np.zeros((first_levels, second_levels), dtype=np.int32)
    np.add.at(incidence, (first, second), 1)

    cross_product = np.diag(second_counts)
    chooser_chunk = max(1, 2_000_000 // second_levels)
    for start in range(0, first_levels, chooser_chunk):
        stop = min(start + chooser_chunk, first_levels)
        block = incidence[start:stop].astype(np.float64)
        cross_product -= (block.T / first_counts[start:stop]) @ block
    del incidence
    cross_product = (cross_product + cross_product.T) / 2.0

    second_cross = np.column_stack(
        [
            np.bincount(second, weights=within_first[:, column], minlength=second_levels)
            for column in range(within_first.shape[1])
        ]
    )
    second_inverse = np.linalg.pinv(cross_product, rcond=1e-12, hermitian=True)
    second_coefficients = second_inverse @ second_cross

    fitted_second = second_coefficients[second].copy()
    for column in range(fitted_second.shape[1]):
        chooser_sums = np.bincount(
            first,
            weights=fitted_second[:, column],
            minlength=first_levels,
        )
        chooser_means = chooser_sums / first_counts
        fitted_second[:, column] -= chooser_means[first]
    residual = within_first - fitted_second

    effects = ((first, first_levels), (second, second_levels))
    scaled_group_mean = maximum_scaled_group_mean(residual, effects, source)
    if not np.isfinite(scaled_group_mean) or scaled_group_mean > orthogonality_tolerance:
        raise RuntimeError(
            "Exact two-way fixed-effect projection failed orthogonality QA: "
            f"maximum_scaled_group_mean={scaled_group_mean:.3e}, "
            f"tolerance={orthogonality_tolerance:.3e}"
        )
    return residual, scaled_group_mean


def absorb_matrix(
    matrix: np.ndarray,
    fixed_effects: Sequence[tuple[np.ndarray, int]],
    tolerance: float = 1e-9,
) -> tuple[np.ndarray, int, float, str]:
    source = np.asarray(matrix, dtype=np.float64)
    if not fixed_effects:
        return source.copy(), 0, 0.0, "none"
    if len(fixed_effects) == 1:
        codes, levels = fixed_effects[0]
        residual = demean_once(source, codes, levels)
        orthogonality = maximum_scaled_group_mean(residual, fixed_effects, source)
        if not np.isfinite(orthogonality) or orthogonality > tolerance:
            raise RuntimeError(
                "One-way fixed-effect projection failed orthogonality QA: "
                f"maximum_scaled_group_mean={orthogonality:.3e}, "
                f"tolerance={tolerance:.3e}"
            )
        return residual, 1, orthogonality, "one_way_exact"
    if len(fixed_effects) == 2:
        residual, orthogonality = absorb_two_way_exact(
            source,
            fixed_effects[0][0],
            fixed_effects[1][0],
            orthogonality_tolerance=tolerance,
        )
        return residual, 1, orthogonality, "two_way_schur_exact"
    raise ValueError(
        f"Stage 08 supports at most two categorical fixed effects; found {len(fixed_effects)}"
    )


def fit_lpm_cluster(
    y: np.ndarray,
    x: np.ndarray,
    x_names: Sequence[str],
    cluster_codes: np.ndarray,
    fixed_effect_codes: Sequence[np.ndarray] = (),
    add_intercept: bool = False,
) -> dict[str, Any]:
    y = np.asarray(y, dtype=np.float64)
    x = np.asarray(x, dtype=np.float64)
    clusters = np.asarray(cluster_codes, dtype=np.int64)
    if x.ndim == 1:
        x = x[:, None]
    if len(y) != len(x) or len(y) != len(clusters):
        raise ValueError("Regression arrays have inconsistent lengths")
    if x.shape[1] != len(x_names):
        raise ValueError("x_names does not match X")

    finite = np.isfinite(y) & np.all(np.isfinite(x), axis=1) & (clusters >= 0)
    for codes in fixed_effect_codes:
        finite &= np.asarray(codes) >= 0
    y = y[finite]
    x = x[finite]
    clusters = clusters[finite]
    fe_arrays = [np.asarray(codes, dtype=np.int64)[finite] for codes in fixed_effect_codes]
    n_raw = int(len(y))
    if n_raw == 0:
        raise ValueError("Regression has no finite rows")

    names = list(x_names)
    if fixed_effect_codes:
        fe = [(codes, int(codes.max()) + 1) for codes in fe_arrays]
        transformed, iterations, last_adjustment, absorption_method = absorb_matrix(
            np.column_stack([y, x]), fe
        )
        y = transformed[:, 0]
        x = transformed[:, 1:]
    else:
        iterations, last_adjustment = 0, 0.0
        absorption_method = "none"
        if add_intercept:
            x = np.column_stack([np.ones(n_raw, dtype=np.float64), x])
            names = ["intercept", *names]

    identifying = np.any(np.abs(x) > 1e-14, axis=1)
    y = y[identifying]
    x = x[identifying]
    clusters = clusters[identifying]
    n = int(len(y))
    k = int(x.shape[1])
    if n <= k:
        raise ValueError(f"Regression has too few identifying rows: n={n}, k={k}")

    xtx = x.T @ x
    rank = int(np.linalg.matrix_rank(xtx))
    inverse = np.linalg.pinv(xtx, hermitian=True)
    beta = inverse @ (x.T @ y)
    residual = y - x @ beta

    cluster_levels = int(clusters.max()) + 1
    cluster_counts = np.bincount(clusters, minlength=cluster_levels)
    g = int(np.count_nonzero(cluster_counts))
    scores = np.column_stack(
        [np.bincount(clusters, weights=x[:, column] * residual, minlength=cluster_levels) for column in range(k)]
    )
    covariance = inverse @ (scores.T @ scores) @ inverse
    if g > 1 and n > k:
        covariance *= (g / (g - 1.0)) * ((n - 1.0) / (n - k))
    standard_errors = np.sqrt(np.maximum(np.diag(covariance), 0.0))
    t_statistics = np.divide(beta, standard_errors, out=np.full_like(beta, np.nan), where=standard_errors > 0)

    return {
        "n_rows_raw": n_raw,
        "n_rows_identifying": n,
        "n_clusters": g,
        "k": k,
        "rank": rank,
        "x_names": names,
        "beta": beta,
        "covariance": covariance,
        "standard_errors_array": standard_errors,
        "t_statistics_array": t_statistics,
        "coefficients": {name: float(value) for name, value in zip(names, beta)},
        "standard_errors": {name: float(value) for name, value in zip(names, standard_errors)},
        "t_statistics": {name: float(value) for name, value in zip(names, t_statistics)},
        "absorption_iterations": iterations,
        "absorption_last_adjustment": last_adjustment,
        "absorption_method": absorption_method,
    }


def run_numerical_self_test() -> None:
    """Cross-check the exact absorber against an explicit dummy regression."""
    rng = np.random.default_rng(20260818)
    rows = 1_800
    chooser_levels = 90
    bin_levels = 6
    chooser = np.repeat(np.arange(chooser_levels, dtype=np.int64), rows // chooser_levels)
    premium_bin = (chooser // 30) * 2 + rng.integers(0, 2, size=rows, dtype=np.int64)
    matrix = rng.normal(size=(rows, 4))

    transformed, iterations, orthogonality, method = absorb_matrix(
        matrix,
        ((chooser, chooser_levels), (premium_bin, bin_levels)),
    )
    dummy = np.zeros((rows, chooser_levels + bin_levels), dtype=np.float64)
    dummy[np.arange(rows), chooser] = 1.0
    dummy[np.arange(rows), chooser_levels + premium_bin] = 1.0
    explicit = matrix - dummy @ np.linalg.lstsq(dummy, matrix, rcond=None)[0]
    maximum_difference = float(np.max(np.abs(transformed - explicit)))

    if method != "two_way_schur_exact" or iterations != 1:
        raise RuntimeError(f"Unexpected exact-absorber metadata: method={method}, iterations={iterations}")
    if maximum_difference > 1e-10:
        raise RuntimeError(
            "Exact-absorber dummy-regression cross-check failed: "
            f"maximum_difference={maximum_difference:.3e}"
        )
    if orthogonality > 1e-10:
        raise RuntimeError(
            "Exact-absorber self-test orthogonality failed: "
            f"maximum_scaled_group_mean={orthogonality:.3e}"
        )

    print("STAGE08_NUMERICAL_SELF_TEST_OK")
    print(f"method: {method}")
    print(f"maximum_dummy_regression_difference: {maximum_difference:.3e}")
    print(f"maximum_scaled_group_mean: {orthogonality:.3e}")


def linear_combination(result: dict[str, Any], weights: dict[str, float]) -> dict[str, float]:
    names = result["x_names"]
    vector = np.array([float(weights.get(name, 0.0)) for name in names], dtype=np.float64)
    estimate = float(vector @ result["beta"])
    variance = float(vector @ result["covariance"] @ vector)
    se = math.sqrt(max(variance, 0.0))
    return {"estimate": estimate, "se": se, "t": estimate / se if se > 0 else math.nan}


def quantile_codes(values: np.ndarray, requested_bins: int) -> tuple[np.ndarray, list[float]]:
    values = np.asarray(values, dtype=np.float64)
    probabilities = np.linspace(0.0, 1.0, requested_bins + 1)
    edges = np.unique(np.quantile(values, probabilities, method="linear"))
    if len(edges) < 3:
        raise ValueError(f"Cannot create {requested_bins} quantile bins from win premium")
    interior = edges[1:-1]
    codes = np.searchsorted(interior, values, side="right").astype(np.int64)
    return codes, [float(value) for value in edges]


def regression_row(
    result: dict[str, Any],
    model: str,
    sample: str,
    variable: str,
    **extra: Any,
) -> dict[str, Any]:
    row = {
        "model": model,
        "sample": sample,
        "variable": variable,
        "coefficient_pp": result["coefficients"].get(variable),
        "se_pp": result["standard_errors"].get(variable),
        "t": result["t_statistics"].get(variable),
        "rows_raw": result["n_rows_raw"],
        "rows_identifying": result["n_rows_identifying"],
        "chooser_clusters": result["n_clusters"],
        "matrix_columns": result["k"],
        "matrix_rank": result["rank"],
        "absorption_iterations": result["absorption_iterations"],
        "absorption_method": result["absorption_method"],
        "absorption_max_scaled_group_mean": result["absorption_last_adjustment"],
    }
    row.update(extra)
    return row


def load_fair_panel(database: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    frame = database.execute(
        """
        SELECT month_index, chooser_fe_id, game_hash_half, temporal_half,
               kind_pp, eval_cp, eval_100_capped, draw_payoff, abs_draw_payoff,
               pos_draw_payoff, neg_draw_payoff, win_premium, favorable,
               log_chooser_clock, log_disconnected_clock, log_clock_ratio
        FROM core
        WHERE fair
        ORDER BY month_index, archive_ordinal
        """
    ).fetchdf()
    frame["chooser_fe_id"] = frame["chooser_fe_id"].astype(np.int64)
    for column in ("game_hash_half", "temporal_half", "month_index"):
        frame[column] = frame[column].astype(np.int8)
    numeric = [
        "kind_pp", "eval_cp", "eval_100_capped", "draw_payoff", "abs_draw_payoff",
        "pos_draw_payoff", "neg_draw_payoff", "win_premium", "favorable",
        "log_chooser_clock", "log_disconnected_clock", "log_clock_ratio",
    ]
    for column in numeric:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if frame[["chooser_fe_id", "kind_pp", "eval_cp", "draw_payoff", "win_premium", "favorable"]].isna().any().any():
        raise RuntimeError("Fair regression panel contains missing core values")
    return frame


def table02_and_figure02(fair: pd.DataFrame, root: Path) -> dict[str, Any]:
    tables = root / "tables"
    figure_data = root / "figure_data"
    maximum = max(TABLE2_BANDWIDTHS)
    local = fair.loc[fair["abs_draw_payoff"].to_numpy() <= maximum].copy()
    y = local["kind_pp"].to_numpy(dtype=np.float64)
    chooser = local["chooser_fe_id"].to_numpy(dtype=np.int64)
    favorable = local["favorable"].to_numpy(dtype=np.float64)
    payoff = local["draw_payoff"].to_numpy(dtype=np.float64)
    absolute = local["abs_draw_payoff"].to_numpy(dtype=np.float64)
    premium = local["win_premium"].to_numpy(dtype=np.float64)

    rows: list[dict[str, Any]] = []
    for bandwidth in TABLE2_BANDWIDTHS:
        mask = absolute <= bandwidth
        specs = (
            ("chooser_fe_sign_only", [favorable[mask]], ["favorable"]),
            ("chooser_fe_plus_win_premium", [favorable[mask], premium[mask]], ["favorable", "win_premium"]),
            (
                "chooser_fe_plus_abs_payoff_win_premium",
                [favorable[mask], absolute[mask], premium[mask]],
                ["favorable", "abs_draw_payoff", "win_premium"],
            ),
        )
        for model, columns, names in specs:
            result = fit_lpm_cluster(
                y[mask],
                np.column_stack(columns),
                names,
                chooser[mask],
                fixed_effect_codes=(chooser[mask],),
            )
            rows.append(
                regression_row(
                    result,
                    model,
                    f"fair_abs_draw_payoff_le_{bandwidth:g}",
                    "favorable",
                    bandwidth=bandwidth,
                    favorable_definition="draw_payoff>=0",
                )
            )
    table02 = pd.DataFrame(rows).sort_values(["bandwidth", "model"]).reset_index(drop=True)
    write_csv(tables / "table02_zero_threshold_all_specs.csv", table02)
    main = table02.loc[table02.model == "chooser_fe_plus_win_premium"].copy()
    write_csv(tables / "table02_zero_threshold_main.csv", main)

    beta_model = fit_lpm_cluster(
        y,
        premium[:, None],
        ["win_premium"],
        chooser,
        fixed_effect_codes=(chooser,),
    )
    beta_premium = beta_model["coefficients"]["win_premium"]
    adjusted = y - beta_premium * premium
    counts = np.bincount(chooser)
    sums = np.bincount(chooser, weights=adjusted)
    means = np.divide(sums, counts, out=np.zeros_like(sums), where=counts > 0)
    residualized = adjusted - means[chooser] + float(np.mean(y))

    binned_parts: list[pd.DataFrame] = []
    for width in (0.10, 0.25, 0.50):
        bin_number = np.floor((payoff + maximum) / width).astype(np.int64)
        max_bin = int(round((2 * maximum) / width))
        bin_number = np.clip(bin_number, 0, max_bin)
        plot = pd.DataFrame(
            {
                "bin_number": bin_number,
                "draw_payoff": payoff,
                "kind_pp": y,
                "residualized_kind_pp": residualized,
                "win_premium": premium,
                "favorable": favorable,
                "chooser_fe_id": chooser,
            }
        )
        grouped = (
            plot.groupby("bin_number", sort=True, observed=True)
            .agg(
                rows=("kind_pp", "size"),
                draw_payoff_mean=("draw_payoff", "mean"),
                kind_rate_raw_pct=("kind_pp", "mean"),
                kind_rate_residualized_pct=("residualized_kind_pp", "mean"),
                residualized_sd=("residualized_kind_pp", "std"),
                win_premium_mean=("win_premium", "mean"),
                favorable_share=("favorable", "mean"),
                chooser_count=("chooser_fe_id", "nunique"),
            )
            .reset_index()
        )
        grouped.insert(0, "bin_width", width)
        grouped["bin_left"] = -maximum + grouped["bin_number"] * width
        grouped["bin_right"] = grouped["bin_left"] + width
        grouped["bin_mid"] = (grouped["bin_left"] + grouped["bin_right"]) / 2.0
        probability = grouped["kind_rate_raw_pct"] / 100.0
        grouped["raw_binomial_se_pp"] = 100.0 * np.sqrt(probability * (1 - probability) / grouped["rows"])
        grouped["residualized_se_mean_pp"] = grouped["residualized_sd"] / np.sqrt(grouped["rows"])
        binned_parts.append(grouped)
    binned = pd.concat(binned_parts, ignore_index=True)
    write_csv(figure_data / "figure02_zero_threshold_binned.csv", binned)

    return {
        "local_rows_abs_payoff_le_6": int(len(local)),
        "local_choosers": int(local.chooser_fe_id.nunique()),
        "figure02_beta_win_premium_pp": beta_premium,
        "table02_main": main.to_dict("records"),
    }


def piecewise_outputs(fair: pd.DataFrame, root: Path) -> dict[str, Any]:
    tables = root / "tables"
    y_all = fair["kind_pp"].to_numpy(dtype=np.float64)
    chooser_all = fair["chooser_fe_id"].to_numpy(dtype=np.int64)
    payoff_all = fair["draw_payoff"].to_numpy(dtype=np.float64)
    abs_all = fair["abs_draw_payoff"].to_numpy(dtype=np.float64)
    pos_all = fair["pos_draw_payoff"].to_numpy(dtype=np.float64)
    neg_all = fair["neg_draw_payoff"].to_numpy(dtype=np.float64)
    favorable_all = fair["favorable"].to_numpy(dtype=np.float64)
    premium_all = fair["win_premium"].to_numpy(dtype=np.float64)

    table03_rows: list[dict[str, Any]] = []
    for window in LOCAL_WINDOWS:
        mask = np.ones(len(fair), dtype=bool) if window is None else abs_all <= window
        names = ["beta_plus", "beta_minus", "threshold_nonnegative", "win_premium"]
        result = fit_lpm_cluster(
            y_all[mask],
            np.column_stack([pos_all[mask], neg_all[mask], favorable_all[mask], premium_all[mask]]),
            names,
            chooser_all[mask],
            fixed_effect_codes=(chooser_all[mask],),
        )
        asymmetry = linear_combination(result, {"beta_plus": 1.0, "beta_minus": 1.0})
        table03_rows.append(
            {
                "window": "full_fair_range" if window is None else f"abs_payoff_le_{window:g}",
                "window_half_width": window,
                "beta_plus_pp_per_rating_point": result["coefficients"]["beta_plus"],
                "se_beta_plus": result["standard_errors"]["beta_plus"],
                "beta_minus_pp_per_rating_point": result["coefficients"]["beta_minus"],
                "se_beta_minus": result["standard_errors"]["beta_minus"],
                "slope_asymmetry_beta_plus_plus_beta_minus": asymmetry["estimate"],
                "se_slope_asymmetry": asymmetry["se"],
                "t_slope_asymmetry": asymmetry["t"],
                "threshold_jump_pp": result["coefficients"]["threshold_nonnegative"],
                "se_threshold_jump_pp": result["standard_errors"]["threshold_nonnegative"],
                "rows_raw": result["n_rows_raw"],
                "rows_identifying": result["n_rows_identifying"],
                "chooser_clusters": result["n_clusters"],
            }
        )
    table03 = pd.DataFrame(table03_rows)
    write_csv(tables / "table03_local_piecewise.csv", table03)

    table04_rows: list[dict[str, Any]] = []
    quantile_receipts: dict[str, Any] = {}
    for window in (0.5, 1.0):
        mask = abs_all <= window
        y = y_all[mask]
        chooser = chooser_all[mask]
        base = np.column_stack([pos_all[mask], neg_all[mask], favorable_all[mask]])
        premium = premium_all[mask]

        model_specs: list[tuple[str, np.ndarray, list[str], Sequence[np.ndarray]]] = []
        model_specs.append(
            ("linear", np.column_stack([base, premium]), ["beta_plus", "beta_minus", "threshold_nonnegative", "win_premium"], (chooser,))
        )
        premium_z = (premium - float(np.mean(premium))) / float(np.std(premium, ddof=0))
        model_specs.append(
            (
                "cubic",
                np.column_stack([base, premium_z, premium_z ** 2, premium_z ** 3]),
                ["beta_plus", "beta_minus", "threshold_nonnegative", "win_premium_z", "win_premium_z2", "win_premium_z3"],
                (chooser,),
            )
        )
        for bins in (20, 50):
            codes, edges = quantile_codes(premium, bins)
            key = f"window_{window:g}_q{bins}"
            quantile_receipts[key] = {"requested_bins": bins, "realized_bins": int(codes.max()) + 1, "edges": edges}
            model_specs.append(
                (
                    f"{bins}_quantile_bins",
                    base,
                    ["beta_plus", "beta_minus", "threshold_nonnegative"],
                    (chooser, codes),
                )
            )

        for model, x, names, fixed_effects in model_specs:
            progress(
                f"Table 04: window={window:g}; premium_control={model}; rows={len(y):,}"
            )
            result = fit_lpm_cluster(y, x, names, chooser, fixed_effect_codes=fixed_effects)
            asymmetry = linear_combination(result, {"beta_plus": 1.0, "beta_minus": 1.0})
            table04_rows.append(
                {
                    "window_half_width": window,
                    "win_premium_control": model,
                    "slope_asymmetry_beta_plus_plus_beta_minus": asymmetry["estimate"],
                    "se_slope_asymmetry": asymmetry["se"],
                    "t_slope_asymmetry": asymmetry["t"],
                    "threshold_jump_pp": result["coefficients"]["threshold_nonnegative"],
                    "rows_raw": result["n_rows_raw"],
                    "rows_identifying": result["n_rows_identifying"],
                    "chooser_clusters": result["n_clusters"],
                    "absorption_iterations": result["absorption_iterations"],
                    "absorption_method": result["absorption_method"],
                    "absorption_max_scaled_group_mean": result["absorption_last_adjustment"],
                }
            )
    table04 = pd.DataFrame(table04_rows)
    write_csv(tables / "table04_flexible_win_premium_controls.csv", table04)
    atomic_write_json(root / "receipts/table04_quantile_edges.json", quantile_receipts)

    table05_rows: list[dict[str, Any]] = []
    placebo_receipts: dict[str, Any] = {}
    for cutoff in PLACEBO_CUTOFFS:
        shifted = payoff_all - cutoff
        for window in PLACEBO_WINDOWS:
            mask = np.abs(shifted) <= window
            local_x = shifted[mask]
            chooser = chooser_all[mask]
            premium = premium_all[mask]
            bin_codes, edges = quantile_codes(premium, 20)
            key = f"cutoff_{cutoff:+.2f}_window_{window:g}"
            placebo_receipts[key] = {"realized_bins": int(bin_codes.max()) + 1, "edges": edges}
            x = np.column_stack(
                [np.maximum(local_x, 0.0), np.maximum(-local_x, 0.0), (local_x >= 0).astype(np.float64)]
            )
            progress(
                f"Table 05: cutoff={cutoff:+.2f}; window={window:g}; rows={len(local_x):,}"
            )
            result = fit_lpm_cluster(
                y_all[mask],
                x,
                ["beta_plus", "beta_minus", "threshold_nonnegative"],
                chooser,
                fixed_effect_codes=(chooser, bin_codes),
            )
            asymmetry = linear_combination(result, {"beta_plus": 1.0, "beta_minus": 1.0})
            table05_rows.append(
                {
                    "cutoff": cutoff,
                    "window_half_width": window,
                    "slope_asymmetry_beta_plus_plus_beta_minus": asymmetry["estimate"],
                    "se_slope_asymmetry": asymmetry["se"],
                    "t_slope_asymmetry": asymmetry["t"],
                    "threshold_jump_pp": result["coefficients"]["threshold_nonnegative"],
                    "rows_raw": result["n_rows_raw"],
                    "rows_identifying": result["n_rows_identifying"],
                    "chooser_clusters": result["n_clusters"],
                    "absorption_iterations": result["absorption_iterations"],
                    "absorption_method": result["absorption_method"],
                    "absorption_max_scaled_group_mean": result["absorption_last_adjustment"],
                }
            )
    table05 = pd.DataFrame(table05_rows).sort_values(["cutoff", "window_half_width"]).reset_index(drop=True)
    write_csv(tables / "table05_placebo_cutoffs.csv", table05)
    atomic_write_json(root / "receipts/table05_quantile_edges.json", placebo_receipts)

    return {
        "table03": table03.to_dict("records"),
        "table04_rows": int(len(table04)),
        "table05_rows": int(len(table05)),
    }


def table07_outputs(fair: pd.DataFrame, root: Path) -> dict[str, Any]:
    tables = root / "tables"
    y = fair["kind_pp"].to_numpy(dtype=np.float64)
    chooser = fair["chooser_fe_id"].to_numpy(dtype=np.int64)
    favorable = fair["favorable"].to_numpy(dtype=np.float64)
    evaluation = fair["eval_100_capped"].to_numpy(dtype=np.float64)
    interaction = favorable * evaluation
    premium = fair["win_premium"].to_numpy(dtype=np.float64)
    log_disconnected = fair["log_disconnected_clock"].to_numpy(dtype=np.float64)
    log_chooser = fair["log_chooser_clock"].to_numpy(dtype=np.float64)
    log_ratio = fair["log_clock_ratio"].to_numpy(dtype=np.float64)

    base = np.column_stack([favorable, evaluation, interaction])
    base_names = ["favorable", "eval_100_capped", "favorable_x_eval_100_capped"]
    controls = np.column_stack([premium, log_disconnected, log_chooser, log_ratio])
    control_names = ["win_premium", "log_disconnected_clock", "log_chooser_clock", "log_clock_ratio"]
    specifications = (
        ("pooled_no_controls", base, base_names, (), True),
        ("pooled_plus_controls", np.column_stack([base, controls]), base_names + control_names, (), True),
        ("chooser_fe_no_controls", base, base_names, (chooser,), False),
        ("chooser_fe_plus_controls", np.column_stack([base, controls]), base_names + control_names, (chooser,), False),
    )

    rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for model, x, names, fixed_effects, intercept in specifications:
        result = fit_lpm_cluster(
            y,
            x,
            names,
            chooser,
            fixed_effect_codes=fixed_effects,
            add_intercept=intercept,
        )
        for variable in base_names:
            rows.append(regression_row(result, model, "all_fair_finite_payoff", variable))
        favorable_at_minus100 = linear_combination(
            result,
            {"favorable": 1.0, "favorable_x_eval_100_capped": -1.0},
        )
        favorable_at_600 = linear_combination(
            result,
            {"favorable": 1.0, "favorable_x_eval_100_capped": 6.0},
        )
        summaries.append(
            {
                "model": model,
                "premium_at_minus100cp_pp": favorable_at_minus100["estimate"],
                "se_at_minus100cp": favorable_at_minus100["se"],
                "premium_at_0cp_pp": result["coefficients"]["favorable"],
                "se_at_0cp": result["standard_errors"]["favorable"],
                "premium_at_600cp_pp": favorable_at_600["estimate"],
                "se_at_600cp": favorable_at_600["se"],
                "rows_raw": result["n_rows_raw"],
                "rows_identifying": result["n_rows_identifying"],
                "chooser_clusters": result["n_clusters"],
                "matrix_columns": result["k"],
                "matrix_rank": result["rank"],
            }
        )
    table07 = pd.DataFrame(rows)
    implied = pd.DataFrame(summaries)
    write_csv(tables / "table07_favorable_x_evaluation.csv", table07)
    write_csv(tables / "table07_implied_price_premium.csv", implied)
    return {
        "rows": int(len(fair)),
        "models": summaries,
        "documented_clock_control_collinearity": (
            "log_clock_ratio = log_chooser_clock - log_disconnected_clock; "
            "the pseudo-inverse estimates the same control span as the two independent log-clock terms"
        ),
    }


def weighted_correlation(x: np.ndarray, y: np.ndarray, weights: np.ndarray) -> float:
    finite = np.isfinite(x) & np.isfinite(y) & np.isfinite(weights) & (weights > 0)
    x, y, weights = x[finite], y[finite], weights[finite]
    if len(x) < 3:
        return math.nan
    total = float(weights.sum())
    mean_x = float(np.sum(weights * x) / total)
    mean_y = float(np.sum(weights * y) / total)
    covariance = float(np.sum(weights * (x - mean_x) * (y - mean_y)) / total)
    variance_x = float(np.sum(weights * (x - mean_x) ** 2) / total)
    variance_y = float(np.sum(weights * (y - mean_y) ** 2) / total)
    if variance_x <= 0 or variance_y <= 0:
        return math.nan
    return covariance / math.sqrt(variance_x * variance_y)


def normal_rate_interval(kind_draws: float, rows: float) -> tuple[float, float]:
    if rows <= 0:
        return math.nan, math.nan
    p = kind_draws / rows
    se = math.sqrt(max(p * (1 - p) / rows, 0.0))
    return 100 * (p - 1.96 * se), 100 * (p + 1.96 * se)


def summarize_split(wide: pd.DataFrame, design: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    base = wide.loc[(wide.n0 > 0) & (wide.n1 > 0)].copy()
    base["rate0"] = base.k0 / base.n0
    base["rate1"] = base.k1 / base.n1
    base["total_n"] = base.n0 + base.n1
    base["total_k"] = base.k0 + base.k1
    base["harmonic_n"] = 2 * base.n0 * base.n1 / (base.n0 + base.n1)

    correlation_rows: list[dict[str, Any]] = []
    transition_rows: list[dict[str, Any]] = []
    for cutoff in SPLIT_MIN_OPPORTUNITIES:
        sample = base.loc[base.total_n >= cutoff].copy()
        correlation_rows.append(
            {
                "split_design": design,
                "min_total_fair_opportunities": cutoff,
                "choosers": int(len(sample)),
                "fair_opportunities": int(sample.total_n.sum()),
                "kind_draws": int(sample.total_k.sum()),
                "pearson_unweighted": float(sample.rate0.corr(sample.rate1)),
                "spearman_unweighted": float(sample.rate0.corr(sample.rate1, method="spearman")),
                "pearson_weighted_total_opportunities": weighted_correlation(
                    sample.rate0.to_numpy(), sample.rate1.to_numpy(), sample.total_n.to_numpy()
                ),
                "pearson_weighted_harmonic_half_opportunities": weighted_correlation(
                    sample.rate0.to_numpy(), sample.rate1.to_numpy(), sample.harmonic_n.to_numpy()
                ),
            }
        )
        sample["first_ever_kind"] = sample.k0 > 0
        for first_kind in (False, True):
            group = sample.loc[sample.first_ever_kind == first_kind]
            second_rows = float(group.n1.sum())
            second_kinds = float(group.k1.sum())
            low, high = normal_rate_interval(second_kinds, second_rows)
            transition_rows.append(
                {
                    "split_design": design,
                    "min_total_fair_opportunities": cutoff,
                    "first_half_any_kind": int(first_kind),
                    "choosers": int(len(group)),
                    "second_half_fair_opportunities": int(second_rows),
                    "second_half_kind_draws": int(second_kinds),
                    "second_half_kind_rate_pct": 100 * second_kinds / second_rows,
                    "normal_95ci_low_pct": low,
                    "normal_95ci_high_pct": high,
                }
            )

    scatter = base.loc[base.total_n >= 4, ["rate0", "rate1"]].copy()
    scatter["first_half_rate_pct_bin"] = np.floor(scatter.rate0 * 100).clip(0, 100).astype(int)
    scatter["second_half_rate_pct_bin"] = np.floor(scatter.rate1 * 100).clip(0, 100).astype(int)
    scatter_grid = (
        scatter.groupby(["first_half_rate_pct_bin", "second_half_rate_pct_bin"], observed=True)
        .size()
        .rename("choosers")
        .reset_index()
    )
    scatter_grid.insert(0, "split_design", design)
    return pd.DataFrame(correlation_rows), pd.DataFrame(transition_rows), scatter_grid


def type_and_split_outputs(database: duckdb.DuckDBPyConnection, fair: pd.DataFrame, root: Path) -> dict[str, Any]:
    tables = root / "tables"
    figure_data = root / "figure_data"

    early = database.execute(
        """
        SELECT chooser_fe_id, COUNT(*)::BIGINT AS early_fair_opps,
               SUM(CASE WHEN kind_pp=100 THEN 1 ELSE 0 END)::BIGINT AS early_kind_draws
        FROM core WHERE fair AND temporal_half=0 GROUP BY chooser_fe_id
        """
    ).fetchdf()
    early["prior_kind_type"] = np.where(early.early_kind_draws > 0, "ever_kind", "never_kind")
    early_type = early.set_index("chooser_fe_id")["prior_kind_type"]

    later = fair.loc[fair.temporal_half == 1].copy()
    later["prior_kind_type"] = later.chooser_fe_id.map(early_type)
    later = later.dropna(subset=["prior_kind_type"]).copy()

    levels = (
        later.groupby("prior_kind_type", observed=True)
        .agg(
            later_rows=("kind_pp", "size"),
            later_kind_rate_pct=("kind_pp", "mean"),
            later_kind_draws=("kind_pp", lambda values: int(round(float(values.sum()) / 100.0))),
            later_choosers=("chooser_fe_id", "nunique"),
        )
        .reset_index()
    )

    model_rows: list[dict[str, Any]] = []
    model_summary: list[dict[str, Any]] = []
    for prior_type in ("ever_kind", "never_kind"):
        sample = later.loc[later.prior_kind_type == prior_type]
        y = sample.kind_pp.to_numpy(dtype=np.float64)
        chooser = sample.chooser_fe_id.to_numpy(dtype=np.int64)
        favorable = sample.favorable.to_numpy(dtype=np.float64)
        evaluation = sample.eval_100_capped.to_numpy(dtype=np.float64)
        premium = sample.win_premium.to_numpy(dtype=np.float64)
        x = np.column_stack([favorable, evaluation, favorable * evaluation, premium])
        names = ["favorable", "eval_100_capped", "favorable_x_eval_100_capped", "win_premium"]
        result = fit_lpm_cluster(y, x, names, chooser, fixed_effect_codes=(chooser,))
        for variable in names:
            model_rows.append(
                regression_row(
                    result,
                    f"chooser_fe_{prior_type}",
                    "later_12_month_fair_rows_with_early_type",
                    variable,
                    prior_kind_type=prior_type,
                )
            )
        model_summary.append(
            {
                "prior_kind_type": prior_type,
                "rows_raw": result["n_rows_raw"],
                "rows_identifying": result["n_rows_identifying"],
                "chooser_clusters": result["n_clusters"],
            }
        )
    models = pd.DataFrame(model_rows)
    table08 = models.merge(levels, on="prior_kind_type", how="left")
    write_csv(tables / "table08_prior_kindness_models.csv", table08)
    write_csv(tables / "table08_prior_kindness_levels.csv", levels)

    eval_edges = [-100, -50, 0, 50, 100, 200, 300, 600, np.inf]
    eval_labels = ["minus100_minus50", "minus50_zero", "zero_50", "50_100", "100_200", "200_300", "300_600", "600_plus"]
    later["eval_bin"] = pd.cut(later.eval_cp, bins=eval_edges, labels=eval_labels, right=False, include_lowest=True)
    profile = (
        later.dropna(subset=["eval_bin"])
        .groupby(["prior_kind_type", "eval_bin"], observed=True)
        .agg(rows=("kind_pp", "size"), kind_rate_pct=("kind_pp", "mean"), choosers=("chooser_fe_id", "nunique"), eval_mean=("eval_cp", "mean"))
        .reset_index()
    )
    write_csv(figure_data / "figureA04_prior_kindness_by_eval_bin.csv", profile)

    correlation_frames: list[pd.DataFrame] = []
    transition_frames: list[pd.DataFrame] = []
    scatter_frames: list[pd.DataFrame] = []
    for design, half_column in (("hash_md5_game_id", "game_hash_half"), ("temporal_first12_second12", "temporal_half")):
        wide = database.execute(
            f"""
            SELECT chooser_fe_id,
              SUM(CASE WHEN {half_column}=0 THEN 1 ELSE 0 END)::BIGINT AS n0,
              SUM(CASE WHEN {half_column}=1 THEN 1 ELSE 0 END)::BIGINT AS n1,
              SUM(CASE WHEN {half_column}=0 AND kind_pp=100 THEN 1 ELSE 0 END)::BIGINT AS k0,
              SUM(CASE WHEN {half_column}=1 AND kind_pp=100 THEN 1 ELSE 0 END)::BIGINT AS k1
            FROM core WHERE fair GROUP BY chooser_fe_id
            """
        ).fetchdf()
        correlation, transitions, scatter = summarize_split(wide, design)
        correlation_frames.append(correlation)
        transition_frames.append(transitions)
        scatter_frames.append(scatter)

    correlations = pd.concat(correlation_frames, ignore_index=True)
    transitions = pd.concat(transition_frames, ignore_index=True)
    scatter_grid = pd.concat(scatter_frames, ignore_index=True)
    write_csv(tables / "tableA01_split_half_full_statistics.csv", correlations)
    write_csv(tables / "tableA02_split_half_cutoffs.csv", correlations)
    write_csv(tables / "table09_second_half_by_first_half_behavior.csv", transitions.loc[transitions.min_total_fair_opportunities == 4].copy())
    write_csv(tables / "split_half_transition_all_cutoffs.csv", transitions)
    write_csv(figure_data / "figureA03_split_half_scatter_grid.csv", scatter_grid)

    return {
        "early_type_choosers": int(len(early)),
        "later_rows_with_early_type": int(len(later)),
        "later_choosers_with_early_type": int(later.chooser_fe_id.nunique()),
        "table08_models": model_summary,
        "split_min4": correlations.loc[correlations.min_total_fair_opportunities == 4].to_dict("records"),
    }


def output_manifest(root: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name.startswith(".") or path.suffix in {".duckdb", ".wal"}:
            continue
        relative = path.relative_to(root).as_posix()
        if relative in {"_SUCCESS.json", "_SELECTED_SUCCESS.json", "manifest_sha256.csv"}:
            continue
        rows.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return pd.DataFrame(rows)


def validate_outputs(
    descriptive: dict[str, Any],
    core_qa: dict[str, Any],
    months: Sequence[str],
    root: Path,
    full_only: dict[str, Any] | None,
) -> dict[str, Any]:
    rows = int(core_qa["core"]["rows"])
    kinds = int(core_qa["core"]["kind_draws"])
    if int(descriptive["overall"]["rows"]) != rows:
        raise RuntimeError("Overall table row total differs from core cache")
    if int(descriptive["overall"]["kind_draws"]) != kinds:
        raise RuntimeError("Overall table kind-draw total differs from core cache")
    if descriptive["table01_rows"] != rows or descriptive["fine_eval_rows"] != rows:
        raise RuntimeError("Fairness or fine-evaluation tables do not partition the sample")
    expected_binary = descriptive["fair_rows"] + descriptive["clearly_worse_rows"]
    if descriptive["table06_rows"] != expected_binary:
        raise RuntimeError("Table 6 does not partition fair plus clearly-worse rows")

    expected_files = [
        "tables/table01_fairness_bins.csv",
        "tables/table02_zero_threshold_main.csv",
        "tables/table03_local_piecewise.csv",
        "tables/table04_flexible_win_premium_controls.csv",
        "tables/table05_placebo_cutoffs.csv",
        "tables/table06_fairness_price_2x2.csv",
        "tables/table07_favorable_x_evaluation.csv",
        "figure_data/figure02_zero_threshold_binned.csv",
        "figure_data/figure03_favorable_minus_costly_by_eval_bin.csv",
    ]
    if tuple(months) == ALL_MONTHS:
        expected_files.extend(
            [
                "tables/table08_prior_kindness_models.csv",
                "tables/table09_second_half_by_first_half_behavior.csv",
                "tables/tableA01_split_half_full_statistics.csv",
                "figure_data/figureA03_split_half_scatter_grid.csv",
                "figure_data/figureA04_prior_kindness_by_eval_bin.csv",
            ]
        )
        if full_only is None:
            raise RuntimeError("Full 24-month run omitted type/split outputs")
    missing = [relative for relative in expected_files if not (root / relative).is_file()]
    if missing:
        raise RuntimeError(f"Stage 08 expected outputs missing: {missing}")

    for relative in expected_files:
        frame = pd.read_csv(root / relative)
        if len(frame) == 0:
            raise RuntimeError(f"Stage 08 output is empty: {relative}")

    return {
        "status": "STAGE08_OUTPUT_QA_OK",
        "rows": rows,
        "kind_draws": kinds,
        "selected_months": len(months),
        "expected_outputs_checked": len(expected_files),
    }


def print_plan(
    months: Sequence[str],
    output_root: Path,
    stage07: dict[str, Any],
    state: dict[str, Any],
    script_path: Path,
    threads: int,
    memory_limit: str,
) -> None:
    print("STAGE08_PLAN_OK")
    print(f"script_version: {SCRIPT_VERSION}")
    print(f"script_sha256: {sha256_file(script_path)}")
    print(f"git_head: {state['head']}")
    print(f"months: {','.join(months)}")
    print(f"selected_rows: {stage07['selected_rows']:,}")
    print(f"selected_input_bytes: {stage07['selected_bytes']:,}")
    print(f"output_root: {output_root}")
    print(f"threads: {threads}")
    print(f"memory_limit: {memory_limit}")
    print(f"stage07_summary_sha256: {stage07['success_sha256']}")
    print("scope: panel-only Tables 1-9, Figures 2-3, clock and split-half plot data")
    print("excluded_external_inputs: patron/profile, opening familiarity, reentry, post-sample holdouts, historical validation")
    print("No files were written. Re-run with --execute to build selected months.")


def execute(args: argparse.Namespace, months: Sequence[str], script_path: Path) -> None:
    started = time.time()
    output_root = Path(args.output_root).expanduser().resolve()
    if output_root.exists():
        raise RuntimeError(f"Output root already exists; refusing to overwrite: {output_root}")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = output_root.with_name(f".{output_root.name}.tmp.{os.getpid()}")
    if temporary_root.exists():
        raise RuntimeError(f"Transactional temporary root already exists: {temporary_root}")
    temporary_root.mkdir(parents=True)
    (temporary_root / "tables").mkdir()
    (temporary_root / "figure_data").mkdir()
    (temporary_root / "receipts").mkdir()
    (temporary_root / "_work/duckdb_tmp").mkdir(parents=True)

    try:
        progress(f"START Stage 08 v{SCRIPT_VERSION}; months={','.join(months)}")
        stage07 = authenticate_stage07(months, verify_hashes=True)
        progress("Stage 07 input authentication passed")
        state = git_state()
        if args.expected_git_head and state["head"] != args.expected_git_head:
            raise RuntimeError(
                "Git HEAD differs from the authenticated launcher contract: "
                f"expected={args.expected_git_head} actual={state['head']}"
            )
        status_lines = {line for line in state["status_porcelain"].splitlines() if line}
        allowed_status_lines = {
            "?? code/08_make_core_paper_results.py",
            " M code/08_make_core_paper_results.py",
            "M  code/08_make_core_paper_results.py",
        }
        unexpected_status = sorted(status_lines - allowed_status_lines)
        if unexpected_status:
            raise RuntimeError(f"Repository contains unrelated changes: {unexpected_status}")
        database, core_qa = create_core_database(
            temporary_root / "_work/stage08.duckdb",
            [record["path"] for record in stage07["month_records"]],
            threads=args.threads,
            memory_limit=args.memory_limit,
            temporary_directory=temporary_root / "_work/duckdb_tmp",
        )
        progress(
            f"Core cache QA passed; rows={core_qa['core']['rows']:,}; "
            f"fair_rows={core_qa['core']['fair_rows']:,}"
        )
        descriptive = descriptive_outputs(database, temporary_root)
        progress("Descriptive tables and plot data complete")
        fair = load_fair_panel(database)
        if len(fair) != int(core_qa["core"]["fair_rows"]):
            raise RuntimeError("Loaded fair regression panel row count changed")

        progress("Table 02 and Figure 02 models starting")
        table02 = table02_and_figure02(fair, temporary_root)
        progress("Table 02 and Figure 02 models complete")
        progress("Tables 03-05 models starting")
        piecewise = piecewise_outputs(fair, temporary_root)
        progress("Tables 03-05 models complete")
        progress("Table 07 models starting")
        table07 = table07_outputs(fair, temporary_root)
        progress("Table 07 models complete")
        full_only = None
        if tuple(months) == ALL_MONTHS:
            progress("Tables 08-09 and split-half outputs starting")
            full_only = type_and_split_outputs(database, fair, temporary_root)
            progress("Tables 08-09 and split-half outputs complete")

        qa = validate_outputs(descriptive, core_qa, months, temporary_root, full_only)
        progress("Output QA passed; finalizing transactional result root")
        database.close()
        shutil.rmtree(temporary_root / "_work")

        manifest = output_manifest(temporary_root)
        write_csv(temporary_root / "manifest_sha256.csv", manifest)
        manifest_sha = sha256_file(temporary_root / "manifest_sha256.csv")

        full = tuple(months) == ALL_MONTHS
        status = "STAGE08_CORE_24M_CERTIFIED_OK" if full else "STAGE08_SELECTED_MONTHS_OK"
        summary = {
            "status": status,
            "created_at_utc": utc_now(),
            "script_version": SCRIPT_VERSION,
            "script_path": str(script_path),
            "script_sha256": sha256_file(script_path),
            "git": state,
            "months": list(months),
            "month_start": months[0],
            "month_end": months[-1],
            "full_24_month_run": full,
            "stage07": {
                "success_path": stage07["success_path"],
                "success_sha256": stage07["success_sha256"],
                "producer_sha256": stage07["producer_sha256"],
                "selected_rows": stage07["selected_rows"],
                "selected_bytes": stage07["selected_bytes"],
                "monthly_inputs": [
                    {
                        "month": record["month"],
                        "path": str(record["path"]),
                        "rows": record["rows"],
                        "bytes": record["size_bytes"],
                        "sha256": record.get("actual_sha256", record["expected_sha256"]),
                    }
                    for record in stage07["month_records"]
                ],
            },
            "scope": {
                "included": "panel-only core paper results and analytical plot data",
                "excluded": [
                    "patron/profile analyses",
                    "opening familiarity",
                    "abandonment/reentry",
                    "post-sample holdouts",
                    "historical rating-rule validation",
                    "rendered publication tables and figures",
                ],
                "paper_favorable_definition": "chooser_draw_payoff_v2 >= 0",
                "fair_definition": "engine_eval_cp_disconnected >= -100",
                "clearly_worse_definition": "engine_eval_cp_disconnected <= -300",
                "chooser_cluster_authority": "chooser_username_norm (mapped losslessly to run-local chooser_fe_id)",
                "prior_kind_windows": "first 12 months classify; second 12 months evaluate",
                "hashed_split": "parity of final hexadecimal digit of md5(game_id)",
            },
            "software": software_versions(),
            "core_qa": core_qa,
            "descriptive": descriptive,
            "table02_and_figure02": table02,
            "piecewise": piecewise,
            "table07": table07,
            "type_and_split": full_only,
            "output_qa": qa,
            "manifest_sha256": manifest_sha,
            "manifest_files": int(len(manifest)),
            "runtime_seconds": round(time.time() - started, 3),
        }
        summary_name = "_SUCCESS.json" if full else "_SELECTED_SUCCESS.json"
        atomic_write_json(temporary_root / summary_name, summary)
        os.replace(temporary_root, output_root)

        print(status)
        print(f"output_root: {output_root}")
        print(f"rows: {core_qa['core']['rows']:,}")
        print(f"kind_draws: {core_qa['core']['kind_draws']:,}")
        print(f"fair_rows: {core_qa['core']['fair_rows']:,}")
        print(f"choosers: {core_qa['core']['choosers']:,}")
        print(f"manifest_sha256: {manifest_sha}")
        print(f"runtime_seconds: {time.time() - started:,.1f}")
    except Exception:
        failure = {
            "status": "STAGE08_FAILED",
            "created_at_utc": utc_now(),
            "script_version": SCRIPT_VERSION,
            "script_sha256": sha256_file(script_path),
            "months": list(months),
            "error": traceback.format_exc(),
        }
        try:
            atomic_write_json(temporary_root / "_FAILED.json", failure)
        except Exception:
            pass
        print("STAGE08_FAIL_CLOSED", file=sys.stderr)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--months", default="all", help="Comma-separated canonical months or 'all'")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--memory-limit", default="12GB")
    parser.add_argument(
        "--expected-git-head",
        default="",
        help="Optional exact repository HEAD required for execution",
    )
    parser.add_argument("--self-test", action="store_true", help="Run deterministic numerical tests and exit")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        run_numerical_self_test()
        return

    if args.threads < 1 or args.threads > 32:
        raise SystemExit("--threads must be between 1 and 32")
    months = parse_months(args.months)
    script_path = Path(__file__).resolve()

    try:
        state = git_state()
        if state["branch"] != "main":
            raise RuntimeError(f"Repository branch is {state['branch']!r}, expected 'main'")
        allowed_heads = {EXPECTED_STAGE07_FINAL_PROVENANCE_HEAD}
        if args.execute:
            # A preproduction Stage 08 commit may advance HEAD before the full run.
            allowed_heads.add(state["head"])
        if not args.execute and state["head"] not in allowed_heads:
            print(
                "NOTE: Git HEAD is beyond the frozen Stage 07 provenance commit; "
                "the exact HEAD will be recorded and the launcher must authenticate it."
            )

        if args.execute:
            execute(args, months, script_path)
        else:
            stage07 = authenticate_stage07(months, verify_hashes=False)
            print_plan(
                months,
                Path(args.output_root).expanduser().resolve(),
                stage07,
                state,
                script_path,
                args.threads,
                args.memory_limit,
            )
    except Exception as exc:
        print(f"STAGE08_FAIL_CLOSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
