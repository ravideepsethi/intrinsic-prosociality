# Model and numerical contract

## Main likelihood

For account i and type k, log-odds are

`alpha[k] + theta[k] * A[cell] - B[k,0] * premium/10 - B[k,1] * loss/10 + Z * eta`.

Type is integrated once outside the product over an account's observations.
The likelihood is evaluated with log-sum-exp. Analytic derivatives include type
posteriors, estimated index factors, common controls, mixture weights, and costs.

The four restrictions retain free type intercepts:

| Model | Desert slopes | Cost amplitudes |
|---|---|---|
| level | Common | Common |
| desert | Vary | Common |
| cost | Common | Vary |
| both | Vary | Vary |

Within each model, dependence among varying coefficients is unrestricted across
the finite support. No claim is made that support points represent discrete
psychological categories. Complexity and regularization grids are the same.

## Cost normalization and zero-cost cases

With the proportional-cost restriction, use

`B[k,:] = amplitude[k] * [cos(angle), sin(angle)]`,

where amplitudes are nonnegative and angle lies in [0,pi/2]. The cost direction
has unit norm, eliminating its redundant scale. Reported coefficients divide
these B values by 10 to restore original rating-point units. Let a_bar be the
account-weighted mean amplitude under the fitted population distribution:

`beta[k] = amplitude[k] / a_bar`,

`beta_kappa = a_bar * cos(angle) / 10`,

`beta_L = a_bar * sin(angle) / 10`.

Thus E_G[beta]=1. If a_bar is zero, multipliers are not reported as identified.
Small nonzero costs can still be weakly identified; inspect recovery, not merely
whether a floating-point coefficient differs from zero.

The premium-only model fixes angle at zero. No-cost omits both cost coefficients.
Separate-costs gives each type two nonnegative coefficients. Signed-costs permits
both signs, a specification check rather than an economic cost-aversion model.

K is reconstructed as twice the premium, and expected score as .5-r_G/K. These
are quantities implied by the supplied reconstructed payoff pair, not a new
rating engine or an exogenous price. The package audits r_C-r_G-premium and
requires E in [0,1]. Invalid/missing cost rows do not silently receive zero cost.

## Index and common-ordering test

The freely estimated separable index is

`A[B,P,Q] = (f[B] * g[P] * h[Q] - f[0]) / (1 - f[0])`.

The equal-board factor f[2], 11–40-ply factor g[2], and middle expected-score
factor h[2] are one. f[0]<1; other factors are nonnegative. No stage or
expected-score monotonicity is imposed. The two reference cells fix A at zero
and one. Bounds on these parameters are computational, not empirical results.
For numerical stability the optimizer uses raw-product coordinates: its internal
intercept and slope multiply f*g*h directly, then are transformed to the stated
two-anchor alpha and theta for reporting. This is the same utility function.

The free-index model estimates A in every supported nonanchor cell, maintaining
`theta[k] * A[cell]`. It relaxes separability but NOT the common-index interaction.

The type-cells model replaces that term with `effect[k,cell]`, fixing only the
zero-reference cell's effect at zero for every type. All remaining effects,
including the other reference cell, are free. This is a genuine relaxation of
the shared index. In the restricted model, the centered type-by-cell matrix is
rank at most one with a common ordering where theta>0. Singular values are
descriptive; the formal predictive comparison is type_cells versus free_index.
Noisy observed account-specific slopes are not treated as measured latent types.

Optional calibrated factors produce a nested comparison with freely estimated
board factors. The optional calibration is held fixed in bootstrap/recovery;
its source-sampling uncertainty is outside these intervals.

## Regularization and optimizer

The negative average account log likelihood is augmented with one half times
ridge times the sum of: mean squared type-by-supported-cell effects, mean
squared actual cost coefficients B, and sum of squared control coefficients.
The penalty is on identified utility contributions, not arbitrary index-factor
scales. The same penalty rule is used across the comparable specifications.
Different dimensions therefore do not receive arbitrary extra penalties merely
because a surface has been factorized differently.

Starts are seeded, dispersed, and supplemented with nested restricted-model
starts. Selected structures are refit on the full first year. Numerical bound
hits trigger a wider-bound attempt before reporting; remaining hits are visible.
Success requires a maximum projected gradient of at most 2.5e-5, not merely the
optimizer's function-tolerance flag. Each start permits at most three solver
passes of --maxiter iterations; the additional passes reset limited-memory
curvature and polish an unfinished fit. Both passes and total iterations are
reported. The main grid stops if any candidate configuration has no converged
start after the nested/bound attempts. Inspect remaining bound warnings.

## Sampling and forecasts

Accounts are selected without using grants or future activity. Original pilot
and returned construal evaluation samples are reconstructed from their exact
eligibility/hash rules and excluded. Development and evaluation accounts are
disjoint. Development-year-two outcomes do not select or estimate parameters.

Support and transformations use early development observations. Past evaluation
choices update only that account's type posterior. Forecasts are computed before
the current outcome enters that posterior. The same update is applied to every
candidate, including the level-only comparator.

Main effects are conditional on recorded active resolutions and chronology
exclusions. No API last-move timestamp is labeled a decision-onset timestamp.

## Inference

Primary comparisons use paired held-out log scores. Conditional SEs cluster the
paired score difference by evaluation account, using the ratio influence for
the opportunity-weighted mean. Equal-account gains are reported separately.
Holm adjustment is applied within the reported primary conditional comparison
family. By-state tables are exploratory diagnostics, not additional independent
confirmatory discoveries.

The bootstrap independently resamples development and evaluation accounts.
Development counts weight the entire account likelihood. Every model's index
and population coefficients are refit and its evaluation posterior is filtered
again; evaluation multiplicities weight paired scores. At least 100 completed
paired refits are required for percentile intervals. Failure rates and remaining
numerical bounds must accompany those intervals. Models/support sizes/ridge,
source preprocessing and optional external calibration are frozen. This is not
an interior chi-square LR test and does not correct specification search.

## Recovery

All selected observed histories and covariates are retained. New persistent
types and binary choices are simulated independently for development and
evaluation accounts. Generators cover the four main fitted restrictions,
type-specific cells, zero cost, and nearly coincident types. Recovery refits do
not start at the generating parameter vector. Fixed structures are scored
sequentially. Parameter RMSE uses an optimal permutation of labels where support
sizes match; no individual-type classification is treated as certain.

Recovery under fitted generators can itself be weak if the fitted generators
are nearly indistinguishable. Report generating expected grants, sample sizes,
parameter errors, failures, and score distributions. Recovery does not validate
the exclusion restrictions or uniqueness outside the maintained functional class.

## Perception stage

The exact probability is a sum of logistic probabilities across five board bins,
weighted by normal-CDF differences. Stable survival-function differences are
used for positive-tail intervals. Zero variance has a separately defined exact
observed-bin probability. Exact boundaries are excluded from the matched
perception sample, avoiding spurious gains from the discontinuous zero-variance
boundary convention. Numeric raw scores are required; mates/censored codes are
not interpreted as ordinary distances. Raw-score bin membership, not capped
numeric distance, defines the matched accurate comparator.

Both accurate_tiers and noisy_tiers permit prior type probabilities to differ
by the first observed pregame rating tier and include the common chooser-rating
control. That initial group remains fixed; noise depends on current rating tier.
The normal-error variances are not forced to decline with rating.

The accurate_common and noisy_common restrictions use common prior type weights
and omit the direct chooser-rating control. Noisy_tiers versus noisy_common
asks whether this restrictive perception explanation is sufficient within the
specified model. It does not identify perception from tier means alone.

Counterfactual decomposition holds type weights and the reference distribution
of all other regressors fixed while substituting each tier's fitted variance:

`J = E[Lambda(m + theta*Ahat)] - Lambda(m + theta*E[Ahat])`,

`M = Lambda(m + theta*E[Ahat]) - Lambda(m + theta*Atrue)`.

J is nonnegative if all attainable utility indices lie below the logistic
inflection point. M can have either sign. Components are computed by type and
opportunity before averaging. A mean-zero board error is not a mean-preserving
error in a nonlinear index. The decomposition is not independent validation.

Perception recovery adds accurate, noisy, restricted-common, and weak-noise
generators. Its bootstrap uses the same refit protocol, on the separately matched
sample. Simulated sigma recovery does not prove the real-data exclusion.
