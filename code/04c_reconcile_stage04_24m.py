#!/usr/bin/env python3
"""Reconcile and freeze the complete 24-month Stage 04 API-status layer.

Purpose
=======

The locked paper window contains exactly the 24 complete UTC months from
2023-11 through 2025-10.  Its Stage 04 API classifications come from three
audited production lineages:

* 2023-11--2024-09: curated historical legacy lookup Parquets;
* 2024-10--2025-07: native canonical Stage 04 unit Parquets; and
* 2025-08--2025-10: legacy lookups converted by the authenticated 04b adapter.

This program performs the one finite integration gate required before the
API-timeout universe can be frozen.  It does not call the Lichess API and does
not modify any source block.  Instead, it writes an additive, common-schema
status index beneath:

    derived/replication/api_timeout_enrichment_24m_reconciled/

For every month it publishes two deterministic Parquets:

    month=YYYY-MM/api_status_index.parquet   # timeout + outoftime targets
    month=YYYY-MM/timeout_ids.parquet        # API timeout only

Both files use the same five-column integration schema:

    month             VARCHAR
    game_id           VARCHAR
    api_status        VARCHAR
    source_block      VARCHAR
    provenance_class  VARCHAR

The narrow schema is intentional.  It standardizes only fields that are
analytically identical and fully available in all three lineages.  Optional
API response fields, PGN outcomes, and operational telemetry remain in their
authenticated source roots and are joined later by the opportunity builder.
No unavailable field is fabricated merely to make the three sources look
native-identical.

Gates
=====

The program fails closed unless all of the following are true:

1. Exactly one source is selected for every month 2023-11--2025-10.
2. October 2023 and November 2025 are absent.
3. Source scripts and bridge month-success files match locked SHA-256 values.
4. Earlier inventory paths match the exact curated selections recorded below.
5. Late normalized files match the production hashes from 04b.
6. Every month has the expected target, timeout, and outoftime counts.
7. Every source and output month has one row per nonmissing game ID.
8. Every status is exactly ``timeout`` or ``outoftime``.
9. The 24-month totals are exactly 170,648,691 targets, 47,587,020 timeout,
   and 123,061,671 outoftime.
10. An exact all-target group-by finds zero duplicate game IDs across the full
    170,648,691-row universe.
11. An explicit unresolved-ID ledger is present and empty.

Design and safety
=================

* Default invocation is a write-free plan; ``--execute`` is required.
* Source files are read and SHA-256 fingerprinted, never changed.
* Each month is written under an isolated temporary directory, validated, and
  atomically renamed into place.
* Completed months are authenticated and reused on restart.
* Interrupted temporary directories are moved—not deleted—to ``_stale``.
* DuckDB is given an explicit memory limit and spill directory.
* Hive partition inference is disabled whenever Parquet is read.  This avoids
  virtual columns derived from temporary or ``month=`` directory names.
* A global success marker is written only after the exact duplicate-ID gate.

Fresh-Terminal example
======================

    ROOT="/Volumes/XT_Pro/lichess_kindness"
    source "$ROOT/venv/bin/activate"
    export PYTHONDONTWRITEBYTECODE=1
    export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
    "$ROOT/venv/bin/python" -B \
      "$ROOT/replication_package/code/04c_reconcile_stage04_24m.py" \
      --project-root "$ROOT" \
      --execute

Expected runtime is usually 30--120 minutes and can approach three hours on a
slow external filesystem.  The exact 170.6-million-ID duplicate group-by is
the expensive final step.  Allow roughly 20--60 GB of temporary free space.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCRIPT_VERSION = "1.0.0"
LOCKED_SAMPLE_START = "2023-11-01"
LOCKED_SAMPLE_END = "2025-10-31"

LOCKED_MONTHS = (
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
    "2025-08",
    "2025-09",
    "2025-10",
)

EARLIER_MONTHS = LOCKED_MONTHS[:11]
BRIDGE_MONTHS = LOCKED_MONTHS[11:21]
LATE_MONTHS = LOCKED_MONTHS[21:]

EXPECTED_TOTAL_TARGETS = 170_648_691
EXPECTED_TOTAL_TIMEOUT = 47_587_020
EXPECTED_TOTAL_OUTOFTIME = 123_061_671

EXPECTED_BLOCK_TOTALS: Mapping[str, Mapping[str, int]] = {
    "earlier": {
        "target_rows": 78_512_947,
        "timeout_rows": 21_600_308,
        "outoftime_rows": 56_912_639,
    },
    "bridge": {
        "target_rows": 71_446_579,
        "timeout_rows": 20_175_915,
        "outoftime_rows": 51_270_664,
    },
    "late": {
        "target_rows": 20_689_165,
        "timeout_rows": 5_810_797,
        "outoftime_rows": 14_878_368,
    },
}

CANONICAL_STAGE04_RELATIVE_PATH = Path(
    "replication_package/code/04_enrich_timeout_candidates.py"
)
CANONICAL_STAGE04_SHA256 = (
    "2c1c23d4d867ce3a5a725cf4761e23f9f512c0063a3b7fc1f3d1f9ffe6d840fa"
)
LATE_ADAPTER_RELATIVE_PATH = Path(
    "replication_package/code/04b_normalize_legacy_stage04_late.py"
)
LATE_ADAPTER_SHA256 = (
    "c450c28d609f4a9ca7b6f3e65132dbc3ca3f0695fbddc18f48555ba9842321d1"
)

EARLIER_INVENTORY_RELATIVE_PATH = Path(
    "output/api_enrichment_canonical_inventory_20260601_163807/"
    "canonical_api_lookup_month_inventory.tsv"
)
BRIDGE_RELATIVE_ROOT = Path("derived/replication/api_timeout_enrichment")
LATE_RELATIVE_ROOT = Path(
    "derived/replication/api_timeout_enrichment_legacy_normalized"
)
DEFAULT_OUTPUT_RELATIVE_ROOT = Path(
    "derived/replication/api_timeout_enrichment_24m_reconciled"
)

BRIDGE_INTEGRITY_RELATIVE_PATH = Path(
    "derived/replication/api_timeout_enrichment/_manifests/"
    "stage04_bridge_integrity_315a3afc1ed7f384.json"
)

COMMON_COLUMNS = (
    "month",
    "game_id",
    "api_status",
    "source_block",
    "provenance_class",
)


@dataclass(frozen=True)
class MonthSpec:
    """Immutable reconciliation contract for one month."""

    month: str
    block: str
    source_block: str
    provenance_class: str
    target_rows: int
    timeout_rows: int | None
    outoftime_rows: int | None
    source_kind: str
    earlier_lookup_relative_path: str | None = None
    bridge_units: int | None = None
    bridge_success_sha256: str | None = None
    late_core_sha256: str | None = None


def earlier_spec(
    month: str,
    target_rows: int,
    timeout_rows: int,
    relative_path: str,
) -> MonthSpec:
    """Construct an earlier legacy month with derived outoftime count."""

    return MonthSpec(
        month=month,
        block="earlier",
        source_block="earlier_legacy",
        provenance_class="legacy_curated_lookup",
        target_rows=target_rows,
        timeout_rows=timeout_rows,
        outoftime_rows=target_rows - timeout_rows,
        source_kind="earlier_single_parquet",
        earlier_lookup_relative_path=relative_path,
    )


def bridge_spec(
    month: str,
    target_rows: int,
    units: int,
    success_sha256: str,
) -> MonthSpec:
    """Construct a bridge month whose status counts come from its locked success file."""

    return MonthSpec(
        month=month,
        block="bridge",
        source_block="bridge_native_stage04",
        provenance_class="native_stage04",
        target_rows=target_rows,
        timeout_rows=None,
        outoftime_rows=None,
        source_kind="bridge_unit_parquets",
        bridge_units=units,
        bridge_success_sha256=success_sha256,
    )


def late_spec(
    month: str,
    target_rows: int,
    timeout_rows: int,
    outoftime_rows: int,
    core_sha256: str,
) -> MonthSpec:
    """Construct a late normalized month with its frozen 04b output hash."""

    return MonthSpec(
        month=month,
        block="late",
        source_block="late_legacy_normalized",
        provenance_class="legacy_normalized_not_native_stage04",
        target_rows=target_rows,
        timeout_rows=timeout_rows,
        outoftime_rows=outoftime_rows,
        source_kind="late_normalized_parquet",
        late_core_sha256=core_sha256,
    )


MONTH_SPECS: Mapping[str, MonthSpec] = {
    "2023-11": earlier_spec(
        "2023-11",
        7_183_319,
        2_015_809,
        "output/api_enrich_main_2023-11_to_2024-01_anon300_sleep1_20260516_110007/"
        "2023-11_lookup_targeted5s_anon300_sleep1_20260516_110007/"
        "game_status_lookup.parquet",
    ),
    "2023-12": earlier_spec(
        "2023-12",
        7_448_160,
        2_101_110,
        "output/api_enrich_main_2023-11_to_2024-01_anon300_sleep1_20260516_110007/"
        "2023-12_lookup_targeted5s_anon300_sleep1_20260519_134140/"
        "game_status_lookup.parquet",
    ),
    "2024-01": earlier_spec(
        "2024-01",
        7_450_435,
        2_049_292,
        "output/api_enrich_main_2023-11_to_2024-01_anon300_sleep1_20260516_110007/"
        "2024-01_lookup_targeted5s_anon300_sleep1_20260522_193316/"
        "game_status_lookup.parquet",
    ),
    "2024-02": earlier_spec(
        "2024-02",
        7_012_824,
        1_931_143,
        "output/api_enrichment_imported_from_lexar_20260601_162203/home_laptop/"
        "lichess_api_kit_2024-02_20260524_212755/output/"
        "2024-02_lookup_targeted5s_anon300_sleep1_20260525_093128/"
        "game_status_lookup.parquet",
    ),
    "2024-03": earlier_spec(
        "2024-03",
        7_333_233,
        2_021_798,
        "output/api_enrichment_imported_from_lexar_20260601_162203/home_laptop/"
        "lichess_api_kit_2024-03_to_2024-05_20260514_151655/output/"
        "2024-03_lookup_targeted5s_anon300_sleep1_20260522_025101/"
        "game_status_lookup.parquet",
    ),
    "2024-04": earlier_spec(
        "2024-04",
        7_015_289,
        1_917_136,
        "output/api_enrichment_imported_from_lexar_20260601_162203/home_laptop/"
        "lichess_api_kit_2024-03_to_2024-05_20260514_151655/output/"
        "2024-04_lookup_targeted5s_anon300_sleep1_20260517_211236/"
        "game_status_lookup.parquet",
    ),
    "2024-05": earlier_spec(
        "2024-05",
        7_304_894,
        2_011_399,
        "output/api_enrichment_imported_from_lexar_20260601_162203/home_laptop/"
        "lichess_api_kit_2024-03_to_2024-05_20260514_151655/output/"
        "2024-05_lookup_targeted5s_anon300_sleep1_20260514_154511/"
        "game_status_lookup.parquet",
    ),
    "2024-06": earlier_spec(
        "2024-06",
        6_913_168,
        1_903_139,
        "output/api_enrich_main_2024-06_anon300_sleep1_20260526_163105/"
        "2024-06_lookup_targeted5s_anon300_sleep1_20260526_163105/"
        "game_status_lookup.parquet",
    ),
    "2024-07": earlier_spec(
        "2024-07",
        6_958_044,
        1_893_461,
        "output/api_enrichment_imported_from_lexar_20260601_162203/work_desktop/"
        "lichess_api_kit_2024-06_to_2024-09_20260514_143228/output/"
        "2024-07_lookup_targeted5s_anon300_sleep1_20260527_132703/"
        "game_status_lookup.parquet",
    ),
    "2024-08": earlier_spec(
        "2024-08",
        7_096_917,
        1_923_975,
        "output/api_enrichment_imported_from_lexar_20260601_162203/work_desktop/"
        "lichess_api_kit_2024-06_to_2024-09_20260514_143228/output/"
        "2024-08_lookup_targeted5s_anon300_sleep1_20260521_133304/"
        "game_status_lookup.parquet",
    ),
    "2024-09": earlier_spec(
        "2024-09",
        6_796_664,
        1_832_046,
        "output/api_enrichment_imported_from_lexar_20260601_162203/work_desktop/"
        "lichess_api_kit_2024-06_to_2024-09_20260514_143228/output/"
        "2024-09_lookup_targeted5s_anon300_sleep1_20260514_151116/"
        "game_status_lookup.parquet",
    ),
    "2024-10": bridge_spec(
        "2024-10",
        7_280_463,
        243,
        "0fcf937b29542e06152e9ce47508cf4d06516b8540e60e6d5cc77b1b5bad944e",
    ),
    "2024-11": bridge_spec(
        "2024-11",
        6_920_848,
        231,
        "9d536e76240ece4239d987b1eb05b7f1f0fda739f46f27b063ddc05cd157a341",
    ),
    "2024-12": bridge_spec(
        "2024-12",
        7_327_917,
        245,
        "984f2148c0f94385c0ad01bb22652f9cd270b1052cd0976c2b84d4b3b4ca96fc",
    ),
    "2025-01": bridge_spec(
        "2025-01",
        7_499_540,
        250,
        "44ad5d9ed861be0dbe7675c0825da0358eb22bc293c4b93cb01c805eda7e18f3",
    ),
    "2025-02": bridge_spec(
        "2025-02",
        6_780_461,
        227,
        "6ed17f79a60d171c5fb50d36e18224911f8b0c7fec4f63233ec152afef786c7a",
    ),
    "2025-03": bridge_spec(
        "2025-03",
        7_371_390,
        246,
        "10a5e7b6b11208a75289290f08676e64a426d6ed38ea856affbc2f83c380a338",
    ),
    "2025-04": bridge_spec(
        "2025-04",
        7_007_508,
        234,
        "69e86e78c299d2261230d871d8f2d6c03687572276910fd4be110b351a00a95d",
    ),
    "2025-05": bridge_spec(
        "2025-05",
        7_209_483,
        241,
        "bfc9491bbe3ae2aa2d9cd391da636ef7ce213124efffd729481ba112a384b200",
    ),
    "2025-06": bridge_spec(
        "2025-06",
        6_937_046,
        232,
        "58841d7b99943d97bbcde708ac4b8c9101e9123526fd0566c006122c6103bf07",
    ),
    "2025-07": bridge_spec(
        "2025-07",
        7_111_923,
        238,
        "77c3a366666d63b7283b2414ad0237cdfabc5367bb68cc41d374515ebf7877ee",
    ),
    "2025-08": late_spec(
        "2025-08",
        6_961_261,
        1_930_170,
        5_031_091,
        "99e0f10463cacd0d4d7b9c035b2d1b7d4cbe7dcd1a9d9a00403f33abf2df8afe",
    ),
    "2025-09": late_spec(
        "2025-09",
        6_698_493,
        1_881_564,
        4_816_929,
        "f6561095d3b874e9f81b1ce414892e6034f1a1cfad7a9eb48422c8f60370037d",
    ),
    "2025-10": late_spec(
        "2025-10",
        7_029_411,
        1_999_063,
        5_030_348,
        "81c588140c550a2b2e89c613c9647ea3f9c8230c54bc34666bf100f36737fd23",
    ),
}


class ContractError(RuntimeError):
    """Raised whenever a fail-closed contract is not satisfied."""


@dataclass(frozen=True)
class ResolvedSource:
    """A fully resolved and, in execute mode, fingerprinted month source."""

    spec: MonthSpec
    data_paths: tuple[Path, ...]
    auxiliary_paths: tuple[Path, ...]
    relation_sql: str
    source_records: tuple[Mapping[str, Any], ...]
    source_set_sha256: str
    source_columns: tuple[str, ...]
    id_column: str
    status_column: str
    source_month_column: str | None


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_run_id() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"_{os.getpid()}"


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{os.getpid()}")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(
        path,
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    )


def write_csv(path: Path, rows: Iterable[Mapping[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{os.getpid()}")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def sql_string(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def sql_path_list(paths: Sequence[Path]) -> str:
    if not paths:
        raise ContractError("Cannot build a Parquet relation from an empty path list")
    return "[" + ", ".join(sql_string(path) for path in paths) + "]"


def import_duckdb() -> Any:
    try:
        import duckdb  # type: ignore
    except ImportError as exc:
        raise ContractError(
            "DuckDB is not importable. Activate the project venv and verify with "
            "python -c 'import duckdb'."
        ) from exc
    return duckdb


def assert_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise ContractError(f"{label}: expected {expected!r}, got {actual!r}")


class EventLog:
    def __init__(self, path: Path | None) -> None:
        self.path = path

    def emit(self, message: str, **details: Any) -> None:
        stamp = utc_now()
        print(f"[{stamp}] {message}", flush=True)
        if self.path is not None:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps({"utc": stamp, "message": message, **details}, sort_keys=True)
                    + "\n"
                )
                handle.flush()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Reconcile and freeze the exact 2023-11 through 2025-10 Stage 04 "
            "API-status layer without API requests."
        )
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path("/Volumes/XT_Pro/lichess_kindness"),
    )
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--memory-limit", default="8GB")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--row-group-size", type=int, default=250_000)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Write outputs. Without this flag the program is write-free.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run isolated schema, Hive-path, and duplicate-gate tests.",
    )
    return parser.parse_args(argv)


def validate_cli(args: argparse.Namespace) -> None:
    if args.threads < 1:
        raise ContractError("--threads must be at least 1")
    if args.row_group_size < 10_000:
        raise ContractError("--row-group-size must be at least 10,000")
    if set(MONTH_SPECS) != set(LOCKED_MONTHS):
        raise ContractError("Internal month contract is not exactly the locked 24 months")


def resolve_output_root(args: argparse.Namespace) -> Path:
    project_root = args.project_root.resolve()
    output_root = (
        args.output_root.resolve()
        if args.output_root is not None
        else (project_root / DEFAULT_OUTPUT_RELATIVE_ROOT).resolve()
    )
    if output_root == project_root:
        raise ContractError("The project root itself cannot be used as the output root")
    try:
        output_root.relative_to(project_root)
    except ValueError as exc:
        raise ContractError(
            f"Output root must remain inside the project root: {project_root}"
        ) from exc

    # Reject overlap in either direction.  In particular, an output directory
    # may not be placed inside a source tree, nor may a broad output directory
    # be chosen that already contains a protected source tree.
    protected_source_roots = (
        (project_root / "output").resolve(),
        (project_root / BRIDGE_RELATIVE_ROOT).resolve(),
        (project_root / LATE_RELATIVE_ROOT).resolve(),
    )
    for source_root in protected_source_roots:
        if (
            output_root == source_root
            or source_root in output_root.parents
            or output_root in source_root.parents
        ):
            raise ContractError(f"Output root overlaps a protected source root: {source_root}")
    return output_root


def configure_duckdb(
    connection: Any,
    *,
    temp_directory: Path,
    memory_limit: str,
    threads: int,
) -> None:
    temp_directory.mkdir(parents=True, exist_ok=True)
    connection.execute(f"SET memory_limit = {sql_string(memory_limit)}")
    connection.execute(f"SET threads = {int(threads)}")
    connection.execute(f"SET temp_directory = {sql_string(temp_directory)}")
    connection.execute("SET preserve_insertion_order = false")
    try:
        connection.execute("PRAGMA enable_progress_bar")
    except Exception:
        pass


def query_one_dict(connection: Any, query: str) -> Mapping[str, Any]:
    cursor = connection.execute(query)
    columns = [description[0] for description in cursor.description]
    row = cursor.fetchone()
    if row is None or cursor.fetchone() is not None:
        raise ContractError("Validation query did not return exactly one row")
    return dict(zip(columns, row))


def relation_columns(connection: Any, relation_sql: str) -> tuple[str, ...]:
    cursor = connection.execute(f"DESCRIBE SELECT * FROM {relation_sql}")
    rows = cursor.fetchall()
    return tuple(row[0] for row in rows)


def parquet_schema(connection: Any, path: Path) -> Sequence[Mapping[str, Any]]:
    cursor = connection.execute(
        f"DESCRIBE SELECT * FROM read_parquet("
        f"{sql_string(path)}, hive_partitioning=false)"
    )
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def load_earlier_inventory(project_root: Path) -> tuple[Path, Mapping[str, Mapping[str, str]]]:
    """Load only the curated selection fields; count anchors are locked in code.

    Several historical preview renderings concatenated adjacent numeric fields.
    The authoritative selection fields occur before those fields, so this
    reconciler uses the TSV only to authenticate ``month``, ``ok``, and the
    selected Parquet path.  Counts are independently scanned and compared with
    the immutable MonthSpec anchors above.
    """

    inventory_path = project_root / EARLIER_INVENTORY_RELATIVE_PATH
    if not inventory_path.is_file():
        raise ContractError(f"Earlier curated inventory is missing: {inventory_path}")
    rows: dict[str, Mapping[str, str]] = {}
    with inventory_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        required = {"month", "ok", "lookup_parquet"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ContractError(
                f"Earlier inventory lacks required columns {sorted(required)}"
            )
        for row in reader:
            month = (row.get("month") or "").strip()
            if month in EARLIER_MONTHS:
                if month in rows:
                    raise ContractError(f"Earlier inventory repeats month {month}")
                rows[month] = row
    assert_equal(set(rows), set(EARLIER_MONTHS), "earlier inventory month set")
    return inventory_path, rows


def validate_program_identities(project_root: Path, verify_hashes: bool) -> Mapping[str, Any]:
    records: dict[str, Any] = {}
    for label, relative, expected in (
        ("canonical_stage04", CANONICAL_STAGE04_RELATIVE_PATH, CANONICAL_STAGE04_SHA256),
        ("late_adapter_04b", LATE_ADAPTER_RELATIVE_PATH, LATE_ADAPTER_SHA256),
    ):
        path = project_root / relative
        if not path.is_file():
            raise ContractError(f"Required program is missing: {path}")
        actual = sha256_file(path) if verify_hashes else None
        if verify_hashes and actual != expected:
            raise ContractError(
                f"{label} SHA-256 mismatch: expected {expected}, got {actual}"
            )
        records[label] = {
            "path": str(path),
            "expected_sha256": expected,
            "sha256": actual,
            "sha256_match": actual == expected if verify_hashes else None,
            "size_bytes": path.stat().st_size,
        }
    return records


def relative_fingerprint_path(path: Path, project_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_root.resolve()))
    except ValueError:
        return str(path.resolve())


def fingerprint_paths(
    paths: Sequence[Path], project_root: Path, verify_hashes: bool
) -> tuple[tuple[Mapping[str, Any], ...], str]:
    records: list[Mapping[str, Any]] = []
    digest = hashlib.sha256()
    for path in paths:
        if not path.is_file():
            raise ContractError(f"Required source file is missing: {path}")
        identity = relative_fingerprint_path(path, project_root)
        actual = sha256_file(path) if verify_hashes else None
        record = {
            "path": str(path),
            "identity_path": identity,
            "size_bytes": path.stat().st_size,
            "sha256": actual,
        }
        records.append(record)
        digest.update(identity.encode("utf-8"))
        digest.update(b"\t")
        digest.update((actual or "HASH_DEFERRED").encode("ascii"))
        digest.update(b"\n")
    return tuple(records), digest.hexdigest()


def validate_contiguous_unit_files(paths: Sequence[Path], expected_units: int, month: str) -> None:
    pattern = re.compile(r"^unit-(\d{5})\.parquet$")
    indices: list[int] = []
    for path in paths:
        match = pattern.fullmatch(path.name)
        if not match:
            raise ContractError(f"{month}: unexpected response filename {path.name}")
        indices.append(int(match.group(1)))
    assert_equal(len(indices), expected_units, f"{month} response unit count")
    assert_equal(indices, list(range(expected_units)), f"{month} contiguous unit indices")


def resolve_source(
    spec: MonthSpec,
    *,
    project_root: Path,
    earlier_inventory_path: Path,
    earlier_inventory_rows: Mapping[str, Mapping[str, str]],
    duckdb: Any,
    verify_hashes: bool,
) -> ResolvedSource:
    auxiliary_paths: list[Path] = []
    if spec.source_kind == "earlier_single_parquet":
        assert spec.earlier_lookup_relative_path is not None
        data_paths = [project_root / spec.earlier_lookup_relative_path]
        row = earlier_inventory_rows[spec.month]
        if (row.get("ok") or "").strip().lower() not in {"true", "1", "yes"}:
            raise ContractError(f"{spec.month}: curated inventory does not mark month OK")
        inventory_selected = Path((row.get("lookup_parquet") or "").strip()).resolve()
        assert_equal(
            inventory_selected,
            data_paths[0].resolve(),
            f"{spec.month} exact curated lookup selection",
        )
        auxiliary_paths.append(earlier_inventory_path)
    elif spec.source_kind == "bridge_unit_parquets":
        month_dir = project_root / BRIDGE_RELATIVE_ROOT / f"month={spec.month}"
        success_path = month_dir / "_SUCCESS.json"
        if not success_path.is_file():
            raise ContractError(f"{spec.month}: bridge _SUCCESS.json is missing")
        assert spec.bridge_success_sha256 is not None
        actual_success_hash = sha256_file(success_path) if verify_hashes else None
        if verify_hashes and actual_success_hash != spec.bridge_success_sha256:
            raise ContractError(
                f"{spec.month}: bridge success SHA mismatch; expected "
                f"{spec.bridge_success_sha256}, got {actual_success_hash}"
            )
        success = read_json(success_path)
        if not success.get("final_ok"):
            raise ContractError(f"{spec.month}: bridge success record is not final_ok")
        assert_equal(success.get("month"), spec.month, f"{spec.month} bridge success month")
        assert_equal(success.get("requested_ids"), spec.target_rows, f"{spec.month} requested IDs")
        assert_equal(
            success.get("returned_unique_ids"),
            spec.target_rows,
            f"{spec.month} returned unique IDs",
        )
        assert_equal(success.get("missing_ids"), 0, f"{spec.month} missing IDs")
        assert_equal(success.get("unit_count"), spec.bridge_units, f"{spec.month} unit count")
        status_counts = success.get("status_counts", {})
        timeout_rows = int(status_counts.get("timeout", -1))
        outoftime_rows = int(status_counts.get("outoftime", -1))
        assert_equal(
            timeout_rows + outoftime_rows,
            spec.target_rows,
            f"{spec.month} bridge status exhaustion",
        )
        spec = replace(
            spec, timeout_rows=timeout_rows, outoftime_rows=outoftime_rows
        )
        data_paths = sorted((month_dir / "responses").glob("unit-*.parquet"))
        assert spec.bridge_units is not None
        validate_contiguous_unit_files(data_paths, spec.bridge_units, spec.month)
        auxiliary_paths.append(success_path)
    elif spec.source_kind == "late_normalized_parquet":
        month_dir = project_root / LATE_RELATIVE_ROOT / f"month={spec.month}"
        core_path = month_dir / "responses" / "legacy-normalized.parquet"
        success_path = month_dir / "_SUCCESS.json"
        if not core_path.is_file() or not success_path.is_file():
            raise ContractError(f"{spec.month}: late normalized source is incomplete")
        success = read_json(success_path)
        if not success.get("final_ok"):
            raise ContractError(f"{spec.month}: late source is not final_ok")
        assert_equal(success.get("target_rows"), spec.target_rows, f"{spec.month} late targets")
        assert_equal(success.get("timeout_rows"), spec.timeout_rows, f"{spec.month} late timeout")
        assert_equal(
            success.get("outoftime_rows"), spec.outoftime_rows, f"{spec.month} late outoftime"
        )
        data_paths = [core_path]
        auxiliary_paths.append(success_path)
    else:
        raise ContractError(f"Unsupported source kind: {spec.source_kind}")

    all_fingerprint_paths = sorted([*data_paths, *auxiliary_paths], key=lambda p: str(p))
    records, source_set_sha = fingerprint_paths(
        all_fingerprint_paths, project_root, verify_hashes
    )
    if spec.source_kind == "late_normalized_parquet" and verify_hashes:
        assert spec.late_core_sha256 is not None
        core_record = next(record for record in records if record["path"] == str(data_paths[0]))
        assert_equal(
            core_record["sha256"],
            spec.late_core_sha256,
            f"{spec.month} frozen late core SHA-256",
        )

    relation = (
        "read_parquet("
        f"{sql_path_list(data_paths)}, union_by_name=true, hive_partitioning=false)"
    )
    connection = duckdb.connect(":memory:")
    try:
        columns = relation_columns(connection, relation)
    finally:
        connection.close()
    id_column = "game_id" if "game_id" in columns else "id" if "id" in columns else ""
    status_column = (
        "api_status" if "api_status" in columns else "status" if "status" in columns else ""
    )
    if not id_column or not status_column:
        raise ContractError(
            f"{spec.month}: source schema lacks an ID/status mapping; columns={columns}"
        )
    source_month_column = "month" if "month" in columns else None
    return ResolvedSource(
        spec=spec,
        data_paths=tuple(data_paths),
        auxiliary_paths=tuple(auxiliary_paths),
        relation_sql=relation,
        source_records=records,
        source_set_sha256=source_set_sha,
        source_columns=columns,
        id_column=id_column,
        status_column=status_column,
        source_month_column=source_month_column,
    )


def existing_month_is_reusable(
    final_dir: Path,
    resolved: ResolvedSource,
    logger: EventLog,
) -> Mapping[str, Any] | None:
    if not final_dir.exists():
        return None
    success_path = final_dir / "_SUCCESS.json"
    if not final_dir.is_dir() or not success_path.is_file():
        raise ContractError(f"Existing final month is incomplete; refusing overwrite: {final_dir}")
    success = read_json(success_path)
    if not success.get("final_ok") or success.get("month") != resolved.spec.month:
        raise ContractError(f"Existing final month success marker is invalid: {final_dir}")
    assert_equal(
        success.get("source_set_sha256"),
        resolved.source_set_sha256,
        f"{resolved.spec.month} reusable source identity",
    )
    for label, filename in (
        ("status_index", "api_status_index.parquet"),
        ("timeout_ids", "timeout_ids.parquet"),
    ):
        path = final_dir / filename
        if not path.is_file():
            raise ContractError(f"Reusable month output is missing: {path}")
        expected = success.get("outputs", {}).get(label, {}).get("sha256")
        if not expected:
            raise ContractError(f"Reusable marker lacks {label} hash")
        assert_equal(sha256_file(path), expected, f"{resolved.spec.month} reusable {label} hash")
    logger.emit(f"{resolved.spec.month}: authenticated existing month reused")
    return success


def quarantine_stale(output_root: Path, month: str, logger: EventLog) -> None:
    stale = sorted(output_root.glob(f".month={month}.partial.*"))
    if not stale:
        return
    destination_root = output_root / "_stale" / make_run_id()
    destination_root.mkdir(parents=True, exist_ok=False)
    moved = []
    for source in stale:
        destination = destination_root / source.name
        os.replace(source, destination)
        moved.append({"source": str(source), "destination": str(destination)})
    atomic_write_json(
        destination_root / "quarantine_receipt.json",
        {
            "created_utc": utc_now(),
            "month": month,
            "reason": "interrupted 04c month build",
            "moved": moved,
            "deleted": [],
        },
    )
    logger.emit(f"{month}: quarantined {len(stale)} interrupted month build(s)")


def build_month(
    *,
    resolved: ResolvedSource,
    output_root: Path,
    args: argparse.Namespace,
    duckdb: Any,
    logger: EventLog,
) -> Mapping[str, Any]:
    spec = resolved.spec
    assert spec.timeout_rows is not None and spec.outoftime_rows is not None
    final_dir = output_root / f"month={spec.month}"
    reused = existing_month_is_reusable(final_dir, resolved, logger)
    if reused is not None:
        return {"status": "reused", "success": reused}
    quarantine_stale(output_root, spec.month, logger)

    partial = output_root / f".month={spec.month}.partial.{os.getpid()}"
    partial.mkdir(parents=True, exist_ok=False)
    work = partial / "_work"
    work.mkdir()
    status_output = partial / "api_status_index.parquet"
    timeout_output = partial / "timeout_ids.parquet"
    started = time.monotonic()

    source_month_expression = (
        f"CAST({resolved.source_month_column} AS VARCHAR)"
        if resolved.source_month_column is not None
        else "CAST(NULL AS VARCHAR)"
    )
    load_sql = f"""
        CREATE TABLE source_data AS
        SELECT
            trim(CAST({resolved.id_column} AS VARCHAR)) AS game_id,
            lower(trim(CAST({resolved.status_column} AS VARCHAR))) AS api_status,
            {source_month_expression} AS source_month
        FROM {resolved.relation_sql}
    """

    connection = duckdb.connect(str(work / "reconciler.duckdb"))
    try:
        configure_duckdb(
            connection,
            temp_directory=work / "duckdb_tmp",
            memory_limit=args.memory_limit,
            threads=args.threads,
        )
        logger.emit(f"{spec.month}: loading {len(resolved.data_paths)} authenticated source file(s)")
        connection.execute(load_sql)
        validation = query_one_dict(
            connection,
            f"""
            SELECT
                count(*) AS rows,
                count(DISTINCT game_id) AS unique_ids,
                count(*) FILTER (WHERE game_id IS NULL OR game_id = '') AS missing_ids,
                count(*) FILTER (WHERE api_status = 'timeout') AS timeout_rows,
                count(*) FILTER (WHERE api_status = 'outoftime') AS outoftime_rows,
                count(*) FILTER (
                    WHERE api_status NOT IN ('timeout','outoftime') OR api_status IS NULL
                ) AS invalid_status_rows,
                count(*) FILTER (
                    WHERE source_month IS NOT NULL
                      AND source_month IS DISTINCT FROM {sql_string(spec.month)}
                ) AS wrong_source_month_rows
            FROM source_data
            """,
        )
        expected = {
            "rows": spec.target_rows,
            "unique_ids": spec.target_rows,
            "missing_ids": 0,
            "timeout_rows": spec.timeout_rows,
            "outoftime_rows": spec.outoftime_rows,
            "invalid_status_rows": 0,
            "wrong_source_month_rows": 0,
        }
        for key, value in expected.items():
            assert_equal(validation[key], value, f"{spec.month} source {key}")

        common_select = f"""
            CAST({sql_string(spec.month)} AS VARCHAR) AS month,
            CAST(game_id AS VARCHAR) AS game_id,
            CAST(api_status AS VARCHAR) AS api_status,
            CAST({sql_string(spec.source_block)} AS VARCHAR) AS source_block,
            CAST({sql_string(spec.provenance_class)} AS VARCHAR) AS provenance_class
        """
        logger.emit(f"{spec.month}: writing common status index and timeout partition")
        connection.execute(
            f"""
            COPY (
                SELECT {common_select}
                FROM source_data
                ORDER BY game_id
            ) TO {sql_string(status_output)}
            (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE {args.row_group_size})
            """
        )
        connection.execute(
            f"""
            COPY (
                SELECT {common_select}
                FROM source_data
                WHERE api_status = 'timeout'
                ORDER BY game_id
            ) TO {sql_string(timeout_output)}
            (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE {args.row_group_size})
            """
        )

        output_validation = query_one_dict(
            connection,
            f"""
            SELECT
                (SELECT count(*) FROM read_parquet(
                    {sql_string(status_output)}, hive_partitioning=false)) AS status_rows,
                (SELECT count(DISTINCT game_id) FROM read_parquet(
                    {sql_string(status_output)}, hive_partitioning=false)) AS status_unique_ids,
                (SELECT count(*) FROM read_parquet(
                    {sql_string(timeout_output)}, hive_partitioning=false)) AS timeout_rows,
                (SELECT count(DISTINCT game_id) FROM read_parquet(
                    {sql_string(timeout_output)}, hive_partitioning=false)) AS timeout_unique_ids,
                (SELECT count(*) FROM read_parquet(
                    {sql_string(timeout_output)}, hive_partitioning=false)
                    WHERE api_status IS DISTINCT FROM 'timeout') AS non_timeout_rows
            """,
        )
        assert_equal(output_validation["status_rows"], spec.target_rows, f"{spec.month} output rows")
        assert_equal(
            output_validation["status_unique_ids"], spec.target_rows, f"{spec.month} output unique IDs"
        )
        assert_equal(output_validation["timeout_rows"], spec.timeout_rows, f"{spec.month} timeout rows")
        assert_equal(
            output_validation["timeout_unique_ids"],
            spec.timeout_rows,
            f"{spec.month} timeout unique IDs",
        )
        assert_equal(output_validation["non_timeout_rows"], 0, f"{spec.month} timeout status")
        for path, label in (
            (status_output, "status index"),
            (timeout_output, "timeout IDs"),
        ):
            names = tuple(row["column_name"] for row in parquet_schema(connection, path))
            assert_equal(names, COMMON_COLUMNS, f"{spec.month} {label} schema")
        connection.execute("CHECKPOINT")
    finally:
        connection.close()

    status_hash = sha256_file(status_output)
    timeout_hash = sha256_file(timeout_output)
    elapsed = round(time.monotonic() - started, 3)
    manifest = {
        "final_ok": True,
        "schema_version": "stage04-status-integration-v1",
        "script_version": SCRIPT_VERSION,
        "month": spec.month,
        "block": spec.block,
        "source_block": spec.source_block,
        "provenance_class": spec.provenance_class,
        "source_contract": asdict(spec),
        "source_columns": list(resolved.source_columns),
        "source_files": list(resolved.source_records),
        "source_set_sha256": resolved.source_set_sha256,
        "source_validation": dict(validation),
        "output_validation": dict(output_validation),
        "common_columns": list(COMMON_COLUMNS),
        "elapsed_seconds": elapsed,
        "outputs": {
            "status_index": {
                "relative_path": "api_status_index.parquet",
                "rows": spec.target_rows,
                "sha256": status_hash,
                "size_bytes": status_output.stat().st_size,
            },
            "timeout_ids": {
                "relative_path": "timeout_ids.parquet",
                "rows": spec.timeout_rows,
                "sha256": timeout_hash,
                "size_bytes": timeout_output.stat().st_size,
            },
        },
    }
    atomic_write_json(partial / "month_manifest.json", manifest)
    success = {
        "final_ok": True,
        "finished_utc": utc_now(),
        "month": spec.month,
        "block": spec.block,
        "target_rows": spec.target_rows,
        "timeout_rows": spec.timeout_rows,
        "outoftime_rows": spec.outoftime_rows,
        "source_set_sha256": resolved.source_set_sha256,
        "outputs": manifest["outputs"],
    }
    atomic_write_json(partial / "_SUCCESS.json", success)
    shutil.rmtree(work)
    if final_dir.exists():
        raise ContractError(f"Final month appeared during build: {final_dir}")
    os.replace(partial, final_dir)
    logger.emit(f"{spec.month}: reconciled and atomically published", elapsed_seconds=elapsed)
    return {"status": "built", "success": success}


def global_relation(paths: Sequence[Path]) -> str:
    return (
        "read_parquet("
        f"{sql_path_list(paths)}, union_by_name=true, hive_partitioning=false)"
    )


def run_global_gates(
    *,
    output_root: Path,
    run_root: Path,
    args: argparse.Namespace,
    duckdb: Any,
    logger: EventLog,
) -> Mapping[str, Any]:
    status_paths = [
        output_root / f"month={month}" / "api_status_index.parquet"
        for month in LOCKED_MONTHS
    ]
    timeout_paths = [
        output_root / f"month={month}" / "timeout_ids.parquet"
        for month in LOCKED_MONTHS
    ]
    for path in [*status_paths, *timeout_paths]:
        if not path.is_file():
            raise ContractError(f"Global gate input is missing: {path}")

    actual_month_dirs = {
        path.name.removeprefix("month=")
        for path in output_root.glob("month=*")
        if path.is_dir()
    }
    assert_equal(actual_month_dirs, set(LOCKED_MONTHS), "published month-directory set")

    work = run_root / "_global_work"
    work.mkdir(parents=True, exist_ok=False)
    duplicate_output = run_root / "duplicate_game_ids.parquet"
    unresolved_output = run_root / "unresolved_ids.parquet"
    status_relation = global_relation(status_paths)
    timeout_relation = global_relation(timeout_paths)
    connection = duckdb.connect(str(work / "global.duckdb"))
    try:
        configure_duckdb(
            connection,
            temp_directory=work / "duckdb_tmp",
            memory_limit=args.memory_limit,
            threads=args.threads,
        )
        logger.emit("Global gate: validating 24-month totals and locked boundaries")
        totals = query_one_dict(
            connection,
            f"""
            SELECT
                count(*) AS target_rows,
                count(*) FILTER (WHERE api_status = 'timeout') AS timeout_rows,
                count(*) FILTER (WHERE api_status = 'outoftime') AS outoftime_rows,
                count(DISTINCT month) AS month_count,
                min(month) AS first_month,
                max(month) AS last_month,
                count(*) FILTER (WHERE month = '2023-10') AS october_2023_rows,
                count(*) FILTER (WHERE month = '2025-11') AS november_2025_rows,
                count(*) FILTER (
                    WHERE api_status NOT IN ('timeout','outoftime') OR api_status IS NULL
                ) AS invalid_status_rows
            FROM {status_relation}
            """,
        )
        expected_totals = {
            "target_rows": EXPECTED_TOTAL_TARGETS,
            "timeout_rows": EXPECTED_TOTAL_TIMEOUT,
            "outoftime_rows": EXPECTED_TOTAL_OUTOFTIME,
            "month_count": 24,
            "first_month": "2023-11",
            "last_month": "2025-10",
            "october_2023_rows": 0,
            "november_2025_rows": 0,
            "invalid_status_rows": 0,
        }
        for key, value in expected_totals.items():
            assert_equal(totals[key], value, f"global {key}")

        timeout_validation = query_one_dict(
            connection,
            f"""
            SELECT
                count(*) AS rows,
                count(*) FILTER (WHERE api_status IS DISTINCT FROM 'timeout')
                    AS invalid_rows,
                count(DISTINCT month) AS month_count
            FROM {timeout_relation}
            """,
        )
        assert_equal(timeout_validation["rows"], EXPECTED_TOTAL_TIMEOUT, "global timeout rows")
        assert_equal(timeout_validation["invalid_rows"], 0, "global timeout-only status")
        assert_equal(timeout_validation["month_count"], 24, "global timeout month count")

        logger.emit(
            "Global gate: exact duplicate-ID group-by over 170,648,691 targets started"
        )
        # Keep the first, expensive aggregate as narrow as possible.  Building
        # string aggregates while grouping 170M mostly-unique IDs would retain
        # unnecessary state for every group.  We first materialize only the
        # duplicate keys, then decorate those keys with provenance if any exist.
        connection.execute(
            f"""
            CREATE TABLE duplicate_keys AS
            SELECT game_id, count(*) AS occurrences
            FROM {status_relation}
            GROUP BY game_id
            HAVING count(*) > 1
            """
        )
        duplicate_count = connection.execute(
            "SELECT count(*) FROM duplicate_keys"
        ).fetchone()[0]
        if duplicate_count:
            connection.execute(
                f"""
                CREATE TABLE duplicate_ids AS
                SELECT
                    keys.game_id,
                    keys.occurrences,
                    min(data.month) AS first_month,
                    max(data.month) AS last_month,
                    string_agg(data.month, '|' ORDER BY data.month) AS months,
                    string_agg(data.source_block, '|' ORDER BY data.month)
                        AS source_blocks
                FROM duplicate_keys AS keys
                JOIN {status_relation} AS data USING (game_id)
                GROUP BY keys.game_id, keys.occurrences
                """
            )
        else:
            connection.execute(
                """
                CREATE TABLE duplicate_ids AS
                SELECT
                    CAST(NULL AS VARCHAR) AS game_id,
                    CAST(NULL AS BIGINT) AS occurrences,
                    CAST(NULL AS VARCHAR) AS first_month,
                    CAST(NULL AS VARCHAR) AS last_month,
                    CAST(NULL AS VARCHAR) AS months,
                    CAST(NULL AS VARCHAR) AS source_blocks
                WHERE false
                """
            )
        connection.execute(
            f"""
            COPY (SELECT * FROM duplicate_ids ORDER BY game_id)
            TO {sql_string(duplicate_output)}
            (FORMAT PARQUET, COMPRESSION ZSTD)
            """
        )
        assert_equal(duplicate_count, 0, "global duplicate game IDs")

        # All three blocks have complete source coverage.  Publish an explicit
        # typed empty ledger rather than leaving unresolved-ID state implicit.
        connection.execute(
            f"""
            COPY (
                SELECT
                    CAST(NULL AS VARCHAR) AS month,
                    CAST(NULL AS VARCHAR) AS game_id,
                    CAST(NULL AS VARCHAR) AS source_block,
                    CAST(NULL AS VARCHAR) AS reason
                WHERE false
            ) TO {sql_string(unresolved_output)}
            (FORMAT PARQUET, COMPRESSION ZSTD)
            """
        )
        unresolved_count = connection.execute(
            f"SELECT count(*) FROM read_parquet("
            f"{sql_string(unresolved_output)}, hive_partitioning=false)"
        ).fetchone()[0]
        assert_equal(unresolved_count, 0, "global unresolved IDs")
        connection.execute("CHECKPOINT")
    finally:
        connection.close()
        shutil.rmtree(work, ignore_errors=True)

    logger.emit("Global duplicate-ID gate: PASSED (zero duplicates)")
    return {
        "totals": dict(totals),
        "timeout_validation": dict(timeout_validation),
        "duplicate_game_ids": duplicate_count,
        "duplicate_ledger": {
            "path": str(duplicate_output),
            "sha256": sha256_file(duplicate_output),
            "rows": duplicate_count,
        },
        "unresolved_ids": unresolved_count,
        "unresolved_ledger": {
            "path": str(unresolved_output),
            "sha256": sha256_file(unresolved_output),
            "rows": unresolved_count,
        },
        "all_gates_pass": True,
    }


def block_totals(month_rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Mapping[str, int]]:
    observed: dict[str, dict[str, int]] = {
        block: {"target_rows": 0, "timeout_rows": 0, "outoftime_rows": 0}
        for block in EXPECTED_BLOCK_TOTALS
    }
    for row in month_rows:
        target = observed[row["block"]]
        for key in ("target_rows", "timeout_rows", "outoftime_rows"):
            target[key] += int(row[key])
    for block, expected in EXPECTED_BLOCK_TOTALS.items():
        assert_equal(observed[block], dict(expected), f"{block} block totals")
    return observed


def software_versions(duckdb: Any) -> Mapping[str, Any]:
    return {
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "duckdb": getattr(duckdb, "__version__", "unknown"),
        "script_version": SCRIPT_VERSION,
    }


def execute(args: argparse.Namespace, output_root: Path) -> int:
    duckdb = import_duckdb()
    project_root = args.project_root.resolve()
    # Fail before creating anything when the external project volume is absent.
    # This prevents an unmounted /Volumes path from being silently recreated on
    # the Mac's internal disk.
    if not project_root.is_dir():
        raise ContractError(f"Project root does not exist: {project_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_root = output_root / "_manifests"
    run_root = manifest_root / "runs" / make_run_id()
    run_root.mkdir(parents=True, exist_ok=False)
    logger = EventLog(run_root / "run_events.jsonl")
    started = time.monotonic()
    atomic_write_text(run_root / "command.txt", shlex.join(sys.argv) + "\n")
    atomic_write_json(run_root / "software_versions.json", software_versions(duckdb))
    script_path = Path(__file__).resolve()
    atomic_write_json(
        run_root / "script_identity.json",
        {
            "path": str(script_path),
            "sha256": sha256_file(script_path),
            "size_bytes": script_path.stat().st_size,
            "version": SCRIPT_VERSION,
        },
    )

    try:
        logger.emit("24-MONTH STAGE 04 RECONCILIATION STARTED")
        logger.emit("Safety: zero API requests; all three source roots are read-only")
        programs = validate_program_identities(project_root, verify_hashes=True)
        inventory_path, inventory_rows = load_earlier_inventory(project_root)
        inventory_identity = {
            "path": str(inventory_path),
            "sha256": sha256_file(inventory_path),
            "size_bytes": inventory_path.stat().st_size,
        }
        bridge_integrity = project_root / BRIDGE_INTEGRITY_RELATIVE_PATH
        if not bridge_integrity.is_file():
            raise ContractError(f"Bridge integrity manifest is missing: {bridge_integrity}")
        bridge_integrity_identity = {
            "path": str(bridge_integrity),
            "sha256": sha256_file(bridge_integrity),
            "size_bytes": bridge_integrity.stat().st_size,
        }
        atomic_write_json(
            run_root / "top_level_source_identities.json",
            {
                "programs": programs,
                "earlier_inventory": inventory_identity,
                "bridge_integrity_manifest": bridge_integrity_identity,
            },
        )

        month_rows: list[Mapping[str, Any]] = []
        for ordinal, month in enumerate(LOCKED_MONTHS, start=1):
            logger.emit(f"Resolving and fingerprinting month {ordinal}/24: {month}")
            resolved = resolve_source(
                MONTH_SPECS[month],
                project_root=project_root,
                earlier_inventory_path=inventory_path,
                earlier_inventory_rows=inventory_rows,
                duckdb=duckdb,
                verify_hashes=True,
            )
            result = build_month(
                resolved=resolved,
                output_root=output_root,
                args=args,
                duckdb=duckdb,
                logger=logger,
            )
            success = result["success"]
            month_rows.append(
                {
                    "month": month,
                    "block": success["block"],
                    "run_status": result["status"],
                    "final_ok": success["final_ok"],
                    "target_rows": success["target_rows"],
                    "timeout_rows": success["timeout_rows"],
                    "outoftime_rows": success["outoftime_rows"],
                    "source_set_sha256": success["source_set_sha256"],
                    "status_index_path": str(
                        output_root / f"month={month}" / "api_status_index.parquet"
                    ),
                    "status_index_sha256": success["outputs"]["status_index"]["sha256"],
                    "timeout_ids_path": str(
                        output_root / f"month={month}" / "timeout_ids.parquet"
                    ),
                    "timeout_ids_sha256": success["outputs"]["timeout_ids"]["sha256"],
                }
            )

        observed_blocks = block_totals(month_rows)
        write_csv(
            run_root / "monthly_funnel.csv",
            month_rows,
            (
                "month",
                "block",
                "run_status",
                "final_ok",
                "target_rows",
                "timeout_rows",
                "outoftime_rows",
                "source_set_sha256",
                "status_index_path",
                "status_index_sha256",
                "timeout_ids_path",
                "timeout_ids_sha256",
            ),
        )
        atomic_write_text(
            run_root / "api_status_index_paths.txt",
            "".join(row["status_index_path"] + "\n" for row in month_rows),
        )
        atomic_write_text(
            run_root / "timeout_id_paths.txt",
            "".join(row["timeout_ids_path"] + "\n" for row in month_rows),
        )

        global_validation = run_global_gates(
            output_root=output_root,
            run_root=run_root,
            args=args,
            duckdb=duckdb,
            logger=logger,
        )
        elapsed = round(time.monotonic() - started, 3)
        summary = {
            "final_ok": True,
            "decision": (
                "STAGE04_24M_RECONCILED__GLOBAL_IDS_UNIQUE__API_TIMEOUT_PANEL_FROZEN"
            ),
            "analysis_authorization": "PROCEED_TO_STAGE05_OPPORTUNITY_PANEL",
            "finished_utc": utc_now(),
            "elapsed_seconds": elapsed,
            "locked_sample_start": LOCKED_SAMPLE_START,
            "locked_sample_end": LOCKED_SAMPLE_END,
            "month_count": 24,
            "months": list(LOCKED_MONTHS),
            "first_month": "2023-11",
            "last_month": "2025-10",
            "total_target_rows": EXPECTED_TOTAL_TARGETS,
            "total_timeout_rows": EXPECTED_TOTAL_TIMEOUT,
            "total_outoftime_rows": EXPECTED_TOTAL_OUTOFTIME,
            "duplicate_game_ids": 0,
            "unresolved_ids": 0,
            "api_refetch_performed": False,
            "block_totals": observed_blocks,
            "global_validation": global_validation,
            "monthly_funnel": month_rows,
            "output_root": str(output_root),
            "next_step": (
                "Build the common 24-month timeout opportunity panel by joining "
                "these frozen timeout IDs to the authenticated PGN candidate lineages."
            ),
        }
        atomic_write_json(run_root / "summary.json", summary)
        atomic_write_json(run_root / "_SUCCESS.json", summary)
        atomic_write_json(manifest_root / "latest_summary.json", summary)
        atomic_write_text(manifest_root / "latest_run_path.txt", str(run_root) + "\n")
        atomic_write_json(output_root / "_SUCCESS.json", summary)
        logger.emit("24-MONTH STAGE 04 RECONCILIATION: TECHNICALLY COMPLETE")
        logger.emit(f"Decision: {summary['decision']}")
        logger.emit(f"API targets: {EXPECTED_TOTAL_TARGETS:,}")
        logger.emit(f"API timeout: {EXPECTED_TOTAL_TIMEOUT:,}")
        logger.emit("Global duplicate game IDs: 0")
        logger.emit(f"Run manifest: {run_root}")
        return 0
    except Exception as exc:
        failure = {
            "final_ok": False,
            "failed_utc": utc_now(),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "api_requests_performed": False,
            "output_root": str(output_root),
        }
        atomic_write_json(run_root / "failure.json", failure)
        logger.emit(f"FAILED CLOSED: {type(exc).__name__}: {exc}")
        raise


def plan(args: argparse.Namespace, output_root: Path) -> int:
    project_root = args.project_root.resolve()
    logger = EventLog(None)
    logger.emit("WRITE-FREE 24-MONTH RECONCILIATION PLAN STARTED")
    if not project_root.is_dir():
        raise ContractError(f"Project root does not exist: {project_root}")
    programs = validate_program_identities(project_root, verify_hashes=False)
    inventory_path, inventory_rows = load_earlier_inventory(project_root)
    duckdb = import_duckdb()
    source_preview = []
    for month in LOCKED_MONTHS:
        resolved = resolve_source(
            MONTH_SPECS[month],
            project_root=project_root,
            earlier_inventory_path=inventory_path,
            earlier_inventory_rows=inventory_rows,
            duckdb=duckdb,
            verify_hashes=False,
        )
        source_preview.append(
            {
                "month": month,
                "block": resolved.spec.block,
                "target_rows": resolved.spec.target_rows,
                "timeout_rows": resolved.spec.timeout_rows,
                "outoftime_rows": resolved.spec.outoftime_rows,
                "data_file_count": len(resolved.data_paths),
                "source_columns": list(resolved.source_columns),
            }
        )
    payload = {
        "mode": "plan_no_writes",
        "programs": programs,
        "project_root": str(project_root),
        "output_root": str(output_root),
        "earlier_inventory": str(inventory_path),
        "locked_months": list(LOCKED_MONTHS),
        "month_count": 24,
        "expected_totals": {
            "targets": EXPECTED_TOTAL_TARGETS,
            "timeout": EXPECTED_TOTAL_TIMEOUT,
            "outoftime": EXPECTED_TOTAL_OUTOFTIME,
        },
        "memory_limit": args.memory_limit,
        "threads": args.threads,
        "expected_runtime": "usually 30-120 minutes; potentially up to 3 hours",
        "temporary_space_guidance": "roughly 20-60 GB free",
        "source_preview": source_preview,
        "api_requests": "none",
        "writes": "none in plan mode; rerun with --execute",
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    logger.emit("WRITE-FREE PLAN COMPLETE")
    return 0


def create_fixture_parquet(
    connection: Any,
    path: Path,
    rows: Sequence[tuple[str, str]],
    *,
    legacy_names: bool,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    values = ",".join(
        f"({sql_string(game_id)}, {sql_string(status)})" for game_id, status in rows
    )
    id_name = "id" if legacy_names else "game_id"
    status_name = "status" if legacy_names else "api_status"
    connection.execute(
        f"""
        COPY (
            SELECT
                CAST(col0 AS VARCHAR) AS {id_name},
                CAST(col1 AS VARCHAR) AS {status_name}
            FROM (VALUES {values})
        ) TO {sql_string(path)} (FORMAT PARQUET)
        """
    )


def self_test(args: argparse.Namespace) -> int:
    duckdb = import_duckdb()
    with tempfile.TemporaryDirectory(prefix="stage04_24m_reconciler_selftest_") as raw:
        root = Path(raw)
        connection = duckdb.connect(":memory:")
        try:
            source_a = root / "source_a.parquet"
            source_b = root / "source_b.parquet"
            create_fixture_parquet(
                connection,
                source_a,
                (("AAA00001", "timeout"), ("AAA00002", "outoftime")),
                legacy_names=True,
            )
            create_fixture_parquet(
                connection,
                source_b,
                (("BBB00001", "timeout"), ("BBB00002", "outoftime")),
                legacy_names=False,
            )

            # Reproduce a production Hive-looking temporary directory and prove
            # that only the five physical output columns are observed.
            partial = root / ".month=2025-08.partial.99999"
            partial.mkdir()
            output = partial / "api_status_index.parquet"
            relation = (
                "read_parquet("
                f"{sql_path_list([source_a])}, hive_partitioning=false)"
            )
            connection.execute(
                f"""
                COPY (
                    SELECT
                        '2025-08'::VARCHAR AS month,
                        id::VARCHAR AS game_id,
                        status::VARCHAR AS api_status,
                        'fixture'::VARCHAR AS source_block,
                        'fixture'::VARCHAR AS provenance_class
                    FROM {relation}
                    ORDER BY game_id
                ) TO {sql_string(output)} (FORMAT PARQUET)
                """
            )
            names = tuple(row["column_name"] for row in parquet_schema(connection, output))
            assert_equal(names, COMMON_COLUMNS, "self-test Hive-safe physical schema")

            second_output = root / "month=2025-09" / "api_status_index.parquet"
            second_output.parent.mkdir()
            connection.execute(
                f"""
                COPY (
                    SELECT
                        '2025-09'::VARCHAR AS month,
                        game_id::VARCHAR AS game_id,
                        api_status::VARCHAR AS api_status,
                        'fixture'::VARCHAR AS source_block,
                        'fixture'::VARCHAR AS provenance_class
                    FROM read_parquet({sql_string(source_b)}, hive_partitioning=false)
                ) TO {sql_string(second_output)} (FORMAT PARQUET)
                """
            )
            unique_relation = global_relation([output, second_output])
            duplicates = connection.execute(
                f"""
                SELECT count(*) FROM (
                    SELECT game_id FROM {unique_relation}
                    GROUP BY game_id HAVING count(*) > 1
                )
                """
            ).fetchone()[0]
            assert_equal(duplicates, 0, "self-test unique global IDs")

            duplicate_output = root / "duplicate.parquet"
            create_fixture_parquet(
                connection,
                duplicate_output,
                (("AAA00001", "timeout"),),
                legacy_names=False,
            )
            duplicate_relation = (
                "SELECT game_id FROM "
                + global_relation([output, second_output])
                + " UNION ALL SELECT game_id FROM read_parquet("
                + sql_string(duplicate_output)
                + ", hive_partitioning=false)"
            )
            detected = connection.execute(
                f"""
                SELECT count(*) FROM (
                    SELECT game_id FROM ({duplicate_relation})
                    GROUP BY game_id HAVING count(*) > 1
                )
                """
            ).fetchone()[0]
            assert_equal(detected, 1, "self-test duplicate detection")
        finally:
            connection.close()
    print("SELF-TEST PASS: schema, Hive-path, unique-ID, and duplicate-detection gates")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
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
        print("INTERRUPTED: completed months remain valid and temporary work is recoverable.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
