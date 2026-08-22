# Dynamic Prosociality Analysis Plan: arm-partition amendment v1.0.2

Date: 2026-08-22 UTC  
Applies to: `Dynamic_Prosociality_Analysis_Plan_v1_0_1_2026-08-21.md`  
Scope: A1/A3 recipient arm eligibility only

## Reason for the amendment

The first v1.0.0 core execution failed closed before chronology scanning or model
estimation. Its recipient-panel QA found 4,067 index exposures that were neither a
certified kind draw nor a chooser win. No A1, A3, B1, balance, encouragement,
common-support, propensity, or arm-specific descriptive result had been estimated.

The discrepancy arose because the feasibility implementation used `kind_draw` as a
binary treatment and implicitly treated every zero as a claimed win. Stage 05/07's
authoritative outcome contract is richer:

```text
timeout_draw + timeout_chooser_win + timeout_chooser_loss = 1
outcome_kind_draw = timeout_draw AND chooser_has_mating_material
timeout_draw_no_mating_material = timeout_draw AND NOT chooser_has_mating_material
```

Thus `NOT kind_draw` is not synonymous with `timeout_chooser_win`.

## Corrected recipient-arm rule

The index event remains each account's first fair/competitive, ordinary,
non-tournament-like Stage 07 disconnection. It is selected before applying the arm
rule and is not reranked after exclusions.

```text
received_mercy = 1  if outcome_kind_draw = 1
received_mercy = 0  if timeout_chooser_win = 1
arm_eligible = outcome_kind_draw OR timeout_chooser_win
```

An index event is excluded from every mercy-versus-claim analysis if it is either:

- a draw without chooser mating material; or
- a chooser loss.

These rows remain in the private index-event audit so the exclusion is visible and
reproducible. They are not recoded as claims, and the account is not replaced by a
later exposure. The correction therefore does not change which already-defined
treated or claimed index events enter the design.

## Certified totals that triggered the correction

The v1.0.0 fail-closed tuple established the following arm-blinded index-event totals:

```text
all first index exposures                 2,556,782
certified kind-draw receipts                 78,936
certified chooser-win claims              2,473,779
non-arm index outcomes                        4,067
arm-eligible index exposures              2,552,715
```

The corrected producer must reproduce these totals and must additionally verify that
every non-arm row is exactly a certified no-mating-material draw or chooser loss.
Subcategory totals are reported rather than assumed.

## Consequences for estimation

- Every A1/A3 treatment contrast, balance table, common-support calculation,
  cross-fitted recipient propensity, and encouragement first stage is restricted to
  `arm_eligible` index events.
- The arm-blind A3 chronology gate, its selected `log(1 + games within 30 days)`
  primary outcome, the private gate cache, and the dense index-event row ordering are
  unchanged. The gate remains valid because it neither read treatment nor produced an
  arm comparison.
- Chronology linkage may retain all index rows for auditing, but non-arm rows cannot
  contribute to an arm-specific estimate.
- B1 is unchanged. Its outcome is the certified `kind_draw` indicator over actual
  fair chooser opportunities and does not use the recipient treatment partition.
- The original three-test Holm family and all other v1.0.1 specifications remain
  unchanged.

## Interpretation and disclosure

Reports must disclose the total and subcategories of excluded index outcomes and say
that the estimand compares receipt of a certified kind draw with being claimed
against at the preselected first index disconnection. This is a semantic correction
to the treatment partition, not an outcome-responsive model change.
