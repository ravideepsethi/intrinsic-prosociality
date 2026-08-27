# Patron Stage 10 final authority ledger v1.0.0

**Project:** *The Structure of Intrinsic Prosociality: Field Evidence from Online Chess*  
**Frozen:** 2026-08-27  
**Scope:** Current-profile Patron analysis on the certified 24-month, Stockfish-18/100,000-node opportunity panel  
**Final status:** **PRIMARY CERTIFIED; POST-CERTIFICATION ADDENDUM CERTIFIED**

---

# 1. Final decision

Patron Stage 10 is computationally complete. The certified v1.0.1 production analysis remains the sole primary lineage. The separately authenticated post-certification addendum supplies missing-date sensitivities and two contract-completion model families without rerunning, replacing, or modifying the primary estimand.

The final authority is therefore deliberately two-lineage:

1. **Primary lineage — Patron Stage 10 v1.0.1:** confirmatory matched analysis, matching robustness, dose, diagnostic-kindness, price-ever indicators, and opportunity-level Patron structure.
2. **Secondary lineage — Post-certification addendum v1.0.0:** corrected account-date rich controls, chooser-level simultaneous five-bin Patron prediction, and continuous price count/rate companions.

These lineages must remain separate in receipts, folders, tables, documentation, and public replication materials. The addendum does not retroactively become part of the primary run.

No additional Patron acquisition, matching, API, or estimation run is required.

---

# 2. Precedence and status rules

Use the following order whenever Patron documents conflict:

1. This final authority ledger.
2. Authenticated v1.0.1 production results, manifests, and `_SUCCESS.json`.
3. Authenticated post-certification addendum results, manifest, stage receipt, and `_SUCCESS.json`.
4. `PATRON_STAGE10_RESULTS_REVIEW_v1_0_0_20260827.md`.
5. The v24 master handoff current layer.
6. Older August 25 handoffs, v23, prior-script memo, and the August 12 manuscript for history only.

Status vocabulary:

- **CERTIFIED PRIMARY:** paper-facing authority within the stated estimand and claim boundary.
- **CERTIFIED SECONDARY/SENSITIVITY:** valid addendum result; may be reported with its label but cannot be presented as a primary result.
- **HISTORICAL BENCHMARK:** older one-year/10,000-node Patron results, used only for replication comparisons.
- **SUPERSEDED FAILURE:** v1.0.0 production attempt; preserve for provenance but never use scientifically.

---

# 3. Locked data and design authority

## 3.1 Opportunity panel

```text
Sample:                       2023-11-01 through 2025-10-31 UTC
Engine:                       Stockfish 18, 100,000 nodes
Certified opportunities:     47,587,020
Kind draws:                      669,503
Fair opportunities:          17,328,130
Error rows:                            0
Duplicate game IDs:                    0
```

The disconnected-player evaluation bins are:

```text
Clearly better:  eval >= +300 cp
Better:          +101 to +299 cp
Roughly equal:   -100 to +100 cp
Modestly worse:  -299 to -101 cp
Clearly worse:   eval <= -300 cp
```

## 3.2 Current-profile snapshot

```text
Planned accounts:          1,305,872
Returned accounts:         1,305,683
Nonreturns:                      189
Current Patrons:               4,896
Snapshot SHA-256:
f42f28a6540a65c0a83f0da488663b4adddf60d1001daeed556f1ffbb961e238
```

The 189 nonreturns remain missing and must never be coded as non-Patrons.

## 3.3 Primary matched sample

The frozen 1:3 design matched current-profile controls before loading Patron outcomes.

```text
Fair-kind accounts:          248,930
Matched controls:            746,676
Total matched N:             995,606
Kind-group Patrons:            1,577
Control-group Patrons:         2,448
Match cells:                      37
```

The paper-facing outcome is **current Patron status**. Patron tenure and adoption dates are unavailable.

---

# 4. Authentication ledger

## 4.1 Primary v1.0.1 lineage

```text
Production status:
PATRON_STAGE10_PRODUCTION_CERTIFIED_OK

Production transfer:
PATRON_STAGE10_PRODUCTION_V101_RESULTS_20260827T011828Z.zip
SHA-256:
84c3067272a5adec9a4bfdfb5b84ffb7d7df8c6230b8ca49b5e1c696107768fd

Base _SUCCESS.json SHA-256:
5ee2169e3b87a0e1064e0d2953f6c5288e65287de7bdc4a5a1f26ae6e2ec2b0a

Base report manifest SHA-256:
4a3b082e655de50c5bc554d1b684387f4ed9ef7da24745d65b9c9c919b8f3f2d

Chooser cache SHA-256:
a0be630ac68f3624b35b0c3d388bc34ecb35be7575c7b911acbf4322354baeee

Opportunity cache SHA-256:
f6ee10fc947776601d513f40ede3d1d897db03ffba1121db68450ac204d3ee80
```

The addendum independently authenticated 23 base report files, the snapshot, the two private-cache hashes, the base success receipt, and the base report manifest. It recorded `base_lineage_modified: false`.

## 4.2 Addendum lineage

```text
Source package:
PatronStage10_Postcertification_Addendum_v1_0_0_20260827.zip
SHA-256:
6728449a9932a83642f2a74d517ec79720f4b0c4dc42a20546cfcc9d78f5d858

Production status:
PATRON_STAGE10_POSTCERTIFICATION_ADDENDUM_CERTIFIED_OK

Production transfer:
PATRON_STAGE10_POSTCERT_ADDENDUM_V100_RESULTS_20260827T022036Z.zip
SHA-256:
4a4b233b4d1a6ccb58f7668c8c00c7448d0c47c129eb93390cb75741f7f7ef5e

Addendum _SUCCESS.json SHA-256:
ed66b7073e19a1dc8654d34c45a449fb5344bf57eae0f5e622d8620707ed29bd

Public report manifest SHA-256:
63060d1c64a806cd1e1b08f23ff4d4653d2462e12642c43f733900074fb47605

Stage receipt SHA-256:
b3c333f29de32dcc650226b7b22f6f731e5574765d5368fd3a7c68584c60ae60

Executed-package manifest SHA-256:
5a98bae993f824f81502bed2439208284e1b02fdf8a7f5c5f5d05ce79aa8b01b
```

Independent review confirmed:

- ZIP and sidecar agreement;
- archive integrity;
- all 15 public-result files match the report manifest;
- all 24 executed-source files match the source manifest;
- all JSON is strict and contains no nonfinite values;
- no unmanifested files, `.pyc`, or `__pycache__` content;
- no username or row-level identifier columns; and
- no private caches in the transfer.

---

# 5. Certified primary results

## 5.1 Headline rates

| Group | Accounts | Patrons | Patron rate |
|---|---:|---:|---:|
| Fair-state kind choosers | 248,930 | 1,577 | 0.6335% |
| Frozen matched controls | 746,676 | 2,448 | 0.3279% |

```text
Raw gap:                  +0.305658 pp
Relative increase:       +93.2%
```

More than 99% of fair-kind choosers are not Patrons. The result is a population-level association, not an individual classifier.

## 5.2 Main estimators

| Specification | Effect (pp) | SE (pp) | 95% CI (pp) | p-value | N |
|---|---:|---:|---:|---:|---:|
| Raw frozen 1:3 | 0.3057 | 0.0172 | [0.2719, 0.3394] | 3.29e-96 | 995,606 |
| Match-cell FE, HC1 — primary | 0.3057 | 0.0172 | [0.2719, 0.3394] | 1.46e-70 | 995,606 |
| Match-cell FE, CR1 | 0.3057 | 0.0386 | [0.2300, 0.3813] | 2.33e-15 | 995,606 |
| v1.0.1 all controls, HC1 | 0.2701 | 0.0172 | [0.2364, 0.3037] | 9.40e-56 | 995,606 |
| v1.0.1 all controls, CR1 | 0.2701 | 0.0348 | [0.2019, 0.3383] | 8.44e-15 | 995,606 |

Exact primary coefficient:

```text
0.3056613950 percentage points
HC1 SE: 0.0172112698 pp
```

The v1.0.1 all-control estimate is 88.4% of the primary coefficient.

## 5.3 Covariate ladder

| Added controls | Effect (pp) |
|---|---:|
| Match-cell FE only | 0.3057 |
| Exposure volume | 0.3109 |
| Tenure, recency, and playtime | 0.2861 |
| Board-state composition | 0.2864 |
| Price composition | 0.2863 |
| Engagement | 0.2773 |
| Skill, stability, and all controls | 0.2701 |

The corrected-date version of the last row is reported separately in Section 7; it does not replace the primary row.

## 5.4 Matching robustness

- Complete four-account groups: 0.2704 pp fully adjusted.
- BOT exclusion: 0.2701 pp fully adjusted.
- Legacy 2–20 support: 0.2902 pp fully adjusted.
- Duration-scaled 2–40 support: 0.3003 pp fully adjusted.
- Pre-outcome overlap cells: 0.2697 pp fully adjusted, retaining 99.989% of the primary sample.
- Fixed control slots 1/2/3: FE effects 0.2977/0.3206/0.2989 pp; fully adjusted effects 0.2565/0.2816/0.2572 pp.
- One hundred deterministic valid 1:1 rematches: every FE and fully adjusted estimate is positive and significant at 5%.
- Rematch FE mean 0.3066 pp, range [0.2877, 0.3295].
- Rematch fully adjusted mean 0.2663 pp, range [0.2456, 0.2907].

## 5.5 Dose

| Fair-state kind count | Accounts | Patron rate |
|---|---:|---:|
| 0 | 1,056,753 | 0.3141% |
| 1 | 169,567 | 0.4783% |
| 2–4 | 60,645 | 0.8492% |
| 5–9 | 13,642 | 1.3561% |
| 10+ | 5,076 | 1.3002% |

Relative to zero, the match-cell-FE lifts are +0.1939, +0.4866, +0.9116, and +0.7993 pp. The pattern rises sharply and then saturates; it is not strictly monotonic at the top bin.

## 5.6 Diagnostic kindness

At the minimum-four common-support threshold:

| Kindness location | Patron rate |
|---|---:|
| Fair only | 0.8975% |
| Both fair and clearly worse | 0.5423% |
| Neither | 0.4334% |
| Clearly-worse only | 0.2575% |

Full-control coefficients:

```text
Fair-state kindness:                 +0.3835 pp
Clearly-worse kindness:              -0.1804 pp
Fair minus clearly-worse contrast:   +0.5638 pp
HC1 SE of contrast:                   0.0424 pp
HC1 p-value:                          1.95e-40
CR1 SE of contrast:                   0.0662 pp
CR1 p-value:                          1.60e-17
```

This is the strongest test against generic platform engagement, interface familiarity, or an undifferentiated tendency to select draws.

## 5.7 Certified price-ever indicators

At minimum four opportunities on each price side, with full controls:

```text
Ever costly-price kindness:          +0.2152 pp
Ever nonnegative-price kindness:     +0.3806 pp
Costly minus nonnegative:            -0.1654 pp
p-value for difference:               0.027
```

Costly kindness remains positively predictive, but favorable/nonnegative kindness carries the larger Patron association.

## 5.8 Opportunity-level Patron structure

These descriptive models use 32,858,962 opportunities from 1,305,683 returned accounts and cluster by chooser.

| Disconnected-player state | Patron-minus-nonpatron kindness gap |
|---|---:|
| Clearly better | +4.9735 pp |
| Better | +2.7650 pp |
| Roughly equal | +2.6693 pp |
| Modestly worse | +0.3000 pp |
| Clearly worse | −0.2583 pp |

In fair states, the patron-specific additional favorable-price response is +1.4626 pp (chooser-clustered SE 0.2431, p=1.79e-9). This is a different conditioning question from chooser-level Patron prediction.

---

# 6. Why the addendum was required

The audit found four limited implementation/documentation issues:

1. Missing `created_at_ms` and `seen_at_ms` values had become zero before v1.0.1 rich-control imputation because of DuckDB `greatest` behavior.
2. The frozen contract requested a chooser-level simultaneous five-bin Patron-prediction companion; v1.0.1 instead contained the distinct opportunity-level Patron-structure model.
3. The frozen contract requested price counts and rates in addition to ever indicators.
4. Typed lifetime total/rated/win/loss/draw counts were unavailable for every returned profile and therefore could not enter the estimator.

None affects the raw matched comparison, match-cell-FE primary, matching/rematch results, raw diagnostic groups, or opportunity-level appendix.

---

# 7. Certified addendum results

## 7.1 Corrected account-date rich controls

The addendum keeps absent dates missing, transforms only observed timestamps, applies outcome-blind within-cell median imputation, and activates explicit missing indicators.

```text
Profiles missing created/seen dates: 69,094
Missing share:                       5.2918%
Outcome used for imputation:         no
```

| Corrected specification | Effect (pp) | SE (pp) | p-value | N |
|---|---:|---:|---:|---:|
| All controls, HC1 | 0.269909 | 0.017170 | 1.10e-55 | 995,606 |
| All controls, match-cell CR1 | 0.269909 | 0.034767 | 8.28e-15 | 995,606 |
| Exclude disabled, HC1 | 0.282814 | 0.017978 | 9.23e-56 | 944,872 |
| Exclude TOS violations, HC1 | 0.272634 | 0.017618 | 5.17e-54 | 964,454 |
| Exclude disabled or TOS, HC1 | 0.285856 | 0.018473 | 5.20e-54 | 913,720 |

Comparison to the certified v1.0.1 rich-control value:

```text
Certified v1.0.1:              0.270085962 pp
Corrected-date sensitivity:    0.269909269 pp
Difference:                   -0.000176693 pp
Relative change:              approximately -0.065%
```

Judgment: the missing-date implementation issue is substantively immaterial. It does not alter the primary or rich-control conclusion.

## 7.2 Chooser-level simultaneous five-bin prediction

Support:

| Minimum opportunities in every bin | Users | Patrons | Match cells |
|---|---:|---:|---:|
| 0 | 1,305,683 | 4,896 | 41 |
| 2 | 254,832 | 1,239 | 20 |
| 4 | 100,904 | 518 | 16 |

Full-control HC1 coefficients, in percentage points:

| Support | Clearly better | Better | Roughly equal | Modestly worse | Clearly worse | Endpoint contrast |
|---|---:|---:|---:|---:|---:|---:|
| Min 0 | +0.2735 | +0.2522 | +0.2141 | −0.0357 | −0.1686 | +0.4421 |
| Min 2 | +0.3759 | +0.3305 | +0.1160 | −0.1428 | −0.2040 | +0.5799 |
| Min 4 | +0.2403 | +0.3072 | +0.1169 | +0.0388 | −0.2129 | +0.4532 |

For the demanding min-4 full-control model:

```text
Clearly-better minus clearly-worse:  +0.453221 pp
HC1 SE:                                0.129844 pp
HC1 p-value:                           0.000482
HC1 95% CI:                           [0.198731, 0.707712] pp
CR1 SE:                                0.104616 pp
CR1 p-value:                           1.48e-5
CR1 95% CI:                           [0.248178, 0.658265] pp
```

All five terms are identified. The broad favorable-to-unfavorable pattern and endpoint contrast are stable, but individual adjacent differences are not uniformly significant and min-4 point estimates are not strictly monotonic. The result supports a **coarse state-dependent gradient**, not a smooth or stepwise monotonic claim.

This +0.4532 pp endpoint is not the same estimand as the +0.5638 pp diagnostic fair-minus-clearly-worse horse race. Both may be reported, with their conditioning questions made explicit.

## 7.3 Continuous price count and rate companions

Support:

| Minimum opportunities on each price side | Users | Patrons | Match cells |
|---|---:|---:|---:|
| 2 | 653,924 | 3,253 | 24 |
| 4 | 399,553 | 2,181 | 20 |

Every coefficient below is the association from a one-standard-deviation increase, with costly and nonnegative measures entered jointly.

| Model | Costly coefficient | Nonnegative coefficient | Costly minus nonnegative | HC1 p for contrast |
|---|---:|---:|---:|---:|
| Min-2 log count, full controls | +0.0599 | +0.1228 | −0.0628 | 0.0128 |
| Min-2 rate, full controls | +0.0365 | +0.1208 | −0.0842 | 0.000636 |
| Min-4 log count, full controls | +0.0526 | +0.1425 | −0.0899 | 0.0137 |
| Min-4 rate, full controls | +0.0256 | +0.1486 | −0.1230 | 0.00616 |

Min-4 match-cell CR1 contrast inference:

```text
Count contrast:  -0.089945 pp, SE 0.037458, p=0.0163
Rate contrast:   -0.122954 pp, SE 0.058170, p=0.0345
```

At min-4 support, costly count intensity remains positively associated with Patron status. The costly rate coefficient is not independently significant, whereas the nonnegative count and rate coefficients are strongly positive. The correct interpretation is **structured, price-sensitive prosociality**, not cost-insensitive altruism.

---

# 8. Figure and table decisions

1. **Headline Patron panel:** retain the 0.6335% versus 0.3279% rates, +0.3057 pp primary effect, corrected +0.2699 pp rich-control sensitivity, and +0.5638 pp diagnostic contrast.
2. **Chooser five-bin figure:** retain a figure because every bin is identified and the endpoint contrast is strong. Plot full-control coefficients with 95% confidence intervals. Label the pattern coarse/state-dependent; do not call it strictly monotonic.
3. **Diagnostic horse race:** retain as a separate table or panel. Do not replace +0.5638 with the addendum's +0.4532.
4. **Price paragraph/table:** report ever indicators as the certified primary-generation diagnostic and add continuous count/rate results as secondary companions.
5. **Opportunity Patron structure:** retain in the appendix or a distinct panel. Never substitute it for chooser-level Patron prediction.

---

# 9. Claim ledger

## 9.1 Supported paper-facing claims

- Fair-state kind choosers have nearly twice the raw current-Patron rate of frozen matched controls.
- The association remains economically similar after extensive observed controls and corrected missing-date handling.
- It survives match-cell clustering, support changes, fixed control slots, and 100 deterministic rematches.
- Patron rates rise sharply with repeated fair-state kindness and then saturate.
- Kindness in fair/prosocially diagnostic states is positively associated with Patron status, while kindness toward clearly-losing opponents is absent or negatively associated.
- The historical one-year/10,000-node diagnostic structure closely replicates in the current 24-month/100,000-node design.
- Patron prediction is state-dependent and price-sensitive.

## 9.2 Claims that remain prohibited

- Kind draws cause Patron adoption.
- Patron status was adopted after the observed behavior.
- The analysis identifies a person's general generosity outside Lichess.
- More rating-costly kindness is more predictive than favorable kindness.
- The five-bin Patron association is strictly monotonic.
- The rich-control model directly observes lifetime total-game counts.
- Opportunity-level Patron structure and chooser-level Patron prediction are the same estimand.
- The addendum is a new primary or a recovery from a failed primary result.

Preferred summary language:

> In the frozen 24-month matched sample, current Patron status is 0.634% among fair-state kind choosers and 0.328% among controls, a 0.306-percentage-point gap and 93% relative increase. The association survives rich observed controls, corrected account-date handling, rematching, and match-cell-clustered inference. It is strongest when kindness occurs in prosocially diagnostic states and is more strongly associated with favorable than costly price-side kindness. Because Patron tenure is unavailable, these results identify stable cross-decision heterogeneity on Lichess rather than Patron adoption or causality.

---

# 10. Data limitations that must remain visible

1. Patron status is current status at the profile query date; adoption timing is unknown.
2. The decision is same-platform, not an independent observation from broader life.
3. Patron is public and monetary, whereas the draw decision is private at the moment of choice and rating-denominated.
4. Typed profile fields for total/rated/win/loss/draw game counts are missing for every returned account. The estimator drops these unsupported terms deterministically.
5. Available controls include panel exposure, active months, playtime where available, per-pool current games/ratings, skill, rating stability, speed composition, and board-state/price composition.
6. Cluster sensitivities use a modest number of match cells; report HC1 as primary and CR1 as a sensitivity rather than calling CR1 automatically conservative.
7. All addendum p-values are secondary/sensitivity inference and should not be promoted into a new confirmatory family.

---

# 11. Privacy, publication, and preservation

Preserve read-only on `XT_Pro`:

```text
/Volumes/XT_Pro/lichess_kindness/output/PATRON_STAGE10_PRODUCTION_V100
/Volumes/XT_Pro/lichess_kindness/output/PATRON_STAGE10_POSTCERT_ADDENDUM_V100
```

Also preserve the complete profile snapshot, acquisition checkpoint/log, v1.0.0 failure lineage, v1.0.1 package/log, addendum package/log, transfer ZIPs, sidecars, manifests, and receipts.

Public release may contain authenticated aggregate results, executed source, documentation, report manifests, and success receipts. It must exclude raw/lossless profile rows, usernames, row-level identifiers, private caches, transfer staging, temporary logs, `.pyc`, and `__pycache__`.

Do not merge the two output trees or rewrite their receipts into a fictional single run.

---

# 12. Final frozen status line

```text
PATRON STAGE 10 FINAL AUTHORITY:
v1.0.1 PRIMARY CERTIFIED + v1.0.0 POST-CERTIFICATION ADDENDUM CERTIFIED.
Primary effect = +0.305661 pp.
Corrected rich-control sensitivity = +0.269909 pp.
Diagnostic fair-minus-clearly-worse contrast = +0.563825 pp.
Chooser five-bin min-4 endpoint contrast = +0.453221 pp.
Interpretation = current cross-sectional stable-type/cross-decision association;
not Patron adoption, causality, or general generosity outside Lichess.
```
