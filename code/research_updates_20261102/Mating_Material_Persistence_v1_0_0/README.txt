Mating Material Persistence v1.0.0
================================

Expected runtime: 15–40 minutes on your 12-core Mac using 10 workers and
11 GB, including input authentication. The existing model environment is
reused. A fresh dependency setup adds 1–3 minutes. Bootstrap progress prints
elapsed time and remaining ETA every 25 resamples. Allow 16 GiB free on XT_Pro.
These are planning estimates; no full-data timing is available for this stage.

RUN
Put Mating_Material_Persistence_v1_0_0.zip in ~/Desktop/Lichess_Desktop.
Paste these two lines in Terminal:

unzip -n -q "$HOME/Desktop/Lichess_Desktop/Mating_Material_Persistence_v1_0_0.zip" -d "$HOME/Desktop/Lichess_Desktop"
bash "$HOME/Desktop/Lichess_Desktop/Mating_Material_Persistence_v1_0_0/RUN_PERSISTENCE.command"

The command can be run from any working directory. The setup checks the package
hashes and pinned dependencies, then runs synthetic tests before production.
It uses ~/Desktop/Lichess_Desktop/MatingMaterial_Models_Env_v100, already created
by the preceding model stage; MMP_ENV may point to another identical environment.

Rerun the same command after interruption. Completed account caches and bootstrap
checkpoints are checked by hash; a completed run re-exports its verified results.
Interrupted bootstrap work resumes from the last committed group of 25 draws.
Input authentication still runs on every launch. A detected corrupt committed
cache stops with a diagnostic; it is never silently accepted or edited.

INPUTS AND OUTPUTS
Default project: /Volumes/XT_Pro/lichess_kindness
Exact reviewed parent:
derived/replication/mating_material_first_run_v100_PRIVATE/aa7e95f275c18f43/
MATERIAL_RESTRICTED_INPUTS_READY_PRIVATE.json

Only the 24 material-restricted MAIN Parquets are read for estimation. The
manifest, parent completion receipt, parent returned results, monthly counts,
full file hashes, independent census, and both-role author exclusion are checked.
No old author-excluded ready manifest is required. No old behavioral account
cache is used. Original prices and factual game chronology remain unchanged.
Known historical chooser-loss records retain their original zero grant label.

Private rebuilt account histories and checkpoints:
derived/replication/mating_material_persistence_v100_PRIVATE/<run-id>/PRIVATE/

Aggregate results:
derived/replication/mating_material_persistence_v100_PRIVATE/<run-id>/report/

Return files in ~/Desktop/Lichess_Desktop:
MATERIAL_PERSISTENCE_<run-id>_PERSISTENCE_READY.zip
MATERIAL_PERSISTENCE_<run-id>_PERSISTENCE_READY.zip.sha256
MATERIAL_PERSISTENCE_LATEST_PRIVATE.json

Upload the ZIP and SHA256 sidecar when complete. The report includes aggregate
tables, bootstrap statistics/replications, source code and execution provenance.
No account IDs, game records or private account histories enter that ZIP.
A failed run instead writes a _FAILED.zip and leaves diagnostics on XT_Pro.

SCOPE AND SPECIFICATIONS
1. Table 3 Panel A: at least one competitive opportunity in each year and at
   least four total; equal-account and total-opportunity correlations, pooled
   second-year grant rates by first-year grant history, and their ratio.
2. Panels B/C: at least four competitive and four clearly-worse opportunities
   in EACH year; own-state and cross-state correlations, both implied propensity
   correlations, and the 4-by-4 transition table. Never-granting accounts remain.
3. 1,999 uniform account bootstrap draws per cohort, retaining each account's
   complete history and original weights. B/C share every draw. A is separate.
   SE = replicate SD (ddof=1); auxiliary intervals = percentile 95%.
4. Original thresholds 1, 4 and 10, selectivity persistence, retention, after-ply-10
   and all-noncompetitive comparisons, and the four weighted state regressions.
   Competitive is evaluation >= -100; clearly worse is <= -300. The intervening
   region enters the all-noncompetitive sensitivity, not the primary C/L groups.
   Periods: Nov 2023–Oct 2024; Nov 2024–Oct 2025.

The original F v1.0.2 aggregation, design, QR estimation, joint account covariance,
threshold and sensitivity functions are vendored unchanged. The old PAPER count
constants are replaced at runtime by the independently checked new census. The
old f0 function's hard-coded cohort warning is replaced with the same weighted
and unweighted correlations and a fresh cohort count. Bootstrap matrix, decoder
and resampling functions are the unchanged Submission_Checks_20261025 kernels.
All four vendored sources have recorded SHA256 hashes.

The recovered supplemental regression producer includes log opportunity counts
in BOTH years/states, and outcome-state second-year rating, rating gap, capped
evaluation, plies and speed shares. It weights each outcome by its second-year
opportunities and uses the original joint n/(n-1) account-robust covariance.
The manuscript note currently mentions only speed controls. This package keeps
the actual producer specification and records the note correction needed.

Optimizations: projected-column Parquet scans; one annual aggregation and one
wide account cache; shared read-only bootstrap sufficient-statistic matrices;
10 threads with one numerical-library thread each; deterministic per-replicate
random seeds; versioned atomic checkpoints. Account order is explicitly sorted
so worker count cannot alter the resampling indices. No large matrix is copied
per worker. No API, Stockfish, rating replay, profile query or new matching.

Main exports: tab_persistence.csv/.tex, tab_supp_state_corr.csv,
tab_supp_state_regressions.csv, PERSISTENCE_BEFORE_AFTER.csv, bootstrap joint
covariance and all replicate statistics. Before/after comparisons use the
reviewed v1.4.2 author-excluded persistence and original Table 3 bootstrap.
No significance test of before/after differences is implied by those columns.

Split-half and condition-adjusted persistence benchmarks are NOT completed by
this stage. Patron, receipt/IV and the other remaining robustness families also
remain pending. DOWNSTREAM_STATUS.csv carries their status forward. A successful
status is PERSISTENCE_COMPLETE_MORE_FAMILIES_PENDING, not a completed paper rerun.

PRECEDING CORE-MODEL RESULTS REVIEW
The returned MATERIAL_MODELS_4823c3c8c0eb800d_MODELS_READY.zip passed its SHA256,
ZIP CRC and all 82 internal manifest entries. Its model census matches stage 1:
41,513,719 decisions, 570,422 grants, 3,223,436 choosers; zero invalid material
labels. All 26 models completed. Fit time after input authentication: 22m 6s,
including 7m 53s for R11 and 13m 52s for continuous/material models.

Selected changes (percentage points unless a rate is explicitly marked %):
                                             Before       After       New SE
Adjusted clearly-worse grant rate (%)        0.634630     0.634692     0.004737
Adjusted roughly-equal grant rate (%)        2.045290     2.067753     0.009351
Adjusted clearly-better grant rate (%)       3.632565     3.671006     0.014828
Competitive decline, 41–80 vs 0–4 plies      -2.330542    -2.334508     0.019311
Competitive rebound, 81+ vs 41–80 plies       0.369606     0.698958     0.031154
Noncompetitive rebound                       -0.070108    -0.070110     0.005482
Continuous +500 vs +300 centipawns            1.020640     1.022563     0.018116

The long-game competitive rebound changes materially; update the manuscript's
0.37 pp statement to 0.70 pp after the remaining stage checks. The earlier
decline and central rating-gap comparison change little. The new competitive
+100 vs -100 rating-gap contrast is 1.019866 pp (SE 0.017770); its noncompetitive
counterpart is 0.037005 pp (SE 0.007297). Noncompetitive here includes the middle
evaluation region, matching the regression specification.
The raw cell comparison locates 19,466 of the 20,570 excluded decisions and
305 of the 332 newly labeled grants in the 81-or-more-ply band.

Full matched core-model comparison (1,487 estimates):
evidence/core_model_review/before_after.csv

VALIDATION
TEST_RESULTS.txt records contract, literal bootstrap, independent weighted
least-squares/covariance, full synthetic pipeline, annual-boundary, resumed
bootstrap, corruption and privacy checks. All 20 tests passed, including a full
CLI run with 1,999 synthetic resamples, completed resume and integrity failure.
These tests do not substitute for
executing the new empirical stage on the Mac's authenticated input files.

Optional checks:
bash RUN_PERSISTENCE.command --estimate-only
bash RUN_PERSISTENCE.command --preflight-only
bash RUN_PERSISTENCE.command --workers 6 --memory-gb 8
