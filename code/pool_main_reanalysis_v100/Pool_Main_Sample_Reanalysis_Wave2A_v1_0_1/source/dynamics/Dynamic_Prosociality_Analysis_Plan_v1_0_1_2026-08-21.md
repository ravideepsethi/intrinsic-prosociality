# Dynamic Prosociality: Frozen Pre-Outcome Analysis Plan

Version: 1.0.1

Date amended: 2026-08-21

Status: amended after the outcome-blind Stage 07 feasibility gate and before any
A1, A3, or B1 effect estimate

Main sample: 2023-11-01 through 2025-10-31

Canonical opportunity panel: certified Stage 07, 47,587,020 rows

## 1. Purpose

The static benchmark is that a chooser's decision depends on a stable chooser type and
the current opportunity only:

```text
kind_draw_it = f(chooser_type_i, current_board_state_it, current_price_it,
                 current_clock_and_context_it) + error_it
```

Equivalently, conditional on stable chooser type and the observed current state,
history should not predict the current choice. The dynamic analyses ask whether
experienced mercy, prior choices, session outcomes, accumulated experience, or the
anticipated future add predictive content.

This document freezes the hypotheses, samples, estimands, reporting hierarchy, and
claim boundaries before inspecting the new 24-month dynamic estimates. It is not a
public preregistration and must not be described as one.

### 1.1 Version history and permitted information

Version 1.0.0 was frozen before the new dynamic outcomes were inspected. Its SHA-256
was:

```text
a80b22b88c7cc132c6415fc8acbf23829d1ae69adfd3d18c36ff7c5045b250ea
```

The Stage 07-only feasibility gate then ran at `20260821T195505Z`. It produced no
effect estimate and did not tabulate any subsequent choice or retention outcome by
mercy receipt. The authenticated transfer ZIP had SHA-256:

```text
13d27ba2a29fc63b22605928912aa4f7a6dc49e44ef0a4114ece16177434665b
```

Permitted feasibility information seen before this amendment was limited to cohort
sizes, exposure/pre-exposure balance, pooled later Stage 07 opportunity availability,
B1 sequence support, and first-grant payoff support. In particular:

- the non-tournament-like exposure cohort contained 2,556,782 accounts, of whom
  78,936 received mercy at the index exposure;
- the largest absolute standardized difference among the audited exposure and
  pre-exposure covariates was 0.174996;
- the prespecified primary B1 support rule selected 64,331 repeat granters, 1,017,944
  fair opportunities, and 273,483 fair kind draws; and
- no all-game A3 retention outcome was read.

Version 1.0.1 responds to the predictable exposure-state imbalance and clarifies the
estimands before outcome estimation. It adds fixed exposure-state adjustment, separates
total-path and state-conditioned A1 estimands, freezes an outcome-blind A3 ceiling rule,
states B1's repeat-granter scope, adds 6-hour and 7-day kernels, permits exploratory B2
regardless of B1, and defines subsequent mercy receipt and pair-excluded encouragement.

## 2. Data authority

The only paper-facing opportunity authority is the certified Stage 07 analysis panel:

```text
/Volumes/XT_Pro/lichess_kindness/derived/replication/analysis_panel_24m_sf100k
```

Required authentication:

- status `STAGE07_24M_CERTIFIED_OK`;
- 24 months, 2023-11 through 2025-10;
- 47,587,020 unique games;
- 669,503 kind draws;
- script SHA-256
  `0411d4061ea9831c20449208a9782aaf668e160139918d106a2b7d63aaa56e6e`;
- global summary SHA-256
  `8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7`.

All-game activity, retention, sessions, lifecycle, and opponent histories must come
from the canonical chronological rating-replay histories. Timeout-only records must
not be used to construct recent results, fatigue, session position, rating trajectory,
or total playing activity.

The recovered historical reentry rule is:

```text
disc_clock_s >= 347.0
```

The inequality is inclusive. The earlier one-second interpretation is superseded.
The fixed 347-second definition will be retained for historical comparability. A
separate 24-month upper-quartile clock threshold may be reported as a sensitivity and
must never silently replace the historical rule.

## 3. Analyses admitted to the current paper

### 3.1 Primary recipient design: mercy transmission (A1)

#### Exposure cohort

For every account, locate its first qualifying Stage 07 opportunity in which it was the
disconnected player and the final board state was fair/competitive under the certified
100,000-node rule. The exposure is:

```text
received_mercy = 1  if the chooser deliberately granted a kind draw
received_mercy = 0  if the chooser claimed the win
```

The principal design is restricted to ordinary, non-tournament-like games and, once
pair history is available, first-ever opponent pairings. Broader samples are
sensitivities.

#### Primary outcome

The first behavioral outcome is the account's decision at its first subsequent
fair/competitive chooser opportunity within 90 days. Because reaching that opportunity
is post-exposure, this is a conditional-choice estimand rather than an unconditional
average treatment effect.

#### Exposure-state adjustment and common support

Mercy receipt is mechanically related to the exposure game's state. No unadjusted arm
contrast will be treated as the principal estimate. The primary adjustment uses fixed
coarsened exposure-game strata formed before outcome inspection:

- disconnected-player engine evaluation bands:
  `[-100,-51]`, `[-50,-1]`, `[0,50]`, `[51,100]`, `[101,200]`, `[201,400]`,
  `[401,800]`, and `[801,+inf]` centipawns;
- chooser draw-payoff class: costly (`<0`), exact zero, or favorable (`>0`), using
  tolerance `1e-12` for exact zero;
- chooser-minus-disconnected rating-gap bands:
  `<-400`, `[-400,-201]`, `[-200,-101]`, `[-100,-1]`, `[0,99]`, `[100,199]`,
  `[200,399]`, and `[400,+inf]`; and
- canonical API speed.

The transparent primary standardization is an ATT-style aggregation of within-stratum
mercy-versus-claim contrasts, weighted by the number of mercy recipients in each
eligible stratum. An eligible stratum must contain at least five mercy recipients and
twenty claimed-against recipients. Month fixed effects and flexible residual controls
for continuous evaluation, payoff, rating gap, ratings/RDs, and clocks are included
within the retained common-support sample.

The feasibility report must disclose the share of mercy recipients retained. If less
than 90% are retained, this estimator will not be run until a dated amendment changes
the cell design. A prespecified sensitivity uses cross-fitted overlap weights from a
treatment-propensity model containing only exposure-time and pre-exposure information;
it targets the overlap population rather than the ATT.

#### Two subsequent-choice estimands

Two estimates are mandatory and must be reported side by side:

1. **Total-path conditional-choice estimate (primary A1 test):** apply the frozen
   exposure-state adjustment but do not control for the subsequent opportunity's board
   state, payoff, ratings, clocks, speed, or timing. These variables may have changed
   through the rating and activity consequences of mercy.
2. **State-conditioned estimate:** additionally control flexibly for the subsequent
   opportunity's engine evaluation, draw payoff, win premium, clocks, chooser and
   opponent ratings/RDs, speed, tournament status, and calendar time.

The second estimate answers whether choices differ at comparable observed subsequent
states. It is not a controlled direct causal effect without sequential-ignorability
assumptions. The first avoids conditioning on those mediators but still conditions on
reaching a later fair chooser opportunity.

Because requiring a subsequent opportunity conditions on post-exposure activity, two
companion decompositions are mandatory:

1. probability of reaching any subsequent fair chooser opportunity within 90 days;
2. probability of making any fair-state kind grant within 90 days, coding accounts
   with no later opportunity as zero.

Neither companion is a pure preference estimand. Together they show whether a
conditional-choice result is being driven by differential retention or opportunity
arrival.

#### Decay profile

Secondary, prespecified horizons are:

```text
same session / <= 6 hours
> 6 hours to 1 day
> 1 to 7 days
> 7 to 30 days
> 30 to 90 days
```

The decay profile is descriptive unless the assignment design below passes its balance
and falsification tests.

#### Identification checks

Actual mercy receipt is not assumed random. Before causal language is considered, the
analysis must report:

- balance in pre-exposure kindness, opportunity counts, activity, rating path, and
  prior disconnection history;
- balance in the exposure game's board, price, clock, rating, speed, and time cells;
- recipient-centered pre-trends;
- results restricted to first opponent pairings and ordinary pool-like games;
- sensitivity to fine rating x speed x hour/day matchmaking cells; and
- an encouragement analysis using the encountered chooser's predetermined,
  leave-one-out kindness propensity where adequate pre-exposure history exists.

The encouragement analysis does not automatically satisfy exclusion: a kind chooser
may alter gameplay as well as the final decision. It is corroborating evidence, not a
guaranteed instrument.

Every leave-one-out chooser-kindness propensity used in the encouragement analysis
must use only games strictly before the index exposure and must exclude the focal game
and every prior game involving the focal chooser-recipient pair.

#### Subsequent exposures and interpretation

Accounts claimed against at the index exposure may receive mercy later, and accounts
shown mercy may have later claimed-against exposures. The principal estimand is therefore
the effect or association of mercy at the first observed qualifying exposure under the
natural subsequent-exposure path. It is ITT-like with respect to later crossover and is
expected to be attenuated relative to a hypothetical never-treated comparison. Later
exposures will be reported descriptively. Censoring at the next qualifying exposure is
a sensitivity only because that censoring is itself post-treatment.

Without these checks, A1 must be described as a conditional dynamic association.

### 3.2 Primary platform outcome: recipient retention (A3)

Using the same exposure cohort and treatment, report:

- next rated-standard game within 10, 30, and 60 minutes;
- any rated-standard game within 7 and 30 days;
- number of rated-standard games within 7 and 30 days; and
- time to the next rated-standard game, with explicit right censoring.

Before any arm-specific A3 result is computed, the chronology feasibility gate will
calculate the pooled 30-day rate while keeping mercy and claim recipients combined.
The outcome hierarchy is frozen as follows:

- if pooled 30-day participation is at most 92%, any rated-standard game within 30
  days remains the primary A3 test;
- if pooled participation exceeds 92%, the primary A3 test becomes
  `log(1 + rated-standard games within 30 days)`, which preserves zeros and measures
  engagement intensity; and
- the binary participation outcome and raw game count are always reported, regardless
  of which test enters the three-outcome Holm family.

This gate addresses a ceiling without inspecting an arm difference. When the count
outcome is promoted, the claim is platform engagement rather than merely retention.
The 10/30/60-minute outcomes connect directly to the reentry layer and remain secondary
short-run outcomes.

The rating consequence of mercy is part of the total platform effect and is not removed
from the main retention estimand. A supplementary mediation decomposition may report
how much of the association is absorbed by the post-result rating path, but it must not
replace the total-effect specification.

### 3.3 Three-state mechanism decomposition (A2)

The following sign patterns will be reported as secondary mechanism evidence:

| Exposure | Empathy | Generalized reciprocity | Negative reciprocity |
| --- | ---: | ---: | ---: |
| Any qualifying disconnection | positive | zero absent mercy | ambiguous |
| Mercy received | positive | positive | positive/zero |
| Claimed against | positive | zero | negative |

Never-disconnected accounts are descriptive only. They are not a primary control group
because entry into the disconnected state is endogenous. The principal empathy contrast
uses within-account pre/post behavior around the first qualifying disconnection, with
denied recipients as the comparison path.

### 3.4 Conditional exchangeability diagnostic (B1)

The static null does not imply that raw choices may be shuffled across nonidentical
opportunities. The valid null preserves each chooser's observed opportunity sequence
and current-state propensities.

The analysis will:

1. estimate a cross-fitted static choice model using only current-state variables;
2. condition on each chooser's observed total number of kind draws;
3. reassign those draws across the chooser's actual opportunities with probabilities
   implied by the static model;
4. preserve timestamps and covariates exactly; and
5. compare actual temporal clustering with the conditional null distribution.

For kernel scale `tau`, define:

```text
T_tau = sum_i sum_{j<k} kind_ij * kind_ik * exp(-time_gap_jk / tau)
```

`T_24h` is the primary B1 statistic. `T_6h` and `T_7d` are prespecified secondary
statistics, separating session-scale clustering from week-scale persistence. Their
randomization p-values will be Holm-adjusted within the three-kernel B1 family; only
`T_24h` enters the paper-wide three-primary Holm family.

The primary sequence sample contains choosers with at least four fair opportunities,
at least two kind draws, and at least one non-kind choice. Support counts at alternative
opportunity thresholds will be reported before the test.

This design identifies sequence dependence among repeat granters, not among all
choosers or the modal one-time granter. Every B1 table and paper claim must say "among
repeat granters." The feasibility and final tables must report the sample's share of:

- all fair choosers;
- ever-kind fair choosers;
- all fair opportunities; and
- all fair kind draws.

Greater clustering than the null is consistent with habit, activated identity, or a
time-varying state. Less clustering is consistent with licensing or a moral budget.
Neither direction by itself identifies a unique mechanism.

### 3.5 Follow-up sequence analyses (B2-B3)

The first-grant event study may be shown as explicitly exploratory whether or not B1
rejects. It becomes confirmatory only if B1 rejects the conditional static null in the
relevant direction. Simulated first grants under the B1 null—not a flat zero line—are
the counterfactual for B2 in either case. The costly-versus-favorable first-grant
comparison remains secondary and is not promoted merely because an exploratory B2
plot is suggestive.

## 4. Gated reference-point pilot (F2)

The color-advantage relocation design (F1) is retired. It will not be reopened. The rule
change was not adequately announced, perception is unobserved, learning is endogenous,
and earlier work found material confounding.

Round-number and personal-best analyses are admitted only after a Lichess-specific
salience validation using all-game chronology:

- discontinuity in session stopping after crossing pooled 100-point boundaries;
- corresponding test around personal bests by speed-specific rating pool;
- 50-point and irregular pseudo-threshold placebos;
- explicit RD/provisional-rating restrictions; and
- current-history completeness checks.

The Anderson-Green evidence came from FICS, where personal bests were prominently
displayed and notified. It is motivating evidence, not proof of salience on Lichess.

If the salience validation fails, no kindness-threshold analysis will be promoted. If it
passes, the kindness analysis will distinguish exact reconstructed Glicko crossing from
a simple crossing heuristic based on rounded ratings visible to players.

Round-number effects extend the current-state reference-point model; they do not alone
reject history independence. Personal-best effects are genuinely history-dependent.

## 5. Analyses reserved for a dynamics paper

Unless unusually decisive evidence changes the packaging decision, the following are
reserved for a separate paper:

- first-grant habit/licensing and costly self-signaling (B2-B3);
- session profit/loss, prior result, tilt, and fatigue (C1-C3);
- experience, account lifecycle, and norm learning (D1-D2);
- ex ante re-pairing probability and direct reciprocity (E1-E2); and
- later timeout-disconnection behavior after mercy (A4).

A4 cannot be described as the propensity to disconnect from a losing position without
a valid denominator of all games reaching comparable losing states. Feasible proxies
are later timeout-disconnections per 1,000 rated games and the board-state composition
of later timeout events.

## 6. Multiple testing and reporting

The current-paper confirmatory hierarchy is:

1. A1 primary 90-day subsequent-choice estimate;
2. the A3 outcome selected by the blinded 92% pooled-ceiling rule;
3. B1 `T_24h` conditional-randomization statistic.

These three primary tests will be reported with raw p-values and Holm-adjusted p-values.
All horizon profiles, mechanism decompositions, encouragement estimates, subgroup
results, and threshold variants are secondary.

Every result must report:

- percentage-point effect;
- standard error or randomization interval;
- control-group mean;
- effect relative to that mean;
- accounts, opportunities, and kind draws;
- follow-up eligibility and censoring; and
- exact specification and sample hash.

The paper will emphasize magnitudes against the approximately 1.4% overall base rate,
not statistical significance generated by sample size.

## 7. Feasibility gate before estimation

Before any A1, A3, or B1 effect estimate is inspected, a read-only audit must report
only:

- sizes of the first-fair-recipient exposure cohorts;
- mercy/claim counts;
- covariate missingness and pre-exposure balance;
- availability of subsequent chooser opportunities by horizon;
- chronology follow-up coverage;
- B1 chooser/opportunity/kind-draw support;
- costly/favorable first-grant support; and
- first/repeat-pair feasibility counts if pair history is available.

Version 1.0.0 completed the Stage 07-only portion of this gate without estimating an
effect. Version 1.0.1 adds fixed-stratum overlap counts and B1 denominator shares. The
A3 all-game chronology linkage and pooled 30-day ceiling calculation remain required
before any A3 arm comparison or paper-wide dynamic unblinding.

The feasibility report must not tabulate subsequent kindness or retention outcomes by
exposure status. If support is inadequate, the design will be revised in a dated new
version before outcome estimation.

## 8. Reproducibility and privacy

All producers must be plan/execute separated, transactional, resumable where a
chronological scan is required, and fail closed on authentication or QA errors. Large
Parquet outputs and account-level histories remain on XT_Pro and outside Git. Only
scripts, documentation, schemas, compact aggregate results, and cryptographic hashes
may enter the repository.

No profile snapshot or personally identifying account-level output may be committed or
published. Public results must use aggregate cells with disclosure-safe minimum counts.

## 9. External timestamp

After the v1.0.1 package and its hashes are authenticated, the preferred credibility
step is a frozen third-party registration that can remain embargoed until the project is
released. Any registration must describe this honestly as a **post-Stage-07-feasibility,
pre-dynamic-outcome amendment**, attach both v1.0.0 and v1.0.1, and include the
feasibility receipt and amendment log. It must not be called a fully ex ante
preregistration.
