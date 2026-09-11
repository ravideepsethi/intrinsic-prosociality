"""Authenticate the fixed Wave-3A gaps, acquire current profiles, export counts."""
from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import io
import json
import os
import sys
import tempfile
import time
import traceback
import zipfile
from collections import Counter
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from runner import fetch
from runner.normalizer import frozen as n
from source import pool_sample_common_v100 as auth
from source import wave3a_design as prior

ROOT = Path(__file__).resolve().parents[1]
WAVE3A_ZIP_SHA = "f56407f3de5bdd02366df28858e689da5f10a05c657f6c5e2feb71a7e227a592"
WAVE3A_CONFIG = "f9dfa2718056083161d58175b5907e1a8b2dfbbc58a1244c45c878c78c3bd238"
VERSION = "1.0.0"
eq, q, log = prior.require_equal, prior.q, prior.log


def bundled_authority():
    path = ROOT / "evidence/WAVE3A_RESULTS.zip"
    eq(auth.sha256_file(path), WAVE3A_ZIP_SHA, "Wave-3A report SHA-256")
    with zipfile.ZipFile(path) as archive:
        eq(archive.testzip(), None, "Wave-3A CRC")
        manifest = next(n for n in archive.namelist() if n.endswith("/REPORT_FILE_HASHES.tsv"))
        prefix = manifest.rsplit("/", 1)[0] + "/"
        entries = list(csv.DictReader(io.StringIO(archive.read(manifest).decode()), delimiter="\t"))
        eq(len(entries), 10, "Wave-3A manifest count")
        eq(set(archive.namelist()), {prefix + row["relative_path"] for row in entries} | {manifest}, "Wave-3A inventory")
        for row in entries:
            data = archive.read(prefix + row["relative_path"])
            eq(len(data), int(row["bytes"]), "Wave-3A member bytes")
            eq(hashlib.sha256(data).hexdigest(), row["sha256"], "Wave-3A member hash")
        status = json.loads(archive.read(prefix + "WAVE3A_RUN_STATUS.json"))
        configuration = json.loads(archive.read(prefix + "CONFIGURATION.json"))
    eq(hashlib.sha256(auth.canonical_json(configuration).encode()).hexdigest(), WAVE3A_CONFIG, "Wave-3A config")
    eq(status["status"], "PATRON_WAVE3A_DESIGN_INPUTS_COMPLETE", "Wave-3A status")
    return configuration, status


def validate_target_counts(rows):
    eq(len(rows), 285, "all missing accounts")
    eq(len({r["username_norm"] for r in rows}), 285, "unique missing identities")
    observed = Counter((r["new_role"], r["gap_reason"], bool(r["primary_fair_kind_group"])) for r in rows)
    expected = Counter({
        ("control", "not_planned_in_august", True): 77,
        ("control", "not_planned_in_august", False): 45,
        ("control", "queried_nonreturn", True): 100,
        ("control", "queried_nonreturn", False): 26,
        ("kind", "queried_nonreturn", True): 30,
        ("kind", "queried_nonreturn", False): 7,
    })
    eq(observed, expected, "frozen gap decomposition")


def authenticate_targets(project):
    configuration, status = bundled_authority()
    state = project / "derived/replication/pool_main_reanalysis_v100_PRIVATE/wave3a_patron" / WAVE3A_CONFIG[:12]
    eq(auth.load_json(state / "CONFIGURATION.json"), configuration, "local Wave-3A configuration")
    log("Authenticating Wave-3A private coverage, matching and history checkpoints")
    for name, expected in status["checkpoint_receipts"].items():
        eq(prior.read_checkpoint(state / name, WAVE3A_CONFIG), expected, "Wave-3A " + name)
    snapshot = prior.authenticate_snapshot(project)
    target = state / "coverage/target_coverage_private.parquet"
    with duckdb.connect() as db:
        db.execute("SET threads=2")
        rows = prior.records(db, f"""SELECT username_norm, new_role, new_match_cell,
            primary_fair_kind_group, matched_kind_chooser_id, control_slot,
            CASE WHEN NOT august_planned THEN 'not_planned_in_august'
              ELSE 'queried_nonreturn' END AS gap_reason
            FROM read_parquet({q(target)}, hive_partitioning=false)
            WHERE NOT coalesce(august_returned,false) ORDER BY username_norm""")
    validate_target_counts(rows)
    return rows, snapshot, auth.sha256_file(target)


def write_parquet(path, rows, schema=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), temporary, compression="zstd")
    temporary.replace(path)


def write_tsv(path, rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    auth.atomic_text(path, stream.getvalue())


def build_report(directory, *, rows, configuration, config_sha, state, complete, private_files, elapsed):
    directory.mkdir(parents=True, exist_ok=True)
    returned = sum(bool(r["returned"]) for r in rows)
    primary_returned = sum(bool(r["returned"]) for r in rows if r["primary_fair_kind_group"])
    dates = sorted(r["queried_at_utc"] for r in rows if r["returned"])
    status = ("ALL_GAPS_HAVE_CURRENT_PROFILES" if returned == len(rows) else
              "COMPLETE_WITH_UNAVAILABLE_ACCOUNTS") if complete else "REQUESTS_INCOMPLETE_RESUME_REQUIRED"
    result = {"status": status, "version": VERSION, "config_sha256": config_sha,
        "target_accounts": len(rows), "current_profiles_returned": returned,
        "still_unavailable": len(rows)-returned,
        "primary_target_accounts": sum(bool(r["primary_fair_kind_group"]) for r in rows),
        "primary_current_profiles_returned": primary_returned,
        "primary_still_unavailable": sum(bool(r["primary_fair_kind_group"]) for r in rows)-primary_returned,
        "successful_response_rounds": state["rounds"], "network_attempts": len(state["attempts"]),
        "observation_start_utc": dates[0] if dates else None,
        "observation_end_utc": dates[-1] if dates else None,
        "august_snapshot_modified": False, "august_outcomes_recovered": 0,
        "august_missing_primary_unchanged": 207, "august_missing_all_unchanged": 285,
        "models_run": False, "sample_or_matching_changed": False,
        "elapsed_seconds_this_invocation": elapsed,
        "analysis_disposition": "Separately dated current-profile supplement; does not close the frozen August coverage gate.",
        "private_file_receipts": private_files,
    }
    auth.atomic_json(directory / "GAP_FILL_RUN_STATUS.json", result)
    auth.atomic_json(directory / "CONFIGURATION.json", configuration)
    write_tsv(directory / "coverage.tsv", fetch.aggregate(rows))
    auth.atomic_text(directory / "SUMMARY.md", f"""# Patron profile gap fill

Status: {status}

Current profiles returned for {returned} of {len(rows)} frozen missing accounts;
{len(rows)-returned} remain unavailable. In the primary comparison, {primary_returned}
of 207 gaps returned current profiles. Successful HTTP-200 rounds: {state['rounds']}.

These are observations made during this run, not recovered August observations.
The original August snapshot and all matching assignments remain unchanged.
An unavailable profile has an unknown Patron outcome, never an imputed zero.
The archive contains aggregate coverage and file receipts only. Account IDs,
response bodies, normalized profiles and the supplement remain on XT_Pro.

No Patron models were run. The August-only and supplemented analyses must be
reported separately; a later estimator must explicitly bind this supplement.
Do not interpret a completed fetch with unavailable accounts as complete coverage.
""")
    files = [{"relative_path": p.name, "bytes": p.stat().st_size, "sha256": auth.sha256_file(p)}
             for p in sorted(directory.iterdir()) if p.is_file() and p.name != "REPORT_FILE_HASHES.tsv"]
    write_tsv(directory / "REPORT_FILE_HASHES.tsv", files)
    return result


def execute(args):
    started = time.monotonic()
    project = Path(args.project_root).expanduser().resolve()
    transfer = Path(args.transfer_dir).expanduser().resolve()
    if not project.is_dir():
        raise RuntimeError("Project directory missing; connect XT_Pro")
    auth.verify_package_manifest(ROOT)
    auth.verify_report_package()
    for binding in json.loads((ROOT / "authority/SOURCE_BINDINGS.json").read_text()):
        eq(auth.sha256_file(ROOT / binding["packaged_path"]), binding["sha256"], "source binding")
    targets, snapshot, coverage_sha = authenticate_targets(project)
    configuration = {"version": VERSION, "wave3a_config_sha256": WAVE3A_CONFIG,
        "wave3a_report_sha256": WAVE3A_ZIP_SHA, "august_snapshot_sha256": prior.SNAPSHOT_SHA,
        "coverage_sha256": coverage_sha,
        "target_records_sha256": hashlib.sha256(auth.canonical_json(targets).encode()).hexdigest(),
        "package_manifest_sha256": auth.sha256_file(ROOT / "PACKAGE_MANIFEST.sha256"),
        "api_url": fetch.API_URL, "target_count": 285, "primary_target_count": 207,
        "max_successful_response_rounds": fetch.MAX_ROUNDS,
        "max_transport_attempts_per_round_per_invocation": fetch.ATTEMPTS_PER_ROUND_PER_INVOCATION,
        "minimum_start_interval_seconds": fetch.MIN_INTERVAL, "omission_retry_delay_seconds": fetch.OMISSION_WAIT,
        "first_successful_response_retained": True, "query_scope": "frozen_285_missing_accounts_only",
        "profile_dates": "actual request start UTC", "august_snapshot_write_authorized": False}
    config_sha = hashlib.sha256(auth.canonical_json(configuration).encode()).hexdigest()
    private = project / "derived/replication/pool_main_reanalysis_v100_PRIVATE/patron_gap_fill_v100" / config_sha[:12]
    private.mkdir(parents=True, exist_ok=True)
    usernames = [r["username_norm"] for r in targets]
    with (private / "RUN.lock").open("a") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("This gap fill is already running") from exc
        try:
            config_path = private / "CONFIGURATION.json"
            if config_path.exists():
                eq(auth.load_json(config_path), configuration, "gap-fill resume configuration")
            else:
                auth.atomic_json(config_path, configuration)
            plan_path = private / "gap_targets_private.parquet"
            if plan_path.exists():
                eq(pq.read_table(plan_path).to_pylist(), targets, "private target plan unchanged")
            else:
                write_parquet(plan_path, targets)
            log("Authenticated 285 gaps (207 primary); the first request will query only these accounts")
            log(f"Private checkpoints: {private}")
            if not args.execute:
                log("Preflight complete. Add --execute to perform the authorized profile requests.")
                return 0
            complete = True
            try:
                state = fetch.run_fetch(private / "requests", config_sha, usernames, log=log)
            except fetch.FetchStopped:
                # Replay succeeds for exhausted transient failures. Invalid or
                # contradictory responses fail again here and stop certification.
                state = fetch.replay(private / "requests", config_sha, usernames)
                complete = False
            rows = fetch.supplement_rows(targets, state)
            schema = n.NORMALIZED_SCHEMA.append(pa.field("gap_reason", pa.string()))
            for name, dtype in (("new_role", pa.string()), ("new_match_cell", pa.string()),
                ("primary_fair_kind_group", pa.bool_()), ("observation_source", pa.string()),
                ("august_outcome_recovered", pa.bool_()), ("first_request_at_utc", pa.string()),
                ("last_request_at_utc", pa.string()), ("request_count", pa.int64())):
                schema = schema.append(pa.field(name, dtype))
            supplement = private / "current_profile_gap_supplement_private.parquet"
            write_parquet(supplement, rows, schema)
            eq(auth.sha256_file(snapshot), prior.SNAPSHOT_SHA, "August snapshot unchanged after fetch")
            receipts = [{"name": p.name, "bytes": p.stat().st_size, "sha256": auth.sha256_file(p)}
                        for p in (plan_path, supplement)]
            request_receipts = []
            for path in sorted((private / "requests").rglob("*")):
                if path.is_file():
                    request_receipts.append({"relative_path": path.relative_to(private).as_posix(),
                        "bytes": path.stat().st_size, "sha256": auth.sha256_file(path)})
            auth.atomic_json(private / "REQUEST_FILE_HASHES.json", request_receipts)
            receipts.append({"name": "REQUEST_FILE_HASHES.json", "sha256": auth.sha256_file(private / "REQUEST_FILE_HASHES.json"),
                "bytes": (private / "REQUEST_FILE_HASHES.json").stat().st_size})
            name = "POOL_MAIN_PATRON_GAP_FILL_RESULTS_" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "_" + config_sha[:12]
            public = project / "output/pool_main_reanalysis_v100/patron_gap_fill_v100" / name
            public.mkdir(parents=True, exist_ok=False)
            result = build_report(public, rows=rows, configuration=configuration, config_sha=config_sha,
                state=state, complete=complete, private_files=receipts, elapsed=time.monotonic()-started)
            transfer.mkdir(parents=True, exist_ok=True)
            archive_path = transfer / (name + ".zip")
            with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
                for p in sorted(public.iterdir()):
                    archive.write(p, name + "/" + p.name)
            with zipfile.ZipFile(archive_path) as archive:
                eq(archive.testzip(), None, "result ZIP CRC")
            auth.atomic_text(Path(str(archive_path) + ".sha256"), auth.sha256_file(archive_path) + "  " + archive_path.name + "\n")
            log(f"{result['status']}: {result['current_profiles_returned']}/285 current profiles returned")
            log(f"Upload: {archive_path}")
            log(f"Upload: {archive_path}.sha256")
            return 0 if complete else 2
        except Exception:
            auth.atomic_text(private / "PRIVATE_ERROR.txt", traceback.format_exc())
            log(f"Stopped. Detailed error saved privately at {private / 'PRIVATE_ERROR.txt'}")
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default="/Volumes/XT_Pro/lichess_kindness")
    parser.add_argument("--transfer-dir", default=str(Path.home() / "Desktop/Lichess_Desktop"))
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        return execute(args)
    except Exception as exc:
        # Do not print an exception containing returned account identifiers into
        # the Desktop log; the private diagnostic above keeps full detail.
        log(f"STOPPED ({type(exc).__name__}). Preserve the log and private checkpoints.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
