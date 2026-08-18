#!/usr/bin/env python3
"""
Canonical Stage 02: extract rating-replay inputs from Lichess PGN archives.

Purpose
-------
Stage 01 preserves the detailed board, clock, and role information needed for
the timeout-opportunity analysis. Stage 02 separately preserves the compact
game-header history needed to reconstruct Glicko-2 states and rating costs.

This separation matters because Glicko-2 replay requires all rated games, not
only Time-forfeit candidates.

For every game in each monthly rated-standard PGN, this script preserves:

    * stable archive order;
    * exact UTC date and time plus parsed UTC milliseconds;
    * Lichess game ID;
    * normalized white and black usernames;
    * pregame ratings;
    * observed rating changes;
    * result;
    * inferred speed;
    * raw fields needed to audit the speed/time transformations.

Deletion safety
---------------
A source PGN is not deletion-ready merely because this script finishes.

Canonical Stage 03 must additionally require:

    1. a successful Stage 00 acquisition checkpoint;
    2. a successful Stage 01 checkpoint;
    3. a production Stage 02 checkpoint;
    4. an exact source SHA-256 stored by Stage 02;
    5. Stage 01 and Stage 02 scanned-game counts that agree;
    6. valid Parquet metadata and matching output-part hashes;
    7. complete candidate-ID coverage.

Smoke runs intentionally omit the expensive hashes and therefore can never
authorize deletion.

Output layout
-------------
    derived/replication/rating_replay_inputs/
        month=YYYY-MM/
            part-00000.parquet
            part-00001.parquet
            ...
            progress.jsonl
            _SUCCESS.json
        _manifests/
            summary.json
            month_status.csv
            month_status.parquet
            rating_replay_input_paths.txt
            source_fingerprints.csv

Design
------
The script reads compressed PGNs as a stream. It extracts headers immediately
when the blank line following a header block is reached and ignores movetext.
It never loads a monthly archive into memory.

Outputs are written in bounded Parquet parts to a temporary month directory.
The completed directory is atomically renamed into place only after all
validation succeeds. An interrupted month can therefore never masquerade as a
successful month.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Dict, Iterator, List, Optional

import pyarrow as pa
import pyarrow.parquet as pq


# The final paper window is locked to the 24 complete months immediately
# preceding the November 2025 color-advantage change.
LOCKED_MONTHS = [
    "2023-11", "2023-12",
    "2024-01", "2024-02", "2024-03", "2024-04",
    "2024-05", "2024-06", "2024-07", "2024-08",
    "2024-09", "2024-10", "2024-11", "2024-12",
    "2025-01", "2025-02", "2025-03", "2025-04",
    "2025-05", "2025-06", "2025-07", "2025-08",
    "2025-09", "2025-10",
]

# The bridge months are the months for which raw PGNs are presently available
# and new downstream analysis remains necessary.
BRIDGE_MONTHS = [
    "2024-10", "2024-11", "2024-12",
    "2025-01", "2025-02", "2025-03", "2025-04",
    "2025-05", "2025-06", "2025-07",
]

# An explicit Arrow schema prevents type drift across batches and months.
SCHEMA = pa.schema(
    [
        pa.field("archive_ordinal", pa.int64()),
        pa.field("utc_ms", pa.int64()),
        pa.field("game_id", pa.string()),
        pa.field("white_username_norm", pa.string()),
        pa.field("black_username_norm", pa.string()),
        pa.field("white_elo", pa.int32()),
        pa.field("black_elo", pa.int32()),
        pa.field("white_rating_diff", pa.int32()),
        pa.field("black_rating_diff", pa.int32()),
        pa.field("result_code", pa.int8()),
        pa.field("speed", pa.string()),
        pa.field("utc_date_raw", pa.string()),
        pa.field("utc_time_raw", pa.string()),
        pa.field("event_raw", pa.string()),
        pa.field("time_control_raw", pa.string()),
        pa.field("variant_raw", pa.string()),
    ]
)


def utc_now() -> str:
    """Return a stable human-readable UTC timestamp."""

    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract canonical rating-replay inputs from PGN.zst files."
    )

    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path("/Volumes/XT_Pro/lichess_kindness"),
    )
    parser.add_argument(
        "--months",
        nargs="+",
        required=True,
        help="Months in YYYY-MM format, or the literal word 'bridge'.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--rows-per-part",
        type=int,
        default=1_000_000,
        help="Maximum rows per Parquet part.",
    )
    parser.add_argument(
        "--row-group-size",
        type=int,
        default=250_000,
    )
    parser.add_argument(
        "--zstd-threads",
        type=int,
        default=0,
        help="Threads passed to zstd; zero requests all available threads.",
    )
    parser.add_argument(
        "--max-games",
        type=int,
        default=None,
        help="Testing cap. Any capped run is permanently marked nonproduction.",
    )
    parser.add_argument(
        "--skip-source-sha256",
        action="store_true",
        help="Testing only. Stage 03 must reject outputs without this hash.",
    )
    parser.add_argument(
        "--skip-output-hashes",
        action="store_true",
        help="Testing only. Stage 03 must reject outputs without part hashes.",
    )
    parser.add_argument(
        "--overwrite-month",
        action="store_true",
        help="Move an old month to _backups before replacing it.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Required safety switch. Without it, only print the plan.",
    )

    return parser.parse_args()


def normalize_months(values: List[str]) -> List[str]:
    """Expand aliases, validate months, and preserve chronological order."""

    expanded: List[str] = []

    for value in values:
        if value == "bridge":
            expanded.extend(BRIDGE_MONTHS)
        else:
            expanded.append(value)

    months = sorted(set(expanded))

    invalid = [month for month in months if month not in LOCKED_MONTHS]
    if invalid:
        raise ValueError(
            "Requested months fall outside the locked paper window: "
            + ", ".join(invalid)
        )

    return months


def safe_int(value: Optional[str]) -> Optional[int]:
    """Parse PGN integer headers while tolerating a leading plus sign."""

    if value is None:
        return None

    text = str(value).strip().replace("+", "")

    if not text or text in {"?", "-", "null", "None"}:
        return None

    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def normalize_username(value: Optional[str]) -> Optional[str]:
    """Apply the lowercase normalization used by the replay dictionary."""

    if value is None:
        return None

    text = str(value).strip()

    if not text or text == "?":
        return None

    return text.lower()


def infer_game_id(headers: Dict[str, str]) -> Optional[str]:
    """Recover the canonical Lichess ID from GameId or Site."""

    game_id = headers.get("GameId")

    if game_id:
        return game_id.strip()

    site = headers.get("Site", "").strip()

    if site.startswith("https://lichess.org/"):
        return site.rstrip("/").rsplit("/", 1)[-1].split("?", 1)[0]

    return None


def parse_utc_ms(
    date_value: Optional[str],
    time_value: Optional[str],
) -> Optional[int]:
    """Parse Lichess UTCDate/UTCTime into Unix milliseconds."""

    if not date_value:
        return None

    date_text = str(date_value).strip()
    time_text = str(time_value or "00:00:00").strip()

    if "?" in date_text or "?" in time_text:
        return None

    candidates = [
        "%Y.%m.%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ]

    for fmt in candidates:
        try:
            parsed = dt.datetime.strptime(
                f"{date_text} {time_text}",
                fmt,
            ).replace(tzinfo=dt.timezone.utc)

            return int(parsed.timestamp() * 1000)
        except ValueError:
            continue

    return None


def infer_speed(headers: Dict[str, str]) -> Optional[str]:
    """
    Infer the historical replay speed.

    The event label is preferred because Lichess monthly PGNs normally label
    the speed explicitly. The TimeControl fallback reproduces the prior
    extractor's base-time thresholds.
    """

    event = headers.get("Event", "")
    event_lower = event.lower()

    for speed in (
        "ultrabullet",
        "bullet",
        "blitz",
        "rapid",
        "classical",
        "correspondence",
    ):
        if speed in event_lower:
            return speed

    time_control = headers.get("TimeControl", "").strip()

    if "+" not in time_control:
        return None

    try:
        base_seconds = int(time_control.split("+", 1)[0])
    except ValueError:
        return None

    if base_seconds <= 29:
        return "ultrabullet"
    if base_seconds <= 179:
        return "bullet"
    if base_seconds <= 479:
        return "blitz"
    if base_seconds <= 1499:
        return "rapid"

    return "classical"


def result_code(value: Optional[str]) -> Optional[int]:
    """
    Encode outcome from White's perspective.

        +1 = White win
         0 = draw
        -1 = Black win
    """

    if value == "1-0":
        return 1
    if value == "1/2-1/2":
        return 0
    if value == "0-1":
        return -1

    return None


def parse_tag_line(line: str) -> Optional[tuple[str, str]]:
    """Parse a normal PGN tag line without invoking a chess move parser."""

    if not (line.startswith("[") and line.endswith("]")):
        return None

    body = line[1:-1]

    try:
        tag, value = body.split(" ", 1)
    except ValueError:
        return None

    value = value.strip()

    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        value = value[1:-1]

    return tag, value


def iter_pgn_headers_zst(
    path: Path,
    zstd_threads: int,
) -> Iterator[Dict[str, str]]:
    """
    Stream header dictionaries from a compressed monthly PGN.

    Headers are yielded at the blank line immediately following the header
    block. Movetext is ignored until the next tag block begins.
    """

    command = [
        "zstd",
        f"-T{zstd_threads}",
        "-dc",
        str(path),
    ]

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1024 * 1024,
    )

    if process.stdout is None:
        raise RuntimeError("zstd stdout pipe was not created")

    headers: Dict[str, str] = {}
    collecting_headers = False
    reached_eof = False

    try:
        for raw_line in process.stdout:
            line = raw_line.rstrip("\r\n")
            parsed_tag = parse_tag_line(line)

            if parsed_tag is not None:
                if not collecting_headers:
                    headers = {}
                    collecting_headers = True

                tag, value = parsed_tag
                headers[tag] = value
                continue

            if collecting_headers and not line:
                yield headers
                headers = {}
                collecting_headers = False

        if collecting_headers and headers:
            yield headers

        reached_eof = True

    finally:
        process.stdout.close()

        if reached_eof:
            return_code = process.wait()

            if return_code != 0:
                raise RuntimeError(
                    f"zstd exited with return code {return_code}: {path}"
                )
        else:
            process.terminate()

            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def sha256_file(path: Path) -> str:
    """Hash a file in bounded chunks."""

    digest = hashlib.sha256()

    with path.open("rb") as handle:
        while True:
            block = handle.read(16 * 1024 * 1024)

            if not block:
                break

            digest.update(block)

    return digest.hexdigest()


def headers_to_row(
    headers: Dict[str, str],
    archive_ordinal: int,
) -> Dict[str, object]:
    """Convert one PGN header dictionary to the locked Stage 02 schema."""

    utc_date = headers.get("UTCDate") or headers.get("Date")
    utc_time = headers.get("UTCTime") or "00:00:00"

    return {
        "archive_ordinal": archive_ordinal,
        "utc_ms": parse_utc_ms(utc_date, utc_time),
        "game_id": infer_game_id(headers),
        "white_username_norm": normalize_username(headers.get("White")),
        "black_username_norm": normalize_username(headers.get("Black")),
        "white_elo": safe_int(headers.get("WhiteElo")),
        "black_elo": safe_int(headers.get("BlackElo")),
        "white_rating_diff": safe_int(headers.get("WhiteRatingDiff")),
        "black_rating_diff": safe_int(headers.get("BlackRatingDiff")),
        "result_code": result_code(headers.get("Result")),
        "speed": infer_speed(headers),
        "utc_date_raw": utc_date,
        "utc_time_raw": utc_time,
        "event_raw": headers.get("Event"),
        "time_control_raw": headers.get("TimeControl"),
        "variant_raw": headers.get("Variant") or "standard",
    }


def write_json(path: Path, value: object) -> None:
    """Write stable, readable JSON."""

    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n"
    )


def write_part(
    month_tmp: Path,
    part_number: int,
    rows: List[Dict[str, object]],
    row_group_size: int,
) -> tuple[Path, int]:
    """Write one independently verifiable Parquet part."""

    path = month_tmp / f"part-{part_number:05d}.parquet"
    table = pa.Table.from_pylist(rows, schema=SCHEMA)

    pq.write_table(
        table,
        path,
        compression="zstd",
        compression_level=6,
        use_dictionary=True,
        row_group_size=row_group_size,
        write_statistics=True,
    )

    return path, table.num_rows


def validate_part(path: Path, expected_rows: int) -> None:
    """Fail immediately if a written part is unreadable or truncated."""

    parquet = pq.ParquetFile(path)

    if parquet.metadata.num_rows != expected_rows:
        raise RuntimeError(
            f"Parquet row mismatch for {path}: "
            f"expected={expected_rows}, "
            f"observed={parquet.metadata.num_rows}"
        )

    observed_schema = parquet.schema_arrow

    if observed_schema != SCHEMA:
        raise RuntimeError(
            f"Parquet schema mismatch for {path}\n"
            f"Expected: {SCHEMA}\nObserved: {observed_schema}"
        )


def backup_existing_month(
    output_root: Path,
    month_dir: Path,
) -> Path:
    """Preserve an existing month before an explicitly requested rebuild."""

    backup_root = output_root / "_backups"
    backup_root.mkdir(parents=True, exist_ok=True)

    timestamp = dt.datetime.now(
        dt.timezone.utc
    ).strftime("%Y%m%d_%H%M%S")

    backup = backup_root / f"{month_dir.name}_{timestamp}"
    shutil.move(str(month_dir), str(backup))

    return backup


def rebuild_manifests(output_root: Path) -> None:
    """Rebuild stable manifests from successful month directories."""

    manifest_root = output_root / "_manifests"
    manifest_root.mkdir(parents=True, exist_ok=True)

    records = []
    part_paths = []

    for month_dir in sorted(output_root.glob("month=*")):
        success_path = month_dir / "_SUCCESS.json"

        if not success_path.exists():
            continue

        success = json.loads(success_path.read_text())

        record = {
            "month": success.get("month"),
            "status": "ok" if success.get("final_ok") else "failed",
            "production": success.get("production"),
            "rows": success.get("rows"),
            "part_count": success.get("part_count"),
            "source_size_bytes": success.get("source_size_bytes"),
            "source_sha256": success.get("source_sha256"),
            "stage1_scanned_games": success.get("stage1_scanned_games"),
            "scan_count_matches_stage1": success.get(
                "scan_count_matches_stage1"
            ),
            "started_utc": success.get("started_utc"),
            "finished_utc": success.get("finished_utc"),
            "elapsed_seconds": success.get("elapsed_seconds"),
        }
        records.append(record)

        for path in sorted(month_dir.glob("part-*.parquet")):
            part_paths.append(str(path))

    fieldnames = [
        "month",
        "status",
        "production",
        "rows",
        "part_count",
        "source_size_bytes",
        "source_sha256",
        "stage1_scanned_games",
        "scan_count_matches_stage1",
        "started_utc",
        "finished_utc",
        "elapsed_seconds",
    ]

    csv_path = manifest_root / "month_status.csv"

    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)

    if records:
        table = pa.Table.from_pylist(records)
        pq.write_table(
            table,
            manifest_root / "month_status.parquet",
            compression="zstd",
        )

    (manifest_root / "rating_replay_input_paths.txt").write_text(
        "\n".join(part_paths) + ("\n" if part_paths else "")
    )

    fingerprint_fields = [
        "month",
        "source_size_bytes",
        "source_sha256",
        "production",
    ]

    with (
        manifest_root / "source_fingerprints.csv"
    ).open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fingerprint_fields,
        )
        writer.writeheader()

        for record in records:
            writer.writerow(
                {
                    key: record.get(key)
                    for key in fingerprint_fields
                }
            )

    summary = {
        "created_utc": utc_now(),
        "output_root": str(output_root),
        "n_successful": sum(
            record["status"] == "ok" for record in records
        ),
        "n_production": sum(
            bool(record["production"]) for record in records
        ),
        "total_rows": sum(
            int(record["rows"] or 0) for record in records
        ),
        "months": [
            record["month"] for record in records
        ],
        "all_have_source_sha256": all(
            bool(record["source_sha256"]) for record in records
        ) if records else False,
        "all_scan_counts_match_stage1": all(
            bool(record["scan_count_matches_stage1"])
            for record in records
        ) if records else False,
    }

    write_json(manifest_root / "summary.json", summary)


def process_month(
    *,
    month: str,
    raw_root: Path,
    stage1_root: Path,
    output_root: Path,
    rows_per_part: int,
    row_group_size: int,
    zstd_threads: int,
    max_games: Optional[int],
    skip_source_sha256: bool,
    skip_output_hashes: bool,
    overwrite_month: bool,
) -> Dict[str, object]:
    """Extract and atomically finalize one month."""

    source = (
        raw_root
        / f"lichess_db_standard_rated_{month}.pgn.zst"
    )
    stage1_success_path = (
        stage1_root / f"month={month}" / "_SUCCESS.json"
    )
    final_month_dir = output_root / f"month={month}"

    if not source.exists():
        raise FileNotFoundError(f"Raw PGN missing: {source}")

    if not stage1_success_path.exists():
        raise FileNotFoundError(
            f"Stage 01 success checkpoint missing: "
            f"{stage1_success_path}"
        )

    if final_month_dir.exists():
        existing_success = final_month_dir / "_SUCCESS.json"

        if existing_success.exists() and not overwrite_month:
            existing = json.loads(existing_success.read_text())
            print(
                f"SKIP {month}: existing successful output; "
                f"rows={existing.get('rows'):,}"
            )
            return existing

        if not overwrite_month:
            raise FileExistsError(
                f"Output month exists without permission to replace it: "
                f"{final_month_dir}"
            )

        backup = backup_existing_month(
            output_root,
            final_month_dir,
        )
        print(f"BACKED UP {month}: {backup}")

    stage1_success = json.loads(stage1_success_path.read_text())
    stage1_scanned = int(
        stage1_success.get("scanned_games") or 0
    )

    production = (
        max_games is None
        and not skip_source_sha256
        and not skip_output_hashes
    )

    started = time.time()
    started_utc = utc_now()

    tmp_dir = output_root / (
        f".{final_month_dir.name}.tmp_"
        f"{os.getpid()}_"
        f"{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    )
    tmp_dir.mkdir(parents=True, exist_ok=False)

    progress_path = tmp_dir / "progress.jsonl"

    source_size = source.stat().st_size
    source_mtime_ns = source.stat().st_mtime_ns

    print()
    print(f"START MONTH: {month}")
    print(f"Source: {source}")
    print(f"Source bytes: {source_size:,}")
    print(f"Stage 01 scanned games: {stage1_scanned:,}")
    print(f"Production mode: {production}")

    source_hash = None

    if not skip_source_sha256:
        hash_started = time.time()
        print("Computing source SHA-256...")
        source_hash = sha256_file(source)
        print(
            f"Source SHA-256 complete in "
            f"{time.time() - hash_started:,.1f}s: "
            f"{source_hash}"
        )

    counters = Counter()
    speed_counts = Counter()
    result_counts = Counter()
    rows: List[Dict[str, object]] = []
    parts = []
    part_number = 0
    scanned = 0

    header_iterator = iter_pgn_headers_zst(
        source,
        zstd_threads,
    )

    try:
        for headers in header_iterator:
            scanned += 1
            row = headers_to_row(headers, scanned)
            rows.append(row)

            for key in (
                "utc_ms",
                "game_id",
                "white_username_norm",
                "black_username_norm",
                "white_elo",
                "black_elo",
                "white_rating_diff",
                "black_rating_diff",
                "result_code",
                "speed",
            ):
                if row[key] is None:
                    counters[f"missing_{key}"] += 1

            speed_counts[str(row["speed"])] += 1
            result_counts[str(row["result_code"])] += 1

            if len(rows) >= rows_per_part:
                part_path, part_rows = write_part(
                    tmp_dir,
                    part_number,
                    rows,
                    row_group_size,
                )
                validate_part(part_path, part_rows)

                parts.append(
                    {
                        "relative_path": part_path.name,
                        "rows": part_rows,
                        "size_bytes": part_path.stat().st_size,
                    }
                )

                part_number += 1
                rows = []

                progress = {
                    "utc": utc_now(),
                    "month": month,
                    "scanned": scanned,
                    "parts_completed": part_number,
                }

                with progress_path.open("a") as handle:
                    handle.write(
                        json.dumps(progress, sort_keys=True)
                        + "\n"
                    )

                print(
                    f"{month} progress: scanned={scanned:,}, "
                    f"parts={part_number:,}"
                )

            if max_games is not None and scanned >= max_games:
                break

    finally:
        header_iterator.close()

    if rows:
        part_path, part_rows = write_part(
            tmp_dir,
            part_number,
            rows,
            row_group_size,
        )
        validate_part(part_path, part_rows)

        parts.append(
            {
                "relative_path": part_path.name,
                "rows": part_rows,
                "size_bytes": part_path.stat().st_size,
            }
        )

    observed_part_rows = sum(
        int(part["rows"]) for part in parts
    )

    if observed_part_rows != scanned:
        raise RuntimeError(
            f"Stage 02 row conservation failure for {month}: "
            f"scanned={scanned:,}, "
            f"part_rows={observed_part_rows:,}"
        )

    expected_scan = (
        min(stage1_scanned, max_games)
        if max_games is not None
        else stage1_scanned
    )
    scan_count_matches = scanned == expected_scan

    if not scan_count_matches:
        raise RuntimeError(
            f"Stage 01/02 scan-count mismatch for {month}: "
            f"stage01_expected={expected_scan:,}, "
            f"stage02_scanned={scanned:,}"
        )

    if not skip_output_hashes:
        print("Computing output-part SHA-256 hashes...")

        for part in parts:
            part["sha256"] = sha256_file(
                tmp_dir / str(part["relative_path"])
            )
    else:
        for part in parts:
            part["sha256"] = None

    success = {
        "stage": "02_extract_rating_replay_inputs",
        "month": month,
        "final_ok": True,
        "production": production,
        "locked_sample_start": "2023-11-01",
        "locked_sample_end": "2025-10-31",
        "source_path": str(source),
        "source_size_bytes": source_size,
        "source_mtime_ns": source_mtime_ns,
        "source_sha256": source_hash,
        "stage00_checkpoint": str(
            raw_root
            / ".acquire_checkpoints"
            / f"{source.name}.ok.json"
        ),
        "stage1_success_checkpoint": str(
            stage1_success_path
        ),
        "stage1_scanned_games": stage1_scanned,
        "rows": scanned,
        "scan_count_matches_stage1": scan_count_matches,
        "max_games": max_games,
        "rows_per_part": rows_per_part,
        "row_group_size": row_group_size,
        "part_count": len(parts),
        "parts": parts,
        "missing_field_counts": dict(counters),
        "speed_counts": dict(speed_counts),
        "result_code_counts": dict(result_counts),
        "schema": [
            {
                "name": field.name,
                "type": str(field.type),
                "nullable": field.nullable,
            }
            for field in SCHEMA
        ],
        "started_utc": started_utc,
        "finished_utc": utc_now(),
        "elapsed_seconds": round(
            time.time() - started,
            3,
        ),
    }

    write_json(tmp_dir / "_SUCCESS.json", success)

    # Final metadata check before exposing the month as successful.
    for part in parts:
        validate_part(
            tmp_dir / str(part["relative_path"]),
            int(part["rows"]),
        )

    os.replace(tmp_dir, final_month_dir)

    print(
        f"COMPLETE {month}: rows={scanned:,}, "
        f"parts={len(parts):,}, "
        f"elapsed={success['elapsed_seconds']:,.1f}s"
    )

    return success


def main() -> None:
    args = parse_args()
    months = normalize_months(args.months)

    project_root = args.project_root.resolve()
    raw_root = (
        project_root / "raw/lichess_pgn_standard"
    )
    stage1_root = (
        project_root
        / "derived/replication/pgn_timeforfeit_candidates"
    )
    output_root = (
        args.output_root.resolve()
        if args.output_root is not None
        else project_root
        / "derived/replication/rating_replay_inputs"
    )

    plan = {
        "stage": "02_extract_rating_replay_inputs",
        "project_root": str(project_root),
        "raw_root": str(raw_root),
        "stage1_root": str(stage1_root),
        "output_root": str(output_root),
        "months": months,
        "rows_per_part": args.rows_per_part,
        "row_group_size": args.row_group_size,
        "zstd_threads": args.zstd_threads,
        "max_games": args.max_games,
        "skip_source_sha256": args.skip_source_sha256,
        "skip_output_hashes": args.skip_output_hashes,
        "execute": args.execute,
    }

    print(json.dumps(plan, indent=2, sort_keys=True))

    if not args.execute:
        print(
            "\nDRY RUN ONLY. Add --execute to process data."
        )
        return

    output_root.mkdir(parents=True, exist_ok=True)

    # Report free space before beginning. The script does not guess a rigid
    # output-size multiplier because compression depends on archive vintage.
    disk = shutil.disk_usage(output_root)
    print(
        f"\nOutput-volume free space: "
        f"{disk.free / (1024 ** 3):,.2f} GiB"
    )

    failures = []

    for month in months:
        try:
            process_month(
                month=month,
                raw_root=raw_root,
                stage1_root=stage1_root,
                output_root=output_root,
                rows_per_part=args.rows_per_part,
                row_group_size=args.row_group_size,
                zstd_threads=args.zstd_threads,
                max_games=args.max_games,
                skip_source_sha256=args.skip_source_sha256,
                skip_output_hashes=args.skip_output_hashes,
                overwrite_month=args.overwrite_month,
            )
            rebuild_manifests(output_root)

        except Exception as exc:
            failures.append(
                {
                    "month": month,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            print(
                f"FAILED {month}: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            break

    rebuild_manifests(output_root)

    if failures:
        raise SystemExit(
            json.dumps(
                {"failures": failures},
                indent=2,
            )
        )

    print("\nFINAL STAGE 02 SUMMARY")
    print(
        (
            output_root
            / "_manifests"
            / "summary.json"
        ).read_text()
    )


if __name__ == "__main__":
    main()
