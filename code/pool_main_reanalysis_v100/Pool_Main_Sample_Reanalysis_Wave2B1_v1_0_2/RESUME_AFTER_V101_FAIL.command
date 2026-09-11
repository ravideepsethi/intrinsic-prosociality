#!/bin/bash
set -euo pipefail
umask 077

task_bundle="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
task_project="${POOL_MAIN_PROJECT:-/Volumes/XT_Pro/lichess_kindness}"
task_private="${POOL_MAIN_WAVE2B1_PRIVATE:-$task_project/derived/replication/pool_main_reanalysis_v100_PRIVATE/wave2b1}"
task_view="$task_private/project_view"
task_audit_state="$task_view/derived/replication/a1_evidence_gap_audit_v100_PRIVATE"
task_binding="$task_private/bindings/a1_evidence_gap_audit_v100.py.binding.json"
task_old_source_sha="3ba21032704a1910060a1ba25a8922091ac6a3510766c7541b1b0a988b665a8e"
task_new_source_sha="514d855b20e31be7c3e3eaa76cc0f11e4db9e0b642466b05639b46ef0da420b6"

fail() {
  printf 'STOP: %s\n' "$*" >&2
  exit 1
}

declare -a task_required=(
  "$task_view/output/dynamic_prosociality_a3_chronology_gate_v100/POOL_MAIN_WAVE2B1_A3/_SUCCESS.json"
  "$task_view/output/dynamic_prosociality_core_v102/POOL_MAIN_WAVE2B1_CORE/_SUCCESS.json"
  "$task_view/output/dynamic_prosociality_core_v102_postaudit/POOL_MAIN_WAVE2B1_POSTAUDIT/_SUCCESS.json"
  "$task_view/output/remaining_dynamic_completion_v100/POOL_MAIN_WAVE2B1_REMAINING/_SUCCESS.json"
)
for task_receipt in "${task_required[@]}"; do
  [[ -f "$task_receipt" ]] || fail "Expected v1.0.1 restart authority is missing: $task_receipt"
done

task_failed_result="$task_view/output/a1_evidence_gap_audit_v100/POOL_MAIN_WAVE2B1_A1_EVIDENCE/_SUCCESS.json"
if [[ -f "$task_failed_result" ]]; then
  printf 'A certified v1.0.2 A1 evidence-gap result already exists and will be adopted.\n'
elif [[ -d "$task_audit_state" ]]; then
  [[ -f "$task_binding" ]] || fail "A1 private state exists without its binding receipt: $task_binding"
  if /usr/bin/grep -q "$task_old_source_sha" "$task_binding"; then
    task_backup="${task_audit_state}_failed_v101_$(/bin/date -u +%Y%m%dT%H%M%SZ)"
    [[ ! -e "$task_backup" ]] || fail "Backup target already exists: $task_backup"
    /bin/mv "$task_audit_state" "$task_backup"
    printf 'Archived the failed v1.0.1 A1 audit cache (recoverable):\n%s\n' "$task_backup"
  elif /usr/bin/grep -q "$task_new_source_sha" "$task_binding"; then
    printf 'Preserving the existing v1.0.2 A1 audit cache for checkpoint resume.\n'
  else
    fail "A1 audit state belongs to an unrecognized source binding; no path was changed."
  fi
else
  printf 'No failed A1 audit cache needs archival.\n'
fi

printf 'Authenticated the completed upstream stages.\n'
printf 'Resuming at a1_evidence_gap; no certified output or checkpoint is deleted.\n'
exec /bin/bash "$task_bundle/RUN_WAVE2B1.command" --start-at a1_evidence_gap
