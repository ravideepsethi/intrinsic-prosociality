# Arena replication, version 1.0.2

This version restores the certified rule that missing disconnected clocks are
retained. My v1.0.1 monthly check incorrectly rejected them. The preceding UTC
repair remains in place and has been confirmed on the production machine.
See `REPAIR_NOTE.md`. This starts a separate v1.0.2 run and preserves previous
run directories. Per-month diagnostics name every failed validation condition.

This package prepares the first arena replication wave against the existing
24-month SF18/100,000-node panel on XT_Pro. It estimates the arena-versus-pool
suppression comparison, arena structural relationships, and persistence. It also
counts the available support for later receipt/IV, episode, and Patron analyses.
It does not yet reproduce every analysis in the paper.

The package has been tested with synthetic data and authenticated upstream
source/report bundles. The production data were not accessible during package
development. No new arena effect estimate is supplied or implied by this ZIP.

## Known sample support

The completed source and observed-adjacency audit covers November 2023 through
October 2025. These are active timeout opportunities, not all tournament games.

| Sample | Opportunities | Kind draws | Competitive opportunities | Competitive kind draws |
|---|---:|---:|---:|---:|
| Original panel, all sources | 47,587,020 | 669,503 | 17,328,130 | 487,170 |
| Arena before adjacency screen | 1,905,304 | 20,884 | 735,845 | 13,186 |
| Arena with main-sample screen | 1,892,835 | Computed by run | Computed by run | Computed by run |
| Pool with main-sample screen | 41,534,331 | 570,091 | 15,207,423 | 419,463 |

The arena restriction is exactly `source='arena'` and
`previous_classification_status='not_mutually_adjacent_observed'`. It retains
99.35% of arena opportunities. This uses the same backward observed-adjacency
classification as the pool main sample. It does not certify literal immediate
end-to-start rematches. Competitive means the disconnected player's engine
evaluation is at least -100 centipawns.

The underlying certified opportunity rule retains disconnected clocks of at
least five seconds **or missing clocks**. Recorded clocks below five seconds
remain invalid. Missing clocks stay in the full arena and all-source panels;
the explicit complete-case restrictions of the new adjusted models apply
separately and are reported in `descriptive/covariate_coverage`.

The source count supports a substantial first replication wave. Power for each
design still depends on grants, repeat users, overlap, and eligible transitions;
the total row count alone does not establish power for every paper analysis.

## Run on the Mac

1. Download `Arena_Replication_v1_0_2.zip` and its `.sha256` file to Downloads.
2. Mount XT_Pro and use the complete command in `TERMINAL_COMMAND.txt`.
3. Upload the new `ARENA_REPLICATION_RESULTS_v102_*.zip`, its checksum, and the
   terminal log from `~/Desktop/Lichess_Desktop` when the run finishes.

The runner uses `/Volumes/XT_Pro/lichess_kindness` by default. New private data,
caches, and checkpoints go under its `output/arena_replication_v102/` directory.
The original panels and source/join files are read only. The shareable report
contains aggregate outputs; private game/user rows stay on XT_Pro.

Python 3.10 or newer is required. The launcher checks Python and dependencies,
and creates a dedicated Desktop virtual environment if dependencies are missing
or incompatible. Internet access is used only by pip if installation is needed.
The analysis makes no Lichess requests and does not rerun Stockfish.

Planning estimate: roughly 1–4 hours on the 18 GB Mac/XT_Pro setup. This is an
unbenchmarked estimate; full input hashing and disk speed can make it longer.
The run logs elapsed time and sends model-stage heartbeats every 30 seconds.
Ten workers/threads is a ceiling. Monthly builds and parallel gap regressions
use fewer workers according to detected RAM; the large stages run sequentially.
DuckDB buffers default to 6 GB. This is not a whole-process RAM cap: the new
fixed-effect regressions also hold selected numerical arrays in Python memory.

The runner computes a conservative free-disk planning allowance from the input
sizes before building outputs. If available space is smaller, it stops before
the expensive build. The allowance is a planning check, not a measured peak.

## What runs

| Stage | Results |
|---|---|
| Input authentication/build | Original source certificates, hashes, schema and identity checks; all-source narrow panel and full-width arena subset; screened grant counts |
| Suppression | Arena versus pool within chooser; calendar/time-control, board/stage and full control ladders; competitive, all-state and clearly-worse contrasts; long-game and within-chooser/time-control/month checks |
| Arena structure | Five board states; competitive versus clearly worse; game-stage profile; roughly-equal versus better with exact-ply robustness |
| Persistence | Fixed first/second 12-month rates, several minimum opportunity thresholds, ordinary and reliability-weighted correlations, prior-granter follow-up rates |
| K/RD | Recovered rating-gap decomposition, rating-payoff identity, fixed-effect band comparisons and figures, re-estimated on arena |
| Nonparametric gap | Recovered gap-bin, K, stable-account, year and common-support families, re-estimated on arena |
| Controlled payoff | Recovered v1.1.0 model and corrected v1.1.1 figure, re-estimated on arena |
| Support | Repeat granters, next fair opportunity following arena exposure, and coverage in the fixed August Patron snapshot |

The primary suppression result is `suppression/competitive_full.json`. Its
linear probability model absorbs chooser, exact time-control × calendar month,
board-state × game-stage, 100-Elo own-rating bins, and 50-Elo rating-gap bins.
Continuous controls are log(1 + own clock), log(1 + opponent clock), log own RD,
log opponent RD, and log win premium. An additive model is reported in
percentage points, with chooser-clustered CR1 covariance and t(G-1) intervals.
Fixed effects use checked alternating projections. Rank deficiencies and
unidentified targets stop the affected stage instead of yielding zero effects.

Within each board-region ladder, every model uses the same complete-case rows
and choosers observed in both formats. The strict check further requires both
formats within a chooser's exact time-control/month cell. These restrictions
will reduce the effective arena sample; coverage tables show the reduction.
The standardized arena and pool rates, and their ratio, are point estimates.
Uncertainty is supplied for the adjusted difference, not for the rate ratio.

Board bins use the disconnected player's evaluation: >=300, 101–299, -100–100,
-299–-101, <=-300 cp. Stage bins are <=4, 5–6, 7–8, 9–10, 11–20, 21–40, 41–80,
and >80 plies. Each inherited rating-gap/payoff engine retains its own frozen
sample rules and model plan; its tables carry the resulting sample counts.

## Receipt, IV, episodes, and Patron scope

Receipt support selects the next observed fair opportunity across ALL sources
after an arena grant or chooser win, then labels that target's source. It never
skips an earlier pool opportunity to create an arena-to-arena link. Duplicate
exposure or target timestamps are counted and left unresolved. `lastMoveAt` is
only a timing proxy; ordinary games and passive endings are absent from this
support panel. These candidate counts are not the certified A1 risk set, a
causal receipt estimate, an instrument, or a full intervening-game history.

Episode output counts repeat granters; it does not rerun episode shuffles.
Patron output authenticates and counts coverage in the existing snapshot,
without requesting new profiles or treating missing profiles as non-Patrons.
If the snapshot is absent, support is explicitly unknown. Rebuilding the
corresponding design and matching remains necessary before those effects can
be interpreted as arena replications.

## Interpreting the suppression test

An adjusted reduction in arena granting would weigh against a setting-invariant
misclick rate. It would not by itself exclude attention or interface-related
error rates that vary with tournament incentives. Arena participation and the
active-resolution sample are selected; the fixed-effect contrast remains
observational. Arena points and streaks also add costs beyond rating payoff,
so the rating-payoff diagnostic does not measure the full arena cost of a draw.
Historical claim/draw interface equivalence is not audited by this package.

## Required existing inputs

The bundled original builder resolves and authenticates the precise files:

- `derived/replication/analysis_panel_24m_sf100k/`, its original certificate,
  and the 24 monthly `analysis_panel.parquet` files;
- the completed source-union map at the private path recorded in its
  authenticated certificate;
- `output/rematch_source_join_v100/20260908T031408Z_6459_source_union_20260909/`,
  including its checkpoint ledger and all 128 joined game partitions;
- optionally, `derived/replication/patron_profile_snapshot_24m_v100_FINAL_CERTIFIED/profile_snapshot_24m_private_lossless.parquet`.

The completed pool filtered panel is not required: the same predicate is
applied directly to the authenticated original panel and its source masks.
The build verifies the exact certified pool margins as well as arena counts.

## Restart and failure handling

Rerun the same terminal command to resume. A run pointer under
`output/arena_replication_v102/ACTIVE_RUN.json` selects the existing run.
Completed months, models, and stages are reused after checksum verification.
An interruption before a checkpoint is committed causes that unit to be
recomputed. Incomplete figure attempts are preserved under another name.
A mismatch in committed output or input bytes is a failure, never a silent
repair. Add `--fresh` to the launcher invocation to start a separate run while
preserving the previous one. A lock prevents two coordinator runs at once.

Independent later stages continue after a model-stage failure; nonparametric
gap analysis waits for a successful K/RD stage. The result ZIP includes
`RUN_STATUS.json` and completed outputs even if the run is partial. `COMPLETE`
means that all stages in this wave ran; unsupported estimates and missing
optional profile data remain explicitly labelled. Read the status and support
tables before using any result in the manuscript.

Optional launcher environment settings are `ARENA_PROJECT_ROOT`, `ARENA_PYTHON`,
`ARENA_WORKERS`, `ARENA_THREADS`, and `ARENA_DUCKDB_MEMORY`. Preserve the default
sample and method choices when changing resource settings.

## Source lineage and validation

`authority/UPSTREAM_FILES.json` records every unchanged recovered source file.
The input authenticator and evidence come from the completed pool main-sample
builder. Structural and payoff engines come from Pool Wave 1 v1.0.0; the
repository head inspected was `bf3b2bf9ffedba8f53c61e3e1b55bb457e58a129`.
Adapters bind these engines to the authenticated arena subset and its expected
rows; the old full-panel numeric bridge is not an arena validation target.
The Stage 08 kernel is retained for an independent projection test. The copied
Stage 09 file is provenance, and is not run as a receipt/IV estimator here.
`source/certified/` contains the exact Stage 05 and Stage 07 producer code for
definition provenance. These producers are not executed by this package.
Their SHA-256 values match the original Stage 07 certificate bundled at
`authority/STAGE07_CERTIFICATE.json`; the clock rule is recorded in
`authority/OPPORTUNITY_CONTRACT.json`.

`VALIDATION.json` records the local checks and their limitations.
`PACKAGE_MANIFEST.sha256` verifies all package files, and the outer ZIP has a
separate checksum. No production result or synthetic result table is bundled.
