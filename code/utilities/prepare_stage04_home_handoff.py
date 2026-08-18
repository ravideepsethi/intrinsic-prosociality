#!/usr/bin/env python3
from __future__ import annotations

"""Build and verify the portable Stage 04 handoff for the home laptop.

The work laptop owns the canonical Stage 01 API-target Parquets for all bridge
months.  The home laptop needs only five of those Parquets (2024-10 through
2025-02), their Stage 01 success records, the canonical Stage 04 program, and
small launcher/monitor files.  It does not need any raw PGN archive.

This utility performs a copy rather than a move, hashes every source and copied
file, checks the authoritative Parquet row counts, writes a machine-readable
manifest, and then creates a single uncompressed TAR handoff file.  Parquet is
already compressed, so another compression layer would add time with almost no
size benefit.

Safety properties:

* Default behavior is plan-only.  --execute is required to create files.
* Existing destinations are never overwritten.
* Raw PGNs are never opened, moved, or deleted.
* The home and work month assignments are explicit and non-overlapping.
* The handoff contains its own install/smoke, production, status, and results
  packaging scripts so that a future chat is not required to reconstruct the
  operational details.
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import stat
import tarfile
from pathlib import Path
from typing import Any, Iterable

import pyarrow.parquet as pq


STAGE04_SHA256 = "2c1c23d4d867ce3a5a725cf4761e23f9f512c0063a3b7fc1f3d1f9ffe6d840fa"
HOME_MONTHS = ("2024-10", "2024-11", "2024-12", "2025-01", "2025-02")
OFFICE_MONTHS = ("2025-03", "2025-04", "2025-05", "2025-06", "2025-07")
EXPECTED_ROWS = {
    "2024-10": 7_280_463,
    "2024-11": 6_920_848,
    "2024-12": 7_327_917,
    "2025-01": 7_499_540,
    "2025-02": 6_780_461,
}
EXPECTED_HOME_TOTAL = 35_809_229


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")


def sha256_file(path: Path, block_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(block_size):
            digest.update(block)
    return digest.hexdigest()


def write_text(path: Path, text: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def json_dump(path: Path, value: Any) -> None:
    write_text(path, json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))


def payload_files(bundle_root: Path) -> Iterable[Path]:
    for path in sorted(bundle_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(bundle_root)
        if relative == Path("manifests/SHA256SUMS"):
            continue
        yield path


def home_readme() -> str:
    return r"""# Lichess kindness Stage 04 — home-laptop handoff

This bundle contains the complete inputs needed for the home half of canonical
Stage 04.  Its month block is contiguous:

- 2024-10
- 2024-11
- 2024-12
- 2025-01
- 2025-02

Total API-target game IDs: **35,809,229**.

The work laptop separately processes the contiguous office block 2025-03
through 2025-07.  The blocks do not overlap.

## What is included

- `code/04_enrich_timeout_candidates.py`: exact canonical Stage 04 script.
- `input/month=YYYY-MM/api_target_game_ids.parquet`: Stage 01 target IDs.
- `input/month=YYYY-MM/_STAGE01_SUCCESS.json`: copied Stage 01 checkpoint.
- `documentation/missing_rating_diff_policy.md`: locked downstream policy.
- `manifests/handoff_manifest.json`: source rows, sizes, and hashes.
- `manifests/SHA256SUMS`: integrity list for every handoff payload file.
- Four executable scripts for home installation, smoke testing, production,
  monitoring, and completed-output packaging.

## What is not included

No raw PGN file is present or needed.  Stage 04 queries only the public Lichess
bulk game-export API using the game IDs in the five Parquets.

## Home-laptop sequence

1. Put the TAR archive on the home laptop Desktop.
2. Extract the archive on the Desktop.
3. Run `01_home_install_and_smoke.sh` from Terminal and inspect its output.
4. Only after the smoke test passes, run `02_home_run_production.sh`.
5. Use `03_home_status.sh` at any time to inspect progress.
6. After all five months finish, run `04_home_package_results.sh` and return
   the resulting TAR plus its `.sha256` sidecar to the work laptop.

Production is safely resumable.  Running `02_home_run_production.sh` after a
stop verifies existing units and requests only unfinished units.  Never run two
copies of production simultaneously on the same home output root.
"""


def missing_rating_diff_policy() -> str:
    return r"""# Missing rating-difference policy

Some completed, API-rated Lichess games omit both players' `ratingDiff` values
in both the monthly PGN and the game-export API.  The omission is genuine and
must not be converted to a zero rating update.

Canonical downstream treatment:

1. Preserve the two observed API `ratingDiff` fields as nullable integers.
2. Include API-rated games in the chronological Glicko-2 replay even when both
   observed differences are absent.
3. Reconstruct the state transition from the two pregame states, outcome, and
   canonical Glicko-2 rules.
4. Use observed differences only to validate the reconstruction.
5. Exclude missing-difference games from observed-difference validation, not
   from the main replay.
6. Report an include/exclude sensitivity for these games in Stage 06.

The earlier next-game inference was superseded because overlapping games make
the next observed rating an unreliable measure of an individual game's update.
"""


def home_install_and_smoke_script() -> str:
    return r'''#!/bin/bash
set -euo pipefail

# Resolve the extracted bundle no matter what timestamp appears in its name.
BUNDLE_ROOT="$(cd "$(dirname "$0")" && pwd)"
RUNTIME_ROOT="$HOME/lichess_stage04_home_runtime"
VENV="$RUNTIME_ROOT/venv"
PYTHON="$VENV/bin/python"
SCRIPT="$BUNDLE_ROOT/code/04_enrich_timeout_candidates.py"
INPUT_ROOT="$BUNDLE_ROOT/input"
SMOKE_ROOT="$RUNTIME_ROOT/smoke_output"
LOG="$RUNTIME_ROOT/home_install_and_smoke.log"
PASSED_MARKER="$RUNTIME_ROOT/HOME_SMOKE_PASSED.json"

echo "===================================================================================================="
echo "HOME STAGE 04 INSTALL, INPUT AUDIT, AND 600-GAME SMOKE TEST"
echo "===================================================================================================="
echo "Expected runtime: approximately 5–12 minutes, including package installation."
echo "Expected normal API requests: two batches of 300 IDs."
echo "No production run will start."
echo "No raw PGNs are present or needed."
echo

mkdir -p "$RUNTIME_ROOT"
rm -f "$PASSED_MARKER"

echo "Verifying every handoff payload hash..."
(cd "$BUNDLE_ROOT" && shasum -a 256 -c manifests/SHA256SUMS)

if [[ ! -x "$PYTHON" ]]; then
    echo
    echo "Creating isolated home-laptop Python environment..."

    # Prefer an existing modern Anaconda/Homebrew Python.  Apple's system
    # Python can be too old for the pinned PyArrow wheel on some Macs.
    BASE_PYTHON="${HOME_STAGE04_BASE_PYTHON:-}"

    if [[ -z "$BASE_PYTHON" ]]; then
        for CANDIDATE in \
            /opt/anaconda3/bin/python3 \
            "$HOME/anaconda3/bin/python3" \
            "$HOME/miniconda3/bin/python3" \
            /opt/homebrew/bin/python3 \
            /usr/local/bin/python3 \
            /usr/bin/python3
        do
            if [[ -x "$CANDIDATE" ]] && "$CANDIDATE" -c \
                'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
                >/dev/null 2>&1
            then
                BASE_PYTHON="$CANDIDATE"
                break
            fi
        done
    fi

    if [[ -z "$BASE_PYTHON" ]] || [[ ! -x "$BASE_PYTHON" ]]; then
        echo "ERROR: no Python 3.10+ interpreter was found."
        echo "Set HOME_STAGE04_BASE_PYTHON to a suitable Python path and rerun."
        exit 1
    fi

    echo "Base Python: $BASE_PYTHON"
    "$BASE_PYTHON" -m venv "$VENV"
fi

"$PYTHON" -m pip install --upgrade pip
"$PYTHON" -m pip install \
    "pyarrow==24.0.0" \
    "requests==2.34.0" \
    "zstandard==0.25.0"

"$PYTHON" -m py_compile "$SCRIPT"

echo
echo "Dependency versions:"
"$PYTHON" - <<'PY'
import pyarrow, requests, zstandard
print("PyArrow:", pyarrow.__version__)
print("Requests:", requests.__version__)
print("Zstandard:", zstandard.__version__)
PY

echo
echo "Auditing the five input Parquets and the contiguous home plan..."
"$PYTHON" "$SCRIPT" \
    --project-root "$BUNDLE_ROOT" \
    --input-root "$INPUT_ROOT" \
    --output-root "$HOME/lichess_stage04_home_output/api_timeout_enrichment" \
    --pile home \
    --machine-label home-laptop

# Use a unique smoke root so the test cannot contaminate production output.
SMOKE_RUN_ROOT="${SMOKE_ROOT}_$(date -u +%Y%m%d_%H%M%S)"
export BUNDLE_ROOT RUNTIME_ROOT PYTHON SCRIPT INPUT_ROOT SMOKE_RUN_ROOT PASSED_MARKER

echo
echo "Running the home-network smoke test..."
"$PYTHON" -u "$SCRIPT" \
    --project-root "$BUNDLE_ROOT" \
    --input-root "$INPUT_ROOT" \
    --output-root "$SMOKE_RUN_ROOT" \
    --months 2024-10 \
    --machine-label home-laptop-smoke \
    --max-games-per-month 600 \
    --batch-size 300 \
    --unit-size 600 \
    --sleep-seconds 1 \
    --execute \
    2>&1 | tee "$LOG"

"$PYTHON" - <<'PY'
from __future__ import annotations
import json, os
from pathlib import Path
import pyarrow.parquet as pq

root = Path(os.environ["SMOKE_RUN_ROOT"])
month = root / "month=2024-10"
summary = json.loads((root / "_manifests/stage04_summary_explicit-months.json").read_text())
success = json.loads((month / "_SUCCESS.json").read_text())
responses = sorted((month / "responses").glob("unit-*.parquet"))
missing = sorted((month / "missing").glob("unit-*.parquet"))
raw = sorted((month / "raw").glob("unit-*.ndjson.zst"))
checkpoints = sorted((month / "_checkpoints").glob("*.success.json"))
assert len(responses) == len(missing) == len(raw) == len(checkpoints) == 1
returned = pq.ParquetFile(responses[0]).metadata.num_rows
not_returned = pq.ParquetFile(missing[0]).metadata.num_rows
schema = pq.ParquetFile(responses[0]).schema_arrow
assert returned + not_returned == 600
assert returned >= 590
assert {"rated", "api_status", "white_rating_diff", "black_rating_diff"}.issubset(schema.names)
assert success["final_ok"] is True and success["production"] is False
assert summary["total_requested_ids"] == 600
marker = {
    "final_ok": True,
    "smoke_root": str(root),
    "returned": returned,
    "missing": not_returned,
    "stage04_sha256": "2c1c23d4d867ce3a5a725cf4761e23f9f512c0063a3b7fc1f3d1f9ffe6d840fa",
}
Path(os.environ["PASSED_MARKER"]).write_text(json.dumps(marker, indent=2) + "\n")
print(json.dumps(marker, indent=2))
print("HOME INSTALL AND SMOKE TEST PASSED")
PY

echo
echo "Smoke marker: $PASSED_MARKER"
echo "Smoke log:    $LOG"
echo "Do not start production until the smoke output has been reviewed."
'''


def home_production_script() -> str:
    return r'''#!/bin/bash
set -euo pipefail

BUNDLE_ROOT="$(cd "$(dirname "$0")" && pwd)"
RUNTIME_ROOT="$HOME/lichess_stage04_home_runtime"
PYTHON="$RUNTIME_ROOT/venv/bin/python"
SCRIPT="$BUNDLE_ROOT/code/04_enrich_timeout_candidates.py"
INPUT_ROOT="$BUNDLE_ROOT/input"
OUTPUT_ROOT="$HOME/lichess_stage04_home_output/api_timeout_enrichment"
LOG_ROOT="$HOME/lichess_stage04_home_output/logs"
PASSED_MARKER="$RUNTIME_ROOT/HOME_SMOKE_PASSED.json"
RUN_STAMP="$(date -u +%Y%m%d_%H%M%S)"
LOG="$LOG_ROOT/home_production_${RUN_STAMP}.log"
PID_FILE="$LOG_ROOT/current_stage04.pid"
LOG_POINTER="$LOG_ROOT/current_stage04_log.txt"

echo "===================================================================================================="
echo "HOME STAGE 04 PRODUCTION LAUNCHER"
echo "===================================================================================================="
echo "Expected duration: roughly 2–4 weeks of continuous running; API speed varies."
echo "Months: 2024-10 through 2025-02."
echo "Targets: 35,809,229. Atomic units: 1,196."
echo "The process is resumable at the completed-unit level."
echo

[[ -x "$PYTHON" ]] || { echo "Missing home venv; run 01_home_install_and_smoke.sh first."; exit 1; }
[[ -f "$PASSED_MARKER" ]] || { echo "Missing passed smoke marker; run 01_home_install_and_smoke.sh first."; exit 1; }

(cd "$BUNDLE_ROOT" && shasum -a 256 -c manifests/SHA256SUMS)
mkdir -p "$OUTPUT_ROOT" "$LOG_ROOT"

# The 600-game smoke implies a single-digit-GB final payload, but retain a
# generous safety margin for raw API responses, Parquet metadata, and retries.
"$PYTHON" - <<'PY'
from pathlib import Path
import shutil

home = Path.home()
free = shutil.disk_usage(home).free
required = 25 * 1024**3
print(f"Home-disk free space: {free / 1024**3:,.2f} GiB")
print(f"Required launch floor: {required / 1024**3:,.2f} GiB")
if free < required:
    raise SystemExit("ERROR: fewer than 25 GiB are free; production was not launched")
PY

if [[ -f "$PID_FILE" ]]; then
    OLD_PID="$(tr -d '[:space:]' < "$PID_FILE")"
    if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "A recorded Stage 04 process is already running with PID $OLD_PID."
        echo "Use 03_home_status.sh instead of starting another copy."
        exit 1
    fi
fi

# Plan once more immediately before launch.  This catches a moved, missing, or
# damaged input without making any API request.
"$PYTHON" "$SCRIPT" \
    --project-root "$BUNDLE_ROOT" \
    --input-root "$INPUT_ROOT" \
    --output-root "$OUTPUT_ROOT" \
    --pile home \
    --machine-label home-laptop

echo
echo "Launching production under caffeinate/nohup..."
nohup /usr/bin/caffeinate -dimsu \
    "$PYTHON" -u "$SCRIPT" \
    --project-root "$BUNDLE_ROOT" \
    --input-root "$INPUT_ROOT" \
    --output-root "$OUTPUT_ROOT" \
    --pile home \
    --machine-label home-laptop \
    --batch-size 300 \
    --unit-size 30000 \
    --sleep-seconds 1 \
    --execute \
    > "$LOG" 2>&1 < /dev/null &

PID="$!"
echo "$PID" > "$PID_FILE"
echo "$LOG" > "$LOG_POINTER"
sleep 5

if ! kill -0 "$PID" 2>/dev/null; then
    echo "ERROR: production process exited during launch."
    tail -n 100 "$LOG"
    exit 1
fi

echo "Home production started successfully."
echo "PID:  $PID"
echo "Log:  $LOG"
echo "Data: $OUTPUT_ROOT"
echo
echo "Use 03_home_status.sh to inspect progress."
tail -n 40 "$LOG"
'''


def home_status_script() -> str:
    return r'''#!/bin/bash
set -euo pipefail

OUTPUT_BASE="$HOME/lichess_stage04_home_output"
OUTPUT_ROOT="$OUTPUT_BASE/api_timeout_enrichment"
LOG_ROOT="$OUTPUT_BASE/logs"
PID_FILE="$LOG_ROOT/current_stage04.pid"
LOG_POINTER="$LOG_ROOT/current_stage04_log.txt"

echo "===================================================================================================="
echo "HOME STAGE 04 STATUS"
echo "===================================================================================================="
echo "Expected runtime: under 10 seconds."
echo "This status command makes no API requests and changes no data."
echo

if [[ -f "$PID_FILE" ]]; then
    PID="$(tr -d '[:space:]' < "$PID_FILE")"
    if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
        echo "Process status: RUNNING (PID $PID)"
        ps -p "$PID" -o pid,etime,%cpu,%mem,command
    else
        echo "Process status: NOT RUNNING (stale recorded PID: ${PID:-empty})"
    fi
else
    echo "Process status: no PID file"
fi

echo
echo "Completed atomic units (out of 1,196):"
find "$OUTPUT_ROOT" -path '*/_checkpoints/unit-*.success.json' -type f 2>/dev/null | wc -l | tr -d ' '

echo
echo "Completed months:"
find "$OUTPUT_ROOT" -maxdepth 2 -name '_SUCCESS.json' -type f -print 2>/dev/null | sort || true

echo
echo "Current output size:"
du -sh "$OUTPUT_ROOT" 2>/dev/null || true

echo
echo "Available home-disk space:"
df -h "$HOME"

if [[ -f "$LOG_POINTER" ]]; then
    LOG="$(cat "$LOG_POINTER")"
    echo
    echo "Current log: $LOG"
    echo "Last 80 lines:"
    tail -n 80 "$LOG" 2>/dev/null || true
fi
'''


def home_package_results_script() -> str:
    return r'''#!/bin/bash
set -euo pipefail

BUNDLE_ROOT="$(cd "$(dirname "$0")" && pwd)"
OUTPUT_BASE="$HOME/lichess_stage04_home_output"
OUTPUT_ROOT="$OUTPUT_BASE/api_timeout_enrichment"
LOG_ROOT="$OUTPUT_BASE/logs"
PID_FILE="$LOG_ROOT/current_stage04.pid"
STAMP="$(date -u +%Y%m%d_%H%M%S)"
ARCHIVE="$HOME/Desktop/lichess_stage04_home_results_${STAMP}.tar"

echo "===================================================================================================="
echo "PACKAGE COMPLETED HOME STAGE 04 RESULTS"
echo "===================================================================================================="
echo "Expected runtime: approximately 5–20 minutes, depending on final output size."
echo "This makes no API requests and deletes nothing."
echo

if [[ -f "$PID_FILE" ]]; then
    PID="$(tr -d '[:space:]' < "$PID_FILE")"
    if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
        echo "ERROR: Stage 04 is still running with PID $PID."
        exit 1
    fi
fi

for MONTH in 2024-10 2024-11 2024-12 2025-01 2025-02; do
    [[ -f "$OUTPUT_ROOT/month=$MONTH/_SUCCESS.json" ]] || {
        echo "ERROR: missing month success record for $MONTH"
        exit 1
    }
done

[[ -f "$OUTPUT_ROOT/_manifests/stage04_summary_home.json" ]] || {
    echo "ERROR: missing final home summary"
    exit 1
}

# Count conservation and production flags are checked before a potentially
# large return archive is created.
OUTPUT_ROOT="$OUTPUT_ROOT" "$HOME/lichess_stage04_home_runtime/venv/bin/python" - <<'PY'
from __future__ import annotations
import json, os
from pathlib import Path

root = Path(os.environ["OUTPUT_ROOT"])
months = ["2024-10", "2024-11", "2024-12", "2025-01", "2025-02"]
expected = {
    "2024-10": 7_280_463,
    "2024-11": 6_920_848,
    "2024-12": 7_327_917,
    "2025-01": 7_499_540,
    "2025-02": 6_780_461,
}
for month in months:
    success = json.loads((root / f"month={month}/_SUCCESS.json").read_text())
    assert success["final_ok"] is True
    assert success["production"] is True
    assert success["requested_ids"] == expected[month]
    assert success["returned_unique_ids"] + success["missing_ids"] == expected[month]
summary = json.loads((root / "_manifests/stage04_summary_home.json").read_text())
assert summary["final_ok"] is True
assert summary["production"] is True
assert summary["months"] == months
assert summary["total_requested_ids"] == 35_809_229
assert summary["total_returned_unique_ids"] + summary["total_missing_ids"] == 35_809_229
print(json.dumps(summary, indent=2))
print("HOME RESULT COUNT CONSERVATION PASSED")
PY

tar -C "$OUTPUT_BASE" -cf "$ARCHIVE" api_timeout_enrichment logs
shasum -a 256 "$ARCHIVE" > "$ARCHIVE.sha256"

echo "Completed results archive:"
ls -lh "$ARCHIVE" "$ARCHIVE.sha256"
cat "$ARCHIVE.sha256"
echo
echo "Return both files to the work laptop Desktop."
'''


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path("/Volumes/XT_Pro/lichess_kindness"),
    )
    parser.add_argument(
        "--destination-directory",
        type=Path,
        default=Path.home() / "Desktop",
    )
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = args.project_root.expanduser().resolve()
    destination = args.destination_directory.expanduser().resolve()
    stage01_root = project_root / "derived/replication/pgn_timeforfeit_candidates"
    stage04_script = project_root / "replication_package/code/04_enrich_timeout_candidates.py"

    source_plan = []
    for month in HOME_MONTHS:
        month_root = stage01_root / f"month={month}"
        parquet = month_root / "api_target_game_ids.parquet"
        success = month_root / "_SUCCESS.json"
        if not parquet.is_file():
            raise SystemExit(f"missing source Parquet: {parquet}")
        if not success.is_file():
            raise SystemExit(f"missing Stage 01 success record: {success}")
        rows = int(pq.ParquetFile(parquet).metadata.num_rows)
        if rows != EXPECTED_ROWS[month]:
            raise SystemExit(f"{month}: found {rows:,} rows; expected {EXPECTED_ROWS[month]:,}")
        source_plan.append(
            {
                "month": month,
                "parquet": str(parquet),
                "success": str(success),
                "rows": rows,
                "parquet_size_bytes": parquet.stat().st_size,
                "success_size_bytes": success.stat().st_size,
            }
        )

    if sum(item["rows"] for item in source_plan) != EXPECTED_HOME_TOTAL:
        raise SystemExit("home target total does not match the locked count")
    if not stage04_script.is_file():
        raise SystemExit(f"missing Stage 04 script: {stage04_script}")
    actual_stage04_sha = sha256_file(stage04_script)
    if actual_stage04_sha != STAGE04_SHA256:
        raise SystemExit(
            f"Stage 04 SHA mismatch: found {actual_stage04_sha}; expected {STAGE04_SHA256}"
        )

    plan = {
        "execute": args.execute,
        "project_root": str(project_root),
        "destination_directory": str(destination),
        "home_months": list(HOME_MONTHS),
        "office_months": list(OFFICE_MONTHS),
        "home_target_rows": EXPECTED_HOME_TOTAL,
        "source_files": source_plan,
        "source_payload_bytes": sum(
            item["parquet_size_bytes"] + item["success_size_bytes"] for item in source_plan
        )
        + stage04_script.stat().st_size,
        "stage04_script": str(stage04_script),
        "stage04_sha256": actual_stage04_sha,
    }
    print(json.dumps(plan, indent=2))
    if not args.execute:
        print("\nPLAN ONLY. Add --execute to create the home-laptop handoff.")
        return 0

    destination.mkdir(parents=True, exist_ok=True)
    stamp = utc_stamp()
    bundle_root = destination / f"lichess_stage04_home_handoff_{stamp}"
    archive_path = destination / f"{bundle_root.name}.tar"
    sidecar_path = Path(str(archive_path) + ".sha256")
    summary_sidecar_path = Path(str(archive_path) + ".summary.json")
    for path in (bundle_root, archive_path, sidecar_path, summary_sidecar_path):
        if path.exists():
            raise SystemExit(f"refusing to overwrite existing destination: {path}")

    (bundle_root / "code").mkdir(parents=True)
    (bundle_root / "input").mkdir(parents=True)
    (bundle_root / "documentation").mkdir(parents=True)
    (bundle_root / "manifests").mkdir(parents=True)

    shutil.copy2(stage04_script, bundle_root / "code/04_enrich_timeout_candidates.py")
    copied_sources = []
    for item in source_plan:
        month = item["month"]
        target_month_root = bundle_root / "input" / f"month={month}"
        target_month_root.mkdir(parents=True)
        target_parquet = target_month_root / "api_target_game_ids.parquet"
        target_success = target_month_root / "_STAGE01_SUCCESS.json"
        source_parquet = Path(item["parquet"])
        source_success = Path(item["success"])
        print(f"Copying {month} API-target Parquet...", flush=True)
        shutil.copy2(source_parquet, target_parquet)
        shutil.copy2(source_success, target_success)
        source_parquet_sha = sha256_file(source_parquet)
        copied_parquet_sha = sha256_file(target_parquet)
        source_success_sha = sha256_file(source_success)
        copied_success_sha = sha256_file(target_success)
        if source_parquet_sha != copied_parquet_sha or source_success_sha != copied_success_sha:
            raise SystemExit(f"copy verification failed for {month}")
        copied_sources.append(
            {
                "month": month,
                "rows": item["rows"],
                "parquet_relative_path": str(target_parquet.relative_to(bundle_root)),
                "parquet_size_bytes": target_parquet.stat().st_size,
                "parquet_sha256": copied_parquet_sha,
                "stage01_success_relative_path": str(target_success.relative_to(bundle_root)),
                "stage01_success_size_bytes": target_success.stat().st_size,
                "stage01_success_sha256": copied_success_sha,
                "original_parquet_path": str(source_parquet),
                "original_stage01_success_path": str(source_success),
            }
        )

    write_text(bundle_root / "README.md", home_readme())
    write_text(
        bundle_root / "documentation/missing_rating_diff_policy.md",
        missing_rating_diff_policy(),
    )
    write_text(
        bundle_root / "01_home_install_and_smoke.sh",
        home_install_and_smoke_script(),
        executable=True,
    )
    write_text(
        bundle_root / "02_home_run_production.sh",
        home_production_script(),
        executable=True,
    )
    write_text(
        bundle_root / "03_home_status.sh",
        home_status_script(),
        executable=True,
    )
    write_text(
        bundle_root / "04_home_package_results.sh",
        home_package_results_script(),
        executable=True,
    )

    manifest = {
        "handoff": "lichess_stage04_home",
        "created_utc": utc_now(),
        "created_on_host": os.uname().nodename,
        "canonical_project_root": str(project_root),
        "locked_sample_start": "2023-11-01",
        "locked_sample_end": "2025-10-31",
        "home_months": list(HOME_MONTHS),
        "office_months": list(OFFICE_MONTHS),
        "home_target_rows": EXPECTED_HOME_TOTAL,
        "stage04_sha256": STAGE04_SHA256,
        "files": copied_sources,
        "raw_pgns_included": False,
    }
    manifest_path = bundle_root / "manifests/handoff_manifest.json"
    json_dump(manifest_path, manifest)

    checksum_lines = []
    for path in payload_files(bundle_root):
        checksum_lines.append(f"{sha256_file(path)}  {path.relative_to(bundle_root)}")
    write_text(bundle_root / "manifests/SHA256SUMS", "\n".join(checksum_lines))

    # Verify the checksum list before archiving it.
    for line in checksum_lines:
        expected, relative = line.split("  ", 1)
        actual = sha256_file(bundle_root / relative)
        if actual != expected:
            raise SystemExit(f"pre-archive checksum verification failed: {relative}")

    print(f"Creating single-file TAR archive {archive_path.name}...", flush=True)
    with tarfile.open(archive_path, mode="w", format=tarfile.PAX_FORMAT) as archive:
        archive.add(bundle_root, arcname=bundle_root.name, recursive=True)
    archive_sha = sha256_file(archive_path)
    write_text(sidecar_path, f"{archive_sha}  {archive_path.name}")

    # Inspect the archive table without extracting it.
    with tarfile.open(archive_path, mode="r") as archive:
        archive_names = archive.getnames()
    required_suffixes = [
        "README.md",
        "code/04_enrich_timeout_candidates.py",
        "manifests/handoff_manifest.json",
        "manifests/SHA256SUMS",
        "01_home_install_and_smoke.sh",
        "02_home_run_production.sh",
        "03_home_status.sh",
        "04_home_package_results.sh",
    ]
    for suffix in required_suffixes:
        if not any(name.endswith(suffix) for name in archive_names):
            raise SystemExit(f"archive missing required payload: {suffix}")

    final = {
        "final_ok": True,
        "bundle_root": str(bundle_root),
        "bundle_size_bytes": sum(path.stat().st_size for path in bundle_root.rglob("*") if path.is_file()),
        "archive_path": str(archive_path),
        "archive_size_bytes": archive_path.stat().st_size,
        "archive_sha256": archive_sha,
        "sha256_sidecar": str(sidecar_path),
        "summary_sidecar": str(summary_sidecar_path),
        "home_months": list(HOME_MONTHS),
        "home_target_rows": EXPECTED_HOME_TOTAL,
        "raw_pgns_included": False,
        "archive_member_count": len(archive_names),
    }
    # This summary is deliberately outside the TAR: it contains the TAR's own
    # hash, which cannot be embedded in the file it authenticates.
    json_dump(summary_sidecar_path, final)
    print("\nFINAL HOME HANDOFF SUMMARY")
    print(json.dumps(final, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
