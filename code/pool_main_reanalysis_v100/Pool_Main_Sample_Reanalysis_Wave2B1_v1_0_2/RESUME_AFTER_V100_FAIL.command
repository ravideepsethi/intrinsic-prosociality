#!/bin/bash
set -euo pipefail
umask 077

task_bundle="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
task_project="${POOL_MAIN_PROJECT:-/Volumes/XT_Pro/lichess_kindness}"
task_private="${POOL_MAIN_WAVE2B1_PRIVATE:-$task_project/derived/replication/pool_main_reanalysis_v100_PRIVATE/wave2b1}"
task_view="$task_private/project_view"
task_a3="$task_view/output/dynamic_prosociality_a3_chronology_gate_v100/POOL_MAIN_WAVE2B1_A3/_SUCCESS.json"
task_core_state="$task_view/derived/replication/dynamic_prosociality_core_v102_PRIVATE"
task_core_success="$task_view/output/dynamic_prosociality_core_v102/POOL_MAIN_WAVE2B1_CORE/_SUCCESS.json"
task_old_bound_sha="31e29f66fbeffd033aac48576f077a60dc490393dfa5c0e870c7591187643040"

fail() {
  printf 'STOP: %s\n' "$*" >&2
  exit 1
}

[[ -f "$task_a3" ]] || fail "The completed v1.0.0 A3 gate was not found: $task_a3"

if [[ -d "$task_core_state" ]] && \
   [[ -f "$task_core_state/resume_config.json" ]] && \
   /usr/bin/grep -q "$task_old_bound_sha" "$task_core_state/resume_config.json"; then
  [[ ! -f "$task_core_success" ]] || \
    fail "A certified dynamic-core result already exists; refusing to archive its state."
  task_backup="${task_core_state}_failed_v100_$(/bin/date -u +%Y%m%dT%H%M%SZ)"
  [[ ! -e "$task_backup" ]] || fail "Backup target already exists: $task_backup"
  /bin/mv "$task_core_state" "$task_backup"
  printf 'Archived the failed v1.0.0 core state (recoverable):\n%s\n' "$task_backup"
elif [[ -d "$task_core_state" ]]; then
  printf 'Preserving an existing non-v1.0.0 core state for ordinary checkpoint resume.\n'
else
  printf 'No failed core state needs archival.\n'
fi

printf 'Preserving and reusing the certified A3 gate:\n%s\n' "$task_a3"
exec /bin/bash "$task_bundle/RUN_WAVE2B1.command" --start-at dynamic_core
