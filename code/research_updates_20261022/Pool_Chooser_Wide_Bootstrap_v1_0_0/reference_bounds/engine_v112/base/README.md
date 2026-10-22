# Pool chooser benchmark v1.0.0

This package implements the priority comparisons discussed after the revised
chooser model. It is a new analysis, not a relabeling of the construal results.
It reads the authenticated 41,534,331-row pool/nonadjacent panel and never changes
source data or previous analysis outputs.

## What runs

1. Four persistent-type models: level only, desert heterogeneity, proportional
   cost heterogeneity, and both.
2. Shared-index test: a free common cell index versus unrestricted type-by-cell
   effects. This tests the common state surface, not just multiplicative shape.
3. Separable versus free-cell index; optional calibrated versus free-board
   separability if an independently prepared training calibration is provided.
4. No cost, premium only, premium plus draw loss, separate nonnegative cost
   coefficients, and unrestricted-sign cost coefficients.
5. Sequential held-out scores, state/tier calibration, opportunity-weighted and
   equal-account gains, optimizer/bound diagnostics and within-account support.
6. Full-history, fixed-design recovery and population-parameter refit bootstrap.
7. Optional matched-sample perception comparisons, using exact normal-bin
   probabilities, plus curvature/mean-index decomposition, recovery and bootstrap.

Not implemented here: a new switching model with these exact emissions, a
two-factor intermediate surface, Patron regressions, or disconnection-cause
identification. The existing switching package remains separate. Do not compare
its score numbers with this package as though samples and regressors were equal.
The unrestricted type-by-cell comparison is the implemented shared-index test.

## Place and run

Put the ZIP and its `.sha256` file in `~/Desktop/Lichess_Desktop`, as usual.
`RUN_TERMINAL.txt` gives complete commands. The default command first audits the
sample and fits the main comparisons. It uses four processes with numerical
libraries limited to one thread each. Set `--workers 2` on a memory-constrained
machine. Up to ten workers are accepted, but more workers multiply memory use.

The source defaults to:

`/Volumes/XT_Pro/lichess_kindness/derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE`

The source root must contain its certified `_SUCCESS.json` and `panel/` directory.
The 24 monthly Parquets are authenticated against the bundled sample report,
including SHA-256. This is NOT the old 47.6-million-row sample.

Outputs and private account caches go to a new directory:

`/Volumes/XT_Pro/lichess_kindness/output/pool_chooser_benchmark_v100_<identity>/`

Only aggregate reports are zipped back onto your Desktop. The return files are:

`POOL_CHOOSER_BENCHMARK_RESULTS_v100_<identity>.zip`

and its `.sha256` sidecar. Return both. Do not upload `PRIVATE/`.

## Recommended stages

- First: `--stages audit,fit`. Inspect support, selection and convergence before
  committing to hundreds of refits.
- Then: `--stages recovery,bootstrap --recovery-reps 20 --bootstrap-refits 120`.
- Separately: `--stages perception,perception-recovery,perception-bootstrap` with
  the same full recovery/bootstrap budgets, after the core comparisons are reviewed.

Recovery uses the full selected development/evaluation histories, not a tiny
1,500-account toy. It simulates independent account types in each cohort and new
choices along the observed designs. The selected number of support points and
regularization remain fixed. Read the event counts and parameter-recovery errors,
not only how often each model wins. Default development size is 25,000 accounts;
evaluation size is 50,000 accounts, with no requirement that they return in year
two. Actual retained histories and events are reported.

This is a substantial local computation. No production runtime is promised.
Progress/heartbeats print throughout. `caffeinate` keeps the Mac awake.

## Resume and identity

Re-run the same command after interruption. Completed individual fits and
simulation replications are cached atomically. Increasing the number of bootstrap
or recovery replications resumes the same run; changing stages or worker counts
also keeps the same identity. Changing the statistical settings, code, software
versions or calibration creates a different run. Do not delete old caches.

The bootstrap reports intervals only with at least 100 successful paired refits.
Failures and bound hits remain visible. Intervals conditional on successful fits
need scrutiny if failures are material. They include population refitting and
evaluation-account resampling, but not the preceding specification search,
re-selection of complexity/support, external calibration uncertainty, or general
cross-account/time dependence. Conditional score SEs are separately labeled.

## Sampling and timing

The new cohorts exclude the original 100,000 pilot/challenge accounts and the
50,000 accounts selected for the returned v100 construal evaluation (seed 20260921).
This does not claim that no aggregate information about these accounts has ever
been inspected. Sampling is by account hash, not observed grants or year-two
activity. The source definitions and exclusion seeds are frozen.

Training for complexity selection ends July 31, 2024. August–October 2024 is
chronological validation. Selected structures are refit on November 2023–October
2024. Evaluation is November 2024–October 2025 on disjoint accounts; year-one and
earlier year-two outcomes update each account's posterior before its next forecast.
No outcome updates the forecast scored for that same outcome.

API `lastMoveAt` is a recorded ordering proxy, not a click/decision timestamp.
The package excludes both sides of overlapping recorded chooser intervals and
applies a 300-second guard. This is conditional on observed active resolutions,
not a model of choosing to act versus waiting for a clock expiration.

## Important differences from the prose benchmark

- Without an external calibration, the default board factor is estimated. The
  package does not invent completed-game nonloss probabilities.
- Controls use extrapolatable month-of-year seasonality rather than unidentified
  calendar-date dummy coefficients for the unseen second year. Time controls are
  speed categories plus log base/increment; exact choices are in MODEL_DESIGN.json.
- The index has 5 board bins × 4 stage bins × 5 expected-score bins, before
  early-training support exclusions. E bins are [0,.2), [.2,.4), [.4,.6), [.6,.8),
  [.8,1]. Both anchors are at 11–40 plies and E in [.4,.6), comparing clearly
  worse with roughly equal positions. Anchors never move in response to results.
- Common support and control scaling are frozen using early development data.
  All main models use that same retained support. Missing/invalid reconstructed
  cost quantities are excluded for all main comparisons, with coverage reported.
- Perception comparisons use verified numeric nonmate scores and omit exact bin
  boundaries in all four candidate models. They are not compared directly against
  main-sample scores. Their zero-noise comparator uses the same raw-score bins.

## Optional board calibration

`--board-calibration /absolute/path/calibration.json` accepts five nonnegative
`board_factor` values, with the equal-position factor greater than the clearly
worse factor, plus `training_end_ms`, `evaluation_accounts_excluded: true`,
`source_sha256`, and `description`. The training end must precede August 1, 2024.
These are required provenance declarations, not independent proof of sample
independence. Do not construct this file from the chooser's held-out choices.
Without it, the calibrated comparison is explicitly marked NOT_RUN.

## First files to read

- `RUN_STATUS.json`, `READ_RESULTS.md`, `SOURCE_AUDIT.json`
- `TIMING_AND_COST_SELECTION.json`, `WITHIN_ACCOUNT_SUPPORT.json`, `COST_SUPPORT.json`
- `complexity_selection.csv`, `optimizer_attempts.csv`
- `comparisons.csv`, `refit_bootstrap_summary.csv`
- `state_surfaces.csv`, `surface_singular_values.csv`, `types.csv`
- `recovery_results.csv`, `recovery_winners.csv`
- Optional `perception_comparisons.csv` and `perception_decomposition_*.csv`

Finite support does not establish bimodality. A score improvement does not prove
a moral motive, homogeneous preferences in a restricted dimension, or two
independent psychological traits. Zero costs make cost multipliers unidentified.
Perception variance is conditional on the measurement/exclusion assumptions.

## Test-to-output map

| Question | Comparison or diagnostic |
|---|---|
| Which response differs across accounts? | level, desert, cost, both; paired scores and full-refit uncertainty |
| Is multiplicative shape adequate? | free_index versus both |
| Do types share one state index? | type_cells versus free_index; inspect utility surfaces, not estimated individual slopes |
| Is cost negligible, kinked or nonproportional? | both versus no_cost/premium_only; separate_costs versus both |
| Does a flat static type recur? | Jointly inspect state-effect range and both cost coefficients in types.csv; this does not identify switching |
| Can perception reproduce the pattern? | Four matched perception specifications plus full-design sigma recovery and the curvature/mean-index decomposition |

No false claim is made that the most negative utility index must have the
largest absolute Jensen effect. The code computes the exact integrated response
and separates curvature from changes in the mean index. Neither a rating-level
gradient nor a positive fitted curvature component independently identifies noise.

See `METHODS.md` for parameterization and precise test mappings.
