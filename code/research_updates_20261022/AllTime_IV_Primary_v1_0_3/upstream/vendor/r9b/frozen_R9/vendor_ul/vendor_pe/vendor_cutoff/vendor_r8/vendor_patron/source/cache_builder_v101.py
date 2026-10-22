#!/usr/bin/env python3
"""Authenticate frozen authorities and build the treatment-blind chooser cache."""

from __future__ import annotations

import argparse
import csv
import json
import os
import time
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from patron_stage10_common import (
    EXPECTED,
    SNAPSHOT_REQUIRED_COLUMNS,
    STAGE07_REQUIRED_COLUMNS,
    VERSION,
    atomic_write_json,
    atomic_write_text,
    connect_database,
    parquet_schema,
    runtime_record,
    sha256_file,
    sql_string,
    utc_now,
    verify_software_exact,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--memory-limit", default="12GB")
    parser.add_argument("--fixture", action="store_true")
    parser.add_argument("--force-rebuild", action="store_true")
    return parser.parse_args()


def resolve_inputs(project_root: Path) -> dict[str, Path]:
    stage07_root = project_root / "derived/replication/analysis_panel_24m_sf100k"
    snapshot_root = project_root / "derived/replication/patron_profile_snapshot_24m_v100_FINAL_CERTIFIED"
    plan_root = project_root / "derived/replication/patron_profile_acquisition_24m_plan_v100"
    return {
        "project_root": project_root,
        "stage07_root": stage07_root,
        "stage07_success": stage07_root / "_SUCCESS.json",
        "stage07_glob": stage07_root / "month=*/analysis_panel.parquet",
        "stage07_script": project_root / "replication_package/code/07_build_analysis_panel.py",
        "snapshot_root": snapshot_root,
        "snapshot": snapshot_root / "profile_snapshot_24m_private_lossless.parquet",
        "snapshot_success": snapshot_root / "_SUCCESS.json",
        "snapshot_manifest": snapshot_root / "audit_file_hashes.tsv",
        "plan_root": plan_root,
        "plan_success": plan_root / "_SUCCESS.json",
        "plan_manifest": plan_root / "plan_file_hashes.tsv",
        "matching_pairs": plan_root / "matching_pairs_1to3_private.parquet",
    }


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_tsv_manifest(root: Path, manifest: Path, *, sha_col: str, bytes_col: str, path_col: str) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    with manifest.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    if not rows:
        raise RuntimeError(f"Empty authority manifest: {manifest}")
    for row in rows:
        target = root / row[path_col]
        if not target.is_file():
            raise RuntimeError(f"Authority-manifest file missing: {target}")
        if target.stat().st_size != int(row[bytes_col]):
            raise RuntimeError(f"Authority-manifest byte mismatch: {target}")
        if sha256_file(target) != row[sha_col]:
            raise RuntimeError(f"Authority-manifest SHA mismatch: {target}")
    return {"files": len(rows), "manifest_sha256": sha256_file(manifest)}


def authenticate_inputs(paths: dict[str, Path], fixture: bool) -> dict[str, Any]:
    for label, path in paths.items():
        if label in {"project_root", "stage07_glob"}:
            continue
        if not path.exists():
            raise RuntimeError(f"Required input is missing ({label}): {path}")

    stage07_success_sha = sha256_file(paths["stage07_success"])
    stage07_script_sha = sha256_file(paths["stage07_script"])
    snapshot_sha = sha256_file(paths["snapshot"])
    plan_success_sha = sha256_file(paths["plan_success"])
    stage07 = load_json(paths["stage07_success"])
    snapshot_success = load_json(paths["snapshot_success"])
    plan_success = load_json(paths["plan_success"])

    if not fixture:
        exact_checks = {
            "stage07_success_sha256": (stage07_success_sha, EXPECTED["stage07_success_sha256"]),
            "stage07_producer_sha256": (stage07_script_sha, EXPECTED["stage07_producer_sha256"]),
            "snapshot_sha256": (snapshot_sha, EXPECTED["snapshot_sha256"]),
            "plan_success_sha256": (plan_success_sha, EXPECTED["plan_success_sha256"]),
            "stage07_status": (stage07.get("status"), EXPECTED["stage07_status"]),
            "snapshot_status": (snapshot_success.get("status"), EXPECTED["snapshot_status"]),
        }
        failures = [name for name, (observed, expected) in exact_checks.items() if observed != expected]
        if failures:
            detail = {name: {"observed": exact_checks[name][0], "expected": exact_checks[name][1]} for name in failures}
            raise RuntimeError(f"Frozen-authority authentication failed: {detail}")

        global_qa = stage07.get("global_qa") or {}
        count_checks = {
            "stage07_rows": (global_qa.get("rows"), EXPECTED["stage07_rows"]),
            "stage07_months": (global_qa.get("months"), EXPECTED["stage07_months"]),
            "stage07_kind_draws": (global_qa.get("kind_draws"), EXPECTED["stage07_kind_draws"]),
            "snapshot_rows": ((snapshot_success.get("final_qa") or {}).get("normalized_rows"), EXPECTED["snapshot_rows"]),
            "returned_profiles": ((snapshot_success.get("final_qa") or {}).get("returned_profiles"), EXPECTED["returned_profiles"]),
            "unreturned_profiles": ((snapshot_success.get("final_qa") or {}).get("unreturned_profiles"), EXPECTED["unreturned_profiles"]),
            "patrons": ((snapshot_success.get("final_qa") or {}).get("patrons"), EXPECTED["patrons"]),
            "audit_file_hashes_sha256": (snapshot_success.get("audit_file_hashes_sha256"), EXPECTED["audit_file_hashes_sha256"]),
        }
        count_failures = [name for name, (observed, expected) in count_checks.items() if observed != expected]
        if count_failures:
            detail = {name: {"observed": count_checks[name][0], "expected": count_checks[name][1]} for name in count_failures}
            raise RuntimeError(f"Frozen-authority count check failed: {detail}")

    plan_manifest = verify_tsv_manifest(
        paths["plan_root"],
        paths["plan_manifest"],
        sha_col="sha256",
        bytes_col="bytes",
        path_col="path",
    )
    if plan_success.get("plan_file_hashes_sha256") != plan_manifest["manifest_sha256"]:
        raise RuntimeError("Plan manifest SHA differs from certified plan receipt")

    snapshot_manifest = verify_tsv_manifest(
        paths["snapshot_root"],
        paths["snapshot_manifest"],
        sha_col="sha256",
        bytes_col="bytes",
        path_col="path",
    )
    if snapshot_success.get("audit_file_hashes_sha256") != snapshot_manifest["manifest_sha256"]:
        raise RuntimeError("Snapshot manifest SHA differs from certified audit receipt")

    snapshot_file = pq.ParquetFile(paths["snapshot"])
    snapshot_columns = snapshot_file.schema_arrow.names
    stage07_files = sorted(paths["stage07_root"].glob("month=*/analysis_panel.parquet"))
    if not stage07_files:
        raise RuntimeError("No Stage 07 monthly Parquet files were found")
    stage07_columns = pq.ParquetFile(stage07_files[0]).schema_arrow.names
    snapshot_missing = sorted(SNAPSHOT_REQUIRED_COLUMNS - set(snapshot_columns))
    stage07_missing = sorted(STAGE07_REQUIRED_COLUMNS - set(stage07_columns))
    if snapshot_missing or stage07_missing:
        raise RuntimeError(
            f"Authority schema mismatch: snapshot_missing={snapshot_missing}; stage07_missing={stage07_missing}"
        )

    stage07_metadata_rows = sum(pq.ParquetFile(path).metadata.num_rows for path in stage07_files)
    if not fixture:
        if snapshot_file.metadata.num_rows != EXPECTED["snapshot_rows"]:
            raise RuntimeError("Snapshot Parquet metadata row count differs from authority")
        if len(snapshot_columns) != EXPECTED["snapshot_columns"]:
            raise RuntimeError("Snapshot Parquet column count differs from authority")
        if len(stage07_files) != EXPECTED["stage07_months"] or stage07_metadata_rows != EXPECTED["stage07_rows"]:
            raise RuntimeError("Stage 07 monthly Parquet metadata differs from authority")

    return {
        "fixture": fixture,
        "stage07": {
            "root": str(paths["stage07_root"]),
            "success_path": str(paths["stage07_success"]),
            "success_sha256": stage07_success_sha,
            "producer_path": str(paths["stage07_script"]),
            "producer_sha256": stage07_script_sha,
            "status": stage07.get("status"),
            "months": len(stage07_files),
            "rows_from_parquet_metadata": stage07_metadata_rows,
            "columns": len(stage07_columns),
        },
        "snapshot": {
            "root": str(paths["snapshot_root"]),
            "path": str(paths["snapshot"]),
            "sha256": snapshot_sha,
            "status": snapshot_success.get("status"),
            "rows_from_parquet_metadata": snapshot_file.metadata.num_rows,
            "columns": len(snapshot_columns),
            "manifest": snapshot_manifest,
        },
        "plan": {
            "root": str(paths["plan_root"]),
            "success_path": str(paths["plan_success"]),
            "success_sha256": plan_success_sha,
            "status": plan_success.get("status"),
            "manifest": plan_manifest,
        },
    }


def mapping_qa(database, snapshot: Path, fixture: bool) -> dict[str, Any]:
    result = database.execute(
        f"""
        WITH s AS (
          SELECT * FROM read_parquet({sql_string(snapshot)})
        ), group_qa AS (
          SELECT
            matched_kind_chooser_id,
            COUNT(*)::BIGINT AS group_rows,
            SUM((acquisition_role='kind')::INTEGER)::BIGINT AS kind_rows,
            SUM((acquisition_role='control')::INTEGER)::BIGINT AS control_rows,
            COUNT(DISTINCT match_cell)::BIGINT AS match_cells,
            COUNT(DISTINCT control_slot)::BIGINT AS distinct_slots,
            MIN(control_slot)::BIGINT AS min_slot,
            MAX(control_slot)::BIGINT AS max_slot
          FROM s GROUP BY matched_kind_chooser_id
        )
        SELECT
          COUNT(*)::BIGINT AS rows,
          COUNT(DISTINCT username_norm)::BIGINT AS unique_users,
          SUM((acquisition_role='kind')::INTEGER)::BIGINT AS kind_role_users,
          SUM((acquisition_role='control')::INTEGER)::BIGINT AS control_role_users,
          COUNT(DISTINCT matched_kind_chooser_id)::BIGINT AS matched_groups,
          SUM((acquisition_role='kind' AND control_slot=0)::INTEGER)::BIGINT AS kind_slot_zero,
          SUM((acquisition_role='control' AND control_slot BETWEEN 1 AND 3)::INTEGER)::BIGINT AS control_slots_1_3,
          SUM((acquisition_role='kind' AND username_norm=matched_kind_chooser_id)::INTEGER)::BIGINT AS self_keyed_kind_rows,
          SUM((NOT exact_1to3_group)::INTEGER)::BIGINT AS non_exact_rows,
          SUM((selected_controls<>3)::INTEGER)::BIGINT AS non_three_control_rows,
          SUM((acquisition_role='control' AND ever_kind_any_state)::INTEGER)::BIGINT AS kind_controls,
          SUM((acquisition_role='kind' AND NOT ever_kind_any_state)::INTEGER)::BIGINT AS nonkind_kind_rows,
          (SELECT COUNT(*) FROM group_qa WHERE group_rows<>4 OR kind_rows<>1 OR control_rows<>3
             OR match_cells<>1 OR distinct_slots<>4 OR min_slot<>0 OR max_slot<>3)::BIGINT AS malformed_groups
        FROM s
        """
    ).fetchdf().iloc[0].to_dict()
    integer_result = {key: int(value) for key, value in result.items()}
    fatal_zero = [
        "non_exact_rows",
        "non_three_control_rows",
        "kind_controls",
        "nonkind_kind_rows",
        "malformed_groups",
    ]
    if integer_result["rows"] != integer_result["unique_users"] or any(integer_result[key] != 0 for key in fatal_zero):
        raise RuntimeError(f"Stored matching mapping failed: {integer_result}")
    if integer_result["kind_slot_zero"] != integer_result["kind_role_users"]:
        raise RuntimeError("Kind-role control_slot mapping failed")
    if integer_result["control_slots_1_3"] != integer_result["control_role_users"]:
        raise RuntimeError("Control-role control_slot mapping failed")
    if integer_result["self_keyed_kind_rows"] != integer_result["kind_role_users"]:
        raise RuntimeError("Kind matched-set identifier mapping failed")
    if not fixture:
        expected_checks = {
            "rows": EXPECTED["snapshot_rows"],
            "kind_role_users": EXPECTED["kind_role_users"],
            "control_role_users": EXPECTED["control_role_users"],
            "matched_groups": EXPECTED["kind_role_users"],
        }
        failed = {key: {"observed": integer_result[key], "expected": expected} for key, expected in expected_checks.items() if integer_result[key] != expected}
        if failed:
            raise RuntimeError(f"Stored matching counts differ from certified plan: {failed}")
    return integer_result


def build_cache(database, paths: dict[str, Path], cache_path: Path) -> None:
    temporary = cache_path.with_name(f".{cache_path.name}.tmp.{os.getpid()}")
    temporary.unlink(missing_ok=True)
    snapshot = sql_string(paths["snapshot"])
    stage07 = sql_string(paths["stage07_glob"])

    database.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE acquired_users AS
        SELECT username_norm
        FROM read_parquet({snapshot})
        ORDER BY username_norm
        """
    )
    print("Aggregating certified Stage 07 rows to acquired chooser accounts...", flush=True)
    database.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE panel_features AS
        SELECT
          p.chooser_username_norm::VARCHAR AS username_norm,
          COUNT(*)::BIGINT AS panel_total_opps,
          SUM(p.kind_draw::INTEGER)::BIGINT AS panel_total_kind_count,
          SUM(p.fair_competitive::INTEGER)::BIGINT AS panel_fair_opps,
          SUM((p.fair_competitive AND p.kind_draw)::INTEGER)::BIGINT AS panel_fair_kind_count,
          SUM(p.clearly_worse::INTEGER)::BIGINT AS panel_clearly_worse_opps,
          SUM((p.clearly_worse AND p.kind_draw)::INTEGER)::BIGINT AS panel_clearly_worse_kind_count,
          SUM(p.excluded_middle::INTEGER)::BIGINT AS panel_excluded_middle_opps,
          SUM((p.excluded_middle AND p.kind_draw)::INTEGER)::BIGINT AS panel_excluded_middle_kind_count,
          SUM((p.engine_fairness_bin='disconnected_clearly_better')::INTEGER)::BIGINT AS eval_bin_disconnected_clearly_better_n,
          SUM((p.engine_fairness_bin='disconnected_better')::INTEGER)::BIGINT AS eval_bin_disconnected_better_n,
          SUM((p.engine_fairness_bin='roughly_equal')::INTEGER)::BIGINT AS eval_bin_roughly_equal_n,
          SUM((p.engine_fairness_bin='modestly_worse_excluded')::INTEGER)::BIGINT AS eval_bin_modestly_worse_n,
          SUM((p.engine_fairness_bin='clearly_worse')::INTEGER)::BIGINT AS eval_bin_clearly_worse_n,
          AVG(p.engine_eval_cp_disconnected_capped600::DOUBLE)::DOUBLE AS mean_eval_capped600,
          SUM((p.fair_competitive AND p.draw_nonnegative)::INTEGER)::BIGINT AS fair_nonnegative_opps,
          SUM((p.fair_competitive AND p.draw_nonnegative AND p.kind_draw)::INTEGER)::BIGINT AS fair_nonnegative_kind_count,
          SUM((p.fair_competitive AND p.draw_costly)::INTEGER)::BIGINT AS fair_costly_opps,
          SUM((p.fair_competitive AND p.draw_costly AND p.kind_draw)::INTEGER)::BIGINT AS fair_costly_kind_count,
          AVG(CASE WHEN p.fair_competitive THEN p.chooser_draw_payoff_v2::DOUBLE END)::DOUBLE AS panel_mean_draw_payoff_fair,
          AVG(CASE WHEN p.fair_competitive THEN p.chooser_win_premium_v2::DOUBLE END)::DOUBLE AS panel_mean_win_premium_fair,
          COUNT(DISTINCT p.month)::SMALLINT AS panel_active_months,
          AVG(p.tournament_like_event::INTEGER)::DOUBLE AS panel_share_tournament,
          AVG(p.chooser_elo::DOUBLE)::DOUBLE AS panel_mean_chooser_elo,
          STDDEV_POP(p.chooser_elo::DOUBLE)::DOUBLE AS panel_sd_chooser_elo,
          SUM((lower(regexp_replace(coalesce(p.api_speed,''),'[^a-zA-Z0-9]','','g'))='ultrabullet')::INTEGER)::BIGINT AS speed_ultrabullet_n,
          SUM((lower(regexp_replace(coalesce(p.api_speed,''),'[^a-zA-Z0-9]','','g'))='bullet')::INTEGER)::BIGINT AS speed_bullet_n,
          SUM((lower(regexp_replace(coalesce(p.api_speed,''),'[^a-zA-Z0-9]','','g'))='blitz')::INTEGER)::BIGINT AS speed_blitz_n,
          SUM((lower(regexp_replace(coalesce(p.api_speed,''),'[^a-zA-Z0-9]','','g'))='rapid')::INTEGER)::BIGINT AS speed_rapid_n,
          SUM((lower(regexp_replace(coalesce(p.api_speed,''),'[^a-zA-Z0-9]','','g')) IN ('classical','correspondence'))::INTEGER)::BIGINT AS speed_classical_long_n
        FROM read_parquet({stage07}, union_by_name=true, hive_partitioning=false) p
        SEMI JOIN acquired_users u ON p.chooser_username_norm=u.username_norm
        GROUP BY p.chooser_username_norm
        """
    )

    print("Joining stored matching fields and profile covariates without patron outcomes...", flush=True)
    database.execute(
        f"""
        COPY (
          WITH s0 AS (
            SELECT
              query_index,
              canonical_batch_index,
              username_norm,
              acquisition_role,
              matched_kind_chooser_id,
              control_slot,
              selected_controls,
              nested_1to1_available,
              exact_1to3_group,
              total_opps,
              total_kind_count,
              fair_opps,
              fair_kind_count,
              clearly_worse_opps,
              clearly_worse_kind_count,
              excluded_middle_opps,
              excluded_middle_kind_count,
              mean_chooser_elo,
              sd_chooser_elo,
              chooser_elo_n,
              mean_draw_payoff_fair,
              mean_win_premium_fair,
              share_tournament,
              first_opportunity_utc_ms,
              last_opportunity_utc_ms,
              active_months,
              modal_speed_group,
              modal_speed_opps,
              ever_kind_any_state,
              ever_kind_fair_state,
              ever_kind_clearly_worse_state,
              fair_opp_bin,
              total_opp_bin,
              historical_common_support_2_20,
              match_cell,
              queried_at_utc,
              title,
              disabled,
              tos_violation,
              created_at_ms,
              seen_at_ms,
              play_time_total_seconds,
              count_all,
              count_rated,
              count_win,
              count_loss,
              count_draw,
              perfs_json
            FROM read_parquet({snapshot})
          ), s AS (
            SELECT
              *,
              MAX(CASE WHEN acquisition_role='kind' THEN ever_kind_fair_state::INTEGER ELSE 0 END)
                OVER (PARTITION BY matched_kind_chooser_id)::BOOLEAN AS group_ever_kind_fair,
              MAX(CASE WHEN acquisition_role='kind' THEN ever_kind_clearly_worse_state::INTEGER ELSE 0 END)
                OVER (PARTITION BY matched_kind_chooser_id)::BOOLEAN AS group_ever_kind_clearly_worse
            FROM s0
          )
          SELECT
            s.* EXCLUDE(perfs_json),
            (s.acquisition_role='kind')::INTEGER AS is_kind_role,
            (upper(coalesce(s.title,''))='BOT')::INTEGER AS bot_title,
            greatest(0.0, (epoch_ms(try_cast(s.queried_at_utc AS TIMESTAMPTZ))-s.created_at_ms)/86400000.0)::DOUBLE AS account_age_days_at_query,
            greatest(0.0, (epoch_ms(try_cast(s.queried_at_utc AS TIMESTAMPTZ))-s.seen_at_ms)/86400000.0)::DOUBLE AS days_since_seen_at_query,
            try_cast(json_extract_string(s.perfs_json, '$.bullet.rating') AS DOUBLE) AS current_bullet_rating,
            try_cast(json_extract_string(s.perfs_json, '$.blitz.rating') AS DOUBLE) AS current_blitz_rating,
            try_cast(json_extract_string(s.perfs_json, '$.rapid.rating') AS DOUBLE) AS current_rapid_rating,
            try_cast(json_extract_string(s.perfs_json, '$.classical.rating') AS DOUBLE) AS current_classical_rating,
            try_cast(json_extract_string(s.perfs_json, '$.correspondence.rating') AS DOUBLE) AS current_correspondence_rating,
            try_cast(json_extract_string(s.perfs_json, '$.bullet.games') AS DOUBLE) AS current_bullet_games,
            try_cast(json_extract_string(s.perfs_json, '$.blitz.games') AS DOUBLE) AS current_blitz_games,
            try_cast(json_extract_string(s.perfs_json, '$.rapid.games') AS DOUBLE) AS current_rapid_games,
            try_cast(json_extract_string(s.perfs_json, '$.classical.games') AS DOUBLE) AS current_classical_games,
            p.* EXCLUDE(username_norm),
            p.eval_bin_disconnected_clearly_better_n::DOUBLE / nullif(p.panel_total_opps,0) AS share_eval_disconnected_clearly_better,
            p.eval_bin_disconnected_better_n::DOUBLE / nullif(p.panel_total_opps,0) AS share_eval_disconnected_better,
            p.eval_bin_roughly_equal_n::DOUBLE / nullif(p.panel_total_opps,0) AS share_eval_roughly_equal,
            p.eval_bin_modestly_worse_n::DOUBLE / nullif(p.panel_total_opps,0) AS share_eval_modestly_worse,
            p.eval_bin_clearly_worse_n::DOUBLE / nullif(p.panel_total_opps,0) AS share_eval_clearly_worse,
            p.panel_fair_opps::DOUBLE / nullif(p.panel_total_opps,0) AS share_fair,
            p.panel_clearly_worse_opps::DOUBLE / nullif(p.panel_total_opps,0) AS share_clearly_worse,
            p.fair_nonnegative_opps::DOUBLE / nullif(p.panel_fair_opps,0) AS share_fair_nonnegative,
            p.fair_costly_opps::DOUBLE / nullif(p.panel_fair_opps,0) AS share_fair_costly,
            p.speed_ultrabullet_n::DOUBLE / nullif(p.panel_total_opps,0) AS share_speed_ultrabullet,
            p.speed_bullet_n::DOUBLE / nullif(p.panel_total_opps,0) AS share_speed_bullet,
            p.speed_blitz_n::DOUBLE / nullif(p.panel_total_opps,0) AS share_speed_blitz,
            p.speed_rapid_n::DOUBLE / nullif(p.panel_total_opps,0) AS share_speed_rapid,
            p.speed_classical_long_n::DOUBLE / nullif(p.panel_total_opps,0) AS share_speed_classical_long,
            (p.panel_total_opps-p.speed_ultrabullet_n-p.speed_bullet_n-p.speed_blitz_n-p.speed_rapid_n-p.speed_classical_long_n)::DOUBLE
              / nullif(p.panel_total_opps,0) AS share_speed_other,
            (p.fair_costly_kind_count>0)::INTEGER AS ever_kind_fair_costly,
            (p.fair_nonnegative_kind_count>0)::INTEGER AS ever_kind_fair_nonnegative,
            p.fair_costly_kind_count::DOUBLE/nullif(p.fair_costly_opps,0) AS fair_costly_kind_rate,
            p.fair_nonnegative_kind_count::DOUBLE/nullif(p.fair_nonnegative_opps,0) AS fair_nonnegative_kind_rate,
            CASE
              WHEN s.mean_chooser_elo < 1200 THEN 'lt1200'
              WHEN s.mean_chooser_elo < 1600 THEN '1200_1599'
              WHEN s.mean_chooser_elo < 2000 THEN '1600_1999'
              WHEN s.mean_chooser_elo < 2400 THEN '2000_2399'
              ELSE '2400_plus'
            END AS rating_tier
          FROM s
          LEFT JOIN panel_features p USING (username_norm)
          ORDER BY s.query_index
        ) TO {sql_string(temporary)}
          (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
        """
    )
    temporary.replace(cache_path)


def verify_cache(database, cache_path: Path, fixture: bool) -> dict[str, Any]:
    q = database.execute(
        f"""
        SELECT
          COUNT(*)::BIGINT AS rows,
          COUNT(DISTINCT username_norm)::BIGINT AS unique_users,
          COUNT(DISTINCT matched_kind_chooser_id)::BIGINT AS matched_groups,
          SUM((panel_total_opps IS NULL)::INTEGER)::BIGINT AS missing_panel_features,
          SUM((total_opps<>panel_total_opps)::INTEGER)::BIGINT AS total_opp_mismatch,
          SUM((total_kind_count<>panel_total_kind_count)::INTEGER)::BIGINT AS total_kind_mismatch,
          SUM((fair_opps<>panel_fair_opps)::INTEGER)::BIGINT AS fair_opp_mismatch,
          SUM((fair_kind_count<>panel_fair_kind_count)::INTEGER)::BIGINT AS fair_kind_mismatch,
          SUM((clearly_worse_opps<>panel_clearly_worse_opps)::INTEGER)::BIGINT AS worse_opp_mismatch,
          SUM((clearly_worse_kind_count<>panel_clearly_worse_kind_count)::INTEGER)::BIGINT AS worse_kind_mismatch,
          SUM((excluded_middle_opps<>panel_excluded_middle_opps)::INTEGER)::BIGINT AS middle_opp_mismatch,
          SUM((excluded_middle_kind_count<>panel_excluded_middle_kind_count)::INTEGER)::BIGINT AS middle_kind_mismatch,
          SUM((panel_fair_opps+panel_clearly_worse_opps+panel_excluded_middle_opps<>panel_total_opps)::INTEGER)::BIGINT AS fairness_partition_mismatch,
          SUM((fair_nonnegative_opps+fair_costly_opps<>panel_fair_opps)::INTEGER)::BIGINT AS price_partition_mismatch,
          SUM((eval_bin_disconnected_clearly_better_n+eval_bin_disconnected_better_n+eval_bin_roughly_equal_n+
               eval_bin_modestly_worse_n+eval_bin_clearly_worse_n<>panel_total_opps)::INTEGER)::BIGINT AS five_bin_partition_mismatch
        FROM read_parquet({sql_string(cache_path)})
        """
    ).fetchdf().iloc[0].to_dict()
    result = {key: int(value) for key, value in q.items()}
    fatal = [key for key in result if key not in {"rows", "unique_users", "matched_groups"} and result[key] != 0]
    if result["rows"] != result["unique_users"] or fatal:
        raise RuntimeError(f"Chooser cache QA failed: {result}")
    if not fixture and result["rows"] != EXPECTED["snapshot_rows"]:
        raise RuntimeError("Chooser cache row count differs from certified snapshot")
    return result


def build_support_receipt(database, cache_path: Path) -> dict[str, Any]:
    rows = database.execute(
        f"""
        WITH d AS (SELECT * FROM read_parquet({sql_string(cache_path)})),
        cell_support AS (
          SELECT
            match_cell,
            COUNT(DISTINCT matched_kind_chooser_id) FILTER (WHERE group_ever_kind_fair)::BIGINT AS fair_kind_groups,
            SUM((group_ever_kind_fair AND acquisition_role='control')::INTEGER)::BIGINT AS fair_kind_group_controls,
            COUNT(*)::BIGINT AS acquired_users
          FROM d GROUP BY match_cell
        )
        SELECT
          (SELECT COUNT(*) FROM d)::BIGINT AS acquired_users,
          (SELECT COUNT(DISTINCT matched_kind_chooser_id) FROM d)::BIGINT AS acquired_groups,
          (SELECT COUNT(DISTINCT match_cell) FROM d)::BIGINT AS match_cells,
          (SELECT SUM((acquisition_role='kind' AND ever_kind_fair_state)::INTEGER) FROM d)::BIGINT AS fair_kind_groups,
          (SELECT SUM((acquisition_role='kind' AND ever_kind_clearly_worse_state)::INTEGER) FROM d)::BIGINT AS clearly_worse_kind_groups,
          (SELECT SUM((acquisition_role='kind' AND fair_opps BETWEEN 2 AND 20)::INTEGER) FROM d)::BIGINT AS kind_groups_legacy_2_20,
          (SELECT SUM((acquisition_role='kind' AND fair_opps BETWEEN 2 AND 40)::INTEGER) FROM d)::BIGINT AS kind_groups_duration_2_40,
          (SELECT COUNT(*) FROM cell_support WHERE fair_kind_groups>=20 AND fair_kind_group_controls>=60)::BIGINT AS overlap_cells_min20,
          (SELECT SUM(fair_kind_groups) FROM cell_support WHERE fair_kind_groups>=20 AND fair_kind_group_controls>=60)::BIGINT AS overlap_fair_kind_groups_min20
        """
    ).fetchdf().iloc[0].to_dict()
    support = {key: int(value) for key, value in rows.items()}
    cell_table = database.execute(
        f"""
        WITH d AS (SELECT * FROM read_parquet({sql_string(cache_path)}))
        SELECT
          match_cell,
          COUNT(DISTINCT matched_kind_chooser_id) FILTER (WHERE group_ever_kind_fair)::BIGINT AS fair_kind_groups,
          SUM((group_ever_kind_fair AND acquisition_role='control')::INTEGER)::BIGINT AS fair_kind_group_controls,
          COUNT(*)::BIGINT AS acquired_users,
          (COUNT(DISTINCT matched_kind_chooser_id) FILTER (WHERE group_ever_kind_fair)>=20
             AND SUM((group_ever_kind_fair AND acquisition_role='control')::INTEGER)>=60)::BOOLEAN AS overlap_cell_min20
        FROM d GROUP BY match_cell ORDER BY match_cell
        """
    ).fetchdf()
    return {
        "created_utc": utc_now(),
        "version": VERSION,
        "treatment_blind_rule": "Support defined from stored matching/exposure fields before patron outcome columns are read.",
        "main_exposure": "kind-role chooser with ever_kind_fair_state=true; controls are that chooser's immutable control_slot 1-3 users",
        "primary_ratio": "stored exact 1:3",
        "one_to_one": "stored control_slot=1; slots 2 and 3 are leave-two-out sensitivities",
        "legacy_common_support": "kind group's fair-opportunity bin/value in [2,20]",
        "duration_scaled_common_support": "kind chooser fair_opps in [2,40]",
        "overlap_cell_rule": "at least 20 fair-kind kind groups and 60 associated immutable controls in the match cell",
        "counts": support,
        "cell_support": cell_table.to_dict(orient="records"),
        "patron_fields_read": False,
    }


def main() -> None:
    args = parse_args()
    started = time.time()
    project_root = args.project_root.expanduser().resolve()
    output_root = args.output_root.expanduser().resolve()
    private_cache = output_root / "private_cache"
    public_results = output_root / "public_results"
    receipts = output_root / "run_receipts"
    for path in (private_cache, public_results, receipts):
        path.mkdir(parents=True, exist_ok=True)

    software = verify_software_exact(args.fixture)
    paths = resolve_inputs(project_root)
    print("PATRON_STAGE10_AUTHENTICATING_AUTHORITIES", flush=True)
    authorities = authenticate_inputs(paths, args.fixture)
    database = connect_database(private_cache / "chooser_build.duckdb", args.threads, args.memory_limit)
    try:
        mapping = mapping_qa(database, paths["snapshot"], args.fixture)
        mapping_path = public_results / "exact_mapping_resolution.json"
        authority_path = public_results / "input_authorities.json"
        support_path = public_results / "preoutcome_support_receipt.json"
        cache_path = private_cache / "chooser_design_features_private.parquet"
        cache_receipt_path = receipts / "chooser_cache_success.json"
        stage_success_path = receipts / "00_chooser_design_stage_success.json"

        # A completed stage is immutable. Authenticate every authority and every
        # stage artifact, then return without changing timestamps or hashes.
        if stage_success_path.exists() and not args.force_rebuild:
            required = [
                mapping_path,
                authority_path,
                support_path,
                cache_path,
                cache_receipt_path,
            ]
            missing = [str(path) for path in required if not path.is_file()]
            if missing:
                raise RuntimeError(
                    "Completed chooser-design receipt has missing artifacts: "
                    + ", ".join(missing)
                )
            stage = load_json(stage_success_path)
            cache_receipt = load_json(cache_receipt_path)
            checks = {
                "stage status": (
                    stage.get("status"),
                    "PATRON_STAGE10_CHOOSER_DESIGN_STAGE_OK",
                ),
                "chooser cache": (
                    sha256_file(cache_path),
                    cache_receipt.get("cache_sha256"),
                ),
                "support receipt": (
                    sha256_file(support_path),
                    cache_receipt.get("support_receipt_sha256"),
                ),
                "mapping resolution": (
                    sha256_file(mapping_path),
                    stage.get("mapping_resolution_sha256"),
                ),
                "input authorities": (
                    sha256_file(authority_path),
                    stage.get("input_authorities_sha256"),
                ),
                "chooser cache receipt": (
                    sha256_file(cache_receipt_path),
                    stage.get("chooser_cache_receipt_sha256"),
                ),
            }
            failed = [name for name, (observed, expected) in checks.items() if observed != expected]
            if failed:
                raise RuntimeError(
                    "Completed chooser-design stage failed authentication: "
                    + ", ".join(failed)
                )
            print(
                "PATRON_STAGE10_CHOOSER_DESIGN_STAGE_AUTHENTICATED_AND_SKIPPED",
                flush=True,
            )
            return
        if stage_success_path.exists():
            raise RuntimeError(
                "Refusing to overwrite a completed chooser-design stage. "
                "Use a new output root instead of --force-rebuild."
            )

        mapping_record = {
            "created_utc": utc_now(),
            "version": VERSION,
            "status": "PATRON_STAGE10_EXACT_MAPPING_RESOLVED_OK",
            "username_authority": "username_norm; Stage 07 authority chooser_username_norm",
            "group_authority": "matched_kind_chooser_id",
            "treatment_row": "acquisition_role=kind and control_slot=0",
            "control_order": "control_slot=1,2,3 copied from certified plan; no reconstruction",
            "one_to_one": "control_slot=1",
            "one_to_three": "control_slot in 1..3",
            "main_fair_kind_group": "kind row ever_kind_fair_state=true plus its stored controls",
            "broad_acquisition_role": "ever kind in any certified fairness state; QA/secondary only",
            "missing_outcome": "returned=false is missing patron status and is never coded as non-patron",
            "patron_semantics": "returned patron=true is current patron; returned patron=false is ordinary non-patron even when optional patron field is absent",
            "interpretation": "current cross-sectional/stable-type association; adoption timing and causality are not identified",
            "mapping_qa": mapping,
        }
        atomic_write_json(mapping_path, mapping_record)
        atomic_write_json(authority_path, {**authorities, "runtime": runtime_record()})

        if cache_path.exists() and cache_receipt_path.exists() and not args.force_rebuild:
            prior = load_json(cache_receipt_path)
            if prior.get("cache_sha256") != sha256_file(cache_path):
                raise RuntimeError("Existing chooser cache does not match its receipt")
            if not support_path.is_file():
                raise RuntimeError("Existing chooser cache has no pre-outcome support receipt")
            if prior.get("support_receipt_sha256") != sha256_file(support_path):
                raise RuntimeError("Existing pre-outcome support receipt failed authentication")
            print("PATRON_STAGE10_CHOOSER_CACHE_AUTHENTICATED_AND_SKIPPED", flush=True)
        else:
            if cache_path.exists() or cache_receipt_path.exists():
                raise RuntimeError("Partial chooser cache exists; do not overwrite it without --force-rebuild")
            build_cache(database, paths, cache_path)
            cache_qa = verify_cache(database, cache_path, args.fixture)
            support = build_support_receipt(database, cache_path)
            atomic_write_json(support_path, support)
            cache_receipt = {
                "created_utc": utc_now(),
                "version": VERSION,
                "status": "PATRON_STAGE10_CHOOSER_CACHE_OK",
                "cache_path": str(cache_path),
                "cache_bytes": cache_path.stat().st_size,
                "cache_sha256": sha256_file(cache_path),
                "qa": cache_qa,
                "support_receipt_sha256": sha256_file(support_path),
                "contains_private_identifiers": True,
                "publish": False,
            }
            atomic_write_json(cache_receipt_path, cache_receipt)

        elapsed = time.time() - started
        stage = {
            "created_utc": utc_now(),
            "version": VERSION,
            "status": "PATRON_STAGE10_CHOOSER_DESIGN_STAGE_OK",
            "fixture": args.fixture,
            "runtime_seconds": round(elapsed, 3),
            "software": software,
            "mapping_resolution_sha256": sha256_file(mapping_path),
            "input_authorities_sha256": sha256_file(authority_path),
            "chooser_cache_receipt_sha256": sha256_file(cache_receipt_path),
        }
        atomic_write_json(stage_success_path, stage)
        print("PATRON_STAGE10_CHOOSER_DESIGN_STAGE_OK", flush=True)
        print(f"Runtime seconds: {elapsed:.3f}", flush=True)
    finally:
        database.close()


if __name__ == "__main__":
    main()
