Remaining Results — Consolidated v1.0.2
Prepared 2026-11-02

RUN THIS TARGETED CORRECTION

The 20261102T190254Z run finished all three jobs in 349.8 seconds. Its rating
validation, counts and five receipt estimates are retained. One estimate is
invalid: conditional_censored_at_next_competitive_disconnection, previously
reported as 1.025175 (0.213562) on 314,639 observations.

Cause: the frozen Arrow loader represents missing integer timestamps as -1.
The new conditional censoring code recognized NaN only, incorrectly excluding
recipients with no recorded later competitive disconnection. This release
uses the completed producer's convention: a timestamp is present if finite
and positive. The conditional sensitivity retains equality ties. The already
completed zero-coded censored primary estimate has separate code and remains
unchanged.

Save this ZIP to ~/Desktop/Lichess_Desktop, mount XT_Pro, then run:

  cd "$HOME/Desktop/Lichess_Desktop" && \
  unzip -n Remaining_Results_Consolidated_v1_0_2.zip && \
  bash Remaining_Results_Consolidated_v1_0_2/REPAIR_CENSORED.command

Dependencies are already installed in the environment verified by your
completed run. No pip command is needed. The launcher uses:
  ~/Desktop/Lichess_Desktop/MatingMaterial_Env_v100/bin/python

The default data source is:
  /Volumes/XT_Pro/lichess_kindness

Allow roughly 1–3 minutes for this correction, depending on drive I/O. This is
an estimate: the original run's reference and censored fits took seconds each,
but the repaired sample is larger. There is no chronology scan, rating replay,
engine evaluation or network data retrieval. The reference model is checked
again, and only the censored companion is newly estimated. Numerical-library
threads are limited to one. No PDF or manuscript is modified.

WHAT THE REPAIR DOES

1. Run all synthetic checks, including nullable integer timestamps loaded
   through the actual frozen Arrow converter, missing floating timestamps,
   complete windows, time boundaries, and retained equality ties.
2. Authenticate the embedded completed return ZIP and every file in it.
3. Authenticate the original corrected receipt Parquet and completed reference
   model against their producer receipts and the completed return's hashes.
4. Reconstruct the defective sample and require an exact match to the returned
   ordered-row hash and count. Restore only missing-timestamp observations.
5. Reproduce the completed conditional reference model's coefficient, standard
   error and ordered-row hash, then estimate the corrected censored model.
6. Export a corrected six-row RECEIPT_COMPANIONS.csv. Preserve the other five
   model JSON files, counts and rating results byte for byte. Retain the old
   censored estimate only as explicitly invalid audit history.

The embedded authority/COMPLETED_20261102T190254Z_RETURN.zip is the original
submitted report. Its censored row is superseded; do not use that old row.
The repair does not need you to locate or re-download that original return.

OUTPUT

Return this single file printed at completion:
  ~/Desktop/Lichess_Desktop/REMAINING_RESULTS_CENSOR_REPAIRED_<timestamp>_RETURN.zip

A successful return contains:
  receipt_companions/RECEIPT_COMPANIONS.csv — all six estimates;
  receipt_companions/conditional_censored_at_next_competitive_disconnection.json;
  repair/CENSOR_REPAIR_AUDIT.json — restored rows, timestamps, hashes and checks;
  counts/ — unchanged completed counts;
  rating_validation/ — unchanged completed rating validation;
  SELF_TEST.log — this release's checks;
  STATUS.json — COMPLETE only after correction and validation finish;
  RETURN_MANIFEST.json — checksums of the returned files.

The top-level success value is ALL_REQUESTED_RESULT_JOBS_COMPLETE and
repair_completed must be true. An error produces an INCOMPLETE diagnostic ZIP.
Return files contain aggregate results and logs, not private account-level
records. Raw p-values and confidence intervals are reported; no Holm or other
multiple-testing adjustments are added.

Private repair checkpoints use a new fingerprinted folder under:
  derived/replication/remaining_results_censor_repair_v102_PRIVATE/

Old private data and checkpoints are not overwritten. Re-running the same
repair command verifies and reuses completed repair fits.

FULL CODE AND OTHER RESULTS

All original consolidated source code is also included. RUN_RESULTS.command
can regenerate the complete three-job batch with the corrected censoring
function. For this completed run, use REPAIR_CENSORED.command instead.

The retained corrected receipt cohort contains 2,296,216 supported exposures,
2,112,426 complete 90-day windows and 994,454 reached competitive choices.
The conditional censoring sample size is calculated, never forced to match
the old manuscript. Original matching-cell weights, exposure controls, cell
and month effects, and chooser-clustered CR1 inference remain the same.

The hours model and engagement results use the corrected cohort and therefore
need not reproduce the earlier manuscript's sample counts. Rating validation
uses paired observed and predicted realized rating changes; it does not
directly validate the unobserved counterfactual payoff.

RESULTS_SCOPE.csv retains the full run/reuse/omit checklist. Already completed
IV, persistence, Patron and other models are not refitted by this correction.
Three historical quantities remain outside this declared batch: the all-time
IV on the both-before/after-supported intersection, scalar partial first-stage
R-squared, and strict-material IV without opponent-environment controls.
This batch does not certify the entire paper or its identification assumptions.

VALIDATION

VALIDATION.json records checks actually performed. Local tests use synthetic
data on Linux, including a symlinked temporary directory to emulate the Mac's
/var to /private/var path alias. Private XT_Pro data are not available here; the
corrected production coefficient will be known after the Mac run returns.
