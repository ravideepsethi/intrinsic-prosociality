#!/usr/bin/env python3
"""Close the remaining evidence gaps around the certified A1 result.

This is a post-result sensitivity audit.  It does not alter the frozen A1/A3/B1
primary family.  It authenticates and exactly reproduces the certified A1
headline, enriches the first later fair-choice opportunity from certified Stage
07 one month at a time, and reports only aggregate diagnostics.  Account-level
checkpoints remain under the private derived-data root on XT_Pro.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import importlib.util
import json
import math
import os
import shutil
import sys
import time
import uuid
import zipfile
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable, Sequence


SCRIPT_VERSION = "1.0.0"
PROJECT_ROOT = Path("/Volumes/XT_Pro/lichess_kindness")
CORE_RUN_ID = "20260822T022146Z"

EXPECTED_BASE_PRODUCER_SHA256 = (
    "2dcf0dd19f7cfe8f694d348e6590df88083a37882404112229d6ef05ebc42713"
)
EXPECTED_CORE_SUCCESS_SHA256 = (
    "bd64005162bf8f37f9488d47e95c2ea4dd946d1227e909930a42dd8e4904f009"
)
EXPECTED_CORE_SUMMARY_SHA256 = (
    "fa49fb15e095fb961a3f4cca5b937d903bc890467ed8404e37683858dd20a269"
)
EXPECTED_CORE_MANIFEST_SHA256 = (
    "e2724dab02a2b7b7c10f68b63ed40ddc67f2345947aa923d851912df946d16d8"
)
EXPECTED_PRIVATE_RECIPIENT_SHA256 = (
    "41ef57b3118ea7d3b0bfb7a5e19040bd82e7794aa54fb6b06625d7793921816d"
)
EXPECTED_OVERLAP_PROPENSITY_SHA256 = (
    "c442a40c8e8261484f888408bd8997eba563730c150721b1c2362397b3c9cbfe"
)
EXPECTED_HEADLINE_COEFFICIENT = 0.010046862925197863
EXPECTED_HEADLINE_STANDARD_ERROR = 0.0012280635224883034
EXPECTED_HEADLINE_ROWS = 1_029_558
EXPECTED_HEADLINE_TREATED = 30_051
EXPECTED_HEADLINE_CONTROL = 999_507
EXPECTED_RAW_REACHERS = 1_029_943

DAY_MS = 24 * 60 * 60 * 1000
HOUR_MS = 60 * 60 * 1000
MINUTE_MS = 60 * 1000
HORIZON_90D_MS = 90 * DAY_MS


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--base-producer", type=Path)
    parser.add_argument("--core-result-root", type=Path)
    parser.add_argument("--core-state-root", type=Path)
    parser.add_argument("--stage07-root", type=Path)
    parser.add_argument("--private-state-root", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--memory-limit", default="16GB")
    parser.add_argument("--verify-stage07-hashes", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--self-test", action="store_true")
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


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


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
    path: Path, rows: Iterable[dict[str, Any]], *, delimiter: str = ","
) -> None:
    materialized = list(rows)
    fields: list[str] = []
    seen: set[str] = set()
    for row in materialized:
        for key in row:
            if key not in seen:
                fields.append(key)
                seen.add(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{uuid.uuid4().hex}")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=fields,
            extrasaction="ignore",
            delimiter=delimiter,
        )
        writer.writeheader()
        for row in materialized:
            writer.writerow(
                {
                    key: json.dumps(value, separators=(",", ":"))
                    if isinstance(value, (list, dict, tuple))
                    else value
                    for key, value in row.items()
                }
            )
    os.replace(temporary, path)


def import_base(path: Path) -> ModuleType:
    if not path.is_file():
        raise RuntimeError(f"Certified base producer is missing: {path}")
    actual = sha256_file(path)
    if actual != EXPECTED_BASE_PRODUCER_SHA256:
        raise RuntimeError(
            "Certified base-producer SHA-256 mismatch: "
            f"expected={EXPECTED_BASE_PRODUCER_SHA256} actual={actual}"
        )
    spec = importlib.util.spec_from_file_location("a1_certified_base", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import certified base producer: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def authenticate_core_result(base: ModuleType, root: Path) -> dict[str, Any]:
    success = root / "_SUCCESS.json"
    summary = root / "summary.json"
    manifest = root / "report_file_hashes.tsv"
    expected = {
        success: EXPECTED_CORE_SUCCESS_SHA256,
        summary: EXPECTED_CORE_SUMMARY_SHA256,
        manifest: EXPECTED_CORE_MANIFEST_SHA256,
    }
    for path, digest in expected.items():
        if not path.is_file() or sha256_file(path) != digest:
            raise RuntimeError(f"Certified core authority mismatch: {path}")
    receipt = load_json(success)
    if receipt.get("status") != "DYNAMIC_PROSOCIALITY_CORE_V102_OK":
        raise RuntimeError("Certified core status changed")
    authenticated = base.authenticate_manifest(root, manifest)
    return {
        "root": str(root),
        "status": receipt["status"],
        "success_sha256": EXPECTED_CORE_SUCCESS_SHA256,
        "summary_sha256": EXPECTED_CORE_SUMMARY_SHA256,
        "manifest_sha256": EXPECTED_CORE_MANIFEST_SHA256,
        "report_files_authenticated": authenticated,
    }


def authenticate_private_file(
    path: Path, receipt: Path, expected_sha256: str, expected_rows: int
) -> dict[str, Any]:
    if not path.is_file() or not receipt.is_file():
        raise RuntimeError(f"Private checkpoint or receipt is missing: {path}")
    actual = sha256_file(path)
    if actual != expected_sha256:
        raise RuntimeError(f"Private checkpoint SHA-256 mismatch: {path}")
    saved = load_json(receipt)
    if saved.get("output_sha256") != expected_sha256:
        raise RuntimeError(f"Private checkpoint receipt SHA mismatch: {receipt}")
    if int(saved.get("rows", -1)) != expected_rows:
        raise RuntimeError(f"Private checkpoint receipt row mismatch: {receipt}")
    return {
        "path": str(path),
        "receipt": str(receipt),
        "sha256": expected_sha256,
        "rows": expected_rows,
    }


def make_plan(args: argparse.Namespace, script_path: Path) -> dict[str, Any]:
    project = args.project_root.expanduser().resolve()
    package = script_path.parent
    base_path = (
        args.base_producer.expanduser().resolve()
        if args.base_producer
        else package / "10c_estimate_dynamic_prosociality_core.py"
    )
    base = import_base(base_path)
    core_result = (
        args.core_result_root.expanduser().resolve()
        if args.core_result_root
        else project / "output/dynamic_prosociality_core_v102" / CORE_RUN_ID
    )
    core_state = (
        args.core_state_root.expanduser().resolve()
        if args.core_state_root
        else project / "derived/replication/dynamic_prosociality_core_v102_PRIVATE"
    )
    stage07_root = (
        args.stage07_root.expanduser().resolve()
        if args.stage07_root
        else project / "derived/replication/analysis_panel_24m_sf100k"
    )
    private_state = (
        args.private_state_root.expanduser().resolve()
        if args.private_state_root
        else project
        / "derived/replication/a1_evidence_gap_audit_v100_PRIVATE"
    )
    output_root = (
        args.output_root.expanduser().resolve()
        if args.output_root
        else project / "output/a1_evidence_gap_audit_v100"
    )
    run_id = args.run_id or default_run_id()

    core = authenticate_core_result(base, core_result)
    recipient = authenticate_private_file(
        core_state / "recipient_with_chronology_private.parquet",
        core_state / "recipient_with_chronology_receipt.json",
        EXPECTED_PRIVATE_RECIPIENT_SHA256,
        base.EXPECTED_A3_PRIVATE_ROWS,
    )
    overlap = authenticate_private_file(
        core_state / "recipient_overlap_propensity_private.parquet",
        core_state / "recipient_overlap_propensity_receipt.json",
        EXPECTED_OVERLAP_PROPENSITY_SHA256,
        base.EXPECTED_A3_PRIVATE_ROWS,
    )
    stage07 = base.authenticate_stage07(
        stage07_root, verify_hashes=args.verify_stage07_hashes
    )
    if shutil.disk_usage(project).free < 20 * 1024**3:
        raise RuntimeError("Less than 20 GiB is free on XT_Pro")

    config = {
        "script_version": SCRIPT_VERSION,
        "script_sha256": sha256_file(script_path),
        "base_producer_sha256": EXPECTED_BASE_PRODUCER_SHA256,
        "core_success_sha256": EXPECTED_CORE_SUCCESS_SHA256,
        "private_recipient_sha256": EXPECTED_PRIVATE_RECIPIENT_SHA256,
        "overlap_propensity_sha256": EXPECTED_OVERLAP_PROPENSITY_SHA256,
        "stage07_success_sha256": base.EXPECTED_STAGE07_SUCCESS_SHA256,
        "stage07_paths": [str(path) for path in stage07["paths"]],
        "threads": int(args.threads),
        "memory_limit": str(args.memory_limit),
        "audit_scope": {
            "same_benefactor": "original next opportunity and first nonbenefactor opportunity",
            "immediate_windows_ms": [
                10 * MINUTE_MS,
                30 * MINUTE_MS,
                HOUR_MS,
                6 * HOUR_MS,
                DAY_MS,
            ],
            "composition_family": "first later fair-choice opportunity",
            "temporal_split": "exposure months 0-11 versus 12-23; post-result internal",
        },
    }
    return {
        "status": "A1_EVIDENCE_GAP_AUDIT_V100_PLAN_OK",
        "base": base,
        "base_path": str(base_path),
        "project": str(project),
        "core": core,
        "recipient": recipient,
        "overlap": overlap,
        "stage07": stage07,
        "stage07_root": str(stage07_root),
        "private_state": str(private_state),
        "output_root": str(output_root),
        "run_id": run_id,
        "threads": int(args.threads),
        "memory_limit": str(args.memory_limit),
        "verify_stage07_hashes": bool(args.verify_stage07_hashes),
        "config": config,
        "config_sha256": sha256_json(config),
    }


def print_plan(payload: dict[str, Any]) -> None:
    print(payload["status"])
    print(f"script_version: {SCRIPT_VERSION}")
    print(f"base_producer_sha256: {EXPECTED_BASE_PRODUCER_SHA256}")
    print(f"core_success_sha256: {EXPECTED_CORE_SUCCESS_SHA256}")
    print(f"private_recipient_sha256: {EXPECTED_PRIVATE_RECIPIENT_SHA256}")
    print(f"stage07_months: {len(payload['stage07']['paths'])}")
    print(f"stage07_hashes_verified: {payload['verify_stage07_hashes']}")
    print(f"threads: {payload['threads']}")
    print(f"memory_limit: {payload['memory_limit']}")
    print(f"private_state: {payload['private_state']}")
    print(f"output_run: {Path(payload['output_root']) / payload['run_id']}")
    print("first-run ETA: approximately 15-40 minutes")
    print("resumed modeling-only ETA: approximately 4-12 minutes")
    if payload["verify_stage07_hashes"]:
        print("full Stage07 hash verification may add approximately 2-10 minutes")
    print("checkpointing: one authenticated private checkpoint per Stage07 month")
    print("privacy: only aggregate CSV/JSON/Markdown leaves the private state root")


def initialize_state(payload: dict[str, Any]) -> Path:
    state = Path(payload["private_state"])
    config_path = state / "resume_config.json"
    if state.exists():
        if not config_path.is_file():
            raise RuntimeError(f"Private state exists without resume config: {state}")
        saved = load_json(config_path)
        if saved.get("config_sha256") != payload["config_sha256"]:
            raise RuntimeError("Existing private state belongs to another audit configuration")
        print("A1_EVIDENCE_AUDIT_RESUME_STATE_AUTHENTICATED_OK", flush=True)
        return state
    (state / "future_months").mkdir(parents=True, exist_ok=False)
    (state / "receipts").mkdir(parents=True, exist_ok=True)
    (state / "duckdb_temp").mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        config_path,
        {
            "status": "A1_EVIDENCE_AUDIT_PRIVATE_STATE_OK",
            "created_utc": utc_now(),
            "config": payload["config"],
            "config_sha256": payload["config_sha256"],
            "raw_account_level_data": "PRIVATE; DO NOT COMMIT OR PUBLISH",
        },
    )
    print(f"A1_EVIDENCE_AUDIT_PRIVATE_STATE_CREATED: {state}", flush=True)
    return state


def checkpoint_is_valid(
    path: Path,
    receipt: Path,
    payload: dict[str, Any],
    *,
    source_path: Path | None = None,
) -> bool:
    present = (path.exists(), receipt.exists())
    if not any(present):
        return False
    if not all(present) or not path.is_file() or not receipt.is_file():
        raise RuntimeError(f"Incomplete checkpoint exists: {path}")
    saved = load_json(receipt)
    if saved.get("config_sha256") != payload["config_sha256"]:
        raise RuntimeError(f"Checkpoint configuration mismatch: {path}")
    if source_path is not None:
        if saved.get("source_path") != str(source_path):
            raise RuntimeError(f"Checkpoint source-path mismatch: {path}")
        if int(saved.get("source_size_bytes", -1)) != source_path.stat().st_size:
            raise RuntimeError(f"Checkpoint source-size mismatch: {path}")
    if saved.get("output_sha256") != sha256_file(path):
        raise RuntimeError(f"Checkpoint output SHA-256 mismatch: {path}")
    return True


def build_eligible_exposures(
    payload: dict[str, Any], state: Path
) -> tuple[Path, dict[str, Any]]:
    base = payload["base"]
    duckdb, _, _, _ = base.import_dependencies()
    recipient = Path(payload["recipient"]["path"])
    output = state / "eligible_exposures_private.parquet"
    receipt = state / "receipts/eligible_exposures.json"
    if checkpoint_is_valid(output, receipt, payload):
        saved = load_json(receipt)
        print(
            f"ELIGIBLE_EXPOSURES_CHECKPOINT_OK rows={int(saved['rows']):,}",
            flush=True,
        )
        return output, saved
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    connection = duckdb.connect()
    temp = state / "duckdb_temp/eligible_exposures"
    base.configure_duckdb(connection, payload, temp)
    started = time.monotonic()
    print("ELIGIBLE_EXPOSURES_BUILD_BEGIN", flush=True)
    connection.execute(
        f"""
        COPY (
          SELECT
            CAST(cohort_row_id AS BIGINT) AS cohort_row_id,
            CAST(recipient_user_id AS BIGINT) AS recipient_user_id,
            CAST(exposure_chooser_user_id AS BIGINT) AS exposure_chooser_user_id,
            CAST(exposure_anchor_utc_ms AS BIGINT) AS exposure_anchor_utc_ms
          FROM read_parquet({base.sql_literal(recipient)})
          WHERE CAST(first_ever_pair AS BOOLEAN)
            AND CAST(arm_eligible AS BOOLEAN)
            AND CAST(a1_90d_followup_eligible AS BOOLEAN)
          ORDER BY cohort_row_id
        ) TO {base.sql_literal(temporary)}
        (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
        """
    )
    qa = connection.execute(
        f"""
        SELECT COUNT(*)::BIGINT, COUNT(DISTINCT cohort_row_id)::BIGINT,
               MIN(cohort_row_id)::BIGINT, MAX(cohort_row_id)::BIGINT
        FROM read_parquet({base.sql_literal(temporary)})
        """
    ).fetchone()
    connection.close()
    if qa[0] <= EXPECTED_HEADLINE_ROWS or qa[0] != qa[1] or qa[2] < 0:
        raise RuntimeError(f"Eligible-exposure checkpoint QA failed: {qa}")
    os.replace(temporary, output)
    saved = {
        "status": "A1_EVIDENCE_ELIGIBLE_EXPOSURES_PRIVATE_OK",
        "created_utc": utc_now(),
        "config_sha256": payload["config_sha256"],
        "source_recipient_sha256": EXPECTED_PRIVATE_RECIPIENT_SHA256,
        "rows": int(qa[0]),
        "minimum_cohort_row_id": int(qa[2]),
        "maximum_cohort_row_id": int(qa[3]),
        "output_path": str(output),
        "output_bytes": output.stat().st_size,
        "output_sha256": sha256_file(output),
        "elapsed_seconds": time.monotonic() - started,
        "raw_account_level_data": "PRIVATE; DO NOT COMMIT OR PUBLISH",
    }
    atomic_write_json(receipt, saved)
    print(
        f"ELIGIBLE_EXPOSURES_BUILD_OK rows={int(qa[0]):,} "
        f"elapsed={saved['elapsed_seconds']:.1f}s",
        flush=True,
    )
    return output, saved


FUTURE_FIELDS: dict[str, str] = {
    "utc_ms": "CAST(p.api_last_move_at_ms AS BIGINT)",
    "archive_ordinal": "CAST(p.archive_ordinal AS BIGINT)",
    "game_id": "CAST(p.game_id AS VARCHAR)",
    "kind_draw": "CAST(CAST(p.kind_draw AS BOOLEAN) AS TINYINT)",
    "delta_ms": "CAST(p.api_last_move_at_ms AS BIGINT) - e.exposure_anchor_utc_ms",
    "eval_cp": "CAST(p.engine_eval_cp_disconnected AS DOUBLE)",
    "draw_payoff": "CAST(p.chooser_draw_payoff_v2 AS DOUBLE)",
    "win_premium": "CAST(p.chooser_win_premium_v2 AS DOUBLE)",
    "chooser_clock_s": "CAST(p.chooser_clock_last_obs_s AS DOUBLE)",
    "opponent_clock_s": "CAST(p.disconnected_clock_last_obs_s AS DOUBLE)",
    "chooser_elo": "CAST(p.chooser_elo AS DOUBLE)",
    "opponent_elo": "CAST(p.disconnected_elo AS DOUBLE)",
    "chooser_rd": "CAST(p.chooser_pre_rd_v2 AS DOUBLE)",
    "opponent_rd": "CAST(p.disconnected_pre_rd_v2 AS DOUBLE)",
    "tournament_like": "CAST(CAST(p.tournament_like_event AS BOOLEAN) AS TINYINT)",
    "ply_count": "CAST(p.ply_count AS DOUBLE)",
    "material_advantage": "CAST(p.material_advantage_chooser AS DOUBLE)",
    "opponent_user_id": "CAST(p.disconnected_user_id AS BIGINT)",
}


def month_future_sql(
    base: ModuleType, eligible: Path, stage_path: Path, output: Path
) -> str:
    speed_expression = base.speed_code_sql("p.api_speed")
    candidate_columns = [
        f"          {expression} AS {name}"
        for name, expression in FUTURE_FIELDS.items()
    ]
    candidate_columns.extend(
        [
            f"          CAST({speed_expression} AS INTEGER) AS speed_code",
            "          CAST(CAST(p.disconnected_user_id AS BIGINT) = "
            "e.exposure_chooser_user_id AS TINYINT) AS same_benefactor",
        ]
    )
    fields = [*FUTURE_FIELDS, "speed_code", "same_benefactor"]
    any_aggregates = [
        f"          MAX(CASE WHEN overall_rank = 1 THEN {name} END) "
        f"AS first_any_{name}"
        for name in fields
    ]
    nonbenefactor_aggregates = [
        f"          MAX(CASE WHEN same_benefactor = 0 AND status_rank = 1 "
        f"THEN {name} END) AS first_nonbenefactor_{name}"
        for name in fields
    ]
    candidate_sql = ",\n".join(candidate_columns)
    aggregate_sql = ",\n".join(any_aggregates + nonbenefactor_aggregates)
    return f"""
      COPY (
        WITH e AS (
          SELECT * FROM read_parquet({base.sql_literal(eligible)})
        ), p AS (
          SELECT * FROM read_parquet({base.sql_literal(stage_path)})
          WHERE CAST(fair_competitive AS BOOLEAN)
        ), candidates AS (
          SELECT
            e.cohort_row_id,
{candidate_sql}
          FROM e
          INNER JOIN p
            ON CAST(p.chooser_user_id AS BIGINT) = e.recipient_user_id
           AND CAST(p.api_last_move_at_ms AS BIGINT) > e.exposure_anchor_utc_ms
           AND CAST(p.api_last_move_at_ms AS BIGINT)
                 <= e.exposure_anchor_utc_ms + {HORIZON_90D_MS}
        ), ranked AS (
          SELECT *,
            ROW_NUMBER() OVER (
              PARTITION BY cohort_row_id ORDER BY utc_ms, archive_ordinal, game_id
            ) AS overall_rank,
            ROW_NUMBER() OVER (
              PARTITION BY cohort_row_id, same_benefactor
              ORDER BY utc_ms, archive_ordinal, game_id
            ) AS status_rank
          FROM candidates
        )
        SELECT
          cohort_row_id,
          COUNT(*)::BIGINT AS future_opportunity_count,
          SUM(CAST(same_benefactor AS BIGINT))::BIGINT
            AS future_benefactor_opportunity_count,
{aggregate_sql}
        FROM ranked
        GROUP BY cohort_row_id
        ORDER BY cohort_row_id
      ) TO {base.sql_literal(output)}
      (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
    """


def build_month_checkpoint(
    payload: dict[str, Any],
    state: Path,
    eligible: Path,
    stage_path: Path,
) -> tuple[Path, dict[str, Any]]:
    base = payload["base"]
    duckdb, _, _, pq = base.import_dependencies()
    month = stage_path.parent.name.removeprefix("month=")
    output = state / "future_months" / f"month={month}.parquet"
    receipt = state / "receipts" / f"future_month_{month}.json"
    if checkpoint_is_valid(
        output, receipt, payload, source_path=stage_path
    ):
        saved = load_json(receipt)
        print(
            f"FUTURE_MONTH_CHECKPOINT_OK month={month} "
            f"rows={int(saved['rows']):,}",
            flush=True,
        )
        return output, saved
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    connection = duckdb.connect()
    temp = state / "duckdb_temp" / f"future_month_{month}"
    base.configure_duckdb(connection, payload, temp)
    started = time.monotonic()
    print(f"FUTURE_MONTH_BUILD_BEGIN month={month}", flush=True)
    connection.execute(month_future_sql(base, eligible, stage_path, temporary))
    connection.close()
    rows = int(pq.read_metadata(temporary).num_rows)
    os.replace(temporary, output)
    saved = {
        "status": "A1_EVIDENCE_FUTURE_MONTH_PRIVATE_OK",
        "created_utc": utc_now(),
        "month": month,
        "config_sha256": payload["config_sha256"],
        "source_path": str(stage_path),
        "source_size_bytes": stage_path.stat().st_size,
        "rows": rows,
        "output_path": str(output),
        "output_bytes": output.stat().st_size,
        "output_sha256": sha256_file(output),
        "elapsed_seconds": time.monotonic() - started,
        "raw_account_level_data": "PRIVATE; DO NOT COMMIT OR PUBLISH",
    }
    atomic_write_json(receipt, saved)
    print(
        f"FUTURE_MONTH_BUILD_OK month={month} rows={rows:,} "
        f"elapsed={saved['elapsed_seconds']:.1f}s",
        flush=True,
    )
    return output, saved


def final_enrichment_sql(
    base: ModuleType, month_paths: Sequence[Path], output: Path
) -> str:
    fields = [*FUTURE_FIELDS, "speed_code", "same_benefactor"]
    any_select = ",\n".join(
        f"          first_any_{name}" for name in fields
    )
    nonbenefactor_select = ",\n".join(
        f"          first_nonbenefactor_{name}" for name in fields
    )
    final_any = ",\n".join(
        f"        a.first_any_{name}" for name in fields
    )
    final_nonbenefactor = ",\n".join(
        f"        n.first_nonbenefactor_{name}" for name in fields
    )
    return f"""
      COPY (
        WITH monthly AS (
          SELECT * FROM read_parquet(
            {base.path_list_literal(month_paths)}, union_by_name = true
          )
        ), counts AS (
          SELECT cohort_row_id,
            SUM(future_opportunity_count)::BIGINT AS future_opportunity_count,
            SUM(future_benefactor_opportunity_count)::BIGINT
              AS future_benefactor_opportunity_count
          FROM monthly
          GROUP BY cohort_row_id
        ), any_ranked AS (
          SELECT cohort_row_id,
{any_select},
            ROW_NUMBER() OVER (
              PARTITION BY cohort_row_id
              ORDER BY first_any_utc_ms, first_any_archive_ordinal,
                       first_any_game_id
            ) AS selected_rank
          FROM monthly
          WHERE first_any_delta_ms IS NOT NULL
        ), nonbenefactor_ranked AS (
          SELECT cohort_row_id,
{nonbenefactor_select},
            ROW_NUMBER() OVER (
              PARTITION BY cohort_row_id
              ORDER BY first_nonbenefactor_utc_ms,
                       first_nonbenefactor_archive_ordinal,
                       first_nonbenefactor_game_id
            ) AS selected_rank
          FROM monthly
          WHERE first_nonbenefactor_delta_ms IS NOT NULL
        )
        SELECT
          c.cohort_row_id,
          c.future_opportunity_count,
          c.future_benefactor_opportunity_count,
{final_any},
{final_nonbenefactor}
        FROM counts c
        INNER JOIN any_ranked a
          ON a.cohort_row_id = c.cohort_row_id AND a.selected_rank = 1
        LEFT JOIN nonbenefactor_ranked n
          ON n.cohort_row_id = c.cohort_row_id AND n.selected_rank = 1
        ORDER BY c.cohort_row_id
      ) TO {base.sql_literal(output)}
      (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
    """


def build_final_enrichment(
    payload: dict[str, Any], state: Path, month_paths: Sequence[Path]
) -> tuple[Path, dict[str, Any]]:
    base = payload["base"]
    duckdb, _, _, _ = base.import_dependencies()
    output = state / "first_future_enriched_private.parquet"
    receipt = state / "receipts/first_future_enriched.json"
    if checkpoint_is_valid(output, receipt, payload):
        saved = load_json(receipt)
        if int(saved.get("rows", -1)) != EXPECTED_RAW_REACHERS:
            raise RuntimeError("Final-enrichment checkpoint row count changed")
        print(
            f"FINAL_ENRICHMENT_CHECKPOINT_OK rows={int(saved['rows']):,}",
            flush=True,
        )
        return output, saved
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    connection = duckdb.connect()
    temp = state / "duckdb_temp/final_enrichment"
    base.configure_duckdb(connection, payload, temp)
    started = time.monotonic()
    print("FINAL_ENRICHMENT_BUILD_BEGIN", flush=True)
    connection.execute(final_enrichment_sql(base, month_paths, temporary))
    qa = connection.execute(
        f"""
        SELECT COUNT(*)::BIGINT, COUNT(DISTINCT cohort_row_id)::BIGINT,
               SUM(CASE WHEN first_nonbenefactor_delta_ms IS NOT NULL
                        THEN 1 ELSE 0 END)::BIGINT,
               SUM(CAST(first_any_same_benefactor AS BIGINT))::BIGINT
        FROM read_parquet({base.sql_literal(temporary)})
        """
    ).fetchone()
    connection.close()
    if qa[0] != EXPECTED_RAW_REACHERS or qa[0] != qa[1]:
        raise RuntimeError(f"Final-enrichment row QA failed: {qa}")
    os.replace(temporary, output)
    saved = {
        "status": "A1_EVIDENCE_FIRST_FUTURE_ENRICHED_PRIVATE_OK",
        "created_utc": utc_now(),
        "config_sha256": payload["config_sha256"],
        "rows": int(qa[0]),
        "reached_nonbenefactor_rows": int(qa[2]),
        "first_next_same_benefactor_rows": int(qa[3]),
        "month_checkpoints": len(month_paths),
        "month_checkpoint_sha256": [sha256_file(path) for path in month_paths],
        "output_path": str(output),
        "output_bytes": output.stat().st_size,
        "output_sha256": sha256_file(output),
        "elapsed_seconds": time.monotonic() - started,
        "raw_account_level_data": "PRIVATE; DO NOT COMMIT OR PUBLISH",
    }
    atomic_write_json(receipt, saved)
    print(
        f"FINAL_ENRICHMENT_BUILD_OK rows={int(qa[0]):,} "
        f"nonbenefactor={int(qa[2]):,} same_benefactor={int(qa[3]):,} "
        f"elapsed={saved['elapsed_seconds']:.1f}s",
        flush=True,
    )
    return output, saved


def nullable_float(column: Any, np: Any, pa: Any) -> Any:
    import pyarrow.compute as pc  # type: ignore

    combined = column.combine_chunks()
    combined = pc.cast(combined, pa.float64(), safe=True)
    combined = pc.fill_null(
        combined, pa.scalar(float("nan"), type=pa.float64())
    )
    return np.asarray(combined.to_numpy(zero_copy_only=False), dtype=np.float64)


def load_analysis_data(
    payload: dict[str, Any], enrichment: Path
) -> tuple[dict[str, Any], Any]:
    base = payload["base"]
    _, np, pa, pq = base.import_dependencies()
    data = base.load_recipient_arrays(Path(payload["recipient"]["path"]))
    table = pq.read_table(enrichment, use_threads=True)
    ids = np.asarray(
        table["cohort_row_id"].combine_chunks().to_numpy(), dtype=np.int64
    )
    if ids.size != EXPECTED_RAW_REACHERS or np.any(ids[1:] <= ids[:-1]):
        raise RuntimeError("Enriched checkpoint cohort ordering changed")
    fields = [
        name
        for name in [*FUTURE_FIELDS, "speed_code", "same_benefactor"]
        if name not in {"game_id", "opponent_user_id", "archive_ordinal", "utc_ms"}
    ]
    rows = data["cohort_row_id"].size
    for source_prefix, target_prefix in (
        ("first_any", "audit_any"),
        ("first_nonbenefactor", "audit_nonbenefactor"),
    ):
        for field in fields:
            values = np.full(rows, np.nan, dtype=np.float64)
            values[ids] = nullable_float(
                table[f"{source_prefix}_{field}"], np, pa
            )
            data[f"{target_prefix}_{field}"] = values
    future_count = np.zeros(rows, dtype=np.float64)
    benefactor_count = np.zeros(rows, dtype=np.float64)
    future_count[ids] = nullable_float(table["future_opportunity_count"], np, pa)
    benefactor_count[ids] = nullable_float(
        table["future_benefactor_opportunity_count"], np, pa
    )
    data["audit_future_opportunity_count"] = future_count
    data["audit_future_benefactor_opportunity_count"] = benefactor_count
    data["audit_reached_nonbenefactor"] = np.isfinite(
        data["audit_nonbenefactor_delta_ms"]
    ).astype(np.float64)
    data["audit_reached_same_benefactor"] = (benefactor_count > 0).astype(
        np.float64
    )
    data["audit_any_rating_gap"] = (
        data["audit_any_chooser_elo"] - data["audit_any_opponent_elo"]
    )
    data["audit_nonbenefactor_rating_gap"] = (
        data["audit_nonbenefactor_chooser_elo"]
        - data["audit_nonbenefactor_opponent_elo"]
    )
    data["audit_any_log1p_delta_hours"] = np.log1p(
        data["audit_any_delta_ms"] / HOUR_MS
    )
    for label, threshold in (
        ("10m", 10 * MINUTE_MS),
        ("30m", 30 * MINUTE_MS),
        ("1h", HOUR_MS),
        ("6h", 6 * HOUR_MS),
        ("1d", DAY_MS),
        ("7d", 7 * DAY_MS),
        ("30d", 30 * DAY_MS),
    ):
        reached = np.isfinite(data["audit_any_delta_ms"])
        values = np.full(rows, np.nan, dtype=np.float64)
        values[reached] = (
            data["audit_any_delta_ms"][reached] <= threshold
        ).astype(np.float64)
        data[f"audit_any_within_{label}"] = values
    same = data["audit_any_same_benefactor"]
    data["audit_any_same_benefactor_within_6h"] = (
        (same > 0.5) & (data["audit_any_delta_ms"] <= 6 * HOUR_MS)
    ).astype(np.float64)
    for code in range(6):
        reached = np.isfinite(data["audit_any_speed_code"])
        values = np.full(rows, np.nan, dtype=np.float64)
        values[reached] = (
            data["audit_any_speed_code"][reached] == code
        ).astype(np.float64)
        data[f"audit_any_speed_{code}"] = values
    return data, ids


def validate_and_reproduce_headline(
    payload: dict[str, Any], data: dict[str, Any], ids: Any
) -> tuple[dict[str, Any], dict[str, Any], Any]:
    base = payload["base"]
    _, np, _, _ = base.import_dependencies()
    support = base.common_support_weights(data)
    first = data["first_ever_pair"].astype(bool) & data["arm_eligible"].astype(
        bool
    )
    full_followup = first & data["a1_90d_followup_eligible"].astype(bool)
    reached = data["reached_fair_chooser_within_90d"].astype(bool)
    expected_ids = np.flatnonzero(full_followup & reached)
    if not np.array_equal(ids, expected_ids):
        raise RuntimeError(
            "Stage07 enrichment does not reproduce the certified raw reacher set"
        )
    original_kind = np.asarray(data["first_subsequent_kind_draw"][ids])
    enriched_kind = np.asarray(data["audit_any_kind_draw"][ids])
    if not np.array_equal(original_kind, enriched_kind):
        mismatch = int(np.count_nonzero(original_kind != enriched_kind))
        raise RuntimeError(f"Enriched first-outcome mismatch rows={mismatch}")
    original_delta = np.asarray(data["first_subsequent_delta_ms"][ids])
    enriched_delta = np.asarray(data["audit_any_delta_ms"][ids])
    if not np.array_equal(original_delta, enriched_delta):
        mismatch = int(np.count_nonzero(original_delta != enriched_delta))
        raise RuntimeError(f"Enriched first-timing mismatch rows={mismatch}")
    headline_sample = full_followup & reached
    headline = base.fit_recipient_outcome(
        data=data,
        support=support,
        outcome_name="first_subsequent_kind_draw",
        sample=headline_sample,
        estimand="certified_headline_reproduction_before_gap_audit",
        state_conditioned=False,
        binary_outcome=True,
    )
    exact_counts = (
        headline["rows"],
        headline["treated_rows"],
        headline["control_rows"],
    )
    if exact_counts != (
        EXPECTED_HEADLINE_ROWS,
        EXPECTED_HEADLINE_TREATED,
        EXPECTED_HEADLINE_CONTROL,
    ):
        raise RuntimeError(f"Headline reproduction sample changed: {exact_counts}")
    if abs(headline["coefficient"] - EXPECTED_HEADLINE_COEFFICIENT) > 1e-8:
        raise RuntimeError("Headline coefficient did not reproduce")
    if abs(headline["standard_error"] - EXPECTED_HEADLINE_STANDARD_ERROR) > 1e-8:
        raise RuntimeError("Headline standard error did not reproduce")
    print(
        "A1_CERTIFIED_HEADLINE_AND_STAGE07_ENRICHMENT_REPRODUCED_OK "
        f"rows={headline['rows']:,} coefficient_pp="
        f"{headline['coefficient_percentage_points']:.6f}",
        flush=True,
    )
    return support, headline, full_followup


def support_for_scope(
    base: ModuleType, data: dict[str, Any], scope: Any
) -> dict[str, Any]:
    _, np, _, _ = base.import_dependencies()
    treatment = data["received_mercy"].astype(bool)
    cell = data["exposure_cell_code"].astype(np.int64)
    valid = (
        np.asarray(scope, dtype=bool)
        & data["first_ever_pair"].astype(bool)
        & data["arm_eligible"].astype(bool)
        & (cell >= 0)
    )
    number_cells = 8 * 3 * 8 * 6
    treated_counts = np.bincount(
        cell[valid & treatment], minlength=number_cells
    ).astype(np.int64)
    control_counts = np.bincount(
        cell[valid & ~treatment], minlength=number_cells
    ).astype(np.int64)
    eligible_cells = (treated_counts >= 5) & (control_counts >= 20)
    eligible = valid & eligible_cells[cell]
    weights = np.zeros(treatment.size, dtype=np.float64)
    weights[eligible & treatment] = 1.0
    controls = eligible & ~treatment
    weights[controls] = (
        treated_counts[cell[controls]] / control_counts[cell[controls]]
    )
    initial_treated = int(np.count_nonzero(valid & treatment))
    retained_treated = int(np.count_nonzero(eligible & treatment))
    return {
        "eligible": eligible,
        "weights": weights,
        "eligible_cells": int(np.count_nonzero(eligible_cells)),
        "scope_rows": int(np.count_nonzero(valid)),
        "scope_treated": initial_treated,
        "retained_rows": int(np.count_nonzero(eligible)),
        "retained_treated": retained_treated,
        "retained_control": int(np.count_nonzero(eligible & ~treatment)),
        "treated_retention_share": retained_treated / initial_treated,
    }


def add_audit_metadata(row: dict[str, Any], label: str) -> dict[str, Any]:
    row["audit_label"] = label
    row["post_result_secondary"] = True
    row["primary_holm_family_reopened"] = False
    return row


def estimate_gap_sensitivities(
    payload: dict[str, Any],
    data: dict[str, Any],
    support: dict[str, Any],
    full_followup: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    base = payload["base"]
    _, np, _, _ = base.import_dependencies()
    reached = data["reached_fair_chooser_within_90d"].astype(bool)
    headline = full_followup & reached
    same = data["audit_any_same_benefactor"] > 0.5
    reached_nonbenefactor = data["audit_reached_nonbenefactor"] > 0.5
    rows: list[dict[str, Any]] = []

    specifications = [
        (
            "drop_original_next_if_same_focal_benefactor",
            "first_subsequent_kind_draw",
            headline & ~same,
        ),
        (
            "retarget_first_later_fair_choice_to_nonbenefactor",
            "audit_nonbenefactor_kind_draw",
            full_followup & reached_nonbenefactor,
        ),
        (
            "original_next_same_focal_benefactor_only_descriptive_subgroup",
            "first_subsequent_kind_draw",
            headline & same,
        ),
        (
            "drop_same_benefactor_or_any_next_within_6h",
            "first_subsequent_kind_draw",
            headline
            & ~same
            & (data["audit_any_delta_ms"] > 6 * HOUR_MS),
        ),
    ]
    for label, outcome, sample in specifications:
        result = base.fit_recipient_outcome(
            data=data,
            support=support,
            outcome_name=outcome,
            sample=sample,
            estimand=label,
            state_conditioned=False,
            binary_outcome=True,
        )
        rows.append(add_audit_metadata(result, label))

    for label, threshold in (
        ("10m", 10 * MINUTE_MS),
        ("30m", 30 * MINUTE_MS),
        ("1h", HOUR_MS),
        ("6h", 6 * HOUR_MS),
        ("1d", DAY_MS),
    ):
        estimand = f"drop_all_original_next_opportunities_within_{label}"
        result = base.fit_recipient_outcome(
            data=data,
            support=support,
            outcome_name="first_subsequent_kind_draw",
            sample=headline & (data["audit_any_delta_ms"] > threshold),
            estimand=estimand,
            state_conditioned=False,
            binary_outcome=True,
        )
        result["excluded_time_threshold_ms"] = threshold
        rows.append(add_audit_metadata(result, estimand))

    selection: list[dict[str, Any]] = []
    for label, outcome, sample in (
        (
            "reproduce_reach_any_fair_choice_within_90d",
            "reached_fair_chooser_within_90d",
            full_followup,
        ),
        (
            "reach_any_nonbenefactor_fair_choice_within_90d",
            "audit_reached_nonbenefactor",
            full_followup,
        ),
        (
            "reach_any_same_benefactor_fair_choice_within_90d",
            "audit_reached_same_benefactor",
            full_followup,
        ),
        (
            "first_next_is_same_focal_benefactor_conditional_on_reach",
            "audit_any_same_benefactor",
            headline,
        ),
    ):
        result = base.fit_recipient_outcome(
            data=data,
            support=support,
            outcome_name=outcome,
            sample=sample,
            estimand=label,
            state_conditioned=False,
            binary_outcome=True,
        )
        selection.append(add_audit_metadata(result, label))
    return rows, selection


def estimate_composition(
    payload: dict[str, Any],
    data: dict[str, Any],
    support: dict[str, Any],
    full_followup: Any,
) -> list[dict[str, Any]]:
    base = payload["base"]
    _, np, _, _ = base.import_dependencies()
    headline = full_followup & data["reached_fair_chooser_within_90d"].astype(bool)
    specifications: list[tuple[str, bool, str]] = [
        ("audit_any_same_benefactor", True, "probability"),
        ("audit_any_same_benefactor_within_6h", True, "probability"),
        ("audit_any_log1p_delta_hours", False, "log1p hours"),
        ("audit_any_eval_cp", False, "centipawns"),
        ("audit_any_draw_payoff", False, "rating points"),
        ("audit_any_win_premium", False, "rating points"),
        ("audit_any_chooser_elo", False, "Elo"),
        ("audit_any_opponent_elo", False, "Elo"),
        ("audit_any_rating_gap", False, "Elo"),
        ("audit_any_chooser_rd", False, "RD"),
        ("audit_any_opponent_rd", False, "RD"),
        ("audit_any_chooser_clock_s", False, "seconds"),
        ("audit_any_opponent_clock_s", False, "seconds"),
        ("audit_any_ply_count", False, "plies"),
        ("audit_any_material_advantage", False, "material units"),
        ("audit_any_tournament_like", True, "probability"),
        ("audit_any_within_10m", True, "probability"),
        ("audit_any_within_30m", True, "probability"),
        ("audit_any_within_1h", True, "probability"),
        ("audit_any_within_6h", True, "probability"),
        ("audit_any_within_1d", True, "probability"),
    ]
    for code in range(6):
        outcome = f"audit_any_speed_{code}"
        values = data[outcome][headline & support["eligible"]]
        if np.unique(values[np.isfinite(values)]).size > 1:
            specifications.append((outcome, True, "probability"))
    rows: list[dict[str, Any]] = []
    for outcome, binary, unit in specifications:
        values = np.asarray(data[outcome], dtype=np.float64)
        selected = headline & support["eligible"] & np.isfinite(values)
        if np.count_nonzero(selected) < 100:
            continue
        if binary and np.unique(values[selected]).size <= 1:
            continue
        label = f"treatment_effect_on_next_opportunity_composition_{outcome}"
        result = base.fit_recipient_outcome(
            data=data,
            support=support,
            outcome_name=outcome,
            sample=headline,
            estimand=label,
            state_conditioned=False,
            binary_outcome=binary,
        )
        result["outcome_unit"] = unit
        rows.append(add_audit_metadata(result, label))
    finite_positions = [
        index
        for index, row in enumerate(rows)
        if math.isfinite(float(row["p_value_raw"]))
    ]
    adjusted = base.holm_adjust(
        [float(rows[index]["p_value_raw"]) for index in finite_positions]
    )
    for row in rows:
        row["p_value_holm_within_composition_family"] = None
    for index, value in zip(finite_positions, adjusted, strict=True):
        rows[index]["p_value_holm_within_composition_family"] = value
    return rows


def weighted_quantile(values: Any, weights: Any, q: float, np: Any) -> float:
    values = np.asarray(values, dtype=np.float64)
    weights = np.asarray(weights, dtype=np.float64)
    valid = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    values = values[valid]
    weights = weights[valid]
    if values.size == 0:
        return math.nan
    order = np.argsort(values, kind="mergesort")
    values = values[order]
    weights = weights[order]
    cumulative = np.cumsum(weights)
    target = min(max(float(q), 0.0), 1.0) * cumulative[-1]
    position = int(np.searchsorted(cumulative, target, side="left"))
    return float(values[min(position, values.size - 1)])


def effective_sample_size(weights: Any, np: Any) -> float:
    weights = np.asarray(weights, dtype=np.float64)
    weights = weights[np.isfinite(weights) & (weights > 0)]
    if weights.size == 0:
        return math.nan
    return float(weights.sum() ** 2 / np.square(weights).sum())


def timing_diagnostics(
    payload: dict[str, Any],
    data: dict[str, Any],
    support: dict[str, Any],
    full_followup: Any,
) -> list[dict[str, Any]]:
    _, np, _, _ = payload["base"].import_dependencies()
    treatment = data["received_mercy"].astype(bool)
    sample = (
        full_followup
        & data["reached_fair_chooser_within_90d"].astype(bool)
        & support["eligible"]
    )
    hours = data["audit_any_delta_ms"] / HOUR_MS
    weights = support["weights"]
    rows: list[dict[str, Any]] = []
    for arm_label, arm_mask in (
        ("mercy", treatment),
        ("claimed", ~treatment),
    ):
        selected = sample & arm_mask
        for q in (0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99):
            rows.append(
                {
                    "diagnostic": "weighted_elapsed_time_quantile",
                    "arm": arm_label,
                    "quantile": q,
                    "elapsed_hours": weighted_quantile(
                        hours[selected], weights[selected], q, np
                    ),
                    "rows": int(np.count_nonzero(selected)),
                    "weight_sum": float(weights[selected].sum()),
                }
            )
        for label, threshold in (
            ("10m", 10 * MINUTE_MS),
            ("30m", 30 * MINUTE_MS),
            ("1h", HOUR_MS),
            ("6h", 6 * HOUR_MS),
            ("1d", DAY_MS),
            ("7d", 7 * DAY_MS),
            ("30d", 30 * DAY_MS),
            ("90d", 90 * DAY_MS),
        ):
            indicator = data["audit_any_delta_ms"][selected] <= threshold
            rows.append(
                {
                    "diagnostic": "weighted_cumulative_elapsed_time_share",
                    "arm": arm_label,
                    "threshold": label,
                    "threshold_ms": threshold,
                    "weighted_share": float(
                        np.average(indicator.astype(float), weights=weights[selected])
                    ),
                    "rows": int(np.count_nonzero(selected)),
                    "weight_sum": float(weights[selected].sum()),
                }
            )
    return rows


def overlap_and_weight_diagnostics(
    payload: dict[str, Any],
    data: dict[str, Any],
    support: dict[str, Any],
    full_followup: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    base = payload["base"]
    _, np, pa, pq = base.import_dependencies()
    table = pq.read_table(Path(payload["overlap"]["path"]), use_threads=True)
    row_ids = np.asarray(
        table["cohort_row_id"].combine_chunks().to_numpy(), dtype=np.int64
    )
    if not np.array_equal(row_ids, data["cohort_row_id"]):
        raise RuntimeError("Overlap propensity checkpoint lost dense row alignment")
    propensity = nullable_float(table["overlap_propensity"], np, pa)
    treatment = data["received_mercy"].astype(bool)
    first_pair = data["first_ever_pair"].astype(bool) & data["arm_eligible"].astype(
        bool
    )
    headline = (
        full_followup
        & data["reached_fair_chooser_within_90d"].astype(bool)
        & support["eligible"]
    )
    rows: list[dict[str, Any]] = []
    for sample_label, sample in (
        ("first_pair_arm_eligible", first_pair),
        ("headline_conditional_choice", headline),
    ):
        for arm_label, arm in (("mercy", treatment), ("claimed", ~treatment)):
            selected = sample & arm & np.isfinite(propensity)
            for q in (0.0, 0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99, 1.0):
                rows.append(
                    {
                        "sample": sample_label,
                        "arm": arm_label,
                        "diagnostic": "crossfit_treatment_propensity_quantile",
                        "quantile": q,
                        "value": weighted_quantile(
                            propensity[selected],
                            np.ones(int(np.count_nonzero(selected))),
                            q,
                            np,
                        ),
                        "rows": int(np.count_nonzero(selected)),
                    }
                )
    ess_rows: list[dict[str, Any]] = []
    for sample_label, sample in (
        ("full_common_support", support["eligible"]),
        ("headline_conditional_choice", headline),
    ):
        for arm_label, arm in (
            ("all", np.ones(treatment.size, dtype=bool)),
            ("mercy", treatment),
            ("claimed", ~treatment),
        ):
            selected = sample & arm
            selected_weights = support["weights"][selected]
            ess_rows.append(
                {
                    "sample": sample_label,
                    "arm": arm_label,
                    "rows": int(np.count_nonzero(selected)),
                    "weight_sum": float(selected_weights.sum()),
                    "weight_square_sum": float(np.square(selected_weights).sum()),
                    "effective_sample_size": effective_sample_size(
                        selected_weights, np
                    ),
                    "minimum_weight": float(selected_weights.min()),
                    "median_weight": weighted_quantile(
                        selected_weights,
                        np.ones(selected_weights.size),
                        0.5,
                        np,
                    ),
                    "maximum_weight": float(selected_weights.max()),
                }
            )
    return rows, ess_rows


def temporal_split_estimates(
    payload: dict[str, Any], data: dict[str, Any], full_followup: Any
) -> list[dict[str, Any]]:
    base = payload["base"]
    _, np, _, _ = base.import_dependencies()
    month = data["exposure_month_code"].astype(np.int64)
    reached = data["reached_fair_chooser_within_90d"].astype(bool)
    rows: list[dict[str, Any]] = []
    for label, scope in (
        ("first_12_exposure_months_2023_11_to_2024_10", (month >= 0) & (month < 12)),
        ("second_12_exposure_months_2024_11_to_2025_10", (month >= 12) & (month < 24)),
    ):
        scoped_support = support_for_scope(base, data, scope)
        result = base.fit_recipient_outcome(
            data=data,
            support=scoped_support,
            outcome_name="first_subsequent_kind_draw",
            sample=scope & full_followup & reached,
            estimand=f"post_result_internal_temporal_split_{label}",
            state_conditioned=False,
            binary_outcome=True,
        )
        result.update(
            {
                "audit_label": label,
                "post_result_secondary": True,
                "independent_replication": False,
                "support_cells": scoped_support["eligible_cells"],
                "support_scope_rows": scoped_support["scope_rows"],
                "support_retained_rows": scoped_support["retained_rows"],
                "support_treated_retention_share": scoped_support[
                    "treated_retention_share"
                ],
                "primary_holm_family_reopened": False,
            }
        )
        rows.append(result)
    return rows


def result_by_label(rows: Sequence[dict[str, Any]], label: str) -> dict[str, Any]:
    matches = [row for row in rows if row.get("audit_label") == label]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one audit result for {label}; found {len(matches)}")
    return matches[0]


def format_model(row: dict[str, Any]) -> str:
    return (
        f"{float(row['coefficient_percentage_points']):+.4f} pp "
        f"(SE {float(row['standard_error_percentage_points']):.4f}; "
        f"p={float(row['p_value_raw']):.4g}; N={int(row['rows']):,})"
    )


def render_report(
    headline: dict[str, Any],
    gap_rows: Sequence[dict[str, Any]],
    selection_rows: Sequence[dict[str, Any]],
    composition_rows: Sequence[dict[str, Any]],
    temporal_rows: Sequence[dict[str, Any]],
    ess_rows: Sequence[dict[str, Any]],
    enrichment_receipt: dict[str, Any],
) -> str:
    drop_same = result_by_label(
        gap_rows, "drop_original_next_if_same_focal_benefactor"
    )
    retarget = result_by_label(
        gap_rows, "retarget_first_later_fair_choice_to_nonbenefactor"
    )
    same_only = result_by_label(
        gap_rows,
        "original_next_same_focal_benefactor_only_descriptive_subgroup",
    )
    reach_nb = result_by_label(
        selection_rows, "reach_any_nonbenefactor_fair_choice_within_90d"
    )
    first_same = result_by_label(
        selection_rows, "first_next_is_same_focal_benefactor_conditional_on_reach"
    )
    significant_composition = [
        row
        for row in composition_rows
        if row.get("p_value_holm_within_composition_family") is not None
        and float(row["p_value_holm_within_composition_family"]) < 0.05
    ]
    headline_ess = next(
        row
        for row in ess_rows
        if row["sample"] == "headline_conditional_choice" and row["arm"] == "all"
    )
    lines = [
        "# A1 evidence-gap audit",
        "",
        "**Status:** post-result sensitivity audit; the frozen A1/A3/B1 primary family is unchanged.",
        "",
        "## Authentication and headline reproduction",
        "",
        f"The certified headline reproduced before any new analysis: {format_model(headline)}. "
        f"The Stage-07 rescan recovered all {int(enrichment_receipt['rows']):,} raw "
        "later-opportunity rows with zero outcome or timing mismatches.",
        "",
        "## Same-benefactor and rematch diagnostics",
        "",
        f"- Dropping recipients whose original next fair opportunity was against the focal benefactor: {format_model(drop_same)}.",
        f"- Retargeting the outcome to the first later fair opportunity against someone other than the focal benefactor: {format_model(retarget)}.",
        f"- Descriptive same-benefactor-only subgroup: {format_model(same_only)}. This is a post-treatment subgroup, not a causal estimand.",
        f"- Treatment effect on reaching a nonbenefactor opportunity within 90 days: {format_model(reach_nb)}.",
        f"- Treatment effect on the next opponent being the focal benefactor: {format_model(first_same)}.",
        "",
        "The exact 10-minute, 30-minute, 1-hour, 6-hour, and 1-day exclusions are in `results/same_benefactor_and_time_sensitivities.csv`. The time windows are explicit proxies; Stage 07 has no canonical session identifier, so they are not labeled as exact same-session tests.",
        "",
        "## Next-opportunity composition",
        "",
    ]
    if significant_composition:
        lines.append(
            "The following composition outcomes survive Holm adjustment within this new family:"
        )
        lines.append("")
        for row in significant_composition:
            lines.append(
                f"- `{row['outcome']}`: coefficient={float(row['coefficient']):+.6g} "
                f"{row['outcome_unit']}; Holm p="
                f"{float(row['p_value_holm_within_composition_family']):.4g}."
            )
    else:
        lines.append(
            "No measured composition outcome survives Holm adjustment within the new composition family."
        )
    lines.extend(
        [
            "",
            "All raw and adjusted composition results are in `results/next_opportunity_composition.csv`.",
            "",
            "## Internal temporal split",
            "",
        ]
    )
    for row in temporal_rows:
        lines.append(f"- `{row['audit_label']}`: {format_model(row)}.")
    lines.extend(
        [
            "",
            "This is a post-result split of the same certified panel, not an independent replication or preregistered holdout.",
            "",
            "## Support",
            "",
            f"Headline weighted effective sample size: {float(headline_ess['effective_sample_size']):,.1f} "
            f"from {int(headline_ess['rows']):,} rows. Propensity quantiles and arm-specific ESS are in `results/overlap_propensity_quantiles.csv` and `results/weight_ess.csv`.",
            "",
            "## Interpretation",
            "",
            "The defensible claim remains a robust conditional dynamic association consistent with behavioral transmission. Same-benefactor removal, timing exclusions, and composition checks can make simple direct-reciprocity or opportunity-selection accounts more or less plausible, but none converts the observational exposure into random assignment.",
            "",
        ]
    )
    return "\n".join(lines)


def report_manifest(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name in {"_SUCCESS.json", "report_file_hashes.tsv"}:
            continue
        rows.append(
            {
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
                "path": path.relative_to(root).as_posix(),
            }
        )
    return rows


def make_public_zip(root: Path, destination: Path) -> None:
    temporary = destination.with_name(destination.name + f".tmp.{uuid.uuid4().hex}")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=f"{root.name}/{path.relative_to(root)}")
    os.replace(temporary, destination)


def execute(payload: dict[str, Any], script_path: Path) -> tuple[Path, Path]:
    started = time.monotonic()
    state = initialize_state(payload)
    eligible, eligible_receipt = build_eligible_exposures(payload, state)
    month_paths: list[Path] = []
    month_receipts: list[dict[str, Any]] = []
    scan_started = time.monotonic()
    total_months = len(payload["stage07"]["paths"])
    for index, stage_path in enumerate(payload["stage07"]["paths"], start=1):
        path, receipt = build_month_checkpoint(
            payload, state, eligible, Path(stage_path)
        )
        month_paths.append(path)
        month_receipts.append(receipt)
        elapsed = time.monotonic() - scan_started
        remaining = max(total_months - index, 0)
        eta = (elapsed / index) * remaining if index else math.nan
        print(
            f"MONTHLY_SCAN_PROGRESS {index}/{total_months} "
            f"elapsed={elapsed / 60:.1f}m ETA={eta / 60:.1f}m",
            flush=True,
        )
    enrichment, enrichment_receipt = build_final_enrichment(
        payload, state, month_paths
    )

    print("A1_EVIDENCE_MODELING_BEGIN ETA=4-12 minutes", flush=True)
    data, ids = load_analysis_data(payload, enrichment)
    support, headline, full_followup = validate_and_reproduce_headline(
        payload, data, ids
    )
    gap_rows, selection_rows = estimate_gap_sensitivities(
        payload, data, support, full_followup
    )
    print("A1_EVIDENCE_GAP_SENSITIVITIES_OK", flush=True)
    composition_rows = estimate_composition(
        payload, data, support, full_followup
    )
    print(
        f"A1_EVIDENCE_COMPOSITION_FAMILY_OK models={len(composition_rows)}",
        flush=True,
    )
    timing_rows = timing_diagnostics(
        payload, data, support, full_followup
    )
    propensity_rows, ess_rows = overlap_and_weight_diagnostics(
        payload, data, support, full_followup
    )
    temporal_rows = temporal_split_estimates(payload, data, full_followup)
    print("A1_EVIDENCE_TEMPORAL_SPLIT_OK", flush=True)

    output_parent = Path(payload["output_root"])
    output_parent.mkdir(parents=True, exist_ok=True)
    final = output_parent / payload["run_id"]
    if final.exists():
        raise RuntimeError(f"Output run already exists: {final}")
    staging = output_parent / f".{payload['run_id']}.incomplete.{uuid.uuid4().hex}"
    (staging / "results").mkdir(parents=True, exist_ok=False)
    (staging / "receipts").mkdir(parents=True, exist_ok=True)
    (staging / "executed_code").mkdir(parents=True, exist_ok=True)

    write_csv(
        staging / "results/same_benefactor_and_time_sensitivities.csv",
        gap_rows,
    )
    write_csv(staging / "results/reach_and_opponent_selection.csv", selection_rows)
    write_csv(staging / "results/next_opportunity_composition.csv", composition_rows)
    write_csv(staging / "results/next_opportunity_timing_distribution.csv", timing_rows)
    write_csv(staging / "results/overlap_propensity_quantiles.csv", propensity_rows)
    write_csv(staging / "results/weight_ess.csv", ess_rows)
    write_csv(staging / "results/internal_temporal_split.csv", temporal_rows)
    write_csv(staging / "results/certified_headline_reproduction.csv", [headline])
    atomic_write_json(staging / "receipts/enrichment_aggregate_receipt.json", enrichment_receipt)
    atomic_write_json(
        staging / "receipts/input_authorities.json",
        {
            "status": "A1_EVIDENCE_GAP_AUDIT_INPUTS_AUTHENTICATED_OK",
            "created_utc": utc_now(),
            "script_version": SCRIPT_VERSION,
            "script_sha256": sha256_file(script_path),
            "base_producer_sha256": EXPECTED_BASE_PRODUCER_SHA256,
            "core_success_sha256": EXPECTED_CORE_SUCCESS_SHA256,
            "core_summary_sha256": EXPECTED_CORE_SUMMARY_SHA256,
            "core_manifest_sha256": EXPECTED_CORE_MANIFEST_SHA256,
            "private_recipient_sha256": EXPECTED_PRIVATE_RECIPIENT_SHA256,
            "overlap_propensity_sha256": EXPECTED_OVERLAP_PROPENSITY_SHA256,
            "stage07_success_sha256": payload["base"].EXPECTED_STAGE07_SUCCESS_SHA256,
            "stage07_parquet_hashes_verified_this_run": payload[
                "verify_stage07_hashes"
            ],
            "stage07_months": total_months,
            "config_sha256": payload["config_sha256"],
            "eligible_exposure_rows": eligible_receipt["rows"],
            "monthly_checkpoint_rows": [row["rows"] for row in month_receipts],
            "account_level_outputs_published": False,
        },
    )
    shutil.copy2(script_path, staging / "executed_code" / script_path.name)
    shutil.copy2(
        Path(payload["base_path"]),
        staging / "executed_code/10c_estimate_dynamic_prosociality_core.py",
    )
    report = render_report(
        headline,
        gap_rows,
        selection_rows,
        composition_rows,
        temporal_rows,
        ess_rows,
        enrichment_receipt,
    )
    atomic_write_text(staging / "A1_EVIDENCE_GAP_AUDIT_REPORT.md", report)
    summary = {
        "status": "A1_EVIDENCE_GAP_AUDIT_V100_OK",
        "created_utc": utc_now(),
        "script_version": SCRIPT_VERSION,
        "run_id": payload["run_id"],
        "headline_reproduction": headline,
        "same_benefactor_and_time_sensitivities": gap_rows,
        "reach_and_opponent_selection": selection_rows,
        "composition_family": composition_rows,
        "internal_temporal_split": temporal_rows,
        "weight_ess": ess_rows,
        "primary_holm_family_reopened": False,
        "independent_replication_completed": False,
        "interpretation": (
            "post-result observational sensitivity audit; no random-assignment claim"
        ),
    }
    atomic_write_json(staging / "summary.json", summary)
    manifest_rows = report_manifest(staging)
    write_csv(staging / "report_file_hashes.tsv", manifest_rows, delimiter="\t")
    success = {
        "status": "A1_EVIDENCE_GAP_AUDIT_V100_OK",
        "created_utc": utc_now(),
        "run_id": payload["run_id"],
        "script_version": SCRIPT_VERSION,
        "script_sha256": sha256_file(script_path),
        "config_sha256": payload["config_sha256"],
        "report_files": len(manifest_rows),
        "report_manifest_sha256": sha256_file(staging / "report_file_hashes.tsv"),
        "headline_reproduced": True,
        "stage07_enrichment_outcome_mismatches": 0,
        "stage07_enrichment_timing_mismatches": 0,
        "account_level_outputs_published": False,
        "elapsed_seconds": time.monotonic() - started,
    }
    atomic_write_json(staging / "_SUCCESS.json", success)
    os.replace(staging, final)
    zip_path = output_parent / f"a1_evidence_gap_audit_{payload['run_id']}.zip"
    make_public_zip(final, zip_path)
    print(
        "A1_EVIDENCE_GAP_AUDIT_V100_OK "
        f"elapsed={success['elapsed_seconds'] / 60:.1f}m",
        flush=True,
    )
    print(f"public_result_root: {final}", flush=True)
    print(f"public_result_zip: {zip_path}", flush=True)
    print(f"public_result_zip_sha256: {sha256_file(zip_path)}", flush=True)
    return final, zip_path


def self_test(script_path: Path) -> None:
    base = import_base(script_path.parent / "10c_estimate_dynamic_prosociality_core.py")
    _, np, _, _ = base.import_dependencies()
    base.run_numerical_self_test()
    observed = weighted_quantile(
        np.asarray([0.0, 10.0]),
        np.asarray([1.0, 3.0]),
        0.5,
        np,
    )
    if observed != 10.0:
        raise RuntimeError("Weighted-quantile self-test failed")
    ess = effective_sample_size(np.asarray([1.0, 1.0, 1.0]), np)
    if abs(ess - 3.0) > 1e-12:
        raise RuntimeError("ESS self-test failed")
    month_sql = month_future_sql(
        base,
        Path("/tmp/eligible.parquet"),
        Path("/tmp/month.parquet"),
        Path("/tmp/output.parquet"),
    )
    final_sql = final_enrichment_sql(
        base,
        [Path("/tmp/month1.parquet"), Path("/tmp/month2.parquet")],
        Path("/tmp/final.parquet"),
    )
    required = (
        "first_any_same_benefactor",
        "first_nonbenefactor_kind_draw",
        "ROW_NUMBER() OVER",
    )
    if any(token not in month_sql + final_sql for token in required):
        raise RuntimeError("SQL-generation self-test failed")
    print("A1_EVIDENCE_GAP_AUDIT_V100_SELF_TEST_OK")


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    script_path = Path(__file__).resolve()
    if args.self_test:
        self_test(script_path)
        return
    payload = make_plan(args, script_path)
    print_plan(payload)
    if args.execute:
        execute(payload, script_path)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        raise
