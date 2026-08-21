#!/usr/bin/env python3
"""Recover the legacy opening contract and build the 24-month acquisition plan.

The script makes no network requests.  It authenticates the certified Stage 07
panel and the legacy one-year ECO mapping, recovers the legacy early-game rule
by exact game-ID comparison, copies the reusable mapping to XT_Pro, and writes
a deterministic, resumable plan for only the still-missing game IDs.

Dry-run is the default.  ``--execute`` writes transactionally and never
overwrites an existing uncertified directory.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
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
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


SCRIPT_VERSION = "1.1.0"

PROJECT = Path("/Volumes/XT_Pro/lichess_kindness")
REPOSITORY = PROJECT / "replication_package"
PANEL_ROOT = PROJECT / "derived/replication/analysis_panel_24m_sf100k"
DEFAULT_PLAN_ROOT = PROJECT / "derived/replication/opening_familiarity_24m_plan_v100"
DEFAULT_LEGACY_MAPPING = Path(
    "/Users/u6025368/projects/lichess_api_work_laptop_local/"
    "full_year_opening_familiarity_twopass_20260605_210828/"
    "appendixF_selfcontained_full_year_20260606_131943/raw/target_eco_all.parquet"
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
EXPECTED_V100_PLAN_SUCCESS_SHA256 = (
    "2c8bc601d50e23fa55e9f3d09969096cd5212177c31eb6e508dc699ec95a38ca"
)

EXPECTED_LEGACY_MAPPING_ROWS = 2_370_477
EXPECTED_LEGACY_MAPPING_BYTES = 20_333_902
EXPECTED_LEGACY_MAPPING_COLUMNS = ("game_id", "eco", "opening_name")

LEGACY_MONTHS = (
    "2023-11",
    "2023-12",
    "2024-01",
    "2024-02",
    "2024-03",
    "2024-04",
    "2024-05",
    "2024-06",
    "2024-07",
    "2024-08",
    "2024-09",
)
THRESHOLD_CANDIDATES = (6, 8, 10, 12, 16, 18, 20, 22, 24, 30, 40)

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
    atomic_write_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def sql_path_list(paths: Sequence[Path]) -> str:
    return (
        "[" + ",".join("'" + str(path).replace("'", "''") + "'" for path in paths) + "]"
    )


def quoted(path: Path) -> str:
    return str(path).replace("'", "''")


def run_git(*args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(REPOSITORY), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def authenticate_stage07(verify_hashes: bool) -> dict[str, Any]:
    success = PANEL_ROOT / "_SUCCESS.json"
    status_path = PANEL_ROOT / "_manifests/month_status.csv"
    producer = REPOSITORY / "code/07_build_analysis_panel.py"
    for path in (success, status_path, producer):
        if not path.is_file():
            raise RuntimeError(f"Required certified Stage 07 input is missing: {path}")
    success_sha = sha256_file(success)
    producer_sha = sha256_file(producer)
    if success_sha != EXPECTED_STAGE07_SUMMARY_SHA256:
        raise RuntimeError(f"Stage 07 success SHA mismatch: {success_sha}")
    if producer_sha != EXPECTED_STAGE07_SCRIPT_SHA256:
        raise RuntimeError(f"Stage 07 producer SHA mismatch: {producer_sha}")
    summary = json.loads(success.read_text(encoding="utf-8"))
    if summary.get("status") != EXPECTED_STAGE07_STATUS:
        raise RuntimeError(f"Stage 07 status changed: {summary.get('status')}")
    if int(summary.get("global_qa", {}).get("rows", -1)) != EXPECTED_STAGE07_ROWS:
        raise RuntimeError("Stage 07 global row count changed")
    status = pd.read_csv(status_path)
    if status["month"].astype(str).tolist() != list(ALL_MONTHS):
        raise RuntimeError("Stage 07 month ordering changed")
    records: list[dict[str, Any]] = []
    for month, expected_rows in MONTH_ROWS.items():
        item = status.loc[status["month"].astype(str) == month].iloc[0]
        path = PANEL_ROOT / f"month={month}/analysis_panel.parquet"
        if not path.is_file():
            raise RuntimeError(f"Stage 07 month is missing: {path}")
        parquet = pq.ParquetFile(path)
        if (
            parquet.metadata.num_rows != expected_rows
            or int(item["rows"]) != expected_rows
        ):
            raise RuntimeError(f"Stage 07 row count changed for {month}")
        if len(parquet.schema_arrow.names) != EXPECTED_STAGE07_COLUMNS:
            raise RuntimeError(f"Stage 07 schema count changed for {month}")
        required = {"month", "game_id", "archive_ordinal", "ply_count"}
        if not required.issubset(parquet.schema_arrow.names):
            raise RuntimeError(f"Stage 07 opening-plan fields missing for {month}")
        if int(item["output_size_bytes"]) != path.stat().st_size:
            raise RuntimeError(f"Stage 07 size changed for {month}")
        records.append(
            {
                "month": month,
                "path": path,
                "rows": expected_rows,
                "bytes": path.stat().st_size,
                "expected_sha256": str(item["output_sha256"]),
            }
        )
    if verify_hashes:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(sha256_file, row["path"]): row for row in records
            }
            for future in concurrent.futures.as_completed(futures):
                row = futures[future]
                actual = future.result()
                if actual != row["expected_sha256"]:
                    raise RuntimeError(
                        f"Stage 07 Parquet SHA mismatch for {row['month']}"
                    )
                row["actual_sha256"] = actual
    return {
        "success_sha256": success_sha,
        "producer_sha256": producer_sha,
        "records": records,
    }


def authenticate_legacy_mapping(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(
            "Legacy one-year ECO mapping was not found. Expected the work-laptop file at: "
            f"{path}"
        )
    parquet = pq.ParquetFile(path)
    names = tuple(parquet.schema_arrow.names)
    if parquet.metadata.num_rows != EXPECTED_LEGACY_MAPPING_ROWS:
        raise RuntimeError(
            f"Legacy mapping rows changed: {parquet.metadata.num_rows:,} != "
            f"{EXPECTED_LEGACY_MAPPING_ROWS:,}"
        )
    if names != EXPECTED_LEGACY_MAPPING_COLUMNS:
        raise RuntimeError(f"Legacy mapping schema changed: {names}")
    if path.stat().st_size != EXPECTED_LEGACY_MAPPING_BYTES:
        raise RuntimeError(
            f"Legacy mapping size changed: {path.stat().st_size:,} != {EXPECTED_LEGACY_MAPPING_BYTES:,}"
        )
    return {
        "path": str(path),
        "rows": parquet.metadata.num_rows,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "columns": list(names),
    }


def configure_database(
    database_path: Path,
    records: Sequence[dict[str, Any]],
    mapping: Path,
    threads: int,
    memory_limit: str,
    temp: Path,
) -> duckdb.DuckDBPyConnection:
    temp.mkdir(parents=True, exist_ok=True)
    database = duckdb.connect(str(database_path))
    database.execute(f"PRAGMA threads={int(threads)}")
    database.execute(f"PRAGMA memory_limit='{memory_limit}'")
    database.execute(f"PRAGMA temp_directory='{quoted(temp)}'")
    database.execute("PRAGMA preserve_insertion_order=false")
    paths = [Path(row["path"]) for row in records]
    database.execute(
        f"CREATE VIEW panel AS SELECT month, game_id, archive_ordinal, ply_count "
        f"FROM read_parquet({sql_path_list(paths)}, union_by_name=false)"
    )
    database.execute(
        f"CREATE VIEW legacy AS SELECT game_id::VARCHAR AS game_id, eco::VARCHAR AS eco, "
        f"opening_name::VARCHAR AS opening_name FROM read_parquet('{quoted(mapping)}')"
    )
    return database


def recover_contract(
    database: duckdb.DuckDBPyConnection,
) -> tuple[int, pd.DataFrame, dict[str, int]]:
    legacy_qa = (
        database.execute(
            """
        SELECT COUNT(*)::BIGINT AS rows,
          COUNT(DISTINCT game_id)::BIGINT AS unique_game_ids,
          SUM((game_id IS NULL OR trim(game_id)='')::INTEGER)::BIGINT AS missing_ids
        FROM legacy
        """
        )
        .fetchdf()
        .iloc[0]
    )
    if int(legacy_qa.rows) != EXPECTED_LEGACY_MAPPING_ROWS:
        raise RuntimeError("Legacy mapping row count changed after DuckDB read")
    if (
        int(legacy_qa.unique_game_ids) != int(legacy_qa.rows)
        or int(legacy_qa.missing_ids) != 0
    ):
        raise RuntimeError(f"Legacy mapping game-ID QA failed: {legacy_qa.to_dict()}")

    month_sql = ",".join(f"'{month}'" for month in LEGACY_MONTHS)
    in_scope = database.execute(
        f"SELECT COUNT(*)::BIGINT FROM legacy l INNER JOIN panel p USING(game_id) "
        f"WHERE p.month IN ({month_sql})"
    ).fetchone()[0]
    audits: list[dict[str, int]] = []
    exact: list[int] = []
    for threshold in THRESHOLD_CANDIDATES:
        row = (
            database.execute(
                f"""
            WITH target AS (
              SELECT game_id FROM panel
              WHERE month IN ({month_sql}) AND ply_count <= {threshold}
            ), mapped AS (
              SELECT l.game_id FROM legacy l INNER JOIN panel p USING(game_id)
              WHERE p.month IN ({month_sql})
            )
            SELECT
              (SELECT COUNT(*) FROM target)::BIGINT AS target_rows,
              (SELECT COUNT(*) FROM mapped)::BIGINT AS mapped_rows,
              (SELECT COUNT(*) FROM target t LEFT JOIN mapped m USING(game_id)
                 WHERE m.game_id IS NULL)::BIGINT AS target_missing_from_mapping,
              (SELECT COUNT(*) FROM mapped m LEFT JOIN target t USING(game_id)
                 WHERE t.game_id IS NULL)::BIGINT AS mapping_extras_vs_target
            """
            )
            .fetchdf()
            .iloc[0]
        )
        item = {
            "ply_count_max": threshold,
            **{key: int(value) for key, value in row.to_dict().items()},
        }
        audits.append(item)
        if (
            item["target_missing_from_mapping"] == 0
            and item["mapping_extras_vs_target"] == 0
        ):
            exact.append(threshold)
    audit = pd.DataFrame(audits)
    if len(exact) != 1:
        raise RuntimeError(
            "Could not recover a unique exact legacy ply-count contract. "
            f"Exact candidates={exact}; audit={audits}"
        )
    qa = {
        "legacy_rows": int(legacy_qa.rows),
        "legacy_unique_game_ids": int(legacy_qa.unique_game_ids),
        "legacy_rows_intersecting_stage07_overlap": int(in_scope),
    }
    return exact[0], audit, qa


def copy_parquet(database: duckdb.DuckDBPyConnection, query: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    database.execute(
        f"COPY ({query}) TO '{quoted(path)}' "
        "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)"
    )


def build_plan(
    database: duckdb.DuckDBPyConnection,
    root: Path,
    threshold: int,
) -> dict[str, Any]:
    target_path = root / "targets/opening_targets_all.parquet"
    seed_path = root / "seed/legacy_opening_mapping_stage07_overlap.parquet"
    fetch_path = root / "targets/opening_targets_needing_fetch.parquet"

    copy_parquet(
        database,
        f"""
        SELECT l.game_id, l.eco, l.opening_name
        FROM legacy l INNER JOIN panel p USING(game_id)
        WHERE p.ply_count <= {threshold}
        ORDER BY p.month, p.archive_ordinal, p.game_id
        """,
        seed_path,
    )
    database.execute(
        f"CREATE VIEW reusable_seed AS SELECT * FROM read_parquet('{quoted(seed_path)}')"
    )
    copy_parquet(
        database,
        f"""
        WITH ordered AS (
          SELECT p.month, p.archive_ordinal, p.game_id, p.ply_count,
            (s.game_id IS NOT NULL) AS mapped_in_reusable_seed,
            row_number() OVER (ORDER BY p.month, p.archive_ordinal, p.game_id) AS target_ordinal
          FROM panel p LEFT JOIN reusable_seed s USING(game_id)
          WHERE p.ply_count <= {threshold}
        )
        SELECT *,
          floor((target_ordinal - 1) / 120000)::BIGINT + 1 AS catalog_macro_batch
        FROM ordered ORDER BY target_ordinal
        """,
        target_path,
    )
    database.execute(
        f"CREATE VIEW targets AS SELECT * FROM read_parquet('{quoted(target_path)}')"
    )
    copy_parquet(
        database,
        """
        WITH missing AS (
          SELECT month, archive_ordinal, game_id, ply_count, target_ordinal,
            row_number() OVER (ORDER BY target_ordinal) AS fetch_ordinal
          FROM targets WHERE NOT mapped_in_reusable_seed
        )
        SELECT *,
          floor((fetch_ordinal - 1) / 300)::BIGINT + 1 AS request_batch,
          floor((fetch_ordinal - 1) / 120000)::BIGINT + 1 AS fetch_macro_batch
        FROM missing ORDER BY fetch_ordinal
        """,
        fetch_path,
    )
    database.execute(
        f"CREATE VIEW fetch_targets AS SELECT * FROM read_parquet('{quoted(fetch_path)}')"
    )
    manifest = database.execute(
        """
        SELECT fetch_macro_batch, MIN(request_batch)::BIGINT AS first_request_batch,
          MAX(request_batch)::BIGINT AS last_request_batch,
          COUNT(*)::BIGINT AS game_ids,
          MIN(fetch_ordinal)::BIGINT AS first_fetch_ordinal,
          MAX(fetch_ordinal)::BIGINT AS last_fetch_ordinal,
          MIN(month)::VARCHAR AS first_month,
          MAX(month)::VARCHAR AS last_month
        FROM fetch_targets GROUP BY 1 ORDER BY 1
        """
    ).fetchdf()
    manifest.to_csv(
        root / "targets/fetch_macro_batches_120k.csv", index=False, lineterminator="\n"
    )
    request_manifest = database.execute(
        """
        SELECT request_batch, fetch_macro_batch, COUNT(*)::BIGINT AS game_ids,
          MIN(fetch_ordinal)::BIGINT AS first_fetch_ordinal,
          MAX(fetch_ordinal)::BIGINT AS last_fetch_ordinal
        FROM fetch_targets GROUP BY 1,2 ORDER BY 1
        """
    ).fetchdf()
    request_manifest.to_csv(
        root / "targets/fetch_request_batches_300.csv", index=False, lineterminator="\n"
    )

    totals = (
        database.execute(
            """
        SELECT COUNT(*)::BIGINT AS target_rows,
          COUNT(DISTINCT game_id)::BIGINT AS unique_target_ids,
          SUM(mapped_in_reusable_seed::INTEGER)::BIGINT AS reusable_seed_rows,
          SUM((NOT mapped_in_reusable_seed)::INTEGER)::BIGINT AS fetch_rows,
          COUNT(DISTINCT month)::BIGINT AS target_months
        FROM targets
        """
        )
        .fetchdf()
        .iloc[0]
    )
    fetch_rows = int(totals.fetch_rows)
    expected_request_batches = (fetch_rows + 299) // 300
    if int(totals.target_rows) != int(totals.unique_target_ids):
        raise RuntimeError("Opening target game IDs are not unique")
    if len(request_manifest) != expected_request_batches:
        raise RuntimeError("Opening request-batch count is inconsistent")
    if fetch_rows and int(request_manifest.game_ids.max()) > 300:
        raise RuntimeError("Opening request batch exceeds 300 IDs")
    if fetch_rows and int(manifest.game_ids.max()) > 120_000:
        raise RuntimeError("Opening macro-batch exceeds 120,000 IDs")
    return {
        "target_rows": int(totals.target_rows),
        "unique_target_ids": int(totals.unique_target_ids),
        "reusable_seed_rows": int(totals.reusable_seed_rows),
        "fetch_rows": fetch_rows,
        "target_months": int(totals.target_months),
        "request_batches_300": int(len(request_manifest)),
        "macro_batches_120k": int(len(manifest)),
        "target_relative_path": str(target_path.relative_to(root)),
        "seed_relative_path": str(seed_path.relative_to(root)),
        "fetch_relative_path": str(fetch_path.relative_to(root)),
    }


def software_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "duckdb": duckdb.__version__,
        "pandas": pd.__version__,
        "pyarrow": pa.__version__,
        "platform": platform.platform(),
    }


def existing_success(root: Path) -> dict[str, Any] | None:
    path = root / "_SUCCESS.json"
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("status") != "OPENING_FAMILIARITY_PLAN_CERTIFIED_OK":
        raise RuntimeError(f"Existing plan is not certified: {path}")
    return value


def run(args: argparse.Namespace) -> None:
    started = time.time()
    script_path = Path(__file__).resolve()
    plan_root = Path(args.output_root).expanduser().resolve()
    mapping_path = Path(args.legacy_mapping).expanduser().resolve()
    state = {
        "head": run_git("rev-parse", "HEAD"),
        "branch": run_git("branch", "--show-current"),
        "status_porcelain": run_git("status", "--porcelain=v1"),
    }
    if state["branch"] != "main":
        raise RuntimeError(f"Expected Git branch main, found {state['branch']!r}")
    if args.expected_git_head and state["head"] != args.expected_git_head:
        raise RuntimeError(
            f"Git HEAD changed: expected={args.expected_git_head} actual={state['head']}"
        )

    existing = existing_success(plan_root)
    if existing is not None:
        current_script_sha = sha256_file(script_path)
        existing_success_sha = sha256_file(plan_root / "_SUCCESS.json")
        compatible_v100_plan = existing_success_sha == EXPECTED_V100_PLAN_SUCCESS_SHA256
        if (
            existing.get("script_sha256") != current_script_sha
            and not compatible_v100_plan
        ):
            raise RuntimeError(
                "Existing opening plan was created by another producer: "
                f"expected={current_script_sha} actual={existing.get('script_sha256')}"
            )
        if existing.get("stage07_summary_sha256") != EXPECTED_STAGE07_SUMMARY_SHA256:
            raise RuntimeError(
                "Existing opening plan references another Stage 07 receipt"
            )
        hashes_path = plan_root / "plan_file_hashes.tsv"
        if not hashes_path.is_file():
            raise RuntimeError("Existing opening plan lacks plan_file_hashes.tsv")
        if sha256_file(hashes_path) != existing.get("plan_file_hashes_sha256"):
            raise RuntimeError("Existing opening plan hash manifest changed")
        hashes = pd.read_csv(hashes_path, sep="\t")
        for row in hashes.itertuples(index=False):
            path = plan_root / str(row.path)
            if not path.is_file() or path.stat().st_size != int(row.bytes):
                raise RuntimeError(f"Existing opening plan file size changed: {path}")
            if sha256_file(path) != str(row.sha256):
                raise RuntimeError(f"Existing opening plan file SHA changed: {path}")
        print("OPENING_FAMILIARITY_PLAN_ALREADY_CERTIFIED_OK")
        if compatible_v100_plan:
            print("OPENING_FAMILIARITY_V100_PLAN_COMPATIBILITY_OK")
        print(f"plan_root: {plan_root}")
        print(f"plan_success_sha256: {sha256_file(plan_root / '_SUCCESS.json')}")
        print(f"target_rows: {existing['plan_qa']['target_rows']:,}")
        print(f"remaining_fetch_rows: {existing['plan_qa']['fetch_rows']:,}")
        return

    stage07 = authenticate_stage07(verify_hashes=args.execute)
    legacy = authenticate_legacy_mapping(mapping_path)
    print("OPENING_FAMILIARITY_PLAN_OK")
    print(f"script_version: {SCRIPT_VERSION}")
    print(f"script_sha256: {sha256_file(script_path)}")
    print(f"git_head: {state['head']}")
    print(f"legacy_mapping: {mapping_path}")
    print(f"legacy_rows: {legacy['rows']:,}")
    print(f"output_root: {plan_root}")
    print("network_requests: 0")
    if not args.execute:
        print(
            "No files were written. Re-run with --execute to recover the contract and build the plan."
        )
        return

    if plan_root.exists():
        raise RuntimeError(
            f"Output root exists without certified success; refusing overwrite: {plan_root}"
        )
    plan_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = plan_root.with_name(f".{plan_root.name}.tmp.{os.getpid()}")
    if temporary.exists():
        raise RuntimeError(f"Transactional temporary root exists: {temporary}")
    (temporary / "_work/duckdb_tmp").mkdir(parents=True)
    (temporary / "audit").mkdir()
    database: duckdb.DuckDBPyConnection | None = None
    try:
        database = configure_database(
            temporary / "_work/opening_plan.duckdb",
            stage07["records"],
            mapping_path,
            args.threads,
            args.memory_limit,
            temporary / "_work/duckdb_tmp",
        )
        threshold, audit, legacy_qa = recover_contract(database)
        audit.to_csv(
            temporary / "audit/legacy_contract_recovery.csv",
            index=False,
            lineterminator="\n",
        )
        progress(f"legacy contract recovered exactly: ply_count <= {threshold}")
        qa = build_plan(database, temporary, threshold)
        progress(
            f"opening plan built; targets={qa['target_rows']:,}; reusable={qa['reusable_seed_rows']:,}; "
            f"fetch={qa['fetch_rows']:,}"
        )
        database.close()
        database = None
        shutil.rmtree(temporary / "_work")
        file_rows = []
        for path in sorted(item for item in temporary.rglob("*") if item.is_file()):
            file_rows.append(
                {
                    "sha256": sha256_file(path),
                    "bytes": path.stat().st_size,
                    "path": str(path.relative_to(temporary)),
                }
            )
        pd.DataFrame(file_rows).to_csv(
            temporary / "plan_file_hashes.tsv",
            index=False,
            sep="\t",
            lineterminator="\n",
        )
        plan_file_hashes_sha = sha256_file(temporary / "plan_file_hashes.tsv")
        summary = {
            "status": "OPENING_FAMILIARITY_PLAN_CERTIFIED_OK",
            "created_at_utc": utc_now(),
            "script_version": SCRIPT_VERSION,
            "script_sha256": sha256_file(script_path),
            "git_head": state["head"],
            "stage08_upstream_git_head": EXPECTED_STAGE08_UPSTREAM_GIT_HEAD,
            "stage07_summary_sha256": stage07["success_sha256"],
            "stage07_producer_sha256": stage07["producer_sha256"],
            "legacy_mapping": legacy,
            "legacy_contract": {
                "rule": f"ply_count <= {threshold}",
                "ply_count_max": threshold,
                "recovery_method": "unique exact game-ID equality over 2023-11 through 2024-09",
                "audit_path": "audit/legacy_contract_recovery.csv",
                **legacy_qa,
            },
            "plan_qa": qa,
            "plan_file_hashes_sha256": plan_file_hashes_sha,
            "api_contract": {
                "endpoint": "POST https://lichess.org/api/games/export/_ids",
                "request_ids_max": 300,
                "request_body": "comma-separated game IDs",
                "parameters": {
                    "moves": "false",
                    "pgnInJson": "false",
                    "tags": "true",
                    "clocks": "false",
                    "evals": "false",
                    "accuracy": "false",
                    "opening": "true",
                    "division": "false",
                    "literate": "false",
                },
                "concurrency": 1,
                "on_429": "honor Retry-After when supplied; otherwise exponential backoff beginning at 60 seconds",
            },
            "network_requests_made": 0,
            "privacy": "Game IDs and acquired metadata are research data; keep outside GitHub.",
            "software": software_versions(),
            "runtime_seconds": round(time.time() - started, 3),
        }
        atomic_write_json(temporary / "_SUCCESS.json", summary)
        os.replace(temporary, plan_root)
        print("OPENING_FAMILIARITY_PLAN_CERTIFIED_OK")
        print(f"plan_root: {plan_root}")
        print(f"plan_success_sha256: {sha256_file(plan_root / '_SUCCESS.json')}")
        print(f"recovered_rule: ply_count <= {threshold}")
        print(f"target_rows: {qa['target_rows']:,}")
        print(f"reusable_seed_rows: {qa['reusable_seed_rows']:,}")
        print(f"fetch_rows: {qa['fetch_rows']:,}")
        print(f"request_batches_300: {qa['request_batches_300']:,}")
        print(f"macro_batches_120k: {qa['macro_batches_120k']:,}")
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
                    "status": "OPENING_FAMILIARITY_PLAN_FAILED",
                    "created_at_utc": utc_now(),
                    "error": traceback.format_exc(),
                },
            )
        except Exception:
            pass
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-mapping", default=str(DEFAULT_LEGACY_MAPPING))
    parser.add_argument("--output-root", default=str(DEFAULT_PLAN_ROOT))
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--memory-limit", default="12GB")
    parser.add_argument("--expected-git-head", default="")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if not 1 <= args.threads <= 32:
            raise RuntimeError("--threads must be between 1 and 32")
        run(args)
    except Exception as exc:
        print(f"OPENING_PLAN_FAIL_CLOSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
