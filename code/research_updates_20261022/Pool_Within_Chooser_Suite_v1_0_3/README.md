# Within-chooser suite v1.0.3: targeted completion of returned v1.0.2

The default launcher reruns ONLY S4 (exact-ply robustness). It authenticates the
bundled returned v102 report and your existing narrow Parquet cache, reuses the
completed results, and exports a combined report. No API calls or full panel
preparation are repeated. Do not run the older run_suite.py entry point; it is
retained for shared helpers and historical tests.

## Expected runtime and resources

Your v102 run took 447.4 seconds (7.46 minutes) before archiving with 10 workers.
This S4-only recovery is estimated at 3–6 minutes; allow 10 minutes, plus Python
environment setup. This is a planning estimate, not a measured full-panel run.
Up to 10 spawned processes use one numerical thread each. The narrow Parquet
cache is partitioned by chooser so clusters never cross workers. Memory is
bounded by batches; no 41.5-million-row design matrix is loaded at once.

## Run

Save this ZIP and its SHA sidecar to ~/Desktop/Lichess_Desktop. Mount XT_Pro.
Paste LAUNCH_MAC.txt into Terminal. The launcher runs the production-width
synthetic test, then recover_v102.py. It creates a unique private work directory
and writes a new report ZIP plus SHA sidecar to the Desktop transfer folder.

Expected cache location:
/Volumes/XT_Pro/lichess_kindness/derived/replication/within_chooser_suite_v102_PRIVATE/20260917T002432Z_12243_*/common_model_PRIVATE.parquet

If you moved this file, pass --cache /absolute/path/common_model_PRIVATE.parquet
to RUN_WITHIN_CHOOSER_SUITE.command. Its complete SHA must match the returned run.
If it is missing or changed, the script stops instead of using another sample.
Existing project data and prior results are never overwritten.

## What changed

The prior weighting repair passed. S4 alone still failed cluster-score
conservation (3.12768e-6 versus the unchanged 1e-7 threshold). Its exact cause is
not established. This version isolates S4 and uses explicit one-column
reductions for centering, predictions and cluster scores. It hashes the entire
centered design in both passes and compares independent response cross-products.
Original Gram checks, normal-equation checks and score tolerances remain.
The statistical specification, sample, weights and clustering are unchanged.

Completed A/S1/S2/S3 coefficients and covariances are authenticated and exported;
weighting, chooser-by-speed, Patron, rating and recipient-FE results are reused.
If S4 fails, the script still produces a clearly marked partial diagnostic ZIP.
No claim of full completion is made until this private-data run passes.

## Included results and tests

verified_v102_states/ contains the four recovered state tables, coefficients,
contrasts and covariance files from your returned v102 run. COMPARISON.parquet
and COMPARISON.tex provide the main/weighted/chooser-by-speed table.
Read METHODS.md for estimands and the selected-sample Patron qualification.
VALIDATION.json records synthetic and orchestration checks. These tests do not
substitute for the real private-panel calculation on your Mac.
