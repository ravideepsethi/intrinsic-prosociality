#!/bin/bash
set -euo pipefail

ROOT="/Volumes/XT_Pro/lichess_kindness"
PY="$ROOT/venv/bin/python"
HERE="$(cd "$(dirname "$0")" && pwd)"
CODE="$HERE/payload/code/run_c7r_fullpanel_prefocal_v100.py"
DESKTOP="/Users/u6025368/Desktop/Lichess_Desktop"

THREADS="${C7R_FULL_THREADS:-10}"
MEMORY="${C7R_FULL_MEMORY:-11GB}"
SHARDS="${C7R_FULL_SHARDS:-8}"

if [[ ! -x "$PY" ]]; then
  echo "ERROR: project Python authority not executable: $PY" >&2
  exit 1
fi

cd "$HERE"
/usr/bin/shasum -a 256 -c PACKAGE_CONTENTS.sha256

mkdir -p "$ROOT/logs/c7r_fullpanel_prefocal_v100"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$ROOT/logs/c7r_fullpanel_prefocal_v100/c7r_fullpanel_${RUN_ID}.log"

echo
echo "C7R FULL-PANEL PRE-FOCAL FIRST/REPEAT CENSUS"
echo "ETA: approximately 6-18 hours with clean Parquets; longer with heavy drive contention."
echo "Scope: all 47,587,020 Stage-07 opportunities; authenticated 2013+ C7R-compatible chronology."
echo "Resources: ${THREADS} DuckDB threads, memory limit ${MEMORY}, ${SHARDS} resumable shards."
echo "Recommended free space on XT_Pro: at least 150 GiB."
echo "Log: $LOG"
echo
echo "Running synthetic/dependency test first..."
"$PY" "$CODE" --self-test

echo
echo "Starting production. Safe to relaunch this same command after interruption."
set +e
/usr/bin/caffeinate -dimsu \
  "$PY" -u "$CODE" \
    --project-root "$ROOT" \
    --desktop-root "$DESKTOP" \
    --threads "$THREADS" \
    --memory "$MEMORY" \
    --shards "$SHARDS" \
    --run-id "$RUN_ID" \
    --execute \
  2>&1 | /usr/bin/tee "$LOG"
status="${PIPESTATUS[0]}"
set -e

if [[ "$status" -ne 0 ]]; then
  echo
  echo "ERROR: full-panel C7R run stopped with exit code $status." >&2
  echo "Rerun this launcher to resume authenticated private checkpoints." >&2
  echo "Log: $LOG" >&2
  exit "$status"
fi

echo
echo "C7R_FULLPANEL_OUTER_LAUNCHER_COMPLETE"
echo "Log: $LOG"
echo "Upload the generated C7R_FULLPANEL_PREFOCAL_RESULTS ZIP and .sha256 sidecar."
