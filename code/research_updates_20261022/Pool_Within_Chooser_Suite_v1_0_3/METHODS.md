# Estimands and model definitions

## Research question and outcome

For the same chooser, how does the probability of granting a draw vary with the
opponent's board position and how much play has occurred? Do these patterns
survive controls for rating circumstances and alternate weighting? Does the
pattern differ with the chooser's observed Patron status in the queried sample?

One row is one certified choice opportunity resolved by the remaining player.
`y=1` for a kind draw, `0` for claiming victory. The analysis is conditional on
acting and on entering the observed-disconnection sample. It cannot identify the
effect of disconnection or the probability of acting among all disconnectors.

Within-chooser FE absorb all time-invariant account characteristics. They remove
an explanation based solely on different types of people encountering different
states. They do not randomize board positions, game lengths, costs, or Patron
status; time-varying circumstances and selection into observed opportunities
remain. Use “within-chooser association” or “state dependence,” not a causal
effect of deservingness. Stockfish evaluation is an operational measure of the
opponent's competitive position, not a direct observation of a moral judgment.

## Common sample and measurement

The source is the certified 24-month pool / observed-nonadjacent panel. Keep all
five board categories, including the bin historically named
`modestly_worse_excluded`. No additional first-encounter restriction is imposed.

Evaluation is from the disconnected player's perspective:

| Board state | Centipawn evaluation |
|---|---|
| Clearly worse / losing | cp <= -300 |
| Modestly worse | -300 < cp < -100 |
| Roughly equal | -100 <= cp <= 100 |
| Better | 100 < cp < 300 |
| Clearly better | cp >= 300 |

Ply bands are 0–4, 5–6, 7–8, 9–10, 11–20, 21–40, 41–80 and 81+.
One ply is one player's move. These are final observed plies, not the exact
instant a network connection was lost.

All state specifications and two main robustness specifications use the same
complete-control rows. Required: chooser ID, outcome, valid stored state,
finite evaluation, nonnegative integer ply, calendar month, API speed, finite
ratings, positive forgone win premium, positive reconstructed pre-game RD and
volatility for each player. Missing values cause explicit counted exclusions.

Each clock is the player's last recorded clock. Missing or nonfinite clocks
enter as log value zero with a separate missingness dummy for each player;
finite negative clocks are clamped to zero and counted. These measurements do
not claim to observe exact remaining seconds at the disconnect/choice instant.

## Primary specification ladder

The saturated linear probability model is

    y_ig = alpha_i + lambda_(month × API-speed)
           + sum_(b,p != reference) theta_bp 1[B_ig=b, P_ig=p]
           + clock terms + economic terms + error_ig.

The omitted cell is clearly losing, plies 0–4. There are 39 state-stage terms;
reported contrasts compare cells directly and do not rely on interpreting the
reference cell's intercept. Calendar effects are month interacted with exact
API speed, using every observed calendar cell except the first.

| Specification | Terms beyond chooser FE and calendar cells |
|---|---|
| S1_state_stage | Saturated board × ply-band cells |
| S2_plus_clocks | S1 + both log(1+clock) values + two missing-clock indicators |
| S3_full (primary) | S2 + economic/account controls below |
| S4_exact_early_ply | S3 + exact-ply indicators through ply 20 |
| A_additive (summary) | Separate board and ply-band indicators + S3 controls |

The additive model is a restricted summary. The saturated S3 model allows the
board-state association to differ in openings and later play. Its 28-df
nonadditivity restriction is tested using the full clustered covariance.
S4 omits one exact-ply indicator within each early band, so exact-ply nuisance
effects add within-band detail without duplicating the band main effects.
It does not interact board state with every exact ply or extrapolate exact-ply
controls beyond 20.

Economic/account controls are additive linear splines with frozen knots:

- Signed rating gap = disconnected rating minus chooser rating, divided by
  100, with knots at -400, -200, -100, 0, 100, 200, 400 Elo.
- Log(1 + chooser win premium), with premium knots 1, 3, 10, 30, 100.
  The premium is the reconstructed rating payoff of win minus draw.
- Each player's log(1 + pre-game RD), with RD knots 50, 100, 200.
- Each player's log(pre-game volatility), entered linearly.
- Chooser rating centered at 1500 and divided by 1000, with a hinge at 1500.

These account for relative strength, forgone payoff and rating uncertainty;
their coefficients are nuisance adjustments, not separate causal estimates of
each channel. Draw payoff is not included again as another highly overlapping
economic regressor. The separate verified rating family already provides the
project's dedicated relative-strength/payoff analysis with its original
specification ladder and chooser×board-state effects.

## Robustness and account weighting

- `W_inverse_account_count`: S3 with each observation weighted by 1/N_i, where
  N_i is that chooser's common-sample opportunity count. Total raw weight per
  chooser is one. This is a different WLS projection, not an unweighted mean of
  individual causal effects; within-person variation still affects information.
- `R_chooser_speed_FE`: S3 with chooser×API-speed fixed effects and calendar
  effects. The estimator demeans within chooser-speed units, while inference
  remains clustered by chooser. Identifying variation can differ from S3 even
  though the input rows and standardization weights are the same.

Never-granters and always-granters remain in all new LPM samples. Singleton FE
units remain in the raw counts but contribute zero within-unit variation. Both
raw N and rows in nonsingleton FE units are reported; do not call raw N the
number of identifying observations. No fixed-effects logit is fit, so there
is no implicit restriction to accounts that sometimes grant and sometimes deny.

## Patron interaction diagnostic

Only returned, classified profiles in the certified August 21–26, 2026 snapshot
are eligible. The normalized profile marker must reproduce 1,305,683 returned
profiles and 4,896 Patrons before it is joined. These are snapshot totals, not
guaranteed regression-sample totals. Later supplements are deliberately kept
out of this one-snapshot diagnostic.

The model adds Patron × the 39 board-stage terms to S3 and includes chooser FE.
A Patron main effect is absorbed by chooser FE and is not estimated. Common
calendar, clock and economic slopes are assumed across Patron groups.

The target is a difference in within-chooser contrasts:

    [competitive minus losing | Patron]
      minus [competitive minus losing | non-Patron], at a fixed ply band.

The ordinary cell coefficients in this model describe the non-Patron baseline;
their exported contrasts have the `nonpatron_` prefix. The interaction contrasts
have the `patron_minus_nonpatron_` prefix. A zero Patron interaction does not mean
Patrons and non-Patrons have equal kindness levels, which this model cannot test.

The profile sampling frame included ever-granters and matched controls and was
chosen using kindness history. Inclusion weights sufficient for population
inference are not available in this package. Thus neither chooser FE nor these
interactions removes that selection. This is a selected-sample diagnostic,
and the current marker is measured after the game window. It cannot establish
that Patron status existed when the choice occurred, that Patrons represent
all paying donors, or that donation caused a different response.

## Contrasts, weighting and inference

For every stage report each of four states versus clearly losing, roughly equal
versus better, and a competitive-versus-losing contrast. Competitive combines
equal, better and clearly better using their fixed opportunity shares in the
common regression sample. The same competitive mix is used at every stage and
in every model. This prevents changes in composition across the three states
from mechanically becoming changes in the summary contrast.

The overall competitive-minus-losing contrast uses fixed common-sample shares
of all eight ply bands. Weights are recorded in `MODEL_DESIGN.json`, stay fixed
for the inverse-count and selected-Patron models, and are treated as fixed in
inference. It is a standardized regression contrast, not a raw difference in
rates and not a causal average effect. Components lacking within-sample support
make the relevant contrast nonidentified rather than being silently imputed.

Also report every later ply band versus 0–4 separately within each board state.
Joint Wald tests cover all board differences, all stage differences, and board
× stage nonadditivity; the Patron model adds differential board selectivity.

All new covariance matrices use the chooser-cluster sandwich with CR1 multiplier
G/(G-1). Absorbed FE nested within clusters are not separately charged in this
convention; there is no additional (N-1)/(N-K) factor. Individual contrasts use
t_(G-1) reference intervals/p-values; joint tests use asymptotic chi-square with
the estimated restriction rank. Intervals are pointwise, not simultaneous, and
no multiplicity correction is asserted. Report magnitudes and uncertainty; tiny
p-values can underflow to zero numerically and should not be printed as an
exact mathematical probability of zero.

The existing rating and receipt files retain their own documented covariance
and small-sample conventions. In particular, the receipt archive preserves its
shared-account-or-date CR0 scheme. Its original IV/weak-instrument diagnostics
remain attached; recipient FE alone does not establish exogeneity of receipt.

## Numerical implementation and audit

Version 1.0.2 responds to two numerical-check failures in the uploaded 1.0.1 run.
It uses SciPy's symmetric BLAS product on an explicit Fortran-order matrix and
checks every diagonal and three deterministic projection identities against
independent NumPy scalar reductions. The tolerance for these checks is 1e-10.
A failed product is recomputed by a nonoptimized einsum and checked again;
persistent disagreement stops the run. Prediction dot products also use a
nonoptimized einsum. Within-chooser centering is checked separately. Positive
account weighting is required to preserve exact unweighted null directions.

The original 1e-7 normal-equation and clustered-score guards remain unchanged.
Score vectors, expected scores from moments, and cluster-meat matrices are saved
before the final guard, along with numerical-library backend information. These
are aggregate outputs. No account identifiers are included. This changes the
calculation and diagnostics, not the estimand or specification.

The code sorts one narrow private Parquet cache by chooser and partitions it by
chooser ID modulo the worker count. Each complete cluster stays in one worker,
which streams bounded batches and performs exact demeaning. A spawn-based pool
of up to ten processes uses one BLAS thread per worker, with Arrow decoder
threads also limited to one. Workers' Gram matrices and RHS vectors are summed
before a single global solve; cluster-score outer products are summed in the
second pass using that global coefficient vector. Coefficients from separate
regressions are never averaged. The reduction order is deterministic.

There is one moment pass and one residual-score pass per family. All state-ladder
models share their moment pass. The pool stays open across families, while SQL
preparation finishes before the pool starts. No row-level residuals or account
IDs are exported. New tabular results are Zstandard-compressed Parquet, with
CSV convenience copies. Covariances and Gram matrices additionally have
upper-triangle Parquet representations. Reused original archives are unchanged.

Gram matrices are column-normalized and solved by symmetric eigendecomposition,
with relative eigenvalue tolerance 1e-10 (absolute floor 1e-12). There is no ridge
penalty. Explicit null-space tests determine whether each published coefficient
and contrast is estimable. Unsupported comparisons receive empty CSV estimates
and “Not identified” in tables. Generalized coefficient vectors inside NPZ files
are numerical representations; use the estimability flags before interpreting
any parameter. Normal-equation and cluster-score residuals must pass 1e-7 checks.

`test_suite.py` compares target contrasts and cluster covariance against
independent full-dummy WLS on synthetic data for every family, tests batch-size
invariance, singleton/never-granter handling, unsupported targets, boundary
coding, common support, missing clocks, profile joining and stored provenance.
It also checks every parallel family against the original serial estimator and
verifies the Parquet column types. It does not certify a full private-panel run. `VALIDATION.json` records the
development results; the terminal launcher reruns these checks before estimation.

## v1.0.3 targeted recovery

The launcher now runs only S4 from the authenticated v102 narrow cache, using
independent columnwise demeaning, prediction accumulation and cluster-score
reductions on contiguous float64 arrays. Full centered-design hashes must match
between passes for every worker. Independent response cross-products and direct
row-to-cluster score sums are checked. The original 1e-7 normal-equation and
score guards are unchanged; score-versus-moments disagreement also stops export.
The source of v102's S4 discrepancy remains unconfirmed. No empirical estimates
are altered to force agreement. A/S1/S2/S3 are exported from saved validated
arrays; completed robustness and prior research modules are copied unchanged.
Only a passing new S4 run yields a COMPLETE ledger.

The startup test now specifically uses the production design width: 96 calendar
cells, 14 early-ply indicators including ply 13, int32 plies, and collinear
centered premium spline terms. Independent full-dummy WLS verifies contrasts and
clustered covariance. Injected faults test prediction, design-hash, and response
cross-product checks. Development orchestration tests exercise both successful
and failed S4 recovery, cache authentication, reuse provenance and report output.
