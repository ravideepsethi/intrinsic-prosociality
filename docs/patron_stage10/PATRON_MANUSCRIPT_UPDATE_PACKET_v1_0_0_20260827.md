# Patron manuscript update packet v1.0.0

**Paper:** *The Structure of Intrinsic Prosociality: Field Evidence from Online Chess*  
**Prepared:** 2026-08-27  
**Purpose:** Ready-to-apply replacement language, tables, figure data, footnotes, and QA checks for the final 24-month Patron section  
**Authority:** Patron Stage 10 v1.0.1 primary + post-certification addendum v1.0.0 secondary/sensitivity

---

# 1. Editorial decision

The current Patron evidence is strong enough for the main paper. It should remain the third results pillar—**cross-decision validation**—after structure and dynamics. The section should be compact in the main text and unusually transparent about three boundaries:

1. Patronage is a distinct monetary decision, but it occurs on the same platform.
2. Current Patron status is cross-sectional; adoption timing is not observed.
3. The association is strongest for kindness in diagnostically prosocial states and for favorable-price kindness. It is not evidence of a cost-insensitive altruistic type.

Recommended main-text content:

- headline matched rates and primary match-cell-FE estimate;
- corrected rich-control sensitivity;
- matching/rematch robustness in one sentence;
- dose pattern in one compact panel or sentence;
- diagnostic fair-versus-clearly-worse horse race;
- chooser five-bin figure;
- one price-sensitivity paragraph; and
- a clear noncausal limitation paragraph.

Put the full ladder, support variants, all rematches, continuous price specifications, opportunity-level interactions, authentication, and missingness details in the appendix.

---

# 2. Global manuscript replacements

Search the entire manuscript, tables, notes, figure captions, online appendix, and abstract for the following stale items.

| Retire | Replace with / action |
|---|---|
| `722,938` matched observations | `995,606` in the frozen 1:3 fair-kind primary sample |
| `0.6042%` kind-chooser Patron rate | `0.6335%` |
| `0.3593%` control Patron rate | `0.3279%` |
| `0.2449 pp` raw gap | `0.3057 pp` |
| `68%` relative difference | `93.2%` relative increase |
| “June snapshot” | “complete current-profile snapshot” or the exact August 2026 query description |
| “later Patron adoption” | “current Patron status” |
| “kindness predicts later adoption” | “kindness is associated with current Patron status” |
| “price diagnostic not run” | Replace with the certified ever-indicator and addendum count/rate results |
| old opportunity Patron interactions | Replace with the current 24-month opportunity estimates |
| old Figure 4 numerical series | Replace with the chooser-level simultaneous five-bin estimates below |

Also search for loose variants:

```text
68 percent
68%
0.60%
0.36%
0.604
0.359
0.245
June profile
later patron
patron adoption
adopted patron
price test
not yet run
```

Do not globally replace historical replication-table values. Those may remain when explicitly labeled **historical one-year/10,000-node benchmark**.

---

# 3. Abstract replacement

Recommended Patron sentence:

> In the frozen 24-month matched sample, current Patron status is 0.634% among fair-state kind choosers and 0.328% among controls, a 0.306-percentage-point gap and 93% relative increase; the association survives rich observed controls and is absent or reversed when kindness occurs toward opponents who were already clearly lost.

If the abstract has space for the conceptual boundary, add:

> Because Patron tenure is unavailable, this result identifies stable cross-decision heterogeneity on the platform rather than a causal effect on Patron adoption.

Do not place the five-bin or price coefficients in the abstract. Their role is to clarify signal content, not to become additional headline estimates.

---

# 4. Introduction contribution paragraph

Ready-to-paste draft:

> Finally, the behavioral signal travels to a distinct costly decision on the same platform. Lichess users may voluntarily support the platform financially and receive a visible Patron badge. In a frozen matched design, current Patron status is 0.634 percent among players who granted fair-state kind draws and 0.328 percent among controls, a 93 percent relative increase. The association survives extensive controls and rematching, rises sharply with repeated fair-state kindness, and depends on where the kindness occurred: kindness when the disconnected opponent remained competitive predicts Patron status, whereas kindness toward already-clearly-losing opponents does not. Patronage is monetary and public rather than rating-denominated and private, so this comparison validates the content of the behavioral signal across decisions. Because Patron adoption dates are unavailable, however, it is evidence of stable cross-decision heterogeneity rather than temporal adoption or causality.

Use “cross-decision validation” as the default label. “Cross-domain evidence within Lichess” is acceptable when the same-platform limitation is stated. Avoid unqualified “external validity.”

---

# 5. Methods/data paragraph for the Patron subsection

Ready-to-paste draft:

> We obtained a complete current-profile snapshot for the 1,305,872 accounts in the frozen acquisition plan. The API returned 1,305,683 accounts, of whom 4,896 were current Patrons; the 189 nonreturns remain missing rather than being coded as non-Patrons. Before loading Patron outcomes, we classified accounts using the certified 24-month opportunity panel and constructed a deterministic 1:3 matched design within opportunity-volume and modal-speed cells. The primary comparison contains 248,930 fair-state kind choosers and 746,676 controls. We estimate linear-probability models with matching-cell fixed effects and HC1 standard errors, and report matching-cell-clustered inference as a sensitivity. Rich specifications add pre-existing panel exposure and composition, current profile engagement, skill, rating stability, account tenure and recency, and available speed-specific activity measures. Typed profile fields for lifetime total, rated, win, loss, and draw counts are unavailable for all returned accounts and therefore are not included.

Methods footnote:

> The profile snapshot records current Patron status but not Patron tenure. The profile query date therefore does not establish when support began relative to the behavioral panel. Missing account dates are retained as missing and imputed within treatment-blind matching cells with explicit missingness indicators in the corrected rich-control sensitivity.

---

# 6. Full replacement draft for the results subsection

## Cross-decision validation: platform support

> Patronage provides a useful cross-decision test of the behavioral signal. A Patron makes a voluntary monetary contribution to Lichess and receives a public badge. This choice differs from granting a draw along several dimensions: it is monetary rather than rating-denominated, public rather than private at the moment of choice, and accompanied by a modest expressive return. At the same time, it remains a decision on Lichess and therefore should not be read as a measure of generosity across life domains.
>
> In the frozen 1:3 matched sample, 1,577 of 248,930 fair-state kind choosers are current Patrons, compared with 2,448 of 746,676 controls. The corresponding rates are 0.6335 and 0.3279 percent. The raw difference is 0.3057 percentage points, a 93.2 percent relative increase. Matching-cell fixed effects leave the estimate unchanged at 0.3057 percentage points (HC1 SE 0.0172). Matching-cell-clustered inference yields an SE of 0.0386 and remains decisive.
>
> Extensive observed controls explain little of the association. With corrected account-date handling and the full control set, the coefficient is 0.2699 percentage points (HC1 SE 0.0172; matching-cell-clustered SE 0.0348), 88 percent of the primary estimate. Excluding disabled accounts or terms-of-service violators produces slightly larger estimates. The result is also insensitive to matching support, fixed control slots, and rematching: across 100 deterministic valid one-to-one rematches, every fixed-effect and fully adjusted estimate is positive and significant at the five-percent level.
>
> Patron rates also rise sharply with repeated fair-state kindness. They are 0.314 percent among accounts with no fair-state kind draw, 0.478 percent after one, 0.849 percent after two to four, 1.356 percent after five to nine, and 1.300 percent after ten or more. The slight decline in the top bin precludes a strictly monotonic interpretation, but the broad dose pattern is large and saturating.
>
> The location of kindness is more informative than an undifferentiated tendency to grant draws. Among accounts with at least four opportunities in both fair and clearly-worse states, the current-Patron rate is 0.898 percent for fair-only kind choosers, 0.542 percent for those kind in both states, 0.433 percent for those kind in neither, and 0.258 percent for clearly-worse-only kind choosers. With full controls, fair-state kindness loads positively by 0.384 percentage points, clearly-worse kindness loads negatively by 0.180 percentage points, and their difference is 0.564 percentage points (HC1 SE 0.042; matching-cell-clustered SE 0.066).
>
> A simultaneous five-state specification reaches the same conclusion without collapsing competitive states. On common min-four support, the full-control Patron coefficients are 0.240, 0.307, 0.117, 0.039, and −0.213 percentage points as the disconnected opponent moves from clearly better to clearly worse. The clearly-better-minus-clearly-worse endpoint is 0.453 percentage points (HC1 SE 0.130; matching-cell-clustered SE 0.105). The pattern is coarse rather than strictly stepwise, but it shows that the cross-decision signal resides in where kindness occurs.
>
> Price further organizes the signal. Both costly-price and nonnegative-price fair-state kindness are positively associated with current Patron status in count specifications, but favorable-price kindness is consistently more predictive. At min-four support, a one-standard-deviation increase in costly-kindness count predicts 0.053 percentage points more Patron status, compared with 0.143 percentage points for nonnegative-price kindness; the difference is −0.090 percentage points. Rate specifications imply a difference of −0.123 percentage points. Both contrasts survive matching-cell-clustered inference. Thus Patron prediction is price-sensitive rather than a measure of cost-insensitive altruism.
>
> These results are most naturally interpreted as stable cross-decision heterogeneity. They replicate the diagnostic structure found in the earlier one-year/shallower-engine analysis using a new 24-month window, deeper engine evaluation, a complete current-profile snapshot, and more Patrons. They do not show that granting a kind draw causes Patron adoption: Patron tenure is unavailable, both decisions occur on Lichess, and unobserved stable traits may contribute to both.

Editorial note: if this complete text is too long for the main paper, keep paragraphs 1, 2, 3, 5, and 8. Move dose, five-bin detail, and continuous-price magnitudes to the appendix while retaining one sentence about each in the main text.

---

# 7. Table 10 — headline matched comparison

Suggested title:

> **Table 10. Fair-state kindness and current Patron status**

| Group/specification | Accounts | Patrons | Patron rate | Effect (pp) | SE (pp) |
|---|---:|---:|---:|---:|---:|
| Fair-state kind choosers | 248,930 | 1,577 | 0.6335% |  |  |
| Frozen matched controls | 746,676 | 2,448 | 0.3279% |  |  |
| Raw difference | 995,606 | 4,025 |  | 0.3057 | 0.0172 |
| Match-cell FE, HC1 — primary | 995,606 | 4,025 |  | 0.3057 | 0.0172 |
| Match-cell FE, CR1 | 995,606 | 4,025 |  | 0.3057 | 0.0386 |
| Corrected full controls, HC1 | 995,606 | 4,025 |  | 0.2699 | 0.0172 |
| Corrected full controls, CR1 | 995,606 | 4,025 |  | 0.2699 | 0.0348 |

Suggested note:

> The primary sample is constructed by deterministic 1:3 matching before Patron outcomes are loaded. Effects are percentage-point coefficients from linear-probability models. The corrected full-control sensitivity retains missing account dates through feature construction, imputes within outcome-blind matching cells, and includes explicit missingness indicators. CR1 clusters by the 37 matching cells. Current Patron status is cross-sectional.

---

# 8. Table 11 — covariate ladder and exclusions

Suggested title:

> **Table 11. Stability across observed controls and account exclusions**

| Specification | Effect (pp) | SE (pp) | N |
|---|---:|---:|---:|
| Match-cell FE only | 0.3057 | 0.0172 | 995,606 |
| + Exposure volume | 0.3109 |  | 995,606 |
| + Tenure, recency, playtime | 0.2861 |  | 995,606 |
| + Board-state composition | 0.2864 |  | 995,606 |
| + Price composition | 0.2863 |  | 995,606 |
| + Engagement | 0.2773 |  | 995,606 |
| Corrected all controls, HC1 | 0.2699 | 0.0172 | 995,606 |
| Corrected all controls, CR1 | 0.2699 | 0.0348 | 995,606 |
| Corrected all controls, exclude disabled | 0.2828 | 0.0180 | 944,872 |
| Corrected all controls, exclude TOS violations | 0.2726 | 0.0176 | 964,454 |
| Corrected all controls, exclude either | 0.2859 | 0.0185 | 913,720 |

Populate the omitted ladder SEs directly from the authenticated v1.0.1 CSV when typesetting. Do not invent them from rounded chat values.

---

# 9. Table 12 — matching robustness

Suggested compact panel:

| Design | FE estimate (pp) | Fully adjusted estimate (pp) |
|---|---:|---:|
| Frozen 1:3 | 0.3057 | 0.2701 |
| Fixed control slot 1 | 0.2977 | 0.2565 |
| Fixed control slot 2 | 0.3206 | 0.2816 |
| Fixed control slot 3 | 0.2989 | 0.2572 |
| 100 valid 1:1 rematches, mean | 0.3066 | 0.2663 |
| 100 valid 1:1 rematches, range | [0.2877, 0.3295] | [0.2456, 0.2907] |

Table note:

> Every estimate across the 100 fixed-effect and fully adjusted rematches is positive and significant at five percent. The 1:3 design is primary; rematches are deterministic robustness checks.

---

# 10. Table 13 — dose

| Fair-state kind-draw count | Accounts | Patron rate |
|---|---:|---:|
| 0 | 1,056,753 | 0.3141% |
| 1 | 169,567 | 0.4783% |
| 2–4 | 60,645 | 0.8492% |
| 5–9 | 13,642 | 1.3561% |
| 10+ | 5,076 | 1.3002% |

Preferred prose:

> Patron rates rise sharply with repeated fair-state kindness and then saturate. We do not interpret the slight 5–9 versus 10+ reversal as evidence against dose dependence or claim strict monotonicity.

---

# 11. Figure 4 — chooser five-bin Patron prediction

Recommended title:

> **Figure 4. The Patron association depends on where kindness occurs**

Use the min-4, full-control HC1 estimates as the main plotted series:

| Disconnected-player state | Coefficient (pp) | HC1 SE | 95% CI |
|---|---:|---:|---:|
| Clearly better | 0.2403 | 0.1033 | [0.0378, 0.4427] |
| Better | 0.3072 | 0.1334 | [0.0457, 0.5686] |
| Roughly equal | 0.1169 | 0.0952 | [−0.0696, 0.3035] |
| Modestly worse | 0.0388 | 0.1550 | [−0.2650, 0.3425] |
| Clearly worse | −0.2129 | 0.0715 | [−0.3530, −0.0729] |

Add a bracket or textual annotation:

```text
Clearly better minus clearly worse:
+0.4532 pp; HC1 p=.00048; match-cell CR1 p=1.48e-5
```

Recommended caption:

> Coefficients from a simultaneous chooser-level linear-probability model of current Patron status on indicators for ever granting a kind draw in each evaluation bin, corresponding exposure controls, matching-cell fixed effects, and the full observed control set. The sample requires at least four opportunities in every evaluation bin (N=100,904; 518 Patrons; 16 matching cells). Error bars show 95% HC1 confidence intervals. The broad favorable-to-unfavorable ordering and endpoint contrast are robust, but adjacent differences are not uniformly significant; the figure should not be interpreted as a strictly monotonic dose curve. Patron status is current and cross-sectional.

Styling guidance:

- Order bins from disconnected clearly better to clearly worse.
- Include a horizontal zero line.
- Use one restrained color family, with the clearly-worse point differentiated only if consistent with the paper's house style.
- Do not plot raw Patron rates and regression coefficients on the same axis.
- Put min-0 and min-2 estimates in an appendix sensitivity figure or table.

---

# 12. Table 14 — opportunity-level Patron structure

This table answers whether Patrons exhibit a steeper state gradient when making draw decisions. It does **not** predict Patron status.

| Disconnected-player state | Adjusted Patron-minus-nonpatron kindness gap |
|---|---:|
| Clearly better | +4.9735 pp |
| Better | +2.7650 pp |
| Roughly equal | +2.6693 pp |
| Modestly worse | +0.3000 pp |
| Clearly worse | −0.2583 pp |

Price panel:

```text
Patron gap at costly fair draws:                  +2.2899 pp
SE:                                                0.3311 pp
Additional patron favorable-price response:      +1.4626 pp
SE:                                                0.2431 pp
Implied patron favorable-price response:          approximately +2.0106 pp
Implied patron gap in favorable fair states:      approximately +3.7525 pp
```

Do not attach standard errors to derived sums unless the covariance is recovered from the authenticated model object.

---

# 13. Table 15 — diagnostic horse race

Panel A: raw rates.

| Kindness location | Patron rate |
|---|---:|
| Fair only | 0.8975% |
| Both | 0.5423% |
| Neither | 0.4334% |
| Clearly-worse only | 0.2575% |

Panel B: fully controlled coefficients.

| Term/contrast | Estimate (pp) | HC1 SE (pp) | Match-cell CR1 SE (pp) |
|---|---:|---:|---:|
| Fair-state kindness | +0.3835 | Use source CSV | Use source CSV |
| Clearly-worse kindness | −0.1804 | Use source CSV | Use source CSV |
| Fair minus clearly worse | +0.5638 | 0.0424 | 0.0662 |

Recommended sentence:

> Patronage is associated with kindness where the act is diagnostically prosocial, not with an undifferentiated tendency to grant draws. With full controls, the fair-state and clearly-worse coefficients differ by 0.564 percentage points (HC1 SE 0.042; matching-cell-clustered SE 0.066).

---

# 14. Appendix price table

Panel A: certified ever-kind indicators.

| Min support | Costly kindness | Nonnegative kindness | Costly minus nonnegative | p-value |
|---|---:|---:|---:|---:|
| 2 opportunities/side | +0.2316 | +0.3166 | −0.0849 | 0.124 |
| 4 opportunities/side | +0.2152 | +0.3806 | −0.1654 | 0.027 |

Panel B: addendum standardized continuous companions.

| Model | Costly | Nonnegative | Difference | HC1 p | CR1 p where available |
|---|---:|---:|---:|---:|---:|
| Min-2 log count | +0.0599 | +0.1228 | −0.0628 | 0.0128 |  |
| Min-2 rate | +0.0365 | +0.1208 | −0.0842 | 0.000636 |  |
| Min-4 log count | +0.0526 | +0.1425 | −0.0899 | 0.0137 | 0.0163 |
| Min-4 rate | +0.0256 | +0.1486 | −0.1230 | 0.00616 | 0.0345 |

Suggested note:

> Count and rate coefficients correspond to one-standard-deviation increases and enter costly and nonnegative kindness jointly with corresponding exposure controls, matching-cell fixed effects, and the full control set. These are post-certification secondary companions. At min-four support, the costly-rate coefficient is not independently significant, although the costly count coefficient remains positive. The consistent negative contrast means favorable/nonnegative kindness is more predictive of current Patron status.

---

# 15. Discussion replacement

Ready-to-paste paragraph:

> The Patron comparison clarifies both the reach and the limits of the behavioral signal. Private fair-state kindness predicts a distinct monetary support decision after extensive matching and observed controls, and the diagnostic pattern closely replicates in a new window and engine layer. Yet the association is neither context-free nor evidence of a unitary cost-insensitive motive. It is concentrated in states where granting the draw is prosocially diagnostic and is stronger for favorable-price than costly-price kindness. The evidence therefore fits stable heterogeneity whose expression is organized by desert and price. Because Patron tenure is unavailable and both decisions occur on Lichess, the result is cross-decision validation rather than a causal adoption design or a claim about generosity across life domains.

---

# 16. Conclusion replacement

Recommended final Patron sentence:

> The same behavioral signal predicts voluntary financial support for the platform, but only in the states where kindness is most diagnostic, linking private revealed preference to a distinct costly decision while preserving the limits of a same-platform, cross-sectional design.

Avoid ending the paper with the 93% number alone. The conceptual contribution is the **organized content** of the association, not merely its statistical size.

---

# 17. Appendix audit disclosure

Suggested concise disclosure:

> A post-certification audit found that missing account-creation and last-seen dates had been transformed to zero before the original rich-control imputation step. This did not affect the raw matched comparison, primary matching-cell-fixed-effect model, matching robustness, diagnostic groups, or opportunity models. A separate addendum retained missing dates explicitly, imputed within outcome-blind matching cells, and activated missingness indicators. The corrected full-control coefficient is 0.2699 percentage points, compared with 0.2701 in the certified production output. The addendum also completed prespecified chooser-level five-bin and continuous price count/rate companions. The primary result and its receipt were not rerun or modified.

Replication-package disclosure:

> The public package keeps the certified v1.0.1 production lineage and the post-certification addendum lineage separate. Each contains aggregate results, executed source, manifests, and success receipts. Raw profiles, usernames, row-level identifiers, and private caches are excluded.

---

# 18. Claim-safe terminology

Use:

- current Patron status;
- matched association;
- cross-decision validation;
- stable cross-decision heterogeneity;
- coarse state-dependent gradient;
- structured, price-sensitive prosociality;
- same-platform limitation;
- post-certification secondary/sensitivity analysis.

Avoid:

- later Patron adoption;
- kindness causes support;
- external validation without qualification;
- general generosity;
- strictly monotonic five-bin gradient;
- cost-insensitive altruism;
- conservative CR1 inference;
- full lifetime-game-count controls;
- corrected primary estimate;
- merged v1.0.1/addendum run.

---

# 19. Final numerical QA checklist

Before generating the next PDF:

1. Rebuild every table/figure from authenticated aggregate CSV/JSON outputs, not rounded prose in this packet.
2. Confirm the primary coefficient remains `0.3056613950 pp` everywhere.
3. Confirm the corrected rich-control value is `0.2699092687 pp` and is labeled sensitivity.
4. Confirm the diagnostic contrast is `0.563825 pp` and is not confused with the chooser five-bin endpoint.
5. Confirm the chooser five-bin endpoint is `0.453221 pp` on min-4 common support.
6. Confirm Table 10 N is `995,606`, not the full returned-profile count.
7. Confirm Figure 4 N is `100,904`, with 518 Patrons and 16 matching cells.
8. Confirm continuous-price min-4 N is `399,553`, with 2,181 Patrons and 20 matching cells.
9. Confirm all price count/rate coefficients are described as one-standard-deviation associations.
10. Confirm the 10+ dose bin is not called evidence of strict monotonicity.
11. Confirm the 189 profile nonreturns remain missing.
12. Confirm no sentence calls current status adoption or implies causal temporal ordering.
13. Confirm opportunity-level Patron structure and chooser-level Patron prediction have distinct headings and notes.
14. Confirm typed lifetime total/rated/win/loss/draw counts are not claimed as controls.
15. Confirm the addendum is labeled secondary/sensitivity and the v1.0.1 primary remains unchanged.
16. Search the compiled PDF text for every stale number and phrase listed in Section 2.

---

# 20. Final section-level takeaway

The Patron section should leave the reader with this hierarchy:

1. The raw current-Patron rate nearly doubles among fair-state kind choosers.
2. Matching, controls, corrected missing-date handling, and rematching do not explain the association.
3. Repetition strengthens the association, but the signal is not merely draw frequency.
4. Kindness predicts Patron status when it occurs in diagnostically prosocial states, not when the opponent is already clearly lost.
5. Favorable-price kindness is more predictive than costly-price kindness, so the stable type is structured and price-sensitive.
6. The evidence validates the behavioral signal across two Lichess decisions; it does not identify Patron adoption or general generosity.
