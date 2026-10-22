# Targeted RD influence audit

Version 1.0.0, September 26, 2026. This is a sensitivity and influence diagnostic, not a newly identified mechanism decomposition.

## Frozen inputs

Read the completed `mechanism_separation_v100_PRIVATE` cache. The authenticated reviewed result is `MECHANISM_RESULT_20260926T170948877768Z.zip`, SHA-256 `ee937afd0547b607a5848efcaca16279bfe0569356c013ec4d9035a274d216e6`. The original package manifest SHA-256 is pinned in `authority/reference.json`.

The original analysis Parquets contain the accepted regularity, pool/adjacency, state, gap and stage screens. The audit preserves those flags and the November 2023–October 2025 panel. It verifies sample counts against the reviewed result and authenticates each monthly Parquet against its original receipt. Full-fit coefficients and estimation counts are checked against the returned package. Each original monthly held-out likelihood must reproduce the returned score before its comparison is accepted.

## Samples and support

The original cohort uses `regular` and the selected board state. The capped cohort adds `rd <= 110 AND opp_rd <= 110`. Primary regularity means at least 100 prior same-speed rated starts, at least one year of observed same-speed history and activity in each of the previous four seven-day windows, as encoded by the original producer. It did **not** impose an RD floor or RD cap. The sensitivity here does not change activity requirements.

Roughly-equal positions are primary; clearly-losing positions are secondary. The original certified definitions and stage restriction remain in the cache. Support tables report monthly counts, RD cross-cells, gap bins, payoff tails, and account retention. Near-tie normalization support uses repeated choosers within that same near-tie window, excluding singleton accounts. Original cost-table coefficients are not refitted here.

After restricting rows, conditional logit retains only accounts with both outcomes in the selected fitting period. Removal therefore changes both histories and the set of identifying accounts. Account-retention tables quantify this. The comparison is not a randomized or isolated within-person change in stakes.

## Models and fitting

The seven candidates, transformations, controls, sign restrictions, exact chooser conditional likelihood, optimizer checks, and training-only curvature search are copied from the original analysis: cost; loss aversion; curved utility; draw framing; displayed-gap spline; gap plus loss; gap plus framing. The original full and two forward-fold fits are reused. Only capped fits are newly estimated.

Full fits export convergence diagnostics and covariance matrices. Coefficient tables explicitly mark constrained boundaries. Ordinary Wald intervals are suppressed for all coefficients when any constrained coefficient is on a boundary, and for unidentified directions. Raw covariance output is retained for audit but does not turn a boundary estimate into a regular Wald test.

Separate fits relax all sign constraints in the cost, framing and gap models for roughly-equal positions and in the gap model for losing positions. They diagnose constrained-zero estimates and signed gap responses. They are excluded from the seven-candidate comparison. A constrained zero alone does not establish the sign of an unrestricted estimate.

## Validation

Fold 0 trains through October 2024 and evaluates November 2024–April 2025. Fold 1 trains through April 2025 and evaluates May–October 2025. The conditional validation group is chooser × month. The group total of grants is conditioned on; accounts without outcome variation in that validation month contribute zero log likelihood.

Each candidate is scored three ways:

| Training fit | Validation rows | Purpose |
|---|---|---|
| Original | Original | Reproduce the reviewed result |
| Original | Both RDs ≤110 | Change validation support only |
| Both RDs ≤110 | The identical RD≤110 rows and groups | Evaluate the effect of refitting on common support |

Restricted validation groups are constructed once and used for both training fits. They are reconditioned on their restricted grant totals, so original-test and capped-test likelihood levels are not directly comparable. Compare model rankings within a validation sample; compare training fits only on the identical capped validation rows.

Pairwise differences use 12 monthly conditional log scores. The retained set uses the prior descriptive rule: a candidate remains compatible if its average shortfall from the best candidate is no more than twice the monthly standard error. Pairwise intervals use 2,000 resamples of those 12 months, with a fixed seed. These are descriptive summaries, not dependence-robust or familywise tests of model truth. They do not replace the original recoverability simulation or solve its nesting/decision-rule limitations. No new recoverability simulation is performed.

Conditional gap calibration compares observed grants with conditional inclusion probabilities on identical informative held-out chooser-month rows. Predicted counts sum to the observed total within each group by construction. This diagnoses within-group allocation across gaps, not marginal grant-rate forecasts or an out-of-sample baseline probability.

## RD score diagnostics

For full-history conditional fits, let `r = y - E[y | group total, X]` and `Z = X - within-chooser mean(X)`. The exact score sums to `sum(Z * r) = sum(X * r)` because group residuals sum to zero. For each substantive regressor, report signed and absolute row-score sums and `sum(Z²)` across four RD classes: both ≤110, own only >110, opponent only >110, both >110.

These figures show where fitted estimating-equation contributions and centered regressor variation lie. They are not causal shares, a decomposition of adjusted regression weights, or Fisher-information/leverage shares. Absolute contributions may be large and cancel. The refitting comparison is the direct sensitivity exercise.

## Profiles and reporting corrections

Select up to 100,000 capped eligible rows using the smallest deterministic game-ID hashes, without using the outcome. Both original and capped fits are evaluated on exactly these rows. Recompute both players' rating consequences for each counterfactual displayed gap under the original certified calculator. Report average conditional-index contrasts relative to gap zero. These are index units, not percentage points. Fixing all other rows while changing the gap is a fitted-model contrast and may cross thin joint support; gap support is reported alongside it.

The inherited M2 figure is reproduced with coincident curves combined in the legend; no values are offset. Its percentage-point profiles used an additional baseline calibration and must not be directly equated with the full-sample fixed-effects LPM coefficients. Common-index profiles and held-out conditional calibration avoid that mismatch.

The four original cost tables summed an outcome multiplied by 100 while labeling the sum as a grant count. This audit replaces those counts from the original support tables after verifying the exact factor and matching row counts. Coefficients are unchanged. The inherited IQR/elasticity normalizations included eligible singleton accounts; these are labeled as inherited, and the new near-tie support separately reports the repeated-chooser frame. The corrected tables do not create a causal cost bound.

## Operational limits

No upstream history, identity, Glicko, API or engine stage is imported. No returning-player design, historical information-cue test, policy event study, power recalculation, IV estimate or mechanism shares are run. Original caches are opened read only, with a shared source-run lock if available. Audit files use a separate directory, immutable input identity and restart receipts. Returned results omit account-level rows and switcher-ID arrays. Aggregate reports may contain local file paths used for provenance.

Results can support a statement about how the specified fitted model ranking responds to removing high-RD observations. They cannot alone establish deference, establish awareness of fractional rating incentives, or rule out every payoff-based model.
