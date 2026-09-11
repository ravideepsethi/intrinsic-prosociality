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
task_project="${IV_SELECTION_PROJECT_ROOT:-/Volumes/XT_Pro/lichess_kindness}"
task_desktop="${IV_SELECTION_DESKTOP:-$HOME/Desktop/Lichess_Desktop}"
if [[ -n "${IV_SELECTION_PYTHON:-}" ]]; then
  task_python="$IV_SELECTION_PYTHON"
elif [[ -x "$task_desktop/Chooser_IV_Main_Rebuild_python/bin/python3" ]]; then
  task_python="$task_desktop/Chooser_IV_Main_Rebuild_python/bin/python3"
else
  task_python="python3"
fi
if ! command -v "$task_python" >/dev/null 2>&1; then
  echo "Python 3 is unavailable. Set IV_SELECTION_PYTHON to the Python used for the chooser-IV rebuild."
  exit 2
fi
if ! "$task_python" -c 'import numpy, pyarrow' >/dev/null 2>&1; then
  echo "NumPy/PyArrow are unavailable. Set IV_SELECTION_PYTHON to the Python used for the chooser-IV rebuild."
  exit 2
fi
"$task_python" test_addendum.py
mkdir -p "$task_desktop"
task_log="$task_desktop/chooser_iv_selection_addendum_$(date -u +%Y%m%dT%H%M%SZ)_$$.log"
echo "Log: $task_log"
task_args=("$task_python" -u "$task_package/run_addendum.py" --project-root "$task_project" --desktop "$task_desktop")
set +e
if command -v /usr/bin/caffeinate >/dev/null 2>&1; then
  /usr/bin/caffeinate -i "${task_args[@]}" 2>&1 | tee "$task_log"
else
  "${task_args[@]}" 2>&1 | tee "$task_log"
fi
task_exit=${PIPESTATUS[0]}
set -e
if [[ "$task_exit" -ne 0 ]]; then
  echo "Stopped with exit $task_exit. Keep this log: $task_log"
else
  echo "Finished. Upload the report ZIP and SHA shown above."
fi
exit "$task_exit"
