#!/bin/bash
set -euo pipefail
umask 077
shopt -s nullglob

task_bundle="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
task_project="${POOL_MAIN_PROJECT:-/Volumes/XT_Pro/lichess_kindness}"
task_transfer="${POOL_MAIN_TRANSFER:-$HOME/Desktop/Lichess_Desktop}"
task_private="${POOL_MAIN_WAVE2B2A_PRIVATE:-$task_project/derived/replication/pool_main_reanalysis_v100_PRIVATE/wave2b2a}"
task_c7r_public="${POOL_MAIN_WAVE2B2A_C7R_PUBLIC:-$task_project/output/pool_main_reanalysis_v100/wave2b2a/c7r/POOL_MAIN_WAVE2B2A_C7R}"
task_cache="${POOL_MAIN_WAVE2B2A_C7R_CACHE:-$task_private/c7r_state_v102/c7r_pair_model_private.parquet}"
task_output="${POOL_MAIN_C7R_COMBINATION_OUTPUT:-$task_project/output/pool_main_reanalysis_v100/wave2b2a_c7r_linear_combination}"

fail() {
  printf 'STOP: %s\n' "$*" >&2
  exit 1
}

[[ -d "$task_project" ]] || fail "Project folder not found; connect XT_Pro: $task_project"
[[ -f "$task_cache" ]] || fail "Wave 2B2A C7R private cache not found: $task_cache"
[[ -f "$task_c7r_public/_SUCCESS.json" ]] || fail "Wave 2B2A C7R public result not found: $task_c7r_public"
mkdir -p "$task_transfer" "$task_output"

if command -v caffeinate >/dev/null 2>&1 && [[ "${POOL_MAIN_CAFFEINATED:-0}" != "1" ]]; then
  export POOL_MAIN_CAFFEINATED=1
  exec /usr/bin/caffeinate -dimsu "$0" "$@"
fi

cd "$task_bundle"
/usr/bin/shasum -a 256 -c PACKAGE_MANIFEST.sha256 || \
  fail "Package checksum validation failed. Re-extract the supplied ZIP."

task_python=""
task_candidates=(
  "${POOL_MAIN_PYTHON:-}"
  "$task_project/venv/bin/python"
  "$task_project/.venv/bin/python"
  "${CONDA_PREFIX:-/nonexistent}/bin/python"
  "${VIRTUAL_ENV:-/nonexistent}/bin/python"
  "$task_transfer"/pool_main_wave2b2a_python.*/bin/python
  "$task_transfer"/pool_main_wave2b1_python.*/bin/python
  "$task_transfer"/pool_main_wave1_python.*/bin/python
  "$HOME/anaconda3/bin/python"
  "$HOME/miniconda3/bin/python"
  "$HOME/miniforge3/bin/python"
  /opt/anaconda3/bin/python
  /opt/homebrew/bin/python3
  /usr/local/bin/python3
  "$(command -v python3 || true)"
)
for task_candidate in "${task_candidates[@]}"; do
  [[ -n "$task_candidate" && -x "$task_candidate" ]] || continue
  if "$task_candidate" - <<'PY' >/dev/null 2>&1
import sys
assert sys.version_info >= (3, 9)
import numpy, pyarrow
PY
  then
    task_python="$task_candidate"
    break
  fi
done
[[ -n "$task_python" ]] || fail \
  "No Python environment with numpy and pyarrow was found. Reuse the Wave 2B2A environment via POOL_MAIN_PYTHON=/absolute/path/to/python."

export PYTHONPATH="$task_bundle${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1 NUMEXPR_NUM_THREADS=1

task_log="$task_transfer/pool_main_c7r_linear_combination_$(date -u +%Y%m%dT%H%M%SZ)_$$.log"
exec > >(tee -a "$task_log") 2>&1

printf 'C7R linear-combination closure v1.0.0\n'
printf 'Expected elapsed time: 2-6 minutes on the configured Mac/XT_Pro setup.\n'
printf 'No network access and no chronology rebuild are required.\n'
printf 'Log: %s\n\n' "$task_log"

"$task_python" -B -u test_closure.py
"$task_python" -B -u run_closure.py \
  --model-cache "$task_cache" \
  --c7r-public "$task_c7r_public" \
  --output-base "$task_output" \
  --transfer-root "$task_transfer" \
  --threads "${POOL_MAIN_THREADS:-8}"

printf '\nCLOSURE COMPLETE. Upload the newest matching ZIP and .sha256 from:\n%s\n' "$task_transfer"
