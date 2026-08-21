#!/usr/bin/env python3
"""Build nonduplicative 24-month panel robustness from certified Stage 07.

This stage is deliberately independent of patron/profile acquisition.  It reads
only the frozen Stage 07 analysis panel and authenticates the frozen Stage 08
result bundle before producing density/support diagnostics, subgroup estimates,
engine-cutoff sensitivity, exact-zero payoff sensitivity, and economic-magnitude
summaries.

The script is dry-run by default.  ``--execute`` writes transactionally into a
new output root and refuses to overwrite an existing result.
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
from typing import Any, Sequence

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


SCRIPT_VERSION = "1.1.0"

PROJECT = Path("/Volumes/XT_Pro/lichess_kindness")
REPOSITORY = PROJECT / "replication_package"
PANEL_ROOT = PROJECT / "derived/replication/analysis_panel_24m_sf100k"
STAGE08_ROOT = PROJECT / "derived/replication/paper_results_core_24m_sf100k"
DEFAULT_OUTPUT_ROOT = PROJECT / "derived/replication/panel_robustness_24m_sf100k_v110"

EXPECTED_STAGE07_SCRIPT_SHA256 = (
    "0411d4061ea9831c20449208a9782aaf668e160139918d106a2b7d63aaa56e6e"
)
EXPECTED_STAGE07_SUMMARY_SHA256 = (
    "8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7"
)
EXPECTED_STAGE07_STATUS = "STAGE07_24M_CERTIFIED_OK"
EXPECTED_STAGE07_ROWS = 47_587_020
EXPECTED_STAGE07_KIND_DRAWS = 669_503
EXPECTED_STAGE07_COLUMNS = 157

EXPECTED_STAGE08_SCRIPT_SHA256 = (
    "e9dd80c52da5ffef3d406c3af25912bd924f6423f123ca535cf4077cb039c41f"
)
EXPECTED_STAGE08_SUMMARY_SHA256 = (
    "a2fd1a868299cba8499de1e72365dbeb4e49ec77768e01e8af84f58f3ceac958"
)
EXPECTED_STAGE08_STATUS = "STAGE08_CORE_24M_CERTIFIED_OK"
EXPECTED_FROZEN_GIT_HEAD = "a7ce86a06c406cf7cfbeb4927cdf40ba5bce4bee"

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

REQUIRED_COLUMNS = (
    "month",
    "game_id",
    "archive_ordinal",
    "chooser_username_norm",
    "kind_draw",
    "engine_eval_cp_disconnected",
    "fair_competitive",
    "clearly_worse",
    "excluded_middle",
    "chooser_draw_payoff_v2",
    "chooser_win_premium_v2",
    "api_speed",
    "chooser_elo",
    "tournament_like_event",
)

DENSITY_WIDTHS = (0.05, 0.10, 0.25, 0.50)
DENSITY_WINDOWS = (0.25, 0.50, 1.0, 2.0, 4.0, 6.0)
MODEL_BANDWIDTHS = (2.0, 6.0)
ZERO_SENSITIVITY_BANDWIDTHS = (0.5, 1.0, 2.0, 6.0)
PAYOFF_ZERO_TOLERANCE = 1e-12
FAIR_THRESHOLDS = (-50, -100, -150)
WORSE_THRESHOLDS = (-200, -300, -400, -500)


def utc_now() -> str:
    return pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def progress(message: str) -> None:
    print(f"[{utc_now()}] {message}", flush=True)


def sha256_file(path: Path, chunk_size: int = 16 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


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
        return json_sanitize(value.tolist())
    if hasattr(value, "item"):
        return json_sanitize(value.item())
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(
        path,
        json.dumps(json_sanitize(value), indent=2, sort_keys=True, allow_nan=False)
        + "\n",
    )


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    frame.to_csv(temporary, index=False, lineterminator="\n", float_format="%.15g")
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


def git_state() -> dict[str, str]:
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
    if len(set(months)) != len(months):
        raise ValueError("--months contains duplicates")
    unknown = [month for month in months if month not in MONTH_ROWS]
    if unknown:
        raise ValueError(f"Unknown months: {unknown}")
    canonical = tuple(month for month in ALL_MONTHS if month in set(months))
    if months != canonical:
        raise ValueError("--months must follow canonical chronological order")
    return months


def sql_path_list(paths: Sequence[Path]) -> str:
    return (
        "[" + ",".join("'" + str(path).replace("'", "''") + "'" for path in paths) + "]"
    )


def authenticate_inputs(months: Sequence[str], verify_hashes: bool) -> dict[str, Any]:
    success07 = PANEL_ROOT / "_SUCCESS.json"
    status_path = PANEL_ROOT / "_manifests/month_status.csv"
    producer07 = REPOSITORY / "code/07_build_analysis_panel.py"
    success08 = STAGE08_ROOT / "_SUCCESS.json"
    producer08 = REPOSITORY / "code/08_make_core_paper_results.py"
    for path in (success07, status_path, producer07, success08, producer08):
        if not path.is_file():
            raise RuntimeError(f"Required certified input is missing: {path}")

    hashes = {
        "stage07_success": sha256_file(success07),
        "stage07_producer": sha256_file(producer07),
        "stage08_success": sha256_file(success08),
        "stage08_producer": sha256_file(producer08),
    }
    expected = {
        "stage07_success": EXPECTED_STAGE07_SUMMARY_SHA256,
        "stage07_producer": EXPECTED_STAGE07_SCRIPT_SHA256,
        "stage08_success": EXPECTED_STAGE08_SUMMARY_SHA256,
        "stage08_producer": EXPECTED_STAGE08_SCRIPT_SHA256,
    }
    changed = [
        f"{key}: expected={expected[key]} actual={value}"
        for key, value in hashes.items()
        if value != expected[key]
    ]
    if changed:
        raise RuntimeError(
            "Certified Stage 07/08 authentication failed:\n" + "\n".join(changed)
        )

    summary07 = json.loads(success07.read_text(encoding="utf-8"))
    summary08 = json.loads(success08.read_text(encoding="utf-8"))
    if summary07.get("status") != EXPECTED_STAGE07_STATUS:
        raise RuntimeError(f"Stage 07 is not certified: {summary07.get('status')}")
    if summary08.get("status") != EXPECTED_STAGE08_STATUS:
        raise RuntimeError(f"Stage 08 is not certified: {summary08.get('status')}")
    qa07 = summary07.get("global_qa", {})
    if int(qa07.get("rows", -1)) != EXPECTED_STAGE07_ROWS:
        raise RuntimeError("Stage 07 row total changed")
    if int(qa07.get("kind_draws", -1)) != EXPECTED_STAGE07_KIND_DRAWS:
        raise RuntimeError("Stage 07 kind-draw total changed")

    status = pd.read_csv(status_path)
    if status["month"].astype(str).tolist() != list(ALL_MONTHS):
        raise RuntimeError("Stage 07 month-status ordering changed")
    records: list[dict[str, Any]] = []
    for month in months:
        item = status.loc[status["month"].astype(str) == month]
        if len(item) != 1:
            raise RuntimeError(
                f"Stage 07 month-status has {len(item)} rows for {month}"
            )
        row = item.iloc[0]
        path = PANEL_ROOT / f"month={month}/analysis_panel.parquet"
        if not path.is_file():
            raise RuntimeError(f"Missing Stage 07 month: {path}")
        parquet = pq.ParquetFile(path)
        names = parquet.schema_arrow.names
        missing = sorted(set(REQUIRED_COLUMNS) - set(names))
        if missing:
            raise RuntimeError(f"{month} lacks Stage 09 columns: {missing}")
        if len(names) != EXPECTED_STAGE07_COLUMNS:
            raise RuntimeError(f"{month} schema has {len(names)} columns, expected 157")
        if (
            parquet.metadata.num_rows != MONTH_ROWS[month]
            or int(row["rows"]) != MONTH_ROWS[month]
        ):
            raise RuntimeError(f"{month} row count changed")
        if int(row["output_size_bytes"]) != path.stat().st_size:
            raise RuntimeError(f"{month} file size changed")
        records.append(
            {
                "month": month,
                "path": path,
                "rows": MONTH_ROWS[month],
                "bytes": path.stat().st_size,
                "expected_sha256": str(row["output_sha256"]),
            }
        )
    if verify_hashes:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(4, len(records))
        ) as executor:
            futures = {
                executor.submit(sha256_file, record["path"]): record
                for record in records
            }
            for future in concurrent.futures.as_completed(futures):
                record = futures[future]
                actual = future.result()
                if actual != record["expected_sha256"]:
                    raise RuntimeError(f"Stage 07 SHA mismatch for {record['month']}")
                record["actual_sha256"] = actual
    return {
        "hashes": hashes,
        "stage07_summary": summary07,
        "stage08_summary": summary08,
        "month_records": records,
        "selected_rows": sum(record["rows"] for record in records),
        "selected_bytes": sum(record["bytes"] for record in records),
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


def configure_database(
    path: Path, paths: Sequence[Path], threads: int, memory_limit: str, temp: Path
) -> duckdb.DuckDBPyConnection:
    temp.mkdir(parents=True, exist_ok=True)
    database = duckdb.connect(str(path))
    database.execute(f"PRAGMA threads={int(threads)}")
    database.execute(f"PRAGMA memory_limit='{memory_limit}'")
    database.execute(
        f"PRAGMA temp_directory='{str(temp).replace(chr(39), chr(39) * 2)}'"
    )
    database.execute("PRAGMA preserve_insertion_order=false")
    database.execute(
        f"CREATE VIEW panel AS SELECT * FROM read_parquet({sql_path_list(paths)}, union_by_name=false)"
    )
    return database


def source_qa(
    database: duckdb.DuckDBPyConnection, expected_rows: int
) -> dict[str, int]:
    row = (
        database.execute(
            """
        SELECT
          COUNT(*)::BIGINT AS rows,
          COUNT(DISTINCT game_id)::BIGINT AS unique_game_ids,
          SUM(kind_draw::INTEGER)::BIGINT AS kind_draws,
          SUM(fair_competitive::INTEGER)::BIGINT AS fair_rows,
          SUM(clearly_worse::INTEGER)::BIGINT AS clearly_worse_rows,
          SUM(excluded_middle::INTEGER)::BIGINT AS excluded_middle_rows,
          SUM((chooser_username_norm IS NULL OR trim(chooser_username_norm)='')::INTEGER)::BIGINT AS missing_chooser,
          SUM((engine_eval_cp_disconnected IS NULL)::INTEGER)::BIGINT AS missing_eval,
          SUM((chooser_draw_payoff_v2 IS NULL)::INTEGER)::BIGINT AS missing_payoff,
          SUM((chooser_win_premium_v2 IS NULL)::INTEGER)::BIGINT AS missing_premium
        FROM panel
        """
        )
        .fetchdf()
        .iloc[0]
        .to_dict()
    )
    result = {key: int(value) for key, value in row.items()}
    if result["rows"] != expected_rows or result["unique_game_ids"] != expected_rows:
        raise RuntimeError(f"Stage 09 source cardinality failure: {result}")
    if (
        result["fair_rows"]
        + result["clearly_worse_rows"]
        + result["excluded_middle_rows"]
        != expected_rows
    ):
        raise RuntimeError(
            "Stage 07 fairness regions no longer partition selected rows"
        )
    for field in (
        "missing_chooser",
        "missing_eval",
        "missing_payoff",
        "missing_premium",
    ):
        if result[field] != 0:
            raise RuntimeError(
                f"Stage 09 source coverage failure: {field}={result[field]:,}"
            )
    return result


def add_rates(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["kind_rate_pct"] = 100.0 * result["kind_draws"] / result["rows"]
    probability = result["kind_draws"] / result["rows"]
    result["binomial_se_pp"] = 100.0 * np.sqrt(
        probability * (1.0 - probability) / result["rows"]
    )
    return result


def density_outputs(database: duckdb.DuckDBPyConnection, root: Path) -> dict[str, Any]:
    parts: list[pd.DataFrame] = []
    for sample, condition in (
        ("all_opportunities", "TRUE"),
        ("standard_fair", "fair_competitive"),
    ):
        for width in DENSITY_WIDTHS:
            frame = database.execute(
                f"""
                SELECT
                  floor((chooser_draw_payoff_v2 + 6.0) / {width})::BIGINT AS bin_number,
                  COUNT(*)::BIGINT AS rows,
                  AVG(chooser_draw_payoff_v2)::DOUBLE AS draw_payoff_mean,
                  COUNT(DISTINCT chooser_username_norm)::BIGINT AS chooser_count
                FROM panel
                WHERE {condition}
                  AND chooser_draw_payoff_v2 >= -6.0
                  AND chooser_draw_payoff_v2 <= 6.0
                GROUP BY 1 ORDER BY 1
                """
            ).fetchdf()
            frame.insert(0, "sample", sample)
            frame.insert(1, "bin_width", width)
            frame["bin_left"] = -6.0 + frame["bin_number"] * width
            frame["bin_right"] = frame["bin_left"] + width
            frame["bin_mid"] = (frame["bin_left"] + frame["bin_right"]) / 2.0
            parts.append(frame)
    binned = pd.concat(parts, ignore_index=True)
    write_csv(root / "figure_data/figureR01_draw_payoff_density.csv", binned)

    checks: list[dict[str, Any]] = []
    for sample, condition in (
        ("all_opportunities", "TRUE"),
        ("standard_fair", "fair_competitive"),
    ):
        for window in DENSITY_WINDOWS:
            row = (
                database.execute(
                    f"""
                SELECT
                  SUM((chooser_draw_payoff_v2 >= -{window} AND chooser_draw_payoff_v2 < 0)::INTEGER)::BIGINT AS left_rows,
                  SUM((abs(chooser_draw_payoff_v2) < 1e-12)::INTEGER)::BIGINT AS exact_zero_rows,
                  SUM((chooser_draw_payoff_v2 > 0 AND chooser_draw_payoff_v2 <= {window})::INTEGER)::BIGINT AS right_rows
                FROM panel WHERE {condition}
                """
                )
                .fetchdf()
                .iloc[0]
            )
            left, zero, right = (
                int(row.left_rows),
                int(row.exact_zero_rows),
                int(row.right_rows),
            )
            sided = left + right
            share = right / sided if sided else math.nan
            se = math.sqrt(0.25 / sided) if sided else math.nan
            checks.append(
                {
                    "sample": sample,
                    "window_half_width": window,
                    "left_rows_excluding_zero": left,
                    "exact_zero_rows": zero,
                    "right_rows_excluding_zero": right,
                    "sided_rows_excluding_zero": sided,
                    "right_share_excluding_zero": share,
                    "binomial_z_vs_half": (share - 0.5) / se if se > 0 else math.nan,
                    "log_right_left_ratio": math.log(right / left)
                    if left > 0 and right > 0
                    else math.nan,
                }
            )
    symmetry = pd.DataFrame(checks)
    write_csv(root / "tables/tableR01_density_symmetry.csv", symmetry)

    all_row = database.execute(
        """
        SELECT 'all_opportunities' AS sample_marker, COUNT(*)::BIGINT AS rows,
          SUM((abs(chooser_draw_payoff_v2) < 1e-12)::INTEGER)::BIGINT AS exact_zero_rows,
          SUM((abs(chooser_draw_payoff_v2 - round(chooser_draw_payoff_v2)) < 1e-9)::INTEGER)::BIGINT AS integer_point_rows,
          SUM((abs(2*chooser_draw_payoff_v2 - round(2*chooser_draw_payoff_v2)) < 1e-9)::INTEGER)::BIGINT AS half_point_rows
        FROM panel
        """
    ).fetchdf()
    fair_row = database.execute(
        """
        SELECT 'standard_fair' AS sample_marker, COUNT(*)::BIGINT AS rows,
          SUM((abs(chooser_draw_payoff_v2) < 1e-12)::INTEGER)::BIGINT AS exact_zero_rows,
          SUM((abs(chooser_draw_payoff_v2 - round(chooser_draw_payoff_v2)) < 1e-9)::INTEGER)::BIGINT AS integer_point_rows,
          SUM((abs(2*chooser_draw_payoff_v2 - round(2*chooser_draw_payoff_v2)) < 1e-9)::INTEGER)::BIGINT AS half_point_rows
        FROM panel WHERE fair_competitive
        """
    ).fetchdf()
    heaping = pd.concat([all_row, fair_row], ignore_index=True)
    for field in ("exact_zero_rows", "integer_point_rows", "half_point_rows"):
        heaping[field.replace("_rows", "_share")] = heaping[field] / heaping["rows"]
    write_csv(root / "tables/tableR02_running_variable_heaping.csv", heaping)
    return {
        "density_bin_rows": int(len(binned)),
        "symmetry_rows": int(len(symmetry)),
        "heaping": heaping.to_dict("records"),
    }


def subgroup_rates(database: duckdb.DuckDBPyConnection, root: Path) -> pd.DataFrame:
    dimensions = {
        "speed_tier": """
          CASE
            WHEN lower(api_speed) IN ('ultrabullet','bullet') THEN 'bullet_ultra'
            WHEN lower(api_speed)='blitz' THEN 'blitz'
            WHEN lower(api_speed)='rapid' THEN 'rapid'
            WHEN lower(api_speed)='classical' THEN 'classical_long'
            ELSE 'other'
          END
        """,
        "chooser_rating_tier": """
          CASE
            WHEN chooser_elo IS NULL THEN 'missing'
            WHEN chooser_elo < 1600 THEN 'below_1600'
            WHEN chooser_elo < 2000 THEN '1600_1999'
            WHEN chooser_elo < 2400 THEN '2000_2399'
            ELSE '2400_plus'
          END
        """,
        "tournament_status": "CASE WHEN tournament_like_event THEN 'tournament_like' ELSE 'ordinary' END",
    }
    parts: list[pd.DataFrame] = []
    for dimension, expression in dimensions.items():
        frame = database.execute(
            f"""
            SELECT '{dimension}' AS dimension, ({expression})::VARCHAR AS subgroup,
              CASE WHEN fair_competitive THEN 'fair' ELSE 'clearly_worse' END AS region,
              COUNT(*)::BIGINT AS rows,
              SUM(kind_draw::INTEGER)::BIGINT AS kind_draws,
              COUNT(DISTINCT chooser_username_norm)::BIGINT AS chooser_count
            FROM panel
            WHERE fair_competitive OR clearly_worse
            GROUP BY 1,2,3 ORDER BY 1,2,3
            """
        ).fetchdf()
        parts.append(add_rates(frame))
    long = pd.concat(parts, ignore_index=True)
    write_csv(root / "tables/tableR03_subgroup_fairness_rates_long.csv", long)
    wide = long.pivot(
        index=["dimension", "subgroup"],
        columns="region",
        values=["rows", "kind_draws", "kind_rate_pct"],
    ).reset_index()
    wide.columns = ["_".join(str(x) for x in item if str(x)) for item in wide.columns]
    wide["fair_minus_clearly_worse_pp"] = (
        wide["kind_rate_pct_fair"] - wide["kind_rate_pct_clearly_worse"]
    )
    wide["fair_to_clearly_worse_ratio"] = (
        wide["kind_rate_pct_fair"] / wide["kind_rate_pct_clearly_worse"]
    )
    write_csv(root / "tables/tableR04_subgroup_fairness_contrasts.csv", wide)
    return long


def dense_codes(values: np.ndarray) -> tuple[np.ndarray, int]:
    codes, uniques = pd.factorize(values, sort=False)
    if np.any(codes < 0):
        raise ValueError("Fixed-effect values contain missing codes")
    return codes.astype(np.int64, copy=False), int(len(uniques))


def demean_once(matrix: np.ndarray, codes: np.ndarray, levels: int) -> np.ndarray:
    residual = np.asarray(matrix, dtype=np.float64).copy()
    counts = np.bincount(codes, minlength=levels).astype(np.float64)
    valid = counts > 0
    for column in range(residual.shape[1]):
        sums = np.bincount(codes, weights=residual[:, column], minlength=levels)
        means = np.zeros(levels, dtype=np.float64)
        means[valid] = sums[valid] / counts[valid]
        residual[:, column] -= means[codes]
    return residual


def fit_lpm_cluster(
    y: np.ndarray,
    x: np.ndarray,
    names: Sequence[str],
    cluster: np.ndarray,
    fixed_effect: np.ndarray | None = None,
    add_intercept: bool = False,
) -> dict[str, Any]:
    y = np.asarray(y, dtype=np.float64)
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = x[:, None]
    cluster = np.asarray(cluster)
    finite = np.isfinite(y) & np.all(np.isfinite(x), axis=1) & pd.notna(cluster)
    if fixed_effect is not None:
        finite &= pd.notna(fixed_effect)
    y, x, cluster = y[finite], x[finite], cluster[finite]
    n_raw = int(len(y))
    output_names = list(names)
    absorption = "none"
    orthogonality = 0.0
    if fixed_effect is not None:
        fe, levels = dense_codes(np.asarray(fixed_effect)[finite])
        source = np.column_stack([y, x])
        transformed = demean_once(source, fe, levels)
        y, x = transformed[:, 0], transformed[:, 1:]
        counts = np.bincount(fe, minlength=levels).astype(np.float64)
        maximum = 0.0
        for column in range(transformed.shape[1]):
            means = np.bincount(fe, weights=transformed[:, column], minlength=levels)
            valid = counts > 0
            means[valid] /= counts[valid]
            scale = max(float(np.sqrt(np.mean(source[:, column] ** 2))), 1.0)
            maximum = max(maximum, float(np.max(np.abs(means[valid]))) / scale)
        orthogonality = maximum
        if orthogonality > 1e-10:
            raise RuntimeError(f"One-way FE absorption failed: {orthogonality:.3e}")
        absorption = "one_way_exact"
    elif add_intercept:
        x = np.column_stack([np.ones(n_raw), x])
        output_names = ["intercept", *output_names]

    identifying = np.any(np.abs(x) > 1e-14, axis=1)
    y, x, cluster = y[identifying], x[identifying], cluster[identifying]
    n, k = len(y), x.shape[1]
    if n <= k:
        raise ValueError(f"Too few identifying rows: n={n}, k={k}")
    xtx = x.T @ x
    inverse = np.linalg.pinv(xtx, hermitian=True)
    beta = inverse @ (x.T @ y)
    residual = y - x @ beta
    cluster_codes, cluster_levels = dense_codes(cluster)
    scores = np.column_stack(
        [
            np.bincount(
                cluster_codes, weights=x[:, j] * residual, minlength=cluster_levels
            )
            for j in range(k)
        ]
    )
    covariance = inverse @ (scores.T @ scores) @ inverse
    if cluster_levels > 1 and n > k:
        covariance *= (cluster_levels / (cluster_levels - 1.0)) * ((n - 1.0) / (n - k))
    se = np.sqrt(np.maximum(np.diag(covariance), 0.0))
    tstat = np.divide(beta, se, out=np.full_like(beta, np.nan), where=se > 0)
    return {
        "n_rows_raw": n_raw,
        "n_rows_identifying": int(n),
        "n_clusters": cluster_levels,
        "rank": int(np.linalg.matrix_rank(xtx)),
        "coefficients": dict(zip(output_names, map(float, beta))),
        "standard_errors": dict(zip(output_names, map(float, se))),
        "t_statistics": dict(zip(output_names, map(float, tstat))),
        "absorption_method": absorption,
        "absorption_max_scaled_group_mean": orthogonality,
    }


def load_model_panel(database: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    database.execute(
        """
        CREATE TEMP TABLE chooser_dimension AS
        SELECT chooser_username_norm,
          (row_number() OVER (ORDER BY chooser_username_norm)-1)::INTEGER AS chooser_id
        FROM (SELECT DISTINCT chooser_username_norm FROM panel)
        """
    )
    frame = database.execute(
        """
        SELECT d.chooser_id,
          CASE WHEN p.kind_draw THEN 100.0 ELSE 0.0 END::DOUBLE AS kind_pp,
          p.engine_eval_cp_disconnected::DOUBLE AS eval_cp,
          p.chooser_draw_payoff_v2::DOUBLE AS draw_payoff,
          abs(p.chooser_draw_payoff_v2::DOUBLE)::DOUBLE AS abs_draw_payoff,
          CASE WHEN p.chooser_draw_payoff_v2 >= 0 THEN 1.0 ELSE 0.0 END::DOUBLE AS favorable,
          p.chooser_win_premium_v2::DOUBLE AS win_premium,
          CASE
            WHEN lower(p.api_speed) IN ('ultrabullet','bullet') THEN 'bullet_ultra'
            WHEN lower(p.api_speed)='blitz' THEN 'blitz'
            WHEN lower(p.api_speed)='rapid' THEN 'rapid'
            WHEN lower(p.api_speed)='classical' THEN 'classical_long'
            ELSE 'other'
          END::VARCHAR AS speed_tier,
          CASE
            WHEN p.chooser_elo IS NULL THEN 'missing'
            WHEN p.chooser_elo < 1600 THEN 'below_1600'
            WHEN p.chooser_elo < 2000 THEN '1600_1999'
            WHEN p.chooser_elo < 2400 THEN '2000_2399'
            ELSE '2400_plus'
          END::VARCHAR AS chooser_rating_tier,
          CASE WHEN p.tournament_like_event THEN 'tournament_like' ELSE 'ordinary' END::VARCHAR AS tournament_status
        FROM panel p JOIN chooser_dimension d USING (chooser_username_norm)
        WHERE p.engine_eval_cp_disconnected >= -150
          AND abs(p.chooser_draw_payoff_v2) <= 6
        ORDER BY p.month, p.archive_ordinal
        """
    ).fetchdf()
    frame["chooser_id"] = frame["chooser_id"].astype(np.int64)
    for column in (
        "kind_pp",
        "eval_cp",
        "draw_payoff",
        "abs_draw_payoff",
        "favorable",
        "win_premium",
    ):
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    frame["exact_zero"] = (frame.draw_payoff.abs() < PAYOFF_ZERO_TOLERANCE).astype(
        "float64"
    )
    frame["strict_positive"] = (frame.draw_payoff >= PAYOFF_ZERO_TOLERANCE).astype(
        "float64"
    )
    frame["strict_negative"] = (frame.draw_payoff <= -PAYOFF_ZERO_TOLERANCE).astype(
        "float64"
    )
    if not np.all(
        frame[["strict_negative", "exact_zero", "strict_positive"]]
        .sum(axis=1)
        .to_numpy()
        == 1.0
    ):
        raise RuntimeError("Payoff-sign categories do not partition the model panel")
    return frame


def model_row(result: dict[str, Any], **labels: Any) -> dict[str, Any]:
    return {
        **labels,
        "coefficient_favorable_pp": result["coefficients"].get("favorable"),
        "se_favorable_pp": result["standard_errors"].get("favorable"),
        "t_favorable": result["t_statistics"].get("favorable"),
        "coefficient_win_premium": result["coefficients"].get("win_premium"),
        "se_win_premium": result["standard_errors"].get("win_premium"),
        "t_win_premium": result["t_statistics"].get("win_premium"),
        "rows_raw": result["n_rows_raw"],
        "rows_identifying": result["n_rows_identifying"],
        "chooser_clusters": result["n_clusters"],
        "matrix_rank": result["rank"],
        "absorption_method": result["absorption_method"],
        "absorption_max_scaled_group_mean": result["absorption_max_scaled_group_mean"],
    }


def regression_outputs(model: pd.DataFrame, root: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    dimensions = ("speed_tier", "chooser_rating_tier", "tournament_status")
    standard = model.loc[model.eval_cp >= -100].copy()
    for dimension in dimensions:
        for subgroup in sorted(standard[dimension].dropna().unique()):
            base = standard.loc[standard[dimension] == subgroup]
            for bandwidth in MODEL_BANDWIDTHS:
                sample = base.loc[base.abs_draw_payoff <= bandwidth]
                if len(sample) < 10_000 or sample.chooser_id.nunique() < 500:
                    rows.append(
                        {
                            "dimension": dimension,
                            "subgroup": subgroup,
                            "fair_threshold_cp": -100,
                            "bandwidth": bandwidth,
                            "status": "too_small",
                            "rows_raw": int(len(sample)),
                            "raw_choosers": int(sample.chooser_id.nunique()),
                        }
                    )
                    continue
                result = fit_lpm_cluster(
                    sample.kind_pp.to_numpy(),
                    sample[["favorable", "win_premium"]].to_numpy(),
                    ["favorable", "win_premium"],
                    sample.chooser_id.to_numpy(),
                    fixed_effect=sample.chooser_id.to_numpy(),
                )
                rows.append(
                    model_row(
                        result,
                        dimension=dimension,
                        subgroup=subgroup,
                        fair_threshold_cp=-100,
                        bandwidth=bandwidth,
                        status="ok",
                        raw_choosers=int(sample.chooser_id.nunique()),
                    )
                )
                progress(
                    f"subgroup model complete: {dimension}={subgroup}; bw={bandwidth:g}; rows={len(sample):,}"
                )
    frame = pd.DataFrame(rows)
    write_csv(root / "tables/tableR05_subgroup_zero_threshold_models.csv", frame)

    cutoff_rows: list[dict[str, Any]] = []
    for threshold in FAIR_THRESHOLDS:
        base = model.loc[model.eval_cp >= threshold]
        for bandwidth in MODEL_BANDWIDTHS:
            sample = base.loc[base.abs_draw_payoff <= bandwidth]
            result = fit_lpm_cluster(
                sample.kind_pp.to_numpy(),
                sample[["favorable", "win_premium"]].to_numpy(),
                ["favorable", "win_premium"],
                sample.chooser_id.to_numpy(),
                fixed_effect=sample.chooser_id.to_numpy(),
            )
            cutoff_rows.append(
                model_row(
                    result,
                    fair_threshold_cp=threshold,
                    fair_definition=f"eval_cp >= {threshold}",
                    bandwidth=bandwidth,
                    status="ok",
                    raw_choosers=int(sample.chooser_id.nunique()),
                )
            )
            progress(
                f"evaluation-threshold model complete: fair>={threshold}; bw={bandwidth:g}; rows={len(sample):,}"
            )
    cutoffs = pd.DataFrame(cutoff_rows)
    write_csv(root / "tables/tableR07_eval_cutoff_zero_threshold_models.csv", cutoffs)
    return {
        "model_panel_rows": int(len(model)),
        "subgroup_models": int(len(frame)),
        "cutoff_models": int(len(cutoffs)),
    }


def exact_zero_sensitivity_outputs(model: pd.DataFrame, root: Path) -> dict[str, Any]:
    """Separate the structural zero-payoff mass from either side of zero.

    The paper-facing favorable definition remains draw payoff >= 0.  These
    diagnostics verify that its estimate is not mechanically generated by the
    exact-zero mass.  Strictly negative payoff is the omitted category in the
    three-category specification.
    """

    standard = model.loc[model.eval_cp >= -100].copy()
    descriptive_parts: list[pd.DataFrame] = []
    model_rows: list[dict[str, Any]] = []
    for bandwidth in ZERO_SENSITIVITY_BANDWIDTHS:
        sample = standard.loc[standard.abs_draw_payoff <= bandwidth].copy()
        sample["payoff_sign"] = np.select(
            [
                sample.strict_negative.eq(1.0),
                sample.exact_zero.eq(1.0),
                sample.strict_positive.eq(1.0),
            ],
            ["strict_negative", "exact_zero", "strict_positive"],
            default="invalid",
        )
        descriptive = (
            sample.groupby("payoff_sign", observed=True)
            .agg(
                rows=("kind_pp", "size"),
                kind_draws=("kind_pp", lambda value: float(value.sum() / 100.0)),
                chooser_count=("chooser_id", "nunique"),
            )
            .reset_index()
        )
        if set(descriptive.payoff_sign) != {
            "strict_negative",
            "exact_zero",
            "strict_positive",
        }:
            raise RuntimeError(
                f"Payoff-sign support is incomplete at bandwidth {bandwidth:g}"
            )
        descriptive.insert(0, "bandwidth", bandwidth)
        descriptive["kind_rate_pct"] = 100.0 * descriptive.kind_draws / descriptive.rows
        descriptive_parts.append(descriptive)

        if bandwidth not in MODEL_BANDWIDTHS:
            continue

        nonzero = sample.loc[sample.exact_zero.eq(0.0)]
        excluded = fit_lpm_cluster(
            nonzero.kind_pp.to_numpy(),
            nonzero[["strict_positive", "win_premium"]].to_numpy(),
            ["strict_positive", "win_premium"],
            nonzero.chooser_id.to_numpy(),
            fixed_effect=nonzero.chooser_id.to_numpy(),
        )
        model_rows.append(
            {
                "specification": "exclude_exact_zero",
                "omitted_payoff_category": "strict_negative",
                "bandwidth": bandwidth,
                "coefficient_strict_positive_pp": excluded["coefficients"].get(
                    "strict_positive"
                ),
                "se_strict_positive_pp": excluded["standard_errors"].get(
                    "strict_positive"
                ),
                "t_strict_positive": excluded["t_statistics"].get("strict_positive"),
                "coefficient_exact_zero_pp": None,
                "se_exact_zero_pp": None,
                "t_exact_zero": None,
                "coefficient_win_premium": excluded["coefficients"].get("win_premium"),
                "se_win_premium": excluded["standard_errors"].get("win_premium"),
                "t_win_premium": excluded["t_statistics"].get("win_premium"),
                "rows_raw": excluded["n_rows_raw"],
                "rows_identifying": excluded["n_rows_identifying"],
                "chooser_clusters": excluded["n_clusters"],
                "matrix_rank": excluded["rank"],
                "absorption_method": excluded["absorption_method"],
                "absorption_max_scaled_group_mean": excluded[
                    "absorption_max_scaled_group_mean"
                ],
            }
        )

        separate = fit_lpm_cluster(
            sample.kind_pp.to_numpy(),
            sample[["strict_positive", "exact_zero", "win_premium"]].to_numpy(),
            ["strict_positive", "exact_zero", "win_premium"],
            sample.chooser_id.to_numpy(),
            fixed_effect=sample.chooser_id.to_numpy(),
        )
        model_rows.append(
            {
                "specification": "exact_zero_separate_category",
                "omitted_payoff_category": "strict_negative",
                "bandwidth": bandwidth,
                "coefficient_strict_positive_pp": separate["coefficients"].get(
                    "strict_positive"
                ),
                "se_strict_positive_pp": separate["standard_errors"].get(
                    "strict_positive"
                ),
                "t_strict_positive": separate["t_statistics"].get("strict_positive"),
                "coefficient_exact_zero_pp": separate["coefficients"].get("exact_zero"),
                "se_exact_zero_pp": separate["standard_errors"].get("exact_zero"),
                "t_exact_zero": separate["t_statistics"].get("exact_zero"),
                "coefficient_win_premium": separate["coefficients"].get("win_premium"),
                "se_win_premium": separate["standard_errors"].get("win_premium"),
                "t_win_premium": separate["t_statistics"].get("win_premium"),
                "rows_raw": separate["n_rows_raw"],
                "rows_identifying": separate["n_rows_identifying"],
                "chooser_clusters": separate["n_clusters"],
                "matrix_rank": separate["rank"],
                "absorption_method": separate["absorption_method"],
                "absorption_max_scaled_group_mean": separate[
                    "absorption_max_scaled_group_mean"
                ],
            }
        )
        progress(
            f"exact-zero sensitivity complete: bandwidth={bandwidth:g}; "
            f"rows={len(sample):,}; exact_zero={int(sample.exact_zero.sum()):,}"
        )

    descriptives = pd.concat(descriptive_parts, ignore_index=True)
    models = pd.DataFrame(model_rows)
    write_csv(root / "tables/tableR11_exact_zero_payoff_descriptives.csv", descriptives)
    write_csv(root / "tables/tableR12_exact_zero_payoff_models.csv", models)
    return {
        "payoff_zero_tolerance": PAYOFF_ZERO_TOLERANCE,
        "standard_fair_exact_zero_rows": int(standard.exact_zero.sum()),
        "descriptive_rows": int(len(descriptives)),
        "model_rows": int(len(models)),
        "maximum_absorption_scaled_group_mean": float(
            models.absorption_max_scaled_group_mean.max()
        ),
    }


def cutoff_rate_outputs(
    database: duckdb.DuckDBPyConnection, root: Path
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for fair_threshold in FAIR_THRESHOLDS:
        for worse_threshold in WORSE_THRESHOLDS:
            row = (
                database.execute(
                    f"""
                SELECT
                  SUM((engine_eval_cp_disconnected >= {fair_threshold})::INTEGER)::BIGINT AS fair_rows,
                  SUM((engine_eval_cp_disconnected >= {fair_threshold} AND kind_draw)::INTEGER)::BIGINT AS fair_kind_draws,
                  SUM((engine_eval_cp_disconnected <= {worse_threshold})::INTEGER)::BIGINT AS worse_rows,
                  SUM((engine_eval_cp_disconnected <= {worse_threshold} AND kind_draw)::INTEGER)::BIGINT AS worse_kind_draws
                FROM panel
                """
                )
                .fetchdf()
                .iloc[0]
            )
            fair_rows, fair_kinds = int(row.fair_rows), int(row.fair_kind_draws)
            worse_rows, worse_kinds = int(row.worse_rows), int(row.worse_kind_draws)
            fair_rate = 100.0 * fair_kinds / fair_rows if fair_rows else math.nan
            worse_rate = 100.0 * worse_kinds / worse_rows if worse_rows else math.nan
            rows.append(
                {
                    "fair_threshold_cp": fair_threshold,
                    "clearly_worse_threshold_cp": worse_threshold,
                    "fair_rows": fair_rows,
                    "fair_kind_draws": fair_kinds,
                    "fair_kind_rate_pct": fair_rate,
                    "clearly_worse_rows": worse_rows,
                    "clearly_worse_kind_draws": worse_kinds,
                    "clearly_worse_kind_rate_pct": worse_rate,
                    "excluded_middle_rows": int(
                        database.execute(
                            f"SELECT COUNT(*) FROM panel WHERE engine_eval_cp_disconnected < {fair_threshold} AND engine_eval_cp_disconnected > {worse_threshold}"
                        ).fetchone()[0]
                    ),
                    "fair_minus_clearly_worse_pp": fair_rate - worse_rate,
                    "fair_to_clearly_worse_ratio": fair_rate / worse_rate
                    if worse_rate and math.isfinite(worse_rate)
                    else math.nan,
                }
            )
    frame = pd.DataFrame(rows)
    write_csv(root / "tables/tableR06_eval_cutoff_rate_grid.csv", frame)
    return frame


def economic_outputs(database: duckdb.DuckDBPyConnection, root: Path) -> dict[str, Any]:
    samples = {
        "all_opportunities": "TRUE",
        "standard_fair": "fair_competitive",
        "standard_clearly_worse": "clearly_worse",
        "fair_kind_draws": "fair_competitive AND kind_draw",
        "fair_favorable_kind_draws": "fair_competitive AND kind_draw AND chooser_draw_payoff_v2 >= 0",
        "fair_costly_kind_draws": "fair_competitive AND kind_draw AND chooser_draw_payoff_v2 < 0",
    }
    rows: list[dict[str, Any]] = []
    for sample, condition in samples.items():
        row = (
            database.execute(
                f"""
            SELECT COUNT(*)::BIGINT AS rows, SUM(kind_draw::INTEGER)::BIGINT AS kind_draws,
              AVG(chooser_draw_payoff_v2)::DOUBLE AS mean_draw_payoff,
              quantile_cont(chooser_draw_payoff_v2, 0.5)::DOUBLE AS median_draw_payoff,
              AVG(chooser_win_premium_v2)::DOUBLE AS mean_win_premium_points_forgone,
              quantile_cont(chooser_win_premium_v2, 0.25)::DOUBLE AS p25_win_premium,
              quantile_cont(chooser_win_premium_v2, 0.5)::DOUBLE AS median_win_premium,
              quantile_cont(chooser_win_premium_v2, 0.75)::DOUBLE AS p75_win_premium,
              SUM(CASE WHEN kind_draw THEN chooser_win_premium_v2 ELSE 0 END)::DOUBLE AS total_win_premium_points_forgone
            FROM panel WHERE {condition}
            """
            )
            .fetchdf()
            .iloc[0]
            .to_dict()
        )
        rows.append({"sample": sample, **row})
    magnitudes = pd.DataFrame(rows)
    write_csv(root / "tables/tableR08_economic_magnitude.csv", magnitudes)

    cells = add_rates(
        database.execute(
            """
            SELECT
              CASE
                WHEN fair_competitive AND chooser_draw_payoff_v2 >= 0 THEN 'fair_favorable'
                WHEN fair_competitive THEN 'fair_costly'
                WHEN clearly_worse THEN 'clearly_worse'
                ELSE 'excluded_middle'
              END AS cell,
              COUNT(*)::BIGINT AS rows, SUM(kind_draw::INTEGER)::BIGINT AS kind_draws
            FROM panel GROUP BY 1 ORDER BY 1
            """
        ).fetchdf()
    )
    write_csv(root / "tables/tableR09_economic_counterfactual_cells.csv", cells)
    index = cells.set_index("cell")
    fair_rows = float(
        index.loc["fair_favorable", "rows"] + index.loc["fair_costly", "rows"]
    )
    fair_kinds = float(
        index.loc["fair_favorable", "kind_draws"]
        + index.loc["fair_costly", "kind_draws"]
    )
    fair_rate = 100.0 * fair_kinds / fair_rows
    worse_rate = float(index.loc["clearly_worse", "kind_rate_pct"])
    fairness_excess = fair_rows * (fair_rate - worse_rate) / 100.0
    favorable_rows = float(index.loc["fair_favorable", "rows"])
    favorable_rate = float(index.loc["fair_favorable", "kind_rate_pct"])
    costly_rate = float(index.loc["fair_costly", "kind_rate_pct"])
    price_excess = favorable_rows * (favorable_rate - costly_rate) / 100.0
    counterfactual = pd.DataFrame(
        [
            {
                "benchmark": "fairness_gap_descriptive",
                "treated_rows": fair_rows,
                "treated_rate_pct": fair_rate,
                "comparison_rate_pct": worse_rate,
                "implied_excess_kind_draws": fairness_excess,
                "share_of_fair_kind_draws": fairness_excess / fair_kinds,
                "interpretation": "Descriptive benchmark; not a causal estimand",
            },
            {
                "benchmark": "favorable_vs_costly_within_fair_descriptive",
                "treated_rows": favorable_rows,
                "treated_rate_pct": favorable_rate,
                "comparison_rate_pct": costly_rate,
                "implied_excess_kind_draws": price_excess,
                "share_of_fair_kind_draws": price_excess / fair_kinds,
                "interpretation": "Descriptive benchmark; not a causal estimand",
            },
        ]
    )
    write_csv(root / "tables/tableR10_descriptive_excess_kindness.csv", counterfactual)
    kind_row = magnitudes.loc[magnitudes["sample"] == "fair_kind_draws"].iloc[0]
    return {
        "fair_kind_draws": int(kind_row["rows"]),
        "mean_rating_points_forgone": float(
            kind_row["mean_win_premium_points_forgone"]
        ),
        "total_rating_points_forgone": float(
            kind_row["total_win_premium_points_forgone"]
        ),
        "descriptive_benchmarks": counterfactual.to_dict("records"),
    }


def output_manifest(root: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if (
            not path.is_file()
            or path.name.startswith(".")
            or path.suffix in {".duckdb", ".wal"}
        ):
            continue
        relative = path.relative_to(root).as_posix()
        if relative in {
            "_SUCCESS.json",
            "_SELECTED_SUCCESS.json",
            "manifest_sha256.csv",
        }:
            continue
        rows.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return pd.DataFrame(rows)


def validate_outputs(root: Path, source: dict[str, int]) -> dict[str, Any]:
    expected = [
        "figure_data/figureR01_draw_payoff_density.csv",
        "tables/tableR01_density_symmetry.csv",
        "tables/tableR02_running_variable_heaping.csv",
        "tables/tableR03_subgroup_fairness_rates_long.csv",
        "tables/tableR04_subgroup_fairness_contrasts.csv",
        "tables/tableR05_subgroup_zero_threshold_models.csv",
        "tables/tableR06_eval_cutoff_rate_grid.csv",
        "tables/tableR07_eval_cutoff_zero_threshold_models.csv",
        "tables/tableR08_economic_magnitude.csv",
        "tables/tableR09_economic_counterfactual_cells.csv",
        "tables/tableR10_descriptive_excess_kindness.csv",
        "tables/tableR11_exact_zero_payoff_descriptives.csv",
        "tables/tableR12_exact_zero_payoff_models.csv",
    ]
    missing = [path for path in expected if not (root / path).is_file()]
    if missing:
        raise RuntimeError(f"Missing Stage 09 outputs: {missing}")
    for relative in expected:
        if pd.read_csv(root / relative).empty:
            raise RuntimeError(f"Empty Stage 09 output: {relative}")
    cells = pd.read_csv(root / "tables/tableR09_economic_counterfactual_cells.csv")
    if (
        int(cells.rows.sum()) != source["rows"]
        or int(cells.kind_draws.sum()) != source["kind_draws"]
    ):
        raise RuntimeError("Economic cells do not reproduce selected source totals")
    zero_models = pd.read_csv(root / "tables/tableR12_exact_zero_payoff_models.csv")
    if set(zero_models.specification) != {
        "exclude_exact_zero",
        "exact_zero_separate_category",
    }:
        raise RuntimeError("Exact-zero sensitivity specifications are incomplete")
    if len(zero_models) != 2 * len(MODEL_BANDWIDTHS):
        raise RuntimeError("Exact-zero sensitivity model count changed")
    return {"status": "STAGE09_OUTPUT_QA_OK", "expected_outputs_checked": len(expected)}


def run_self_test() -> None:
    chooser = np.repeat(np.arange(60), 20)
    rng = np.random.default_rng(20260821)
    x = rng.normal(size=(len(chooser), 2))
    fe = rng.normal(size=60)[chooser]
    y = 0.7 * x[:, 0] - 0.2 * x[:, 1] + fe + rng.normal(scale=0.05, size=len(chooser))
    result = fit_lpm_cluster(y, x, ["x0", "x1"], chooser, fixed_effect=chooser)
    if (
        abs(result["coefficients"]["x0"] - 0.7) > 0.01
        or abs(result["coefficients"]["x1"] + 0.2) > 0.01
    ):
        raise RuntimeError(
            f"Stage 09 regression self-test failed: {result['coefficients']}"
        )
    if result["absorption_max_scaled_group_mean"] > 1e-10:
        raise RuntimeError("Stage 09 absorption self-test failed")
    print("STAGE09_NUMERICAL_SELF_TEST_OK")
    print(f"x0: {result['coefficients']['x0']:.8f}")
    print(f"x1: {result['coefficients']['x1']:.8f}")
    print(f"orthogonality: {result['absorption_max_scaled_group_mean']:.3e}")


def print_plan(
    args: argparse.Namespace,
    months: Sequence[str],
    authenticated: dict[str, Any],
    state: dict[str, str],
    script_path: Path,
) -> None:
    print("STAGE09_PLAN_OK")
    print(f"script_version: {SCRIPT_VERSION}")
    print(f"script_sha256: {sha256_file(script_path)}")
    print(f"git_head: {state['head']}")
    print(f"months: {','.join(months)}")
    print(f"selected_rows: {authenticated['selected_rows']:,}")
    print(f"selected_input_bytes: {authenticated['selected_bytes']:,}")
    print(f"output_root: {Path(args.output_root).expanduser().resolve()}")
    print(f"threads: {args.threads}")
    print(f"memory_limit: {args.memory_limit}")
    print(f"stage07_summary_sha256: {authenticated['hashes']['stage07_success']}")
    print(f"stage08_summary_sha256: {authenticated['hashes']['stage08_success']}")
    print(
        "scope: density/support, exact-zero payoff sensitivity, speed/rating/tournament heterogeneity, evaluation cutoffs, economic magnitude"
    )
    print(
        "excluded: patron/profile data and opening metadata (handled by the companion Stage 09 opening module)"
    )
    print("No files were written. Re-run with --execute to build selected months.")


def execute(args: argparse.Namespace, months: Sequence[str], script_path: Path) -> None:
    started = time.time()
    output_root = Path(args.output_root).expanduser().resolve()
    if output_root.exists():
        raise RuntimeError(
            f"Output root already exists; refusing to overwrite: {output_root}"
        )
    output_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_root.with_name(f".{output_root.name}.tmp.{os.getpid()}")
    if temporary.exists():
        raise RuntimeError(f"Transactional temporary root already exists: {temporary}")
    (temporary / "tables").mkdir(parents=True)
    (temporary / "figure_data").mkdir()
    (temporary / "receipts").mkdir()
    (temporary / "_work/duckdb_tmp").mkdir(parents=True)
    database: duckdb.DuckDBPyConnection | None = None
    try:
        progress(f"START Stage 09 v{SCRIPT_VERSION}; months={','.join(months)}")
        authenticated = authenticate_inputs(months, verify_hashes=True)
        state = git_state()
        if args.expected_git_head and state["head"] != args.expected_git_head:
            raise RuntimeError(
                f"Git HEAD mismatch: expected={args.expected_git_head} actual={state['head']}"
            )
        allowed = {
            "?? code/09_build_panel_robustness.py",
            "?? code/09_prepare_opening_familiarity.py",
            "?? code/09_fetch_opening_metadata.py",
            "?? code/09_analyze_opening_familiarity.py",
        }
        unexpected = sorted(set(state["status_porcelain"].splitlines()) - allowed)
        if unexpected:
            raise RuntimeError(f"Repository contains unrelated changes: {unexpected}")
        database = configure_database(
            temporary / "_work/stage09.duckdb",
            [record["path"] for record in authenticated["month_records"]],
            args.threads,
            args.memory_limit,
            temporary / "_work/duckdb_tmp",
        )
        source = source_qa(database, authenticated["selected_rows"])
        progress(
            f"source QA passed; rows={source['rows']:,}; fair={source['fair_rows']:,}"
        )
        density = density_outputs(database, temporary)
        progress("density/support outputs complete")
        subgroup_rates(database, temporary)
        progress("subgroup descriptive outputs complete")
        cutoff_rate_outputs(database, temporary)
        progress("evaluation-cutoff rate grid complete")
        economic = economic_outputs(database, temporary)
        progress("economic-magnitude outputs complete")
        model = load_model_panel(database)
        progress(f"model panel loaded; rows={len(model):,}")
        regressions = regression_outputs(model, temporary)
        progress("subgroup and cutoff regressions complete")
        exact_zero = exact_zero_sensitivity_outputs(model, temporary)
        del model
        progress("exact-zero payoff sensitivity complete")
        qa = validate_outputs(temporary, source)
        database.close()
        database = None
        shutil.rmtree(temporary / "_work")
        manifest = output_manifest(temporary)
        write_csv(temporary / "manifest_sha256.csv", manifest)
        manifest_sha = sha256_file(temporary / "manifest_sha256.csv")
        full = tuple(months) == ALL_MONTHS
        status = (
            "STAGE09_PANEL_ROBUSTNESS_24M_CERTIFIED_OK"
            if full
            else "STAGE09_SELECTED_MONTHS_OK"
        )
        summary = {
            "status": status,
            "created_at_utc": utc_now(),
            "script_version": SCRIPT_VERSION,
            "script_path": str(script_path),
            "script_sha256": sha256_file(script_path),
            "git": state,
            "months": list(months),
            "full_24_month_run": full,
            "stage07_summary_sha256": authenticated["hashes"]["stage07_success"],
            "stage08_summary_sha256": authenticated["hashes"]["stage08_success"],
            "monthly_inputs": [
                {
                    "month": record["month"],
                    "path": str(record["path"]),
                    "rows": record["rows"],
                    "bytes": record["bytes"],
                    "sha256": record.get("actual_sha256", record["expected_sha256"]),
                }
                for record in authenticated["month_records"]
            ],
            "scope": {
                "included": [
                    "running-variable density, support, and heaping diagnostics",
                    "exact-zero payoff exclusion and separate-category sensitivity",
                    "speed, chooser-rating, and tournament subgroup robustness",
                    "nonoverlapping engine-evaluation cutoff sensitivity",
                    "rating-point and descriptive-count economic magnitudes",
                ],
                "excluded": [
                    "patron/profile analyses",
                    "opening familiarity (companion module)",
                ],
                "interpretation_guardrail": "Density and excess-count outputs are descriptive diagnostics, not causal estimands.",
            },
            "software": software_versions(),
            "source_qa": source,
            "density": density,
            "regressions": regressions,
            "exact_zero_sensitivity": exact_zero,
            "economic_magnitude": economic,
            "output_qa": qa,
            "manifest_sha256": manifest_sha,
            "manifest_files": int(len(manifest)),
            "runtime_seconds": round(time.time() - started, 3),
        }
        atomic_write_json(
            temporary / ("_SUCCESS.json" if full else "_SELECTED_SUCCESS.json"), summary
        )
        os.replace(temporary, output_root)
        print(status)
        print(f"output_root: {output_root}")
        print(f"rows: {source['rows']:,}")
        print(f"kind_draws: {source['kind_draws']:,}")
        print(f"manifest_sha256: {manifest_sha}")
        print(f"runtime_seconds: {time.time() - started:,.1f}")
    except Exception:
        if database is not None:
            try:
                database.close()
            except Exception:
                pass
        try:
            atomic_write_json(
                temporary / "_FAILED.json",
                {
                    "status": "STAGE09_FAILED",
                    "created_at_utc": utc_now(),
                    "script_version": SCRIPT_VERSION,
                    "script_sha256": sha256_file(script_path),
                    "months": list(months),
                    "error": traceback.format_exc(),
                },
            )
        except Exception:
            pass
        print("STAGE09_FAIL_CLOSED", file=sys.stderr)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--months", default="all")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--memory-limit", default="12GB")
    parser.add_argument("--expected-git-head", default="")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        run_self_test()
        return
    if not 1 <= args.threads <= 32:
        raise SystemExit("--threads must be between 1 and 32")
    months = parse_months(args.months)
    script_path = Path(__file__).resolve()
    try:
        state = git_state()
        if state["branch"] != "main":
            raise RuntimeError(
                f"Repository branch is {state['branch']!r}, expected 'main'"
            )
        if args.execute:
            execute(args, months, script_path)
        else:
            authenticated = authenticate_inputs(months, verify_hashes=False)
            print_plan(args, months, authenticated, state, script_path)
    except Exception as exc:
        print(f"STAGE09_FAIL_CLOSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
