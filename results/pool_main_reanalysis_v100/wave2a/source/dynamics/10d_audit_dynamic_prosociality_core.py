#!/usr/bin/env python3
"""Complete the post-outcome audit of Dynamic Prosociality core v1.0.2.

This supplement does not alter or rerun the frozen A1, A3, or B1 primary tests.
It authenticates their public result and private recipient checkpoint, then produces
the previously required pre-trend, fine-matchmaking, and time-to-next-game diagnostics,
plus an exposure-chooser fixed-effect sensitivity. Private rows remain on XT_Pro.
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
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable, Sequence


SCRIPT_VERSION = "1.0.1"
PROJECT_ROOT = Path("/Volumes/XT_Pro/lichess_kindness")
CORE_RUN_ID = "20260822T022146Z"
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
EXPECTED_BASE_PRODUCER_SHA256 = (
    "2dcf0dd19f7cfe8f694d348e6590df88083a37882404112229d6ef05ebc42713"
)
EXPECTED_FROZEN_PLAN_SHA256 = (
    "b11b546ea6fde608140619cffadffad1a7aab054b6fd1a9dcbee8900c98d0a6f"
)
EXPECTED_ARM_AMENDMENT_SHA256 = (
    "db951a0ea42945cbe4ec8a86cf436a839b1821a2225d73442dddb6262e908ec5"
)
EXPECTED_PARALLEL_NOTE_SHA256 = (
    "a2759dead0c1a67cf0e5a3976075389702a4c8900343ff5134cb74e106feea4d"
)
EXPECTED_POSTAUDIT_PLAN_SHA256 = (
    "29eae92125b625d4919b11ebd51b6d80d69a1f487ac402e0018d41764334bbd0"
)
EXPECTED_RECOVERY_NOTE_SHA256 = (
    "d126ac5bd7200142456658dbf86b5b74edc74aa9221f53740932e1de721a3627"
)
EXPECTED_PRIOR_V100_PRODUCER_SHA256 = (
    "4a6888a68826b62c688158c20e9998d6e737c10e19ca8e62ea784505c0cc524a"
)
EXPECTED_PRIOR_V100_RESUME_CONFIG_SHA256 = (
    "cf16f75cf04fb376b612a55f88506517dd4ecaac3f9ba4a3f41ae0aa670935eb"
)

CORE_INDEX_ROWS = 2_556_782
DAY_MS = 24 * 60 * 60 * 1000
HOUR_MS = 60 * 60 * 1000
HORIZON_30D_MS = 30 * DAY_MS
HORIZON_90D_MS = 90 * DAY_MS
FULL_PREHISTORY_START_MS = 1_706_572_800_000  # 2024-01-30T00:00:00Z


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--base-producer", type=Path)
    parser.add_argument("--post-audit-plan", type=Path)
    parser.add_argument("--core-result-root", type=Path)
    parser.add_argument("--core-state-root", type=Path)
    parser.add_argument("--private-state-root", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--memory-limit", default="12GB")
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


def write_csv(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    rows = list(rows)
    if not rows:
        raise RuntimeError(f"Refusing to write empty CSV: {path}")
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)
    temporary = path.with_name(path.name + f".tmp.{uuid.uuid4().hex}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: canonical_json(value)
                    if isinstance(value, (dict, list, tuple))
                    else ""
                    if value is None
                    else value
                    for key, value in row.items()
                }
            )
    os.replace(temporary, path)


def sql_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def import_base(path: Path) -> ModuleType:
    if not path.is_file() or sha256_file(path) != EXPECTED_BASE_PRODUCER_SHA256:
        raise RuntimeError("Authenticated v1.0.2 base producer is unavailable")
    spec = importlib.util.spec_from_file_location("dynamic_core_v102_base", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load v1.0.2 base producer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def authenticate_core_result(base: ModuleType, root: Path) -> dict[str, Any]:
    success = root / "_SUCCESS.json"
    summary_path = root / "summary.json"
    manifest = root / "report_file_hashes.tsv"
    for path in (success, summary_path, manifest):
        if not path.is_file():
            raise RuntimeError(f"Core result authority is missing: {path}")
    if sha256_file(success) != EXPECTED_CORE_SUCCESS_SHA256:
        raise RuntimeError("Core v1.0.2 success SHA-256 mismatch")
    if sha256_file(summary_path) != EXPECTED_CORE_SUMMARY_SHA256:
        raise RuntimeError("Core v1.0.2 summary SHA-256 mismatch")
    if sha256_file(manifest) != EXPECTED_CORE_MANIFEST_SHA256:
        raise RuntimeError("Core v1.0.2 manifest SHA-256 mismatch")
    authenticated = base.authenticate_manifest(root, manifest)
    summary = load_json(summary_path)
    if summary.get("status") != "DYNAMIC_PROSOCIALITY_CORE_V102_RESULTS_READY":
        raise RuntimeError("Core v1.0.2 result status mismatch")
    if summary.get("script_sha256") != EXPECTED_BASE_PRODUCER_SHA256:
        raise RuntimeError("Core result producer authority mismatch")
    if summary.get("analysis_plan_sha256") != EXPECTED_FROZEN_PLAN_SHA256:
        raise RuntimeError("Core result plan authority mismatch")
    return {
        "root": str(root),
        "success_sha256": EXPECTED_CORE_SUCCESS_SHA256,
        "summary_sha256": EXPECTED_CORE_SUMMARY_SHA256,
        "manifest_sha256": EXPECTED_CORE_MANIFEST_SHA256,
        "files_authenticated": authenticated,
        "summary": summary,
    }


def make_base_args(args: argparse.Namespace, package: Path) -> argparse.Namespace:
    return argparse.Namespace(
        project_root=args.project_root,
        analysis_plan=package / "Dynamic_Prosociality_Analysis_Plan_v1_0_1_2026-08-21.md",
        arm_amendment=package / "Dynamic_Prosociality_Arm_Partition_Amendment_v1_0_2_2026-08-22.md",
        stage07_root=None,
        a3_gate_root=None,
        a3_private_cache=None,
        chronology_root=None,
        state_root=args.core_state_root,
        output_root=None,
        run_id=None,
        threads=args.threads,
        chronology_workers=4,
        b1_workers=5,
        memory_limit=args.memory_limit,
        batch_rows=500_000,
        verify_stage07_hashes=args.verify_stage07_hashes,
        execute=False,
        self_test=False,
        integration_self_test=False,
        parallel_self_test=False,
    )


def make_plan(args: argparse.Namespace, script_path: Path) -> dict[str, Any]:
    if args.threads < 1:
        raise RuntimeError("--threads must be at least one")
    project = args.project_root.expanduser().resolve()
    if project != PROJECT_ROOT or not project.is_dir():
        raise RuntimeError(f"XT_Pro project authority is unavailable: {project}")
    package = script_path.parent
    plan_path = (
        args.post_audit_plan.expanduser().resolve()
        if args.post_audit_plan
        else package / "Dynamic_Prosociality_PostOutcome_Audit_Plan_v1_0_0_2026-08-22.md"
    )
    if not plan_path.is_file() or sha256_file(plan_path) != EXPECTED_POSTAUDIT_PLAN_SHA256:
        raise RuntimeError("Post-outcome audit-plan SHA-256 mismatch")
    recovery_note = (
        package
        / "Dynamic_Prosociality_PostAudit_Boolean_Recovery_Note_v1_0_1_2026-08-22.md"
    )
    if (
        not recovery_note.is_file()
        or sha256_file(recovery_note) != EXPECTED_RECOVERY_NOTE_SHA256
    ):
        raise RuntimeError("Post-audit Boolean-recovery note SHA-256 mismatch")
    base_path = (
        args.base_producer.expanduser().resolve()
        if args.base_producer
        else package / "10c_estimate_dynamic_prosociality_core.py"
    )
    base = import_base(base_path)
    base_payload = base.make_plan(make_base_args(args, package), base_path)
    core_result_root = (
        args.core_result_root.expanduser().resolve()
        if args.core_result_root
        else project / "output/dynamic_prosociality_core_v102" / CORE_RUN_ID
    )
    core_result = authenticate_core_result(base, core_result_root)
    core_state_root = Path(base_payload["state_root"])
    recipient = core_state_root / "recipient_with_chronology_private.parquet"
    recipient_receipt = core_state_root / "recipient_with_chronology_receipt.json"
    if not recipient.is_file() or not recipient_receipt.is_file():
        raise RuntimeError("Core private recipient checkpoint is incomplete")
    if sha256_file(recipient) != EXPECTED_PRIVATE_RECIPIENT_SHA256:
        raise RuntimeError("Core private recipient SHA-256 mismatch")
    rr = load_json(recipient_receipt)
    if rr.get("output_sha256") != EXPECTED_PRIVATE_RECIPIENT_SHA256:
        raise RuntimeError("Core private recipient receipt mismatch")
    if int(rr.get("rows", -1)) != CORE_INDEX_ROWS:
        raise RuntimeError("Core private recipient row total mismatch")
    private_state = (
        args.private_state_root.expanduser().resolve()
        if args.private_state_root
        else project
        / "derived/replication/dynamic_prosociality_core_v102_POSTAUDIT_PRIVATE"
    )
    output_root = (
        args.output_root.expanduser().resolve()
        if args.output_root
        else project / "output/dynamic_prosociality_core_v102_postaudit"
    )
    if shutil.disk_usage(project).free < 20 * 1024**3:
        raise RuntimeError("Less than 20 GiB is free on XT_Pro")
    frozen = {
        "postaudit_plan_sha256": EXPECTED_POSTAUDIT_PLAN_SHA256,
        "base_producer_sha256": EXPECTED_BASE_PRODUCER_SHA256,
        "core_success_sha256": EXPECTED_CORE_SUCCESS_SHA256,
        "core_summary_sha256": EXPECTED_CORE_SUMMARY_SHA256,
        "private_recipient_sha256": EXPECTED_PRIVATE_RECIPIENT_SHA256,
        "pretrend_windows_days_before_exposure": [[0, 30], [31, 60], [61, 90]],
        "fine_matchmaking": [
            {
                "name": "supported_200rating_weekday_6hour",
                "rating_width": 200,
                "hour_width": 6,
                "minimum_mercy": 5,
                "minimum_claimed": 20,
            },
            {
                "name": "very_fine_100rating_weekday_4hour",
                "rating_width": 100,
                "hour_width": 4,
                "minimum_mercy": 3,
                "minimum_claimed": 10,
            },
        ],
        "chooser_fe": "exposure chooser + frozen exposure cell + exposure month",
        "a3_time": "30-day RMST; no event censored at 720 hours",
        "primary_results_reopened": False,
    }
    resume_sha = sha256_text(
        canonical_json(
            {
                "script_sha256": sha256_file(script_path),
                "frozen": frozen,
                "git_head": base_payload["git"]["head"],
                "recovery_note_sha256": EXPECTED_RECOVERY_NOTE_SHA256,
            }
        )
    )
    return {
        "status": "DYNAMIC_PROSOCIALITY_POSTOUTCOME_AUDIT_V101_PLAN_OK",
        "created_utc": utc_now(),
        "script_version": SCRIPT_VERSION,
        "script_path": str(script_path),
        "script_sha256": sha256_file(script_path),
        "postaudit_plan_path": str(plan_path),
        "postaudit_plan_sha256": EXPECTED_POSTAUDIT_PLAN_SHA256,
        "recovery_note_path": str(recovery_note),
        "recovery_note_sha256": EXPECTED_RECOVERY_NOTE_SHA256,
        "base_producer_path": str(base_path),
        "base_producer_sha256": EXPECTED_BASE_PRODUCER_SHA256,
        "base": base,
        "base_payload": base_payload,
        "core_result": core_result,
        "recipient_path": str(recipient),
        "recipient_sha256": EXPECTED_PRIVATE_RECIPIENT_SHA256,
        "private_state_root": str(private_state),
        "output_root": str(output_root),
        "run_id": args.run_id or default_run_id(),
        "threads": args.threads,
        "memory_limit": args.memory_limit,
        "frozen": frozen,
        "resume_config_sha256": resume_sha,
    }


def print_plan(payload: dict[str, Any]) -> None:
    print(payload["status"])
    print(f"script_version: {payload['script_version']}")
    print(f"script_sha256: {payload['script_sha256']}")
    print(f"postaudit_plan_sha256: {payload['postaudit_plan_sha256']}")
    print(f"recovery_note_sha256: {payload['recovery_note_sha256']}")
    print(f"core_success_sha256: {payload['core_result']['success_sha256']}")
    print(f"private_recipient_sha256: {payload['recipient_sha256']}")
    print(f"Stage 07 paths: {len(payload['base_payload']['stage07']['paths'])}")
    print(
        "Stage 07 Parquet hashes verified: "
        f"{payload['base_payload']['stage07']['input_hashes_verified']}"
    )
    print(f"private_state_root: {payload['private_state_root']}")
    print(f"output_root: {payload['output_root']}")
    print("primary_results_reopened: False")
    print("Patron/profile inputs read: False")
    print(
        "compatible prior checkpoint config: "
        f"{EXPECTED_PRIOR_V100_RESUME_CONFIG_SHA256}"
    )


def initialize_private_state(payload: dict[str, Any]) -> Path:
    root = Path(payload["private_state_root"])
    config = root / "resume_config.json"
    if root.exists():
        if not config.is_file():
            raise RuntimeError("Post-audit private state exists without resume config")
        saved = load_json(config)
        saved_sha = saved.get("resume_config_sha256")
        compatible = {
            payload["resume_config_sha256"],
            EXPECTED_PRIOR_V100_RESUME_CONFIG_SHA256,
        }
        if saved_sha not in compatible:
            raise RuntimeError("Post-audit private state belongs to another configuration")
        payload["active_state_resume_config_sha256"] = saved_sha
        payload["checkpoint_recovery_mode"] = (
            "native_v101"
            if saved_sha == payload["resume_config_sha256"]
            else "authenticated_v100_checkpoint"
        )
        print(
            "POSTAUDIT_PRIVATE_STATE_AUTHENTICATED_OK "
            f"mode={payload['checkpoint_recovery_mode']}",
            flush=True,
        )
        return root
    root.mkdir(parents=True, exist_ok=False)
    (root / "duckdb_temp").mkdir()
    atomic_write_json(
        config,
        {
            "status": "DYNAMIC_POSTAUDIT_RESUME_CONFIG_OK",
            "created_utc": utc_now(),
            "resume_config_sha256": payload["resume_config_sha256"],
            "raw_account_level_data": "PRIVATE; DO NOT COMMIT OR PUBLISH",
        },
    )
    payload["active_state_resume_config_sha256"] = payload["resume_config_sha256"]
    payload["checkpoint_recovery_mode"] = "native_v101"
    print(f"POSTAUDIT_PRIVATE_STATE_CREATED: {root}", flush=True)
    return root


def build_or_authenticate_pretrend(
    payload: dict[str, Any], state: Path
) -> tuple[Path, dict[str, Any]]:
    base = payload["base"]
    duckdb, _, _, _ = base.import_dependencies()
    output = state / "recipient_pretrend_private.parquet"
    receipt = state / "recipient_pretrend_receipt.json"
    if output.is_file() and receipt.is_file():
        saved = load_json(receipt)
        if saved.get("output_sha256") != sha256_file(output):
            raise RuntimeError("Pretrend checkpoint SHA-256 mismatch")
        active_sha = payload.get(
            "active_state_resume_config_sha256", payload["resume_config_sha256"]
        )
        if saved.get("resume_config_sha256") != active_sha:
            raise RuntimeError("Pretrend checkpoint configuration mismatch")
        print(
            "RECIPIENT_PRETREND_CHECKPOINT_AUTHENTICATED_OK "
            f"mode={payload.get('checkpoint_recovery_mode', 'native_v101')}",
            flush=True,
        )
        return output, saved
    if output.exists() or receipt.exists():
        raise RuntimeError("Incomplete pretrend checkpoint exists")
    if payload.get("checkpoint_recovery_mode") == "authenticated_v100_checkpoint":
        raise RuntimeError(
            "Authenticated v1.0.0 state has no complete pretrend checkpoint; "
            "refusing to mix producer configurations"
        )
    connection = duckdb.connect()
    base.configure_duckdb(
        connection,
        {"threads": payload["threads"], "memory_limit": payload["memory_limit"]},
        state / "duckdb_temp/pretrend",
    )
    recipient = Path(payload["recipient_path"])
    paths = payload["base_payload"]["stage07"]["paths"]
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    query = f"""
      WITH exposure AS (
        SELECT
          cohort_row_id,
          recipient_user_id,
          exposure_anchor_utc_ms
        FROM read_parquet({sql_literal(recipient)})
        WHERE first_ever_pair
          AND arm_eligible
          AND a1_90d_followup_eligible
          AND exposure_anchor_utc_ms >= {FULL_PREHISTORY_START_MS}
      ), panel AS (
        SELECT
          CAST(chooser_user_id AS BIGINT) AS chooser_user_id,
          CAST(api_last_move_at_ms AS BIGINT) AS event_utc_ms,
          CAST(kind_draw AS BOOLEAN) AS kind_draw
        FROM read_parquet({base.path_list_literal(paths)}, union_by_name=true)
        WHERE CAST(fair_competitive AS BOOLEAN)
          AND chooser_user_id IS NOT NULL
          AND api_last_move_at_ms IS NOT NULL
      ), joined AS (
        SELECT
          e.cohort_row_id,
          e.exposure_anchor_utc_ms - p.event_utc_ms AS prior_delta_ms,
          p.event_utc_ms,
          p.kind_draw
        FROM exposure e
        LEFT JOIN panel p
          ON p.chooser_user_id = e.recipient_user_id
         AND p.event_utc_ms < e.exposure_anchor_utc_ms
         AND p.event_utc_ms >= e.exposure_anchor_utc_ms - {HORIZON_90D_MS}
      )
      SELECT
        cohort_row_id,
        TRUE AS pretrend_full_history,
        COUNT(event_utc_ms) FILTER (
          WHERE prior_delta_ms > 0 AND prior_delta_ms <= {30 * DAY_MS}
        )::INTEGER AS pre_opportunities_0_30d,
        COUNT(event_utc_ms) FILTER (
          WHERE prior_delta_ms > {30 * DAY_MS} AND prior_delta_ms <= {60 * DAY_MS}
        )::INTEGER AS pre_opportunities_31_60d,
        COUNT(event_utc_ms) FILTER (
          WHERE prior_delta_ms > {60 * DAY_MS} AND prior_delta_ms <= {90 * DAY_MS}
        )::INTEGER AS pre_opportunities_61_90d,
        COALESCE(BOOL_OR(kind_draw) FILTER (
          WHERE prior_delta_ms > 0 AND prior_delta_ms <= {30 * DAY_MS}
        ), FALSE) AS pre_any_kind_0_30d,
        COALESCE(BOOL_OR(kind_draw) FILTER (
          WHERE prior_delta_ms > {30 * DAY_MS} AND prior_delta_ms <= {60 * DAY_MS}
        ), FALSE) AS pre_any_kind_31_60d,
        COALESCE(BOOL_OR(kind_draw) FILTER (
          WHERE prior_delta_ms > {60 * DAY_MS} AND prior_delta_ms <= {90 * DAY_MS}
        ), FALSE) AS pre_any_kind_61_90d,
        ARG_MAX(kind_draw, event_utc_ms) FILTER (
          WHERE prior_delta_ms > 0 AND prior_delta_ms <= {30 * DAY_MS}
        ) AS pre_last_kind_0_30d,
        ARG_MAX(kind_draw, event_utc_ms) FILTER (
          WHERE prior_delta_ms > {30 * DAY_MS} AND prior_delta_ms <= {60 * DAY_MS}
        ) AS pre_last_kind_31_60d,
        ARG_MAX(kind_draw, event_utc_ms) FILTER (
          WHERE prior_delta_ms > {60 * DAY_MS} AND prior_delta_ms <= {90 * DAY_MS}
        ) AS pre_last_kind_61_90d
      FROM joined
      GROUP BY cohort_row_id
      ORDER BY cohort_row_id
    """
    print("RECIPIENT_PRETREND_BUILD_BEGIN", flush=True)
    connection.execute(
        f"COPY ({query}) TO {sql_literal(temporary)} "
        "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)"
    )
    qa = connection.execute(
        f"""
        SELECT
          COUNT(*)::BIGINT,
          COUNT(DISTINCT cohort_row_id)::BIGINT,
          MIN(cohort_row_id)::BIGINT,
          MAX(cohort_row_id)::BIGINT,
          SUM(CAST(pretrend_full_history AS BIGINT))::BIGINT
        FROM read_parquet({sql_literal(temporary)})
        """
    ).fetchone()
    connection.close()
    if qa[0] <= 100_000 or qa[0] != qa[1] or qa[0] != qa[4]:
        raise RuntimeError(f"Pretrend checkpoint QA failed: {qa}")
    os.replace(temporary, output)
    saved = {
        "status": "DYNAMIC_RECIPIENT_PRETREND_PRIVATE_OK",
        "created_utc": utc_now(),
        "resume_config_sha256": payload["resume_config_sha256"],
        "rows": int(qa[0]),
        "minimum_cohort_row_id": int(qa[2]),
        "maximum_cohort_row_id": int(qa[3]),
        "output_sha256": sha256_file(output),
        "output_bytes": output.stat().st_size,
        "raw_account_level_data": "PRIVATE; DO NOT COMMIT OR PUBLISH",
    }
    atomic_write_json(receipt, saved)
    print(f"RECIPIENT_PRETREND_BUILD_OK rows={qa[0]:,}", flush=True)
    return output, saved


def nullable_float(column: Any, np: Any, pa: Any) -> Any:
    import pyarrow.compute as pc  # type: ignore

    column = column.combine_chunks()
    column = pc.cast(column, pa.float64(), safe=True)
    column = pc.fill_null(column, pa.scalar(float("nan"), type=pa.float64()))
    return np.asarray(column.to_numpy(zero_copy_only=False), dtype=np.float64)


def load_analysis_data(
    payload: dict[str, Any], pretrend_path: Path
) -> dict[str, Any]:
    base = payload["base"]
    _, np, pa, pq = base.import_dependencies()
    recipient = Path(payload["recipient_path"])
    data = base.load_recipient_arrays(recipient)
    extra = pq.read_table(
        recipient,
        columns=["exposure_anchor_utc_ms", "next_game_delta_ms"],
        use_threads=True,
    )
    data["exposure_anchor_utc_ms"] = np.asarray(
        extra["exposure_anchor_utc_ms"].combine_chunks().to_numpy(), dtype=np.int64
    )
    data["next_game_delta_ms"] = nullable_float(extra["next_game_delta_ms"], np, pa)
    pre = pq.read_table(pretrend_path, use_threads=True)
    ids = np.asarray(pre["cohort_row_id"].combine_chunks().to_numpy(), dtype=np.int64)
    if ids.size == 0 or np.any(ids[1:] <= ids[:-1]) or ids.min() < 0 or ids.max() >= CORE_INDEX_ROWS:
        raise RuntimeError("Pretrend checkpoint cohort ordering is invalid")
    data["pretrend_full_history"] = np.zeros(CORE_INDEX_ROWS, dtype=bool)
    data["pretrend_full_history"][ids] = True
    for name in (
        "pre_opportunities_0_30d",
        "pre_opportunities_31_60d",
        "pre_opportunities_61_90d",
    ):
        array = np.zeros(CORE_INDEX_ROWS, dtype=np.float64)
        array[ids] = np.asarray(
            pre[name].combine_chunks().to_numpy(zero_copy_only=False),
            dtype=np.float64,
        )
        data[name] = array
    for name in (
        "pre_any_kind_0_30d",
        "pre_any_kind_31_60d",
        "pre_any_kind_61_90d",
    ):
        array = np.zeros(CORE_INDEX_ROWS, dtype=np.float64)
        array[ids] = np.asarray(
            pre[name].combine_chunks().to_numpy(zero_copy_only=False),
            dtype=np.float64,
        )
        data[name] = array
    for name in (
        "pre_last_kind_0_30d",
        "pre_last_kind_31_60d",
        "pre_last_kind_61_90d",
    ):
        array = np.full(CORE_INDEX_ROWS, np.nan, dtype=np.float64)
        array[ids] = nullable_float(pre[name], np, pa)
        data[name] = array
    return data


def estimate_pretrends(
    payload: dict[str, Any], data: dict[str, Any], support: dict[str, Any]
) -> list[dict[str, Any]]:
    base = payload["base"]
    _, np, _, _ = base.import_dependencies()
    sample = (
        data["first_ever_pair"].astype(bool)
        & data["arm_eligible"].astype(bool)
        & data["a1_90d_followup_eligible"].astype(bool)
        & data["pretrend_full_history"].astype(bool)
    )
    rows: list[dict[str, Any]] = []
    for suffix in ("61_90d", "31_60d", "0_30d"):
        opportunity = f"pre_opportunities_{suffix}"
        has_name = f"pre_has_opportunity_{suffix}"
        data[has_name] = (data[opportunity] > 0).astype(np.float64)
        rows.append(
            base.fit_recipient_outcome(
                data=data,
                support=support,
                outcome_name=has_name,
                sample=sample,
                estimand=f"postoutcome_placebo_prior_opportunity_{suffix}",
                state_conditioned=False,
                binary_outcome=True,
            )
        )
        rows.append(
            base.fit_recipient_outcome(
                data=data,
                support=support,
                outcome_name=f"pre_any_kind_{suffix}",
                sample=sample,
                estimand=f"postoutcome_placebo_prior_any_kind_{suffix}",
                state_conditioned=False,
                binary_outcome=True,
            )
        )
        rows.append(
            base.fit_recipient_outcome(
                data=data,
                support=support,
                outcome_name=f"pre_last_kind_{suffix}",
                sample=sample & (data[opportunity] > 0),
                estimand=f"postoutcome_placebo_prior_last_choice_{suffix}",
                state_conditioned=False,
                binary_outcome=True,
            )
        )
    for row in rows:
        row["postoutcome_secondary"] = True
        row["future_treatment_placebo"] = True
    adjusted = base.holm_adjust([float(row["p_value_raw"]) for row in rows])
    for row, value in zip(rows, adjusted, strict=True):
        row["p_value_holm_within_pretrend_family"] = value
        row["primary_holm_family_reopened"] = False
    return rows


def fine_support(
    payload: dict[str, Any],
    data: dict[str, Any],
    base_support: dict[str, Any],
    specification: dict[str, Any],
) -> dict[str, Any]:
    _, np, _, _ = payload["base"].import_dependencies()
    treatment = data["received_mercy"].astype(bool)
    first = data["first_ever_pair"].astype(bool) & data["arm_eligible"].astype(bool)
    valid = first & base_support["eligible"]
    rating_width = int(specification["rating_width"])
    hour_width = int(specification["hour_width"])
    rating_mean = (data["exposure_chooser_elo"] + data["exposure_recipient_elo"]) / 2.0
    valid &= np.isfinite(rating_mean)
    rating_band = np.zeros(treatment.size, dtype=np.int64)
    rating_band[valid] = np.floor(rating_mean[valid] / rating_width).astype(np.int64)
    anchor = data["exposure_anchor_utc_ms"].astype(np.int64)
    valid &= anchor > 0
    utc_day = anchor // DAY_MS
    weekday = (utc_day + 3) % 7
    hour = (anchor // HOUR_MS) % 24
    daypart = hour // hour_width
    dayparts = 24 // hour_width
    speed = data["exposure_speed_code"].astype(np.int64)
    valid &= (speed >= 0) & (speed <= 5)
    raw_key = (
        ((rating_band * 6 + speed) * 7 + weekday) * dayparts + daypart
    )
    codes = np.full(treatment.size, -1, dtype=np.int64)
    _, codes[valid] = np.unique(raw_key[valid], return_inverse=True)
    groups = int(codes[valid].max()) + 1
    treated_counts = np.bincount(codes[valid & treatment], minlength=groups)
    control_counts = np.bincount(codes[valid & ~treatment], minlength=groups)
    eligible_groups = (
        (treated_counts >= int(specification["minimum_mercy"]))
        & (control_counts >= int(specification["minimum_claimed"]))
    )
    eligible = np.zeros(treatment.size, dtype=bool)
    eligible[valid] = eligible_groups[codes[valid]]
    weights = np.zeros(treatment.size, dtype=np.float64)
    weights[eligible & treatment] = 1.0
    control = eligible & ~treatment
    weights[control] = treated_counts[codes[control]] / control_counts[codes[control]]
    base_treated = int(np.count_nonzero(valid & treatment))
    retained_treated = int(np.count_nonzero(eligible & treatment))
    return {
        "name": specification["name"],
        "eligible": eligible,
        "weights": weights,
        "eligible_cells": int(np.count_nonzero(eligible_groups)),
        "rating_width": rating_width,
        "hour_width": hour_width,
        "minimum_mercy": int(specification["minimum_mercy"]),
        "minimum_claimed": int(specification["minimum_claimed"]),
        "base_rows": int(np.count_nonzero(valid)),
        "retained_rows": int(np.count_nonzero(eligible)),
        "base_mercy": base_treated,
        "retained_mercy": retained_treated,
        "retained_claimed": int(np.count_nonzero(eligible & ~treatment)),
        "mercy_retention_share": retained_treated / base_treated,
    }


def fit_with_custom_support(
    payload: dict[str, Any],
    data: dict[str, Any],
    support: dict[str, Any],
    *,
    outcome_name: str,
    sample: Any,
    estimand: str,
    binary: bool,
) -> dict[str, Any]:
    base = payload["base"]
    _, np, _, _ = base.import_dependencies()
    outcome = np.asarray(data[outcome_name], dtype=np.float64)
    selected = np.asarray(sample, dtype=bool) & support["eligible"] & np.isfinite(outcome)
    indices = np.flatnonzero(selected)
    controls, names = base.model_controls(data, indices, state_conditioned=False)
    specification = {
        "analysis": "postoutcome_fine_matchmaking_sensitivity",
        "outcome": outcome_name,
        "estimand": estimand,
        "postoutcome_secondary": True,
        "matchmaking_design": support["name"],
        "rating_width": support["rating_width"],
        "hour_width": support["hour_width"],
        "minimum_mercy": support["minimum_mercy"],
        "minimum_claimed": support["minimum_claimed"],
        "eligible_matchmaking_cells": support["eligible_cells"],
        "matchmaking_mercy_retention_share": support["mercy_retention_share"],
        "fixed_effects": "frozen exposure cell and exposure month",
        "cluster": "exposure chooser",
        "standardization": "ATT-style fine-matchmaking-cell weights",
    }
    return base.fit_weighted_cluster_model(
        outcome=outcome[indices],
        treatment=data["received_mercy"][indices],
        controls=controls,
        control_names=names,
        weights=support["weights"][indices],
        cell_fe=data["exposure_cell_code"][indices],
        month_fe=data["exposure_month_code"][indices],
        clusters=data["exposure_chooser_user_id"][indices],
        row_ids=data["cohort_row_id"][indices],
        specification=specification,
        binary_outcome=binary,
    )


def estimate_fine_matchmaking(
    payload: dict[str, Any], data: dict[str, Any], base_support: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    _, np, _, _ = payload["base"].import_dependencies()
    first = data["first_ever_pair"].astype(bool) & data["arm_eligible"].astype(bool)
    conditional = (
        first
        & data["a1_90d_followup_eligible"].astype(bool)
        & data["reached_fair_chooser_within_90d"].astype(bool)
    )
    rows: list[dict[str, Any]] = []
    supports: list[dict[str, Any]] = []
    for spec in payload["frozen"]["fine_matchmaking"]:
        support = fine_support(payload, data, base_support, spec)
        supports.append({key: value for key, value in support.items() if key not in {"eligible", "weights"}})
        rows.append(
            fit_with_custom_support(
                payload,
                data,
                support,
                outcome_name="first_subsequent_kind_draw",
                sample=conditional,
                estimand=f"A1_total_path_{spec['name']}",
                binary=True,
            )
        )
        rows.append(
            fit_with_custom_support(
                payload,
                data,
                support,
                outcome_name="log1p_games_within_30d",
                sample=first,
                estimand=f"A3_log1p_30d_{spec['name']}",
                binary=False,
            )
        )
    return rows, supports


def fit_multi_fe(
    payload: dict[str, Any],
    *,
    outcome: Any,
    treatment: Any,
    controls: Any,
    control_names: Sequence[str],
    weights: Any,
    fixed_effects: Sequence[Any],
    clusters: Any,
    row_ids: Any,
    specification: dict[str, Any],
) -> dict[str, Any]:
    base = payload["base"]
    _, np, _, _ = base.import_dependencies()
    y = np.asarray(outcome, dtype=np.float64)
    d = np.asarray(treatment, dtype=np.float64)
    x = np.column_stack([d, controls])
    transformed, iterations, last = base.weighted_absorb(
        np.column_stack([y, x]), weights, fixed_effects, tolerance=1e-9
    )
    yr = transformed[:, 0]
    xr = transformed[:, 1:]
    wx = xr * np.sqrt(weights)[:, None]
    wy = yr * np.sqrt(weights)
    # Keep treatment first, then retain controls in their frozen order only when
    # they add numerical rank. This makes the treatment coefficient invariant to
    # constant or absorbed control columns while recording every dropped column.
    gram_all = wx.T @ wx
    gram_scale = max(float(np.max(np.diag(gram_all))), 1.0)
    rank_tolerance = max(wx.shape) * np.finfo(np.float64).eps * gram_scale
    selected_columns = [0]
    if np.linalg.matrix_rank(gram_all[np.ix_([0], [0])], tol=rank_tolerance) != 1:
        raise RuntimeError("Treatment has no identifying variation after absorption")
    current_rank = 1
    for column in range(1, wx.shape[1]):
        candidate = [*selected_columns, column]
        candidate_rank = int(
            np.linalg.matrix_rank(
                gram_all[np.ix_(candidate, candidate)], tol=rank_tolerance
            )
        )
        if candidate_rank > current_rank:
            selected_columns.append(column)
            current_rank = candidate_rank
    dropped_control_indices = [
        column - 1
        for column in range(1, wx.shape[1])
        if column not in selected_columns
    ]
    retained_control_indices = [column - 1 for column in selected_columns[1:]]
    xr_fit = xr[:, selected_columns]
    wx_fit = wx[:, selected_columns]
    beta, _, rank, singular = np.linalg.lstsq(wx_fit, wy, rcond=None)
    if int(rank) != wx_fit.shape[1]:
        raise RuntimeError(
            f"Chooser-FE identified matrix is rank deficient: {rank}/{wx_fit.shape[1]}"
        )
    residual = yr - xr_fit @ beta
    gram = wx_fit.T @ wx_fit
    bread = np.linalg.inv(gram)
    _, cluster_codes = np.unique(np.asarray(clusters), return_inverse=True)
    groups = int(cluster_codes.max()) + 1
    scores = np.empty((groups, xr_fit.shape[1]), dtype=np.float64)
    score_weight = weights * residual
    for column in range(xr_fit.shape[1]):
        scores[:, column] = np.bincount(
            cluster_codes,
            weights=score_weight * xr_fit[:, column],
            minlength=groups,
        )
    correction = 1.0
    if groups > 1 and y.size > int(rank):
        correction = (groups / (groups - 1)) * ((y.size - 1) / (y.size - rank))
    variance = bread @ (scores.T @ scores) @ bread * correction
    se = float(np.sqrt(max(float(variance[0, 0]), 0.0)))
    coefficient = float(beta[0])
    t_value = coefficient / se if se > 0 else math.nan
    treated = d > 0.5
    return {
        **specification,
        "rows": int(y.size),
        "clusters": groups,
        "treated_rows": int(np.count_nonzero(treated)),
        "control_rows": int(np.count_nonzero(~treated)),
        "coefficient": coefficient,
        "standard_error": se,
        "t_value": t_value,
        "p_value_raw": base.normal_two_sided_p(t_value),
        "weighted_treated_mean": float(np.average(y[treated], weights=weights[treated])),
        "weighted_control_mean": float(np.average(y[~treated], weights=weights[~treated])),
        "effect_relative_to_control_mean": (
            coefficient / float(np.average(y[~treated], weights=weights[~treated]))
            if abs(float(np.average(y[~treated], weights=weights[~treated]))) > 1e-15
            else None
        ),
        "coefficient_percentage_points": coefficient * 100,
        "standard_error_percentage_points": se * 100,
        "matrix_rank": int(rank),
        "smallest_singular_value": float(singular[-1]),
        "weighted_design_condition_number": float(np.linalg.cond(gram)),
        "rank_tolerance": rank_tolerance,
        "absorption_iterations": iterations,
        "absorption_last_adjustment": last,
        "cluster_correction": correction,
        "sample_specification_sha256": base.sample_fingerprint(row_ids, specification),
        "control_count_requested": len(control_names),
        "control_count_retained": len(retained_control_indices),
        "control_names": [control_names[index] for index in retained_control_indices],
        "dropped_collinear_controls": [
            control_names[index] for index in dropped_control_indices
        ],
    }


def estimate_chooser_fe(
    payload: dict[str, Any], data: dict[str, Any], support: dict[str, Any]
) -> dict[str, Any]:
    base = payload["base"]
    _, np, _, _ = base.import_dependencies()
    outcome = np.asarray(data["first_subsequent_kind_draw"], dtype=np.float64)
    treatment = data["received_mercy"].astype(bool)
    sample = (
        data["first_ever_pair"].astype(bool)
        & data["arm_eligible"].astype(bool)
        & data["a1_90d_followup_eligible"].astype(bool)
        & data["reached_fair_chooser_within_90d"].astype(bool)
        & support["eligible"]
        & np.isfinite(outcome)
    )
    chooser = data["exposure_chooser_user_id"].astype(np.int64)
    candidate = np.flatnonzero(sample)
    _, code = np.unique(chooser[candidate], return_inverse=True)
    groups = int(code.max()) + 1
    treated_count = np.bincount(code, weights=treatment[candidate], minlength=groups)
    control_count = np.bincount(code, weights=~treatment[candidate], minlength=groups)
    varying = (treated_count > 0) & (control_count > 0)
    selected = candidate[varying[code]]
    controls, names = base.model_controls(data, selected, state_conditioned=False)
    specification = {
        "analysis": "postoutcome_exposure_chooser_fe_sensitivity",
        "outcome": "first_subsequent_kind_draw",
        "estimand": "A1_total_path_with_exposure_chooser_FE",
        "postoutcome_secondary": True,
        "fixed_effects": "exposure chooser, frozen exposure cell, exposure month",
        "cluster": "exposure chooser",
        "standardization": "frozen ATT exposure-cell weights",
        "support": "exposure chooser has both mercy and claim in conditional-choice sample",
        "varying_exposure_choosers": int(np.count_nonzero(varying)),
    }
    return fit_multi_fe(
        payload,
        outcome=outcome[selected],
        treatment=treatment[selected],
        controls=controls,
        control_names=names,
        weights=support["weights"][selected],
        fixed_effects=(
            data["exposure_cell_code"][selected],
            data["exposure_month_code"][selected],
            chooser[selected],
        ),
        clusters=chooser[selected],
        row_ids=data["cohort_row_id"][selected],
        specification=specification,
    )


def weighted_quantile(values: Any, weights: Any, q: float, np: Any) -> float:
    values = np.asarray(values, dtype=np.float64)
    weights = np.asarray(weights, dtype=np.float64)
    valid = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    order = np.argsort(values[valid], kind="mergesort")
    x = values[valid][order]
    w = weights[valid][order]
    cutoff = q * float(np.sum(w))
    return float(x[min(int(np.searchsorted(np.cumsum(w), cutoff, side="left")), x.size - 1)])


def estimate_a3_time(
    payload: dict[str, Any], data: dict[str, Any], support: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    base = payload["base"]
    _, np, _, _ = base.import_dependencies()
    delta = np.asarray(data["next_game_delta_ms"], dtype=np.float64)
    event = np.isfinite(delta) & (delta > 0) & (delta <= HORIZON_30D_MS)
    any30 = data["any_game_within_30d"].astype(bool)
    if not np.array_equal(event, any30):
        mismatch = int(np.count_nonzero(event != any30))
        raise RuntimeError(
            f"Time-to-next event disagrees with certified 30-day indicator: {mismatch}"
        )
    rmst = np.full(delta.size, HORIZON_30D_MS / HOUR_MS, dtype=np.float64)
    rmst[event] = delta[event] / HOUR_MS
    data["rmst_time_to_next_game_30d_hours"] = rmst
    first = data["first_ever_pair"].astype(bool) & data["arm_eligible"].astype(bool)
    model = base.fit_recipient_outcome(
        data=data,
        support=support,
        outcome_name="rmst_time_to_next_game_30d_hours",
        sample=first,
        estimand="postoutcome_secondary_RMST_30d_hours",
        state_conditioned=False,
        binary_outcome=False,
    )
    model["postoutcome_secondary"] = True
    model["analysis"] = "postoutcome_A3_time_to_next_game"
    model["censoring_rule"] = "no rated-standard game by 30d censored at 720 hours"
    selected = first & support["eligible"]
    treatment = data["received_mercy"].astype(bool)
    w = support["weights"]
    arm_rows: list[dict[str, Any]] = []
    for label, arm in (("mercy", treatment), ("claimed", ~treatment)):
        mask = selected & arm
        arm_rows.append(
            {
                "arm": label,
                "rows": int(np.count_nonzero(mask)),
                "events_by_30d": int(np.count_nonzero(mask & event)),
                "censored_at_30d": int(np.count_nonzero(mask & ~event)),
                "weighted_event_rate_30d": float(np.average(any30[mask], weights=w[mask])),
                "weighted_rmst_hours": float(np.average(rmst[mask], weights=w[mask])),
                "weighted_median_time_hours": weighted_quantile(rmst[mask], w[mask], 0.5, np),
            }
        )
    gate = {
        "diagnostic": "final_first_pair_common_support_pooled_30d_rate",
        "postoutcome_secondary": True,
        "cannot_reopen_arm_blind_gate": True,
        "rows": int(np.count_nonzero(selected)),
        "unweighted_pooled_rate_30d": float(np.mean(any30[selected])),
        "att_weighted_pooled_rate_30d": float(np.average(any30[selected], weights=w[selected])),
        "original_arm_blind_full_cohort_rate_30d": float(
            payload["base_payload"]["a3_gate"]["pooled_rate_30d"]
        ),
        "original_selected_primary": payload["base_payload"]["a3_gate"][
            "a3_primary_outcome_selected"
        ],
    }
    return model, {"arms": arm_rows, "gate": gate}


def report_manifest(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name in {"_SUCCESS.json", "report_file_hashes.tsv"}:
            continue
        rows.append(
            {
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
                "path": str(path.relative_to(root)),
            }
        )
    return rows


def execute(payload: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    base = payload["base"]
    started = time.time()
    state = initialize_private_state(payload)
    pretrend_path, pretrend_receipt = build_or_authenticate_pretrend(payload, state)
    print("POSTAUDIT_RECIPIENT_DATA_LOAD_BEGIN", flush=True)
    data = load_analysis_data(payload, pretrend_path)
    support = base.common_support_weights(data)
    expected_support = payload["core_result"]["summary"]["common_support"]
    for key in (
        "eligible_cells",
        "recipient_index_rows",
        "recipient_arm_eligible_rows",
        "recipient_arm_ineligible_rows",
        "first_pair_rows",
        "first_pair_mercy",
        "first_pair_claimed",
        "retained_rows",
        "retained_mercy",
        "retained_claimed",
    ):
        if support[key] != expected_support[key]:
            raise RuntimeError(f"Core common-support reproduction failed: {key}")
    print("POSTAUDIT_CORE_COMMON_SUPPORT_REPRODUCED_OK", flush=True)
    print("POSTAUDIT_PRETREND_ESTIMATION_BEGIN", flush=True)
    pretrend = estimate_pretrends(payload, data, support)
    print("POSTAUDIT_FINE_MATCHMAKING_ESTIMATION_BEGIN", flush=True)
    fine, fine_support_rows = estimate_fine_matchmaking(payload, data, support)
    print("POSTAUDIT_CHOOSER_FE_ESTIMATION_BEGIN", flush=True)
    chooser_fe = estimate_chooser_fe(payload, data, support)
    print("POSTAUDIT_A3_TIME_ESTIMATION_BEGIN", flush=True)
    a3_time, a3_descriptive = estimate_a3_time(payload, data, support)
    run_id = payload["run_id"]
    output_base = Path(payload["output_root"])
    output_base.mkdir(parents=True, exist_ok=True)
    final = output_base / run_id
    if final.exists():
        raise RuntimeError(f"Post-audit output already exists: {final}")
    temporary = output_base / f".{run_id}.tmp.{uuid.uuid4().hex}"
    (temporary / "results").mkdir(parents=True)
    (temporary / "receipts").mkdir()
    write_csv(temporary / "results/pretrend_placebos.csv", pretrend)
    write_csv(temporary / "results/fine_matchmaking_sensitivities.csv", fine)
    write_csv(temporary / "results/fine_matchmaking_support.csv", fine_support_rows)
    write_csv(temporary / "results/exposure_chooser_fe_sensitivity.csv", [chooser_fe])
    write_csv(temporary / "results/a3_time_to_next_game.csv", [a3_time])
    write_csv(temporary / "results/a3_time_to_next_game_arms.csv", a3_descriptive["arms"])
    write_csv(temporary / "results/a3_final_sample_gate_diagnostic.csv", [a3_descriptive["gate"]])
    authorities = {
        "core_success_sha256": EXPECTED_CORE_SUCCESS_SHA256,
        "core_summary_sha256": EXPECTED_CORE_SUMMARY_SHA256,
        "core_manifest_sha256": EXPECTED_CORE_MANIFEST_SHA256,
        "private_recipient_sha256": EXPECTED_PRIVATE_RECIPIENT_SHA256,
        "base_producer_sha256": EXPECTED_BASE_PRODUCER_SHA256,
        "frozen_analysis_plan_sha256": EXPECTED_FROZEN_PLAN_SHA256,
        "arm_amendment_sha256": EXPECTED_ARM_AMENDMENT_SHA256,
        "parallel_note_sha256": EXPECTED_PARALLEL_NOTE_SHA256,
        "postaudit_plan_sha256": EXPECTED_POSTAUDIT_PLAN_SHA256,
        "recovery_note_sha256": EXPECTED_RECOVERY_NOTE_SHA256,
        "prior_v100_producer_sha256": EXPECTED_PRIOR_V100_PRODUCER_SHA256,
        "prior_v100_resume_config_sha256": EXPECTED_PRIOR_V100_RESUME_CONFIG_SHA256,
        "stage07_success_sha256": base.EXPECTED_STAGE07_SUCCESS_SHA256,
        "git_head": payload["base_payload"]["git"]["head"],
    }
    atomic_write_json(temporary / "receipts/input_authorities.json", authorities)
    summary = {
        "status": "DYNAMIC_PROSOCIALITY_POSTOUTCOME_AUDIT_V101_RESULTS_READY",
        "created_utc": utc_now(),
        "run_id": run_id,
        "script_version": SCRIPT_VERSION,
        "script_sha256": payload["script_sha256"],
        "postaudit_plan_sha256": EXPECTED_POSTAUDIT_PLAN_SHA256,
        "postoutcome_secondary_only": True,
        "primary_results_reopened": False,
        "checkpoint_recovery_mode": payload.get(
            "checkpoint_recovery_mode", "native_v101"
        ),
        "core_authorities": authorities,
        "private_pretrend_receipt": {
            key: value
            for key, value in pretrend_receipt.items()
            if key not in {"output_path"}
        },
        "pretrend_placebos": pretrend,
        "fine_matchmaking_sensitivities": fine,
        "fine_matchmaking_support": fine_support_rows,
        "exposure_chooser_fe_sensitivity": chooser_fe,
        "a3_time_to_next_game": a3_time,
        "a3_time_to_next_game_arms": a3_descriptive["arms"],
        "a3_final_sample_gate_diagnostic": a3_descriptive["gate"],
        "runtime_seconds": time.time() - started,
        "privacy": "Aggregate results only; private recipient/pretrend rows remain on XT_Pro.",
    }
    atomic_write_json(temporary / "summary.json", summary)
    manifest_rows = report_manifest(temporary)
    with (temporary / "report_file_hashes.tsv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["sha256", "bytes", "path"],
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(manifest_rows)
    success = {
        **summary,
        "status": "DYNAMIC_PROSOCIALITY_POSTOUTCOME_AUDIT_V101_OK",
        "summary_sha256": sha256_file(temporary / "summary.json"),
        "report_manifest_sha256": sha256_file(temporary / "report_file_hashes.tsv"),
        "report_files_hashed": len(manifest_rows),
    }
    atomic_write_json(temporary / "_SUCCESS.json", success)
    os.replace(temporary, final)
    print(f"DYNAMIC_PROSOCIALITY_POSTOUTCOME_AUDIT_V101_OK: {final}", flush=True)
    return final, success


def self_test(payload: dict[str, Any]) -> None:
    base = payload["base"]
    _, np, _, _ = base.import_dependencies()
    values = np.asarray([1.0, 2.0, 3.0, 4.0])
    weights = np.asarray([1.0, 1.0, 1.0, 7.0])
    if weighted_quantile(values, weights, 0.5, np) != 4.0:
        raise RuntimeError("Weighted-quantile self-test failed")
    treatment = np.asarray([0, 1, 0, 1, 0, 1, 0, 1], dtype=float)
    chooser = np.asarray([0, 0, 1, 1, 2, 2, 3, 3])
    cell = np.asarray([0, 0, 0, 0, 1, 1, 1, 1])
    month = np.asarray([0, 0, 1, 1, 0, 0, 1, 1])
    outcome = 0.37 * treatment + chooser * 0.2 + cell * 0.1 - month * 0.05
    result = fit_multi_fe(
        payload,
        outcome=outcome,
        treatment=treatment,
        controls=np.empty((8, 0)),
        control_names=[],
        weights=np.ones(8),
        fixed_effects=(cell, month, chooser),
        clusters=chooser,
        row_ids=np.arange(8),
        specification={"analysis": "synthetic"},
    )
    if abs(result["coefficient"] - 0.37) > 1e-10:
        raise RuntimeError("Multi-FE self-test failed")
    print("DYNAMIC_PROSOCIALITY_POSTOUTCOME_AUDIT_SELF_TEST_OK")


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    script_path = Path(__file__).resolve()
    payload = make_plan(args, script_path)
    if args.self_test:
        self_test(payload)
        return
    print_plan(payload)
    if not args.execute:
        print("No files were written. Re-run with --execute.")
        return
    final, success = execute(payload)
    print("\nPOST-OUTCOME AUDIT SUMMARY")
    print(f"status: {success['status']}")
    print(f"result: {final}")
    print("primary results reopened: False")
    print("Patron/profile inputs read: False")


if __name__ == "__main__":
    main()
