# Pool Construal Tests v1.0.0

Tests and diagnostics for the revised engagement model. Run on the Mac with
XT_Pro mounted. Put the ZIP and its SHA-256 sidecar in
`~/Desktop/Lichess_Desktop`; the complete command is in `RUN_TERMINAL.txt`.

The package reads the **certified 41,534,331-row pool / observed-nonadjacent
sample**. It does not rebuild that sample, run Stockfish, call the Lichess
API, or change source files. The supplied September 1 index and September 3
manuscript describe an older sample; their 47.6 million rows are not the main
input here.

## What runs

| Original implication | Implemented analysis | What the result can establish |
|---|---|---|
| T1: different response types | Static finite mixtures, a correlated bivariate-normal intercept/sensitivity comparator, and switching models, scored on account-disjoint evaluation data | Relative predictive performance of specified distributions; no proof of bimodality or rejection of every continuous alternative |
| T2: cost insensitivity in the flat component | Gate versus gate-cost, which frees lower-state loss, gain and win-premium coefficients | Whether relaxing those restrictions improves prediction; nominal payoff is not an exogenous price |
| T3: state insensitivity | Gate versus unrestricted switching emissions; calibration by board, stage, payoff, clocks and rating gap | A test of the flat-emission restriction within the maintained model; no observed non-construer classification |
| T4: ply-2 granting comes from crossings | Year-two ply-2/ply-20 tables using first-year other-opportunity history; account-FE interaction on accounts with both targets and at least five prior other opportunities | A conditional descriptive comparison with explicit support; it cannot decide salience versus warrant by itself |
| T5: receipt heterogeneity | Reviewed IV re-estimated by strictly prior observed main-panel history; direct prior-granter/non-granter contrast with joint covariance; known-age subgroups when available | Heterogeneous responses under the IV design's assumptions; not a mechanism-specific conversion test |
| T6: front-loaded responses | IV grant and opportunity counts over days 1–7, 8–30, and 31–90; early-minus-late effects per day; matched switching forecast contrasts | Response profiles and opportunity exposure; not permanent conversion, an isolated impulse, or a causal grant/opportunity ratio |
| T7: latency | Source-field feasibility audit | Explicitly unavailable: no invented decision latency from last-move timestamps |
| T8: external acts | Incremental Patron prediction beyond first-year observed granting, on returned profiles in the certified selected snapshot | Additional same-platform prediction, not moral-trait identification or causal Patron adoption |

The central comparison fits **gate**, **intercept-shift willingness**, and
**unrestricted** two-state models with the same persistent granting level,
persistent transition heterogeneity, covariates, initial state model, and
transition specification. It also fits gate-cost, static level mixtures,
static selectivity mixtures, and a continuous normal selectivity model.

The original claims of a zero marginal receipt-by-board interaction under
willingness and a universal T5 conversion prediction are not tested as if
they were valid. The report instead uses full model forecasts and direct
subgroup contrasts. See `METHODS.md`.

## Defaults and resources

- Development: 20,000 accounts from the original pilot's first-year hash order.
- Evaluation: 50,000 other accounts, excluding **all 100,000 original pilot accounts**.
- Selection ignores second-year giving and second-year participation.
- First-year chronological validation chooses support size from common grids.
- 2 fitting workers; 1 thread per numerical process; 1 source-hashing worker.
- DuckDB memory limit: 4GB. This is not a cap on total Python/process memory.
- 20 account-refit bootstrap repetitions. These give an exploratory SE;
  percentile intervals are withheld until 100 converged refits.
- Fixed-design recovery checks on up to 1,500 actual first-year histories.
- Minimum 20 GiB free disk for private caches and spill; more may be needed.

The first run verifies approximately 12GB of panel files, constructs ordered
histories, and estimates many models. **Allow hours; production runtime has
not been benchmarked.** The two-worker default leaves CPU capacity for your
running Stockfish job, though both jobs still compete for RAM and disk.
There is no need for ten workers for this first pass.

## Timing limitation

The panel supplies game start and API `lastMoveAt`, **not verified choice or
countdown timestamps**. The switching run therefore estimates a recorded-time
version of the model. It excludes overlapping recorded game intervals and
uses a five-minute separation guard. Receipt inputs include only main-panel
acts whose recorded game interval lies safely between consecutive retained
chooser opportunities. Ambiguous recorded receipts are counted separately
and included as a transition control. A guard does not certify true click
times or observe unrecorded receipts. The IV module independently preserves
the reviewed design's existing timing proxy and exact outcome definition.

The report makes this qualification visible. It does not claim to have
estimated a verified decision-time recognition process. The guard is an
implementation sensitivity, not a new exclusion restriction or instrument.

## Outputs and resuming

Outputs go to a new deterministic directory under:

`/Volumes/XT_Pro/lichess_kindness/output/pool_construal_tests_v100_<run_id>/`

- `PRIVATE/`: account IDs, ordered histories, first-year posteriors, model
  attempts, bootstrap attempts, and local error logs. Keep these private.
- `report/`: aggregate support, scores, estimates, diagnostics, status,
  provenance, and model parameters.

The aggregate report ZIP and sidecar are copied to `Lichess_Desktop` and
printed after `UPLOAD:`. **Upload those two files; do not upload `PRIVATE/`.**

Repeat the same command to resume. Completed preparation and fit attempts
are verified by checksum and reused. An interrupted fit restarts; completed
fits do not. Worker counts may change without changing statistical identity.
Changing statistical settings, bootstrap budget, package bytes, or numerical
dependencies creates a new run identity. Source files remain read-only.

Missing optional IV/profile inputs produce explicit `NOT_RUN` statuses.
Contract mismatches produce failures, not silent substitutions. Numerical
nonconvergence and boundary solutions remain visible even if a report is
successfully produced. A computation-complete marker is not a passed theory
test. A failed run still exports its aggregate diagnostics.

## Main files to read

1. `RUN_STATUS.json`, `TIMING_AUDIT.json`, `cohort_support.csv` and `sequence_support.csv`.
2. `optimizer_attempts.csv` and `first_year_selection.csv`.
3. `primary_comparisons.csv`, `refit_bootstrap_summary.csv`, `heldout_gains.csv`.
4. `heldout_calibration.csv`, `receipt_model_forecast_surface.csv`.
5. `PLY2_INTERACTION.json`, `ply2_prior_history.csv`.
6. `receipt_IV_contrasts.csv`, `receipt_IV_estimates.csv`.
7. `patron_incremental_gains.csv`, `LATENCY_FEASIBILITY.json`.

Named emission, transition, initial-state, and persistent-support coefficients
are also exported. They describe the fitted latent model; their state labels
are not observed psychological categories.

## Optional settings

Append these to the launcher command before its log redirection:

- `--audit-only`: source, chronology, ply-2 support, and latency feasibility only.
- `--bootstrap-refits 100`: a larger refit budget; requires at least 100
  converged draws for percentile intervals. Choose before the first run if desired.
- `--timing-guard-seconds 0` or `3600`: separate recorded-time sensitivity runs.
- `--dev-accounts 50000 --eval-accounts 100000`: larger cohorts.
- `--support-grid 2,3,5 --normal-grid 5,9`: richer heterogeneity/quadrature check.
- `--maxiter 1000 --starts 3`: more optimisation effort if diagnostics warrant it.
- `--sample-root /absolute/path/to/certified_sample`: a relocated unchanged sample.

Use `LICHESS_CONSTRUAL_WORKERS=1` for less CPU/process memory, or up to 10 on
an idle machine with sufficient RAM. Extra workers help parallel restarts;
most large data stages are not duplicated across workers.

The package's offline tests enumerate state paths to check the likelihood,
check all analytic gradients against finite differences, verify that future
outcomes cannot change earlier forecasts, check exact nested embeddings,
validate the IV follow-up exclusions, and compare covariance calculations
with an explicit pairwise dependency calculation. The full private source
panel is unavailable here; real estimates are produced when you run the Mac
command.
