#!/bin/bash
set -euo pipefail
umask 077
shopt -s nullglob

task_bundle="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
task_project="${PATRON_GAP_FILL_PROJECT:-/Volumes/XT_Pro/lichess_kindness}"
task_transfer="${PATRON_GAP_FILL_DESKTOP:-$HOME/Desktop/Lichess_Desktop}"
[[ -d "$task_project" ]] || { echo "Connect XT_Pro; project missing: $task_project" >&2; exit 1; }
cd "$task_bundle"
/usr/bin/shasum -a 256 -c PACKAGE_MANIFEST.sha256

if command -v caffeinate >/dev/null 2>&1 && [[ "${PATRON_GAP_FILL_CAFFEINATED:-0}" != 1 ]]; then
  export PATRON_GAP_FILL_CAFFEINATED=1
  exec /usr/bin/caffeinate -dimsu /bin/bash "$0" "$@"
fi

if [[ -n "${PATRON_GAP_FILL_PYTHON:-}" ]]; then
  task_candidates=("$PATRON_GAP_FILL_PYTHON")
else
  task_candidates=(
    "$task_transfer"/pool_main_wave1_python.*/bin/python
    "$task_transfer"/pool_main_wave2a_python.*/bin/python
    "$task_project/venv/bin/python" "$task_project/.venv/bin/python"
    "${CONDA_PREFIX:-/nonexistent}/bin/python"
    /opt/anaconda3/bin/python /opt/homebrew/bin/python3
    "$(command -v python3 || true)"
  )
fi
task_python=""
for task_candidate in "${task_candidates[@]}"; do
  [[ -x "$task_candidate" ]] || continue
  if "$task_candidate" - <<'PY' >/dev/null 2>&1
import sys, duckdb, pyarrow
assert sys.version_info >= (3, 10)
assert tuple(map(int, duckdb.__version__.split('.')[:2])) == (1, 5)
assert 24 <= int(pyarrow.__version__.split('.')[0]) <= 25
PY
  then task_python="$task_candidate"; break; fi
done
[[ -n "$task_python" ]] || {
  echo "No compatible Python found. Set PATRON_GAP_FILL_PYTHON to the existing Wave-1 interpreter." >&2
  exit 1
}
export PYTHONPATH="$task_bundle"
export PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
mkdir -p "$task_transfer"
task_log="$task_transfer/pool_main_patron_gap_fill_$(date -u +%Y%m%dT%H%M%SZ)_$$.log"
exec > >(tee -a "$task_log") 2>&1
printf 'Patron gap fill: 285 missing accounts, including 207 in the primary comparison.\n'
printf 'Expected runtime: 2-5 minutes; API backoff or a slow drive can extend this estimate.\n'
printf 'Network required. Serial profile reads; no token or package installation.\n'
printf 'Do not run another profile API acquisition at the same time.\n'
printf 'Responses are checkpointed. Re-run this same command to resume.\n'
printf 'Python: %s\nLog: %s\n' "$task_python" "$task_log"
"$task_python" -B -u -m runner.self_test
"$task_python" -B -u -m runner.run --project-root "$task_project" --transfer-dir "$task_transfer" --execute
