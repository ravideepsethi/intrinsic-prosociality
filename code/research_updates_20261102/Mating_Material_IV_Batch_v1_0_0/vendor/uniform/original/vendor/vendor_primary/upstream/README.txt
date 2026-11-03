R12 / R13 LOCAL RUNNER v1.0.3

This is executable estimation code, not another partial-results report.
The authoring environment did not have /Volumes/XT_Pro. Numerical tests use
synthetic fixtures and direct reference calculations. No new empirical result
is claimed until this runs on the local certified data. Vendor code and evidence
from R9b, R11, KAC companion analyses and Test G are included unchanged.

RECOVERY v1.0.3 (2026-10-14)
The supplied v1.0.2 terminal log completed matched and IV. The cutoff stage
finished its 16 history shards and merged their results, then failed before
the 30-day chronology scan with KeyError: 'bytes'. The upstream authenticated
chronology binding stores signature=[file size, modification time in ns], not
a top-level bytes field. The volume reader now checks that signature using
the same io.sig function as the upstream environment scan, checks Parquet
rows/schema, and rejects a file changed during the scan. The canonical
manifest authentication in bind() is retained unchanged.

A verified clean_features.parquet is now reused before preparing history
queries. This avoids rewriting inputs whose timestamps are bound to the
completed history shards. Donor scores, selection, histories, successful
matched/IV fits, and opportunity results keep the same input-key/SHA256 gates
and run identity 4df83f1178f3. The underlying samples, definitions, estimators,
and report schemas are unchanged. No chronology count from the failed reader
was committed. The remaining scan prints file completion counts and elapsed
time; file sizes and time-window pruning vary, so these are not a whole-run ETA.

Use --stages cutoffs for this retry. It resumes the cutoff work, then attaches
opponent-environment controls and fits the four rebuilt cutoff specifications.
Successful matched and IV stages need no retry. The report retains their
existing aggregate tables. Archive work and R13(b) remain separately pending;
this repair makes no archive downloads or engine evaluations.

Validation exercises the actual volume worker and a two-worker spawned scan
against direct counts, including both player roles, repeated queries, inclusive
30-day lower and exclusive upper bounds, missing Parquet statistics, invalid
games, input-change rejection, and checkpoint reuse. The external data drive
is unavailable here, so this is a tested code repair, not a new empirical run.

The earlier recovery notes below describe the previous checkpoint states.

RECOVERY v1.0.2 (2026-10-14)
The supplied 4df83f1178f3 checkpoint completes opportunities/R13(a)/clocks.
Its matched baseline and start-hour rows are accepted cached results; last-move
hour reached 2,000 alternating-projection iterations without convergence.
The three-FE matched models now use a direct weighted Schur-complement
projection: hour dummies are eliminated and the cell/month system is solved.
The same rows, weights, controls and covariance calculation are preserved.
Every projected column must have all FE weighted means <=1e-10. No tolerance
loosening, row removal, or FE removal is used. Existing successful rows reuse
their certified JSON receipts. Censored-window estimation runs after the
last-move model. Numerical fixtures compare the projection to full dummy OLS,
including near-nested month/hour effects and redundant dummy directions.

All 15 ancestral PACKAGE_MANIFEST.sha256 files are included unchanged and are
now covered by the root manifest too. They were absent from the v1.0.0 ZIP;
v1.0.1 already included them. The supplied IV failures are from v1.0.0 and
have not yet been retried under the corrected archive.

The supplied archive census accepted only 2023-11. Twenty-two files failed
ratedness checks; 2025-06 was not found. archive-probe reads at most 64 games
per file and exports fixed header categories/presence counts and source sizes.
It does not infer ratedness from a filename, skip unknown records, alter any
archive, make API requests, or run an engine. The archive parser is unchanged:
its exact failure cause needs the local probe before another repair.

R13(b) now refuses anything short of COMPLETE_24_MONTHS with all 24 requested
months. A partial R12 quantile table is still allowed, as requested for R12;
it is not a valid substitute population for R13(b). Completed R13(a), clocks,
matched rows and the November census keep their old checksummed caches.
The completed-game cache branch now also includes the covered months and
archive hashes, so an earlier partial-month draw cannot be reused as the
requested 24-month comparison. Earlier files are preserved.

Recovery command stages: --stages archive-probe matched iv cutoffs
Stop any old R13(b) process and any previously queued old launcher before
starting this recovery. The single-writer lock still prevents overlap.
The probe report is packaged before the matched/IV work begins, so its
checkpoint ZIP can be returned while the longer stages continue.

REPAIR v1.0.1 (2026-10-14)
DuckDB rejected the bare year alias in the other-year chooser grouping.
The identifier is now explicitly quoted throughout those SQL statements.
The full updated package still authenticates every listed source file.
Existing v1.0.0 caches use the same namespace and input/checksum gates:
projection, matched, IV, cutoff and monthly census results are reused.
Actual execution-package SHA256 and cache-lineage SHA256 are both reported
in execution_package.json. No old package file or data source is edited.
Wait for any active v1.0.0 run to finish before launching this version; the
existing single-writer lock remains enforced.

R13(b) depends on the opportunities and ply stages, not matched/IV/cutoffs.
It uses POOLED.json for its final comparison, the competitive-ply histogram
for the draw, and the all-game census to bind archives and sample sizes.
After the current run finishes, this order prioritizes R13(b):
  --stages opportunities ply part-b matched iv cutoffs --fetch-metadata
The default stage order is unchanged and does not start R13(b).

QUICK START (macOS, Python 3.11 or newer)

After extracting the ZIP, open Terminal in R12_R13_Local_Runner_v1_0_3:

  chmod +x RUN_LOCAL.command
  ./RUN_LOCAL.command --self-test
  ./RUN_LOCAL.command --project /Volumes/XT_Pro/lichess_kindness --workers 10 --memory-gb 11

The default run performs R12's six outstanding items and R13(a). It carries
forward the accepted position-contrast CSV and omits the dropped ultrabullet
pipeline audit. It authenticates inputs, recreates the missing fits, and writes
aggregate ZIPs, SHA256 sidecars and a log to:

  /Volumes/XT_Pro/lichess_kindness/reports/R12_R13/

Private checkpoints live under derived/replication/r12_r13_followups_v100_PRIVATE.
Rerun the same command to resume. Completed stages/checkpoints are verified
before reuse. Concurrent writers to the same run are locked out. All original
data and earlier report folders are read-only. The Mac is kept awake while
the command is running. Check available disk space: the code requires at least
20 GiB free initially; rebuilding new cutoff histories and sampling completed
games can require more. Ten is a worker cap; stages reduce concurrency to fit
the 11-GiB working-memory budget. This is a planning bound, not an OS memory cap.

If archives are stored elsewhere, repeat --archive-root as necessary:

  ./RUN_LOCAL.command --archive-root /Volumes/XT_Pro/lichess_archives

Use the SAME --archive-root and other source options in later commands; they
form part of the run identity. Missing monthly archives are listed and the
quantiles use the successfully scanned months. No PGN archive is downloaded.

RUN INDIVIDUAL STAGES

  ./RUN_LOCAL.command --stages opportunities
  ./RUN_LOCAL.command --stages matched iv cutoffs
  ./RUN_LOCAL.command --stages ply
  ./RUN_LOCAL.command --preflight-only

opportunities produces R12 clocks, R13(a), bin counts and the exact empirical
competitive-ply histogram. The default runs can be lengthy: new cutoff rows
may require a local chronology scan for 30-day playing volume. Existing certified
values are reused where the original frame covers a row.

R13(b): SEPARATE EXPENSIVE STAGE

Run the default stages first. The exact original Stockfish executable is found
by SHA256, or can be passed via --engine /absolute/path/to/original/stockfish.
No engine is downloaded or replaced. Run the full draw:

  ./RUN_LOCAL.command --stages part-b --games 2000000 --fetch-metadata

Part b requires all 24 authenticated months. The default implements the request's no-timeout API-status screen: outoftime
is an eligible flag, timeout is not. The README states that API status does
not independently reconstruct both players' historical socket presence.
Local metadata are reused first; --fetch-metadata permits public game exports
for unresolved candidates. To remain offline, omit that flag. To add a local
metadata source, use --metadata-source /path/to/metadata.parquet (repeatable;
NDJSON and SQLite are also supported). Optional --flag-policy strict-connected
requires explicit historical both-connected evidence for every flagged game.

The authorized smaller alternative:

  ./RUN_LOCAL.command --stages part-b --games 500000 --speeds blitz rapid \
    --fetch-metadata --flag-policy api-status-proxy

Here the no-timeout status convention is explicit. To use 2 million games,
replace --games 500000 with --games 2000000 and omit --speeds blitz rapid.
Both games and positions are sampled independently of
outcomes, and every candidate through the selected priority cutoff must have
resolved source/status. No selection on whether metadata happened to be cached.

The candidate multiplier defaults to 8. If too few eligible games lie within
that hash threshold, increase --candidate-multiplier (e.g. 16). A different
completed-game option set gets a separate private checkpoint branch. The
default metadata budget is 10 million game records; --max-metadata-games changes
this bound without invalidating cached responses. No token is needed or printed.
Stop/restart is safe at completed batches/chunks. The engine stage can take
many hours or days; its duration depends on the exact original engine settings
and hardware. No runtime estimate is promised before observing throughput.

TWO IMPORTANT DESIGN DETAILS

1. Minimum decisions: certified R9 applied a lag-seven support restriction
before spacing exposures. A genuine all-time Score A cutoff run from the
pre-five universe can change the cutoff-five cohort too. cutoff_robustness.csv
therefore contains the four consistently rebuilt cohorts AND a separately
labelled certified R9 cutoff-five reference. Exact overlap is reported. Do not
replace the rebuilt cutoff-five row with the historical primary estimate.

2. Completed-game plies: some games end before an independently drawn target
ply. The runner reports those draws as unavailable; it never silently caps or
redraws them. The evaluated-position count can be smaller than the game draw.
The report describes the corresponding available-position population.

OUTPUTS

R12: position_contrasts_alt.csv (accepted), all_games_ply_quantiles.csv,
matched_zero_coded_sensitivity.csv, balance_contrast.csv,
first_stage_ladder.csv, cutoff_robustness.csv, clocks_by_region.csv.
R13: exchange_rate_part_a.csv (estimates and equality tests),
exchange_rate_part_b.csv, exchange_rate_comparison.csv,
completed_game_sample.csv and completed_game_drawn_plies.csv.
Additional aggregate files include opportunity/evaluation-bin counts, source
hashes, monthly coverage, cutoff cohort overlap, numerical gates and runtime.
REPORT_METHODS.txt contains the complete sample and model conventions and is
included in the generated report README.

The first-stage and matched baseline checks fail loudly if certified values
do not reproduce. No p-value or SE is fabricated for an indefinite covariance
or unidentified ratio. A weak denominator is explicitly marked. CSVs can have
both estimate and test rows, identified by row_type. E and R use percentage
points; ratio SEs use the joint covariance. Equality tests retain cross-group
chooser dependence. The score SD is fixed at 0.04979005187533171.

API REFERENCES (consulted 2026-10-14)

https://lichess.org/api
https://github.com/lichess-org/api/blob/master/doc/specs/lichess-api.yaml
https://lichess.org/page/api-tips

No API request, Stockfish run, or private-data estimation was performed when
this package was authored. See VALIDATION.json and validation.log for the
checks that were actually run.
