#!/usr/bin/env python3
"""Analyze opening familiarity against the certified 100k-node Stage 07 panel.

The analysis reproduces the legacy prior-calendar-month familiarity definition
and extends it to both ECO and named-opening identities.  A selected-month run
must be a chronological prefix of the 24-month sample so familiarity history is
well defined.  Full certification requires a metadata record (including an
explicit not-returned record) for every target game.

Dry-run is the default.  ``--execute`` writes transactionally.
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
DEFAULT_PLAN_ROOT = PROJECT / "derived/replication/opening_familiarity_24m_plan_v100"
DEFAULT_OUTPUT_ROOT = (
    PROJECT / "derived/replication/opening_familiarity_results_24m_sf100k_v110"
)

EXPECTED_STAGE07_SCRIPT_SHA256 = (
    "0411d4061ea9831c20449208a9782aaf668e160139918d106a2b7d63aaa56e6e"
)
EXPECTED_STAGE07_SUMMARY_SHA256 = (
    "8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7"
)
EXPECTED_STAGE07_STATUS = "STAGE07_24M_CERTIFIED_OK"
EXPECTED_STAGE07_ROWS = 47_587_020
EXPECTED_STAGE07_COLUMNS = 157
EXPECTED_STAGE08_UPSTREAM_GIT_HEAD = "a7ce86a06c406cf7cfbeb4927cdf40ba5bce4bee"

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


def parse_months(text: str) -> tuple[str, ...]:
    if text.strip().lower() in {"all", "full", "24m"}:
        return ALL_MONTHS
    months = tuple(part.strip() for part in text.split(",") if part.strip())
    if not months:
        raise ValueError("--months selected no months")
    if months != ALL_MONTHS[: len(months)]:
        raise ValueError(
            "Opening-familiarity selected months must be a chronological prefix beginning 2023-11"
        )
    return months


def sql_path_list(paths: Sequence[Path]) -> str:
    return (
        "[" + ",".join("'" + str(path).replace("'", "''") + "'" for path in paths) + "]"
    )


def quoted(path: Path) -> str:
    return str(path).replace("'", "''")


def authenticate_stage07(months: Sequence[str], verify_hashes: bool) -> dict[str, Any]:
    success = PANEL_ROOT / "_SUCCESS.json"
    status_path = PANEL_ROOT / "_manifests/month_status.csv"
    producer = REPOSITORY / "code/07_build_analysis_panel.py"
    for path in (success, status_path, producer):
        if not path.is_file():
            raise RuntimeError(f"Required Stage 07 file is missing: {path}")
    success_sha = sha256_file(success)
    producer_sha = sha256_file(producer)
    if success_sha != EXPECTED_STAGE07_SUMMARY_SHA256:
        raise RuntimeError(f"Stage 07 success SHA mismatch: {success_sha}")
    if producer_sha != EXPECTED_STAGE07_SCRIPT_SHA256:
        raise RuntimeError(f"Stage 07 producer SHA mismatch: {producer_sha}")
    summary = json.loads(success.read_text(encoding="utf-8"))
    if summary.get("status") != EXPECTED_STAGE07_STATUS:
        raise RuntimeError(f"Stage 07 is not certified: {summary.get('status')}")
    if int(summary.get("global_qa", {}).get("rows", -1)) != EXPECTED_STAGE07_ROWS:
        raise RuntimeError("Stage 07 row total changed")
    status = pd.read_csv(status_path)
    if status["month"].astype(str).tolist() != list(ALL_MONTHS):
        raise RuntimeError("Stage 07 month ordering changed")
    records: list[dict[str, Any]] = []
    required = {
        "month",
        "game_id",
        "archive_ordinal",
        "ply_count",
        "chooser_username_norm",
        "kind_draw",
        "fair_competitive",
        "engine_eval_cp_disconnected",
        "chooser_draw_payoff_v2",
        "chooser_win_premium_v2",
    }
    for month in months:
        item = status.loc[status["month"].astype(str) == month].iloc[0]
        path = PANEL_ROOT / f"month={month}/analysis_panel.parquet"
        if not path.is_file():
            raise RuntimeError(f"Stage 07 month is missing: {path}")
        parquet = pq.ParquetFile(path)
        if (
            parquet.metadata.num_rows != MONTH_ROWS[month]
            or int(item["rows"]) != MONTH_ROWS[month]
        ):
            raise RuntimeError(f"Stage 07 row count changed for {month}")
        if len(parquet.schema_arrow.names) != EXPECTED_STAGE07_COLUMNS:
            raise RuntimeError(f"Stage 07 schema count changed for {month}")
        if not required.issubset(parquet.schema_arrow.names):
            raise RuntimeError(f"Stage 07 opening-analysis columns missing for {month}")
        if int(item["output_size_bytes"]) != path.stat().st_size:
            raise RuntimeError(f"Stage 07 file size changed for {month}")
        records.append(
            {
                "month": month,
                "path": path,
                "rows": MONTH_ROWS[month],
                "bytes": path.stat().st_size,
                "expected_sha256": str(item["output_sha256"]),
            }
        )
    if verify_hashes:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(4, len(records))
        ) as executor:
            futures = {
                executor.submit(sha256_file, row["path"]): row for row in records
            }
            for future in concurrent.futures.as_completed(futures):
                row = futures[future]
                actual = future.result()
                if actual != row["expected_sha256"]:
                    raise RuntimeError(f"Stage 07 SHA mismatch for {row['month']}")
                row["actual_sha256"] = actual
    return {
        "success_sha256": success_sha,
        "producer_sha256": producer_sha,
        "records": records,
        "selected_rows": sum(row["rows"] for row in records),
    }


def authenticate_plan(root: Path) -> tuple[dict[str, Any], str, Path, Path]:
    success = root / "_SUCCESS.json"
    target = root / "targets/opening_targets_all.parquet"
    seed = root / "seed/legacy_opening_mapping_stage07_overlap.parquet"
    hashes_path = root / "plan_file_hashes.tsv"
    for path in (success, target, seed, hashes_path):
        if not path.is_file():
            raise RuntimeError(f"Opening plan is incomplete: {path}")
    value = json.loads(success.read_text(encoding="utf-8"))
    if value.get("status") != "OPENING_FAMILIARITY_PLAN_CERTIFIED_OK":
        raise RuntimeError(f"Opening plan status changed: {value.get('status')}")
    if value.get("stage07_summary_sha256") != EXPECTED_STAGE07_SUMMARY_SHA256:
        raise RuntimeError("Opening plan references another Stage 07 input")
    if sha256_file(hashes_path) != value.get("plan_file_hashes_sha256"):
        raise RuntimeError("Opening plan hash manifest changed")
    if pq.ParquetFile(target).metadata.num_rows != int(value["plan_qa"]["target_rows"]):
        raise RuntimeError("Opening target Parquet row count changed")
    if pq.ParquetFile(seed).metadata.num_rows != int(
        value["plan_qa"]["reusable_seed_rows"]
    ):
        raise RuntimeError("Opening seed Parquet row count changed")
    hashes = pd.read_csv(hashes_path, sep="\t")
    for row in hashes.itertuples(index=False):
        path = root / str(row.path)
        if not path.is_file() or path.stat().st_size != int(row.bytes):
            raise RuntimeError(f"Opening plan file size changed: {path}")
        if sha256_file(path) != str(row.sha256):
            raise RuntimeError(f"Opening plan file SHA changed: {path}")
    return value, sha256_file(success), target, seed


def authenticate_fetch_roots(
    roots: Sequence[str], plan_sha: str
) -> tuple[list[Path], list[dict[str, Any]]]:
    normalized_paths: list[Path] = []
    records: list[dict[str, Any]] = []
    seen_batches: set[int] = set()
    for text in roots:
        root = Path(text).expanduser().resolve()
        config_path = root / "config.json"
        ledger_path = root / "completed_request_batches.json"
        if not config_path.is_file() or not ledger_path.is_file():
            raise RuntimeError(f"Fetch root lacks config or completion ledger: {root}")
        config = json.loads(config_path.read_text(encoding="utf-8"))
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        if config.get("plan_success_sha256") != plan_sha:
            raise RuntimeError(f"Fetch root config references another plan: {root}")
        if ledger.get("plan_success_sha256") != plan_sha:
            raise RuntimeError(f"Fetch root ledger references another plan: {root}")
        completed = ledger.get("completed_request_batches", {})
        if not isinstance(completed, dict):
            raise RuntimeError(f"Fetch completion ledger is malformed: {ledger_path}")
        root_batches = {int(item) for item in completed}
        overlap = root_batches & seen_batches
        if overlap:
            raise RuntimeError(
                f"Fetch roots contain overlapping request batches: {sorted(overlap)[:10]}"
            )
        seen_batches |= root_batches
        returned = 0
        explicit_missing = 0
        for batch_text, expected_receipt_sha in completed.items():
            batch = int(batch_text)
            macro = (batch - 1) // 400 + 1
            receipt_path = (
                root / f"batches/macro_{macro:04d}/request_{batch:06d}.receipt.json"
            )
            if (
                not receipt_path.is_file()
                or sha256_file(receipt_path) != expected_receipt_sha
            ):
                raise RuntimeError(
                    f"Fetch receipt failed authentication: {receipt_path}"
                )
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if receipt.get("status") != "OPENING_REQUEST_CERTIFIED_OK":
                raise RuntimeError(f"Fetch receipt status changed: {receipt_path}")
            raw = root / receipt["raw_relative_path"]
            normalized = root / receipt["normalized_relative_path"]
            if sha256_file(raw) != receipt["raw_sha256"]:
                raise RuntimeError(f"Raw response SHA mismatch: {raw}")
            if sha256_file(normalized) != receipt["normalized_sha256"]:
                raise RuntimeError(f"Normalized response SHA mismatch: {normalized}")
            parquet = pq.ParquetFile(normalized)
            if parquet.metadata.num_rows != int(receipt["normalized_rows"]):
                raise RuntimeError(f"Normalized response rows changed: {normalized}")
            ids = (
                pd.read_parquet(normalized, columns=["game_id"])["game_id"]
                .astype(str)
                .tolist()
            )
            ids_sha = hashlib.sha256(
                ("\n".join(ids) + "\n").encode("ascii")
            ).hexdigest()
            if ids_sha != receipt["requested_game_ids_sha256"]:
                raise RuntimeError(
                    f"Normalized response game-ID order changed: {normalized}"
                )
            normalized_paths.append(normalized)
            returned += int(receipt["returned_games"])
            explicit_missing += int(receipt["explicit_not_returned_rows"])
        records.append(
            {
                "root": str(root),
                "direction": config.get("direction"),
                "config_sha256": sha256_file(config_path),
                "ledger_sha256": sha256_file(ledger_path),
                "completed_request_batches": len(root_batches),
                "returned_games": returned,
                "explicit_not_returned_rows": explicit_missing,
            }
        )
    return normalized_paths, records


def configure_database(
    path: Path,
    panel_paths: Sequence[Path],
    seed: Path,
    normalized: Sequence[Path],
    threads: int,
    memory_limit: str,
    temp: Path,
) -> duckdb.DuckDBPyConnection:
    temp.mkdir(parents=True, exist_ok=True)
    database = duckdb.connect(str(path))
    database.execute(f"PRAGMA threads={int(threads)}")
    database.execute(f"PRAGMA memory_limit='{memory_limit}'")
    database.execute(f"PRAGMA temp_directory='{quoted(temp)}'")
    database.execute("PRAGMA preserve_insertion_order=false")
    database.execute(
        f"CREATE VIEW panel AS SELECT * FROM read_parquet({sql_path_list(panel_paths)}, union_by_name=false)"
    )
    seed_sql = (
        f"SELECT game_id::VARCHAR AS game_id, eco::VARCHAR AS eco, "
        f"opening_name::VARCHAR AS opening_name, NULL::BIGINT AS opening_ply, "
        f"TRUE AS returned, 'legacy_seed'::VARCHAR AS metadata_source "
        f"FROM read_parquet('{quoted(seed)}')"
    )
    if normalized:
        fetched_sql = (
            f"SELECT game_id::VARCHAR AS game_id, eco::VARCHAR AS eco, "
            f"opening_name::VARCHAR AS opening_name, opening_ply::BIGINT AS opening_ply, "
            f"returned::BOOLEAN AS returned, 'live_fetch'::VARCHAR AS metadata_source "
            f"FROM read_parquet({sql_path_list(normalized)}, union_by_name=false)"
        )
        database.execute(f"CREATE VIEW metadata AS {seed_sql} UNION ALL {fetched_sql}")
    else:
        database.execute(f"CREATE VIEW metadata AS {seed_sql}")
    return database


def coverage_qa(
    database: duckdb.DuckDBPyConnection, threshold: int, expected_panel_rows: int
) -> dict[str, int]:
    duplicates = database.execute(
        "SELECT COUNT(*) - COUNT(DISTINCT game_id) FROM metadata"
    ).fetchone()[0]
    if int(duplicates) != 0:
        raise RuntimeError(
            f"Opening metadata contains {int(duplicates):,} duplicate game IDs"
        )
    row = (
        database.execute(
            f"""
        WITH target AS (
          SELECT game_id FROM panel WHERE ply_count <= {threshold}
        ), joined AS (
          SELECT t.game_id, m.game_id AS metadata_id, m.returned, m.eco, m.opening_name,
            m.metadata_source
          FROM target t LEFT JOIN metadata m USING(game_id)
        )
        SELECT
          (SELECT COUNT(*) FROM panel)::BIGINT AS selected_panel_rows,
          COUNT(*)::BIGINT AS target_rows,
          COUNT(metadata_id)::BIGINT AS covered_target_rows,
          SUM((metadata_id IS NULL)::INTEGER)::BIGINT AS missing_target_rows,
          SUM((metadata_id IS NOT NULL AND returned)::INTEGER)::BIGINT AS returned_target_rows,
          SUM((metadata_id IS NOT NULL AND NOT returned)::INTEGER)::BIGINT AS explicit_not_returned_rows,
          SUM((eco IS NOT NULL AND trim(eco)!='')::INTEGER)::BIGINT AS usable_eco_rows,
          SUM((opening_name IS NOT NULL AND trim(opening_name)!='')::INTEGER)::BIGINT AS usable_opening_name_rows,
          SUM((metadata_source='legacy_seed')::INTEGER)::BIGINT AS legacy_seed_rows,
          SUM((metadata_source='live_fetch')::INTEGER)::BIGINT AS live_fetch_rows
        FROM joined
        """
        )
        .fetchdf()
        .iloc[0]
    )
    result = {key: int(value) for key, value in row.to_dict().items()}
    if result["selected_panel_rows"] != expected_panel_rows:
        raise RuntimeError("Opening analysis selected-panel row count changed")
    if result["missing_target_rows"] != 0:
        raise RuntimeError(
            f"Opening metadata acquisition is incomplete for selected months: "
            f"missing_target_rows={result['missing_target_rows']:,}"
        )
    return result


def display_bin(values: pd.Series) -> pd.Series:
    x = pd.to_numeric(values, errors="coerce")
    result = pd.Series("missing", index=x.index, dtype="object")
    result[x >= 300] = "disconnected_clearly_better"
    result[(x >= 101) & (x <= 299)] = "disconnected_better"
    result[(x >= -100) & (x <= 100)] = "roughly_equal"
    return result


def load_fair_panel(
    database: duckdb.DuckDBPyConnection, threshold: int, months: Sequence[str]
) -> pd.DataFrame:
    month_case = (
        "CASE "
        + " ".join(
            f"WHEN p.month='{month}' THEN {index}" for index, month in enumerate(months)
        )
        + " ELSE NULL END"
    )
    frame = database.execute(
        f"""
        SELECT p.month::VARCHAR AS month, p.game_id::VARCHAR AS game_id,
          p.archive_ordinal::BIGINT AS archive_ordinal,
          p.chooser_username_norm::VARCHAR AS chooser,
          (100.0 * p.kind_draw::INTEGER)::DOUBLE AS kind_pp,
          p.engine_eval_cp_disconnected::DOUBLE AS eval_cp,
          p.chooser_draw_payoff_v2::DOUBLE AS draw_payoff,
          p.chooser_win_premium_v2::DOUBLE AS win_premium,
          ({month_case})::BIGINT AS month_index,
          NULLIF(trim(m.eco), '')::VARCHAR AS eco,
          NULLIF(trim(m.opening_name), '')::VARCHAR AS opening_name
        FROM panel p INNER JOIN metadata m USING(game_id)
        WHERE p.ply_count <= {threshold} AND p.fair_competitive
          AND (NULLIF(trim(m.eco), '') IS NOT NULL OR NULLIF(trim(m.opening_name), '') IS NOT NULL)
        ORDER BY p.month, p.archive_ordinal, p.game_id
        """
    ).fetchdf()
    if frame.empty:
        raise RuntimeError("Opening analysis has no usable fair rows")
    if frame.game_id.nunique() != len(frame):
        raise RuntimeError("Opening analysis fair-panel game IDs are not unique")
    frame["favorable_draw"] = (frame.draw_payoff >= 0).astype("float64")
    frame["eval_100"] = frame.eval_cp / 100.0
    frame["price_cell"] = np.where(frame.favorable_draw == 1, "favorable", "costly")
    frame["display_bin"] = display_bin(frame.eval_cp)
    return frame


def dense_codes(values: Sequence[Any]) -> tuple[np.ndarray, int]:
    codes, uniques = pd.factorize(pd.Series(values).astype(str), sort=False)
    if np.any(codes < 0):
        raise RuntimeError("Fixed-effect or cluster code contains missing values")
    return codes.astype(np.int64), int(len(uniques))


def absorb_one_way(
    matrix: np.ndarray, codes: np.ndarray, levels: int
) -> tuple[np.ndarray, float]:
    residual = matrix.astype("float64", copy=True)
    counts = np.bincount(codes, minlength=levels).astype("float64")
    if np.any(counts == 0):
        raise RuntimeError("Fixed-effect codes are not dense")
    for column in range(residual.shape[1]):
        sums = np.bincount(codes, weights=residual[:, column], minlength=levels)
        residual[:, column] -= (sums / counts)[codes]
    maxima = []
    for column in range(residual.shape[1]):
        sums = np.bincount(codes, weights=residual[:, column], minlength=levels)
        scale = max(float(np.max(np.abs(residual[:, column]))), 1.0)
        maxima.append(float(np.max(np.abs(sums / counts))) / scale)
    return residual, max(maxima)


def fit_lpm_cluster(
    y: np.ndarray,
    x: np.ndarray,
    names: Sequence[str],
    cluster_values: Sequence[Any],
    fixed_effect_values: Sequence[Any] | None = None,
) -> dict[str, Any]:
    y = np.asarray(y, dtype="float64")
    x = np.asarray(x, dtype="float64")
    valid = np.isfinite(y) & np.all(np.isfinite(x), axis=1)
    cluster_array = np.asarray(cluster_values)
    valid &= pd.notna(cluster_array)
    if fixed_effect_values is not None:
        fe_array = np.asarray(fixed_effect_values)
        valid &= pd.notna(fe_array)
    else:
        fe_array = None
    y, x, cluster_array = y[valid], x[valid], cluster_array[valid]
    if fe_array is not None:
        fe_array = fe_array[valid]
        fe_codes, fe_levels = dense_codes(fe_array)
        transformed, orthogonality = absorb_one_way(
            np.column_stack([y, x]), fe_codes, fe_levels
        )
        y, x = transformed[:, 0], transformed[:, 1:]
        coefficient_names = list(names)
        absorption_method = "one_way_exact"
    else:
        x = np.column_stack([np.ones(len(x)), x])
        coefficient_names = ["intercept", *names]
        orthogonality = 0.0
        absorption_method = "none_intercept_included"
    identifying = np.any(np.abs(x) > 1e-14, axis=1)
    y, x, cluster_array = y[identifying], x[identifying], cluster_array[identifying]
    n, k = x.shape
    if n <= k or n < 100:
        raise RuntimeError(
            f"Opening model has insufficient identifying rows: n={n}, k={k}"
        )
    inverse = np.linalg.pinv(x.T @ x, rcond=1e-12, hermitian=True)
    beta = inverse @ (x.T @ y)
    residual = y - x @ beta
    cluster_codes, clusters = dense_codes(cluster_array)
    if clusters < 2:
        raise RuntimeError("Opening model needs at least two chooser clusters")
    scores = np.zeros((clusters, k), dtype="float64")
    np.add.at(scores, cluster_codes, x * residual[:, None])
    vcov = inverse @ (scores.T @ scores) @ inverse
    vcov *= (clusters / (clusters - 1)) * ((n - 1) / (n - k))
    standard_errors = np.sqrt(np.maximum(np.diag(vcov), 0.0))
    t_statistics = np.divide(
        beta,
        standard_errors,
        out=np.full_like(beta, np.nan),
        where=standard_errors > 0,
    )
    return {
        "n_rows": int(n),
        "n_clusters": int(clusters),
        "coefficients": dict(zip(coefficient_names, beta)),
        "standard_errors": dict(zip(coefficient_names, standard_errors)),
        "tstats": dict(zip(coefficient_names, t_statistics)),
        "absorption_method": absorption_method,
        "absorption_max_scaled_group_mean": orthogonality,
    }


def add_familiarity(frame: pd.DataFrame, identity: str) -> pd.DataFrame:
    result = frame.loc[frame[identity].notna()].copy()
    usable = result[identity].astype(str).str.strip()
    result = result.loc[(usable != "") & (usable.str.lower() != "nan")].copy()
    first = result.groupby(["chooser", identity], observed=True)[
        "month_index"
    ].transform("min")
    result["familiar_prior_months"] = result.month_index > first
    result["familiar_prior_months_int"] = result.familiar_prior_months.astype("float64")
    result["identity_definition"] = identity
    return result


def descriptive_outputs(frame: pd.DataFrame, root: Path) -> dict[str, Any]:
    monthly_parts = []
    total_parts = []
    for identity in ("eco", "opening_name"):
        work = add_familiarity(frame, identity)
        monthly = (
            work.groupby(
                [
                    "identity_definition",
                    "month",
                    "familiar_prior_months",
                    "price_cell",
                    "display_bin",
                ],
                observed=True,
            )
            .agg(
                rows=("kind_pp", "size"),
                kind_draws=("kind_pp", lambda value: float(value.sum() / 100.0)),
                chooser_count=("chooser", "nunique"),
                identity_count=(identity, "nunique"),
            )
            .reset_index()
        )
        monthly["kind_rate_pct"] = 100.0 * monthly.kind_draws / monthly.rows
        monthly_parts.append(monthly)
        total = (
            work.groupby(
                [
                    "identity_definition",
                    "familiar_prior_months",
                    "price_cell",
                    "display_bin",
                ],
                observed=True,
            )
            .agg(
                rows=("kind_pp", "size"),
                kind_draws=("kind_pp", lambda value: float(value.sum() / 100.0)),
                chooser_count=("chooser", "nunique"),
                identity_count=(identity, "nunique"),
            )
            .reset_index()
        )
        total["kind_rate_pct"] = 100.0 * total.kind_draws / total.rows
        total_parts.append(total)
    monthly_output = pd.concat(monthly_parts, ignore_index=True)
    total_output = pd.concat(total_parts, ignore_index=True)
    write_csv(root / "tables/tableO01_opening_familiarity_monthly.csv", monthly_output)
    write_csv(root / "tables/tableO02_opening_familiarity_total.csv", total_output)
    return {
        "monthly_rows": int(len(monthly_output)),
        "total_rows": int(len(total_output)),
    }


def model_outputs(frame: pd.DataFrame, root: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    variables = [
        "familiar_prior_months_int",
        "favorable_draw",
        "win_premium",
        "eval_100",
    ]
    for identity in ("eco", "opening_name"):
        work = add_familiarity(frame, identity)
        for sample, selected in (
            ("all_standard_fair", work),
            (
                "roughly_equal_minus100_to_plus100",
                work.loc[work.eval_cp.between(-100, 100)],
            ),
        ):
            for specification, fixed_effect in (
                ("pooled", None),
                ("chooser_fixed_effects", "chooser"),
                ("month_fixed_effects", "month"),
            ):
                result = fit_lpm_cluster(
                    selected.kind_pp.to_numpy(),
                    selected[variables].to_numpy(),
                    variables,
                    selected.chooser.to_numpy(),
                    selected[fixed_effect].to_numpy() if fixed_effect else None,
                )
                for variable in variables:
                    rows.append(
                        {
                            "identity_definition": identity,
                            "sample": sample,
                            "specification": specification,
                            "fixed_effect": fixed_effect or "none",
                            "variable": variable,
                            "coefficient_pp": result["coefficients"][variable],
                            "standard_error_pp": result["standard_errors"][variable],
                            "t_statistic": result["tstats"][variable],
                            "rows": result["n_rows"],
                            "chooser_clusters": result["n_clusters"],
                            "absorption_method": result["absorption_method"],
                            "absorption_max_scaled_group_mean": result[
                                "absorption_max_scaled_group_mean"
                            ],
                        }
                    )
    output = pd.DataFrame(rows)
    write_csv(root / "tables/tableO03_opening_familiarity_models.csv", output)
    return {
        "model_rows": int(len(output)),
        "maximum_absorption_scaled_group_mean": float(
            output.absorption_max_scaled_group_mean.max()
        ),
    }


def output_manifest(root: Path) -> pd.DataFrame:
    rows = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name in {
            "manifest_sha256.csv",
            "_SUCCESS.json",
            "_SELECTED_SUCCESS.json",
        }:
            continue
        rows.append(
            {
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
                "path": str(path.relative_to(root)),
            }
        )
    return pd.DataFrame(rows)


def software_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "duckdb": duckdb.__version__,
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "pyarrow": pa.__version__,
    }


def run_self_test() -> None:
    chooser = np.repeat(np.arange(80), 16)
    rng = np.random.default_rng(20260821)
    x = rng.normal(size=(len(chooser), 2))
    effects = rng.normal(size=80)[chooser]
    y = (
        1.2 * x[:, 0]
        - 0.4 * x[:, 1]
        + effects
        + rng.normal(scale=0.02, size=len(chooser))
    )
    result = fit_lpm_cluster(y, x, ["x0", "x1"], chooser, chooser)
    if abs(result["coefficients"]["x0"] - 1.2) > 0.01:
        raise RuntimeError("Opening regression self-test failed for x0")
    if abs(result["coefficients"]["x1"] + 0.4) > 0.01:
        raise RuntimeError("Opening regression self-test failed for x1")
    if result["absorption_max_scaled_group_mean"] > 1e-12:
        raise RuntimeError("Opening regression absorption self-test failed")
    print("OPENING_ANALYSIS_SELF_TEST_OK")


def print_plan(
    args: argparse.Namespace,
    months: Sequence[str],
    stage07: dict[str, Any],
    plan: dict[str, Any],
    plan_sha: str,
) -> None:
    print("OPENING_ANALYSIS_PLAN_OK")
    print(f"script_version: {SCRIPT_VERSION}")
    print(f"script_sha256: {sha256_file(Path(__file__).resolve())}")
    print(f"git_head: {run_git('rev-parse', 'HEAD')}")
    print(f"months: {','.join(months)}")
    print(f"selected_panel_rows: {stage07['selected_rows']:,}")
    print(f"opening_plan_success_sha256: {plan_sha}")
    print(f"legacy_rule: {plan['legacy_contract']['rule']}")
    print(f"fetch_roots_supplied: {len(args.fetch_root)}")
    print(f"output_root: {Path(args.output_root).expanduser().resolve()}")
    print(
        "definitions: prior-calendar-month ECO familiarity and named-opening familiarity"
    )
    print("No files were written. Re-run with --execute to estimate selected months.")


def execute(
    args: argparse.Namespace,
    months: Sequence[str],
    stage07: dict[str, Any],
    plan: dict[str, Any],
    plan_sha: str,
    seed: Path,
) -> None:
    started = time.time()
    output_root = Path(args.output_root).expanduser().resolve()
    if output_root.exists():
        raise RuntimeError(
            f"Output root already exists; refusing overwrite: {output_root}"
        )
    output_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_root.with_name(f".{output_root.name}.tmp.{os.getpid()}")
    if temporary.exists():
        raise RuntimeError(f"Transactional temporary root exists: {temporary}")
    (temporary / "tables").mkdir(parents=True)
    (temporary / "receipts").mkdir()
    (temporary / "_work/duckdb_tmp").mkdir(parents=True)
    database: duckdb.DuckDBPyConnection | None = None
    try:
        normalized, fetch_records = authenticate_fetch_roots(args.fetch_root, plan_sha)
        progress(
            f"authenticated opening metadata; legacy seed plus {len(normalized):,} fetched request batches"
        )
        database = configure_database(
            temporary / "_work/opening_analysis.duckdb",
            [Path(row["path"]) for row in stage07["records"]],
            seed,
            normalized,
            args.threads,
            args.memory_limit,
            temporary / "_work/duckdb_tmp",
        )
        threshold = int(plan["legacy_contract"]["ply_count_max"])
        coverage = coverage_qa(database, threshold, stage07["selected_rows"])
        write_csv(
            temporary / "receipts/opening_metadata_coverage.csv",
            pd.DataFrame([coverage]),
        )
        progress(
            f"coverage QA passed; targets={coverage['target_rows']:,}; usable ECO={coverage['usable_eco_rows']:,}"
        )
        fair = load_fair_panel(database, threshold, months)
        progress(f"fair opening-analysis panel loaded; rows={len(fair):,}")
        descriptive = descriptive_outputs(fair, temporary)
        progress("opening familiarity descriptives complete")
        models = model_outputs(fair, temporary)
        progress("opening familiarity models complete")
        database.close()
        database = None
        del fair
        shutil.rmtree(temporary / "_work")
        if models["model_rows"] != 48:
            raise RuntimeError(
                f"Expected 48 opening model rows, found {models['model_rows']}"
            )
        if models["maximum_absorption_scaled_group_mean"] > 1e-10:
            raise RuntimeError("Opening fixed-effect orthogonality QA failed")
        manifest = output_manifest(temporary)
        write_csv(temporary / "manifest_sha256.csv", manifest)
        full = tuple(months) == ALL_MONTHS
        status = (
            "OPENING_FAMILIARITY_24M_CERTIFIED_OK"
            if full
            else "OPENING_FAMILIARITY_SELECTED_MONTHS_OK"
        )
        summary = {
            "status": status,
            "created_at_utc": utc_now(),
            "script_version": SCRIPT_VERSION,
            "script_sha256": sha256_file(Path(__file__).resolve()),
            "git_head": run_git("rev-parse", "HEAD"),
            "stage08_upstream_git_head": EXPECTED_STAGE08_UPSTREAM_GIT_HEAD,
            "months": list(months),
            "full_24_month_run": full,
            "stage07_summary_sha256": stage07["success_sha256"],
            "opening_plan_success_sha256": plan_sha,
            "legacy_contract": plan["legacy_contract"],
            "fetch_roots": fetch_records,
            "coverage_qa": coverage,
            "definitions": {
                "primary": "same chooser had same ECO in at least one earlier sample month among fair target games",
                "secondary": "same chooser had same named opening in at least one earlier sample month among fair target games",
                "first_month_policy": "all appearances in the identity's first sample month are unfamiliar",
                "fairness": "certified Stage 07 standard fair: disconnected-player 100k evaluation >= -100 cp",
                "favorable_draw": "chooser_draw_payoff_v2 >= 0",
                "roughly_equal": "100k evaluation between -100 and +100 cp inclusive",
            },
            "descriptive_outputs": descriptive,
            "models": models,
            "software": software_versions(),
            "manifest_sha256": sha256_file(temporary / "manifest_sha256.csv"),
            "manifest_files": int(len(manifest)),
            "runtime_seconds": round(time.time() - started, 3),
        }
        atomic_write_json(
            temporary / ("_SUCCESS.json" if full else "_SELECTED_SUCCESS.json"), summary
        )
        os.replace(temporary, output_root)
        print(status)
        print(f"output_root: {output_root}")
        print(f"target_rows: {coverage['target_rows']:,}")
        print(f"usable_eco_rows: {coverage['usable_eco_rows']:,}")
        print(f"usable_opening_name_rows: {coverage['usable_opening_name_rows']:,}")
        print(f"model_rows: {models['model_rows']}")
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
                    "status": "OPENING_FAMILIARITY_ANALYSIS_FAILED",
                    "created_at_utc": utc_now(),
                    "error": traceback.format_exc(),
                },
            )
        except Exception:
            pass
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--months", default="all")
    parser.add_argument("--plan-root", default=str(DEFAULT_PLAN_ROOT))
    parser.add_argument("--fetch-root", action="append", default=[])
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--memory-limit", default="12GB")
    parser.add_argument("--expected-git-head", default="")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            run_self_test()
            return
        if not 1 <= args.threads <= 32:
            raise RuntimeError("--threads must be between 1 and 32")
        months = parse_months(args.months)
        state_head = run_git("rev-parse", "HEAD")
        if args.expected_git_head and state_head != args.expected_git_head:
            raise RuntimeError(
                f"Git HEAD changed: expected={args.expected_git_head} actual={state_head}"
            )
        if run_git("branch", "--show-current") != "main":
            raise RuntimeError("Repository is not on main")
        stage07 = authenticate_stage07(months, verify_hashes=args.execute)
        plan_root = Path(args.plan_root).expanduser().resolve()
        plan, plan_sha, _target, seed = authenticate_plan(plan_root)
        if args.execute:
            execute(args, months, stage07, plan, plan_sha, seed)
        else:
            print_plan(args, months, stage07, plan, plan_sha)
    except Exception as exc:
        print(
            f"OPENING_ANALYSIS_FAIL_CLOSED: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        raise


if __name__ == "__main__":
    main()
