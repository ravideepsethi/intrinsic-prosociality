#!/usr/bin/env python3
"""Outcome-blind feasibility audit for the dynamic-prosociality second wave.

The audit authenticates the frozen 24-month panel, the certified dynamic core, its
private B1 checkpoints, and the all-game chronology manifest.  It reports only B2
event-window support, F2 action-gap support, schema/coverage facts, and an execution
shard plan.  It does not estimate post-first-grant kindness, session stopping,
re-pairing outcomes, or any new kindness effect.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence


SCRIPT_VERSION = "1.0.0"
EXPECTED_PLAN_SHA256 = (
    "4f572bb8da7531bfa1b894cfde92da280a936d695bdee72d9bbde6ca4545f039"
)
EXPECTED_GIT_HEAD = "f0f92fb38efb9dea59d4f41d90049fae3e6c57fa"

EXPECTED_STAGE07_STATUS = "STAGE07_24M_CERTIFIED_OK"
EXPECTED_STAGE07_ROWS = 47_587_020
EXPECTED_STAGE07_FAIR_ROWS = 17_328_130
EXPECTED_STAGE07_KIND_DRAWS = 669_503
EXPECTED_STAGE07_SCRIPT_SHA256 = (
    "0411d4061ea9831c20449208a9782aaf668e160139918d106a2b7d63aaa56e6e"
)
EXPECTED_STAGE07_SUCCESS_SHA256 = (
    "8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7"
)

EXPECTED_CORE_STATUS = "DYNAMIC_PROSOCIALITY_CORE_V102_OK"
EXPECTED_CORE_RUN_ID = "20260822T022146Z"
EXPECTED_CORE_SUCCESS_SHA256 = (
    "bd64005162bf8f37f9488d47e95c2ea4dd946d1227e909930a42dd8e4904f009"
)
EXPECTED_CORE_SCRIPT_SHA256 = (
    "2dcf0dd19f7cfe8f694d348e6590df88083a37882404112229d6ef05ebc42713"
)
EXPECTED_B1_SAMPLE_SHA256 = (
    "08429d99aa839c0fc087e3d4d4de270c322086287c3814886f2bcd3bf32e7d56"
)
EXPECTED_B1_PROPENSITY_SHA256 = (
    "0aebdbb279c52308140a819c940655e4341524b3160bcc385cfa8a92030b02df"
)
EXPECTED_B1_CHOOSERS = 64_331
EXPECTED_B1_ROWS = 1_017_944
EXPECTED_B1_KIND_DRAWS = 273_483

EXPECTED_A3_GATE_RUN_ID = "20260821T234626Z"
EXPECTED_A3_GATE_SUCCESS_SHA256 = (
    "bb6592a31fae8af34a6537e843386d6e5423ea31338be4d1bb4a78b0808e7b4f"
)
EXPECTED_CHRONOLOGY_MANIFEST_SHA256 = (
    "1d4648bb17cafd9e58c14ab78d32abe855f0bc62a6fb75ac88e02494a73337cd"
)
EXPECTED_CHRONOLOGY_FILES = 852
EXPECTED_CHRONOLOGY_ROWS = 7_763_847_245

MAIN_MONTHS = tuple(
    f"{absolute // 12:04d}-{absolute % 12 + 1:02d}"
    for absolute in range(2023 * 12 + 10, 2023 * 12 + 10 + 24)
)
MAIN_START_MS = 1_698_796_800_000
MAIN_END_MS = 1_761_955_199_999
HOUR_MS = 60 * 60 * 1000

STAGE07_REQUIRED = {
    "month",
    "game_id",
    "utc_ms",
    "chooser_user_id",
    "disconnected_user_id",
    "chooser_elo",
    "chooser_pre_rd_v2",
    "chooser_draw_payoff_v2",
    "chooser_win_premium_v2",
    "fair_competitive",
    "kind_draw",
    "api_speed",
    "tournament_like_event",
    "engine_eval_cp_disconnected",
}

B1_SAMPLE_REQUIRED = {
    "b1_row_id",
    "chooser_index",
    "sequence_index",
    "utc_ms",
    "kind_draw",
    "current_draw_payoff",
}

GRID_SPECS = (
    ("round100", 100.0, 0.0),
    ("ending50_placebo", 100.0, 50.0),
    ("shift37_placebo", 100.0, 37.0),
)

GLOBAL_WHITE_RATING_CANDIDATES = (
    "white_elo",
    "white_elo_replay",
    "white_rating",
    "white_pre_rating",
)
GLOBAL_BLACK_RATING_CANDIDATES = (
    "black_elo",
    "black_elo_replay",
    "black_rating",
    "black_pre_rating",
)
GLOBAL_WHITE_DIFF_CANDIDATES = (
    "white_rating_diff",
    "observed_white_rating_diff",
    "white_rating_diff_pgn",
)
GLOBAL_BLACK_DIFF_CANDIDATES = (
    "black_rating_diff",
    "observed_black_rating_diff",
    "black_rating_diff_pgn",
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path("/Volumes/XT_Pro/lichess_kindness"),
    )
    parser.add_argument("--analysis-plan", type=Path)
    parser.add_argument("--stage07-root", type=Path)
    parser.add_argument("--core-root", type=Path)
    parser.add_argument("--core-state-root", type=Path)
    parser.add_argument("--a3-gate-root", type=Path)
    parser.add_argument("--rating-input-root", type=Path)
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


def command_output(args: list[str], *, cwd: Path | None = None) -> str:
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def import_dependencies() -> tuple[Any, Any]:
    try:
        import duckdb  # type: ignore
        import pyarrow.parquet as pq  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "DuckDB and PyArrow are required. Use the XT_Pro project venv."
        ) from exc
    return duckdb, pq


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


def authenticate_stage07(root: Path, verify_hashes: bool) -> dict[str, Any]:
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
    if summary.get("status") != EXPECTED_STAGE07_STATUS:
        raise RuntimeError("Stage 07 status mismatch")
    if summary.get("script_sha256") != EXPECTED_STAGE07_SCRIPT_SHA256:
        raise RuntimeError("Stage 07 producer SHA mismatch")
    if int(qa.get("rows", -1)) != EXPECTED_STAGE07_ROWS:
        raise RuntimeError("Stage 07 row total mismatch")
    if int(qa.get("fair_rows", -1)) != EXPECTED_STAGE07_FAIR_ROWS:
        raise RuntimeError("Stage 07 fair-row total mismatch")
    if int(qa.get("kind_draws", -1)) != EXPECTED_STAGE07_KIND_DRAWS:
        raise RuntimeError("Stage 07 kind-draw total mismatch")
    missing = sorted(STAGE07_REQUIRED - schema_names(summary))
    if missing:
        raise RuntimeError(f"Stage 07 required columns are missing: {missing}")

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
    hashes: dict[str, str] = {}
    for month, path, row in zip(MAIN_MONTHS, paths, monthly, strict=True):
        if not path.is_file():
            raise RuntimeError(f"Stage 07 Parquet is missing: {path}")
        if path.stat().st_size != int(row["output_size_bytes"]):
            raise RuntimeError(f"Stage 07 size mismatch: {month}")
        hashes[month] = row["output_sha256"]
    if verify_hashes:
        print("STAGE07_PARQUET_HASH_VERIFICATION_BEGIN", flush=True)
        for month, path in zip(MAIN_MONTHS, paths, strict=True):
            if sha256_file(path) != hashes[month]:
                raise RuntimeError(f"Stage 07 Parquet SHA mismatch: {month}")
            print(f"STAGE07_PARQUET_HASH_OK month={month}", flush=True)
        print("STAGE07_PARQUET_HASH_VERIFICATION_OK", flush=True)
    return {
        "root": str(root),
        "paths": paths,
        "selected_input_bytes": sum(path.stat().st_size for path in paths),
        "hashes_verified": verify_hashes,
        "schema_columns": len(schema_names(summary)),
    }


def parquet_rows_and_columns(path: Path, pq: Any) -> tuple[int, set[str]]:
    parquet = pq.ParquetFile(path)
    return int(parquet.metadata.num_rows), set(parquet.schema_arrow.names)


def authenticate_core(core_root: Path, state_root: Path, pq: Any) -> dict[str, Any]:
    success = core_root / "_SUCCESS.json"
    if not success.is_file():
        raise RuntimeError(f"Certified dynamic-core receipt is missing: {success}")
    if sha256_file(success) != EXPECTED_CORE_SUCCESS_SHA256:
        raise RuntimeError("Dynamic-core success SHA mismatch")
    saved = load_json(success)
    checks = {
        "status": EXPECTED_CORE_STATUS,
        "run_id": EXPECTED_CORE_RUN_ID,
        "script_sha256": EXPECTED_CORE_SCRIPT_SHA256,
    }
    for key, expected in checks.items():
        if saved.get(key) != expected:
            raise RuntimeError(f"Dynamic-core {key} mismatch")
    support = saved.get("b1_support") or {}
    propensity = saved.get("b1_propensity_model") or {}
    if (
        int(support.get("choosers", -1)) != EXPECTED_B1_CHOOSERS
        or int(support.get("opportunities", -1)) != EXPECTED_B1_ROWS
        or int(support.get("kind_draws", -1)) != EXPECTED_B1_KIND_DRAWS
        or support.get("output_sha256") != EXPECTED_B1_SAMPLE_SHA256
    ):
        raise RuntimeError("Certified B1 support mismatch")
    if (
        int(propensity.get("rows", -1)) != EXPECTED_B1_ROWS
        or propensity.get("output_sha256") != EXPECTED_B1_PROPENSITY_SHA256
    ):
        raise RuntimeError("Certified B1 propensity mismatch")

    sample = state_root / "b1_repeat_granter_private.parquet"
    sample_receipt = state_root / "b1_repeat_granter_receipt.json"
    score = state_root / "b1_crossfit_propensity_private.parquet"
    score_receipt = state_root / "b1_crossfit_propensity_receipt.json"
    for path in (sample, sample_receipt, score, score_receipt):
        if not path.is_file():
            raise RuntimeError(f"B1 private checkpoint is missing: {path}")
    if sha256_file(sample) != EXPECTED_B1_SAMPLE_SHA256:
        raise RuntimeError("B1 sample checkpoint SHA mismatch")
    if sha256_file(score) != EXPECTED_B1_PROPENSITY_SHA256:
        raise RuntimeError("B1 propensity checkpoint SHA mismatch")
    if load_json(sample_receipt).get("output_sha256") != EXPECTED_B1_SAMPLE_SHA256:
        raise RuntimeError("B1 sample receipt mismatch")
    if load_json(score_receipt).get("output_sha256") != EXPECTED_B1_PROPENSITY_SHA256:
        raise RuntimeError("B1 propensity receipt mismatch")
    sample_rows, sample_columns = parquet_rows_and_columns(sample, pq)
    score_rows, score_columns = parquet_rows_and_columns(score, pq)
    if sample_rows != EXPECTED_B1_ROWS or score_rows != EXPECTED_B1_ROWS:
        raise RuntimeError("B1 private Parquet row mismatch")
    missing = sorted(B1_SAMPLE_REQUIRED - sample_columns)
    if missing or "static_propensity" not in score_columns:
        raise RuntimeError(
            f"B1 private schema mismatch: sample_missing={missing}, "
            f"score_columns={sorted(score_columns)}"
        )
    chronology_history = saved.get("chronology_history") or {}
    return {
        "success_path": str(success),
        "success_sha256": EXPECTED_CORE_SUCCESS_SHA256,
        "sample": sample,
        "score": score,
        "sample_columns": sorted(sample_columns),
        "chronology_history": chronology_history,
    }


def parse_partition(path: str) -> tuple[str | None, str | None]:
    speed_match = re.search(r"(?:^|/)speed=([^/]+)(?:/|$)", path)
    month_match = re.search(r"(?:^|/)month=(\d{4}-\d{2})(?:/|$)", path)
    return (
        speed_match.group(1) if speed_match else None,
        month_match.group(1) if month_match else None,
    )


def detect_first(columns: set[str], candidates: Sequence[str]) -> str | None:
    return next((candidate for candidate in candidates if candidate in columns), None)


def detect_chronology_schema(columns: set[str]) -> dict[str, Any]:
    return {
        "columns": sorted(columns),
        "utc_ms": "utc_ms" if "utc_ms" in columns else None,
        "white_id": "white_id" if "white_id" in columns else None,
        "black_id": "black_id" if "black_id" in columns else None,
        "game_id": "game_id" if "game_id" in columns else None,
        "speed_column": "speed" if "speed" in columns else None,
        "white_rating": detect_first(columns, GLOBAL_WHITE_RATING_CANDIDATES),
        "black_rating": detect_first(columns, GLOBAL_BLACK_RATING_CANDIDATES),
        "white_rating_diff": detect_first(columns, GLOBAL_WHITE_DIFF_CANDIDATES),
        "black_rating_diff": detect_first(columns, GLOBAL_BLACK_DIFF_CANDIDATES),
        "white_rd": detect_first(columns, ("white_pre_rd_v2", "white_rd")),
        "black_rd": detect_first(columns, ("black_pre_rd_v2", "black_rd")),
    }


def read_chronology_manifest(path: Path, pq: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not path.is_file():
        raise RuntimeError(f"Chronology manifest is missing: {path}")
    if sha256_file(path) != EXPECTED_CHRONOLOGY_MANIFEST_SHA256:
        raise RuntimeError("Chronology manifest SHA mismatch")
    with path.open(encoding="utf-8", newline="") as stream:
        raw = list(csv.DictReader(stream, delimiter="\t"))
    if len(raw) != EXPECTED_CHRONOLOGY_FILES:
        raise RuntimeError("Chronology file count mismatch")
    rows: list[dict[str, Any]] = []
    total = 0
    for index, row in enumerate(raw):
        if int(row["file_index"]) != index:
            raise RuntimeError("Chronology file ordering mismatch")
        candidate = Path(row["path"])
        if not candidate.is_file():
            raise RuntimeError(f"Chronology file is missing: {candidate}")
        if candidate.stat().st_size != int(row["bytes"]):
            raise RuntimeError(f"Chronology file size mismatch: {candidate}")
        speed, month = parse_partition(str(candidate))
        parsed = {
            "file_index": index,
            "path": str(candidate),
            "bytes": int(row["bytes"]),
            "rows": int(row["rows"]),
            "row_groups": int(row["row_groups"]),
            "utc_ms_min": int(row["utc_ms_min"]) if row["utc_ms_min"] else None,
            "utc_ms_max": int(row["utc_ms_max"]) if row["utc_ms_max"] else None,
            "footer_signature_sha256": row["footer_signature_sha256"],
            "speed": speed,
            "month": month,
        }
        rows.append(parsed)
        total += parsed["rows"]
    if total != EXPECTED_CHRONOLOGY_ROWS:
        raise RuntimeError("Chronology row total mismatch")
    probe = next(
        (row for row in rows if row["month"] == "2024-10" and row["speed"] == "blitz"),
        rows[0],
    )
    probe_rows, columns = parquet_rows_and_columns(Path(probe["path"]), pq)
    if probe_rows != probe["rows"]:
        raise RuntimeError("Chronology probe footer row mismatch")
    detected = detect_chronology_schema(columns)
    if not all(detected[key] for key in ("utc_ms", "white_id", "black_id")):
        raise RuntimeError("Chronology identity/time columns are missing")
    detected.update(
        {
            "probe_path": probe["path"],
            "probe_footer_signature_sha256": probe["footer_signature_sha256"],
            "files": len(rows),
            "rows": total,
            "utc_ms_min": min(
                row["utc_ms_min"] for row in rows if row["utc_ms_min"] is not None
            ),
            "utc_ms_max": max(
                row["utc_ms_max"] for row in rows if row["utc_ms_max"] is not None
            ),
            "partition_speeds": sorted({row["speed"] for row in rows if row["speed"]}),
            "partition_months": sorted({row["month"] for row in rows if row["month"]}),
        }
    )
    return rows, detected


def parquet_utc_bounds(parquet: Any, utc_column: str) -> tuple[int | None, int | None]:
    metadata = parquet.metadata
    names = parquet.schema_arrow.names
    if utc_column not in names:
        return None, None
    column_index = names.index(utc_column)
    minima: list[int] = []
    maxima: list[int] = []
    for group_index in range(metadata.num_row_groups):
        statistics = metadata.row_group(group_index).column(column_index).statistics
        if statistics is None or not statistics.has_min_max:
            continue
        minima.append(int(statistics.min))
        maxima.append(int(statistics.max))
    return (min(minima) if minima else None, max(maxima) if maxima else None)


def inventory_rating_inputs(root: Path, pq: Any) -> dict[str, Any]:
    files = sorted(root.glob("month=*/part-*.parquet"))
    if not files:
        return {
            "root": str(root),
            "present": False,
            "files": 0,
            "rows": 0,
            "bytes": 0,
            "months": [],
            "schema": {},
            "month_rows": [],
        }
    month_rows: dict[str, int] = defaultdict(int)
    month_files: dict[str, int] = defaultdict(int)
    month_bytes: dict[str, int] = defaultdict(int)
    total_rows = 0
    total_bytes = 0
    utc_min: int | None = None
    utc_max: int | None = None
    reference_columns: set[str] | None = None
    for index, path in enumerate(files):
        month = parse_partition(str(path))[1]
        if month is None:
            raise RuntimeError(f"Rating input has no month partition: {path}")
        parquet = pq.ParquetFile(path)
        columns = set(parquet.schema_arrow.names)
        if reference_columns is None:
            reference_columns = columns
        elif index in {len(files) // 2, len(files) - 1} and columns != reference_columns:
            raise RuntimeError("Rating-input schema is inconsistent")
        rows = int(parquet.metadata.num_rows)
        size = path.stat().st_size
        low, high = parquet_utc_bounds(parquet, "utc_ms")
        if low is not None:
            utc_min = low if utc_min is None else min(utc_min, low)
        if high is not None:
            utc_max = high if utc_max is None else max(utc_max, high)
        month_rows[month] += rows
        month_files[month] += 1
        month_bytes[month] += size
        total_rows += rows
        total_bytes += size
    columns = reference_columns or set()
    required = {
        "utc_ms",
        "game_id",
        "white_username_norm",
        "black_username_norm",
        "white_elo",
        "black_elo",
        "white_rating_diff",
        "black_rating_diff",
        "speed",
    }
    return {
        "root": str(root),
        "present": True,
        "files": len(files),
        "rows": total_rows,
        "bytes": total_bytes,
        "months": sorted(month_rows),
        "utc_ms_min": utc_min,
        "utc_ms_max": utc_max,
        "schema": {
            "columns": sorted(columns),
            "required_columns_present": not bool(required - columns),
            "missing_required_columns": sorted(required - columns),
        },
        "month_rows": [
            {
                "month": month,
                "files": month_files[month],
                "rows": month_rows[month],
                "bytes": month_bytes[month],
            }
            for month in sorted(month_rows)
        ],
    }


def configure_duckdb(connection: Any, threads: int, memory_limit: str, temp: Path) -> None:
    temp.mkdir(parents=True, exist_ok=True)
    connection.execute(f"SET threads = {int(threads)}")
    connection.execute(f"SET memory_limit = {sql_literal(memory_limit)}")
    connection.execute(f"SET temp_directory = {sql_literal(temp)}")
    connection.execute("SET preserve_insertion_order = false")


def b2_support(
    connection: Any,
    sample: Path,
    *,
    expected_choosers: int = EXPECTED_B1_CHOOSERS,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    source = sql_literal(sample)
    query = f"""
      WITH events AS (
        SELECT
          chooser_index,
          MIN(sequence_index) FILTER (WHERE CAST(kind_draw AS BOOLEAN)) AS first_seq,
          ARG_MIN(utc_ms, sequence_index) FILTER (WHERE CAST(kind_draw AS BOOLEAN)) AS first_utc,
          COUNT(*)::BIGINT AS total_opps
        FROM read_parquet({source})
        GROUP BY chooser_index
      ), support AS (
        SELECT
          e.chooser_index,
          e.first_seq,
          e.first_utc,
          e.total_opps,
          COUNT(*) FILTER (WHERE b.sequence_index < e.first_seq)::BIGINT AS pre_opps,
          COUNT(*) FILTER (WHERE b.sequence_index > e.first_seq)::BIGINT AS post_opps,
          COUNT(*) FILTER (
            WHERE b.sequence_index > e.first_seq
              AND b.utc_ms - e.first_utc <= {6 * HOUR_MS}
          )::BIGINT AS post_opps_6h,
          COUNT(*) FILTER (
            WHERE b.sequence_index > e.first_seq
              AND b.utc_ms - e.first_utc <= {24 * HOUR_MS}
          )::BIGINT AS post_opps_24h,
          COUNT(*) FILTER (
            WHERE b.sequence_index > e.first_seq
              AND b.utc_ms - e.first_utc <= {7 * 24 * HOUR_MS}
          )::BIGINT AS post_opps_7d
        FROM events e
        INNER JOIN read_parquet({source}) b USING (chooser_index)
        GROUP BY ALL
      )
      SELECT
        COUNT(*)::BIGINT AS choosers,
        SUM(total_opps)::BIGINT AS opportunities,
        COUNT(*) FILTER (WHERE pre_opps >= 1)::BIGINT AS choosers_pre_ge1,
        COUNT(*) FILTER (WHERE pre_opps >= 4)::BIGINT AS choosers_pre_ge4,
        COUNT(*) FILTER (WHERE post_opps >= 1)::BIGINT AS choosers_post_ge1,
        COUNT(*) FILTER (WHERE post_opps >= 4)::BIGINT AS choosers_post_ge4,
        COUNT(*) FILTER (WHERE post_opps_6h >= 1)::BIGINT AS choosers_window_6h,
        COUNT(*) FILTER (WHERE post_opps_24h >= 1)::BIGINT AS choosers_window_24h,
        COUNT(*) FILTER (WHERE post_opps_7d >= 1)::BIGINT AS choosers_window_7d,
        SUM(post_opps_6h)::BIGINT AS opportunities_window_6h,
        SUM(post_opps_24h)::BIGINT AS opportunities_window_24h,
        SUM(post_opps_7d)::BIGINT AS opportunities_window_7d,
        MIN(first_utc)::BIGINT AS first_event_utc_min,
        MAX(first_utc)::BIGINT AS first_event_utc_max
      FROM support
    """
    result = connection.execute(query).fetchone()
    fields = [item[0] for item in connection.description]
    summary = dict(zip(fields, result, strict=True))
    rows = [
        {"criterion": key, "value": value}
        for key, value in summary.items()
    ]

    monthly_query = f"""
      WITH events AS (
        SELECT
          chooser_index,
          ARG_MIN(utc_ms, sequence_index) FILTER (WHERE CAST(kind_draw AS BOOLEAN)) AS first_utc
        FROM read_parquet({source})
        GROUP BY chooser_index
      )
      SELECT
        STRFTIME(TO_TIMESTAMP(first_utc / 1000.0), '%Y-%m') AS first_event_month,
        COUNT(*)::BIGINT AS choosers
      FROM events
      GROUP BY first_event_month
      ORDER BY first_event_month
    """
    monthly = [
        {"first_event_month": row[0], "choosers": row[1]}
        for row in connection.execute(monthly_query).fetchall()
    ]
    if int(summary["choosers"]) != expected_choosers:
        raise RuntimeError("B2 support did not reproduce certified chooser count")
    return rows, monthly


def f2_support(
    connection: Any, stage07_paths: Sequence[Path]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    paths = path_list_literal(stage07_paths)
    grids = ",".join(
        f"({sql_literal(name)}, {step}, {offset})"
        for name, step, offset in GRID_SPECS
    )
    scopes = "('all_fair', 9999.0),('rd_le_110', 110.0),('rd_le_80', 80.0)"
    common = f"""
      WITH base AS (
        SELECT
          CAST(chooser_elo AS DOUBLE) AS rating,
          CAST(chooser_pre_rd_v2 AS DOUBLE) AS rd,
          CAST(chooser_draw_payoff_v2 AS DOUBLE) AS draw_diff,
          CAST(chooser_draw_payoff_v2 + chooser_win_premium_v2 AS DOUBLE) AS win_diff
        FROM read_parquet({paths}, union_by_name=true)
        WHERE CAST(fair_competitive AS BOOLEAN)
          AND chooser_elo IS NOT NULL
          AND chooser_pre_rd_v2 IS NOT NULL
          AND chooser_draw_payoff_v2 IS NOT NULL
          AND chooser_win_premium_v2 IS NOT NULL
      ), expanded AS (
        SELECT
          scope_name,
          grid_name,
          step,
          offset_value,
          rating,
          rd,
          rating + draw_diff AS exact_draw,
          rating + win_diff AS exact_win,
          rating + ROUND(draw_diff) AS visible_draw,
          rating + ROUND(win_diff) AS visible_win
        FROM base
        CROSS JOIN (VALUES {scopes}) scopes(scope_name, maximum_rd)
        CROSS JOIN (VALUES {grids}) grids(grid_name, step, offset_value)
        WHERE scope_name = 'all_fair' OR rd <= maximum_rd
      ), levels AS (
        SELECT *,
          FLOOR((exact_draw - offset_value) / step) AS exact_draw_level,
          FLOOR((exact_win - offset_value) / step) AS exact_win_level,
          FLOOR((visible_draw - offset_value) / step) AS visible_draw_level,
          FLOOR((visible_win - offset_value) / step) AS visible_win_level
        FROM expanded
      )
    """
    support_query = common + """
      SELECT
        scope_name AS scope,
        grid_name AS grid,
        COUNT(*)::BIGINT AS eligible_rows,
        COUNT(*) FILTER (WHERE exact_win < exact_draw)::BIGINT AS inverted_action_gaps,
        COUNT(*) FILTER (WHERE exact_win_level > exact_draw_level)::BIGINT AS pivotal_exact,
        COUNT(*) FILTER (WHERE visible_win_level > visible_draw_level)::BIGINT AS pivotal_visible,
        COUNT(*) FILTER (
          WHERE (exact_win_level > exact_draw_level)
            = (visible_win_level > visible_draw_level)
        )::BIGINT AS exact_visible_agreement,
        COUNT(*) FILTER (
          WHERE (exact_win_level > exact_draw_level)
            != (visible_win_level > visible_draw_level)
        )::BIGINT AS exact_visible_disagreement,
        COUNT(*) FILTER (
          WHERE exact_win_level - exact_draw_level > 1
        )::BIGINT AS multiple_boundaries_spanned,
        COUNT(*) FILTER (
          WHERE exact_win_level > exact_draw_level
            AND ((exact_draw_level + 1) * step + offset_value) BETWEEN 1000 AND 2600
        )::BIGINT AS pivotal_exact_boundary_1000_2600
      FROM levels
      GROUP BY scope, grid
      ORDER BY scope, grid
    """
    result = connection.execute(support_query)
    fields = [item[0] for item in result.description]
    support = [dict(zip(fields, row, strict=True)) for row in result.fetchall()]
    if not support or any(int(row["inverted_action_gaps"]) for row in support):
        raise RuntimeError("F2 action-gap support failed ordering QA")

    boundary_query = common + """
      SELECT
        grid_name AS grid,
        CAST((exact_draw_level + 1) * step + offset_value AS INTEGER) AS boundary,
        COUNT(*)::BIGINT AS pivotal_rows
      FROM levels
      WHERE scope_name = 'rd_le_110'
        AND exact_win_level - exact_draw_level = 1
        AND ((exact_draw_level + 1) * step + offset_value) BETWEEN 1000 AND 2600
      GROUP BY grid, boundary
      ORDER BY grid, boundary
    """
    result = connection.execute(boundary_query)
    boundary_fields = [item[0] for item in result.description]
    boundary = [
        dict(zip(boundary_fields, row, strict=True)) for row in result.fetchall()
    ]
    return support, boundary


def chronology_shards(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        month = row["month"]
        e1_window = bool(month and "2022-10" <= month <= "2025-11")
        f2_window = month in MAIN_MONTHS
        output.append(
            {
                "file_index": row["file_index"],
                "speed": row["speed"] or "",
                "month": month or "",
                "rows": row["rows"],
                "bytes": row["bytes"],
                "pair_history_full": True,
                "e1_training_focal_followup": e1_window,
                "f2_salience_main_window": f2_window,
                "relative_partition": "/".join(
                    part
                    for part in (
                        f"speed={row['speed']}" if row["speed"] else "",
                        f"month={month}" if month else "",
                        Path(row["path"]).name,
                    )
                    if part
                ),
                "footer_signature_sha256": row["footer_signature_sha256"],
            }
        )
    return output


def readiness(
    chronology: dict[str, Any], rating_inputs: dict[str, Any]
) -> dict[str, Any]:
    global_ratings = bool(
        chronology.get("white_rating") and chronology.get("black_rating")
    )
    global_diffs = bool(
        chronology.get("white_rating_diff") and chronology.get("black_rating_diff")
    )
    global_all_history = bool(
        chronology.get("utc_ms_min") is not None
        and chronology["utc_ms_min"] < MAIN_START_MS - 365 * 24 * HOUR_MS
        and chronology.get("utc_ms_max") is not None
        and chronology["utc_ms_max"] >= MAIN_END_MS + 30 * 24 * HOUR_MS
    )
    raw_months = rating_inputs.get("months") or []
    raw_ready = bool(
        rating_inputs.get("present")
        and rating_inputs.get("schema", {}).get("required_columns_present")
        and len(raw_months) >= 6
    )
    round_ready = bool((global_ratings and global_diffs) or raw_ready)
    peak_ready = bool(global_ratings and global_diffs and global_all_history)
    e1_ready = bool(global_ratings and global_all_history)
    return {
        "B2": {
            "ready": True,
            "basis": "certified B1 sample and cross-fitted static propensities",
        },
        "F2_round_salience": {
            "ready": round_ready,
            "basis": (
                "all-history replay ratings/diffs"
                if global_ratings and global_diffs
                else "bounded rating-replay input months"
                if raw_ready
                else "no authenticated rating/diff chronology source"
            ),
        },
        "F2_personal_best_salience": {
            "ready": peak_ready,
            "basis": (
                "all-history replay contains ratings, diffs, ids, and complete coverage"
                if peak_ready
                else "requires a deterministic all-history rating-state source"
            ),
        },
        "E1": {
            "ready": e1_ready,
            "basis": (
                "past-only all-history ids, ratings, time, and speed partitions"
                if e1_ready
                else "pair history is ready but rating-cell construction needs a rating join"
            ),
        },
        "all_three_families_ready_without_source_amendment": bool(
            round_ready and peak_ready and e1_ready
        ),
    }


def manifest_rows(root: Path, excluded: set[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative in excluded:
            continue
        rows.append(
            {
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
                "path": relative,
            }
        )
    return rows


def authenticate_report_manifest(root: Path) -> int:
    manifest = root / "report_file_hashes.tsv"
    with manifest.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    for row in rows:
        path = root / row["path"]
        if not path.is_file() or path.stat().st_size != int(row["bytes"]):
            raise RuntimeError(f"Report manifest size/path mismatch: {path}")
        if sha256_file(path) != row["sha256"]:
            raise RuntimeError(f"Report manifest SHA mismatch: {path}")
    return len(rows)


def build_payload(args: argparse.Namespace, script_path: Path) -> dict[str, Any]:
    project = args.project_root.expanduser().resolve()
    repo = project / "replication_package"
    plan = (
        args.analysis_plan.expanduser().resolve()
        if args.analysis_plan
        else script_path.with_name(
            "Dynamic_Prosociality_Second_Wave_Analysis_Plan_v1_0_0_2026-08-22.md"
        )
    )
    if not plan.is_file() or sha256_file(plan) != EXPECTED_PLAN_SHA256:
        raise RuntimeError("Second-wave analysis-plan SHA mismatch")
    git = git_state(repo)
    if git != {"head": EXPECTED_GIT_HEAD, "branch": "main", "clean": True}:
        raise RuntimeError(f"Replication Git state mismatch: {git}")
    stage07_root = (
        args.stage07_root.expanduser().resolve()
        if args.stage07_root
        else project / "derived/replication/analysis_panel_24m_sf100k"
    )
    core_root = (
        args.core_root.expanduser().resolve()
        if args.core_root
        else project / "output/dynamic_prosociality_core_v102" / EXPECTED_CORE_RUN_ID
    )
    state_root = (
        args.core_state_root.expanduser().resolve()
        if args.core_state_root
        else project / "derived/replication/dynamic_prosociality_core_v102_PRIVATE"
    )
    gate_root = (
        args.a3_gate_root.expanduser().resolve()
        if args.a3_gate_root
        else project
        / "output/dynamic_prosociality_a3_chronology_gate_v100"
        / EXPECTED_A3_GATE_RUN_ID
    )
    gate_success = gate_root / "_SUCCESS.json"
    chronology_manifest = gate_root / "chronology_input_manifest.tsv"
    if not gate_success.is_file() or sha256_file(gate_success) != EXPECTED_A3_GATE_SUCCESS_SHA256:
        raise RuntimeError("A3 gate success authority mismatch")
    rating_input_root = (
        args.rating_input_root.expanduser().resolve()
        if args.rating_input_root
        else project / "derived/replication/rating_replay_inputs"
    )
    output_root = (
        args.output_root.expanduser().resolve()
        if args.output_root
        else project / "output/dynamic_second_wave_feasibility_v100"
    )
    if shutil.disk_usage(project).free < 40 * 1024**3:
        raise RuntimeError("Less than 40 GiB is free on XT_Pro")
    return {
        "project": project,
        "repo": repo,
        "plan": plan,
        "git": git,
        "stage07_root": stage07_root,
        "core_root": core_root,
        "state_root": state_root,
        "gate_root": gate_root,
        "chronology_manifest": chronology_manifest,
        "rating_input_root": rating_input_root,
        "output_root": output_root,
        "run_id": args.run_id or default_run_id(),
        "threads": args.threads,
        "memory_limit": args.memory_limit,
        "verify_stage07_hashes": args.verify_stage07_hashes,
        "script_sha256": sha256_file(script_path),
    }


def print_plan(payload: dict[str, Any]) -> None:
    print("DYNAMIC_SECOND_WAVE_FEASIBILITY_V100_PLAN_OK")
    print(f"script_version: {SCRIPT_VERSION}")
    print(f"script_sha256: {payload['script_sha256']}")
    print(f"analysis_plan_sha256: {EXPECTED_PLAN_SHA256}")
    print(f"git_head: {payload['git']['head']}")
    print(f"stage07_root: {payload['stage07_root']}")
    print(f"core_root: {payload['core_root']}")
    print(f"private_b1_state: {payload['state_root']}")
    print(f"chronology_manifest: {payload['chronology_manifest']}")
    print(f"rating_input_root: {payload['rating_input_root']}")
    print(f"output_root: {payload['output_root']}")
    print(f"threads: {payload['threads']}")
    print(f"memory_limit: {payload['memory_limit']}")
    print("new kindness effects: prohibited")
    print("salience stopping estimates: prohibited")
    print("re-pair outcomes: prohibited")
    print("account-level output: prohibited")


def execute(payload: dict[str, Any]) -> Path:
    started = time.time()
    duckdb, pq = import_dependencies()
    stage07 = authenticate_stage07(
        payload["stage07_root"], payload["verify_stage07_hashes"]
    )
    print("SECOND_WAVE_STAGE07_AUTHENTICATED_OK", flush=True)
    core = authenticate_core(payload["core_root"], payload["state_root"], pq)
    print("SECOND_WAVE_CORE_AND_B1_CHECKPOINTS_AUTHENTICATED_OK", flush=True)
    chronology_rows, chronology_schema = read_chronology_manifest(
        payload["chronology_manifest"], pq
    )
    print("SECOND_WAVE_CHRONOLOGY_MANIFEST_AUTHENTICATED_OK", flush=True)
    rating_inputs = inventory_rating_inputs(payload["rating_input_root"], pq)
    print(
        "SECOND_WAVE_RATING_INPUT_INVENTORY_OK "
        f"files={rating_inputs['files']} rows={rating_inputs['rows']:,}",
        flush=True,
    )

    output_root = payload["output_root"]
    output_root.mkdir(parents=True, exist_ok=True)
    final = output_root / payload["run_id"]
    staging = output_root / f".{payload['run_id']}.staging"
    if final.exists() or staging.exists():
        raise RuntimeError("Requested feasibility run id already exists")
    staging.mkdir(parents=True)
    temp = payload["project"] / "derived/replication/dynamic_second_wave_feasibility_v100_TEMP" / payload["run_id"]
    connection = duckdb.connect()
    configure_duckdb(connection, payload["threads"], payload["memory_limit"], temp)
    try:
        print("B2_EVENT_SUPPORT_AUDIT_BEGIN", flush=True)
        b2_rows, b2_months = b2_support(connection, core["sample"])
        print("B2_EVENT_SUPPORT_AUDIT_OK", flush=True)
        print("F2_ACTION_GAP_SUPPORT_AUDIT_BEGIN", flush=True)
        f2_rows, f2_boundaries = f2_support(connection, stage07["paths"])
        print("F2_ACTION_GAP_SUPPORT_AUDIT_OK", flush=True)
    finally:
        connection.close()
        shutil.rmtree(temp, ignore_errors=True)

    ready = readiness(chronology_schema, rating_inputs)
    shards = chronology_shards(chronology_rows)
    write_csv(
        staging / "b2_event_window_support.csv",
        b2_rows,
        ("criterion", "value"),
    )
    write_csv(
        staging / "b2_first_event_month_support.csv",
        b2_months,
        ("first_event_month", "choosers"),
    )
    write_csv(
        staging / "f2_action_gap_support.csv",
        f2_rows,
        (
            "scope",
            "grid",
            "eligible_rows",
            "inverted_action_gaps",
            "pivotal_exact",
            "pivotal_visible",
            "exact_visible_agreement",
            "exact_visible_disagreement",
            "multiple_boundaries_spanned",
            "pivotal_exact_boundary_1000_2600",
        ),
    )
    write_csv(
        staging / "f2_boundary_support_rd_le_110.csv",
        f2_boundaries,
        ("grid", "boundary", "pivotal_rows"),
    )
    write_csv(
        staging / "rating_input_month_inventory.csv",
        rating_inputs["month_rows"],
        ("month", "files", "rows", "bytes"),
    )
    write_csv(
        staging / "chronology_execution_shards.tsv",
        shards,
        (
            "file_index",
            "speed",
            "month",
            "rows",
            "bytes",
            "pair_history_full",
            "e1_training_focal_followup",
            "f2_salience_main_window",
            "relative_partition",
            "footer_signature_sha256",
        ),
        delimiter="\t",
    )
    atomic_write_json(staging / "chronology_schema_and_coverage.json", chronology_schema)
    atomic_write_json(
        staging / "rating_input_schema_and_coverage.json",
        {key: value for key, value in rating_inputs.items() if key != "month_rows"},
    )
    atomic_write_json(staging / "second_wave_readiness.json", ready)
    authorities = {
        "git_head": payload["git"]["head"],
        "analysis_plan_sha256": EXPECTED_PLAN_SHA256,
        "script_sha256": payload["script_sha256"],
        "stage07_success_sha256": EXPECTED_STAGE07_SUCCESS_SHA256,
        "dynamic_core_success_sha256": EXPECTED_CORE_SUCCESS_SHA256,
        "b1_sample_sha256": EXPECTED_B1_SAMPLE_SHA256,
        "b1_propensity_sha256": EXPECTED_B1_PROPENSITY_SHA256,
        "a3_gate_success_sha256": EXPECTED_A3_GATE_SUCCESS_SHA256,
        "chronology_manifest_sha256": EXPECTED_CHRONOLOGY_MANIFEST_SHA256,
    }
    atomic_write_json(staging / "input_authorities.json", authorities)

    report_rows = manifest_rows(
        staging, {"_SUCCESS.json", "report_file_hashes.tsv"}
    )
    write_csv(
        staging / "report_file_hashes.tsv",
        report_rows,
        ("sha256", "bytes", "path"),
        delimiter="\t",
    )
    success = {
        "status": "DYNAMIC_SECOND_WAVE_FEASIBILITY_V100_OK",
        "created_utc": utc_now(),
        "run_id": payload["run_id"],
        "script_version": SCRIPT_VERSION,
        "script_sha256": payload["script_sha256"],
        "analysis_plan_sha256": EXPECTED_PLAN_SHA256,
        "git_head": payload["git"]["head"],
        "stage07_rows": EXPECTED_STAGE07_ROWS,
        "stage07_fair_rows": EXPECTED_STAGE07_FAIR_ROWS,
        "stage07_hashes_verified": stage07["hashes_verified"],
        "b1_choosers": EXPECTED_B1_CHOOSERS,
        "b1_rows": EXPECTED_B1_ROWS,
        "chronology_files": EXPECTED_CHRONOLOGY_FILES,
        "chronology_rows": EXPECTED_CHRONOLOGY_ROWS,
        "rating_input_files": rating_inputs["files"],
        "rating_input_rows": rating_inputs["rows"],
        "readiness": ready,
        "certified_first_ever_pair_share_from_core": core[
            "chronology_history"
        ].get("first_ever_pair_share"),
        "new_kindness_effects_estimated": False,
        "post_first_kindness_rate_tabulated": False,
        "salience_stopping_outcome_read": False,
        "re_pair_outcome_constructed": False,
        "patron_profile_input_read": False,
        "account_level_output_retained": False,
        "report_manifest_sha256": sha256_file(staging / "report_file_hashes.tsv"),
        "report_files_hashed": len(report_rows),
        "runtime_seconds": time.time() - started,
        "next_step": (
            "Review only support/readiness. If no source amendment is required, "
            "freeze the plan and full producer in Git before estimating B2, F2 "
            "salience, E1, or downstream kindness effects."
        ),
    }
    atomic_write_json(staging / "_SUCCESS.json", success)
    authenticate_report_manifest(staging)
    os.replace(staging, final)
    print(f"DYNAMIC_SECOND_WAVE_FEASIBILITY_V100_OK: {final}", flush=True)
    return final


def self_test() -> None:
    assert parse_partition("/x/speed=blitz/month=2024-10/a.parquet") == (
        "blitz",
        "2024-10",
    )
    detected = detect_chronology_schema(
        {
            "utc_ms",
            "white_id",
            "black_id",
            "white_elo_replay",
            "black_elo_replay",
            "observed_white_rating_diff",
            "observed_black_rating_diff",
        }
    )
    assert detected["white_rating"] == "white_elo_replay"
    assert detected["black_rating_diff"] == "observed_black_rating_diff"

    def pivotal(draw: float, win: float, step: float, offset: float) -> bool:
        return math.floor((win - offset) / step) > math.floor(
            (draw - offset) / step
        )

    assert pivotal(1498.0, 1501.0, 100.0, 0.0)
    assert not pivotal(1500.0, 1501.0, 100.0, 0.0)
    assert pivotal(1549.0, 1550.0, 100.0, 50.0)
    assert not pivotal(1498.0, 1501.0, 100.0, 37.0)
    assert len(MAIN_MONTHS) == 24
    assert MAIN_MONTHS[0] == "2023-11" and MAIN_MONTHS[-1] == "2025-10"
    print("DYNAMIC_SECOND_WAVE_FEASIBILITY_SELF_TEST_OK")


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    if args.self_test:
        self_test()
        return
    if args.threads < 1 or args.threads > 32:
        raise SystemExit("--threads must be between 1 and 32")
    script_path = Path(__file__).resolve()
    payload = build_payload(args, script_path)
    print_plan(payload)
    if not args.execute:
        print("No row-level query was executed. Re-run with --execute.")
        return
    execute(payload)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            f"DYNAMIC_SECOND_WAVE_FEASIBILITY_FAIL_CLOSED: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        raise
