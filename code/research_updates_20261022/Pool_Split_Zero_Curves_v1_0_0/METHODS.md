# Split the zero-payoff bin: methods

This package refits the full competitive-sample curves after replacing the
pooled draw-payoff category [−0.4,+0.4) with three categories:

| Category | Definition | Plotting coordinate |
|---|---|---:|
| Small loss | −0.4 ≤ D < 0 | −0.2 |
| Exact zero | D = 0 | 0 |
| Small gain | 0 < D < 0.4 | +0.2 |

D is the stored, unrounded `chooser_draw_payoff_v2`. No rounding or numerical
tolerance assigns observations to exact zero. Positive 0.4 belongs to the next
bin centered at +0.6. The finite endpoint +6 remains in the last finite bin;
more extreme observations remain in overflow categories.

The left rating-gap panel is unchanged: opponent-minus-chooser displayed
rating, 50-point bins centered on 0, ±50, ..., ±600, reference [−25,+25).
Both panels are refitted and the unchanged gap estimates and standard errors
are compared with the prior completed stable-rating run. The ±600/±6 views
show the supported finite bins; the central figures show the same central
ranges as the preceding figures, with the additional payoff dots at ±0.2.

## Sample

Parent authority: 41,534,331 pool, non-adjacent-rematch opportunities from
November 2023 through October 2025, with Stockfish 18 at 100,000 nodes. The
existing timeout/material/clock filters are inherited from the authenticated
monthly panel. There is no API acquisition and no change to those rules.

Competitive positions have recipient-oriented evaluation ≥−100 centipawns:
15,207,423 opportunities before chooser × board-state singleton removal;
13,203,811 estimation opportunities, 334,458 grants, 1,421,546 chooser clusters,
and 2,444,061 absorbed chooser × board-state units. All-zero granting accounts
remain in the estimator. No RD cutoff or K=11–12 restriction is applied.

The sample and all state-specific counts must match the prior stable run
68050a8540511454 exactly. The old pooled reference-bin observations must be
partitioned exhaustively into the three new categories. Both axes use the
same estimation observations.

## Estimator

Separate linear probability models for the two axes, with unrestricted bin
indicators. Fixed effects are chooser × broad competitive board state:
roughly equal (−100 through +100), better (>100 and <300), clearly better
(≥300). The nuisance controls are unchanged: spline in log(1+ply), separate
splines in both players' pregame RD and volatility, month and speed indicators,
fine 50-centipawn evaluation categories, frozen K20 categories, and log K.
K = 2 × chooser win premium. K cutpoints use the same frozen full-panel scope.

Complete chooser histories stay within worker shards and streamed blocks.
The estimator absorbs chooser × state units, but standard errors cluster by
chooser across all of their states. CR1 uses the absorbed-unit count plus the
within-design rank in residual degrees of freedom; pointwise intervals use
Student t critical values with chooser clusters minus one degrees of freedom.
Both coefficients and covariance are tested against a full dummy-variable
OLS calculation on synthetic data.

## Normalization and presentation

The payoff reference category is now **exact zero**. Its plotted value is zero
by normalization, not an estimated zero probability of kindness. Its hollow
diamond and zero-width interval are a reference marker, not evidence of
perfect precision about a substantive effect. The gap panel retains the
near-zero reference category [−25,+25).

Changing the payoff reference can shift the vertical location of the curve.
Splitting the bin also changes the specification, so payoff coefficients must
be refitted rather than obtaining extra dots by interpolation. The raw curves
and contrasts use exactly the corresponding retained FE estimation rows.

The main figures show one adjusted unrestricted-sample curve in each panel.
Payoff lines connect negative bins to other negative bins and positive bins
to other positive bins. They do not connect through the zero atom. There is
no smoothing, sigmoid fitting, monotonicity constraint, or imposed kink.

Finite bins appear only if the contrast is estimable and both the bin and the
reference satisfy the inherited support rule: ≥500 observations, ≥50 chooser
accounts switching across bins within a chooser-state unit, and ≥6 months.
Unsupported holes are not bridged. Extreme overflow bins remain in estimation
but do not have finite plotting coordinates. All bins and their counts are
reported in curves.csv, including unsupported ones.

## Near-zero contrasts and limits

near_zero_contrasts.csv reports small gain minus small loss, exact zero minus
small loss, and small gain minus exact zero, with their full chooser-clustered
covariance. Holm adjustment covers the three adjusted-model contrasts. Raw
versions are descriptive. These are exploratory finite-bin contrasts, not
local derivative discontinuities, causal price effects, or an identification
of a prospect-theory or Kőszegi–Rabin mechanism.

ZERO_AUDIT.json reports the exact-zero mass, tiny nonzero values, disagreement
between stored payoff zeros and displayed rating ties, sign disagreements,
and the old central-bin count. Nonzero values are never silently relabeled.

## Provenance and execution

Every monthly input is authenticated against the frozen main-sample report.
The prior authenticated within-chooser sorted cache is reused if available;
otherwise a sorted cache is rebuilt from the same authenticated source.
New moment and covariance passes are necessary even when the source cache
can be reused. Outputs are stored in a separate identity-specific directory.
Hashes guard checkpoints, code, source identities and transfer artifacts.
Source panels and prior result directories are not modified.

The transferable result contains only aggregate statistics, figures,
documentation and executed code. Private Parquet shards stay on the local
project volume. The production result requires POOL_SPLIT_ZERO_CURVES_OK.
