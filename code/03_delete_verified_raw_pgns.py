#!/usr/bin/env python3
"""
Canonical Stage 03: delete verified raw Lichess PGN archives.

Purpose
-------
Stages 01 and 02 substantially reduce the raw monthly Lichess archives:

* Stage 01 preserves detailed move, board, clock, and role information for every
  PGN-level Time-forfeit candidate.
* Stage 02 preserves compact all-game header histories needed for chronological
  Glicko-2 replay.

After both stages have completed and been independently verified, the large raw
`.pgn.zst` files may be removed from local storage. The public archives remain
available from database.lichess.org and can be reacquired by canonical Stage 00.

Safety model
------------
This is intentionally the most conservative script in the replication pipeline.

The default behavior is always plan-only. A plan-only run performs every integrity
check—including expensive SHA-256 checks—but never calls Path.unlink().

Actual deletion requires BOTH:

    --delete-confirmed-raw
    --confirmation DELETE-VERIFIED-LICHESS-BRIDGE-PGNS

Even with both switches, deletion is blocked unless every requested month passes
every gate. This is an all-or-none preflight: no file is deleted if any requested
month is ineligible.

The script never deletes:

* Stage 00 acquisition checkpoints;
* Stage 01 candidate Parquets;
* Stage 02 replay-input Parquets;
* manifests, logs, hashes, or deletion receipts.

Canonical bridge months
-----------------------
The current deletion set is:

    2024-10 through 2025-07

These ten months contain 939,153,041 games and occupy 306,343,594,372 raw bytes.
They bridge the prior paper data to the expanded main-sample endpoint.

Main paper window
-----------------
The final planned paper window is locked as:

    2023-11-01 through 2025-10-31

The bridge archives checked here cover only 2024-10 through 2025-07. Other months
must never be inferred or deleted merely because they exist in the raw directory.

Deletion gates
--------------
For every month, the script verifies:

1. Canonical Stage 00–02 script fingerprints.
2. Stage 00 checkpoint exists and reports final_ok.
3. Raw path, size, and metadata agree with Stage 00.
4. Stage 01 production checkpoint exists and is uncapped.
5. Stage 01 row counts agree with its retained Parquet metadata.
6. Stage 01 candidate and API-target paths occur in stable manifests.
7. Stage 01 retained data files are fingerprinted before deletion.
8. Stage 02 checkpoint exists, is production, and is uncapped.
9. Stage 02 source size, mtime, and SHA-256 match the current raw file.
10. Stage 01 and Stage 02 scan counts agree exactly.
11. Every Stage 02 Parquet exists with the stored size, row count, schema, and hash.
12. Every Stage 02 part is listed in the stable path manifest.
13. Stage 02 source-fingerprint manifest agrees with the checkpoint.
14. Stage 02 API-target coverage reports zero missing IDs.
15. Global Stage 01 and Stage 02 summaries cover every requested month.

Outputs
-------
Each run writes a timestamped or explicitly supplied run directory containing:

    command.txt
    events.jsonl
    delete_plan.csv
    delete_plan.json
    retained_stage1_fingerprints.json
    summary.json
    deletion_receipts.jsonl        # deletion runs only
    deleted_files.txt              # deletion runs only

The shell wrapper should capture stdout/stderr separately as run.log.

Recovery
--------
The deletion plan and receipts retain each archive's:

* public download URL;
* filename and month;
* compressed byte size;
* SHA-256 hash;
* Stage 00 checkpoint path;
* Stage 01 and Stage 02 checkpoint paths.

Canonical Stage 00 can therefore reacquire any deleted archive.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import shutil
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

import pyarrow.parquet as pq


# --------------------------------------------------------------------------------------
# Locked project constants
# --------------------------------------------------------------------------------------

BRIDGE_MONTHS = [
    "2024-10",
    "2024-11",
    "2024-12",
    "2025-01",
    "2025-02",
    "2025-03",
    "2025-04",
    "2025-05",
    "2025-06",
    "2025-07",
]

EXPECTED_BRIDGE_RAW_BYTES = 306_343_594_372
EXPECTED_BRIDGE_STAGE02_ROWS = 939_153_041
EXPECTED_BRIDGE_API_TARGETS = 71_446_579

PUBLIC_ARCHIVE_BASE = "https://database.lichess.org/standard"

DELETE_CONFIRMATION = "DELETE-VERIFIED-LICHESS-BRIDGE-PGNS"

# These are the exact canonical scripts inspected immediately before Stage 03 was built.
EXPECTED_SCRIPT_HASHES = {
    "00_acquire_raw_data.py":
        "61591ee70a5e43b8fa47c57e315e8d2b63288e7361358e370db5a27a82bbec47",
    "01_extract_pgn_candidate_parquets.py":
        "3addba09f0c1cec4d55516cef26e25f819791f454fa2bfb56ed932e7cdb8e139",
    "02_extract_rating_replay_inputs.py":
        "27ab349e64d4ccebdc84e468441bf95177772853f0e495604e07bed8733c136e",
}


# --------------------------------------------------------------------------------------
# General helpers
# --------------------------------------------------------------------------------------

def utc_now() -> str:
    """Return a stable UTC timestamp."""

    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_stamp() -> str:
    """Return a filename-safe UTC timestamp."""

    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")


def write_json_atomic(path: Path, value: Any) -> None:
    """Write JSON through a temporary file and atomically replace the destination."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_text_atomic(path: Path, text: str) -> None:
    """Atomically write a small text artifact."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def write_csv_atomic(
    path: Path,
    fieldnames: List[str],
    rows: Iterable[Dict[str, Any]],
) -> None:
    """Atomically write a CSV plan or ledger."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")

    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    temporary.replace(path)


def append_jsonl_durable(path: Path, value: Dict[str, Any]) -> None:
    """
    Append one JSON object and flush it to disk.

    Deletion receipts use fsync so a sudden interruption cannot erase the most
    recently completed deletion from the ledger.
    """

    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def append_text_durable(path: Path, text: str) -> None:
    """Append and fsync a human-readable deletion ledger."""

    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


def load_json(path: Path) -> Dict[str, Any]:
    """Read and validate that a JSON file contains an object."""

    value = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(value, dict):
        raise TypeError(f"Expected JSON object in {path}")

    return value


def read_path_manifest(path: Path) -> Set[str]:
    """Read a newline-delimited stable path manifest."""

    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def read_csv_by_month(path: Path) -> Dict[str, Dict[str, str]]:
    """Read a CSV manifest and index it by its month column."""

    with path.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    result: Dict[str, Dict[str, str]] = {}

    for row in rows:
        month = row.get("month")

        if month:
            result[month] = row

    return result


def bool_text(value: Any) -> bool:
    """Interpret common CSV/JSON truth representations."""

    if isinstance(value, bool):
        return value

    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def normalize_path(value: Any) -> str:
    """Normalize a stored path without requiring that it exist."""

    return str(Path(str(value)).expanduser().resolve())


def sha256_file(
    path: Path,
    *,
    progress_label: Optional[str] = None,
    chunk_size: int = 16 * 1024 * 1024,
) -> str:
    """
    Hash a file in bounded chunks.

    Progress is reported roughly every 8 GiB. This matters for the raw archives:
    an apparently quiet terminal during a multi-hundred-gigabyte audit should not
    be mistaken for a stalled process.
    """

    digest = hashlib.sha256()
    bytes_read = 0
    next_progress = 8 * 1024**3
    started = time.time()

    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk_size)

            if not block:
                break

            digest.update(block)
            bytes_read += len(block)

            if progress_label and bytes_read >= next_progress:
                elapsed = max(time.time() - started, 0.001)
                gib = bytes_read / 1024**3
                rate = bytes_read / elapsed / 1024**2

                print(
                    f"  {progress_label}: hashed={gib:,.1f} GiB, "
                    f"average={rate:,.1f} MiB/s",
                    flush=True,
                )
                next_progress += 8 * 1024**3

    return digest.hexdigest()


def parquet_rows(path: Path) -> int:
    """Return the row count stored in Parquet metadata."""

    return int(pq.ParquetFile(path).metadata.num_rows)


def parquet_schema_description(path: Path) -> List[Dict[str, Any]]:
    """Return the same schema representation stored by canonical Stage 02."""

    schema = pq.ParquetFile(path).schema_arrow

    return [
        {
            "name": field.name,
            "type": str(field.type),
            "nullable": field.nullable,
        }
        for field in schema
    ]


def raw_filename(month: str) -> str:
    """Canonical Lichess standard-rated monthly archive filename."""

    return f"lichess_db_standard_rated_{month}.pgn.zst"


def normalize_months(values: List[str]) -> List[str]:
    """Normalize CLI month tokens and expand the literal word 'bridge'."""

    months: List[str] = []

    for value in values:
        for token in value.split(","):
            token = token.strip()

            if not token:
                continue

            if token.lower() == "bridge":
                months.extend(BRIDGE_MONTHS)
            else:
                months.append(token)

    deduplicated: List[str] = []

    for month in months:
        if month not in deduplicated:
            deduplicated.append(month)

    for month in deduplicated:
        try:
            dt.datetime.strptime(month, "%Y-%m")
        except ValueError as exc:
            raise ValueError(f"Invalid month: {month}") from exc

    if not deduplicated:
        raise ValueError("At least one month is required.")

    return deduplicated


# --------------------------------------------------------------------------------------
# Gate recording
# --------------------------------------------------------------------------------------

def record_gate(
    gates: Dict[str, Dict[str, Any]],
    blockers: List[str],
    name: str,
    condition: bool,
    detail: Any,
) -> bool:
    """Record one auditable pass/fail gate."""

    passed = bool(condition)

    gates[name] = {
        "ok": passed,
        "detail": detail,
    }

    if not passed:
        blockers.append(name)

    return passed


@dataclass
class MonthPlan:
    """Compact plan record written to CSV and embedded in the JSON plan."""

    month: str
    eligible: bool
    raw_path: str
    public_url: str
    raw_size_bytes: Optional[int]
    expected_source_sha256: Optional[str]
    observed_source_sha256: Optional[str]
    stage1_scanned_games: Optional[int]
    stage1_candidate_rows: Optional[int]
    stage1_api_target_rows: Optional[int]
    stage2_rows: Optional[int]
    stage2_part_count: Optional[int]
    stage2_part_hashes_verified: int
    blocked_reasons: str


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """Define the deliberately confirmation-heavy Stage 03 interface."""

    parser = argparse.ArgumentParser(
        description=(
            "Verify and optionally delete raw Lichess PGN archives whose "
            "canonical Stage 01 and Stage 02 outputs are complete."
        )
    )

    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path("/Volumes/XT_Pro/lichess_kindness"),
    )
    parser.add_argument(
        "--months",
        nargs="+",
        default=["bridge"],
        help="YYYY-MM values or the literal word 'bridge'. Default: bridge.",
    )
    parser.add_argument(
        "--run-root",
        type=Path,
        default=None,
        help="Timestamped audit/deletion output directory.",
    )
    parser.add_argument(
        "--delete-confirmed-raw",
        action="store_true",
        help=(
            "Permit deletion only after every integrity gate passes. "
            "Still requires the exact --confirmation phrase."
        ),
    )
    parser.add_argument(
        "--confirmation",
        default="",
        help=(
            f"Deletion requires the exact phrase: {DELETE_CONFIRMATION}"
        ),
    )

    return parser.parse_args()


# --------------------------------------------------------------------------------------
# Global manifest inspection
# --------------------------------------------------------------------------------------

def inspect_global_context(
    *,
    project_root: Path,
    months: List[str],
) -> Dict[str, Any]:
    """Load and validate the stable context shared by every requested month."""

    code_root = project_root / "replication_package" / "code"
    stage1_root = (
        project_root / "derived" / "replication"
        / "pgn_timeforfeit_candidates"
    )
    stage2_root = (
        project_root / "derived" / "replication"
        / "rating_replay_inputs"
    )

    gates: Dict[str, Dict[str, Any]] = {}
    blockers: List[str] = []
    script_fingerprints: Dict[str, Dict[str, Any]] = {}

    for filename, expected_hash in EXPECTED_SCRIPT_HASHES.items():
        path = code_root / filename
        observed_hash = sha256_file(path) if path.is_file() else None

        script_fingerprints[filename] = {
            "path": str(path),
            "expected_sha256": expected_hash,
            "observed_sha256": observed_hash,
        }

        record_gate(
            gates,
            blockers,
            f"canonical_script_hash_{filename}",
            observed_hash == expected_hash,
            script_fingerprints[filename],
        )

    stage1_summary_path = stage1_root / "_manifests" / "summary.json"
    stage2_summary_path = stage2_root / "_manifests" / "summary.json"

    stage1_summary = load_json(stage1_summary_path)
    stage2_summary = load_json(stage2_summary_path)

    stage1_months = set(stage1_summary.get("months_requested") or [])
    stage2_months = set(stage2_summary.get("months") or [])

    record_gate(
        gates,
        blockers,
        "stage1_global_summary_status",
        stage1_summary.get("status") == "ok",
        stage1_summary.get("status"),
    )
    record_gate(
        gates,
        blockers,
        "stage1_global_month_coverage",
        set(months).issubset(stage1_months),
        {
            "requested": months,
            "available": sorted(stage1_months),
        },
    )
    record_gate(
        gates,
        blockers,
        "stage2_global_month_coverage",
        set(months).issubset(stage2_months),
        {
            "requested": months,
            "available": sorted(stage2_months),
        },
    )
    record_gate(
        gates,
        blockers,
        "stage2_global_all_source_hashes",
        stage2_summary.get("all_have_source_sha256") is True,
        stage2_summary.get("all_have_source_sha256"),
    )
    record_gate(
        gates,
        blockers,
        "stage2_global_all_scan_counts_match",
        stage2_summary.get("all_scan_counts_match_stage1") is True,
        stage2_summary.get("all_scan_counts_match_stage1"),
    )

    stage1_candidate_paths = read_path_manifest(
        stage1_root / "_manifests" / "timeforfeit_candidate_paths.txt"
    )
    stage1_api_target_paths = read_path_manifest(
        stage1_root / "_manifests" / "api_target_game_id_paths.txt"
    )
    stage2_part_paths = read_path_manifest(
        stage2_root / "_manifests" / "rating_replay_input_paths.txt"
    )

    stage1_month_status = read_csv_by_month(
        stage1_root / "_manifests" / "month_status.csv"
    )
    stage2_month_status = read_csv_by_month(
        stage2_root / "_manifests" / "month_status.csv"
    )
    source_fingerprints = read_csv_by_month(
        stage2_root / "_manifests" / "source_fingerprints.csv"
    )
    api_coverage = read_csv_by_month(
        stage2_root / "_manifests" / "api_target_replay_coverage.csv"
    )

    api_coverage_summary = load_json(
        stage2_root
        / "_manifests"
        / "api_target_replay_coverage_summary.json"
    )

    record_gate(
        gates,
        blockers,
        "stage2_api_coverage_summary_passed",
        (
            api_coverage_summary.get("status_stage02") == "passed"
            and int(api_coverage_summary.get("missing_stage2") or 0) == 0
        ),
        {
            "status_stage02":
                api_coverage_summary.get("status_stage02"),
            "missing_stage2":
                api_coverage_summary.get("missing_stage2"),
            "target_rows":
                api_coverage_summary.get("target_rows"),
        },
    )

    if months == BRIDGE_MONTHS:
        record_gate(
            gates,
            blockers,
            "locked_bridge_stage02_rows",
            int(stage2_summary.get("total_rows") or 0)
                == EXPECTED_BRIDGE_STAGE02_ROWS,
            {
                "expected": EXPECTED_BRIDGE_STAGE02_ROWS,
                "observed": stage2_summary.get("total_rows"),
            },
        )
        record_gate(
            gates,
            blockers,
            "locked_bridge_api_targets",
            int(api_coverage_summary.get("target_rows") or 0)
                == EXPECTED_BRIDGE_API_TARGETS,
            {
                "expected": EXPECTED_BRIDGE_API_TARGETS,
                "observed": api_coverage_summary.get("target_rows"),
            },
        )

    return {
        "gates": gates,
        "blockers": blockers,
        "script_fingerprints": script_fingerprints,
        "stage1_root": stage1_root,
        "stage2_root": stage2_root,
        "stage1_summary": stage1_summary,
        "stage2_summary": stage2_summary,
        "stage1_candidate_paths": stage1_candidate_paths,
        "stage1_api_target_paths": stage1_api_target_paths,
        "stage2_part_paths": stage2_part_paths,
        "stage1_month_status": stage1_month_status,
        "stage2_month_status": stage2_month_status,
        "source_fingerprints": source_fingerprints,
        "api_coverage": api_coverage,
        "api_coverage_summary": api_coverage_summary,
    }


# --------------------------------------------------------------------------------------
# Per-month inspection
# --------------------------------------------------------------------------------------

def inspect_month(
    *,
    month: str,
    project_root: Path,
    context: Dict[str, Any],
    events_path: Path,
) -> Dict[str, Any]:
    """Run every cheap and expensive deletion gate for one month."""

    raw_root = project_root / "raw" / "lichess_pgn_standard"
    stage1_root: Path = context["stage1_root"]
    stage2_root: Path = context["stage2_root"]

    filename = raw_filename(month)
    raw_path = raw_root / filename
    public_url = f"{PUBLIC_ARCHIVE_BASE}/{filename}"

    stage0_path = (
        raw_root / ".acquire_checkpoints" / f"{filename}.ok.json"
    )
    stage1_success_path = stage1_root / f"month={month}" / "_SUCCESS.json"
    stage2_success_path = stage2_root / f"month={month}" / "_SUCCESS.json"

    gates: Dict[str, Dict[str, Any]] = {}
    blockers: List[str] = []

    append_jsonl_durable(
        events_path,
        {
            "event": "month_audit_started",
            "month": month,
            "utc": utc_now(),
            "raw_path": str(raw_path),
        },
    )

    raw_exists = raw_path.is_file()
    raw_is_symlink = raw_path.is_symlink()
    raw_size = raw_path.stat().st_size if raw_exists else None
    raw_mtime_ns = raw_path.stat().st_mtime_ns if raw_exists else None

    record_gate(
        gates,
        blockers,
        "raw_file_exists",
        raw_exists,
        str(raw_path),
    )
    record_gate(
        gates,
        blockers,
        "raw_file_not_symlink",
        raw_exists and not raw_is_symlink,
        {"exists": raw_exists, "is_symlink": raw_is_symlink},
    )

    for gate_name, path in [
        ("stage00_checkpoint_exists", stage0_path),
        ("stage01_checkpoint_exists", stage1_success_path),
        ("stage02_checkpoint_exists", stage2_success_path),
    ]:
        record_gate(
            gates,
            blockers,
            gate_name,
            path.is_file(),
            str(path),
        )

    if blockers:
        return {
            "month": month,
            "eligible": False,
            "raw_path": str(raw_path),
            "public_url": public_url,
            "raw_size_bytes": raw_size,
            "raw_mtime_ns": raw_mtime_ns,
            "expected_source_sha256": None,
            "observed_source_sha256": None,
            "stage1_scanned_games": None,
            "stage1_candidate_rows": None,
            "stage1_api_target_rows": None,
            "stage2_rows": None,
            "stage2_part_count": None,
            "stage2_part_hashes_verified": 0,
            "stage1_output_fingerprints": [],
            "gates": gates,
            "blockers": blockers,
        }

    stage0 = load_json(stage0_path)
    stage1 = load_json(stage1_success_path)
    stage2 = load_json(stage2_success_path)

    # ----------------------------------------------------------------------------------
    # Stage 00 gates
    # ----------------------------------------------------------------------------------

    record_gate(
        gates,
        blockers,
        "stage00_final_ok",
        stage0.get("final_ok") is True,
        stage0.get("final_ok"),
    )
    record_gate(
        gates,
        blockers,
        "stage00_month_matches",
        stage0.get("month") == month,
        stage0.get("month"),
    )
    record_gate(
        gates,
        blockers,
        "stage00_filename_matches",
        stage0.get("filename") == filename,
        stage0.get("filename"),
    )
    record_gate(
        gates,
        blockers,
        "stage00_local_path_matches",
        normalize_path(stage0.get("local_path")) == str(raw_path.resolve()),
        stage0.get("local_path"),
    )
    record_gate(
        gates,
        blockers,
        "stage00_local_size_matches",
        int(stage0.get("local_size") or -1) == raw_size,
        {
            "checkpoint": stage0.get("local_size"),
            "observed": raw_size,
        },
    )
    record_gate(
        gates,
        blockers,
        "stage00_remote_size_matches",
        int(stage0.get("remote_size") or -1) == raw_size,
        {
            "checkpoint": stage0.get("remote_size"),
            "observed": raw_size,
        },
    )
    record_gate(
        gates,
        blockers,
        "stage00_size_not_failed",
        stage0.get("size_ok") is not False,
        stage0.get("size_ok"),
    )
    record_gate(
        gates,
        blockers,
        "stage00_zstd_not_failed",
        stage0.get("zstd_ok") is not False,
        stage0.get("zstd_ok"),
    )
    record_gate(
        gates,
        blockers,
        "stage00_url_matches",
        stage0.get("url") == public_url,
        stage0.get("url"),
    )

    # ----------------------------------------------------------------------------------
    # Stage 01 checkpoint, manifest, and retained-output gates
    # ----------------------------------------------------------------------------------

    stage1_scanned = int(stage1.get("scanned_games") or 0)
    stage1_candidate_rows = int(
        stage1.get("matched_timeforfeit_games_written") or 0
    )
    stage1_api_target_rows = int(stage1.get("api_target_rows") or 0)
    stage1_deferred_rows = int(stage1.get("api_deferred_rows") or 0)
    stage1_parse_error_rows = int(
        stage1.get("parse_failures_on_matched_games") or 0
    )

    record_gate(
        gates,
        blockers,
        "stage01_final_ok",
        stage1.get("final_ok") is True,
        stage1.get("final_ok"),
    )
    record_gate(
        gates,
        blockers,
        "stage01_month_matches",
        stage1.get("month") == month,
        stage1.get("month"),
    )
    record_gate(
        gates,
        blockers,
        "stage01_uncapped_games",
        stage1.get("max_games") is None,
        stage1.get("max_games"),
    )
    record_gate(
        gates,
        blockers,
        "stage01_uncapped_matches",
        stage1.get("max_matches") is None,
        stage1.get("max_matches"),
    )
    record_gate(
        gates,
        blockers,
        "stage01_raw_path_matches",
        normalize_path(stage1.get("pgn_zst")) == str(raw_path.resolve()),
        stage1.get("pgn_zst"),
    )
    record_gate(
        gates,
        blockers,
        "stage01_local_size_matches",
        int(stage1.get("local_size") or -1) == raw_size,
        {
            "checkpoint": stage1.get("local_size"),
            "observed": raw_size,
        },
    )
    record_gate(
        gates,
        blockers,
        "stage01_scanned_positive",
        stage1_scanned > 0,
        stage1_scanned,
    )

    stage1_month_dir = stage1_root / f"month={month}"
    candidate_path = stage1_month_dir / "timeforfeit_candidates.parquet"
    target_candidate_path = (
        stage1_month_dir / "api_target_candidates_ge5s_or_missing.parquet"
    )
    deferred_path = (
        stage1_month_dir / "api_deferred_candidates_lt5s.parquet"
    )
    target_ids_path = stage1_month_dir / "api_target_game_ids.parquet"
    parse_errors_path = stage1_month_dir / "parse_errors.parquet"

    expected_stage1_outputs = [
        (candidate_path, stage1_candidate_rows, "timeforfeit_candidates"),
        (target_candidate_path, stage1_api_target_rows, "api_target_candidates"),
        (deferred_path, stage1_deferred_rows, "api_deferred_candidates"),
        (target_ids_path, stage1_api_target_rows, "api_target_game_ids"),
        (parse_errors_path, stage1_parse_error_rows, "parse_errors"),
    ]

    record_gate(
        gates,
        blockers,
        "stage01_candidate_manifest_membership",
        str(candidate_path) in context["stage1_candidate_paths"],
        str(candidate_path),
    )
    record_gate(
        gates,
        blockers,
        "stage01_api_target_manifest_membership",
        str(target_ids_path) in context["stage1_api_target_paths"],
        str(target_ids_path),
    )

    stage1_output_fingerprints: List[Dict[str, Any]] = []

    for output_path, expected_rows, label in expected_stage1_outputs:
        exists = output_path.is_file()

        record_gate(
            gates,
            blockers,
            f"stage01_{label}_exists",
            exists,
            str(output_path),
        )

        if not exists:
            continue

        observed_rows = parquet_rows(output_path)

        record_gate(
            gates,
            blockers,
            f"stage01_{label}_row_count",
            observed_rows == expected_rows,
            {
                "expected": expected_rows,
                "observed": observed_rows,
            },
        )

        print(f"  Fingerprinting retained Stage 01 output: {output_path.name}")
        observed_hash = sha256_file(
            output_path,
            progress_label=f"{month} Stage01 {output_path.name}",
        )

        stage1_output_fingerprints.append(
            {
                "relative_path": str(output_path.relative_to(project_root)),
                "absolute_path": str(output_path),
                "size_bytes": output_path.stat().st_size,
                "rows": observed_rows,
                "sha256": observed_hash,
            }
        )

    # ----------------------------------------------------------------------------------
    # Stage 02 checkpoint, stable-manifest, Parquet, and hash gates
    # ----------------------------------------------------------------------------------

    stage2_rows = int(stage2.get("rows") or 0)
    stage2_parts = stage2.get("parts") or []
    stage2_part_count = int(stage2.get("part_count") or 0)
    expected_source_hash = stage2.get("source_sha256")

    record_gate(
        gates,
        blockers,
        "stage02_final_ok",
        stage2.get("final_ok") is True,
        stage2.get("final_ok"),
    )
    record_gate(
        gates,
        blockers,
        "stage02_production",
        stage2.get("production") is True,
        stage2.get("production"),
    )
    record_gate(
        gates,
        blockers,
        "stage02_uncapped",
        stage2.get("max_games") is None,
        stage2.get("max_games"),
    )
    record_gate(
        gates,
        blockers,
        "stage02_month_matches",
        stage2.get("month") == month,
        stage2.get("month"),
    )
    record_gate(
        gates,
        blockers,
        "stage02_source_path_matches",
        normalize_path(stage2.get("source_path")) == str(raw_path.resolve()),
        stage2.get("source_path"),
    )
    record_gate(
        gates,
        blockers,
        "stage02_source_size_matches",
        int(stage2.get("source_size_bytes") or -1) == raw_size,
        {
            "checkpoint": stage2.get("source_size_bytes"),
            "observed": raw_size,
        },
    )
    record_gate(
        gates,
        blockers,
        "stage02_source_mtime_matches",
        int(stage2.get("source_mtime_ns") or -1) == raw_mtime_ns,
        {
            "checkpoint": stage2.get("source_mtime_ns"),
            "observed": raw_mtime_ns,
        },
    )
    record_gate(
        gates,
        blockers,
        "stage02_source_hash_present",
        isinstance(expected_source_hash, str)
            and len(expected_source_hash) == 64,
        expected_source_hash,
    )
    record_gate(
        gates,
        blockers,
        "stage01_stage02_scan_count_match",
        (
            stage2.get("scan_count_matches_stage1") is True
            and stage2_rows == stage1_scanned
            and int(stage2.get("stage1_scanned_games") or -1)
                == stage1_scanned
        ),
        {
            "stage1": stage1_scanned,
            "stage2": stage2_rows,
            "stored_stage1": stage2.get("stage1_scanned_games"),
            "flag": stage2.get("scan_count_matches_stage1"),
        },
    )
    record_gate(
        gates,
        blockers,
        "stage02_part_count_matches_checkpoint",
        stage2_part_count == len(stage2_parts) and stage2_part_count > 0,
        {
            "part_count": stage2_part_count,
            "part_records": len(stage2_parts),
        },
    )

    fingerprint_row = context["source_fingerprints"].get(month) or {}

    record_gate(
        gates,
        blockers,
        "stage02_source_fingerprint_manifest",
        (
            int(fingerprint_row.get("source_size_bytes") or -1) == raw_size
            and fingerprint_row.get("source_sha256") == expected_source_hash
            and bool_text(fingerprint_row.get("production"))
        ),
        fingerprint_row,
    )

    stage2_status_row = context["stage2_month_status"].get(month) or {}

    record_gate(
        gates,
        blockers,
        "stage02_month_status_manifest",
        (
            stage2_status_row.get("status") == "ok"
            and bool_text(stage2_status_row.get("production"))
            and int(stage2_status_row.get("rows") or -1) == stage2_rows
            and int(stage2_status_row.get("part_count") or -1)
                == stage2_part_count
        ),
        stage2_status_row,
    )

    coverage_row = context["api_coverage"].get(month) or {}

    record_gate(
        gates,
        blockers,
        "stage02_api_target_coverage",
        (
            int(coverage_row.get("target_rows") or -1)
                == stage1_api_target_rows
            and int(coverage_row.get("target_unique") or -1)
                == stage1_api_target_rows
            and int(coverage_row.get("stage2_matches") or -1)
                == stage1_api_target_rows
            and int(coverage_row.get("missing_stage2") or -1) == 0
        ),
        coverage_row,
    )

    stage2_month_dir = stage2_root / f"month={month}"
    observed_part_rows = 0
    verified_part_hashes = 0
    schema_variants: Set[str] = set()

    for part in stage2_parts:
        relative_path = str(part.get("relative_path"))
        part_path = stage2_month_dir / relative_path
        expected_rows = int(part.get("rows") or -1)
        expected_size = int(part.get("size_bytes") or -1)
        expected_hash = part.get("sha256")

        exists = part_path.is_file()

        record_gate(
            gates,
            blockers,
            f"stage02_part_exists_{relative_path}",
            exists,
            str(part_path),
        )

        if not exists:
            continue

        actual_size = part_path.stat().st_size
        actual_rows = parquet_rows(part_path)
        actual_schema = parquet_schema_description(part_path)
        schema_variants.add(json.dumps(actual_schema, sort_keys=True))

        observed_part_rows += actual_rows

        record_gate(
            gates,
            blockers,
            f"stage02_part_size_{relative_path}",
            actual_size == expected_size,
            {
                "expected": expected_size,
                "observed": actual_size,
            },
        )
        record_gate(
            gates,
            blockers,
            f"stage02_part_rows_{relative_path}",
            actual_rows == expected_rows,
            {
                "expected": expected_rows,
                "observed": actual_rows,
            },
        )
        record_gate(
            gates,
            blockers,
            f"stage02_part_manifest_{relative_path}",
            str(part_path) in context["stage2_part_paths"],
            str(part_path),
        )
        record_gate(
            gates,
            blockers,
            f"stage02_part_hash_present_{relative_path}",
            isinstance(expected_hash, str) and len(expected_hash) == 64,
            expected_hash,
        )

        actual_hash = sha256_file(part_path)
        hash_matches = actual_hash == expected_hash

        record_gate(
            gates,
            blockers,
            f"stage02_part_hash_{relative_path}",
            hash_matches,
            {
                "expected": expected_hash,
                "observed": actual_hash,
            },
        )

        if hash_matches:
            verified_part_hashes += 1

    record_gate(
        gates,
        blockers,
        "stage02_part_rows_conserved",
        observed_part_rows == stage2_rows,
        {
            "expected": stage2_rows,
            "observed": observed_part_rows,
        },
    )
    record_gate(
        gates,
        blockers,
        "stage02_schema_matches_checkpoint",
        (
            len(schema_variants) == 1
            and (
                not stage2_parts
                or json.loads(next(iter(schema_variants)))
                    == stage2.get("schema")
            )
        ),
        {
            "schema_variants": len(schema_variants),
            "checkpoint_schema_fields":
                len(stage2.get("schema") or []),
        },
    )

    # Hash the raw file only after all cheaper structural checks have run.
    observed_source_hash = None

    if raw_exists and expected_source_hash:
        print(f"  Hashing raw source for {month}: {raw_path.name}")
        observed_source_hash = sha256_file(
            raw_path,
            progress_label=f"{month} raw",
        )

    record_gate(
        gates,
        blockers,
        "raw_sha256_matches_stage02",
        observed_source_hash == expected_source_hash,
        {
            "expected": expected_source_hash,
            "observed": observed_source_hash,
        },
    )

    eligible = not blockers

    append_jsonl_durable(
        events_path,
        {
            "event": "month_audit_finished",
            "month": month,
            "utc": utc_now(),
            "eligible": eligible,
            "blockers": blockers,
            "raw_size_bytes": raw_size,
            "observed_source_sha256": observed_source_hash,
        },
    )

    return {
        "month": month,
        "eligible": eligible,
        "raw_path": str(raw_path),
        "public_url": public_url,
        "raw_size_bytes": raw_size,
        "raw_mtime_ns": raw_mtime_ns,
        "expected_source_sha256": expected_source_hash,
        "observed_source_sha256": observed_source_hash,
        "stage0_checkpoint": str(stage0_path),
        "stage1_checkpoint": str(stage1_success_path),
        "stage2_checkpoint": str(stage2_success_path),
        "stage1_scanned_games": stage1_scanned,
        "stage1_candidate_rows": stage1_candidate_rows,
        "stage1_api_target_rows": stage1_api_target_rows,
        "stage2_rows": stage2_rows,
        "stage2_part_count": stage2_part_count,
        "stage2_part_hashes_verified": verified_part_hashes,
        "stage1_output_fingerprints": stage1_output_fingerprints,
        "gates": gates,
        "blockers": blockers,
    }


# --------------------------------------------------------------------------------------
# Plan and deletion execution
# --------------------------------------------------------------------------------------

def plan_csv_row(record: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten one detailed month record for the human-readable CSV plan."""

    plan = MonthPlan(
        month=record["month"],
        eligible=record["eligible"],
        raw_path=record["raw_path"],
        public_url=record["public_url"],
        raw_size_bytes=record.get("raw_size_bytes"),
        expected_source_sha256=record.get("expected_source_sha256"),
        observed_source_sha256=record.get("observed_source_sha256"),
        stage1_scanned_games=record.get("stage1_scanned_games"),
        stage1_candidate_rows=record.get("stage1_candidate_rows"),
        stage1_api_target_rows=record.get("stage1_api_target_rows"),
        stage2_rows=record.get("stage2_rows"),
        stage2_part_count=record.get("stage2_part_count"),
        stage2_part_hashes_verified=record.get(
            "stage2_part_hashes_verified", 0
        ),
        blocked_reasons=";".join(record.get("blockers") or []),
    )

    return asdict(plan)


def perform_deletion(
    *,
    records: List[Dict[str, Any]],
    run_root: Path,
) -> List[Dict[str, Any]]:
    """
    Delete raw files after the entire requested set has passed.

    The plan has already verified every source hash. Immediately before each unlink,
    the script rechecks path, size, mtime, and regular-file status to guard against a
    file changing between the audit and deletion phases.
    """

    receipts_path = run_root / "deletion_receipts.jsonl"
    deleted_files_path = run_root / "deleted_files.txt"
    receipts: List[Dict[str, Any]] = []

    for record in records:
        raw_path = Path(record["raw_path"])

        if not raw_path.is_file() or raw_path.is_symlink():
            raise RuntimeError(
                f"Raw file changed before deletion: {raw_path}"
            )

        stat = raw_path.stat()

        if stat.st_size != record["raw_size_bytes"]:
            raise RuntimeError(
                f"Raw size changed before deletion: {raw_path}"
            )

        if stat.st_mtime_ns != record["raw_mtime_ns"]:
            raise RuntimeError(
                f"Raw mtime changed before deletion: {raw_path}"
            )

        intent = {
            "event": "delete_intent",
            "utc": utc_now(),
            "month": record["month"],
            "raw_path": record["raw_path"],
            "public_url": record["public_url"],
            "size_bytes": record["raw_size_bytes"],
            "sha256": record["observed_source_sha256"],
            "stage0_checkpoint": record["stage0_checkpoint"],
            "stage1_checkpoint": record["stage1_checkpoint"],
            "stage2_checkpoint": record["stage2_checkpoint"],
        }
        append_jsonl_durable(receipts_path, intent)

        # This is the sole destructive operation in the canonical Stage 03 script.
        raw_path.unlink()

        if raw_path.exists():
            raise RuntimeError(f"Deletion verification failed: {raw_path}")

        receipt = {
            **intent,
            "event": "delete_complete",
            "deleted_utc": utc_now(),
            "verified_absent": True,
        }
        append_jsonl_durable(receipts_path, receipt)
        append_text_durable(deleted_files_path, str(raw_path) + "\n")
        receipts.append(receipt)

        print(
            f"DELETED {record['month']}: "
            f"{record['raw_size_bytes']:,} bytes",
            flush=True,
        )

    return receipts


def main() -> int:
    """Build the full plan and optionally execute confirmation-gated deletion."""

    args = parse_args()
    months = normalize_months(args.months)
    project_root = args.project_root.expanduser().resolve()

    run_root = (
        args.run_root.expanduser().resolve()
        if args.run_root is not None
        else (
            project_root
            / "output"
            / "replication_delete_verified_raw_pgns"
            / f"delete_plan_{run_stamp()}"
        )
    )
    # The shell wrapper normally opens run.log through tee before Python starts.
    # Consequently, an explicitly supplied run directory can legitimately exist
    # with run.log as its sole entry. Any other pre-existing content remains a
    # blocker because reusing an earlier audit directory could mix plans or receipts.
    if run_root.exists():
        existing_names = sorted(
            entry.name for entry in run_root.iterdir()
        )
        unexpected_names = [
            name for name in existing_names
            if name != "run.log"
        ]

        if unexpected_names:
            raise FileExistsError(
                f"Run root already contains prior artifacts: {run_root}; "
                f"unexpected entries={unexpected_names}"
            )
    else:
        run_root.mkdir(parents=True, exist_ok=False)

    events_path = run_root / "events.jsonl"

    write_text_atomic(
        run_root / "command.txt",
        " ".join([sys.executable, *sys.argv]) + "\n",
    )

    started = time.time()
    started_utc = utc_now()

    print("=" * 100)
    print("CANONICAL STAGE 03: VERIFIED RAW-PGN DELETION PLAN")
    print("=" * 100)
    print(f"Project root: {project_root}")
    print(f"Run root:     {run_root}")
    print(f"Months:       {', '.join(months)}")
    print(f"Delete flag:  {args.delete_confirmed_raw}")
    print()

    context = inspect_global_context(
        project_root=project_root,
        months=months,
    )

    records: List[Dict[str, Any]] = []

    for month in months:
        print()
        print("-" * 100)
        print(f"AUDITING {month}")
        print("-" * 100)

        try:
            record = inspect_month(
                month=month,
                project_root=project_root,
                context=context,
                events_path=events_path,
            )
        except Exception as exc:
            record = {
                "month": month,
                "eligible": False,
                "raw_path": str(
                    project_root
                    / "raw"
                    / "lichess_pgn_standard"
                    / raw_filename(month)
                ),
                "public_url":
                    f"{PUBLIC_ARCHIVE_BASE}/{raw_filename(month)}",
                "raw_size_bytes": None,
                "expected_source_sha256": None,
                "observed_source_sha256": None,
                "stage1_scanned_games": None,
                "stage1_candidate_rows": None,
                "stage1_api_target_rows": None,
                "stage2_rows": None,
                "stage2_part_count": None,
                "stage2_part_hashes_verified": 0,
                "stage1_output_fingerprints": [],
                "gates": {},
                "blockers": [
                    f"{type(exc).__name__}: {exc}"
                ],
            }

            append_jsonl_durable(
                events_path,
                {
                    "event": "month_audit_exception",
                    "month": month,
                    "utc": utc_now(),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )

        records.append(record)

        print(
            f"RESULT {month}: "
            f"{'ELIGIBLE' if record['eligible'] else 'BLOCKED'}"
        )

        if record["blockers"]:
            for blocker in record["blockers"]:
                print(f"  BLOCKER: {blocker}")

    global_ok = not context["blockers"]
    eligible_count = sum(record["eligible"] for record in records)
    blocked_count = len(records) - eligible_count
    raw_bytes = sum(
        int(record.get("raw_size_bytes") or 0)
        for record in records
    )
    stage2_rows = sum(
        int(record.get("stage2_rows") or 0)
        for record in records
    )
    api_targets = sum(
        int(record.get("stage1_api_target_rows") or 0)
        for record in records
    )

    all_passed = (
        global_ok
        and eligible_count == len(records)
        and blocked_count == 0
    )

    if months == BRIDGE_MONTHS:
        locked_totals_ok = (
            raw_bytes == EXPECTED_BRIDGE_RAW_BYTES
            and stage2_rows == EXPECTED_BRIDGE_STAGE02_ROWS
            and api_targets == EXPECTED_BRIDGE_API_TARGETS
        )
    else:
        locked_totals_ok = True

    if not locked_totals_ok:
        all_passed = False

    plan = {
        "stage": "03_delete_verified_raw_pgns",
        "created_utc": utc_now(),
        "project_root": str(project_root),
        "run_root": str(run_root),
        "months": months,
        "delete_requested": args.delete_confirmed_raw,
        "confirmation_phrase_matches":
            args.confirmation == DELETE_CONFIRMATION,
        "global_gates": context["gates"],
        "global_blockers": context["blockers"],
        "locked_totals_ok": locked_totals_ok,
        "month_records": records,
    }

    write_json_atomic(run_root / "delete_plan.json", plan)

    csv_rows = [plan_csv_row(record) for record in records]
    csv_fieldnames = list(asdict(MonthPlan(
        month="",
        eligible=False,
        raw_path="",
        public_url="",
        raw_size_bytes=None,
        expected_source_sha256=None,
        observed_source_sha256=None,
        stage1_scanned_games=None,
        stage1_candidate_rows=None,
        stage1_api_target_rows=None,
        stage2_rows=None,
        stage2_part_count=None,
        stage2_part_hashes_verified=0,
        blocked_reasons="",
    )).keys())

    write_csv_atomic(
        run_root / "delete_plan.csv",
        csv_fieldnames,
        csv_rows,
    )

    retained_fingerprints = {
        record["month"]: record.get("stage1_output_fingerprints") or []
        for record in records
    }
    write_json_atomic(
        run_root / "retained_stage1_fingerprints.json",
        retained_fingerprints,
    )

    summary = {
        "stage": "03_delete_verified_raw_pgns",
        "started_utc": started_utc,
        "finished_utc": utc_now(),
        "elapsed_seconds": round(time.time() - started, 3),
        "months_requested": months,
        "month_count": len(months),
        "global_gates_passed": global_ok,
        "eligible_months": eligible_count,
        "blocked_months": blocked_count,
        "all_requested_months_passed": all_passed,
        "locked_totals_ok": locked_totals_ok,
        "raw_bytes_planned": raw_bytes,
        "raw_gib_planned": raw_bytes / 1024**3,
        "stage2_rows_preserved": stage2_rows,
        "api_targets_preserved": api_targets,
        "delete_requested": args.delete_confirmed_raw,
        "deleted_months": 0,
        "deleted_bytes": 0,
        "raw_files_remain": sum(
            Path(record["raw_path"]).is_file()
            for record in records
        ),
    }

    if not all_passed:
        summary["status"] = "blocked"
        write_json_atomic(run_root / "summary.json", summary)

        print()
        print("STAGE 03 PLAN BLOCKED")
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 2

    if not args.delete_confirmed_raw:
        summary["status"] = "plan_passed_no_deletion"
        write_json_atomic(run_root / "summary.json", summary)

        print()
        print("=" * 100)
        print("STAGE 03 FULL PLAN PASSED — NO FILES DELETED")
        print("=" * 100)
        print(json.dumps(summary, indent=2, sort_keys=True))
        print()
        print(
            "Deletion requires a new invocation with both the deletion flag "
            "and exact confirmation phrase."
        )
        return 0

    if args.confirmation != DELETE_CONFIRMATION:
        summary["status"] = "confirmation_failed_no_deletion"
        write_json_atomic(run_root / "summary.json", summary)

        print()
        print("DELETION BLOCKED: confirmation phrase did not match.")
        return 3

    # All requested months passed as a set. Only now may deletion begin.
    receipts = perform_deletion(
        records=records,
        run_root=run_root,
    )

    summary["status"] = "deletion_complete"
    summary["finished_utc"] = utc_now()
    summary["elapsed_seconds"] = round(time.time() - started, 3)
    summary["deleted_months"] = len(receipts)
    summary["deleted_bytes"] = sum(
        int(receipt["size_bytes"]) for receipt in receipts
    )
    summary["raw_files_remain"] = sum(
        Path(record["raw_path"]).is_file()
        for record in records
    )

    write_json_atomic(run_root / "summary.json", summary)

    print()
    print("=" * 100)
    print("STAGE 03 DELETION COMPLETE")
    print("=" * 100)
    print(json.dumps(summary, indent=2, sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
