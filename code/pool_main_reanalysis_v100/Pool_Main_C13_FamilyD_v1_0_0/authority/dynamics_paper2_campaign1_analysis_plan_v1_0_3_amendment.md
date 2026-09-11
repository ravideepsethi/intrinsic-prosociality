# Dynamics of Intrinsic Prosociality — Campaign 1 Analysis Plan

## v1.0.3 Pre-Outcome Technical Amendment: Session-Timestamp Operationalization

**Date:** 2026-08-24
**Status:** freeze-ready pre-outcome technical amendment
**Base plan SHA-256:** `ded9965994b6c00ed613adc90eaff3f976b257e9eb6dafdda61819916dde49fe`
**v1.0.1 amendment SHA-256:** `01c0ed96bfca62b1659a98d978bedaaf9a4540fcdc5a30a075e2f032e35e05ee`
**v1.0.2 amendment SHA-256:** `7eeca3ab8591620a196badbd1b9d3184236d67a031cf9eff06b76584995c0049`

This amendment is adopted before inspection of any C1, C2, or C3 outcome estimate.

## 1. Reason

The frozen plan defines a session as consecutive rated games separated by less than
30 minutes, described as a previous-game-last-move to current-game-first-move gap.
The certified all-game rating/replay chronology is a header/replay chronology whose
universal timestamp authority may provide only one authenticated game-event/start
timestamp rather than an explicit end timestamp for every rated game.

Campaign 1 must not manufacture game-end timestamps or infer them from nominal time
controls.

## 2. Operational rule

For C1-C3:

1. If the certified user-history layer provides authenticated explicit game-start and
   game-end timestamps for all required observations, use the original end-to-start
   gap definition.
2. Otherwise, use the certified chronological event/game-start timestamp and define a
   session by consecutive game-start gaps less than 30 minutes.
3. Preserve the frozen 15-minute and 60-minute sensitivity definitions under the same
   timestamp convention actually used by the primary.
4. The production output must state which convention was used.
5. No mixed convention is permitted within one estimate.

The start-to-start implementation is an operational measurement fallback, not a claim
that game duration is zero. Its limitation must be reported, especially for slower time
controls.

## 3. Scientific interpretation

C1 and C2 remain within-person state-dependence tests, not causal effects. C3 remains
exploratory. The hypotheses, current-state controls, chooser fixed effects, chooser
clustering, Holm-family membership, and all other Campaign 1 rules are unchanged.

This amendment makes no change to any previously inspected Campaign 1 result.
