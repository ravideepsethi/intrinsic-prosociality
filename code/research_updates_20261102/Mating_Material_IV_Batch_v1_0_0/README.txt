MATING MATERIAL IV BATCH 1.0.0
Prepared 30 October 2026

Save and extract this folder in ~/Desktop/Lichess_Desktop, then run:

  bash "$HOME/Desktop/Lichess_Desktop/Mating_Material_IV_Batch_v1_0_0/RUN_IV_BATCH.command"

EXPECTED RUNTIME

Allow 6–12 hours provisionally on the MacBook Pro, with XT_Pro mounted and
other large research jobs stopped. Allow overnight if new factual chronology
scans are needed. This new combined batch has not been timed on the production
data. The completed original Uniform90 analysis took approximately 3.1 hours
excluding metadata acquisition; this batch rebuilds changed inputs and adds
many specifications and companion analyses. Environment installation normally
takes a few minutes. Synthetic validation normally takes about a minute.

Defaults: at most 10 workers, 11 GiB compute budget, one BLAS thread, at most
two heavy data tasks, sequential model fits, and bounded covariance spills.
The first launch requires at least 160 GiB free on the project drive. That is
a conservative reservation, not a measured disk-use forecast. Run plugged in;
the launcher uses caffeinate on macOS to prevent idle sleep.

WHAT THIS RUNS

1. Authenticate the completed material-input contract and original Uniform90
   producer lineage. Both author accounts are excluded in both roles.
2. Rebuild broad donor decisions and the held-out-fold state reference, with
   corrected grants and eligible arms. Rebuild every recipient history and
   the first later qualifying choice from the corrected inputs.
3. Rebuild exposure membership before support and spacing. Recompute all-time,
   before-exposure, after-exposure, competitive-only and noncompetitive-only
   scores, including each instrument's own history controls.
4. Fit the primary unspaced IV, the spaced/first/repeated-recipient variants,
   recipient fixed effects, calendar/history contrasts, minimum-history and
   score sensitivities, prior-choice splits, same-UTC-hour sensitivities,
   and first-stage subgroups. The no-environment spaced sensitivity is included.
5. Fit recipient-weighted IV, same-row OLS, and transformed-outcome complier
   means. Export paired differences under the joint covariance, exposure
   concentration and overlapping-window/shared-choice counts.
6. Produce the 20-bin first-stage figure and data. Refit later competitive and
   clearly-worse granting on the primary competitive-receipt frame, with joint
   proportional contrasts, reach/first-choice diagnostics and matched results.
7. Refit receipt and the August Patron snapshot, preserving the original
   acquisition probabilities. No new profiles are queried.
8. Rebuild support and entry labels in the original full hash-sampled
   all-ending frame. Refit entry, ordinary-ending placebo, balance, and the
   receipt-minus-placebo difference with shared covariance.

The return report's COVERAGE.json distinguishes these analyses from the
remaining paper work. BATCH_COMPLETE means this batch finished; it does not
mean every paper appendix or manuscript update is finished. The lost-position
receipt frame, two-instrument overidentification/characteristic diagnostics,
act-versus-result mechanism models, some older auxiliary receipt checks,
adjacent-payoff check, and manuscript reconciliation remain outside this build.
Previously completed non-IV material reruns are not rerun here.

SCIENTIFIC AND EXECUTION RULES

Only the mating-material correction changes the decision universe and labels.
Original rating prices, engine evaluations, factual game chronology and
metadata are reused. Removed decisions remain in factual chronology. A newly
eligible grant can change support; a removed opportunity can change the first
later choice. Old exposure IDs, donor scores, histories and outcome endpoints
are therefore not used as the new statistical sample.

Unchanged real-world facts are reused only after checking their producer
lineage and joining by identity. Primary row IDs can change: factual volume
reuse joins on game ID, recipient ID and game start. New first-pair queries and
missing factual volume use local chronology. Original first-pair answers are
reused only for arms covered by the original complete pre-support stream.

The shared-account-in-either-role OR date covariance is retained, including
unordered-pair and account-date inclusion–exclusion. No PSD clipping is used.
Generated scores are treated as fixed. The common instrument unit remains
0.04979005187533171, not each new frame's residual standard deviation.

The spaced cohort is selected before administrative history/follow-up cuts.
The first-exposure flag is formed before arm/support cuts. Primary histories
use [start-90 days, start); legacy histories use [start-97 days, start-7 days).
The future-choice window is anchored at the recorded last move, requires a
later game start, and excludes the exposure opponent. Complete windows with
no qualifying later choice are zero coded.

The environment correction keeps factual all-game denominators. It subtracts
removed decision events from the two decision numerators only within the
original supported windows and with the original pair exclusion. Incomplete
windows do not acquire negative counts from subtraction.

PRODUCTION INPUTS

Project:
  /Volumes/XT_Pro/lichess_kindness

Material-ready manifest:
  derived/replication/mating_material_first_run_v100_PRIVATE/
  aa7e95f275c18f43/MATERIAL_RESTRICTED_INPUTS_READY_PRIVATE.json

Completed Uniform90 parent:
  derived/replication/receipt_iv_uniform90_v100_PRIVATE/af114813b1ad

The runner reads the original R12/R9/cache locations from that parent's
config.json and authenticates their original completion receipts. It does not
search for a different sample when a dependency is missing. The material
contract is the reviewed build with 41,513,719 main decisions, 570,422 grants,
and 47,561,517 broad donor-source decisions. These are input checks, not
constraints on the new IV sample size or estimates.

Python 3.11–3.13 is required. The launcher creates its isolated environment at:
  ~/Desktop/Lichess_Desktop/MatingMaterial_IV_Env_v100

Package installation may use the network once. Production data work blocks
network connections: no API fetch, engine search, rating replay or profile
pull is allowed. If an expanded comparison contains a genuinely uncached
metadata record, that branch reports OFFLINE_HOLD and keeps completed receipt
outputs. The private missing-record list stays on XT_Pro; return the report.

OUTPUTS AND RESUME

New private work is isolated under:
  /Volumes/XT_Pro/lichess_kindness/derived/replication/
  mating_material_iv_batch_v100_PRIVATE/<configuration prefix>

The desktop folder receives:
  MATERIAL_IV_BATCH_<configuration prefix>_RETURN.zip
  MATERIAL_IV_BATCH_<configuration prefix>_RETURN.zip.sha256
  MATERIAL_IV_BATCH_LATEST_PRIVATE.json

Upload the RETURN.zip after the run. It contains estimates, diagnostics,
coverage, status, stage timings, logs and checksums. The private row-level
Parquet files remain on XT_Pro. The report is refreshed after every stage;
independent analyses continue after a non-core failure.

To resume, run exactly the same command. Completed stage products are checked
and reused. Interrupted products are recomputed only where their completion
receipt is absent. A changed input or corrupt completed output stops the
affected branch rather than being silently accepted. Do not edit this package
or rename its input files midway through a run.

Optional read-only preflight (authentication can take several minutes):
  bash "$HOME/Desktop/Lichess_Desktop/Mating_Material_IV_Batch_v1_0_0/RUN_IV_BATCH.command" --preflight-only

Other supported overrides: --project PATH, --material-manifest PATH,
--legacy-root PATH, --workers N, --memory-gb N, --result-dir PATH.
Overrides do not relax the reviewed scientific or provenance checks.

VALIDATION

See VALIDATION.json for the executed tests and limits. Tests cover numerical
agreement with independent fixed-effect and covariance calculations, donor
support changes, history/outcome boundaries, first-pair reconstruction,
spacing, factual-cache identity, corrected environment counts, companion
estimators, restart reuse and corruption rejection. Tests use synthetic data;
the 41.5-million-decision production run must execute on the Mac.

VENDORED_SOURCES.json records the reused original producers and narrow input
adaptations. Their scientific estimators are reused instead of replaced with
an approximate regression library.
