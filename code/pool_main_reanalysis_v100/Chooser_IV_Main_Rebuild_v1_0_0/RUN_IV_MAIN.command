#!/bin/bash
set -euo pipefail
task_package="$(cd "$(dirname "$0")" && pwd -P)"
cd "$task_package"
/usr/bin/shasum -a 256 -c PACKAGE_MANIFEST.sha256
export PYTHONDONTWRITEBYTECODE=1
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1
export TMPDIR="$(cd "${TMPDIR:-/tmp}" && pwd -P)"
task_project="${IV_MAIN_PROJECT_ROOT:-/Volumes/XT_Pro/lichess_kindness}"
task_desktop="${IV_MAIN_DESKTOP:-$HOME/Desktop/Lichess_Desktop}"
task_python="${IV_MAIN_PYTHON:-python3}"
if ! command -v "$task_python" >/dev/null 2>&1; then
  echo "Python 3 is unavailable. Open the work laptop's usual Anaconda Terminal and run this command again."
  exit 2
fi
if ! "$task_python" -c 'import numpy, pyarrow, duckdb; assert duckdb.__version__ == "1.5.4"' >/dev/null 2>&1; then
  task_env="$task_desktop/Chooser_IV_Main_Rebuild_python"
  if [[ ! -x "$task_env/bin/python3" ]]; then
    "$task_python" -m venv "$task_env"
  fi
  task_python="$task_env/bin/python3"
  "$task_python" -m pip install 'numpy==2.2.6' 'pyarrow==21.0.0' 'duckdb==1.5.4'
fi
"$task_python" test_rebuild.py
mkdir -p "$task_desktop"
task_log="$task_desktop/chooser_iv_main_rebuild_$(date -u +%Y%m%dT%H%M%SZ)_$$.log"
echo "Log: $task_log"
set +e
/usr/bin/caffeinate -i "$task_python" -u "$task_package/run_rebuild.py" \
  --project-root "$task_project" --desktop "$task_desktop" \
  --workers "${IV_MAIN_WORKERS:-10}" --memory-gb "${IV_MAIN_MEMORY_GB:-0}" \
  2>&1 | tee "$task_log"
task_exit=${PIPESTATUS[0]}
set -e
if [[ "$task_exit" -ne 0 ]]; then
  echo "Stopped with exit $task_exit. Keep this log: $task_log"
else
  echo "Finished. Upload the report ZIP and SHA shown above."
fi
exit "$task_exit"
