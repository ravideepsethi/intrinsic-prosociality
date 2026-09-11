#!/bin/bash
set -euo pipefail
umask 077
shopt -s nullglob

task_bundle="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
task_project="${POOL_MAIN_PROJECT:-/Volumes/XT_Pro/lichess_kindness}"
task_sample="${POOL_MAIN_SAMPLE:-$task_project/derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE}"
task_transfer="${POOL_MAIN_TRANSFER:-$HOME/Desktop/Lichess_Desktop}"
task_private="${POOL_MAIN_WAVE2B1_PRIVATE:-$task_project/derived/replication/pool_main_reanalysis_v100_PRIVATE/wave2b1}"
task_public="${POOL_MAIN_WAVE2B1_PUBLIC:-$task_project/output/pool_main_reanalysis_v100/wave2b1}"

fail() {
  printf 'STOP: %s\n' "$*" >&2
  exit 1
}

[[ -d "$task_project" ]] || fail "Project folder not found; connect XT_Pro: $task_project"
[[ -f "$task_sample/_SUCCESS.json" && -d "$task_sample/panel" ]] || \
  fail "Certified pool-main sample not found: $task_sample"
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
    "No existing compatible environment found. The prior Wave-1 environment should be reusable. To allow a new dependency download, rerun with POOL_MAIN_ALLOW_PIP=1."
  [[ -n "$task_base_python" ]] || \
    fail "No usable Python 3.9+ found. Set POOL_MAIN_PYTHON to an absolute interpreter path."
  task_environment="$(mktemp -d "$task_transfer/pool_main_wave2b1_python.XXXXXX")"
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

"$task_python" - <<'PY'
import sys, duckdb, numpy, pandas, pyarrow, matplotlib
print("Python:", sys.executable)
print("Versions:", "duckdb", duckdb.__version__, "numpy", numpy.__version__,
      "pandas", pandas.__version__, "pyarrow", pyarrow.__version__,
      "matplotlib", matplotlib.__version__)
PY

printf '\nRunning offline provenance, binding, and estimator self-tests.\n'
"$task_python" -B -u -m runner.self_test

printf '\nAuthenticating the package, all 24 panel files, and canonical chronology.\n'
"$task_python" -B -u -m runner.preflight \
  --project-root "$task_project" \
  --sample-root "$task_sample" \
  --receipt "$task_public/PREFLIGHT.json" \
  --hash-workers "${POOL_MAIN_HASH_WORKERS:-10}" \
  --min-free-gb "${POOL_MAIN_MIN_FREE_GB:-80}"

printf '\nStarting authenticated pool-main Wave 2B1.\n'
printf 'Sample: %s\n' "$task_sample"
printf 'Public receipts: %s\n' "$task_public"
printf 'Private restart state: %s\n' "$task_private"
printf 'Transfer destination: %s\n' "$task_transfer"
printf 'Rerun this launcher after interruption; certified stages authenticate and skip.\n\n'

task_command=(
  "$task_python" -B -u -m runner.orchestrate
  --project-root "$task_project"
  --sample-root "$task_sample"
  --private-base "$task_private"
  --public-base "$task_public"
  --workers "${POOL_MAIN_THREADS:-10}"
  --memory-limit "${POOL_MAIN_MEMORY:-12GB}"
  --worker-memory "${POOL_MAIN_WORKER_MEMORY:-3GB}"
  --batch-rows "${POOL_MAIN_BATCH_ROWS:-500000}"
)
task_command+=("$@")
"${task_command[@]}"

printf '\nCollecting aggregate-only return artifacts.\n'
"$task_python" -B -u -m runner.collect \
  --sample-root "$task_sample" \
  --private-base "$task_private" \
  --public-base "$task_public" \
  --transfer-root "$task_transfer"

printf '\nWAVE 2B1 COMPLETE. Upload the newest matching ZIP and .sha256 from:\n%s\n' "$task_transfer"
