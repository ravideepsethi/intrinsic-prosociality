# Mechanism separation, version 1.0.0

Specification frozen September 26, 2026. This code release contains no estimates
from the user's production data. The synthetic tests are software validation.

## Sample and provenance

The primary source is the existing certified 41,534,331-row pool/observed-
nonadjacency panel, November 2023–October 2025. The pinned predicate is
`source='pool' AND previous_classification_status='not_mutually_adjacent_observed'`.
It is a preceding-observed-game screen, not certification of every literal
immediate rematch. Existing rows, outcome definitions, engine evaluations,
rating states, and payoff fields are retained.

Screen to ply >10, gap in [-575,575), and either roughly equal positions
[-100,100) centipawns or clearly losing positions <=-300, from the disconnected
player's perspective. Account eligibility is evaluated separately before each
focal game. The primary regularity rule requires >=100 prior observed same-speed
rated starts, >=365 days since the first observed same-speed start, and activity
in all four preceding exact seven-day intervals. The second tier requires the
first two conditions, own RD <=110, and inactivity <90 days. It is a sensitivity,
not an extra source of exogenous stakes. No long-return window is used.

The authenticated chronology supplies game starts, not authenticated completion
times. This release therefore explicitly defines experience as prior observed
rated-game starts and inactivity as time since the last such start. These fields
are not called completed-game counts, account age, or lifetime counts. Unknown-
speed early records are not retrospectively assigned a speed. The first observed
same-speed game establishes a lower bound on history length. A long record is
enough to establish one year's history, but a short observed record need not
establish a new account.

Focal games are reconciled to chronology IDs, player IDs and timestamps. API
starts must be within one second of chronology starts. History anchors use the
matched chronology time, so a whole-second PGN time preceding its API timestamp
by a fraction of a second cannot make the focal game count as prior. All tied
starts at the anchor are excluded. Weekly intervals include their lower boundary
and exclude their upper boundary. Self-player chronology records are excluded.

The history extraction is reusable and performs no Glicko update. Historical
months collapse to per-user counts/first/last start. The focal and preceding
month supply exact recent timestamps. Opponent history uses the same definition.
The supplied chronology inventory pins paths, sizes and row counts; the run
also records actual complete-file SHA256 values. It does not claim that a newly
computed hash independently authenticates a previously unpinned byte sequence.

## Payoffs and support

The vectorized calculator reproduces the certified anchored novol/noreg
convention, including opponent RD attenuation and posterior precision. Every
prepared opportunity is checked against both chooser payoffs and both players'
premiums. A mismatch >1e-6 rating points stops preparation.

The support output precedes estimation. It contains monthly activity attrition,
opportunities/grants/choosers, actual premium distributions, own-RD-floor shares,
opponent high-RD shares, and mechanical premium-versus-gap curves standardized
over all primary regular rows. Own RD at its floor is never labeled global
minimum stakes. High opponent-RD payoff errors remain a reconstruction concern.

Near displayed ties, report raw, chooser-demeaned and control-residualized
correlations of the two premiums. Any absolute correlation >0.9 blocks separate
stake coefficients. Passing that rule is insufficient: both stakes must retain
>=0.01 point residual SD after conditioning on the other stake, controls,
chooser effects and an opponent-RD cubic; within-chooser own-RD SD must exceed
0.01. At least 100 choosers and 100 grants are required. These are operational
support screens, not identification theorems.

The opponent-RD variance diagnostic is the incremental variance explained by an
opponent-RD cubic after chooser/control residualization. It is a descriptive
projection, not a randomized-assignment variance decomposition. The never-
granter share is simple within-chooser premium-squared weight, not a decomposition
of the adjusted regression.

## Estimation and model comparison

Controls are calendar month, speed, stage bands (11–20/21–40/41–80/81+), a cubic
in evaluation capped at +/-600 centipawns, both log(1+clock) values with missing
indicators, log(1+observed history duration), log(1+prior starts),
log(1+inactivity days), log(1+opponent prior starts), and chooser rating/400.
Recorded same-speed history duration is used explicitly; no selected current-
profile snapshot is used to silently impose an account-age complete-case sample.

Primary comparisons use exact conditional logit with chooser intercepts
conditioned out. A stable log-domain dynamic program computes the likelihood
and analytic score; reverse differentiation computes inclusion probabilities.
Accounts without outcome variation contribute no conditional information.
There is no rare-event Poisson substitution. A computationally oversized chooser
causes an explicit stop, not silent account removal.

The seven candidate specifications and sign restrictions are in FROZEN_PLAN.json.
Curved utility is a specified gain-concave family with p in {0.25,0.5,0.75};
loss-side value is linear. Curvature is selected by training likelihood, never
held-out outcomes. This does not span every reference-dependent preference.
The displayed-strength function is a monotone piecewise-linear spline, centered
at gap zero, with knots -575,-300,-100,0,100,300,575. Mixed specifications add
extra loss cost or draw framing. All candidates include the same nuisance
controls and opponent-stake term. Weakly separated payoff coefficients are
explicitly conditional model parameters, not separately identified motives.

Chooser-cluster sandwich covariance uses the numerical Hessian of the exact
score. Conditional-logit finite-sample factor is G/(G-1)*(N-1)/(N-rank).
Wald coefficient intervals are suppressed when a constrained parameter is on
its boundary or the parameter direction is locally unidentified. Such fits can
still produce predictions and enter the recovery simulation. The descriptive
LPM uses CR1 G/(G-1)*(N-1)/(N-G-rank), in percentage points. LPM computations
stream complete chooser blocks to avoid a census-size dense interaction matrix.

The descriptive gap-by-K surface is estimated on all eligible rows and again
on exactly the conditional-logit switcher sample. Its reference bin is [-25,25);
50-point gap bins have centers -550..550. K group 0 means own RD <45.01; groups
1..4 are non-floor K quartiles defined on the primary regular roughly-equal
sample and reused in the sensitivities. Empty or unidentified cells stay missing.
The separate unrestricted index diagnostic interacts the gap spline with
(K-K*)/K*, centered at the observed median. It reports L, S and G at observed
K percentiles, not at K=0. It does not name the residual component deference.
Chooser effects do not remove heterogeneous chooser-specific gap slopes.

Forward validation uses two fixed folds: train through October 2024 and test
November 2024–April 2025; train through April 2025 and test May–October 2025.
The score is the conditional log likelihood within held-out chooser-month
groups. This conditions away unknown test-month baseline effects rather than
estimating them from held-out outcomes. It evaluates allocation within those
groups, not unconditional grant-rate forecasting. All candidates use the same
rows. Paired monthly scores receive 2,000 month-resampling intervals, with the
limited 12-month validation span stated explicitly.

A unique predictive selection requires a positive mean score advantage over
every competitor exceeding two monthly standard errors. Otherwise selection is
INDISTINGUISHABLE. The retained model set is also reported. This is a frozen
descriptive comparison rule, not a formal familywise model-truth test.

Absolute probability profiles need an additional baseline assumption because
conditional logit supplies no intercept estimates. For each training account,
solve for an intercept giving average probability (observed grants +20 times
training base rate)/(observed opportunities +20). Unseen accounts use the global
training baseline. Probability profiles and color predictions explicitly carry
this assumption; it is not used to fit the conditional slope coefficients.
Gap-profile standardization uses an outcome-independent 5% hash sample of rows
(the entire frame if that produces fewer than 1,000 rows), while mechanical
support curves use all primary rows. No profile is labeled causal mediation.

## Recoverability

The default is 20 repetitions for each successfully fitted generator: seven
candidate models and an additional half-framing effect. Binary outcomes are
generated on the actual full primary design and complete chooser histories.
The intercept calibration preserves smoothed account baselines, while each
generator retains its restrictions; cost is not forced to explain incompatible
weaker/stronger-side contrasts.

Every simulated outcome reruns both forward training fits for all candidates,
including selection of curvature and re-selection of outcome-varying accounts.
The full-sample covariance/profile pass is not repeated because it is not part
of the predictive-selection rule. Failed fits, retained sets, and indistinguishable
outcomes remain in the report. Twenty repetitions yield a coarse 0.05 frequency
resolution. The simulation does not establish robustness to arbitrary omitted
variables, misperceived payoffs or measurement error. No mechanism shares are
automatically released, even if some models appear recoverable.

## Cost diagnostic

Exact displayed ties are primary; abs(gap)<=25 is the sensitivity with linear
and quadratic gap controls. If support passes, estimate both premiums using
chooser FE and report coefficients and effects across the observed interquartile
range. The elasticity uses the sample median premium and actual sample base
rate. If support fails, estimate one linear opponent-RD bundle coefficient per
100 RD points and report its observed interquartile effect. This does not bound
own-cost sensitivity without restrictions on other channels. No doubling of
stakes is extrapolated.

## Information and policy deliverables

INPUT_CONTRACTS.md defines the optional game-time information and post-policy
inputs. The supplied 157-column certified panel does not itself establish those
historical labels. Tests use actual authenticated cue values, not present-day
status backfilled over earlier games. Main effects and cue-by-gap interactions
are compared on the same cue-complete held-out sample. The local provisional
threshold is separately gated. A cue association is not uniquely a belief,
deference, reputation, or rating-preference effect.

The color module computes both action changes and the opponent-stake change at
fixed states. It never replaces the premium change with zero. The statistic is
the average weekly White-minus-Black rate after implementation relative to eight
pre weeks, with unannounced and announced complete weeks separate. Pre-noise
moving-block bootstrap lengths are 4 and 8; the screen uses two-sided 5% critical
values and 80% power. Pairwise model-prediction differences, not only effects
versus zero, are compared at assumed awareness levels 0.05..1.

Without certified post membership, fixed cohort, calibration and censor inputs,
only pre-policy transported predictions and a clearly labeled planning screen
are released. Even with those inputs, this version does not propagate fitted-
parameter uncertainty or open post-policy behavioral coefficients. The next
behavioral opening therefore remains a separate step after reviewing this
prediction/power deliverable. No automatic GO, preference bound, or IV follows.

## Provenance and implementation references

- Pool authority copied from the delivered Color_Change_Followup_v1_0_0 package;
  authoritative 24-month report SHA256
  `917aa14ed8a8dbb7e82f9af1424aae079797edf4b1b06a4c27de084aca102c57`.
- Chronology inventory copied from Rating_Motives_v1_0_0. No unrelated 2013
  Rating Redesign history-closure material is consumed.
- Payoff algebra matches Color_Change_FirstPass_v1_0_2 `code/common.py`, under
  the certified anchored novol/noreg convention; reconstructed values are not
  observations of fractional production ratings or awareness.
- Conditional likelihood convention:
  https://www.statsmodels.org/stable/generated/statsmodels.discrete.conditional_models.ConditionalLogit.html
- Numerical optimization:
  https://docs.scipy.org/doc/scipy/reference/optimize.minimize-lbfgsb.html
- Glicko-2 derivation: https://glicko.net/glicko/glicko2.pdf

The public result archive excludes account/game-level analysis rows and fitted
account intercepts. The private external-drive cache is retained for restart.
