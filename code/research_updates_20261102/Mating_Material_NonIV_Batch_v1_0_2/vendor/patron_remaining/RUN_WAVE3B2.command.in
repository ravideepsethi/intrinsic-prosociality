#!/bin/bash
set -euo pipefail
umask 077
shopt -s nullglob
task_bundle="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
task_project="${POOL_MAIN_PROJECT:-/Volumes/XT_Pro/lichess_kindness}"
task_transfer="${POOL_MAIN_TRANSFER:-$HOME/Desktop/Lichess_Desktop}"
[[ -d "$task_project" ]] || { echo "Connect XT_Pro: $task_project" >&2; exit 1; }
cd "$task_bundle"
/usr/bin/shasum -a 256 -c PACKAGE_MANIFEST.sha256
if command -v caffeinate >/dev/null 2>&1 && [[ "${PATRON_WAVE3B2_CAFFEINATED:-0}" != 1 ]]; then
  export PATRON_WAVE3B2_CAFFEINATED=1
  exec /usr/bin/caffeinate -dimsu /bin/bash "$0" "$@"
fi
if [[ -n "${POOL_MAIN_PYTHON:-}" ]]; then
  task_candidates=("$POOL_MAIN_PYTHON")
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
import sys,duckdb,numpy,pandas,pyarrow
assert sys.version_info >= (3,10)
assert tuple(map(int,duckdb.__version__.split('.')[:2])) == (1,5)
assert 24 <= int(pyarrow.__version__.split('.')[0]) <= 25
assert int(numpy.__version__.split('.')[0]) == 2
assert int(pandas.__version__.split('.')[0]) in (2,3)
PY
  then task_python="$task_candidate"; break; fi
done
[[ -n "$task_python" ]] || { echo 'Set POOL_MAIN_PYTHON to your existing Wave-1 interpreter.' >&2; exit 1; }
export PYTHONPATH="$task_bundle"
export PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
mkdir -p "$task_transfer"
task_log="$task_transfer/pool_main_patron_wave3b2_$(date -u +%Y%m%dT%H%M%SZ)_$$.log"
exec > >(tee -a "$task_log") 2>&1
printf 'Patron Wave 3B2 v1.0.1: remaining Patron models, rematches, ply and dyad checks.\n'
printf 'Expected runtime: 1-3 hours of compute, excluding any C9 queue time (planning estimate).\n'
printf 'Offline; each successful model is checkpointed. Repeat this command to resume.\n'
printf 'Python: %s\nLog: %s\n' "$task_python" "$task_log"
"$task_python" -B -u -m runner.self_test
"$task_python" -B -u -m runner.run \
  --project-root "$task_project" --transfer-dir "$task_transfer" \
  --threads "${POOL_MAIN_THREADS:-8}" --hash-workers "${POOL_MAIN_HASH_WORKERS:-10}" \
  --memory-limit "${POOL_MAIN_MEMORY:-12GB}"
