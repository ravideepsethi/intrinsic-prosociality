# R7: Balance in the literature's form, the environment model on the headline rows, and entry composition

8 October 2026 · Specification v1.0 · Not a completed analysis. Every fit here is a diagnostic specified after the reviewed Run 2, environment, and Phase-050 results.

## 1. Purpose and interpretation fixed before the results

Three deliverables, in priority order.

**A. Balance in the form leniency designs report it.** One regression of the treatment on all pre-exposure recipient traits and one regression of the instrument on the same traits, each with a joint test, plus a predicted-outcome row that converts whatever imbalance exists into implied reduced-form bias. The current package reports balance trait by trait with the trait as outcome; that form stays in the appendix. The joint form goes in the main text.

**B. The opponent-environment controls on the headline rows.** The environment ladder was run on 1,860,351 exposures that have both a supported competitive-only score and a complete environment history, with the competitive-history controls. The specification under which assignment is conditionally as good as random should be estimated on the headline cohort itself, with the headline controls, so the two are comparable row for row. This is a candidate headline. The decision is made after review, not by this run.

**C. Entry composition.** The score predicts entry into the exposure sample (−0.0118 pp per reference SD on a 0.275 percent base in the 7,371,688-game frame). The question is whether the exposures removed at the margin differ in prior granting from the rest, and in which exit classes the margin lives.

Rules that bind every part:

- Keep the current pooled-score headline on S0. Nothing is promoted for a larger coefficient, a smaller p-value, or better balance.
- All intervals are nominal. No sequential or stopping guarantees.
- Generated scores are fixed. Inference is the shared-account-or-exposure-date CR0 convention.
- Units: percentage points per reference score SD (0.0594 pooled; the competitive-only reference SD where that instrument is used). Balance coefficients in trait SD per native residual-score SD, with the native SD in every row. Raw coefficients retained.
- Author treatment, quarantines, chronology, cutoff and pair-exclusion rules are those of the Run 2 environment package (`receipt_original_author_clean` cohort objects). No new exclusions, no API or network calls, no Stockfish searches. Part C uses recorded moves and clocks only.
- Unsupported histories are left missing, as in Run 2, except under the explicit indicator convention of B2, which is stated there and reported separately.

## 2. Frozen inputs and reproduction gate

| Object | Definition |
|---|---|
| S0 | 2,682,330 headline exposures, 1,625,389 recipients, as reconstructed and author-treated in the Run 2 environment package |
| F50 | 7,371,688-game entry frame, 90-day eligibility, all endings (Phase-050; row set `83ec8b2d5b1b9836…`) |
| O50 | 4,764,089-game ordinary-ending frame (Phase-050; row set `f303f4a5a6af0090…`) |
| S0-CS | 1,914,886 competitive-supported rows of S0 |
| S0-CSE | 1,860,351 competitive-and-environment-supported rows of S0 |
| Fixed effects | month × exact time control × pair-mean-rating cells; exposure-date; hour-of-week |
| X0 | `recipient_rating, rating_gap, rating_gap_square, abs_rating_gap, log_opponent_prior_decisions, log_opponent_prior_counterparts, opponent_history_expected_rate, fair_history_present_90, log_fair_90, kind_ever_90, kind_rate_90, log_disconnect_90, log_receipt_90, log_volume_30, log_claim_90` |
| X0-NH | X0 without the eight recipient-history terms (the first seven names above) |
| XC | X0 + `competitive_expected_rate, log_competitive_decisions, log_competitive_counterparts` |
| ENV | `log_opponent_games90, opponent_observed_disconnect_rate, opponent_observed_chooser_rate`, 90-day window ending seven days before the exposure month, current pair excluded from numerators and denominator, both players author-clean, unsupported when the window is incomplete or the other-opponent denominator is zero |
| T30 | the seven recent traits: `fair_history_present_30, log_fair_30, kind_ever_30, kind_rate_30, log_disconnect_30, log_receipt_30, log_claim_30` |
| T15 | T30 plus the eight recipient-history terms of X0 |
| D, Y, R | receipt indicator; later-grant indicator (zero for a complete window without a choice); reached-a-choice indicator |

Reproduce before any new fit, from archived full-precision objects, not manuscript rounding:

- Panel A headline on S0: first stage 6.912 (0.040); reduced form 0.02039 (0.009); 2SLS 0.295 (0.127); AR [0.044, 0.545]; first-stage F 30,430.
- Primary balance: joint Wald on T30, χ²(7) = 11.746, p = 0.109; `kind_rate_30` 0.000202 (0.000457).
- Environment ladder on S0-CSE: 2SLS 0.294 (0.147) → 0.285 (0.147); reduced form 0.02234 (0.01120) → 0.02166 (0.01120); first stage 7.606 → 7.599; joint p 0.2007 → 0.7270.
- Entry on F50 with X0: `analysis_entry_90` −0.01180 (0.00212), mean 0.2747; `recipient_disconnect_main` −0.02668 (0.00378), mean 0.8995; `active_timeout` −0.09417 (0.00560), mean 1.8900; joint balance χ² 7.815, p = 0.349.
- Placebo on O50 with X0: −0.00137 (0.00703), mean 1.9996.

## 3. Part A — balance in the literature's form

**A1. Joint regressions without the history controls.** On S0, with the fixed effects and X0-NH only, estimate three regressions on the same rows, each with all fifteen traits T15 entered jointly, each trait standardized to unit SD on the estimation rows:

- (1) D on T15; (2) Y on T15; (3) the pooled score on T15, score in native residual-SD units after the same fixed effects and X0-NH.

Report for each column every coefficient and SE, the joint Wald χ² and p on all fifteen traits, and the same test on the T30 subset. Column (3) is the instrument's balance in the form of Dobbie, Goldin and Yang (2018) and Bhuller et al. (2020); columns (1) and (2) show that the same traits predict the treatment and the outcome, which is the contrast those papers draw.

**A2. Joint regression under the Panel A model.** Same as A1 column (3) with the full X0 as controls and the seven T30 traits entered jointly; joint χ²(7). This tests the same null as the existing Panel A test (11.746, from the stacked trait-on-score coefficients) with a different weighting, so the two statistics need not coincide; report both side by side.

**A3. Predicted-outcome rows.** From A1 column (2), form Ŷ as the trait component of the fit (T15 coefficients times traits, excluding fixed effects and X0-NH). Regress Ŷ on the pooled score under the Panel A model (fixed effects, X0-NH, score in reference-SD units). Report the coefficient in pp per reference SD with its SE. Do the same with D̂ from column (1). The Ŷ row is the implied reduced-form bias from imbalance on observed traits, to be read against 0.02039; the D̂ row is read against 6.912.

**A4. Repeat A1–A3** (a) on S0-CSE with XC and with XC + ENV, (b) on the B1 and B2 samples of Part B with their controls, and (c) on F50 with the treatment replaced by `analysis_entry_90` and, as a second treatment column, `recipient_disconnect_main`.

**A5. Competitive-only instrument.** A1 column (3), A2 and A3 with the competitive-only score on S0-CS, in that score's units.

## 4. Part B — the environment model on the headline rows

**B1. Environment-supported subset of S0, headline controls.** Restrict S0 to rows with a supported ENV (complete window, positive other-opponent denominator). Report the row count and the three reasons for exclusion with counts. On those rows fit, on identical rows: X0; X0 + ENV; and XC + ENV as the bridge to the 1,860,351-row ladder. For each: first stage, reduced form, 2SLS with Wald and AR 95 percent intervals, first-stage F, R-outcome reduced form, balance on T30 trait by trait with Holm within the seven and the joint test, and the A1–A3 tables. Include the one-rung ladder (volume; volume + own rate; volume + counterpart rate; all three) for X0 as it was done for XC.

**B2. All 2,682,330 rows with an availability indicator.** Add `env_supported` (1 if ENV is supported, 0 otherwise) to X0 and set the three ENV measures to zero where unsupported, the same convention X0 already uses for `fair_history_present_90` and the recipient's own grant rate. This is a control with an indicator, not an estimate of a rate, and it is the only place in this request where an unsupported value is filled. Report the unsupported share, the coefficient on the indicator, and the same outputs as B1. Report B2 beside B1 so the effect of the support restriction is visible on the same page.

**B3. Entry under the same controls.** On F50: X0 + ENV on the environment-supported games (report the count; expected to exceed 2,293,113 because the competitive-support restriction is dropped) and X0 + ENV + indicator on all 7,371,688. Outcomes: `analysis_entry_90`, `recipient_disconnect_main`, `active_timeout`. Balance on T30 under each. Also the competitive-only score on its supported rows.

**B4. Placebo under the same controls.** On O50: X0 + ENV on the environment-supported games and X0 + ENV + indicator on all 4,764,089. Report Y and R outcomes, the 95 and 90 percent intervals, and the matching reduced forms on the corresponding S0 rows from B1/B2 so each placebo sits beside its own reduced form.

**B5. Repeated-recipient rows.** B1 and B2 on the 1,658,609 repeated-recipient rows, pooled and with recipient fixed effects, reduced form and 2SLS only.

## 5. Part C — entry composition

Context fixed before the results. In F50 the score's association is −5.0 percent of the base rate per SD for any active timeout, −3.0 percent for recipient-side disconnection in any position, and −4.3 percent for entry, which requires a competitive final position and an active resolution. Taking entries as the subset of recipient-side disconnections the frame's definitions make them, the implied margin on recipient disconnections that are not entries is about −2.4 percent of their base (−0.0149 pp on 0.625 percent); confirm the subset relation before using this. Exits after a decisive blunder end in a clearly worse position and are therefore outside the exposure sample by construction; if the entry margin were driven by such exits, the relative margin on entries would be smaller than on non-entries, and it is larger. Part C tests this directly rather than assuming it.

**C1. Exit classes.** For every S0 exposure and for every recipient-side disconnection in F50, from the recorded move list and clocks, no engine:

- ply band at the final recorded move: ≤10, 11–30, 31–60, >60 (existing bands);
- material change for the recipient over the last four plies before the final recorded position, standard values 1/3/3/5/9: ≤ −3; −2 to −1; 0; ≥ +1;
- final-position merit code from the recipient's side (existing cell codes; F50 disconnections only, since S0 is competitive by construction);
- recipient clock remaining at the final recorded move as a share of the initial time: < 10 percent; ≥ 10 percent; clock unavailable.

Define `swing_exit` = material change ≤ −3 and ply ≤ 30; `quiet_exit` = material change 0, ply > 30, clock ≥ 10 percent. Report the cross-tabulation of classes with counts and shares, separately for S0 and for F50 recipient disconnections, before any regression. If `swing_exit` is under one percent of S0, say so first and treat C4(a) as not estimable.

**C2. Prior granting by class.** On S0, for each class and for `swing_exit` versus `quiet_exit`: `kind_rate_90`, `kind_ever_90`, `kind_rate_30`, `log_disconnect_90`, and the share with any prior competitive choice. Report the swing-minus-quiet difference in each with its CR0 standard error, unadjusted and adjusted for the fixed effects and X0-NH. The number the paper needs is the adjusted difference in `kind_rate_90` and `kind_ever_90`, in percentage points and as a share of the S0 mean.

**C3. Entry by class.** On F50, with X0 and the fixed effects, the score's association with the indicator for a recipient-side disconnection in each class, in pp per reference SD and relative to the class base rate. Same for the competitive-position entry indicator by ply band.

**C4. Restricted receipt models.** On S0 with X0: (a) excluding `swing_exit`; (b) ply > 30 only; (c) ply > 30 and clock ≥ 10 percent. For each: row count, first stage, reduced form, 2SLS with AR interval, and the T30 joint balance. These are influence checks on a post-assignment classification and are reported as such.

**C5. Deferred.** A trap-opening propensity built from opening tags is specified separately only if C1–C3 show the swing class carrying the entry margin. No list of openings is frozen here.

## 6. Outputs

The package format of the Run 2 reports: `READ_RESULTS.txt`, `REPORT_MANIFEST.json`, `summary.json`, and for each part CSV, JSON and Parquet with the standard row fields (`control_level`, `instrument`, `sample`, `n`, `row_set_sha256`, `native_residual_score_SD`, `reference_score_SD`, `units`, `clustering`, `nominal_interim_intervals`, `diagnostic_after_reviewed_results`, `causal_identification_certified = false`). Suggested files: `A_joint_balance.csv`, `A_predicted_outcome.csv`, `B_estimates.csv`, `B_balance.csv`, `B_ladder.csv`, `B_entry.csv`, `B_placebo.csv`, `C_classes.csv`, `C_prior_by_class.csv`, `C_entry_by_class.csv`, `C_restricted_iv.csv`. State in `READ_RESULTS.txt` the order in which the parts were specified and run, the support counts behind every sample, and the indicator convention of B2. Return the ZIP with its SHA-256.

## 7. What the paper does with each part

- A: a main-text balance table in the two-column form replaces the single joint-p row of Table 5 Panel B; the predicted-outcome row is reported beside the reduced form. The trait-by-trait table stays in Appendix D.
- B: if the X0 + ENV model on the headline rows holds the estimate and its interval, it becomes the specification that carries the number, with the current Panel A reported as the model without environment controls; otherwise the current headline stays and B is reported as the conditional-balance check with an unchanged point estimate. Either way the entry and placebo rows under the same controls replace the current subset rows.
- C: the entry paragraph of Section 5.2 and Appendix D.4 state where the margin lives and whether the recipients at the margin differ in prior granting; C4 is reported as a sensitivity.
