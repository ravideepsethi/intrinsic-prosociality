#!/bin/bash
set -euo pipefail
umask 077
shopt -s nullglob

task_bundle="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
task_project="${POOL_MAIN_PROJECT:-/Volumes/XT_Pro/lichess_kindness}"
task_sample="${POOL_MAIN_SAMPLE:-$task_project/derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE}"
task_transfer="${POOL_MAIN_TRANSFER:-$HOME/Desktop/Lichess_Desktop}"
task_wave2b1_private="${POOL_MAIN_WAVE2B1_PRIVATE:-$task_project/derived/replication/pool_main_reanalysis_v100_PRIVATE/wave2b1}"
task_wave2b1_public="${POOL_MAIN_WAVE2B1_PUBLIC:-$task_project/output/pool_main_reanalysis_v100/wave2b1}"
task_wave2b2a_private="${POOL_MAIN_WAVE2B2A_PRIVATE:-$task_project/derived/replication/pool_main_reanalysis_v100_PRIVATE/wave2b2a}"
task_wave2b2a_public="${POOL_MAIN_WAVE2B2A_PUBLIC:-$task_project/output/pool_main_reanalysis_v100/wave2b2a}"
task_old_dyad="${POOL_MAIN_FREQUENT_DYAD_STATE:-$task_project/derived/replication/frequent_dyad_census_24m_v101_PRIVATE}"
task_private="${POOL_MAIN_WAVE2B2B1_PRIVATE:-$task_project/derived/replication/pool_main_reanalysis_v100_PRIVATE/wave2b2b1}"
task_public="${POOL_MAIN_WAVE2B2B1_PUBLIC:-$task_project/output/pool_main_reanalysis_v100/wave2b2b1}"

fail() {
  printf 'STOP: %s\n' "$*" >&2
  exit 1
}

[[ -d "$task_project" ]] || fail "Project folder not found; connect XT_Pro: $task_project"
[[ -f "$task_sample/_SUCCESS.json" && -d "$task_sample/panel" ]] || \
  fail "Certified pool-main sample not found: $task_sample"
[[ -f "$task_wave2b1_public/WAVE2B1_RUN_STATUS.json" ]] || \
  fail "Certified Wave 2B1 result is missing: $task_wave2b1_public/WAVE2B1_RUN_STATUS.json"
[[ -f "$task_wave2b2a_public/WAVE2B2A_RUN_STATUS.json" ]] || \
  fail "Certified Wave 2B2A result is missing: $task_wave2b2a_public/WAVE2B2A_RUN_STATUS.json"
[[ -f "$task_old_dyad/state_config.json" ]] || \
  fail "Exact invariant frequent-dyad state is missing: $task_old_dyad/state_config.json"
mkdir -p "$task_transfer" "$task_private" "$task_public/logs"

if command -v caffeinate >/dev/null 2>&1 && [[ "${POOL_MAIN_CAFFEINATED:-0}" != "1" ]]; then
  export POOL_MAIN_CAFFEINATED=1
  exec /usr/bin/caffeinate -dimsu "$0" "$@"
fi

cd "$task_bundle"
/usr/bin/shasum -a 256 -c PACKAGE_MANIFEST.sha256 || \
  fail "Package checksum validation failed. Re-extract the supplied ZIP."

task_python=""
task_base_python=""
if [[ -n "${POOL_MAIN_PYTHON:-}" ]]; then
  task_candidates=("$POOL_MAIN_PYTHON")
else
  task_candidates=(
    "$task_project/venv/bin/python"
    "$task_project/.venv/bin/python"
    "${CONDA_PREFIX:-/nonexistent}/bin/python"
    "${VIRTUAL_ENV:-/nonexistent}/bin/python"
    "$task_transfer"/pool_main_wave1_python.*/bin/python
    "$task_transfer"/pool_main_wave2a_python.*/bin/python
    "$task_transfer"/pool_main_wave2b1_python.*/bin/python
    "$task_transfer"/pool_main_wave2b2a_python.*/bin/python
    "$HOME/anaconda3/bin/python"
    "$HOME/miniconda3/bin/python"
    "$HOME/miniforge3/bin/python"
    /opt/anaconda3/bin/python
    /opt/miniconda3/bin/python
    /opt/homebrew/bin/python3
    /usr/local/bin/python3
    "$(command -v python3 || true)"
    "$(command -v python || true)"
  )
fi

for task_candidate in "${task_candidates[@]}"; do
  [[ -n "$task_candidate" && -x "$task_candidate" ]] || continue
  if "$task_candidate" - <<'PY' >/dev/null 2>&1
import re, sys
assert sys.version_info >= (3, 9)
limits = {
    "duckdb": ((1, 5, 2), (1, 6, 0)),
    "numpy": ((2, 3, 0), (2, 6, 0)),
    "pandas": ((2, 2, 0), (3, 1, 0)),
    "pyarrow": ((24, 0, 0), (26, 0, 0)),
    "matplotlib": ((3, 10, 0), (3, 12, 0)),
}
for name, (low, high) in limits.items():
    module = __import__(name)
    pieces = tuple(int(x) for x in re.findall(r"\d+", module.__version__)[:3])
    version = pieces + (0,) * (3 - len(pieces))
    assert low <= version < high, (name, module.__version__)
PY
  then
    task_python="$task_candidate"
    break
  fi
  if [[ -z "$task_base_python" ]] && \
     "$task_candidate" -c 'import sys,venv; assert sys.version_info >= (3,9)' >/dev/null 2>&1; then
    task_base_python="$task_candidate"
  fi
done

if [[ -z "$task_python" ]]; then
  [[ "${POOL_MAIN_ALLOW_PIP:-0}" == "1" ]] || fail \
    "No compatible environment found. Reuse the Wave-1/Wave-2B1 environment, set POOL_MAIN_PYTHON, or explicitly rerun with POOL_MAIN_ALLOW_PIP=1."
  [[ -n "$task_base_python" ]] || \
    fail "No usable Python 3.9+ found. Set POOL_MAIN_PYTHON to an absolute interpreter path."
  task_environment="$(mktemp -d "$task_transfer/pool_main_wave2b2b1_python.XXXXXX")"
  printf 'Creating an isolated analysis environment: %s\n' "$task_environment"
  "$task_base_python" -m venv "$task_environment" || \
    fail "Could not create the analysis environment."
  task_python="$task_environment/bin/python"
  "$task_python" -I -m pip --disable-pip-version-check --require-virtualenv install \
    --only-binary=:all: --no-user -r "$task_bundle/requirements.lock.txt" || \
    fail "Dependency installation failed; see the pip error above."
fi

export PYTHONPATH="$task_bundle${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 MPLBACKEND=Agg
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1 NUMEXPR_NUM_THREADS=1

exec > >(tee -a "$task_public/logs/launcher.log") 2>&1

printf 'Pool-main Wave 2B2B1 v1.0.0: C6/C10, C6 ply, C12, and C7X dyad diagnostic\n'
printf 'Expected elapsed time: 35-75 minutes on the prior 10-core/12-GB setup.\n'
printf 'The run is checkpointed. Re-run this same command after interruption.\n\n'

"$task_python" - <<'PY'
import sys, duckdb, numpy, pandas, pyarrow, matplotlib
print("Python:", sys.executable)
print("Versions:", "duckdb", duckdb.__version__, "numpy", numpy.__version__,
      "pandas", pandas.__version__, "pyarrow", pyarrow.__version__,
      "matplotlib", matplotlib.__version__)
PY

printf '\nRunning offline source-binding and estimator self-tests.\n'
"$task_python" -B -u -m runner.self_test

printf '\nAuthenticating the sample, prior waves, histories, and exact dyad index.\n'
"$task_python" -B -u -m runner.preflight \
  --project-root "$task_project" \
  --sample-root "$task_sample" \
  --wave2b1-private "$task_wave2b1_private" \
  --wave2b1-public "$task_wave2b1_public" \
  --wave2b2a-private "$task_wave2b2a_private" \
  --wave2b2a-public "$task_wave2b2a_public" \
  --old-frequent-state "$task_old_dyad" \
  --private-base "$task_private" \
  --receipt "$task_public/PREFLIGHT.json" \
  --hash-workers "${POOL_MAIN_HASH_WORKERS:-10}" \
  --min-free-gb "${POOL_MAIN_MIN_FREE_GB:-80}"

printf '\nRunning/resuming Wave 2B2B1.\n'
printf 'Private restart state: %s\n' "$task_private"
printf 'Public aggregate results: %s\n\n' "$task_public"
"$task_python" -B -u -m runner.orchestrate \
  --project-root "$task_project" \
  --sample-root "$task_sample" \
  --wave2b1-private "$task_wave2b1_private" \
  --wave2b1-public "$task_wave2b1_public" \
  --wave2b2a-private "$task_wave2b2a_private" \
  --wave2b2a-public "$task_wave2b2a_public" \
  --old-frequent-state "$task_old_dyad" \
  --private-base "$task_private" \
  --public-base "$task_public" \
  --threads "${POOL_MAIN_THREADS:-8}" \
  --workers "${POOL_MAIN_WORKERS:-10}" \
  --memory-limit "${POOL_MAIN_MEMORY:-12GB}" \
  --batch-rows "${POOL_MAIN_BATCH_ROWS:-500000}"

printf '\nCollecting aggregate-only return artifacts.\n'
"$task_python" -B -u -m runner.collect \
  --sample-root "$task_sample" \
  --private-base "$task_private" \
  --public-base "$task_public" \
  --transfer-root "$task_transfer"

printf '\nWAVE 2B2B1 COMPLETE. Upload the newest matching ZIP and .sha256 from:\n%s\n' "$task_transfer"

