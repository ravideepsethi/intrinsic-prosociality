# Handoff: tests the Section 3 framework leans on

Six analyses, in run order. A, B, C are required before the framework text is finalized; D runs only if B is uninformative; E and F can run in parallel with B. Test F examines which kinds of granting persist from the first year to the second. Everything uses the analysis sample of Section 2.3 (41,534,331 opportunities, pool games, observed-adjacency screen) unless stated. Freeze this document before running anything; the paper discloses specification timing and these are specified after the main results and before estimation.

Conventions throughout:
- `v` = final-position engine evaluation from the disconnected player's side (cp). Competitive: `v >= -100`. Clearly worse: `v <= -300`.
- `ply` = recorded plies before the final position. "After ply 10" = `ply > 10`.
- `rG` = reconstructed draw payoff (rating points, signed; Section 2.5). `kappa` = forgone premium = K/2. `K` = rating-update scale.
- P1 = Nov 2023–Oct 2024. P2 = Nov 2024–Oct 2025.
- Outcome in all regressions: `100 * grant` (pp), LPM, SEs clustered by chooser account with G/(G-1), unless stated.
- "Baseline controls" = stage-band FE (11–20, 21–40, 41–80, 81+ when after ply 10; add 1–2, 3–10 when all stages), speed FE, month FE, log(1+kappa) and its square, chooser log RD and square, opponent log RD and square, log(1+seconds) on each clock with a missing indicator.
- Evaluation spline `f(v)` = natural cubic spline in raw cp, boundaries −100 and +600, interior knots 0, +100, +300, plus separate indicators for finite `v >= 600` and forced mate for the opponent (Appendix B.1).

---

## Test A — Flagged accounts and the Patron sign reversal

**Why.** Section 3.3 reads the negative Patron association for lost-position granters as "accounts that place no value on rating points." If those accounts are disproportionately closed or TOS-flagged, the negative sign is partly mechanical (no badge on a closed account) and the reading has to be weakened. This test can change the framework, so it runs first.

**Data.** The August 2026 profile snapshot used for Table 3. Fields: `disabled` (closed account), `tosViolation`. Treat absent fields as false. Also record profile availability (404 or missing) from the acquisition cohort, since unavailable accounts were dropped without replacement.

**Samples.**
1. The 599,045-account state-specific sample (Table 3 Panel B/C) with its four granting-history groups: CO (competitive-only), BOTH, LO (lost-only), NEI (neither).
2. The 851,131-account main comparison (Panel A): competitive-position granters vs never-granter controls.
3. The full acquisition cohort (1,105,634 with available August profiles, plus the unavailable ones) for the availability rates.

**Outputs.**
- `tabA1_flags_by_group.csv`: for each group in sample 1 and each arm in sample 2: N, share `disabled`, share `tosViolation`, share either, share profile-unavailable (from sample 3, by the same grouping), Patron rate among all, Patron rate among unflagged, Patron rate among flagged.
- `tabA2_patron_excluding_flags.csv`: re-estimate Table 3 Panel A (adjusted association, HC1 and cell-clustered SEs), Panel B (both indicators in one model), and Panel C (raw rates), each three ways: excluding `tosViolation`, excluding `disabled`, excluding either. Same cells, same controls, matching groups re-formed after exclusion (drop a matched group if its focal account is excluded).
- `tabA3_recipient_patron_excluding_flags.csv`: the Appendix E recipient-side estimate (0.319 competitive, −0.001 lost) excluding flagged opponents.

**Decision rule.**
- Panel B clearly-worse coefficient after excluding "either" remains negative with |t| ≥ 2 and at least half its original magnitude (≤ −0.10 pp): keep Section 3.3 and Proposition 1(i) as written.
- Coefficient shrinks below half or loses significance: the reversal is at least partly mechanical. Rewrite Section 3.3's reading of lost-position grants to "accounts that leave or are removed from the platform," drop the sentence in Section 5.2 that treats the negative sign as a test, and footnote the flag shares.
- Report the flag shares regardless; a referee who knows the platform will ask.

---

## Test B — Rating-gap slope by granting history (price vs merit)

**Why.** The framework now puts the rating gap into the price, not into merit. Under the price reading the gap slope within competitive positions is proportional to `lambda_i`; under the merit reading it is proportional to `b_i`. Accounts that grant in both states are, by the model, `lambda ≈ 0` with high `b`; competitive-only accounts are `lambda > 0` with high `b`. So the price reading predicts a steep gap slope for competitive-only accounts and a flat one for both-state accounts, with both groups responding to the position. The merit reading predicts both groups respond to the gap.

**Design: holdout classification.** Classify accounts on P1 outcomes, estimate slopes on P2 opportunities. This avoids conditioning the estimation sample on its own outcome.

**Step B1 — classification (P1 only).** For each chooser account, count in P1: competitive opportunities (all stages), clearly-worse opportunities, competitive grants, clearly-worse grants. Keep accounts with ≥ 4 competitive and ≥ 4 clearly-worse opportunities in P1. Assign:
- CO: competitive grants ≥ 1, clearly-worse grants = 0
- BOTH: ≥ 1 and ≥ 1
- LO: 0 and ≥ 1
- NEI: 0 and 0
Modestly-worse grants do not affect classification. Save `accounts_B_groups.parquet` with counts and group. Report group sizes and P1 opportunity counts by group.

**Step B2 — estimation sample (P2).** All P2 competitive opportunities (`v >= -100`) after ply 10 whose chooser is in a B1 group. Report N opportunities, N accounts, and raw grant rate by group.

**Step B3 — primary model.**
```
100*grant_io = alpha_i
             + sum_g 1{g(i)=g} * [ beta_g * rG_o + f_g(v_o) ]
             + baseline controls (stage bands 11–20, 21–40, 41–80, 81+)
             + e_io
```
Chooser FE `alpha_i` absorb group main effects. `rG` centered at zero. `f_g` is the spline with group-specific coefficients. Cluster by chooser. Note that log(1+kappa) is in the controls, so `rG`'s identifying variation is the rating gap at a given update scale.

**Step B4 — estimands, by group g ∈ {CO, BOTH, LO, NEI}.**
- `beta_g`: pp per rating point of draw payoff.
- `D_g = f_g(500) − f_g(300)`; also `f_g(300) − f_g(100)` and `f_g(100) − f_g(0)`.
- `m_g`: adjusted group grant rate, standardized to the group's own P2 composition.
- Proportional slopes `beta_g / m_g` and `D_g / m_g`, delta-method SEs.
- Differences BOTH − CO for both proportional slopes, with SEs from the joint covariance.
- Stage check: the coefficient on the 41–80 band relative to 11–20, by group; both CO and BOTH should show a decline.

**Step B5 — figure.** `figB1_gap_by_group.pdf`: adjusted grant rate against 50-point bins of the displayed rating gap (as Figure 4 Panel A, reference bin [−25, 25)), one line per group, roughly-equal positions only (`-100 <= v < 100`), after ply 10, chooser FE and baseline controls. Second panel: the same for the evaluation profile (eight bins of Appendix B.1 Panel B), one line per group.

**Step B6 — robustness, same rows unless stated.**
1. Replace `rG` with the displayed gap (opponent minus chooser rating).
2. Replace `rG` with `rG / kappa` (draw payoff in units of the premium).
3. Conditional logit with chooser FE on a uniform 20% sample of accounts; report log-odds slopes by group (proportional effects directly) and the BOTH − CO difference.
4. Roughly-equal positions only (`-100 <= v < 100`): `beta_g` from a model without the spline.
5. Exclude accounts flagged in Test A.
6. Full-panel classification with chooser FE (classify on all 24 months, estimate on all 24 months). Report as secondary only; it conditions the sample on its outcome and is here for comparison with Table 3's groups.

**Decision rule (pre-specified).** Let `rho_gap = (beta_BOTH/m_BOTH) / (beta_CO/m_CO)` and `rho_pos = (D_BOTH/m_BOTH) / (D_CO/m_CO)`.
- **Price**: `D_BOTH/m_BOTH` has a 95% CI excluding zero and `rho_pos >= 0.5`; AND `rho_gap <= 0.5` with the BOTH − CO difference in proportional gap slope significant at 5%. Keep the current framework file; apply its edit notes to Sections 4.5 and 7.2.
- **Merit**: `D_BOTH/m_BOTH` CI excludes zero and `rho_pos >= 0.5`; AND `rho_gap >= 0.5` with the 95% CI of the BOTH − CO difference including zero. Revert the framework to the version with the gap inside `mu` and `kappa` as the price; keep Section 4.5's existing text.
- **Uninformative**: `D_BOTH/m_BOTH` CI includes zero (BOTH accounts do not respond to the position; they are whim-granters). Run Test D.
- Anything else: report all four numbers with CIs and write the framework's price paragraph as a conjecture with the test described.

**Power note.** With roughly 10k BOTH accounts and ~15–25 P2 competitive opportunities each at an 8–10% grant rate, the SE on `beta_BOTH` is on the order of 0.05 pp per rating point; the pooled-sample slope is about 0.2 pp per point at a 2% base, i.e. roughly 0.1 proportional, so a merit-sized `beta_BOTH` (~0.8–1.0 pp/point) and zero are easily separated. Survivorship: BOTH accounts classified in P1 that stop playing before P2 drop out; report the P2 retention rate by group.

---

## Test C — Zero inflation among heavy players (the construal gate)

**Why.** Section 3.2 says most accounts never see a choice. A mixture with mass at zero predicts that, among accounts with many competitive opportunities, the share with zero grants flattens at a floor instead of falling toward zero as a smooth propensity distribution would predict.

**Sample.** All chooser accounts, full panel, competitive opportunities at all stages (the Section 5.1 definition).

**Step C1 — exposure.** For each competitive opportunity, compute `p_hat_o` = population grant rate in its cell, using the 500-cell grid of Appendix D.2 (five evaluation bands × four ply bands × five speeds × five gap bands), estimated on the full sample without cross-fitting. For each account: `n_i` (opportunities), `y_i` (grants), `E_i = sum_o p_hat_o` (expected grants at the population rate).

**Step C2 — descriptive figure.** `figC1_zero_share.pdf`: observed share of accounts with `y_i = 0` by bins of `E_i`: [0.25, 0.5), [0.5, 1), [1, 2), [2, 4), [4, 8), [8, 16), [16, 32), 32+. Overlay the zero share implied by a gamma–Poisson fit (Step C3a). Report N accounts per bin. Prediction under the gate: the observed curve flattens to a positive floor and sits above the fitted curve in the high-`E` bins.

**Step C3 — formal fits, on accounts with `E_i >= 0.25`.**
- (a) Gamma–Poisson: `y_i ~ Poisson(theta_i E_i)`, `theta_i ~ Gamma(k, k)`. ML for `k`. Implied zero share by bin: `(1 + E_i/k)^(-k)` averaged within bin.
- (b) Zero-inflated gamma–Poisson: with probability `1 − gamma` the account has `theta_i = 0`; otherwise as (a). ML for `(gamma, k)`.
- Report: `gamma` with 95% CI; LR test of (a) nested in (b) (boundary: use the 50:50 mixture of chi-square(0) and chi-square(1)); predicted vs observed zero share by bin under each.
- Also fit both on P1 alone and predict the P2 grant rate of accounts with `y_i = 0` and `E_i >= 8` in P1; compare with the observed P2 rate for those accounts (Section 5.1 reports 0.94% for a related group).

**Outputs.** `tabC1_zero_inflation.csv` (fits, tests, by-bin predictions), `figC1_zero_share.pdf`.

**Decision rule.**
- `gamma` CI excludes 1 and the high-`E` bins show a floor above the gamma–Poisson prediction: the gate is evidenced. Add a paragraph to Section 5.1 and cite it from Section 3.2.
- No floor and `gamma` CI includes 1: drop the construal gate as a mechanism. Section 3.2 keeps "most accounts never grant" as a description; Section 3.4 loses the gate-opening channel and the receipt effect is framed as a shift in `b_i`, i.e. the paper returns to the upstream-reciprocity framing of Section 1.1.

---

## Test D — Second proxy for not valuing rating points (only if B is uninformative)

**Why.** If BOTH accounts turn out to be whim-granters, a different proxy for low `lambda` is needed to test whether the gap slope is flatter where rating matters less.

**Proxy 1 — casual-game share.** The monthly database dumps include casual games (Event tag "Casual ... game"). For each chooser opportunity, compute the chooser's share of casual games among standard games in the 90 days ending the day before the opportunity; require ≥ 20 games in the window. Split into terciles of casual share (or ≥ 0.5 vs < 0.1 for a sharper contrast). Run the Test B primary model on the full competitive after-ply-10 sample with the tercile indicators in place of the granting-history groups; chooser FE stay in (casual share varies little within account, so group main effects are mostly absorbed; the interactions with `rG` and `f(v)` are identified from within-account variation in the game).

**Proxy 2 — provisional rating.** Chooser RD > 110 at the opportunity (the platform's provisional threshold). Same model with a provisional indicator interacted with `rG` and `f(v)`. Caveat to state in the output: provisional accounts are new accounts with large `K`, so `kappa` and `rG` are both larger in rating points; use the `rG / kappa` version of the regressor for this proxy.

**Prediction under price.** `beta` flatter in the high-casual or provisional group; `D` similar across groups. **Under merit.** No difference in `beta` across groups. Same decision thresholds as Test B with the proxy groups in place of BOTH and CO.

---

## Test E — Receipt: gate-opening vs a transient shift in `b_i`

**Why.** Section 3.4 carries two channels. A pure gate opens only for accounts that had not construed the choice; a transient `b_i` shift operates on everyone, including accounts that already grant.

**Groups of recipients at exposure.**
- PG: at least one grant as chooser, in any state, before the exposure date (full panel history, not the 90-day window). Construal known.
- PC: at least one competitive chooser-side choice before the exposure, all claims.
- NC: no competitive chooser-side choice before the exposure.

**Primary.** The Section 6.1 receipt design (exposure cells, weights, exposure-month FE, thirteen exposure-game controls, SEs clustered by exposure-opponent account), with the receipt indicator interacted with the three groups. Outcomes: grant at first later competitive choice (conditional) and the zero-coded version. Report the three effects, their SEs, and PG − NC with SE.

**Secondary.** The Table 4 IV model with receipt × group instrumented by score × group; report first stages by group and the three 2SLS estimates. Group PG is small (a few percent of exposures); report its SE and treat a CI that includes both zero and the pooled effect as uninformative.

**Also.** The interval profile of Section 6.1 (first choice within six hours; 30–90 days) by group, descriptively.

**Decision rule.**
- PG effect's CI excludes the pooled effect (0.4 OLS / 0.3 IV) and includes zero, and NC effect is positive: gate-opening dominates. Section 3.4 can lead with the gate and describe the `b_i` shift as not detected.
- PG effect positive with CI excluding zero: the `b_i` shift is present; keep both channels, and Section 1.1's upstream-reciprocity framing stands.
- PG uninformative: keep Section 3.4 as written.

---

## Test F — What persists between years: competitive generosity, lost-position grants, or both?

**Why.** The existing persistence result (competitive-position grant-rate correlation 0.545, unweighted, and 0.618, opportunity-weighted, among returning accounts) does not tell us whether granting to clearly-worse rivals is persistent, whether the same accounts exhibit both behaviors, or whether the two choices predict each other. Test F separates a stable general tendency to grant from persistence in *where* an account grants. This is prospective descriptive evidence, not identification of latent types or intrinsic motives.

**Main definitions.** Competitive (C): disconnected player's engine evaluation `v >= -100` cp. Clearly worse (L): `v <= -300` cp. The modestly-worse region `-300 < v < -100` (M) is excluded from the *main* C/L classification, not silently called noncompetitive. In a sensitivity, define all noncompetitive (N) as `v < -100`, i.e. M plus L. Use the paper's 41,534,331-row pool/nonadjacent sample, observed `grant` indicator, and P1/P2 windows from the conventions above.

**Step F0 — Reconcile the published competitive persistence statistic.** Reconstruct, for every chooser and year, the number of C/L/M opportunities and grants. Replicate the paper's C-only returning-account cohort: at least one competitive opportunity in each year and at least four competitive opportunities total. Report its size, raw year-to-year Pearson correlation, and correlation weighted by total competitive opportunities. Compare with the manuscript benchmarks (666,131 accounts; 0.545 and 0.618). If they differ, investigate sample/input definitions before reporting any F result.

**Step F1 — Year-specific histories.** For each chooser `i` and period `t ∈ {P1,P2}`, calculate `n_{iCt}, y_{iCt}` and `n_{iLt}, y_{iLt}` (and separate M quantities), and grant rates `p_{ist}=y_{ist}/n_{ist}` only where the denominator is positive. Export the account-level intermediate *privately* (Parquet; never put IDs in the transfer report). Report how many accounts lack exposure to either region in either year. Also report overall opportunities and grant rates by year/state.

**Step F2 — Holdout 4×4 transition matrix.** Classify each account *separately in each year* into `CO` (≥1 C grant, 0 L grants), `LO` (0 C, ≥1 L), `BOTH` (≥1 each), or `NEI` (0 in either focal region). A modestly-worse-only grant does not change `NEI`; always describe it as **neither focal state**, not **never grants**. Primary cohort: `n_C >= 4` and `n_L >= 4` in **each** year. Report accounts entering the P1 eligibility pool, return/eligibility rates by P1 group, and the complete 4×4 transition counts **and row percentages**. Recompute at thresholds of ≥1 and ≥10 opportunities per state per year, with cohort sizes. Do not characterize attrition as loss of propensity.

**Step F3 — Behavioral persistence, not just repeated ever-grants.** For each P1 group (CO, LO, BOTH, NEI), show P2 competitive and clearly-worse *opportunities, grants, pooled granting rate and equal-account mean granting rate*, conditioning on the F2 cohort. This is necessary because a year-two `BOTH` indicator is mechanically more likely among accounts with more opportunities. Report all four pairwise correlations on the same balanced cohort: `corr(C1,C2)`, `corr(L1,L2)`, `corr(C1,L2)`, and `corr(L1,C2)`, both with equal-account weights and harmonic-exposure weights. Also report the year-to-year correlation of the *selectivity index* `p_C - p_L`, alongside the correlation of the arithmetic mean `(p_C+p_L)/2`, on the same balanced cohort. Different base rates and sparse lost-position grants make the magnitudes incomparable without scale and precision qualifications.

**Step F4 — Joint cross-prediction models.** Estimate year-two C and L grant rates separately, weighted by the year-two number of opportunities in the dependent region, with a chooser-level cluster-robust covariance. In each model include P1 indicators `ever_C1`, `ever_L1`, and their interaction, plus at least the P1 C and L opportunity counts and the P2 opportunity counts. Adjust descriptively for the P2 region's mean chooser rating, rating gap, evaluation, game stage, and speed mix if available. On a parallel specification replace P1 ever-indicators with P1 region-specific grant rates. Report both outcomes on the same cohort, the joint covariance for between-outcome contrasts, and direct tests of whether C1 more strongly predicts C2 than L2, and whether L1 more strongly predicts L2 than C2, **scaling by each second-year outcome's mean**. Include confidence intervals, not only significance labels. These are predictive associations, not causal effects.

**Step F5 — Robustness and interpretation.** Repeat the transition/correlation analysis (i) for all noncompetitive states (`v < -100`, pooling M and L), (ii) for grants after ply 10 rather than all game stages, without silently changing the primary eligibility cohort, (iii) under 1/4/10-opportunity exposure thresholds, and (iv) excluding flagged accounts after Test A *if authenticated August flags and the same IDs can be safely linked*. The latter uses August status as a diagnostic, not a pre-P1 control.

**Decision framing (do not force a binary verdict).**
- **Selective persistence:** C1 strongly predicts C2 above L2 on an outcome-standardized scale, even after accounting for L1, and there is substantial same-region C persistence; L persistence can be weaker or absent.
- **Both persist, separately:** C1→C2 and L1→L2 are both strong, with meaningful within-region excess over cross-region predictions.
- **General granting tendency:** P1 C and L histories predict both P2 outcomes comparably, with little state-specific persistence after accounting for exposure.
- **Insufficient support:** L opportunities/grants or BOTH accounts are too sparse for precise inference; report intervals and do not equate imprecision with no persistence.

**Deliverables.** `tabF0_original_competitive_reconciliation.csv`, `tabF1_opportunities_by_year_state.csv`, `tabF1_region_exposure_support.csv`, `tabF2_transition_4x4.csv`, `tabF2_retention.csv`, `tabF3_P2_rates_by_P1_group.csv`, `tabF4_cross_year_correlations.csv`, `tabF4_selectivity_persistence.csv`, `tabF5_cross_prediction.csv`, `tabF6_threshold_sensitivity.csv`, `tabF6_transition_thresholds.csv`, `tabF7_noncompetitive_and_stage_sensitivity.csv`, `figF1_transition_heatmap.pdf` where the plotting library is available, and a private account-year-state Parquet with counts. All results must carry the F2 sample definition and N. **No API calls, Stockfish evaluations, or rating replay are required.**

---

## Output checklist

| File | Test |
|---|---|
| `tabA1_flags_by_group.csv`, `tabA2_patron_excluding_flags.csv`, `tabA3_recipient_patron_excluding_flags.csv` | A |
| `accounts_B_groups.parquet`, `tabB1_group_sizes.csv`, `tabB2_slopes_by_group.csv` (beta_g, D_g, m_g, proportional slopes, BOTH−CO differences, stage check), `tabB3_robustness.csv`, `figB1_gap_by_group.pdf` | B |
| `tabC1_zero_inflation.csv`, `figC1_zero_share.pdf` | C |
| `tabD1_proxy_slopes.csv` | D (conditional) |
| `tabE1_receipt_by_prior.csv` | E |
| `tabF0_original_competitive_reconciliation.csv`, `tabF1_opportunities_by_year_state.csv`, `tabF1_region_exposure_support.csv`, `tabF2_transition_4x4.csv`, `tabF2_retention.csv`, `tabF3_P2_rates_by_P1_group.csv`, `tabF4_cross_year_correlations.csv`, `tabF4_selectivity_persistence.csv`, `tabF5_cross_prediction.csv`, `tabF6_threshold_sensitivity.csv`, `tabF6_transition_thresholds.csv`, `tabF7_noncompetitive_and_stage_sensitivity.csv`, `figF1_transition_heatmap.pdf` | F |

Each table carries N opportunities, N accounts, and the exact sample definition in a header row. Log the run date and the commit hash of the code.

## What each outcome changes in the paper

| Outcome | Framework | Elsewhere |
|---|---|---|
| A: reversal survives exclusion | Keep 3.3, Prop 1(i) | Footnote flag shares in 5.2 |
| A: reversal collapses | 3.3 reads lost grants as "accounts that leave or are removed" | Rewrite 5.2's test paragraph; 7.1 second finding softened |
| B: price | Keep current file | 4.5: delete "does not fit" sentence, add the group-slope result; 7.2 "The cost" rewritten; Pope–Schweitzer to footnote |
| B: merit | Revert to gap-in-mu, kappa as price | 4.5 unchanged; 7.2 "The cost" unchanged |
| B: uninformative | Run D; price paragraph written as conjecture | — |
| C: floor found | Gate evidenced; cite from 3.2 | New paragraph in 5.1 |
| C: no floor | Gate dropped; receipt = b-shift only | 1.1 reciprocity framing stays; 3.4 shortened |
| E: PG ≈ 0, NC > 0 | Gate leads 3.4 | 7.2 "bundles" paragraph resolved toward learning |
| E: PG > 0 | Both channels kept | 1.1 unchanged |
| F: persistence concentrated in C | Distinguish stable selectivity from generic granting | Section 5.1: report C vs L cross-year persistence |
| F: both states persistent | Allow a stable general accommodation component and stable selectivity | Section 5.1: report both within-state and cross-state patterns |
| F: weak L support | No directional mechanistic conclusion | Footnote low lost-grant frequency and confidence intervals |

Compute: A and C are cheap (account-level). B is one regression on roughly 1–2M rows with chooser FE plus the robustness set. D requires extracting casual games from the dumps, the only new data pull. E reuses the Section 6 pipelines. F uses the same 41.5m analysis panel and only requires a new account-by-year-by-state aggregation (no new API, engine, or rating replay).


## 2026-10-12 runner engineering addendum

The `Framework_Tests_v1_0_2` runner repairs a numerical rank deficiency in
Test F's year-two cross-prediction regressions. Focal predictors are kept;
only redundant descriptive controls are pruned, with a report audit. The
original v1.0.1 output failed after source preflight and is not a result.
