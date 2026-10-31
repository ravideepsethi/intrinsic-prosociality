Mating Material Patron Rerun — v1.0.0

EXPECTED RUNTIME
10–30 minutes on the 12-core Mac with XT_Pro; allow up to 45 minutes if
the Mac or drive is busy. Estimate, not a full-data benchmark: checks 1–5
minutes, histories/design 2–8, models 5–20. New environment setup adds
1–3 minutes. The existing MatingMaterial_Models_Env_v100 is reused.
For context, the returned persistence run took 7 minutes 8 seconds.
This stage estimates models; it does not repeat that bootstrap.

RUN
Put the ZIP in ~/Desktop/Lichess_Desktop. In Terminal:

bash <<'BASH'
set -euo pipefail
cd "$HOME/Desktop/Lichess_Desktop"
unzip -n -q Mating_Material_Patron_v1_0_0.zip
bash Mating_Material_Patron_v1_0_0/RUN_PATRON.command
BASH

Python 3.11–3.13; pinned numpy 2.3.5, pandas 2.3.3, pyarrow 20.0.0,
duckdb 1.3.2 and scipy 1.16.3. The launcher checks every package file,
uses the isolated environment and runs 20 tests before production.
Only first-time dependency installation needs a network connection.
Default 10 database threads, 11 GB memory setting (9 GB for the main
database stages, leaving headroom). Each numerical fit is sequential
with one BLAS thread; --memory-gb controls database allocation, not a
hard OS cap on pandas memory. At least 16 GiB free disk is required.

SOURCE FILES: EXACT HASHES CHECKED BEFORE ESTIMATION
Project root: __PRIVATE_VALUE_1__

Material manifest:
derived/replication/mating_material_first_run_v100_PRIVATE/
aa7e95f275c18f43/MATERIAL_RESTRICTED_INPUTS_READY_PRIVATE.json
Only the 24 new main panels named by that reviewed manifest are used.
Expected: 41,513,719 opportunities; 570,422 grants; 3,223,436 choosers.
The old missing AUTHOR_EXCLUDED_MAIN_READY_PRIVATE.json is not required.

Fixed acquisition roster:
derived/replication/pool_main_reanalysis_v100_PRIVATE/wave3a_patron/
f9dfa2718056/matching/acquisition_users_private.parquet
1,105,919 original targets; 57,938,596 bytes.
SHA256: 6b14aad34a726addd62bc192b7d443bfa743d54944aec3b08963151b143b9bf8

Fixed August profile snapshot:
derived/replication/patron_profile_snapshot_24m_v100_FINAL_CERTIFIED/
profile_snapshot_24m_private_lossless.parquet
SHA256: f42f28a6540a65c0a83f0da488663b4adddf60d1001daeed556f1ffbb961e238
Also checks the original snapshot audit and acquisition success receipt.
No new profile queries, engine evaluations or rating replay.

WHAT IS REBUILT
1. Fresh account histories, granting classifications, opportunity counts,
   count/speed cells, exposure covariates and full chooser design features.
2. The exact original v1.4.1 eligibility rule on frozen roles, groups and
   control slots. A focal must still grant somewhere, a control must never
   grant, their fresh matching cells must agree, and at least one eligible
   original control must remain. No replacement matches. Authors are
   excluded in both analytical roles and as acquisition focals.
3. All 34 original Wave3B1 core models and four corrected-date sensitivities.
   Includes the Table 4 main comparison, both grant-state indicators jointly,
   their covariance-based contrast, raw four-group rates, thresholds 2/4/5/10,
   dose/price checks, control ladders, stored-slot and missingness checks.
4. TWO SEPARATE SENSITIVITY FITS: the same min-four state model on all
   originally acquired surviving non-author accounts, even if a former
   control now grants or its focal/cell is no longer eligible. These are
   labelled broad_acquired, not silently substituted for the original
   adapter's main estimates. They address the manuscript's broader-cohort
   wording while keeping the main before/after comparison reproducible.
5. Table 4 CSV/LaTeX, before/after values, complete fit covariances,
   original-roster coverage and mutually exclusive eligibility-removal flow.

Preserved: August outcome/missingness definitions, profile-based descriptive
controls, original covariate imputation, original HC1/CR1 finite-sample
conventions, original rating-cost layer and the known historical-loss policy.
Unknown Patron outcomes are never converted to non-Patrons. The date fix
remains separately labelled. No September profile supplement is added.

OPTIMIZATION AND RESTART
Only required frozen files are authenticated; obsolete full history caches
are not scanned. One broad account-feature aggregation serves both cohorts.
The retained cache is an exact subset with fresh group counts. This is tested
against a separate unchanged producer build. Database stages and every
regression have checksummed checkpoints. Repeating the command verifies and
reuses completed work; corrupted checkpoints stop instead of being ignored.
The original data are read only. Interrupted temporary work is preserved.

OUTPUT AND RETURN
Private caches and run log:
<project>/derived/replication/mating_material_patron_v100_PRIVATE/<run-id>/
No account-level data go into the return ZIP.

Return files in ~/Desktop/Lichess_Desktop:
MATERIAL_PATRON_<run-id>_PATRON_READY.zip
MATERIAL_PATRON_<run-id>_PATRON_READY.zip.sha256
MATERIAL_PATRON_LATEST_PRIVATE.json

Send those three files back. The aggregate ZIP includes results, all 40
covariance matrices, lineage, eligibility audit, exact code and a file hash
manifest. A stopped run instead produces a FAILED ZIP and private traceback.
The top-level RETURN_STATUS.json always indicates whether this return passed.

SCOPE STILL PENDING
This completes the core Patron stage only. Tenure-restricted Patron models,
the recipient-badge association, opportunity-level and 100 fixed-slot rematch
sensitivities remain pending. Receipt/IV/entry/placebo families and the other
paper sensitivities also remain in DOWNSTREAM_STATUS.csv. The finished
persistence stage still has split-half/condition-adjusted checks outstanding.

TESTS AND SOURCE PROVENANCE
20 tests cover the material input contract, unchanged source hashes, exact
original-roster selection, new-grant/control and matching-cell changes,
author exclusions, independent dense-FE HC1/CR1 covariances and contrasts,
exhaustive binary missing-outcome bounds, nullable-median imputation,
fresh feature binding, shared-cache equivalence, full 40-model synthetic
CLI execution, completed resume, corrupt checkpoint rejection and report
privacy/hash verification. Production data are on your Mac; local tests use
synthetic data and never claim to reproduce new full-sample Patron results.

Original implementations are unmodified in vendor/patron. Source hashes
are in authority/VENDORED_SOURCES.json. evidence/v141_adapters.py is the
original adapter used for exact roster-equivalence testing. The two broad
cohort fits are explicitly implemented and labelled in code/patron.py.

OPTIONS
bash RUN_PATRON.command --estimate-only
bash RUN_PATRON.command --self-test
bash RUN_PATRON.command --preflight-only
bash RUN_PATRON.command --workers 6 --memory-gb 8
bash RUN_PATRON.command --project-root "__PRIVATE_VALUE_1__"

MMPATRON_ENV overrides the isolated environment location if needed.
MMR_PYTHON chooses the Python executable used to create/check it.
