# Patron Stage 10 certified-results review v1.0.0

Prepared 2026-08-27 from the authenticated Stage 10 v1.0.1 transfer bundle.

## 1. Bottom line

The 24-month, Stockfish-100k patron analysis provides strong and unusually
coherent cross-domain evidence for stable, structured prosocial heterogeneity.
Among returned accounts in the frozen fair-kind matched sample, current patron
status is 0.6335% for kind choosers and 0.3279% for their three immutable
controls. The raw gap is 0.3057 percentage points, a 93.2% relative increase.
The prespecified match-cell fixed-effects estimate is 0.3057 pp (HC1 SE 0.0172,
95% CI [0.2719, 0.3394], p = 1.46e-70).

The association is not explained by one matching choice, a few cells, bots,
nonreturns, or observed activity/profile composition. The fully adjusted
estimate is 0.2701 pp (HC1 SE 0.0172, 95% CI [0.2364, 0.3037]); conservative
match-cell-clustered inference remains decisive (CR1 SE 0.0348, p = 8.44e-15).

The most probative result is the diagnostic horse race. At the prespecified
minimum-four-opportunity threshold and with the full control set, ever being
kind in a fair state predicts patronage by +0.3835 pp, whereas ever being kind
when the disconnected opponent was clearly worse predicts patronage by
-0.1804 pp. Their difference is +0.5638 pp (HC1 SE 0.0424, p = 1.95e-40;
match-cell-clustered p = 1.60e-17). Patronage therefore loads on kindness where
the act is diagnostically prosocial, not on an undifferentiated tendency to
choose draws.

These results support a stable-type/cross-decision interpretation. They do not
identify patron-adoption timing and do not show that kind draws cause patronage.

## 2. Authentication and provenance

- Uploaded transfer ZIP SHA-256:
  `84c3067272a5adec9a4bfdfb5b84ffb7d7df8c6230b8ca49b5e1c696107768fd`.
- The uploaded sidecar and observed ZIP digest agree exactly.
- ZIP integrity test passed.
- All 23 public result files match `report_file_hashes.tsv` by byte count and
  SHA-256.
- The report-manifest SHA matches `_SUCCESS.json`:
  `4a3b082e655de50c5bc554d1b684387f4ed9ef7da24745d65b9c9c919b8f3f2d`.
- All Stage 01 and Stage 02 public-output hashes match their authenticated
  success receipts.
- Final status: `PATRON_STAGE10_PRODUCTION_CERTIFIED_OK`, version 1.0.1.
- Runtime environment: Python 3.13.9, DuckDB 1.5.2, NumPy 2.4.4,
  Pandas 3.0.3, PyArrow 24.0.0.
- Privacy audit passed: no usernames, raw profile JSON, row-level profiles, or
  private caches appear in public results.

The copied executed-source directory contains one unmanifested, generated
Python bytecode file:
`code/__pycache__/patron_stage10_common.cpython-313.pyc`, SHA-256
`7962031e1b15d86ba8b4ca3fda64cd5b191ceaf14d5beb70b5ffb7b219837f06`.
All 16 manifested source files still authenticate. The extra is a runtime cache,
contains no observed row identifiers, and has no analytical or privacy effect.
It should be removed from any public publication bundle.

## 3. Outcome and coverage QA

- Planned unique accounts: 1,305,872.
- Returned profiles: 1,305,683 (99.9855%).
- Explicit nonreturns: 189; all remain missing outcomes.
- Current patrons: 4,896.
- Kind-role returned accounts: 326,427; patrons: 1,743.
- Control-role returned accounts: 979,256; patrons: 3,153.
- No returned profile has missing patron status.
- No nonreturned profile was assigned patron status.
- No patron=true row lacks the patron field.
- BOT-title accounts: 43; patrons among them: zero.

The broad acquisition-role audit is 0.5340% versus 0.3220%, a 0.2120 pp gap
and 65.8% relative increase. This is QA/secondary. The paper-facing estimand is
the fair-kind frozen 1:3 comparison below.

## 4. Main fair-kind matched result

| Specification | Effect (pp) | SE (pp) | 95% CI (pp) | p-value | N |
|---|---:|---:|---:|---:|---:|
| Raw frozen 1:3 | 0.3057 | 0.0172 | [0.2719, 0.3394] | 3.29e-96 | 995,606 |
| Match-cell FE, HC1 (primary) | 0.3057 | 0.0172 | [0.2719, 0.3394] | 1.46e-70 | 995,606 |
| Match-cell FE, CR1 | 0.3057 | 0.0386 | [0.2300, 0.3813] | 2.33e-15 | 995,606 |
| All controls, HC1 | 0.2701 | 0.0172 | [0.2364, 0.3037] | 9.40e-56 | 995,606 |
| All controls, CR1 | 0.2701 | 0.0348 | [0.2019, 0.3383] | 8.44e-15 | 995,606 |

The all-control estimate is 88.4% of the primary coefficient. Observed profile,
engagement, opportunity, board-state, price, and skill composition therefore
explain only about 11.6% of the matched association.

### Covariate ladder

| Added controls | Effect (pp) |
|---|---:|
| Match-cell FE only | 0.3057 |
| Exposure volume | 0.3109 |
| Tenure/recency/playtime | 0.2861 |
| Board-state composition | 0.2864 |
| Price composition | 0.2863 |
| Engagement | 0.2773 |
| Skill/stability and all controls | 0.2701 |

The stability is more important than the p-values: even with nearly one million
observations, the point estimate remains in a narrow economically similar band.

## 5. Matching and support robustness

- Complete four-account groups: 0.2704 pp fully adjusted.
- BOT exclusion: 0.2701 pp fully adjusted.
- Legacy 2-20 support: 0.2902 pp fully adjusted.
- Duration-scaled 2-40 support: 0.3003 pp fully adjusted.
- Pre-outcome overlap cells: 0.2697 pp fully adjusted; retains 99.989% of the
  primary estimation sample.
- Fixed control slots 1, 2, and 3 yield FE estimates of 0.2977, 0.3206, and
  0.2989 pp; fully adjusted estimates are 0.2565, 0.2816, and 0.2572 pp.
- Across 100 deterministic valid 1:1 rematches, every estimate is positive and
  significant at 5%.
  - FE mean 0.3066 pp; range [0.2877, 0.3295].
  - Fully adjusted mean 0.2663 pp; range [0.2456, 0.2907].

The result is not an artifact of the selected control slot or a favorable
random rematch.

## 6. Dose response

| Fair-state kind-draw count | Accounts | Patron rate |
|---|---:|---:|
| 0 | 1,056,753 | 0.3141% |
| 1 | 169,567 | 0.4783% |
| 2-4 | 60,645 | 0.8492% |
| 5-9 | 13,642 | 1.3561% |
| 10+ | 5,076 | 1.3002% |

Relative to zero, the match-cell-FE lifts are +0.1939, +0.4866, +0.9116,
and +0.7993 pp for the four positive-dose bins. Every coefficient is strongly
positive. Conditional on exposure volume, a one-standard-deviation increase in
`log(1 + fair kind count)` predicts +0.1553 pp patron status; a one-standard-
deviation increase in the fair-kind rate predicts +0.1020 pp.

The top-bin raw rate is slightly below 5-9 but has only 5,076 accounts. The
overall pattern is a large, saturating dose relationship rather than a strict
step-by-step monotonicity claim.

## 7. Diagnostic kindness

At the prespecified minimum-four opportunities in both fair and clearly-worse
states, the raw patron rates are:

| Kindness location | Patron rate |
|---|---:|
| Fair only | 0.8975% |
| Both | 0.5423% |
| Neither | 0.4334% |
| Clearly-worse/losing only | 0.2575% |

Fair-only accounts are about 2.07 times as likely to be patrons as neither
accounts. Losing-only accounts are only about 0.59 times as likely. With the
full control set:

- fair-state kindness coefficient: +0.3835 pp;
- clearly-worse-state kindness coefficient: -0.1804 pp;
- fair-minus-clearly-worse contrast: +0.5638 pp;
- HC1 p = 1.95e-40;
- match-cell-clustered contrast: +0.5638 pp, SE 0.0662, p = 1.60e-17.

The contrast remains between +0.504 and +0.631 pp at thresholds 2, 5, and 10.
This is much harder to explain with generic engagement, interface familiarity,
or an undifferentiated preference for selecting draws.

## 8. Replication of the historical patron pattern

The new analysis is not merely positive; it closely reproduces the older
one-year/Stockfish-10k pattern with a new 24-month window, deeper engine
evaluation, a later complete profile snapshot, and more patrons.

| Result | Historical 10k/one-year | Current 100k/24-month |
|---|---:|---:|
| Main kind patron rate | 0.6042% | 0.6335% |
| Main control patron rate | 0.3593% | 0.3279% |
| Raw gap | 0.2449 pp | 0.3057 pp |
| Diagnostic fair-only | 0.9060% | 0.8975% |
| Diagnostic losing-only | 0.2852% | 0.2575% |
| Diagnostic neither | 0.4590% | 0.4334% |
| Diagnostic both | 0.6247% | 0.5423% |
| Full fair-minus-losing contrast | about 0.551 pp | 0.5638 pp |

The diagnostic rates and contrast are strikingly stable. This substantially
strengthens the case that the patron result reflects a replicable behavioral
structure rather than an idiosyncratic first sample.

## 9. Price-side diagnostic

Both costly and nonnegative fair-state kindness positively predict patronage,
but nonnegative-price kindness generally has the larger coefficient.

- Minimum two opportunities per price side, full controls:
  - costly kindness: +0.2316 pp;
  - nonnegative kindness: +0.3166 pp;
  - costly minus nonnegative: -0.0849 pp, p = 0.124.
- Minimum four opportunities per side, full controls:
  - costly kindness: +0.2152 pp;
  - nonnegative kindness: +0.3806 pp;
  - costly minus nonnegative: -0.1654 pp, p = 0.027.

The correct interpretation is not that costly kindness carries no signal: its
coefficient is positive and precisely estimated. Rather, current patrons are
also more responsive to favorable prices. This is compatible with structured,
price-sensitive prosociality and argues against describing the stable type as
cost-insensitive altruism.

## 10. Opportunity-level patron structure

These models use 32,858,962 opportunities belonging to 1,305,683 returned
matched accounts and cluster inference by chooser. They condition on current
patron status and are descriptive.

### Desert gradient

Relative to nonpatrons, the adjusted patron kindness gap is largest where a
draw is most justified and collapses as the disconnected player becomes less
deserving. Derived point estimates from the interacted model are:

| Disconnected-player state | Patron-minus-nonpatron kindness gap |
|---|---:|
| Clearly better | +4.9735 pp |
| Better | +2.7650 pp |
| Roughly equal | +2.6693 pp |
| Modestly worse/excluded | +0.3000 pp |
| Clearly worse | -0.2583 pp |

These are linear-combination point estimates. The saved table reports standard
errors for component terms, not the covariance needed for confidence intervals
on every derived sum. The interaction departures from the clearly-better
baseline are individually significant under chooser-clustered inference.

### Price in fair states

- At an unfavorable/costly fair draw, the adjusted patron gap is +2.2899 pp
  (chooser-clustered SE 0.3311, p = 4.63e-12).
- The favorable-price effect is +0.5480 pp for nonpatrons.
- Patrons have an additional favorable-price response of +1.4626 pp
  (chooser-clustered SE 0.2431, p = 1.79e-9).
- The implied patron favorable-price response is about +2.0106 pp, and the
  implied patron gap in favorable fair states is about +3.7525 pp.

In the three-way model, the patron-specific favorable-price interaction is
essentially zero in clearly-worse states (+0.0639 pp, p = 0.186) but increases
by +1.4052 pp in fair states (chooser-clustered SE 0.2439, p = 8.41e-9).
Patrons therefore display stronger price responsiveness specifically where
kindness is fair/desert-aligned.

## 11. Interpretation for the paper

The patron result should be presented as external/cross-domain validation of a
stable behavioral type, not as a causal result. The strongest paper-facing
claim is:

> Accounts that make privately kind choices in fair competitive states are
> substantially more likely to make a second costly choice in support of the
> platform. This association nearly doubles the raw patron rate, survives the
> frozen matching design and rich observed controls, rises with repeated fair
> kindness, and is absent or reversed for kindness toward already-clearly-
> losing opponents. Because patron adoption dates are unavailable, the result
> identifies stable cross-decision heterogeneity rather than a causal effect of
> kindness on patronage.

Recommended placement:

1. Main text: one compact patron panel with the raw rates, primary FE estimate,
   full-control estimate, and diagnostic fair-versus-losing contrast.
2. Main text or nearby figure: the five-bin dose pattern if space permits.
3. Appendix: full ladder, support restrictions, all rematches, price-side
   diagnostic, and opportunity-level patron-by-desert/price structure.

The patron material is strong supporting evidence, but it should not displace
the paper's core revealed-preference evidence from the game-level analysis.

## 12. Technical caveats and required addendum

The core confirmatory results are valid and certified. Before final paper
integration or public publication, a short post-certification addendum should
address the following limited items.

1. **Profile total-game counts unavailable.** `count_all`, `count_rated`,
   `count_win`, `count_loss`, and `count_draw` are null for every returned
   profile. The all-control model therefore drops total/rated count terms, but
   retains available per-pool games, playtime, active months, speed mix, and
   other engagement controls. This does not affect the primary model.
2. **Creation/seen-date missingness encoding.** The snapshot has 69,094 returned
   profiles with missing `created_at_ms` and `seen_at_ms`. DuckDB's
   `greatest(0.0, NULL)` produced zero rather than null, so the intended age and
   recency missing indicators were dropped. Available per-pool missing
   indicators partly absorb the same minimal-profile accounts, and the effect
   remains large, but the prespecified median-imputation sensitivity should be
   rerun with an explicit `CASE WHEN ... IS NULL THEN NULL` rule.
3. **Two secondary contract companions were not emitted.** The chooser-level
   five-bin graded patron-prediction companion and the price-side count/rate
   versions should be added. The opportunity-level five-bin model is not a
   substitute because it conditions on patron status and reverses the
   prediction direction.
4. **Publication cleanliness.** Remove the generated bytecode file and convert
   the few JSON `NaN` placeholders to strict `null` before GitHub publication.

These items call for a short supplemental run, not a rerun or retraction of the
primary Stage 10 result. Preserve the v1.0.1 certified bundle unchanged as the
canonical first production lineage.
