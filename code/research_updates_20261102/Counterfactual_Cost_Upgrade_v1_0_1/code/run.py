#!/usr/bin/env python3
from __future__ import annotations

# Set BEFORE importing array libraries and before spawning workers.
import os
for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[name] = "1"

import argparse
import concurrent.futures as cf
import multiprocessing as mp
from pathlib import Path
import platform
import shutil
import sys
import time
import traceback

import numpy as np
import pyarrow as pa
import duckdb

from engine import require
from support import (ROOT, VERSION, EXPECTED_EXCLUDED_ROWS, authenticate, verify_package,
    record, read_json, write_json, digest, canonical, stamp, sha, now, log, lock,
    heartbeat, bundle_report)
from worker import BASE_COLUMNS, process_month
from reporting import make_report, dataset_manifest


def progress_estimate(items, completed, run, start):
    total = sum(x["rows"] for x in items)
    done_months = {s["month"] for s in completed}
    done = sum(x["rows"] for x in items if x["month"] in done_months)
    for x in items:
        if x["month"] not in done_months:
            p = run / "months" / x["month"] / "progress.json"
            if p.is_file():
                try:
                    done += min(x["rows"], read_json(p)["input_rows_done"])
                except (ValueError, OSError, KeyError):
                    pass
    elapsed = time.monotonic()-start
    if done <= 0 or elapsed < 5:
        return f"{len(completed)}/24 months complete; estimating ETA"
    speed = done/elapsed
    finish = max(0, total-done)/speed/60
    next_percent = next((p for p in (25,50,75,100) if len(completed) < 24*p/100), 100)
    next_rows = max(0, total*next_percent/100-done)
    return (f"{len(completed)}/24 months complete; {100*done/total:.1f}% rows processed; "
            f"ETA next {next_percent}% checkpoint about {next_rows/speed/60:.1f} min; "
            f"ETA month processing finish about {finish:.1f} min, then final summaries")


def execute(items, config, expected_rows=None):
    run, desktop = Path(config["run_root"]), Path(config["desktop"])
    run.mkdir(parents=True, exist_ok=True)
    with lock(run / "run.lock"):
        success = run / "_SUCCESS.json"
        if success.is_file():
            receipt = read_json(success)
            require(receipt["fingerprint"] == config["fingerprint"], "Completed run identity mismatch")
            with heartbeat("Verifying completed outputs for reuse"):
                for r in receipt["files"]:
                    require(Path(r["path"]).is_file() and sha(r["path"]) == r["sha256"], "Completed output is corrupt")
            report = run / "reports/checkpoint_100"
            archive = Path(receipt["report_zip"])
            if not archive.is_file() or sha(archive) != receipt["report_sha256"]:
                archive = bundle_report(report, desktop, config["fingerprint"], 100)
                receipt["report_zip"] = str(archive)
                receipt["report_sha256"] = sha(archive)
                write_json(success, receipt)
            log(f"COST_UPGRADE_ALREADY_COMPLETE: {archive}")
            return receipt
        start = time.monotonic(); completed=[]; emitted=set()
        # Old progress files are not counted until the corresponding worker checks
        # its receipt or begins a fresh month. Completed checkpoints remain intact.
        for x in items:
            progress = run / "months" / x["month"] / "progress.json"
            if progress.is_file():
                progress.unlink()
        workers = min(config["workers"], len(items))
        with cf.ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn")) as pool:
            pending = {pool.submit(process_month, x, config):x["month"] for x in items}
            while pending:
                done, _ = cf.wait(pending, timeout=20, return_when=cf.FIRST_COMPLETED)
                for f in done:
                    month = pending.pop(f)
                    s = f.result(); completed.append(s)
                    log(f"Month {month}: {s['counts']['rows']:,} retained rows; checkpoint saved")
                    count = s["counts"]
                    if count.get("material_rule_disagreements") or count.get("material_result_conflicts"):
                        log(f"Material audit {month}: {count.get('material_rule_disagreements', 0):,} historical/platform differences; "
                            f"{count.get('material_result_conflicts', 0):,} unresolved win conflicts (action costs NULL)")
                log(progress_estimate(items, completed, run, start))
                for percent in (25,50,75):
                    if len(completed) >= len(items)*percent/100 and percent not in emitted:
                        # Completed months only; unfinished months never enter a partial report.
                        report, _ = make_report(completed, config, percent)
                        archive = bundle_report(report, desktop, config["fingerprint"], percent)
                        emitted.add(percent)
                        log(f"CHECKPOINT {percent}%: {archive.name}")
        require(len(completed) == len(items), "Incomplete monthly computation")
        retained = sum(s["counts"]["rows"] for s in completed)
        if expected_rows is not None:
            require(retained == expected_rows, f"Unexpected author-free sample size: {retained:,}")
        require(sum(s["counts"]["actual_draws"]+s["counts"]["chooser_claimed_wins"]+
                    s["counts"]["chooser_losses"] for s in completed) == retained, "Outcome partition mismatch")
        log("All monthly Parquets complete. Checking unique IDs and computing exact cost quantiles.")
        with heartbeat("Final summaries and output validation"):
            report, totals = make_report(completed, config, 100, final=True)
        for x in items:
            require(stamp(x["path"]) == x["stamp"], "Input changed before final completion")
        manifest_path = run / "COST_CANDIDATES_READY_PRIVATE.json"
        write_json(manifest_path, dataset_manifest(completed, config, totals))
        archive = bundle_report(report, desktop, config["fingerprint"], 100)
        # Bind all month outputs and all final aggregate files for safe reuse.
        files = [record(manifest_path)] + [s["output"] for s in completed]
        files += [record(p) for p in sorted(report.rglob("*")) if p.is_file()]
        result = {"status":"COUNTERFACTUAL_COST_AUDIT_COMPLETE", "fingerprint":config["fingerprint"],
                  "files":files, "report_zip":str(archive), "report_sha256":sha(archive),
                  "elapsed_seconds":time.monotonic()-start, "finished":now()}
        write_json(success, result)
        log(f"CHECKPOINT 100%: {archive.name}")
        log(f"COST_UPGRADE_OK: {retained:,} rows. Report: {archive}")
        log(f"Private cost Parquets and join manifest: {manifest_path}")
        return result


def main(argv=None):
    p = argparse.ArgumentParser(description="Cached-state counterfactual cost audit; no API, engine, or historical replay")
    p.add_argument("--project-root", type=Path, default=Path("/Volumes/XT_Pro/lichess_kindness"))
    p.add_argument("--desktop", type=Path, default=Path.home()/"Desktop/Lichess_Desktop")
    p.add_argument("--manifest", type=Path, help="Existing author-excluded ready manifest, if relocated")
    p.add_argument("--sample-root", type=Path, help="Explicit original certified sample root; applies author filter")
    p.add_argument("--workers", type=int, default=10)
    p.add_argument("--hash-workers", type=int, default=2)
    p.add_argument("--memory-gb", type=int, default=11)
    p.add_argument("--batch-rows", type=int, default=32768)
    p.add_argument("--bot-status", type=Path, help="Optional documented username_norm/is_bot Parquet")
    p.add_argument("--factor-calendar", type=Path, help="Optional evidence-backed historical multiplier calendar JSON")
    args = p.parse_args(argv)
    require(1 <= args.workers <= 10, "Choose 1-10 workers")
    require(1 <= args.hash_workers <= 4, "Choose 1-4 hashing workers")
    require(4 <= args.memory_gb <= 128, "Memory budget must be at least 4 GiB")
    require(1024 <= args.batch_rows <= 131072, "Batch rows must be 1,024-131,072")
    require(args.project_root.is_dir(), "Project root does not exist; check that XT_Pro is mounted")
    args.desktop.mkdir(parents=True, exist_ok=True)
    code_id = verify_package()
    log("Expected first run: about 20-60 minutes on a modern Mac/external SSD; planning estimate, not a measured full-data benchmark.")
    log("Using cached Parquets. There are no API requests, PGN downloads, engine jobs, or full-history replays.")
    run = None; config = None
    try:
        items, provenance = authenticate(args.project_root, args.manifest, args.sample_root, args.hash_workers)
        for x in items:
            require(set(BASE_COLUMNS) <= set(x["columns"]), "Cached state schema incomplete for " + x["month"])
        calendar = None; calendar_record = None; bot_record = None
        if args.factor_calendar:
            calendar = read_json(args.factor_calendar)
            require(calendar.get("periods"), "Factor calendar is empty")
            for row in calendar["periods"]:
                require(row.get("evidence"), "Every factor period needs an evidence description")
            calendar_record = record(args.factor_calendar)
        if args.bot_status:
            bot_record = record(args.bot_status)
        environment = {"python":sys.version, "platform":platform.platform(), "numpy":np.__version__,
                       "pyarrow":pa.__version__, "duckdb":duckdb.__version__}
        identity = {k:v for k,v in provenance.items() if k != "runtime"}
        # File stamps guard in-session mutation; content hashes determine identity.
        identity["files"] = [{k:v for k,v in x.items() if k != "stamp"} for x in items]
        settings = {"version":VERSION, "code":code_id, "input":digest(identity), "environment":environment,
                    "batch_rows":args.batch_rows, "calendar":calendar_record, "bots":bot_record,
                    "workers":args.workers, "memory_gb":args.memory_gb}
        fingerprint = digest(settings)
        run = args.project_root / "derived/replication/counterfactual_cost_upgrade_v100_PRIVATE" / fingerprint[:16]
        run.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(run).free
        require(free >= 12 * 1024**3, "Allow at least 12 GiB free for cost Parquets and temporary summaries")
        workers = min(args.workers, max(1, args.memory_gb//1))
        if bot_record:
            bot_n = __import__("pyarrow.parquet", fromlist=["ParquetFile"]).ParquetFile(args.bot_status).metadata.num_rows
            per_worker = 256*1024**2 + bot_n*180
            workers = min(workers, max(1, int((args.memory_gb-2)*1024**3/per_worker)))
        config = {"version":VERSION, "fingerprint":fingerprint, "run_root":str(run.resolve()),
            "desktop":str(args.desktop.resolve()), "workers":workers, "memory_gb":args.memory_gb,
            "batch_rows":args.batch_rows, "already_author_excluded":provenance["mode"]=="authenticated_author_excluded",
            "calendar":calendar, "bot_status":str(args.bot_status.resolve()) if args.bot_status else None,
            "code_identity":code_id, "input_identity":digest(identity), "environment":environment}
        write_json(run / "INPUT_MANIFEST_PRIVATE.json", provenance)
        write_json(run / "RUN_CONFIG_PRIVATE.json", config)
        log(f"Authenticated {len(items)} months; using {workers} workers, one array-library thread each.")
        execute(items, config, expected_rows=EXPECTED_EXCLUDED_ROWS)
        return 0
    except Exception as exc:
        error_root = run or args.desktop / "Counterfactual_Cost_Upgrade_v1_0_1_errors"
        error_root.mkdir(parents=True, exist_ok=True)
        write_json(error_root / "ERROR_PRIVATE.json", {"error":str(exc), "traceback":traceback.format_exc(), "time":now()})
        log(f"COST_UPGRADE_STOPPED: {exc}")
        log(f"Diagnostic file: {error_root / 'ERROR_PRIVATE.json'}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
