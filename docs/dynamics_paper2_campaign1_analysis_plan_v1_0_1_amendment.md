# Dynamics of Intrinsic Prosociality: Campaign 1 Analysis Plan (Paper 2)

## v1.0.1 Pre-Outcome Amendment — Additional No-New-API Analyses

**Version:** 1.0.1-AMENDMENT-FREEZE-READY
**Date:** 2026-08-24
**Base plan:** `docs/dynamics_paper2_campaign1_analysis_plan_v1_0_0.md`
**Base plan SHA-256:** `ded9965994b6c00ed613adc90eaff3f976b257e9eb6dafdda61819916dde49fe`
**Base-plan freeze Git authority:** `5e6e9c66d514211382e6f9df130b2017a10a8ec4`

**Status:** pre-outcome additive amendment. The v1.0.0 plan is already frozen and is not
modified by this document. This amendment becomes part of the effective Campaign 1 plan
only when these exact bytes are SHA-256 hashed and an external amendment freeze receipt is
committed. No Campaign 1 outcome estimation has been run. This is an internal analysis
plan amendment, not a public preregistration, and must not be described as one.

**Reason for amendment:** after the v1.0.0 freeze, an exhaustiveness review asked whether
that ten-analysis set covered all substantively distinct tests available from already
certified/on-hand data without further Lichess game-API acquisition. The review confirmed
that C4 already contains the prespecified early-rise-then-fall **inverse-U / inverted-U
norm-learning hypothesis**, and C5 contains the distinct **U-shaped experience hypothesis**.
It also identified four previously articulated, no-new-API hypotheses that were omitted
from the ten-analysis Campaign 1 list. They are added here before any Campaign 1 outcome
inspection. The original five-member Holm family is unchanged.

This amendment is **additive only**. Every definition, authority rule, privacy rule,
B2/C9 anchoring precondition, execution hold, gate rule, and interpretation limit in
v1.0.0 remains in force unless this amendment explicitly adds a narrower rule.

---

## A. Amendment to scope and purpose

Effective Campaign 1 now contains **fourteen** analysis modules: C1-C10 from the frozen
v1.0.0 plan plus C11-C14 below.

The four added modules address:

- **frequency-dependent norm erosion:** whether repeated mercy opportunities erode
  kindness faster when those moral decisions arrive densely rather than being spread
  out in time (C11);
- **recipient experience:** whether mercy depends on how experienced the disconnected
  opponent is, conditional on skill and the current position (C12);
- **ambient norm exposure:** whether a chooser's kindness covaries with the recent
  mercy norm among other comparable players on the platform (C13); and
- **calendar/cohort norm evolution:** how adjusted kindness changes across calendar
  time and account-entry cohorts within the locked 24-month panel (C14).

These additions do not reopen A1/A3/B1, B2/E1/F2-R/F2-P, or A2 completion. They feed
only the dynamics paper.

---

## B. Additional global definitions

The following definitions supplement §3 of v1.0.0.

- **Observed prior fair-opportunity count:** the number of certified Stage 07 fair
  chooser opportunities strictly before the focal opportunity.
- **Recent fair-opportunity density:** for a focal fair opportunity, the number of
  prior fair chooser opportunities for the same chooser in a prespecified trailing
  calendar window. C11 primary uses 30 days; 7, 14, and 60 days are sensitivities.
- **Recipient pre-opportunity experience:** cumulative rated games for the disconnected
  opponent observed in the canonical chronological rating-replay history strictly before
  the focal game. It is a predetermined history variable. It is not `count.all` from a
  later profile snapshot and is not called lifetime experience.
- **Ambient mercy norm:** a lagged leave-one-chooser-out kind-draw rate constructed only
  from certified Stage 07 opportunities of *other* choosers in the same speed-pool ×
  chooser-rating-band cell. The primary C13 window uses the preceding 28 complete UTC
  days ending before the focal UTC day. The focal chooser's own opportunities are
  excluded from both numerator and denominator.
- **Entry cohort:** for C14, six-month bins of `createdAt` among the v1.0.0 birth-cohort
  accounts. These accounts are observed from creation but remain right-censored at the
  locked panel end.

No new API request is permitted to construct any of these objects.

---

## C. Added analyses

Epistemic labels retain the v1.0.0 meaning: **[C]** confirmatory Holm-family member;
**[S]** prespecified secondary; **[X]** exploratory/descriptive. None of C11-C14 enters
Holm family D.

### C11. Frequency-dependent norm erosion [S]

- **Question (plain):** holding fixed how many fair mercy opportunities a player has
  already encountered, does kindness erode faster when those opportunities arrive in a
  dense cluster rather than being spread out over time?
- **Motivation:** C4 asks whether kindness first rises and then falls with early mercy-
  opportunity experience. C11 asks a distinct mechanism question: whether the *spacing*
  of repeated moral decisions helps determine that erosion. Dense repeated exposure is
  the field analogue of laboratory environments in which the same prosocial decision is
  posed unusually often.
- **Primary sample:** v1.0.0 birth-cohort accounts at career fair chooser opportunities
  3 through 20. Restricting to accounts observed from creation avoids left-censoring of
  the relevant fair-opportunity history; right-censoring at panel end remains and is
  reported.
- **Primary exposure:** `log(1 + N30)`, where `N30` is the number of prior fair chooser
  opportunities for that chooser in the trailing 30 days before the focal opportunity.
- **Primary estimand [S]:** chooser-FE linear-probability coefficient on `log(1 + N30)`
  with **career-fair-opportunity-index fixed effects** (3,...,20), the v1.0.0 current-state
  vector, and trailing-30-day total rated-game activity. The index fixed effects hold
  cumulative mercy-opportunity exposure fixed nonparametrically; the activity control
  separates density of mercy decisions from general chess activity. The conjectured
  norm-erosion sign is **negative**. Report a two-sided p-value.
- **Mandatory display:** adjusted kind-draw rates by career-opportunity index and
  recent-density quartile, so the result is visible without relying on one functional
  form.
- **Sensitivities [S]:** replace 30 days by 7, 14, and 60 days; replace `log(1 + N)`
  with density quartiles; replicate using the first 10 rather than first 20 career fair
  opportunities.
- **Full-panel companion [X]:** repeat using opportunity number since the first
  *observed* fair opportunity in the locked panel for all choosers. This version is
  explicitly left-censored for pre-existing accounts and cannot be called a career
  learning design.
- **Interpretive limit:** C11 is state/lifecycle evidence, not causal identification of
  exposure frequency. Dense opportunity arrival may reflect endogenous play patterns
  even after chooser FE, opportunity-index FE, general activity, and current-state
  adjustment.

### C12. Recipient experience and mercy [S]

- **Question (plain):** conditional on board state, price, rating, and chooser type, are
  players more or less willing to grant mercy to inexperienced opponents than to highly
  experienced opponents?
- **Sample:** certified Stage 07 fair opportunities with nonmissing recipient
  pre-opportunity experience from the canonical chronology.
- **Exposure:** disconnected opponent's cumulative rated games strictly before the focal
  game. Primary display uses deciles formed within disconnected-opponent rating band ×
  speed pool. This conditioning is mandatory so experience is not a disguised skill or
  pool comparison.
- **Primary estimand [S]:** within-chooser, current-state-adjusted difference in kind-draw
  probability between recipient-experience deciles 1-2 and 9-10, aggregated across the
  rating-band × speed cells by opportunity weight. Two-sided; **no directional sign is
  imposed**.
- **Continuous companion [S]:** chooser-FE coefficient on
  `log(1 + recipient prior rated games)` with the current-state vector.
- **Checks:** report the full decile profile; repeat within each chooser rating band;
  require same-speed-pool experience as a sensitivity; if certified `createdAt` is bound,
  show recipient account age as a separate descriptive companion rather than mixing it
  into the primary experience measure.
- **Interpretive limit:** this is a recipient-selection/targeting gradient. It does not
  identify a causal effect of opponent experience and does not imply that choosers know
  the opponent's exact lifetime game count.

### C13. Ambient norm exposure [X]

- **Question (plain):** is an individual's private mercy decision more common when the
  recent mercy norm among other comparable players has been stronger?
- **Exposure construction:** for each focal fair opportunity, construct the **lagged
  leave-one-chooser-out** kind-draw rate among other choosers in the same speed-pool ×
  chooser-rating-band cell during the preceding 28 complete UTC days, ending before the
  focal UTC day. The focal chooser contributes neither numerator nor denominator.
- **Support rule:** an ambient cell must contain at least 5,000 other-chooser fair
  opportunities in the 28-day window. Thin focal rows are excluded and their number is
  reported. The threshold is based only on the denominator and therefore can be audited
  before ambient outcome rates are inspected.
- **Estimand [X]:** chooser-FE coefficient on a one-percentage-point increase in the
  lagged ambient mercy rate, with the v1.0.0 current-state vector plus cell and calendar
  controls sufficient to keep the exposure from being a simple speed/rating composition
  proxy. Also report adjusted focal kindness by ambient-rate quartile.
- **Sensitivities [X]:** 14- and 56-day lag windows; leave-one-chooser-out construction
  at speed-pool only and speed-pool × rating-band levels; one-calendar-week washout
  between ambient window and focal day.
- **No causal peer-effect claim:** common platform shocks, composition, interface
  changes, and unobserved calendar conditions can move both ambient and focal behavior.
  The leave-one-chooser-out lag removes mechanical self-inclusion and simultaneity at the
  focal observation; it does not turn the association into randomized social influence.

### C14. Calendar and entry-cohort norm evolution [X]

- **Question (plain):** did the platform's adjusted kindness norm change over the locked
  24 months, and do accounts entering at different times trace different early mercy
  trajectories?
- **Panel A — period map (Stage 07 alone):** report raw and current-state-adjusted
  fair-state kindness rates for every calendar month from 2023-11 through 2025-10.
  A chooser-FE month profile is reported as the within-chooser companion. No single
  trend coefficient is privileged and no structural break is claimed.
- **Panel B — entry-cohort map (profile authority required):** among birth-cohort
  accounts, define six-month `createdAt` entry cohorts and plot current-state-adjusted
  kindness over career fair chooser opportunities 1 through 10 separately by cohort.
  Report retention/support at every cohort × opportunity index.
- **Relation to C4:** C4 tests the prespecified within-lifecycle inverted-U contrasts
  (2-4 minus 1; 8+ minus 2-4). C14 asks whether that trajectory itself differs across
  calendar entry cohorts and whether the platform-level period profile moves over time.
  C14 does not replace or duplicate C4.
- **Interpretive limit:** age, period, and cohort are not separately identified by this
  descriptive map. No causal platform-norm or cohort effect is claimed. Panel B is
  deferred if the certified 24-month `createdAt` authority is not bound.

---

## D. Amendment to confirmatory family and multiple testing

**No change.** Holm family D remains the five conceptual members frozen in v1.0.0:

1. C1 loss-minus-win within-chooser contrast;
2. C2 ahead-minus-behind session contrast;
3. C5 between-person U statistic;
4. C6 clearly-losing timeout-disconnections per 1,000 rated games over 90 days,
   mercy minus claimed; and
5. C9 later-session ignition excess.

C11 and C12 are prespecified **secondary** analyses. C13 and C14 are
**exploratory/descriptive**. They are always reported with those labels and cannot be
promoted into Holm family D after outcomes are seen.

The v1.0.0 C6 support gates and B2/C9 implementation precondition are unchanged.

---

## E. Amendment to feasibility audit

The pre-estimation feasibility audit gains the following **support-only** checks. These
checks must not tabulate focal kind-draw outcomes by the added exposures.

- **C11:** birth-cohort chooser count; fair-opportunity counts at indices 3-20; support
  by `N30` density bins/quartiles; share of focal rows with sufficient chronology to
  compute trailing activity and density.
- **C12:** share and count of fair opportunities with recipient pre-opportunity
  experience; support by recipient-experience decile within rating-band × speed cells.
- **C13:** denominator sizes of candidate 28-day ambient cells and share of focal rows
  satisfying the 5,000-other-opportunity support threshold. **Do not calculate or display
  the ambient kindness numerator/rate in the feasibility audit.**
- **C14:** monthly fair-opportunity support for Panel A; if `createdAt` authority is
  bound, account counts and retention by six-month entry cohort × career-opportunity
  index for Panel B.

If these support checks reveal that a prespecified binning scheme is infeasible, any
redesign must be recorded in a dated v1.0.x amendment **before** focal outcomes are
inspected by the relevant exposure.

---

## F. Amendment to reporting standards

In addition to v1.0.0 §6:

- C11 must report the cumulative-opportunity index and general-activity conditioning
  used to distinguish opportunity **density** from opportunity **count**.
- C12 must report recipient-experience support within rating-band × speed cells so the
  gradient cannot be mistaken for a skill-composition result.
- C13 must report the ambient-cell definition, lag window, leave-one-chooser-out rule,
  support threshold, and excluded-row share; all prose must say **association**, not
  contagion, peer effect, or causal norm transmission.
- C14 must report period and cohort profiles as descriptive maps and state the
  age-period-cohort identification limitation.

Statistical significance is never the headline for C11-C14; effect sizes and adjusted
profiles are reported against the relevant base rate.

---

## G. Reproducibility and sequencing

No sequencing rule changes.

- No new Lichess game-API pull is authorized by this amendment.
- No new patron/profile acquisition is authorized; C14 Panel B and any profile-dependent
  companion simply wait for the already-planned certified 24-month profile authority.
- No chronology rebuild is authorized.
- C11-C14 are held unestimated until the flagship manuscript has been submitted, under
  the same v1.0.0 execution constraint.
- The read-only B2 anchoring audit and treatment-blind/support-only feasibility audit
  remain the only early work permitted.
- Runtime authority bindings remain governed by
  `manifests/dynamics_campaign1_input_authorities.json`.
- The immutable effective scientific plan after this amendment is the **ordered pair**:
  (1) frozen v1.0.0 base plan and (2) frozen v1.0.1 amendment. The base file is never
  edited or silently replaced by a merged copy.

---

## H. Version history and process note

- **v1.0.0-FROZEN (2026-08-24):** ten-analysis Campaign 1 plan frozen before Campaign 1
  outcome estimation; base SHA-256
  `ded9965994b6c00ed613adc90eaff3f976b257e9eb6dafdda61819916dde49fe`.
- **v1.0.1-AMENDMENT-FREEZE-READY (2026-08-24):** additive pre-outcome exhaustiveness
  amendment. Confirms that C4 already contains the inverse-U / early-rise-then-fall norm
  learning hypothesis and C5 the distinct experience U-shape; adds C11 frequency-
  dependent norm erosion, C12 recipient experience, C13 ambient norm exposure, and C14
  calendar/cohort norm evolution. The five-member Holm family, all v1.0.0 gates and
  preconditions, and the flagship execution hold remain unchanged.

**Process note.** The base plan was not edited after freeze. The additional hypotheses
were added through a separately hashable amendment because they were identified in an
exhaustiveness review conducted before any Campaign 1 outcome estimation. This preserves
both facts: what v1.0.0 contained when it was frozen, and what was added subsequently
while the additions were still epistemically clean.
