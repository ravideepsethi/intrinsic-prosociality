# Dynamic Prosociality: Post-Outcome Audit Supplement

Version: 1.0.0  
Date: 2026-08-22 UTC  
Status: frozen after the v1.0.2 primary results were observed  

## Scope and claim boundary

This is explicitly a **post-outcome audit supplement**. It is not a preregistration,
does not amend the frozen v1.0.1 primary analysis plan, and cannot change the identity,
ordering, p-values, or interpretation hierarchy of the three frozen primary tests.
The authenticated v1.0.2 estimates remain:

1. A1 total-path conditional choice;
2. A3 `log(1 + rated-standard games within 30 days)` selected by the arm-blind gate;
3. B1 `T_24h` among repeat granters.

The supplement completes diagnostics and secondary outputs that the frozen plan required
but the v1.0.2 aggregate result package did not contain. Every new estimate must be
labeled post-outcome and secondary.

## Authenticated inputs

- certified v1.0.2 public success receipt, SHA-256
  `bd64005162bf8f37f9488d47e95c2ea4dd946d1227e909930a42dd8e4904f009`;
- certified v1.0.2 private joined recipient panel, SHA-256
  `41ef57b3118ea7d3b0bfb7a5e19040bd82e7794aa54fb6b06625d7793921816d`;
- v1.0.2 producer, SHA-256
  `2dcf0dd19f7cfe8f694d348e6590df88083a37882404112229d6ef05ebc42713`;
- frozen v1.0.1 analysis plan, dated arm-partition amendment, certified Stage 07
  authority, and arm-blind A3 chronology gate already authenticated by that producer.

No Patron/profile input is read.

## 1. Recipient-centered pre-trend placebos

For recipients whose index exposure occurs at least 90 days after the Stage 07 sample
begins, reconstruct their fair chooser opportunities strictly before the exposure in
three non-overlapping windows:

- 61--90 days before exposure;
- 31--60 days before exposure;
- 0--30 days before exposure (strictly before the exposure timestamp).

Within each window report, using the frozen first-ever-pair, arm, common-support,
ATT-weight, exposure-cell, month-FE, residual-control, and exposure-chooser clustering
rules:

1. whether the recipient had any fair chooser opportunity;
2. whether the recipient made any kind grant, coding no opportunity as zero; and
3. the recipient's last fair choice in that window, conditional on an opportunity.

These are placebo associations of *future* mercy receipt with prior recipient behavior.
They are not treatment effects. A systematic positive pre-pattern weakens causal
language for A1; its absence is supportive but cannot prove exchangeability.
Report raw p-values and Holm-adjusted p-values within this nine-placebo diagnostic
family. This adjustment is separate from and cannot alter the frozen primary family.

## 2. Fine matchmaking-cell sensitivities

Re-estimate the frozen A1 total-path conditional-choice model and the frozen A3
log-engagement model under two additional exposure-time support/weighting designs.
Both retain the original exposure-state and month fixed effects and continuous exposure
controls.

### Supported fine cells

- mean opponent-pair rating in 200-point bands;
- canonical speed;
- UTC weekday; and
- UTC six-hour block.

Cells require at least five mercy and twenty claimed-against recipients.

### Very-fine cells

- mean opponent-pair rating in 100-point bands;
- canonical speed;
- UTC weekday; and
- UTC four-hour block.

Cells require at least three mercy and ten claimed-against recipients. This variant is
reported even if its treated retention is low; retention and cell counts must accompany
the estimate.

In each eligible cell, treated rows receive weight one and claimed rows receive the
mercy-to-claim count ratio. These are post-outcome robustness sensitivities, not new
primary estimands.

## 3. Exposure-chooser fixed-effect sensitivity

For A1, restrict to exposure choosers who contribute both mercy and claimed recipients
to the frozen conditional-choice sample. Re-estimate with exposure chooser, original
exposure-state cell, and exposure-month fixed effects, the frozen continuous exposure
controls, original ATT weights, and standard errors clustered by exposure chooser.

This removes stable observed and unobserved treatment-source heterogeneity within the
retained sample. It changes the population and does not establish random assignment.

## 4. Time to next rated-standard game

Using the completed all-game chronology, report the 30-day restricted mean time to the
next rated-standard game. Accounts with no event by 30 days are explicitly right-
censored at 720 hours. Report:

- adjusted difference in 30-day restricted mean time using the frozen A3 model;
- ATT-weighted arm means and medians;
- event and censoring counts by arm; and
- the unweighted and ATT-weighted pooled 30-day participation rates in the final
  first-ever-pair/common-support sample.

The original arm-blind gate used the full non-tournament first-exposure cohort and
selected log engagement before treatment was joined. The final-sample pooled rates are
diagnostic only and cannot reopen that frozen choice.

## 5. Reproducibility and privacy

The producer is plan/execute separated, authenticates all authorities, writes private
intermediate data only on XT_Pro, and publishes only disclosure-safe aggregates and
hashes. It performs no API request and no Git mutation. A failed or partial run may be
rerun; completed private checkpoints are authenticated and reused.
