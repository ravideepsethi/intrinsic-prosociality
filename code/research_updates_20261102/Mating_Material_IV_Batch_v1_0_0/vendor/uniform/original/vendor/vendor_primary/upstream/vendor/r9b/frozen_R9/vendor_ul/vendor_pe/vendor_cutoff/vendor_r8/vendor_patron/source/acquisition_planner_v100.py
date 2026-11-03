#!/usr/bin/env python3
"""Prepare the frozen 24-month patron/profile acquisition universe.

This program reads only the certified Stage 07 Parquet panel.  It makes no
network requests.  It constructs a deterministic chooser-level summary,
selects every chooser who was ever kind in any board state, selects up to
three never-kind controls in the historical fair-opportunity-bin x modal-speed
cells, and emits authenticated query batches of at most 300 user IDs.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import pyarrow.parquet as pq


SCRIPT_VERSION = "1.0.0"
DESIGN_SEED = "intrinsic-prosociality-profile-acquisition-v1-20260819"
EXPECTED_STAGE07_SUCCESS_SHA256 = (
    "8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7"
)
EXPECTED_STAGE07_SCRIPT_SHA256 = (
    "0411d4061ea9831c20449208a9782aaf668e160139918d106a2b7d63aaa56e6e"
)
EXPECTED_ROWS = 47_587_020
EXPECTED_KIND_DRAWS = 669_503
EXPECTED_MONTHS = tuple(
    f"{year:04d}-{month:02d}"
    for year, month in (
        [(2023, 11), (2023, 12)]
        + [(2024, month) for month in range(1, 13)]
        + [(2025, month) for month in range(1, 11)]
    )
)
REQUIRED_COLUMNS = {
    "month",
    "game_id",
    "chooser_username_norm",
    "kind_draw",
    "fair_competitive",
    "clearly_worse",
    "excluded_middle",
    "api_speed",
    "chooser_elo",
    "chooser_draw_payoff_v2",
    "chooser_win_premium_v2",
    "tournament_like_event",
    "utc_ms",
}
BATCH_SIZE = 300
PRIMARY_RATIO = 3
TEN_MINUTE_OPERATIONAL_USERS = 7_800
DAILY_OPERATIONAL_USERS = 120_000
REQUESTS_PER_MACRO_BATCH = DAILY_OPERATIONAL_USERS // BATCH_SIZE


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sql_string(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{uuid.uuid4().hex}")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def authenticate_stage07(stage07_root: Path) -> tuple[dict[str, Any], list[Path], str]:
    success_path = stage07_root / "_SUCCESS.json"
    if not success_path.is_file():
        raise RuntimeError(f"Stage 07 success receipt is missing: {success_path}")
    success_sha = sha256_file(success_path)
    if success_sha != EXPECTED_STAGE07_SUCCESS_SHA256:
        raise RuntimeError(
            "Stage 07 success-receipt SHA mismatch: "
            f"expected={EXPECTED_STAGE07_SUCCESS_SHA256} actual={success_sha}"
        )
    receipt = json.loads(success_path.read_text(encoding="utf-8"))
    qa = receipt.get("global_qa") or {}
    receipt_months = receipt.get("months")
    if isinstance(receipt_months, list):
        receipt_months_ok = tuple(receipt_months) == EXPECTED_MONTHS
    elif isinstance(receipt_months, int):
        receipt_months_ok = receipt_months == 24
    else:
        # The exact authenticated v1.3.0 receipt has authoritative start/end
        # fields; some producer variants do not repeat a separate month count.
        receipt_months_ok = True
    checks = {
        "status": receipt.get("status") == "STAGE07_24M_CERTIFIED_OK",
        "script_version": receipt.get("script_version") == "1.3.0",
        "script_sha256": receipt.get("script_sha256") == EXPECTED_STAGE07_SCRIPT_SHA256,
        "rows": qa.get("rows") == EXPECTED_ROWS,
        "unique_game_ids": qa.get("unique_game_ids") == EXPECTED_ROWS,
        "kind_draws": qa.get("kind_draws") == EXPECTED_KIND_DRAWS,
        "month_start": receipt.get("month_start") == EXPECTED_MONTHS[0],
        "month_end": receipt.get("month_end") == EXPECTED_MONTHS[-1],
        "months": receipt_months_ok,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError("Stage 07 certification fields failed: " + ", ".join(failed))

    panel_paths = [
        stage07_root / f"month={month}" / "analysis_panel.parquet"
        for month in EXPECTED_MONTHS
    ]
    missing = [str(path) for path in panel_paths if not path.is_file()]
    if missing:
        raise RuntimeError("Missing Stage 07 monthly panels: " + "; ".join(missing))

    schema0 = pq.read_schema(panel_paths[0])
    missing_columns = sorted(REQUIRED_COLUMNS - set(schema0.names))
    if missing_columns:
        raise RuntimeError("Stage 07 schema lacks required columns: " + ", ".join(missing_columns))
    schema_string = str(schema0)
    schema_sha = sha256_text(schema_string)
    for path in panel_paths[1:]:
        schema = pq.read_schema(path)
        if schema != schema0:
            raise RuntimeError(f"Stage 07 monthly schema differs at {path}")
    return receipt, panel_paths, schema_sha


def configure_database(database: duckdb.DuckDBPyConnection, temp_dir: Path, threads: int, memory: str) -> None:
    temp_dir.mkdir(parents=True, exist_ok=True)
    database.execute(f"SET threads = {int(threads)}")
    database.execute(f"SET memory_limit = {sql_string(memory)}")
    database.execute(f"SET temp_directory = {sql_string(temp_dir)}")
    database.execute("SET preserve_insertion_order = false")


def create_panel_view(database: duckdb.DuckDBPyConnection, panel_paths: list[Path]) -> None:
    paths_sql = ", ".join(sql_string(path) for path in panel_paths)
    database.execute(
        f"""
        CREATE OR REPLACE VIEW stage07 AS
        SELECT *
        FROM read_parquet([{paths_sql}], union_by_name = true)
        """
    )


def source_qa(database: duckdb.DuckDBPyConnection) -> dict[str, int]:
    row = database.execute(
        """
        SELECT
          COUNT(*)::BIGINT AS rows,
          COUNT(DISTINCT game_id)::BIGINT AS unique_game_ids,
          COUNT(DISTINCT month)::BIGINT AS months,
          SUM(CAST(kind_draw AS BIGINT))::BIGINT AS kind_draws,
          COUNT(*) FILTER (
            WHERE chooser_username_norm IS NULL OR trim(chooser_username_norm) = ''
          )::BIGINT AS missing_chooser_rows,
          COUNT(*) FILTER (
            WHERE CAST(fair_competitive AS INTEGER)
                + CAST(clearly_worse AS INTEGER)
                + CAST(excluded_middle AS INTEGER) <> 1
          )::BIGINT AS fairness_partition_failures
        FROM stage07
        """
    ).fetchone()
    names = [item[0] for item in database.description]
    qa = {name: int(value) for name, value in zip(names, row)}
    expected = {
        "rows": EXPECTED_ROWS,
        "unique_game_ids": EXPECTED_ROWS,
        "months": 24,
        "kind_draws": EXPECTED_KIND_DRAWS,
        "missing_chooser_rows": 0,
        "fairness_partition_failures": 0,
    }
    failures = [f"{key}={qa[key]} expected={value}" for key, value in expected.items() if qa[key] != value]
    if failures:
        raise RuntimeError("Stage 07 row-data QA failed: " + ", ".join(failures))
    return qa


def build_chooser_summary(database: duckdb.DuckDBPyConnection) -> None:
    database.execute(
        """
        CREATE OR REPLACE TABLE chooser_summary AS
        WITH normalized AS (
          SELECT
            lower(trim(chooser_username_norm)) AS chooser_id,
            CAST(kind_draw AS INTEGER) AS is_kind,
            CAST(fair_competitive AS INTEGER) AS is_fair,
            CAST(clearly_worse AS INTEGER) AS is_clearly_worse,
            CAST(excluded_middle AS INTEGER) AS is_excluded_middle,
            CASE
              WHEN api_speed IS NULL OR trim(api_speed) = '' THEN 'unknown'
              WHEN lower(api_speed) LIKE '%ultra%' THEN 'ultra'
              WHEN lower(api_speed) LIKE '%bullet%' THEN 'bullet'
              WHEN lower(api_speed) LIKE '%blitz%' THEN 'blitz'
              WHEN lower(api_speed) LIKE '%rapid%' THEN 'rapid'
              WHEN lower(api_speed) LIKE '%classical%'
                OR lower(api_speed) LIKE '%correspondence%'
                OR lower(api_speed) LIKE '%long%' THEN 'classical_or_long'
              ELSE regexp_replace(lower(trim(api_speed)), '[^a-z0-9]+', '_', 'g')
            END AS speed_group,
            chooser_elo,
            chooser_draw_payoff_v2,
            chooser_win_premium_v2,
            CAST(tournament_like_event AS INTEGER) AS is_tournament,
            utc_ms,
            month
          FROM stage07
        ),
        aggregate AS (
          SELECT
            chooser_id,
            COUNT(*)::BIGINT AS total_opps,
            SUM(is_kind)::BIGINT AS total_kind_count,
            SUM(is_fair)::BIGINT AS fair_opps,
            SUM(is_kind * is_fair)::BIGINT AS fair_kind_count,
            SUM(is_clearly_worse)::BIGINT AS clearly_worse_opps,
            SUM(is_kind * is_clearly_worse)::BIGINT AS clearly_worse_kind_count,
            SUM(is_excluded_middle)::BIGINT AS excluded_middle_opps,
            SUM(is_kind * is_excluded_middle)::BIGINT AS excluded_middle_kind_count,
            AVG(chooser_elo)::DOUBLE AS mean_chooser_elo,
            STDDEV_POP(chooser_elo)::DOUBLE AS sd_chooser_elo,
            COUNT(chooser_elo)::BIGINT AS chooser_elo_n,
            AVG(chooser_draw_payoff_v2) FILTER (WHERE is_fair = 1)::DOUBLE AS mean_draw_payoff_fair,
            AVG(chooser_win_premium_v2) FILTER (WHERE is_fair = 1)::DOUBLE AS mean_win_premium_fair,
            AVG(is_tournament)::DOUBLE AS share_tournament,
            MIN(utc_ms)::BIGINT AS first_opportunity_utc_ms,
            MAX(utc_ms)::BIGINT AS last_opportunity_utc_ms,
            COUNT(DISTINCT month)::SMALLINT AS active_months
          FROM normalized
          GROUP BY chooser_id
        ),
        speed_counts AS (
          SELECT chooser_id, speed_group, COUNT(*)::BIGINT AS speed_opps
          FROM normalized
          GROUP BY chooser_id, speed_group
        ),
        modal_speed AS (
          SELECT chooser_id, speed_group AS modal_speed_group, speed_opps AS modal_speed_opps
          FROM (
            SELECT *, ROW_NUMBER() OVER (
              PARTITION BY chooser_id ORDER BY speed_opps DESC, speed_group ASC
            ) AS speed_rank
            FROM speed_counts
          )
          WHERE speed_rank = 1
        )
        SELECT
          a.*,
          m.modal_speed_group,
          m.modal_speed_opps,
          (a.total_kind_count > 0) AS ever_kind_any_state,
          (a.fair_kind_count > 0) AS ever_kind_fair_state,
          (a.clearly_worse_kind_count > 0) AS ever_kind_clearly_worse_state,
          CASE
            WHEN a.fair_opps <= 0 THEN '00'
            WHEN a.fair_opps = 1 THEN '01'
            WHEN a.fair_opps = 2 THEN '02'
            WHEN a.fair_opps = 3 THEN '03'
            WHEN a.fair_opps = 4 THEN '04'
            WHEN a.fair_opps BETWEEN 5 AND 9 THEN '05_09'
            WHEN a.fair_opps BETWEEN 10 AND 20 THEN '10_20'
            WHEN a.fair_opps BETWEEN 21 AND 50 THEN '21_50'
            WHEN a.fair_opps BETWEEN 51 AND 100 THEN '51_100'
            ELSE '101_plus'
          END AS fair_opp_bin,
          CASE
            WHEN a.total_opps = 1 THEN '01'
            WHEN a.total_opps = 2 THEN '02'
            WHEN a.total_opps = 3 THEN '03'
            WHEN a.total_opps = 4 THEN '04'
            WHEN a.total_opps BETWEEN 5 AND 9 THEN '05_09'
            WHEN a.total_opps BETWEEN 10 AND 20 THEN '10_20'
            WHEN a.total_opps BETWEEN 21 AND 50 THEN '21_50'
            WHEN a.total_opps BETWEEN 51 AND 100 THEN '51_100'
            ELSE '101_plus'
          END AS total_opp_bin,
          (a.fair_opps BETWEEN 2 AND 20) AS historical_common_support_2_20,
          CASE
            WHEN a.fair_opps <= 0 THEN '00'
            WHEN a.fair_opps = 1 THEN '01'
            WHEN a.fair_opps = 2 THEN '02'
            WHEN a.fair_opps = 3 THEN '03'
            WHEN a.fair_opps = 4 THEN '04'
            WHEN a.fair_opps BETWEEN 5 AND 9 THEN '05_09'
            WHEN a.fair_opps BETWEEN 10 AND 20 THEN '10_20'
            WHEN a.fair_opps BETWEEN 21 AND 50 THEN '21_50'
            WHEN a.fair_opps BETWEEN 51 AND 100 THEN '51_100'
            ELSE '101_plus'
          END || '__' || m.modal_speed_group AS match_cell
        FROM aggregate a
        JOIN modal_speed m USING (chooser_id)
        """
    )


def build_matching(database: duckdb.DuckDBPyConnection, seed: str = DESIGN_SEED) -> None:
    seed_sql = sql_string(seed)
    database.execute(
        f"""
        CREATE OR REPLACE TABLE kind_ranked AS
        SELECT
          *,
          ROW_NUMBER() OVER (
            PARTITION BY match_cell
            ORDER BY sha256({seed_sql} || '|kind|' || chooser_id), chooser_id
          )::BIGINT AS kind_rank
        FROM chooser_summary
        WHERE ever_kind_any_state
        """
    )
    database.execute(
        f"""
        CREATE OR REPLACE TABLE control_ranked AS
        SELECT
          *,
          ROW_NUMBER() OVER (
            PARTITION BY match_cell
            ORDER BY sha256({seed_sql} || '|control|' || chooser_id), chooser_id
          )::BIGINT AS control_rank
        FROM chooser_summary
        WHERE NOT ever_kind_any_state
        """
    )
    database.execute(
        """
        CREATE OR REPLACE TABLE cell_counts AS
        WITH kinds AS (
          SELECT match_cell, COUNT(*)::BIGINT AS n_kind FROM kind_ranked GROUP BY match_cell
        ), controls AS (
          SELECT match_cell, COUNT(*)::BIGINT AS n_control_reservoir
          FROM control_ranked GROUP BY match_cell
        )
        SELECT
          COALESCE(k.match_cell, c.match_cell) AS match_cell,
          COALESCE(k.n_kind, 0)::BIGINT AS n_kind,
          COALESCE(c.n_control_reservoir, 0)::BIGINT AS n_control_reservoir,
          LEAST(COALESCE(c.n_control_reservoir, 0), 3 * COALESCE(k.n_kind, 0))::BIGINT
            AS n_control_selected,
          (COALESCE(c.n_control_reservoir, 0) >= 3 * COALESCE(k.n_kind, 0)
            AND COALESCE(k.n_kind, 0) > 0) AS exact_1to3_support,
          (COALESCE(c.n_control_reservoir, 0) >= COALESCE(k.n_kind, 0)
            AND COALESCE(k.n_kind, 0) > 0) AS exact_1to1_support
        FROM kinds k FULL OUTER JOIN controls c USING (match_cell)
        """
    )
    database.execute(
        """
        CREATE OR REPLACE TABLE matching_pairs AS
        WITH selected_controls AS (
          SELECT
            c.*,
            counts.n_kind,
            (((c.control_rank - 1) % counts.n_kind) + 1)::BIGINT AS target_kind_rank,
            (floor((c.control_rank - 1) / counts.n_kind) + 1)::SMALLINT AS control_slot
          FROM control_ranked c
          JOIN cell_counts counts USING (match_cell)
          WHERE counts.n_kind > 0
            AND c.control_rank <= 3 * counts.n_kind
        )
        SELECT
          k.chooser_id AS kind_chooser_id,
          c.chooser_id AS control_chooser_id,
          k.match_cell,
          k.kind_rank,
          c.control_rank,
          c.control_slot,
          counts.exact_1to3_support AS cell_exact_1to3_support,
          counts.exact_1to1_support AS cell_exact_1to1_support,
          k.ever_kind_fair_state AS kind_ever_fair_kind,
          k.ever_kind_clearly_worse_state AS kind_ever_clearly_worse_kind
        FROM selected_controls c
        JOIN kind_ranked k
          ON c.match_cell = k.match_cell AND c.target_kind_rank = k.kind_rank
        JOIN cell_counts counts ON counts.match_cell = k.match_cell
        """
    )
    database.execute(
        """
        CREATE OR REPLACE TABLE kind_groups AS
        SELECT
          k.chooser_id AS kind_chooser_id,
          k.match_cell,
          k.kind_rank,
          COUNT(p.control_chooser_id)::SMALLINT AS selected_controls,
          (COUNT(p.control_chooser_id) >= 1) AS nested_1to1_available,
          (COUNT(p.control_chooser_id) = 3) AS exact_1to3_group,
          counts.exact_1to3_support AS cell_exact_1to3_support,
          counts.exact_1to1_support AS cell_exact_1to1_support
        FROM kind_ranked k
        LEFT JOIN matching_pairs p ON k.chooser_id = p.kind_chooser_id
        JOIN cell_counts counts ON counts.match_cell = k.match_cell
        GROUP BY ALL
        """
    )
    database.execute(
        """
        CREATE OR REPLACE TABLE acquisition_users_unsorted AS
        SELECT
          k.chooser_id AS username_norm,
          'kind' AS acquisition_role,
          k.chooser_id AS matched_kind_chooser_id,
          0::SMALLINT AS control_slot,
          g.selected_controls,
          g.nested_1to1_available,
          g.exact_1to3_group,
          k.* EXCLUDE (chooser_id, kind_rank)
        FROM kind_ranked k
        JOIN kind_groups g ON k.chooser_id = g.kind_chooser_id
        UNION ALL
        SELECT
          c.chooser_id AS username_norm,
          'control' AS acquisition_role,
          p.kind_chooser_id AS matched_kind_chooser_id,
          p.control_slot,
          g.selected_controls,
          g.nested_1to1_available,
          g.exact_1to3_group,
          c.* EXCLUDE (chooser_id, control_rank)
        FROM matching_pairs p
        JOIN control_ranked c ON p.control_chooser_id = c.chooser_id
        JOIN kind_groups g ON p.kind_chooser_id = g.kind_chooser_id
        """
    )
    database.execute(
        f"""
        CREATE OR REPLACE TABLE acquisition_users AS
        SELECT
          (ROW_NUMBER() OVER (
            ORDER BY
              sha256({seed_sql} || '|group|' || matched_kind_chooser_id),
              matched_kind_chooser_id,
              CASE acquisition_role WHEN 'kind' THEN 0 ELSE 1 END,
              control_slot,
              username_norm
          ) - 1)::BIGINT AS query_index,
          floor((ROW_NUMBER() OVER (
            ORDER BY
              sha256({seed_sql} || '|group|' || matched_kind_chooser_id),
              matched_kind_chooser_id,
              CASE acquisition_role WHEN 'kind' THEN 0 ELSE 1 END,
              control_slot,
              username_norm
          ) - 1) / {BATCH_SIZE})::BIGINT AS canonical_batch_index,
          *
        FROM acquisition_users_unsorted
        ORDER BY query_index
        """
    )


def write_query_manifests(
    database: duckdb.DuckDBPyConnection,
    output_root: Path,
) -> dict[str, Any]:
    total_users = int(database.execute("SELECT COUNT(*) FROM acquisition_users").fetchone()[0])
    query = database.execute(
        """
        SELECT canonical_batch_index, username_norm, acquisition_role, match_cell
        FROM acquisition_users
        ORDER BY query_index
        """
    )
    fieldnames = [
        "batch_id",
        "batch_index",
        "macro_batch_id",
        "macro_batch_index",
        "request_index_within_macro",
        "macro_batch_planned_users",
        "n_users",
        "n_kind",
        "n_control",
        "n_match_cells",
        "request_body_sha256",
        "single_machine_macro_sequence",
        "work_ascending_macro_sequence",
        "home_descending_macro_sequence",
        "full_redundant_assignment",
        "request_ids_csv",
    ]
    all_path = output_root / "query_batches_all.tsv"
    single_path = output_root / "query_assignment_single.tsv"
    work_path = output_root / "query_assignment_work_ascending.tsv"
    home_path = output_root / "query_assignment_home_descending.tsv"
    macro_summary_path = output_root / "macro_batch_summary.tsv"

    total_micro_batches = math.ceil(total_users / BATCH_SIZE)
    total_macro_batches = math.ceil(total_users / DAILY_OPERATIONAL_USERS)
    records: list[dict[str, Any]] = []
    batch_rows: list[tuple[Any, ...]] = []
    current_index: int | None = None

    def flush(rows: list[tuple[Any, ...]], batch_index: int) -> None:
        if not rows:
            return
        usernames = [str(row[1]) for row in rows]
        body = ",".join(usernames)
        macro_index = 1 + batch_index // REQUESTS_PER_MACRO_BATCH
        request_in_macro = 1 + batch_index % REQUESTS_PER_MACRO_BATCH
        macro_start = (macro_index - 1) * DAILY_OPERATIONAL_USERS
        macro_users = min(DAILY_OPERATIONAL_USERS, total_users - macro_start)
        records.append(
            {
                "batch_id": f"profile_v100_macro_{macro_index:04d}_request_{request_in_macro:04d}",
                "batch_index": batch_index,
                "macro_batch_id": f"macro_batch_{macro_index:04d}",
                "macro_batch_index": macro_index,
                "request_index_within_macro": request_in_macro,
                "macro_batch_planned_users": macro_users,
                "n_users": len(rows),
                "n_kind": sum(str(row[2]) == "kind" for row in rows),
                "n_control": sum(str(row[2]) == "control" for row in rows),
                "n_match_cells": len({str(row[3]) for row in rows}),
                "request_body_sha256": sha256_text(body),
                "single_machine_macro_sequence": macro_index,
                "work_ascending_macro_sequence": macro_index,
                "home_descending_macro_sequence": total_macro_batches - macro_index + 1,
                "full_redundant_assignment": "work-and-home",
                "request_ids_csv": body,
            }
        )

    while True:
        rows = query.fetchmany(50_000)
        if not rows:
            break
        for row in rows:
            batch_index = int(row[0])
            if current_index is None:
                current_index = batch_index
            if batch_index != current_index:
                flush(batch_rows, current_index)
                batch_rows = []
                current_index = batch_index
            batch_rows.append(row)
    if current_index is not None:
        flush(batch_rows, current_index)

    if total_users == 0 or len(records) != total_micro_batches:
        raise RuntimeError("Internal query-batch construction failure")

    def write_records(path: Path, selected: list[dict[str, Any]]) -> None:
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames, delimiter="\t")
            writer.writeheader()
            writer.writerows(selected)

    write_records(all_path, records)
    write_records(single_path, records)
    # Both laptops receive the complete query universe.  Only traversal order
    # differs; authenticated completion ledgers coordinate ownership at run
    # time and allow either laptop to take over every unfinished macro-batch.
    work_records = list(records)
    home_records = list(records)
    work_records.sort(key=lambda row: (int(row["macro_batch_index"]), int(row["request_index_within_macro"])))
    home_records.sort(key=lambda row: (-int(row["macro_batch_index"]), int(row["request_index_within_macro"])))
    write_records(work_path, work_records)
    write_records(home_path, home_records)

    macro_lines = [
        "macro_batch_id\tmacro_batch_index\tusers\tapi_requests\t"
        "work_ascending_sequence\thome_descending_sequence\t"
        "first_batch_id\tlast_batch_id"
    ]
    for macro_index in range(1, total_macro_batches + 1):
        selected = [row for row in records if int(row["macro_batch_index"]) == macro_index]
        macro_lines.append(
            "\t".join(
                [
                    f"macro_batch_{macro_index:04d}",
                    str(macro_index),
                    str(sum(int(row["n_users"]) for row in selected)),
                    str(len(selected)),
                    str(macro_index),
                    str(total_macro_batches - macro_index + 1),
                    str(selected[0]["batch_id"]),
                    str(selected[-1]["batch_id"]),
                ]
            )
        )
    atomic_write_text(macro_summary_path, "\n".join(macro_lines) + "\n")

    return {
        "query_users": total_users,
        "api_request_batches": len(records),
        "numbered_120k_macro_batches": total_macro_batches,
        "single_machine_quota_days": total_macro_batches,
        "work_ascending_full_catalog_macro_batches": total_macro_batches,
        "home_descending_full_catalog_macro_batches": total_macro_batches,
        "two_machine_completion_days_if_independent_quotas_approved": math.ceil(
            total_macro_batches / 2
        ),
        "coordination_rule": (
            "both laptops carry all macro-batches; work traverses ascending, home traverses "
            "descending, and each skips macro-batches authenticated as complete by the peer ledger"
        ),
        "all_manifest": all_path.name,
        "single_assignment": single_path.name,
        "work_ascending_assignment": work_path.name,
        "home_descending_assignment": home_path.name,
        "macro_batch_summary": macro_summary_path.name,
    }


def table_row(database: duckdb.DuckDBPyConnection, query: str) -> dict[str, Any]:
    values = database.execute(query).fetchone()
    names = [item[0] for item in database.description]
    return dict(zip(names, values))


def write_outputs(
    database: duckdb.DuckDBPyConnection,
    output_root: Path,
    authentication: dict[str, Any],
    source_qa_result: dict[str, int],
    script_path: Path,
    repo: Path,
    started: float,
) -> dict[str, Any]:
    for table, filename, order in (
        ("chooser_summary", "chooser_summary_private.parquet", "chooser_id"),
        ("matching_pairs", "matching_pairs_1to3_private.parquet", "kind_chooser_id, control_slot"),
        ("kind_groups", "kind_groups_private.parquet", "kind_chooser_id"),
        ("acquisition_users", "acquisition_users_private.parquet", "query_index"),
    ):
        path = output_root / filename
        database.execute(
            f"COPY (SELECT * FROM {table} ORDER BY {order}) TO {sql_string(path)} "
            "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)"
        )

    cell_path = output_root / "matching_cell_diagnostics.tsv"
    database.execute(
        f"""
        COPY (
          SELECT *,
            CASE WHEN n_kind = 0 THEN NULL
              ELSE n_control_selected::DOUBLE / n_kind END AS selected_controls_per_kind
          FROM cell_counts ORDER BY match_cell
        ) TO {sql_string(cell_path)} (HEADER, DELIMITER '\t')
        """
    )

    batch_summary = write_query_manifests(database, output_root)
    chooser_qa = table_row(
        database,
        """
        SELECT
          COUNT(*)::BIGINT AS unique_choosers,
          SUM(total_opps)::BIGINT AS reconstructed_opportunities,
          SUM(total_kind_count)::BIGINT AS reconstructed_kind_draws,
          SUM(CAST(ever_kind_any_state AS INTEGER))::BIGINT AS ever_kind_any_state_choosers,
          SUM(CAST(ever_kind_fair_state AS INTEGER))::BIGINT AS ever_kind_fair_state_choosers,
          SUM(CAST(ever_kind_clearly_worse_state AS INTEGER))::BIGINT
            AS ever_kind_clearly_worse_state_choosers,
          COUNT(*) FILTER (WHERE NOT ever_kind_any_state)::BIGINT AS never_kind_control_reservoir,
          COUNT(DISTINCT match_cell)::BIGINT AS match_cells
        FROM chooser_summary
        """,
    )
    matching_qa = table_row(
        database,
        """
        SELECT
          (SELECT COUNT(*) FROM kind_ranked)::BIGINT AS kind_users_acquired,
          (SELECT COUNT(*) FROM matching_pairs)::BIGINT AS controls_acquired,
          (SELECT COUNT(*) FROM kind_groups WHERE selected_controls = 3)::BIGINT AS exact_1to3_kind_groups,
          (SELECT COUNT(*) FROM kind_groups WHERE selected_controls >= 1)::BIGINT AS nested_1to1_kind_groups,
          (SELECT COUNT(*) FROM kind_groups WHERE selected_controls = 0)::BIGINT AS kind_groups_without_controls,
          (SELECT COUNT(*) FROM cell_counts WHERE n_kind > 0)::BIGINT AS kind_cells,
          (SELECT COUNT(*) FROM cell_counts WHERE n_kind > 0 AND exact_1to3_support)::BIGINT
            AS exact_1to3_support_cells,
          (SELECT COUNT(*) FROM cell_counts WHERE n_kind > 0 AND NOT exact_1to3_support)::BIGINT
            AS thin_1to3_cells,
          (SELECT COUNT(*) FROM acquisition_users)::BIGINT AS acquisition_users,
          (SELECT COUNT(DISTINCT username_norm) FROM acquisition_users)::BIGINT
            AS unique_acquisition_users
        """,
    )
    if int(chooser_qa["reconstructed_opportunities"]) != EXPECTED_ROWS:
        raise RuntimeError("Chooser aggregation does not reconstruct all Stage 07 rows")
    if int(chooser_qa["reconstructed_kind_draws"]) != EXPECTED_KIND_DRAWS:
        raise RuntimeError("Chooser aggregation does not reconstruct the certified kind-draw total")
    if int(matching_qa["acquisition_users"]) != int(matching_qa["unique_acquisition_users"]):
        raise RuntimeError("Acquisition universe contains duplicate usernames")
    if int(matching_qa["acquisition_users"]) != int(batch_summary["query_users"]):
        raise RuntimeError("Query batches do not cover the acquisition universe exactly")

    git_info = {
        "repo": str(repo),
        "head": run_git(repo, "rev-parse", "HEAD") if (repo / ".git").is_dir() else None,
        "branch": run_git(repo, "branch", "--show-current") if (repo / ".git").is_dir() else None,
        "status_porcelain": run_git(repo, "status", "--porcelain=v1") if (repo / ".git").is_dir() else None,
    }
    summary = {
        "status": "PROFILE_ACQUISITION_PLAN_CERTIFIED_OK",
        "created_utc": utc_now(),
        "runtime_seconds": round(time.time() - started, 2),
        "script_version": SCRIPT_VERSION,
        "script_sha256": sha256_file(script_path),
        "design_seed": DESIGN_SEED,
        "stage07_authentication": authentication,
        "stage07_source_qa": source_qa_result,
        "chooser_qa": chooser_qa,
        "matching_qa": matching_qa,
        "query_plan": batch_summary,
        "matching_contract": {
            "treatment": "every chooser with at least one kind draw in any fairness state",
            "controls": "never-kind choosers, without replacement",
            "primary_ratio": "up to 1:3 within match cell; thin cells retained and flagged",
            "nested_robustness": "control_slot=1 supplies deterministic 1:1 subset",
            "match_cell": "fair-opportunity-count bin x modal API speed",
            "fair_opportunity_bins": ["00", "01", "02", "03", "04", "05_09", "10_20", "21_50", "51_100", "101_plus"],
            "modal_speed_ties": "descending count, then alphabetical normalized speed",
            "profile_information_used_for_selection": False,
        },
        "rate_plan": {
            "endpoint": "POST https://lichess.org/api/users?profile=true&rank=true",
            "batch_size": BATCH_SIZE,
            "published_limit_users_per_10_minutes": 8_000,
            "operational_limit_users_per_10_minutes": TEN_MINUTE_OPERATIONAL_USERS,
            "published_limit_users_per_day": 120_000,
            "operational_limit_users_per_rolling_24_hours": DAILY_OPERATIONAL_USERS,
            "operational_requests_per_120k_macro_batch": REQUESTS_PER_MACRO_BATCH,
            "minimum_seconds_between_request_starts": 23.2,
        },
        "git": git_info,
        "software": {
            "python": sys.version,
            "duckdb": duckdb.__version__,
            "platform": platform.platform(),
        },
    }
    atomic_write_json(output_root / "plan_summary.json", summary)
    return summary


def write_hash_manifest(output_root: Path) -> str:
    excluded = {"plan_file_hashes.tsv", "_SUCCESS.json"}
    files = sorted(path for path in output_root.rglob("*") if path.is_file() and path.name not in excluded)
    rows = ["sha256\tbytes\tpath"]
    for path in files:
        rows.append(
            f"{sha256_file(path)}\t{path.stat().st_size}\t{path.relative_to(output_root)}"
        )
    text = "\n".join(rows) + "\n"
    atomic_write_text(output_root / "plan_file_hashes.tsv", text)
    return sha256_file(output_root / "plan_file_hashes.tsv")


def execute(args: argparse.Namespace, receipt: dict[str, Any], paths: list[Path], schema_sha: str) -> None:
    started = time.time()
    output_root = args.output_root.resolve()
    if output_root.exists():
        raise RuntimeError(f"Refusing to overwrite existing output root: {output_root}")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = output_root.with_name(output_root.name + f".tmp.{uuid.uuid4().hex}")
    temporary_root.mkdir(mode=0o700)
    try:
        database = duckdb.connect(str(temporary_root / "planner.duckdb"))
        try:
            configure_database(database, temporary_root / "duckdb_tmp", args.threads, args.memory_limit)
            create_panel_view(database, paths)
            print("STAGE07_ROW_DATA_QA_BEGIN", flush=True)
            qa = source_qa(database)
            print("STAGE07_ROW_DATA_QA_OK", json.dumps(qa, sort_keys=True), flush=True)
            print("CHOOSER_AGGREGATION_BEGIN", flush=True)
            build_chooser_summary(database)
            print("CHOOSER_AGGREGATION_OK", flush=True)
            print("DETERMINISTIC_MATCHING_BEGIN", flush=True)
            build_matching(database)
            print("DETERMINISTIC_MATCHING_OK", flush=True)
            authentication = {
                "stage07_root": str(args.stage07_root.resolve()),
                "success_receipt_sha256": EXPECTED_STAGE07_SUCCESS_SHA256,
                "producer_sha256": receipt.get("script_sha256"),
                "git_head_recorded_by_stage07": receipt.get("git_head"),
                "panel_schema_sha256": schema_sha,
                "monthly_panel_paths": [str(path) for path in paths],
            }
            summary = write_outputs(
                database,
                temporary_root,
                authentication,
                qa,
                Path(__file__).resolve(),
                args.repo.resolve(),
                started,
            )
        finally:
            database.close()
        for unwanted in (temporary_root / "planner.duckdb", temporary_root / "duckdb_tmp"):
            if unwanted.is_file():
                unwanted.unlink()
            elif unwanted.is_dir():
                shutil.rmtree(unwanted)
        manifest_sha = write_hash_manifest(temporary_root)
        success = dict(summary)
        success["plan_file_hashes_sha256"] = manifest_sha
        atomic_write_json(temporary_root / "_SUCCESS.json", success)
        os.replace(temporary_root, output_root)
        print("PROFILE_ACQUISITION_PLAN_CERTIFIED_OK", flush=True)
        print(json.dumps(success, indent=2, sort_keys=True), flush=True)
    except Exception:
        print(f"FAILED TEMPORARY OUTPUT PRESERVED: {temporary_root}", file=sys.stderr, flush=True)
        raise


def self_test() -> None:
    database = duckdb.connect(":memory:")
    database.execute(
        """
        CREATE TABLE chooser_summary (
          chooser_id VARCHAR, match_cell VARCHAR,
          ever_kind_any_state BOOLEAN, ever_kind_fair_state BOOLEAN,
          ever_kind_clearly_worse_state BOOLEAN,
          total_opps BIGINT, total_kind_count BIGINT, fair_opps BIGINT,
          fair_kind_count BIGINT, clearly_worse_opps BIGINT,
          clearly_worse_kind_count BIGINT, excluded_middle_opps BIGINT,
          excluded_middle_kind_count BIGINT, mean_chooser_elo DOUBLE,
          sd_chooser_elo DOUBLE, chooser_elo_n BIGINT,
          mean_draw_payoff_fair DOUBLE, mean_win_premium_fair DOUBLE,
          share_tournament DOUBLE, first_opportunity_utc_ms BIGINT,
          last_opportunity_utc_ms BIGINT, active_months SMALLINT,
          modal_speed_group VARCHAR, modal_speed_opps BIGINT,
          fair_opp_bin VARCHAR, total_opp_bin VARCHAR,
          historical_common_support_2_20 BOOLEAN
        )
        """
    )
    rows = []
    # Cell A has exact 1:3 support for two kinds; cell B is deliberately thin.
    for name in ("kind_a1", "kind_a2"):
        rows.append((name, "01__blitz", True, True, False))
    for number in range(1, 8):
        rows.append((f"control_a{number}", "01__blitz", False, False, False))
    rows.append(("kind_b1", "00__rapid", True, False, True))
    rows.append(("control_b1", "00__rapid", False, False, False))
    expanded = [
        row + (1, int(row[2]), 1, int(row[3]), 0, 0, 0, 0, 1500.0, 0.0, 1, 0.0, 0.0, 0.0,
               1, 1, 1, "blitz" if "blitz" in row[1] else "rapid", 1, "01", "01", False)
        for row in rows
    ]
    placeholders = ",".join(["?"] * len(expanded[0]))
    database.executemany(f"INSERT INTO chooser_summary VALUES ({placeholders})", expanded)
    build_matching(database, seed="self-test")
    result = table_row(
        database,
        """
        SELECT
          (SELECT COUNT(*) FROM kind_ranked) AS kinds,
          (SELECT COUNT(*) FROM matching_pairs) AS controls,
          (SELECT COUNT(*) FROM kind_groups WHERE selected_controls = 3) AS exact_groups,
          (SELECT COUNT(*) FROM kind_groups WHERE selected_controls = 1) AS one_control_groups,
          (SELECT COUNT(*) FROM acquisition_users) AS users,
          (SELECT COUNT(DISTINCT username_norm) FROM acquisition_users) AS unique_users
        """,
    )
    expected = {"kinds": 3, "controls": 7, "exact_groups": 2, "one_control_groups": 1, "users": 10, "unique_users": 10}
    if result != expected:
        raise RuntimeError(f"Planner self-test failed: observed={result} expected={expected}")
    database.close()
    print("PROFILE_ACQUISITION_PLANNER_SELF_TEST_OK")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--stage07-root", type=Path)
    result.add_argument("--repo", type=Path)
    result.add_argument("--output-root", type=Path)
    result.add_argument("--threads", type=int, default=8)
    result.add_argument("--memory-limit", default="12GB")
    result.add_argument("--execute", action="store_true")
    result.add_argument("--self-test", action="store_true")
    return result


def main() -> None:
    os.umask(0o077)
    args = parser().parse_args()
    if args.self_test:
        self_test()
        return
    for name in ("stage07_root", "repo", "output_root"):
        if getattr(args, name) is None:
            raise SystemExit(f"--{name.replace('_', '-')} is required")
    receipt, paths, schema_sha = authenticate_stage07(args.stage07_root.resolve())
    selected_bytes = sum(path.stat().st_size for path in paths)
    print("PROFILE_ACQUISITION_PLAN_OK")
    print(f"script_version: {SCRIPT_VERSION}")
    print(f"script_sha256: {sha256_file(Path(__file__).resolve())}")
    print(f"stage07_success_sha256: {EXPECTED_STAGE07_SUCCESS_SHA256}")
    print(f"stage07_rows: {EXPECTED_ROWS:,}")
    print(f"months: {EXPECTED_MONTHS[0]} through {EXPECTED_MONTHS[-1]}")
    print(f"monthly_panels: {len(paths)}")
    print(f"selected_input_bytes: {selected_bytes:,}")
    print(f"output_root: {args.output_root.resolve()}")
    print("api_calls_planned_now: 0")
    if not args.execute:
        print("No files were written. Re-run with --execute to build the acquisition plan.")
        return
    execute(args, receipt, paths, schema_sha)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"PROFILE_ACQUISITION_PLANNER_FAIL_CLOSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
