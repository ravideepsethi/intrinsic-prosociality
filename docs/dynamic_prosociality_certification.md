# Dynamic prosociality core and post-outcome audit certification

**Certification status:** `DYNAMIC_PROSOCIALITY_CORE_AND_POSTAUDIT_CERTIFIED_OK`

**Main sample:** November 1, 2023 through October 31, 2025

**Core run:** `20260822T022146Z`

**Post-outcome audit run:** `20260822T041411Z`

**Certification date:** August 22, 2026

## Purpose

The dynamic analysis asks whether behavior depends only on a fixed chooser type, the
current board state, and the current price of kindness, or whether history and sequence
also matter. The frozen core evaluates three primary hypotheses:

1. **A1 — mercy transmission:** whether receiving a mercy draw predicts greater
   kindness when the recipient later becomes a chooser;
2. **A3 — platform engagement:** whether receiving mercy changes rated-standard-game
   activity over the following 30 days; and
3. **B1 — conditional exchangeability:** whether kind draws are more temporally
   clustered than expected after conditioning on each repeat granter's actual
   opportunity sequence, estimated static propensities, and total number of kind draws.

The post-outcome audit was defined as secondary. It did not reopen the three frozen
primary tests or their Holm family.

## Data and authenticated inputs

The analysis uses the certified 24-month Stage 07 panel with 47,587,020 unique timeout
opportunities and the canonical all-game chronology used to measure later play. The
chronology contains 7,763,847,245 rows across 852 files and ends on April 30, 2026,
which supplies complete follow-up for main-sample exposures.

The core producer is version 1.0.2 with SHA-256
`2dcf0dd19f7cfe8f694d348e6590df88083a37882404112229d6ef05ebc42713`.
The post-outcome producer is version 1.0.1 with SHA-256
`f1279072391e5933e4e2936df7e07abcc431a03a1f03aabceb147949257b1e6f`.
Both authenticate the frozen analysis plan and the certified Stage 07 authority.

## Frozen primary family

| Primary test | Estimate or statistic | Raw p-value | Holm p-value |
|---|---:|---:|---:|
| A1 mercy transmission | +1.0047 percentage points | 2.81e-16 | 8.44e-16 |
| A3 log(1 + 30-day rated games) | +0.00337 log points | 0.5626 | 0.5626 |
| B1 24-hour clustering statistic | 11,003.14; null mean 8,408.06 | 0.0004 | 0.0008 |

### A1: mercy transmission

Among recipients who later reach a fair-state chooser opportunity, the weighted control
mean for kindness at the first subsequent opportunity is 3.4695%. Receiving mercy is
associated with a 1.0047-percentage-point increase (standard error 0.1228 percentage
points), or approximately 29% of the control mean.

The result is stable across the principal and mandatory companion specifications:

- controlling for subsequent-opportunity state gives +1.0164 percentage points;
- cross-fitted overlap weighting gives +0.9269 percentage points;
- 200-rating-point by weekday by six-hour matching cells give +0.9445 percentage
  points while retaining 99.43% of mercy observations;
- 100-rating-point by weekday by four-hour cells give +0.9525 percentage points while
  retaining 98.96% of mercy observations; and
- exposure-chooser fixed effects give +1.2752 percentage points in the restricted
  sample of 8,662 choosers observed granting both mercy and claims.

Mercy does not significantly predict whether the recipient reaches a later fair-state
opportunity within 90 days (-0.1998 percentage points, p = 0.288), while the
unconditional probability of making any fair-state kind grant within 90 days rises by
0.4957 percentage points (p < 5e-12). The pattern therefore is not explained simply by
mercy recipients reaching more observable kindness opportunities.

The descriptive horizon estimates remain positive through 90 days: +1.6685 percentage
points within six hours, +1.2002 from one to seven days, +0.7975 from seven to 30 days,
and +0.4866 from 30 to 90 days. The six-hour-to-one-day estimate is also positive but
less precise (+0.8923 percentage points, p = 0.075). The estimates support persistence,
but their nonmonotonicity does not justify a literal parametric decay claim.

### A3: platform engagement

The frozen 30-day engagement primary is null. The coefficient on
`log1p(rated-standard games within 30 days)` is 0.00337 with standard error 0.00582
(p = 0.563). Binary 30-day retention and raw 30-day game counts are likewise not
statistically distinguishable from zero.

Secondary reentry outcomes reveal a narrower short-run response. Mercy is associated
with increases of 0.882, 1.005, and 0.966 percentage points in playing another rated
standard game within 10, 30, and 60 minutes, respectively; all three p-values are below
2.1e-7. The adjusted restricted-mean time-to-next-game estimate is 1.41 hours shorter,
with p = 0.057. The defensible conclusion is that mercy predicts immediate continuation
of play, not increased activity over 30 days.

The arm-blind feasibility gate selected the log-count primary because the pooled
30-day continuation rate was 92.48%. The final common-support sample has a pooled
weighted rate of 91.83%. Because that diagnostic was observed after treatment labels
were available, it cannot reopen or change the frozen outcome selection.

### B1: conditional exchangeability among repeat granters

The sequence analysis covers 64,331 repeat granters, 1,017,944 fair opportunities, and
273,483 kind draws. It includes 56.14% of all fair-state kind draws but only 2.40% of
all fair-state choosers, so its inferential scope is explicitly **among repeat
granters**.

For all three prespecified kernels—six hours, 24 hours, and seven days—the observed
clustering statistic lies far above the conditional-randomization distribution. Each
two-sided randomization p-value is 0.0004 using 4,999 draws. The primary 24-hour result
has a three-primary Holm-adjusted p-value of 0.0008.

This rejects the frozen static-propensity conditional-exchangeability null. It does not,
by itself, distinguish habit, self-signaling, mood, session state, or another persistent
time-varying mechanism.

## Post-outcome falsification and sensitivity audit

The post-outcome audit constructed an authenticated 1,543,725-row private pretrend
checkpoint. None of nine pre-exposure placebo tests is significant after Holm
adjustment. The smallest raw p-value is 0.0324 for prior opportunities in the nearest
30-day window, but its family-adjusted p-value is 0.2918.

The audit also reproduces A1 under substantially finer matchmaking support and under
exposure-chooser fixed effects, as reported above. These checks materially reduce
concerns about coarse exposure cells, stable chooser heterogeneity, and differential
pre-exposure prosocial behavior.

## Interpretation discipline

The results justify three statements:

1. receiving mercy is followed by a large, persistent, and unusually robust increase
   in recipients' later kindness;
2. kind actions among repeat granters are not conditionally exchangeable over time; and
3. mercy increases immediate reentry but not measured 30-day engagement.

A1 should nevertheless be described as a **robust conditional dynamic association
consistent with behavioral transmission**, not as literal random assignment. Exposure
characteristics retain some residual imbalance, and the behavior of the encountered
chooser may be correlated with unobserved features of the recipient or match. Fine-cell,
overlap, pretrend, encouragement, and chooser-fixed-effect evidence make simple
selection explanations increasingly demanding, but they do not supply an unconditional
randomized causal design.

## Reproducibility and privacy

Only code, analysis plans, aggregate success receipts, report manifests, and this
certification memo belong in Git. Account-level recipient histories, pretrend rows,
conditional-randomization state, chronology caches, Patron/profile data, and other
private inputs remain on XT_Pro and must not be committed or published.

Core success receipt SHA-256:
`bd64005162bf8f37f9488d47e95c2ea4dd946d1227e909930a42dd8e4904f009`.

Post-outcome success receipt SHA-256:
`ba8c97841b6abe35986c5c6532d2800185cb7ef8d06936158c17984bb29719ad`.
