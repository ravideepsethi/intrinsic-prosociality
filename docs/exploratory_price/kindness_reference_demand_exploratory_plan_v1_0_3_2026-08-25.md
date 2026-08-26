# Kindness reference-dependent demand plan v1.0.3

Frozen: 2026-08-25, after v1.0.2 outcomes and before v1.0.3 production
outcomes.

## 1. Question and objects

Quantity is the probability that a certified fair-state timeout opportunity
ends in a kind draw.

The central varying margin is `chooser_draw_payoff_v2`, denoted `D`: the rating
consequence of granting a draw relative to the chooser's pre-game rating.
`D < 0` is a rating loss, `D = 0` is the reference, and `D > 0` is a rating gain.

`chooser_win_premium_v2` is the true opportunity cost: the rating gain forgone
by drawing instead of claiming the timeout win. It remains a control and the
secondary estimand of v1.0.2. The paper's central empirical statement is that
behavior is organized around `D = 0` conditional on that premium.

No single global log elasticity in `D` is defined. The headline output is a
reference-dependent demand schedule. The closest scalar conventional price
elasticity is estimated only on `D < 0`, using the strictly positive loss
magnitude `L = -D`.

## 2. Status and retention

All new estimates are exploratory (`X`), associational, outside the Campaign 1
Holm family, and retained regardless of sign, magnitude, significance, or
usefulness to the paper. Certified reproductions are validation (`V`). Every
attempt is checkpointed and appears as estimated or failed-retained.

The post-outcome timing and conceptual correction are disclosed in
`kindness_reference_demand_v1_0_3_postoutcome_correction.md`.

## 3. Authority and computation

The population is the certified Stage07 fair-state panel:

- 17,328,130 opportunities;
- 487,170 kind draws;
- 2,685,525 choosers;
- November 2023 through October 2025.

The Stage07 receipt and all 24 monthly Parquets are physically authenticated.
The module first tries to authenticate the successful v1.0.2 private model
Parquet read-only, including its configuration, receipts, hashes, schema, row
count, outcome count, chooser count, row IDs, and row fingerprints. It never
writes to that state. If the cache is absent, it builds a separate v1.0.3
ZSTD-compressed Parquet using the exact-key v1.0.2 cache builder and the same
certified Stage07 inputs.

DuckDB uses eight workers. Linear algebra uses four threads. Public outputs are
aggregate JSON/CSV/text only; the collector fails if any Parquet enters the
upload bundle.

## 4. Validation gate

Before interpreting new estimates, reproduce the certified full-24-month
Stage08 piecewise model exactly:

`kind = chooser FE + beta_plus max(D,0) + beta_minus max(-D,0)`
`       + tau 1[D>=0] + gamma win premium + error`.

The following three coefficients must match the certified authority within
`5e-10` percentage points:

- favorable-side slope;
- loss-magnitude slope; and
- nonnegative indicator.

The indicator in this full-range model is a functional-form component, not a
clean causal or intercept discontinuity.

## 5. Signed reference-demand schedule

Estimate the full-range piecewise equation with chooser fixed effects under:

1. 20 outcome-blind premium-quantile fixed effects (preferred schedule);
2. linear premium;
3. log premium;
4. cubic log-premium control; and
5. premium-bin fixed effects plus engine, RD, clock, tournament, month, and
   speed controls.

Repeat the piecewise model within symmetric `|D|` windows of 0.5, 1, 2, 4, and
6 rating points with both linear-premium and premium-bin controls.

## 6. Zero-reference contrasts and local shape

For symmetric windows `w` in {0.5, 1, 2, 4, 6}, estimate the coefficient on
`1[D >= 0]` with chooser fixed effects using:

- a linear premium control, matching the paper's bridge specification; and
- 20 premium-quantile fixed effects.

Report a donut grid using `d` in {0.1, 0.25, 0.5, 1, 2, 4} whenever `0 < d < w`,
retaining rows with `d <= |D| <= w`. Donut models use chooser fixed effects and
the level premium.

Estimate uniform-kernel local polynomial descriptions of orders one and two
within windows 0.25, 0.5, 1, 2, and 4. These distinguish local slopes from the
intercept component but are descriptive, not causal RDD estimates.

Estimate placebo cutoff contrasts at {-6, -4, -2, -1, 0, 1, 2, 4, 6}, each in
a symmetric 0.5-point window, with chooser fixed effects and level premium.

## 7. Loss-side elasticity

On strictly negative draw-payoff rows define `L = -D > 0`. The preferred scalar
companion model is:

`kind = chooser FE + 20 premium-bin FE + beta log(L) + error`.

The mean-scaled LPM elasticity is `beta / mean(kind)` on that loss-side sample.
Report chooser-clustered standard errors and 95 percent intervals.

Retain sensitivities with:

- linear premium;
- log premium;
- cubic log-premium;
- premium-bin fixed effects plus current-state controls;
- level `L` rather than log `L`;
- 0.5--99.5 and 1--99 percentile loss-magnitude trims;
- 0.5--99.5 and 1--99 percentile loss-magnitude winsorization; and
- conditional chooser-fixed-effect Poisson QMLE with log `L`, log premium, and
  quadratic evaluation controls.

From the level-loss slope, report mean-scaled local elasticities at the loss
magnitude's 10th, 25th, 50th, 75th, and 90th percentiles. These use the observed
loss-side mean kindness rate as the descriptive quantity denominator.

## 8. Favorable-side response

On `D > 0`, repeat log-magnitude, level-magnitude, trimmed, winsorized, and
conditional-Poisson models. These are called rating-gain responsiveness
measures, not price elasticities.

## 9. Nonparametric schedule

Use predetermined signed bands with boundaries:

`[-inf,-6,-4,-2,-1,-0.5,-0.25,-0.1,0,0.1,0.25,0.5,1,2,4,6,+inf]`.

Estimate band indicators with chooser fixed effects and 20 premium-bin fixed
effects, omitting `[-0.1,0)` as the reference. Report raw and adjusted rates,
support, and effects. Report adjacent midpoint arc elasticities separately on
the loss side and gain-responsiveness arcs on the favorable side. Report the
adjacent-bin zero contrast, but mark elasticity at zero undefined.

## 10. Heterogeneity

Estimate loss-side log elasticities, with chooser fixed effects and level
premium, across every declared level of:

- four rating bands;
- six speed categories;
- five evaluation bands;
- two temporal halves;
- two rating-certainty groups;
- four activity quartiles; and
- three lagged-kindness strata.

Low support, no residual variation, singularity, and numerical failures remain
in the model-attempt ledger.

## 11. Support and balance diagnostics

Before outcome models, freeze counts and quantiles for negative, zero, and
positive draw payoff. Within each symmetric reference window, report left/right
means and standardized differences for premium, evaluation, ratings, rating
deviations, clocks, tournament, month, and speed. These are diagnostics, not a
claim that the cutoff is as-if randomly assigned.

## 12. Interpretation boundaries

The permitted claims are reduced-form and descriptive:

- kindness follows a signed, reference-dependent schedule;
- on the loss side, responsiveness can be summarized as a conventional
  conditional elasticity in loss magnitude;
- at zero, proportional elasticity is undefined; and
- the premium elasticity remains a separate opportunity-cost result.

The module does not identify causal price effects, loss aversion, a structural
value function, or a dollar elasticity. Draw payoff and relative rating are the
same ordering variable under the Glicko update, so the reference-loss and
near-peer readings cannot be separated within this design.

## 13. Runtime

Expected production runtime is approximately 20--60 minutes when the
authenticated v1.0.2 private Parquet is reusable. Allow up to two hours if the
cache must be rebuilt or the external drive is contended. Every model is
checkpointed and the exact package can be relaunched safely.
