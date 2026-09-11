#!/usr/bin/env python3
"""Fetch a lossless Lichess patron/profile snapshot from a certified plan.

The client is serial, resumable, and conservative relative to the published
bulk-user limits.  It preserves exact request and response bytes, normalized
per-user rows containing canonical raw JSON, a JSON-key inventory, telemetry,
and cryptographic receipts.  It never treats an unreturned profile as a
non-patron.
"""

from __future__ import annotations

import argparse
import csv
import email.utils
import hashlib
import json
import os
import random
import sys
import time
import traceback
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import requests


SCRIPT_VERSION = "1.0.0"
API_URL = "https://lichess.org/api/users?profile=true&rank=true"
BATCH_SIZE = 300
TEN_MINUTE_SAFE_USERS = 7_800
DAY_SAFE_USERS = 120_000
MIN_START_INTERVAL_SECONDS = 23.2
MAX_ATTEMPTS_PER_BATCH = 8
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
SENSITIVE_RESPONSE_HEADERS = {"set-cookie", "set-cookie2"}


NORMALIZED_SCHEMA = pa.schema(
    [
        ("batch_id", pa.string()),
        ("batch_index", pa.int64()),
        ("request_position", pa.int16()),
        ("username_requested", pa.string()),
        ("username_norm", pa.string()),
        ("returned", pa.bool_()),
        ("username_returned", pa.string()),
        ("queried_at_utc", pa.string()),
        ("http_status", pa.int16()),
        ("raw_user_json", pa.large_string()),
        ("raw_user_sha256", pa.string()),
        ("top_level_keys_json", pa.string()),
        ("id", pa.string()),
        ("username", pa.string()),
        ("patron", pa.bool_()),
        ("patron_field_present", pa.bool_()),
        ("patron_color", pa.string()),
        ("title", pa.string()),
        ("flair", pa.string()),
        ("verified", pa.bool_()),
        ("disabled", pa.bool_()),
        ("tos_violation", pa.bool_()),
        ("created_at_ms", pa.int64()),
        ("seen_at_ms", pa.int64()),
        ("play_time_total_seconds", pa.int64()),
        ("play_time_tv_seconds", pa.int64()),
        ("count_all", pa.int64()),
        ("count_rated", pa.int64()),
        ("count_win", pa.int64()),
        ("count_loss", pa.int64()),
        ("count_draw", pa.int64()),
        ("profile_present", pa.bool_()),
        ("profile_real_name", pa.string()),
        ("profile_bio", pa.large_string()),
        ("profile_location", pa.string()),
        ("profile_country", pa.string()),
        ("profile_flag", pa.string()),
        ("profile_fide_rating", pa.int64()),
        ("profile_uscf_rating", pa.int64()),
        ("profile_ecf_rating", pa.int64()),
        ("profile_cfc_rating", pa.int64()),
        ("profile_dsb_rating", pa.int64()),
        ("profile_links", pa.large_string()),
        ("profile_json", pa.large_string()),
        ("perfs_json", pa.large_string()),
        ("play_time_json", pa.large_string()),
        ("count_json", pa.large_string()),
    ]
)


class DailyQuotaReached(RuntimeError):
    def __init__(self, next_eligible_utc: str):
        super().__init__(f"Daily safety cap reached; next eligible UTC approximately {next_eligible_utc}")
        self.next_eligible_utc = next_eligible_utc


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def iso_from_epoch(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{uuid.uuid4().hex}")
    with temporary.open("wb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def atomic_write_text(path: Path, value: str) -> None:
    atomic_write_bytes(path, value.encode("utf-8"))


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def atomic_write_parquet(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{uuid.uuid4().hex}")
    table = pa.Table.from_pylist(rows, schema=NORMALIZED_SCHEMA)
    pq.write_table(table, temporary, compression="zstd", row_group_size=300)
    os.replace(temporary, path)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def norm_user(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def nullable_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def nullable_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None


def nullable_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return canonical_json(value)
    return str(value)


def profile_value(profile: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in profile:
            return profile.get(name)
    return None


def normalized_row(
    requested: str,
    position: int,
    user: dict[str, Any] | None,
    batch: dict[str, str],
    queried_at: str,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        name: None for name in NORMALIZED_SCHEMA.names
    }
    base.update(
        {
            "batch_id": batch["batch_id"],
            "batch_index": int(batch["batch_index"]),
            "request_position": position,
            "username_requested": requested,
            "username_norm": norm_user(requested),
            "returned": user is not None,
            "queried_at_utc": queried_at,
            "http_status": 200,
            "profile_present": False,
        }
    )
    if user is None:
        return base
    profile = user.get("profile") if isinstance(user.get("profile"), dict) else {}
    play_time = user.get("playTime") if isinstance(user.get("playTime"), dict) else {}
    counts = user.get("count") if isinstance(user.get("count"), dict) else {}
    perfs = user.get("perfs") if isinstance(user.get("perfs"), dict) else {}
    raw = canonical_json(user)
    returned_name = user.get("id") or user.get("username")
    base.update(
        {
            "username_returned": str(returned_name) if returned_name is not None else None,
            "raw_user_json": raw,
            "raw_user_sha256": sha256_text(raw),
            "top_level_keys_json": canonical_json(sorted(user.keys())),
            "id": str(user.get("id")) if user.get("id") is not None else None,
            "username": str(user.get("username")) if user.get("username") is not None else None,
            # The public API represents ordinary non-patrons by omitting the
            # optional patron flag.  Preserve that omission separately while
            # exposing the API-semantic patron indicator for returned users.
            "patron": bool(user.get("patron", False)),
            "patron_field_present": "patron" in user,
            "patron_color": str(user.get("patronColor")) if user.get("patronColor") is not None else None,
            "title": str(user.get("title")) if user.get("title") is not None else None,
            "flair": str(user.get("flair")) if user.get("flair") is not None else None,
            "verified": nullable_bool(user.get("verified")),
            "disabled": nullable_bool(user.get("disabled")),
            "tos_violation": nullable_bool(user.get("tosViolation")),
            "created_at_ms": nullable_int(user.get("createdAt")),
            "seen_at_ms": nullable_int(user.get("seenAt")),
            "play_time_total_seconds": nullable_int(play_time.get("total")),
            "play_time_tv_seconds": nullable_int(play_time.get("tv")),
            "count_all": nullable_int(counts.get("all")),
            "count_rated": nullable_int(counts.get("rated")),
            "count_win": nullable_int(counts.get("win")),
            "count_loss": nullable_int(counts.get("loss")),
            "count_draw": nullable_int(counts.get("draw")),
            "profile_present": bool(profile),
            "profile_real_name": nullable_text(profile_value(profile, "realName")),
            "profile_bio": nullable_text(profile_value(profile, "bio")),
            "profile_location": nullable_text(profile_value(profile, "location")),
            "profile_country": nullable_text(profile_value(profile, "country")),
            "profile_flag": nullable_text(profile_value(profile, "flag")),
            "profile_fide_rating": nullable_int(profile_value(profile, "fideRating")),
            "profile_uscf_rating": nullable_int(profile_value(profile, "uscfRating")),
            "profile_ecf_rating": nullable_int(profile_value(profile, "ecfRating")),
            "profile_cfc_rating": nullable_int(profile_value(profile, "cfcRating")),
            "profile_dsb_rating": nullable_int(profile_value(profile, "dsbRating")),
            "profile_links": nullable_text(profile_value(profile, "links")),
            "profile_json": canonical_json(profile),
            "perfs_json": canonical_json(perfs),
            "play_time_json": canonical_json(play_time),
            "count_json": canonical_json(counts),
        }
    )
    return base


def json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def pointer_escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def inventory_json(value: Any, path: str, counter: Counter[tuple[str, str]]) -> None:
    kind = json_type(value)
    counter[(path or "/", kind)] += 1
    if isinstance(value, dict):
        for key, child in value.items():
            inventory_json(child, (path + "/" + pointer_escape(str(key))) or "/", counter)
    elif isinstance(value, list):
        for child in value:
            inventory_json(child, path + "/[]", counter)


def write_key_inventory(path: Path, payload: list[dict[str, Any]]) -> None:
    counter: Counter[tuple[str, str]] = Counter()
    for user in payload:
        inventory_json(user, "", counter)
    rows = ["json_pointer\tjson_type\toccurrences"]
    rows.extend(f"{pointer}\t{kind}\t{count}" for (pointer, kind), count in sorted(counter.items()))
    atomic_write_text(path, "\n".join(rows) + "\n")


def verify_plan(plan_root: Path) -> tuple[dict[str, Any], str]:
    success_path = plan_root / "_SUCCESS.json"
    manifest_path = plan_root / "plan_file_hashes.tsv"
    if not success_path.is_file() or not manifest_path.is_file():
        raise RuntimeError("Certified acquisition plan is missing _SUCCESS.json or its hash manifest")
    success = json.loads(success_path.read_text(encoding="utf-8"))
    if success.get("status") != "PROFILE_ACQUISITION_PLAN_CERTIFIED_OK":
        raise RuntimeError("Acquisition plan is not certified")
    actual_manifest_sha = sha256_file(manifest_path)
    if actual_manifest_sha != success.get("plan_file_hashes_sha256"):
        raise RuntimeError("Acquisition plan hash-manifest SHA mismatch")
    with manifest_path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    for row in rows:
        path = plan_root / row["path"]
        if not path.is_file():
            raise RuntimeError(f"Plan file is missing: {path}")
        if path.stat().st_size != int(row["bytes"]) or sha256_file(path) != row["sha256"]:
            raise RuntimeError(f"Plan file authentication failed: {path}")
    return success, sha256_file(success_path)


def assignment_path(plan_root: Path, assignment: str) -> Path:
    mapping = {
        "single": "query_assignment_single.tsv",
        "work-ascending": "query_assignment_work_ascending.tsv",
        "home-descending": "query_assignment_home_descending.tsv",
    }
    if assignment not in mapping:
        raise RuntimeError(f"Unknown assignment: {assignment}")
    return plan_root / mapping[assignment]


def read_batches(path: Path, assignment: str) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    seen: set[str] = set()
    for row in rows:
        if row["batch_id"] in seen:
            raise RuntimeError("Assignment manifest contains a duplicate batch ID")
        seen.add(row["batch_id"])
        ids = row["request_ids_csv"].split(",") if row["request_ids_csv"] else []
        if len(ids) != int(row["n_users"]) or not (1 <= len(ids) <= BATCH_SIZE):
            raise RuntimeError(f"Malformed batch size for {row['batch_id']}")
        if len(ids) != len(set(ids)) or any(norm_user(user) != user for user in ids):
            raise RuntimeError(f"Malformed or duplicate user IDs in {row['batch_id']}")
        if sha256_text(row["request_ids_csv"]) != row["request_body_sha256"]:
            raise RuntimeError(f"Request body hash mismatch in {row['batch_id']}")
    if assignment == "home-descending":
        expected = sorted(
            rows,
            key=lambda row: (
                -int(row["macro_batch_index"]),
                int(row["request_index_within_macro"]),
            ),
        )
    else:
        expected = sorted(
            rows,
            key=lambda row: (
                int(row["macro_batch_index"]),
                int(row["request_index_within_macro"]),
            ),
        )
    if [row["batch_id"] for row in rows] != [row["batch_id"] for row in expected]:
        raise RuntimeError(f"Assignment manifest order is invalid for {assignment}")
    return rows


def load_attempt_ledger(fetch_root: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for path in sorted((fetch_root / "attempt_ledger").glob("*.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
            if row.get("post_counted_for_rate_limit"):
                result.append(row)
        except Exception as exc:
            raise RuntimeError(f"Unreadable attempt ledger entry {path}: {exc}") from exc
    return result


def quota_gate(ledger: list[dict[str, Any]], next_users: int, min_interval: float) -> None:
    while True:
        now = time.time()
        recent_day = sorted(
            (row for row in ledger if now - float(row["attempt_started_epoch"]) < 86_400),
            key=lambda row: float(row["attempt_started_epoch"]),
        )
        users_day = sum(int(row["n_requested"]) for row in recent_day)
        if users_day + next_users > DAY_SAFE_USERS:
            need_to_expire = users_day + next_users - DAY_SAFE_USERS
            expired = 0
            threshold = now + 86_400
            for row in recent_day:
                expired += int(row["n_requested"])
                if expired >= need_to_expire:
                    threshold = float(row["attempt_started_epoch"]) + 86_401
                    break
            raise DailyQuotaReached(iso_from_epoch(threshold))

        if ledger:
            latest = max(float(row["attempt_started_epoch"]) for row in ledger)
            interval_wait = latest + min_interval - now
            if interval_wait > 0:
                print(f"PACING_WAIT seconds={interval_wait:.1f}", flush=True)
                time.sleep(interval_wait)
                continue

        recent_ten = sorted(
            (row for row in ledger if now - float(row["attempt_started_epoch"]) < 600),
            key=lambda row: float(row["attempt_started_epoch"]),
        )
        users_ten = sum(int(row["n_requested"]) for row in recent_ten)
        if users_ten + next_users > TEN_MINUTE_SAFE_USERS:
            need_to_expire = users_ten + next_users - TEN_MINUTE_SAFE_USERS
            expired = 0
            threshold = now + 600
            for row in recent_ten:
                expired += int(row["n_requested"])
                if expired >= need_to_expire:
                    threshold = float(row["attempt_started_epoch"]) + 601
                    break
            wait = max(1.0, threshold - now)
            print(f"ROLLING_10_MINUTE_WAIT seconds={wait:.1f}", flush=True)
            time.sleep(wait)
            continue
        return


def retry_after_seconds(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            target = email.utils.parsedate_to_datetime(value)
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
            return max(0.0, target.timestamp() - time.time())
        except Exception:
            return 0.0


def safe_headers(headers: requests.structures.CaseInsensitiveDict[str]) -> tuple[dict[str, str], list[str]]:
    kept: dict[str, str] = {}
    redacted: list[str] = []
    for key, value in headers.items():
        if key.lower() in SENSITIVE_RESPONSE_HEADERS:
            redacted.append(key)
        else:
            kept[key] = value
    return kept, sorted(redacted)


def validate_payload(
    payload: Any, requested: list[str], batch: dict[str, str], queried_at: str
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(payload, list) or any(not isinstance(user, dict) for user in payload):
        raise RuntimeError("HTTP 200 response is not a JSON array of user objects")
    requested_set = set(requested)
    returned_ids: list[str] = []
    lookup: dict[str, dict[str, Any]] = {}
    for user in payload:
        user_id = norm_user(user.get("id") or user.get("username"))
        if not user_id:
            raise RuntimeError("Returned user object lacks id and username")
        if user_id in lookup:
            raise RuntimeError(f"Duplicate returned user ID: {user_id}")
        if user_id not in requested_set:
            raise RuntimeError(f"API returned an unrequested user ID: {user_id}")
        lookup[user_id] = user
        returned_ids.append(user_id)
    requested_positions = {user: index for index, user in enumerate(requested)}
    positions = [requested_positions[user] for user in returned_ids]
    returned_order_is_requested_subsequence = positions == sorted(positions)
    rows = [
        normalized_row(user, position, lookup.get(user), batch, queried_at)
        for position, user in enumerate(requested)
    ]
    diagnostics = {
        "requested_users": len(requested),
        "returned_users": len(payload),
        "unreturned_users": len(requested) - len(payload),
        "returned_order_is_requested_subsequence": returned_order_is_requested_subsequence,
        "duplicate_returned_users": 0,
        "extra_returned_users": 0,
    }
    return rows, diagnostics, payload


def verify_existing_batch(batch_dir: Path, batch: dict[str, str], plan_success_sha: str) -> bool:
    receipt_path = batch_dir / "SUCCESS.json"
    if not receipt_path.is_file():
        return False
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    checks = [
        receipt.get("status") == "PROFILE_BATCH_CERTIFIED_OK",
        receipt.get("batch_id") == batch["batch_id"],
        receipt.get("macro_batch_id") == batch["macro_batch_id"],
        receipt.get("macro_batch_index") == int(batch["macro_batch_index"]),
        receipt.get("request_body_sha256") == batch["request_body_sha256"],
        receipt.get("plan_success_sha256") == plan_success_sha,
    ]
    for key in ("normalized_parquet", "key_inventory", "response_body", "response_headers"):
        item = receipt.get(key) or {}
        path = batch_dir / str(item.get("path", ""))
        checks.append(path.is_file() and sha256_file(path) == item.get("sha256"))
    if not all(checks):
        raise RuntimeError(f"Existing batch receipt cannot be resumed safely: {batch_dir}")
    return True


def group_batches_by_macro(
    batches: list[dict[str, str]],
) -> list[tuple[str, list[dict[str, str]]]]:
    groups: list[tuple[str, list[dict[str, str]]]] = []
    for batch in batches:
        macro_id = batch["macro_batch_id"]
        if not groups or groups[-1][0] != macro_id:
            groups.append((macro_id, []))
        groups[-1][1].append(batch)
    seen: set[str] = set()
    for macro_id, rows in groups:
        if macro_id in seen:
            raise RuntimeError(f"Macro-batch is not contiguous in assignment: {macro_id}")
        seen.add(macro_id)
        request_indexes = [int(row["request_index_within_macro"]) for row in rows]
        if request_indexes != list(range(1, len(rows) + 1)):
            raise RuntimeError(f"Macro-batch request sequence is malformed: {macro_id}")
        planned = {int(row["macro_batch_planned_users"]) for row in rows}
        if len(planned) != 1 or sum(int(row["n_users"]) for row in rows) != next(iter(planned)):
            raise RuntimeError(f"Macro-batch user total is malformed: {macro_id}")
        if len(rows) > 400:
            raise RuntimeError(f"Macro-batch exceeds 400 API requests: {macro_id}")
    return groups


def inspect_local_completion(
    fetch_root: Path,
    groups: list[tuple[str, list[dict[str, str]]]],
    plan_success_sha: str,
) -> dict[str, Any]:
    completed_batch_ids: set[str] = set()
    complete_macros: list[dict[str, Any]] = []
    partial_macros: list[dict[str, Any]] = []
    for macro_id, rows in groups:
        receipt_lines: list[str] = []
        certified_times: list[str] = []
        completed_users = 0
        completed_ids: list[str] = []
        for batch in rows:
            batch_dir = fetch_root / "batches" / batch["batch_id"]
            if not verify_existing_batch(batch_dir, batch, plan_success_sha):
                continue
            receipt_path = batch_dir / "SUCCESS.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            completed_batch_ids.add(batch["batch_id"])
            completed_ids.append(batch["batch_id"])
            completed_users += int(batch["n_users"])
            receipt_lines.append(f"{batch['batch_id']}\t{sha256_file(receipt_path)}")
            certified_times.append(str(receipt.get("certified_utc", "")))
        if not completed_ids:
            continue
        detail = {
            "macro_batch_id": macro_id,
            "macro_batch_index": int(rows[0]["macro_batch_index"]),
            "planned_request_batches": len(rows),
            "planned_users": sum(int(row["n_users"]) for row in rows),
            "completed_request_batches": len(completed_ids),
            "completed_users": completed_users,
            "completed_batch_ids": completed_ids,
            "success_receipt_manifest_sha256": sha256_text("\n".join(receipt_lines) + "\n"),
            "latest_certified_utc": max(certified_times),
        }
        if len(completed_ids) == len(rows):
            complete_macros.append(detail)
        else:
            partial_macros.append(detail)
    return {
        "completed_batch_ids": completed_batch_ids,
        "complete_macros": complete_macros,
        "partial_macros": partial_macros,
    }


def add_payload_hash(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result["ledger_payload_sha256"] = sha256_text(canonical_json(payload))
    return result


def verify_payload_hash(payload: dict[str, Any], label: str) -> None:
    claimed = payload.get("ledger_payload_sha256")
    unhashed = dict(payload)
    unhashed.pop("ledger_payload_sha256", None)
    if not isinstance(claimed, str) or sha256_text(canonical_json(unhashed)) != claimed:
        raise RuntimeError(f"{label} payload hash is invalid")


def write_completion_ledger(
    fetch_root: Path,
    config: dict[str, Any],
    groups: list[tuple[str, list[dict[str, str]]]],
    local: dict[str, Any],
) -> tuple[dict[str, Any], Path, str]:
    complete_ids = [row["macro_batch_id"] for row in local["complete_macros"]]
    partial_ids = [row["macro_batch_id"] for row in local["partial_macros"]]
    payload = {
        "status": "PROFILE_COMPLETED_MACRO_LEDGER_OK",
        "ledger_version": 1,
        "created_utc": utc_now(),
        "created_epoch": time.time(),
        "fetch_root_uuid": config["fetch_root_uuid"],
        "assignment": config["assignment"],
        "plan_success_sha256": config["plan_success_sha256"],
        "fetcher_sha256": config["fetcher_sha256"],
        "catalog_macro_batches": len(groups),
        "catalog_request_batches": sum(len(rows) for _, rows in groups),
        "completed_macro_batch_ids": complete_ids,
        "partial_macro_batch_ids": partial_ids,
        "started_macro_batch_ids": complete_ids + partial_ids,
        "completed_batch_ids": sorted(local["completed_batch_ids"]),
        "completed_macro_batches": local["complete_macros"],
        "partial_macro_batches": local["partial_macros"],
        "coordination_contract": (
            "Peer may skip completed macros, must not enter a started macro, and must reject "
            "any duplicate completed request-batch ID."
        ),
    }
    ledger = add_payload_hash(payload)
    path = fetch_root / "completed_macro_batches.json"
    atomic_write_json(path, ledger)
    return ledger, path, sha256_file(path)


def load_peer_completion_ledgers(
    paths: list[Path],
    groups: list[tuple[str, list[dict[str, str]]]],
    plan_success_sha: str,
    local_fetch_root_uuid: str,
    local_fetcher_sha: str,
) -> dict[str, Any]:
    macro_map = {macro_id: rows for macro_id, rows in groups}
    batch_map = {row["batch_id"]: row for _, rows in groups for row in rows}
    completed_batch_ids: set[str] = set()
    completed_macro_ids: set[str] = set()
    started_macro_ids: set[str] = set()
    ledger_info: list[dict[str, Any]] = []
    seen_roots: set[str] = set()
    for raw_path in paths:
        path = raw_path.resolve()
        if not path.is_file():
            raise RuntimeError(f"Peer completion ledger does not exist: {path}")
        ledger = json.loads(path.read_text(encoding="utf-8"))
        verify_payload_hash(ledger, f"Peer ledger {path}")
        if ledger.get("status") != "PROFILE_COMPLETED_MACRO_LEDGER_OK":
            raise RuntimeError(f"Peer completion ledger has wrong status: {path}")
        if ledger.get("ledger_version") != 1:
            raise RuntimeError(f"Peer completion ledger has an unsupported version: {path}")
        if ledger.get("plan_success_sha256") != plan_success_sha:
            raise RuntimeError(f"Peer completion ledger belongs to another plan: {path}")
        if ledger.get("fetcher_sha256") != local_fetcher_sha:
            raise RuntimeError(f"Peer completion ledger was produced by another fetcher: {path}")
        if (
            ledger.get("catalog_macro_batches") != len(groups)
            or ledger.get("catalog_request_batches") != len(batch_map)
        ):
            raise RuntimeError(f"Peer completion ledger has the wrong catalog dimensions: {path}")
        peer_uuid = str(ledger.get("fetch_root_uuid", ""))
        if not peer_uuid or peer_uuid == local_fetch_root_uuid or peer_uuid in seen_roots:
            raise RuntimeError(f"Peer completion ledger has invalid or duplicate fetch-root UUID: {path}")
        seen_roots.add(peer_uuid)
        peer_batches = list(ledger.get("completed_batch_ids") or [])
        if len(peer_batches) != len(set(peer_batches)):
            raise RuntimeError(f"Peer completion ledger repeats request-batch IDs: {path}")
        for batch_id in peer_batches:
            if batch_id not in batch_map:
                raise RuntimeError(f"Peer completion ledger names an unknown request batch: {batch_id}")
            if batch_id in completed_batch_ids:
                raise RuntimeError(f"Two peer ledgers both claim request batch: {batch_id}")
            completed_batch_ids.add(batch_id)
        peer_complete = set(ledger.get("completed_macro_batch_ids") or [])
        peer_partial = set(ledger.get("partial_macro_batch_ids") or [])
        if peer_complete & peer_partial or not (peer_complete | peer_partial) <= set(macro_map):
            raise RuntimeError(f"Peer completion ledger has invalid macro-batch membership: {path}")
        represented_macros = {batch_map[batch_id]["macro_batch_id"] for batch_id in peer_batches}
        if represented_macros != peer_complete | peer_partial:
            raise RuntimeError(f"Peer completion ledger has inconsistent request/macro claims: {path}")
        if set(ledger.get("started_macro_batch_ids") or []) != represented_macros:
            raise RuntimeError(f"Peer completion ledger has inconsistent started-macro claims: {path}")
        for macro_id in peer_complete:
            expected_ids = {row["batch_id"] for row in macro_map[macro_id]}
            if not expected_ids <= set(peer_batches):
                raise RuntimeError(f"Peer ledger falsely marks macro complete: {macro_id}")
        for macro_id in peer_partial:
            expected_ids = {row["batch_id"] for row in macro_map[macro_id]}
            count = len(expected_ids & set(peer_batches))
            if count == 0 or count == len(expected_ids):
                raise RuntimeError(f"Peer ledger falsely marks macro partial: {macro_id}")
        completed_macro_ids.update(peer_complete)
        started_macro_ids.update(peer_complete | peer_partial)
        ledger_info.append(
            {
                "path": str(path),
                "sha256": sha256_file(path),
                "fetch_root_uuid": peer_uuid,
                "assignment": ledger.get("assignment"),
                "created_utc": ledger.get("created_utc"),
                "completed_request_batches": len(peer_batches),
                "completed_macro_batches": len(peer_complete),
                "partial_macro_batches": len(peer_partial),
            }
        )
    bundle_material = "\n".join(sorted(row["sha256"] for row in ledger_info))
    return {
        "completed_batch_ids": completed_batch_ids,
        "completed_macro_ids": completed_macro_ids,
        "started_macro_ids": started_macro_ids,
        "ledger_info": ledger_info,
        "bundle_sha256": sha256_text(bundle_material) if ledger_info else None,
    }


def select_active_macro(
    groups: list[tuple[str, list[dict[str, str]]]],
    local_partial_id: str | None,
    covered_batch_ids: set[str],
    peer_started_macro_ids: set[str],
    assignment: str,
    peer_ledger_supplied: bool,
    peer_offline_confirmed: bool,
) -> tuple[str | None, list[dict[str, str]], list[str]]:
    unresolved_macro_ids = [
        macro_id
        for macro_id, rows in groups
        if any(row["batch_id"] not in covered_batch_ids for row in rows)
    ]
    active_macro_id: str | None = None
    active_macro_rows: list[dict[str, str]] = []
    if local_partial_id is not None:
        active_macro_id = local_partial_id
        active_macro_rows = next(rows for macro, rows in groups if macro == local_partial_id)
    else:
        for macro_id, rows in groups:
            unresolved = [row for row in rows if row["batch_id"] not in covered_batch_ids]
            if not unresolved:
                continue
            if macro_id in peer_started_macro_ids and not peer_offline_confirmed:
                continue
            active_macro_id = macro_id
            active_macro_rows = rows
            break
    if (
        local_partial_id is None
        and len(unresolved_macro_ids) == 1
        and assignment == "home-descending"
        and peer_ledger_supplied
        and not peer_offline_confirmed
    ):
        # Deterministic convergence tie-break: when both directions see the
        # same final macro, work-ascending owns it.  Home retains the complete
        # catalog and can take over only after explicitly declaring work offline.
        active_macro_id = None
        active_macro_rows = []
    return active_macro_id, active_macro_rows, unresolved_macro_ids


def initialize_fetch_root(
    fetch_root: Path,
    plan_root: Path,
    assignment: str,
    plan_success_sha: str,
    assignment_sha: str,
    script_path: Path,
) -> dict[str, Any]:
    fetch_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    for directory in ("batches", "attempt_ledger", "runs"):
        (fetch_root / directory).mkdir(exist_ok=True, mode=0o700)
    config_path = fetch_root / "fetch_config.json"
    proposed = {
        "status": "PROFILE_FETCH_CONFIG_FROZEN",
        "created_utc": utc_now(),
        "fetch_root_uuid": uuid.uuid4().hex,
        "plan_root": str(plan_root.resolve()),
        "plan_success_sha256": plan_success_sha,
        "assignment": assignment,
        "assignment_sha256": assignment_sha,
        "fetcher_version": SCRIPT_VERSION,
        "fetcher_sha256": sha256_file(script_path),
        "api_url": API_URL,
        "batch_size": BATCH_SIZE,
        "ten_minute_safe_users": TEN_MINUTE_SAFE_USERS,
        "rolling_24_hour_safe_users": DAY_SAFE_USERS,
        "minimum_start_interval_seconds": MIN_START_INTERVAL_SECONDS,
        "lossless_capture": True,
        "response_header_exclusion": sorted(SENSITIVE_RESPONSE_HEADERS),
    }
    if config_path.exists():
        existing = json.loads(config_path.read_text(encoding="utf-8"))
        if not existing.get("fetch_root_uuid"):
            raise RuntimeError("Existing fetch-root configuration lacks fetch_root_uuid")
        for key in (
            "plan_success_sha256", "assignment", "assignment_sha256", "fetcher_sha256",
            "api_url", "batch_size", "ten_minute_safe_users", "rolling_24_hour_safe_users",
        ):
            if existing.get(key) != proposed.get(key):
                raise RuntimeError(f"Fetch-root configuration mismatch for {key}")
        return existing
    atomic_write_json(config_path, proposed)
    return proposed


def execute(args: argparse.Namespace, batches: list[dict[str, str]], plan_success_sha: str) -> dict[str, Any]:
    started = time.time()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"_{os.getpid()}"
    fetch_root = args.fetch_root.resolve()
    assignment = assignment_path(args.plan_root.resolve(), args.assignment)
    config = initialize_fetch_root(
        fetch_root,
        args.plan_root.resolve(),
        args.assignment,
        plan_success_sha,
        sha256_file(assignment),
        Path(__file__).resolve(),
    )
    groups = group_batches_by_macro(batches)
    local_before = inspect_local_completion(fetch_root, groups, plan_success_sha)
    peer = load_peer_completion_ledgers(
        list(args.peer_completion_ledger),
        groups,
        plan_success_sha,
        str(config["fetch_root_uuid"]),
        str(config["fetcher_sha256"]),
    )
    expected_peer_assignment = {
        "work-ascending": "home-descending",
        "home-descending": "work-ascending",
    }.get(args.assignment)
    if expected_peer_assignment is not None:
        wrong_peer_assignments = [
            row.get("assignment")
            for row in peer["ledger_info"]
            if row.get("assignment") != expected_peer_assignment
        ]
        if wrong_peer_assignments:
            raise RuntimeError(
                f"Expected peer assignment {expected_peer_assignment}; observed "
                f"{wrong_peer_assignments}"
            )
    exact_overlap = local_before["completed_batch_ids"] & peer["completed_batch_ids"]
    if exact_overlap:
        examples = sorted(exact_overlap)[:5]
        raise RuntimeError(
            f"Local and peer roots both completed {len(exact_overlap)} request batches; "
            f"examples={examples}"
        )
    local_started = {
        row["macro_batch_id"]
        for row in local_before["complete_macros"] + local_before["partial_macros"]
    }
    macro_overlap = local_started & peer["started_macro_ids"]
    combined_before_overlap_check = (
        local_before["completed_batch_ids"] | peer["completed_batch_ids"]
    )
    group_lookup = dict(groups)
    dangerous_macro_overlap = {
        macro_id
        for macro_id in macro_overlap
        if not {
            row["batch_id"] for row in group_lookup[macro_id]
        } <= combined_before_overlap_check
    }
    if dangerous_macro_overlap and not args.peer_offline_confirmed:
        raise RuntimeError(
            "Local and peer roots both entered the same macro-batch; refusing possible collision: "
            + ",".join(sorted(dangerous_macro_overlap))
        )

    covered_before = local_before["completed_batch_ids"] | peer["completed_batch_ids"]
    incomplete_local_partial_ids = [
        detail["macro_batch_id"]
        for detail in local_before["partial_macros"]
        if not {
            row["batch_id"] for row in group_lookup[detail["macro_batch_id"]]
        } <= covered_before
    ]
    if len(incomplete_local_partial_ids) > 1:
        raise RuntimeError(
            "More than one local macro-batch remains partially unresolved: "
            + ",".join(sorted(incomplete_local_partial_ids))
        )
    local_partial_id = incomplete_local_partial_ids[0] if incomplete_local_partial_ids else None
    active_macro_id, active_macro_rows, _unresolved_macro_ids = select_active_macro(
        groups,
        local_partial_id,
        covered_before,
        peer["started_macro_ids"],
        args.assignment,
        bool(peer["ledger_info"]),
        bool(args.peer_offline_confirmed),
    )

    coordination_path = fetch_root / "coordination_state.json"
    coordination = (
        json.loads(coordination_path.read_text(encoding="utf-8"))
        if coordination_path.exists()
        else {}
    )
    starting_new_macro = active_macro_id is not None and local_partial_id is None
    if starting_new_macro and args.assignment != "single":
        local_complete_count = len(local_before["complete_macros"])
        if (
            local_before["completed_batch_ids"]
            and not peer["ledger_info"]
            and not args.peer_offline_confirmed
        ):
            raise RuntimeError(
                "A refreshed peer completion ledger is required before starting the next macro-batch"
            )
        last_started = coordination.get("last_started_macro_batch_id")
        last_bundle = coordination.get("last_peer_ledger_bundle_sha256")
        if (
            last_started
            and last_started != active_macro_id
            and last_bundle == peer["bundle_sha256"]
            and not args.peer_offline_confirmed
        ):
            raise RuntimeError(
                "Peer completion ledger has not changed since the preceding macro-batch; "
                "synchronize a fresh ledger before continuing"
            )
        if len(groups) == 1 and not peer["ledger_info"] and not args.peer_offline_confirmed:
            raise RuntimeError(
                "A one-macro catalog cannot be started independently on two laptops; use single "
                "assignment or supply a coordinated peer ledger"
            )
        coordination = {
            "status": "PROFILE_MACRO_COORDINATION_STATE_OK",
            "updated_utc": utc_now(),
            "last_started_macro_batch_id": active_macro_id,
            "last_peer_ledger_bundle_sha256": peer["bundle_sha256"],
            "peer_ledger_paths": [row["path"] for row in peer["ledger_info"]],
            "peer_offline_confirmed": bool(args.peer_offline_confirmed),
            "local_complete_macro_batches_before_start": local_complete_count,
        }
        atomic_write_json(coordination_path, coordination)

    _, _, local_ledger_sha_before = write_completion_ledger(
        fetch_root, config, groups, local_before
    )
    batches_to_run = [
        row
        for row in active_macro_rows
        if row["batch_id"] not in covered_before
    ]
    state_path = fetch_root / "runtime_state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
    else:
        state = {"pacing_seconds": float(args.min_interval), "429_responses": 0}
    state["pacing_seconds"] = max(float(args.min_interval), float(state.get("pacing_seconds", args.min_interval)))

    ledger = load_attempt_ledger(fetch_root)
    completed_before = len(local_before["completed_batch_ids"])
    completed_this_run = 0
    status = (
        "PROFILE_FETCH_WAITING_FOR_PEER"
        if active_macro_id is None and len(covered_before) < len(batches)
        else "PROFILE_FETCH_COMBINED_COMPLETE"
        if active_macro_id is None
        else "PROFILE_FETCH_MACRO_BATCH_IN_PROGRESS"
    )
    next_eligible = None
    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "Content-Type": "text/plain; charset=utf-8",
            "User-Agent": "intrinsic-prosociality-research-profile-snapshot/1.0",
        }
    )
    try:
        for batch in batches_to_run:
            batch_dir = fetch_root / "batches" / batch["batch_id"]
            if verify_existing_batch(batch_dir, batch, plan_success_sha):
                continue
            if args.max_batches is not None and completed_this_run >= args.max_batches:
                status = "PROFILE_FETCH_RUN_BATCH_LIMIT_REACHED"
                break
            batch_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            requested = batch["request_ids_csv"].split(",")
            request_bytes = batch["request_ids_csv"].encode("utf-8")
            success = False
            existing_attempts = sorted(batch_dir.glob("attempt_*_receipt.json"))
            first_attempt = len(existing_attempts) + 1
            for attempt in range(first_attempt, MAX_ATTEMPTS_PER_BATCH + 1):
                try:
                    quota_gate(ledger, len(requested), float(state["pacing_seconds"]))
                except DailyQuotaReached as exc:
                    status = "PROFILE_FETCH_DAILY_CAP_REACHED"
                    next_eligible = exc.next_eligible_utc
                    raise

                attempt_started = time.time()
                attempt_label = f"attempt_{attempt:02d}"
                request_path = batch_dir / f"{attempt_label}_request.txt"
                response_path = batch_dir / f"{attempt_label}_response.body"
                headers_path = batch_dir / f"{attempt_label}_response_headers.json"
                receipt_path = batch_dir / f"{attempt_label}_receipt.json"
                atomic_write_bytes(request_path, request_bytes)
                attempt_receipt: dict[str, Any] = {
                    "status": "REQUEST_STARTED",
                    "batch_id": batch["batch_id"],
                    "batch_index": int(batch["batch_index"]),
                    "macro_batch_id": batch["macro_batch_id"],
                    "macro_batch_index": int(batch["macro_batch_index"]),
                    "request_index_within_macro": int(batch["request_index_within_macro"]),
                    "attempt": attempt,
                    "attempt_started_epoch": attempt_started,
                    "attempt_started_utc": iso_from_epoch(attempt_started),
                    "n_requested": len(requested),
                    "request_body_sha256": sha256_bytes(request_bytes),
                    "request_path": request_path.name,
                    "post_counted_for_rate_limit": True,
                    "api_url": API_URL,
                }
                atomic_write_json(receipt_path, attempt_receipt)
                ledger_copy = dict(attempt_receipt)
                ledger_path = fetch_root / "attempt_ledger" / f"{stamp}_{batch['batch_id']}_{attempt:02d}.json"
                atomic_write_json(ledger_path, ledger_copy)
                ledger.append(ledger_copy)

                response: requests.Response | None = None
                try:
                    response = session.post(API_URL, data=request_bytes, timeout=(15, args.timeout))
                    response_bytes = response.content
                    atomic_write_bytes(response_path, response_bytes)
                    kept_headers, redacted_headers = safe_headers(response.headers)
                    atomic_write_json(headers_path, kept_headers)
                    attempt_receipt.update(
                        {
                            "status": "HTTP_RESPONSE_RECEIVED",
                            "http_status": response.status_code,
                            "response_body_path": response_path.name,
                            "response_body_sha256": sha256_bytes(response_bytes),
                            "response_headers_path": headers_path.name,
                            "response_headers_sha256": sha256_file(headers_path),
                            "redacted_response_header_names": redacted_headers,
                            "elapsed_seconds": round(time.time() - attempt_started, 3),
                        }
                    )
                    atomic_write_json(receipt_path, attempt_receipt)
                    atomic_write_json(ledger_path, attempt_receipt)
                    ledger[-1] = dict(attempt_receipt)

                    if response.status_code == 200:
                        payload = json.loads(response_bytes.decode("utf-8"))
                        queried_at = utc_now()
                        rows, diagnostics, payload_users = validate_payload(
                            payload, requested, batch, queried_at
                        )
                        normalized_path = batch_dir / "normalized_users.parquet"
                        inventory_path = batch_dir / "json_key_inventory.tsv"
                        atomic_write_parquet(normalized_path, rows)
                        write_key_inventory(inventory_path, payload_users)
                        final_headers_path = batch_dir / "response_headers.json"
                        final_response_path = batch_dir / "response.body"
                        atomic_write_bytes(final_response_path, response_bytes)
                        atomic_write_json(final_headers_path, kept_headers)
                        success_receipt = {
                            "status": "PROFILE_BATCH_CERTIFIED_OK",
                            "certified_utc": utc_now(),
                            "batch_id": batch["batch_id"],
                            "batch_index": int(batch["batch_index"]),
                            "macro_batch_id": batch["macro_batch_id"],
                            "macro_batch_index": int(batch["macro_batch_index"]),
                            "request_index_within_macro": int(batch["request_index_within_macro"]),
                            "plan_success_sha256": plan_success_sha,
                            "request_body_sha256": batch["request_body_sha256"],
                            "attempt_count": attempt,
                            "query_diagnostics": diagnostics,
                            "normalized_parquet": {
                                "path": normalized_path.name,
                                "sha256": sha256_file(normalized_path),
                                "bytes": normalized_path.stat().st_size,
                            },
                            "key_inventory": {
                                "path": inventory_path.name,
                                "sha256": sha256_file(inventory_path),
                                "bytes": inventory_path.stat().st_size,
                            },
                            "response_body": {
                                "path": final_response_path.name,
                                "sha256": sha256_file(final_response_path),
                                "bytes": final_response_path.stat().st_size,
                            },
                            "response_headers": {
                                "path": final_headers_path.name,
                                "sha256": sha256_file(final_headers_path),
                                "bytes": final_headers_path.stat().st_size,
                            },
                            "response_header_redactions": redacted_headers,
                            "raw_capture_note": "Exact response entity bytes; Accept-Encoding identity requested.",
                        }
                        atomic_write_json(batch_dir / "SUCCESS.json", success_receipt)
                        completed_this_run += 1
                        success = True
                        if completed_this_run == 1 or completed_this_run % 25 == 0:
                            print(
                                f"FETCH_PROGRESS new_batches={completed_this_run:,} "
                                f"batch={batch['batch_id']} returned={diagnostics['returned_users']}/"
                                f"{diagnostics['requested_users']}",
                                flush=True,
                            )
                        break

                    if response.status_code not in RETRYABLE_STATUS:
                        raise RuntimeError(
                            f"Non-retryable HTTP status {response.status_code} for {batch['batch_id']}"
                        )
                    if response.status_code == 429:
                        state["429_responses"] = int(state.get("429_responses", 0)) + 1
                        state["pacing_seconds"] = max(36.0, float(state["pacing_seconds"]) * 1.5)
                        atomic_write_json(state_path, state)
                        wait = max(60.0, retry_after_seconds(response.headers.get("Retry-After")))
                    else:
                        wait = min(300.0, 30.0 * (2 ** (attempt - 1)))
                    wait += random.uniform(0.5, 2.0)
                    print(
                        f"RETRYABLE_HTTP status={response.status_code} attempt={attempt}/"
                        f"{MAX_ATTEMPTS_PER_BATCH} wait_seconds={wait:.1f}",
                        flush=True,
                    )
                    time.sleep(wait)
                except DailyQuotaReached:
                    raise
                except Exception as exc:
                    attempt_receipt.update(
                        {
                            "status": "REQUEST_OR_VALIDATION_EXCEPTION",
                            "exception_type": type(exc).__name__,
                            "exception_message": str(exc),
                            "elapsed_seconds": round(time.time() - attempt_started, 3),
                        }
                    )
                    atomic_write_json(receipt_path, attempt_receipt)
                    atomic_write_json(ledger_path, attempt_receipt)
                    ledger[-1] = dict(attempt_receipt)
                    if response is not None and response.status_code not in RETRYABLE_STATUS:
                        raise
                    if attempt >= MAX_ATTEMPTS_PER_BATCH:
                        raise RuntimeError(
                            f"Maximum attempts exceeded for {batch['batch_id']}: {exc}"
                        ) from exc
                    wait = min(300.0, 30.0 * (2 ** (attempt - 1))) + random.uniform(0.5, 2.0)
                    print(
                        f"REQUEST_EXCEPTION type={type(exc).__name__} attempt={attempt}/"
                        f"{MAX_ATTEMPTS_PER_BATCH} wait_seconds={wait:.1f}",
                        flush=True,
                    )
                    time.sleep(wait)
            if not success:
                raise RuntimeError(f"Batch did not reach certified success: {batch['batch_id']}")
    except DailyQuotaReached:
        pass
    finally:
        session.close()

    atomic_write_json(state_path, state)
    local_after = inspect_local_completion(fetch_root, groups, plan_success_sha)
    _, local_ledger_path, local_ledger_sha = write_completion_ledger(
        fetch_root, config, groups, local_after
    )
    total_completed = len(local_after["completed_batch_ids"])
    combined_completed_ids = local_after["completed_batch_ids"] | peer["completed_batch_ids"]
    remaining = len(batches) - len(combined_completed_ids)
    active_macro_complete = False
    if active_macro_id is not None:
        active_ids = {row["batch_id"] for row in active_macro_rows}
        active_macro_complete = active_ids <= combined_completed_ids
    if remaining == 0:
        status = "PROFILE_FETCH_COMBINED_COMPLETE"
    elif status not in {"PROFILE_FETCH_DAILY_CAP_REACHED", "PROFILE_FETCH_RUN_BATCH_LIMIT_REACHED"}:
        if active_macro_complete:
            status = "PROFILE_FETCH_MACRO_BATCH_COMPLETE"
        elif active_macro_id is None:
            status = "PROFILE_FETCH_WAITING_FOR_PEER"
        else:
            status = "PROFILE_FETCH_MACRO_BATCH_IN_PROGRESS"
    summary = {
        "status": status,
        "run_utc": utc_now(),
        "runtime_seconds": round(time.time() - started, 2),
        "fetch_root": str(fetch_root),
        "assignment": args.assignment,
        "assignment_batches": len(batches),
        "assignment_macro_batches": len(groups),
        "active_macro_batch_id": active_macro_id,
        "active_macro_batch_complete": active_macro_complete,
        "completed_before_run": completed_before,
        "completed_this_run": completed_this_run,
        "local_completed_total": total_completed,
        "peer_completed_total": len(peer["completed_batch_ids"]),
        "combined_completed_total": len(combined_completed_ids),
        "remaining_combined_batches": remaining,
        "local_completed_macro_batches": len(local_after["complete_macros"]),
        "local_partial_macro_batches": len(local_after["partial_macros"]),
        "peer_completed_macro_batches": len(peer["completed_macro_ids"]),
        "peer_started_macro_batches": len(peer["started_macro_ids"]),
        "peer_ledger_bundle_sha256": peer["bundle_sha256"],
        "peer_ledgers": peer["ledger_info"],
        "peer_offline_confirmed": bool(args.peer_offline_confirmed),
        "completion_ledger_path": str(local_ledger_path),
        "completion_ledger_sha256": local_ledger_sha,
        "completion_ledger_sha256_before_run": local_ledger_sha_before,
        "next_eligible_utc": next_eligible,
        "plan_success_sha256": plan_success_sha,
        "fetcher_sha256": sha256_file(Path(__file__).resolve()),
        "pacing_seconds_current": state["pacing_seconds"],
        "429_responses_recorded": state.get("429_responses", 0),
        "raw_and_personally_identifying_profile_data": "PRIVATE; DO NOT COMMIT OR PUBLISH",
    }
    atomic_write_json(fetch_root / "runs" / f"{stamp}_summary.json", summary)
    atomic_write_json(fetch_root / "latest_run_summary.json", summary)
    print(status)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


def self_test() -> None:
    batch = {"batch_id": "profile_v100_batch_000000", "batch_index": "0"}
    requested = ["alpha", "missing", "gamma"]
    payload = [
        {
            "id": "alpha",
            "username": "Alpha",
            "patron": True,
            "profile": {"realName": "A Name", "bio": "text", "flag": "US"},
            "perfs": {"blitz": {"rating": 1800, "games": 10}},
        },
        {"id": "gamma", "username": "Gamma", "disabled": True},
    ]
    rows, diagnostics, users = validate_payload(payload, requested, batch, utc_now())
    if len(rows) != 3 or diagnostics["returned_users"] != 2:
        raise RuntimeError("Fetcher normalization self-test row counts failed")
    if rows[0]["patron"] is not True or rows[1]["returned"] is not False:
        raise RuntimeError("Fetcher normalization self-test values failed")
    if "A Name" not in str(rows[0]["raw_user_json"]):
        raise RuntimeError("Fetcher did not preserve profile-identifying data losslessly")
    with tempfile_directory() as directory:
        path = directory / "test.parquet"
        atomic_write_parquet(path, rows)
        if pq.read_table(path).num_rows != 3:
            raise RuntimeError("Fetcher Parquet self-test failed")
        inventory = directory / "keys.tsv"
        write_key_inventory(inventory, users)
        if "/profile/realName" not in inventory.read_text(encoding="utf-8"):
            raise RuntimeError("Fetcher JSON-key inventory self-test failed")
    payload = add_payload_hash({"status": "test", "items": [1, 2, 3]})
    verify_payload_hash(payload, "self-test")
    groups = [
        ("macro_batch_0001", [{"batch_id": "b1"}]),
        ("macro_batch_0002", [{"batch_id": "b2"}]),
        ("macro_batch_0003", [{"batch_id": "b3"}]),
    ]
    active, _, _ = select_active_macro(
        groups, None, {"b1", "b3"}, set(), "work-ascending", True, False
    )
    if active != "macro_batch_0002":
        raise RuntimeError("Work convergence selection self-test failed")
    active, _, _ = select_active_macro(
        list(reversed(groups)), None, {"b1", "b3"}, set(), "home-descending", True, False
    )
    if active is not None:
        raise RuntimeError("Home convergence tie-break self-test failed")
    active, _, _ = select_active_macro(
        list(reversed(groups)), None, {"b1", "b3"}, set(), "home-descending", True, True
    )
    if active != "macro_batch_0002":
        raise RuntimeError("Home offline-takeover self-test failed")
    print("PROFILE_FETCHER_SELF_TEST_OK")


class tempfile_directory:
    def __enter__(self) -> Path:
        import tempfile

        self._context = tempfile.TemporaryDirectory()
        return Path(self._context.__enter__())

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Any:
        return self._context.__exit__(exc_type, exc, tb)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--plan-root", type=Path)
    result.add_argument("--fetch-root", type=Path)
    result.add_argument(
        "--assignment",
        choices=["single", "work-ascending", "home-descending"],
        default="single",
    )
    result.add_argument("--min-interval", type=float, default=MIN_START_INTERVAL_SECONDS)
    result.add_argument("--timeout", type=float, default=90.0)
    result.add_argument("--max-batches", type=int)
    result.add_argument(
        "--peer-completion-ledger",
        type=Path,
        action="append",
        default=[],
        help="Fresh completed_macro_batches.json copied from the other laptop",
    )
    result.add_argument(
        "--peer-offline-confirmed",
        action="store_true",
        help="Allow failover without a fresh peer ledger after confirming the peer is not running",
    )
    result.add_argument("--execute", action="store_true")
    result.add_argument("--self-test", action="store_true")
    return result


def main() -> None:
    os.umask(0o077)
    args = parser().parse_args()
    if args.self_test:
        self_test()
        return
    if args.plan_root is None or args.fetch_root is None:
        raise SystemExit("--plan-root and --fetch-root are required")
    if args.min_interval < MIN_START_INTERVAL_SECONDS:
        raise RuntimeError(f"Refusing min interval below {MIN_START_INTERVAL_SECONDS} seconds")
    _plan, plan_success_sha = verify_plan(args.plan_root.resolve())
    manifest = assignment_path(args.plan_root.resolve(), args.assignment)
    batches = read_batches(manifest, args.assignment)
    users = sum(int(batch["n_users"]) for batch in batches)
    macro_batches = len({batch["macro_batch_id"] for batch in batches})
    print("PROFILE_FETCH_PLAN_OK")
    print(f"script_version: {SCRIPT_VERSION}")
    print(f"script_sha256: {sha256_file(Path(__file__).resolve())}")
    print(f"plan_success_sha256: {plan_success_sha}")
    print(f"assignment: {args.assignment}")
    print(f"users: {users:,}")
    print(f"batches: {len(batches):,}")
    print(f"numbered_120k_macro_batches_for_this_assignment: {macro_batches:,}")
    print("macro_batches_processed_per_invocation: 1")
    print(f"peer_completion_ledgers_supplied: {len(args.peer_completion_ledger):,}")
    print(f"peer_offline_confirmed: {bool(args.peer_offline_confirmed)}")
    print(f"fetch_root: {args.fetch_root.resolve()}")
    print("capture: exact response bytes + every returned user object + common flattened fields")
    if not args.execute:
        print("No API requests were made. Re-run with --execute to begin or resume.")
        return
    execute(args, batches, plan_success_sha)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"PROFILE_FETCH_FAIL_CLOSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc()
        raise
