#!/usr/bin/env python3
"""Fetch missing Lichess opening metadata from a certified Stage 09 plan.

The client is resumable after every request batch, processes at most 300 game
IDs per request, uses one request at a time, and adds no fixed delay by default.
It honors Lichess ``Retry-After`` and otherwise applies exponential backoff on
HTTP 429.  There is deliberately no artificial daily quota or 24-hour lock.

Dry-run is the default.  Use ``--execute`` for live requests.  Separate laptops
can traverse the complete plan in opposite directions and exchange their small
completion-ledger JSON files to avoid overlap.
"""

from __future__ import annotations

import argparse
import email.utils
import hashlib
import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


SCRIPT_VERSION = "1.0.0"
PROJECT = Path("/Volumes/XT_Pro/lichess_kindness")
DEFAULT_PLAN_ROOT = PROJECT / "derived/replication/opening_familiarity_24m_plan_v100"
DEFAULT_FETCH_PARENT = PROJECT / "derived/replication"
ENDPOINT = "https://lichess.org/api/games/export/_ids"
PARAMETERS = {
    "moves": "false",
    "pgnInJson": "false",
    "tags": "true",
    "clocks": "false",
    "evals": "false",
    "accuracy": "false",
    "opening": "true",
    "division": "false",
    "literate": "false",
}


def utc_now() -> str:
    return pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path, chunk_size: int = 16 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    temporary.write_bytes(value)
    os.replace(temporary, path)


def atomic_write_text(path: Path, value: str) -> None:
    atomic_write_bytes(path, value.encode("utf-8"))


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def atomic_write_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    table = pa.Table.from_pandas(frame, preserve_index=False)
    pq.write_table(table, temporary, compression="zstd")
    os.replace(temporary, path)


def load_plan(root: Path) -> tuple[dict[str, Any], str, Path]:
    success = root / "_SUCCESS.json"
    fetch_plan = root / "targets/opening_targets_needing_fetch.parquet"
    hashes_path = root / "plan_file_hashes.tsv"
    if not success.is_file() or not fetch_plan.is_file() or not hashes_path.is_file():
        raise RuntimeError(f"Certified opening plan is incomplete: {root}")
    value = json.loads(success.read_text(encoding="utf-8"))
    if value.get("status") != "OPENING_FAMILIARITY_PLAN_CERTIFIED_OK":
        raise RuntimeError(f"Opening plan status changed: {value.get('status')}")
    if sha256_file(hashes_path) != value.get("plan_file_hashes_sha256"):
        raise RuntimeError("Opening plan hash manifest changed")
    plan_sha = sha256_file(success)
    parquet = pq.ParquetFile(fetch_plan)
    required = {
        "game_id",
        "fetch_ordinal",
        "request_batch",
        "fetch_macro_batch",
    }
    if not required.issubset(parquet.schema_arrow.names):
        raise RuntimeError("Opening fetch-plan schema is incomplete")
    expected = int(value["plan_qa"]["fetch_rows"])
    if parquet.metadata.num_rows != expected:
        raise RuntimeError(
            f"Opening fetch-plan rows changed: {parquet.metadata.num_rows:,} != {expected:,}"
        )
    hashes = pd.read_csv(hashes_path, sep="\t")
    for row in hashes.itertuples(index=False):
        path = root / str(row.path)
        if not path.is_file() or path.stat().st_size != int(row.bytes):
            raise RuntimeError(f"Opening plan file size changed: {path}")
        if sha256_file(path) != str(row.sha256):
            raise RuntimeError(f"Opening plan file SHA changed: {path}")
    return value, plan_sha, fetch_plan


def fetch_root_for(plan_sha: str, direction: str, explicit: str) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    return (
        DEFAULT_FETCH_PARENT
        / f"opening_familiarity_24m_fetch_v100_{direction}_{plan_sha[:12]}"
    )


def initialize_or_authenticate(
    root: Path,
    plan_root: Path,
    plan_sha: str,
    direction: str,
    script_sha: str,
) -> dict[str, Any]:
    config_path = root / "config.json"
    expected = {
        "status": "OPENING_FETCH_CONFIG_OK",
        "created_at_utc": None,
        "script_version": SCRIPT_VERSION,
        "script_sha256": script_sha,
        "plan_root": str(plan_root),
        "plan_success_sha256": plan_sha,
        "direction": direction,
        "endpoint": ENDPOINT,
        "parameters": PARAMETERS,
        "request_ids_max": 300,
        "concurrency": 1,
        "privacy": "Research data; keep outside GitHub.",
    }
    if not root.exists():
        root.mkdir(parents=True)
        value = dict(expected)
        value["created_at_utc"] = utc_now()
        atomic_write_json(config_path, value)
        return value
    if not config_path.is_file():
        raise RuntimeError(f"Fetch root exists without config.json: {root}")
    value = json.loads(config_path.read_text(encoding="utf-8"))
    for key in (
        "status",
        "script_version",
        "script_sha256",
        "plan_root",
        "plan_success_sha256",
        "direction",
        "endpoint",
        "parameters",
        "request_ids_max",
        "concurrency",
    ):
        if value.get(key) != expected.get(key):
            raise RuntimeError(
                f"Existing fetch config mismatch for {key}: "
                f"expected={expected.get(key)!r} actual={value.get(key)!r}"
            )
    return value


def load_local_ledger(root: Path, plan_sha: str, direction: str) -> dict[str, Any]:
    path = root / "completed_request_batches.json"
    if not path.is_file():
        return {
            "status": "OPENING_FETCH_IN_PROGRESS",
            "updated_at_utc": utc_now(),
            "plan_success_sha256": plan_sha,
            "direction": direction,
            "completed_request_batches": {},
        }
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        value.get("plan_success_sha256") != plan_sha
        or value.get("direction") != direction
    ):
        raise RuntimeError(f"Local completion ledger does not match this run: {path}")
    completed = value.get("completed_request_batches")
    if not isinstance(completed, dict):
        raise RuntimeError(f"Local completion ledger is malformed: {path}")
    for batch_text, receipt_sha in completed.items():
        batch = int(batch_text)
        receipt = receipt_path(root, batch)
        if not receipt.is_file():
            raise RuntimeError(
                f"Ledger receipt is missing for request batch {batch}: {receipt}"
            )
        if sha256_file(receipt) != receipt_sha:
            raise RuntimeError(f"Ledger receipt SHA mismatch for request batch {batch}")
    return value


def load_peer_batches(
    paths: Iterable[str], plan_sha: str
) -> tuple[set[int], list[dict[str, Any]]]:
    completed: set[int] = set()
    records: list[dict[str, Any]] = []
    for text in paths:
        path = Path(text).expanduser().resolve()
        if not path.is_file():
            raise RuntimeError(f"Peer completion ledger is missing: {path}")
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("plan_success_sha256") != plan_sha:
            raise RuntimeError(f"Peer completion ledger is for another plan: {path}")
        peer = {int(item) for item in value.get("completed_request_batches", {})}
        overlap = completed & peer
        if overlap:
            raise RuntimeError(
                f"Peer ledgers overlap one another: {sorted(overlap)[:10]}"
            )
        completed |= peer
        records.append(
            {
                "path": str(path),
                "sha256": sha256_file(path),
                "direction": value.get("direction"),
                "completed_batches": len(peer),
            }
        )
    return completed, records


def receipt_path(root: Path, batch: int) -> Path:
    macro = (batch - 1) // 400 + 1
    return root / f"batches/macro_{macro:04d}/request_{batch:06d}.receipt.json"


def raw_path(root: Path, batch: int) -> Path:
    macro = (batch - 1) // 400 + 1
    return root / f"batches/macro_{macro:04d}/request_{batch:06d}.ndjson"


def normalized_path(root: Path, batch: int) -> Path:
    macro = (batch - 1) // 400 + 1
    return root / f"batches/macro_{macro:04d}/request_{batch:06d}.parquet"


def parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            parsed = email.utils.parsedate_to_datetime(value)
            now = pd.Timestamp.now(tz="UTC").to_pydatetime()
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=now.tzinfo)
            return max(0.0, (parsed - now).total_seconds())
        except Exception:
            return None


def response_objects(body: bytes) -> list[dict[str, Any]]:
    text = body.decode("utf-8")
    stripped = text.strip()
    if not stripped:
        return []
    if stripped.startswith("["):
        value = json.loads(stripped)
        if not isinstance(value, list) or not all(
            isinstance(item, dict) for item in value
        ):
            raise RuntimeError("Lichess response JSON array is malformed")
        return value
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise RuntimeError(f"Lichess NDJSON line {number} is not an object")
        rows.append(value)
    return rows


def opening_row(
    game_id: str, value: dict[str, Any] | None, fetched_at: str
) -> dict[str, Any]:
    opening = value.get("opening") if value else None
    if not isinstance(opening, dict):
        opening = {}
    return {
        "game_id": game_id,
        "returned": value is not None,
        "eco": opening.get("eco"),
        "opening_name": opening.get("name"),
        "opening_ply": opening.get("ply"),
        "rated": value.get("rated") if value else None,
        "speed": value.get("speed") if value else None,
        "variant": value.get("variant") if value else None,
        "created_at": value.get("createdAt") if value else None,
        "last_move_at": value.get("lastMoveAt") if value else None,
        "fetched_at_utc": fetched_at,
    }


def make_request(
    game_ids: list[str],
    timeout: float,
    max_retries: int,
    backoff_base: float,
    backoff_cap: float,
) -> tuple[bytes, dict[str, Any]]:
    url = ENDPOINT + "?" + urllib.parse.urlencode(PARAMETERS)
    body = ",".join(game_ids).encode("ascii")
    token = os.environ.get("LICHESS_TOKEN", "").strip()
    headers = {
        "Accept": "application/x-ndjson",
        "Content-Type": "text/plain; charset=utf-8",
        "User-Agent": "intrinsic-prosociality-research/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    attempts: list[dict[str, Any]] = []
    for attempt in range(1, max_retries + 1):
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read()
                status = int(response.status)
                meta = {
                    "attempt": attempt,
                    "status": status,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "content_type": response.headers.get("Content-Type"),
                    "retry_after": response.headers.get("Retry-After"),
                }
                attempts.append(meta)
                if status != 200:
                    raise RuntimeError(
                        f"Unexpected successful HTTP status object: {status}"
                    )
                return payload, {
                    "attempts": attempts,
                    "request_body_sha256": sha256_bytes(body),
                }
        except urllib.error.HTTPError as exc:
            error_body = exc.read()
            status = int(exc.code)
            retry_after = parse_retry_after(exc.headers.get("Retry-After"))
            attempts.append(
                {
                    "attempt": attempt,
                    "status": status,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "retry_after": exc.headers.get("Retry-After"),
                    "error_body_sha256": sha256_bytes(error_body),
                    "error_body_preview": error_body[:500].decode(
                        "utf-8", errors="replace"
                    ),
                }
            )
            if status == 429 and attempt < max_retries:
                exponential = min(backoff_cap, backoff_base * (2 ** (attempt - 1)))
                wait = max(exponential, retry_after or 0.0) + random.uniform(0.25, 1.25)
                print(
                    f"RETRYABLE_HTTP status=429 attempt={attempt}/{max_retries} "
                    f"wait_seconds={wait:.1f}",
                    flush=True,
                )
                time.sleep(wait)
                continue
            if 500 <= status <= 599 and attempt < max_retries:
                wait = min(60.0, 2.0 * (2 ** (attempt - 1))) + random.uniform(0.1, 0.9)
                print(
                    f"RETRYABLE_HTTP status={status} attempt={attempt}/{max_retries} "
                    f"wait_seconds={wait:.1f}",
                    flush=True,
                )
                time.sleep(wait)
                continue
            raise RuntimeError(
                f"Lichess request failed with HTTP {status} after {attempt} attempt(s); "
                f"response={error_body[:500]!r}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            attempts.append(
                {
                    "attempt": attempt,
                    "status": "network_error",
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "error": repr(exc),
                }
            )
            if attempt >= max_retries:
                raise RuntimeError(
                    f"Lichess request exhausted network retries: {exc!r}"
                ) from exc
            wait = min(60.0, 2.0 * (2 ** (attempt - 1))) + random.uniform(0.1, 0.9)
            print(
                f"RETRYABLE_NETWORK attempt={attempt}/{max_retries} wait_seconds={wait:.1f}",
                flush=True,
            )
            time.sleep(wait)
    raise AssertionError("unreachable")


def certify_batch(
    root: Path,
    batch: int,
    macro: int,
    game_ids: list[str],
    body: bytes,
    request_meta: dict[str, Any],
    plan_sha: str,
) -> tuple[Path, str, dict[str, Any]]:
    objects = response_objects(body)
    by_id: dict[str, dict[str, Any]] = {}
    requested_ids = set(game_ids)
    for value in objects:
        game_id = str(value.get("id", ""))
        if not game_id:
            raise RuntimeError(f"Returned game lacks id in request batch {batch}")
        if game_id in by_id:
            raise RuntimeError(
                f"Duplicate returned game id {game_id!r} in request batch {batch}"
            )
        if game_id not in requested_ids:
            raise RuntimeError(f"Lichess returned unrequested game id {game_id!r}")
        by_id[game_id] = value
    fetched_at = utc_now()
    normalized = pd.DataFrame(
        opening_row(game_id, by_id.get(game_id), fetched_at) for game_id in game_ids
    )
    if len(normalized) != len(game_ids) or normalized.game_id.nunique() != len(
        game_ids
    ):
        raise RuntimeError(f"Normalized row QA failed for request batch {batch}")
    raw = raw_path(root, batch)
    norm = normalized_path(root, batch)
    receipt = receipt_path(root, batch)
    for path in (raw, norm, receipt):
        if path.exists():
            raise RuntimeError(f"Refusing to overwrite existing batch artifact: {path}")
    atomic_write_bytes(raw, body)
    atomic_write_parquet(norm, normalized)
    value = {
        "status": "OPENING_REQUEST_CERTIFIED_OK",
        "created_at_utc": utc_now(),
        "plan_success_sha256": plan_sha,
        "request_batch": batch,
        "fetch_macro_batch": macro,
        "requested_game_ids": len(game_ids),
        "returned_games": len(by_id),
        "explicit_not_returned_rows": len(game_ids) - len(by_id),
        "requested_game_ids_sha256": sha256_bytes(
            ("\n".join(game_ids) + "\n").encode("ascii")
        ),
        "raw_relative_path": str(raw.relative_to(root)),
        "raw_sha256": sha256_file(raw),
        "raw_bytes": raw.stat().st_size,
        "normalized_relative_path": str(norm.relative_to(root)),
        "normalized_sha256": sha256_file(norm),
        "normalized_rows": len(normalized),
        "request": request_meta,
    }
    atomic_write_json(receipt, value)
    return receipt, sha256_file(receipt), value


def plan_database(fetch_plan: Path) -> duckdb.DuckDBPyConnection:
    database = duckdb.connect(":memory:")
    escaped = str(fetch_plan).replace("'", "''")
    database.execute(f"CREATE VIEW targets AS SELECT * FROM read_parquet('{escaped}')")
    return database


def run_self_test() -> None:
    body = (
        b'{"id":"abcdefgh","opening":{"eco":"C20","name":"King Pawn Game","ply":4}}\n'
        b'{"id":"ijklmnop","rated":true}\n'
    )
    values = response_objects(body)
    assert len(values) == 2
    row = opening_row("abcdefgh", values[0], "2026-08-21T00:00:00Z")
    assert row["eco"] == "C20" and row["opening_ply"] == 4
    missing = opening_row("qrstuvwx", None, "2026-08-21T00:00:00Z")
    assert missing["returned"] is False and missing["eco"] is None
    assert parse_retry_after("60") == 60.0
    print("OPENING_FETCH_SELF_TEST_OK")


def execute(args: argparse.Namespace) -> None:
    started = time.time()
    plan_root = Path(args.plan_root).expanduser().resolve()
    _plan, plan_sha, fetch_plan = load_plan(plan_root)
    script_sha = sha256_file(Path(__file__).resolve())
    root = fetch_root_for(plan_sha, args.direction, args.output_root)
    if args.execute or root.exists():
        initialize_or_authenticate(
            root, plan_root, plan_sha, args.direction, script_sha
        )
    if root.exists():
        ledger = load_local_ledger(root, plan_sha, args.direction)
    else:
        ledger = {
            "status": "OPENING_FETCH_IN_PROGRESS",
            "updated_at_utc": utc_now(),
            "plan_success_sha256": plan_sha,
            "direction": args.direction,
            "completed_request_batches": {},
        }
    local_completed = {int(item) for item in ledger["completed_request_batches"]}
    peer_completed, peer_records = load_peer_batches(args.peer_ledger, plan_sha)
    overlap = local_completed & peer_completed
    if overlap:
        raise RuntimeError(f"Local and peer ledgers overlap: {sorted(overlap)[:10]}")

    database = plan_database(fetch_plan)
    batch_rows = database.execute(
        "SELECT request_batch::BIGINT AS request_batch, "
        "min(fetch_macro_batch)::BIGINT AS fetch_macro_batch, count(*)::BIGINT AS game_ids "
        "FROM targets GROUP BY 1 ORDER BY 1"
    ).fetchdf()
    all_batches = [int(value) for value in batch_rows.request_batch]
    visible_completed = local_completed | peer_completed
    remaining = [batch for batch in all_batches if batch not in visible_completed]
    if args.direction == "descending":
        remaining.reverse()
    print("OPENING_FETCH_PLAN_OK")
    print(f"script_version: {SCRIPT_VERSION}")
    print(f"script_sha256: {script_sha}")
    print(f"plan_success_sha256: {plan_sha}")
    print(f"direction: {args.direction}")
    print(f"fetch_root: {root}")
    print(f"all_request_batches: {len(all_batches):,}")
    print(f"local_completed_batches: {len(local_completed):,}")
    print(f"peer_completed_batches: {len(peer_completed):,}")
    print(f"remaining_visible_batches: {len(remaining):,}")
    print(f"fixed_inter_request_pause_seconds: {args.min_interval_seconds}")
    print("concurrency: 1")
    print(
        "429_policy: Retry-After or exponential backoff; no artificial daily cooldown"
    )
    if not args.execute:
        print("No API requests were made. Re-run with --execute to begin or resume.")
        database.close()
        return

    completed_this_run = 0
    last_request_started: float | None = None
    for batch in remaining:
        if args.max_batches and completed_this_run >= args.max_batches:
            break
        if last_request_started is not None and args.min_interval_seconds > 0:
            wait = args.min_interval_seconds - (time.monotonic() - last_request_started)
            if wait > 0:
                print(f"MIN_INTERVAL_WAIT seconds={wait:.1f}", flush=True)
                time.sleep(wait)
        rows = database.execute(
            "SELECT game_id::VARCHAR AS game_id, fetch_macro_batch::BIGINT AS fetch_macro_batch "
            "FROM targets WHERE request_batch=? ORDER BY fetch_ordinal",
            [batch],
        ).fetchdf()
        game_ids = rows.game_id.astype(str).tolist()
        macro = int(rows.fetch_macro_batch.iloc[0])
        if not 1 <= len(game_ids) <= 300:
            raise RuntimeError(f"Request batch {batch} contains {len(game_ids)} IDs")
        last_request_started = time.monotonic()
        body, request_meta = make_request(
            game_ids,
            args.timeout_seconds,
            args.max_retries,
            args.backoff_base_seconds,
            args.backoff_cap_seconds,
        )
        receipt, receipt_sha, receipt_value = certify_batch(
            root, batch, macro, game_ids, body, request_meta, plan_sha
        )
        ledger["completed_request_batches"][str(batch)] = receipt_sha
        ledger["updated_at_utc"] = utc_now()
        ledger["status"] = "OPENING_FETCH_IN_PROGRESS"
        ledger["local_completed_batches"] = len(ledger["completed_request_batches"])
        ledger["last_completed_request_batch"] = batch
        ledger["last_receipt_relative_path"] = str(receipt.relative_to(root))
        atomic_write_json(root / "completed_request_batches.json", ledger)
        completed_this_run += 1
        if completed_this_run == 1 or completed_this_run % 25 == 0:
            print(
                f"FETCH_PROGRESS new_batches={completed_this_run} request_batch={batch:06d} "
                f"returned={receipt_value['returned_games']}/{len(game_ids)}",
                flush=True,
            )

    local_completed = {int(item) for item in ledger["completed_request_batches"]}
    combined = local_completed | peer_completed
    remaining_count = len(set(all_batches) - combined)
    status = (
        "OPENING_FETCH_ALL_VISIBLE_BATCHES_COMPLETE"
        if remaining_count == 0
        else "OPENING_FETCH_CHECKPOINT_OK"
    )
    ledger["status"] = status
    ledger["updated_at_utc"] = utc_now()
    ledger["local_completed_batches"] = len(local_completed)
    atomic_write_json(root / "completed_request_batches.json", ledger)
    run_summary = {
        "status": status,
        "created_at_utc": utc_now(),
        "script_version": SCRIPT_VERSION,
        "script_sha256": script_sha,
        "plan_success_sha256": plan_sha,
        "direction": args.direction,
        "fetch_root": str(root),
        "completed_this_run": completed_this_run,
        "local_completed_batches": len(local_completed),
        "peer_completed_batches": len(peer_completed),
        "combined_completed_batches": len(combined),
        "remaining_batches": remaining_count,
        "peer_ledgers": peer_records,
        "completion_ledger": str(root / "completed_request_batches.json"),
        "completion_ledger_sha256": sha256_file(
            root / "completed_request_batches.json"
        ),
        "runtime_seconds": round(time.time() - started, 3),
        "pacing": {
            "fixed_minimum_interval_seconds": args.min_interval_seconds,
            "concurrency": 1,
            "max_retries": args.max_retries,
            "backoff_base_seconds": args.backoff_base_seconds,
            "backoff_cap_seconds": args.backoff_cap_seconds,
            "artificial_daily_cooldown": False,
        },
    }
    runs = root / "run_summaries"
    runs.mkdir(exist_ok=True)
    run_path = runs / f"{pd.Timestamp.now(tz='UTC').strftime('%Y%m%dT%H%M%SZ')}.json"
    atomic_write_json(run_path, run_summary)
    database.close()
    print(status)
    print(f"completed_this_run: {completed_this_run:,}")
    print(f"local_completed_batches: {len(local_completed):,}")
    print(f"combined_remaining_batches: {remaining_count:,}")
    print(f"completion_ledger: {root / 'completed_request_batches.json'}")
    print(f"run_summary: {run_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-root", default=str(DEFAULT_PLAN_ROOT))
    parser.add_argument("--output-root", default="")
    parser.add_argument(
        "--direction", choices=("ascending", "descending"), default="ascending"
    )
    parser.add_argument("--peer-ledger", action="append", default=[])
    parser.add_argument("--max-batches", type=int, default=0)
    parser.add_argument("--min-interval-seconds", type=float, default=0.0)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--max-retries", type=int, default=12)
    parser.add_argument("--backoff-base-seconds", type=float, default=60.0)
    parser.add_argument("--backoff-cap-seconds", type=float, default=900.0)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            run_self_test()
            return
        if args.max_batches < 0:
            raise RuntimeError("--max-batches cannot be negative")
        if args.min_interval_seconds < 0:
            raise RuntimeError("--min-interval-seconds cannot be negative")
        if not 1 <= args.max_retries <= 30:
            raise RuntimeError("--max-retries must be between 1 and 30")
        execute(args)
    except Exception as exc:
        print(
            f"OPENING_FETCH_FAIL_CLOSED: {type(exc).__name__}: {exc}", file=sys.stderr
        )
        raise


if __name__ == "__main__":
    main()
