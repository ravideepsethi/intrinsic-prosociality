# Remaining Patron analyses — pool-main Wave 3B2 v1.0.0

This package completes the outstanding Patron analysis families listed in the
Wave 3B1 status. It does not revise the manuscript or assert results before the
new run completes. All models use the certified 41,534,331-opportunity pool,
observed-nonadjacent panel (fingerprint
`a17c89d750cb4fdfdf84f950859e45c58b19996efae02045def68285e305cf30`).

## Outcomes and design

The source population is the frozen Wave 3A pool-main target set: 1,105,919
accounts. Of these, 1,105,634 have returned August outcomes, 122 were never
queried in August, and 163 were queried but did not return. The latter two
groups remain missing. September gap-fill outcomes are not mixed into these
August-only robustness families; Wave 3B1 already reports their separately
dated core sensitivity. No profile request, new account acquisition, or
imputation of missing Patron outcomes occurs here.

The existing Wave 3B1 design cache is authenticated against its configuration
and checkpoint, compared account by account to the authenticated Wave 3A
matches, and checked against its published support receipt. New five-bin
counts must reproduce every target account's total opportunities and grants.
Two core Wave 3B1 coefficients and standard errors must reproduce before the
100 control draws begin.

## Scheduled families

| Family | Specification | Outputs |
|---|---|---|
| 100 alternative controls | Original deterministic seed 20260826, replicate IDs 1–100, one of the immutable three control slots; match-cell FE and full-control HC1 fits | 200 fits, raw/adjusted replicate estimates, SEs, ranges and distribution summaries |
| Five-bin chooser companion | Original postcertification family; support thresholds 0, 2, 4 in every bin; exposure and full controls; min-4 CR1 | 7 fits, adjacent and endpoint contrasts, support counts |
| Price count/rate companion | Original postcertification family; thresholds 2 and 4 on both sides, exposure/full controls and min-4 CR1 | 10 fits and covariance-based costly-minus-nonnegative contrasts |
| Opportunity-level structure | Original three models: five-bin Patron interactions; favorable-price interaction within fair states; fair-state × price × Patron | 3 fits; HC1 and chooser-clustered CR1, with covariance matrices and derived Patron gaps |
| Ply checks | Each opportunity model with ply >4, >10, >20, and all rows with ply-band controls | 12 explicitly new sensitivity fits |
| Dyad appendix | Frozen whole-window focal-pair filters: all, singleton, fewer than 3, fewer than 5 games; reconstruct fair-kind signal and deterministic 1:3 rematches | 4 raw and match-cell FE comparisons with support counts |

The control draws retain the frozen missing-slot rule: if the selected slot
is unavailable, omit that entire 1:1 pair for that replicate. Do not substitute
a different slot or draw an unqueried account. Draw denominators are reported.
The main focal-return rule applies to the 100 draws. Full-control draws use
the frozen primary v1.0.1 feature construction; the five-bin and count/rate
companions use the addendum's corrected account-date handling.

Ply checks are new sensitivity analyses, not a retroactive confirmatory
family. Thresholds are strict (>4, >10, >20). Missing ply is excluded by those
thresholds and retained as its own category in the all-row ply-control model.
Bands are <=4, 5–10, 11–20, 21–40, 41–80, >80, and missing. The reference
category is the first observed band in lexicographic order. These are
opportunity-level checks; no new chooser classification based on later ply
is silently substituted into the primary matched design.

The opportunity cache includes ply bands solely to support these checks.
Ignoring that extra grouping variable is algebraically equivalent to the
original collapsed sufficient statistics. Synthetic expanded-row OLS/HC1/CR1
checks verify that equivalence, including chooser clusters spanning batches.
The original estimator is retained; its only extension serializes beta and
the two covariance matrices that it already computed. Derived gaps use the
full covariance matrix. An unsupported required term is marked not estimable.

The dyad count comes from the authenticated invariant 2,229,237,137-game
standard-rated census. Only new main-panel flags are created; the census is
not rerun or changed. Only the focal opportunity is dropped, not other games
involving either account. Whole-window frequency includes post-focal games,
so this is a descriptive sensitivity, not a pre-focal recognition test.
The frozen dyad appendix rematches within the new target pool before dropping
missing profile outcomes. It uses its own available-profile rule, rather
than the focal-return group gate of the primary design. Its all-row rematch
is a distinct benchmark and need not equal the primary matched coefficient.

## Interpretation and completion

Current Patron status is a same-platform correlate. Adoption dates, tenure,
gifted versus self-funded status, and causality are not identified. Optional
timing/churn work is not scheduled because these snapshots do not supply the
required history. These families do not form a new omnibus confirmatory or
Holm family. Use each source family's inference and label the new ply checks.

Checkpointed fits are never treated as complete without their hashes. A
failure exports a clearly labelled PARTIAL report with completed stages; it
does not make the final success claim. Required contrasts that cannot be
estimated are counted in the run status, which then reports completion with
estimability warnings instead of unrestricted completion. The final report contains aggregates,
model parameters, covariance matrices and provenance only. Private Parquets
and account/game-level rows remain on XT_Pro. Manuscript assembly remains a
separate step after reviewing the results.
