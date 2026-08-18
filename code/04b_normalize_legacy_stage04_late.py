#!/usr/bin/env python3
"""Normalize the audited August--October 2025 legacy API layer.

Scientific purpose
==================

The locked paper window is 2023-11-01 through 2025-10-31.  The ten bridge
months (2024-10 through 2025-07) were produced by the native canonical Stage
04 program.  August through October 2025 were instead produced earlier by a
legacy, eight-shard API pipeline.  A sequence of read-only audits established
that the three legacy candidate universes and merged API lookups are complete,
internally unique, and exactly reconciled.  The audits also established that
the legacy layer does *not* retain all native Stage 04 operational provenance.

This program performs the authorized next step: it converts those three
audited source pairs into a stable integration schema without pretending that
the legacy run was native Stage 04.  It makes no HTTP or API requests.

The program deliberately writes to a separate root:

    derived/replication/api_timeout_enrichment_legacy_normalized/

It never writes inside the native canonical Stage 04 root
``derived/replication/api_timeout_enrichment``.  The later 24-month reconciler
may consume both roots, but their provenance classes remain distinct.

Important field decisions
=========================

* ``request_ordinal`` is a deterministic integration ordinal: zero-based
  lexicographic ``game_id`` order within month.  It is not represented as the
  unavailable historical API request order.
* ``is_draw`` is derived from the PGN result and is checked against the API
  winner.  The legacy ``draw`` field (winner is null) is retained in a keyed
  evidence sidecar and is not used mechanically as the final outcome.
* ``white_rating_diff`` and ``black_rating_diff`` come from the audited PGN
  candidate tags.  The API lookup did not retain API ratingDiff fields.  The
  source is declared in the evidence sidecar and field-contract manifest.
* ``retrieved_utc`` and ``unit_index`` are null because the corresponding
  historical provenance was not retained.  They are never reconstructed.

Safety and restartability
=========================

* Default invocation is a write-free plan.
* ``--execute`` is required for any output.
* All large source files are authenticated against locked SHA-256 values.
* The producing legacy script and canonical comparison script are also
  authenticated.
* Each month is built under an isolated temporary directory, validated, and
  then atomically renamed into place.
* A completed, authenticated month is skipped on a rerun.
* An existing but unauthenticated final month directory causes a hard failure.
* Interrupted temporary directories are moved to a timestamped ``_stale``
  quarantine inside this output root; they are never deleted silently.
* Structured run, month, schema, source, software, and failure manifests are
  emitted.  A global success marker is published only if every requested month
  passes.

Dependencies
============

Only the Python standard library and DuckDB are required.  The project's
existing virtual environment is expected to provide DuckDB.

Fresh-Terminal example
======================

    ROOT="/Volumes/XT_Pro/lichess_kindness"
    source "$ROOT/venv/bin/activate"
    export PYTHONDONTWRITEBYTECODE=1
    export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
    "$ROOT/venv/bin/python" -B \
      "$ROOT/replication_package/code/04b_normalize_legacy_stage04_late.py" \
      --project-root "$ROOT" \
      --legacy-root "/Users/u6025368/projects/lichess_kindness" \
      --execute

Expected runtime is normally 30--90 minutes on the audited Mac/external-drive
layout, and can approach two hours on a slow filesystem.  Source hashing,
external sorting, Parquet compression, and output hashing are all included.
The run may need roughly 10--25 GB of temporary free space.  Memory is bounded
by ``--memory-limit`` (default: 8GB).
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import platform
import shlex
import shutil
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCRIPT_VERSION = "1.0.1"
LOCKED_SAMPLE_START = "2023-11-01"
LOCKED_SAMPLE_END = "2025-10-31"
LATE_MONTHS = ("2025-08", "2025-09", "2025-10")

NATIVE_RELATIVE_ROOT = Path("derived/replication/api_timeout_enrichment")
DEFAULT_OUTPUT_RELATIVE_ROOT = Path(
    "derived/replication/api_timeout_enrichment_legacy_normalized"
)

LEGACY_PRODUCER_RELATIVE_PATH = Path(
    "scripts/02_enrich_timeforfeit_status_streaming_sharded.py"
)
LEGACY_PRODUCER_SHA256 = (
    "d2f029562f56908f05429fd90c51115e0ff80224a7823d526d0b172bb2547f54"
)
CANONICAL_STAGE04_RELATIVE_PATH = Path(
    "replication_package/code/04_enrich_timeout_candidates.py"
)
CANONICAL_STAGE04_SHA256 = (
    "2c1c23d4d867ce3a5a725cf4761e23f9f512c0063a3b7fc1f3d1f9ffe6d840fa"
)

EXPECTED_CANDIDATE_HEADER = (
    "archive_month",
    "game_id",
    "site",
    "event",
    "utc_date",
    "utc_time",
    "white",
    "black",
    "white_elo",
    "black_elo",
    "white_rating_diff",
    "black_rating_diff",
    "result",
    "termination",
    "time_control",
    "tc_base_s",
    "tc_inc_s",
    "last_mover_color",
    "candidate_chooser",
    "candidate_chooser_color",
    "candidate_chooser_elo",
    "likely_disconnected_player",
    "likely_disconnected_color",
    "likely_disconnected_elo",
    "white_clock_last_obs_s",
    "black_clock_last_obs_s",
    "chooser_clock_last_obs_s",
    "disconnected_clock_last_obs_s",
    "clock_gap_chooser_minus_disconnected_s",
    "disconnected_clock_positive",
    "chooser_raw_win",
    "raw_draw",
    "last_move_uci",
    "last_move_san",
    "ply_count",
    "side_to_move_after_last",
    "fen_after_last_move",
    "tournament_like_event",
)

EXPECTED_LOOKUP_HEADER = (
    "id",
    "status",
    "winner",
    "draw",
    "speed",
    "perf",
    "rated",
    "variant",
    "createdAt",
    "lastMoveAt",
    "white_name",
    "black_name",
    "white_rating",
    "black_rating",
)

# This is the 24-column native Stage 04 *field order*.  In this legacy adapter
# retrieved_utc and unit_index are intentionally nullable, so the output is an
# integration representation rather than a native Stage 04 artifact.
CORE_COLUMNS = (
    "month",
    "request_ordinal",
    "game_id",
    "api_target",
    "pgn_timeforfeit_candidate",
    "api_status",
    "winner",
    "is_draw",
    "speed",
    "perf",
    "rated",
    "variant",
    "created_at_ms",
    "last_move_at_ms",
    "white_username",
    "white_username_norm",
    "white_rating",
    "white_rating_diff",
    "black_username",
    "black_username_norm",
    "black_rating",
    "black_rating_diff",
    "retrieved_utc",
    "unit_index",
)

EVIDENCE_COLUMNS = (
    "month",
    "game_id",
    "pgn_result",
    "legacy_draw_winner_null",
    "is_draw",
    "is_draw_source",
    "rating_diff_source",
    "request_ordinal_basis",
    "provenance_class",
)


@dataclass(frozen=True)
class MonthSpec:
    """Immutable source and reconciliation contract for one audited month."""

    month: str
    candidate_relative_path: str
    candidate_sha256: str
    lookup_relative_path: str
    lookup_sha256: str
    summary_relative_path: str
    summary_sha256: str
    target_rows: int
    timeout_rows: int
    outoftime_rows: int
    white_winner_rows: int
    black_winner_rows: int
    draw_rows: int


MONTH_SPECS: Mapping[str, MonthSpec] = {
    "2025-08": MonthSpec(
        month="2025-08",
        candidate_relative_path=(
            "output/2025-08_candidates_split_5s_20260403_002014/"
            "targeted_ge5s_or_missing.csv"
        ),
        candidate_sha256=(
            "90a25df3bec29dcd750d56aeedfad1e83a5e522182cb0fda1e9c0b621fa18dfc"
        ),
        lookup_relative_path=(
            "output/2025-08_lookup_targeted5s_auth300_20260403_114120/"
            "game_status_lookup.csv"
        ),
        lookup_sha256=(
            "8a3f4f649da6c35754630ee6d68e5f2c8a8ea92579a50418f72e5ee9ff14caad"
        ),
        summary_relative_path=(
            "output/2025-08_lookup_targeted5s_auth300_20260403_114120/summary.json"
        ),
        summary_sha256=(
            "f2c07587d7b57d6b84fc04ae92146e29a55c5f8647aeb4f9df71e4d1ac1b2744"
        ),
        target_rows=6_961_261,
        timeout_rows=1_930_170,
        outoftime_rows=5_031_091,
        white_winner_rows=3_536_746,
        black_winner_rows=3_387_105,
        draw_rows=37_410,
    ),
    "2025-09": MonthSpec(
        month="2025-09",
        candidate_relative_path=(
            "output/2025-09_candidates_split_5s_20260403_002014/"
            "targeted_ge5s_or_missing.csv"
        ),
        candidate_sha256=(
            "fd226766f2569ac0ebf3be959f6e09c1120f5d619c9852a3a799dfd0b9a18469"
        ),
        lookup_relative_path=(
            "output/2025-09_lookup_targeted5s_auth300_20260405_011637/"
            "game_status_lookup.csv"
        ),
        lookup_sha256=(
            "9ac95692d7308d7da1ef291e1b3038deca87aaa12c778cd6be4be46c5a6f45ab"
        ),
        summary_relative_path=(
            "output/2025-09_lookup_targeted5s_auth300_20260405_011637/summary.json"
        ),
        summary_sha256=(
            "15bb0d939bc235e7de55454908af347a4ab6aa4e67e34687e3622c7dfbe9df60"
        ),
        target_rows=6_698_493,
        timeout_rows=1_881_564,
        outoftime_rows=4_816_929,
        white_winner_rows=3_404_363,
        black_winner_rows=3_256_972,
        draw_rows=37_158,
    ),
    "2025-10": MonthSpec(
        month="2025-10",
        candidate_relative_path=(
            "output/2025-10_candidates_split_5s_20260403_002014/"
            "targeted_ge5s_or_missing.csv"
        ),
        candidate_sha256=(
            "cfe4d84962edd078d5ca725963132b9fb0a0f43c6dd72d8803ef89d95d6b11d2"
        ),
        lookup_relative_path=(
            "output/2025-10_lookup_targeted5s_auth300_20260406_132615/"
            "game_status_lookup.csv"
        ),
        lookup_sha256=(
            "e425ee128b2fe127b45ccb9b64ed394e7042ecdb80355525f650bdb1f963a871"
        ),
        summary_relative_path=(
            "output/2025-10_lookup_targeted5s_auth300_20260406_132615/summary.json"
        ),
        summary_sha256=(
            "155629053b587be9bcd1afe25ad50a4d8db728417e3e6c969f6c7133716338c7"
        ),
        target_rows=7_029_411,
        timeout_rows=1_999_063,
        outoftime_rows=5_030_348,
        white_winner_rows=3_571_120,
        black_winner_rows=3_418_906,
        draw_rows=39_385,
    ),
}


FIELD_CONTRACT: Sequence[Mapping[str, Any]] = (
    {
        "field": "month",
        "mapping": "candidate.archive_month",
        "availability": "direct",
    },
    {
        "field": "request_ordinal",
        "mapping": "zero-based lexicographic game_id order within month",
        "availability": "deterministic_adapter_value_not_historical_request_order",
    },
    {"field": "game_id", "mapping": "lookup.id", "availability": "direct"},
    {
        "field": "api_target",
        "mapping": "constant true after exact audited target-ID reconciliation",
        "availability": "deterministic",
    },
    {
        "field": "pgn_timeforfeit_candidate",
        "mapping": "constant true for audited candidate universe",
        "availability": "deterministic",
    },
    {"field": "api_status", "mapping": "lookup.status", "availability": "direct"},
    {"field": "winner", "mapping": "lookup.winner", "availability": "direct"},
    {
        "field": "is_draw",
        "mapping": "candidate.result == '1/2-1/2', verified against API winner",
        "availability": "adjudicated",
    },
    {"field": "speed", "mapping": "lookup.speed", "availability": "direct"},
    {"field": "perf", "mapping": "lookup.perf", "availability": "direct"},
    {"field": "rated", "mapping": "lookup.rated", "availability": "direct"},
    {"field": "variant", "mapping": "lookup.variant", "availability": "direct"},
    {"field": "created_at_ms", "mapping": "lookup.createdAt", "availability": "direct"},
    {
        "field": "last_move_at_ms",
        "mapping": "lookup.lastMoveAt",
        "availability": "direct",
    },
    {
        "field": "white_username",
        "mapping": "lookup.white_name",
        "availability": "direct",
    },
    {
        "field": "white_username_norm",
        "mapping": "lower(trim(lookup.white_name)); audited usernames are ASCII",
        "availability": "deterministic",
    },
    {
        "field": "white_rating",
        "mapping": "lookup.white_rating",
        "availability": "direct",
    },
    {
        "field": "white_rating_diff",
        "mapping": "candidate.white_rating_diff PGN tag",
        "availability": "direct_pgn_not_retained_api_field",
    },
    {
        "field": "black_username",
        "mapping": "lookup.black_name",
        "availability": "direct",
    },
    {
        "field": "black_username_norm",
        "mapping": "lower(trim(lookup.black_name)); audited usernames are ASCII",
        "availability": "deterministic",
    },
    {
        "field": "black_rating",
        "mapping": "lookup.black_rating",
        "availability": "direct",
    },
    {
        "field": "black_rating_diff",
        "mapping": "candidate.black_rating_diff PGN tag",
        "availability": "direct_pgn_not_retained_api_field",
    },
    {
        "field": "retrieved_utc",
        "mapping": None,
        "availability": "historically_unavailable_null_never_reconstructed",
    },
    {
        "field": "unit_index",
        "mapping": None,
        "availability": "historically_unavailable_null_never_reconstructed",
    },
)

HISTORICAL_PROVENANCE_GAPS = (
    "complete raw API response retention",
    "per-request API telemetry",
    "canonical 30,000-ID request units",
    "canonical unit checkpoints",
    "per-record retrieval UTC",
)


class ContractError(RuntimeError):
    """Raised when a fail-closed source or output contract is violated."""


def utc_now() -> str:
    """Return an RFC-3339-like UTC timestamp with whole-second precision."""

    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_id() -> str:
    """Return a sortable, collision-resistant run label."""

    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"_{os.getpid()}"


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    """Hash a file without loading it into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_text(path: Path, text: str) -> None:
    """Write text beside its destination, fsync it, and atomically replace."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{os.getpid()}")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def atomic_write_json(path: Path, payload: Any) -> None:
    """Write stable, human-readable JSON atomically."""

    atomic_write_text(
        path,
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    )


def write_csv(path: Path, rows: Iterable[Mapping[str, Any]], fieldnames: Sequence[str]) -> None:
    """Write a small manifest CSV atomically."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{os.getpid()}")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def read_json(path: Path) -> Any:
    """Read UTF-8 JSON."""

    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def sql_string(value: str | Path) -> str:
    """Return a safely quoted DuckDB string literal."""

    return "'" + str(value).replace("'", "''") + "'"


def first_csv_header(path: Path) -> tuple[str, ...]:
    """Read only the header record from a CSV source."""

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            return tuple(next(reader))
        except StopIteration as exc:
            raise ContractError(f"CSV is empty: {path}") from exc


class EventLog:
    """Print concise progress and mirror structured events to JSONL."""

    def __init__(self, path: Path | None) -> None:
        self.path = path

    def emit(self, message: str, **details: Any) -> None:
        stamp = utc_now()
        print(f"[{stamp}] {message}", flush=True)
        if self.path is None:
            return
        payload = {"utc": stamp, "message": message, **details}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
            handle.flush()


def import_duckdb() -> Any:
    """Import DuckDB with a direct installation diagnostic."""

    try:
        import duckdb  # type: ignore
    except ImportError as exc:
        raise ContractError(
            "DuckDB is required but is not importable in this Python environment. "
            "Activate the project venv and verify with: python -c 'import duckdb'."
        ) from exc
    return duckdb


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse a plan-by-default command line."""

    parser = argparse.ArgumentParser(
        description=(
            "Normalize the audited 2025-08 through 2025-10 legacy API layer "
            "without API requests or native-provenance fabrication."
        )
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path("/Volumes/XT_Pro/lichess_kindness"),
        help="Canonical project root on XT_Pro.",
    )
    parser.add_argument(
        "--legacy-root",
        type=Path,
        default=Path("/Users/u6025368/projects/lichess_kindness"),
        help="Local project root holding the audited legacy source files.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help=(
            "Dedicated legacy-normalized output root. Defaults below the canonical "
            "project root and must not equal or sit inside the native Stage 04 root."
        ),
    )
    parser.add_argument(
        "--months",
        nargs="+",
        choices=LATE_MONTHS,
        default=list(LATE_MONTHS),
        help="Requested late months; all three are selected by default.",
    )
    parser.add_argument(
        "--memory-limit",
        default="8GB",
        help="DuckDB memory limit, for example 6GB, 8GB, or 12GB.",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=4,
        help="DuckDB worker threads. Numerical-library env vars should remain capped.",
    )
    parser.add_argument(
        "--row-group-size",
        type=int,
        default=250_000,
        help="Parquet row-group size.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Perform the transformation. Without this flag the program is write-free.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run a tiny isolated end-to-end fixture and exit.",
    )
    return parser.parse_args(argv)


def resolve_output_root(args: argparse.Namespace) -> Path:
    """Resolve the dedicated output root and enforce native-root separation."""

    project_root = args.project_root.resolve()
    native_root = (project_root / NATIVE_RELATIVE_ROOT).resolve()
    output_root = (
        args.output_root.resolve()
        if args.output_root is not None
        else (project_root / DEFAULT_OUTPUT_RELATIVE_ROOT).resolve()
    )

    if output_root == native_root or native_root in output_root.parents:
        raise ContractError(
            f"Legacy-normalized output must not equal or sit inside native Stage 04: "
            f"{native_root}"
        )
    if output_root == project_root:
        raise ContractError("Refusing to use the project root itself as output root.")
    return output_root


def validate_cli(args: argparse.Namespace) -> None:
    """Reject nonsensical resource or month settings before any write."""

    if args.threads < 1:
        raise ContractError("--threads must be at least 1")
    if args.row_group_size < 10_000:
        raise ContractError("--row-group-size must be at least 10,000")
    if len(set(args.months)) != len(args.months):
        raise ContractError("--months contains a duplicate")


def source_paths(spec: MonthSpec, legacy_root: Path) -> Mapping[str, Path]:
    """Resolve one month's locked relative source paths."""

    return {
        "candidate": legacy_root / spec.candidate_relative_path,
        "lookup": legacy_root / spec.lookup_relative_path,
        "summary": legacy_root / spec.summary_relative_path,
    }


def validate_static_sources(
    args: argparse.Namespace,
    output_root: Path,
    logger: EventLog,
    *,
    verify_hashes: bool,
) -> Mapping[str, Any]:
    """Validate roots, collisions, headers, and optionally all locked hashes."""

    project_root = args.project_root.resolve()
    legacy_root = args.legacy_root.resolve()
    if not project_root.is_dir():
        raise ContractError(f"Canonical project root does not exist: {project_root}")
    if not legacy_root.is_dir():
        raise ContractError(f"Legacy project root does not exist: {legacy_root}")

    legacy_script = legacy_root / LEGACY_PRODUCER_RELATIVE_PATH
    canonical_script = project_root / CANONICAL_STAGE04_RELATIVE_PATH
    expected_scripts = (
        ("legacy_producer", legacy_script, LEGACY_PRODUCER_SHA256),
        ("canonical_stage04", canonical_script, CANONICAL_STAGE04_SHA256),
    )

    inventory: dict[str, Any] = {"scripts": {}, "months": {}}
    for label, path, expected_hash in expected_scripts:
        if not path.is_file():
            raise ContractError(f"Required {label} script is missing: {path}")
        actual_hash = sha256_file(path) if verify_hashes else None
        if verify_hashes and actual_hash != expected_hash:
            raise ContractError(
                f"{label} SHA-256 mismatch: expected {expected_hash}, got {actual_hash}"
            )
        inventory["scripts"][label] = {
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "expected_sha256": expected_hash,
            "sha256": actual_hash,
            "sha256_match": actual_hash == expected_hash if verify_hashes else None,
        }

    native_root = project_root / NATIVE_RELATIVE_ROOT
    for month in args.months:
        spec = MONTH_SPECS[month]
        native_month = native_root / f"month={month}"
        if native_month.exists():
            raise ContractError(
                f"Native Stage 04 month already exists; refusing an ambiguous collision: "
                f"{native_month}"
            )

        paths = source_paths(spec, legacy_root)
        expected_hashes = {
            "candidate": spec.candidate_sha256,
            "lookup": spec.lookup_sha256,
            "summary": spec.summary_sha256,
        }
        month_record: dict[str, Any] = {
            "contract": asdict(spec),
            "native_month_collision": False,
            "files": {},
        }
        for label, path in paths.items():
            if not path.is_file():
                raise ContractError(f"Missing {month} {label} source: {path}")
            actual_hash = sha256_file(path) if verify_hashes else None
            expected_hash = expected_hashes[label]
            if verify_hashes and actual_hash != expected_hash:
                raise ContractError(
                    f"{month} {label} SHA-256 mismatch: expected {expected_hash}, "
                    f"got {actual_hash}"
                )
            month_record["files"][label] = {
                "path": str(path),
                "size_bytes": path.stat().st_size,
                "expected_sha256": expected_hash,
                "sha256": actual_hash,
                "sha256_match": actual_hash == expected_hash if verify_hashes else None,
            }

        candidate_header = first_csv_header(paths["candidate"])
        lookup_header = first_csv_header(paths["lookup"])
        if candidate_header != EXPECTED_CANDIDATE_HEADER:
            raise ContractError(
                f"{month} candidate header mismatch. Expected {EXPECTED_CANDIDATE_HEADER}; "
                f"got {candidate_header}"
            )
        if lookup_header != EXPECTED_LOOKUP_HEADER:
            raise ContractError(
                f"{month} lookup header mismatch. Expected {EXPECTED_LOOKUP_HEADER}; "
                f"got {lookup_header}"
            )
        month_record["candidate_header"] = list(candidate_header)
        month_record["lookup_header"] = list(lookup_header)
        inventory["months"][month] = month_record
        logger.emit(
            f"{month}: source paths and headers pass"
            + ("; hashes pass" if verify_hashes else " (hashes deferred to --execute)"),
            month=month,
        )

    inventory["output_root"] = str(output_root)
    inventory["verified_hashes"] = verify_hashes
    return inventory


def configure_duckdb(
    connection: Any,
    *,
    temp_directory: Path,
    memory_limit: str,
    threads: int,
) -> None:
    """Apply bounded, deterministic-enough DuckDB execution settings."""

    temp_directory.mkdir(parents=True, exist_ok=True)
    connection.execute(f"SET memory_limit = {sql_string(memory_limit)}")
    connection.execute(f"SET threads = {int(threads)}")
    connection.execute(f"SET temp_directory = {sql_string(temp_directory)}")
    connection.execute("SET preserve_insertion_order = false")
    try:
        connection.execute("PRAGMA enable_progress_bar")
    except Exception:
        # Very old DuckDB releases may not expose this pragma.  Progress bars
        # are ergonomic only and have no bearing on correctness.
        pass


def scalar(connection: Any, query: str) -> Any:
    """Execute a query that must return one row and one column."""

    row = connection.execute(query).fetchone()
    if row is None or len(row) != 1:
        raise ContractError(f"Expected one scalar result from query: {query[:160]}")
    return row[0]


def query_one_dict(connection: Any, query: str) -> Mapping[str, Any]:
    """Return exactly one SQL row as a dictionary."""

    cursor = connection.execute(query)
    columns = [description[0] for description in cursor.description]
    row = cursor.fetchone()
    if row is None or cursor.fetchone() is not None:
        raise ContractError("Expected exactly one row from validation query")
    return dict(zip(columns, row))


def parquet_schema(connection: Any, path: Path) -> Sequence[Mapping[str, Any]]:
    """Read the physical Parquet schema without Hive-directory inference.

    Production months are first written below a directory whose name contains
    ``.month=YYYY-MM.partial``.  DuckDB otherwise interprets the ``=`` as a
    Hive partition and adds a virtual ``.month`` column that is not physically
    present in the Parquet file.  Explicitly disabling inference makes this
    validator inspect the file contract itself.
    """

    cursor = connection.execute(
        f"DESCRIBE SELECT * FROM read_parquet("
        f"{sql_string(path)}, hive_partitioning=false)"
    )
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def assert_equal(actual: Any, expected: Any, label: str) -> None:
    """Raise a contract error with a compact value comparison."""

    if actual != expected:
        raise ContractError(f"{label}: expected {expected!r}, got {actual!r}")


def build_month_sql(
    *,
    spec: MonthSpec,
    candidate_path: Path,
    lookup_path: Path,
    core_output: Path,
    evidence_output: Path,
    row_group_size: int,
) -> Mapping[str, str]:
    """Return the documented DuckDB statements used for one month."""

    candidate_reader = (
        "read_csv_auto("
        f"{sql_string(candidate_path)}, header=true, all_varchar=true, "
        "sample_size=20480, parallel=true)"
    )
    lookup_reader = (
        "read_csv_auto("
        f"{sql_string(lookup_path)}, header=true, all_varchar=true, "
        "sample_size=20480, parallel=true)"
    )

    load_candidate = f"""
        CREATE TABLE candidate AS
        SELECT
            trim(game_id) AS game_id,
            trim(archive_month) AS archive_month,
            trim(result) AS pgn_result,
            nullif(trim(white_rating_diff), '') AS white_rating_diff_raw,
            nullif(trim(black_rating_diff), '') AS black_rating_diff_raw
        FROM {candidate_reader}
    """

    load_lookup = f"""
        CREATE TABLE lookup AS
        SELECT
            trim(id) AS game_id,
            lower(trim(status)) AS api_status,
            nullif(lower(trim(winner)), '') AS winner,
            lower(trim(draw)) AS legacy_draw_raw,
            nullif(trim(speed), '') AS speed,
            nullif(trim(perf), '') AS perf,
            lower(trim(rated)) AS rated_raw,
            nullif(trim(variant), '') AS variant,
            nullif(trim(createdAt), '') AS created_at_raw,
            nullif(trim(lastMoveAt), '') AS last_move_at_raw,
            nullif(trim(white_name), '') AS white_username,
            nullif(trim(black_name), '') AS black_username,
            nullif(trim(white_rating), '') AS white_rating_raw,
            nullif(trim(black_rating), '') AS black_rating_raw
        FROM {lookup_reader}
    """

    # The normalized work table is deliberately richer than the compact core.
    # It allows both output files to be created from exactly the same join.
    create_normalized = f"""
        CREATE TABLE normalized AS
        WITH joined AS (
            SELECT
                c.game_id,
                c.archive_month,
                c.pgn_result,
                c.white_rating_diff_raw,
                c.black_rating_diff_raw,
                l.api_status,
                l.winner,
                l.legacy_draw_raw,
                l.speed,
                l.perf,
                l.rated_raw,
                l.variant,
                l.created_at_raw,
                l.last_move_at_raw,
                l.white_username,
                l.black_username,
                l.white_rating_raw,
                l.black_rating_raw
            FROM candidate AS c
            INNER JOIN lookup AS l USING (game_id)
        ), ordered AS (
            SELECT
                row_number() OVER (ORDER BY game_id) - 1 AS request_ordinal,
                *
            FROM joined
        )
        SELECT
            CAST(archive_month AS VARCHAR) AS month,
            CAST(request_ordinal AS BIGINT) AS request_ordinal,
            CAST(game_id AS VARCHAR) AS game_id,
            CAST(true AS BOOLEAN) AS api_target,
            CAST(true AS BOOLEAN) AS pgn_timeforfeit_candidate,
            CAST(api_status AS VARCHAR) AS api_status,
            CAST(winner AS VARCHAR) AS winner,
            CAST(pgn_result = '1/2-1/2' AS BOOLEAN) AS is_draw,
            CAST(speed AS VARCHAR) AS speed,
            CAST(perf AS VARCHAR) AS perf,
            CAST(
                CASE
                    WHEN rated_raw IN ('true', '1', 't', 'yes') THEN true
                    WHEN rated_raw IN ('false', '0', 'f', 'no') THEN false
                    ELSE NULL
                END AS BOOLEAN
            ) AS rated,
            CAST(variant AS VARCHAR) AS variant,
            CAST(created_at_raw AS BIGINT) AS created_at_ms,
            CAST(last_move_at_raw AS BIGINT) AS last_move_at_ms,
            CAST(white_username AS VARCHAR) AS white_username,
            CAST(lower(white_username) AS VARCHAR) AS white_username_norm,
            CAST(white_rating_raw AS INTEGER) AS white_rating,
            CAST(white_rating_diff_raw AS INTEGER) AS white_rating_diff,
            CAST(black_username AS VARCHAR) AS black_username,
            CAST(lower(black_username) AS VARCHAR) AS black_username_norm,
            CAST(black_rating_raw AS INTEGER) AS black_rating,
            CAST(black_rating_diff_raw AS INTEGER) AS black_rating_diff,
            CAST(NULL AS VARCHAR) AS retrieved_utc,
            CAST(NULL AS INTEGER) AS unit_index,
            CAST(pgn_result AS VARCHAR) AS pgn_result,
            CAST(
                CASE
                    WHEN legacy_draw_raw IN ('true', '1', 't', 'yes') THEN true
                    WHEN legacy_draw_raw IN ('false', '0', 'f', 'no') THEN false
                    ELSE NULL
                END AS BOOLEAN
            ) AS legacy_draw_winner_null,
            CAST('pgn_result_verified_against_api_winner' AS VARCHAR) AS is_draw_source,
            CAST('pgn_candidate_tag_not_retained_api_ratingdiff' AS VARCHAR)
                AS rating_diff_source,
            CAST('lexicographic_game_id_zero_based' AS VARCHAR)
                AS request_ordinal_basis,
            CAST('legacy_normalized_not_native_stage04' AS VARCHAR)
                AS provenance_class
        FROM ordered
    """

    core_select = ", ".join(CORE_COLUMNS)
    evidence_select = ", ".join(EVIDENCE_COLUMNS)
    copy_core = f"""
        COPY (
            SELECT {core_select}
            FROM normalized
            ORDER BY request_ordinal
        ) TO {sql_string(core_output)}
        (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE {int(row_group_size)})
    """
    copy_evidence = f"""
        COPY (
            SELECT {evidence_select}
            FROM normalized
            ORDER BY game_id
        ) TO {sql_string(evidence_output)}
        (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE {int(row_group_size)})
    """
    return {
        "load_candidate": load_candidate,
        "load_lookup": load_lookup,
        "create_normalized": create_normalized,
        "copy_core": copy_core,
        "copy_evidence": copy_evidence,
    }


def validate_loaded_tables(connection: Any, spec: MonthSpec) -> Mapping[str, Any]:
    """Prove source row, uniqueness, set-equality, status, and outcome gates."""

    candidate = query_one_dict(
        connection,
        """
        SELECT
            count(*) AS rows,
            count(DISTINCT game_id) AS unique_ids,
            count(*) FILTER (WHERE game_id IS NULL OR game_id = '') AS missing_ids,
            count(*) FILTER (WHERE archive_month IS DISTINCT FROM '"""
        + spec.month
        + """') AS wrong_month_rows,
            count(*) FILTER (WHERE pgn_result NOT IN ('1-0','0-1','1/2-1/2'))
                AS unexpected_result_rows,
            count(*) FILTER (
                WHERE white_rating_diff_raw IS NOT NULL
                  AND try_cast(white_rating_diff_raw AS INTEGER) IS NULL
            ) AS invalid_white_rating_diff_rows,
            count(*) FILTER (
                WHERE black_rating_diff_raw IS NOT NULL
                  AND try_cast(black_rating_diff_raw AS INTEGER) IS NULL
            ) AS invalid_black_rating_diff_rows
        FROM candidate
        """,
    )
    lookup = query_one_dict(
        connection,
        """
        SELECT
            count(*) AS rows,
            count(DISTINCT game_id) AS unique_ids,
            count(*) FILTER (WHERE game_id IS NULL OR game_id = '') AS missing_ids,
            count(*) FILTER (WHERE api_status = 'timeout') AS timeout_rows,
            count(*) FILTER (WHERE api_status = 'outoftime') AS outoftime_rows,
            count(*) FILTER (WHERE api_status NOT IN ('timeout','outoftime')
                             OR api_status IS NULL) AS unexpected_status_rows,
            count(*) FILTER (WHERE winner = 'white') AS white_winner_rows,
            count(*) FILTER (WHERE winner = 'black') AS black_winner_rows,
            count(*) FILTER (WHERE winner IS NULL) AS no_winner_rows,
            count(*) FILTER (WHERE winner NOT IN ('white','black')
                             AND winner IS NOT NULL) AS unexpected_winner_rows,
            count(*) FILTER (WHERE rated_raw NOT IN
                ('true','false','1','0','t','f','yes','no')) AS invalid_rated_rows,
            count(*) FILTER (WHERE try_cast(created_at_raw AS BIGINT) IS NULL)
                AS invalid_created_at_rows,
            count(*) FILTER (WHERE try_cast(last_move_at_raw AS BIGINT) IS NULL)
                AS invalid_last_move_at_rows,
            count(*) FILTER (
                WHERE try_cast(last_move_at_raw AS BIGINT)
                    < try_cast(created_at_raw AS BIGINT)
            ) AS timestamp_order_violations,
            count(*) FILTER (WHERE try_cast(white_rating_raw AS INTEGER) IS NULL)
                AS invalid_white_rating_rows,
            count(*) FILTER (WHERE try_cast(black_rating_raw AS INTEGER) IS NULL)
                AS invalid_black_rating_rows
        FROM lookup
        """,
    )
    join = query_one_dict(
        connection,
        """
        SELECT
            count(*) AS joined_rows,
            count(*) FILTER (
                WHERE (c.pgn_result = '1-0' AND l.winner IS DISTINCT FROM 'white')
                   OR (c.pgn_result = '0-1' AND l.winner IS DISTINCT FROM 'black')
                   OR (c.pgn_result = '1/2-1/2' AND l.winner IS NOT NULL)
            ) AS pgn_result_vs_api_winner_mismatch_rows,
            count(*) FILTER (
                WHERE (l.legacy_draw_raw IN ('true','1','t','yes'))
                      IS DISTINCT FROM (c.pgn_result = '1/2-1/2')
            ) AS legacy_draw_vs_pgn_result_mismatch_rows
        FROM candidate AS c
        INNER JOIN lookup AS l USING (game_id)
        """,
    )

    expected = {
        "candidate.rows": spec.target_rows,
        "candidate.unique_ids": spec.target_rows,
        "candidate.missing_ids": 0,
        "candidate.wrong_month_rows": 0,
        "candidate.unexpected_result_rows": 0,
        "candidate.invalid_white_rating_diff_rows": 0,
        "candidate.invalid_black_rating_diff_rows": 0,
        "lookup.rows": spec.target_rows,
        "lookup.unique_ids": spec.target_rows,
        "lookup.missing_ids": 0,
        "lookup.timeout_rows": spec.timeout_rows,
        "lookup.outoftime_rows": spec.outoftime_rows,
        "lookup.unexpected_status_rows": 0,
        "lookup.white_winner_rows": spec.white_winner_rows,
        "lookup.black_winner_rows": spec.black_winner_rows,
        "lookup.no_winner_rows": spec.draw_rows,
        "lookup.unexpected_winner_rows": 0,
        "lookup.invalid_rated_rows": 0,
        "lookup.invalid_created_at_rows": 0,
        "lookup.invalid_last_move_at_rows": 0,
        "lookup.timestamp_order_violations": 0,
        "lookup.invalid_white_rating_rows": 0,
        "lookup.invalid_black_rating_rows": 0,
        "join.joined_rows": spec.target_rows,
        "join.pgn_result_vs_api_winner_mismatch_rows": 0,
        "join.legacy_draw_vs_pgn_result_mismatch_rows": 0,
    }
    observed: dict[str, Any] = {}
    for section_name, section in (
        ("candidate", candidate),
        ("lookup", lookup),
        ("join", join),
    ):
        for key, value in section.items():
            observed[f"{section_name}.{key}"] = value
    for label, expected_value in expected.items():
        assert_equal(observed[label], expected_value, f"{spec.month} {label}")
    return {
        "candidate": dict(candidate),
        "lookup": dict(lookup),
        "join": dict(join),
        "all_gates_pass": True,
    }


def validate_outputs(
    connection: Any,
    spec: MonthSpec,
    core_output: Path,
    evidence_output: Path,
) -> Mapping[str, Any]:
    """Validate the two Parquet products after they are physically written."""

    if not core_output.is_file() or not evidence_output.is_file():
        raise ContractError(f"{spec.month}: expected Parquet output is missing")

    core = query_one_dict(
        connection,
        f"""
        SELECT
            count(*) AS rows,
            count(DISTINCT game_id) AS unique_ids,
            min(request_ordinal) AS min_request_ordinal,
            max(request_ordinal) AS max_request_ordinal,
            count(DISTINCT request_ordinal) AS unique_request_ordinals,
            count(*) FILTER (WHERE api_status = 'timeout') AS timeout_rows,
            count(*) FILTER (WHERE api_status = 'outoftime') AS outoftime_rows,
            count(*) FILTER (WHERE is_draw) AS draw_rows,
            count(*) FILTER (WHERE retrieved_utc IS NOT NULL) AS retrieved_utc_present,
            count(*) FILTER (WHERE unit_index IS NOT NULL) AS unit_index_present,
            count(*) FILTER (WHERE month IS DISTINCT FROM {sql_string(spec.month)})
                AS wrong_month_rows
        FROM read_parquet({sql_string(core_output)}, hive_partitioning=false)
        """,
    )
    evidence = query_one_dict(
        connection,
        f"""
        SELECT
            count(*) AS rows,
            count(DISTINCT game_id) AS unique_ids,
            count(*) FILTER (
                WHERE legacy_draw_winner_null IS DISTINCT FROM is_draw
            ) AS legacy_draw_vs_is_draw_mismatch_rows,
            count(*) FILTER (
                WHERE provenance_class IS DISTINCT FROM
                    'legacy_normalized_not_native_stage04'
            ) AS wrong_provenance_rows
        FROM read_parquet({sql_string(evidence_output)}, hive_partitioning=false)
        """,
    )

    core_expected = {
        "rows": spec.target_rows,
        "unique_ids": spec.target_rows,
        "min_request_ordinal": 0,
        "max_request_ordinal": spec.target_rows - 1,
        "unique_request_ordinals": spec.target_rows,
        "timeout_rows": spec.timeout_rows,
        "outoftime_rows": spec.outoftime_rows,
        "draw_rows": spec.draw_rows,
        "retrieved_utc_present": 0,
        "unit_index_present": 0,
        "wrong_month_rows": 0,
    }
    evidence_expected = {
        "rows": spec.target_rows,
        "unique_ids": spec.target_rows,
        "legacy_draw_vs_is_draw_mismatch_rows": 0,
        "wrong_provenance_rows": 0,
    }
    for key, value in core_expected.items():
        assert_equal(core[key], value, f"{spec.month} output core.{key}")
    for key, value in evidence_expected.items():
        assert_equal(evidence[key], value, f"{spec.month} output evidence.{key}")

    core_schema = list(parquet_schema(connection, core_output))
    evidence_schema = list(parquet_schema(connection, evidence_output))
    core_names = tuple(row["column_name"] for row in core_schema)
    evidence_names = tuple(row["column_name"] for row in evidence_schema)
    assert_equal(core_names, CORE_COLUMNS, f"{spec.month} core column order")
    assert_equal(evidence_names, EVIDENCE_COLUMNS, f"{spec.month} evidence column order")

    return {
        "core": dict(core),
        "evidence": dict(evidence),
        "core_schema": core_schema,
        "evidence_schema": evidence_schema,
        "all_gates_pass": True,
    }


def existing_month_is_reusable(
    month_dir: Path,
    spec: MonthSpec,
    logger: EventLog,
) -> Mapping[str, Any] | None:
    """Authenticate a completed month sufficiently to resume without overwrite."""

    if not month_dir.exists():
        return None
    if not month_dir.is_dir():
        raise ContractError(f"Existing month path is not a directory: {month_dir}")
    success_path = month_dir / "_SUCCESS.json"
    if not success_path.is_file():
        raise ContractError(
            f"Existing final month lacks _SUCCESS.json; refusing overwrite: {month_dir}"
        )
    success = read_json(success_path)
    if not success.get("final_ok"):
        raise ContractError(f"Existing month is not final_ok: {month_dir}")
    if success.get("month") != spec.month:
        raise ContractError(f"Existing month success marker has wrong month: {month_dir}")
    source_hashes = success.get("source_sha256", {})
    expected_source_hashes = {
        "candidate": spec.candidate_sha256,
        "lookup": spec.lookup_sha256,
        "summary": spec.summary_sha256,
    }
    if source_hashes != expected_source_hashes:
        raise ContractError(
            f"Existing month was built from different source identities: {month_dir}"
        )

    outputs = success.get("outputs", {})
    for label, relative_path in (
        ("core", "responses/legacy-normalized.parquet"),
        ("evidence", "evidence/legacy-outcome-evidence.parquet"),
    ):
        path = month_dir / relative_path
        if not path.is_file():
            raise ContractError(f"Existing {label} output is missing: {path}")
        expected_hash = outputs.get(label, {}).get("sha256")
        if not expected_hash:
            raise ContractError(f"Existing success marker lacks {label} SHA-256")
        actual_hash = sha256_file(path)
        if actual_hash != expected_hash:
            raise ContractError(
                f"Existing {label} hash mismatch at {path}: "
                f"expected {expected_hash}, got {actual_hash}"
            )
    logger.emit(f"{spec.month}: existing completed output authenticated; skipping")
    return success


def quarantine_stale_partials(output_root: Path, month: str, logger: EventLog) -> None:
    """Move interrupted month work aside with a receipt; never delete it."""

    stale_candidates = sorted(output_root.glob(f".month={month}.partial.*"))
    if not stale_candidates:
        return
    quarantine_root = output_root / "_stale" / run_id()
    quarantine_root.mkdir(parents=True, exist_ok=False)
    moved: list[Mapping[str, str]] = []
    for source in stale_candidates:
        destination = quarantine_root / source.name
        os.replace(source, destination)
        moved.append({"source": str(source), "destination": str(destination)})
    atomic_write_json(
        quarantine_root / "quarantine_receipt.json",
        {
            "created_utc": utc_now(),
            "reason": "interrupted temporary month directories found before resume",
            "month": month,
            "moved": moved,
            "recoverability": "preserved inside dedicated output-root quarantine",
        },
    )
    logger.emit(
        f"{month}: quarantined {len(stale_candidates)} interrupted temporary directory(s)",
        quarantine_root=str(quarantine_root),
    )


def process_month(
    *,
    args: argparse.Namespace,
    output_root: Path,
    spec: MonthSpec,
    source_inventory: Mapping[str, Any],
    logger: EventLog,
    duckdb: Any,
) -> Mapping[str, Any]:
    """Build, validate, hash, and atomically publish one month."""

    final_dir = output_root / f"month={spec.month}"
    reusable = existing_month_is_reusable(final_dir, spec, logger)
    if reusable is not None:
        return {"month": spec.month, "status": "reused", "success": reusable}

    quarantine_stale_partials(output_root, spec.month, logger)
    partial_dir = output_root / f".month={spec.month}.partial.{os.getpid()}"
    partial_dir.mkdir(parents=True, exist_ok=False)
    core_output = partial_dir / "responses" / "legacy-normalized.parquet"
    evidence_output = partial_dir / "evidence" / "legacy-outcome-evidence.parquet"
    work_dir = partial_dir / "_work"
    core_output.parent.mkdir(parents=True, exist_ok=True)
    evidence_output.parent.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    source_files = source_paths(spec, args.legacy_root.resolve())
    sql_statements = build_month_sql(
        spec=spec,
        candidate_path=source_files["candidate"],
        lookup_path=source_files["lookup"],
        core_output=core_output,
        evidence_output=evidence_output,
        row_group_size=args.row_group_size,
    )
    atomic_write_text(
        partial_dir / "transformation.sql",
        "\n\n".join(
            f"-- {name}\n{statement.strip()};" for name, statement in sql_statements.items()
        )
        + "\n",
    )

    started = time.monotonic()
    logger.emit(f"{spec.month}: loading audited CSV sources into bounded DuckDB work tables")
    database_path = work_dir / "normalizer.duckdb"
    connection = duckdb.connect(str(database_path))
    try:
        configure_duckdb(
            connection,
            temp_directory=work_dir / "duckdb_tmp",
            memory_limit=args.memory_limit,
            threads=args.threads,
        )
        connection.execute(sql_statements["load_candidate"])
        connection.execute(sql_statements["load_lookup"])

        logger.emit(f"{spec.month}: enforcing row, uniqueness, coverage, status, and outcome gates")
        source_validation = validate_loaded_tables(connection, spec)

        logger.emit(f"{spec.month}: building deterministic normalized table")
        connection.execute(sql_statements["create_normalized"])
        normalized_rows = scalar(connection, "SELECT count(*) FROM normalized")
        assert_equal(normalized_rows, spec.target_rows, f"{spec.month} normalized rows")

        logger.emit(f"{spec.month}: writing compact response and outcome-evidence Parquets")
        connection.execute(sql_statements["copy_core"])
        connection.execute(sql_statements["copy_evidence"])
        output_validation = validate_outputs(
            connection, spec, core_output, evidence_output
        )
        connection.execute("CHECKPOINT")
    finally:
        connection.close()

    logger.emit(f"{spec.month}: hashing completed Parquet outputs")
    core_hash = sha256_file(core_output)
    evidence_hash = sha256_file(evidence_output)
    elapsed = round(time.monotonic() - started, 3)

    month_manifest = {
        "schema_version": "legacy-stage04-integration-v1",
        "script_version": SCRIPT_VERSION,
        "month": spec.month,
        "provenance_class": "legacy_normalized_not_native_stage04",
        "locked_sample_start": LOCKED_SAMPLE_START,
        "locked_sample_end": LOCKED_SAMPLE_END,
        "source_contract": asdict(spec),
        "source_inventory": source_inventory["months"][spec.month],
        "source_validation": source_validation,
        "output_validation": output_validation,
        "field_contract": list(FIELD_CONTRACT),
        "historical_provenance_gaps": list(HISTORICAL_PROVENANCE_GAPS),
        "elapsed_seconds": elapsed,
        "outputs": {
            "core": {
                "relative_path": "responses/legacy-normalized.parquet",
                "rows": spec.target_rows,
                "size_bytes": core_output.stat().st_size,
                "sha256": core_hash,
            },
            "evidence": {
                "relative_path": "evidence/legacy-outcome-evidence.parquet",
                "rows": spec.target_rows,
                "size_bytes": evidence_output.stat().st_size,
                "sha256": evidence_hash,
            },
        },
        "final_ok": True,
    }
    atomic_write_json(partial_dir / "month_manifest.json", month_manifest)

    success = {
        "final_ok": True,
        "finished_utc": utc_now(),
        "month": spec.month,
        "schema_version": "legacy-stage04-integration-v1",
        "provenance_class": "legacy_normalized_not_native_stage04",
        "target_rows": spec.target_rows,
        "timeout_rows": spec.timeout_rows,
        "outoftime_rows": spec.outoftime_rows,
        "source_sha256": {
            "candidate": spec.candidate_sha256,
            "lookup": spec.lookup_sha256,
            "summary": spec.summary_sha256,
        },
        "outputs": month_manifest["outputs"],
        "historical_provenance_gaps": list(HISTORICAL_PROVENANCE_GAPS),
    }
    atomic_write_json(partial_dir / "_SUCCESS.json", success)

    # The work database is a reproducible intermediate and can be very large.
    # Remove it only after the durable Parquets, hashes, validation manifest, and
    # success marker exist.  If cleanup fails, the month remains unpublished.
    shutil.rmtree(work_dir)
    if final_dir.exists():
        raise ContractError(f"Final month appeared during build; refusing replace: {final_dir}")
    os.replace(partial_dir, final_dir)
    logger.emit(
        f"{spec.month}: NORMALIZED AND ATOMICALLY PUBLISHED",
        elapsed_seconds=elapsed,
        final_dir=str(final_dir),
    )
    return {"month": spec.month, "status": "built", "success": success}


def software_versions(duckdb: Any) -> Mapping[str, Any]:
    """Capture the runtime versions relevant to reproducibility."""

    return {
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "duckdb": getattr(duckdb, "__version__", "unknown"),
        "script_version": SCRIPT_VERSION,
    }


def execute(args: argparse.Namespace, output_root: Path) -> int:
    """Execute the authenticated, checkpointed three-month transformation."""

    duckdb = import_duckdb()
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_root = output_root / "_manifests"
    this_run = manifest_root / "runs" / run_id()
    this_run.mkdir(parents=True, exist_ok=False)
    logger = EventLog(this_run / "run_events.jsonl")
    started = time.monotonic()

    atomic_write_text(this_run / "command.txt", shlex.join(sys.argv) + "\n")
    atomic_write_json(this_run / "software_versions.json", software_versions(duckdb))
    atomic_write_json(this_run / "field_contract.json", list(FIELD_CONTRACT))
    atomic_write_json(
        this_run / "historical_provenance_gaps.json",
        {
            "gaps": list(HISTORICAL_PROVENANCE_GAPS),
            "policy": "declare unavailable; never reconstruct or fabricate",
        },
    )
    script_path = Path(__file__).resolve()
    atomic_write_json(
        this_run / "script_identity.json",
        {
            "path": str(script_path),
            "sha256": sha256_file(script_path),
            "size_bytes": script_path.stat().st_size,
            "version": SCRIPT_VERSION,
        },
    )

    try:
        logger.emit("AUTHENTICATED LEGACY NORMALIZATION STARTED")
        logger.emit("Safety: no API calls; native Stage 04 root is read-only")
        logger.emit("Hashing and authenticating locked source files")
        inventory = validate_static_sources(
            args, output_root, logger, verify_hashes=True
        )
        atomic_write_json(this_run / "source_inventory.json", inventory)

        results: list[Mapping[str, Any]] = []
        for month in args.months:
            result = process_month(
                args=args,
                output_root=output_root,
                spec=MONTH_SPECS[month],
                source_inventory=inventory,
                logger=logger,
                duckdb=duckdb,
            )
            results.append(result)

        month_rows = []
        for result in results:
            success = result["success"]
            month_rows.append(
                {
                    "month": result["month"],
                    "run_status": result["status"],
                    "final_ok": success["final_ok"],
                    "target_rows": success["target_rows"],
                    "timeout_rows": success["timeout_rows"],
                    "outoftime_rows": success["outoftime_rows"],
                    "core_path": str(
                        output_root
                        / f"month={result['month']}"
                        / success["outputs"]["core"]["relative_path"]
                    ),
                    "core_sha256": success["outputs"]["core"]["sha256"],
                    "evidence_path": str(
                        output_root
                        / f"month={result['month']}"
                        / success["outputs"]["evidence"]["relative_path"]
                    ),
                    "evidence_sha256": success["outputs"]["evidence"]["sha256"],
                }
            )

        elapsed = round(time.monotonic() - started, 3)
        total_targets = sum(row["target_rows"] for row in month_rows)
        total_timeout = sum(row["timeout_rows"] for row in month_rows)
        total_outoftime = sum(row["outoftime_rows"] for row in month_rows)
        summary = {
            "final_ok": True,
            "decision": (
                "LATE_LEGACY_STAGE04_NORMALIZED__PROVENANCE_DISTINCT__READY_FOR_24M_RECONCILER"
            ),
            "finished_utc": utc_now(),
            "elapsed_seconds": elapsed,
            "output_root": str(output_root),
            "months": list(args.months),
            "month_count": len(month_rows),
            "total_target_rows": total_targets,
            "total_timeout_rows": total_timeout,
            "total_outoftime_rows": total_outoftime,
            "expected_all_late_target_rows": 20_689_165,
            "expected_all_late_timeout_rows": 5_810_797,
            "expected_all_late_outoftime_rows": 14_878_368,
            "all_three_months_requested": tuple(args.months) == LATE_MONTHS,
            "provenance_class": "legacy_normalized_not_native_stage04",
            "api_refetch_performed": False,
            "historical_provenance_gaps": list(HISTORICAL_PROVENANCE_GAPS),
            "month_status": month_rows,
            "next_gate": (
                "24-month manifest reconciliation, schema union, and global duplicate-ID check"
            ),
        }
        if tuple(args.months) == LATE_MONTHS:
            assert_equal(total_targets, 20_689_165, "three-month target total")
            assert_equal(total_timeout, 5_810_797, "three-month timeout total")
            assert_equal(total_outoftime, 14_878_368, "three-month outoftime total")

        atomic_write_json(this_run / "summary.json", summary)
        write_csv(
            this_run / "month_status.csv",
            month_rows,
            (
                "month",
                "run_status",
                "final_ok",
                "target_rows",
                "timeout_rows",
                "outoftime_rows",
                "core_path",
                "core_sha256",
                "evidence_path",
                "evidence_sha256",
            ),
        )
        atomic_write_text(
            this_run / "normalized_core_paths.txt",
            "".join(row["core_path"] + "\n" for row in month_rows),
        )
        atomic_write_json(this_run / "_SUCCESS.json", summary)
        atomic_write_json(manifest_root / "latest_summary.json", summary)
        atomic_write_text(
            manifest_root / "latest_run_path.txt", str(this_run) + "\n"
        )
        logger.emit("LEGACY NORMALIZATION: TECHNICALLY COMPLETE")
        logger.emit(f"Decision: {summary['decision']}")
        logger.emit(f"Late target rows: {total_targets:,}")
        logger.emit(f"Late timeout rows: {total_timeout:,}")
        logger.emit(f"Run manifest: {this_run}")
        return 0
    except Exception as exc:
        failure = {
            "final_ok": False,
            "failed_utc": utc_now(),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "output_root": str(output_root),
            "requested_months": list(args.months),
            "api_requests_performed": False,
        }
        atomic_write_json(this_run / "failure.json", failure)
        logger.emit(f"FAILED CLOSED: {type(exc).__name__}: {exc}")
        raise


def plan(args: argparse.Namespace, output_root: Path) -> int:
    """Perform a write-free, non-hashing preflight and print the production plan."""

    logger = EventLog(None)
    logger.emit("WRITE-FREE PLAN STARTED")
    inventory = validate_static_sources(
        args, output_root, logger, verify_hashes=False
    )
    plan_payload = {
        "mode": "plan_no_writes",
        "script_version": SCRIPT_VERSION,
        "project_root": str(args.project_root.resolve()),
        "legacy_root": str(args.legacy_root.resolve()),
        "native_stage04_root": str(
            args.project_root.resolve() / NATIVE_RELATIVE_ROOT
        ),
        "output_root": str(output_root),
        "months": list(args.months),
        "memory_limit": args.memory_limit,
        "threads": args.threads,
        "row_group_size": args.row_group_size,
        "expected_runtime": "normally 30-90 minutes; potentially up to 2 hours",
        "temporary_space_guidance": "roughly 10-25 GB free",
        "source_hashing": "required automatically in --execute mode",
        "source_inventory": inventory,
        "writes_planned": [
            str(output_root / f"month={month}") for month in args.months
        ],
        "api_requests": "none",
        "native_stage04_mutation": "forbidden",
        "historical_provenance_policy": (
            "declare unavailable; never reconstruct or fabricate"
        ),
    }
    print(json.dumps(plan_payload, indent=2, sort_keys=True))
    logger.emit("WRITE-FREE PLAN COMPLETE; rerun with --execute to produce outputs")
    return 0


def write_fixture_csvs(root: Path) -> tuple[Path, Path, Path]:
    """Create a four-row fixture used only by --self-test."""

    candidate = root / "candidate.csv"
    lookup = root / "lookup.csv"
    summary = root / "summary.json"

    candidate_rows = [
        {
            "archive_month": "2025-08",
            "game_id": "AAA00001",
            "white_rating_diff": "5",
            "black_rating_diff": "-5",
            "result": "1-0",
        },
        {
            "archive_month": "2025-08",
            "game_id": "AAA00002",
            "white_rating_diff": "0",
            "black_rating_diff": "0",
            "result": "1/2-1/2",
        },
        {
            "archive_month": "2025-08",
            "game_id": "AAA00003",
            "white_rating_diff": "-4",
            "black_rating_diff": "4",
            "result": "0-1",
        },
        {
            "archive_month": "2025-08",
            "game_id": "AAA00004",
            "white_rating_diff": "6",
            "black_rating_diff": "-6",
            "result": "1-0",
        },
    ]
    candidate.parent.mkdir(parents=True, exist_ok=True)
    with candidate.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=EXPECTED_CANDIDATE_HEADER)
        writer.writeheader()
        for partial in candidate_rows:
            row = {name: "" for name in EXPECTED_CANDIDATE_HEADER}
            row.update(partial)
            writer.writerow(row)

    lookup_rows = [
        ("AAA00001", "timeout", "white", "0"),
        ("AAA00002", "timeout", "", "1"),
        ("AAA00003", "outoftime", "black", "0"),
        ("AAA00004", "outoftime", "white", "0"),
    ]
    with lookup.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=EXPECTED_LOOKUP_HEADER)
        writer.writeheader()
        for index, (game_id, status, winner, draw) in enumerate(lookup_rows):
            writer.writerow(
                {
                    "id": game_id,
                    "status": status,
                    "winner": winner,
                    "draw": draw,
                    "speed": "blitz",
                    "perf": "blitz",
                    "rated": "true",
                    "variant": "standard",
                    "createdAt": str(1_700_000_000_000 + index * 10_000),
                    "lastMoveAt": str(1_700_000_001_000 + index * 10_000),
                    "white_name": f"White{index}",
                    "black_name": f"Black{index}",
                    "white_rating": str(1500 + index),
                    "black_rating": str(1510 + index),
                }
            )
    atomic_write_json(summary, {"fixture": True})
    return candidate, lookup, summary


def self_test(args: argparse.Namespace) -> int:
    """Run the production SQL and validators against an isolated tiny fixture."""

    duckdb = import_duckdb()
    with tempfile.TemporaryDirectory(prefix="legacy_stage04_normalizer_selftest_") as raw:
        root = Path(raw)
        candidate, lookup, summary = write_fixture_csvs(root)
        spec = MonthSpec(
            month="2025-08",
            candidate_relative_path=str(candidate),
            candidate_sha256=sha256_file(candidate),
            lookup_relative_path=str(lookup),
            lookup_sha256=sha256_file(lookup),
            summary_relative_path=str(summary),
            summary_sha256=sha256_file(summary),
            target_rows=4,
            timeout_rows=2,
            outoftime_rows=2,
            white_winner_rows=2,
            black_winner_rows=1,
            draw_rows=1,
        )
        # Reproduce the production temporary-directory name exactly.  This is
        # a regression test for accidental DuckDB Hive-column inference.
        partial = root / ".month=2025-08.partial.99999"
        work = partial / "_work"
        work.mkdir(parents=True)
        core = partial / "responses" / "legacy-normalized.parquet"
        evidence = partial / "evidence" / "legacy-outcome-evidence.parquet"
        core.parent.mkdir(parents=True)
        evidence.parent.mkdir(parents=True)
        statements = build_month_sql(
            spec=spec,
            candidate_path=candidate,
            lookup_path=lookup,
            core_output=core,
            evidence_output=evidence,
            row_group_size=10_000,
        )
        connection = duckdb.connect(str(work / "selftest.duckdb"))
        try:
            configure_duckdb(
                connection,
                temp_directory=work / "tmp",
                memory_limit="1GB",
                threads=1,
            )
            connection.execute(statements["load_candidate"])
            connection.execute(statements["load_lookup"])
            validate_loaded_tables(connection, spec)
            connection.execute(statements["create_normalized"])
            connection.execute(statements["copy_core"])
            connection.execute(statements["copy_evidence"])
            validation = validate_outputs(connection, spec, core, evidence)
        finally:
            connection.close()
        assert validation["all_gates_pass"]
    print("SELF-TEST PASS: SQL transform, schemas, semantics, and validators")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point with a concise fail-closed terminal diagnostic."""

    args = parse_args(argv)
    try:
        validate_cli(args)
        if args.self_test:
            return self_test(args)
        output_root = resolve_output_root(args)
        if args.execute:
            return execute(args, output_root)
        return plan(args, output_root)
    except ContractError as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 2
    except KeyboardInterrupt:
        print("INTERRUPTED: temporary work remains recoverable and will be quarantined on resume.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
