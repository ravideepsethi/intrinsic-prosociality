#!/bin/bash
set -uo pipefail

ROOT="/Volumes/XT_Pro/lichess_kindness"
PY="$ROOT/venv/bin/python"
SCRIPT="$ROOT/replication_package/code/04_enrich_timeout_candidates.py"
INPUT_ROOT="$ROOT/derived/replication/pgn_timeforfeit_candidates"
OUTPUT_ROOT="$ROOT/derived/replication/api_timeout_enrichment"

LOG="${1:?Usage: supervisor LOG STATE_DIR}"
STATE_DIR="${2:?Usage: supervisor LOG STATE_DIR}"

MONTHS=(
    2025-03
    2025-04
    2025-05
    2025-06
    2025-07
)

mkdir -p "$STATE_DIR"

timestamp() {
    date -u '+%Y-%m-%dT%H:%M:%SZ'
}

WORKER_PID=""

stop_worker() {
    echo "[$(timestamp)] [SUPERVISOR] termination requested"

    if [[ -n "${WORKER_PID:-}" ]] && kill -0 "$WORKER_PID" 2>/dev/null; then
        kill "$WORKER_PID" 2>/dev/null || true
        wait "$WORKER_PID" 2>/dev/null || true
    fi

    exit 143
}

trap stop_worker INT TERM

ATTEMPT=0

while true; do
    # Wait indefinitely for the laptop to have a usable route to Lichess.
    while ! curl \
        --silent \
        --show-error \
        --location \
        --max-time 20 \
        --output /dev/null \
        https://lichess.org
    do
        echo "[$(timestamp)] [SUPERVISOR] network unavailable; checking again in 60 seconds"
        sleep 60
    done

    ATTEMPT=$((ATTEMPT + 1))
    ATTEMPT_START_LINE="$(wc -l < "$LOG" | tr -d ' ')"

    echo "[$(timestamp)] [SUPERVISOR] connectivity available"
    echo "[$(timestamp)] [SUPERVISOR] starting canonical Stage 04 attempt $ATTEMPT"

    "$PY" -u "$SCRIPT" \
        --project-root "$ROOT" \
        --input-root "$INPUT_ROOT" \
        --output-root "$OUTPUT_ROOT" \
        --pile office \
        --machine-label office-laptop \
        --months "${MONTHS[@]}" \
        --batch-size 300 \
        --unit-size 30000 \
        --sleep-seconds 1.0 \
        --execute &

    WORKER_PID=$!
    printf '%s\n' "$WORKER_PID" > "$STATE_DIR/worker.pid"

    echo "[$(timestamp)] [SUPERVISOR] worker_pid=$WORKER_PID"

    wait "$WORKER_PID"
    RC=$?
    WORKER_PID=""

    printf '%s\n' "$RC" > "$STATE_DIR/last_exit_code.txt"

    if [[ "$RC" -eq 0 ]]; then
        echo "[$(timestamp)] [SUPERVISOR] Stage 04 completed successfully"
        printf '%s\n' "$(timestamp)" > "$STATE_DIR/completed_utc.txt"
        exit 0
    fi

    echo "[$(timestamp)] [SUPERVISOR] Stage 04 exited with code $RC"

    # Inspect only output produced during the failed attempt.
    ATTEMPT_OUTPUT="$(
        tail -n "+$((ATTEMPT_START_LINE + 1))" "$LOG" 2>/dev/null |
        tail -n 800
    )"

    if printf '%s\n' "$ATTEMPT_OUTPUT" |
        grep -Eiq \
        'Network is unreachable|ConnectionError|NewConnectionError|NameResolutionError|Temporary failure in name resolution|nodename nor servname|Connection reset|RemoteDisconnected|Read timed out|ConnectTimeout|HTTP (429|500|502|503|504)'
    then
        echo "[$(timestamp)] [SUPERVISOR] failure classified as transient network/API failure"
        echo "[$(timestamp)] [SUPERVISOR] waiting 60 seconds before connectivity check and resume"
        sleep 60
        continue
    fi

    echo "[$(timestamp)] [SUPERVISOR] NON-NETWORK FAILURE — automatic restart disabled"
    echo "[$(timestamp)] [SUPERVISOR] inspect log: $LOG"
    printf '%s\n' "$(timestamp)" > "$STATE_DIR/nonnetwork_failure_utc.txt"
    exit "$RC"
done
