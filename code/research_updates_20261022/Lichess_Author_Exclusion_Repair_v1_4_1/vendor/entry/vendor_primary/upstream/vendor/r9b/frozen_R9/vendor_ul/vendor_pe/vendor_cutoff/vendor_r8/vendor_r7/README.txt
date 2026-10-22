R7 Analysis v1.0.3 — 9 October 2026

v1.0.3 fixes the F50 A4 KeyError: 'y'. The frozen Phase-050 entry
projection deliberately removes later-choice outcomes. The assembled feature
cache retains them, including nulls for incomplete follow-up. The new attachment
uses that authenticated cache and verifies unique row IDs, game/player/time
identities, complete-window rules, cohort/author flags, and exact agreement with
the existing O50 later outcomes. All F50 rows and existing columns are preserved.
No outcome is recomputed or filled. All 32 A/B input schemas and the Part C
endpoint schemas are checked before expensive fitting begins.

The tests previously used a synthetic entry table that already contained Y and
therefore missed this production schema difference. New regression tests use the
actual upstream entry projection with all six later-outcome columns removed.

Resume both completed stages:
  bash RUN_R7_ANALYSES.command --workers 10 --memory-gb 11 \
    --reuse-r7-root /Volumes/XT_Pro/lichess_kindness/derived/replication/r7_analysis_v100_PRIVATE/dae86f8a1785 \
    --reuse-reproduction-root /Volumes/XT_Pro/lichess_kindness/derived/replication/r7_analysis_v101_PRIVATE/30547781f2c4

The first option preserves all 120 completed ENV chronology tasks. The second
verifies the exact reviewed v1.0.2 configuration, source binding, dependency
signatures and all nine passed reproduction checks, then copies their aggregate
results into the new run. The three result hashes are pinned to the verified
Mac report. Old run directories remain unchanged. The numerical estimators are
unchanged; only input preparation, validation and missing-outcome reporting change.
Omit the second option to recompute the full numerical gate. A fresh run may
omit both reuse options. Rerun the same command after an interruption.

F50 entry eligibility uses the game start for calendar support; later-choice
completeness uses the final anchor. These are not identical boundary conditions.
If any selected F50 row lacks complete follow-up, its requested full-row A1/A3 Y
column is explicitly reported unsupported, with counts and a visible report
status. Entry, disconnection and score columns still use all frozen rows. No
complete-case subset or incomplete-window zero is silently substituted. This
preserves the handoff's no-new-exclusions and missing-value rules.

Defaults:
  project: /Volumes/XT_Pro/lichess_kindness
  Python:  /Volumes/XT_Pro/lichess_kindness/venv/bin/python
  reports: ~/Desktop/Lichess_Desktop
  private work: derived/replication/r7_analysis_v103_PRIVATE/<configuration hash>

Required completed runs, authenticated against the included full-precision archives:
  Environment v1.0.2: cea0b052e5f2
  Phase-050 v1.0.1:   550c6ca9fab6
These are the existing private run directories, not just downloaded report ZIPs.
The program does not recreate missing completed runs or change any upstream cache.

Requires existing Python >=3.10, NumPy, PyArrow, DuckDB, python-chess.
Optional zstandard module or zstd executable for compressed local move caches.
No automatic installation, API call, download, new score construction, rating
replay, or Stockfish search occurs. Vendored sources are unchanged.

CONTENTS AND DESIGN

A1: D, Y and the score on all 15 standardized recipient traits with joint tests.
F50 replaces D with entry and adds recipient disconnection, retaining Y.
A2: score on T30 under the full model, beside the stacked trait-on-score test.
A3: in-sample and four-fold observed-history calibrations, separately under
NH and full-model outer controls. The handoff calls NH the Panel A controls in
one sentence; this bundle labels both specifications explicitly. Standard errors
include estimation of the prediction coefficients using a first-order sandwich.
Training folds exclude both roles of all accounts hashed to the held-out
recipient fold. This is an out-of-fold recipient index, not a claim that shared
opponent/date dependence vanishes. That dependence enters CR0 inference.
A4/A5: requested sample/control repeats and competitive-score diagnostics.

B1: full ENV-supported S0 with X0 and X0+ENV, plus volume/rate ladder. XC is not
available on every ENV-supported row. An explicit common-row S0_CSE bridge fits
X0, X0+ENV, XC and XC+ENV on precisely the same rows. This avoids silently dropping
rows from only the XC column.
B2: all author-clean S0 rows, zero-valued unsupported ENV plus an unscaled support
indicator. This convention is confined to the expressly labeled indicator
models, including their F50/O50 analogues. Original missing values stay missing.
B3/B4: matched-control entry/ordinary models; paired receipt-minus-ordinary RF
contrasts use a joint account/date covariance, not independent standard errors.
B5: recipient-repeat membership fixed on full S0 before ENV restriction, pooled
and recipient FE. Author-clean repeat row counts are reported, not forced to the
original manuscript count.

C1/C2: certified final ply/merit/clock and legal recorded-move replay; net material
balance change over the last four plies (all available plies if fewer than four).
Local move sources: known API/export/enrichment cache roots and
derived/replication/pgn_timeforfeit_candidates. --move-root adds an existing local
folder. Recognized Parquets have game_id/id and moves/pgn_moves/movetext/pgn or
metadata_json/raw_json/response_json/api_json. JSON/NDJSON, gzip, bzip2 and zstd
API exports are read locally. Complete legal replays must match certified final
ply. Conflicting complete replays are unavailable, never selected by file order.
Clock share uses the certified last observed recipient clock in seconds divided
by initial time in seconds. It is not the clock at physical disconnection.
C3: marginal classes, full observed cross-classes, swing/quiet/unknown, and
competitive entry by ply; every entry regression uses the entire F50 denominator.
C4: influence checks on post-assignment restrictions. Below 1% observed swings,
C4(a) is reported not estimable. Unknown histories are disclosed. When C4(a) is
run, it reports both exclusion of observed swings with unknowns retained and
the corresponding matched known-move comparison. Missing histories are never
declared quiet or proven nonswing.
C5 remains deferred. Opening ECO tags, where recorded, are carried privately;
no opening-propensity model is selected or estimated in this run.

COHORT DISCREPANCY RESOLVED

The handoff's S0 row count and its receipt_original_author_clean instruction
refer to two distinct objects. The original 2,682,330 rows are kept for an
independent reproduction gate. All new R7 diagnostics use the authenticated
2,682,329-row author-clean object, with its already cleaned fixed scores and
outcomes. No replacement, re-spacing, fresh author exclusion or score rebuild.
The original headline stays the headline; this code does not promote a model.

REPRODUCTION AND NUMERICAL CHECKS

Before new fits: reproduce (or verify the pinned completed v1.0.2 gate for) original Panel A coefficients, SEs and AR intervals
against full-precision archived objects; recompute original T30 balance with the
frozen producer and compare the R7 adapter at full precision; reproduce the
1,860,351-row ENV ladder and Phase-050 entry/placebo estimates and balance.
Original balance has no separate full-precision member in the supplied archive;
the independent frozen-producer recomputation is retained in the private gate.
The manuscript's rounded 11.746 is not used as a numeric gate target.

Every fit uses shared-account-in-either-role OR exposure-date CR0. Generated
scores are fixed, intervals nominal. No covariance eigenvalue clipping or ridge.
Rank-deficient joint trait designs fail explicitly; sparse outcomes and
nonpositive covariance are marked unsupported without invented intervals.
Exact reference SDs: pooled 0.059411690344000595; competitive 0.09545502195393069.
Balance uses trait SD/native residual score SD. Raw coefficients are retained.

OUTPUTS

READ_RESULTS.txt, summary.json, REPORT_MANIFEST.json, support, reproduction,
reproduction-reuse provenance, outcome-attachment, input-preflight and move-coverage files; A/B/C tables as CSV/JSON/Parquet. JSON preserves nested fields;
CSV/Parquet encode those cells as JSON strings. Private account IDs, moves,
row-level features and influence functions stay outside the portable report.
The report ZIP and its SHA256 sidecar are refreshed after completed model stages.
A partial or missing-move report is visibly labeled; no identification certificate.
An aggregate report is written on failure whenever the run root exists.

RESUME / RESOURCE OPTIONS

Rerun the same command to reuse authenticated checkpoints. Each new R7 stage
stores dependency SHA256s and file signatures. Changed dependency signatures,
changed output hashes, mismatched run authority or changed move snapshots stop.
No upstream receipt is overwritten. Failed .partial_* directories are retained.
One configuration lock prevents concurrent writers.

  --reproduce-only       Stop after the numerical gate.
  --parts AB             Finish A/B and paired contrasts; C remains pending.
  --memory-gb 11         Budget used by the reviewed Mac run; no increase needed.
  --reuse-r7-root P      Reuse reviewed v1.0.0 prepared ENV tables, read-only.
  --reuse-reproduction-root P  Reuse the passed v1.0.2 production gate, read-only.
  --move-root PATH       Add an existing local recorded-move cache folder.
  --environment-root P   Exact completed ENV directory if relocated.
  --phase50-root P       Exact completed Phase-050 directory if relocated.

IV_PROJECT_ROOT, IV_DESKTOP and IV_PYTHON override launcher defaults.
Up to ten workers, one BLAS/Arrow thread per worker; memory-weighted scheduling.
The largest A4 model reserves about 9.24 GiB plus 1.5 GiB headroom, fitting the
reviewed 11 GiB budget. Large models run alone; smaller fits can run together.
Fresh model workers release allocator high-water marks after each job (Python
3.11+). A/B inputs omit strings and unrelated columns. Completed B matrices are
released before A1/A3, FE absorption owns one matrix instead of copying it, and
CR0 group sums use bounded column blocks. A3 training projections are shared
across outcomes and outer specifications, preserving separate coefficient and
delta-method calculations. C class masks are made in batches rather than held
for every possible class. Move replay target copies also use memory scheduling.
Whole-run Mac duration has not been benchmarked. Full-size synthetic Linux
memory measurements are included in VALIDATION.json; they are not a Mac ETA.
Many cached replays or slower external disks may increase duration. Progress messages
are emitted every 30–45 seconds; measured current-stage ETAs appear when possible.

The complete synthetic 7,371,688-row F50 X0+ENV+availability fit, including
all 12 A3 calibrations, completed at 6.68 GiB peak RSS on Linux. Both account
roles used unique IDs to stress the largest possible covariance group arrays.
The A-model reservation is deliberately higher (9.24 GiB for this row count).
A separate full-row C probe reached 7.55 GiB while classifying all rows and
fitting the first eight of 387 class outcomes. It did not time the remaining
C batches; each uses the same allocation shape and releases its arrays before
the next batch. C reserves 8.90 GiB at this row count, plus 1.5 GiB headroom.

Validation here uses synthetic data and the authenticated code/result archives.
The private multi-million-row source data were not available in the build
environment. The production reproduction gate passed on the Mac in v1.0.2. Its verified
results may be reused by the command above; the new full analysis has not yet
been run on the private data. See VALIDATION.json for the shipped checks.

Tests only:
  bash RUN_TESTS.command

All results remain diagnostics specified after the reviewed Run 2 evidence.
Observed-history calibration is not identified bias; class comparisons do not
observe marginal entrants; balanced measured traits do not certify exclusion.
