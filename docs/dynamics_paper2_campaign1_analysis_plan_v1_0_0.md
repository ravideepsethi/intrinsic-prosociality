# Dynamics of Intrinsic Prosociality: Campaign 1 Analysis Plan (Paper 2)

Version: 1.0.0-FREEZE-READY (author-approved; freeze by external hash before any campaign estimation)

Date drafted: 2026-08-24

Status: pre-outcome freeze candidate. The scientific design was approved by the author
on 2026-08-24, but this file is not frozen until these exact bytes are SHA-256 hashed and
the external freeze receipt is committed. This document is an internal analysis plan. It
is not a public preregistration and must not be described as one.

Scope: the ten analyses runnable from data already certified and on hand. This campaign
feeds the dynamics paper only. Nothing in this plan may modify, reopen, or reinterpret
the frozen flagship families (A1/A3/B1; B2/E1/F2-R/F2-P; A2 completion). No result from
this campaign enters the flagship paper. A technical audit triggered by this plan may
identify a pre-existing implementation issue in inherited B2 machinery; if so, that issue
is handled separately as a B2 provenance/audit matter before C9 is allowed to inherit the
machinery.

---

## 1. Purpose

The flagship established: a persistent person-specific propensity (structure), gated by
desert and price, transmitted by receipt (A1), expressed in temporally clustered episodes
(B1/B2), with denial followed by withdrawn kindness (A2). This campaign tests the
remaining reserved hypotheses about *when* the propensity is expressed and *what kind of
object* the transient state is:

- short-run state dependence: prior results, session profit/loss, fatigue (C1-C3);
- lifecycle: norm learning and the experience U-shape (C4-C5);
- equilibrium responses: exploitation of mercy and direct reciprocity (C6-C7);
- descriptive maps: structure by rating tier (C8);
- mechanism discriminators: ignition transfer across sessions and pools (C9), and the
  anatomy of the denial effect (C10).

The static null throughout: conditional on stable chooser type and the current
opportunity's observables, none of the history variables below predict the current
choice.

## 2. Data authorities

All estimation reads only the following certified inputs. No Lichess API call, no new
patron/profile acquisition, no chronology rebuild, no private-cache mutation, and no Git
result commit is permitted in this campaign.

1. **Stage 07 analysis panel (24m, sf100k).** Status `STAGE07_24M_CERTIFIED_OK`;
   47,587,020 rows; 669,503 kind draws; script SHA-256
   `0411d4061ea9831c20449208a9782aaf668e160139918d106a2b7d63aaa56e6e`; global summary
   SHA-256 `8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7`.
2. **Canonical chronological rating-replay histories.** 7,763,847,245 rows across 852
   authenticated files (authority: second-wave chronology manifest). All sessions,
   streaks, fatigue, activity, and experience counters derive from this layer. Timeout-
   only records must never be used to construct recent results, session position,
   rating trajectory, or activity.
3. **Second-wave history layers** (run `20260822T150914Z` and successors): sampled
   user-history events (309,961,276 rows; 685,731 sampled Stage 07 targets),
   pair-history events (154,693,194 rows), deterministic 2% cluster samples of whole
   users and whole unordered pairs.
4. **A2 account-window cache** (run `20260823T141145Z`): 1,642,449 rows.
5. **24-month profile covariates.** Only the full 24-month patron/profile snapshot may
   serve as the profile authority, and only after it is certified. Only `createdAt`,
   `count.all`, and per-pool game counts may be read; patron status must not be joined
   in this campaign. There is **no June-2026 fallback** for confirmatory C5. If the
   full 24-month profile authority is not certified when execution otherwise becomes
   permissible, profile-dependent C4/C5 components are deferred rather than moved to a
   different population.
6. **Reentry rule** (historical, inclusive): `disc_clock_s >= 347.0`.

### 2.1 Authority binding rule

The scientific plan is frozen independently of machine-specific paths and of an authority
that is still awaiting certification. Exact runtime authority bindings live in:

```text
manifests/dynamics_campaign1_input_authorities.json
```

The companion schema/template is committed with this plan. Before any feasibility or
estimation routine reads an authority, that authority must be marked `BOUND` in the
runtime manifest with its exact canonical path, certification marker, and SHA-256 copied
verbatim from its `_SUCCESS`/manifest authority. The campaign runner authenticates the
runtime manifest and every bound authority fail-closed before reading one analysis row.
A pending authority may not be silently substituted. Any change in the identity of an
allowed authority requires a dated v1.0.x amendment before exposure-specific or
outcome-specific estimation.

## 3. Global definitions (fixed for the campaign)

- **Session:** a maximal run of a chooser's rated games with inter-game gaps < 30
  minutes (gap measured last-move-to-first-move). Sensitivities: 15 and 60 minutes.
  The 30-minute primary is fixed now, before any campaign outcome inspection.
- **Fair opportunity / kind draw:** the certified Stage 07 100k-node definitions,
  unchanged.
- **Speed pools, rating bands:** the flagship's certified partitions. The rating bands
  are fixed as **<1600, 1600-1999, 2000-2399, 2400+** for this campaign.
- **In-window experience:** cumulative rated games (all pools) before the current
  opportunity, from the chronology.
- **Snapshot total-game count:** `count.all` at the certified 24-month profile snapshot;
  account age from `createdAt`. Because the snapshot count can include games played
  after a focal opportunity, it is a between-person eventual-engagement/experience
  measure, not a time-varying causal exposure.
- **Birth cohort:** accounts with `createdAt` inside 2023-11-01..2025-10-31. These
  accounts are observed from account creation but are right-censored at the end of the
  locked panel; they do **not** have complete observed lifetimes.
- **Standard controls ("current-state vector"):** engine evaluation bin, draw payoff,
  win premium, both clocks, chooser and opponent ratings and RDs, speed pool,
  tournament status, calendar month, hour-of-week. Identical to the frozen A1 control
  set unless an analysis states otherwise.
- **Inference:** cluster on chooser unless stated; report percentage-point effects,
  control means, effects relative to control means, and denominators, per house
  reporting standards.

### 3.1 B2/C9 randomization-anchor precondition

C9 may inherit the certified B2 conditional-randomization machinery only after a
read-only producer audit resolves the outstanding anchoring question. The required rule
is fixed now:

> In every conditional-randomization draw, the simulated sequence must identify its own
> pseudo-first grant, and every post-first-grant window and partition must be anchored to
> that draw's pseudo-first grant rather than to the observed sequence's first grant.

The B2 producer must be inspected and the answer archived before C9 estimation. If B2
already follows this rule, C9 may inherit the implementation after authentication. If B2
instead fixed windows at the observed first grant, C9 is blocked until a corrected
randomization implementation is independently audited, and the pre-existing B2 issue is
escalated as a separate flagship provenance matter. A software/precondition failure does
**not** resize the Holm family opportunistically; family-D inference is held until the C9
machinery is valid.

## 4. Analyses

Epistemic status key: **[C]** confirmatory (member of the Holm family in §5);
**[S]** secondary (prespecified, reported, not in the family); **[X]** exploratory /
descriptive (always reported, labeled).

### C1. Prior-result state dependence (streaks and tilt)

- **Hypothesis (plain):** players are less kind immediately after losing.
- **Sample:** fair opportunities where the chooser completed >= 1 rated game earlier in
  the same session.
- **Exposure:** result of the immediately preceding rated game (loss vs win; draws a
  separate category). Secondary: streak length (>= 3 consecutive losses / wins).
- **Primary estimand [C]:** within-chooser (chooser FE) difference in kind-draw
  probability, loss-preceded minus win-preceded, with the current-state vector.
  Two-sided.
- **Mechanism signs:** tilt/frustration negative; guilt/compensation positive; static
  null zero.
- **Confounds and checks:** matchmaking after wins/losses shifts opponent quality and
  own rating mechanically (current-state vector absorbs); report the raw and adjusted
  contrast; sensitivity restricting to same-pool preceding games.
- **Interpretive limit:** this is a within-person state-dependence estimate, not a causal
  effect of losing. Chooser FE remove stable person heterogeneity; they do not randomize
  the preceding result.

### C2. Session profit/loss reference (house money)

- **Hypothesis (plain):** players behind on the session are less kind; players ahead
  are kinder.
- **Sample:** as C1.
- **Exposure:** session net rating change before the current game (sum of ratingDiff in
  the chooser's pools this session). Primary form: sign (ahead / behind / exactly
  even). Continuous P&L winsorized at +/- 50 as secondary.
- **Primary estimand [C]:** within-chooser ahead-minus-behind contrast with the
  current-state vector and games-so-far-in-session controls. Two-sided.
- **Explicit non-claim:** no localization/kink claim at zero session P&L. Placebo
  session thresholds at +/- 25 points as sensitivity only. (Lesson of the flagship's
  Section 5 applies here in full.)
- **Confounds:** session P&L correlates with session length and current rating drift;
  both controlled. Chooser FE remove stable type.
- **Interpretive limit:** this is a within-person state-dependence estimate, not a causal
  effect of being ahead or behind in the session.

### C3. Fatigue and session position [X]

- **Descriptives:** kind rate by within-session game index (1, 2-3, 4-6, 7-10, 11+)
  and by session elapsed time, within chooser, current-state adjusted.
- **No confirmatory test.** Note in output: late-session opportunities condition on
  having continued; within-chooser profiles mitigate but do not remove this.

### C4. Norm learning (birth cohort) [S]

- **Hypothesis (plain):** new accounts first must discover the mercy option, then
  absorb the claiming norm: kindness rises over the first few chooser opportunities,
  then falls.
- **Sample:** birth-cohort accounts observed from account creation, with right-censoring
  at the end of the locked panel, at their 1st, 2nd, ..., 10th career fair chooser
  opportunity.
- **Estimand:** kind rate by career opportunity index, current-state adjusted;
  prespecified contrasts: (a) opportunities 2-4 minus opportunity 1 (discovery,
  predicted positive); (b) opportunities 8+ minus 2-4 (norm absorption, predicted
  negative).
- **Checks:** cohort survivorship (report share of cohort reaching each index);
  calendar-time controls (cohort entry spread across 24 months); replication within
  each entry half-year.
- **Status:** secondary, because survivorship and right-censoring make the later-index
  contrast interpretable only jointly with the retention profile.

### C5. The experience U-shape (D1)

- **Hypothesis (plain, as conjectured in the 2026-05-10 correspondence):** very casual
  and very invested players are the kind ones; the middle is not.
- **Between-person primary [C]:** deciles of snapshot total games (`count.all`) within
  rating band x speed pool. Prespecified U statistic:
  `U = [mean(kind | deciles 1-2) + mean(kind | deciles 9-10)] / 2 - mean(kind | deciles 5-6)`
  computed on current-state-adjusted rates, aggregated across bands by opportunity
  weight. Two-sided test of U = 0; the conjecture predicts U > 0.
- **Interpretation of the primary:** because `count.all` is measured at a later snapshot
  and may include games played after focal opportunities, this is a between-person
  eventual-engagement/experience association. It is **not** a developmental or causal
  effect of accumulated experience.
- **Within-person companion [S]:** chooser-FE coefficient on log(1 + in-window
  cumulative games), current-state adjusted. This removes stable chooser heterogeneity
  but remains conditional on continued activity; it answers a related within-account
  temporal-trend question and is not "immune to survivorship."
- **Confounds and mandatory conditioning:** rating-band conditioning is mandatory
  (experience and skill travel together and structure varies by tier); survivorship
  and account-era effects reported via cohort splits; opportunity-exposure differences
  noted (casual players face fewer timeouts).
- **Universe:** the certified full 24-month profile/chooser universe only. If that
  authority is unavailable when execution otherwise becomes permissible, C5 is
  deferred. There is no substitute June-snapshot confirmatory population.

### C6. Exploitation of mercy (A4 proxies)

- **Hypothesis (plain):** receiving mercy teaches that disconnection is cheap; treated
  recipients subsequently disconnect from clearly losing positions more often.
- **Sample and identification:** the certified A1 first-exposure cohort, ATT
  stratification, clustering, and companion structure inherited unchanged.
- **Primary outcome [C]:** the number of later timeout-disconnections in which the
  recipient is **clearly losing** (certified Stage 07 threshold) per 1,000 rated games
  played during the next 90 days, mercy minus claimed. This outcome is unconditional
  on having a later timeout-disconnection and therefore does not condition the primary
  test on a post-treatment event.
- **Denominator license and sensitivity:** rated games played is itself post-treatment.
  The rate normalization is prespecified because the certified A3 primary found
  approximately zero mercy effect on 30-day game counts, providing an empirical license
  for activity normalization. Because that certified activity result is at 30 days while
  the C6 primary horizon is 90 days, the **unnormalized 90-day count of clearly-losing
  timeout-disconnections per recipient is a mandatory sensitivity**. The 90-day rated-
  game denominator difference is also reported as a descriptive denominator diagnostic,
  not as a Holm-family outcome. The confirmatory interpretation must not hinge silently
  on denominator balance.
- **Secondary decomposition [S]:** (a) all later timeout-disconnections as the
  disconnector per 1,000 rated games, 90 days; (b) the share of those later timeout-
  disconnections occurring in clearly losing positions; (c) the unnormalized count
  sensitivity described above. A valid all-games *losing-state* denominator does not
  exist and must not be claimed.
- **Mechanism signs:** exploitation predicts a positive mercy-minus-claimed effect on
  the primary; norm-of-mercy stability predicts zero. Deterrence-by-denial would appear
  as claimed-against-arm changes and is described under C10.
- **Support gate (treatment-blind, pooled):** before any mercy/claim-specific C6 outcome
  is inspected, require both (i) at least **4,000 pooled A1 recipients** with >= 1 later
  timeout-disconnection in the 90-day window and (ii) at least **4,000 pooled clearly-
  losing timeout-disconnection events** in that window. The second condition explicitly
  checks support for the rarer confirmatory event, not merely for all disconnections.
  Counts are pooled across arms only. If either threshold fails, C6 demotes to [S] with
  an infeasibility note and is removed from Holm family D before any arm-specific C6
  effect is viewed (see §5).

### C7. Direct reciprocity in repeat pairs (E2) [S, support-gated]

- **Hypothesis (plain):** in the rare repeat meeting, players favor a past benefactor.
- **Sample:** pair-history 2% cluster sample; fair chooser opportunities where the
  chooser previously met this opponent, categorized: prior mercy received from this
  opponent / prior claim by this opponent / prior meetings with no timeout event.
- **Estimand:** kind rate toward past benefactor minus past claimer, within chooser
  where possible, current-state adjusted.
- **Support gate (treatment/outcome-blind):** if benefactor-facing fair opportunities
  are < **1,000** in the cluster sample, the analysis is reported as descriptive counts
  only. This threshold is set on opportunities rather than inferred after seeing kind
  outcomes.
- **Scope note:** whatever the result, it bounds the anonymity claim; it does not
  reopen E1.

### C8. Structure by rating tier (elite map) [X]

- Full descriptive replication of the structure results (desert gradient, price gap,
  persistence) within each fixed rating band including 2400+, from Stage 07 alone.
  Current-state-adjusted where applicable. No hypothesis test; output is one table and
  one figure for the paper's heterogeneity section.

### C9. Ignition transfer (mechanism discriminator for B2)

- **Question (plain):** is the post-first-grant state a mood that stays where it
  started, or something that travels with the person?
- **Machinery:** the certified B2 conditional-randomization framework (repeat granters;
  chooser totals and static propensities fixed; 4,999 sequence draws), but only after
  the §3.1 anchoring precondition is cleared.
- **Per-draw reclassification rule (mandatory):** every randomization draw identifies
  its own simulated pseudo-first grant. Relative to that pseudo-first grant, the draw
  then recomputes: (a) same-session vs later-session using the §3 session definition
  (30-minute primary; 15/60 sensitivities), and (b) same speed pool vs different pool
  within 24h. Null partitions must **not** be inherited from the observed sequence.
  Compute therefore scales with `draws x sequence reclassification`; the runner must
  budget for that explicitly and cache/reuse only objects that do not depend on the
  draw-specific pseudo-first grant.
- **Primary estimand [C]:** the later-session excess (observed minus conditional null)
  within 7 days of the first observed/simulated grant as appropriate to the observed or
  null sequence. Pure transient-mood accounts predict ~ 0; habit / identity accounts
  predict > 0. Two-sided.
- **Secondary [S]:** same-session minus later-session excess (state-component size);
  same-pool minus cross-pool excess within 24h (context-boundness).
- **Inherited caveats, restated verbatim in output:** first *observed* grant in the
  locked panel, not necessarily first lifetime grant; repeat-granter scope; timing
  evidence, not a causal claim.

### C10. Anatomy of the denial effect (A2 extensions) [X]

- (a) **Decay clock:** the claimed-against within-account decline at 7/14/30/60/90-day
  horizons (extends the certified 30/60/90 variants).
- (b) **Behavioral channel:** denied recipients' subsequent timeout-disconnection
  behavior (links to the C6 decomposition, claimed arm).
- (c) **Personal-slight test:** does the denial effect depend on the denier's
  predetermined leave-pair-out kindness propensity? Norm-updating predicts denial by
  anyone teaches the norm equally; resentment predicts a larger effect when denied by
  an otherwise-kind chooser ("it was personal"). Uses the certified LOO propensity
  construction from the A1 encouragement layer.
- All three exploratory: mechanism-generating for the paper's discussion, not
  confirmatory claims.

## 5. Confirmatory family, gates, and multiple testing

**Holm family D (five conceptual members, fixed now):**

1. C1 loss-minus-win within-chooser contrast;
2. C2 ahead-minus-behind session contrast;
3. C5 between-person U statistic;
4. C6 clearly-losing timeout-disconnections per 1,000 rated games over 90 days,
   mercy minus claimed;
5. C9 later-session ignition excess.

Raw and Holm-adjusted p-values are reported for all estimable family members under the
rules below. Everything else in §4 is [S] or [X] and is always reported with its label.

**Gate/precondition semantics (distinguished deliberately):**

- *Validity gates* (none in this campaign) would follow the F2 rule: failure is charged
  at p = 1 inside the family.
- *Support gates* are power/support statements fixed before treatment-specific outcome
  inspection. C6 has the dual pooled 4,000/4,000 gate in §4; if it fails, C6 demotes to
  [S] and is removed from the family, with the resulting family size recorded before
  any arm-specific C6 effect is seen. C7's 1,000-opportunity gate demotes C7 to
  descriptive only and does **not** change Holm family D because C7 is not a family
  member.
- *Implementation preconditions* are not statistical gates. The B2/C9 anchoring audit
  in §3.1 must be cleared before C9 can be estimated. Failure or ambiguity does not
  remove C9 or shrink the family; family-D inference is held until valid machinery is
  available.

**Feasibility audit (treatment-blind; run and archived before estimation):** session
coverage (share of fair opportunities with a prior same-session game); birth-cohort
sizes and per-index retention; per-band decile supports for C5; C6 pooled support counts
from §4 (including the pooled clearly-losing event count, never split by mercy/claim);
C7 category counts; C9 later-session and cross-pool opportunity counts per horizon.
The audit must not tabulate kindness or any C6 behavioral outcome **by exposure/treatment
status**. The pooled C6 event count is permitted solely to establish support for the
prespecified rare outcome. If support forces redesign, a dated v1.0.x amendment precedes
any exposure-specific or outcome-specific estimation.

## 6. Reporting standards

Every result reports: percentage-point effect or rate effect as appropriate; SE or
randomization interval; control-group or null mean; effect relative to that mean;
choosers/recipients, opportunities or rated-game denominator, and kind draws/events;
specification and sample hash; epistemic label. Magnitudes are emphasized against the
relevant base rate; statistical significance generated by sample size is never the
headline. B2-derived numbers use the certified re-denominated form (rates vs conditional
null, never raw excess against the population base).

For C6 specifically, every primary report must place the normalized 90-day rate beside
(i) the unnormalized 90-day clearly-losing-disconnection count sensitivity and (ii) the
90-day rated-game denominator diagnostic, so the interpretation cannot depend silently
on post-treatment activity normalization.

## 7. Reproducibility, privacy, and non-interference

- Plan/execute separation; transactional, resumable producers; fail-closed
  authentication of the runtime authority manifest and every input authority in §2.
- Private account/pair caches remain on XT_Pro; exports are aggregate-only with
  disclosure-safe minimum cell counts; no identifiers in any published artifact.
- No Lichess API request; no patron-status field is read; no chronology rebuild; no
  mutation of any frozen result directory; results are archived and hashed but not
  committed until the standard sync review.
- The scientific plan is frozen by an external SHA-256 receipt. The plan file never
  embeds its own hash. Runtime data authorities are separately bound and hashed in
  `manifests/dynamics_campaign1_input_authorities.json` under §2.1.
- The flagship freeze is inviolate: no output of this campaign may be cited in, merged
  into, or used to reword the flagship paper. Promotion target for every result in
  this plan is the dynamics paper.

## 8. Execution constraint (sequencing)

This freeze-ready plan is to be SHA-256 hashed and committed with an external freeze
receipt. After that, it is **held unexecuted until the flagship manuscript is submitted.**
Freezing now captures the design at full sharpness; holding estimation protects the
critical path.

Two non-estimation activities may occur earlier:

1. the §3.1 read-only B2 anchoring audit, because it is a provenance/software check and
   is now a blocking precondition for C9; and
2. the treatment-blind feasibility audit in §5, at the author's discretion.

No campaign estimation may begin until all three conditions hold: (i) the flagship
manuscript has been submitted; (ii) every authority needed by the relevant analysis is
`BOUND` and authenticated in the runtime authority manifest; and (iii) the B2/C9
anchoring precondition is cleared. Profile-dependent analyses remain deferred if the
24-month profile authority is still unavailable.

## 9. Author decisions fixed before freeze

The following decisions were explicitly approved on 2026-08-24 and are no longer open
review items for v1.0.0:

1. **Session gap:** 30 minutes primary; 15/60-minute sensitivities.
2. **Confirmatory family:** C1, C2, C5, C6, C9; C4 remains secondary.
3. **C6 primary:** clearly-losing timeout-disconnections per 1,000 rated games over 90
   days, unconditional on later disconnection; A3's certified ~zero 30-day game-count
   effect is the stated normalization license; unnormalized 90-day event count is a
   mandatory sensitivity.
4. **C6 support:** treatment-blind pooled dual gate of 4,000 recipients with any later
   timeout-disconnection and 4,000 pooled clearly-losing timeout-disconnection events.
5. **C7 support:** 1,000 benefactor-facing fair opportunities; below that, descriptive
   counts only.
6. **C5 universe:** certified full 24-month profile universe only; otherwise deferred,
   with no June-snapshot fallback.
7. **Rating bands:** <1600, 1600-1999, 2000-2399, 2400+.
8. **Authority hashes:** bound in a separate authenticated runtime authority manifest,
   not inserted recursively into this plan's prose.
9. **B2/C9 anchoring:** per-draw pseudo-first-grant anchoring is mandatory; the B2
   producer's implementation must be resolved and archived before C9 estimation.

## 10. Version history

- **v1.0.0-DRAFT (2026-08-24):** initial design, drafted before any outcome inspection
  in this campaign. Prior related decisions inherited: reserved list (core plan §5,
  2026-08-21); B2 re-denomination and caveats (second-wave audit, 2026-08-22); A2
  completion results and heterogeneity note (2026-08-23); gate-semantics distinction.
- **v1.0.0-FREEZE-READY (2026-08-24):** author-approved pre-hash revision after plan
  review. The revision corrects the C6 post-treatment conditioning error; requires
  per-draw pseudo-first-grant anchoring in C9 and elevates the unresolved B2 anchoring
  question to a blocking implementation precondition; corrects the C5 survivorship and
  ex-post `count.all` interpretation; corrects the C4 "complete lifetime" wording;
  removes the C5 population fallback; makes C6 support treatment-blind and directly
  relevant to its rarer primary event; raises C7's support threshold; fixes the rating
  bands and session definition; and moves runtime authority hashes to an external
  manifest.

## 11. Process note

The first substantive review of the draft occurred before a freeze hash existed and
before any Campaign 1 outcome estimation. It identified several genuine design errors,
most importantly a post-treatment conditioning error in the original C6 confirmatory
outcome. Those errors were corrected in the design rather than rationalized after seeing
results. This history is preserved because it is the point of reviewing analysis plans
before estimation: the review process was allowed to change the plan while changes were
still epistemically clean.
