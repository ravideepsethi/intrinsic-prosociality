# Specification and interpretation

This is an exploratory computational implementation of the revised model.
The code and named comparisons are frozen before its evaluation output is
opened, but the motivating pilot and aggregate results elsewhere have
already been examined. Account disjointness is not preregistration.

## Common switching family

For persistent support point j and latent state e:

`P(grant | e,s,j) = logistic(ell_j + alpha_e + B(s) beta_e)`

`P(E_t=1 | E_(t-1)=e,j) = logistic(H_t kappa_e + gamma_j)`

`P(E_1=1 | j) = logistic(zeta0 + zeta_ell ell_j + gamma_j)`

The persistent pair `(ell_j,gamma_j)` has freely estimated joint support and
weights. It is drawn once per account, outside the sequence product. We
anchor the first support point at zero internally; this is equivalent to
shifting the intercepts and initial-state constant to obtain mean-zero
random effects. Support labels are exchangeable and are not named moral
types. `alpha_1 = alpha_0 + softplus(delta)` orders the states at the fixed
reference configuration. Under the gate this additionally orients the flat
state as the lower-reference-propensity state. It does not order emissions
everywhere on the board.

- Gate: `beta_0 = 0`.
- Willingness: `beta_0 = beta_1`.
- Unrestricted: both free.
- Gate-cost: lower-state loss magnitude, positive draw payoff, and win premium
  may enter, while its other coefficients remain zero.

The joint finite-support grid is the same across switching candidates.
Optimiser bounds are numerical restrictions and are reported. A common weak
ridge penalises the two emission coefficient vectors symmetrically; it
does not create valid mixture likelihood-ratio chi-square tests.

`B(s)` is frozen in `features.py`: five board bins by four stage categories
(exactly ply 2, other <=10, 11–40, >40), a competitive contrast, rating and
payoff terms, RDs, volatilities, clocks, speed, colour and month-of-year.
No year-two intercept or outcome-derived category is fitted. Missing
quantities receive fixed reference values with missingness indicators.
State coefficients are conditional associations; reconstructed rating
payoffs are not exogenous treatment prices.

`H_t` contains an intercept, well-separated observed receipt, log elapsed
time, log observed receipt opportunities, and an ambiguous-receipt indicator.
Receipt may change both transition rows in all four models. The chain moves
once per retained recorded chooser opportunity. It does not infer a
continuous-time law or model opportunity arrival.

## Recorded chronology

The timing audit excludes missing/invalid timestamps, correspondence, ties,
and both sides of overlapping or insufficiently separated recorded game
intervals. Start must precede the API last-move proxy. Retained intervals
use strict inequalities; no tie is resolved by assigning a potentially
future outcome as an earlier receipt. The default separation guard is 300
seconds. This reduces ambiguity but **does not establish the true decision
time**. Eligibility can depend on recorded subsequent game starts and hence
on future participation; the predictive estimand is conditional on retained
histories, not a causal effect on all opportunities.

Recipient events come from the full certified main panel, not just sampled
chooser histories. Each recorded event can enter at most one open chooser
interval. A qualifying received draw starts after the previous retained
chooser anchor plus the guard and has its last-move proxy plus the guard
before the current game starts. Other recorded grants in the interval are
flagged as ambiguous rather than labelled absent. Counts describe this
observed main-panel exposure universe. Excluded-source or unobserved acts
may still affect behaviour; zero qualifying receipts does not mean no
kindness was ever received.

## Selection and forecasts

Original pilot eligibility and MD5 order are reproduced from first-year
competitive/clearly-worse opportunities. Development accounts come from that
set; evaluation excludes all 100,000 original pilot accounts. Neither cohort
requires second-year activity or giving. Accounts with no later opportunity
remain in cohort reports.

The original pilot exclusion reproduces its archive-month definition exactly.
All new prior-grant classifications and chronological model windows instead
use recorded anchor timestamps. An October-archived game with a November
anchor therefore cannot enter first-year prior giving. Histories used for
classification include all main-panel acts within that recorded time window,
including those not retained in the switching chronology.

Development observations before August 2024 fit candidate complexities.
August–October 2024 sequential forecasts choose complexity within each
family. Population parameters are then refitted on the whole first year.
Evaluation accounts' first-year histories update individual type/state
beliefs but never population parameters. Each second-year outcome is scored
before it updates beliefs for the next forecast, in both dynamic and static
models. The joint log score is the sum of these sequential log scores.

The main score uses observed second-year opportunities. Equal-account
per-opportunity gains, regional scores, Brier loss, calibration, and richer
first-year-history groups are also reported. Conditional score SEs cluster
on account and condition on all fitted parameters. Four designated overall
predictive comparisons have a separate Holm adjustment; subgroup p-values
are descriptive diagnostics. A winning flat-state model is not proof of
psychological recognition; a tie leaves the restrictions unresolved.

Static comparators have finite intercept support, optionally finite
competitive-response heterogeneity. The continuous comparator has jointly
normal intercept and competitive slope, with unrestricted Cholesky
correlation, integrated by product Gauss–Hermite quadrature. The normal grid
is a numerical approximation. A finite-mixture advantage over it rejects
neither every continuous distribution nor a one-dimensional utility model
with nonlinear choice thresholds. More quadrature nodes and richer support
are available as explicit sensitivity runs.

## Refit and recovery

The refit bootstrap resamples development accounts through multinomial
likelihood weights and independently resamples evaluation accounts. It
refits each switching candidate at its frozen complexity from two starting
points, then refilters and scores all evaluation histories. Failed
replications are counted and excluded from the reported refit SE, with
requested/converged totals visible. Percentile intervals require 100
converged draws. This does not include prior model-search uncertainty or all
cross-account/calendar dependence. No chi-square mixture LR test is used.

Recovery simulations hold observed covariate and opportunity patterns fixed,
draw persistent types once, and generate hidden states and outcomes under
gate, willingness, and nearly collapsed states. Competing fits are compared
on account-disjoint simulated histories. Reference-intercept separation and
receipt-entry recovery are reported. This is a limited design diagnostic;
it cannot establish identification or resolve endogenous recorded histories.

## Receipt and external measurement

The switching receipt surface compares `R=0` and `R=1` with the same
pre-interval type/state posterior and other transition inputs. It averages
the joint product, rather than multiplying average engagement and emission
differences. It is reported only in intervals with at least one separated
receipt opportunity and no ambiguous recorded grants. It remains a
model-input comparison, not a causal intervention.

The receipt-IV module authenticates the exact reviewed 2,682,330-row
90-day-spaced cohort and reproduces its next-competitive-choice event,
outcome, coefficient, and covariance before publishing extensions. Future
games must start after the exposure anchor, occur within the complete
90-day horizon, and face someone other than the original giver. Complete
window nonreachers have zero event counts; administrative censoring is not
coded as zero.

Prior-behaviour groups use main-panel choices strictly before exposure game
start. This history is left-truncated and excludes non-main sources. Known
account age uses the selected certified profile snapshot; missing age is not
newness. Subgroup IV fits include subgroup controls and first stages. The
prior-granter versus prior-nongranter contrast uses cross-group covariance
under the same shared-account OR date dependence rule. Weak-instrument
null-moment Anderson–Rubin sets are retained for individual IV coefficients;
subgroup-difference and horizon contrasts are asymptotic Wald diagnostics,
not weak-IV-robust tests.

Effects on grant counts and opportunity counts are reported separately for
days 1–7, 8–30, and 31–90. Per-day early/late contrasts use their joint
covariance. The windows contain subsequent receipts and own-action
feedback; they do not isolate a single impulse. An apparent plateau is not
evidence of permanent conversion. Receipt by later board state on the
marginal log-odds scale is not assigned a zero null under willingness.

The Patron exercise trains a ridge-logit prediction on development accounts
with returned profiles and evaluates on separate accounts in that selected
snapshot. It compares observed first-year history with the same history plus
first-year latent posterior features. It does not recover acquisition
probabilities, backdate a badge, infer adoption, or claim an off-platform
prosocial trait. Missing and unreturned profiles remain missing.

There are no action-onset/click timestamps or data on time extensions,
resignations, and draw offers in this opportunity panel. Their tests need
additional measurements; the report explicitly marks that limitation.

## Implementation references

- The revised `section_construal_v4.tex` supplied with the preceding model edit.
- Netzer, Lattin and Srinivasan (2008), HMM precedent:
  https://pubsonline.informs.org/doi/10.1287/mksc.1070.0294
- SciPy optimisation interface:
  https://docs.scipy.org/doc/scipy/reference/optimize.minimize-lbfgsb.html
- Numba installation and compatibility:
  https://numba.readthedocs.io/en/stable/user/installing.html

Sample authentication and IV numerical routines are carried from the
previously delivered packages; `CODE_PROVENANCE.json` records their source
hashes. This package's code manifest records the exact executable versions.
