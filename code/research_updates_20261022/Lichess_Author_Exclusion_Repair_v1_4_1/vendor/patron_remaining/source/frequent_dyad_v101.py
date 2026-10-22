#!/usr/bin/env python3
"""Exact, outcome-blind frequent-dyad census for the 24-month Lichess window.

The program scans every authenticated chronology shard in 2023-11--2025-10,
pools all named time controls, and counts games by unordered player pair.  It
then constructs treatment-blind exclusion flags for Stage 07 and, when
available, the certified C7X classification.  Player identifiers and row-level
flags remain under the private state root; public output is aggregate only.

The expensive stages are checkpointed and authenticated.  A stopped run may
be restarted with the same command.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import time
import traceback
from typing import Any, Iterable, Mapping, Sequence
import uuid


SCRIPT_VERSION = "1.0.1"
PROJECT_AUTHORITY = Path("/Volumes/XT_Pro/lichess_kindness")
CHRONOLOGY_MANIFEST_AUTHORITY = PROJECT_AUTHORITY / (
    "output/dynamic_prosociality_a3_chronology_gate_v100/"
    "20260821T234626Z/chronology_input_manifest.tsv"
)
CHRONOLOGY_MANIFEST_SHA256 = (
    "1d4648bb17cafd9e58c14ab78d32abe855f0bc62a6fb75ac88e02494a73337cd"
)
STAGE07_RELATIVE = Path("derived/replication/analysis_panel_24m_sf100k")
C7X_RELATIVE = Path(
    "derived/replication/dynamics_campaign1_c7x_fullpanel_v101_PRIVATE/"
    "c7x_classification_private.parquet"
)
PRIVATE_STATE_RELATIVE = Path(
    "derived/replication/frequent_dyad_census_24m_v101_PRIVATE"
)
PUBLIC_OUTPUT_RELATIVE = Path("output/frequent_dyad_census_24m_v101")

MAIN_START_MS = 1_698_796_800_000  # 2023-11-01T00:00:00Z
MAIN_END_EXCLUSIVE_MS = 1_761_955_200_000  # 2025-11-01T00:00:00Z
MAIN_MONTHS = tuple(
    f"{year:04d}-{month:02d}"
    for year, month in (
        (2023 + (offset + 10) // 12, (offset + 10) % 12 + 1)
        for offset in range(24)
    )
)
NAMED_SPEEDS = (
    "ultrabullet",
    "bullet",
    "blitz",
    "rapid",
    "classical",
    "correspondence",
)
# The published monthly standard-rated archive counts and the authenticated
# downstream chronology are distinct authorities.  The chronology is the
# exact pair-identification frame; the raw archive total is used to bound the
# whole-archive game share without guessing how omitted rows would classify.
PUBLISHED_RAW_GAMES = 2_231_251_938
EXPECTED_CHRONOLOGY_GAMES = 2_229_237_137
EXPECTED_STAGE07_ROWS = 47_587_020
EXPECTED_STAGE07_SUCCESS_SHA256 = (
    "8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7"
)
EXPECTED_C7X_ROWS = 27_627
EXPECTED_C7X_SHA256 = (
    "998b6087806b8300718897537b67828cc893259d96023a92d91de9ed64e331ed"
)
PAIR_HASH_SEED = 2_026_090_301
DEFAULT_THRESHOLDS = (2, 3, 5, 10)
STATUS = "FREQUENT_DYAD_CENSUS_24M_V101_OK"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def utc_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if hasattr(value, "item"):
        try:
            return json_safe(value.item())
        except (ValueError, AttributeError):
            pass
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Path):
        return str(value)
    return value


def canonical_json(payload: Any) -> str:
    return json.dumps(
        json_safe(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_json(payload: Any) -> str:
    return sha256_bytes(canonical_json(payload).encode("utf-8"))


def sha256_file(path: Path, chunk_size: int = 16 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{uuid.uuid4().hex}")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def atomic_json(path: Path, payload: Any) -> None:
    atomic_text(path, json.dumps(json_safe(payload), indent=2, sort_keys=True) + "\n")


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        raise RuntimeError(f"Refusing to write headerless empty CSV: {path}")
    fieldnames = list(rows[0].keys())
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{uuid.uuid4().hex}")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(json_safe(rows))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected JSON object: {path}")
    return value


def sql_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def path_list_literal(paths: Sequence[Path]) -> str:
    if not paths:
        raise RuntimeError("Empty Parquet path list")
    return "[" + ",".join(sql_literal(p) for p in paths) + "]"


def parse_memory_bytes(value: str) -> int:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([KMGTP]?B)\s*", value.upper())
    if not match:
        raise ValueError(f"Invalid memory limit: {value}")
    number = float(match.group(1))
    powers = {"B": 0, "KB": 1, "MB": 2, "GB": 3, "TB": 4, "PB": 5}
    return int(number * (1024 ** powers[match.group(2)]))


def import_dependencies() -> tuple[Any, Any]:
    try:
        import duckdb  # type: ignore
        import pyarrow.parquet as pq  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "This program requires DuckDB 1.5.2 and PyArrow 24.0.0 in the "
            "project virtual environment"
        ) from exc
    return duckdb, pq


def dependency_versions() -> dict[str, str]:
    duckdb, pq = import_dependencies()
    import pyarrow  # type: ignore

    return {"duckdb": duckdb.__version__, "pyarrow": pyarrow.__version__}


def configure_duckdb(
    connection: Any,
    *,
    threads: int,
    memory_limit: str,
    temp_directory: Path,
) -> None:
    temp_directory.mkdir(parents=True, exist_ok=True)
    connection.execute(f"SET threads={int(threads)}")
    connection.execute(f"SET memory_limit={sql_literal(memory_limit)}")
    connection.execute(
        f"SET temp_directory={sql_literal(temp_directory.resolve())}"
    )
    connection.execute("SET preserve_insertion_order=false")


def parquet_rows(path: Path) -> int:
    _, pq = import_dependencies()
    return int(pq.ParquetFile(path).metadata.num_rows)


def parse_thresholds(value: str) -> tuple[int, ...]:
    thresholds = tuple(sorted({int(item.strip()) for item in value.split(",")}))
    if not thresholds or any(value < 2 for value in thresholds):
        raise argparse.ArgumentTypeError("Thresholds must be distinct integers >=2")
    return thresholds


def parse_manifest_path(path: str) -> tuple[str, str]:
    normalized = path.replace("\\", "/")
    match = re.search(r"(?:^|/)speed=([^/]+)/month=(\d{4}-\d{2})(?:/|$)", normalized)
    if not match:
        raise RuntimeError(f"Cannot parse speed/month from chronology path: {path}")
    return match.group(1), match.group(2)


def read_chronology_manifest(
    path: Path,
    *,
    expected_sha256: str,
    expected_chronology_games: int,
    allow_incomplete_months: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not path.is_file():
        raise RuntimeError(f"Chronology manifest is missing: {path}")
    observed_sha = sha256_file(path)
    if expected_sha256 and observed_sha != expected_sha256:
        raise RuntimeError(
            f"Chronology manifest SHA-256 changed: {observed_sha} != {expected_sha256}"
        )
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        required = {"file_index", "path", "bytes", "rows", "footer_signature_sha256"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise RuntimeError(
                f"Chronology manifest schema changed: {reader.fieldnames}; required={required}"
            )
        all_rows = [dict(row) for row in reader]

    selected: list[dict[str, Any]] = []
    unexpected: list[tuple[str, str, int]] = []
    seen_paths: set[str] = set()
    for raw in all_rows:
        speed, month = parse_manifest_path(raw["path"])
        rows = int(raw["rows"])
        if month not in MAIN_MONTHS:
            continue
        if speed not in NAMED_SPEEDS:
            if rows:
                unexpected.append((speed, month, rows))
            continue
        source_path = Path(raw["path"])
        key = str(source_path)
        if key in seen_paths:
            raise RuntimeError(f"Duplicate chronology path in manifest: {source_path}")
        seen_paths.add(key)
        selected.append(
            {
                "file_index": int(raw["file_index"]),
                "path": str(source_path),
                "bytes": int(raw["bytes"]),
                "rows": rows,
                "footer_signature_sha256": raw["footer_signature_sha256"],
                "speed": speed,
                "month": month,
            }
        )
    if unexpected:
        raise RuntimeError(
            "Rows with a non-format/unknown speed occurred inside the focal window; "
            f"do not silently pool them: {unexpected[:10]}"
        )
    selected.sort(key=lambda row: (row["month"], row["speed"], row["file_index"]))
    months = sorted({row["month"] for row in selected})
    if not allow_incomplete_months and tuple(months) != MAIN_MONTHS:
        raise RuntimeError(f"Focal chronology month coverage changed: {months}")
    if not selected:
        raise RuntimeError("No chronology inputs selected")
    total_rows = sum(int(row["rows"]) for row in selected)
    if expected_chronology_games and total_rows != expected_chronology_games:
        by_speed: dict[str, int] = {}
        for row in selected:
            by_speed[row["speed"]] = by_speed.get(row["speed"], 0) + int(row["rows"])
        raise RuntimeError(
            "The authenticated 24-month chronology row total changed: "
            f"{total_rows:,} != {expected_chronology_games:,}; by_speed={by_speed}"
        )
    for row in selected:
        source = Path(row["path"])
        if not source.is_file():
            raise RuntimeError(f"Chronology source is missing: {source}")
        if source.stat().st_size != int(row["bytes"]):
            raise RuntimeError(f"Chronology source byte size changed: {source}")
    return selected, {
        "path": str(path.resolve()),
        "sha256": observed_sha,
        "manifest_rows": len(all_rows),
        "selected_files": len(selected),
        "selected_rows": total_rows,
        "months": months,
        "speeds": sorted({row["speed"] for row in selected}),
    }


def stage07_paths(
    root: Path, *, allow_incomplete_months: bool, expected_success_sha256: str
) -> list[Path]:
    success = root / "_SUCCESS.json"
    if expected_success_sha256:
        if not success.is_file():
            raise RuntimeError(f"Stage 07 success authority is missing: {success}")
        observed = sha256_file(success)
        if observed != expected_success_sha256:
            raise RuntimeError(
                f"Stage 07 success authority changed: {observed} != "
                f"{expected_success_sha256}"
            )
    paths = sorted(root.glob("month=*/analysis_panel.parquet"))
    if not paths:
        raise RuntimeError(f"No Stage 07 monthly files found under {root}")
    months = [p.parent.name.removeprefix("month=") for p in paths]
    if not allow_incomplete_months and tuple(months) != MAIN_MONTHS:
        raise RuntimeError(f"Stage 07 month coverage changed: {months}")
    return paths


def authenticate_or_create_state_config(state: Path, payload: dict[str, Any]) -> str:
    config_sha = sha256_json(payload)
    path = state / "state_config.json"
    if path.is_file():
        saved = load_json(path)
        if saved.get("config_sha256") != config_sha or saved.get("config") != payload:
            raise RuntimeError(
                "Private checkpoint configuration differs from this run. Use a new "
                "--state-root rather than mixing censuses."
            )
        print("STATE_CONFIGURATION_AUTHENTICATED_OK", flush=True)
        return config_sha
    if state.exists() and any(state.iterdir()):
        raise RuntimeError(f"Nonempty state root has no authenticated config: {state}")
    state.mkdir(parents=True, exist_ok=True)
    atomic_json(
        path,
        {
            "status": "FREQUENT_DYAD_CENSUS_PRIVATE_CONFIG_V101",
            "created_utc": utc_now(),
            "config_sha256": config_sha,
            "privacy": "PRIVATE ACCOUNT/PAIR CHECKPOINTS; DO NOT PUBLISH",
            "config": payload,
        },
    )
    print("STATE_CONFIGURATION_CREATED", flush=True)
    return config_sha


def authenticate_single_parquet_checkpoint(
    output: Path,
    receipt: Path,
    *,
    status: str,
    config_sha256: str,
) -> dict[str, Any] | None:
    if output.is_file() and receipt.is_file():
        saved = load_json(receipt)
        observed_rows = parquet_rows(output)
        observed_bytes = output.stat().st_size
        observed_sha = sha256_file(output)
        if (
            saved.get("status") != status
            or saved.get("config_sha256") != config_sha256
            or int(saved.get("output_rows", -1)) != observed_rows
            or int(saved.get("output_bytes", -1)) != observed_bytes
            or saved.get("output_sha256") != observed_sha
        ):
            raise RuntimeError(f"Checkpoint authentication failed: {output}")
        return saved
    if output.exists() or receipt.exists():
        raise RuntimeError(f"Partial checkpoint exists: {output} / {receipt}")
    return None


def source_partial_worker(payload: dict[str, Any]) -> dict[str, Any]:
    source = Path(payload["source"]["path"])
    output = Path(payload["output"])
    receipt = Path(payload["receipt"])
    config_sha256 = payload["config_sha256"]
    status = "FREQUENT_DYAD_SOURCE_PARTIAL_PRIVATE_OK"
    existing = authenticate_single_parquet_checkpoint(
        output, receipt, status=status, config_sha256=config_sha256
    )
    if existing is not None:
        return {**existing, "resumed": True}

    duckdb, _ = import_dependencies()
    output.parent.mkdir(parents=True, exist_ok=True)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    temp_dir = Path(payload["temp_dir"])
    connection = duckdb.connect()
    try:
        configure_duckdb(
            connection,
            threads=int(payload["threads"]),
            memory_limit=payload["memory_limit"],
            temp_directory=temp_dir,
        )
        connection.execute(
            f"""
            COPY (
              WITH valid AS (
                SELECT
                  LEAST(CAST(white_id AS BIGINT), CAST(black_id AS BIGINT)) AS low_id,
                  GREATEST(CAST(white_id AS BIGINT), CAST(black_id AS BIGINT)) AS high_id
                FROM read_parquet({sql_literal(source)})
                WHERE CAST(utc_ms AS BIGINT) >= {MAIN_START_MS}
                  AND CAST(utc_ms AS BIGINT) < {MAIN_END_EXCLUSIVE_MS}
                  AND white_id IS NOT NULL AND black_id IS NOT NULL
                  AND CAST(white_id AS BIGINT) > 0 AND CAST(black_id AS BIGINT) > 0
                  AND CAST(white_id AS BIGINT) <> CAST(black_id AS BIGINT)
              ), local_counts AS (
                SELECT low_id, high_id, COUNT(*)::UBIGINT AS games_in_source
                FROM valid GROUP BY low_id, high_id
              )
              SELECT
                CAST(hash(low_id, high_id, {PAIR_HASH_SEED}) % {int(payload['buckets'])}
                     AS USMALLINT) AS pair_bucket,
                low_id, high_id, games_in_source
              FROM local_counts
              ORDER BY pair_bucket, low_id, high_id
            ) TO {sql_literal(temp_output)}
              (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
            """
        )
        qa = connection.execute(
            f"""
            SELECT COUNT(*)::UBIGINT, COALESCE(SUM(games_in_source),0)::UBIGINT,
                   MIN(pair_bucket), MAX(pair_bucket)
            FROM read_parquet({sql_literal(temp_output)})
            """
        ).fetchone()
    finally:
        connection.close()
        shutil.rmtree(temp_dir, ignore_errors=True)

    expected_rows = int(payload["source"]["rows"])
    if int(qa[1]) != expected_rows:
        raise RuntimeError(
            f"Source row conservation failed for {source}: selected={int(qa[1]):,}, "
            f"manifest={expected_rows:,}. This detects null/self/nonpositive IDs or "
            "out-of-window rows."
        )
    os.replace(temp_output, output)
    saved = {
        "status": status,
        "created_utc": utc_now(),
        "config_sha256": config_sha256,
        "source_file_index": int(payload["source"]["file_index"]),
        "source_path": str(source),
        "source_speed": payload["source"]["speed"],
        "source_month": payload["source"]["month"],
        "source_manifest_rows": expected_rows,
        "source_manifest_bytes": int(payload["source"]["bytes"]),
        "source_footer_signature_sha256": payload["source"]["footer_signature_sha256"],
        "output_path": str(output),
        "output_rows": int(qa[0]),
        "represented_games": int(qa[1]),
        "minimum_bucket": None if qa[2] is None else int(qa[2]),
        "maximum_bucket": None if qa[3] is None else int(qa[3]),
        "output_bytes": output.stat().st_size,
        "output_sha256": sha256_file(output),
        "privacy": "PRIVATE UNORDERED PLAYER PAIRS; DO NOT PUBLISH",
        "resumed": False,
    }
    atomic_json(receipt, saved)
    return saved


def bucket_worker(payload: dict[str, Any]) -> dict[str, Any]:
    bucket = int(payload["bucket"])
    output = Path(payload["output"])
    receipt = Path(payload["receipt"])
    config_sha256 = payload["config_sha256"]
    status = "FREQUENT_DYAD_EXACT_BUCKET_PRIVATE_OK"
    existing = authenticate_single_parquet_checkpoint(
        output, receipt, status=status, config_sha256=config_sha256
    )
    if existing is not None:
        if int(existing.get("bucket", -1)) != bucket:
            raise RuntimeError(f"Bucket receipt mismatch: {receipt}")
        return {**existing, "resumed": True}

    partials = [Path(value) for value in payload["partials"]]
    duckdb, _ = import_dependencies()
    output.parent.mkdir(parents=True, exist_ok=True)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    temp_dir = Path(payload["temp_dir"])
    thresholds = tuple(int(value) for value in payload["thresholds"])
    minimum = min(thresholds)
    connection = duckdb.connect()
    try:
        configure_duckdb(
            connection,
            threads=int(payload["threads"]),
            memory_limit=payload["memory_limit"],
            temp_directory=temp_dir,
        )
        connection.execute(
            f"""
            CREATE TEMP TABLE exact_pair_counts AS
            SELECT low_id, high_id,
                   SUM(games_in_source)::UBIGINT AS pair_games_24m
            FROM read_parquet({path_list_literal(partials)}, union_by_name=true)
            WHERE pair_bucket={bucket}
            GROUP BY low_id, high_id
            """
        )
        threshold_sql = ",\n".join(
            f"COUNT(*) FILTER (WHERE pair_games_24m >= {threshold})::UBIGINT AS pairs_ge_{threshold}, "
            f"COALESCE(SUM(pair_games_24m) FILTER (WHERE pair_games_24m >= {threshold}),0)::UBIGINT AS games_ge_{threshold}"
            for threshold in thresholds
        )
        qa = connection.execute(
            f"""
            SELECT COUNT(*)::UBIGINT AS pairs,
                   COALESCE(SUM(pair_games_24m),0)::UBIGINT AS games,
                   {threshold_sql},
                   COUNT(*) FILTER (WHERE pair_games_24m=1)::UBIGINT AS bin_1,
                   COUNT(*) FILTER (WHERE pair_games_24m=2)::UBIGINT AS bin_2,
                   COUNT(*) FILTER (WHERE pair_games_24m BETWEEN 3 AND 4)::UBIGINT AS bin_3_4,
                   COUNT(*) FILTER (WHERE pair_games_24m BETWEEN 5 AND 9)::UBIGINT AS bin_5_9,
                   COUNT(*) FILTER (WHERE pair_games_24m BETWEEN 10 AND 19)::UBIGINT AS bin_10_19,
                   COUNT(*) FILTER (WHERE pair_games_24m BETWEEN 20 AND 49)::UBIGINT AS bin_20_49,
                   COUNT(*) FILTER (WHERE pair_games_24m >= 50)::UBIGINT AS bin_50_plus,
                   COALESCE(MAX(pair_games_24m),0)::UBIGINT AS maximum_pair_games
            FROM exact_pair_counts
            """
        ).fetchone()
        connection.execute(
            f"""
            COPY (
              SELECT {bucket}::USMALLINT AS pair_bucket,
                     low_id, high_id, pair_games_24m
              FROM exact_pair_counts
              WHERE pair_games_24m >= {minimum}
              ORDER BY low_id, high_id
            ) TO {sql_literal(temp_output)}
              (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
            """
        )
    finally:
        connection.close()
        shutil.rmtree(temp_dir, ignore_errors=True)

    os.replace(temp_output, output)
    offset = 2
    threshold_counts: dict[str, dict[str, int]] = {}
    for threshold in thresholds:
        threshold_counts[str(threshold)] = {
            "pairs": int(qa[offset]),
            "games": int(qa[offset + 1]),
        }
        offset += 2
    bins = {
        "1": int(qa[offset]),
        "2": int(qa[offset + 1]),
        "3-4": int(qa[offset + 2]),
        "5-9": int(qa[offset + 3]),
        "10-19": int(qa[offset + 4]),
        "20-49": int(qa[offset + 5]),
        "50+": int(qa[offset + 6]),
    }
    saved = {
        "status": status,
        "created_utc": utc_now(),
        "config_sha256": config_sha256,
        "bucket": bucket,
        "all_pairs": int(qa[0]),
        "all_games": int(qa[1]),
        "threshold_counts": threshold_counts,
        "pair_bins": bins,
        "maximum_pair_games": int(qa[offset + 7]),
        "output_path": str(output),
        "output_rows": parquet_rows(output),
        "output_bytes": output.stat().st_size,
        "output_sha256": sha256_file(output),
        "privacy": "PRIVATE REPEATED UNORDERED PLAYER PAIRS; DO NOT PUBLISH",
        "resumed": False,
    }
    if saved["output_rows"] != threshold_counts[str(minimum)]["pairs"]:
        raise RuntimeError(f"Frequent-pair bucket row conservation failed: {bucket}")
    if sum(bins.values()) != saved["all_pairs"]:
        raise RuntimeError(f"Pair-frequency bin conservation failed: {bucket}")
    atomic_json(receipt, saved)
    return saved


def run_parallel_stage(
    *,
    label: str,
    worker: Any,
    payloads: Sequence[dict[str, Any]],
    max_workers: int,
) -> list[dict[str, Any]]:
    print(f"{label}_BEGIN tasks={len(payloads):,} workers={max_workers}", flush=True)
    results: list[dict[str, Any]] = []
    completed = 0
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(worker, payload): payload for payload in payloads}
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            completed += 1
            print(
                f"{label}_PROGRESS completed={completed:,}/{len(payloads):,} "
                f"resumed={bool(result.get('resumed'))}",
                flush=True,
            )
    print(f"{label}_OK", flush=True)
    return results


def build_source_partials(
    *,
    sources: Sequence[dict[str, Any]],
    state: Path,
    config_sha256: str,
    buckets: int,
    workers: int,
    threads: int,
    memory_limit: str,
) -> tuple[list[Path], list[dict[str, Any]]]:
    payloads: list[dict[str, Any]] = []
    partials: list[Path] = []
    for ordinal, source in enumerate(sources):
        stem = f"source_{ordinal:04d}_{source['speed']}_{source['month']}"
        output = state / "source_partials" / f"{stem}.parquet"
        partials.append(output)
        payloads.append(
            {
                "source": source,
                "output": str(output),
                "receipt": str(state / "source_receipts" / f"{stem}.json"),
                "temp_dir": str(state / "duckdb_temp" / "source" / stem),
                "config_sha256": config_sha256,
                "buckets": buckets,
                "threads": threads,
                "memory_limit": memory_limit,
            }
        )
    results = run_parallel_stage(
        label="SOURCE_LOCAL_PAIR_COLLAPSE",
        worker=source_partial_worker,
        payloads=payloads,
        max_workers=workers,
    )
    represented = sum(int(row["represented_games"]) for row in results)
    expected = sum(int(row["rows"]) for row in sources)
    if represented != expected:
        raise RuntimeError(f"Source-partial conservation failed: {represented} != {expected}")
    return partials, results


def build_exact_buckets(
    *,
    partials: Sequence[Path],
    state: Path,
    config_sha256: str,
    buckets: int,
    thresholds: Sequence[int],
    workers: int,
    threads: int,
    memory_limit: str,
) -> tuple[list[Path], list[dict[str, Any]]]:
    payloads: list[dict[str, Any]] = []
    outputs: list[Path] = []
    for bucket in range(buckets):
        output = (
            state
            / "frequent_pairs"
            / f"pair_bucket={bucket:03d}"
            / "part-00000.parquet"
        )
        outputs.append(output)
        payloads.append(
            {
                "bucket": bucket,
                "partials": [str(path) for path in partials],
                "output": str(output),
                "receipt": str(state / "bucket_receipts" / f"bucket_{bucket:03d}.json"),
                "temp_dir": str(state / "duckdb_temp" / "bucket" / f"bucket_{bucket:03d}"),
                "config_sha256": config_sha256,
                "thresholds": list(thresholds),
                "threads": threads,
                "memory_limit": memory_limit,
            }
        )
    results = run_parallel_stage(
        label="GLOBAL_EXACT_PAIR_REDUCTION",
        worker=bucket_worker,
        payloads=payloads,
        max_workers=workers,
    )
    results.sort(key=lambda row: int(row["bucket"]))
    return outputs, results


def build_frequent_players(
    *,
    pair_paths: Sequence[Path],
    state: Path,
    config_sha256: str,
    thresholds: Sequence[int],
    threads: int,
    memory_limit: str,
) -> tuple[Path, dict[str, Any]]:
    output = state / "frequent_players_private.parquet"
    receipt = state / "frequent_players_receipt.json"
    status = "FREQUENT_DYAD_PLAYERS_PRIVATE_OK"
    existing = authenticate_single_parquet_checkpoint(
        output, receipt, status=status, config_sha256=config_sha256
    )
    if existing is not None:
        print("FREQUENT_PLAYER_INDEX_AUTHENTICATED_OK", flush=True)
        return output, existing

    duckdb, _ = import_dependencies()
    temp_output = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    temp_dir = state / "duckdb_temp/frequent_players"
    connection = duckdb.connect()
    minimum = min(thresholds)
    try:
        configure_duckdb(
            connection,
            threads=threads,
            memory_limit=memory_limit,
            temp_directory=temp_dir,
        )
        count_columns = ",\n".join(
            f"COUNT(*) FILTER (WHERE pair_games_24m >= {threshold})::UINTEGER "
            f"AS dyads_ge_{threshold}"
            for threshold in thresholds
        )
        connection.execute(
            f"""
            COPY (
              WITH sides AS (
                SELECT low_id AS player_id, pair_games_24m
                FROM read_parquet({path_list_literal(pair_paths)}, union_by_name=true)
                UNION ALL
                SELECT high_id AS player_id, pair_games_24m
                FROM read_parquet({path_list_literal(pair_paths)}, union_by_name=true)
              )
              SELECT player_id,
                     MAX(pair_games_24m)::UBIGINT AS maximum_pair_games_24m,
                     {count_columns}
              FROM sides
              GROUP BY player_id
              HAVING MAX(pair_games_24m) >= {minimum}
              ORDER BY player_id
            ) TO {sql_literal(temp_output)}
              (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
            """
        )
        select_counts = ", ".join(
            f"COUNT(*) FILTER (WHERE maximum_pair_games_24m >= {threshold})::UBIGINT"
            for threshold in thresholds
        )
        qa = connection.execute(
            f"SELECT COUNT(*)::UBIGINT, {select_counts} "
            f"FROM read_parquet({sql_literal(temp_output)})"
        ).fetchone()
    finally:
        connection.close()
        shutil.rmtree(temp_dir, ignore_errors=True)
    os.replace(temp_output, output)
    saved = {
        "status": status,
        "created_utc": utc_now(),
        "config_sha256": config_sha256,
        "output_path": str(output),
        "output_rows": int(qa[0]),
        "players_by_threshold": {
            str(threshold): int(qa[index + 1])
            for index, threshold in enumerate(thresholds)
        },
        "output_bytes": output.stat().st_size,
        "output_sha256": sha256_file(output),
        "privacy": "PRIVATE PLAYER INDEX; DO NOT PUBLISH",
    }
    atomic_json(receipt, saved)
    print("FREQUENT_PLAYER_INDEX_CREATED", flush=True)
    return output, saved


def directory_parquets(path: Path) -> list[Path]:
    return sorted(p for p in path.rglob("*.parquet") if p.is_file())


def directory_fingerprint(path: Path) -> tuple[int, int, str]:
    files = directory_parquets(path)
    digest = hashlib.sha256()
    total_bytes = 0
    for file in files:
        relative = file.relative_to(path).as_posix()
        size = file.stat().st_size
        total_bytes += size
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(str(size).encode("ascii") + b"\0")
        digest.update(sha256_file(file).encode("ascii") + b"\n")
    return len(files), total_bytes, digest.hexdigest()


def authenticate_directory_checkpoint(
    output: Path,
    receipt: Path,
    *,
    status: str,
    config_sha256: str,
) -> dict[str, Any] | None:
    if output.is_dir() and receipt.is_file():
        saved = load_json(receipt)
        files, size, fingerprint = directory_fingerprint(output)
        if (
            saved.get("status") != status
            or saved.get("config_sha256") != config_sha256
            or int(saved.get("output_files", -1)) != files
            or int(saved.get("output_bytes", -1)) != size
            or saved.get("output_fingerprint_sha256") != fingerprint
        ):
            raise RuntimeError(f"Directory checkpoint authentication failed: {output}")
        return saved
    if output.exists() or receipt.exists():
        raise RuntimeError(f"Partial directory checkpoint exists: {output} / {receipt}")
    return None


def build_stage07_flags(
    *,
    stage_paths: Sequence[Path],
    pair_paths: Sequence[Path],
    player_path: Path,
    state: Path,
    config_sha256: str,
    thresholds: Sequence[int],
    expected_rows: int,
    threads: int,
    memory_limit: str,
) -> tuple[Path, dict[str, Any]]:
    output = state / "stage07_frequency_flags_private"
    receipt = state / "stage07_frequency_flags_receipt.json"
    status = "STAGE07_FREQUENT_DYAD_FLAGS_PRIVATE_OK"
    existing = authenticate_directory_checkpoint(
        output, receipt, status=status, config_sha256=config_sha256
    )
    if existing is not None:
        print("STAGE07_FREQUENCY_FLAGS_AUTHENTICATED_OK", flush=True)
        return output, existing

    duckdb, _ = import_dependencies()
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    temporary.mkdir(parents=True, exist_ok=False)
    temp_dir = state / "duckdb_temp/stage07_flags"
    flag_columns = ",\n".join(
        f"(COALESCE(fp.pair_games_24m,1) >= {threshold}) AS dyad_ge_{threshold},\n"
        f"(GREATEST(COALESCE(pc.maximum_pair_games_24m,1), "
        f"COALESCE(po.maximum_pair_games_24m,1)) >= {threshold}) "
        f"AS either_player_ge_{threshold}"
        for threshold in thresholds
    )
    connection = duckdb.connect()
    try:
        configure_duckdb(
            connection,
            threads=threads,
            memory_limit=memory_limit,
            temp_directory=temp_dir,
        )
        connection.execute(
            f"""
            COPY (
              WITH focal AS (
                SELECT CAST(game_id AS VARCHAR) AS game_id,
                       CAST(month AS VARCHAR) AS month,
                       CAST(chooser_user_id AS BIGINT) AS chooser_id,
                       CAST(disconnected_user_id AS BIGINT) AS opponent_id,
                       LEAST(CAST(chooser_user_id AS BIGINT),
                             CAST(disconnected_user_id AS BIGINT)) AS low_id,
                       GREATEST(CAST(chooser_user_id AS BIGINT),
                                CAST(disconnected_user_id AS BIGINT)) AS high_id
                FROM read_parquet({path_list_literal(stage_paths)}, union_by_name=true)
              )
              SELECT f.game_id, f.month,
                     COALESCE(fp.pair_games_24m,1)::UBIGINT AS pair_games_24m,
                     COALESCE(pc.maximum_pair_games_24m,1)::UBIGINT
                       AS chooser_maximum_pair_games_24m,
                     COALESCE(po.maximum_pair_games_24m,1)::UBIGINT
                       AS opponent_maximum_pair_games_24m,
                     {flag_columns}
              FROM focal f
              LEFT JOIN read_parquet({path_list_literal(pair_paths)}, union_by_name=true) fp
                ON fp.low_id=f.low_id AND fp.high_id=f.high_id
              LEFT JOIN read_parquet({sql_literal(player_path)}) pc
                ON pc.player_id=f.chooser_id
              LEFT JOIN read_parquet({sql_literal(player_path)}) po
                ON po.player_id=f.opponent_id
            ) TO {sql_literal(temporary)}
              (FORMAT PARQUET, PARTITION_BY(month), COMPRESSION ZSTD,
               ROW_GROUP_SIZE 250000)
            """
        )
        flag_paths = directory_parquets(temporary)
        measures = ", ".join(
            f"COUNT(*) FILTER (WHERE dyad_ge_{threshold})::UBIGINT, "
            f"COUNT(*) FILTER (WHERE either_player_ge_{threshold})::UBIGINT"
            for threshold in thresholds
        )
        qa = connection.execute(
            f"""
            SELECT COUNT(*)::UBIGINT, COUNT(DISTINCT game_id)::UBIGINT,
                   COUNT(*) FILTER (WHERE pair_games_24m < 1)::UBIGINT,
                   {measures}
            FROM read_parquet({path_list_literal(flag_paths)}, union_by_name=true)
            """
        ).fetchone()
    finally:
        connection.close()
        shutil.rmtree(temp_dir, ignore_errors=True)
    rows = int(qa[0])
    if rows != int(qa[1]) or int(qa[2]) != 0:
        raise RuntimeError(f"Stage 07 flag conservation failed: {qa}")
    if expected_rows and rows != expected_rows:
        raise RuntimeError(f"Stage 07 row authority changed: {rows:,} != {expected_rows:,}")
    os.replace(temporary, output)
    exclusions: dict[str, dict[str, int]] = {}
    offset = 3
    for threshold in thresholds:
        exclusions[str(threshold)] = {
            "dyad": int(qa[offset]),
            "either_player": int(qa[offset + 1]),
        }
        offset += 2
    files, size, fingerprint = directory_fingerprint(output)
    saved = {
        "status": status,
        "created_utc": utc_now(),
        "config_sha256": config_sha256,
        "rows": rows,
        "unique_games": int(qa[1]),
        "exclusions": exclusions,
        "output_path": str(output),
        "output_files": files,
        "output_bytes": size,
        "output_fingerprint_sha256": fingerprint,
        "focal_kind_outcome_read": False,
        "privacy": "PRIVATE GAME-LEVEL FLAGS; DO NOT PUBLISH",
    }
    atomic_json(receipt, saved)
    print("STAGE07_FREQUENCY_FLAGS_CREATED", flush=True)
    return output, saved


def build_c7x_flags(
    *,
    classification: Path,
    pair_paths: Sequence[Path],
    player_path: Path,
    state: Path,
    config_sha256: str,
    thresholds: Sequence[int],
    expected_rows: int,
    expected_sha256: str,
    threads: int,
    memory_limit: str,
) -> tuple[Path, dict[str, Any]]:
    if not classification.is_file():
        raise RuntimeError(f"Required C7X classification is missing: {classification}")
    observed_sha = sha256_file(classification)
    if expected_sha256 and observed_sha != expected_sha256:
        raise RuntimeError(f"C7X classification SHA-256 changed: {observed_sha}")
    output = state / "c7x_frequency_flags_private.parquet"
    receipt = state / "c7x_frequency_flags_receipt.json"
    status = "C7X_FREQUENT_DYAD_FLAGS_PRIVATE_OK"
    existing = authenticate_single_parquet_checkpoint(
        output, receipt, status=status, config_sha256=config_sha256
    )
    if existing is not None:
        if existing.get("classification_sha256") != observed_sha:
            raise RuntimeError("C7X input authentication changed")
        print("C7X_FREQUENCY_FLAGS_AUTHENTICATED_OK", flush=True)
        return output, existing

    duckdb, pq = import_dependencies()
    forbidden = {"kind", "kind_draw", "outcome_kind_draw"}.intersection(
        pq.ParquetFile(classification).schema_arrow.names
    )
    if forbidden:
        raise RuntimeError(f"C7X classification unexpectedly contains focal outcome: {forbidden}")
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    temp_dir = state / "duckdb_temp/c7x_flags"
    flag_columns = ",\n".join(
        f"(COALESCE(fp.pair_games_24m,1) >= {threshold}) AS dyad_ge_{threshold},\n"
        f"(GREATEST(COALESCE(pc.maximum_pair_games_24m,1), "
        f"COALESCE(po.maximum_pair_games_24m,1)) >= {threshold}) "
        f"AS either_player_ge_{threshold}"
        for threshold in thresholds
    )
    connection = duckdb.connect()
    try:
        configure_duckdb(
            connection,
            threads=threads,
            memory_limit=memory_limit,
            temp_directory=temp_dir,
        )
        connection.execute(
            f"""
            COPY (
              WITH focal AS (
                SELECT CAST(game_id AS VARCHAR) AS game_id,
                       CAST(chooser_id AS BIGINT) AS chooser_id,
                       CAST(opponent_id AS BIGINT) AS opponent_id,
                       LEAST(CAST(chooser_id AS BIGINT), CAST(opponent_id AS BIGINT)) AS low_id,
                       GREATEST(CAST(chooser_id AS BIGINT), CAST(opponent_id AS BIGINT)) AS high_id,
                       CAST(latest_prior_arm AS TINYINT) AS latest_prior_arm
                FROM read_parquet({sql_literal(classification)})
              )
              SELECT f.game_id, f.latest_prior_arm,
                     COALESCE(fp.pair_games_24m,1)::UBIGINT AS pair_games_24m,
                     COALESCE(pc.maximum_pair_games_24m,1)::UBIGINT
                       AS chooser_maximum_pair_games_24m,
                     COALESCE(po.maximum_pair_games_24m,1)::UBIGINT
                       AS opponent_maximum_pair_games_24m,
                     {flag_columns}
              FROM focal f
              LEFT JOIN read_parquet({path_list_literal(pair_paths)}, union_by_name=true) fp
                ON fp.low_id=f.low_id AND fp.high_id=f.high_id
              LEFT JOIN read_parquet({sql_literal(player_path)}) pc
                ON pc.player_id=f.chooser_id
              LEFT JOIN read_parquet({sql_literal(player_path)}) po
                ON po.player_id=f.opponent_id
              ORDER BY f.game_id
            ) TO {sql_literal(temporary)}
              (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)
            """
        )
        measures = ", ".join(
            f"COUNT(*) FILTER (WHERE dyad_ge_{threshold})::UBIGINT, "
            f"COUNT(*) FILTER (WHERE either_player_ge_{threshold})::UBIGINT"
            for threshold in thresholds
        )
        qa = connection.execute(
            f"""
            SELECT COUNT(*)::UBIGINT, COUNT(DISTINCT game_id)::UBIGINT,
                   COUNT(*) FILTER (WHERE latest_prior_arm NOT IN (0,1))::UBIGINT,
                   {measures}
            FROM read_parquet({sql_literal(temporary)})
            """
        ).fetchone()
        arm_rows = connection.execute(
            f"""
            SELECT latest_prior_arm, COUNT(*)::UBIGINT,
                   {measures}
            FROM read_parquet({sql_literal(temporary)})
            GROUP BY latest_prior_arm ORDER BY latest_prior_arm
            """
        ).fetchall()
    finally:
        connection.close()
        shutil.rmtree(temp_dir, ignore_errors=True)
    rows = int(qa[0])
    if rows != int(qa[1]) or int(qa[2]) != 0:
        raise RuntimeError(f"C7X flag conservation failed: {qa}")
    if expected_rows and rows != expected_rows:
        raise RuntimeError(f"C7X row authority changed: {rows:,} != {expected_rows:,}")
    os.replace(temporary, output)

    def unpack(values: Sequence[Any], first_offset: int) -> dict[str, dict[str, int]]:
        result: dict[str, dict[str, int]] = {}
        offset = first_offset
        for threshold in thresholds:
            result[str(threshold)] = {
                "dyad": int(values[offset]),
                "either_player": int(values[offset + 1]),
            }
            offset += 2
        return result

    arms = {
        ("claimer" if int(row[0]) == 0 else "benefactor"): {
            "rows": int(row[1]),
            "exclusions": unpack(row, 2),
        }
        for row in arm_rows
    }
    saved = {
        "status": status,
        "created_utc": utc_now(),
        "config_sha256": config_sha256,
        "classification_path": str(classification),
        "classification_sha256": observed_sha,
        "rows": rows,
        "unique_games": int(qa[1]),
        "exclusions": unpack(qa, 3),
        "arms": arms,
        "output_path": str(output),
        "output_rows": parquet_rows(output),
        "output_bytes": output.stat().st_size,
        "output_sha256": sha256_file(output),
        "focal_kind_outcome_read": False,
        "privacy": "PRIVATE C7X GAME-LEVEL FLAGS; DO NOT PUBLISH",
    }
    atomic_json(receipt, saved)
    print("C7X_FREQUENCY_FLAGS_CREATED", flush=True)
    return output, saved


def aggregate_pair_results(
    bucket_results: Sequence[Mapping[str, Any]],
    player_receipt: Mapping[str, Any],
    thresholds: Sequence[int],
    chronology_games: int,
    published_raw_games: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    total_pairs = sum(int(row["all_pairs"]) for row in bucket_results)
    represented_games = sum(int(row["all_games"]) for row in bucket_results)
    if represented_games != chronology_games:
        raise RuntimeError(
            f"Global pair conservation failed: {represented_games:,} != "
            f"{chronology_games:,}"
        )
    if published_raw_games < chronology_games:
        raise RuntimeError(
            "Published raw-game authority cannot be smaller than the chronology: "
            f"{published_raw_games:,} < {chronology_games:,}"
        )
    unrepresented_games = published_raw_games - chronology_games
    threshold_rows: list[dict[str, Any]] = []
    previous_pairs = total_pairs + 1
    previous_games = chronology_games + 1
    previous_players = int(player_receipt["output_rows"]) + 1
    for threshold in thresholds:
        pairs = sum(
            int(row["threshold_counts"][str(threshold)]["pairs"])
            for row in bucket_results
        )
        games = sum(
            int(row["threshold_counts"][str(threshold)]["games"])
            for row in bucket_results
        )
        players = int(player_receipt["players_by_threshold"][str(threshold)])
        if pairs > previous_pairs or games > previous_games or players > previous_players:
            raise RuntimeError("Threshold monotonicity failed")
        previous_pairs, previous_games, previous_players = pairs, games, players
        threshold_rows.append(
            {
                "threshold_games_per_unordered_pair": threshold,
                "unordered_pairs_at_or_above": pairs,
                "games_in_pairs_at_or_above": games,
                "share_of_chronology_games_pct": 100.0 * games / chronology_games,
                "lower_bound_share_of_published_games_pct": (
                    100.0 * games / published_raw_games
                ),
                "upper_bound_share_of_published_games_pct": (
                    100.0
                    * min(
                        published_raw_games,
                        games + threshold * unrepresented_games,
                    )
                    / published_raw_games
                ),
                "players_in_any_pair_at_or_above": players,
            }
        )
    labels = ("1", "2", "3-4", "5-9", "10-19", "20-49", "50+")
    histogram_rows = [
        {
            "pair_game_count_bin": label,
            "unordered_pairs": sum(int(row["pair_bins"][label]) for row in bucket_results),
        }
        for label in labels
    ]
    if sum(int(row["unordered_pairs"]) for row in histogram_rows) != total_pairs:
        raise RuntimeError("Global pair histogram conservation failed")
    summary = {
        "all_unordered_pairs": total_pairs,
        "authenticated_chronology_games": chronology_games,
        "published_standard_rated_archive_games": published_raw_games,
        "published_games_not_represented_in_chronology": unrepresented_games,
        "chronology_coverage_pct": 100.0 * chronology_games / published_raw_games,
        "maximum_pair_games_24m": max(
            int(row["maximum_pair_games"]) for row in bucket_results
        ),
    }
    return threshold_rows, histogram_rows, summary


def make_attrition_rows(
    *,
    sample: str,
    total: int,
    exclusions: Mapping[str, Mapping[str, int]],
    thresholds: Sequence[int],
    subgroup: str = "all",
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for threshold in thresholds:
        for rule, description in (
            ("dyad", "drop only games between a pair meeting the threshold"),
            (
                "either_player",
                "drop every game involving either member of any pair meeting the threshold",
            ),
        ):
            excluded = int(exclusions[str(threshold)][rule])
            if not (0 <= excluded <= total):
                raise RuntimeError(f"Invalid attrition count for {sample}: {excluded}/{total}")
            rows.append(
                {
                    "sample": sample,
                    "subgroup": subgroup,
                    "threshold_games_per_unordered_pair": threshold,
                    "exclusion_rule": rule,
                    "rule_description": description,
                    "total_rows_before": total,
                    "rows_excluded": excluded,
                    "share_excluded_pct": 100.0 * excluded / total if total else 0.0,
                    "rows_retained": total - excluded,
                    "share_retained_pct": 100.0 * (total - excluded) / total if total else 0.0,
                }
            )
    return rows


def public_file_manifest(root: Path) -> list[dict[str, Any]]:
    excluded = {"file_manifest.tsv", "_SUCCESS.json"}
    rows = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative in excluded:
            continue
        rows.append(
            {"file": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path)}
        )
    return rows


def write_public_output(
    *,
    final: Path,
    run_id: str,
    config: Mapping[str, Any],
    config_sha256: str,
    chronology_auth: Mapping[str, Any],
    sources: Sequence[Mapping[str, Any]],
    threshold_rows: Sequence[Mapping[str, Any]],
    histogram_rows: Sequence[Mapping[str, Any]],
    pair_summary: Mapping[str, Any],
    stage_receipt: Mapping[str, Any],
    c7x_receipt: Mapping[str, Any] | None,
    source_results: Sequence[Mapping[str, Any]],
    bucket_results: Sequence[Mapping[str, Any]],
    player_receipt: Mapping[str, Any],
    elapsed_seconds: float,
) -> None:
    staging = final.with_name("." + final.name + f".tmp.{uuid.uuid4().hex}")
    staging.mkdir(parents=True, exist_ok=False)
    try:
        speed_totals: dict[str, dict[str, int]] = {}
        for source in sources:
            row = speed_totals.setdefault(source["speed"], {"files": 0, "games": 0})
            row["files"] += 1
            row["games"] += int(source["rows"])
        games_by_speed = [
            {
                "speed": speed,
                "source_files": speed_totals[speed]["files"],
                "games": speed_totals[speed]["games"],
                "share_of_chronology_games_pct": 100.0
                * speed_totals[speed]["games"]
                / int(pair_summary["authenticated_chronology_games"]),
            }
            for speed in NAMED_SPEEDS
            if speed in speed_totals
        ]
        denominator_rows = [
            {
                "published_standard_rated_archive_games": int(
                    pair_summary["published_standard_rated_archive_games"]
                ),
                "authenticated_chronology_games": int(
                    pair_summary["authenticated_chronology_games"]
                ),
                "published_games_not_represented_in_chronology": int(
                    pair_summary["published_games_not_represented_in_chronology"]
                ),
                "chronology_coverage_pct": float(
                    pair_summary["chronology_coverage_pct"]
                ),
                "unrepresented_share_of_published_games_pct": (
                    100.0
                    * int(pair_summary["published_games_not_represented_in_chronology"])
                    / int(pair_summary["published_standard_rated_archive_games"])
                ),
            }
        ]
        stage_rows = make_attrition_rows(
            sample="Stage07 opportunities",
            total=int(stage_receipt["rows"]),
            exclusions=stage_receipt["exclusions"],
            thresholds=config["thresholds"],
        )
        c7x_rows: list[dict[str, Any]] = []
        if c7x_receipt is not None:
            c7x_rows.extend(
                make_attrition_rows(
                    sample="C7X classified opportunities",
                    total=int(c7x_receipt["rows"]),
                    exclusions=c7x_receipt["exclusions"],
                    thresholds=config["thresholds"],
                )
            )
            for arm in ("benefactor", "claimer"):
                arm_payload = c7x_receipt["arms"].get(arm)
                if arm_payload:
                    c7x_rows.extend(
                        make_attrition_rows(
                            sample="C7X classified opportunities",
                            subgroup=arm,
                            total=int(arm_payload["rows"]),
                            exclusions=arm_payload["exclusions"],
                            thresholds=config["thresholds"],
                        )
                    )

        write_csv(staging / "pair_threshold_census.csv", list(threshold_rows))
        write_csv(staging / "pair_frequency_histogram.csv", list(histogram_rows))
        write_csv(staging / "games_by_speed.csv", games_by_speed)
        write_csv(staging / "denominator_reconciliation.csv", denominator_rows)
        write_csv(staging / "stage07_attrition.csv", stage_rows)
        if c7x_rows:
            write_csv(staging / "c7x_attrition.csv", c7x_rows)

        resumed_sources = sum(bool(row.get("resumed")) for row in source_results)
        resumed_buckets = sum(bool(row.get("resumed")) for row in bucket_results)
        input_auth = {
            "status": "FREQUENT_DYAD_INPUTS_AUTHENTICATED_OK",
            "chronology_manifest": chronology_auth,
            "denominators": denominator_rows[0],
            "stage07": {
                "paths": len(config["stage07_files"]),
                "rows": int(stage_receipt["rows"]),
            },
            "c7x": None
            if c7x_receipt is None
            else {
                "path": c7x_receipt["classification_path"],
                "sha256": c7x_receipt["classification_sha256"],
                "rows": int(c7x_receipt["rows"]),
            },
            "focal_kind_outcome_read": False,
        }
        qa = {
            "status": "FREQUENT_DYAD_CENSUS_QA_OK",
            "chronology_row_conservation": int(
                pair_summary["authenticated_chronology_games"]
            )
            == int(chronology_auth["selected_rows"]),
            "published_denominator_reconciliation": int(
                pair_summary["authenticated_chronology_games"]
            )
            + int(pair_summary["published_games_not_represented_in_chronology"])
            == int(pair_summary["published_standard_rated_archive_games"]),
            "published_share_bounds_valid": all(
                0.0
                <= float(row["lower_bound_share_of_published_games_pct"])
                <= float(row["upper_bound_share_of_published_games_pct"])
                <= 100.0
                for row in threshold_rows
            ),
            "stage07_unique_game_conservation": int(stage_receipt["rows"])
            == int(stage_receipt["unique_games"]),
            "c7x_unique_game_conservation": c7x_receipt is None
            or int(c7x_receipt["rows"]) == int(c7x_receipt["unique_games"]),
            "pair_histogram_conservation": sum(
                int(row["unordered_pairs"]) for row in histogram_rows
            )
            == int(pair_summary["all_unordered_pairs"]),
            "threshold_monotonicity": all(
                int(threshold_rows[index]["games_in_pairs_at_or_above"])
                >= int(threshold_rows[index + 1]["games_in_pairs_at_or_above"])
                for index in range(len(threshold_rows) - 1)
            ),
            "public_outputs_identifier_free": True,
            "focal_kind_outcome_read": False,
        }
        qa_passes = [
            value
            for key, value in qa.items()
            if isinstance(value, bool) and key != "focal_kind_outcome_read"
        ]
        if not all(qa_passes) or qa["focal_kind_outcome_read"] is not False:
            raise RuntimeError(f"Public QA failed: {qa}")
        summary = {
            "status": STATUS,
            "created_utc": utc_now(),
            "run_id": run_id,
            "script_version": SCRIPT_VERSION,
            "config_sha256": config_sha256,
            "window": {"start": "2023-11-01", "end_inclusive": "2025-10-31"},
            "scope": (
                "authenticated standard-rated chronology; all named time formats "
                "pooled, with published-archive prevalence bounds"
            ),
            "denominator_note": (
                "Exact pair classification covers the authenticated chronology. "
                "The published-archive lower bound assigns no chronology-"
                "unrepresented game to a qualifying dyad. The conservative upper "
                "bound allows each such game to count itself and to push as many as "
                "threshold-minus-one chronology games in its pair across the "
                "threshold, capped at the published total."
            ),
            "friendship_measurement_note": (
                "Repeated matching is a proxy for familiarity, not a direct friendship measure."
            ),
            "timing_note": (
                "The requested whole-window count can include rematches after a focal game; "
                "it is a descriptive sensitivity, not a pre-treatment restriction."
            ),
            "recommended_primary_sensitivity": "dyad",
            "account_wide_sensitivity_warning": (
                "The either-player rule removes unrelated opponents too and is deliberately aggressive."
            ),
            "pair_census": pair_summary,
            "thresholds": list(threshold_rows),
            "stage07_attrition": stage_rows,
            "c7x_attrition": c7x_rows,
            "checkpoint_resume": {
                "source_tasks_resumed": resumed_sources,
                "source_tasks_total": len(source_results),
                "bucket_tasks_resumed": resumed_buckets,
                "bucket_tasks_total": len(bucket_results),
            },
            "private_artifacts": {
                "frequent_pairs": config["private_paths"]["frequent_pairs"],
                "frequent_players": player_receipt["output_path"],
                "stage07_flags": stage_receipt["output_path"],
                "c7x_flags": None if c7x_receipt is None else c7x_receipt["output_path"],
            },
            "elapsed_seconds": elapsed_seconds,
            "focal_kind_outcome_read": False,
        }
        atomic_json(staging / "run_config.json", dict(config))
        atomic_json(staging / "input_authentication.json", input_auth)
        atomic_json(staging / "qa.json", qa)
        atomic_json(staging / "summary.json", summary)
        readme = f"""# Exact frequent-dyad census ({run_id})

Status: `{STATUS}`

This run counts unordered player pairs over every authenticated standard-rated
chronology game from 2023-11-01 through 2025-10-31, pooling ultrabullet,
bullet, blitz, rapid, classical, and correspondence. The chronology contains
{int(pair_summary['authenticated_chronology_games']):,} games, or
{float(pair_summary['chronology_coverage_pct']):.6f}% of the published monthly
archive total of {int(pair_summary['published_standard_rated_archive_games']):,}.
No kindness outcome was read while constructing pair-frequency or exclusion
flags.

The exact frequent-pair share is reported for chronology games. For the
published archive denominator, the lower bound lets none of the
{int(pair_summary['published_games_not_represented_in_chronology']):,}
chronology-unrepresented games qualify. The conservative upper bound also
allows each unrepresented game to push up to threshold-minus-one already-seen
games in its pair across the threshold, capped at the published total. The
report does not guess why downstream chronology rows are absent or how they
classify.

## Which exclusion is defensible?

`dyad` drops only an observation in which the two players themselves met at
least the threshold number of times. This is the clean, targeted robustness
check for the concern that repeat/friend-like pairs drive the finding.

`either_player` drops every observation involving anyone who belonged to any
frequent dyad. It also discards those players' games against unrelated people,
so it is intentionally much more aggressive and should be reported as a bound,
not the default specification.

Thresholds are whole-window counts across all time controls. Repeated matching
is evidence of familiarity, not proof of offline or platform friendship.
For focal games before the end of the window, the count can include later
rematches; this is therefore a descriptive sensitivity rather than a
pre-treatment restriction.

## Files

- `pair_threshold_census.csv`: exact chronology prevalence plus conservative
  published-archive game-share bounds at each threshold.
- `pair_frequency_histogram.csv`: exact-dyad count distribution in broad bins.
- `games_by_speed.csv`: chronology denominator audit by time format.
- `denominator_reconciliation.csv`: published and chronology authorities,
  coverage, and the unrepresented remainder.
- `stage07_attrition.csv`: opportunity loss under dyad and either-player rules.
- `c7x_attrition.csv`: outcome-blind C7X support loss overall and by prior arm.
- `summary.json`: machine-readable combined report.
- `input_authentication.json`, `run_config.json`, `qa.json`: provenance and gates.

The row-level pair/player/game flags are intentionally retained only under the
private derived-state root listed in `summary.json`; they are not copied into
this aggregate report.
"""
        atomic_text(staging / "README_results.md", readme)
        manifest_rows = public_file_manifest(staging)
        manifest_text = "file\tbytes\tsha256\n" + "".join(
            f"{row['file']}\t{row['bytes']}\t{row['sha256']}\n"
            for row in manifest_rows
        )
        atomic_text(staging / "file_manifest.tsv", manifest_text)
        atomic_json(
            staging / "_SUCCESS.json",
            {
                "status": STATUS,
                "created_utc": utc_now(),
                "run_id": run_id,
                "config_sha256": config_sha256,
                "report_manifest_sha256": sha256_file(staging / "file_manifest.tsv"),
                "focal_kind_outcome_read": False,
            },
        )
        final.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, final)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def execute(args: argparse.Namespace) -> Path:
    started = time.time()
    project = args.project_root.resolve()
    manifest = args.chronology_manifest.resolve()
    stage_root = (args.stage07_root or project / STAGE07_RELATIVE).resolve()
    c7x_path = (args.c7x_classification or project / C7X_RELATIVE).resolve()
    state = (args.state_root or project / PRIVATE_STATE_RELATIVE).resolve()
    output_root = (args.output_root or project / PUBLIC_OUTPUT_RELATIVE).resolve()
    run_id = args.run_id or utc_run_id()
    final = output_root / run_id
    if final.exists():
        raise RuntimeError(f"Public run already exists: {final}")

    versions = dependency_versions()
    if versions != {"duckdb": "1.5.2", "pyarrow": "24.0.0"}:
        raise RuntimeError(f"Dependency authority changed: {versions}")
    thresholds = args.thresholds
    if args.buckets < 2 or args.buckets > 4096:
        raise RuntimeError("--buckets must be in [2, 4096]")
    for value in (args.source_workers, args.bucket_workers, args.source_threads, args.bucket_threads, args.final_threads):
        if value < 1:
            raise RuntimeError("Worker/thread counts must be positive")
    projected_memory = max(
        args.source_workers * parse_memory_bytes(args.worker_memory_limit),
        args.bucket_workers * parse_memory_bytes(args.worker_memory_limit),
        parse_memory_bytes(args.final_memory_limit),
    )
    print(
        f"CONCURRENCY_PLAN source_workers={args.source_workers} "
        f"bucket_workers={args.bucket_workers} projected_memory_gib="
        f"{projected_memory / 1024**3:.1f}",
        flush=True,
    )

    sources, chronology_auth = read_chronology_manifest(
        manifest,
        expected_sha256=args.manifest_sha256,
        expected_chronology_games=args.expected_chronology_games,
        allow_incomplete_months=args.allow_incomplete_months,
    )
    stage_paths = stage07_paths(
        stage_root,
        allow_incomplete_months=args.allow_incomplete_months,
        expected_success_sha256=args.stage07_success_sha256,
    )
    if not args.skip_c7x and not c7x_path.is_file():
        raise RuntimeError(
            f"C7X classification missing at {c7x_path}. Use --skip-c7x only if "
            "you deliberately want the census without the quoted C7X support audit."
        )
    free_bytes = shutil.disk_usage(state.parent if state.parent.exists() else project).free
    required_free = int(args.minimum_free_gib * 1024**3)
    if free_bytes < required_free:
        raise RuntimeError(
            f"Only {free_bytes / 1024**3:.1f} GiB free; this exact census requires "
            f"at least {args.minimum_free_gib:.1f} GiB."
        )

    script_path = Path(__file__).resolve()
    source_fingerprints = [
        {
            "file_index": row["file_index"],
            "path": row["path"],
            "bytes": row["bytes"],
            "rows": row["rows"],
            "footer_signature_sha256": row["footer_signature_sha256"],
            "speed": row["speed"],
            "month": row["month"],
        }
        for row in sources
    ]
    config = {
        "status": "FREQUENT_DYAD_CENSUS_CONFIGURATION_V101",
        "script_version": SCRIPT_VERSION,
        "script_sha256": sha256_file(script_path),
        "dependencies": versions,
        "date_window": {
            "start_ms": MAIN_START_MS,
            "end_exclusive_ms": MAIN_END_EXCLUSIVE_MS,
            "months": list(MAIN_MONTHS),
        },
        "speeds_pooled": list(NAMED_SPEEDS),
        "unknown_speed_policy": "fail if any in-window rows",
        "unordered_pair_definition": "least(player_id), greatest(player_id)",
        "pair_hash_seed": PAIR_HASH_SEED,
        "buckets": args.buckets,
        "thresholds": list(thresholds),
        "expected_chronology_games": args.expected_chronology_games,
        "published_raw_games": args.published_raw_games,
        "expected_stage07_rows": args.expected_stage07_rows,
        "chronology_manifest": chronology_auth,
        "chronology_sources": source_fingerprints,
        "stage07_files": [str(path) for path in stage_paths],
        "stage07_success_sha256": args.stage07_success_sha256,
        "c7x_path": None if args.skip_c7x else str(c7x_path),
        "c7x_expected_sha256": "" if args.skip_c7x else args.c7x_sha256,
        "c7x_expected_rows": 0 if args.skip_c7x else args.expected_c7x_rows,
        "resource_plan": {
            "source_workers": args.source_workers,
            "bucket_workers": args.bucket_workers,
            "source_threads": args.source_threads,
            "bucket_threads": args.bucket_threads,
            "worker_memory_limit": args.worker_memory_limit,
            "final_threads": args.final_threads,
            "final_memory_limit": args.final_memory_limit,
        },
        "privacy": "pair, player, and game identifiers remain private",
        "outcome_blinding": "no focal kindness outcome columns read",
        "private_paths": {
            "state_root": str(state),
            "frequent_pairs": str(state / "frequent_pairs"),
        },
    }
    config_sha256 = authenticate_or_create_state_config(state, config)
    print(
        f"INPUT_AUTHENTICATION_OK files={len(sources):,} games="
        f"{chronology_auth['selected_rows']:,} stage07_files={len(stage_paths)}",
        flush=True,
    )

    partials, source_results = build_source_partials(
        sources=sources,
        state=state,
        config_sha256=config_sha256,
        buckets=args.buckets,
        workers=args.source_workers,
        threads=args.source_threads,
        memory_limit=args.worker_memory_limit,
    )
    pair_paths, bucket_results = build_exact_buckets(
        partials=partials,
        state=state,
        config_sha256=config_sha256,
        buckets=args.buckets,
        thresholds=thresholds,
        workers=args.bucket_workers,
        threads=args.bucket_threads,
        memory_limit=args.worker_memory_limit,
    )
    player_path, player_receipt = build_frequent_players(
        pair_paths=pair_paths,
        state=state,
        config_sha256=config_sha256,
        thresholds=thresholds,
        threads=args.final_threads,
        memory_limit=args.final_memory_limit,
    )
    _, stage_receipt = build_stage07_flags(
        stage_paths=stage_paths,
        pair_paths=pair_paths,
        player_path=player_path,
        state=state,
        config_sha256=config_sha256,
        thresholds=thresholds,
        expected_rows=args.expected_stage07_rows,
        threads=args.final_threads,
        memory_limit=args.final_memory_limit,
    )
    c7x_receipt: dict[str, Any] | None = None
    if not args.skip_c7x:
        _, c7x_receipt = build_c7x_flags(
            classification=c7x_path,
            pair_paths=pair_paths,
            player_path=player_path,
            state=state,
            config_sha256=config_sha256,
            thresholds=thresholds,
            expected_rows=args.expected_c7x_rows,
            expected_sha256=args.c7x_sha256,
            threads=args.final_threads,
            memory_limit=args.final_memory_limit,
        )

    threshold_rows, histogram_rows, pair_summary = aggregate_pair_results(
        bucket_results,
        player_receipt,
        thresholds,
        int(chronology_auth["selected_rows"]),
        args.published_raw_games,
    )
    elapsed = time.time() - started
    write_public_output(
        final=final,
        run_id=run_id,
        config=config,
        config_sha256=config_sha256,
        chronology_auth=chronology_auth,
        sources=sources,
        threshold_rows=threshold_rows,
        histogram_rows=histogram_rows,
        pair_summary=pair_summary,
        stage_receipt=stage_receipt,
        c7x_receipt=c7x_receipt,
        source_results=source_results,
        bucket_results=bucket_results,
        player_receipt=player_receipt,
        elapsed_seconds=elapsed,
    )
    pointer = {
        "status": STATUS,
        "created_utc": utc_now(),
        "run_id": run_id,
        "output_dir": str(final),
        "success_sha256": sha256_file(final / "_SUCCESS.json"),
        "summary_sha256": sha256_file(final / "summary.json"),
        "config_sha256": config_sha256,
    }
    atomic_json(output_root / "latest_execution.json", pointer)
    if args.execution_pointer:
        atomic_json(args.execution_pointer.resolve(), pointer)
    print(f"{STATUS}: {final}", flush=True)
    return final


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Exact 24-month unordered-pair census and outcome-blind attrition audit"
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--project-root", type=Path, default=PROJECT_AUTHORITY)
    parser.add_argument(
        "--chronology-manifest", type=Path, default=CHRONOLOGY_MANIFEST_AUTHORITY
    )
    parser.add_argument("--manifest-sha256", default=CHRONOLOGY_MANIFEST_SHA256)
    parser.add_argument("--stage07-root", type=Path)
    parser.add_argument(
        "--stage07-success-sha256", default=EXPECTED_STAGE07_SUCCESS_SHA256
    )
    parser.add_argument("--c7x-classification", type=Path)
    parser.add_argument("--c7x-sha256", default=EXPECTED_C7X_SHA256)
    parser.add_argument("--state-root", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--execution-pointer", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--thresholds", type=parse_thresholds, default=DEFAULT_THRESHOLDS)
    parser.add_argument("--buckets", type=int, default=128)
    parser.add_argument("--source-workers", type=int, default=4)
    parser.add_argument("--bucket-workers", type=int, default=4)
    parser.add_argument("--source-threads", type=int, default=2)
    parser.add_argument("--bucket-threads", type=int, default=2)
    parser.add_argument("--worker-memory-limit", default="4GB")
    parser.add_argument("--final-threads", type=int, default=8)
    parser.add_argument("--final-memory-limit", default="20GB")
    parser.add_argument("--minimum-free-gib", type=float, default=100.0)
    parser.add_argument(
        "--expected-chronology-games", type=int, default=EXPECTED_CHRONOLOGY_GAMES
    )
    parser.add_argument(
        "--published-raw-games", type=int, default=PUBLISHED_RAW_GAMES
    )
    parser.add_argument(
        "--expected-stage07-rows", type=int, default=EXPECTED_STAGE07_ROWS
    )
    parser.add_argument("--expected-c7x-rows", type=int, default=EXPECTED_C7X_ROWS)
    parser.add_argument("--skip-c7x", action="store_true")
    parser.add_argument("--allow-incomplete-months", action="store_true")
    args = parser.parse_args(argv)
    if not args.execute:
        parser.error("Pass --execute after reviewing the package README")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        execute(args)
        return 0
    except BaseException as exc:
        print(f"FREQUENT_DYAD_CENSUS_FAILED: {exc}", file=sys.stderr, flush=True)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
