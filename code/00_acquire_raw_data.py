#!/usr/bin/env python3
"""
00_acquire_raw_data.py

Replication stage 00 for the Lichess Kindness project.

Purpose
-------
Download the missing public Lichess standard-rated monthly PGN archives needed
to expand coverage around the already-acquired windows.

This script is intentionally narrow. It does NOT parse games, does NOT call the
Lichess API, does NOT build the timeout opportunity set, and does NOT make paper
tables. It only acquires and verifies raw public monthly PGN archives.

Target months downloaded by default
-----------------------------------
Missing months:
  - 2024-10 through 2025-07
  - 2026-01
  - 2026-03 through 2026-06

Already acquired elsewhere, so not downloaded by default:
  - 2023-10 through 2024-09
  - 2025-08 through 2025-12
  - 2026-02

Outputs
-------
Raw files:
  raw/lichess_pgn_standard/lichess_db_standard_rated_YYYY-MM.pgn.zst

Stable completion checkpoints:
  raw/lichess_pgn_standard/.acquire_checkpoints/
    lichess_db_standard_rated_YYYY-MM.pgn.zst.ok.json

Timestamped run metadata:
  output/replication_acquire_raw_data/acquire_lichess_standard_pgn_<timestamp>/
    command.txt
    run.log
    events.jsonl
    download_manifest.csv
    download_manifest.parquet      # if pandas/parquet available
    download_status.csv
    download_status.parquet        # if pandas/parquet available
    pgn_zst_paths.txt
    summary_pre.json
    summary.json

Checkpoint / resume design
--------------------------
The script is safe to rerun.

For each month:
  1. If an .ok.json checkpoint exists and the local file size still matches
     the remote file size, the month is skipped.
  2. If a partial file exists, curl resumes it with --continue-at -.
  3. After download, the script verifies file size against the remote HEAD size.
  4. If zstd is installed and not skipped, it runs `zstd -t` to verify compressed
     file integrity.
  5. Only then does it write the .ok.json checkpoint.

Live progress
-------------
A background monitor prints the current bytes downloaded and recent speed every
--progress-interval seconds while downloads are active.

Parallelism
-----------
The script supports --download-workers, but defaults to 1.

For this raw acquisition step, one or two workers is usually better than many:
these are huge public files, and the bottleneck is network/disk I/O plus polite
use of the public Lichess archive. Heavy multi-worker Parquet work begins in
Script 01, where we scan .pgn.zst files by month and write candidate Parquets.
"""

from __future__ import annotations

# ----------------------------- Standard library -----------------------------
# The acquisition script deliberately uses only Python standard-library modules
# for its core functionality. This makes it easy to run on a fresh machine.
import argparse
import csv
import json
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


# ------------------------------- Configuration ------------------------------
# Public Lichess monthly standard-rated PGN archive.
BASE_URL = "https://database.lichess.org/standard"

# Local project layout. This script assumes the project lives here.
PROJECT_ROOT = Path("/Volumes/XT_Pro/lichess_kindness")

# Where raw monthly .pgn.zst archives are stored.
RAW_DIR = PROJECT_ROOT / "raw" / "lichess_pgn_standard"

# Where timestamped metadata/logs for this acquisition run are stored.
OUT_BASE = PROJECT_ROOT / "output" / "replication_acquire_raw_data"

# Stable checkpoint directory. This is intentionally outside the timestamped
# output folder so that reruns can see earlier completed months.
CHECKPOINT_DIR = RAW_DIR / ".acquire_checkpoints"

# Missing months to acquire for this expansion.
TARGET_MONTHS = [
    "2024-10", "2024-11", "2024-12",
    "2025-01", "2025-02", "2025-03", "2025-04", "2025-05", "2025-06", "2025-07",
    "2026-01",
    "2026-03", "2026-04", "2026-05", "2026-06",
]


# ----------------------------- Result structure -----------------------------
# One row per month. Keeping this as a dataclass makes it easy to write the same
# information to CSV, Parquet, JSONL events, and checkpoint files.
@dataclass
class MonthResult:
    month: str
    filename: str
    url: str
    local_path: str
    checkpoint_path: str
    remote_size: Optional[int]
    local_size: Optional[int]
    existed_before: bool
    action: str
    curl_returncode: Optional[int]
    size_ok: Optional[bool]
    zstd_ok: Optional[bool]
    final_ok: bool
    started_utc: str
    finished_utc: str
    elapsed_seconds: float
    error: str


# ------------------------------ Small utilities -----------------------------
def now_utc() -> str:
    """Return a compact UTC timestamp for logs and manifests."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def filename_for_month(month: str) -> str:
    """Map YYYY-MM to the public Lichess standard-rated archive filename."""
    return f"lichess_db_standard_rated_{month}.pgn.zst"


def human_bytes(n: Optional[int]) -> str:
    """Human-readable byte formatting for console output and summaries."""
    if n is None:
        return "NA"
    x = float(n)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if x < 1024 or unit == "TB":
            return f"{x:.2f} {unit}"
        x /= 1024
    return str(n)


def head_size(url: str) -> Tuple[Optional[int], str]:
    """
    Query the remote file size via HTTP HEAD.

    This gives us the expected compressed size before downloading. We use it for:
      - dry-run size reporting,
      - free-space checks,
      - post-download verification,
      - deciding whether an existing local file is complete.
    """
    req = Request(url, method="HEAD", headers={"User-Agent": "lichess-kindness-replication/1.0"})
    try:
        with urlopen(req, timeout=60) as r:
            s = r.headers.get("Content-Length")
            return (int(s) if s and s.isdigit() else None, "")
    except (HTTPError, URLError, TimeoutError, OSError) as e:
        # We return the error string rather than immediately crashing so the
        # dry-run manifest can show exactly which month/URL failed.
        return None, repr(e)


def run_logged(cmd: List[str], log_path: Path) -> int:
    """
    Run a shell command and append stdout/stderr to the run log.

    We use this for curl and zstd so that the console stays readable while the
    full low-level command output is preserved for debugging.
    """
    with log_path.open("a", encoding="utf-8") as log:
        log.write("\n$ " + " ".join(cmd) + "\n")
        log.flush()
        p = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, text=True)
        log.write(f"\nreturncode={p.returncode}\n")
        log.flush()
        return int(p.returncode)


def curl_download(url: str, local_path: Path, log_path: Path) -> int:
    """
    Download or resume one archive using curl.

    Important curl flags:
      --continue-at -       resume a partial file if one exists
      --retry-all-errors    retry transient network/server errors
      --speed-limit/time    abort and retry if connection stalls badly
    """
    cmd = [
        "curl",
        "--fail",
        "--location",
        "--continue-at", "-",
        "--retry", "8",
        "--retry-all-errors",
        "--connect-timeout", "30",
        "--speed-limit", "1024",
        "--speed-time", "90",
        "--output", str(local_path),
        url,
    ]
    return run_logged(cmd, log_path)


def zstd_test(local_path: Path, log_path: Path) -> Tuple[Optional[bool], str]:
    """
    Verify compressed-file integrity with `zstd -t`.

    If zstd is not installed, we return None rather than failing. Size matching is
    still checked. For final replication-grade acquisition, installing zstd is
    recommended:
        brew install zstd
    """
    if shutil.which("zstd") is None:
        return None, "zstd_not_installed"
    rc = run_logged(["zstd", "-t", "-q", str(local_path)], log_path)
    return rc == 0, f"zstd_rc_{rc}"


def read_checkpoint(path: Path) -> Optional[dict]:
    """Read a prior .ok.json checkpoint if it exists and is valid JSON."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def write_json_atomic(path: Path, obj: dict) -> None:
    """
    Atomically write JSON.

    We write to a temporary file and then replace the destination. This avoids
    leaving a half-written checkpoint if the process is interrupted mid-write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def append_jsonl(path: Path, obj: dict) -> None:
    """
    Append one structured event to events.jsonl.

    JSONL is useful because it is append-only, human-readable, and easy to parse
    after crashes. Each line is one event.
    """
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, sort_keys=True) + "\n")


def write_csv(path: Path, rows: List[dict]) -> None:
    """Write small human-readable manifests/status tables."""
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def write_parquet_if_possible(path: Path, rows: List[dict]) -> str:
    """
    Write Parquet status files when pandas + a Parquet engine are available.

    This acquisition script does not require pandas. If pandas/pyarrow is not
    available, CSV/JSONL/JSON are still written and the script remains valid.
    """
    if not rows:
        return "skipped_empty"
    try:
        import pandas as pd
        df = pd.DataFrame(rows)
        df.to_parquet(path, index=False)
        return "ok"
    except Exception as e:
        return f"skipped_or_failed: {repr(e)}"


# -------------------------- Live progress monitor ---------------------------
class ProgressMonitor:
    """
    Background progress reporter.

    curl writes its detailed progress to run.log. This monitor gives a cleaner
    console-level progress update by checking how large each active local file is.
    """

    def __init__(self, interval: float = 30.0):
        self.interval = interval
        self.lock = threading.Lock()
        self.active: Dict[str, dict] = {}
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> None:
        """Start the background progress thread."""
        self.thread.start()

    def stop(self) -> None:
        """Stop the background progress thread cleanly."""
        self.stop_event.set()
        self.thread.join(timeout=5)

    def add(self, month: str, path: Path, remote_size: Optional[int]) -> None:
        """Mark a month as actively downloading."""
        with self.lock:
            size = path.stat().st_size if path.exists() else 0
            self.active[month] = {
                "path": path,
                "remote_size": remote_size,
                "last_size": size,
                "last_time": time.time(),
            }

    def remove(self, month: str) -> None:
        """Mark a month as no longer actively downloading."""
        with self.lock:
            self.active.pop(month, None)

    def _loop(self) -> None:
        """Print progress every interval seconds until stopped."""
        while not self.stop_event.wait(self.interval):
            lines = []

            with self.lock:
                for month, info in sorted(self.active.items()):
                    path = info["path"]
                    remote_size = info["remote_size"]

                    current = path.stat().st_size if path.exists() else 0
                    t = time.time()
                    dt = max(t - info["last_time"], 1e-9)
                    speed = (current - info["last_size"]) / dt

                    info["last_size"] = current
                    info["last_time"] = t

                    if remote_size:
                        pct = 100.0 * current / remote_size
                        lines.append(
                            f"{month}: {human_bytes(current)} / {human_bytes(remote_size)} "
                            f"({pct:.2f}%), recent {human_bytes(int(speed))}/s"
                        )
                    else:
                        lines.append(
                            f"{month}: {human_bytes(current)}, recent {human_bytes(int(speed))}/s"
                        )

            if lines:
                print("\nLIVE DOWNLOAD PROGRESS [" + now_utc() + "]")
                for line in lines:
                    print("  " + line)
                sys.stdout.flush()


# ----------------------------- Month processor ------------------------------
def process_month(
    month: str,
    log_path: Path,
    jsonl_path: Path,
    monitor: ProgressMonitor,
    skip_zstd_test: bool,
    force: bool,
) -> MonthResult:
    """
    Download/verify/checkpoint one month.

    This is the unit of checkpointing. Each successful month writes one stable
    .ok.json checkpoint. Rerunning the script skips completed months.
    """
    started = now_utc()
    t0 = time.time()

    fn = filename_for_month(month)
    url = f"{BASE_URL}/{fn}"
    local_path = RAW_DIR / fn
    checkpoint_path = CHECKPOINT_DIR / f"{fn}.ok.json"

    existed_before = local_path.exists()
    remote_size, head_error = head_size(url)

    action = "unknown"
    curl_rc: Optional[int] = None
    z_ok: Optional[bool] = None
    error = ""

    try:
        # Step 1: Check whether a prior completed checkpoint is still valid.
        # A checkpoint is valid only if the file still exists and, when remote
        # size is known, local size matches remote size.
        cp = read_checkpoint(checkpoint_path)
        local_size0 = local_path.stat().st_size if local_path.exists() else None
        checkpoint_valid = bool(
            cp
            and cp.get("final_ok") is True
            and local_path.exists()
            and (remote_size is None or local_size0 == remote_size)
        )

        if checkpoint_valid and not force:
            action = "skip_checkpoint_ok"

        else:
            # Step 2: If the complete file exists but the checkpoint is missing,
            # verify it and then recreate the checkpoint. This is useful if you
            # copied files manually or deleted old metadata.
            already_complete_by_size = bool(
                local_path.exists()
                and remote_size is not None
                and local_size0 == remote_size
                and not force
            )

            if already_complete_by_size:
                action = "verify_existing_size_ok"

            else:
                # Step 3: Download or resume the month.
                action = "download_or_resume"

                monitor.add(month, local_path, remote_size)
                append_jsonl(jsonl_path, {
                    "event": "download_start",
                    "month": month,
                    "utc": now_utc(),
                    "local_path": str(local_path),
                    "remote_size": remote_size,
                })

                curl_rc = curl_download(url, local_path, log_path)

                monitor.remove(month)
                append_jsonl(jsonl_path, {
                    "event": "download_finish",
                    "month": month,
                    "utc": now_utc(),
                    "curl_returncode": curl_rc,
                })

                if curl_rc != 0:
                    error = f"curl_returncode_{curl_rc}"

            # Step 4: Verify local size against remote size.
            local_size = local_path.stat().st_size if local_path.exists() else None
            size_ok = (local_size == remote_size) if remote_size is not None and local_size is not None else None

            if error == "" and size_ok is False:
                error = f"size_mismatch_local_{local_size}_remote_{remote_size}"

            # Step 5: Verify zstd integrity when available/requested.
            if error == "" and not skip_zstd_test and local_path.exists():
                append_jsonl(jsonl_path, {"event": "zstd_start", "month": month, "utc": now_utc()})
                z_ok, z_msg = zstd_test(local_path, log_path)
                append_jsonl(jsonl_path, {
                    "event": "zstd_finish",
                    "month": month,
                    "utc": now_utc(),
                    "zstd_ok": z_ok,
                    "zstd_msg": z_msg,
                })

                if z_ok is False:
                    error = z_msg

        # Step 6: Recompute final status after all checks.
        local_size = local_path.stat().st_size if local_path.exists() else None
        size_ok = (local_size == remote_size) if remote_size is not None and local_size is not None else None
        final_ok = bool(local_path.exists() and size_ok is not False and z_ok is not False and error == "")

        result = MonthResult(
            month=month,
            filename=fn,
            url=url,
            local_path=str(local_path),
            checkpoint_path=str(checkpoint_path),
            remote_size=remote_size,
            local_size=local_size,
            existed_before=existed_before,
            action=action,
            curl_returncode=curl_rc,
            size_ok=size_ok,
            zstd_ok=z_ok,
            final_ok=final_ok,
            started_utc=started,
            finished_utc=now_utc(),
            elapsed_seconds=round(time.time() - t0, 3),
            error=error or head_error,
        )

        # Step 7: Write the stable checkpoint only after all checks pass.
        if result.final_ok:
            write_json_atomic(checkpoint_path, {
                **asdict(result),
                "checkpoint_written_utc": now_utc(),
            })

        # Step 8: Append a structured event for postmortem debugging.
        append_jsonl(jsonl_path, {"event": "month_result", **asdict(result)})

        return result

    finally:
        # Always remove from the live monitor, even if an exception occurs.
        monitor.remove(month)


# ------------------------------- CLI parsing --------------------------------
def parse_args() -> argparse.Namespace:
    """Command-line interface for dry runs, reruns, and controlled parallelism."""
    p = argparse.ArgumentParser()

    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Only build manifest and check remote sizes/free space. Do not download.",
    )

    p.add_argument(
        "--download-workers",
        type=int,
        default=1,
        help="Number of concurrent month downloads. Default 1; use 2 cautiously.",
    )

    p.add_argument(
        "--skip-zstd-test",
        action="store_true",
        help="Skip zstd -t integrity checks after download.",
    )

    p.add_argument(
        "--force",
        action="store_true",
        help="Ignore checkpoints and redownload/reverify target months.",
    )

    p.add_argument(
        "--months",
        default="",
        help="Optional comma-separated YYYY-MM list to run instead of default target months.",
    )

    p.add_argument(
        "--progress-interval",
        type=float,
        default=30.0,
        help="Seconds between live progress prints.",
    )

    return p.parse_args()


# ---------------------------------- Main -------------------------------------
def main() -> int:
    """Main orchestration function for acquisition stage 00."""
    args = parse_args()

    # Allow a small targeted rerun, e.g. --months 2026-06,2026-05.
    months = [m.strip() for m in args.months.split(",") if m.strip()] if args.months.strip() else TARGET_MONTHS

    # Guard against accidentally launching many huge public downloads.
    if args.download_workers < 1:
        raise SystemExit("--download-workers must be >= 1")
    if args.download_workers > 2:
        print("WARNING: More than 2 download workers is usually not polite or optimal for huge public archives.")

    # Create all output/checkpoint folders.
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    OUT_BASE.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

    # Each run gets a timestamped metadata folder. Stable completion status lives
    # in CHECKPOINT_DIR, not only here.
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_root = OUT_BASE / f"acquire_lichess_standard_pgn_{stamp}"
    out_root.mkdir(parents=True, exist_ok=False)

    log_path = out_root / "run.log"
    jsonl_path = out_root / "events.jsonl"
    status_csv = out_root / "download_status.csv"
    status_parquet = out_root / "download_status.parquet"

    # Preserve the exact command used for this run.
    (out_root / "command.txt").write_text(" ".join(sys.argv) + "\n", encoding="utf-8")

    # Preflight manifest: remote sizes, existing local sizes, checkpoint status.
    manifest = []
    total_remote_size = 0

    for month in months:
        fn = filename_for_month(month)
        url = f"{BASE_URL}/{fn}"
        remote_size, head_error = head_size(url)
        local_path = RAW_DIR / fn
        local_size = local_path.stat().st_size if local_path.exists() else None
        cp = read_checkpoint(CHECKPOINT_DIR / f"{fn}.ok.json")
        checkpoint_ok = bool(cp and cp.get("final_ok") is True)

        if remote_size is not None:
            total_remote_size += remote_size

        manifest.append({
            "month": month,
            "filename": fn,
            "url": url,
            "local_path": str(local_path),
            "remote_size": remote_size,
            "remote_size_human": human_bytes(remote_size),
            "local_size": local_size,
            "local_size_human": human_bytes(local_size),
            "checkpoint_ok": checkpoint_ok,
            "head_error": head_error,
        })

    # Write preflight manifests in human-readable and machine-readable formats.
    write_csv(out_root / "download_manifest.csv", manifest)
    manifest_parquet_status = write_parquet_if_possible(out_root / "download_manifest.parquet", manifest)

    # Free-space reporting. The script does not hard-fail here, because some files
    # may already exist and remote sizes may be missing, but the warning is useful.
    free = shutil.disk_usage(RAW_DIR).free

    pre_summary = {
        "started_utc": now_utc(),
        "out_root": str(out_root),
        "raw_dir": str(RAW_DIR),
        "checkpoint_dir": str(CHECKPOINT_DIR),
        "months": months,
        "n_months": len(months),
        "download_workers": args.download_workers,
        "skip_zstd_test": args.skip_zstd_test,
        "known_remote_size_bytes": total_remote_size,
        "known_remote_size_human": human_bytes(total_remote_size),
        "free_space_bytes": free,
        "free_space_human": human_bytes(free),
        "dry_run": args.dry_run,
        "manifest_parquet_write": manifest_parquet_status,
    }

    write_json_atomic(out_root / "summary_pre.json", pre_summary)
    print(json.dumps(pre_summary, indent=2))

    # Dry-run exits here after writing manifest and size/free-space summary.
    if args.dry_run:
        write_json_atomic(out_root / "summary.json", {**pre_summary, "status": "dry_run_ok"})
        print(f"\nDRY_RUN_OUTPUT_ROOT={out_root}")
        return 0

    # Start the live progress monitor.
    monitor = ProgressMonitor(interval=args.progress_interval)
    monitor.start()

    results: List[MonthResult] = []

    try:
        # Run month-level jobs. With one worker, this is sequential but still
        # uses the same checkpointing and status machinery. With two workers,
        # two monthly archives download concurrently.
        with ThreadPoolExecutor(max_workers=args.download_workers) as ex:
            futures = {
                ex.submit(
                    process_month,
                    month,
                    log_path,
                    jsonl_path,
                    monitor,
                    args.skip_zstd_test,
                    args.force,
                ): month
                for month in months
            }

            for fut in as_completed(futures):
                month = futures[fut]

                # Convert unexpected exceptions into explicit failed month rows,
                # rather than letting one error erase all run metadata.
                try:
                    res = fut.result()
                except Exception as e:
                    res = MonthResult(
                        month=month,
                        filename=filename_for_month(month),
                        url=f"{BASE_URL}/{filename_for_month(month)}",
                        local_path=str(RAW_DIR / filename_for_month(month)),
                        checkpoint_path=str(CHECKPOINT_DIR / f"{filename_for_month(month)}.ok.json"),
                        remote_size=None,
                        local_size=None,
                        existed_before=False,
                        action="exception",
                        curl_returncode=None,
                        size_ok=None,
                        zstd_ok=None,
                        final_ok=False,
                        started_utc="",
                        finished_utc=now_utc(),
                        elapsed_seconds=0.0,
                        error=repr(e),
                    )
                    append_jsonl(jsonl_path, {"event": "month_exception", **asdict(res)})

                results.append(res)

                # Rewrite status after every completed month. This is another
                # checkpoint-style behavior: even if a later month fails, status
                # for completed months is already on disk.
                rows = [asdict(r) for r in sorted(results, key=lambda x: x.month)]
                write_csv(status_csv, rows)
                write_parquet_if_possible(status_parquet, rows)

                print(
                    f"MONTH DONE {res.month}: action={res.action}, "
                    f"final_ok={res.final_ok}, local={human_bytes(res.local_size)}, "
                    f"error={res.error or 'none'}"
                )
                sys.stdout.flush()

    finally:
        # Stop the monitor no matter how the run ends.
        monitor.stop()

    # Final status files.
    results_sorted = sorted(results, key=lambda x: x.month)
    final_rows = [asdict(r) for r in results_sorted]

    write_csv(status_csv, final_rows)
    status_parquet_write = write_parquet_if_possible(status_parquet, final_rows)

    # Path list for downstream scripts. Only successfully verified files appear.
    good_paths = [r.local_path for r in results_sorted if r.final_ok]
    (out_root / "pgn_zst_paths.txt").write_text(
        "\n".join(good_paths) + ("\n" if good_paths else ""),
        encoding="utf-8",
    )

    n_ok = sum(r.final_ok for r in results_sorted)
    failed = [r.month for r in results_sorted if not r.final_ok]

    summary = {
        **pre_summary,
        "finished_utc": now_utc(),
        "status": "ok" if not failed else "partial_or_failed",
        "n_ok": n_ok,
        "n_failed": len(failed),
        "failed_months": failed,
        "status_csv": str(status_csv),
        "status_parquet": str(status_parquet),
        "status_parquet_write": status_parquet_write,
        "events_jsonl": str(jsonl_path),
        "path_list": str(out_root / "pgn_zst_paths.txt"),
    }

    write_json_atomic(out_root / "summary.json", summary)

    print("\nFINAL SUMMARY")
    print(json.dumps(summary, indent=2))
    print(f"\nOUTPUT_ROOT={out_root}")

    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
