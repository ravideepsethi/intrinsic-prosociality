Mating Material Receipt v1.0.0 — matched receipt rerun

Save the ZIP in ~/Desktop/Lichess_Desktop, extract it there, and run:
  bash "$HOME/Desktop/Lichess_Desktop/Mating_Material_Receipt_v1_0_0/RUN_RECEIPT.command"

Expected runtime on the 12-core Mac and XT_Pro:
  30–90 minutes if fresh first-exposure pairs need chronology reconstruction.
  10–25 minutes if all first-pair dates can be reused.
  Budget up to 2 hours on a busy drive. These are planning estimates, not a
  full-data benchmark. The scan prints its measured ETA as files complete.
  Startup tests take about 5–15 seconds. Existing pinned environment is reused;
  a missing environment adds approximately 1–3 minutes of installation.

Defaults: project __PRIVATE_VALUE_1__, 10 workers, 11 GB budget
(9 GB DuckDB limit plus Python/headroom), one BLAS thread, two hash workers.
At least 30 GiB free on XT_Pro is required for new caches and spill. Large
files stay on XT_Pro. Do not run another large model package simultaneously.

This is the next stage after the reviewed material input, core models,
persistence and Patron runs. It completes 18 matched-receipt regressions:
  * the four rows of tab_dynamics: zero-coded first-choice granting,
    next-disconnection censoring, reach, and conditional first-choice granting;
  * the five interval-profile rows;
  * later-choice controls, any later grant, and the later-receipt count;
  * start-hour and last-move-hour fixed effects for the primary, reach and
    conditional outcomes.
All IV analyses and the other pending families are separate later stages.
This package does not claim to complete the entire paper rerun.

WHAT IS REBUILT
The first competitive, non-tournament exposure is selected again from the
41,513,719 material-restricted main-panel rows. Dropping an earlier ineligible
event can move the first exposure. The original within-recipient start-time,
archive-ordinal and game-ID ranking is preserved. The historical non-arm
chooser-loss rule is preserved: it does not silently select a later claim.
Grant/claim arms, matching-cell support, ATT weights, subsequent choices,
intervals, reach and censor events are rebuilt. The original 13 exposure
variables, their transformed terms, fixed effects, timing, and covariance
rules are preserved. Complete follow-up uses the maximum observed last-move
timestamp in the source panel, as in the original receipt core.

Only factual first-meeting dates are reused from the authenticated original
recipient file. No old exposure eligibility, matching weights, grant outcomes
or behavioral-history estimates are reused. Pair dates are keyed by the
unordered numeric account pair, not by the old cohort row ID. Missing pairs
are reconstructed from the existing 852-file chronology, reading only utc_ms,
white_id and black_id. The original positive-timestamp rule is preserved;
timestamps are not rewritten. The 7.76-billion-record rating replay is not
rerun. There are no API requests, profile queries or engine evaluations.

INPUTS
The reviewed ready manifest is selected automatically:
  derived/replication/mating_material_first_run_v100_PRIVATE/
  aa7e95f275c18f43/MATERIAL_RESTRICTED_INPUTS_READY_PRIVATE.json
It binds the new full-width material-restricted panels. The earlier missing
AUTHOR_EXCLUDED_MAIN_READY_PRIVATE.json is not required.

The certified factual-history file is found at either existing location:
  derived/replication/pool_main_reanalysis_v100_PRIVATE/wave2b1/project_view/
  derived/replication/dynamic_prosociality_core_v102_PRIVATE/
  recipient_with_chronology_private.parquet
or:
  derived/replication/dynamic_prosociality_core_v102_PRIVATE/
  recipient_with_chronology_private.parquet
Its complete SHA256 is checked against the original authority. The packaged
chronology manifest maps the existing rating_events_replay_sorted_v2_time
files. Historical chronology validation uses the original manifest's file
sizes and footer counts, plus current raw-footer SHA and stat checks bound to
each new checkpoint; it does not claim full-file SHA authentication of all
150.7 GB of chronology. Every new output checkpoint is SHA256-verified.

OPTIMIZATION AND RESTARTS
Unused A3/encouragement branches are pruned from the original SQL; the retained
columns are tested against the complete original query. First exposures and
later outcomes are each materialized once. Existing factual pair dates avoid
most pair lookups; projected scans use vectorized filtering and per-file
checkpoints. Numerical crossproducts use bounded batches, and hour fixed
effects use the existing exact Schur-complement projection. Models run
sequentially to avoid multiplying memory. Each file and model has a sealed
checkpoint; repeat the same command after interruption. A completed run
verifies its outputs without repeating the regressions. Corrupted outputs
stop the run instead of being accepted as complete.

OUTPUTS
Private caches:
  __PRIVATE_VALUE_1__/derived/replication/
  mating_material_receipt_v100_PRIVATE/<run-ID>/
Return these three files from ~/Desktop/Lichess_Desktop:
  MATERIAL_RECEIPT_<run-ID>_RECEIPT_READY.zip
  MATERIAL_RECEIPT_<run-ID>_RECEIPT_READY.zip.sha256
  MATERIAL_RECEIPT_LATEST_PRIVATE.json
If the run stops, return its *_FAILED.zip and terminal error.

The return ZIP includes tab_dynamics.csv/.tex, tab_app_intervals.csv,
tab_app_receipt_hours.csv, tab_app_receipt_sensitivities.csv, one CSV per fit,
complete coefficient/covariance JSONs, fresh support and sample-flow counts,
history scan counts, before/after comparisons, source code, tests and run.log.
No account-level or game-level data are included in the return ZIP.

For hour models, both chooser-clustered and chooser-or-hour CR0 inference are
reported explicitly. The zero-coded hour tests use CR0 as paper_se, following
the Uniform90 matched producer; conditional/reach hour tests use the original
companion's chooser-clustered correction. Do not substitute one SE column for
another. The main table always uses the original chooser-clustered correction.

TESTS AND PROVENANCE
The unmodified original receipt, censoring, absorption and numerical sources
are in vendor/ with source hashes. Tests cover exposure reselection, original
SQL equivalence, first-pair lookup and reversed pairs, censor boundaries,
original and independent dense-fit covariance agreement, input contracts,
all 18 models end to end, completion/resume, corruption and return privacy.
The test fixtures are synthetic; the full-data results require the Mac run.
The reviewed Patron results and remaining-family ledger are included as
evidence. No manuscript numbers are automatically replaced.

Optional commands:
  RUN_RECEIPT.command --estimate-only
  RUN_RECEIPT.command --preflight-only
  RUN_RECEIPT.command --workers 6 --memory-gb 8
  RUN_RECEIPT.command --project-root /different/path/lichess_kindness
Use bash with the full launcher path as shown above. Python 3.11–3.13 is
required. The environment defaults to MatingMaterial_Models_Env_v100 in the
Desktop folder; MMRECEIPT_ENV can point to another isolated environment.
