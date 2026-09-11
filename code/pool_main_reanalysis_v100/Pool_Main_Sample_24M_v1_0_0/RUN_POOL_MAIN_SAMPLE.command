#!/bin/bash
set -euo pipefail
umask 077
shopt -s nullglob

task_bundle="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
task_desktop="${POOL_MAIN_DESKTOP:-$HOME/Desktop/Lichess_Desktop}"
task_project="${POOL_MAIN_PROJECT:-/Volumes/XT_Pro/lichess_kindness}"
task_output="${POOL_MAIN_OUTPUT:-$task_project/derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE}"
task_reports="${POOL_MAIN_REPORT_ROOT:-$task_project/output/pool_main_sample_24m_v100}"
fail() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
[[ -d "$task_project" ]] || fail "Project folder not found; connect XT_Pro: $task_project"
cd "$task_bundle"
/usr/bin/shasum -a 256 -c PACKAGE_MANIFEST.sha256
mkdir -p "$task_desktop"

task_python=""
task_base=""
if [[ -n "${POOL_MAIN_PYTHON:-}" ]]; then
  task_candidates=("$POOL_MAIN_PYTHON")
else
  task_candidates=(
    "${CONDA_PREFIX:-/nonexistent}/bin/python"
    "${VIRTUAL_ENV:-/nonexistent}/bin/python"
    "$(command -v python3 || true)" "$(command -v python || true)"
    "$task_project/replication_package/.venv/bin/python"
    "$task_project/.venv/bin/python"
    "$HOME"/projects/lichess_kindness/.venv*/bin/python
    "$HOME"/projects/lichess_kindness/venv*/bin/python
    "$task_desktop"/pool_main_python.*/bin/python
    "$task_desktop"/pool_predecessor_python.*/bin/python
    "$task_desktop"/source_union_python.*/bin/python
    "$task_desktop"/source_api_python.*/bin/python
    "$HOME/anaconda3/bin/python" "$HOME/miniconda3/bin/python"
    "$HOME/miniforge3/bin/python" "$HOME/mambaforge/bin/python"
    /opt/anaconda3/bin/python /opt/miniconda3/bin/python
    /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3
    "$HOME"/anaconda3/envs/*/bin/python "$HOME"/miniconda3/envs/*/bin/python
    "$HOME"/miniforge3/envs/*/bin/python "$HOME"/mambaforge/envs/*/bin/python
    "$HOME"/.conda/envs/*/bin/python /opt/anaconda3/envs/*/bin/python
    /opt/miniconda3/envs/*/bin/python
    /Library/Frameworks/Python.framework/Versions/*/bin/python3
  )
fi
for task_candidate in "${task_candidates[@]}"; do
  [[ -x "$task_candidate" ]] || continue
  if "$task_candidate" -c 'import sys; assert sys.version_info >= (3,9)' >/dev/null 2>&1; then
    if "$task_candidate" -c 'import duckdb, pyarrow; v=tuple(map(int,duckdb.__version__.split(".")[:3])); assert (1,5,4)<=v<(1,6,0); assert 18<=int(pyarrow.__version__.split(".")[0])<26' >/dev/null 2>&1; then
      task_python="$task_candidate"
      break
    fi
    if [[ -z "$task_base" ]] && "$task_candidate" -c 'import venv' >/dev/null 2>&1; then
      task_base="$task_candidate"
    fi
  fi
done
if [[ -z "$task_python" ]]; then
  [[ -n "$task_base" ]] || fail "No usable Python 3.9+ found. Set POOL_MAIN_PYTHON to its absolute path."
  task_env="$(mktemp -d "$task_desktop/pool_main_python.XXXXXX")"
  printf 'Creating a separate environment for DuckDB and PyArrow: %s\n' "$task_env"
  "$task_base" -m venv "$task_env" || fail 'Could not create the separate Python environment.'
  task_python="$task_env/bin/python"
  "$task_python" -I -m pip --disable-pip-version-check --require-virtualenv install \
    --only-binary=:all: --no-user 'duckdb==1.5.4' 'pyarrow>=18,<26' || fail 'Dependency setup failed; see the pip error above.'
fi
"$task_python" -c 'import sys, duckdb, pyarrow; print("Python:",sys.executable); print("DuckDB:",duckdb.__version__,"PyArrow:",pyarrow.__version__)'

export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
mkdir -p "$task_reports"
task_stamp="$(date -u +%Y%m%dT%H%M%SZ)_$$"
task_log="$task_reports/main_sample_$task_stamp.log"
task_tests="$task_reports/self_test_$task_stamp.log"
printf 'Checking sample selection, full-schema copying, accounting and resume on offline fixtures.\n'
"$task_python" -B -m unittest discover -s "$task_bundle" -p test_main_sample.py -v > "$task_tests" 2>&1 || {
  cat "$task_tests"
  fail "Self-test failed; production inputs were not opened. Log: $task_tests"
}
printf 'Self-test passed: %s\n' "$task_tests"
printf 'Building the main panel: expected 41,534,331 of 47,587,020 opportunities.\n'
printf 'Hash workers: %s; DuckDB threads: %s; DuckDB memory limit: %s.\n' \
  "${POOL_MAIN_WORKERS:-4}" "${POOL_MAIN_THREADS:-8}" "${POOL_MAIN_MEMORY:-6GB}"
printf 'Planning estimate: 30-120 minutes on an external SSD; input size, drive speed and spill can extend this.\n'
printf 'Free-space budget is calculated from actual Stage07 panel sizes before large writes. No Lichess requests.\n'
printf 'Main rule: pool plus observed non-adjacency; missing/ambiguous previous status is excluded.\n'
printf 'Resume by rerunning this command; completed stages are authenticated and reused.\n'
printf 'Project: %s\nPrivate outputs: %s\nReports: %s\nLog: %s\n' \
  "$task_project" "$task_output" "$task_reports" "$task_log"
printf 'Command:' >> "$task_log"
printf ' %q' "$task_python" "$task_bundle/build_main_sample.py" \
  --project "$task_project" --output "$task_output" --report-root "$task_reports" \
  --workers "${POOL_MAIN_WORKERS:-4}" --threads "${POOL_MAIN_THREADS:-8}" \
  --memory "${POOL_MAIN_MEMORY:-6GB}" "$@" >> "$task_log"
printf '\n' >> "$task_log"
"$task_python" -B -u "$task_bundle/build_main_sample.py" \
  --project "$task_project" --output "$task_output" --report-root "$task_reports" \
  --workers "${POOL_MAIN_WORKERS:-4}" --threads "${POOL_MAIN_THREADS:-8}" \
  --memory "${POOL_MAIN_MEMORY:-6GB}" "$@" 2>&1 | tee -a "$task_log"
