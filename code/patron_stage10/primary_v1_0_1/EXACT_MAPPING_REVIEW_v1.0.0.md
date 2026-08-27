# Patron Stage 10 exact mapping review v1.0.0

Prepared 2026-08-27 after authentication and complete inspection of
`PATRON_STAGE10_INVENTORY_RESULTS_20260827T001414Z.zip`.

## Decision

`READY_FOR_AUTHENTICATED_PRODUCTION`

The certified inventory found every authority required for production. The apparent
absence of a `control_rank` column in the final profile snapshot is not a design gap.
It was caused by the inventory's literal candidate-name search. The operative stored
field is `control_slot`, and its semantics are established by both the certified plan
schema and the authenticated acquisition source.

Production must use the stored assignments. It must not rematch the primary sample.

## Authentication

- Inventory-results ZIP SHA-256:
  `02157d054b841b9c27fbc4e87a7b6465a0a86ab562876c7d81784807c8f3707a`
- All files listed in `report_file_hashes.tsv` reproduced their byte counts and
  SHA-256 values.
- Inventory verifier status: `PATRON_STAGE10_INVENTORY_VERIFIED_OK`.
- Files authenticated by the inventory verifier: 80.
- Profile snapshot SHA-256:
  `f42f28a6540a65c0a83f0da488663b4adddf60d1001daeed556f1ffbb961e238`.
- Stage 07 success-receipt SHA-256:
  `8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7`.
- Stage 07 producer SHA-256:
  `0411d4061ea9831c20449208a9782aaf668e160139918d106a2b7d63aaa56e6e`.
- Acquisition-plan success SHA-256:
  `2838aa942e20027561763855c387a454d74bb0a92d0a8b62ca47343511897e57`.

## Exact field mapping

| Concept | Certified field | Rule |
| --- | --- | --- |
| Normalized account key | `username_norm` | Lossless join to Stage 07 `chooser_username_norm` |
| Acquisition role | `acquisition_role` | Exactly `kind` or `control` |
| Immutable matched-set key | `matched_kind_chooser_id` | The kind chooser's normalized account key |
| Kind row | `control_slot=0` and `acquisition_role='kind'` | One per set |
| First control | `control_slot=1` | Frozen nested 1:1 result |
| Second and third controls | `control_slot=2,3` | Remaining frozen 1:3 controls |
| Exact-group flag | `exact_1to3_group` | Must be true |
| Selected-control count | `selected_controls` | Must equal three |
| Matching cell | `match_cell` | Fair-opportunity bin × modal normalized speed |
| Broad acquisition exposure | `ever_kind_any_state` | Used to create the acquisition universe; QA/secondary |
| Main fair-kind exposure | kind row with `ever_kind_fair_state=true` | Include that kind row and its stored controls |
| Clearly-worse diagnostic | `ever_kind_clearly_worse_state` | Joint horse race with fair-state kindness |
| Returned profile | `returned=true` | Patron outcome observed |
| Current patron | `returned=true` and `patron=true` | Optional API patron field present |
| Ordinary non-patron | `returned=true` and `patron=false` | Omitted optional patron field is valid API semantics |
| Nonreturn | `returned=false` | Patron outcome missing; never recode to zero |
| BOT diagnostic | `upper(title)='BOT'` | Report include- and exclude-BOT versions without rematching |

## Stored assignment proof

The authenticated acquisition planner ranks kind and never-kind accounts separately
inside `match_cell` using SHA-256. Controls are allocated without replacement in
rounds. For a cell with `n_kind` kind accounts:

1. `target_kind_rank = ((control_rank - 1) % n_kind) + 1`;
2. `control_slot = floor((control_rank - 1) / n_kind) + 1`;
3. every kind account receives slot 1 before any receives slot 2; and
4. every supported kind account receives slot 2 before any receives slot 3.

The final snapshot copied `control_slot`, `matched_kind_chooser_id`,
`selected_controls`, `nested_1to1_available`, and `exact_1to3_group` into every row.
The separate plan Parquet retains both `control_rank` and `control_slot`. Thus no
ordering reconstruction is needed or permitted.

The certified totals prove complete exact support:

- 326,468 kind-role accounts;
- 979,404 control-role accounts;
- 979,404 = 3 × 326,468; and
- 1,305,872 distinct planned and normalized accounts.

## Missingness mapping

There are 1,305,683 returned profiles and 189 explicit nonreturns:

| Role | Requested | Returned | Nonreturned | Current patrons |
| --- | ---: | ---: | ---: | ---: |
| Kind | 326,468 | 326,427 | 41 | 1,743 |
| Control | 979,404 | 979,256 | 148 | 3,153 |
| Total | 1,305,872 | 1,305,683 | 189 | 4,896 |

The production package first reports return rates by role and match cell. It then
excludes nonreturns from patron-outcome estimation. It retains returned profiles with
missing age, recency, playtime, game-count, or per-pool fields using within-match-cell
median imputation, explicit missing indicators, and a global median only when an
entire cell lacks a value.

## Main estimand and samples

The acquisition universe was intentionally broad: every chooser ever kind in any
certified fairness state plus three never-kind controls. The paper-facing main
estimand is narrower:

1. identify kind rows with `ever_kind_fair_state=true`;
2. retain those kind rows and their immutable `control_slot=1,2,3` controls;
3. require the kind profile to have returned;
4. treat a missing control patron outcome as missing rather than zero;
5. use all available returned controls in the primary precision-oriented 1:3 result;
6. report complete four-account groups as a sensitivity; and
7. report all three frozen one-to-one selections separately.

The primary model is a match-cell fixed-effects linear probability model in percentage
points with HC1 standard errors. Match-cell CR1 inference is a conservative
sensitivity. The full covariate ladder, common-support variants, BOT sensitivity,
three fixed 1:1 slots, and 100 deterministic valid 1:1 selections from each immutable
three-control set are all retained.

## Support rules fixed without patron outcomes

- Legacy common support: the kind chooser has 2–20 fair opportunities.
- Duration-scaled common support: the kind chooser has 2–40 fair opportunities.
- Overlap-cell sensitivity: at least 20 fair-kind kind groups and 60 associated stored
  controls in the certified match cell.
- Dose bins: 0, 1, 2–4, 5–9, and 10+ fair-state kind draws.
- Diagnostic horse race: at least four fair and four clearly-worse opportunities,
  with thresholds 2, 5, and 10 retained as robustness checks.
- Price-side diagnostic: at least 2 and at least 4 fair opportunities on each of the
  costly and nonnegative draw-payoff sides.

## Interpretation boundary

The profile acquisition is a fixed current snapshot taken on 2026-08-26. It does not
recover when patronage began. The analysis can establish whether private kind-draw
behavior is associated with another costly decision on the platform. It cannot show
that kindness caused later patron adoption, cannot establish event order, and must not
be described as an adoption analysis.

## Privacy boundary

The snapshot, chooser cache, opportunity-cell cache, normalized account keys, and raw
profile fields remain private on XT_Pro. Transfer outputs contain only aggregate
support, coefficients, standard errors, model receipts, hashes, and redacted QA. No
username, account ID, game ID, raw JSON, country/location field, free text, or row-level
profile data is authorized for transfer or publication.

