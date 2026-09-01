# A1 evidence response — authenticated final

## Bottom line

The +1.004686 percentage-point A1 result compares recipients whose opponent granted a mercy draw at a fixed first fair disconnection with recipients whose opponent claimed the timeout win at that same type of event. It is an adjusted, ATT-weighted linear-probability estimate of kindness at the recipient’s first later fair chooser opportunity within 90 days, **conditional on reaching such an opportunity**. It is not a raw mean difference and it is not an unconditional estimate that codes nonreturners as zero.

The frozen estimate is large and statistically precise: +1.004686 pp, SE 0.122806 pp, 95% CI 0.76399 to 1.24538 pp, raw p = 2.81×10⁻¹⁶, and Holm p = 8.44×10⁻¹⁶. The adjusted effect is 28.96% of the weighted control mean of 3.4695%. The raw ATT-weighted arm means are 4.5855% for mercy recipients and 3.4695% for claim recipients; their raw difference is not the adjusted regression coefficient.

The evidence supports a **robust conditional dynamic association consistent with behavioral transmission**. It does not establish literal random assignment: the focal opponent chooses whether to grant mercy, and exposure-state covariates retain some residual imbalance.

The authenticated post-result gap audit passed its headline-reproduction gate, recovered all 1,029,943 raw later-opportunity rows with zero outcome or timing mismatches, and materially closes the two largest factual gaps. The three decisive questions now have direct answers:

1. **Exact comparison:** fully answered below. The headline is conditional on reaching a later fair chooser opportunity; the zero-coded nonreacher model is a companion, not the headline.
2. **Prior relationship and direct reciprocity:** the focal pair is first-ever in the 7.763-billion-row chronology. Dropping original next opportunities against the focal opponent gives +0.980531 pp (SE 0.122530), and retargeting every recipient to the first later fair opportunity against someone else gives +0.982900 pp (SE 0.122544). Direct reciprocity to the focal person therefore cannot mechanically generate the +1.005-pp headline.
3. **Opportunity reach and composition:** reach to a non-focal-opponent opportunity is unchanged within sampling error (−0.2075 pp, p = .269). Two rating-level measures and an extremely small ultrabullet-share difference survive Holm correction, so it would be wrong to claim that all downstream composition is identical. The recipient and next opponent both shift upward by about 9 Elo, the rating gap does not change, and the later-state-conditioned A1 estimate remains +1.0164 pp.

The strongest defensible conclusion is therefore narrower than randomized contagion but stronger than a fragile descriptive correlation: A1 is a large, precise, temporally stable conditional association that survives removal of the focal opponent, explicit short-window exclusions, rich pre-treatment adjustment, common-support alternatives, later-state adjustment, and two zero-coded nonreacher companions. The newly executed exact first-opportunity companion is +0.4583 pp (SE 0.0578), or 28.2% of its 1.6243% weighted control mean.

## 1. Exact design and comparison

### Treatment and control

- **Index event:** for each account, the first fair/competitive Stage-07 event in the November 1, 2023–October 31, 2025 main window where that account is the disconnected player and the game is ordinary/non-tournament-like.
- **Treatment (`received_mercy=1`):** the focal chooser selected the certified kind-draw outcome.
- **Control (`received_mercy=0`):** the focal chooser claimed the timeout win.
- **Excluded but not replaced:** draws caused by insufficient mating material and chooser losses. The account’s index event is selected before applying the arm rule; the code does not rerank to a later event after an exclusion.
- **Prior relationship restriction:** the focal opponent–recipient pair must be a first-ever observed pair in the complete all-game chronology before the focal event.

This is therefore not “kind people versus unkind people” in the abstract. It is mercy versus a claimed win at a fixed recipient-level first eligible event, with detailed exposure-state standardization and a first-ever-pair restriction.

### Unit of analysis and repeat observations

The unit is a recipient account with one index exposure. Each account contributes at most one focal exposure and one primary outcome, its first later fair chooser opportunity. The same focal chooser can expose many recipients, which is why standard errors cluster by focal exposure chooser. The focal pair is unique in prehistory by construction.

### Outcome and time horizon

The primary outcome is a binary indicator that the recipient grants a kind draw at its **first subsequent fair/competitive chooser opportunity**, strictly after the index event and within 90 days. The primary total-path specification does not condition on the state of that later opportunity. A mandatory companion model adds the later state.

The headline sample also requires complete 90-day panel coverage and actual arrival at a later fair chooser opportunity. Thus:

- nonreturners and people who return but never reach a fair chooser opportunity are absent from the headline regression;
- they are coded zero only in the mandatory unconditional companion outcome, “any fair kind grant within 90 days.”

The producer defines that companion with `BOOL_OR(subsequent_kind_draw)`: it equals one if the recipient grants at any fair opportunity within 90 days. A post-result audit now also estimates the exact unconditional version of the headline—`reached × first_subsequent_kind_draw`, with nonreachers coded zero—without altering the frozen primary family.

## 2. Sample construction and attrition

| Step | Total | Mercy | Claim/control | Removed at step |
|---|---:|---:|---:|---:|
| Fixed first index exposures/accounts | 2,556,782 | 78,936 | 2,473,779 | — |
| Arm eligible | 2,552,715 | 78,936 | 2,473,779 | 4,067 non-arm events |
| First-ever focal pair | 2,372,445 | 70,517 | 2,301,928 | 180,270 |
| Common support retained | 2,370,142 | 70,447 | 2,299,695 | 2,303 |
| Complete 90-day follow-up | 2,185,073 | 65,085 | 2,119,988 | 185,069 |
| Headline: reached later fair choice | 1,029,558 | 30,051 | 999,507 | 1,155,515 nonreachers |

The 4,067 non-arm index events are 4,038 insufficient-mating-material draws and 29 chooser losses. Common support contains 257 exposure cells and retains 99.9007% of first-pair mercy observations. The headline has 668,683 focal-chooser clusters.

The headline unweighted treatment share is 2.919%. The full common-support treatment share is 2.972%.

## 3. Estimator, controls, fixed effects, and uncertainty

### Primary estimator

The primary model is an ATT-style weighted linear probability model. Treated observations receive weight 1. Within each eligible exposure cell, control weight is:

`number of mercy observations / number of claim observations`.

The code absorbs exposure-cell and exposure-month fixed effects by weighted alternating projections, then estimates a weighted least-squares coefficient. The primary coefficient is therefore adjusted; it is not simply the difference between the two weighted arm means.

### Exposure cells

Cells cross:

- 8 engine-evaluation bands;
- 3 draw-payoff classes: costly, exact zero, favorable;
- 8 chooser-minus-recipient rating-gap bands; and
- 6 speeds.

A cell must contain at least 5 mercy and 20 claim observations.

### Flexible exposure-time controls

The primary model includes standardized linear and squared terms for 13 exposure variables, 26 columns in total:

- engine evaluation;
- draw payoff and win premium;
- chooser and recipient Elo;
- chooser and recipient rating deviation;
- chooser and recipient clock;
- ply count;
- material advantage;
- base time; and
- increment.

The mandatory state-conditioned model adds flexible controls for the later opportunity’s evaluation, payoffs, clocks, Elo/RD, and elapsed time, plus later speed, tournament status, and month. It uses 75 control columns in total.

### Fixed effects and standard errors

- Fixed effects: focal exposure cell and exposure month.
- Standard errors: one-way cluster-robust by focal exposure chooser, with the reported finite-sample correction.
- Not used: recipient fixed effects, pair fixed effects, day fixed effects, or two-way clustering.

Recipient clustering is not informative for the primary because there is one index observation per recipient. Pair clustering is likewise not a repeated dimension because focal pairs are first-ever and contribute one index row. Chooser clustering is the main repeated assignment-side dimension.

## 4. Main estimate and certified robustness

| Specification | Effect (pp) | SE (pp) | Rows | Interpretation |
|---|---:|---:|---:|---|
| Frozen primary total path | +1.004686 | 0.122806 | 1,029,558 | ATT conditional on later fair-choice reach |
| Later-state conditioned | +1.016378 | 0.122710 | 1,029,558 | Adds later-opportunity state |
| Cross-fitted overlap weights | +0.926878 | 0.121901 | 1,029,943 | Overlap population, not ATT |
| Fine 200-rating/weekday/6-hour support | +0.944492 | 0.123715 | 1,024,386 | Retains 99.43% of mercy |
| Very fine 100-rating/weekday/4-hour support | +0.952453 | 0.124185 | 1,016,908 | Retains 98.96% of mercy |
| Exposure-chooser fixed effects | +1.275168 | 0.388888 | 25,094 | 8,662 switcher choosers |
| Censor at next opposing exposure | +1.266692 | 0.159674 | 641,407 | Removes 388,151 potentially re-exposed rows |

The fine-cell and chooser-fixed-effect models are post-outcome secondary audits; they do not reopen the primary family. The chooser-FE result is much less broadly representative because it uses only focal choosers observed giving both mercy and claims in the conditional-choice sample.

## 5. Balance, overlap, and effective sample size

### Common-support weights

The authenticated weight audit gives:

| Sample | Rows | Weight sum | Overall ESS | Mercy ESS | Control ESS | Control-weight range |
|---|---:|---:|---:|---:|---:|---:|
| Full common support | 2,370,142 | 140,894.000 | 272,820.3 | 70,447.0 | 2,143,174.6 | 0.016287–0.244898 |
| Headline conditional choice | 1,029,558 | 60,426.933 | 117,652.9 | 30,051.0 | 937,252.6 | 0.016287–0.244898 |

All mercy observations have weight 1. In the headline controls, the median weight is 0.028919; the maximum remains 0.244898. ESS is nonlinear and the arm-specific values are not additive; unequal arm weight sums within the reached-outcome subset produce the combined ESS of 117,652.9.

### Cross-fitted propensity overlap

The overlap sensitivity uses fivefold chooser-level cross-fitting and a ridge-logit treatment model with 70 exposure/pre-exposure features. Predictions are clipped to [0.001, 0.999]; 171 rows are clipped. The observed pre-clipping range is approximately 9.36×10⁻¹⁴ to 0.9970. The overlap estimator weights treated rows by `1-p` and controls by `p`, targeting the overlap population rather than the ATT.

Headline treatment-propensity quantiles from the authenticated private checkpoint are:

| Quantile | Mercy | Claim/control |
|---:|---:|---:|
| Minimum | 0.001000 | 0.001000 |
| 1% | 0.012756 | 0.010749 |
| 5% | 0.016913 | 0.014065 |
| 50% | 0.031713 | 0.026780 |
| 95% | 0.067966 | 0.052736 |
| 99% | 0.105997 | 0.078276 |
| Maximum | 0.938641 | 0.993026 |

The bulk of both arms overlaps closely, with sparse extremes. The separately targeted overlap-population model remains positive at +0.926878 pp (SE 0.121901), so the result is not being created solely by the ATT cell weights or propensity tails.

### Balance

Final ATT-adjusted pre-treatment/history balance is generally good:

| Variable | Adjusted absolute SMD |
|---|---:|
| Prior fair opportunities, 90d | 0.0013 |
| Prior kind draws, 90d | 0.0077 |
| Prior kindness rate, 90d | 0.0183 |
| Prior rating change, 90d | 0.0209 |
| Prior disconnections | 0.0526 |
| Prior mercy receipts | 0.0053 |
| Prior games, 30d | 0.0223 |

Exposure-state balance is not perfect even after weighting. The largest adjusted SMDs include ply 0.1637, chooser RD 0.1398, chooser Elo 0.1255, recipient Elo 0.1216, and win premium 0.1090. These variables are explicitly controlled in the regression, but residual unobserved imbalance remains possible. This is a central reason not to describe A1 as randomized.

## 6. Reach, return, and opportunity composition

### Reach and unconditional outcome

- Effect on reaching a later fair chooser opportunity within 90 days: −0.1998 pp, SE 0.1879 pp, p = .288.
- Effect on any fair kind grant within 90 days, coding nonreachers zero: +0.4957 pp, SE 0.0718 pp, p = 4.97×10⁻¹².
- Weighted control mean for the unconditional outcome: 2.7532%; weighted mercy mean: 3.3095%.
- Effect on kindness at the first later fair opportunity with nonreachers coded zero: +0.4583 pp, SE 0.0578 pp, p = 2.14×10⁻¹⁵.
- Weighted control mean for the exact zero-coded first-opportunity outcome: 1.6243%; weighted mercy mean: 2.1172%; adjusted effect relative to the control mean: 28.2%.

The any-grant companion is broader because a recipient can decline at the first fair opportunity and grant at a later one. The new exact companion instead holds the headline outcome definition fixed and changes only the nonreacher rule. Its +0.4583-pp estimate shows directly that coding nonreachers zero does not erase the A1 association. It is naturally smaller in percentage-point terms than the conditional +1.0047-pp headline because only about 47% of the complete-follow-up sample reaches a qualifying opportunity.

### Engagement and immediate reentry

The frozen 30-day engagement primary is null: +0.00337 log points for `log(1 + games)`, SE 0.00582, p = .563. Binary 30-day play and raw game count are also null. Seven-day engagement is weakly positive but not conventionally significant.

Immediate reentry is different:

- any rated-standard game within 10 minutes: +0.8820 pp, p = 6.09×10⁻⁸;
- within 30 minutes: +1.0049 pp, p = 1.97×10⁻⁸; and
- within 60 minutes: +0.9660 pp, p = 2.03×10⁻⁷.

Thus mercy does affect immediate continuation of play. That is substantively important and should be disclosed; the result is not consistent with saying treatment leaves all post-event behavior unchanged.

### Opportunity composition

The later-state-conditioned A1 coefficient (+1.0164 pp) is almost identical to the total-path coefficient (+1.0047 pp), which argues against the measured later state explaining the result. Existing threshold-reach outcomes for later ply are also null at 5%:

- reaching later ply >4: −0.2622 pp, p = .162;
- reaching later ply >10: −0.3129 pp, p = .092; and
- reaching later ply >20: −0.1721 pp, p = .342.

The post-result audit directly estimates 26 next-opportunity composition outcomes and applies Holm adjustment within that disclosed family. Three survive:

| Next-opportunity outcome | Adjusted effect | SE | Holm p | Substantive reading |
|---|---:|---:|---:|---|
| Recipient/chooser Elo | +8.7719 Elo | 0.8187 | 2.27×10⁻²⁵ | Higher next rating level |
| Opponent Elo | +9.0683 Elo | 0.9563 | 6.18×10⁻²⁰ | Opponent shifts by essentially the same amount |
| Ultrabullet share | −0.002519 pp | 0.000563 | .000181 | Statistically detectable but substantively tiny |

The next-game rating gap is unchanged (−0.2964 Elo, raw p = .604). The paired upward shifts in recipient and opponent Elo are consistent with the mechanical rating consequence of receiving a draw rather than a loss followed by rating-based matching; they do not show a more favorable rating gap. No board evaluation, payoff, clock, ply, material, tournament-status, elapsed-time, immediate-window, or other speed outcome survives the same Holm family. The focal-opponent indicator has raw p = .030 but Holm p = .692.

Thus, the exact answer is not “composition is entirely null.” Mercy changes the rating level at which the next opportunity is observed and produces one negligible speed-category difference. But the measured opportunity state does not account for A1: conditioning flexibly on that later state leaves the coefficient at +1.0164 pp.

## 7. Pair history, pretrends, and repeated interaction

The focal exposure pair is required to be first-ever in the canonical all-game chronology: 852 files, 7,763,847,245 rows. This is stronger than merely “no prior fair timeout encounter”; it excludes any observed earlier game between the focal pair.

Nine pre-exposure placebo outcomes across 0–30, 31–60, and 61–90 days are jointly null after Holm adjustment. The smallest raw p-value is .0324 for having a prior fair opportunity in the nearest 30 days, but its adjusted p-value is .2918. No prior-opportunity, prior-kindness, or last-prior-choice placebo survives adjustment.

The authenticated audit now resolves whether the **later primary outcome** occurs against the focal exposure opponent. Calling that person the “benefactor” is exact only in the mercy arm; in the control arm the same role is the focal claimer.

- The Stage-07 rescan finds 139 same-focal-opponent original-next rows among 1,029,943 raw later-opportunity rows; 138 remain in the headline support sample.
- In the headline, these are 12 of 30,051 mercy rows and 126 of 999,507 control rows. The ATT-weighted shares are 0.03993% and 0.01363%, respectively.
- The adjusted treatment effect on the next opportunity being against the focal person is +0.02559 pp (SE 0.01180, raw p = .0301), but it does not survive the 26-outcome composition family (Holm p = .692).
- The same-focal-only subgroup has a descriptive +34.85-pp coefficient (SE 20.58, p = .090; N = 138). This tiny subgroup is selected after treatment and is not a causal estimand.
- Dropping it leaves A1 at +0.980531 pp (SE 0.122530, 95% CI 0.74037–1.22069, p = 1.22×10⁻¹⁵; N = 1,029,420).
- Retargeting the outcome to each recipient’s first later fair opportunity against someone else gives +0.982900 pp (SE 0.122544, 95% CI 0.74271–1.22309, p = 1.05×10⁻¹⁵; N = 1,029,505).
- Only 53 of the 1,029,943 raw later-opportunity recipients fail to reach a non-focal-opponent fair opportunity within 90 days. The effect on reaching one is −0.2075 pp (SE 0.1878, p = .269).

The headline therefore cannot be an artifact of recipients simply repaying the focal opponent. The data remain compatible with generalized reciprocity, gratitude, mood, or self-signaling toward other people; those are mechanism distinctions, not explanations based on direct rematching.

## 8. Timing, horizon, and immediate-rematch plausibility

The certified horizon strata are:

| Time to measured fair choice | Effect (pp) | SE (pp) | p-value |
|---|---:|---:|---:|
| ≤6 hours | +1.6685 | 0.6675 | .0124 |
| >6 hours–1 day | +0.8923 | 0.5010 | .0750 |
| >1–7 days | +1.2002 | 0.2337 | 2.82×10⁻⁷ |
| >7–30 days | +0.7975 | 0.1592 | 5.42×10⁻⁷ |
| >30–90 days | +0.4866 | 0.1366 | .000367 |

The estimates remain positive through 90 days but are nonmonotone, so they should not be described as a literal parametric decay curve.

The elapsed-time distributions are nearly identical by arm. The ATT-weighted medians are 354.2 hours (14.76 days) for mercy and 351.8 hours (14.66 days) for controls; the 25th percentiles are 117.1 and 116.7 hours, and the 75th percentiles are 840.9 and 841.1 hours. Within one day are 8.126% of mercy outcomes and 8.107% of weighted controls; within six hours are 3.581% and 3.526%; within ten minutes are 0.363% and 0.326%. None of the audit’s elapsed-time threshold indicators survives the 26-outcome Holm family.

More decisively, re-estimating A1 after removing every original next opportunity inside each window gives:

| Exclusion | Effect (pp) | SE (pp) | 95% CI (pp) | p-value | Rows |
|---|---:|---:|---:|---:|---:|
| ≤10 minutes | +1.006484 | 0.123036 | 0.76533–1.24763 | 2.83×10⁻¹⁶ | 1,026,229 |
| ≤30 minutes | +0.994770 | 0.123225 | 0.75325–1.23629 | 6.87×10⁻¹⁶ | 1,021,213 |
| ≤1 hour | +0.990949 | 0.123620 | 0.74865–1.23325 | 1.09×10⁻¹⁵ | 1,016,459 |
| ≤6 hours | +0.980815 | 0.125005 | 0.73580–1.22583 | 4.29×10⁻¹⁵ | 993,753 |
| ≤1 day | +0.978753 | 0.128396 | 0.72710–1.23041 | 2.48×10⁻¹⁴ | 947,234 |

Dropping either a same-focal-opponent next opportunity or any next opportunity within six hours gives +0.960211 pp (SE 0.124719, p = 1.37×10⁻¹⁴; N = 993,656). Short-window rematches therefore do not drive the result.

Stage 07 has no canonical session identifier, so these are explicit time-window proxies rather than exact same-session exclusions. The audit also does not compute game-rank-to-outcome from the 309.9-million-row all-game user-history layer. Those labeling limits should remain explicit even though the one-day exclusion is a demanding practical test.

## 9. Outcome plausibility and ply/investment

The A1 association survives requiring a minimally developed later choice:

- later fair choice after >4 plies: +0.9433 pp, SE 0.1221;
- later choice after >10 plies: +0.9650 pp, SE 0.1247;
- later choice after >20 plies: +0.8887 pp, SE 0.1316;
- both focal and later events after >10 plies: +0.9923 pp, SE 0.1501; and
- both focal and later events after >20 plies: +1.0133 pp, SE 0.1901.

The >10-ply later-state-conditioned model is +0.9756 pp. These results make a pure “accidental early timeout-button click” account less plausible.

Focal-event heterogeneity does not show a meaningful early-versus-late difference: ≤10-ply focal events yield +0.9362 pp and >10-ply events +1.0336 pp; the difference is +0.0974 pp, p = .711. Therefore the evidence does not support claiming that greater focal game investment strengthens transmission.

## 10. Salience, learning, gratitude, and generalized reciprocity

The targeted salience/investment closure was frozen after the headline result and is secondary. It finds:

- no observed prior timeout choice after a 180-day burn-in: +0.4950 pp, SE 0.3094, p = .110;
- prior timeout choice but no prior grant: +0.7362 pp, SE 0.1755, p = 2.73×10⁻⁵;
- at least one prior observed grant: +5.2173 pp, SE 1.6127, Holm p = .00365; and
- formal prior-granter versus prior-decliner interaction difference: +4.4777 pp, SE 1.5986, p = .00509.

This weakens the narrow explanation that recipients merely discover that the draw button exists. It does **not** rule out reminder salience, gratitude, generalized reciprocity, mood, self-signaling, or residual selection. Indeed, the much larger association among prior granters is compatible with heterogeneous responsiveness rather than a universal learning mechanism.

The first-ever focal-pair restriction and the new non-focal-opponent outcome are important for distinguishing direct reciprocity toward one person from generalized behavior toward others.

## 11. Rival explanations and auxiliary designs

### Encountered-opponent propensity (“encouragement”)

The auxiliary predictor is the focal chooser’s strictly pre-index, focal-pair-excluded kindness rate, requiring at least 10 earlier fair opportunities.

- First-stage association with receiving mercy: 1.1915 per full-unit prior-kindness rate, SE 0.0104, p effectively zero; 589,168 rows.
- Reduced-form association with later A1 kindness: +2.8048 pp per full-unit prior-kindness rate, SE 0.8056 pp, p = .000498; 220,340 rows.
- Reduced-form 30-day engagement association: null, p = .269.

This is corroborating evidence, not a valid IV claim. The exclusion restriction is not established: encountering a historically kind opponent could correlate with matchmaking, recipient traits, session context, or other channels that also predict the later outcome.

### Ambient/network spillovers

A separate ambient-exposure module is weak and null: roughly +0.082 pp in focal kindness per one-percentage-point increase in recent ambient kindness (p ≈ .12), with a noisy top-versus-bottom contrast. This does not support a large ambient contagion story, but it is not a definitive no-interference test for A1.

### Subsequent treatment contamination

When the measured next fair choice is censored if it occurs after another qualifying disconnection exposure, 62.30% of the headline rows remain and A1 increases to +1.2667 pp (SE 0.1597). The mandatory state-conditioned counterpart is +1.2696 pp. This argues against later opposing exposure being necessary for the headline association.

## 12. Multiplicity and replication

The frozen primary family contains exactly three tests:

| Test | Raw p | Holm p |
|---|---:|---:|
| A1 mercy transmission | 2.81×10⁻¹⁶ | 8.44×10⁻¹⁶ |
| A3 30-day log games | .5626 | .5626 |
| B1 24-hour clustering | .0004 | .0008 |

Post-outcome fine matching, chooser fixed effects, pretrends, remaining-dynamics analyses, and salience/investment closure are explicitly secondary and do not reopen this family. The nine pretrend tests have their own Holm family. The salience closure applies a disclosed Holm correction to its decisive family. The gap audit applies Holm correction to the newly introduced next-opportunity composition family; exclusion and temporal-split models remain labeled sensitivity analyses rather than new confirmatory tests.

There is **no independent external replication, preregistered holdout, or untouched temporal replication** in the current artifacts. The post-result internal split is nevertheless stable:

| Exposure period | Effect (pp) | SE (pp) | 95% CI (pp) | p-value | Rows |
|---|---:|---:|---:|---:|---:|
| Nov. 2023–Oct. 2024 | +0.983473 | 0.144088 | 0.70106–1.26589 | 8.76×10⁻¹² | 738,926 |
| Nov. 2024–Oct. 2025 | +1.082566 | 0.234658 | 0.62264–1.54250 | 3.96×10⁻⁶ | 289,576 |

Support is recomputed within each half. These estimates show internal temporal stability, not independent replication, and should be labeled that way.

## 13. Registration and provenance

The analysis was internally frozen and versioned, but not publicly preregistered.

- The initial plan was frozen before dynamic outcomes were estimated.
- An outcome-blind feasibility gate observed cohort sizes, balance, support, and the pooled 30-day continuation rate, but did not read treatment-specific effects.
- Analysis plan v1.0.1 was amended after the outcome-blind feasibility gate and before A1/A3/B1 effect estimation. SHA-256: `b11b546ea6fde608140619cffadffad1a7aab054b6fd1a9dcbee8900c98d0a6f`.
- Arm-partition amendment v1.0.2 corrected the treatment/control partition after a failed pre-estimation execution and before effect estimates. SHA-256: `db951a0ea42945cbe4ec8a86cf436a839b1821a2225d73442dddb6262e908ec5`.
- The post-outcome audit and August 30 salience contract were frozen after the headline and are secondary.

### Core run

- Run ID: `20260822T022146Z`
- Status: `DYNAMIC_PROSOCIALITY_CORE_V102_OK`
- Executed producer: `10c_estimate_dynamic_prosociality_core.py`
- Producer SHA-256: `2dcf0dd19f7cfe8f694d348e6590df88083a37882404112229d6ef05ebc42713`
- Execution Git HEAD: `7fa2cf415b43c69f4d8d5fc973442d81dbb6ecbf`
- Certified core success SHA-256: `bd64005162bf8f37f9488d47e95c2ea4dd946d1227e909930a42dd8e4904f009`
- Core summary SHA-256: `fa49fb15e095fb961a3f4cca5b937d903bc890467ed8404e37683858dd20a269`
- Core report manifest SHA-256: `e2724dab02a2b7b7c10f68b63ed40ddc67f2345947aa923d851912df946d16d8`
- Private recipient checkpoint SHA-256: `41ef57b3118ea7d3b0bfb7a5e19040bd82e7794aa54fb6b06625d7793921816d`
- Cross-fit propensity checkpoint SHA-256: `c442a40c8e8261484f888408bd8997eba563730c150721b1c2362397b3c9cbfe`
- Stage-07 success SHA-256: `8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7`
- Stage-07 producer SHA-256: `0411d4061ea9831c20449208a9782aaf668e160139918d106a2b7d63aaa56e6e`
- Chronology manifest SHA-256: `1d4648bb17cafd9e58c14ab78d32abe855f0bc62a6fb75ac88e02494a73337cd`

### Post-outcome audit

- Run ID: `20260822T041411Z`
- Status: `DYNAMIC_PROSOCIALITY_POSTOUTCOME_AUDIT_V101_OK`
- Producer SHA-256: `f1279072391e5933e4e2936df7e07abcc431a03a1f03aabceb147949257b1e6f`
- Success SHA-256: `ba8c97841b6abe35986c5c6532d2800185cb7ef8d06936158c17984bb29719ad`

### Remaining-dynamics completion

- Run ID: `20260823T141145Z`
- Status: `REMAINING_DYNAMIC_COMPLETION_V100_OK`
- Producer SHA-256: `e7b302bae6c73e2f35d3b004c7206e8b2ff07fd77d49a63871f5d72d9467a73a`
- Success SHA-256: `65555d86abbcfb9eb7918bbddb8460bad1d78198c7767eebe80fb3d3dac373e5`
- Summary SHA-256: `78417ab83aee731ada49f3bb1e5e26d631c118a58cb7964a9b3a539eef9bce74`
- Report manifest SHA-256: `fafed536852c779d0717c8e0080f4a189db15a7c5d258f7a6cb3815ca75f92fe`

### A1 salience/investment closure

- Run ID: `20260831T165103Z`
- Status: `A1_SALIENCE_INVESTMENT_CLOSURE_V100_OK`
- Results SHA-256: `1bdca9022689a3a5558dcdbd1e5db86d9c6b6ce025da60a31b18aa53e47a440d`
- Success SHA-256: `3837a45bd81705b8424d52b0ff37443199f1c856aa69fa7244493b21480f942b`
- Report manifest SHA-256: `d7948a37f788c573f75cea2dce040b37b87fd84d3f4e3effd04f03304511b95c`

### A1 evidence-gap audit

- Run ID: `20260901T184907Z`
- Status: `A1_EVIDENCE_GAP_AUDIT_V100_OK`
- Executed audit script: `a1_evidence_gap_audit_v100.py`
- Audit script SHA-256: `efc8b443b6db762b438868556416cd69774ad7db27fa3bcd805eda1618dd1f21`
- Configuration SHA-256: `6674c2889d80a84f8c8a0f27de68d3ee7fed70e2d91b81ae09969f2f283937b9`
- Audit report-manifest SHA-256: `a868aca2c510bcea680e93f2f65c707ff2a8274f52c97237e8cd4ea2e49b0ebb`
- Public result ZIP SHA-256: `ca025ed1d8558af30ca834c18e87cbdcc80d355719a11a9e02b94e9f21c4e6e8`
- Private enrichment SHA-256: `c769077b4b122b63f9c4a4b0dd095497f15cefdd81904f7205d3a4cc385dd9b1`
- Raw later-opportunity rows: 1,029,943
- Stage-07 enrichment mismatches: 0 outcomes and 0 timings
- Public report files: 14; every recorded file hash and byte count independently verified after upload

The evidence-gap audit authenticated the Stage-07 success authority and the exact certified core/private-input hashes but did not itself re-hash every Stage-07 Parquet file (`stage07_parquet_hashes_verified_this_run=false`). The subsequent unconditional first-opportunity audit closed that archival gap: all 24 monthly Parquet hashes verified successfully using four workers, and the frozen headline, reach companion, and any-grant companion then reproduced exactly before the new model ran.

### Unconditional first-opportunity audit

- Run ID: `20260901T194953Z`
- Status: `A1_UNCONDITIONAL_FIRST_OPPORTUNITY_AUDIT_V100_OK`
- Public result ZIP SHA-256: `b2eb90c69ed1864c74e3b7bdbdb7da728fc30e3525d058fdeb00474412fe0f08`
- Exact zero-coded first-opportunity estimate: +0.458260 pp, SE 0.057765 pp, p = 2.14×10⁻¹⁵
- Complete-follow-up sample: 2,185,073 recipients, including 65,085 mercy and 2,119,988 claim observations
- Stage-07 Parquet hashes verified in this run: `true`
- Account-level outputs published: `false`
- Every recorded public file hash and byte count independently verified after upload

## 14. Final evidence judgment and remaining limitations

### What the completed audit materially strengthens

1. **Direct reciprocity is not the headline mechanism.** Focal-opponent next opportunities are vanishingly rare, and removing or retargeting them leaves about +0.98 pp.
2. **Immediate rematches are not driving A1.** The estimate remains +0.979 pp after excluding every next opportunity within one day.
3. **Differential reach does not erase the result.** Reach effects are small and nonsignificant. The zero-coded “any grant within 90 days” outcome is +0.496 pp, and the exact zero-coded first-opportunity outcome is +0.458 pp; both are highly significant.
4. **Measured later-state selection does not absorb A1.** Rating level changes, but rating gap and nearly all other composition measures do not; the fully later-state-conditioned estimate is +1.016 pp.
5. **The finding is internally stable over time.** The first and second 12-month halves are +0.983 and +1.083 pp.

### What remains unidentified

1. **Kindness versus material benefit:** a mercy draw is also a better game and rating outcome than a claimed timeout loss. The paired approximately +9-Elo downstream shift makes this channel visible. The later-state adjustment shows that measured rating composition does not explain A1, but no design here cleanly separates the social meaning of mercy from favorable-outcome relief.
2. **Assignment:** focal opponents choose mercy. Rich adjustment, overlap, pretrend placebos, first-pair restriction, and chooser fixed effects reduce but cannot eliminate unobserved selection.
3. **Mechanism among other people:** the non-focal-opponent result supports generalized rather than direct reciprocity, but it cannot separate gratitude, mood, self-signaling, reminder salience, or a broader behavioral response.
4. **Exact sessions and game ranks:** the one-day exclusion is strong, but Stage 07 has no canonical session identifier and this audit does not report the number of intervening all-game events.
5. **Independent confirmation:** there is no public preregistration, untouched holdout, or external replication.

### Recommended paper claim

> Receiving a mercy draw rather than a claimed timeout loss is associated with an approximately one-percentage-point increase in kindness at the recipient’s next fair chooser opportunity within 90 days, conditional on reaching such an opportunity. The association persists for later choices against other opponents, after excluding short-window opportunities, under alternative support and fixed-effect specifications, and in both halves of the panel. Because mercy is chosen rather than randomized and also changes the recipient’s material outcome, we interpret this as robust quasi-experimental evidence consistent with generalized prosocial transmission, not definitive proof of a causal contagion mechanism.

With that framing, A1 can credibly carry the paper as its central empirical contribution. The completed audit materially improves publication prospects because it neutralizes the most damaging mechanical alternative—repayment to the same opponent—and shows that the result is not a short-session artifact. A stronger causal claim would still require a design that separates mercy’s social meaning from its payoff consequence and, ideally, an independent or genuinely held-out replication.

## 15. Files to send with this response

Send the already authenticated public core, post-outcome, remaining-dynamics, and salience result bundles keyed by the hashes above, together with `a1_evidence_gap_audit_20260901T184907Z.zip` (SHA-256 `ca025ed1d8558af30ca834c18e87cbdcc80d355719a11a9e02b94e9f21c4e6e8`), `a1_unconditional_first_opportunity_20260901T194953Z.zip` (SHA-256 `b2eb90c69ed1864c74e3b7bdbdb7da728fc30e3525d058fdeb00474412fe0f08`), and this response. The audit ZIPs contain executed code, aggregate tables, input authorities, report hashes, summaries, reports, and `_SUCCESS.json`. Do not send private recipient, propensity, chronology-derived, enrichment, or other account-level Parquet files.
