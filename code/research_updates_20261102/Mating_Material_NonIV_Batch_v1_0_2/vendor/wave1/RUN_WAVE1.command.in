#!/bin/bash
set -euo pipefail
umask 077
shopt -s nullglob

task_bundle="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
task_project="${POOL_MAIN_PROJECT:-/Volumes/XT_Pro/lichess_kindness}"
task_sample="${POOL_MAIN_SAMPLE:-$task_project/derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE}"
task_transfer="${POOL_MAIN_TRANSFER:-$HOME/Desktop/Lichess_Desktop}"

fail() {
  printf 'STOP: %s\n' "$*" >&2
  exit 1
}

[[ -d "$task_project" ]] || fail "Project folder not found; connect XT_Pro: $task_project"
[[ -f "$task_sample/_SUCCESS.json" && -d "$task_sample/panel" ]] || \
  fail "Certified pool-main sample not found: $task_sample"
mkdir -p "$task_transfer"
cd "$task_bundle"
/usr/bin/shasum -a 256 -c PACKAGE_MANIFEST.sha256 || fail "Package checksum validation failed."

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
  [[ -n "$task_base_python" ]] || \
    fail "No usable Python 3.9+ found. Set POOL_MAIN_PYTHON to an absolute interpreter path."
  task_environment="$(mktemp -d "$task_transfer/pool_main_wave1_python.XXXXXX")"
  printf 'Creating an isolated analysis environment: %s\n' "$task_environment"
  "$task_base_python" -m venv "$task_environment" || fail "Could not create the analysis environment."
  task_python="$task_environment/bin/python"
  "$task_python" -I -m pip --disable-pip-version-check --require-virtualenv install \
    --only-binary=:all: --no-user -r "$task_bundle/requirements.lock.txt" || \
    fail "Dependency installation failed; see the pip error above."
fi

"$task_python" - <<'PY'
import sys, duckdb, numpy, pandas, pyarrow, matplotlib
print("Python:", sys.executable)
print("Versions:", "duckdb", duckdb.__version__, "numpy", numpy.__version__,
      "pandas", pandas.__version__, "pyarrow", pyarrow.__version__,
      "matplotlib", matplotlib.__version__)
PY

export PYTHONPATH="$task_bundle${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 MPLBACKEND=Agg
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1 NUMEXPR_NUM_THREADS=1

printf '\nRunning offline provenance and estimator self-tests.\n'
if [[ "${WAVE1_SKIP_CONTROLLED_SMOKE:-0}" != "1" ]]; then
  "$task_python" -B -u -m runner.self_test --full-controlled-smoke
else
  "$task_python" -B -u -m runner.self_test
fi

printf '\nStarting the authenticated pool-main reanalysis.\n'
printf 'Sample: %s\n' "$task_sample"
printf 'Results root: %s\n' "$task_project/output/pool_main_reanalysis_v100/wave1"
printf 'Private restart state: %s\n' "$task_project/derived/replication/pool_main_reanalysis_v100_PRIVATE/wave1"
printf 'Transfer destination: %s\n' "$task_transfer"
printf 'Rerun this launcher after interruption; completed stages authenticate and skip.\n\n'

task_command=(
  "$task_python" -B -u -m runner.orchestrate
  --project-root "$task_project"
  --sample-root "$task_sample"
  --transfer-root "$task_transfer"
  --threads "${POOL_MAIN_THREADS:-8}"
  --hash-workers "${POOL_MAIN_HASH_WORKERS:-8}"
  --model-workers "${POOL_MAIN_MODEL_WORKERS:-4}"
  --memory-limit "${POOL_MAIN_MEMORY:-12GB}"
  --worker-memory-limit "${POOL_MAIN_WORKER_MEMORY:-2.5GB}"
)
task_command+=("$@")

if command -v caffeinate >/dev/null 2>&1; then
  /usr/bin/caffeinate -dimsu "${task_command[@]}"
else
  "${task_command[@]}"
fi
