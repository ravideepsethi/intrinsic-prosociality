# Methods and interpretation

## Sample and inherited quantities

The parent is the authenticated 24-month pool/nonadjacent main panel: November 2023–October 2025, 41,534,331 opportunities, 570,091 grants. Only competitive recipient positions (evaluation ≥−100 cp) enter this exercise. No row is selected on whether its chooser ever grants. “Stable” is a research restriction on pregame rating uncertainty, not a measured age or official provisional-status restriction.

The two samples are both pregame RDs ≤75, and additionally chooser K in [11,12]. Before the local windows, their retained chooser-state FE samples must reproduce 11,114,912 and 9,263,266 rows respectively. Every local restriction recomputes chooser-state singleton removal; local sample sizes therefore differ across windows and tie specifications. Board-state comparisons share an axis, cutoff and window but may have different covariate distributions.

Payoff uses the frozen `chooser_draw_payoff_v2`, K is twice `chooser_win_premium_v2`, and relative strength is disconnected player's displayed Elo minus chooser's displayed Elo. D/K=0.5−E is computed from the frozen D and K. The rating layer is not replaced. K cutpoints remain the parent full-main-sample empirical cutpoints, with ties unbroken.

## Regression

For cutoff c and half-window h, set z=(x−c)/h. Retain |x−c|≤h. The local quadratic includes:

```
left_z           = z * 1{x<c, x is not the cutoff atom}
right_z          = z * 1{x>c, x is not the cutoff atom}
right_indicator  = 1{x>c, x is not the cutoff atom}
center_atom      = 1{|x−c|≤1e−12*max(1,h)}
left_z_squared   = z² * 1{x<c, x is not the cutoff atom}
right_z_squared  = z² * 1{x>c, x is not the cutoff atom}
```

Both the jump and derivative difference are unrestricted. Linear benchmarks omit the two quadratic terms. The left/right derivatives at c are the corresponding z coefficients divided by h. The cutoff-atom coefficient compares exact-cutoff observations with the extrapolated left limit; it is not an intercept jump. The tie-exclusion sensitivity removes exactly equal displayed ratings, using |rating gap|≤1e−12, before local singleton removal. At nonzero placebos the cutoff atom refers to that placebo value, not equal ratings.

The kernel is uniform within the declared window. No outcome-dependent bandwidth selection, shape constraint, smoothing of returned estimates, or monotonicity restriction is used. This is a conditional local-shape diagnostic, not a causal regression-kink design. Standard errors account for clustered sampling variation conditional on the specified polynomial; they are not automatically robust to approximation bias. The bandwidth and polynomial checks are consequently substantive, not cosmetic.

Absorbed effects are chooser × broad competitive board state: roughly equal [−100,+100] cp, better (100,300) cp, clearly better ≥300 cp, from the recipient's perspective. Clustering is by chooser across all of that account's states.

Nuisance controls exactly match the preceding stable run:

- Linear splines in log(1+ply), knots at 2, 5, 10, 20, 40, 80, 160 plies.
- Separate splines in log(RD/50) for both players, knots at RD 50, 75, 110, 150, 200, 300.
- Separate splines in log(volatility/0.06) for both players, knots at 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.10.
- Month and speed indicators; 50-cp board-evaluation categories from −600 through +600 with endpoint tails.
- K20 indicators based on frozen full-panel cutpoints, plus log K.

There are no additional clock, account-age, streamer, Patron, or recipient fixed-effect controls in this package. Such variables are not silently added or inferred.

The state-interacted fits multiply every local polynomial term, jump and atom by the three states. Nuisance slopes remain common. The joint null is equality of the three right-minus-left derivatives; two independent restrictions are tested. Pairwise state differences also use their joint clustered covariance.

## Declared specification grid

| Axis | Half-windows | Main reporting window |
|---|---|---|
| Normalized D/K | 0.025, 0.05, 0.10 | 0.05 |
| Draw payoff D | 0.5, 1, 2 rating points | 0.5 |
| Displayed rating gap | 25, 50, 100 rating points | 25 |

For each sample: 18 pooled fits (three axes × three windows × two polynomial degrees); five quadratic tie-exclusion fits (all normalized windows and the other axes' main windows); five quadratic state-interacted fits on those same windows; two quadratic placebo fits. Total: 30 per sample, 60 overall. The primary follow-up is the narrow-K, normalized-payoff, h=0.05 quadratic fit with ties retained.

## Support and covariance

A reported local contrast requires at least 500 retained observations on each side, at least 50 chooser accounts crossing the cutoff within a chooser-state unit, at least six months on each side, and at least five distinct non-overflow displayed-rating-gap values on each side. The atom additionally requires 500 observations, 50 within-unit atom-versus-nonatom switching choosers, and six months. Rank-based estimability is checked independently; a zero coefficient from a generalized inverse is not treated as an identified zero.

State joint and pairwise tests additionally require at least five displayed-gap values present in common on each side across the states being compared. The regression windows are identical, but neither exact matching of the distributions nor random assignment is claimed. Detailed gap support and per-side counts are exported.

The estimator uses sparse within-unit normal equations and a scaled rank-revealing eigensolve. Near-constant nuisance columns are explicitly recentered to avoid cancellation. Let N be local rows, H absorbed chooser-state units, G chooser clusters and r the rank of the within design. The finite-sample covariance factor is:

`G/(G−1) × (N−1)/(N−H−r)`.

Coefficient inference uses t(G−1). Joint tests use the corresponding cluster F approximation and explicitly fail if their covariance restrictions are singular. Neither H nor the number of observations substitutes for G.

For the zero/placebo comparison, the derivative influence scores at c=0,−0.10,+0.10 are aligned by chooser and jointly accumulated. A chooser absent from one local fit contributes zero influence there. Cross-fit covariance is the joint raw influence covariance multiplied by the geometric mean of the two CR1 factors. Contrasts use the minimum of the three local G values minus one as conservative reference degrees of freedom. Both a pairwise comparison and a joint test are reported; individual significance/non-significance comparisons are not substitutes.

## Multiple testing

The following distinct families are declared, with unavailable/unsupported tests retained as p=1:

- Primary quadratic fit: its five terms (left slope, right slope, derivative difference, jump, atom).
- Pooled zero-cutoff derivative differences: all 46 sample/axis/window/degree/tie specifications.
- Pooled zero-cutoff jumps: the corresponding 46 specifications.
- State-specific derivative differences: 30 tests (two samples × five windows × three states).
- Joint state-heterogeneity tests: 10.
- Pairwise state-heterogeneity contrasts: 30.
- Placebo comparisons: eight, comprising six scalar contrasts and two joint tests.

Holm adjustment is separate within each stated family. Raw p-values remain visible. These families do not transform the exploratory follow-up into a preregistered confirmatory design. No global “one significant result anywhere” claim is warranted.

## Figures and audit

The five figure pairs show slope robustness across degrees/windows/ties, local quadratic profiles, state-specific slope changes, placebo-cutoff slope changes, and discrete displayed-rating support. Local profiles hold nuisance regressors fixed and normalize to the model's extrapolated left limit at the cutoff; they do not display absolute kindness probabilities. Left and right fits are drawn separately, and exact-cutoff atoms are marked separately.

Before a success receipt is written, the earlier stable sample counts and all 90 earlier local-linear terms must reproduce. The code compares counts exactly and coefficients/SEs within numerical tolerance of 0.0001 percentage points plus relative tolerance 0.00001. This validates the inherited model/data link; it imposes no restrictions on the new quadratic findings.

Moment and score checkpoints are SHA-256 checked. The package identity includes source fingerprint, specification settings, dependency versions and package manifest. Inputs are read-only. Exported CSV/Parquet tables and NPZ matrices contain only aggregates; complete chooser histories remain in private Parquet shards on the external drive.
