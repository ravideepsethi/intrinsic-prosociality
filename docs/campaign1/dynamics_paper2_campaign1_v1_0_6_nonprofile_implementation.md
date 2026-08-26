# Dynamics Paper 2 Campaign 1 v1.0.6 non-profile implementation record

**Frozen before C6, C7, C10, C12, or C13 outcome estimation:** 2026-08-25  
**Scope:** implementation resolution only. The v1.0.0 estimands, v1.0.1-v1.0.3 amendments, v1.0.5 C1 correction, epistemic labels, support gates, and Holm family remain unchanged.

## 1. Execution authorization and reporting

All scientifically useful analyses are to be run when their certified inputs exist. No result is reserved for later. Confirmatory, secondary, exploratory, and outcome-informed analyses retain those labels; favorable, null, and unfavorable estimates are all exported. Technical authentication and support gates remain fail-closed.

The incomplete profile snapshot blocks only C4, C5, C11, and C14B. It does not block C6, C7, C10, C12, or C13. No profile or Patron field is read by this package.

## 2. C6 rated-game denominator and zero-activity rule

The frozen C6 primary is the individual recipient's clearly-losing timeout-disconnection count per 1,000 rated games in the next 90 days. The implementation uses the certified A1 first-pair/common-support/90-day-follow-up cohort and:

1. estimates the frozen normalized primary among recipients with at least one subsequent rated game, because a rate with a zero denominator is undefined;
2. reports a zero-coded nonreturner sensitivity (`0` when both event and game count are zero), explicitly labeled as a constructed unconditional contribution rather than a literal individual rate;
3. reports an ATT-weighted ratio-of-sums arm diagnostic;
4. reports the unnormalized clearly-losing event count for the full eligible cohort as the mandatory sensitivity; and
5. estimates and displays the 90-day rated-game denominator effect and arm means.

The primary remains unconditional on a later timeout-disconnection. All recipients with rated-game denominators but zero timeout events enter with a zero event rate.

The retained secondary table is deliberately exhaustive rather than selective: all-timeout and clearly-losing counts/rates, any-event indicators, clearly-losing shares, and the corresponding tournament-exclusion diagnostics are all emitted whether favorable, null, or unfavorable.

The treatment-blind support gate is frozen before any arm-specific C6 outcome is read: at least 4,000 pooled eligible recipients with any later timeout-disconnection and at least 4,000 pooled clearly-losing timeout-disconnection events. If either condition fails, C6 is demoted to secondary and removed from family D before treatment is joined.

Later timeout events use the complete Stage 07 timeout-opportunity panel, with the certified `clearly_worse` rule (`engine_eval_cp_disconnected <= -300`). The primary includes tournament-like events because the frozen wording says all later timeout-disconnections; an exclusion sensitivity is also reported.

## 3. C7 prior-pair orientation and category rule

The focal chooser can reciprocate only an action previously taken by the current opponent toward the focal chooser. A qualifying historical decision therefore requires reversed roles: the focal chooser was previously the disconnected player and the current opponent was the chooser.

The primary category is the latest prior reversed-role arm-eligible timeout decision before the focal game:

- `prior_benefactor`: latest decision was a kind draw;
- `prior_claimer`: latest decision was a claimed chooser win;
- `prior_other_timeout`: latest reversed-role timeout was outside those two arms; and
- `prior_meeting_no_reversed_decision`: the pair met before, but no reversed-role Stage 07 decision is observed.

The support gate counts benefactor-facing focal fair opportunities without reading the focal kind outcome. At least 1,000 are required for adjusted estimation. Sensitivities report any-prior-benefactor/any-prior-claimer histories, histories with conflicting prior decisions, and a same-speed prior-decision restriction. The primary comparison is benefactor minus claimer with chooser fixed effects and the frozen current-state vector.

## 4. C10 completion rules

The denial decay clock reports 7/14/30/60/90-day symmetric pre/post changes. The main display uses recipients with at least one fair opportunity on each side and a common 90-day endpoint-eligible cohort so horizons are comparable. Minimum-four-opportunity and horizon-specific endpoint-eligibility versions are retained as sensitivities. Existing certified 30/60/90 results are reproduced and checked where their exact source cache is available.

The behavioral channel reports the claimed arm's C6 event levels, normalized rates, event shares, and the mercy-minus-claim contrasts from C6.

The personal-slight test uses the certified exposure-time leave-pair-out chooser kindness propensity with at least ten prior pair-excluded opportunities. It reports both (i) the propensity slope within claimed recipients and (ii) a pooled claim-by-propensity interaction with main effects, A1 ATT weights, exposure-cell and month fixed effects, current-state controls, and exposure-chooser clustering. These analyses are exploratory.

## 5. C12 recipient-history sample and bins

C12 uses the pre-existing deterministic 2% whole-user chronology sample (`hash(user_id, 2026082202) % 50 = 0`) applied to the disconnected recipient. For sampled recipients, `user_events` contains the complete canonical all-rated-game history, so cumulative games strictly before the focal game are exact. This avoids a new full-history rebuild and preserves the frozen authority. The sample restriction and support by disconnected-player rating band × speed are reported.

Primary deciles are formed within disconnected-recipient rating band × speed. Ties are broken deterministically by the focal game identifier hash, never by the kindness outcome. The primary uses deciles 1-2 versus 9-10, with deciles 9-10 as the reference, chooser fixed effects, current-state adjustment, and cell/calendar controls. The full decile profile, `log(1 + prior all-pool games)`, chooser-rating-band splits, and same-speed cumulative-game sensitivity are all reported.

## 6. C13 time, leave-one-out, and controls

The focal decision time is `api_last_move_at_ms`, matching the certified Wave 0 field mapping. A complete UTC day ends at 00:00 UTC before the focal day.

The leave-one-chooser-out identity is the certified Wave 0 chooser field, `chooser_username_norm`; stable numeric chooser IDs remain the fixed-effect and clustering key. This distinction preserves the exact prior denominator audit while keeping inference on the established account identifier.

The primary ambient exposure is the other-chooser kind rate in the same speed × chooser-rating-band cell during days `t-28` through `t-1`. The focal chooser's numerator and denominator are both removed. The frozen 5,000-other-opportunity threshold is applied before the focal outcome is read.

The model includes chooser fixed effects, speed × chooser-rating-band cell effects, UTC calendar-week effects, engine-evaluation-bin effects, hour-of-week effects, and the frozen numeric current-state vector. The coefficient is reported for a one-percentage-point ambient-rate increase. Quartile profiles are adjusted with the same design.

Sensitivities include 14- and 56-day windows, speed-only and speed × rating-band ambient definitions, and a 28-day window separated from the focal day by a seven-complete-day washout (`t-35` through `t-8`). All C13 estimates are associations, not causal peer effects.

Because the author directed that useful analyses not be held for later, the package also retains explicitly exploratory, non-confirmatory C13 diagnostics fixed here before the ambient numerator is read: a quadratic ambient-rate companion and the primary 28-day slope separately by chooser rating band and speed wherever at least 1,000 supported rows and 100 chooser clusters exist. Every attempted subgroup is governed mechanically by those support thresholds; none may enter Holm family D.

## 7. Privacy and non-interference

Private Parquet checkpoints remain under the dedicated XT_Pro state root. Public outputs contain aggregate tables, diagnostics, hashes, and source only—never identifiers or row-level data. The package performs no API call, profile read, chronology rebuild, Patron read, Git mutation, or mutation of earlier result trees.
