# Kindness price-elasticity exploratory analysis plan v1.0.2

Date frozen: 2026-08-25, before this module reads new production elasticity outcomes.

## Pre-outcome recovery amendments

v1.0.0 failed closed during construction of the first private Parquet and before
any production regression was estimated. It exposed a lossy chooser-key cast,
an incorrect calendar-window anchor, and a nullable hash expression. v1.0.1
repaired the key and fingerprint, then also failed closed before regression.
Its exact-key scan reproduced every full-panel certified total and showed that
two residual anchors inherited from the malformed v1.0.0 cache were wrong: the
current first temporal half has 8,575,710 fair rows, and the physical fair source
has no nonpositive premium. v1.0.2 freezes those source facts, adds an independent
physical-source preflight, and leaves the declared model family unchanged. The
reconciliations are packaged in
`kindness_price_elasticity_v1_0_1_preoutcome_recovery.md` and
`kindness_price_elasticity_v1_0_2_preoutcome_recovery.md`.

## Status and scope

Every new estimate in this module is exploratory (`X`) and associational. The module is not part of the Campaign 1 confirmatory Holm family. It uses the already certified 24-month Stage07 panel and does not alter any earlier result, plan, chronology, or private checkpoint.

No result is gated on sign, statistical significance, or whether it helps the paper. Every requested model is either estimated or retained with its exact support/numerical failure. Nothing is silently deferred. Analyses that cannot be defined from the frozen authority are recorded as attempted-unestimable, with the reason.

## Economic objects

- Quantity: the probability that a fair-state timeout opportunity ends in a kind draw.
- Economic price: `chooser_win_premium_v2`, the reconstructed rating-point gain the chooser forgoes by granting a draw rather than claiming the win. It is strictly positive on the authenticated exact-key fair source.
- Reference location: `chooser_draw_payoff_v2`, the change in the chooser's rating from a draw relative to the pre-game rating. It is not the economic opportunity cost. It is conditioned on because the paper documents a strong reference-dependent response to it.

The primary estimand is

`epsilon = [d Pr(kind draw) / d log(forgone-win premium)] / Pr(kind draw)`.

For the linear-probability log-price model, the log-price coefficient is a semi-elasticity in probability units; dividing it by the sample kind-draw probability produces the point elasticity. In level-price models, the slope is multiplied by the sample mean or median price before dividing by the sample probability. Confidence intervals use the delta scaling while treating the observed sample probability and price scale as fixed descriptive denominators.

## Population and authority

The main population is every certified fair-state observation (`fair_competitive`) in Stage07, expected to contain 17,328,130 opportunities, 487,170 kind draws, and 2,685,525 choosers from November 2023 through October 2025. The Stage07 success receipt and all 24 physical monthly Parquets are authenticated before estimation. The exact physical fair authority has zero nonpositive premiums, so level- and log-price estimators use the same 17,328,130 rows. No value is imputed, clipped, or altered.

Before constructing the chooser dimension, the module independently requires the physical fair source to reproduce its total rows, distinct game IDs, kind draws, chooser identities, null-key counts, price validity, first-half rows, first-half choosers, and strictly positive minimum price. The exact-key joined cache must then reproduce the same marginals independently.

The row-level analysis cache is private, chooser-sorted, ZSTD-compressed Parquet. Price and reference quantile edges are constructed without using the kindness outcome. All public outputs are aggregates; the collector refuses to package Parquet files.

## Validation before interpretation

1. Reproduce the certified Stage08 24-month full-fair piecewise model exactly: positive draw-payoff slope, negative draw-payoff slope, zero-reference indicator, and level win-premium, with chooser fixed effects and chooser-clustered standard errors. The three published Stage08 reference coefficients must match within `5e-10` percentage points.
2. Estimate a bridge model on the current authority's first temporal half, November 2023 through October 2024, with the Appendix A11 equation (positive payoff, negative payoff, level premium, chooser fixed effects). This current window has 8,575,710 fair rows and 1,744,924 choosers. The draft's displayed A11 coefficients came from the predecessor 10k-node October-2023--September-2024 window with 8,648,684 fair rows. Their difference is reported as a nonidentical-engine, nonidentical-calendar-window comparison and is not treated as a pass/fail reproduction.

New elasticities are not interpreted unless validation step 1 passes.

## Primary model

The primary exploratory model is a linear-probability model on all fair-state rows with:

- log forgone-win premium as the exposure;
- chooser fixed effects;
- 50 outcome-blind empirical-quantile fixed effects for draw payoff;
- flexible current-state controls: quadratic engine evaluation, chooser and opponent rating deviation, log chooser and opponent clock with missingness indicators, tournament status, quadratic month trend, and speed indicators;
- chooser-clustered standard errors.

The fixed-effect projection is exact. The large chooser effect and the small draw-payoff-bin effect are absorbed with a Schur-complement projection and explicit orthogonality checks.

## Full retained model family

The module attempts and retains:

1. Level price with chooser fixed effects and piecewise reference controls.
2. Log price with chooser fixed effects and no reference control.
3. Log price with piecewise reference controls.
4. Log price with cubic reference controls.
5. Log price with 20 draw-payoff-bin fixed effects.
6. Log price with 50 draw-payoff-bin fixed effects.
7. The fully adjusted primary 50-bin model.
8. An adjusted level-price 50-bin model, with elasticities at mean and median price.
9. A 1st–99th percentile trimmed adjusted log-price model.
10. A 1st–99th percentile winsorized adjusted log-price model.
11. A pooled adjusted model to expose between-chooser versus within-chooser differences.
12. A conditional chooser-fixed-effect Poisson QMLE with log link. Its log-price coefficient is a direct elasticity. The conditional likelihood necessarily excludes all-zero chooser groups, and the changed support is reported.
13. A 20-bin nonparametric price curve with chooser fixed effects and piecewise reference controls, plus all adjacent midpoint arc elasticities for raw and adjusted rates.
14. Heterogeneity models by all four rating bands, all six speed categories, five engine-evaluation bands, both temporal halves, both rating-certainty states, all four chooser-activity quartiles, and three lagged-kindness strata. Low-support and numerical failures remain in the result bundle.

Subgroup models use the same full-sample, outcome-blind 20-bin draw-payoff cut points. The lagged-kindness strata use only kindness observed before the current opportunity and are explicitly descriptive rather than pretreatment types.

## Inference, multiplicity, and interpretation

Linear models use chooser-clustered sandwich covariance. The conditional Poisson model uses chooser-clustered sandwich covariance for the conditional score. Two-sided normal-reference p-values and 95% confidence intervals are reported without significance gating.

No multiplicity correction is imposed because this is a fully disclosed exploratory map rather than a confirmatory family. The model inventory and every failed attempt are published so readers can see the complete search.

The output may be described only as a functional-form-sensitive conditional elasticity of kind-draw probability with respect to the forgone rating premium. It is not a causal demand elasticity. The premium is a deterministic nonlinear function of chooser RD, opponent RD, and expected score; these rating states and matchmaking are not randomly assigned and can proxy activity, provisional status, tenure, rustiness, and opponent selection. A positive coefficient is reported as a conditionally upward-sloping association, not rationalized away. A negative coefficient is described as conditionally consistent with downward-sloping demand, not proof of it. The nominal primary model is one declared cell in a fully retained stability family, not a privileged structural estimate.

## Explicitly attempted but currently unestimable objects

- The November 18, 2025 color-advantage rule change cannot be estimated inside this certified Stage07 authority because it ends in October 2025. A separate Aug--Dec 2025 branch already estimated the reference-location design; it is neither concealed nor reserved by this module.
- Fixed-RD and local-RD predecessor elasticities cannot be re-estimated from Stage07 because those row-level predecessor price fields are not members of the certified schema.
- A causal elasticity is not identified without exogenous price variation.
- A dollar-price elasticity is undefined because there is no defensible cardinal exchange rate from rating points to money.

These are recorded as attempted-unestimable in the output; none is reserved as an undisclosed future analysis.

## Computation

Expected runtime is approximately 1–4 hours, with up to 8 hours allowed for unusual external-drive contention. DuckDB uses eight workers. Numerical linear algebra uses four threads and runs memory-bound HDFE steps serially to avoid duplicating multi-gigabyte arrays. Every large checkpoint is compressed Parquet and authenticated for safe resume.
