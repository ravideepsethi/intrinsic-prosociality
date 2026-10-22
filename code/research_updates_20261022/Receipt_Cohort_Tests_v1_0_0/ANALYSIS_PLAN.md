# Gratitude or resentment: exploratory tests on the receipt cohort

Revised October 6, 2026. This is a corrected analysis specification, not a results report or an executed code package. It was written after reviewing the completed Receipt Mechanisms v1.0.1 results. The existing cost-interaction result has already been seen; this extension must be described as exploratory.

## What these tests can answer

Use the existing receipt cohort to ask whether the adjusted grant-versus-claim association varies with (1) the giver's forgone rating premium and (2) the recipient's board position at disconnection. The cohort contains 2,682,329 exposures, 1,625,388 distinct recipients and 64,689 grants. This gives substantially more information about granted draws than the separate ordinary-game comparison frame.

These tests do not separately identify gratitude, resentment and relief at avoiding a loss. Both arms involve a discretionary opponent decision, and the game outcome changes with that decision. An OLS interaction is heterogeneity in a conditional association; it does not inherit the causal interpretation of the headline IV.

The earlier ordinary-draw versus ordinary-loss estimate was +0.043 percentage points, with a nominal 95% interval of [−0.037, +0.122]. This is a relatively precise small association in that comparison population. It does not establish that the game result cannot explain part or all of the receipt effect after a disconnection. Expectations, selection and the population affected by the instrument can differ.

The proposed psychological predictions require additional assumptions:

| Pattern | Possible interpretation | Why it is not decisive |
| --- | --- | --- |
| Larger receipt association at higher giver cost | Recipients may respond to a larger sacrifice. | The recipient may not perceive the counterfactual cost. Cost is strongly related to rating uncertainty and player characteristics. A higher cost does not necessarily make a claim more excusable. |
| Larger receipt association when the recipient was ahead | Denied leniency or a lost deserved win may matter more. | Receiving leniency that respects a deserved outcome could also generate greater gratitude. Avoiding an unexpected loss can matter more in these positions. |
| Larger receipt association near equality | Leniency may be particularly appreciated near an even position. | Selection into grants, expectations and later opportunities also vary with position. |

There is no automatic mapping from coefficient signs to a paper headline. In particular, an expected claim can still cause resentment, and a rare grant need not be perceived as an unexpected gift. Observed grant frequencies do not measure individual beliefs or entitlement.

## Sources, sample and variables

Use the verified monthly `dose.parquet` files from Receipt Mechanisms v1.0.1, run key `08b0e91f184f54156d8a5386118bebc5540cf08994035d36b9243f7d5ea8f0df`. These files join the original author-clean receipt cohort to its certified board and stake fields. The complete row-level files remain on the research computer; the uploaded report contains aggregate results only.

Verify the completed run, monthly manifests and `secondary_status.json` before fitting. Preserve the recorded receipt/claim arms, author exclusions, spacing, current-pair exclusion, histories, instruments and follow-up. The original recorded claim definition does not add a new mating-material exclusion. Do not repeat the v1.0.0 failure by imposing one. Report discrepancies without silently dropping or relabeling observations.

Use the same treatment and outcome definitions:

- `D = received`: one for a granted draw, zero for a recorded claimed loss.
- `Y`: one for granting at the first later qualifying competitive opportunity against a different opponent within 90 days. Complete-window nonreachers have zero; incomplete windows are not converted into zeros.
- `R = reached`: one if that later opportunity occurred. Report all Y and R coefficients in percentage points by multiplying probability-scale coefficients and standard errors by 100.
- `giver_cost`: the giver's stored win-minus-draw premium.
- `recipient_benefit`: the recipient-side half-win stake from the frozen common-scale replay. This is not a newly simulated rating update with outcome-dependent volatility.
- `board_cp`: `engine_eval_cp_disconnected`, already from the recipient's perspective. Positive means the recipient was ahead. Do not negate it because the focal player is the recipient.

For the new profile, use these exact half-open bands: `[-100, 0)`, `[0, 100)`, `[100, 300)`, `[300, infinity)`. The first two jointly define the near-equal comparison `[-100,100)` in this extension. This makes the +100 boundary explicit; it is not identical to a historical inclusive `[-100,+100]` label. Verify finite evaluations, the competitive flag, and the stored mate convention. An inconsistency blocks the new fit pending diagnosis; it does not authorize an exclusion or a sign flip.

The RD ≤110 restriction on both players is a sensitivity. Its already verified cohort contains 2,349,581 exposures and 56,544 grants. Each sample uses its own reported stake means for centering and the same five-point scale. Differences in the treatment coefficient at sample means therefore are not automatically comparisons at identical stakes.

## Audit before new estimation

Save the sample table before fitting; the program can then continue automatically. No user pause is needed.

For each band and treatment arm, report rows, distinct recipients, grants/claims, receipt rate, Y events, reach events, assignment support, and the distribution of each stake, each RD, rating gap, ply and both clocks. Report min/max, mean, SD and quartiles of stakes, and the number of recipients observed under both treatments. Keep sample hashes and aggregate reconciliation checks.

Pregame determination is not balance. A particular game's cost does not change when its board position changes, but different games in different position bands can have different pregame costs. Show those distributions; do not write that sacrifice is held fixed merely because it was determined before play.

The completed full-cohort dose analysis found giver-cost/recipient-benefit correlation 0.038, with interaction VIFs about 1.04 and 1.03. The two stake measures were not nearly collinear with each other. Their correlations with their own RDs were approximately 0.927 and 0.983, rising above 0.99 in the RD ≤110 sensitivity. Diagnose stake/RD dependence and the remaining stake variation after adjustment. Dropping the other stake interaction is a specification sensitivity, not a demonstrated cure for collinearity.

Fewer than 20 grants in a band triggers the original descriptive support flag. Twenty grants is not a certificate of reliable inference: also report independent recipients, outcome events, both-arm support and residual design rank. Do not drop a band because its estimated sign is inconvenient. If a required band lacks support, mark the focal contrast unsupported rather than redefine it.

## Estimation contract

Separate exact reproduction from the new extension.

**Reproduction.** Reuse the completed all-RD dose model as an archived benchmark. Its fixed effects are month × speed class, its controls are those in `dose.py::build_design`, and its primary covariance covers accounts shared across recipient, exposure-opponent and later-opponent roles with the implemented finite-sample adjustment. It is not a shared-account-or-date CR0 estimator. The completed giver-cost interaction is +0.0332 pp per five points, SE 0.0192, two-sided p = 0.0837, nominal 95% interval [−0.0044, +0.0708]. Preserve its original status as exploratory evidence.

**New joint model.** Estimate both focal contrasts from one model, adding position-band intercepts and treatment-by-position interactions to that established dose-model framework:

\[
Y_i = \sum_{k=1}^{4}\delta_k D_i B_{ik}
    + \beta_c D_i\widetilde c_i + \beta_b D_i\widetilde b_i
    + \sum_{k=2}^{4}\phi_k B_{ik}
    + \gamma_c\widetilde c_i+\gamma_b\widetilde b_i
    +X_i'\theta+\alpha_{m\times s}+u_i.
\]

Here the stakes are centered and divided by five. X preserves the established ratings, log RDs, histories, opponent scores, bounded continuous board evaluation, log ply, log clocks and giver-color controls. The continuous board control remains alongside the added band indicators. There is no separate D main effect when all four D × band columns are included.

Repeat this model with R as the outcome. Do not control Y for R, the realized game result or realized rating change. Y combines future opportunity availability and generosity at that opportunity. A zero average effect on R would not prove that reaching is unaffected for every person.

This is a deliberately new model. It does not reproduce the archived +0.0332 coefficient by definition. Month × exact-time-control × 100-point-rating cells, date effects, hour-of-week effects, or a date-inclusive CR0 covariance would be another explicitly labeled specification, implemented through a verified producer. They must not be introduced while calling the result an unchanged rerun of the mechanism dose model. Record controls, fixed effects and covariance independently in every output.

## Test 1: giver-cost heterogeneity

The first focal statistic is `beta_c` from the joint model. Interpret it as the change in the adjusted receipt association per five additional giver rating points, holding recipient benefit and modeled covariates fixed, under the model's common cost-slope assumption across bands.

Report its two-sided p-value, nominal interval, and the corresponding R coefficient. Also translate the slope into a contrast across the observed giver-cost interquartile range. Five rating points can be a large movement compared with the central spread; the report must show how much support the scaling represents.

Retain these secondary analyses:

1. A giver-cost tercile profile. Set cut points from the full analysis sample without using treatment or outcomes. Include tercile main effects and replace the linear D × cost interaction with two D × tercile indicators relative to the first tercile. Retain position interactions and D × recipient benefit. Report standardized receipt contrasts using a common position-band distribution and mean recipient benefit, plus support by band and tercile. Flag extrapolation where joint support is thin.
2. Models removing either stake interaction, one at a time, with all changes recorded. The model without D × cost cannot estimate beta_c; it describes the recipient-benefit sensitivity.
3. The same joint model with both RDs ≤110, showing the changed support and uncertainty. Do not select the favored sample from coefficient signs.

These analyses investigate shape and specification sensitivity. They do not convert previously viewed results into an independent confirmation.

## Test 2: board-position heterogeneity

Report the four `delta_k` coefficients from the same joint model. They are the modeled receipt contrasts at common centered stakes within each analysis sample, not differences between each band's own mean stakes. Controls do not make the groups randomized.

Define the equal-position comparison explicitly. Let `q_- = N_1/(N_1+N_2)` and `q_+ = N_2/(N_1+N_2)`, using all eligible exposures in the first two bands before fitting, without looking at their treatments or outcomes. Then

\[
\delta_{equal}=q_-\delta_1+q_+\delta_2,\qquad
\Delta=\delta_4-\delta_{equal}.
\]

Report these weights. Compute `Var(Delta) = a' V a` using the joint coefficient covariance, where `a=(-q_-,-q_+,0,1)` for the four band effects. Never combine four separate standard errors as if the estimates were independent. If a referenced band is unsupported, retain that status for Delta.

A positive Delta establishes, within this observational model, a larger receipt association when the recipient was well ahead. It is consistent with heightened resentment after a claim, heightened gratitude after a grant, and stronger disappointment/relief tied to the board position. It does not distinguish these accounts by itself.

The within-recipient sensitivity uses recipients with at least two spaced exposures and adds recipient fixed effects. Report treatment switchers, within-person position variation and rank for the focal contrasts. Two exposures alone do not guarantee identifying treatment variation. Retain intervals and support counts; never report only a sign because precision is poor.

## Inference and optional IV extension

For the two focal Y statistics, beta_c and Delta, report two-sided p-values and Holm-adjusted p-values across this declared family of two. This controls multiplicity within the specified analysis subject to its assumptions; it does not account for the earlier search and viewing of related results. Ordinary 95% intervals remain labeled nominal. Do not call an ordinary interval Holm-adjusted. R and other secondary analyses are labeled separately.

An interval that includes zero may be either precise or uninformative. Discuss the effect sizes it admits. Do not equate nonsignificance with no heterogeneity, support for the opposite sign, or lack of power. Do not count a nonpositive point estimate as evidence for the claim Delta ≤0.

Keep IV secondary and separate from the unchanged headline IV. A full interacted IV version of the joint model has six endogenous columns: four D × band terms, D × cost and D × benefit. The proposed excluded instruments are the four Z × band terms, Z × cost and Z × benefit. All band and stake main effects remain included. Instrumenting only D and D × cost while retaining D × benefit as an ordinary exogenous control is not a complete IV specification.

Do not mechanically carry the OLS control matrix into IV. The mechanism OLS controls include `adjusted_7d` as opponent leniency. If Z is this same pooled score divided by its reference SD, including that score as a control absorbs the excluded variation for the pooled treatment direction: the four Z × band columns sum to Z. Bind IV to the authenticated headline IV control specification, explicitly documenting this difference from OLS. Verify full residualized instrument and regressor rank before estimating.

The interacted instruments require conditional validity across the modifiers, not just a strong pooled first stage. Report the instrument scale, support, rank, reduced forms, first stages and conditional strength diagnostics for the actual endogenous system. Conditional F statistics address weakness in multiple-endogenous-variable models; they do not test exclusion restrictions. A threshold of 10 or 50 is not an identification certificate. Use inference appropriate to the authenticated covariance structure; label weak or unidentified results and use weak-instrument-robust inference where validated and feasible.

Use a joint covariance for all reported IV contrasts. Different position bands can induce different complier populations and weights, so a difference between local IV effects need not be a pure psychological response to board position. Do not claim that adding an interaction inherits every assumption and diagnostic of the original IV.

Method reference: Sanderson and Windmeijer, *A weak instrument F-test in linear IV models with multiple endogenous variables*, Journal of Econometrics 190(2), 2016, 212–221; [authors' working-paper summary at IFS](https://ifs.org.uk/publications/weak-instrument-f-test-linear-iv-models-multiple-endogenous-variables-0).

## Output and interpretation

Use cached local inputs. The required OLS variables are already in the verified dose files; this extension does not require new API requests or Stockfish work. A runnable implementation must still be built and tested before the research-computer run. Do not rerun completed preparation merely to reprint archived results.

| File | Required content |
| --- | --- |
| `00_sample.csv` | Overall and band-by-arm counts, events, support and reconciliation |
| `00_stake_balance.csv` | Stake/RD distributions, correlations and residual-variation diagnostics |
| `00_archived_benchmark.csv` | Clearly labeled previously observed dose estimates |
| `01_joint_model.csv` | Both outcomes, all band effects and stake interactions, covariance definition |
| `01_test1_terciles.csv` | Cut points, standardized effects, uncertainty and joint support |
| `01_test1_sensitivity.csv` | Dropped-interaction and RD restrictions with specification changes |
| `02_test2_contrasts.csv` | Equal-position weights, Delta, joint-covariance SE, nominal CI and Holm p |
| `02_test2_within.csv` | Recipient-FE sensitivity, identifying variation and uncertainty |
| `03_iv.csv` | Optional IV system, diagnostics and contrasts, or exact implementation/support limitation |
| `summary.json` | Source/sample hashes, model versions, controls, covariance, rank and support flags |
| `READ_RESULTS.txt` | Magnitudes and uncertainty, prior-viewing disclosure, reach results and interpretation limits |

Package the completed outputs with their manifest and SHA-256. The report should say whether the association rises or falls with sacrifice and with the recipient's advantage, and how precisely. It must not automatically choose “gratitude,” “resentment,” or “both” from a sign grid.

The immediate priority is the new board-position profile and its jointly estimated ahead-minus-equal contrast. Retain the cost test as a companion exploratory analysis. Stronger evidence would require a defended source of variation that separates perceived discretion, game outcome, or deservingness; agreement between these two associations is not by itself that separation.
