#!/usr/bin/env python3
from __future__ import annotations

"""Canonical Stage 04: enrich Lichess timeout candidates via the bulk API.

This stage is deliberately conservative because it can run continuously for
many days.  Its main guarantees are:

* The two supported laptop piles are contiguous, non-overlapping month blocks.
* Only one HTTP request is in flight per process, with at most 300 game IDs.
* HTTP 429 always causes a wait of at least 60 seconds before another request.
* Work is divided into deterministic atomic units (30,000 IDs by default).
* A completed unit is never requested again unless one of its hashed artifacts
  has been changed or removed.
* Every full API JSON object is retained in compressed NDJSON, while a compact,
  typed Parquet keeps the fields needed downstream, including both players'
  optional ratingDiff values.
* A month is marked complete only after counts and every unit checkpoint pass.

The API can legitimately omit games or ratingDiff values.  Missing API games
are retained in a separate Parquet.  Missing ratingDiff is never converted to
zero: Stage 06 will reconstruct the Glicko-2 state transition and use observed
ratingDiff only as a validation field.
"""

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
import platform
import socket
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

import pyarrow as pa
import pyarrow.parquet as pq
import requests
import zstandard as zstd


STAGE = "04_enrich_timeout_candidates"
API_URL = "https://lichess.org/api/games/export/_ids"
LOCKED_SAMPLE_START = "2023-11-01"
LOCKED_SAMPLE_END = "2025-10-31"

# Whole, contiguous month blocks.  The early block is only 0.48% larger.
PILE_MONTHS: dict[str, tuple[str, ...]] = {
    "home": ("2024-10", "2024-11", "2024-12", "2025-01", "2025-02"),
    "office": ("2025-03", "2025-04", "2025-05", "2025-06", "2025-07"),
}
BRIDGE_MONTHS = PILE_MONTHS["home"] + PILE_MONTHS["office"]

# Locked against the canonical Stage 01 _SUCCESS records.  A mismatch stops the
# job before it makes an API request.
EXPECTED_TARGET_ROWS: dict[str, int] = {
    "2024-10": 7_280_463,
    "2024-11": 6_920_848,
    "2024-12": 7_327_917,
    "2025-01": 7_499_540,
    "2025-02": 6_780_461,
    "2025-03": 7_371_390,
    "2025-04": 7_007_508,
    "2025-05": 7_209_483,
    "2025-06": 6_937_046,
    "2025-07": 7_111_923,
}

COMPACT_SCHEMA = pa.schema(
    [
        pa.field("month", pa.string(), nullable=False),
        pa.field("request_ordinal", pa.int64(), nullable=False),
        pa.field("game_id", pa.string(), nullable=False),
        pa.field("api_target", pa.bool_(), nullable=False),
        pa.field("pgn_timeforfeit_candidate", pa.bool_(), nullable=False),
        pa.field("api_status", pa.string()),
        pa.field("winner", pa.string()),
        pa.field("is_draw", pa.bool_()),
        pa.field("speed", pa.string()),
        pa.field("perf", pa.string()),
        pa.field("rated", pa.bool_()),
        pa.field("variant", pa.string()),
        pa.field("created_at_ms", pa.int64()),
        pa.field("last_move_at_ms", pa.int64()),
        pa.field("white_username", pa.string()),
        pa.field("white_username_norm", pa.string()),
        pa.field("white_rating", pa.int32()),
        pa.field("white_rating_diff", pa.int32()),
        pa.field("black_username", pa.string()),
        pa.field("black_username_norm", pa.string()),
        pa.field("black_rating", pa.int32()),
        pa.field("black_rating_diff", pa.int32()),
        pa.field("retrieved_utc", pa.string(), nullable=False),
        pa.field("unit_index", pa.int32(), nullable=False),
    ]
)

MISSING_SCHEMA = pa.schema(
    [
        pa.field("month", pa.string(), nullable=False),
        pa.field("request_ordinal", pa.int64(), nullable=False),
        pa.field("game_id", pa.string(), nullable=False),
        pa.field("api_target", pa.bool_(), nullable=False),
        pa.field("reason", pa.string(), nullable=False),
        pa.field("unit_index", pa.int32(), nullable=False),
    ]
)

REQUEST_SCHEMA = pa.schema(
    [
        pa.field("request_ordinal", pa.int64(), nullable=False),
        pa.field("game_id", pa.string(), nullable=False),
    ]
)

DRAW_STATUSES = {"draw", "stalemate", "repetition", "insufficient", "fiftyMoves"}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".partial-{os.getpid()}")
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_bytes(path, json_bytes(value))


def sha256_file(path: Path, block_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(block_size):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_ordered_ids(ids: Iterable[str]) -> str:
    """Hash an ordered ID stream without ambiguous string concatenation."""
    digest = hashlib.sha256()
    for game_id in ids:
        encoded = game_id.encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def chunks(values: Sequence[str], size: int) -> Iterator[list[str]]:
    for start in range(0, len(values), size):
        yield list(values[start : start + size])


def normalized_username(value: str | None) -> str | None:
    return value.casefold() if value else None


def optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def player_username(player: Any) -> str | None:
    if not isinstance(player, dict):
        return None
    user = player.get("user")
    if isinstance(user, dict):
        value = user.get("name") or user.get("id")
    else:
        value = player.get("name")
    return str(value) if value not in (None, "") else None


def variant_key(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("key") or value.get("name")
    return str(value) if value not in (None, "") else None


def compact_game(
    game: dict[str, Any],
    month: str,
    request_ordinal: int,
    retrieved_utc: str,
    unit_index: int,
) -> dict[str, Any]:
    players = game.get("players") if isinstance(game.get("players"), dict) else {}
    white = players.get("white") if isinstance(players.get("white"), dict) else {}
    black = players.get("black") if isinstance(players.get("black"), dict) else {}
    status = game.get("status")
    winner = game.get("winner")
    white_name = player_username(white)
    black_name = player_username(black)
    return {
        "month": month,
        "request_ordinal": request_ordinal,
        "game_id": str(game.get("id")),
        "api_target": True,
        "pgn_timeforfeit_candidate": True,
        "api_status": str(status) if status not in (None, "") else None,
        "winner": str(winner) if winner not in (None, "") else None,
        "is_draw": bool(status in DRAW_STATUSES) if status is not None else None,
        "speed": str(game.get("speed")) if game.get("speed") not in (None, "") else None,
        "perf": str(game.get("perf")) if game.get("perf") not in (None, "") else None,
        "rated": game.get("rated") if isinstance(game.get("rated"), bool) else None,
        "variant": variant_key(game.get("variant")),
        "created_at_ms": optional_int(game.get("createdAt")),
        "last_move_at_ms": optional_int(game.get("lastMoveAt")),
        "white_username": white_name,
        "white_username_norm": normalized_username(white_name),
        "white_rating": optional_int(white.get("rating")),
        "white_rating_diff": optional_int(white.get("ratingDiff")),
        "black_username": black_name,
        "black_username_norm": normalized_username(black_name),
        "black_rating": optional_int(black.get("rating")),
        "black_rating_diff": optional_int(black.get("ratingDiff")),
        "retrieved_utc": retrieved_utc,
        "unit_index": unit_index,
    }


def resolve_months(pile: str | None, explicit: list[str] | None) -> list[str]:
    if explicit:
        invalid = [month for month in explicit if month not in BRIDGE_MONTHS]
        if invalid:
            raise SystemExit(f"unsupported bridge month(s): {', '.join(invalid)}")
        if len(set(explicit)) != len(explicit):
            raise SystemExit("--months contains duplicates")
        return explicit
    if pile == "all":
        return list(BRIDGE_MONTHS)
    if pile in PILE_MONTHS:
        return list(PILE_MONTHS[pile])
    raise SystemExit("choose --pile home, --pile office, --pile all, or provide --months")


def locate_target_parquet(input_root: Path, month: str) -> Path:
    month_dir = input_root / f"month={month}"
    canonical = month_dir / "api_target_game_ids.parquet"
    if canonical.is_file():
        return canonical
    matches = sorted(month_dir.glob("*api*target*.parquet"))
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise FileNotFoundError(f"no API-target Parquet found under {month_dir}")
    raise RuntimeError(f"ambiguous API-target Parquets under {month_dir}: {matches}")


def identify_id_column(path: Path) -> str:
    names = pq.ParquetFile(path).schema_arrow.names
    for candidate in ("game_id", "id"):
        if candidate in names:
            return candidate
    raise RuntimeError(f"{path} has no game_id or id column; columns={names}")


def parquet_rows(path: Path) -> int:
    metadata = pq.ParquetFile(path).metadata
    return int(metadata.num_rows)


def selected_source_ids(path: Path, id_column: str, limit: int | None) -> Iterator[str]:
    emitted = 0
    parquet = pq.ParquetFile(path)
    for batch in parquet.iter_batches(batch_size=250_000, columns=[id_column]):
        for value in batch.column(0).to_pylist():
            if limit is not None and emitted >= limit:
                return
            game_id = str(value).strip() if value is not None else ""
            if not game_id:
                raise RuntimeError(f"empty game ID at selected ordinal {emitted:,} in {path}")
            yield game_id
            emitted += 1


def remove_if_present(path: Path) -> None:
    with contextlib.suppress(FileNotFoundError):
        path.unlink()


def atomic_write_parquet(path: Path, table: pa.Table, row_group_size: int = 100_000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".partial-{os.getpid()}")
    pq.write_table(
        table,
        temporary,
        compression="zstd",
        compression_level=9,
        row_group_size=row_group_size,
        use_dictionary=True,
        write_statistics=True,
    )
    os.replace(temporary, path)


def build_request_units(
    source_path: Path,
    id_column: str,
    month_dir: Path,
    month: str,
    source_rows: int,
    source_sha256: str,
    unit_size: int,
    max_games: int | None,
) -> dict[str, Any]:
    requests_dir = month_dir / "requests"
    manifest_path = month_dir / "_plan.json"
    selected_rows = min(source_rows, max_games) if max_games is not None else source_rows
    production = max_games is None

    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        locked = {
            "month": month,
            "source_path": str(source_path),
            "source_rows": source_rows,
            "source_sha256": source_sha256,
            "selected_rows": selected_rows,
            "unit_size": unit_size,
            "production": production,
        }
        mismatches = {key: (manifest.get(key), value) for key, value in locked.items() if manifest.get(key) != value}
        if mismatches:
            raise RuntimeError(f"existing month plan conflicts with this run: {mismatches}")
        for unit in manifest["units"]:
            request_path = month_dir / unit["request_relative_path"]
            if not request_path.is_file():
                raise RuntimeError(f"planned request unit is absent: {request_path}")
            if parquet_rows(request_path) != unit["rows"] or sha256_file(request_path) != unit["sha256"]:
                raise RuntimeError(f"planned request unit failed integrity verification: {request_path}")
        return manifest

    requests_dir.mkdir(parents=True, exist_ok=True)
    if any(requests_dir.iterdir()):
        raise RuntimeError(f"request directory exists without _plan.json and is not empty: {requests_dir}")

    units: list[dict[str, Any]] = []
    selected_hasher = hashlib.sha256()
    buffer_ids: list[str] = []
    buffer_ordinals: list[int] = []

    def flush_unit() -> None:
        if not buffer_ids:
            return
        unit_index = len(units)
        request_path = requests_dir / f"unit-{unit_index:05d}.parquet"
        table = pa.Table.from_arrays(
            [pa.array(buffer_ordinals, type=pa.int64()), pa.array(buffer_ids, type=pa.string())],
            schema=REQUEST_SCHEMA,
        )
        atomic_write_parquet(request_path, table, row_group_size=unit_size)
        units.append(
            {
                "unit_index": unit_index,
                "first_ordinal": buffer_ordinals[0],
                "last_ordinal": buffer_ordinals[-1],
                "rows": len(buffer_ids),
                "ordered_ids_sha256": sha256_ordered_ids(buffer_ids),
                "request_relative_path": str(request_path.relative_to(month_dir)),
                "sha256": sha256_file(request_path),
                "size_bytes": request_path.stat().st_size,
            }
        )
        buffer_ids.clear()
        buffer_ordinals.clear()

    for ordinal, game_id in enumerate(selected_source_ids(source_path, id_column, max_games)):
        encoded = game_id.encode("utf-8")
        selected_hasher.update(len(encoded).to_bytes(4, "big"))
        selected_hasher.update(encoded)
        buffer_ordinals.append(ordinal)
        buffer_ids.append(game_id)
        if len(buffer_ids) == unit_size:
            flush_unit()
    flush_unit()

    if sum(unit["rows"] for unit in units) != selected_rows:
        raise RuntimeError("request-unit row total does not equal selected source rows")

    manifest = {
        "stage": STAGE,
        "created_utc": utc_now(),
        "month": month,
        "locked_sample_start": LOCKED_SAMPLE_START,
        "locked_sample_end": LOCKED_SAMPLE_END,
        "source_path": str(source_path),
        "source_rows": source_rows,
        "source_sha256": source_sha256,
        "id_column": id_column,
        "selected_rows": selected_rows,
        "selected_ordered_ids_sha256": selected_hasher.hexdigest(),
        "unit_size": unit_size,
        "unit_count": len(units),
        "production": production,
        "units": units,
    }
    atomic_write_json(manifest_path, manifest)
    return manifest


def request_unit_paths(month_dir: Path, unit_index: int) -> dict[str, Path]:
    stem = f"unit-{unit_index:05d}"
    return {
        "compact": month_dir / "responses" / f"{stem}.parquet",
        "raw": month_dir / "raw" / f"{stem}.ndjson.zst",
        "missing": month_dir / "missing" / f"{stem}.parquet",
        "telemetry": month_dir / "telemetry" / f"{stem}.json",
        "checkpoint": month_dir / "_checkpoints" / f"{stem}.success.json",
    }


def valid_unit_checkpoint(month_dir: Path, unit: dict[str, Any]) -> bool:
    paths = request_unit_paths(month_dir, unit["unit_index"])
    checkpoint_path = paths["checkpoint"]
    if not checkpoint_path.is_file():
        return False
    try:
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if checkpoint.get("final_ok") is not True:
            return False
        if checkpoint.get("request_rows") != unit["rows"]:
            return False
        if checkpoint.get("request_ordered_ids_sha256") != unit["ordered_ids_sha256"]:
            return False
        for name in ("compact", "raw", "missing", "telemetry"):
            path = paths[name]
            recorded = checkpoint["artifacts"][name]
            if not path.is_file():
                return False
            if path.stat().st_size != recorded["size_bytes"]:
                return False
            if sha256_file(path) != recorded["sha256"]:
                return False
        if checkpoint["returned_unique_ids"] + checkpoint["missing_ids"] != unit["rows"]:
            return False
    except (KeyError, OSError, ValueError, json.JSONDecodeError):
        return False
    return True


def parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, float(value.strip()))
    except ValueError:
        return None


def fetch_batch(
    session: requests.Session,
    game_ids: list[str],
    timeout_seconds: float,
    max_retries: int,
    batch_sequence: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    params = {
        "moves": "false",
        "pgnInJson": "false",
        "clocks": "false",
        "evals": "false",
        "opening": "false",
        "accuracy": "false",
        "literate": "false",
    }
    headers = {"Accept": "application/x-ndjson", "Content-Type": "text/plain"}
    body = ",".join(game_ids).encode("utf-8")
    telemetry: list[dict[str, Any]] = []

    for attempt in range(1, max_retries + 2):
        started = time.monotonic()
        status_code: int | None = None
        try:
            response = session.post(
                API_URL,
                params=params,
                data=body,
                headers=headers,
                timeout=timeout_seconds,
            )
            status_code = response.status_code
        except requests.RequestException as error:
            elapsed = time.monotonic() - started
            wait_seconds = min(60.0, float(2 ** min(attempt - 1, 6)))
            telemetry.append(
                {
                    "batch_sequence": batch_sequence,
                    "attempt": attempt,
                    "requested_ids": len(game_ids),
                    "http_status": None,
                    "elapsed_seconds": round(elapsed, 3),
                    "outcome": "network_error",
                    "error": repr(error),
                    "wait_before_retry_seconds": wait_seconds if attempt <= max_retries else None,
                }
            )
            if attempt > max_retries:
                raise RuntimeError(f"network error after {attempt} attempts: {error}") from error
            print(f"  network error; waiting {wait_seconds:.0f}s before retry {attempt + 1}", flush=True)
            time.sleep(wait_seconds)
            continue

        elapsed = time.monotonic() - started
        if status_code == 200:
            games: list[dict[str, Any]] = []
            try:
                for line_number, raw_line in enumerate(response.text.splitlines(), start=1):
                    line = raw_line.strip()
                    if not line:
                        continue
                    parsed = json.loads(line)
                    if not isinstance(parsed, dict):
                        raise ValueError(f"NDJSON line {line_number} is not an object")
                    games.append(parsed)
            except (json.JSONDecodeError, ValueError) as error:
                telemetry.append(
                    {
                        "batch_sequence": batch_sequence,
                        "attempt": attempt,
                        "requested_ids": len(game_ids),
                        "http_status": status_code,
                        "elapsed_seconds": round(elapsed, 3),
                        "outcome": "malformed_ndjson",
                        "error": repr(error),
                        "wait_before_retry_seconds": 5.0 if attempt <= max_retries else None,
                    }
                )
                if attempt > max_retries:
                    raise RuntimeError(f"malformed NDJSON after {attempt} attempts: {error}") from error
                print("  malformed NDJSON; waiting 5s before retry", flush=True)
                time.sleep(5.0)
                continue

            telemetry.append(
                {
                    "batch_sequence": batch_sequence,
                    "attempt": attempt,
                    "requested_ids": len(game_ids),
                    "returned_objects": len(games),
                    "http_status": 200,
                    "elapsed_seconds": round(elapsed, 3),
                    "outcome": "success",
                    "wait_before_retry_seconds": None,
                }
            )
            return games, telemetry

        retryable = status_code == 429 or status_code in {500, 502, 503, 504}
        if retryable:
            retry_after = parse_retry_after(response.headers.get("Retry-After"))
            if status_code == 429:
                wait_seconds = max(60.0, retry_after or 0.0)
            elif retry_after is not None:
                wait_seconds = retry_after
            else:
                wait_seconds = min(60.0, float(2 ** min(attempt - 1, 6)))
            telemetry.append(
                {
                    "batch_sequence": batch_sequence,
                    "attempt": attempt,
                    "requested_ids": len(game_ids),
                    "http_status": status_code,
                    "elapsed_seconds": round(elapsed, 3),
                    "outcome": "retryable_http_error",
                    "response_excerpt": response.text[:500],
                    "retry_after_header": response.headers.get("Retry-After"),
                    "wait_before_retry_seconds": wait_seconds if attempt <= max_retries else None,
                }
            )
            if attempt > max_retries:
                raise RuntimeError(f"HTTP {status_code} after {attempt} attempts: {response.text[:500]}")
            print(f"  HTTP {status_code}; waiting {wait_seconds:.0f}s before retry {attempt + 1}", flush=True)
            time.sleep(wait_seconds)
            continue

        telemetry.append(
            {
                "batch_sequence": batch_sequence,
                "attempt": attempt,
                "requested_ids": len(game_ids),
                "http_status": status_code,
                "elapsed_seconds": round(elapsed, 3),
                "outcome": "fatal_http_error",
                "response_excerpt": response.text[:500],
                "wait_before_retry_seconds": None,
            }
        )
        raise RuntimeError(f"non-retryable HTTP {status_code}: {response.text[:500]}")

    raise RuntimeError("unreachable")


def run_unit(
    session: requests.Session,
    month_dir: Path,
    month: str,
    unit: dict[str, Any],
    batch_size: int,
    sleep_seconds: float,
    timeout_seconds: float,
    max_retries: int,
    missing_id_retries: int,
    zstd_level: int,
) -> dict[str, Any]:
    unit_index = int(unit["unit_index"])
    request_path = month_dir / unit["request_relative_path"]
    request_table = pq.read_table(request_path, schema=REQUEST_SCHEMA)
    ordinals = request_table.column("request_ordinal").to_pylist()
    ids = request_table.column("game_id").to_pylist()
    if len(ids) != unit["rows"] or sha256_ordered_ids(ids) != unit["ordered_ids_sha256"]:
        raise RuntimeError(f"request unit {unit_index} does not match its plan")
    if len(set(ids)) != len(ids):
        raise RuntimeError(f"duplicate game IDs inside request unit {unit_index}")

    ordinal_by_id = dict(zip(ids, ordinals, strict=True))
    requested_set = set(ids)
    records_by_id: dict[str, dict[str, Any]] = {}
    telemetry: list[dict[str, Any]] = []
    paths = request_unit_paths(month_dir, unit_index)
    for directory_key in ("compact", "raw", "missing", "telemetry", "checkpoint"):
        paths[directory_key].parent.mkdir(parents=True, exist_ok=True)
    if not paths["checkpoint"].is_file():
        for name in ("compact", "raw", "missing", "telemetry"):
            remove_if_present(paths[name])

    raw_partial = paths["raw"].with_name(paths["raw"].name + f".partial-{os.getpid()}")
    retrieved_utc = utc_now()
    batch_sequence = 0
    raw_objects_written = 0

    try:
        with raw_partial.open("wb") as raw_handle:
            compressor = zstd.ZstdCompressor(level=zstd_level, threads=0)
            with compressor.stream_writer(raw_handle, closefd=False) as compressed:
                pending = list(ids)
                for pass_index in range(missing_id_retries + 1):
                    if not pending:
                        break
                    if pass_index > 0:
                        print(f"  retrying {len(pending):,} IDs absent from prior 200 responses", flush=True)
                    for batch_ids in chunks(pending, batch_size):
                        batch_sequence += 1
                        games, attempts = fetch_batch(
                            session,
                            batch_ids,
                            timeout_seconds=timeout_seconds,
                            max_retries=max_retries,
                            batch_sequence=batch_sequence,
                        )
                        for attempt_row in attempts:
                            attempt_row["missing_pass"] = pass_index
                        telemetry.extend(attempts)

                        batch_set = set(batch_ids)
                        seen_this_response: set[str] = set()
                        for game in games:
                            game_id_value = game.get("id")
                            game_id = str(game_id_value).strip() if game_id_value is not None else ""
                            if not game_id:
                                raise RuntimeError("API returned an object without a game id")
                            if game_id not in batch_set:
                                raise RuntimeError(f"API returned unexpected ID {game_id} for this batch")
                            if game_id in seen_this_response:
                                raise RuntimeError(f"API returned duplicate ID {game_id} in one response")
                            seen_this_response.add(game_id)
                            records_by_id.setdefault(game_id, game)
                            compressed.write((json.dumps(game, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
                            raw_objects_written += 1
                        compressed.flush(zstd.FLUSH_BLOCK)
                        print(
                            f"  unit={unit_index:05d} pass={pass_index} batch={batch_sequence:,} "
                            f"requested={len(batch_ids):,} returned={len(games):,} "
                            f"unit_unique={len(records_by_id):,}/{len(ids):,}",
                            flush=True,
                        )
                        time.sleep(sleep_seconds)
                    pending = [game_id for game_id in ids if game_id not in records_by_id]
                # Exiting the stream-writer context closes the frame.  Avoid an
                # explicit FLUSH_FRAME here because a second close operation is
                # not handled consistently across zstandard package versions.
            raw_handle.flush()
            os.fsync(raw_handle.fileno())
        os.replace(raw_partial, paths["raw"])
    except BaseException:
        remove_if_present(raw_partial)
        raise

    unexpected = set(records_by_id).difference(requested_set)
    if unexpected:
        raise RuntimeError(f"unit contains unexpected returned IDs: {sorted(unexpected)[:10]}")

    compact_rows = [
        compact_game(
            records_by_id[game_id],
            month=month,
            request_ordinal=ordinal_by_id[game_id],
            retrieved_utc=retrieved_utc,
            unit_index=unit_index,
        )
        for game_id in ids
        if game_id in records_by_id
    ]
    missing_ids = [game_id for game_id in ids if game_id not in records_by_id]
    missing_rows = [
        {
            "month": month,
            "request_ordinal": ordinal_by_id[game_id],
            "game_id": game_id,
            "api_target": True,
            "reason": "not_returned_after_retries",
            "unit_index": unit_index,
        }
        for game_id in missing_ids
    ]
    compact_table = pa.Table.from_pylist(compact_rows, schema=COMPACT_SCHEMA)
    missing_table = pa.Table.from_pylist(missing_rows, schema=MISSING_SCHEMA)
    atomic_write_parquet(paths["compact"], compact_table)
    atomic_write_parquet(paths["missing"], missing_table)

    status_counts = Counter((row["api_status"] or "<missing>") for row in compact_rows)
    rated_counts = Counter(str(row["rated"]).lower() if row["rated"] is not None else "null" for row in compact_rows)
    both_rating_diffs_present = sum(
        row["white_rating_diff"] is not None and row["black_rating_diff"] is not None for row in compact_rows
    )
    telemetry_document = {
        "stage": STAGE,
        "month": month,
        "unit_index": unit_index,
        "retrieved_utc": retrieved_utc,
        "request_rows": len(ids),
        "returned_unique_ids": len(records_by_id),
        "missing_ids": len(missing_ids),
        "raw_objects_written_including_retry_duplicates": raw_objects_written,
        "batch_sequences": batch_sequence,
        "http_attempts": len(telemetry),
        "status_counts": dict(sorted(status_counts.items())),
        "rated_counts": dict(sorted(rated_counts.items())),
        "both_rating_diffs_present": both_rating_diffs_present,
        "attempts": telemetry,
    }
    atomic_write_json(paths["telemetry"], telemetry_document)

    artifacts = {}
    for name in ("compact", "raw", "missing", "telemetry"):
        path = paths[name]
        artifacts[name] = {
            "relative_path": str(path.relative_to(month_dir)),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
    checkpoint = {
        "stage": STAGE,
        "final_ok": True,
        "finished_utc": utc_now(),
        "month": month,
        "unit_index": unit_index,
        "request_rows": len(ids),
        "request_ordered_ids_sha256": unit["ordered_ids_sha256"],
        "returned_unique_ids": len(records_by_id),
        "missing_ids": len(missing_ids),
        "both_rating_diffs_present": both_rating_diffs_present,
        "status_counts": dict(sorted(status_counts.items())),
        "rated_counts": dict(sorted(rated_counts.items())),
        "batch_sequences": batch_sequence,
        "http_attempts": len(telemetry),
        "artifacts": artifacts,
    }
    if checkpoint["returned_unique_ids"] + checkpoint["missing_ids"] != checkpoint["request_rows"]:
        raise RuntimeError("unit count conservation failed")
    atomic_write_json(paths["checkpoint"], checkpoint)
    if not valid_unit_checkpoint(month_dir, unit):
        raise RuntimeError(f"unit {unit_index} failed post-write checkpoint verification")
    return checkpoint


def finalize_month(month_dir: Path, plan: dict[str, Any], machine_label: str) -> dict[str, Any]:
    checkpoints: list[dict[str, Any]] = []
    for unit in plan["units"]:
        if not valid_unit_checkpoint(month_dir, unit):
            raise RuntimeError(f"cannot finalize {plan['month']}: invalid unit {unit['unit_index']}")
        path = request_unit_paths(month_dir, unit["unit_index"])["checkpoint"]
        checkpoints.append(json.loads(path.read_text(encoding="utf-8")))
    requested = sum(row["request_rows"] for row in checkpoints)
    returned = sum(row["returned_unique_ids"] for row in checkpoints)
    missing = sum(row["missing_ids"] for row in checkpoints)
    if requested != plan["selected_rows"] or returned + missing != requested:
        raise RuntimeError(f"month count conservation failed for {plan['month']}")
    status_counts: Counter[str] = Counter()
    rated_counts: Counter[str] = Counter()
    for checkpoint in checkpoints:
        status_counts.update(checkpoint["status_counts"])
        rated_counts.update(checkpoint["rated_counts"])
    success = {
        "stage": STAGE,
        "final_ok": True,
        "finished_utc": utc_now(),
        "month": plan["month"],
        "machine_label": machine_label,
        "locked_sample_start": LOCKED_SAMPLE_START,
        "locked_sample_end": LOCKED_SAMPLE_END,
        "production": plan["production"],
        "source_path": plan["source_path"],
        "source_rows": plan["source_rows"],
        "source_sha256": plan["source_sha256"],
        "selected_rows": plan["selected_rows"],
        "selected_ordered_ids_sha256": plan["selected_ordered_ids_sha256"],
        "unit_size": plan["unit_size"],
        "unit_count": plan["unit_count"],
        "requested_ids": requested,
        "returned_unique_ids": returned,
        "missing_ids": missing,
        "both_rating_diffs_present": sum(row["both_rating_diffs_present"] for row in checkpoints),
        "batch_sequences": sum(row["batch_sequences"] for row in checkpoints),
        "http_attempts": sum(row["http_attempts"] for row in checkpoints),
        "status_counts": dict(sorted(status_counts.items())),
        "rated_counts": dict(sorted(rated_counts.items())),
        "unit_checkpoint_sha256": [
            {
                "unit_index": unit["unit_index"],
                "sha256": sha256_file(request_unit_paths(month_dir, unit["unit_index"])["checkpoint"]),
            }
            for unit in plan["units"]
        ],
    }
    atomic_write_json(month_dir / "_SUCCESS.json", success)
    return success


@contextlib.contextmanager
def output_lock(output_root: Path, machine_label: str) -> Iterator[None]:
    output_root.mkdir(parents=True, exist_ok=True)
    lock_path = output_root / ".stage04.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError(f"another Stage 04 process holds {lock_path}") from error
        handle.seek(0)
        handle.truncate()
        handle.write(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "host": socket.gethostname(),
                    "machine_label": machine_label,
                    "locked_utc": utc_now(),
                },
                sort_keys=True,
            )
            + "\n"
        )
        handle.flush()
        yield
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def plan_rows(
    months: list[str],
    input_root: Path,
    max_games: int | None,
    batch_size: int,
    unit_size: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for month in months:
        source = locate_target_parquet(input_root, month)
        source_rows = parquet_rows(source)
        expected = EXPECTED_TARGET_ROWS[month]
        if source_rows != expected:
            raise RuntimeError(f"{month}: target Parquet has {source_rows:,} rows; expected {expected:,}")
        selected = min(source_rows, max_games) if max_games is not None else source_rows
        rows.append(
            {
                "month": month,
                "source": str(source),
                "source_rows": source_rows,
                "selected_rows": selected,
                "units": math.ceil(selected / unit_size),
                "api_batches": math.ceil(selected / batch_size),
            }
        )
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Canonical, resumable, Parquet-first Lichess API enrichment for timeout candidates."
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(os.environ.get("LICHESS_KINDNESS_ROOT", "/Volumes/XT_Pro/lichess_kindness")),
    )
    parser.add_argument("--input-root", type=Path, default=None)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--pile", choices=("home", "office", "all"), default=None)
    parser.add_argument("--months", nargs="+", default=None, help="Explicit bridge YYYY-MM values; overrides --pile.")
    parser.add_argument("--machine-label", default=socket.gethostname())
    parser.add_argument("--execute", action="store_true", help="Make API requests. Without this flag, print plan only.")
    parser.add_argument("--max-games-per-month", type=int, default=None, help="Smoke-test cap; makes non-production output.")
    parser.add_argument("--batch-size", type=int, default=300)
    parser.add_argument("--unit-size", type=int, default=30_000)
    parser.add_argument("--sleep-seconds", type=float, default=1.0)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--max-retries", type=int, default=20)
    parser.add_argument("--missing-id-retries", type=int, default=2)
    parser.add_argument("--zstd-level", type=int, default=9)
    parser.add_argument("--oauth-token-env", default=None, help="Optional token env var; batch limit remains 300.")
    parser.add_argument("--user-agent", default=None)
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if not (1 <= args.batch_size <= 300):
        raise SystemExit("--batch-size must be between 1 and 300")
    if args.unit_size < args.batch_size:
        raise SystemExit("--unit-size must be at least --batch-size")
    if args.max_games_per_month is not None and args.max_games_per_month < 1:
        raise SystemExit("--max-games-per-month must be positive")
    if args.sleep_seconds < 1.0:
        raise SystemExit("--sleep-seconds must be at least 1.0")
    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be positive")
    if args.max_retries < 0 or args.missing_id_retries < 0:
        raise SystemExit("retry counts cannot be negative")


def main() -> int:
    args = parse_args()
    validate_args(args)
    months = resolve_months(args.pile, args.months)
    project_root = args.project_root.expanduser().resolve()
    input_root = (
        args.input_root.expanduser().resolve()
        if args.input_root
        else project_root / "derived" / "replication" / "pgn_timeforfeit_candidates"
    )
    output_root = (
        args.output_root.expanduser().resolve()
        if args.output_root
        else project_root / "derived" / "replication" / "api_timeout_enrichment"
    )
    pile = args.pile or "explicit-months"
    plan = plan_rows(months, input_root, args.max_games_per_month, args.batch_size, args.unit_size)
    summary_plan = {
        "stage": STAGE,
        "execute": args.execute,
        "project_root": str(project_root),
        "input_root": str(input_root),
        "output_root": str(output_root),
        "pile": pile,
        "machine_label": args.machine_label,
        "months": months,
        "locked_sample_start": LOCKED_SAMPLE_START,
        "locked_sample_end": LOCKED_SAMPLE_END,
        "production": args.max_games_per_month is None,
        "batch_size": args.batch_size,
        "unit_size": args.unit_size,
        "sleep_seconds": args.sleep_seconds,
        "max_games_per_month": args.max_games_per_month,
        "month_plan": plan,
        "total_source_rows": sum(row["source_rows"] for row in plan),
        "total_selected_rows": sum(row["selected_rows"] for row in plan),
        "total_units": sum(row["units"] for row in plan),
        "total_api_batches_before_retries": sum(row["api_batches"] for row in plan),
    }
    print(json.dumps(summary_plan, indent=2), flush=True)
    if not args.execute:
        print("\nPLAN ONLY. Add --execute to prepare units and make sequential API requests.")
        return 0

    token = None
    if args.oauth_token_env:
        token = os.environ.get(args.oauth_token_env)
        if not token:
            raise SystemExit(f"environment variable {args.oauth_token_env!r} is not set")
    user_agent = args.user_agent or (
        f"lichess-kindness-replication/1.0 (academic research; machine={args.machine_label})"
    )
    session = requests.Session()
    session.headers.update({"User-Agent": user_agent})
    if token:
        session.headers.update({"Authorization": f"Bearer {token}"})

    successes: list[dict[str, Any]] = []
    run_started = utc_now()
    with output_lock(output_root, args.machine_label):
        manifests_dir = output_root / "_manifests"
        manifests_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(manifests_dir / f"active_plan_{pile}.json", summary_plan | {"started_utc": run_started})

        for month in months:
            month_started = time.monotonic()
            month_dir = output_root / f"month={month}"
            source_path = locate_target_parquet(input_root, month)
            source_rows = parquet_rows(source_path)
            id_column = identify_id_column(source_path)
            print(f"\nSTART MONTH {month}: computing API-target source SHA-256", flush=True)
            source_sha256 = sha256_file(source_path)
            print(f"{month}: source SHA-256 {source_sha256}", flush=True)
            month_plan = build_request_units(
                source_path=source_path,
                id_column=id_column,
                month_dir=month_dir,
                month=month,
                source_rows=source_rows,
                source_sha256=source_sha256,
                unit_size=args.unit_size,
                max_games=args.max_games_per_month,
            )
            completed_before = sum(valid_unit_checkpoint(month_dir, unit) for unit in month_plan["units"])
            print(
                f"{month}: units={month_plan['unit_count']:,}; valid completed={completed_before:,}; "
                f"remaining={month_plan['unit_count'] - completed_before:,}",
                flush=True,
            )
            for unit in month_plan["units"]:
                if valid_unit_checkpoint(month_dir, unit):
                    continue
                unit_started = time.monotonic()
                print(
                    f"\n{month}: START UNIT {unit['unit_index']:05d} "
                    f"({unit['rows']:,} IDs)",
                    flush=True,
                )
                checkpoint = run_unit(
                    session=session,
                    month_dir=month_dir,
                    month=month,
                    unit=unit,
                    batch_size=args.batch_size,
                    sleep_seconds=args.sleep_seconds,
                    timeout_seconds=args.timeout_seconds,
                    max_retries=args.max_retries,
                    missing_id_retries=args.missing_id_retries,
                    zstd_level=args.zstd_level,
                )
                print(
                    f"{month}: COMPLETE UNIT {unit['unit_index']:05d}; "
                    f"returned={checkpoint['returned_unique_ids']:,}; missing={checkpoint['missing_ids']:,}; "
                    f"elapsed={time.monotonic() - unit_started:,.1f}s",
                    flush=True,
                )
            success = finalize_month(month_dir, month_plan, args.machine_label)
            successes.append(success)
            print(
                f"\nCOMPLETE MONTH {month}: requested={success['requested_ids']:,}; "
                f"returned={success['returned_unique_ids']:,}; missing={success['missing_ids']:,}; "
                f"elapsed={time.monotonic() - month_started:,.1f}s",
                flush=True,
            )

        final_summary = {
            "stage": STAGE,
            "final_ok": True,
            "started_utc": run_started,
            "finished_utc": utc_now(),
            "pile": pile,
            "machine_label": args.machine_label,
            "months": months,
            "production": args.max_games_per_month is None,
            "output_root": str(output_root),
            "total_requested_ids": sum(row["requested_ids"] for row in successes),
            "total_returned_unique_ids": sum(row["returned_unique_ids"] for row in successes),
            "total_missing_ids": sum(row["missing_ids"] for row in successes),
            "month_success_sha256": [
                {
                    "month": month,
                    "sha256": sha256_file(output_root / f"month={month}" / "_SUCCESS.json"),
                }
                for month in months
            ],
        }
        atomic_write_json(manifests_dir / f"stage04_summary_{pile}.json", final_summary)
        print("\nFINAL STAGE 04 SUMMARY")
        print(json.dumps(final_summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
