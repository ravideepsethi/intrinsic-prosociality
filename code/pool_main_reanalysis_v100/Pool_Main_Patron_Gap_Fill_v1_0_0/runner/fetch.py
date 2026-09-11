"""Serial HTTPS fetch with authenticated response replay and bounded retries."""
from __future__ import annotations

import email.utils
import hashlib
import json
import math
import ssl
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

from runner.normalizer import frozen as n
from source import pool_sample_common_v100 as auth

API_URL = "https://lichess.org/api/users?profile=true&rank=true"
MAX_ROUNDS = 3
ATTEMPTS_PER_ROUND_PER_INVOCATION = 4
MIN_INTERVAL = 30.0
OMISSION_WAIT = 60.0
RETRYABLE = {429, 500, 502, 503, 504}


class FetchStopped(RuntimeError):
    pass


class Clock:
    def time(self):
        return time.time()

    def sleep(self, seconds):
        time.sleep(seconds)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def https_post(usernames):
    # One public endpoint, no credentials, cookies, token, or profile writes.
    context = ssl.create_default_context()
    try:
        import certifi
    except ImportError:
        pass
    else:
        context.load_verify_locations(certifi.where())
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=context))
    request = urllib.request.Request(API_URL, method="POST",
        data=",".join(usernames).encode("utf-8"), headers={
            "Accept": "application/json", "Accept-Encoding": "identity",
            "Content-Type": "text/plain; charset=utf-8",
            "User-Agent": "lichess-kindness-profile-gap-fill/1.0 (research; serial requests)",
        })
    try:
        response = opener.open(request, timeout=45)
    except urllib.error.HTTPError as response:
        return response.code, dict(response.headers.items()), response.read()
    with response:
        return response.status, dict(response.headers.items()), response.read()


def wait_until(epoch, clock, log):
    while epoch > clock.time():
        remaining = epoch - clock.time()
        log(f"Waiting {math.ceil(remaining)} seconds before the next API request")
        clock.sleep(min(30.0, remaining))


def retry_after(headers, now):
    value = next((v for k, v in headers.items() if k.lower() == "retry-after"), None)
    if value is None:
        return 0.0
    try:
        duration = float(value)
        return max(0.0, duration) if math.isfinite(duration) else 0.0
    except ValueError:
        try:
            return max(0.0, email.utils.parsedate_to_datetime(value).timestamp() - now)
        except (ValueError, TypeError, OverflowError):
            return 0.0


def decode(body, requested, round_index, queried_at):
    payload = json.loads(body.decode("utf-8"))
    if isinstance(payload, list):
        for user in payload:
            if isinstance(user, dict) and "patron" in user and not isinstance(user["patron"], bool):
                raise FetchStopped("API Patron flag is not boolean")
    batch = {"batch_id": f"gap_round_{round_index}", "batch_index": str(round_index)}
    rows, diagnostics, users = n.validate_payload(payload, requested, batch, queried_at)
    return rows, diagnostics, users


def load_attempts(directory, config_sha):
    attempts = []
    for path in sorted(directory.glob("attempt_*")):
        if not path.is_dir():
            raise FetchStopped("Attempt path is not a directory")
        request_path = path / "REQUEST.json"
        if not request_path.exists():
            # Interrupted between mkdir and the atomic request record: no POST
            # could have occurred. Leave the empty directory and use a new ID.
            if any(path.iterdir()):
                raise FetchStopped("Attempt has files but no request record")
            continue
        request = auth.load_json(request_path)
        if request["config_sha256"] != config_sha:
            raise FetchStopped("Attempt configuration differs")
        receipt_path = path / "RESPONSE.json"
        receipt = auth.load_json(receipt_path) if receipt_path.is_file() else None
        if receipt:
            if receipt["request_sha256"] != auth.sha256_file(request_path):
                raise FetchStopped("Request checkpoint hash differs")
            body_path = path / "response_body.bin"
            if body_path.stat().st_size != receipt["body_bytes"] or auth.sha256_file(body_path) != receipt["body_sha256"]:
                raise FetchStopped("Response checkpoint hash differs")
        attempts.append((path, request, receipt))
    return attempts


def replay(directory, config_sha, usernames):
    best, latest, queries = {}, {}, Counter()
    first_request, last_request = {}, {}
    rounds = 0
    next_allowed = 0.0
    attempts = load_attempts(directory, config_sha)
    for path, request, receipt in attempts:
        remaining = [u for u in usernames if u not in best]
        if request["usernames"] != remaining or request["round"] != rounds + 1 or rounds >= MAX_ROUNDS:
            raise FetchStopped("Request is not the frozen remaining-account set")
        for user in remaining:
            queries[user] += 1
            first_request.setdefault(user, request["started_at_utc"])
            last_request[user] = request["started_at_utc"]
        next_allowed = max(next_allowed, request["started_epoch"] + MIN_INTERVAL)
        if receipt is None:
            # Unknown outcome after interruption: conservatively wait a minute
            # after start before retrying; the 45-second network timeout is shorter.
            next_allowed = max(next_allowed, request["started_epoch"] + 60.0)
            continue
        next_allowed = max(next_allowed, receipt["next_allowed_epoch"])
        status = receipt["http_status"]
        if status == 200:
            rows, diagnostics, payload = decode((path / "response_body.bin").read_bytes(),
                remaining, rounds + 1, request["started_at_utc"])
            # Regenerate incomplete normalized derivatives from durable raw bytes.
            normalized = path / "normalized_private.parquet"
            if not normalized.exists():
                n.atomic_write_parquet(normalized, rows)
            elif n.pq.read_table(normalized).to_pylist() != rows:
                raise FetchStopped("Normalized response differs from authenticated raw response")
            for row in rows:
                latest[row["username_norm"]] = row
                if row["returned"]:
                    best.setdefault(row["username_norm"], row)
            rounds += 1
        elif status is not None and status not in RETRYABLE:
            raise FetchStopped(f"HTTP {status}: response saved privately; no automatic retry")
    return {"best": best, "latest": latest, "queries": queries, "rounds": rounds,
        "next_allowed": next_allowed, "attempts": attempts,
        "first_request": first_request, "last_request": last_request}


def quota_time(attempts, count, now):
    # Conservatively retain the original producer's operational ceilings, also
    # across restarts. These apply to this runner; no other profile job should run.
    until = now
    for span, limit in ((600.0, 7800), (86400.0, 120000)):
        entries = sorted((req["started_epoch"], len(req["usernames"])) for _, req, _ in attempts
                         if req["started_epoch"] > now - span)
        total = count + sum(nusers for _, nusers in entries)
        for start, nusers in entries:
            if total <= limit:
                break
            until = max(until, start + span + 0.1)
            total -= nusers
    return until


def recover_interrupted(directory, config_sha, clock):
    for path, request, receipt in load_attempts(directory, config_sha):
        if receipt is not None:
            continue
        body = path / "response_body.bin"
        if body.exists():
            body.rename(path / "uncommitted_response_body.bin")
        n.atomic_write_bytes(body, b"")
        now = clock.time()
        auth.atomic_json(path / "RESPONSE.json", {
            "request_sha256": auth.sha256_file(path / "REQUEST.json"),
            "http_status": None, "headers": {}, "redacted_header_names": [],
            "transport_error_type": "InterruptedBeforeResponseCommit",
            "completed_at_utc": n.iso_from_epoch(now), "completed_epoch": now,
            "next_allowed_epoch": now + 60.0, "body_bytes": 0,
            "body_sha256": hashlib.sha256(b"").hexdigest(),
        })


def run_fetch(directory, config_sha, usernames, *, transport=https_post, clock=None, log=print):
    if not usernames or len(usernames) > 300 or len(set(usernames)) != len(usernames):
        raise FetchStopped("Target must have 1-300 unique accounts")
    if any(u != n.norm_user(u) or not u or "," in u or any(c.isspace() for c in u) for u in usernames):
        raise FetchStopped("Target identities are malformed")
    directory.mkdir(parents=True, exist_ok=True)
    clock = clock or Clock()
    recover_interrupted(directory, config_sha, clock)
    round_attempts = Counter()
    while True:
        state = replay(directory, config_sha, usernames)
        remaining = [u for u in usernames if u not in state["best"]]
        if not remaining or state["rounds"] == MAX_ROUNDS:
            return state
        round_index = state["rounds"] + 1
        if round_attempts[round_index] >= ATTEMPTS_PER_ROUND_PER_INVOCATION:
            raise FetchStopped("Transport attempts exhausted; rerun to resume the same remaining accounts")
        wait_until(max(state["next_allowed"], quota_time(state["attempts"], len(remaining), clock.time())), clock, log)
        indexes = [int(p.name.split("_")[-1]) for p in directory.glob("attempt_*")]
        path = directory / f"attempt_{max(indexes, default=0)+1:06d}"
        path.mkdir()
        now = clock.time()
        request = {"config_sha256": config_sha, "url": API_URL, "method": "POST",
            "round": round_index, "started_epoch": now, "started_at_utc": n.iso_from_epoch(now),
            "usernames": remaining}
        auth.atomic_json(path / "REQUEST.json", request)
        round_attempts[round_index] += 1
        log(f"Profile fetch round {round_index}/{MAX_ROUNDS}: {len(remaining)} accounts")
        error = None
        try:
            status, headers, body = transport(remaining)
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            status, headers, body = None, {}, b""
            error = type(exc).__name__
        ended = clock.time()
        cleaned_headers, redacted = n.safe_headers(headers)
        delay = OMISSION_WAIT if status == 200 else max(60.0, 30.0 * 2 ** (round_attempts[round_index] - 1))
        delay = max(delay, retry_after(headers, ended))
        n.atomic_write_bytes(path / "response_body.bin", body)
        auth.atomic_json(path / "RESPONSE.json", {
            "request_sha256": auth.sha256_file(path / "REQUEST.json"),
            "http_status": status, "headers": cleaned_headers, "redacted_header_names": redacted,
            "transport_error_type": error, "completed_at_utc": n.iso_from_epoch(ended),
            "completed_epoch": ended, "next_allowed_epoch": ended + delay,
            "body_bytes": len(body), "body_sha256": hashlib.sha256(body).hexdigest(),
        })
        if status != 200:
            log(f"Request returned {status if status is not None else error}; response retained for resume")


def supplement_rows(targets, state):
    rows = []
    for target in targets:
        user = target["username_norm"]
        row = dict(state["best"].get(user) or state["latest"].get(user) or
            n.normalized_row(user, 0, None, {"batch_id": "no_successful_response", "batch_index": "0"}, None))
        if user not in state["latest"]:
            row["http_status"] = None
        row.update({k: target[k] for k in ("gap_reason", "new_role", "new_match_cell", "primary_fair_kind_group")})
        row.update({"observation_source": "current_profile_gap_fill",
            "august_outcome_recovered": False,
            "first_request_at_utc": state["first_request"].get(user),
            "last_request_at_utc": state["last_request"].get(user),
            "request_count": state["queries"].get(user, 0)})
        rows.append(row)
    return rows


def aggregate(rows):
    result = []
    for scope in ("all_target_groups", "primary_fair_kind_groups"):
        for role in ("kind", "control"):
            for reason in ("not_planned_in_august", "queried_nonreturn"):
                selected = [r for r in rows if r["new_role"] == role and r["gap_reason"] == reason
                            and (scope == "all_target_groups" or r["primary_fair_kind_group"])]
                recovered = sum(bool(r["returned"]) for r in selected)
                result.append({"scope": scope, "role": role, "august_gap_reason": reason,
                    "target_accounts": len(selected), "current_profiles_returned": recovered,
                    "still_unavailable": len(selected) - recovered})
    return result
