# Pool Activity / Rating Adjustment — v1.0.0

Test whether rating composition accounts for the previously observed activity-group pattern. The runner produces:

1. Mean/median chooser rating and rating–activity correlations for light, medium and heavy choosers.
2. Competitive and clearly-worse granting rates within rating/time-control cells.
3. Unadjusted, rating-standardized and rating-plus-time-control-standardized comparisons on the same common-support sample, including gaps, rate ratios, heavy/light contrasts and paired change intervals.

The program retains observed zero-grant choosers. Common support is defined using covariates and chooser counts, never granting. Its starting sample is the same 1,982,345 both-state choosers; all support exclusions are reported.

Rating means the chooser's average pre-game rating in their most-used observed time control, jointly defined with speed. The outcome rates still use all of their binary opportunities. This adjusts typical skill and preferred time control; it does not hold every focal game's covariates fixed. Full definitions and inference are in `docs/METHODS.md`.

## Run on the Mac

Place the ZIP and SHA-256 sidecar in `~/Desktop/Lichess_Desktop`. Connect `XT_Pro`. Paste this entire block into Terminal:

```bash
/bin/bash <<'BASH'
set -euo pipefail
task_root="$HOME/Desktop/Lichess_Desktop"
cd "$task_root"
/usr/bin/shasum -a 256 -c Pool_Activity_Rating_Adjustment_v1_0_0.zip.sha256
task_stage="$(/usr/bin/mktemp -d "$task_root/activity_rating_adjustment.XXXXXX")"
/usr/bin/ditto -x -k Pool_Activity_Rating_Adjustment_v1_0_0.zip "$task_stage"
task_log="$task_root/activity_rating_adjustment_$(/bin/date -u +%Y%m%dT%H%M%SZ).log"
RATING_ADJ_WORKERS=4 RATING_ADJ_THREADS=8 \
  /bin/bash "$task_stage/Pool_Activity_Rating_Adjustment_v1_0_0/RUN_ACTIVITY_RATING_ADJUSTMENT.command" \
  2>&1 | /usr/bin/tee "$task_log"
BASH
```

The launcher checks the package, reuses a compatible Python environment or creates an isolated one, runs the small synthetic checks, and keeps the Mac awake during the analysis. It uses four monthly scan workers (1 GB DuckDB memory each), then an eight-thread merge (4 GB). Workers may be set from 1 to 10. It uses no Lichess API or Stockfish work.

Estimated first-run time: **2–6 minutes**, depending on drive speed and load. This is an estimate, not a full-panel benchmark of this new runner. The preceding simpler chooser-support audit took about 77 seconds on the source machine. The new pass reads rating and time-control columns, builds reusable profiles, and authenticates about 12.6 GB of existing source Parquets. Python installation, if needed, takes additional time.

The success marker is `ACTIVITY_RATING_ADJUSTMENT_COMPLETE`. Upload the new `POOL_ACTIVITY_RATING_ADJUSTMENT_RESULTS_v100_*.zip` and matching `.zip.sha256` created in `Lichess_Desktop`.

## Inputs and outputs

Required existing inputs:

- `/Volumes/XT_Pro/lichess_kindness/derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE`
- `/Volumes/XT_Pro/lichess_kindness/derived/replication/pool_chooser_support_v100_PRIVATE`

New private cache:

- `/Volumes/XT_Pro/lichess_kindness/derived/replication/pool_activity_rating_adjustment_v100_PRIVATE`

Aggregate results:

- `/Volumes/XT_Pro/lichess_kindness/output/pool_activity_rating_adjustment_v100/run_<timestamp>`

The old census and panel are read-only. Chooser identifiers and individual profiles stay in the new private cache. Only aggregate tables, methods, a LaTeX table and audit receipts enter the return ZIP.

## Resume and configuration

To resume an interrupted run, run the same command again. Completed monthly caches are reused after checksum/contract checks. Source panel hashes are verified each run. No stale or incompatible cache is silently reused or deleted.

Overrides: `RATING_ADJ_PROJECT`, `RATING_ADJ_SOURCE`, `RATING_ADJ_SAMPLE`, `RATING_ADJ_TRANSFER`, `RATING_ADJ_PYTHON`, `RATING_ADJ_WORKERS`, `RATING_ADJ_THREADS`, `RATING_ADJ_WORKER_MEMORY`, `RATING_ADJ_MERGE_MEMORY`. Defaults use the paths above. Do not point the source variables at the old unfiltered panel; the source fingerprint is enforced.

## Validation and claim limits

The build validation covers pure rating composition, pure time-control composition, residual activity differences, exact rating/activity boundaries, common support, zero-grant and missing-rating cells, paired covariance, source joins, parallel execution, resumability, corruption detection and aggregate exports. Actual adjusted estimates require the Mac's private panel; no production rating-adjustment result was calculated during packaging.

The runner first reproduces all previously returned state-rate rows and the minimal FE reference. It then verifies the new scan's counts and grants for every binary-sample chooser. Any mismatch stops the run. Its comparison supplements the paper's results; it does not replace or reestimate the paper's other adjusted specifications.
