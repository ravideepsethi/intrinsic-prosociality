#!/bin/bash
set -euo pipefail
umask 077
shopt -s nullglob

task_bundle="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
task_project="${POOL_MAIN_PROJECT:-/Volumes/XT_Pro/lichess_kindness}"
task_desktop="${POOL_MAIN_TRANSFER:-$HOME/Desktop/Lichess_Desktop}"
task_workers="${POOL_MAIN_C9_WORKERS:-10}"
task_memory="${POOL_MAIN_C9_MEMORY:-12GB}"

fail() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
[[ -d "$task_project" ]] || fail "Connect XT_Pro; project missing: $task_project"
mkdir -p "$task_desktop"
if [[ "${POOL_MAIN_C9_CAFFEINATED:-0}" != "1" ]] && [[ -x /usr/bin/caffeinate ]]; then
  export POOL_MAIN_C9_CAFFEINATED=1
  exec /usr/bin/caffeinate -dimsu /bin/bash "$0" "$@"
fi
cd "$task_bundle"
/usr/bin/shasum -a 256 -c PACKAGE_MANIFEST.sha256

if [[ -n "${POOL_MAIN_PYTHON:-}" ]]; then
  task_candidates=("$POOL_MAIN_PYTHON")
else
  task_candidates=(
    "$task_desktop"/pool_main_wave1_python.*/bin/python
    "$task_desktop"/pool_main_wave2a_python.*/bin/python
    "$task_project/venv/bin/python"
    "$task_project/.venv/bin/python"
    "${CONDA_PREFIX:-/nonexistent}/bin/python"
    /opt/anaconda3/bin/python
    /opt/homebrew/bin/python3
    "$(command -v python3 || true)"
  )
fi
task_python=""
for task_candidate in "${task_candidates[@]}"; do
  [[ -x "$task_candidate" ]] || continue
  if "$task_candidate" - <<'PY' >/dev/null 2>&1
import sys, re, numpy, pandas, pyarrow, duckdb
assert sys.version_info >= (3, 10)
for module, low, high in [(numpy,(2,3,0),(2,6,0)),(pandas,(2,2,0),(3,1,0)),
                         (pyarrow,(24,0,0),(26,0,0)),(duckdb,(1,5,2),(1,6,0))]:
    version=tuple(int(x) for x in re.findall(r'\d+',module.__version__)[:3])
    assert low <= version < high
PY
  then task_python="$task_candidate"; break; fi
done
[[ -n "$task_python" ]] || fail "Compatible offline Python not found. Set POOL_MAIN_PYTHON to the Python used by Wave 2B1."
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMEXPR_NUM_THREADS=1

task_log="$task_desktop/pool_main_c9_fresh_$(date -u +%Y%m%dT%H%M%SZ)_$$.log"
printf 'Pool-main C9: original producer, fresh new-sample conditional draws.\n'
printf 'Expected first-run elapsed time: 45-120 minutes (planning estimate).\n'
printf 'Session construction scans 150 chronology files, about 45 GB, with disk spill.\n'
printf 'The run is checkpointed. Repeat this command after interruption.\n'
printf 'Python: %s\nWorkers: %s; DuckDB memory: %s\nLog: %s\n' "$task_python" "$task_workers" "$task_memory" "$task_log"

(
  "$task_python" -B -u -m runner.test_c9
  "$task_python" -B -u -m runner.run_c9 \
    --project-root "$task_project" --desktop "$task_desktop" \
    --workers "$task_workers" --memory-limit "$task_memory" "$@"
) 2>&1 | /usr/bin/tee "$task_log"
