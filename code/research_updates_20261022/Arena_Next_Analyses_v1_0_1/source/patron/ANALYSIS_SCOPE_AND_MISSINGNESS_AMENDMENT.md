# Patron Wave 3B1: primary results and explicit missing outcomes

This v1.0.1 amendment is fixed after reviewing Wave 3A coverage and the September 11 profile acquisition, before estimating Patron associations in the new target sample. It defines the August-only source-family analysis and a separately dated supplemented sensitivity. It implements the requested sample reset and prioritizes the paper's main estimates. It is not a new preregistration.

## Authenticated input and the coverage finding

Wave 3A reconstructed 3,224,173 chooser histories on 41,534,331 certified pool nonadjacent opportunities. The original acquisition functions and seed selected 276,482 any-kind accounts and 829,437 never-kind controls, independently of profile availability or Patron outcomes. The primary fair-kind target contains 212,859 focal kind accounts and 638,569 controls, totaling 851,428 accounts. Eight focal groups have two controls; all other primary groups have three.

Of this primary target, 77 controls were never queried in August. Thirty kind accounts and 100 controls were queried but did not return profiles. Hence 851,221 target accounts have observed outcomes and 207 do not: 0.0243121% missing. All focal kind accounts were included in the August acquisition plan. The additional unqueried controls are 0.0120582% of the target control arm.

The Wave-3A gate remains `BLOCKED_INCOMPLETE_AUGUST_PROFILE_COVERAGE`. This package does not re-label it as complete. It defines available-outcome analyses and missing-outcome sensitivities on the already frozen target. No targets are replaced, no matches are redrawn conditional on available profiles, and no missing account is coded as a non-Patron. The August-only cohort contains only August observations. The separately labelled sensitivity below appends the recovered September profiles.

## Completed gap fill and separately dated sensitivity

The authenticated gap-fill report is `POOL_MAIN_PATRON_GAP_FILL_RESULTS_20260911T153303Z_2c3aaceee64b.zip`, SHA-256 `99938ce0e0ebc2306e449148f76b50d87771677805ea4c35afc45066889b8737`. Its ZIP sidecar, CRC and all four listed files were verified. It completed three successful API rounds in 144.863 seconds.

All 122 controls absent from the August plan returned profiles, including the 77 primary controls. None of the 163 earlier nonreturns returned in the three new rounds. All recovered profiles were observed at `2026-09-11T15:30:44.718996+00:00`. These observations do not establish August Patron status. They are appended to a private derived profile table; an overlap with an existing August username is a fatal error. The original August file must retain its authenticated SHA-256 throughout.

| Cohort | Primary fixed target | Available primary profiles | Eligible under original focal-group rule | Primary unknown outcomes |
|---|---:|---:|---:|---:|
| August only | 851,428 | 851,221 | 851,131 | 207 |
| August plus September gap fill | 851,428 | 851,298 | 851,208 | 130 |

The supplemented primary model contains 212,829 kind accounts and 638,379 controls. Thirty missing kind profiles and 100 missing controls remain. As in the August cohort, 90 available controls are excluded because their focal kind profile is unavailable. The remaining missing primary outcome fraction is 0.0152685%. All broad-target returned accounts total 1,105,756, including 122 September observations; the broader state diagnostic keeps its original broad-target scope.

The supplemented sensitivity repeats only the paper's core results: main match-cell FE and full-control models under HC1/CR1, and the threshold-four fair-versus-clearly-worse horse race under HC1/CR1 (six fits). The documented corrected-date versions of the main full-control and threshold-four models add four fits. All ten are labelled `mixed_date_profile_gap_fill_sensitivity`, with corrected-date labels where applicable. Profile controls for the appended accounts come from the same September observation as their outcomes. All behavioral histories, eligibility, matching cells and group assignments still come from Wave 3A.

Full-target raw and FE-only outcome bounds are computed separately for this mixed-date cohort. Its raw identification interval has width `100*(30/212859 + 100/638569) = 0.0297539` pp. This is a statement about the mixed-date outcomes. It does not reduce the uncertainty about the unavailable August outcomes without an extra temporal-stability assumption, which this package does not make.

The baseline 38 August fits are retained, with ten focused supplemented fits. The new run makes no API calls. Existing complete-response nonreturns remain missing; more repeated bulk fetching is not a prerequisite for the core available-outcome analyses.

## Main analysis and missingness

The original v1.0.1 primary sample rule is retained: returned profiles in fair-kind focal groups, provided the focal kind account itself returned. The 30 focal nonreturns each have three returned controls; those 90 controls are excluded by that rule. Thus the anticipated main available-case sample is 212,829 kind accounts and 638,302 controls (851,131 total), subject to exact reproduction checks. All classification, group membership, opportunity counts and match cells use the new panel.

The main FE coefficient is an association among these available profiles. Missingness is not assumed random merely because its fraction is small. The package reports:

1. All fixed-target outcome missingness, separately for unqueried accounts and queried nonreturns, with their associated new-panel opportunities and kind draws.
2. Raw rates and match-cell-FE estimates for the main source-family sample.
3. A complete-four-account-group sensitivity, as in the original family. This additionally excludes the eight structurally two-control groups.
4. The raw contrast and match-cell-FE estimate on all available primary target profiles, including controls whose focal kind profile was unavailable.
5. Sharp binary-outcome bounds for the raw difference and the match-cell-FE-only coefficient over **all 851,428 fixed target accounts**. Unknown kind outcomes are set to 0 and unknown control outcomes to 1 for the lower endpoint, with the assignments reversed for the upper endpoint. For the FE coefficient, cell weights are `n_kind * n_control / (n_kind + n_control)` fixed from the complete target, not observed-outcome counts.

These endpoints quantify uncertainty about missing outcomes. They are not confidence intervals, not assumptions about the missing accounts, and not bounds for regressions with unavailable profile covariates. The raw interval's width is known before reading outcomes: `100*(30/212859 + 177/638569) = 0.0418121` percentage points. Its location requires the observed Patron counts. The 77 unqueried controls contribute 0.0120582 pp to this width.

## Frozen estimation functions and sample scope

The original v1.0.1 chooser-cache, feature-preparation, absorbed-OLS and contrast functions are bundled unchanged. The wrapper authenticates the new sample and Wave-3A checkpoints directly, rather than invoking old full-panel entry points or bypassing their authority checks with `--fixture`. A new bridge takes design and history fields from Wave 3A and profile covariates from the explicitly selected profile cohort: August only for the baseline, or August with September additions for the sensitivity. Cache conservation must reproduce the new target histories in both cases. Original August snapshot outcome semantics are checked against their original certified totals; separate typed-outcome checks govern the supplement.

Main models: match-cell FE, covariate ladder through all controls, HC1 and CR1 inference, complete groups, no-BOT sensitivity, original common-support restrictions, and the three stored one-to-one control slots.

State heterogeneity: the original fair versus clearly-worse horse race and its covariance-based contrast at thresholds 2, 4, 5 and 10 opportunities in both states. The threshold-four specification is the main paper family, with HC1 and CR1. As in the source family, this analysis uses the returned broad any-kind target cohort, not just fair-kind focal groups; excluding losing-only groups would change the diagnostic.

Dose and price: the original broad-target dose bins and continuous companions, and separate costly/nonnegative fair-kind indicators at the frozen minimum-opportunity thresholds. These are secondary.

The old labels `confirmatory` are reported here as `frozen_primary_family_new_sample`: these were the historical primary models, not a fresh confirmatory design.

## Corrected dates remain a separate sensitivity

The primary lineage retains the original v1.0.1 date construction for exact specification comparability. A separate output family applies the documented post-certification correction: missing creation/last-seen timestamps remain missing before within-cell median imputation and missing indicators. It repeats the full-control main model and threshold-four state diagnostic with HC1/CR1. Its coefficients must not silently replace or be mixed with the primary lineage.

## Deliberately pending

To put the main writing results first, this package does not run the 100 deterministic full-control rematches, five-bin post-certification chooser family, Patron opportunity-level models, ply/dyad sensitivities, or integrated manuscript figures. Old numbers for those analyses remain stale. C9 fresh conditional randomization and C13, if its ambient-exposure claim is retained, remain separate outstanding dynamics work.

All interpretations remain descriptive and within Lichess. The snapshot does not identify when Patron status began or whether it was self-funded. No causal effect of kindness on Patron adoption is claimed.
