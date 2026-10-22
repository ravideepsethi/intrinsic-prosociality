# Rating milestones and kindness: frozen exploratory specification

Version 1.0.0, 2026-09-16. This is executable analysis code, not a report of empirical results.

## Sample and provenance

The source is exactly the 24-month, 41,534,331-row main pool sample:

`source = 'pool' AND previous_classification_status = 'not_mutually_adjacent_observed'`.

It spans November 2023 through October 2025. The runner verifies the original success receipt, all 24 full-file SHA-256 hashes, schemas, sizes, and counts against the bundled certified main-sample report. The original sample has 570,091 kind draws and 3,224,173 choosers. The 100,000-node disconnected-player evaluation identifies 15,207,423 competitive opportunities (evaluation >= -100 cp), including 419,463 kind draws. The complete source is authenticated and audited, then these competitive rows are staged. Clearly-lost and excluded-middle boards do not enter this analysis.

The existing screen is an **observed mutual-adjacency screen**. The sample's own certificate does not certify the removal of every literal immediate rematch. This runner preserves the exact current sample and its qualification.

Default sample root:

`/Volumes/XT_Pro/lichess_kindness/derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE`

Each month is `panel/month=YYYY-MM/analysis_panel.parquet`. The runner never replaces this sample or falls back to the old 47.6M panel. Required invalid fields, identity failures, altered source hashes, and missing months stop the run. Missing/nonfinite/negative clock and time-control values get explicit missing indicators; they do not silently remove observations.

## Two primary tests

Let R be the chooser's displayed pre-game integer rating, D the reconstructed draw payoff, and W the reconstructed win payoff. Their difference W-D must equal the stored chooser win premium, K/2. Reconstruct the two post-game rating quantities as R+D and R+W. They are **approximations based on the displayed starting rating**, not observed counterfactual outcomes or recovered exact display values.

For the primary analysis, T is the nearest multiple of 100 from 500 through 3000, and d=R-T. Keep |d|<=25. These windows do not overlap; an observation can appear at most once in a given specification. Ratings outside these windows remain in source auditing but not the local regression. The threshold range is frozen, not selected from significance. Major milestones such as 1000, 1500, 2000 and 2500 also have separately tabulated estimates.

1. **Loss crossing / protecting a milestone**: R>=T and R+D<T<=R+W. A draw puts a milestone already held at risk, while a claim retains it.
2. **Gain crossing / reaching a milestone**: R<T and R+D<T<=R+W. A claim reaches the target, while a draw does not.

The two indicators are mutually exclusive and enter the primary regression jointly. Equality at the target counts as retaining or reaching it; crossing below is strict. A negative coefficient means lower conditional kindness in that state. No negative sign is imposed during estimation.

This operationalizes the older near-zero supplement's round-number idea, with local, nonoverlapping windows and explicit control for the pre-rating's position relative to the threshold. It does not execute the other unrelated near-zero supplement modules. It also does not claim that the crossing variables are independent of opponent characteristics: D and W are functions of the rating pair and rating uncertainty.

## Estimator and controls

The outcome is `outcome_kind_draw`, scaled to percentage points only when reporting. Every model is an exact within-chooser linear probability regression. A chooser with only one eligible observation in that model contributes no identifying variation and is dropped. The same chooser's observations across months and speed pools stay together, so fixed effects and cluster covariance are never computed independently by month or shard.

Controls, fixed before looking at results:

- Chooser fixed effects, one intercept per account.
- Threshold indicators; a pre-rating-at/above-threshold indicator; separate linear and quadratic distance terms below and above the threshold.
- Rating gap (opponent minus chooser), clipped at +/-1000 points, with a piecewise-linear spline at -400, -200, -100, 0, 100, 200 and 400.
- Draw payoff: asinh(D/5), with piecewise-linear hinges corresponding to D=-15,-5,0,5,15.
- Log K and its square, where K=2 times the win premium.
- Both players' log RD and log volatility, each with its square.
- Disconnected-player engine evaluation clipped to [-100,600], linear and quadratic, plus 50-centipawn categories with an upper tail.
- Game stage: log(1+ply) and its square; bands <=4, 5-10, 11-20, 21-40, 41-80, 81+.
- Log(1+clock) for both players; log(1+base time) and log(1+increment); missing indicators for each.
- Chooser color, calendar-month indicators, and speed-pool indicators.

All these variables precede the draw-versus-claim action. The coefficients remain conditional associations; many controls, including game stage and the board position, may themselves reflect earlier play. The local analysis is not a randomized assignment or an RD design.

## Sensitivities, comparisons and figures

The complete fixed set is in `milestone_model.py:specifications()`:

- Primary hundred-point targets, +/-25 points.
- +/-15 and +/-40-point windows.
- Both pre-game RDs <=100 (an established-rating proxy, not a recovered historical provisional flag).
- Both RDs <=100 and the entire 1500-target window omitted. This addresses the special starting-rating concentration at 1500 without selecting individual observations by outcome.
- Games past ply 10.
- Rounding-safe subset: both reconstructed post-game ratings must be more than 0.5 points from T. This checks local classification ambiguity; it does not authenticate exact counterfactual display values.
- Nearest-integer sensitivity using floor(R+payoff+0.5) for each action. This is an explicit half-up approximation, not a claim about the platform's precise historical display implementation.
- Thresholds ending in 50. These may themselves be salient, so they are a weaker-salience comparison, not a guaranteed null.
- Two frozen pseudo-threshold grids: 100k+37 and 100k+73, using the same +/-25-point window and controls. These are diagnostics, not valid randomization placebos by assumption.
- Individual hundred-point targets: loss/gain indicators interacted with T, estimated together in a single model. These allow a direct look at 1000, 1500, 2000 and 2500 without running a significance search.
- An adjusted proximity profile in five-point distance bins, relative to +10 through +14 points. The last bin also contains +25. This model uses bin indicators instead of crossing indicators and distance polynomials; it retains the other controls and threshold indicators. It answers whether kindness changes with proximity, a distinct descriptive question from action-specific crossing.

Raw one-point distance cells, by threshold and pooled, retain all eligible competitive rows, including chooser singletons. Adjusted figures use their model-specific nonsingleton samples. They are labeled separately and should not be read as a decomposition on identical samples.

## Inference, support and multiple testing

Covariance is clustered by chooser with correction G/(G-1) * (N-1)/(N-G-rank(X_within)). Confidence intervals and two-sided p-values use a t distribution with G-1 degrees of freedom. Tests of a coefficient's estimability are based on the scaled within-design eigenspace. Collinear or constant treatment directions are not silently reported as zero.

To report a coefficient, require an estimable contrast, positive residual degrees of freedom, at least 1000 treated/bin observations and 1000 other observations, at least 100 choosers who switch into/out of that treatment/bin, and treated/bin support in at least six months. The proximity profile also requires supported reference-bin counts. These gates concern support, not whether a coefficient is significant. Every attempted test is retained in `all_model_attempts.csv`, including failed gates.

The two primary crossing tests receive Holm correction within a two-test family. All remaining crossing coefficients, including individual milestones and offset checks, form a separate fixed secondary family (72 tests). Unsupported attempts enter Holm arithmetic as p=1, and retain missing coefficient/p-value fields with a stated reason. Profile intervals are pointwise descriptive intervals; they do not support a search for significant bins. All analysis is exploratory in the broader project: this is not a preregistration or a previously untouched confirmatory outcome.

A negative primary estimate that is stable in the established/no-1500 checks and absent at the offset grids would be consistent with milestone sensitivity. It would not alone establish a causal reference point, identify loss aversion, or rule out selection near thresholds. A non-rejection is not equivalence.

## Personal bests

No personal-best result is produced. The maximum rating among selected disconnect opportunities is not a valid prior personal best. A proper extension needs the authenticated **all-game, prior-only rating chronology within each speed pool**, a lookback/support rule, and controls for recent results. This package does not relabel a selected-sample maximum as a lifetime or historical peak.

## Computation and outputs

The source authentication reads about 12.6 GB. DuckDB projects just the required fields, audits the full sample and sorts the competitive subset by chooser, spilling to disk if needed. A slim ZSTD Parquet is then split by chooser ID modulo the worker count. Up to ten processes perform exact FE moments and cluster covariance in two passes. Numerical-library threads are capped at one per worker. DuckDB's default 6 GB limit applies only to its staging phase, not as a total RAM limit for all worker processes. Estimation streams 8192-row blocks, extended when necessary to keep a complete chooser together.

Indicative runtime: roughly 30-120 minutes on a modern Mac with ten workers and a fast external SSD; allow 2-3 hours for a slower drive or busy machine. This is an engineering estimate, not a benchmark on your actual data or Mac. Reserve roughly 15-25 GB of free output/spill space. Existing source files are never modified. No API or Stockfish work is needed. Dependency installation may use the network; the analysis itself makes no network requests.

Output root:

`/Volumes/XT_Pro/lichess_kindness/output/pool_rating_milestones_v100/<run identity>/`

`PRIVATE/` holds slim rows and checkpoints. `report/` contains aggregate CSV tables, pointwise cluster intervals, figures, input/source receipts, executed code and `_SUCCESS.json`. User identifiers and row-level records stay out of the returned results ZIP. The run identity hashes the package manifest, sample fingerprint, settings and dependency versions. Completed base, shard, moments and covariance stages can be resumed by re-running the same command with unchanged settings/environment. A completed report is reused, not re-estimated. Corrupted checkpoints stop the run.

The desktop receives `POOL_RATING_MILESTONES_RESULTS_v100_<identity>.zip` and `.zip.sha256`. A log is written to `~/Desktop/Lichess_Desktop`. A failed run retains diagnostics and partial files; it does not get a success receipt.
