# Matched cohort and comparison specification

Version 1.0.0, 26 September 2026. This package freezes a new matched comparison before running it. Earlier aggregate results and pre-policy model diagnostics were already reviewed; this is not historical preregistration.

## Population and opportunity selection

For each of ultrabullet, bullet, blitz, rapid, and classical, construct the roster from all same-speed rated-game start histories available strictly before 18 November 2025 07:22 UTC. An account qualifies with at least 100 prior starts, at least 365 days since its first observed same-speed start, and at least one start in each of the four preceding half-open seven-day intervals. No later activity, post-policy opportunity, or grant is needed to qualify. Observed history age is not verified account age.

Roster membership is fixed at this cutoff and applied to chooser accounts on both sides of the event. Contemporaneous own and opponent RD must both lie in [45,110]. The earlier panel's rolling `regular` flag is deliberately not retained. This design therefore changes the earlier sample; its mechanical shifts need not reproduce the rolling-cohort estimates. Selecting the cohort late in the pre-period may affect earlier composition and stationarity.

The primary board state is −100 ≤ disconnected-player centipawn evaluation < 100. Clearly losing, cp ≤ −300, is secondary. Both require ply > 10 and opponent-minus-chooser displayed rating gap in [−575,575). The inherited opportunity producer's timeout, material, and disconnected-player-clock rules remain in force. Missing clocks retain the fitted missing-value controls; observed disconnected-player clock < 5 seconds fails the window gate. Nonfinite required histories are excluded and counted.

Main membership requires explicit recovered game source `pool` and previous status `not_mutually_adjacent_observed`. This is the existing observed previous-adjacency screen, not verification of literal immediate rematches. No next-game relationship selects the sample. Recognized ambiguous-start and left-boundary statuses are excluded under the original predicate and remain visible in the membership audit; missing or unrecognized pool classifications fail coverage. Unknown or conflicting source is not recoded as non-pool. The pinned pre-policy panel already carries the same source/screen selection.

Within every candidate window, any unresolved source, unmapped pool adjacency, or sub-five-second clock violation among fixed-roster/RD-eligible narrow-state opportunities withholds that window's behavioral comparison. This strict gate does not substitute a known-source subset or an all-source comparison. Source audit failures outside the color window remain reported but do not automatically invalidate a complete earlier window.

## Timing, histories, and weights

All event calculations use explicit UTC milliseconds. Weeks start Monday at 00:00 UTC. The implementation bracket starts 18 November 2025 07:15 UTC; the carried implementation switch is 07:22 UTC. The announcement is 22 December 2025 22:35 UTC. These are inherited working event times, not new deployment verification.

The comparison uses the eight complete preimplementation weeks (22 September–16 November) and four complete unannounced weeks (24 November–21 December). The implementation-crossing week is omitted. Announcement-crossing week 22–28 December is omitted from every behavioral contrast. Announced sensitivities contain one complete week before 7 January or four before 30 January. Pooled sensitivities combine the four unannounced weeks with those one/four announced weeks. The skipped calendar weeks remain gaps in bootstrap offsets.

January 7 and January 30 are scenario endpoints, not certified mechanics censors. The primary unannounced window has a bounded announcement interpretation but no general certification that every concurrent process remained stable. Announced and pooled windows have greater exposure to later-mechanics uncertainty.

Historical features count recorded same-speed starts strictly before the focal chronology event. The API time is reconciled to that game's chronology start within 1,000 ms, excluding the focal game and every simultaneous start. Older monthly summaries plus local starts preserve exact prior counts, first-start age, and inactivity. No-prior-history post rows use zero days/count; earlier rows with missing history controls are excluded and counted.

For every week, compute separate White and Black grant probabilities over matched opportunities, then White minus Black in percentage points. Average weekly gaps with equal week weights. The observed contrast is post mean minus eight-week pre mean. All model forecasts, noise calculations, and behavioral contrasts use the same color orientation and equal-week convention. These are opportunity-weighted within each color-week, not equal-account estimands.

## Frozen models and transported baselines

Use the repaired RD110 full fits for seven candidates: cost, loss, curved, framing, strength, strength_loss, and strength_framing. No candidate coefficient or curvature is re-estimated. Both own and opponent premiums are recalculated under old/new rules at the same stored rating/RD state. This is the anchored no-volatility/no-regression calculator; missing internal fractional ratings are not recovered.

The existing fit lacks future month coefficients. Carry the final fitted October 2025 month effect into November–January. This is an explicit transport choice. All other fitted controls use each opportunity's measured values, including contemporaneous histories and rating state; post-policy histories may themselves respond to behavior. The computation conditions on the observed opportunities and states rather than estimating a fully counterfactual population.

Calibrate chooser intercepts using only opportunities before 18 November 07:15. Account targets use 20 pooled-rate pseudo-observations, followed by one global intercept adjustment matching the pre-policy grant rate. Accounts without a pre-policy matched opportunity use the pooled pre-calibrated intercept. Baseline sensitivities of 5, 100, and pooled-only are also produced for curved, framing, and strength. Report fallback exposure and pre-rate conservation. Calibration excludes every post-policy choice, and forecast file hashes are sealed before post-choice aggregation.

For each model/window, report three quantities in percentage points:

1. Mechanical shift: post mean White-minus-Black difference in new-versus-old predicted probability on the same states.
2. No-policy composition change: post-minus-pre gap predicted under the old rule, holding model coefficients and pre-calibrated baselines fixed.
3. Total forecast at awareness a: composition change + a × mechanical shift.

Awareness a ∈ {0.05,0.10,0.20,0.50,1.00} is a mixture/attenuation assumption, not an estimated awareness share. The full forecast is needed when comparing the raw observed contrast with predictions. Composition adjustment does not prove parallel counterfactual color trends.

The repaired pre-policy two-monthly-SE compatibility sets are carried as descriptive flags. Equal-state compatible models are curved, framing, strength, strength_framing, and strength_loss; all seven remain compatible in losing states. These sets are neither formal familywise acceptance regions nor statements of model truth. Tables flag comparisons between two compatible candidates.

## Conditional noise, power, and behavioral summaries

Use complete pre-policy weekly color gaps from 6 November 2023 through 26 October 2025 (103 weeks when supported). A missing week/color or fewer than 32 complete usable pre weeks prevents the noise-based comparison; no missing weeks are compressed away. Blocks of 4 and 8 contiguous pre weeks are sampled with replacement to generate 10,000 synthetic event calendars, preserving omitted implementation/announcement week positions. Center the simulated post-minus-pre differences. The 95th percentile of their absolute values gives a two-sided 5% critical magnitude.

The 80% minimum detectable effect and pairwise power use the less favorable of positive/negative shift directions. Mechanical-only power and total-forecast power are separate columns. Descriptive intervals invert the pre-noise distribution around the actual contrast. Model p-values compare observed-minus-total-forecast residuals with that distribution, with a finite-simulation adjustment. They are conditional point-fit checks, not unconditional model rejections; no multiplicity-adjusted selection is made across awareness values, baselines, models, or windows.

Fitted-parameter, curvature-selection, baseline-estimation, opportunity-composition, and awareness uncertainty are not propagated. The fitted model's in-sample use and fixed-cohort selection can also matter. Pretrend, lag-one correlation, and nine fixed placebo anchors are exported as stationarity diagnostics, not independent replications. This package cannot establish causal mechanism selection, consciousness, or motive shares.

## Calibration and exposure diagnostics

By period, state, speed, color, actual score, and rating-gap band, report observed displayed update coverage, signed error, MAE, and old/new-rule MAE. Near-equality draws, strict sign-flip gaps, and displayed ties remain separate. These diagnose anchored replay behavior; they do not certify internal fractional rounding or later deployment dates.

Count all observed rated-player starts of the fixed roster by speed, source month, week, and color, alongside active-roster accounts. Starts are additive across the cells. Distinct active-account counts are not additive across months or speeds and must not be summed as unique people. This is an exposure diagnostic, not a complete disconnect or incident denominator and not a source-pool denominator.
