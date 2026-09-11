#!/usr/bin/env python3
"""Build the outcome-blind A3 all-game chronology feasibility gate.

The program links the frozen, non-tournament first-fair-recipient cohort to the
canonical all-history rated-standard event substrate.  It deliberately omits mercy
receipt and every chooser outcome from the private cohort, and reports only pooled
30-day activity.  The scan is resumable at the chronology-file level.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Iterable, Sequence


SCRIPT_VERSION = "1.0.0"
PROJECT_AUTHORITY = Path("/Volumes/XT_Pro/lichess_kindness")

EXPECTED_STAGE07_STATUS = "STAGE07_24M_CERTIFIED_OK"
EXPECTED_STAGE07_ROWS = 47_587_020
EXPECTED_STAGE07_SUCCESS_SHA256 = (
    "8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7"
)
EXPECTED_STAGE07_SCRIPT_SHA256 = (
    "0411d4061ea9831c20449208a9782aaf668e160139918d106a2b7d63aaa56e6e"
)
EXPECTED_PLAN_SHA256 = (
    "b11b546ea6fde608140619cffadffad1a7aab054b6fd1a9dcbee8900c98d0a6f"
)
EXPECTED_V101_RUN_ID = "20260821T201202Z"
EXPECTED_V101_STATUS = "DYNAMIC_PROSOCIALITY_STAGE07_FEASIBILITY_AUDIT_V101_OK"
EXPECTED_V101_SCRIPT_SHA256 = (
    "c7c1da3ce422d3dfeb69c568fe0ca74d6cb1b466da3bace9771e8a6d01004790"
)
EXPECTED_V101_TRANSFER_SHA256 = (
    "4566206c494812bf47aeb618526895f68bf8c416355c5d861002b6be9851111b"
)
EXPECTED_PRIMARY_COHORT_ROWS = 2_556_782
EXPECTED_GIT_HEAD = "7fa2cf415b43c69f4d8d5fc973442d81dbb6ecbf"

EXPECTED_REENTRY_STATUS = "REENTRY_SOURCE_CONTRACT_FINAL_AUDIT_OK"
EXPECTED_REENTRY_SCRIPT_SHA256 = (
    "48806ab26ce53eca826cdcd5c441a816efec8f4d45b5e38d4662fbd3f4b1a61b"
)
EXPECTED_CHRONOLOGY_FILES = 852
EXPECTED_CHRONOLOGY_ROWS = 7_763_847_245
MINIMUM_CHRONOLOGY_MAX_MS = int(
    dt.datetime(2026, 4, 30, 23, 59, 58, tzinfo=dt.timezone.utc).timestamp() * 1000
)

MAIN_MONTHS = tuple(
    f"{absolute // 12:04d}-{absolute % 12 + 1:02d}"
    for absolute in range(2023 * 12 + 10, 2023 * 12 + 10 + 24)
)
DAY_MS = 24 * 60 * 60 * 1000
HORIZON_7D_MS = 7 * DAY_MS
HORIZON_30D_MS = 30 * DAY_MS
POOLED_CEILING_THRESHOLD = 0.92

EVENT_COLUMNS = ("utc_ms", "white_id", "black_id")
PROHIBITED_PRIVATE_COLUMNS = {
    "received_mercy",
    "kind_draw",
    "outcome_kind_draw",
    "timeout_draw",
    "timeout_chooser_win",
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_AUTHORITY)
    parser.add_argument("--analysis-plan", type=Path)
    parser.add_argument("--stage07-root", type=Path)
    parser.add_argument("--chronology-root", type=Path)
    parser.add_argument("--reentry-audit-root", type=Path)
    parser.add_argument("--prior-feasibility-root", type=Path)
    parser.add_argument("--state-root", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--memory-limit", default="12GB")
    parser.add_argument("--batch-rows", type=int, default=500_000)
    parser.add_argument("--verify-stage07-hashes", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--integration-self-test", action="store_true")
    return parser.parse_args(argv)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def default_run_id() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(chunk_size):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{uuid.uuid4().hex}")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def write_csv(
    path: Path,
    rows: Iterable[dict[str, Any]],
    fields: Sequence[str],
    *,
    delimiter: str = ",",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{uuid.uuid4().hex}")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=list(fields),
            extrasaction="raise",
            delimiter=delimiter,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def sql_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def path_list_literal(paths: Sequence[Path]) -> str:
    return "[" + ",".join(sql_literal(path) for path in paths) + "]"


def safe_int(value: Any) -> int:
    return 0 if value is None else int(value)


def select_a3_primary(pooled_rate_30d: float) -> str:
    return (
        "any_rated_standard_game_within_30d"
        if pooled_rate_30d <= POOLED_CEILING_THRESHOLD
        else "log1p_rated_standard_games_within_30d"
    )


def command_output(args: Sequence[str], *, cwd: Path | None = None) -> str:
    return subprocess.check_output(list(args), cwd=cwd, text=True).strip()


def import_dependencies() -> tuple[Any, Any, Any, Any]:
    try:
        import duckdb  # type: ignore
        import numpy as np  # type: ignore
        import pyarrow as pa  # type: ignore
        import pyarrow.parquet as pq  # type: ignore
    except ImportError as exc:  # pragma: no cover - production environment check
        raise SystemExit(
            "duckdb, numpy, and pyarrow are required; run with the XT_Pro project venv"
        ) from exc
    return duckdb, np, pa, pq


def directory_manifest(
    root: Path, *, excluded: set[str] | None = None
) -> list[dict[str, Any]]:
    excluded = excluded or set()
    rows: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name in excluded:
            continue
        rows.append(
            {
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
                "path": str(path.relative_to(root)),
            }
        )
    return rows


def authenticate_manifest(root: Path, manifest: Path) -> int:
    if not manifest.is_file():
        raise RuntimeError(f"Hash manifest is missing: {manifest}")
    with manifest.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    if not rows:
        raise RuntimeError(f"Hash manifest is empty: {manifest}")
    for row in rows:
        path = root / str(row["path"])
        if not path.is_file():
            raise RuntimeError(f"Manifest file is missing: {path}")
        if path.stat().st_size != int(row["bytes"]):
            raise RuntimeError(f"Manifest byte-size mismatch: {path}")
        if sha256_file(path) != row["sha256"]:
            raise RuntimeError(f"Manifest SHA-256 mismatch: {path}")
    return len(rows)


def schema_names(summary: dict[str, Any]) -> set[str]:
    output = set()
    for field in summary.get("output_schema", []):
        if isinstance(field, str):
            output.add(field)
        elif isinstance(field, dict) and field.get("name"):
            output.add(str(field["name"]))
    return output


def authenticate_stage07(root: Path, *, verify_hashes: bool) -> dict[str, Any]:
    success = root / "_SUCCESS.json"
    status_path = root / "_manifests/month_status.csv"
    path_list = root / "_manifests/analysis_panel_paths.txt"
    for path in (success, status_path, path_list):
        if not path.is_file():
            raise RuntimeError(f"Stage 07 authority is missing: {path}")
    if sha256_file(success) != EXPECTED_STAGE07_SUCCESS_SHA256:
        raise RuntimeError("Stage 07 success SHA-256 mismatch")
    summary = load_json(success)
    if summary.get("status") != EXPECTED_STAGE07_STATUS:
        raise RuntimeError("Stage 07 certification status mismatch")
    if summary.get("script_sha256") != EXPECTED_STAGE07_SCRIPT_SHA256:
        raise RuntimeError("Stage 07 producer SHA-256 mismatch")
    qa = summary.get("global_qa") or {}
    if safe_int(qa.get("rows")) != EXPECTED_STAGE07_ROWS:
        raise RuntimeError("Stage 07 row total mismatch")
    required = {
        "game_id",
        "archive_ordinal",
        "utc_ms",
        "api_last_move_at_ms",
        "disconnected_user_id",
        "disconnected_username_norm",
        "fair_competitive",
        "tournament_like_event",
    }
    missing = sorted(required - schema_names(summary))
    if missing:
        raise RuntimeError(f"Stage 07 is missing A3 gate fields: {missing}")
    paths = [root / f"month={month}/analysis_panel.parquet" for month in MAIN_MONTHS]
    listed = [
        Path(line.strip())
        for line in path_list.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if [str(path) for path in listed] != [str(path) for path in paths]:
        raise RuntimeError("Stage 07 ordered path list mismatch")
    with status_path.open(encoding="utf-8", newline="") as stream:
        monthly = list(csv.DictReader(stream))
    if [row["month"] for row in monthly] != list(MAIN_MONTHS):
        raise RuntimeError("Stage 07 month-status ordering mismatch")
    expected_hashes: dict[str, str] = {}
    for month, path, row in zip(MAIN_MONTHS, paths, monthly, strict=True):
        if not path.is_file():
            raise RuntimeError(f"Stage 07 Parquet is missing: {path}")
        if path.stat().st_size != int(row["output_size_bytes"]):
            raise RuntimeError(f"Stage 07 Parquet size mismatch: {month}")
        expected_hashes[month] = row["output_sha256"]
    if verify_hashes:
        print("STAGE07_PARQUET_HASH_VERIFICATION_BEGIN", flush=True)
        for month, path in zip(MAIN_MONTHS, paths, strict=True):
            if sha256_file(path) != expected_hashes[month]:
                raise RuntimeError(f"Stage 07 Parquet SHA-256 mismatch: {month}")
            print(f"STAGE07_PARQUET_HASH_OK month={month}", flush=True)
        print("STAGE07_PARQUET_HASH_VERIFICATION_OK", flush=True)
    return {
        "root": str(root),
        "success_sha256": EXPECTED_STAGE07_SUCCESS_SHA256,
        "paths": paths,
        "selected_input_bytes": sum(path.stat().st_size for path in paths),
        "input_hashes_verified": verify_hashes,
    }


def authenticate_v101_feasibility(root: Path) -> dict[str, Any]:
    success = root / "_SUCCESS.json"
    if not success.is_file():
        raise RuntimeError(f"v1.0.1 feasibility receipt is missing: {success}")
    summary = load_json(success)
    expected = {
        "status": EXPECTED_V101_STATUS,
        "script_version": "1.0.1",
        "script_sha256": EXPECTED_V101_SCRIPT_SHA256,
        "analysis_plan_sha256": EXPECTED_PLAN_SHA256,
        "stage07_success_sha256": EXPECTED_STAGE07_SUCCESS_SHA256,
        "effect_estimates_produced": False,
        "account_level_outputs_retained": False,
        "a3_all_game_chronology_linkage_run": False,
    }
    failures = {
        key: {"expected": value, "actual": summary.get(key)}
        for key, value in expected.items()
        if summary.get(key) != value
    }
    if failures:
        raise RuntimeError(
            "v1.0.1 feasibility receipt mismatch: "
            + json.dumps(failures, sort_keys=True)
        )
    count = authenticate_manifest(root, root / "report_file_hashes.tsv")
    overlap = summary.get("a1_exposure_overlap_summary", {}).get(
        "non_tournament_like", {}
    )
    if not overlap.get("primary_90pct_mercy_retention_gate_pass"):
        raise RuntimeError("The v1.0.1 A1 common-support gate did not pass")
    return {
        "root": str(root),
        "success_sha256": sha256_file(success),
        "status": summary["status"],
        "report_files_authenticated": count,
        "transfer_zip_sha256_recorded": EXPECTED_V101_TRANSFER_SHA256,
    }


def find_reentry_audit(project: Path, explicit: Path | None) -> Path:
    if explicit:
        candidates = [explicit.expanduser().resolve()]
    else:
        candidates = sorted(
            (project / "output/reentry_source_contract_audits").glob(
                "*source_contract_final_v121"
            ),
            reverse=True,
        )
    for path in candidates:
        if path.is_dir():
            return path
    raise RuntimeError("Authenticated final v1.2.1 reentry audit was not found")


def authenticate_reentry_audit(root: Path) -> dict[str, Any]:
    summary_path = root / "final_audit_summary.json"
    manifest_path = root / "report_file_hashes.tsv"
    if not summary_path.is_file():
        raise RuntimeError(f"Final reentry audit summary is missing: {summary_path}")
    authenticated_files = authenticate_manifest(root, manifest_path)
    summary = load_json(summary_path)
    if summary.get("status") != EXPECTED_REENTRY_STATUS:
        raise RuntimeError("Final reentry audit success status mismatch")
    if summary.get("producer_ready") is not True:
        raise RuntimeError("Final reentry audit did not clear the producer gate")
    if summary.get("version") != "1.2.1":
        raise RuntimeError("Final reentry audit version mismatch")
    if summary.get("script_sha256") != EXPECTED_REENTRY_SCRIPT_SHA256:
        raise RuntimeError("Final reentry audit producer SHA-256 mismatch")
    blockers = (summary.get("decision") or {}).get("blockers")
    if blockers != []:
        raise RuntimeError(f"Final reentry audit has blockers: {blockers}")
    v110 = summary.get("v110_canonical_chronology_authentication") or {}
    chronology = v110.get("chronology") or {}
    if safe_int(chronology.get("rows_inspected")) != EXPECTED_CHRONOLOGY_ROWS:
        raise RuntimeError("Final reentry audit chronology row total mismatch")
    if safe_int(chronology.get("parquet_files")) != EXPECTED_CHRONOLOGY_FILES:
        raise RuntimeError("Final reentry audit chronology file count mismatch")
    clock = summary.get("clock_contract") or {}
    if (
        clock.get("contract_recovered") is not True
        or clock.get("clock_field") != "disc_clock_s"
        or clock.get("exact_operator") != ">="
        or float(clock.get("exact_threshold_seconds", math.nan)) != 347.0
    ):
        raise RuntimeError(f"Final reentry audit clock contract mismatch: {clock}")
    manifest = directory_manifest(root)
    digest = sha256_text(
        "".join(f"{row['sha256']}\t{row['bytes']}\t{row['path']}\n" for row in manifest)
    )
    return {
        "root": str(root),
        "status": EXPECTED_REENTRY_STATUS,
        "files": len(manifest),
        "authenticated_report_files": authenticated_files,
        "summary_sha256": sha256_file(summary_path),
        "historical_clock_rule": "disc_clock_s >= 347.0",
        "directory_manifest_sha256": digest,
    }


def row_group_stat(
    metadata: Any, row_group: int, field: str
) -> tuple[int | None, int | None]:
    schema_names = list(metadata.schema.names)
    if field not in schema_names:
        return None, None
    index = schema_names.index(field)
    column = metadata.row_group(row_group).column(index)
    statistics = column.statistics
    if statistics is None or not statistics.has_min_max:
        return None, None
    try:
        return int(statistics.min), int(statistics.max)
    except (TypeError, ValueError):
        return None, None


def arm_blind_anchor_bounds(paths: Sequence[Path]) -> dict[str, Any]:
    duckdb, _, _, _ = import_dependencies()
    connection = duckdb.connect()
    row = connection.execute(
        f"""
        SELECT
          COUNT(*)::BIGINT AS qualifying_rows,
          MIN(CAST(api_last_move_at_ms AS BIGINT))::BIGINT AS minimum_anchor_utc_ms,
          MAX(CAST(api_last_move_at_ms AS BIGINT))::BIGINT AS maximum_anchor_utc_ms,
          COUNT(*) FILTER (
            WHERE api_last_move_at_ms IS NULL OR api_last_move_at_ms <= 0
          )::BIGINT AS invalid_anchor_rows
        FROM read_parquet({path_list_literal(paths)}, union_by_name = true)
        WHERE CAST(fair_competitive AS BOOLEAN)
          AND NOT CAST(tournament_like_event AS BOOLEAN)
          AND disconnected_username_norm IS NOT NULL
          AND trim(disconnected_username_norm) <> ''
        """
    ).fetchone()
    connection.close()
    qualifying, minimum, maximum, invalid = row
    if safe_int(qualifying) < EXPECTED_PRIMARY_COHORT_ROWS:
        raise RuntimeError(f"Implausibly small qualifying exposure set: {row}")
    if minimum is None or maximum is None or safe_int(invalid):
        raise RuntimeError(f"Arm-blind exposure-anchor QA failed: {row}")
    return {
        "qualifying_exposure_rows": int(qualifying),
        "minimum_anchor_utc_ms": int(minimum),
        "maximum_anchor_utc_ms": int(maximum),
        "chronology_scan_lower_exclusive_ms": int(minimum),
        "chronology_scan_upper_inclusive_ms": int(maximum) + HORIZON_30D_MS,
        "treatment_or_choice_outcome_read": False,
    }


def inspect_chronology(
    root: Path, *, scan_lower_ms: int, scan_upper_ms: int
) -> dict[str, Any]:
    _, _, _, pq = import_dependencies()
    paths = sorted(root.rglob("*.parquet"), key=str)
    if len(paths) != EXPECTED_CHRONOLOGY_FILES:
        raise RuntimeError(
            f"Chronology file count mismatch: expected={EXPECTED_CHRONOLOGY_FILES} "
            f"actual={len(paths)}"
        )
    rows = 0
    global_min: int | None = None
    global_max: int | None = None
    file_rows: list[dict[str, Any]] = []
    for index, path in enumerate(paths):
        parquet = pq.ParquetFile(path)
        metadata = parquet.metadata
        names = set(parquet.schema_arrow.names)
        missing = sorted(set(EVENT_COLUMNS) - names)
        if missing:
            raise RuntimeError(f"Chronology schema is missing {missing}: {path}")
        selected_groups: list[int] = []
        file_min: int | None = None
        file_max: int | None = None
        groups_without_stats = 0
        for group in range(metadata.num_row_groups):
            minimum, maximum = row_group_stat(metadata, group, "utc_ms")
            if minimum is None or maximum is None:
                groups_without_stats += 1
                selected_groups.append(group)
            else:
                file_min = minimum if file_min is None else min(file_min, minimum)
                file_max = maximum if file_max is None else max(file_max, maximum)
                global_min = minimum if global_min is None else min(global_min, minimum)
                global_max = maximum if global_max is None else max(global_max, maximum)
                if maximum > scan_lower_ms and minimum <= scan_upper_ms:
                    selected_groups.append(group)
        rows += metadata.num_rows
        signature = {
            "path": str(path),
            "bytes": path.stat().st_size,
            "rows": metadata.num_rows,
            "row_groups": metadata.num_row_groups,
            "selected_row_groups": selected_groups,
            "utc_ms_min": file_min,
            "utc_ms_max": file_max,
            "row_groups_without_utc_stats": groups_without_stats,
            "schema": parquet.schema_arrow.to_string(),
        }
        signature["footer_signature_sha256"] = sha256_text(canonical_json(signature))
        file_rows.append(signature)
        if (index + 1) % 100 == 0 or index + 1 == len(paths):
            print(
                f"CHRONOLOGY_FOOTER_PROGRESS {index + 1}/{len(paths)}",
                flush=True,
            )
    if rows != EXPECTED_CHRONOLOGY_ROWS:
        raise RuntimeError(
            f"Chronology row total mismatch: expected={EXPECTED_CHRONOLOGY_ROWS} "
            f"actual={rows}"
        )
    if global_max is None or global_max < MINIMUM_CHRONOLOGY_MAX_MS:
        raise RuntimeError(
            "Chronology does not reach the authenticated post-sample buffer"
        )
    if global_max < scan_upper_ms:
        raise RuntimeError(
            "Chronology does not cover 30 days after the latest qualifying anchor"
        )
    selected = [row for row in file_rows if row["selected_row_groups"]]
    plan_digest = sha256_text(canonical_json(file_rows))
    return {
        "root": str(root),
        "files": len(file_rows),
        "rows": rows,
        "utc_ms_min": global_min,
        "utc_ms_max": global_max,
        "selected_files": len(selected),
        "selected_row_groups": sum(len(row["selected_row_groups"]) for row in selected),
        "scan_lower_exclusive_ms": scan_lower_ms,
        "scan_upper_inclusive_ms": scan_upper_ms,
        "footer_plan_sha256": plan_digest,
        "file_rows": file_rows,
    }


def git_state(repo: Path) -> dict[str, Any]:
    if not (repo / ".git").exists():
        raise RuntimeError(f"Replication repository is missing: {repo}")
    return {
        "head": command_output(["git", "rev-parse", "HEAD"], cwd=repo),
        "branch": command_output(["git", "branch", "--show-current"], cwd=repo),
        "clean": not bool(
            command_output(["git", "status", "--porcelain=v1"], cwd=repo)
        ),
    }


def make_plan(args: argparse.Namespace, script_path: Path) -> dict[str, Any]:
    project = args.project_root.expanduser().resolve()
    if project != PROJECT_AUTHORITY or not project.is_dir():
        raise RuntimeError(f"XT_Pro project authority is unavailable: {project}")
    analysis_plan = (
        args.analysis_plan.expanduser().resolve()
        if args.analysis_plan
        else script_path.with_name(
            "Dynamic_Prosociality_Analysis_Plan_v1_0_1_2026-08-21.md"
        )
    )
    if sha256_file(analysis_plan) != EXPECTED_PLAN_SHA256:
        raise RuntimeError("Frozen v1.0.1 analysis-plan SHA-256 mismatch")
    stage07_root = (
        args.stage07_root.expanduser().resolve()
        if args.stage07_root
        else project / "derived/replication/analysis_panel_24m_sf100k"
    )
    chronology_root = (
        args.chronology_root.expanduser().resolve()
        if args.chronology_root
        else project
        / "derived/glicko2_replay/rating_events_replay_sorted_v2_time"
        / "events_replay_sorted_time"
    )
    prior_root = (
        args.prior_feasibility_root.expanduser().resolve()
        if args.prior_feasibility_root
        else project
        / "output/dynamic_prosociality_feasibility_v101"
        / EXPECTED_V101_RUN_ID
    )
    state_root = (
        args.state_root.expanduser().resolve()
        if args.state_root
        else project
        / "derived/replication/dynamic_prosociality_a3_chronology_gate_v100_PRIVATE"
    )
    output_root = (
        args.output_root.expanduser().resolve()
        if args.output_root
        else project / "output/dynamic_prosociality_a3_chronology_gate_v100"
    )
    stage07 = authenticate_stage07(
        stage07_root, verify_hashes=args.verify_stage07_hashes
    )
    prior = authenticate_v101_feasibility(prior_root)
    reentry = authenticate_reentry_audit(
        find_reentry_audit(project, args.reentry_audit_root)
    )
    anchor_bounds = arm_blind_anchor_bounds(stage07["paths"])
    chronology = inspect_chronology(
        chronology_root,
        scan_lower_ms=anchor_bounds["chronology_scan_lower_exclusive_ms"],
        scan_upper_ms=anchor_bounds["chronology_scan_upper_inclusive_ms"],
    )
    git = git_state(project / "replication_package")
    if not git["clean"]:
        raise RuntimeError("Replication repository is not clean")
    if git["head"] != EXPECTED_GIT_HEAD:
        raise RuntimeError(
            f"Replication Git HEAD mismatch: expected={EXPECTED_GIT_HEAD} "
            f"actual={git['head']}"
        )
    if shutil.disk_usage(project).free < 50 * 1024**3:
        raise RuntimeError("Less than 50 GiB is free on XT_Pro")
    payload = {
        "status": "A3_CHRONOLOGY_GATE_PLAN_OK",
        "created_utc": utc_now(),
        "script_version": SCRIPT_VERSION,
        "script_path": str(script_path),
        "script_sha256": sha256_file(script_path),
        "analysis_plan_path": str(analysis_plan),
        "analysis_plan_sha256": EXPECTED_PLAN_SHA256,
        "project_root": str(project),
        "stage07": stage07,
        "prior_feasibility": prior,
        "reentry_audit": reentry,
        "chronology": chronology,
        "arm_blind_anchor_bounds": anchor_bounds,
        "git": git,
        "state_root": str(state_root),
        "output_root": str(output_root),
        "batch_rows": args.batch_rows,
        "threads": args.threads,
        "memory_limit": args.memory_limit,
        "pooled_ceiling_threshold": POOLED_CEILING_THRESHOLD,
        "treatment_or_choice_outcome_read": False,
    }
    config_source = {
        "script_sha256": payload["script_sha256"],
        "analysis_plan_sha256": payload["analysis_plan_sha256"],
        "stage07_success_sha256": stage07["success_sha256"],
        "prior_feasibility_success_sha256": prior["success_sha256"],
        "reentry_directory_manifest_sha256": reentry["directory_manifest_sha256"],
        "chronology_footer_plan_sha256": chronology["footer_plan_sha256"],
        "scan_lower_ms": chronology["scan_lower_exclusive_ms"],
        "scan_upper_ms": chronology["scan_upper_inclusive_ms"],
        "horizon_30d_ms": HORIZON_30D_MS,
        "cohort": "first fair recipient exposure; non-tournament-like; no treatment field",
    }
    payload["resume_config"] = config_source
    payload["resume_config_sha256"] = sha256_text(canonical_json(config_source))
    return payload


def print_plan(payload: dict[str, Any]) -> None:
    chronology = payload["chronology"]
    anchors = payload["arm_blind_anchor_bounds"]
    print(payload["status"])
    print(f"script_version: {payload['script_version']}")
    print(f"script_sha256: {payload['script_sha256']}")
    print(f"analysis_plan_sha256: {payload['analysis_plan_sha256']}")
    print(f"git_head: {payload['git']['head']}")
    print(f"chronology_files: {chronology['files']:,}")
    print(f"chronology_rows: {chronology['rows']:,}")
    print(f"selected_chronology_files: {chronology['selected_files']:,}")
    print(f"selected_row_groups: {chronology['selected_row_groups']:,}")
    print(f"qualifying_exposure_rows: {anchors['qualifying_exposure_rows']:,}")
    print(f"minimum_anchor_utc_ms: {anchors['minimum_anchor_utc_ms']}")
    print(f"maximum_anchor_utc_ms: {anchors['maximum_anchor_utc_ms']}")
    print(
        f"chronology_scan_upper_inclusive_ms: {chronology['scan_upper_inclusive_ms']}"
    )
    print(f"chronology_footer_plan_sha256: {chronology['footer_plan_sha256']}")
    print(f"state_root: {payload['state_root']}")
    print(f"output_root: {payload['output_root']}")
    print(f"pooled_30d_ceiling_threshold: {payload['pooled_ceiling_threshold']}")
    print("treatment_or_choice_outcome_read: False")
    print("resumability: atomic checkpoint after each selected chronology file")


def configure_duckdb(connection: Any, payload: dict[str, Any], temp: Path) -> None:
    temp.mkdir(parents=True, exist_ok=True)
    connection.execute(f"SET threads = {int(payload['threads'])}")
    connection.execute(f"SET memory_limit = {sql_literal(payload['memory_limit'])}")
    connection.execute(f"SET temp_directory = {sql_literal(temp)}")
    connection.execute("SET preserve_insertion_order = false")


def cohort_sql(paths: Sequence[Path]) -> str:
    return f"""
        WITH panel AS (
          SELECT
            game_id,
            CAST(archive_ordinal AS BIGINT) AS archive_ordinal,
            CAST(utc_ms AS BIGINT) AS utc_ms,
            CAST(api_last_move_at_ms AS BIGINT) AS api_last_move_at_ms,
            CAST(disconnected_user_id AS BIGINT) AS disconnected_user_id,
            disconnected_username_norm,
            CAST(fair_competitive AS BOOLEAN) AS fair_competitive,
            CAST(tournament_like_event AS BOOLEAN) AS tournament_like_event
          FROM read_parquet({path_list_literal(paths)}, union_by_name = true)
        ), ranked AS (
          SELECT
            disconnected_user_id,
            disconnected_username_norm,
            game_id AS exposure_game_id,
            api_last_move_at_ms AS exposure_anchor_utc_ms,
            utc_ms AS exposure_game_utc_ms,
            archive_ordinal AS exposure_archive_ordinal,
            ROW_NUMBER() OVER (
              PARTITION BY disconnected_username_norm
              ORDER BY utc_ms, archive_ordinal, game_id
            ) AS exposure_rank
          FROM panel
          WHERE fair_competitive
            AND NOT tournament_like_event
            AND disconnected_username_norm IS NOT NULL
            AND trim(disconnected_username_norm) <> ''
        ), firsts AS (
          SELECT * EXCLUDE (exposure_rank)
          FROM ranked
          WHERE exposure_rank = 1
        )
        SELECT
          ROW_NUMBER() OVER (ORDER BY disconnected_username_norm)::BIGINT - 1
            AS cohort_row_id,
          disconnected_user_id,
          exposure_game_id,
          exposure_anchor_utc_ms,
          exposure_game_utc_ms,
          exposure_archive_ordinal
        FROM firsts
        ORDER BY disconnected_username_norm
    """


def build_or_authenticate_cohort(payload: dict[str, Any], state: Path) -> Path:
    duckdb, _, _, pq = import_dependencies()
    cohort = state / "cohort_private_no_treatment.parquet"
    receipt = state / "cohort_receipt.json"
    if cohort.is_file() and receipt.is_file():
        saved = load_json(receipt)
        if saved.get("sha256") != sha256_file(cohort):
            raise RuntimeError("Private cohort checkpoint SHA-256 mismatch")
        if safe_int(saved.get("rows")) != EXPECTED_PRIMARY_COHORT_ROWS:
            raise RuntimeError("Private cohort checkpoint row-count mismatch")
        names = set(pq.ParquetFile(cohort).schema_arrow.names)
        if names & PROHIBITED_PRIVATE_COLUMNS:
            raise RuntimeError(
                "Treatment/outcome field found in private cohort checkpoint"
            )
        print("A3_PRIVATE_COHORT_CHECKPOINT_AUTHENTICATED_OK", flush=True)
        return cohort
    if cohort.exists() or receipt.exists():
        raise RuntimeError(
            "Incomplete private cohort checkpoint exists; inspect manually"
        )
    temporary = cohort.with_name(cohort.name + f".tmp.{uuid.uuid4().hex}")
    connection = duckdb.connect()
    temp = state / "duckdb_temp/cohort"
    configure_duckdb(connection, payload, temp)
    query = cohort_sql(payload["stage07"]["paths"])
    connection.execute(
        f"COPY ({query}) TO {sql_literal(temporary)} "
        "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)"
    )
    qa = connection.execute(
        f"""
        SELECT
          COUNT(*)::BIGINT,
          COUNT(DISTINCT disconnected_user_id)::BIGINT,
          COUNT(DISTINCT exposure_game_id)::BIGINT,
          MIN(cohort_row_id)::BIGINT,
          MAX(cohort_row_id)::BIGINT,
          MIN(exposure_anchor_utc_ms)::BIGINT,
          MAX(exposure_anchor_utc_ms)::BIGINT,
          COUNT(*) FILTER (
            WHERE exposure_anchor_utc_ms IS NULL OR exposure_anchor_utc_ms <= 0
          )::BIGINT AS invalid_anchors,
          COUNT(*) FILTER (WHERE disconnected_user_id IS NULL)::BIGINT
            AS missing_numeric_user_ids
        FROM read_parquet({sql_literal(temporary)})
        """
    ).fetchone()
    connection.close()
    shutil.rmtree(temp.parent, ignore_errors=True)
    (
        rows,
        users,
        games,
        minimum_id,
        maximum_id,
        minimum_anchor,
        maximum_anchor,
        invalid,
        missing_user_ids,
    ) = qa
    if (rows, users, games) != (
        EXPECTED_PRIMARY_COHORT_ROWS,
        EXPECTED_PRIMARY_COHORT_ROWS,
        EXPECTED_PRIMARY_COHORT_ROWS,
    ):
        raise RuntimeError(f"Private cohort authority mismatch: {qa}")
    if minimum_id != 0 or maximum_id != rows - 1 or invalid or missing_user_ids:
        raise RuntimeError(f"Private cohort row-id/anchor QA failed: {qa}")
    os.replace(temporary, cohort)
    result = {
        "status": "A3_PRIVATE_COHORT_NO_TREATMENT_OK",
        "created_utc": utc_now(),
        "path": str(cohort),
        "sha256": sha256_file(cohort),
        "bytes": cohort.stat().st_size,
        "rows": rows,
        "unique_users": users,
        "unique_exposure_games": games,
        "minimum_anchor_utc_ms": minimum_anchor,
        "maximum_anchor_utc_ms": maximum_anchor,
        "prohibited_treatment_or_choice_fields": sorted(PROHIBITED_PRIVATE_COLUMNS),
        "treatment_or_choice_outcome_read": False,
    }
    atomic_write_json(receipt, result)
    print(f"A3_PRIVATE_COHORT_BUILD_OK rows={rows:,}", flush=True)
    return cohort


def arrow_int64(array: Any, np: Any, pa: Any) -> Any:
    import pyarrow.compute as pc  # type: ignore

    converted = pc.cast(array, pa.int64(), safe=True)
    if converted.null_count:
        converted = pc.fill_null(converted, pa.scalar(-1, type=pa.int64()))
    return np.asarray(converted.to_numpy(zero_copy_only=False), dtype=np.int64)


def update_endpoint(
    *,
    event_ids: Any,
    event_times: Any,
    lookup: Any,
    anchors: Any,
    counts_7d: Any,
    counts_30d: Any,
    first_next: Any,
    np: Any,
) -> tuple[int, int]:
    in_bounds = (event_ids >= 0) & (event_ids < lookup.size)
    if not np.any(in_bounds):
        return 0, 0
    ids = event_ids[in_bounds]
    times = event_times[in_bounds]
    cohort_index = lookup[ids]
    target = cohort_index >= 0
    if not np.any(target):
        return 0, 0
    cohort_index = cohort_index[target]
    times = times[target]
    delta = times - anchors[cohort_index]
    within_30d = (delta > 0) & (delta <= HORIZON_30D_MS)
    if not np.any(within_30d):
        return 0, 0
    matched_index = cohort_index[within_30d]
    matched_times = times[within_30d]
    unique_index, frequency = np.unique(matched_index, return_counts=True)
    counts_30d[unique_index] += frequency.astype(np.int32, copy=False)
    np.minimum.at(first_next, matched_index, matched_times)
    within_7d = delta[within_30d] <= HORIZON_7D_MS
    if np.any(within_7d):
        seven_index, seven_frequency = np.unique(
            matched_index[within_7d], return_counts=True
        )
        counts_7d[seven_index] += seven_frequency.astype(np.int32, copy=False)
    return int(matched_index.size), int(np.unique(matched_index).size)


def process_event_file(
    *,
    file_row: dict[str, Any],
    file_index: int,
    cohort_rows: int,
    lookup: Any,
    anchors: Any,
    output_path: Path,
    batch_rows: int,
) -> dict[str, Any]:
    _, np, pa, pq = import_dependencies()
    path = Path(file_row["path"])
    parquet = pq.ParquetFile(path)
    counts_7d = np.zeros(cohort_rows, dtype=np.int32)
    counts_30d = np.zeros(cohort_rows, dtype=np.int32)
    first_next = np.full(cohort_rows, np.iinfo(np.int64).max, dtype=np.int64)
    endpoint_hits = 0
    endpoint_batches_with_hits = 0
    scanned_rows = 0
    invalid_event_time_rows = 0
    for batch in parquet.iter_batches(
        batch_size=batch_rows,
        row_groups=list(file_row["selected_row_groups"]),
        columns=list(EVENT_COLUMNS),
        use_threads=True,
    ):
        scanned_rows += batch.num_rows
        times = arrow_int64(batch.column(0), np, pa)
        invalid_event_time_rows += int(np.count_nonzero(times <= 0))
        white = arrow_int64(batch.column(1), np, pa)
        black = arrow_int64(batch.column(2), np, pa)
        for ids in (white, black):
            hits, _ = update_endpoint(
                event_ids=ids,
                event_times=times,
                lookup=lookup,
                anchors=anchors,
                counts_7d=counts_7d,
                counts_30d=counts_30d,
                first_next=first_next,
                np=np,
            )
            endpoint_hits += hits
            endpoint_batches_with_hits += int(hits > 0)
    nonzero = np.flatnonzero(counts_30d > 0)
    table = pa.table(
        {
            "cohort_row_id": pa.array(nonzero, type=pa.int64()),
            "games_within_7d": pa.array(counts_7d[nonzero], type=pa.int32()),
            "games_within_30d": pa.array(counts_30d[nonzero], type=pa.int32()),
            "first_next_game_utc_ms": pa.array(first_next[nonzero], type=pa.int64()),
            "chronology_file_index": pa.array(
                np.full(nonzero.size, file_index, dtype=np.int32), type=pa.int32()
            ),
        }
    )
    temporary = output_path.with_name(output_path.name + f".tmp.{uuid.uuid4().hex}")
    pq.write_table(
        table,
        temporary,
        compression="zstd",
        row_group_size=250_000,
        write_statistics=True,
    )
    os.replace(temporary, output_path)
    return {
        "status": "A3_CHRONOLOGY_FILE_CHECKPOINT_OK",
        "created_utc": utc_now(),
        "chronology_file_index": file_index,
        "input_path": str(path),
        "input_footer_signature_sha256": file_row["footer_signature_sha256"],
        "selected_row_groups": list(file_row["selected_row_groups"]),
        "scanned_rows": scanned_rows,
        "invalid_event_time_rows_excluded": invalid_event_time_rows,
        "matched_endpoint_events_30d": endpoint_hits,
        "endpoint_batches_with_hits": endpoint_batches_with_hits,
        "accounts_with_events_30d_in_file": int(nonzero.size),
        "output_path": str(output_path),
        "output_rows": table.num_rows,
        "output_bytes": output_path.stat().st_size,
        "output_sha256": sha256_file(output_path),
    }


def authenticate_file_checkpoint(
    output: Path, receipt: Path, file_row: dict[str, Any], file_index: int
) -> dict[str, Any] | None:
    if not output.exists() and not receipt.exists():
        return None
    if not output.is_file() or not receipt.is_file():
        raise RuntimeError(f"Incomplete chronology checkpoint at index {file_index}")
    saved = load_json(receipt)
    expected = {
        "status": "A3_CHRONOLOGY_FILE_CHECKPOINT_OK",
        "chronology_file_index": file_index,
        "input_path": file_row["path"],
        "input_footer_signature_sha256": file_row["footer_signature_sha256"],
        "output_path": str(output),
    }
    failures = {
        key: {"expected": value, "actual": saved.get(key)}
        for key, value in expected.items()
        if saved.get(key) != value
    }
    if failures:
        raise RuntimeError(
            f"Chronology checkpoint metadata mismatch at {file_index}: {failures}"
        )
    if output.stat().st_size != safe_int(saved.get("output_bytes")):
        raise RuntimeError(f"Chronology checkpoint size mismatch at {file_index}")
    if sha256_file(output) != saved.get("output_sha256"):
        raise RuntimeError(f"Chronology checkpoint SHA mismatch at {file_index}")
    return saved


def load_cohort_lookup(cohort: Path) -> tuple[Any, Any, int]:
    _, np, _, pq = import_dependencies()
    table = pq.read_table(
        cohort,
        columns=["cohort_row_id", "disconnected_user_id", "exposure_anchor_utc_ms"],
    )
    row_ids = np.asarray(table["cohort_row_id"].to_numpy(), dtype=np.int64)
    user_ids = np.asarray(table["disconnected_user_id"].to_numpy(), dtype=np.int64)
    anchors = np.asarray(table["exposure_anchor_utc_ms"].to_numpy(), dtype=np.int64)
    rows = row_ids.size
    if rows != EXPECTED_PRIMARY_COHORT_ROWS or not np.array_equal(
        row_ids, np.arange(rows, dtype=np.int64)
    ):
        raise RuntimeError("Private cohort row order is not the certified dense order")
    if np.any(user_ids < 0) or np.unique(user_ids).size != rows:
        raise RuntimeError("Private cohort user IDs are invalid or nonunique")
    maximum_user_id = int(user_ids.max())
    if maximum_user_id > 100_000_000:
        raise RuntimeError(f"Implausible maximum global user ID: {maximum_user_id}")
    lookup = np.full(maximum_user_id + 1, -1, dtype=np.int32)
    lookup[user_ids] = row_ids.astype(np.int32)
    return lookup, anchors, rows


def initialize_or_authenticate_state(payload: dict[str, Any]) -> Path:
    state = Path(payload["state_root"])
    config_path = state / "resume_config.json"
    if state.exists():
        if not config_path.is_file():
            raise RuntimeError(f"State root exists without resume config: {state}")
        saved = load_json(config_path)
        if saved.get("resume_config_sha256") != payload["resume_config_sha256"]:
            raise RuntimeError(
                "Existing A3 checkpoint root belongs to another configuration"
            )
        print("A3_RESUME_STATE_AUTHENTICATED_OK", flush=True)
        return state
    state.mkdir(parents=True, exist_ok=False)
    (state / "updates").mkdir()
    (state / "receipts").mkdir()
    atomic_write_json(
        config_path,
        {
            "status": "A3_CHRONOLOGY_RESUME_CONFIG_OK",
            "created_utc": utc_now(),
            "resume_config": payload["resume_config"],
            "resume_config_sha256": payload["resume_config_sha256"],
            "raw_account_level_data": "PRIVATE; DO NOT COMMIT OR PUBLISH",
            "treatment_or_choice_outcome_read": False,
        },
    )
    print(f"A3_RESUME_STATE_CREATED: {state}", flush=True)
    return state


def finalize_private_activity(
    payload: dict[str, Any], state: Path, cohort: Path, update_paths: Sequence[Path]
) -> tuple[Path, dict[str, Any]]:
    duckdb, _, _, _ = import_dependencies()
    final = state / "a3_30d_activity_private_no_treatment.parquet"
    receipt = state / "_PRIVATE_SUCCESS.json"
    if final.is_file() and receipt.is_file():
        saved = load_json(receipt)
        if saved.get("output_sha256") != sha256_file(final):
            raise RuntimeError("Private A3 activity success SHA mismatch")
        if saved.get("resume_config_sha256") != payload["resume_config_sha256"]:
            raise RuntimeError("Private A3 activity success config mismatch")
        print("A3_PRIVATE_ACTIVITY_ALREADY_CERTIFIED_OK", flush=True)
        return final, saved
    if final.exists() or receipt.exists():
        raise RuntimeError("Incomplete private A3 finalization exists")
    temporary = final.with_name(final.name + f".tmp.{uuid.uuid4().hex}")
    connection = duckdb.connect()
    temp = state / "duckdb_temp/finalize"
    configure_duckdb(connection, payload, temp)
    updates_literal = path_list_literal(update_paths)
    connection.execute(
        f"""
        COPY (
          WITH updates AS (
            SELECT
              cohort_row_id,
              SUM(games_within_7d)::BIGINT AS games_within_7d,
              SUM(games_within_30d)::BIGINT AS games_within_30d,
              MIN(first_next_game_utc_ms)::BIGINT AS first_next_game_utc_ms
            FROM read_parquet({updates_literal}, union_by_name = true)
            GROUP BY cohort_row_id
          )
          SELECT
            c.cohort_row_id,
            c.disconnected_user_id,
            c.exposure_game_id,
            c.exposure_anchor_utc_ms,
            COALESCE(u.games_within_7d, 0)::INTEGER AS games_within_7d,
            COALESCE(u.games_within_30d, 0)::INTEGER AS games_within_30d,
            u.first_next_game_utc_ms,
            (COALESCE(u.games_within_7d, 0) > 0) AS any_game_within_7d,
            (COALESCE(u.games_within_30d, 0) > 0) AS any_game_within_30d
          FROM read_parquet({sql_literal(cohort)}) c
          LEFT JOIN updates u USING (cohort_row_id)
          ORDER BY c.cohort_row_id
        ) TO {sql_literal(temporary)}
        (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
        """
    )
    row = connection.execute(
        f"""
        SELECT
          COUNT(*)::BIGINT AS rows,
          COUNT(DISTINCT cohort_row_id)::BIGINT AS unique_rows,
          COUNT(DISTINCT disconnected_user_id)::BIGINT AS unique_users,
          COUNT(DISTINCT exposure_game_id)::BIGINT AS unique_exposures,
          SUM(CAST(any_game_within_7d AS BIGINT))::BIGINT AS any_7d,
          SUM(CAST(any_game_within_30d AS BIGINT))::BIGINT AS any_30d,
          SUM(games_within_7d)::BIGINT AS games_7d,
          SUM(games_within_30d)::BIGINT AS games_30d,
          COUNT(*) FILTER (
            WHERE games_within_7d > games_within_30d
               OR any_game_within_7d AND NOT any_game_within_30d
               OR (games_within_30d = 0) <> (first_next_game_utc_ms IS NULL)
          )::BIGINT AS consistency_failures,
          MAX(exposure_anchor_utc_ms)::BIGINT AS maximum_anchor_utc_ms
        FROM read_parquet({sql_literal(temporary)})
        """
    ).fetchone()
    connection.close()
    shutil.rmtree(temp.parent, ignore_errors=True)
    rows, unique_rows, unique_users, unique_exposures = row[:4]
    if (rows, unique_rows, unique_users, unique_exposures) != (
        EXPECTED_PRIMARY_COHORT_ROWS,
        EXPECTED_PRIMARY_COHORT_ROWS,
        EXPECTED_PRIMARY_COHORT_ROWS,
        EXPECTED_PRIMARY_COHORT_ROWS,
    ):
        raise RuntimeError(f"Private A3 final row/uniqueness QA failed: {row}")
    if row[8] != 0:
        raise RuntimeError(f"Private A3 consistency QA failed: {row}")
    if payload["chronology"]["utc_ms_max"] < int(row[9]) + HORIZON_30D_MS:
        raise RuntimeError(
            "Chronology does not fully cover every cohort member for 30 days"
        )
    os.replace(temporary, final)
    saved = {
        "status": "A3_PRIVATE_30D_ACTIVITY_CERTIFIED_OK",
        "created_utc": utc_now(),
        "resume_config_sha256": payload["resume_config_sha256"],
        "output_path": str(final),
        "output_sha256": sha256_file(final),
        "output_bytes": final.stat().st_size,
        "rows": rows,
        "unique_users": unique_users,
        "accounts_with_any_game_7d": row[4],
        "accounts_with_any_game_30d": row[5],
        "games_within_7d": row[6],
        "games_within_30d": row[7],
        "chronology_30d_coverage_complete": True,
        "treatment_or_choice_outcome_read": False,
        "raw_account_level_data": "PRIVATE; DO NOT COMMIT OR PUBLISH",
    }
    atomic_write_json(receipt, saved)
    return final, saved


def pooled_gate_statistics(payload: dict[str, Any], private: Path) -> dict[str, Any]:
    duckdb, _, _, _ = import_dependencies()
    connection = duckdb.connect()
    row = connection.execute(
        f"""
        SELECT
          COUNT(*)::BIGINT AS accounts,
          SUM(CAST(any_game_within_7d AS BIGINT))::BIGINT AS accounts_any_7d,
          SUM(CAST(any_game_within_30d AS BIGINT))::BIGINT AS accounts_any_30d,
          AVG(CAST(any_game_within_30d AS DOUBLE))::DOUBLE AS pooled_rate_30d,
          AVG(CAST(games_within_7d AS DOUBLE))::DOUBLE AS mean_games_7d,
          AVG(CAST(games_within_30d AS DOUBLE))::DOUBLE AS mean_games_30d,
          AVG(LN(1.0 + games_within_30d))::DOUBLE AS mean_log1p_games_30d,
          QUANTILE_CONT(games_within_30d, 0.25)::DOUBLE AS count_30d_p25,
          QUANTILE_CONT(games_within_30d, 0.50)::DOUBLE AS count_30d_p50,
          QUANTILE_CONT(games_within_30d, 0.75)::DOUBLE AS count_30d_p75,
          QUANTILE_CONT(games_within_30d, 0.90)::DOUBLE AS count_30d_p90,
          QUANTILE_CONT(games_within_30d, 0.99)::DOUBLE AS count_30d_p99,
          MAX(games_within_30d)::BIGINT AS count_30d_max
        FROM read_parquet({sql_literal(private)})
        """
    ).fetchone()
    fields = [item[0] for item in connection.description]
    connection.close()
    result = dict(zip(fields, row))
    rate = float(result["pooled_rate_30d"])
    selected = select_a3_primary(rate)
    result.update(
        {
            "scope": "non_tournament_like_first_fair_recipient_exposure",
            "pooled_ceiling_threshold": POOLED_CEILING_THRESHOLD,
            "a3_primary_outcome_selected": selected,
            "binary_30d_always_reported": True,
            "raw_count_30d_always_reported": True,
            "treatment_or_choice_outcome_read": False,
            "arm_specific_result_produced": False,
        }
    )
    return result


def write_aggregate_report(
    payload: dict[str, Any],
    state: Path,
    private: Path,
    private_receipt: dict[str, Any],
    checkpoints: Sequence[dict[str, Any]],
    run_id: str,
    started: float,
) -> Path:
    output_base = Path(payload["output_root"])
    final = output_base / run_id
    partial = output_base / f".{run_id}.partial"
    if final.exists() or partial.exists():
        raise RuntimeError(f"Aggregate report target exists: {final} or {partial}")
    partial.mkdir(parents=True, exist_ok=False)
    pooled = pooled_gate_statistics(payload, private)
    write_csv(
        partial / "pooled_a3_30d_gate.csv",
        [pooled],
        tuple(pooled.keys()),
    )
    checkpoint_summary = {
        "selected_chronology_files": len(checkpoints),
        "scanned_rows": sum(safe_int(row.get("scanned_rows")) for row in checkpoints),
        "matched_endpoint_events_30d": sum(
            safe_int(row.get("matched_endpoint_events_30d")) for row in checkpoints
        ),
        "checkpoint_output_rows": sum(
            safe_int(row.get("output_rows")) for row in checkpoints
        ),
        "all_file_checkpoints_authenticated": True,
    }
    write_csv(
        partial / "chronology_checkpoint_summary.csv",
        [checkpoint_summary],
        tuple(checkpoint_summary.keys()),
    )
    chronology_rows = []
    for index, row in enumerate(payload["chronology"]["file_rows"]):
        chronology_rows.append(
            {
                "file_index": index,
                "path": row["path"],
                "bytes": row["bytes"],
                "rows": row["rows"],
                "row_groups": row["row_groups"],
                "selected_row_groups": ",".join(
                    str(item) for item in row["selected_row_groups"]
                ),
                "utc_ms_min": row["utc_ms_min"],
                "utc_ms_max": row["utc_ms_max"],
                "footer_signature_sha256": row["footer_signature_sha256"],
            }
        )
    write_csv(
        partial / "chronology_input_manifest.tsv",
        chronology_rows,
        (
            "file_index",
            "path",
            "bytes",
            "rows",
            "row_groups",
            "selected_row_groups",
            "utc_ms_min",
            "utc_ms_max",
            "footer_signature_sha256",
        ),
        delimiter="\t",
    )
    input_auth = {
        "analysis_plan_sha256": payload["analysis_plan_sha256"],
        "script_sha256": payload["script_sha256"],
        "stage07_success_sha256": payload["stage07"]["success_sha256"],
        "prior_feasibility": payload["prior_feasibility"],
        "reentry_audit": payload["reentry_audit"],
        "arm_blind_anchor_bounds": payload["arm_blind_anchor_bounds"],
        "chronology_footer_plan_sha256": payload["chronology"]["footer_plan_sha256"],
        "resume_config_sha256": payload["resume_config_sha256"],
        "git": payload["git"],
    }
    atomic_write_json(partial / "input_authentication.json", input_auth)
    summary = {
        "status": "A3_CHRONOLOGY_POOLED_FEASIBILITY_GATE_OK",
        "created_utc": utc_now(),
        "script_version": SCRIPT_VERSION,
        "script_sha256": payload["script_sha256"],
        "analysis_plan_sha256": payload["analysis_plan_sha256"],
        "git_head": payload["git"]["head"],
        "pooled_gate": pooled,
        "checkpoint_summary": checkpoint_summary,
        "private_activity_sha256": private_receipt["output_sha256"],
        "private_activity_rows": private_receipt["rows"],
        "private_activity_path_machine_specific": str(private),
        "chronology_30d_coverage_complete": True,
        "arm_blind_anchor_bounds": payload["arm_blind_anchor_bounds"],
        "treatment_or_choice_outcome_read": False,
        "arm_specific_result_produced": False,
        "a1_a3_b1_effect_estimates_produced": False,
        "runtime_seconds": time.time() - started,
        "next_step": (
            "The blinded feasibility gate is complete. Freeze the exact A1/A3/B1 "
            "estimation producer before joining mercy receipt to this private cache."
        ),
    }
    atomic_write_json(partial / "summary.json", summary)
    atomic_write_json(partial / "_SUCCESS.json", summary)
    manifest = directory_manifest(partial)
    write_csv(
        partial / "report_file_hashes.tsv",
        manifest,
        ("sha256", "bytes", "path"),
        delimiter="\t",
    )
    for row in manifest:
        path = partial / row["path"]
        if path.stat().st_size != row["bytes"] or sha256_file(path) != row["sha256"]:
            raise RuntimeError(f"Aggregate report hash validation failed: {path}")
    os.replace(partial, final)
    state_success = state / "_GATE_SUCCESS.json"
    atomic_write_json(
        state_success,
        {
            "status": summary["status"],
            "created_utc": summary["created_utc"],
            "aggregate_report": str(final),
            "aggregate_success_sha256": sha256_file(final / "_SUCCESS.json"),
            "private_activity_sha256": private_receipt["output_sha256"],
            "resume_config_sha256": payload["resume_config_sha256"],
        },
    )
    return final


def execute(args: argparse.Namespace, payload: dict[str, Any]) -> Path:
    started = time.time()
    state = initialize_or_authenticate_state(payload)
    cohort = build_or_authenticate_cohort(payload, state)
    private_success = state / "_PRIVATE_SUCCESS.json"
    selected_rows = [
        row for row in payload["chronology"]["file_rows"] if row["selected_row_groups"]
    ]
    if private_success.is_file():
        print("A3_EVENT_SCAN_ALREADY_COMPLETE; authenticating final cache", flush=True)
        update_paths = [
            state / "updates" / f"chronology_{index:04d}.parquet"
            for index in range(len(selected_rows))
        ]
        checkpoints = [
            load_json(state / "receipts" / f"chronology_{index:04d}.json")
            for index in range(len(selected_rows))
        ]
    else:
        lookup, anchors, cohort_rows = load_cohort_lookup(cohort)
        update_paths = []
        checkpoints = []
        for index, file_row in enumerate(selected_rows):
            output = state / "updates" / f"chronology_{index:04d}.parquet"
            receipt = state / "receipts" / f"chronology_{index:04d}.json"
            saved = authenticate_file_checkpoint(output, receipt, file_row, index)
            if saved is None:
                file_started = time.time()
                saved = process_event_file(
                    file_row=file_row,
                    file_index=index,
                    cohort_rows=cohort_rows,
                    lookup=lookup,
                    anchors=anchors,
                    output_path=output,
                    batch_rows=args.batch_rows,
                )
                saved["runtime_seconds"] = time.time() - file_started
                atomic_write_json(receipt, saved)
            update_paths.append(output)
            checkpoints.append(saved)
            if (index + 1) % 5 == 0 or index + 1 == len(selected_rows):
                print(
                    "A3_SCAN_PROGRESS "
                    f"completed_files={index + 1}/{len(selected_rows)} "
                    f"last_rows={saved['scanned_rows']:,} "
                    f"last_matches={saved['matched_endpoint_events_30d']:,}",
                    flush=True,
                )
        del lookup, anchors
    private, private_receipt = finalize_private_activity(
        payload, state, cohort, update_paths
    )
    run_id = args.run_id or default_run_id()
    final = write_aggregate_report(
        payload,
        state,
        private,
        private_receipt,
        checkpoints,
        run_id,
        started,
    )
    print(f"A3_CHRONOLOGY_POOLED_FEASIBILITY_GATE_OK: {final}", flush=True)
    return final


def run_self_test() -> None:
    import numpy as np  # type: ignore

    assert HORIZON_7D_MS == 604_800_000
    assert HORIZON_30D_MS == 2_592_000_000
    assert select_a3_primary(0.92) == "any_rated_standard_game_within_30d"
    assert select_a3_primary(0.9200001) == "log1p_rated_standard_games_within_30d"
    query = cohort_sql([Path("synthetic.parquet")])
    assert "PARTITION BY disconnected_username_norm" in query
    assert not any(field in query for field in PROHIBITED_PRIVATE_COLUMNS)
    anchors = np.array([1_000, 2_000], dtype=np.int64)
    lookup = np.full(8, -1, dtype=np.int32)
    lookup[2] = 0
    lookup[5] = 1
    counts_7d = np.zeros(2, dtype=np.int32)
    counts_30d = np.zeros(2, dtype=np.int32)
    first_next = np.full(2, np.iinfo(np.int64).max, dtype=np.int64)
    update_endpoint(
        event_ids=np.array([2, 2, 5, 5, 7], dtype=np.int64),
        event_times=np.array(
            [900, 1_100, 2_100, 2_000 + 8 * DAY_MS, 3_000], dtype=np.int64
        ),
        lookup=lookup,
        anchors=anchors,
        counts_7d=counts_7d,
        counts_30d=counts_30d,
        first_next=first_next,
        np=np,
    )
    assert counts_7d.tolist() == [1, 1]
    assert counts_30d.tolist() == [1, 2]
    assert first_next.tolist() == [1_100, 2_100]
    print("A3_CHRONOLOGY_GATE_SELF_TEST_OK")


def run_integration_self_test() -> None:
    _, np, pa, pq = import_dependencies()
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        events = root / "events.parquet"
        output = root / "updates.parquet"
        anchors = np.array([1_000, 2_000], dtype=np.int64)
        lookup = np.full(8, -1, dtype=np.int32)
        lookup[2] = 0
        lookup[5] = 1
        table = pa.table(
            {
                "utc_ms": pa.array(
                    [900, 1_100, 2_000, 2_100, 1_000 + 8 * DAY_MS, 1_000 + 31 * DAY_MS],
                    type=pa.int64(),
                ),
                "white_id": pa.array([2, 2, 7, 7, 2, 2], type=pa.int64()),
                "black_id": pa.array([7, 7, 5, 5, 7, 7], type=pa.int64()),
            }
        )
        pq.write_table(table, events, row_group_size=3)
        parquet = pq.ParquetFile(events)
        file_row = {
            "path": str(events),
            "selected_row_groups": list(range(parquet.metadata.num_row_groups)),
            "footer_signature_sha256": "synthetic",
        }
        result = process_event_file(
            file_row=file_row,
            file_index=0,
            cohort_rows=2,
            lookup=lookup,
            anchors=anchors,
            output_path=output,
            batch_rows=2,
        )
        produced = pq.read_table(output).to_pydict()
        observed = {
            row_id: (seven, thirty, first)
            for row_id, seven, thirty, first in zip(
                produced["cohort_row_id"],
                produced["games_within_7d"],
                produced["games_within_30d"],
                produced["first_next_game_utc_ms"],
                strict=True,
            )
        }
        assert observed == {0: (1, 2, 1_100), 1: (1, 1, 2_100)}, observed
        assert result["matched_endpoint_events_30d"] == 3
    print("A3_CHRONOLOGY_GATE_INTEGRATION_SELF_TEST_OK")


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    if args.self_test:
        run_self_test()
        return
    if args.integration_self_test:
        run_integration_self_test()
        return
    if args.threads < 1 or args.threads > 32:
        raise SystemExit("--threads must be between 1 and 32")
    if args.batch_rows < 10_000 or args.batch_rows > 5_000_000:
        raise SystemExit("--batch-rows must be between 10,000 and 5,000,000")
    script_path = Path(__file__).resolve()
    payload = make_plan(args, script_path)
    print_plan(payload)
    if not args.execute:
        print(
            "No chronology row data was read. Re-run with --execute to begin or resume."
        )
        return
    execute(args, payload)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            f"A3_CHRONOLOGY_GATE_FAIL_CLOSED: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        raise
