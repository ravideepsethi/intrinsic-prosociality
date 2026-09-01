#!/usr/bin/env python3
"""Estimate the frozen A1, A3, and B1 dynamic-prosociality analyses.

This producer is the first arm-unblinded dynamic analysis.  It authenticates the
frozen v1.0.1 plan, its dated v1.0.2 arm-partition amendment, certified Stage 07
panel, completed arm-blind A3 chronology gate, and its private all-game activity
cache before reading mercy receipt.  It
then builds a private recipient panel, reconstructs first-pair and pre-activity
history from the canonical chronology with parallel file-level checkpoints,
estimates the frozen A1/A3 ATT-standardized models, and runs the five frozen exact
conditional-Bernoulli B1 randomization batches in independent processes.

Large and account-level files remain private on XT_Pro.  Only aggregate results,
receipts, schemas, and hashes are written to the public-result directory.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import datetime as dt
import hashlib
import json
import math
import multiprocessing
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Iterable, Sequence


SCRIPT_VERSION = "1.0.2"
PROJECT_AUTHORITY = Path("/Volumes/XT_Pro/lichess_kindness")

EXPECTED_GIT_HEAD = "7fa2cf415b43c69f4d8d5fc973442d81dbb6ecbf"
EXPECTED_PLAN_SHA256 = (
    "b11b546ea6fde608140619cffadffad1a7aab054b6fd1a9dcbee8900c98d0a6f"
)
EXPECTED_ARM_AMENDMENT_SHA256 = (
    "db951a0ea42945cbe4ec8a86cf436a839b1821a2225d73442dddb6262e908ec5"
)
EXPECTED_EXECUTION_NOTE_SHA256 = (
    "a2759dead0c1a67cf0e5a3976075389702a4c8900343ff5134cb74e106feea4d"
)
EXPECTED_STAGE07_STATUS = "STAGE07_24M_CERTIFIED_OK"
EXPECTED_STAGE07_ROWS = 47_587_020
EXPECTED_STAGE07_KIND_DRAWS = 669_503
EXPECTED_STAGE07_FAIR_ROWS = 17_328_130
EXPECTED_STAGE07_SUCCESS_SHA256 = (
    "8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7"
)
EXPECTED_STAGE07_SCRIPT_SHA256 = (
    "0411d4061ea9831c20449208a9782aaf668e160139918d106a2b7d63aaa56e6e"
)

EXPECTED_A3_GATE_RUN_ID = "20260821T234626Z"
EXPECTED_A3_GATE_STATUS = "A3_CHRONOLOGY_POOLED_FEASIBILITY_GATE_OK"
EXPECTED_A3_GATE_SCRIPT_SHA256 = (
    "156bfe3f4256a428ea3a00fcc42a6544b51d6048379b1e2875c8e71f31cd8f14"
)
EXPECTED_A3_GATE_SUCCESS_SHA256 = (
    "bb6592a31fae8af34a6537e843386d6e5423ea31338be4d1bb4a78b0808e7b4f"
)
EXPECTED_A3_GATE_ZIP_SHA256 = (
    "995da49926bcb583a6b0b0e18f3ae087b3ac2fcb2973c0c60080e70c97b1bb56"
)
EXPECTED_A3_PRIVATE_SHA256 = (
    "4206745c181aebae5dea034e4670cdb5eeb85e1b7fff3b1743cbe8a04d05c06b"
)
EXPECTED_A3_PRIVATE_ROWS = 2_556_782
EXPECTED_RECIPIENT_MERCY = 78_936
EXPECTED_RECIPIENT_CLAIMED = 2_473_779
EXPECTED_RECIPIENT_NONARM = 4_067
EXPECTED_RECIPIENT_ARM_ELIGIBLE = (
    EXPECTED_RECIPIENT_MERCY + EXPECTED_RECIPIENT_CLAIMED
)
EXPECTED_A3_PRIMARY = "log1p_rated_standard_games_within_30d"
EXPECTED_CHRONOLOGY_MANIFEST_SHA256 = (
    "1d4648bb17cafd9e58c14ab78d32abe855f0bc62a6fb75ac88e02494a73337cd"
)
EXPECTED_CHRONOLOGY_FOOTER_PLAN_SHA256 = (
    "355c48f2a9be94f647e8d1383030aed0d598afd000974fa887800ad2d066f860"
)
EXPECTED_CHRONOLOGY_FILES = 852
EXPECTED_CHRONOLOGY_ROWS = 7_763_847_245

EXPECTED_B1_CHOOSERS = 64_331
EXPECTED_B1_OPPORTUNITIES = 1_017_944
EXPECTED_B1_KIND_DRAWS = 273_483

DAY_MS = 24 * 60 * 60 * 1000
HOUR_MS = 60 * 60 * 1000
HORIZON_30D_MS = 30 * DAY_MS
HORIZON_90D_MS = 90 * DAY_MS
B1_TAUS_HOURS = (6.0, 24.0, 168.0)
B1_PRIMARY_TAU_HOURS = 24.0
B1_FOLDS = 5
B1_RANDOMIZATIONS = 4_999
B1_RANDOMIZATION_BATCH = 1_000
B1_SEED = 20_260_821
PAIR_KEY_SHIFT = 32

MAIN_MONTHS = tuple(
    f"{absolute // 12:04d}-{absolute % 12 + 1:02d}"
    for absolute in range(2023 * 12 + 10, 2023 * 12 + 10 + 24)
)
CHRONOLOGY_COLUMNS = ("utc_ms", "white_id", "black_id")

_B1_WORKER_DATA: dict[str, Any] | None = None
_B1_WORKER_PROBABILITY: Any | None = None

EXPOSURE_EVAL_BANDS = (
    "[-100,-51]",
    "[-50,-1]",
    "[0,50]",
    "[51,100]",
    "[101,200]",
    "[201,400]",
    "[401,800]",
    "[801,+inf]",
)
EXPOSURE_GAP_BANDS = (
    "<-400",
    "[-400,-201]",
    "[-200,-101]",
    "[-100,-1]",
    "[0,99]",
    "[100,199]",
    "[200,399]",
    "[400,+inf]",
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_AUTHORITY)
    parser.add_argument("--analysis-plan", type=Path)
    parser.add_argument("--arm-amendment", type=Path)
    parser.add_argument("--stage07-root", type=Path)
    parser.add_argument("--a3-gate-root", type=Path)
    parser.add_argument("--a3-private-cache", type=Path)
    parser.add_argument("--chronology-root", type=Path)
    parser.add_argument("--state-root", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--chronology-workers", type=int, default=4)
    parser.add_argument("--b1-workers", type=int, default=5)
    parser.add_argument("--memory-limit", default="12GB")
    parser.add_argument("--batch-rows", type=int, default=500_000)
    parser.add_argument("--verify-stage07-hashes", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--integration-self-test", action="store_true")
    parser.add_argument("--parallel-self-test", action="store_true")
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


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


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
            delimiter=delimiter,
            extrasaction="raise",
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


def normal_two_sided_p(t_value: float) -> float:
    return math.erfc(abs(float(t_value)) / math.sqrt(2.0))


def command_output(args: Sequence[str], *, cwd: Path | None = None) -> str:
    return subprocess.check_output(list(args), cwd=cwd, text=True).strip()


def import_dependencies() -> tuple[Any, Any, Any, Any]:
    try:
        import duckdb  # type: ignore
        import numpy as np  # type: ignore
        import pyarrow as pa  # type: ignore
        import pyarrow.parquet as pq  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "duckdb, numpy, and pyarrow are required; use the XT_Pro project venv"
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
        path = root / row["path"]
        if not path.is_file():
            raise RuntimeError(f"Manifest member is missing: {path}")
        if path.stat().st_size != int(row["bytes"]):
            raise RuntimeError(f"Manifest size mismatch: {path}")
        if sha256_file(path) != row["sha256"]:
            raise RuntimeError(f"Manifest SHA-256 mismatch: {path}")
    return len(rows)


def schema_names(summary: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for field in summary.get("output_schema", []):
        if isinstance(field, str):
            names.add(field)
        elif isinstance(field, dict) and field.get("name"):
            names.add(str(field["name"]))
    return names


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
    qa = summary.get("global_qa") or {}
    expected = {
        "status": EXPECTED_STAGE07_STATUS,
        "script_sha256": EXPECTED_STAGE07_SCRIPT_SHA256,
    }
    for key, value in expected.items():
        if summary.get(key) != value:
            raise RuntimeError(f"Stage 07 {key} mismatch")
    if safe_int(qa.get("rows")) != EXPECTED_STAGE07_ROWS:
        raise RuntimeError("Stage 07 row total mismatch")
    if safe_int(qa.get("kind_draws")) != EXPECTED_STAGE07_KIND_DRAWS:
        raise RuntimeError("Stage 07 kind-draw total mismatch")
    if safe_int(qa.get("fair_rows")) != EXPECTED_STAGE07_FAIR_ROWS:
        raise RuntimeError("Stage 07 fair-row total mismatch")
    required = {
        "game_id",
        "archive_ordinal",
        "utc_ms",
        "api_last_move_at_ms",
        "chooser_user_id",
        "disconnected_user_id",
        "chooser_username_norm",
        "disconnected_username_norm",
        "fair_competitive",
        "tournament_like_event",
        "kind_draw",
        "timeout_chooser_win",
        "timeout_draw_no_mating_material",
        "timeout_chooser_loss",
        "month",
        "chooser_elo",
        "disconnected_elo",
        "chooser_clock_last_obs_s",
        "disconnected_clock_last_obs_s",
        "ply_count",
        "material_advantage_chooser",
        "tc_base_s",
        "tc_inc_s",
        "api_speed",
        "engine_eval_cp_disconnected",
        "chooser_draw_payoff_v2",
        "chooser_win_premium_v2",
        "chooser_pre_rd_v2",
        "disconnected_pre_rd_v2",
    }
    missing = sorted(required - schema_names(summary))
    if missing:
        raise RuntimeError(f"Stage 07 is missing dynamic-analysis fields: {missing}")
    paths = [root / f"month={month}/analysis_panel.parquet" for month in MAIN_MONTHS]
    listed = [
        Path(line.strip())
        for line in path_list.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if [str(path) for path in listed] != [str(path) for path in paths]:
        raise RuntimeError("Stage 07 path-list ordering mismatch")
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
                raise RuntimeError(f"Stage 07 Parquet SHA mismatch: {month}")
            print(f"STAGE07_PARQUET_HASH_OK month={month}", flush=True)
        print("STAGE07_PARQUET_HASH_VERIFICATION_OK", flush=True)
    return {
        "root": str(root),
        "success_sha256": EXPECTED_STAGE07_SUCCESS_SHA256,
        "paths": paths,
        "input_hashes_verified": verify_hashes,
        "selected_input_bytes": sum(path.stat().st_size for path in paths),
    }


def authenticate_a3_gate(root: Path, private_cache: Path) -> dict[str, Any]:
    success = root / "_SUCCESS.json"
    manifest = root / "report_file_hashes.tsv"
    chronology_manifest = root / "chronology_input_manifest.tsv"
    input_auth = root / "input_authentication.json"
    for path in (success, manifest, chronology_manifest, input_auth):
        if not path.is_file():
            raise RuntimeError(f"A3 gate authority is missing: {path}")
    if sha256_file(success) != EXPECTED_A3_GATE_SUCCESS_SHA256:
        raise RuntimeError("A3 gate success SHA-256 mismatch")
    authenticated = authenticate_manifest(root, manifest)
    if sha256_file(chronology_manifest) != EXPECTED_CHRONOLOGY_MANIFEST_SHA256:
        raise RuntimeError("A3 chronology manifest SHA-256 mismatch")
    summary = load_json(success)
    checks = {
        "status": EXPECTED_A3_GATE_STATUS,
        "script_version": "1.0.0",
        "script_sha256": EXPECTED_A3_GATE_SCRIPT_SHA256,
        "analysis_plan_sha256": EXPECTED_PLAN_SHA256,
        "private_activity_rows": EXPECTED_A3_PRIVATE_ROWS,
        "private_activity_sha256": EXPECTED_A3_PRIVATE_SHA256,
        "treatment_or_choice_outcome_read": False,
        "arm_specific_result_produced": False,
        "a1_a3_b1_effect_estimates_produced": False,
    }
    failures = {
        key: {"expected": value, "actual": summary.get(key)}
        for key, value in checks.items()
        if summary.get(key) != value
    }
    if failures:
        raise RuntimeError("A3 gate receipt mismatch: " + canonical_json(failures))
    pooled = summary.get("pooled_gate") or {}
    if pooled.get("a3_primary_outcome_selected") != EXPECTED_A3_PRIMARY:
        raise RuntimeError("A3 gate primary-outcome selection mismatch")
    if float(pooled.get("pooled_rate_30d", math.nan)) <= 0.92:
        raise RuntimeError("A3 gate pooled rate does not support the selected outcome")
    if not private_cache.is_file():
        raise RuntimeError(f"A3 private cache is missing: {private_cache}")
    if sha256_file(private_cache) != EXPECTED_A3_PRIVATE_SHA256:
        raise RuntimeError("A3 private cache SHA-256 mismatch")
    auth = load_json(input_auth)
    if auth.get("chronology_footer_plan_sha256") != EXPECTED_CHRONOLOGY_FOOTER_PLAN_SHA256:
        raise RuntimeError("A3 chronology footer-plan SHA mismatch")
    return {
        "root": str(root),
        "success_sha256": EXPECTED_A3_GATE_SUCCESS_SHA256,
        "report_files_authenticated": authenticated,
        "pooled_rate_30d": pooled["pooled_rate_30d"],
        "a3_primary_outcome_selected": pooled["a3_primary_outcome_selected"],
        "private_cache": str(private_cache),
        "private_cache_sha256": EXPECTED_A3_PRIVATE_SHA256,
        "chronology_manifest": str(chronology_manifest),
        "chronology_footer_plan_sha256": EXPECTED_CHRONOLOGY_FOOTER_PLAN_SHA256,
        "recorded_transfer_zip_sha256": EXPECTED_A3_GATE_ZIP_SHA256,
    }


def read_chronology_manifest(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    if len(rows) != EXPECTED_CHRONOLOGY_FILES:
        raise RuntimeError(
            f"Chronology manifest file count mismatch: {len(rows)}"
        )
    total_rows = 0
    parsed: list[dict[str, Any]] = []
    for expected_index, row in enumerate(rows):
        if int(row["file_index"]) != expected_index:
            raise RuntimeError("Chronology manifest index ordering mismatch")
        candidate = Path(row["path"])
        if not candidate.is_file():
            raise RuntimeError(f"Chronology input is missing: {candidate}")
        if candidate.stat().st_size != int(row["bytes"]):
            raise RuntimeError(f"Chronology input size mismatch: {candidate}")
        total_rows += int(row["rows"])
        parsed.append(
            {
                "file_index": expected_index,
                "path": str(candidate),
                "bytes": int(row["bytes"]),
                "rows": int(row["rows"]),
                "row_groups": int(row["row_groups"]),
                "utc_ms_min": int(row["utc_ms_min"]) if row["utc_ms_min"] else None,
                "utc_ms_max": int(row["utc_ms_max"]) if row["utc_ms_max"] else None,
                "footer_signature_sha256": row["footer_signature_sha256"],
            }
        )
    if total_rows != EXPECTED_CHRONOLOGY_ROWS:
        raise RuntimeError(f"Chronology row total mismatch: {total_rows}")
    return parsed


def configure_duckdb(connection: Any, payload: dict[str, Any], temp: Path) -> None:
    temp.mkdir(parents=True, exist_ok=True)
    connection.execute(f"SET threads = {int(payload['threads'])}")
    connection.execute(f"SET memory_limit = {sql_literal(payload['memory_limit'])}")
    connection.execute(f"SET temp_directory = {sql_literal(temp)}")
    connection.execute("SET preserve_insertion_order = false")


def speed_code_sql(field: str) -> str:
    return f"""
      CASE lower(replace(CAST({field} AS VARCHAR), '_', ''))
        WHEN 'ultrabullet' THEN 0
        WHEN 'bullet' THEN 1
        WHEN 'blitz' THEN 2
        WHEN 'rapid' THEN 3
        WHEN 'classical' THEN 4
        WHEN 'correspondence' THEN 5
        ELSE -1
      END
    """.strip()


def eval_band_sql(field: str) -> str:
    return f"""
      CASE
        WHEN {field} BETWEEN -100 AND -51 THEN 0
        WHEN {field} BETWEEN -50 AND -1 THEN 1
        WHEN {field} BETWEEN 0 AND 50 THEN 2
        WHEN {field} BETWEEN 51 AND 100 THEN 3
        WHEN {field} BETWEEN 101 AND 200 THEN 4
        WHEN {field} BETWEEN 201 AND 400 THEN 5
        WHEN {field} BETWEEN 401 AND 800 THEN 6
        WHEN {field} >= 801 THEN 7
        ELSE -1
      END
    """.strip()


def payoff_class_sql(field: str) -> str:
    return f"""
      CASE
        WHEN abs({field}) <= 1e-12 THEN 1
        WHEN {field} < -1e-12 THEN 0
        WHEN {field} > 1e-12 THEN 2
        ELSE -1
      END
    """.strip()


def gap_band_sql(field: str) -> str:
    return f"""
      CASE
        WHEN {field} < -400 THEN 0
        WHEN {field} BETWEEN -400 AND -201 THEN 1
        WHEN {field} BETWEEN -200 AND -101 THEN 2
        WHEN {field} BETWEEN -100 AND -1 THEN 3
        WHEN {field} BETWEEN 0 AND 99 THEN 4
        WHEN {field} BETWEEN 100 AND 199 THEN 5
        WHEN {field} BETWEEN 200 AND 399 THEN 6
        WHEN {field} >= 400 THEN 7
        ELSE -1
      END
    """.strip()


def make_plan(args: argparse.Namespace, script_path: Path) -> dict[str, Any]:
    if args.threads < 1:
        raise RuntimeError("--threads must be at least 1")
    if args.chronology_workers < 1:
        raise RuntimeError("--chronology-workers must be at least 1")
    if args.b1_workers < 1:
        raise RuntimeError("--b1-workers must be at least 1")
    if args.batch_rows < 1:
        raise RuntimeError("--batch-rows must be at least 1")
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
    if not analysis_plan.is_file() or sha256_file(analysis_plan) != EXPECTED_PLAN_SHA256:
        raise RuntimeError("Frozen v1.0.1 analysis-plan SHA-256 mismatch")
    arm_amendment = (
        args.arm_amendment.expanduser().resolve()
        if args.arm_amendment
        else script_path.with_name(
            "Dynamic_Prosociality_Arm_Partition_Amendment_v1_0_2_2026-08-22.md"
        )
    )
    if (
        not arm_amendment.is_file()
        or sha256_file(arm_amendment) != EXPECTED_ARM_AMENDMENT_SHA256
    ):
        raise RuntimeError("Arm-partition amendment v1.0.2 SHA-256 mismatch")
    execution_note = script_path.with_name(
        "Dynamic_Prosociality_Parallel_Execution_Note_v1_0_0_2026-08-22.md"
    )
    if (
        not execution_note.is_file()
        or sha256_file(execution_note) != EXPECTED_EXECUTION_NOTE_SHA256
    ):
        raise RuntimeError("Parallel-execution note SHA-256 mismatch")
    stage07_root = (
        args.stage07_root.expanduser().resolve()
        if args.stage07_root
        else project / "derived/replication/analysis_panel_24m_sf100k"
    )
    gate_root = (
        args.a3_gate_root.expanduser().resolve()
        if args.a3_gate_root
        else project
        / "output/dynamic_prosociality_a3_chronology_gate_v100"
        / EXPECTED_A3_GATE_RUN_ID
    )
    private_cache = (
        args.a3_private_cache.expanduser().resolve()
        if args.a3_private_cache
        else project
        / "derived/replication/dynamic_prosociality_a3_chronology_gate_v100_PRIVATE"
        / "a3_30d_activity_private_no_treatment.parquet"
    )
    state_root = (
        args.state_root.expanduser().resolve()
        if args.state_root
        else project
        / "derived/replication/dynamic_prosociality_core_v102_PRIVATE"
    )
    output_root = (
        args.output_root.expanduser().resolve()
        if args.output_root
        else project / "output/dynamic_prosociality_core_v102"
    )
    stage07 = authenticate_stage07(
        stage07_root, verify_hashes=args.verify_stage07_hashes
    )
    gate = authenticate_a3_gate(gate_root, private_cache)
    chronology = read_chronology_manifest(Path(gate["chronology_manifest"]))
    git = git_state(project / "replication_package")
    if not git["clean"]:
        raise RuntimeError("Replication repository is not clean")
    if git["head"] != EXPECTED_GIT_HEAD or git["branch"] != "main":
        raise RuntimeError(
            f"Replication Git state mismatch: head={git['head']} branch={git['branch']}"
        )
    if shutil.disk_usage(project).free < 80 * 1024**3:
        raise RuntimeError("Less than 80 GiB is free on XT_Pro")
    frozen_spec = {
        "analysis_plan_sha256": EXPECTED_PLAN_SHA256,
        "arm_partition_amendment_sha256": EXPECTED_ARM_AMENDMENT_SHA256,
        "stage07_success_sha256": EXPECTED_STAGE07_SUCCESS_SHA256,
        "a3_gate_success_sha256": EXPECTED_A3_GATE_SUCCESS_SHA256,
        "a3_private_cache_sha256": EXPECTED_A3_PRIVATE_SHA256,
        "chronology_manifest_sha256": EXPECTED_CHRONOLOGY_MANIFEST_SHA256,
        "recipient_scope": (
            "first fair disconnected-player exposure; ordinary non-tournament-like; "
            "first-ever pair after canonical chronology reconstruction"
        ),
        "recipient_arm_rule": {
            "eligible": "outcome_kind_draw OR timeout_chooser_win",
            "treatment": "outcome_kind_draw",
            "control": "timeout_chooser_win",
            "excluded": (
                "timeout_draw_no_mating_material OR timeout_chooser_loss"
            ),
            "index_reranked_after_exclusion": False,
            "expected_index_rows": EXPECTED_A3_PRIVATE_ROWS,
            "expected_arm_eligible_rows": EXPECTED_RECIPIENT_ARM_ELIGIBLE,
            "expected_nonarm_rows": EXPECTED_RECIPIENT_NONARM,
        },
        "exposure_cell": {
            "eval_bands": EXPOSURE_EVAL_BANDS,
            "payoff_classes": ("costly", "exact_zero", "favorable"),
            "rating_gap_bands": EXPOSURE_GAP_BANDS,
            "speed_codes": {
                "ultrabullet": 0,
                "bullet": 1,
                "blitz": 2,
                "rapid": 3,
                "classical": 4,
                "correspondence": 5,
            },
            "minimum_mercy": 5,
            "minimum_claimed": 20,
            "minimum_mercy_retention_share": 0.90,
        },
        "a1_primary": "first subsequent fair chooser decision within 90 days",
        "a1_primary_estimand": "exposure-adjusted total-path conditional choice",
        "a1_state_conditioned_reported": True,
        "a3_primary": EXPECTED_A3_PRIMARY,
        "a3_binary_and_raw_counts_always_reported": True,
        "b1": {
            "sample": "n_fair>=4, kind>=2, nonkind>=1; repeat granters",
            "folds": B1_FOLDS,
            "static_model": "cross-fitted ridge logistic model",
            "conditional_sampler": "exact conditional Bernoulli using odds and dynamic programming",
            "taus_hours": B1_TAUS_HOURS,
            "primary_tau_hours": B1_PRIMARY_TAU_HOURS,
            "randomizations": B1_RANDOMIZATIONS,
            "randomization_batch": B1_RANDOMIZATION_BATCH,
            "seed": B1_SEED,
            "two_sided_p": "2*min(plus-one upper, plus-one lower), capped at 1",
        },
        "multiple_testing": "Holm across A1, selected A3, and B1 T_24h",
    }
    payload: dict[str, Any] = {
        "status": "DYNAMIC_PROSOCIALITY_CORE_V102_PLAN_OK",
        "created_utc": utc_now(),
        "script_version": SCRIPT_VERSION,
        "script_path": str(script_path),
        "script_sha256": sha256_file(script_path),
        "analysis_plan_path": str(analysis_plan),
        "analysis_plan_sha256": EXPECTED_PLAN_SHA256,
        "arm_amendment_path": str(arm_amendment),
        "arm_amendment_sha256": EXPECTED_ARM_AMENDMENT_SHA256,
        "execution_note_path": str(execution_note),
        "execution_note_sha256": EXPECTED_EXECUTION_NOTE_SHA256,
        "project_root": str(project),
        "stage07": stage07,
        "a3_gate": gate,
        "chronology": chronology,
        "chronology_files": len(chronology),
        "chronology_rows": sum(row["rows"] for row in chronology),
        "git": git,
        "state_root": str(state_root),
        "output_root": str(output_root),
        "threads": args.threads,
        "chronology_workers": args.chronology_workers,
        "b1_workers": args.b1_workers,
        "memory_limit": args.memory_limit,
        "batch_rows": args.batch_rows,
        "frozen_spec": frozen_spec,
    }
    resume_source = {
        "script_sha256": payload["script_sha256"],
        "execution_note_sha256": EXPECTED_EXECUTION_NOTE_SHA256,
        "frozen_spec": frozen_spec,
        "git_head": git["head"],
    }
    payload["resume_config"] = resume_source
    payload["resume_config_sha256"] = sha256_text(canonical_json(resume_source))
    return payload


def print_plan(payload: dict[str, Any]) -> None:
    print(payload["status"])
    print(f"script_version: {payload['script_version']}")
    print(f"script_sha256: {payload['script_sha256']}")
    print(f"analysis_plan_sha256: {payload['analysis_plan_sha256']}")
    print(f"arm_amendment_sha256: {payload['arm_amendment_sha256']}")
    print(f"execution_note_sha256: {payload['execution_note_sha256']}")
    print(f"git_head: {payload['git']['head']}")
    print(f"stage07_rows: {EXPECTED_STAGE07_ROWS:,}")
    print(f"stage07_paths: {len(payload['stage07']['paths'])}")
    print(
        "stage07_input_hashes_verified: "
        f"{payload['stage07']['input_hashes_verified']}"
    )
    print(f"a3_gate_success_sha256: {payload['a3_gate']['success_sha256']}")
    print(f"a3_private_cache_sha256: {payload['a3_gate']['private_cache_sha256']}")
    print(
        "recipient index/arm totals: "
        f"{EXPECTED_A3_PRIVATE_ROWS:,} / {EXPECTED_RECIPIENT_ARM_ELIGIBLE:,}; "
        f"non-arm={EXPECTED_RECIPIENT_NONARM:,}"
    )
    print(
        "a3_primary_outcome: "
        f"{payload['a3_gate']['a3_primary_outcome_selected']}"
    )
    print(f"chronology_files: {payload['chronology_files']:,}")
    print(f"chronology_rows: {payload['chronology_rows']:,}")
    print(f"chronology_workers: {payload['chronology_workers']}")
    print(f"b1_workers: {payload['b1_workers']}")
    print(f"state_root: {payload['state_root']}")
    print(f"output_root: {payload['output_root']}")
    print(f"B1 randomizations: {B1_RANDOMIZATIONS:,}")
    print("resumability: chronology-file and B1-randomization-batch checkpoints")
    print("privacy: account-level analysis files remain private on XT_Pro")


def initialize_or_authenticate_state(payload: dict[str, Any]) -> Path:
    state = Path(payload["state_root"])
    config = state / "resume_config.json"
    if state.exists():
        if not config.is_file():
            raise RuntimeError(f"State root exists without resume config: {state}")
        saved = load_json(config)
        if saved.get("resume_config_sha256") != payload["resume_config_sha256"]:
            raise RuntimeError("Existing private state belongs to another configuration")
        print("DYNAMIC_CORE_RESUME_STATE_AUTHENTICATED_OK", flush=True)
        return state
    state.mkdir(parents=True, exist_ok=False)
    for relative in (
        "chronology_updates/activity",
        "chronology_updates/pairs",
        "chronology_receipts",
        "b1_randomizations",
        "duckdb_temp",
    ):
        (state / relative).mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        config,
        {
            "status": "DYNAMIC_CORE_RESUME_CONFIG_OK",
            "created_utc": utc_now(),
            "resume_config": payload["resume_config"],
            "resume_config_sha256": payload["resume_config_sha256"],
            "raw_account_level_data": "PRIVATE; DO NOT COMMIT OR PUBLISH",
        },
    )
    print(f"DYNAMIC_CORE_RESUME_STATE_CREATED: {state}", flush=True)
    return state


def recipient_panel_sql(paths: Sequence[Path], a3_cache: Path, panel_end_ms: int) -> str:
    speed_exposure = speed_code_sql("api_speed")
    eval_exposure = eval_band_sql("engine_eval_cp_disconnected")
    payoff_exposure = payoff_class_sql("chooser_draw_payoff_v2")
    gap_exposure = gap_band_sql("chooser_elo - disconnected_elo")
    speed_future = speed_code_sql("p.api_speed")
    month_code = (
        "date_diff('month', DATE '2023-11-01', "
        "strptime(month || '-01', '%Y-%m-%d'))"
    )
    future_month_code = (
        "date_diff('month', DATE '2023-11-01', "
        "strptime(p.month || '-01', '%Y-%m-%d'))"
    )
    return f"""
      WITH panel AS (
        SELECT *
        FROM read_parquet({path_list_literal(paths)}, union_by_name = true)
      ), exposure_ranked AS (
        SELECT
          disconnected_username_norm,
          CAST(disconnected_user_id AS BIGINT) AS recipient_user_id,
          CAST(chooser_user_id AS BIGINT) AS exposure_chooser_user_id,
          chooser_username_norm AS exposure_chooser_username_norm,
          game_id AS exposure_game_id,
          CAST(api_last_move_at_ms AS BIGINT) AS exposure_anchor_utc_ms,
          CAST(utc_ms AS BIGINT) AS exposure_game_utc_ms,
          CAST(archive_ordinal AS BIGINT) AS exposure_archive_ordinal,
          CAST(kind_draw AS BOOLEAN) AS received_mercy,
          CAST(timeout_chooser_win AS BOOLEAN) AS exposure_claimed_win,
          CAST(
            CAST(kind_draw AS BOOLEAN) OR CAST(timeout_chooser_win AS BOOLEAN)
            AS BOOLEAN
          ) AS arm_eligible,
          CAST(timeout_draw_no_mating_material AS BOOLEAN)
            AS exposure_no_mating_draw,
          CAST(timeout_chooser_loss AS BOOLEAN) AS exposure_chooser_loss,
          CAST(engine_eval_cp_disconnected AS DOUBLE) AS exposure_eval_cp,
          CAST(chooser_draw_payoff_v2 AS DOUBLE) AS exposure_draw_payoff,
          CAST(chooser_win_premium_v2 AS DOUBLE) AS exposure_win_premium,
          CAST(chooser_elo AS DOUBLE) AS exposure_chooser_elo,
          CAST(disconnected_elo AS DOUBLE) AS exposure_recipient_elo,
          CAST(chooser_pre_rd_v2 AS DOUBLE) AS exposure_chooser_rd,
          CAST(disconnected_pre_rd_v2 AS DOUBLE) AS exposure_recipient_rd,
          CAST(chooser_clock_last_obs_s AS DOUBLE) AS exposure_chooser_clock_s,
          CAST(disconnected_clock_last_obs_s AS DOUBLE) AS exposure_recipient_clock_s,
          CAST(ply_count AS DOUBLE) AS exposure_ply_count,
          CAST(material_advantage_chooser AS DOUBLE) AS exposure_material_advantage,
          CAST(tc_base_s AS DOUBLE) AS exposure_tc_base_s,
          CAST(tc_inc_s AS DOUBLE) AS exposure_tc_inc_s,
          CAST({speed_exposure} AS INTEGER) AS exposure_speed_code,
          CAST({month_code} AS INTEGER) AS exposure_month_code,
          CAST({eval_exposure} AS INTEGER) AS exposure_eval_band,
          CAST({payoff_exposure} AS INTEGER) AS exposure_payoff_class,
          CAST({gap_exposure} AS INTEGER) AS exposure_gap_band,
          ROW_NUMBER() OVER (
            PARTITION BY disconnected_username_norm
            ORDER BY utc_ms, archive_ordinal, game_id
          ) AS exposure_rank
        FROM panel
        WHERE CAST(fair_competitive AS BOOLEAN)
          AND NOT CAST(tournament_like_event AS BOOLEAN)
          AND disconnected_username_norm IS NOT NULL
          AND trim(disconnected_username_norm) <> ''
      ), exposure_pre_number AS (
        SELECT * EXCLUDE (exposure_rank)
        FROM exposure_ranked
        WHERE exposure_rank = 1
      ), exposure AS (
        SELECT
          ROW_NUMBER() OVER (ORDER BY disconnected_username_norm)::BIGINT - 1
            AS cohort_row_id,
          *,
          (
            exposure_eval_band * 3 * 8 * 6
            + exposure_payoff_class * 8 * 6
            + exposure_gap_band * 6
            + exposure_speed_code
          )::INTEGER AS exposure_cell_code,
          (exposure_anchor_utc_ms + {HORIZON_90D_MS} <= {int(panel_end_ms)})
            AS a1_90d_followup_eligible
        FROM exposure_pre_number
      ), future_labeled AS (
        SELECT
          e.cohort_row_id,
          CAST(p.api_last_move_at_ms AS BIGINT) - e.exposure_anchor_utc_ms
            AS subsequent_delta_ms,
          CAST(p.kind_draw AS BOOLEAN) AS subsequent_kind_draw,
          CAST(p.engine_eval_cp_disconnected AS DOUBLE) AS subsequent_eval_cp,
          CAST(p.chooser_draw_payoff_v2 AS DOUBLE) AS subsequent_draw_payoff,
          CAST(p.chooser_win_premium_v2 AS DOUBLE) AS subsequent_win_premium,
          CAST(p.chooser_clock_last_obs_s AS DOUBLE) AS subsequent_chooser_clock_s,
          CAST(p.disconnected_clock_last_obs_s AS DOUBLE)
            AS subsequent_opponent_clock_s,
          CAST(p.chooser_elo AS DOUBLE) AS subsequent_chooser_elo,
          CAST(p.disconnected_elo AS DOUBLE) AS subsequent_opponent_elo,
          CAST(p.chooser_pre_rd_v2 AS DOUBLE) AS subsequent_chooser_rd,
          CAST(p.disconnected_pre_rd_v2 AS DOUBLE) AS subsequent_opponent_rd,
          CAST({speed_future} AS INTEGER) AS subsequent_speed_code,
          CAST(p.tournament_like_event AS BOOLEAN) AS subsequent_tournament_like,
          CAST({future_month_code} AS INTEGER) AS subsequent_month_code,
          CAST(p.api_last_move_at_ms AS BIGINT) AS subsequent_utc_ms,
          CAST(p.archive_ordinal AS BIGINT) AS subsequent_archive_ordinal,
          p.game_id AS subsequent_game_id,
          CASE
            WHEN CAST(p.api_last_move_at_ms AS BIGINT) - e.exposure_anchor_utc_ms
                   <= {6 * HOUR_MS} THEN 0
            WHEN CAST(p.api_last_move_at_ms AS BIGINT) - e.exposure_anchor_utc_ms
                   <= {DAY_MS} THEN 1
            WHEN CAST(p.api_last_move_at_ms AS BIGINT) - e.exposure_anchor_utc_ms
                   <= {7 * DAY_MS} THEN 2
            WHEN CAST(p.api_last_move_at_ms AS BIGINT) - e.exposure_anchor_utc_ms
                   <= {30 * DAY_MS} THEN 3
            ELSE 4
          END AS decay_band
        FROM exposure e
        INNER JOIN panel p
          ON CAST(p.chooser_user_id AS BIGINT) = e.recipient_user_id
         AND CAST(p.fair_competitive AS BOOLEAN)
         AND CAST(p.api_last_move_at_ms AS BIGINT) > e.exposure_anchor_utc_ms
         AND CAST(p.api_last_move_at_ms AS BIGINT)
               <= e.exposure_anchor_utc_ms + {HORIZON_90D_MS}
      ), future_ranked AS (
        SELECT
          *,
          ROW_NUMBER() OVER (
            PARTITION BY cohort_row_id
            ORDER BY subsequent_utc_ms, subsequent_archive_ordinal, subsequent_game_id
          ) AS overall_rank,
          ROW_NUMBER() OVER (
            PARTITION BY cohort_row_id, decay_band
            ORDER BY subsequent_utc_ms, subsequent_archive_ordinal, subsequent_game_id
          ) AS band_rank
        FROM future_labeled
      ), future_summary AS (
        SELECT
          cohort_row_id,
          TRUE AS reached_fair_chooser_within_90d,
          BOOL_OR(subsequent_kind_draw) AS any_fair_kind_grant_within_90d,
          MAX(CASE WHEN overall_rank = 1 THEN subsequent_kind_draw END)
            AS first_subsequent_kind_draw,
          MAX(CASE WHEN overall_rank = 1 THEN subsequent_delta_ms END)
            AS first_subsequent_delta_ms,
          MAX(CASE WHEN overall_rank = 1 THEN subsequent_eval_cp END)
            AS first_subsequent_eval_cp,
          MAX(CASE WHEN overall_rank = 1 THEN subsequent_draw_payoff END)
            AS first_subsequent_draw_payoff,
          MAX(CASE WHEN overall_rank = 1 THEN subsequent_win_premium END)
            AS first_subsequent_win_premium,
          MAX(CASE WHEN overall_rank = 1 THEN subsequent_chooser_clock_s END)
            AS first_subsequent_chooser_clock_s,
          MAX(CASE WHEN overall_rank = 1 THEN subsequent_opponent_clock_s END)
            AS first_subsequent_opponent_clock_s,
          MAX(CASE WHEN overall_rank = 1 THEN subsequent_chooser_elo END)
            AS first_subsequent_chooser_elo,
          MAX(CASE WHEN overall_rank = 1 THEN subsequent_opponent_elo END)
            AS first_subsequent_opponent_elo,
          MAX(CASE WHEN overall_rank = 1 THEN subsequent_chooser_rd END)
            AS first_subsequent_chooser_rd,
          MAX(CASE WHEN overall_rank = 1 THEN subsequent_opponent_rd END)
            AS first_subsequent_opponent_rd,
          MAX(CASE WHEN overall_rank = 1 THEN subsequent_speed_code END)
            AS first_subsequent_speed_code,
          MAX(CASE WHEN overall_rank = 1 THEN subsequent_tournament_like END)
            AS first_subsequent_tournament_like,
          MAX(CASE WHEN overall_rank = 1 THEN subsequent_month_code END)
            AS first_subsequent_month_code,
          MAX(CASE WHEN decay_band = 0 AND band_rank = 1 THEN subsequent_kind_draw END)
            AS decay_6h_kind,
          MAX(CASE WHEN decay_band = 1 AND band_rank = 1 THEN subsequent_kind_draw END)
            AS decay_1d_kind,
          MAX(CASE WHEN decay_band = 2 AND band_rank = 1 THEN subsequent_kind_draw END)
            AS decay_7d_kind,
          MAX(CASE WHEN decay_band = 3 AND band_rank = 1 THEN subsequent_kind_draw END)
            AS decay_30d_kind,
          MAX(CASE WHEN decay_band = 4 AND band_rank = 1 THEN subsequent_kind_draw END)
            AS decay_90d_kind
        FROM future_ranked
        GROUP BY cohort_row_id
      ), recipient_pre90 AS (
        SELECT
          e.cohort_row_id,
          COUNT(*)::BIGINT AS recipient_prior_fair_opportunities_90d,
          SUM(CAST(p.kind_draw AS BIGINT))::BIGINT AS recipient_prior_kind_draws_90d,
          ARG_MIN(CAST(p.chooser_elo AS DOUBLE), CAST(p.api_last_move_at_ms AS BIGINT))
            AS recipient_prior_first_rating_90d,
          ARG_MAX(CAST(p.chooser_elo AS DOUBLE), CAST(p.api_last_move_at_ms AS BIGINT))
            AS recipient_prior_last_rating_90d
        FROM exposure e
        INNER JOIN panel p
          ON CAST(p.chooser_user_id AS BIGINT) = e.recipient_user_id
         AND CAST(p.fair_competitive AS BOOLEAN)
         AND CAST(p.api_last_move_at_ms AS BIGINT) < e.exposure_anchor_utc_ms
         AND CAST(p.api_last_move_at_ms AS BIGINT)
               >= e.exposure_anchor_utc_ms - {HORIZON_90D_MS}
        GROUP BY e.cohort_row_id
      ), recipient_prior_disconnect AS (
        SELECT
          e.cohort_row_id,
          COUNT(*)::BIGINT AS recipient_prior_disconnections_main_sample,
          SUM(CAST(p.kind_draw AS BIGINT))::BIGINT
            AS recipient_prior_mercy_receipts_main_sample
        FROM exposure e
        INNER JOIN panel p
          ON CAST(p.disconnected_user_id AS BIGINT) = e.recipient_user_id
         AND CAST(p.api_last_move_at_ms AS BIGINT) < e.exposure_anchor_utc_ms
        GROUP BY e.cohort_row_id
      ), recipient_future_disconnect AS (
        SELECT
          e.cohort_row_id,
          COUNT(*)::BIGINT AS recipient_future_disconnections_90d,
          SUM(CAST(p.kind_draw AS BIGINT))::BIGINT
            AS recipient_future_mercy_receipts_90d,
          MIN(CAST(p.api_last_move_at_ms AS BIGINT))::BIGINT
            AS recipient_next_disconnection_utc_ms
        FROM exposure e
        INNER JOIN panel p
          ON CAST(p.disconnected_user_id AS BIGINT) = e.recipient_user_id
         AND CAST(p.fair_competitive AS BOOLEAN)
         AND CAST(p.api_last_move_at_ms AS BIGINT) > e.exposure_anchor_utc_ms
         AND CAST(p.api_last_move_at_ms AS BIGINT)
               <= e.exposure_anchor_utc_ms + {HORIZON_90D_MS}
        GROUP BY e.cohort_row_id
      ), chooser_time AS (
        SELECT
          CAST(chooser_user_id AS BIGINT) AS chooser_user_id,
          CAST(api_last_move_at_ms AS BIGINT) AS hist_time,
          COUNT(*)::BIGINT AS n_at_time,
          SUM(CAST(kind_draw AS BIGINT))::BIGINT AS k_at_time
        FROM panel
        WHERE CAST(fair_competitive AS BOOLEAN)
          AND chooser_user_id IS NOT NULL
          AND api_last_move_at_ms IS NOT NULL
        GROUP BY chooser_user_id, hist_time
      ), chooser_cum AS (
        SELECT
          chooser_user_id,
          hist_time,
          SUM(n_at_time) OVER (
            PARTITION BY chooser_user_id ORDER BY hist_time
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
          )::BIGINT AS cum_n,
          SUM(k_at_time) OVER (
            PARTITION BY chooser_user_id ORDER BY hist_time
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
          )::BIGINT AS cum_k
        FROM chooser_time
      ), pair_time AS (
        SELECT
          CAST(chooser_user_id AS BIGINT) AS chooser_user_id,
          CAST(disconnected_user_id AS BIGINT) AS disconnected_user_id,
          CAST(api_last_move_at_ms AS BIGINT) AS hist_time,
          COUNT(*)::BIGINT AS n_at_time,
          SUM(CAST(kind_draw AS BIGINT))::BIGINT AS k_at_time
        FROM panel
        WHERE CAST(fair_competitive AS BOOLEAN)
          AND chooser_user_id IS NOT NULL
          AND disconnected_user_id IS NOT NULL
          AND api_last_move_at_ms IS NOT NULL
        GROUP BY chooser_user_id, disconnected_user_id, hist_time
      ), pair_cum AS (
        SELECT
          chooser_user_id,
          disconnected_user_id,
          hist_time,
          SUM(n_at_time) OVER (
            PARTITION BY chooser_user_id, disconnected_user_id ORDER BY hist_time
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
          )::BIGINT AS pair_cum_n,
          SUM(k_at_time) OVER (
            PARTITION BY chooser_user_id, disconnected_user_id ORDER BY hist_time
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
          )::BIGINT AS pair_cum_k
        FROM pair_time
      ), chooser_snapshot AS (
        SELECT e.cohort_row_id, h.cum_n, h.cum_k
        FROM exposure e
        ASOF LEFT JOIN chooser_cum h
          ON e.exposure_chooser_user_id = h.chooser_user_id
         AND e.exposure_anchor_utc_ms > h.hist_time
      ), pair_snapshot AS (
        SELECT e.cohort_row_id, h.pair_cum_n, h.pair_cum_k
        FROM exposure e
        ASOF LEFT JOIN pair_cum h
          ON e.exposure_chooser_user_id = h.chooser_user_id
         AND e.recipient_user_id = h.disconnected_user_id
         AND e.exposure_anchor_utc_ms > h.hist_time
      ), a3 AS (
        SELECT *
        FROM read_parquet({sql_literal(a3_cache)})
      )
      SELECT
        e.*,
        COALESCE(f.reached_fair_chooser_within_90d, FALSE)
          AS reached_fair_chooser_within_90d,
        COALESCE(f.any_fair_kind_grant_within_90d, FALSE)
          AS any_fair_kind_grant_within_90d,
        f.* EXCLUDE (
          cohort_row_id,
          reached_fair_chooser_within_90d,
          any_fair_kind_grant_within_90d
        ),
        COALESCE(r.recipient_prior_fair_opportunities_90d, 0)::BIGINT
          AS recipient_prior_fair_opportunities_90d,
        COALESCE(r.recipient_prior_kind_draws_90d, 0)::BIGINT
          AS recipient_prior_kind_draws_90d,
        CASE
          WHEN COALESCE(r.recipient_prior_fair_opportunities_90d, 0) > 0
          THEN CAST(r.recipient_prior_kind_draws_90d AS DOUBLE)
               / r.recipient_prior_fair_opportunities_90d
        END AS recipient_prior_kind_rate_90d,
        r.recipient_prior_first_rating_90d,
        r.recipient_prior_last_rating_90d,
        r.recipient_prior_last_rating_90d - r.recipient_prior_first_rating_90d
          AS recipient_prior_rating_change_90d,
        COALESCE(d.recipient_prior_disconnections_main_sample, 0)::BIGINT
          AS recipient_prior_disconnections_main_sample,
        COALESCE(d.recipient_prior_mercy_receipts_main_sample, 0)::BIGINT
          AS recipient_prior_mercy_receipts_main_sample,
        COALESCE(fd.recipient_future_disconnections_90d, 0)::BIGINT
          AS recipient_future_disconnections_90d,
        COALESCE(fd.recipient_future_mercy_receipts_90d, 0)::BIGINT
          AS recipient_future_mercy_receipts_90d,
        fd.recipient_next_disconnection_utc_ms,
        GREATEST(
          COALESCE(c.cum_n, 0) - COALESCE(ps.pair_cum_n, 0), 0
        )::BIGINT AS encouragement_prior_pair_excluded_n,
        GREATEST(
          COALESCE(c.cum_k, 0) - COALESCE(ps.pair_cum_k, 0), 0
        )::BIGINT AS encouragement_prior_pair_excluded_kind,
        CASE
          WHEN COALESCE(c.cum_n, 0) - COALESCE(ps.pair_cum_n, 0) >= 10
          THEN CAST(COALESCE(c.cum_k, 0) - COALESCE(ps.pair_cum_k, 0) AS DOUBLE)
               / (COALESCE(c.cum_n, 0) - COALESCE(ps.pair_cum_n, 0))
        END AS encouragement_pair_excluded_propensity,
        a3.games_within_7d,
        a3.games_within_30d,
        a3.first_next_game_utc_ms,
        a3.any_game_within_7d,
        a3.any_game_within_30d,
        CASE
          WHEN a3.first_next_game_utc_ms IS NOT NULL
          THEN a3.first_next_game_utc_ms - e.exposure_anchor_utc_ms
        END AS next_game_delta_ms,
        (a3.first_next_game_utc_ms IS NOT NULL
          AND a3.first_next_game_utc_ms - e.exposure_anchor_utc_ms
              <= {10 * 60 * 1000}) AS any_game_within_10m,
        (a3.first_next_game_utc_ms IS NOT NULL
          AND a3.first_next_game_utc_ms - e.exposure_anchor_utc_ms
              <= {30 * 60 * 1000}) AS any_game_within_30m,
        (a3.first_next_game_utc_ms IS NOT NULL
          AND a3.first_next_game_utc_ms - e.exposure_anchor_utc_ms
              <= {60 * 60 * 1000}) AS any_game_within_60m,
        LN(1.0 + a3.games_within_30d) AS log1p_games_within_30d
      FROM exposure e
      INNER JOIN a3
        ON a3.cohort_row_id = e.cohort_row_id
       AND a3.disconnected_user_id = e.recipient_user_id
       AND a3.exposure_game_id = e.exposure_game_id
       AND a3.exposure_anchor_utc_ms = e.exposure_anchor_utc_ms
      LEFT JOIN future_summary f ON f.cohort_row_id = e.cohort_row_id
      LEFT JOIN recipient_pre90 r ON r.cohort_row_id = e.cohort_row_id
      LEFT JOIN recipient_prior_disconnect d ON d.cohort_row_id = e.cohort_row_id
      LEFT JOIN recipient_future_disconnect fd ON fd.cohort_row_id = e.cohort_row_id
      LEFT JOIN chooser_snapshot c ON c.cohort_row_id = e.cohort_row_id
      LEFT JOIN pair_snapshot ps ON ps.cohort_row_id = e.cohort_row_id
      ORDER BY e.cohort_row_id
    """


def build_or_authenticate_recipient_panel(
    payload: dict[str, Any], state: Path
) -> Path:
    duckdb, _, _, pq = import_dependencies()
    output = state / "recipient_analysis_private.parquet"
    receipt = state / "recipient_analysis_receipt.json"
    if output.is_file() and receipt.is_file():
        saved = load_json(receipt)
        if saved.get("output_sha256") != sha256_file(output):
            raise RuntimeError("Recipient-panel checkpoint SHA mismatch")
        if saved.get("resume_config_sha256") != payload["resume_config_sha256"]:
            raise RuntimeError("Recipient-panel checkpoint config mismatch")
        if safe_int(saved.get("rows")) != EXPECTED_A3_PRIVATE_ROWS:
            raise RuntimeError("Recipient-panel checkpoint row count mismatch")
        print("RECIPIENT_PANEL_CHECKPOINT_AUTHENTICATED_OK", flush=True)
        return output
    if output.exists() or receipt.exists():
        raise RuntimeError("Incomplete recipient-panel checkpoint exists")
    connection = duckdb.connect()
    temp = state / "duckdb_temp/recipient"
    configure_duckdb(connection, payload, temp)
    paths = payload["stage07"]["paths"]
    panel_end = connection.execute(
        f"SELECT MAX(CAST(api_last_move_at_ms AS BIGINT)) "
        f"FROM read_parquet({path_list_literal(paths)}, union_by_name=true)"
    ).fetchone()[0]
    if panel_end is None:
        raise RuntimeError("Stage 07 has no valid follow-up endpoint")
    query = recipient_panel_sql(
        paths,
        Path(payload["a3_gate"]["private_cache"]),
        int(panel_end),
    )
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    print("RECIPIENT_PANEL_BUILD_BEGIN", flush=True)
    connection.execute(
        f"COPY ({query}) TO {sql_literal(temporary)} "
        "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)"
    )
    qa = connection.execute(
        f"""
        SELECT
          COUNT(*)::BIGINT AS rows,
          COUNT(DISTINCT cohort_row_id)::BIGINT AS unique_rows,
          COUNT(DISTINCT recipient_user_id)::BIGINT AS unique_recipients,
          COUNT(DISTINCT exposure_game_id)::BIGINT AS unique_exposures,
          SUM(CAST(received_mercy AS BIGINT))::BIGINT AS mercy,
          SUM(CAST(exposure_claimed_win AS BIGINT))::BIGINT AS claims,
          SUM(CAST(arm_eligible AS BIGINT))::BIGINT AS arm_eligible,
          SUM(CAST(exposure_no_mating_draw AS BIGINT))::BIGINT
            AS no_mating_draws,
          SUM(CAST(exposure_chooser_loss AS BIGINT))::BIGINT AS chooser_losses,
          COUNT(*) FILTER (
            WHERE arm_eligible IS DISTINCT FROM (
                    received_mercy OR exposure_claimed_win
                  )
               OR CAST(received_mercy AS INTEGER)
                + CAST(exposure_claimed_win AS INTEGER)
                + CAST(exposure_no_mating_draw AS INTEGER)
                + CAST(exposure_chooser_loss AS INTEGER) <> 1
               OR (
                    arm_eligible
                    AND CAST(received_mercy AS INTEGER)
                      + CAST(exposure_claimed_win AS INTEGER) <> 1
                  )
               OR (
                    NOT arm_eligible
                    AND CAST(exposure_no_mating_draw AS INTEGER)
                      + CAST(exposure_chooser_loss AS INTEGER) <> 1
                  )
          )::BIGINT AS invalid_arm_partition,
          COUNT(*) FILTER (
            WHERE exposure_cell_code < 0
               OR exposure_eval_band NOT BETWEEN 0 AND 7
               OR exposure_payoff_class NOT BETWEEN 0 AND 2
               OR exposure_gap_band NOT BETWEEN 0 AND 7
               OR exposure_speed_code NOT BETWEEN 0 AND 5
               OR exposure_month_code NOT BETWEEN 0 AND 23
          )::BIGINT AS invalid_cells,
          SUM(CAST(any_game_within_30d AS BIGINT))::BIGINT AS any_30d,
          COUNT(*) FILTER (WHERE log1p_games_within_30d IS NULL)::BIGINT
            AS missing_primary_a3,
          COUNT(*) FILTER (
            WHERE first_subsequent_kind_draw IS NOT NULL
              AND NOT reached_fair_chooser_within_90d
          )::BIGINT AS future_consistency_failures,
          SUM(CAST(a1_90d_followup_eligible AS BIGINT))::BIGINT AS a1_eligible,
          MAX(cohort_row_id)::BIGINT AS maximum_row_id
        FROM read_parquet({sql_literal(temporary)})
        """
    ).fetchone()
    connection.close()
    shutil.rmtree(temp, ignore_errors=True)
    rows, unique_rows, users, games = qa[:4]
    if (rows, unique_rows, users, games) != (
        EXPECTED_A3_PRIVATE_ROWS,
        EXPECTED_A3_PRIVATE_ROWS,
        EXPECTED_A3_PRIVATE_ROWS,
        EXPECTED_A3_PRIVATE_ROWS,
    ):
        raise RuntimeError(f"Recipient-panel identity QA failed: {qa}")
    if (
        qa[4] != EXPECTED_RECIPIENT_MERCY
        or qa[5] != EXPECTED_RECIPIENT_CLAIMED
        or qa[6] != EXPECTED_RECIPIENT_ARM_ELIGIBLE
        or qa[7] + qa[8] != EXPECTED_RECIPIENT_NONARM
    ):
        raise RuntimeError(f"Recipient treatment totals changed: {qa}")
    if qa[9] or qa[10] or qa[12] or qa[13] or qa[15] != rows - 1:
        raise RuntimeError(f"Recipient-panel hardened QA failed: {qa}")
    if qa[11] != 2_364_521:
        raise RuntimeError(f"A3 cache join changed the pooled 30-day total: {qa}")
    os.replace(temporary, output)
    saved = {
        "status": "DYNAMIC_RECIPIENT_PRIVATE_PANEL_OK",
        "created_utc": utc_now(),
        "resume_config_sha256": payload["resume_config_sha256"],
        "output_path": str(output),
        "output_sha256": sha256_file(output),
        "output_bytes": output.stat().st_size,
        "rows": rows,
        "mercy_recipients": qa[4],
        "claimed_recipients": qa[5],
        "arm_eligible_recipients": qa[6],
        "arm_ineligible_recipients": qa[7] + qa[8],
        "no_mating_draw_index_events": qa[7],
        "chooser_loss_index_events": qa[8],
        "index_reranked_after_arm_exclusion": False,
        "a1_90d_followup_eligible": qa[14],
        "raw_account_level_data": "PRIVATE; DO NOT COMMIT OR PUBLISH",
    }
    atomic_write_json(receipt, saved)
    print(f"RECIPIENT_PANEL_BUILD_OK rows={rows:,}", flush=True)
    return output


def arrow_int64(array: Any, np: Any, pa: Any) -> Any:
    import pyarrow.compute as pc  # type: ignore

    converted = pc.cast(array, pa.int64(), safe=True)
    if converted.null_count:
        converted = pc.fill_null(converted, pa.scalar(-1, type=pa.int64()))
    return np.asarray(converted.to_numpy(zero_copy_only=False), dtype=np.int64)


def build_pair_scan_lookups(
    recipient: Path, state: Path
) -> tuple[Any, Any, Any, Any, int, int, Path]:
    _, np, pa, pq = import_dependencies()
    table = pq.read_table(
        recipient,
        columns=[
            "cohort_row_id",
            "recipient_user_id",
            "exposure_chooser_user_id",
            "exposure_game_utc_ms",
        ],
    )
    row_ids = np.asarray(table["cohort_row_id"].to_numpy(), dtype=np.int64)
    recipients = np.asarray(table["recipient_user_id"].to_numpy(), dtype=np.int64)
    choosers = np.asarray(
        table["exposure_chooser_user_id"].to_numpy(), dtype=np.int64
    )
    game_times = np.asarray(table["exposure_game_utc_ms"].to_numpy(), dtype=np.int64)
    rows = row_ids.size
    if rows != EXPECTED_A3_PRIVATE_ROWS or not np.array_equal(
        row_ids, np.arange(rows, dtype=np.int64)
    ):
        raise RuntimeError("Recipient panel does not have the certified dense row order")
    if np.any(recipients < 0) or np.any(choosers < 0) or np.any(game_times <= 0):
        raise RuntimeError("Recipient pair-scan identifiers/times are invalid")
    maximum_user = int(max(recipients.max(), choosers.max()))
    if maximum_user > 100_000_000:
        raise RuntimeError(f"Implausible maximum global user ID: {maximum_user}")
    user_lookup = np.full(maximum_user + 1, -1, dtype=np.int32)
    user_lookup[recipients] = row_ids.astype(np.int32)
    low = np.minimum(recipients, choosers).astype(np.uint64)
    high = np.maximum(recipients, choosers).astype(np.uint64)
    keys = (low << np.uint64(PAIR_KEY_SHIFT)) | high
    unique_keys, inverse = np.unique(keys, return_inverse=True)
    mapping_path = state / "pair_index_private.parquet"
    mapping_receipt = state / "pair_index_receipt.json"
    if mapping_path.is_file() and mapping_receipt.is_file():
        saved = load_json(mapping_receipt)
        if saved.get("output_sha256") != sha256_file(mapping_path):
            raise RuntimeError("Pair-index checkpoint SHA mismatch")
        if safe_int(saved.get("rows")) != rows:
            raise RuntimeError("Pair-index checkpoint row count mismatch")
    elif mapping_path.exists() or mapping_receipt.exists():
        raise RuntimeError("Incomplete pair-index checkpoint exists")
    else:
        temporary = mapping_path.with_name(
            mapping_path.name + f".tmp.{uuid.uuid4().hex}"
        )
        pq.write_table(
            pa.table(
                {
                    "cohort_row_id": pa.array(row_ids, type=pa.int64()),
                    "pair_index": pa.array(inverse.astype(np.int32), type=pa.int32()),
                    "exposure_game_utc_ms": pa.array(game_times, type=pa.int64()),
                }
            ),
            temporary,
            compression="zstd",
            row_group_size=250_000,
        )
        os.replace(temporary, mapping_path)
        atomic_write_json(
            mapping_receipt,
            {
                "status": "DYNAMIC_PAIR_INDEX_PRIVATE_OK",
                "created_utc": utc_now(),
                "output_path": str(mapping_path),
                "output_sha256": sha256_file(mapping_path),
                "output_bytes": mapping_path.stat().st_size,
                "rows": rows,
                "unique_pairs": int(unique_keys.size),
                "raw_account_level_data": "PRIVATE; DO NOT COMMIT OR PUBLISH",
            },
        )
    return (
        user_lookup,
        game_times,
        unique_keys,
        inverse.astype(np.int32),
        rows,
        int(unique_keys.size),
        mapping_path,
    )


def update_pre_activity(
    *,
    event_ids: Any,
    event_times: Any,
    user_lookup: Any,
    exposure_game_times: Any,
    counts: Any,
    np: Any,
) -> int:
    valid = (event_ids >= 0) & (event_ids < user_lookup.size)
    if not np.any(valid):
        return 0
    ids = event_ids[valid]
    times = event_times[valid]
    rows = user_lookup[ids]
    target = rows >= 0
    if not np.any(target):
        return 0
    rows = rows[target]
    times = times[target]
    delta = exposure_game_times[rows] - times
    in_window = (delta > 0) & (delta <= HORIZON_30D_MS)
    if not np.any(in_window):
        return 0
    selected = rows[in_window]
    unique, frequency = np.unique(selected, return_counts=True)
    counts[unique] += frequency.astype(np.int32, copy=False)
    return int(selected.size)


def update_pair_minima(
    *,
    white_ids: Any,
    black_ids: Any,
    event_times: Any,
    sorted_pair_keys: Any,
    minima: Any,
    np: Any,
) -> int:
    valid = (white_ids >= 0) & (black_ids >= 0) & (white_ids != black_ids)
    if not np.any(valid):
        return 0
    white = white_ids[valid].astype(np.uint64, copy=False)
    black = black_ids[valid].astype(np.uint64, copy=False)
    times = event_times[valid]
    low = np.minimum(white, black)
    high = np.maximum(white, black)
    keys = (low << np.uint64(PAIR_KEY_SHIFT)) | high
    positions = np.searchsorted(sorted_pair_keys, keys)
    in_range = positions < sorted_pair_keys.size
    matched = in_range.copy()
    matched[in_range] &= sorted_pair_keys[positions[in_range]] == keys[in_range]
    if not np.any(matched):
        return 0
    np.minimum.at(minima, positions[matched], times[matched])
    return int(np.count_nonzero(matched))


def process_chronology_history_file(
    *,
    file_row: dict[str, Any],
    user_lookup: Any,
    exposure_game_times: Any,
    sorted_pair_keys: Any,
    cohort_rows: int,
    unique_pairs: int,
    activity_output: Path,
    pair_output: Path,
    batch_rows: int,
    parquet_use_threads: bool = True,
) -> dict[str, Any]:
    _, np, pa, pq = import_dependencies()
    path = Path(file_row["path"])
    parquet = pq.ParquetFile(path)
    if set(CHRONOLOGY_COLUMNS) - set(parquet.schema_arrow.names):
        raise RuntimeError(f"Chronology schema changed: {path}")
    pre_counts = np.zeros(cohort_rows, dtype=np.int32)
    pair_minima = np.full(unique_pairs, np.iinfo(np.int64).max, dtype=np.int64)
    scanned_rows = 0
    invalid_time_rows = 0
    pre_hits = 0
    pair_hits = 0
    for batch in parquet.iter_batches(
        batch_size=batch_rows,
        columns=list(CHRONOLOGY_COLUMNS),
        use_threads=parquet_use_threads,
    ):
        scanned_rows += batch.num_rows
        times = arrow_int64(batch.column(0), np, pa)
        white = arrow_int64(batch.column(1), np, pa)
        black = arrow_int64(batch.column(2), np, pa)
        invalid_time_rows += int(np.count_nonzero(times <= 0))
        valid_time = times > 0
        if not np.all(valid_time):
            times = times[valid_time]
            white = white[valid_time]
            black = black[valid_time]
        pre_hits += update_pre_activity(
            event_ids=white,
            event_times=times,
            user_lookup=user_lookup,
            exposure_game_times=exposure_game_times,
            counts=pre_counts,
            np=np,
        )
        pre_hits += update_pre_activity(
            event_ids=black,
            event_times=times,
            user_lookup=user_lookup,
            exposure_game_times=exposure_game_times,
            counts=pre_counts,
            np=np,
        )
        pair_hits += update_pair_minima(
            white_ids=white,
            black_ids=black,
            event_times=times,
            sorted_pair_keys=sorted_pair_keys,
            minima=pair_minima,
            np=np,
        )
    active_rows = np.flatnonzero(pre_counts > 0)
    active_pairs = np.flatnonzero(pair_minima < np.iinfo(np.int64).max)
    activity_temporary = activity_output.with_name(
        activity_output.name + f".tmp.{uuid.uuid4().hex}"
    )
    pair_temporary = pair_output.with_name(
        pair_output.name + f".tmp.{uuid.uuid4().hex}"
    )
    pq.write_table(
        pa.table(
            {
                "cohort_row_id": pa.array(active_rows, type=pa.int64()),
                "pre_games_30d": pa.array(pre_counts[active_rows], type=pa.int32()),
            }
        ),
        activity_temporary,
        compression="zstd",
        row_group_size=250_000,
    )
    pq.write_table(
        pa.table(
            {
                "pair_index": pa.array(active_pairs, type=pa.int32()),
                "first_pair_utc_ms": pa.array(pair_minima[active_pairs], type=pa.int64()),
            }
        ),
        pair_temporary,
        compression="zstd",
        row_group_size=250_000,
    )
    os.replace(activity_temporary, activity_output)
    os.replace(pair_temporary, pair_output)
    return {
        "status": "DYNAMIC_CHRONOLOGY_HISTORY_FILE_OK",
        "created_utc": utc_now(),
        "chronology_file_index": file_row["file_index"],
        "input_path": file_row["path"],
        "input_bytes": file_row["bytes"],
        "input_rows": file_row["rows"],
        "input_footer_signature_sha256": file_row["footer_signature_sha256"],
        "scanned_rows": scanned_rows,
        "invalid_event_time_rows_excluded": invalid_time_rows,
        "pre_activity_endpoint_hits": pre_hits,
        "focal_pair_event_hits": pair_hits,
        "activity_output_path": str(activity_output),
        "activity_output_rows": int(active_rows.size),
        "activity_output_bytes": activity_output.stat().st_size,
        "activity_output_sha256": sha256_file(activity_output),
        "pair_output_path": str(pair_output),
        "pair_output_rows": int(active_pairs.size),
        "pair_output_bytes": pair_output.stat().st_size,
        "pair_output_sha256": sha256_file(pair_output),
    }


def write_chronology_history_checkpoint(
    *,
    file_row: dict[str, Any],
    user_lookup: Any,
    exposure_game_times: Any,
    sorted_pair_keys: Any,
    cohort_rows: int,
    unique_pairs: int,
    activity_output: Path,
    pair_output: Path,
    receipt_output: Path,
    batch_rows: int,
    parquet_use_threads: bool,
) -> dict[str, Any]:
    """Build one independently resumable chronology checkpoint."""
    started = time.time()
    saved = process_chronology_history_file(
        file_row=file_row,
        user_lookup=user_lookup,
        exposure_game_times=exposure_game_times,
        sorted_pair_keys=sorted_pair_keys,
        cohort_rows=cohort_rows,
        unique_pairs=unique_pairs,
        activity_output=activity_output,
        pair_output=pair_output,
        batch_rows=batch_rows,
        parquet_use_threads=parquet_use_threads,
    )
    saved["runtime_seconds"] = time.time() - started
    saved["execution_mode"] = (
        "file_parallel_internal_parquet_threads_off"
        if not parquet_use_threads
        else "file_serial_internal_parquet_threads_on"
    )
    atomic_write_json(receipt_output, saved)
    return saved


def authenticate_history_checkpoint(
    file_row: dict[str, Any], activity: Path, pairs: Path, receipt: Path
) -> dict[str, Any] | None:
    present = (activity.exists(), pairs.exists(), receipt.exists())
    if not any(present):
        return None
    if not all(path.is_file() for path in (activity, pairs, receipt)):
        raise RuntimeError(
            f"Incomplete chronology-history checkpoint: {file_row['file_index']}"
        )
    saved = load_json(receipt)
    expected = {
        "status": "DYNAMIC_CHRONOLOGY_HISTORY_FILE_OK",
        "chronology_file_index": file_row["file_index"],
        "input_path": file_row["path"],
        "input_footer_signature_sha256": file_row["footer_signature_sha256"],
        "activity_output_path": str(activity),
        "pair_output_path": str(pairs),
    }
    for key, value in expected.items():
        if saved.get(key) != value:
            raise RuntimeError(f"History checkpoint metadata mismatch: {key}")
    for path, prefix in ((activity, "activity"), (pairs, "pair")):
        if path.stat().st_size != safe_int(saved.get(f"{prefix}_output_bytes")):
            raise RuntimeError(f"History checkpoint size mismatch: {path}")
        if sha256_file(path) != saved.get(f"{prefix}_output_sha256"):
            raise RuntimeError(f"History checkpoint SHA mismatch: {path}")
    return saved


def finalize_chronology_history(
    payload: dict[str, Any],
    state: Path,
    recipient: Path,
    mapping: Path,
    activity_paths: Sequence[Path],
    pair_paths: Sequence[Path],
    receipts: Sequence[dict[str, Any]],
) -> tuple[Path, dict[str, Any]]:
    duckdb, _, _, _ = import_dependencies()
    output = state / "chronology_pre_pair_private.parquet"
    receipt_path = state / "chronology_pre_pair_receipt.json"
    if output.is_file() and receipt_path.is_file():
        saved = load_json(receipt_path)
        if saved.get("output_sha256") != sha256_file(output):
            raise RuntimeError("Final chronology-history SHA mismatch")
        if safe_int(saved.get("rows")) != EXPECTED_A3_PRIVATE_ROWS:
            raise RuntimeError("Final chronology-history row count mismatch")
        print("CHRONOLOGY_HISTORY_ALREADY_CERTIFIED_OK", flush=True)
        return output, saved
    if output.exists() or receipt_path.exists():
        raise RuntimeError("Incomplete final chronology-history output exists")
    connection = duckdb.connect()
    temp = state / "duckdb_temp/history_finalize"
    configure_duckdb(connection, payload, temp)
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    connection.execute(
        f"""
        COPY (
          WITH activity AS (
            SELECT cohort_row_id, SUM(pre_games_30d)::BIGINT AS pre_games_30d
            FROM read_parquet({path_list_literal(activity_paths)}, union_by_name=true)
            GROUP BY cohort_row_id
          ), pairs AS (
            SELECT pair_index, MIN(first_pair_utc_ms)::BIGINT AS first_pair_utc_ms
            FROM read_parquet({path_list_literal(pair_paths)}, union_by_name=true)
            GROUP BY pair_index
          )
          SELECT
            r.cohort_row_id,
            COALESCE(a.pre_games_30d, 0)::INTEGER AS pre_games_30d,
            p.first_pair_utc_ms,
            (p.first_pair_utc_ms = r.exposure_game_utc_ms) AS first_ever_pair
          FROM read_parquet({sql_literal(recipient)}) r
          INNER JOIN read_parquet({sql_literal(mapping)}) m USING (cohort_row_id)
          LEFT JOIN activity a USING (cohort_row_id)
          LEFT JOIN pairs p USING (pair_index)
          ORDER BY r.cohort_row_id
        ) TO {sql_literal(temporary)}
        (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
        """
    )
    qa = connection.execute(
        f"""
        SELECT
          COUNT(*)::BIGINT,
          COUNT(DISTINCT cohort_row_id)::BIGINT,
          COUNT(*) FILTER (WHERE first_pair_utc_ms IS NULL)::BIGINT,
          COUNT(*) FILTER (
            WHERE first_pair_utc_ms > r.exposure_game_utc_ms
          )::BIGINT,
          SUM(CAST(first_ever_pair AS BIGINT))::BIGINT,
          AVG(CAST(pre_games_30d AS DOUBLE))::DOUBLE,
          MAX(pre_games_30d)::BIGINT
        FROM read_parquet({sql_literal(temporary)}) h
        INNER JOIN read_parquet({sql_literal(recipient)}) r USING (cohort_row_id)
        """
    ).fetchone()
    connection.close()
    shutil.rmtree(temp, ignore_errors=True)
    if qa[0] != EXPECTED_A3_PRIVATE_ROWS or qa[1] != EXPECTED_A3_PRIVATE_ROWS:
        raise RuntimeError(f"Chronology-history identity QA failed: {qa}")
    if qa[2] or qa[3]:
        raise RuntimeError(f"Chronology did not recover every exposure pair: {qa}")
    os.replace(temporary, output)
    saved = {
        "status": "DYNAMIC_CHRONOLOGY_PRE_PAIR_PRIVATE_OK",
        "created_utc": utc_now(),
        "resume_config_sha256": payload["resume_config_sha256"],
        "output_path": str(output),
        "output_sha256": sha256_file(output),
        "output_bytes": output.stat().st_size,
        "rows": qa[0],
        "first_ever_pair_rows": qa[4],
        "first_ever_pair_share": qa[4] / qa[0],
        "mean_pre_games_30d": qa[5],
        "maximum_pre_games_30d": qa[6],
        "chronology_files_authenticated": len(receipts),
        "chronology_rows_scanned": sum(row["scanned_rows"] for row in receipts),
        "parallel_execution": {
            "requested_workers": int(payload["chronology_workers"]),
            "parquet_internal_threads_per_worker": False,
            "checkpoint_aggregation_order": "ascending chronology_file_index",
        },
        "raw_account_level_data": "PRIVATE; DO NOT COMMIT OR PUBLISH",
    }
    atomic_write_json(receipt_path, saved)
    print(
        "CHRONOLOGY_HISTORY_CERTIFIED_OK "
        f"first_pair_rows={qa[4]:,} scanned_rows={saved['chronology_rows_scanned']:,}",
        flush=True,
    )
    return output, saved


def build_or_authenticate_chronology_history(
    payload: dict[str, Any], state: Path, recipient: Path
) -> tuple[Path, dict[str, Any]]:
    (
        user_lookup,
        exposure_game_times,
        unique_keys,
        _,
        cohort_rows,
        unique_pairs,
        mapping,
    ) = build_pair_scan_lookups(recipient, state)
    count = len(payload["chronology"])
    activity_paths = [
        state / "chronology_updates/activity" / f"file_{index:04d}.parquet"
        for index in range(count)
    ]
    pair_paths = [
        state / "chronology_updates/pairs" / f"file_{index:04d}.parquet"
        for index in range(count)
    ]
    receipt_paths = [
        state / "chronology_receipts" / f"file_{index:04d}.json"
        for index in range(count)
    ]
    receipts: list[dict[str, Any] | None] = [None] * count
    pending: list[int] = []
    for index, file_row in enumerate(payload["chronology"]):
        saved = authenticate_history_checkpoint(
            file_row,
            activity_paths[index],
            pair_paths[index],
            receipt_paths[index],
        )
        receipts[index] = saved
        if saved is None:
            pending.append(index)
    authenticated = count - len(pending)
    if authenticated:
        print(
            "CHRONOLOGY_HISTORY_RESUME_CHECKPOINTS_OK "
            f"authenticated_files={authenticated}/{count}",
            flush=True,
        )
    if pending:
        workers = min(int(payload["chronology_workers"]), len(pending))
        print(
            "CHRONOLOGY_HISTORY_PARALLEL_BEGIN "
            f"pending_files={len(pending)} workers={workers} "
            "parquet_internal_threads=off",
            flush=True,
        )
        future_to_index: dict[Any, int] = {}
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="chronology",
        ) as executor:
            for index in pending:
                future = executor.submit(
                    write_chronology_history_checkpoint,
                    file_row=payload["chronology"][index],
                    user_lookup=user_lookup,
                    exposure_game_times=exposure_game_times,
                    sorted_pair_keys=unique_keys,
                    cohort_rows=cohort_rows,
                    unique_pairs=unique_pairs,
                    activity_output=activity_paths[index],
                    pair_output=pair_paths[index],
                    receipt_output=receipt_paths[index],
                    batch_rows=payload["batch_rows"],
                    parquet_use_threads=False,
                )
                future_to_index[future] = index
            completed = authenticated
            for future in concurrent.futures.as_completed(future_to_index):
                index = future_to_index[future]
                saved = future.result()
                receipts[index] = saved
                completed += 1
                if completed % 10 == 0 or completed == count:
                    print(
                        "CHRONOLOGY_HISTORY_PROGRESS "
                        f"completed_files={completed}/{count} "
                        f"last_file={index:04d} "
                        f"last_rows={saved['scanned_rows']:,}",
                        flush=True,
                    )
    if any(saved is None for saved in receipts):
        raise RuntimeError("Chronology parallel scheduler left missing checkpoints")
    ordered_receipts = [saved for saved in receipts if saved is not None]
    if len(ordered_receipts) != count:
        raise RuntimeError("Chronology checkpoint count mismatch after scheduling")
    if not pending:
        if count:
            print(
                "CHRONOLOGY_HISTORY_ALL_FILE_CHECKPOINTS_AUTHENTICATED_OK "
                f"completed_files={count}/{count}",
                flush=True,
            )
    del user_lookup, exposure_game_times, unique_keys
    return finalize_chronology_history(
        payload,
        state,
        recipient,
        mapping,
        activity_paths,
        pair_paths,
        ordered_receipts,
    )


def materialize_joined_recipient_panel(
    payload: dict[str, Any], state: Path, recipient: Path, history: Path
) -> Path:
    """Join the two authenticated private row-aligned recipient sources."""
    duckdb, _, _, _ = import_dependencies()
    output = state / "recipient_with_chronology_private.parquet"
    receipt = state / "recipient_with_chronology_receipt.json"
    if output.is_file() and receipt.is_file():
        saved = load_json(receipt)
        if saved.get("output_sha256") != sha256_file(output):
            raise RuntimeError("Joined-recipient checkpoint SHA mismatch")
        if saved.get("resume_config_sha256") != payload["resume_config_sha256"]:
            raise RuntimeError("Joined-recipient checkpoint config mismatch")
        if safe_int(saved.get("rows")) != EXPECTED_A3_PRIVATE_ROWS:
            raise RuntimeError("Joined-recipient checkpoint row count mismatch")
        print("JOINED_RECIPIENT_CHECKPOINT_AUTHENTICATED_OK", flush=True)
        return output
    if output.exists() or receipt.exists():
        raise RuntimeError("Incomplete joined-recipient checkpoint exists")
    connection = duckdb.connect()
    temp = state / "duckdb_temp/recipient_join"
    configure_duckdb(connection, payload, temp)
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    connection.execute(
        f"""
        COPY (
          SELECT
            r.*,
            h.pre_games_30d,
            h.first_pair_utc_ms,
            h.first_ever_pair
          FROM read_parquet({sql_literal(recipient)}) r
          INNER JOIN read_parquet({sql_literal(history)}) h USING (cohort_row_id)
          ORDER BY r.cohort_row_id
        ) TO {sql_literal(temporary)}
        (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
        """
    )
    qa = connection.execute(
        f"""
        SELECT
          COUNT(*)::BIGINT,
          COUNT(DISTINCT cohort_row_id)::BIGINT,
          MIN(cohort_row_id)::BIGINT,
          MAX(cohort_row_id)::BIGINT,
          SUM(CAST(first_ever_pair AS BIGINT))::BIGINT,
          COUNT(*) FILTER (WHERE first_pair_utc_ms IS NULL)::BIGINT
        FROM read_parquet({sql_literal(temporary)})
        """
    ).fetchone()
    connection.close()
    shutil.rmtree(temp, ignore_errors=True)
    if qa[0:4] != (
        EXPECTED_A3_PRIVATE_ROWS,
        EXPECTED_A3_PRIVATE_ROWS,
        0,
        EXPECTED_A3_PRIVATE_ROWS - 1,
    ) or qa[5]:
        raise RuntimeError(f"Joined-recipient hardened QA failed: {qa}")
    os.replace(temporary, output)
    atomic_write_json(
        receipt,
        {
            "status": "DYNAMIC_JOINED_RECIPIENT_PRIVATE_OK",
            "created_utc": utc_now(),
            "resume_config_sha256": payload["resume_config_sha256"],
            "output_path": str(output),
            "output_sha256": sha256_file(output),
            "output_bytes": output.stat().st_size,
            "rows": qa[0],
            "first_ever_pair_rows": qa[4],
            "raw_account_level_data": "PRIVATE; DO NOT COMMIT OR PUBLISH",
        },
    )
    print(
        f"JOINED_RECIPIENT_PRIVATE_OK rows={qa[0]:,} first_pairs={qa[4]:,}",
        flush=True,
    )
    return output


NULLABLE_BOOLEAN_OUTCOMES = {
    "first_subsequent_kind_draw",
    "decay_6h_kind",
    "decay_1d_kind",
    "decay_7d_kind",
    "decay_30d_kind",
    "decay_90d_kind",
}


def arrow_column_numpy(table: Any, name: str, np: Any, pa: Any) -> Any:
    """Convert a nullable Arrow column to a stable NumPy representation."""
    import pyarrow.compute as pc  # type: ignore

    column = table[name].combine_chunks()
    if pa.types.is_boolean(column.type) and name in NULLABLE_BOOLEAN_OUTCOMES:
        column = pc.cast(column, pa.float64(), safe=True)
        column = pc.fill_null(column, pa.scalar(float("nan"), type=pa.float64()))
        return np.asarray(column.to_numpy(zero_copy_only=False), dtype=np.float64)
    if pa.types.is_boolean(column.type):
        column = pc.fill_null(column, pa.scalar(False, type=pa.bool_()))
        return np.asarray(column.to_numpy(zero_copy_only=False), dtype=np.bool_)
    if pa.types.is_integer(column.type):
        column = pc.cast(column, pa.int64(), safe=True)
        column = pc.fill_null(column, pa.scalar(-1, type=pa.int64()))
        return np.asarray(column.to_numpy(zero_copy_only=False), dtype=np.int64)
    column = pc.cast(column, pa.float64(), safe=True)
    column = pc.fill_null(column, pa.scalar(float("nan"), type=pa.float64()))
    return np.asarray(column.to_numpy(zero_copy_only=False), dtype=np.float64)


RECIPIENT_NUMERIC_COLUMNS = (
    "cohort_row_id",
    "recipient_user_id",
    "exposure_chooser_user_id",
    "received_mercy",
    "exposure_claimed_win",
    "arm_eligible",
    "exposure_no_mating_draw",
    "exposure_chooser_loss",
    "first_ever_pair",
    "a1_90d_followup_eligible",
    "exposure_cell_code",
    "exposure_month_code",
    "exposure_eval_cp",
    "exposure_draw_payoff",
    "exposure_win_premium",
    "exposure_chooser_elo",
    "exposure_recipient_elo",
    "exposure_chooser_rd",
    "exposure_recipient_rd",
    "exposure_chooser_clock_s",
    "exposure_recipient_clock_s",
    "exposure_ply_count",
    "exposure_material_advantage",
    "exposure_tc_base_s",
    "exposure_tc_inc_s",
    "exposure_speed_code",
    "recipient_prior_fair_opportunities_90d",
    "recipient_prior_kind_draws_90d",
    "recipient_prior_kind_rate_90d",
    "recipient_prior_rating_change_90d",
    "recipient_prior_disconnections_main_sample",
    "recipient_prior_mercy_receipts_main_sample",
    "pre_games_30d",
    "encouragement_prior_pair_excluded_n",
    "encouragement_pair_excluded_propensity",
    "reached_fair_chooser_within_90d",
    "any_fair_kind_grant_within_90d",
    "first_subsequent_kind_draw",
    "first_subsequent_delta_ms",
    "first_subsequent_eval_cp",
    "first_subsequent_draw_payoff",
    "first_subsequent_win_premium",
    "first_subsequent_chooser_clock_s",
    "first_subsequent_opponent_clock_s",
    "first_subsequent_chooser_elo",
    "first_subsequent_opponent_elo",
    "first_subsequent_chooser_rd",
    "first_subsequent_opponent_rd",
    "first_subsequent_speed_code",
    "first_subsequent_tournament_like",
    "first_subsequent_month_code",
    "decay_6h_kind",
    "decay_1d_kind",
    "decay_7d_kind",
    "decay_30d_kind",
    "decay_90d_kind",
    "any_game_within_10m",
    "any_game_within_30m",
    "any_game_within_60m",
    "any_game_within_7d",
    "any_game_within_30d",
    "games_within_7d",
    "games_within_30d",
    "log1p_games_within_30d",
    "recipient_future_disconnections_90d",
    "recipient_future_mercy_receipts_90d",
)


def load_recipient_arrays(path: Path) -> dict[str, Any]:
    _, np, pa, pq = import_dependencies()
    table = pq.read_table(path, columns=list(RECIPIENT_NUMERIC_COLUMNS))
    arrays = {
        name: arrow_column_numpy(table, name, np, pa)
        for name in RECIPIENT_NUMERIC_COLUMNS
    }
    row_ids = arrays["cohort_row_id"]
    if row_ids.size != EXPECTED_A3_PRIVATE_ROWS or not np.array_equal(
        row_ids, np.arange(row_ids.size, dtype=np.int64)
    ):
        raise RuntimeError("Loaded recipient arrays lost the certified dense row order")
    return arrays


def common_support_weights(data: dict[str, Any]) -> dict[str, Any]:
    _, np, _, _ = import_dependencies()
    first = data["first_ever_pair"].astype(bool)
    arm = data["arm_eligible"].astype(bool)
    treatment = data["received_mercy"].astype(bool)
    cell = data["exposure_cell_code"].astype(np.int64)
    no_mating = data["exposure_no_mating_draw"].astype(bool)
    chooser_loss = data["exposure_chooser_loss"].astype(bool)
    partition = (
        int(np.count_nonzero(treatment)),
        int(np.count_nonzero(data["exposure_claimed_win"].astype(bool))),
        int(np.count_nonzero(arm)),
        int(np.count_nonzero(~arm)),
    )
    expected = (
        EXPECTED_RECIPIENT_MERCY,
        EXPECTED_RECIPIENT_CLAIMED,
        EXPECTED_RECIPIENT_ARM_ELIGIBLE,
        EXPECTED_RECIPIENT_NONARM,
    )
    if partition != expected or not np.array_equal(~arm, no_mating | chooser_loss):
        raise RuntimeError(
            f"Recipient arm-partition checkpoint changed: {partition}"
        )
    valid = first & arm & (cell >= 0)
    number_cells = 8 * 3 * 8 * 6
    treated_counts = np.bincount(
        cell[valid & treatment], minlength=number_cells
    ).astype(np.int64)
    control_counts = np.bincount(
        cell[valid & ~treatment], minlength=number_cells
    ).astype(np.int64)
    eligible_cells = (treated_counts >= 5) & (control_counts >= 20)
    eligible = valid & eligible_cells[cell]
    first_treated = int(np.count_nonzero(valid & treatment))
    retained_treated = int(np.count_nonzero(eligible & treatment))
    retention = retained_treated / first_treated if first_treated else 0.0
    if retention < 0.90:
        raise RuntimeError(
            f"Frozen common-support design retained only {retention:.6f} of mercy"
        )
    weights = np.zeros(treatment.size, dtype=np.float64)
    weights[eligible & treatment] = 1.0
    control_rows = eligible & ~treatment
    weights[control_rows] = (
        treated_counts[cell[control_rows]] / control_counts[cell[control_rows]]
    )
    cell_rows: list[dict[str, Any]] = []
    for code in np.flatnonzero(eligible_cells):
        cell_rows.append(
            {
                "exposure_cell_code": int(code),
                "eval_band_code": int(code // (3 * 8 * 6)),
                "payoff_class_code": int((code // (8 * 6)) % 3),
                "rating_gap_band_code": int((code // 6) % 8),
                "speed_code": int(code % 6),
                "mercy_recipients": int(treated_counts[code]),
                "claimed_recipients": int(control_counts[code]),
                "control_att_weight": float(
                    treated_counts[code] / control_counts[code]
                ),
            }
        )
    return {
        "eligible": eligible,
        "weights": weights,
        "eligible_cells": int(np.count_nonzero(eligible_cells)),
        "recipient_index_rows": int(treatment.size),
        "recipient_arm_eligible_rows": int(np.count_nonzero(arm)),
        "recipient_arm_ineligible_rows": int(np.count_nonzero(~arm)),
        "recipient_no_mating_draw_rows": int(
            np.count_nonzero(no_mating)
        ),
        "recipient_chooser_loss_rows": int(
            np.count_nonzero(chooser_loss)
        ),
        "recipient_arm_rule": "kind draw versus chooser win at fixed first index event",
        "index_reranked_after_arm_exclusion": False,
        "first_pair_rows": int(np.count_nonzero(valid)),
        "first_pair_mercy": first_treated,
        "first_pair_claimed": int(np.count_nonzero(valid & ~treatment)),
        "retained_rows": int(np.count_nonzero(eligible)),
        "retained_mercy": retained_treated,
        "retained_claimed": int(np.count_nonzero(eligible & ~treatment)),
        "mercy_retention_share": retention,
        "cell_rows": cell_rows,
    }


EXPOSURE_CONTROLS = (
    "exposure_eval_cp",
    "exposure_draw_payoff",
    "exposure_win_premium",
    "exposure_chooser_elo",
    "exposure_recipient_elo",
    "exposure_chooser_rd",
    "exposure_recipient_rd",
    "exposure_chooser_clock_s",
    "exposure_recipient_clock_s",
    "exposure_ply_count",
    "exposure_material_advantage",
    "exposure_tc_base_s",
    "exposure_tc_inc_s",
)

PRE_EXPOSURE_BALANCE_FIELDS = (
    "recipient_prior_fair_opportunities_90d",
    "recipient_prior_kind_draws_90d",
    "recipient_prior_kind_rate_90d",
    "recipient_prior_rating_change_90d",
    "recipient_prior_disconnections_main_sample",
    "recipient_prior_mercy_receipts_main_sample",
    "pre_games_30d",
)

SUBSEQUENT_CONTROLS = (
    "first_subsequent_eval_cp",
    "first_subsequent_draw_payoff",
    "first_subsequent_win_premium",
    "first_subsequent_chooser_clock_s",
    "first_subsequent_opponent_clock_s",
    "first_subsequent_chooser_elo",
    "first_subsequent_opponent_elo",
    "first_subsequent_chooser_rd",
    "first_subsequent_opponent_rd",
    "first_subsequent_delta_ms",
)


def flexible_numeric_controls(
    data: dict[str, Any], indices: Any, fields: Sequence[str]
) -> tuple[Any, list[str]]:
    _, np, _, _ = import_dependencies()
    columns: list[Any] = []
    names: list[str] = []
    for field in fields:
        raw = np.asarray(data[field][indices], dtype=np.float64)
        missing = ~np.isfinite(raw)
        observed = raw[~missing]
        if observed.size == 0:
            continue
        median = float(np.median(observed))
        filled = raw.copy()
        filled[missing] = median
        mean = float(np.mean(filled))
        scale = float(np.std(filled))
        if not math.isfinite(scale) or scale <= 1e-12:
            z = np.zeros(filled.size, dtype=np.float64)
        else:
            z = (filled - mean) / scale
        columns.extend((z, z * z - float(np.mean(z * z))))
        names.extend((f"{field}_z", f"{field}_z2"))
        if np.any(missing):
            columns.append(missing.astype(np.float64))
            names.append(f"{field}_missing")
    if not columns:
        return np.empty((indices.size, 0), dtype=np.float64), []
    return np.column_stack(columns), names


def categorical_controls(
    data: dict[str, Any], indices: Any, fields: Sequence[str]
) -> tuple[Any, list[str]]:
    _, np, _, _ = import_dependencies()
    columns: list[Any] = []
    names: list[str] = []
    for field in fields:
        values = np.asarray(data[field][indices], dtype=np.int64)
        categories = np.unique(values)
        if categories.size <= 1:
            continue
        reference = int(categories[0])
        for category in categories[1:]:
            columns.append((values == category).astype(np.float64))
            names.append(f"{field}_{int(category)}_vs_{reference}")
    if not columns:
        return np.empty((indices.size, 0), dtype=np.float64), []
    return np.column_stack(columns), names


def weighted_absorb(
    matrix: Any,
    weights: Any,
    fixed_effects: Sequence[Any],
    *,
    tolerance: float = 1e-10,
    maximum_iterations: int = 2_000,
) -> tuple[Any, int, float]:
    """Weighted alternating projections for two low-dimensional fixed effects."""
    _, np, _, _ = import_dependencies()
    transformed = np.asarray(matrix, dtype=np.float64).copy()
    w = np.asarray(weights, dtype=np.float64)
    if np.any(~np.isfinite(transformed)) or np.any(~np.isfinite(w)) or np.any(w <= 0):
        raise RuntimeError("Nonfinite matrix or invalid weights reached FE absorption")
    prepared: list[tuple[Any, int, Any]] = []
    for values in fixed_effects:
        _, codes = np.unique(np.asarray(values), return_inverse=True)
        groups = int(codes.max()) + 1
        denominator = np.bincount(codes, weights=w, minlength=groups)
        if np.any(denominator <= 0):
            raise RuntimeError("Empty fixed-effect level reached absorption")
        prepared.append((codes, groups, denominator))
    last = math.inf
    for iteration in range(1, maximum_iterations + 1):
        last = 0.0
        for codes, groups, denominator in prepared:
            for column in range(transformed.shape[1]):
                numerator = np.bincount(
                    codes,
                    weights=w * transformed[:, column],
                    minlength=groups,
                )
                adjustment = numerator / denominator
                last = max(last, float(np.max(np.abs(adjustment))))
                transformed[:, column] -= adjustment[codes]
        if last <= tolerance:
            return transformed, iteration, last
    raise RuntimeError(
        "Fixed-effect absorption did not converge: "
        f"iterations={maximum_iterations} last_adjustment={last:.3e}"
    )


def sample_fingerprint(row_ids: Any, specification: dict[str, Any]) -> str:
    _, np, _, _ = import_dependencies()
    digest = hashlib.sha256()
    digest.update(np.asarray(row_ids, dtype="<i8").tobytes(order="C"))
    digest.update(canonical_json(specification).encode("utf-8"))
    return digest.hexdigest()


def fit_weighted_cluster_model(
    *,
    outcome: Any,
    treatment: Any,
    controls: Any,
    control_names: Sequence[str],
    weights: Any,
    cell_fe: Any,
    month_fe: Any,
    clusters: Any,
    row_ids: Any,
    specification: dict[str, Any],
    binary_outcome: bool,
) -> dict[str, Any]:
    _, np, _, _ = import_dependencies()
    y = np.asarray(outcome, dtype=np.float64)
    treatment = np.asarray(treatment, dtype=np.float64)
    x = np.column_stack([treatment, controls])
    transformed, iterations, last = weighted_absorb(
        np.column_stack([y, x]), weights, (cell_fe, month_fe)
    )
    y_resid = transformed[:, 0]
    x_resid = transformed[:, 1:]
    weighted_x = x_resid * np.sqrt(weights)[:, None]
    weighted_y = y_resid * np.sqrt(weights)
    beta, _, rank, singular = np.linalg.lstsq(weighted_x, weighted_y, rcond=None)
    if int(rank) != x_resid.shape[1]:
        raise RuntimeError(
            f"Model matrix is rank deficient: {rank}/{x_resid.shape[1]}"
        )
    residual = y_resid - x_resid @ beta
    bread = np.linalg.inv(weighted_x.T @ weighted_x)
    _, cluster_codes = np.unique(np.asarray(clusters), return_inverse=True)
    groups = int(cluster_codes.max()) + 1
    scores = np.empty((groups, x_resid.shape[1]), dtype=np.float64)
    score_weight = weights * residual
    for column in range(x_resid.shape[1]):
        scores[:, column] = np.bincount(
            cluster_codes,
            weights=score_weight * x_resid[:, column],
            minlength=groups,
        )
    meat = scores.T @ scores
    correction = 1.0
    if groups > 1 and y.size > int(rank):
        correction = (groups / (groups - 1)) * ((y.size - 1) / (y.size - rank))
    variance = bread @ meat @ bread * correction
    standard_errors = np.sqrt(np.maximum(np.diag(variance), 0.0))
    coefficient = float(beta[0])
    standard_error = float(standard_errors[0])
    t_value = coefficient / standard_error if standard_error > 0 else math.nan
    treated = treatment > 0.5
    mean_treated = float(np.average(y[treated], weights=weights[treated]))
    mean_control = float(np.average(y[~treated], weights=weights[~treated]))
    result = {
        **specification,
        "rows": int(y.size),
        "clusters": groups,
        "treated_rows": int(np.count_nonzero(treated)),
        "control_rows": int(np.count_nonzero(~treated)),
        "coefficient": coefficient,
        "standard_error": standard_error,
        "t_value": t_value,
        "p_value_raw": normal_two_sided_p(t_value),
        "weighted_treated_mean": mean_treated,
        "weighted_control_mean": mean_control,
        "effect_relative_to_control_mean": (
            coefficient / mean_control if abs(mean_control) > 1e-15 else None
        ),
        "coefficient_percentage_points": coefficient * 100 if binary_outcome else None,
        "standard_error_percentage_points": standard_error * 100
        if binary_outcome
        else None,
        "matrix_rank": int(rank),
        "smallest_singular_value": float(singular[-1]),
        "absorption_iterations": iterations,
        "absorption_last_adjustment": last,
        "cluster_correction": correction,
        "sample_specification_sha256": sample_fingerprint(row_ids, specification),
        "control_count": len(control_names),
        "control_names": list(control_names),
    }
    return result


def model_controls(
    data: dict[str, Any], indices: Any, *, state_conditioned: bool
) -> tuple[Any, list[str]]:
    _, np, _, _ = import_dependencies()
    base, base_names = flexible_numeric_controls(data, indices, EXPOSURE_CONTROLS)
    if not state_conditioned:
        return base, base_names
    later, later_names = flexible_numeric_controls(data, indices, SUBSEQUENT_CONTROLS)
    categories, category_names = categorical_controls(
        data,
        indices,
        (
            "first_subsequent_speed_code",
            "first_subsequent_tournament_like",
            "first_subsequent_month_code",
        ),
    )
    return (
        np.column_stack([base, later, categories]),
        [*base_names, *later_names, *category_names],
    )


def fit_recipient_outcome(
    *,
    data: dict[str, Any],
    support: dict[str, Any],
    outcome_name: str,
    sample: Any,
    estimand: str,
    state_conditioned: bool,
    binary_outcome: bool,
) -> dict[str, Any]:
    _, np, _, _ = import_dependencies()
    outcome_all = np.asarray(data[outcome_name], dtype=np.float64)
    sample = np.asarray(sample, dtype=bool) & support["eligible"]
    sample &= np.isfinite(outcome_all)
    indices = np.flatnonzero(sample)
    if indices.size < 100 or np.unique(data["received_mercy"][indices]).size != 2:
        raise RuntimeError(f"Insufficient support for recipient outcome: {outcome_name}")
    controls, names = model_controls(
        data, indices, state_conditioned=state_conditioned
    )
    a3_outcomes = {
        "log1p_games_within_30d",
        "any_game_within_30d",
        "games_within_30d",
        "any_game_within_7d",
        "games_within_7d",
        "any_game_within_10m",
        "any_game_within_30m",
        "any_game_within_60m",
    }
    specification = {
        "analysis": "A3" if outcome_name in a3_outcomes else "A1",
        "outcome": outcome_name,
        "estimand": estimand,
        "state_conditioned": state_conditioned,
        "exposure_common_support": "n_mercy>=5 and n_claimed>=20",
        "standardization": "ATT-style exposure-cell weights",
        "fixed_effects": "exposure cell and exposure month",
        "cluster": "exposure chooser",
    }
    return fit_weighted_cluster_model(
        outcome=outcome_all[indices],
        treatment=data["received_mercy"][indices],
        controls=controls,
        control_names=names,
        weights=support["weights"][indices],
        cell_fe=data["exposure_cell_code"][indices],
        month_fe=data["exposure_month_code"][indices],
        clusters=data["exposure_chooser_user_id"][indices],
        row_ids=data["cohort_row_id"][indices],
        specification=specification,
        binary_outcome=binary_outcome,
    )


def fit_encouragement_model(
    *,
    data: dict[str, Any],
    support: dict[str, Any],
    outcome_name: str,
    sample: Any,
    label: str,
    binary_outcome: bool,
) -> dict[str, Any]:
    """Corroborating reduced-form association using pair-excluded prior kindness."""
    _, np, _, _ = import_dependencies()
    z_all = np.asarray(
        data["encouragement_pair_excluded_propensity"], dtype=np.float64
    )
    y_all = np.asarray(data[outcome_name], dtype=np.float64)
    sample = (
        np.asarray(sample, dtype=bool)
        & support["eligible"]
        & np.isfinite(z_all)
        & np.isfinite(y_all)
        & (data["encouragement_prior_pair_excluded_n"] >= 10)
    )
    indices = np.flatnonzero(sample)
    if indices.size < 100:
        raise RuntimeError(f"Insufficient pair-excluded encouragement support: {label}")
    controls, names = model_controls(data, indices, state_conditioned=False)
    specification = {
        "analysis": "A1_encouragement",
        "outcome": outcome_name,
        "estimand": label,
        "predictor": "encountered chooser prior pair-excluded kindness propensity",
        "predictor_history_minimum": 10,
        "exclusion_claim": "not assumed; corroborating evidence only",
        "state_conditioned": False,
        "exposure_common_support": "n_mercy>=5 and n_claimed>=20",
        "standardization": "ATT-style exposure-cell weights",
        "fixed_effects": "exposure cell and exposure month",
        "cluster": "exposure chooser",
    }
    result = fit_weighted_cluster_model(
        outcome=y_all[indices],
        treatment=z_all[indices],
        controls=controls,
        control_names=names,
        weights=support["weights"][indices],
        cell_fe=data["exposure_cell_code"][indices],
        month_fe=data["exposure_month_code"][indices],
        clusters=data["exposure_chooser_user_id"][indices],
        row_ids=data["cohort_row_id"][indices],
        specification=specification,
        binary_outcome=binary_outcome,
    )
    for key in (
        "treated_rows",
        "control_rows",
        "weighted_treated_mean",
        "weighted_control_mean",
        "effect_relative_to_control_mean",
    ):
        result.pop(key, None)
    result["predictor_minimum"] = float(np.min(z_all[indices]))
    result["predictor_maximum"] = float(np.max(z_all[indices]))
    result["coefficient_interpretation"] = "outcome units per 1.0 prior-kindness rate"
    return result


def weighted_moments(values: Any, weights: Any) -> tuple[float, float]:
    _, np, _, _ = import_dependencies()
    values = np.asarray(values, dtype=np.float64)
    weights = np.asarray(weights, dtype=np.float64)
    valid = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    if not np.any(valid):
        return math.nan, math.nan
    values = values[valid]
    weights = weights[valid]
    mean = float(np.average(values, weights=weights))
    variance = float(np.average((values - mean) ** 2, weights=weights))
    return mean, variance


def balance_rows(data: dict[str, Any], support: dict[str, Any]) -> list[dict[str, Any]]:
    _, np, _, _ = import_dependencies()
    treatment = data["received_mercy"].astype(bool)
    first = (
        data["first_ever_pair"].astype(bool)
        & data["arm_eligible"].astype(bool)
    )
    adjusted = support["eligible"]
    fields = (*EXPOSURE_CONTROLS, *PRE_EXPOSURE_BALANCE_FIELDS)
    output: list[dict[str, Any]] = []
    for field in fields:
        values = np.asarray(data[field], dtype=np.float64)
        for label, mask, weights in (
            ("unadjusted_first_pair", first, np.ones(values.size)),
            ("att_common_support", adjusted, support["weights"]),
        ):
            m1, v1 = weighted_moments(
                values[mask & treatment], weights[mask & treatment]
            )
            m0, v0 = weighted_moments(
                values[mask & ~treatment], weights[mask & ~treatment]
            )
            denominator = math.sqrt(max((v1 + v0) / 2, 0.0))
            smd = (m1 - m0) / denominator if denominator > 0 else math.nan
            output.append(
                {
                    "adjustment": label,
                    "field": field,
                    "mercy_mean": m1,
                    "claimed_mean": m0,
                    "standardized_mean_difference": smd,
                    "absolute_standardized_mean_difference": abs(smd),
                    "mercy_nonmissing": int(
                        np.count_nonzero(mask & treatment & np.isfinite(values))
                    ),
                    "claimed_nonmissing": int(
                        np.count_nonzero(mask & ~treatment & np.isfinite(values))
                    ),
                }
            )
    return output


def estimate_recipient_analyses(
    data: dict[str, Any], support: dict[str, Any]
) -> dict[str, Any]:
    _, np, _, _ = import_dependencies()
    first = (
        data["first_ever_pair"].astype(bool)
        & data["arm_eligible"].astype(bool)
    )
    followup = data["a1_90d_followup_eligible"].astype(bool)
    reached = data["reached_fair_chooser_within_90d"].astype(bool)
    conditional_choice = first & followup & reached
    full_a1 = first & followup
    models: list[dict[str, Any]] = []
    models.append(
        fit_recipient_outcome(
            data=data,
            support=support,
            outcome_name="first_subsequent_kind_draw",
            sample=conditional_choice,
            estimand="primary_total_path_conditional_choice",
            state_conditioned=False,
            binary_outcome=True,
        )
    )
    models.append(
        fit_recipient_outcome(
            data=data,
            support=support,
            outcome_name="first_subsequent_kind_draw",
            sample=conditional_choice,
            estimand="mandatory_state_conditioned_conditional_choice",
            state_conditioned=True,
            binary_outcome=True,
        )
    )
    for outcome, estimand in (
        ("reached_fair_chooser_within_90d", "mandatory_reach_companion"),
        ("any_fair_kind_grant_within_90d", "mandatory_unconditional_kind_companion"),
        ("recipient_future_mercy_receipts_90d", "natural_path_crossover_count"),
    ):
        models.append(
            fit_recipient_outcome(
                data=data,
                support=support,
                outcome_name=outcome,
                sample=full_a1,
                estimand=estimand,
                state_conditioned=False,
                binary_outcome=outcome != "recipient_future_mercy_receipts_90d",
            )
        )
    decay: list[dict[str, Any]] = []
    for outcome, label in (
        ("decay_6h_kind", "same_session_le_6h"),
        ("decay_1d_kind", "gt_6h_to_1d"),
        ("decay_7d_kind", "gt_1d_to_7d"),
        ("decay_30d_kind", "gt_7d_to_30d"),
        ("decay_90d_kind", "gt_30d_to_90d"),
    ):
        row = fit_recipient_outcome(
            data=data,
            support=support,
            outcome_name=outcome,
            sample=full_a1,
            estimand=f"descriptive_decay_{label}",
            state_conditioned=False,
            binary_outcome=True,
        )
        decay.append(row)
    a3: list[dict[str, Any]] = []
    for outcome, label, binary in (
        ("log1p_games_within_30d", "primary_blinded_ceiling_selected", False),
        ("any_game_within_30d", "mandatory_binary_30d", True),
        ("games_within_30d", "mandatory_raw_count_30d", False),
        ("any_game_within_7d", "secondary_binary_7d", True),
        ("games_within_7d", "secondary_raw_count_7d", False),
        ("any_game_within_10m", "secondary_reentry_10m", True),
        ("any_game_within_30m", "secondary_reentry_30m", True),
        ("any_game_within_60m", "secondary_reentry_60m", True),
    ):
        a3.append(
            fit_recipient_outcome(
                data=data,
                support=support,
                outcome_name=outcome,
                sample=first,
                estimand=label,
                state_conditioned=False,
                binary_outcome=binary,
            )
        )
    encouragement = [
        fit_encouragement_model(
            data=data,
            support=support,
            outcome_name="received_mercy",
            sample=first,
            label="encouragement_first_stage_mercy_receipt",
            binary_outcome=True,
        ),
        fit_encouragement_model(
            data=data,
            support=support,
            outcome_name="first_subsequent_kind_draw",
            sample=conditional_choice,
            label="encouragement_reduced_form_a1_total_path",
            binary_outcome=True,
        ),
        fit_encouragement_model(
            data=data,
            support=support,
            outcome_name="log1p_games_within_30d",
            sample=first,
            label="encouragement_reduced_form_a3_engagement",
            binary_outcome=False,
        ),
    ]
    return {
        "a1_models": models,
        "a1_decay": decay,
        "a3_models": a3,
        "encouragement": encouragement,
        "balance": balance_rows(data, support),
    }


B1_CONTINUOUS_FIELDS = (
    "current_eval_cp",
    "current_draw_payoff",
    "current_win_premium",
    "current_chooser_elo",
    "current_opponent_elo",
    "current_chooser_rd",
    "current_opponent_rd",
    "current_chooser_clock_s",
    "current_opponent_clock_s",
    "current_ply_count",
    "current_material_advantage",
    "current_tc_base_s",
    "current_tc_inc_s",
)


def b1_sample_sql(paths: Sequence[Path]) -> str:
    speed = speed_code_sql("p.api_speed")
    month_code = (
        "date_diff('month', DATE '2023-11-01', "
        "strptime(p.month || '-01', '%Y-%m-%d'))"
    )
    return f"""
      WITH panel AS (
        SELECT *
        FROM read_parquet({path_list_literal(paths)}, union_by_name=true)
      ), support AS (
        SELECT
          chooser_username_norm AS account_id,
          COUNT(*)::BIGINT AS fair_opportunities,
          SUM(CAST(kind_draw AS BIGINT))::BIGINT AS kind_draws
        FROM panel
        WHERE CAST(fair_competitive AS BOOLEAN)
          AND chooser_username_norm IS NOT NULL
          AND trim(chooser_username_norm) <> ''
          AND kind_draw IS NOT NULL
        GROUP BY chooser_username_norm
        HAVING COUNT(*) >= 4
           AND SUM(CAST(kind_draw AS BIGINT)) >= 2
           AND SUM(CAST(kind_draw AS BIGINT)) < COUNT(*)
      ), chooser_map AS (
        SELECT
          account_id,
          ROW_NUMBER() OVER (ORDER BY account_id)::BIGINT - 1 AS chooser_index,
          fair_opportunities,
          kind_draws
        FROM support
      ), selected AS (
        SELECT
          m.chooser_index,
          ROW_NUMBER() OVER (
            PARTITION BY m.chooser_index
            ORDER BY COALESCE(CAST(p.api_last_move_at_ms AS BIGINT), CAST(p.utc_ms AS BIGINT)),
                     CAST(p.utc_ms AS BIGINT),
                     CAST(p.archive_ordinal AS BIGINT), p.game_id
          )::INTEGER - 1 AS sequence_index,
          COALESCE(CAST(p.api_last_move_at_ms AS BIGINT), CAST(p.utc_ms AS BIGINT))
            AS utc_ms,
          CAST(p.kind_draw AS BOOLEAN) AS kind_draw,
          CAST(p.engine_eval_cp_disconnected AS DOUBLE) AS current_eval_cp,
          CAST(p.chooser_draw_payoff_v2 AS DOUBLE) AS current_draw_payoff,
          CAST(p.chooser_win_premium_v2 AS DOUBLE) AS current_win_premium,
          CAST(p.chooser_elo AS DOUBLE) AS current_chooser_elo,
          CAST(p.disconnected_elo AS DOUBLE) AS current_opponent_elo,
          CAST(p.chooser_pre_rd_v2 AS DOUBLE) AS current_chooser_rd,
          CAST(p.disconnected_pre_rd_v2 AS DOUBLE) AS current_opponent_rd,
          CAST(p.chooser_clock_last_obs_s AS DOUBLE) AS current_chooser_clock_s,
          CAST(p.disconnected_clock_last_obs_s AS DOUBLE)
            AS current_opponent_clock_s,
          CAST(p.ply_count AS DOUBLE) AS current_ply_count,
          CAST(p.material_advantage_chooser AS DOUBLE) AS current_material_advantage,
          CAST(p.tc_base_s AS DOUBLE) AS current_tc_base_s,
          CAST(p.tc_inc_s AS DOUBLE) AS current_tc_inc_s,
          CAST({speed} AS INTEGER) AS current_speed_code,
          CAST(p.tournament_like_event AS BOOLEAN) AS current_tournament_like,
          CAST({month_code} AS INTEGER) AS current_month_code
        FROM panel p
        INNER JOIN chooser_map m
          ON p.chooser_username_norm = m.account_id
        WHERE CAST(p.fair_competitive AS BOOLEAN)
          AND p.kind_draw IS NOT NULL
      )
      SELECT
        ROW_NUMBER() OVER (
          ORDER BY chooser_index, sequence_index
        )::BIGINT - 1 AS b1_row_id,
        *
      FROM selected
      ORDER BY chooser_index, sequence_index
    """


def build_or_authenticate_b1_sample(
    payload: dict[str, Any], state: Path
) -> tuple[Path, dict[str, Any]]:
    duckdb, _, _, _ = import_dependencies()
    output = state / "b1_repeat_granter_private.parquet"
    receipt = state / "b1_repeat_granter_receipt.json"
    if output.is_file() and receipt.is_file():
        saved = load_json(receipt)
        if saved.get("output_sha256") != sha256_file(output):
            raise RuntimeError("B1 private checkpoint SHA mismatch")
        expected = (EXPECTED_B1_CHOOSERS, EXPECTED_B1_OPPORTUNITIES, EXPECTED_B1_KIND_DRAWS)
        actual = (
            safe_int(saved.get("choosers")),
            safe_int(saved.get("opportunities")),
            safe_int(saved.get("kind_draws")),
        )
        if actual != expected:
            raise RuntimeError(f"B1 private checkpoint support mismatch: {actual}")
        print("B1_SAMPLE_CHECKPOINT_AUTHENTICATED_OK", flush=True)
        return output, saved
    if output.exists() or receipt.exists():
        raise RuntimeError("Incomplete B1 sample checkpoint exists")
    connection = duckdb.connect()
    temp = state / "duckdb_temp/b1_sample"
    configure_duckdb(connection, payload, temp)
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    print("B1_REPEAT_GRANTER_SAMPLE_BUILD_BEGIN", flush=True)
    connection.execute(
        f"COPY ({b1_sample_sql(payload['stage07']['paths'])}) "
        f"TO {sql_literal(temporary)} "
        "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)"
    )
    qa = connection.execute(
        f"""
        SELECT
          COUNT(*)::BIGINT,
          COUNT(DISTINCT chooser_index)::BIGINT,
          SUM(CAST(kind_draw AS BIGINT))::BIGINT,
          MIN(b1_row_id)::BIGINT,
          MAX(b1_row_id)::BIGINT,
          COUNT(*) FILTER (
            WHERE current_speed_code NOT BETWEEN 0 AND 5
               OR current_month_code NOT BETWEEN 0 AND 23
          )::BIGINT,
          COUNT(*) FILTER (WHERE utc_ms IS NULL OR utc_ms <= 0)::BIGINT
        FROM read_parquet({sql_literal(temporary)})
        """
    ).fetchone()
    support_qa = connection.execute(
        f"""
        WITH by_chooser AS (
          SELECT
            chooser_index,
            COUNT(*)::BIGINT AS n,
            SUM(CAST(kind_draw AS BIGINT))::BIGINT AS k,
            MIN(sequence_index)::BIGINT AS min_sequence,
            MAX(sequence_index)::BIGINT AS max_sequence
          FROM read_parquet({sql_literal(temporary)})
          GROUP BY chooser_index
        )
        SELECT
          COUNT(*) FILTER (
            WHERE n < 4 OR k < 2 OR k >= n
               OR min_sequence <> 0 OR max_sequence <> n - 1
          )::BIGINT,
          MIN(n)::BIGINT,
          MAX(n)::BIGINT,
          MIN(k)::BIGINT,
          MAX(k)::BIGINT
        FROM by_chooser
        """
    ).fetchone()
    connection.close()
    shutil.rmtree(temp, ignore_errors=True)
    if qa[:3] != (
        EXPECTED_B1_OPPORTUNITIES,
        EXPECTED_B1_CHOOSERS,
        EXPECTED_B1_KIND_DRAWS,
    ):
        raise RuntimeError(f"B1 exact support changed: {qa}")
    if qa[3:5] != (0, EXPECTED_B1_OPPORTUNITIES - 1) or qa[5] or qa[6] or support_qa[0]:
        raise RuntimeError(f"B1 hardened sample QA failed: qa={qa} support={support_qa}")
    os.replace(temporary, output)
    saved = {
        "status": "DYNAMIC_B1_REPEAT_GRANTER_PRIVATE_OK",
        "created_utc": utc_now(),
        "resume_config_sha256": payload["resume_config_sha256"],
        "output_path": str(output),
        "output_sha256": sha256_file(output),
        "output_bytes": output.stat().st_size,
        "choosers": qa[1],
        "opportunities": qa[0],
        "kind_draws": qa[2],
        "minimum_opportunities": support_qa[1],
        "maximum_opportunities": support_qa[2],
        "minimum_kind_draws": support_qa[3],
        "maximum_kind_draws": support_qa[4],
        "share_all_fair_choosers": EXPECTED_B1_CHOOSERS / 2_685_525,
        "share_ever_kind_fair_choosers": EXPECTED_B1_CHOOSERS / 248_963,
        "share_repeat_fair_granters": EXPECTED_B1_CHOOSERS / 79_372,
        "share_all_fair_opportunities": EXPECTED_B1_OPPORTUNITIES / 17_328_130,
        "share_all_fair_kind_draws": EXPECTED_B1_KIND_DRAWS / 487_170,
        "scope": "sequence dependence among repeat granters",
        "raw_account_level_data": "PRIVATE; DO NOT COMMIT OR PUBLISH",
    }
    atomic_write_json(receipt, saved)
    print(
        "B1_REPEAT_GRANTER_SAMPLE_OK "
        f"choosers={qa[1]:,} opportunities={qa[0]:,} kind_draws={qa[2]:,}",
        flush=True,
    )
    return output, saved


B1_ARRAY_COLUMNS = (
    "b1_row_id",
    "chooser_index",
    "sequence_index",
    "utc_ms",
    "kind_draw",
    *B1_CONTINUOUS_FIELDS,
    "current_speed_code",
    "current_tournament_like",
    "current_month_code",
)
B1_SIMULATION_COLUMNS = ("chooser_index", "utc_ms", "kind_draw")


def load_b1_arrays(path: Path) -> dict[str, Any]:
    _, np, pa, pq = import_dependencies()
    table = pq.read_table(path, columns=list(B1_ARRAY_COLUMNS))
    data = {
        name: arrow_column_numpy(table, name, np, pa) for name in B1_ARRAY_COLUMNS
    }
    row_ids = data["b1_row_id"]
    if row_ids.size != EXPECTED_B1_OPPORTUNITIES or not np.array_equal(
        row_ids, np.arange(row_ids.size, dtype=np.int64)
    ):
        raise RuntimeError("B1 arrays lost certified row ordering")
    if int(data["kind_draw"].sum()) != EXPECTED_B1_KIND_DRAWS:
        raise RuntimeError("B1 arrays lost the certified kind-draw total")
    return data


def load_b1_simulation_arrays(
    path: Path,
    *,
    expected_rows: int = EXPECTED_B1_OPPORTUNITIES,
    expected_kind_draws: int = EXPECTED_B1_KIND_DRAWS,
) -> dict[str, Any]:
    """Load only the three columns needed by the conditional sampler."""
    _, np, pa, pq = import_dependencies()
    table = pq.read_table(
        path,
        columns=list(B1_SIMULATION_COLUMNS),
        use_threads=False,
    )
    data = {
        name: arrow_column_numpy(table, name, np, pa)
        for name in B1_SIMULATION_COLUMNS
    }
    if data["chooser_index"].size != expected_rows:
        raise RuntimeError("B1 simulation arrays have the wrong row count")
    if int(np.count_nonzero(data["kind_draw"])) != expected_kind_draws:
        raise RuntimeError("B1 simulation arrays have the wrong kind-draw total")
    if np.any(data["utc_ms"] <= 0):
        raise RuntimeError("B1 simulation arrays contain invalid timestamps")
    return data


def b1_feature_matrix(data: dict[str, Any]) -> tuple[Any, list[str]]:
    _, np, _, _ = import_dependencies()
    indices = np.arange(EXPECTED_B1_OPPORTUNITIES, dtype=np.int64)
    continuous, names = flexible_numeric_controls(data, indices, B1_CONTINUOUS_FIELDS)
    categories, category_names = categorical_controls(
        data,
        indices,
        ("current_speed_code", "current_tournament_like", "current_month_code"),
    )
    intercept = np.ones((indices.size, 1), dtype=np.float64)
    return (
        np.column_stack([intercept, continuous, categories]),
        ["intercept", *names, *category_names],
    )


def ridge_logistic_fit(
    x: Any,
    y: Any,
    *,
    ridge: float = 1e-4,
    tolerance: float = 1e-8,
    maximum_iterations: int = 100,
) -> tuple[Any, int, float]:
    _, np, _, _ = import_dependencies()
    beta = np.zeros(x.shape[1], dtype=np.float64)
    penalty = np.eye(x.shape[1], dtype=np.float64) * ridge
    penalty[0, 0] = 0.0
    last = math.inf
    for iteration in range(1, maximum_iterations + 1):
        eta = np.clip(x @ beta, -30.0, 30.0)
        probability = 1.0 / (1.0 + np.exp(-eta))
        variance = np.maximum(probability * (1.0 - probability), 1e-8)
        gradient = x.T @ (y - probability) - penalty @ beta
        hessian = (x.T * variance) @ x + penalty
        step = np.linalg.solve(hessian, gradient)
        beta += step
        last = float(np.max(np.abs(step)))
        if last <= tolerance:
            return beta, iteration, last
    raise RuntimeError(
        f"Ridge logistic model failed to converge; last step={last:.3e}"
    )


def build_or_authenticate_recipient_overlap_propensity(
    payload: dict[str, Any], state: Path, data: dict[str, Any]
) -> tuple[Any, dict[str, Any]]:
    """Cross-fit the frozen exposure/pre-exposure-only overlap sensitivity."""
    _, np, pa, pq = import_dependencies()
    output = state / "recipient_overlap_propensity_private.parquet"
    receipt = state / "recipient_overlap_propensity_receipt.json"
    rows = data["cohort_row_id"].size
    if output.is_file() and receipt.is_file():
        saved = load_json(receipt)
        if saved.get("output_sha256") != sha256_file(output):
            raise RuntimeError("Recipient overlap-propensity checkpoint SHA mismatch")
        table = pq.read_table(output, columns=["overlap_propensity"])
        propensity = np.asarray(
            table["overlap_propensity"].to_numpy(), dtype=np.float64
        )
        if propensity.size != rows:
            raise RuntimeError("Recipient overlap-propensity checkpoint row mismatch")
        print("RECIPIENT_OVERLAP_PROPENSITY_CHECKPOINT_OK", flush=True)
        return propensity, saved
    if output.exists() or receipt.exists():
        raise RuntimeError("Incomplete recipient overlap-propensity checkpoint exists")
    first = (
        data["first_ever_pair"].astype(bool)
        & data["arm_eligible"].astype(bool)
    )
    indices = np.flatnonzero(first)
    continuous, continuous_names = flexible_numeric_controls(
        data, indices, (*EXPOSURE_CONTROLS, *PRE_EXPOSURE_BALANCE_FIELDS)
    )
    categories, category_names = categorical_controls(
        data, indices, ("exposure_speed_code", "exposure_month_code")
    )
    x = np.column_stack(
        [np.ones((indices.size, 1)), continuous, categories]
    )
    names = ["intercept", *continuous_names, *category_names]
    y = data["received_mercy"][indices].astype(np.float64)
    chooser = data["exposure_chooser_user_id"][indices].astype(np.int64)
    fold = chooser % B1_FOLDS
    selected_probability = np.full(indices.size, np.nan, dtype=np.float64)
    diagnostics: list[dict[str, Any]] = []
    print("RECIPIENT_OVERLAP_PROPENSITY_CROSSFIT_BEGIN", flush=True)
    for held_out in range(B1_FOLDS):
        train = fold != held_out
        test = ~train
        beta, iterations, last = ridge_logistic_fit(x[train], y[train])
        eta = np.clip(x[test] @ beta, -30.0, 30.0)
        selected_probability[test] = 1.0 / (1.0 + np.exp(-eta))
        diagnostics.append(
            {
                "fold": held_out,
                "training_rows": int(np.count_nonzero(train)),
                "held_out_rows": int(np.count_nonzero(test)),
                "iterations": iterations,
                "last_step": last,
                "held_out_mean_treatment": float(np.mean(y[test])),
                "held_out_mean_prediction": float(
                    np.mean(selected_probability[test])
                ),
                "held_out_brier_score": float(
                    np.mean((y[test] - selected_probability[test]) ** 2)
                ),
                "coefficient_sha256": sha256_bytes(
                    np.asarray(beta, dtype="<f8").tobytes()
                ),
            }
        )
    if np.any(~np.isfinite(selected_probability)):
        raise RuntimeError("Recipient overlap propensities contain missing values")
    unclipped = selected_probability.copy()
    selected_probability = np.clip(selected_probability, 1e-3, 1.0 - 1e-3)
    propensity = np.full(rows, np.nan, dtype=np.float64)
    propensity[indices] = selected_probability
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    pq.write_table(
        pa.table(
            {
                "cohort_row_id": pa.array(data["cohort_row_id"], type=pa.int64()),
                "overlap_propensity": pa.array(propensity, type=pa.float64()),
            }
        ),
        temporary,
        compression="zstd",
        row_group_size=250_000,
    )
    os.replace(temporary, output)
    saved = {
        "status": "DYNAMIC_RECIPIENT_OVERLAP_PROPENSITY_PRIVATE_OK",
        "created_utc": utc_now(),
        "resume_config_sha256": payload["resume_config_sha256"],
        "output_path": str(output),
        "output_sha256": sha256_file(output),
        "output_bytes": output.stat().st_size,
        "rows": rows,
        "first_pair_rows": int(indices.size),
        "folds": B1_FOLDS,
        "model": "ridge logistic; exposure-time and pre-exposure variables only",
        "ridge": 1e-4,
        "clipping": [0.001, 0.999],
        "feature_count": len(names),
        "feature_names": names,
        "minimum_before_clipping": float(np.min(unclipped)),
        "maximum_before_clipping": float(np.max(unclipped)),
        "clipped_rows": int(
            np.count_nonzero(selected_probability != unclipped)
        ),
        "fold_diagnostics": diagnostics,
        "raw_account_level_data": "PRIVATE; DO NOT COMMIT OR PUBLISH",
    }
    atomic_write_json(receipt, saved)
    print("RECIPIENT_OVERLAP_PROPENSITY_CROSSFIT_OK", flush=True)
    return propensity, saved


def fit_overlap_sensitivity_outcome(
    *,
    data: dict[str, Any],
    propensity: Any,
    outcome_name: str,
    sample: Any,
    label: str,
    binary_outcome: bool,
) -> dict[str, Any]:
    _, np, _, _ = import_dependencies()
    outcome = np.asarray(data[outcome_name], dtype=np.float64)
    treatment = data["received_mercy"].astype(bool)
    sample = np.asarray(sample, dtype=bool) & np.isfinite(outcome) & np.isfinite(propensity)
    indices = np.flatnonzero(sample)
    p = propensity[indices]
    weights = np.where(treatment[indices], 1.0 - p, p)
    controls, names = model_controls(data, indices, state_conditioned=False)
    specification = {
        "analysis": "overlap_sensitivity",
        "outcome": outcome_name,
        "estimand": label,
        "state_conditioned": False,
        "propensity_inputs": "exposure-time and pre-exposure only",
        "standardization": "cross-fitted overlap weights",
        "target_population": "overlap population, not ATT",
        "fixed_effects": "exposure cell and exposure month",
        "cluster": "exposure chooser",
    }
    return fit_weighted_cluster_model(
        outcome=outcome[indices],
        treatment=treatment[indices],
        controls=controls,
        control_names=names,
        weights=weights,
        cell_fe=data["exposure_cell_code"][indices],
        month_fe=data["exposure_month_code"][indices],
        clusters=data["exposure_chooser_user_id"][indices],
        row_ids=data["cohort_row_id"][indices],
        specification=specification,
        binary_outcome=binary_outcome,
    )


def estimate_overlap_sensitivities(
    payload: dict[str, Any], state: Path, data: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    propensity, receipt = build_or_authenticate_recipient_overlap_propensity(
        payload, state, data
    )
    first = (
        data["first_ever_pair"].astype(bool)
        & data["arm_eligible"].astype(bool)
    )
    conditional = (
        first
        & data["a1_90d_followup_eligible"].astype(bool)
        & data["reached_fair_chooser_within_90d"].astype(bool)
    )
    rows = [
        fit_overlap_sensitivity_outcome(
            data=data,
            propensity=propensity,
            outcome_name="first_subsequent_kind_draw",
            sample=conditional,
            label="A1_total_path_crossfit_overlap_population",
            binary_outcome=True,
        ),
        fit_overlap_sensitivity_outcome(
            data=data,
            propensity=propensity,
            outcome_name="log1p_games_within_30d",
            sample=first,
            label="A3_log1p_30d_crossfit_overlap_population",
            binary_outcome=False,
        ),
    ]
    return rows, receipt


def build_or_authenticate_b1_propensities(
    payload: dict[str, Any], state: Path, sample: Path
) -> tuple[Any, dict[str, Any]]:
    _, np, pa, pq = import_dependencies()
    output = state / "b1_crossfit_propensity_private.parquet"
    receipt = state / "b1_crossfit_propensity_receipt.json"
    if output.is_file() and receipt.is_file():
        saved = load_json(receipt)
        if saved.get("output_sha256") != sha256_file(output):
            raise RuntimeError("B1 propensity checkpoint SHA mismatch")
        if saved.get("resume_config_sha256") != payload["resume_config_sha256"]:
            raise RuntimeError("B1 propensity checkpoint config mismatch")
        table = pq.read_table(output, columns=["static_propensity"])
        probability = np.asarray(table["static_propensity"].to_numpy(), dtype=np.float64)
        if probability.size != EXPECTED_B1_OPPORTUNITIES:
            raise RuntimeError("B1 propensity checkpoint row mismatch")
        print("B1_CROSSFIT_PROPENSITY_CHECKPOINT_AUTHENTICATED_OK", flush=True)
        return probability, saved
    if output.exists() or receipt.exists():
        raise RuntimeError("Incomplete B1 propensity checkpoint exists")
    data = load_b1_arrays(sample)
    x, names = b1_feature_matrix(data)
    y = data["kind_draw"].astype(np.float64)
    chooser = data["chooser_index"].astype(np.int64)
    fold = chooser % B1_FOLDS
    probability = np.full(y.size, np.nan, dtype=np.float64)
    fold_rows: list[dict[str, Any]] = []
    print("B1_CROSSFIT_STATIC_MODEL_BEGIN", flush=True)
    for held_out in range(B1_FOLDS):
        train = fold != held_out
        test = ~train
        beta, iterations, last = ridge_logistic_fit(x[train], y[train])
        eta = np.clip(x[test] @ beta, -30.0, 30.0)
        probability[test] = 1.0 / (1.0 + np.exp(-eta))
        fold_rows.append(
            {
                "fold": held_out,
                "training_rows": int(np.count_nonzero(train)),
                "held_out_rows": int(np.count_nonzero(test)),
                "iterations": iterations,
                "last_step": last,
                "held_out_mean_outcome": float(np.mean(y[test])),
                "held_out_mean_prediction": float(np.mean(probability[test])),
                "held_out_brier_score": float(
                    np.mean((y[test] - probability[test]) ** 2)
                ),
                "coefficient_sha256": sha256_bytes(
                    np.asarray(beta, dtype="<f8").tobytes()
                ),
            }
        )
        print(
            f"B1_CROSSFIT_FOLD_OK fold={held_out + 1}/{B1_FOLDS} "
            f"iterations={iterations}",
            flush=True,
        )
    if np.any(~np.isfinite(probability)):
        raise RuntimeError("B1 cross-fitted propensities contain missing values")
    unclipped = probability.copy()
    probability = np.clip(probability, 1e-6, 1.0 - 1e-6)
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    pq.write_table(
        pa.table(
            {
                "b1_row_id": pa.array(data["b1_row_id"], type=pa.int64()),
                "static_propensity": pa.array(probability, type=pa.float64()),
            }
        ),
        temporary,
        compression="zstd",
        row_group_size=250_000,
    )
    os.replace(temporary, output)
    saved = {
        "status": "DYNAMIC_B1_CROSSFIT_PROPENSITY_PRIVATE_OK",
        "created_utc": utc_now(),
        "resume_config_sha256": payload["resume_config_sha256"],
        "output_path": str(output),
        "output_sha256": sha256_file(output),
        "output_bytes": output.stat().st_size,
        "rows": int(y.size),
        "folds": B1_FOLDS,
        "model": "ridge logistic; current-state variables only",
        "ridge": 1e-4,
        "feature_count": len(names),
        "feature_names": names,
        "prediction_minimum_before_clipping": float(np.min(unclipped)),
        "prediction_maximum_before_clipping": float(np.max(unclipped)),
        "clipped_rows": int(np.count_nonzero(probability != unclipped)),
        "fold_diagnostics": fold_rows,
        "raw_account_level_data": "PRIVATE; DO NOT COMMIT OR PUBLISH",
    }
    atomic_write_json(receipt, saved)
    print("B1_CROSSFIT_STATIC_MODEL_OK", flush=True)
    return probability, saved


def chooser_slices(chooser: Any) -> list[tuple[int, int]]:
    _, np, _, _ = import_dependencies()
    boundaries = np.flatnonzero(np.r_[True, chooser[1:] != chooser[:-1], True])
    return [
        (int(boundaries[index]), int(boundaries[index + 1]))
        for index in range(boundaries.size - 1)
    ]


def kernel_statistic(times_ms: Any, choices: Any, taus_hours: Sequence[float]) -> Any:
    _, np, _, _ = import_dependencies()
    running = np.zeros(len(taus_hours), dtype=np.float64)
    statistic = np.zeros(len(taus_hours), dtype=np.float64)
    previous = int(times_ms[0])
    for time_value, choice in zip(times_ms, choices, strict=True):
        delta_hours = max(int(time_value) - previous, 0) / HOUR_MS
        decay = np.exp(-delta_hours / np.asarray(taus_hours, dtype=np.float64))
        running *= decay
        if bool(choice):
            statistic += running
            running += 1.0
        previous = int(time_value)
    return statistic


def conditional_selection_probabilities(log_odds: Any, kind_total: int) -> Any:
    """Return exact sequential draw probabilities conditional on the fixed total."""
    _, np, _, _ = import_dependencies()
    n = int(log_odds.size)
    k = int(kind_total)
    suffix = np.full((n + 1, k + 1), -np.inf, dtype=np.float64)
    suffix[n, 0] = 0.0
    for position in range(n - 1, -1, -1):
        suffix[position, 0] = 0.0
        maximum = min(k, n - position)
        for remaining in range(1, maximum + 1):
            without = suffix[position + 1, remaining]
            with_current = log_odds[position] + suffix[position + 1, remaining - 1]
            suffix[position, remaining] = np.logaddexp(without, with_current)
    if not np.isfinite(suffix[0, k]):
        raise RuntimeError("Conditional-Bernoulli normalizer is nonfinite")
    probabilities = np.zeros((n, k + 1), dtype=np.float64)
    for position in range(n):
        maximum = min(k, n - position)
        for remaining in range(1, maximum + 1):
            numerator = log_odds[position] + suffix[position + 1, remaining - 1]
            probabilities[position, remaining] = math.exp(
                min(0.0, numerator - suffix[position, remaining])
            )
    return np.clip(probabilities, 0.0, 1.0)


def simulate_b1_batch(
    *,
    data: dict[str, Any],
    probability: Any,
    simulations: int,
    seed_components: Sequence[int],
    progress_label: str = "serial",
) -> Any:
    _, np, _, _ = import_dependencies()
    rng = np.random.default_rng(np.random.SeedSequence(list(seed_components)))
    chooser = data["chooser_index"].astype(np.int64)
    times = data["utc_ms"].astype(np.int64)
    observed = data["kind_draw"].astype(bool)
    taus = np.asarray(B1_TAUS_HOURS, dtype=np.float64)
    total = np.zeros((simulations, taus.size), dtype=np.float64)
    slices = chooser_slices(chooser)
    for chooser_number, (start, stop) in enumerate(slices):
        sequence_times = times[start:stop]
        k = int(np.count_nonzero(observed[start:stop]))
        odds = np.log(probability[start:stop]) - np.log1p(-probability[start:stop])
        selection = conditional_selection_probabilities(odds, k)
        remaining = np.full(simulations, k, dtype=np.int32)
        running = np.zeros((simulations, taus.size), dtype=np.float64)
        statistic = np.zeros((simulations, taus.size), dtype=np.float64)
        previous = int(sequence_times[0])
        n = stop - start
        for position, time_value in enumerate(sequence_times):
            delta_hours = max(int(time_value) - previous, 0) / HOUR_MS
            running *= np.exp(-delta_hours / taus)[None, :]
            left = n - position
            forced = remaining == left
            probability_now = selection[position, remaining]
            chosen = forced | (
                (remaining > 0) & (rng.random(simulations) < probability_now)
            )
            statistic += chosen[:, None] * running
            running += chosen[:, None]
            remaining -= chosen.astype(np.int32)
            previous = int(time_value)
        if np.any(remaining != 0):
            raise RuntimeError("Exact conditional sampler failed to preserve chooser total")
        total += statistic
        if (chooser_number + 1) % 10_000 == 0:
            print(
                "B1_RANDOMIZATION_CHOOSER_PROGRESS "
                f"batch={progress_label} "
                f"choosers={chooser_number + 1:,}/{len(slices):,}",
                flush=True,
            )
    return total


def initialize_b1_process_worker(
    sample_path: str,
    propensity_path: str,
    propensity_sha256: str,
    expected_rows: int,
    expected_kind_draws: int,
) -> None:
    """Load immutable B1 inputs once in each spawned worker process."""
    for variable in (
        "OPENBLAS_NUM_THREADS",
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        os.environ[variable] = "1"
    global _B1_WORKER_DATA, _B1_WORKER_PROBABILITY
    sample = Path(sample_path)
    propensity = Path(propensity_path)
    if sha256_file(propensity) != propensity_sha256:
        raise RuntimeError("B1 worker propensity SHA-256 mismatch")
    _B1_WORKER_DATA = load_b1_simulation_arrays(
        sample,
        expected_rows=expected_rows,
        expected_kind_draws=expected_kind_draws,
    )
    _, np, _, pq = import_dependencies()
    table = pq.read_table(
        propensity,
        columns=["static_propensity"],
        use_threads=False,
    )
    _B1_WORKER_PROBABILITY = np.asarray(
        table["static_propensity"].to_numpy(), dtype=np.float64
    )
    if _B1_WORKER_PROBABILITY.size != expected_rows:
        raise RuntimeError("B1 worker propensity row count mismatch")
    if np.any(~np.isfinite(_B1_WORKER_PROBABILITY)) or np.any(
        (_B1_WORKER_PROBABILITY <= 0.0) | (_B1_WORKER_PROBABILITY >= 1.0)
    ):
        raise RuntimeError("B1 worker propensities are outside (0,1)")


def simulate_b1_from_worker_globals(
    simulations: int, seed_components: Sequence[int], progress_label: str
) -> Any:
    if _B1_WORKER_DATA is None or _B1_WORKER_PROBABILITY is None:
        raise RuntimeError("B1 process worker was not initialized")
    return simulate_b1_batch(
        data=_B1_WORKER_DATA,
        probability=_B1_WORKER_PROBABILITY,
        simulations=simulations,
        seed_components=seed_components,
        progress_label=progress_label,
    )


def write_b1_randomization_checkpoint_worker(
    *,
    start: int,
    stop: int,
    state_root: str,
    resume_config_sha256: str,
    propensity_sha256: str,
) -> dict[str, Any]:
    """Compute and atomically certify one frozen B1 randomization batch."""
    state = Path(state_root)
    path = (
        state
        / "b1_randomizations"
        / f"randomizations_{start:04d}_{stop - 1:04d}.npz"
    )
    receipt = path.with_suffix(".json")
    if path.exists() or receipt.exists():
        raise RuntimeError(f"B1 worker was assigned an existing checkpoint: {start}")
    started = time.time()
    statistics = simulate_b1_from_worker_globals(
        stop - start,
        (B1_SEED, start, stop),
        f"{start + 1}-{stop}",
    )
    atomic_save_npz(path, statistics=statistics)
    saved = {
        "status": "DYNAMIC_B1_RANDOMIZATION_BATCH_OK",
        "created_utc": utc_now(),
        "resume_config_sha256": resume_config_sha256,
        "randomization_start": start,
        "randomization_stop_exclusive": stop,
        "propensity_sha256": propensity_sha256,
        "seed_components": [B1_SEED, start, stop],
        "output_path": str(path),
        "output_sha256": sha256_file(path),
        "output_bytes": path.stat().st_size,
        "runtime_seconds": time.time() - started,
        "execution_mode": "independent_spawned_process",
    }
    atomic_write_json(receipt, saved)
    return {
        "randomization_start": start,
        "randomization_stop_exclusive": stop,
        "output_sha256": saved["output_sha256"],
        "runtime_seconds": saved["runtime_seconds"],
    }


def authenticate_b1_randomization_checkpoint(
    path: Path,
    receipt: Path,
    payload: dict[str, Any],
    start: int,
    stop: int,
    propensity_sha256: str,
) -> Any | None:
    _, np, _, _ = import_dependencies()
    if not path.exists() and not receipt.exists():
        return None
    if not path.is_file() or not receipt.is_file():
        raise RuntimeError(f"Incomplete B1 randomization checkpoint: {start}")
    saved = load_json(receipt)
    expected = {
        "status": "DYNAMIC_B1_RANDOMIZATION_BATCH_OK",
        "resume_config_sha256": payload["resume_config_sha256"],
        "randomization_start": start,
        "randomization_stop_exclusive": stop,
        "propensity_sha256": propensity_sha256,
        "seed_components": [B1_SEED, start, stop],
        "output_path": str(path),
        "output_sha256": sha256_file(path),
        "output_bytes": path.stat().st_size,
    }
    for key, value in expected.items():
        if saved.get(key) != value:
            raise RuntimeError(f"B1 randomization checkpoint mismatch: {key}")
    array = np.load(path)["statistics"]
    if array.shape != (stop - start, len(B1_TAUS_HOURS)):
        raise RuntimeError("B1 randomization checkpoint shape mismatch")
    return array


def atomic_save_npz(path: Path, **arrays: Any) -> None:
    _, np, _, _ = import_dependencies()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{uuid.uuid4().hex}.npz")
    np.savez_compressed(temporary, **arrays)
    os.replace(temporary, path)


def holm_adjust(p_values: Sequence[float]) -> list[float]:
    count = len(p_values)
    order = sorted(range(count), key=lambda index: p_values[index])
    adjusted = [math.nan] * count
    running = 0.0
    for rank, index in enumerate(order):
        candidate = min(1.0, (count - rank) * float(p_values[index]))
        running = max(running, candidate)
        adjusted[index] = running
    return adjusted


def run_b1_conditional_randomization(
    payload: dict[str, Any],
    state: Path,
    sample: Path,
    support: dict[str, Any],
) -> dict[str, Any]:
    _, np, _, _ = import_dependencies()
    data = load_b1_arrays(sample)
    probability, propensity_receipt = build_or_authenticate_b1_propensities(
        payload, state, sample
    )
    propensity_sha256 = str(propensity_receipt["output_sha256"])
    observed = np.zeros(len(B1_TAUS_HOURS), dtype=np.float64)
    for start, stop in chooser_slices(data["chooser_index"]):
        observed += kernel_statistic(
            data["utc_ms"][start:stop],
            data["kind_draw"][start:stop],
            B1_TAUS_HOURS,
        )
    propensity_path = Path(str(propensity_receipt["output_path"]))
    batch_specs: list[tuple[int, int, Path, Path]] = []
    pending: list[tuple[int, int]] = []
    for start in range(0, B1_RANDOMIZATIONS, B1_RANDOMIZATION_BATCH):
        stop = min(start + B1_RANDOMIZATION_BATCH, B1_RANDOMIZATIONS)
        path = (
            state
            / "b1_randomizations"
            / f"randomizations_{start:04d}_{stop - 1:04d}.npz"
        )
        receipt = path.with_suffix(".json")
        batch_specs.append((start, stop, path, receipt))
        saved = authenticate_b1_randomization_checkpoint(
            path, receipt, payload, start, stop, propensity_sha256
        )
        if saved is None:
            pending.append((start, stop))
    authenticated = len(batch_specs) - len(pending)
    if authenticated:
        print(
            "B1_RANDOMIZATION_RESUME_CHECKPOINTS_OK "
            f"authenticated_batches={authenticated}/{len(batch_specs)}",
            flush=True,
        )
    del data, probability
    if pending:
        workers = min(int(payload["b1_workers"]), len(pending))
        print(
            "B1_RANDOMIZATION_PARALLEL_BEGIN "
            f"pending_batches={len(pending)} workers={workers} "
            "numerical_threads_per_worker=1",
            flush=True,
        )
        context = multiprocessing.get_context("spawn")
        future_to_range: dict[Any, tuple[int, int]] = {}
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=workers,
            mp_context=context,
            initializer=initialize_b1_process_worker,
            initargs=(
                str(sample),
                str(propensity_path),
                propensity_sha256,
                EXPECTED_B1_OPPORTUNITIES,
                EXPECTED_B1_KIND_DRAWS,
            ),
        ) as executor:
            for start, stop in pending:
                future = executor.submit(
                    write_b1_randomization_checkpoint_worker,
                    start=start,
                    stop=stop,
                    state_root=str(state),
                    resume_config_sha256=payload["resume_config_sha256"],
                    propensity_sha256=propensity_sha256,
                )
                future_to_range[future] = (start, stop)
            completed = authenticated
            for future in concurrent.futures.as_completed(future_to_range):
                result = future.result()
                completed += 1
                print(
                    "B1_RANDOMIZATION_BATCH_OK "
                    f"range={result['randomization_start'] + 1}-"
                    f"{result['randomization_stop_exclusive']} "
                    f"completed_batches={completed}/{len(batch_specs)} "
                    f"runtime_seconds={result['runtime_seconds']:.1f}",
                    flush=True,
                )
    checkpoint_arrays: list[Any] = []
    for start, stop, path, receipt in batch_specs:
        saved = authenticate_b1_randomization_checkpoint(
            path, receipt, payload, start, stop, propensity_sha256
        )
        if saved is None:
            raise RuntimeError(f"B1 batch was not certified after scheduling: {start}")
        checkpoint_arrays.append(saved)
    print(
        "B1_RANDOMIZATION_ALL_BATCHES_AUTHENTICATED_OK "
        f"batches={len(checkpoint_arrays)} randomizations={B1_RANDOMIZATIONS:,}",
        flush=True,
    )
    null = np.vstack(checkpoint_arrays)
    if null.shape != (B1_RANDOMIZATIONS, len(B1_TAUS_HOURS)):
        raise RuntimeError("Combined B1 null distribution shape mismatch")
    rows: list[dict[str, Any]] = []
    raw_p: list[float] = []
    for column, tau in enumerate(B1_TAUS_HOURS):
        lower = (1 + int(np.count_nonzero(null[:, column] <= observed[column]))) / (
            B1_RANDOMIZATIONS + 1
        )
        upper = (1 + int(np.count_nonzero(null[:, column] >= observed[column]))) / (
            B1_RANDOMIZATIONS + 1
        )
        p_value = min(1.0, 2.0 * min(lower, upper))
        raw_p.append(p_value)
        rows.append(
            {
                "analysis": "B1",
                "scope": "sequence dependence among repeat granters",
                "tau_hours": tau,
                "primary_kernel": tau == B1_PRIMARY_TAU_HOURS,
                "observed_statistic": float(observed[column]),
                "null_mean": float(np.mean(null[:, column])),
                "null_standard_deviation": float(np.std(null[:, column], ddof=1)),
                "null_quantile_025": float(np.quantile(null[:, column], 0.025)),
                "null_quantile_975": float(np.quantile(null[:, column], 0.975)),
                "standardized_difference": float(
                    (observed[column] - np.mean(null[:, column]))
                    / np.std(null[:, column], ddof=1)
                ),
                "lower_tail_plus_one": lower,
                "upper_tail_plus_one": upper,
                "p_value_raw": p_value,
                "randomizations": B1_RANDOMIZATIONS,
            }
        )
    adjusted = holm_adjust(raw_p)
    for row, value in zip(rows, adjusted, strict=True):
        row["p_value_holm_within_b1"] = value
    return {
        "rows": rows,
        "support": support,
        "propensity_receipt": propensity_receipt,
        "parallel_execution": {
            "requested_workers": int(payload["b1_workers"]),
            "frozen_batch_count": len(batch_specs),
            "frozen_batch_boundaries": [
                [start, stop] for start, stop, _, _ in batch_specs
            ],
            "seed_components": "(20260821, start, stop)",
            "concatenation_order": "ascending frozen randomization_start",
        },
        "null_distribution_sha256": sha256_bytes(
            np.asarray(null, dtype="<f8").tobytes(order="C")
        ),
    }


def csv_safe_rows(rows: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                fields.append(key)
                seen.add(key)
    converted: list[dict[str, Any]] = []
    for row in rows:
        clean: dict[str, Any] = {}
        for field in fields:
            value = row.get(field)
            if isinstance(value, (dict, list, tuple)):
                clean[field] = canonical_json(value)
            elif value is None:
                clean[field] = ""
            else:
                clean[field] = value
        converted.append(clean)
    return converted, fields


def write_result_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    if not rows:
        raise RuntimeError(f"Refusing to write an empty result table: {path}")
    converted, fields = csv_safe_rows(rows)
    write_csv(path, converted, fields)


def primary_holm_rows(
    recipient: dict[str, Any], b1: dict[str, Any]
) -> list[dict[str, Any]]:
    a1 = next(
        row
        for row in recipient["a1_models"]
        if row["estimand"] == "primary_total_path_conditional_choice"
    )
    a3 = next(
        row
        for row in recipient["a3_models"]
        if row["estimand"] == "primary_blinded_ceiling_selected"
    )
    b1_primary = next(
        row for row in b1["rows"] if row["primary_kernel"]
    )
    rows = [
        {
            "family_order": 1,
            "primary_test": "A1 mercy transmission",
            "estimand_or_statistic": a1["estimand"],
            "estimate": a1["coefficient"],
            "standard_error": a1["standard_error"],
            "p_value_raw": a1["p_value_raw"],
        },
        {
            "family_order": 2,
            "primary_test": "A3 platform engagement",
            "estimand_or_statistic": a3["outcome"],
            "estimate": a3["coefficient"],
            "standard_error": a3["standard_error"],
            "p_value_raw": a3["p_value_raw"],
        },
        {
            "family_order": 3,
            "primary_test": "B1 conditional exchangeability among repeat granters",
            "estimand_or_statistic": "T_24h",
            "estimate": b1_primary["observed_statistic"],
            "standard_error": "",
            "p_value_raw": b1_primary["p_value_raw"],
        },
    ]
    adjusted = holm_adjust([float(row["p_value_raw"]) for row in rows])
    for row, value in zip(rows, adjusted, strict=True):
        row["p_value_holm_three_primary"] = value
    return rows


def resolve_active_run_id(
    state: Path, payload: dict[str, Any], requested: str | None
) -> str:
    path = state / "active_result_run.json"
    if path.is_file():
        saved = load_json(path)
        if saved.get("resume_config_sha256") != payload["resume_config_sha256"]:
            raise RuntimeError("Active result run belongs to another configuration")
        run_id = str(saved["run_id"])
        if requested and requested != run_id:
            raise RuntimeError(
                f"Requested run ID {requested} conflicts with active run {run_id}"
            )
        return run_id
    run_id = requested or default_run_id()
    if not run_id or "/" in run_id or ".." in run_id:
        raise RuntimeError(f"Unsafe result run ID: {run_id!r}")
    atomic_write_json(
        path,
        {
            "status": "DYNAMIC_CORE_ACTIVE_RESULT_RUN",
            "created_utc": utc_now(),
            "run_id": run_id,
            "resume_config_sha256": payload["resume_config_sha256"],
        },
    )
    return run_id


def authenticate_completed_result(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    success = path / "_SUCCESS.json"
    manifest = path / "report_file_hashes.tsv"
    if not success.is_file() or not manifest.is_file():
        raise RuntimeError(f"Incomplete public result directory exists: {path}")
    saved = load_json(success)
    if saved.get("status") != "DYNAMIC_PROSOCIALITY_CORE_V102_OK":
        raise RuntimeError("Existing result has the wrong completion status")
    authenticate_manifest(path, manifest)
    if saved.get("report_manifest_sha256") != sha256_file(manifest):
        raise RuntimeError("Existing result manifest SHA mismatch")
    print(f"DYNAMIC_CORE_RESULT_ALREADY_CERTIFIED_OK: {path}", flush=True)
    return saved


def write_public_results(
    *,
    payload: dict[str, Any],
    state: Path,
    run_id: str,
    recipient_path: Path,
    history_receipt: dict[str, Any],
    support: dict[str, Any],
    recipient: dict[str, Any],
    b1: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    output_root = Path(payload["output_root"])
    output_root.mkdir(parents=True, exist_ok=True)
    final = output_root / run_id
    existing = authenticate_completed_result(final)
    if existing is not None:
        return final, existing
    staging = output_root / f".{run_id}.staging"
    if staging.exists():
        shutil.rmtree(staging)
    (staging / "results").mkdir(parents=True)
    (staging / "receipts").mkdir(parents=True)
    write_result_csv(
        staging / "results/a1_primary_and_companions.csv",
        recipient["a1_models"],
    )
    write_result_csv(staging / "results/a1_decay.csv", recipient["a1_decay"])
    write_result_csv(staging / "results/a1_balance.csv", recipient["balance"])
    write_result_csv(
        staging / "results/a1_encouragement.csv", recipient["encouragement"]
    )
    write_result_csv(
        staging / "results/a1_a3_overlap_sensitivity.csv",
        recipient["overlap_sensitivities"],
    )
    write_result_csv(staging / "results/a3_retention.csv", recipient["a3_models"])
    write_result_csv(staging / "results/b1_conditional_randomization.csv", b1["rows"])
    write_result_csv(
        staging / "results/common_support_cells.csv", support["cell_rows"]
    )
    holm = primary_holm_rows(recipient, b1)
    write_result_csv(staging / "results/primary_holm_family.csv", holm)
    public_support = {key: value for key, value in support.items() if key not in {"eligible", "weights", "cell_rows"}}
    public_b1_support = {
        key: value
        for key, value in b1["support"].items()
        if key not in {"output_path"}
    }
    sanitized_propensity = {
        key: value
        for key, value in b1["propensity_receipt"].items()
        if key not in {"output_path"}
    }
    summary = {
        "status": "DYNAMIC_PROSOCIALITY_CORE_V102_RESULTS_READY",
        "created_utc": utc_now(),
        "run_id": run_id,
        "script_version": SCRIPT_VERSION,
        "script_sha256": payload["script_sha256"],
        "analysis_plan_sha256": EXPECTED_PLAN_SHA256,
        "arm_partition_amendment_sha256": EXPECTED_ARM_AMENDMENT_SHA256,
        "parallel_execution_note_sha256": EXPECTED_EXECUTION_NOTE_SHA256,
        "git_head": payload["git"]["head"],
        "stage07_success_sha256": EXPECTED_STAGE07_SUCCESS_SHA256,
        "a3_gate_success_sha256": EXPECTED_A3_GATE_SUCCESS_SHA256,
        "a3_private_cache_sha256": EXPECTED_A3_PRIVATE_SHA256,
        "chronology_manifest_sha256": EXPECTED_CHRONOLOGY_MANIFEST_SHA256,
        "chronology_history": {
            key: value
            for key, value in history_receipt.items()
            if key not in {"output_path"}
        },
        "recipient_private_input_sha256": sha256_file(recipient_path),
        "common_support": public_support,
        "a1_models": recipient["a1_models"],
        "a1_decay": recipient["a1_decay"],
        "a1_encouragement": recipient["encouragement"],
        "a1_a3_overlap_sensitivities": recipient["overlap_sensitivities"],
        "recipient_overlap_propensity_model": {
            key: value
            for key, value in recipient["overlap_propensity_receipt"].items()
            if key not in {"output_path"}
        },
        "a3_models": recipient["a3_models"],
        "b1_rows": b1["rows"],
        "b1_support": public_b1_support,
        "b1_propensity_model": sanitized_propensity,
        "b1_parallel_execution": b1["parallel_execution"],
        "b1_null_distribution_sha256": b1["null_distribution_sha256"],
        "execution_configuration": {
            "duckdb_threads": int(payload["threads"]),
            "chronology_workers": int(payload["chronology_workers"]),
            "b1_workers": int(payload["b1_workers"]),
            "batch_rows": int(payload["batch_rows"]),
            "memory_limit": payload["memory_limit"],
        },
        "primary_holm_family": holm,
        "interpretation": {
            "A1": (
                "conditional dynamic association unless balance, falsification, and "
                "encouragement checks justify stronger language"
            ),
            "A3": "total platform-engagement association; rating consequences retained",
            "B1": (
                "conditional exchangeability test among repeat granters; direction "
                "does not uniquely identify a mechanism"
            ),
        },
        "privacy": (
            "Only aggregate results are public here; private account-level state "
            "remains on XT_Pro and must not be committed or published."
        ),
    }
    atomic_write_json(staging / "summary.json", summary)
    atomic_write_json(
        staging / "receipts/input_authorities.json",
        {
            "analysis_plan_sha256": EXPECTED_PLAN_SHA256,
            "arm_partition_amendment_sha256": EXPECTED_ARM_AMENDMENT_SHA256,
            "parallel_execution_note_sha256": EXPECTED_EXECUTION_NOTE_SHA256,
            "stage07_success_sha256": EXPECTED_STAGE07_SUCCESS_SHA256,
            "stage07_script_sha256": EXPECTED_STAGE07_SCRIPT_SHA256,
            "a3_gate_success_sha256": EXPECTED_A3_GATE_SUCCESS_SHA256,
            "a3_gate_script_sha256": EXPECTED_A3_GATE_SCRIPT_SHA256,
            "a3_private_cache_sha256": EXPECTED_A3_PRIVATE_SHA256,
            "chronology_manifest_sha256": EXPECTED_CHRONOLOGY_MANIFEST_SHA256,
            "chronology_footer_plan_sha256": EXPECTED_CHRONOLOGY_FOOTER_PLAN_SHA256,
            "git_head": payload["git"]["head"],
        },
    )
    manifest_rows = directory_manifest(
        staging, excluded={"_SUCCESS.json", "report_file_hashes.tsv"}
    )
    write_csv(
        staging / "report_file_hashes.tsv",
        manifest_rows,
        ("sha256", "bytes", "path"),
        delimiter="\t",
    )
    success = {
        **summary,
        "status": "DYNAMIC_PROSOCIALITY_CORE_V102_OK",
        "summary_sha256": sha256_file(staging / "summary.json"),
        "report_manifest_sha256": sha256_file(staging / "report_file_hashes.tsv"),
        "report_files_hashed": len(manifest_rows),
    }
    atomic_write_json(staging / "_SUCCESS.json", success)
    authenticate_manifest(staging, staging / "report_file_hashes.tsv")
    os.replace(staging, final)
    atomic_write_json(
        state / "completed_result.json",
        {
            "status": "DYNAMIC_CORE_PUBLIC_RESULT_OK",
            "created_utc": utc_now(),
            "run_id": run_id,
            "output_path": str(final),
            "success_sha256": sha256_file(final / "_SUCCESS.json"),
            "report_manifest_sha256": success["report_manifest_sha256"],
        },
    )
    print(f"DYNAMIC_CORE_PUBLIC_RESULT_OK: {final}", flush=True)
    return final, success


def run_numerical_self_test() -> None:
    _, np, _, _ = import_dependencies()
    rng = np.random.default_rng(112358)
    n = 360
    cell = rng.integers(0, 6, size=n)
    month = rng.integers(0, 4, size=n)
    treatment = rng.normal(size=n)
    control = rng.normal(size=n)
    weights = rng.uniform(0.5, 2.0, size=n)
    y = 0.37 * treatment - 0.21 * control + cell * 0.15 - month * 0.07 + rng.normal(scale=0.1, size=n)
    transformed, _, _ = weighted_absorb(
        np.column_stack([y, treatment, control]), weights, (cell, month)
    )
    beta_absorbed = np.linalg.lstsq(
        transformed[:, 1:] * np.sqrt(weights)[:, None],
        transformed[:, 0] * np.sqrt(weights),
        rcond=None,
    )[0]
    cell_dummy = np.column_stack([(cell == value) for value in range(6)])
    month_dummy = np.column_stack([(month == value) for value in range(1, 4)])
    design = np.column_stack([treatment, control, cell_dummy, month_dummy])
    beta_dummy = np.linalg.lstsq(
        design * np.sqrt(weights)[:, None], y * np.sqrt(weights), rcond=None
    )[0]
    difference = float(np.max(np.abs(beta_absorbed - beta_dummy[:2])))
    if difference > 1e-9:
        raise RuntimeError(f"Weighted FE self-test failed: {difference:.3e}")
    log_odds = np.log(np.asarray([0.7, 1.2, 2.4, 0.4]))
    selection = conditional_selection_probabilities(log_odds, 2)
    subsets: list[tuple[tuple[int, ...], float, float]] = []
    denominator = 0.0
    for a in range(4):
        for b in range(a + 1, 4):
            denominator += math.exp(log_odds[a] + log_odds[b])
    for a in range(4):
        for b in range(a + 1, 4):
            chosen = {a, b}
            remaining = 2
            sequential = 1.0
            for position in range(4):
                q = selection[position, remaining]
                if position in chosen:
                    sequential *= q
                    remaining -= 1
                else:
                    sequential *= 1.0 - q
            exact = math.exp(log_odds[a] + log_odds[b]) / denominator
            subsets.append(((a, b), sequential, exact))
    sampler_difference = max(abs(row[1] - row[2]) for row in subsets)
    if sampler_difference > 1e-12:
        raise RuntimeError(
            f"Conditional-Bernoulli self-test failed: {sampler_difference:.3e}"
        )
    times = np.asarray([0, HOUR_MS, 4 * HOUR_MS, 9 * HOUR_MS], dtype=np.int64)
    choices = np.asarray([1, 0, 1, 1], dtype=bool)
    recurrence = kernel_statistic(times, choices, (6.0,))
    direct = sum(
        math.exp(-(times[k] - times[j]) / HOUR_MS / 6.0)
        for j in range(4)
        for k in range(j + 1, 4)
        if choices[j] and choices[k]
    )
    if abs(float(recurrence[0]) - direct) > 1e-12:
        raise RuntimeError("Kernel recurrence self-test failed")
    if holm_adjust([0.01, 0.04, 0.03]) != [0.03, 0.06, 0.06]:
        raise RuntimeError("Holm self-test failed")
    print("DYNAMIC_CORE_NUMERICAL_SELF_TEST_OK")
    print(f"weighted_fe_dummy_max_difference: {difference:.3e}")
    print(f"conditional_sampler_max_difference: {sampler_difference:.3e}")


def run_parallel_self_test() -> None:
    """Prove serial/parallel equality for both parallelized execution layers."""
    _, np, pa, pq = import_dependencies()
    with tempfile.TemporaryDirectory(prefix="dynamic_core_parallel_test_") as directory:
        root = Path(directory)

        sample = root / "b1_sample.parquet"
        propensity = root / "b1_propensity.parquet"
        chooser = np.asarray([0, 0, 0, 0, 1, 1, 1, 1], dtype=np.int64)
        times = np.asarray(
            [0, HOUR_MS, 2 * HOUR_MS, 7 * HOUR_MS] * 2,
            dtype=np.int64,
        ) + HOUR_MS
        kind = np.asarray([1, 0, 1, 0, 0, 1, 0, 1], dtype=bool)
        probability = np.asarray(
            [0.20, 0.35, 0.55, 0.70, 0.25, 0.40, 0.60, 0.75],
            dtype=np.float64,
        )
        pq.write_table(
            pa.table(
                {
                    "chooser_index": chooser,
                    "utc_ms": times,
                    "kind_draw": kind,
                }
            ),
            sample,
        )
        pq.write_table(
            pa.table({"static_propensity": probability}),
            propensity,
        )
        simulations = 31
        seed = (314_159, 0, simulations)
        serial = simulate_b1_batch(
            data={
                "chooser_index": chooser,
                "utc_ms": times,
                "kind_draw": kind,
            },
            probability=probability,
            simulations=simulations,
            seed_components=seed,
            progress_label="self-test-serial",
        )
        context = multiprocessing.get_context("spawn")
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=1,
            mp_context=context,
            initializer=initialize_b1_process_worker,
            initargs=(
                str(sample),
                str(propensity),
                sha256_file(propensity),
                8,
                4,
            ),
        ) as executor:
            parallel = executor.submit(
                simulate_b1_from_worker_globals,
                simulations,
                seed,
                "self-test-parallel",
            ).result()
        if not np.array_equal(serial, parallel):
            difference = float(np.max(np.abs(serial - parallel)))
            raise RuntimeError(
                f"Parallel B1 self-test differs from serial: {difference:.3e}"
            )

        input_root = root / "chronology_inputs"
        serial_root = root / "chronology_serial"
        parallel_root = root / "chronology_parallel"
        for path in (input_root, serial_root, parallel_root):
            path.mkdir()
        input_tables = (
            pa.table(
                {
                    "utc_ms": [100, 200, 1_000],
                    "white_id": [1, 5, 1],
                    "black_id": [9, 6, 9],
                }
            ),
            pa.table(
                {
                    "utc_ms": [150, 900],
                    "white_id": [2, 2],
                    "black_id": [8, 8],
                }
            ),
        )
        file_rows: list[dict[str, Any]] = []
        for index, table in enumerate(input_tables):
            path = input_root / f"file_{index}.parquet"
            pq.write_table(table, path)
            file_rows.append(
                {
                    "file_index": index,
                    "path": str(path),
                    "bytes": path.stat().st_size,
                    "rows": table.num_rows,
                    "footer_signature_sha256": f"synthetic-{index}",
                }
            )
        user_lookup = np.full(10, -1, dtype=np.int32)
        user_lookup[1] = 0
        user_lookup[2] = 1
        exposure_times = np.asarray([1_000, 1_000], dtype=np.int64)
        pair_keys = np.asarray(
            [
                (np.uint64(1) << np.uint64(PAIR_KEY_SHIFT)) | np.uint64(9),
                (np.uint64(2) << np.uint64(PAIR_KEY_SHIFT)) | np.uint64(8),
            ],
            dtype=np.uint64,
        )

        def chronology_call(index: int, output_root: Path) -> dict[str, Any]:
            return process_chronology_history_file(
                file_row=file_rows[index],
                user_lookup=user_lookup,
                exposure_game_times=exposure_times,
                sorted_pair_keys=pair_keys,
                cohort_rows=2,
                unique_pairs=2,
                activity_output=output_root / f"activity_{index}.parquet",
                pair_output=output_root / f"pairs_{index}.parquet",
                batch_rows=2,
                parquet_use_threads=False,
            )

        for index in range(2):
            chronology_call(index, serial_root)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(chronology_call, index, parallel_root)
                for index in range(2)
            ]
            for future in futures:
                future.result()
        for index in range(2):
            for prefix in ("activity", "pairs"):
                serial_table = pq.read_table(
                    serial_root / f"{prefix}_{index}.parquet"
                )
                parallel_table = pq.read_table(
                    parallel_root / f"{prefix}_{index}.parquet"
                )
                if not serial_table.equals(parallel_table):
                    raise RuntimeError(
                        "Parallel chronology self-test differs from serial: "
                        f"{prefix}_{index}"
                    )
    print("DYNAMIC_CORE_PARALLEL_SELF_TEST_OK")
    print("b1_parallel_serial_exact: True")
    print("chronology_parallel_serial_exact: True")


def run_integration_self_test() -> None:
    duckdb, _, _, _ = import_dependencies()
    connection = duckdb.connect()
    connection.execute("CREATE TABLE left_t(id INTEGER, t INTEGER)")
    connection.execute("INSERT INTO left_t VALUES (1, 5), (1, 10), (2, 3)")
    connection.execute("CREATE TABLE right_t(id INTEGER, t INTEGER, value INTEGER)")
    connection.execute("INSERT INTO right_t VALUES (1, 1, 11), (1, 7, 17), (2, 2, 22)")
    rows = connection.execute(
        """
        SELECT l.id, l.t, r.value
        FROM left_t l
        ASOF LEFT JOIN right_t r ON l.id = r.id AND l.t > r.t
        ORDER BY l.id, l.t
        """
    ).fetchall()
    connection.close()
    if rows != [(1, 5, 11), (1, 10, 17), (2, 3, 22)]:
        raise RuntimeError(f"DuckDB ASOF integration self-test failed: {rows}")
    print("DYNAMIC_CORE_INTEGRATION_SELF_TEST_OK")


def execute(payload: dict[str, Any], args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    started = time.time()
    state = initialize_or_authenticate_state(payload)
    run_id = resolve_active_run_id(state, payload, args.run_id)
    final = Path(payload["output_root"]) / run_id
    existing = authenticate_completed_result(final)
    if existing is not None:
        return final, existing
    recipient_panel = build_or_authenticate_recipient_panel(payload, state)
    history_path, history_receipt = build_or_authenticate_chronology_history(
        payload, state, recipient_panel
    )
    joined = materialize_joined_recipient_panel(
        payload, state, recipient_panel, history_path
    )
    recipient_cache = state / "recipient_aggregate_estimates.json"
    if recipient_cache.is_file():
        recipient_results = load_json(recipient_cache)
        if recipient_results.get("resume_config_sha256") != payload["resume_config_sha256"]:
            raise RuntimeError("Recipient aggregate checkpoint config mismatch")
        if "overlap_sensitivities" not in recipient_results:
            raise RuntimeError("Recipient aggregate checkpoint lacks frozen overlap sensitivity")
        print("RECIPIENT_AGGREGATE_ESTIMATES_CHECKPOINT_OK", flush=True)
    else:
        print("RECIPIENT_A1_A3_ESTIMATION_BEGIN", flush=True)
        recipient_data = load_recipient_arrays(joined)
        support = common_support_weights(recipient_data)
        estimates = estimate_recipient_analyses(recipient_data, support)
        overlap_rows, overlap_receipt = estimate_overlap_sensitivities(
            payload, state, recipient_data
        )
        recipient_results = {
            "status": "DYNAMIC_RECIPIENT_AGGREGATE_ESTIMATES_OK",
            "created_utc": utc_now(),
            "resume_config_sha256": payload["resume_config_sha256"],
            "support": {
                key: value
                for key, value in support.items()
                if key not in {"eligible", "weights"}
            },
            **estimates,
            "overlap_sensitivities": overlap_rows,
            "overlap_propensity_receipt": overlap_receipt,
        }
        atomic_write_json(recipient_cache, recipient_results)
        print("RECIPIENT_A1_A3_ESTIMATION_OK", flush=True)
    recipient_data = load_recipient_arrays(joined)
    support = common_support_weights(recipient_data)
    b1_sample, b1_support = build_or_authenticate_b1_sample(payload, state)
    b1 = run_b1_conditional_randomization(
        payload, state, b1_sample, b1_support
    )
    final, success = write_public_results(
        payload=payload,
        state=state,
        run_id=run_id,
        recipient_path=joined,
        history_receipt=history_receipt,
        support=support,
        recipient=recipient_results,
        b1=b1,
    )
    print("DYNAMIC_PROSOCIALITY_CORE_V102_COMPLETE", flush=True)
    print(f"output: {final}")
    print(f"success_sha256: {sha256_file(final / '_SUCCESS.json')}")
    print(f"elapsed_seconds: {time.time() - started:.1f}")
    return final, success


def print_key_results(success: dict[str, Any]) -> None:
    print("\nPRIMARY HOLM FAMILY")
    for row in success["primary_holm_family"]:
        print(
            f"{row['primary_test']}: estimate={row['estimate']} "
            f"raw_p={row['p_value_raw']:.6g} "
            f"holm_p={row['p_value_holm_three_primary']:.6g}"
        )
    a1 = next(
        row
        for row in success["a1_models"]
        if row["estimand"] == "primary_total_path_conditional_choice"
    )
    a1_state = next(
        row
        for row in success["a1_models"]
        if row["estimand"] == "mandatory_state_conditioned_conditional_choice"
    )
    a3 = next(
        row
        for row in success["a3_models"]
        if row["estimand"] == "primary_blinded_ceiling_selected"
    )
    print("\nA1 SIDE-BY-SIDE")
    print(
        f"total-path pp={a1['coefficient_percentage_points']:.6f} "
        f"se={a1['standard_error_percentage_points']:.6f} rows={a1['rows']:,}"
    )
    print(
        f"state-conditioned pp={a1_state['coefficient_percentage_points']:.6f} "
        f"se={a1_state['standard_error_percentage_points']:.6f} "
        f"rows={a1_state['rows']:,}"
    )
    print("\nA3 SELECTED PRIMARY")
    print(
        f"outcome={a3['outcome']} coefficient={a3['coefficient']:.8f} "
        f"se={a3['standard_error']:.8f} rows={a3['rows']:,}"
    )
    print("\nB1 CONDITIONAL EXCHANGEABILITY — AMONG REPEAT GRANTERS")
    for row in success["b1_rows"]:
        print(
            f"tau={row['tau_hours']:g}h observed={row['observed_statistic']:.6f} "
            f"z={row['standardized_difference']:.4f} "
            f"raw_p={row['p_value_raw']:.6g}"
        )


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    if args.self_test:
        run_numerical_self_test()
        if args.integration_self_test:
            run_integration_self_test()
        if args.parallel_self_test:
            run_parallel_self_test()
        return
    script_path = Path(__file__).resolve()
    print("DYNAMIC_CORE_PLAN_BEGIN")
    payload = make_plan(args, script_path)
    print_plan(payload)
    if not args.execute:
        print("No files were written. Re-run with --execute to estimate and resume.")
        return
    print("DYNAMIC_CORE_EXECUTE_BEGIN")
    final, success = execute(payload, args)
    print_key_results(success)
    print(f"\nRESULT_ROOT: {final}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"DYNAMIC_CORE_FAIL_CLOSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
