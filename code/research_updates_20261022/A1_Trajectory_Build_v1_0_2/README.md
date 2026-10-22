# A1 Trajectory Build v1.0.2

This release removes the slow creation of 7,047 separate plan Parquet files.
The same 2,110,400 targets are now stored in 22 nonempty monthly Parquets, with
one 300-game row group per original API batch. Game order and batch boundaries
are unchanged. The two empty months produce no snapshot file or request.

The entire plan is authenticated by file hashes. During recovery the current
monthly snapshot is kept open, checked in full on first use, and each batch's
decoded values are checked against their own hash. Changes during use stop
the run. Plan creation prints each month's progress. Recovery prints each
batch, with a 45-second status heartbeat during longer operations.

The Python 3.13 worker-shutdown fix from v1.0.1 is retained. Each batch closes
its engine explicitly before returning. A worker's bounded score cache remains
reusable. All 27 offline tests pass on Python 3.12.14 and 3.13.15 on Linux;
macOS itself was not available here. Tests print diagnostic stacks after
45 seconds and stop after 180 seconds if they stall. That limit applies only
to the offline tests.

Run on the work Mac with XT_Pro connected, using the Python environment that ran
A1 preparation. This package downloads complete moves and clocks for the fixed
2,110,400 A1 games, reconstructs the requested earlier boards, then automatically
runs Stockfish and writes a trajectory balance report. It uses up to ten engine
workers. It makes no new A1 or IV treatment-effect estimates.

Start this job after any other Lichess API downloader has finished. The engine
stage makes no API requests. Keep the Mac powered, awake with the lid open, and
XT_Pro connected. The launcher uses caffeinate. Nothing is installed, and no
upstream files are overwritten.

## Run

Save this ZIP and its checksum in ~/Desktop/Lichess_Desktop. Paste the entire
block into Terminal:

```bash
/bin/bash <<'BASH'
set -euo pipefail
cd "$HOME/Desktop/Lichess_Desktop"
/usr/bin/shasum -a 256 -c A1_Trajectory_Build_v1_0_2.zip.sha256
if [[ ! -d A1_Trajectory_Build_v1_0_2 ]]; then
  /usr/bin/ditto -x -k A1_Trajectory_Build_v1_0_2.zip .
fi
export A1_TRAJ_PYTHON="$PWD/A1_Session_Trajectory_Prepare_v1_0_0/.venv/bin/python"
export A1_TRAJ_PROJECT_ROOT="/Volumes/XT_Pro/lichess_kindness"
export A1_TRAJ_DESKTOP="$PWD"
export A1_TRAJ_WORKERS=10
/bin/bash "$PWD/A1_Trajectory_Build_v1_0_2/RUN_BUILD.command"
BASH
```

The same block resumes after an interruption. Completed response batches and
completed Stockfish batches are checked and reused. In-flight work may repeat.
The HTTP response cache has a key based on request IDs/options independently of
analysis code, so a later code fix can still reuse those complete responses.
Stop the older run with Ctrl+C and wait for its prompt before this launch.
Moving to v1.0.2 creates a new analysis configuration. The incomplete old plan
is left in place; the compact plan is rebuilt from authenticated source targets.
Completed full-move API responses are reused even across this code change.
Older replay/engine checkpoints are not silently adopted under the new code.

At the previous 29 games/second, downloads alone would take roughly 20 hours.
The short final-position pilot suggested about 74 engine hours. Full-move
payloads, local writes, earlier-board complexity, score reuse, thermal load and
server backoffs can change those figures. Use the live recovery rate for the
current download ETA. The monthly-plan optimization has not been timed on
the work Mac; it removes thousands of file creations from preparation.

## Outputs

The log is printed at startup and saved on Lichess_Desktop. After recovery, an
aggregate report is printed beside UPLOAD; Stockfish then starts automatically.
After the engine and assembly finish, upload the FINAL A1_TRAJECTORY_REPORT ZIP
and its .sha256. The final SUMMARY status begins A1_TRAJECTORY_BUILD_COMPLETE.
An early stop during recovery also produces a small diagnostic report.

Private full responses and reproducible Parquets stay on XT_Pro under:

`derived/replication/a1_trajectory_build_v100_PRIVATE/`

- `api_payloads/`: compressed full NDJSON, exact request IDs, checksums.
- `<config>/plan/month_XX.parquet`: monthly snapshots with 300-row groups.
- `<config>/plan/units.json`: the fixed batch order, row-group pointers and hashes.
- `<config>/replay/`: move verification and requested earlier FENs.
- `<config>/engine/`: per-board engine results and per-game features.
- `<config>/final/trajectory_features_PRIVATE.parquet`: every target, with
  original row IDs, weights and explicit missingness.
- `<config>/final/trajectory_balance.csv` and `sample_accounting.json`: aggregate
  balance and recovery accounting, also in the final report ZIP.

The existing preparation directory is required. The original source data and
A1 result are authenticated; the package does not recreate that earlier work.
Stockfish must match the binary used in the preparation benchmark. If its path
is not found automatically, set A1_TRAJ_STOCKFISH to that executable.

Only aggregate tables and methodological notes enter the report ZIP. Account
IDs, game IDs, full moves, clocks and local file inventories remain private.
Read DESIGN.md for exact feature definitions and treatment of missingness.
Session-state controls, elapsed move times, and weighted sensitivity/regression
estimates are subsequent steps; this run builds trajectory inputs and balance.
