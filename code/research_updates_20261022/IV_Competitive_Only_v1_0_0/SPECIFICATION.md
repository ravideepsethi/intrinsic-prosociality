# Competitive-only instrument: reviewed run specification

3 October 2026 · Proposed implementation specification, v1.1

This revises the attached 3 October memo after inspection of the existing code and returned Run 2 diagnostics. It is a specification, not a completed analysis or executable runner. The original memo is preserved. No competitive-only IV estimates have been produced by this review.

## 1. Question and interpretation fixed before the new results

Does the receipt IV give a similar answer when its instrument uses only the opponent's earlier grant-or-claim decisions in competitive positions? How much independent first-stage variation comes from the non-competitive component?

Keep the current pooled-score headline. Treat this as a newly specified robustness and mechanism diagnostic, developed after observing the existing results. Do not promote an instrument because it has a larger coefficient, a smaller p-value, or more favorable balance tests.

The split identifies components of recorded behavior, not distinct psychological types. The same player can contribute to both components. Competitive-only does not automatically mean more valid, merit-sensitive, or closer to random assignment.

For each historical decision, a grant contributes `1 - p_hat` and a claim contributes `-p_hat`. A grant where the benchmark grant probability is low has a larger positive residual. That fact alone does not establish that the pooled instrument is biased or that non-competitive decisions dilute the IV effect. Under a valid homogeneous-effect model, an additional noisy predictor can change precision without attenuating the population IV ratio.

## 2. Frozen inputs and reproduction gate

Reuse the original headline data, including author accounts, as expressly requested. Do not substitute the author-excluded Run 3 objects or the updated receipt cohort from another workstream.

| Object | Rule |
|---|---|
| S0 | Exactly 2,682,330 headline exposures from the saved `spaced90.parquet` |
| Exposure | Preserve the existing eligibility, first-observed-pair rule, greedy spacing, complete history and follow-up, and competitive recipient-position restriction |
| D | Original draw-received indicator, coded 0/1 |
| Y | Original later-grant indicator, coded 0/1 internally; report effects in percentage points |
| R | Original qualifying-later-choice indicator, coded 0/1 internally |
| Later choice | First qualifying competitive choice against a different opponent; original game-start and last-move timing rules; no choice becomes zero only with complete follow-up |
| Fixed effects | Original month × exact time control × pair-mean-rating cells, exposure-date effects, and hour-of-week effects; retain definitions when subsets contain fewer occupied cells |
| X0 | Exact frozen headline controls, transformations, and missingness treatment |
| Covariance | Exact shared-account-or-exposure-date CR0 convention; historical scores treated as fixed |
| State reference | Existing month-, lag-, and focal-fold-specific probabilities; no competitive-only refit |
| Ordinary placebo | Original 307,863 eligible ordinary games, using original scores/histories/outcomes and author treatment; no expanded Run 2 games |

Authenticate the headline source at:

`derived/replication/chooser_iv_expanded_v100_PRIVATE/f14a1105a9f7/analysis/spaced90.parquet`

Expected SHA-256:

`3bc55d83f113cd7c5942348b16ae9ff5e940ae8aad13f9db3d99a6a526ef250c`

Expected source configuration SHA-256:

`f14a1105a9f70782dffad6ecd98b651f5e6d57f1ce4d39ee0f0248e9e1d3bc0f`

Before new regressions, reproduce the pooled-score headline on S0, including sample membership, receipts, score values, first stage, reduced forms, OLS, 2SLS, uncertainty and AR set. Use the archived full-precision results as authority, not rounded manuscript numbers. Reproduce the original placebo as well. Matching N alone does not authenticate either sample.

The original placebo has 307,863 rows both before and after the recent author-clean refresh, but its refreshed score values are slightly different. The original returned ordinary-kindness coefficient was approximately +0.0006245357 pp per old reference SD; the refreshed one was +0.0006246164. Do not silently use the refreshed inputs for this historically matched run.

## 3. Score construction

For each query pair (recipient i, opponent j) and exposure month m, preserve:

- The all-source historical grant-or-claim eligibility rule.
- The strict historical decision cutoff: decision timestamp < start of month m minus seven days.
- Removal of all decisions by j against focal recipient i before computing counts, means or distinct counterparts.
- The original four-fold state reference that excludes both focal accounts' folds in both reference roles. Their folds are excluded from reference training; this is not a reason to remove j's own history from the score.

Partition this same history into:

- Hcomp: disconnected player's final-position evaluation ≥ −100 cp from that player's side.
- Hnon: disconnected player's evaluation < −100 cp.

For each subset, save decision count, grant count, expected-grant sum, distinct counterpart count, raw grant rate, expected grant rate and adjusted score. The adjusted score is mean(grant − p_hat). Missing/unknown evaluations must not be classified as non-competitive.

The inspected encoder uses 500 cells, with 100 cells per merit band. Once its provenance and perspective are authenticated, `cell // 100` identifies:

| Merit code | Disconnected-player evaluation |
|---:|---|
| 0 | ≤ −300 cp |
| 1 | > −300 and < −100 cp |
| 2 | ≥ −100 and ≤ +100 cp |
| 3 | > +100 and < +300 cp |
| 4 | ≥ +300 cp |

Thus the exact split can use existing cell codes; it needs no fresh engine evaluations. Validate cell range and the upstream finite-evaluation contract. Check agreement with any cached competitive flag where that flag has the identical definition.

Report the share of Hnon at ≤ −300 cp. Label whether a statistic weights historical decisions, exposure-specific histories, or opponents; repeated queries can reuse the same historical decision.

Required accounting identity, before support restrictions:

`n_all = n_comp + n_non`

`n_all * Z_all = n_comp * Z_comp + n_non * Z_non`

Implement the second identity using residual sums so an empty subset contributes a zero numerator without assigning a fabricated score. Pooled grant and expected-grant sums must also reconstruct exactly, to stated floating-point tolerance. Distinct counterpart counts are not additive across subsets.

Reuse stored fitted probability arrays if available. If only authenticated original sufficient-statistic deltas are available, algebraically reconstruct the same original arrays and verify pooled-score reproduction. This is reconstruction of the frozen reference, not fitting a new competitive-only model. Record which route was used.

## 4. Samples

| Sample | Definition |
|---|---|
| S0 | Frozen headline rows |
| S1 | S0 with at least five competitive historical decisions and a finite competitive score |
| S2 | S1 with at least five non-competitive historical decisions and a finite non-competitive score |
| S1_3 | S0 with at least three competitive historical decisions and a finite competitive score |

Do not rerun spacing, choose replacement exposures, top up the sample, or repeat eligibility selection after restricting support. Check whether finite-score requirements exclude any otherwise count-supported rows and report them separately.

Report exposures, unique recipients, unique opponents, occupied assignment cells, receipts, receipt rate, Y mean, reach rate, and Y mean conditional on reach for S0, S1, S2, S1_3, S0 minus S1, S0 minus S2, and S1 minus S2. Also report the pooled and component decision/counterpart counts and recipient prior activity for retained and omitted rows.

## 5. Common controls: isolate an instrument change

Let X0 denote the unchanged headline controls. Let XC be X0 plus competitive-only expected grant rate, log(1 + competitive decision count), and log(1 + competitive distinct counterpart count).

Run two explicitly paired comparison families:

1. **Primary restricted-score family: common XC.** Every pooled, competitive, non-competitive and joint-instrument comparison in this family uses the identical XC controls, fixed effects, and rows.
2. **Original-controls check: common X0.** Repeat the instrument comparisons with X0, again holding rows and controls fixed.

This adds an XC pooled baseline to the original memo. Comparing pooled Z with X0 against competitive Z with XC would confound the instrument and control changes. Similarly, the two just-identified estimates entering the S2 difference test must share the joint model's controls.

Preserve recipient controls exactly. Do not add final exposure evaluation, clocks or ply. Do not silently add non-competitive history controls. If later desired, symmetric component controls constitute a separately specified sensitivity applied to every instrument on S2.

## 6. Scaling and units

Estimate with D, Y and R coded 0/1. Convert only for reporting.

- First stages and reduced forms: report pp per raw score unit and pp per reference residual SD.
- 2SLS and OLS: report pp per draw received.
- Pooled and competitive scores: use each instrument's own residual SD on S1, separately for X0 and XC; retain those reference SDs when comparing its S1 and S2 results.
- Non-competitive score: use its residual SD on S2. It need not be supported throughout S1, so an S1-wide non-competitive SD is not a valid universal requirement.
- Print every reference SD, sample and control family. Also report native residual SDs on each estimation sample.
- The historical 0.059411690344000595 scale is used only to reproduce the archived headline and placebo. Do not impose it on the new components.

For the OLS-implied reduced form, compute in probability units before converting. If both displayed first stage and displayed OLS effect are in pp, use:

`implied RF_pp = first_stage_pp * OLS_pp / 100`

This is a descriptive benchmark, not an identification test. OLS and IV can target different relationships under confounding or heterogeneous effects.

## 7. Core runs

First report score support, raw and residualized correlations on S2 under each common control family, raw quantiles, 40-bin histograms, grant-zero shares, and residual variation. For grant-zero shares, distinguish query-weighted rates from a documented opponent/month summary; scores are pair-specific and time-varying, so a single undated opponent score is undefined.

| Run | Sample | Instruments and controls |
|---|---|---|
| A0 | S0 | Original pooled instrument with X0; reproduction only |
| A | S1 and S2 | Pooled score with XC and with X0 |
| B | S1 and S2 | Competitive score with XC and with X0 |
| C | S2 | Non-competitive score with XC and with X0 |
| D | S2 | Both component scores jointly, with XC and with X0 |
| Support sensitivity | S1_3 | Pooled and competitive scores, matched rows and controls, XC and X0 |

Each panel reports receipt first stage, kindness reduced form, reach reduced form, 2SLS, same-row OLS, OLS-implied reduced form, first-stage strength and partial R². Put AR confidence sets in the footer. Two-instrument reduced-form/first-stage equations must label coefficients as conditional on the other instrument; joint 2SLS has one treatment coefficient and no single instrument SD.

Do not assume the first stage strengthens or that the 2SLS SE necessarily rises after restricting history. Measure both.

## 8. Joint inference, overidentification and weak instruments

Retain shared-account-or-date CR0 throughout. Stack the observation-level moment/influence contributions so the covariance between the two component IV estimates includes their common observations, accounts and dates.

For each common-control S2 family, report:

- Both just-identified IV estimates and their difference with its joint-covariance SE and interval.
- Two-instrument 2SLS with its robust SE, joint first-stage Wald statistic, df, F-style statistic where appropriate, and partial R².
- A properly constructed robust Hansen J test with df = 1, using the same moment covariance convention. One transparent route is two-step efficient GMM: estimate the moment covariance at a consistent preliminary estimate, minimize with its inverse, and calculate J at that efficient GMM estimate. Report the GMM estimate separately; do not relabel it as the 2SLS estimate.
- Moment-covariance eigenvalues, instrument rank and conditional support. If the moment covariance is not positive definite at the required rank, report the affected test as unsupported; do not repair its eigenvalues silently.

A chi-square statistic formed by plugging a generic robust covariance into the ordinary 2SLS criterion is not automatically a valid Hansen J. The difference-of-estimates Wald test and J address related restrictions but need not be numerically identical in finite samples. Do not impose equality between them as a software test.

For one instrument, preserve the archived null-restricted moment AR inversion. For two instruments, use a two-moment null test with the appropriate chi-square reference and null-specific covariance; do not reuse the one-instrument formula. Retain unbounded or disconnected confidence sets and record numerical inversion limits. A finite search grid must not be reported as establishing bounded endpoints.

J non-rejection does not establish validity or harmless pooling. Rejection can reflect incompatible moment restrictions, including exclusion/assignment problems or heterogeneous effects targeted by different instruments. The run cannot select among these explanations by itself. Weak or nearly redundant instruments can make J uninformative.

## 9. Diagnostics E–I

**E: binned first stages.** On S1, produce competitive and pooled score plots under common XC, with X0 as a check. Use up to 20 quantile bins of residualized Z and mean residualized D. State how ties are handled; do not force identical scores apart solely to obtain equal counts. Report bin N, mean score, mean D residual, and intervals accounting for the frozen clustering convention. Label the figure descriptive and state whether uncertainty conditions on estimated residualization/bin cutoffs. A positive curve or a tail-driven slope does not prove individual monotonicity or identify a LATE population without further assumptions.

**F: recent-history balance.** Use the frozen seven recent traits on [exposure start −37 days, exposure start −7 days): any competitive history, log competitive opportunities, ever granted, grant rate, log disconnections, log receipts, and log claims. The all-game volume control is a different window, [start −30 days, start), and is not an additional independent recent-window balance outcome in the rich specification. Report trait-level and joint tests with, and without, recipient history/volume controls. Include matched pooled-score balance on the same S1/S2 rows. Report multiple-testing families explicitly. Do not count an exactly controlled trait's forced zero as evidence of balance or select the headline from balance p-values.

**G: original ordinary-game placebo only.** Authenticate the original 307,863-row frame and original author treatment. Define P1 by competitive-history support ≥5 without resampling. Fit both pooled and competitive scores on exactly P1 with common XC and common X0. Report the original pooled result on the full original frame separately. Report the rows lost, Y and R, own native score SDs and the applicable S1 reference SDs. For a new instrument, the old +0.020 pp benchmark cannot simply be copied across scales: report its corresponding receipt reduced form and OLS-implied benchmark in the same raw-score units. Do not mechanically subtract the ordinary placebo from the IV reduced form; that requires a justified transport assumption. The observed ending-selection concern remains relevant even after changing the score.

**H: joint first stage.** On S2, report coefficients and SEs of both components, conditional partial R² for each, the joint strength statistic, residualized score correlation, and conditioning/rank diagnostics. A small non-competitive conditional coefficient means little detectable incremental prediction given competitive Z and controls; it does not establish that the underlying behavior is only noise or justify switching the headline.

**I: subgroup first stages.** Use the frozen speed, rating, prior-granting and month cuts on S1. Report raw and adjusted signs, N, receipts and residual score support. These are subgroup consistency checks, not a formal proof of individual monotonicity.

## 10. Performance and storage

Use the saved cohort, original comparison, scored-history projections and state-reference caches. No API requests, Stockfish searches, raw PGN reparse, all-game chronology rebuild, new outcome search, or reconstruction of exposure eligibility should be needed.

The original score lineage contains 47,587,020 projected history rows across 384 month/shard files. Existing phase-independent score indexes aggregate by opponent, counterpart, cell and cutoff bucket. Competitive/non-competitive classification is a function of the existing cell, so those indexes can support both components, their counts, their grant sums, expected values and distinct counterparts. Authenticate compatibility before reuse; never reuse author-clean reference probabilities for this author-included run.

Process missing score work by the existing 16 opponent shards. Request up to ten workers, cap actual concurrent workers from measured RAM, and avoid multiplying BLAS/Arrow thread pools inside each worker. Reuse the same absorbed design and covariance codes across models with identical samples and controls when possible. Keep dense model concurrency bounded independently of score workers. Log stage times, worker counts and peak memory.

Parquet is the authoritative working format. Keep per-exposure scores and private identifiers locally; generate the requested `01_scores.csv` as a streamed export, never as a regression input. The uploadable result ZIP contains aggregate tables/figures, definitions, provenance and validation only. Save atomic, hashed checkpoints and emit a core-results report after A–D, then continue E–I without waiting for approval. Source input hashes and code/specification hashes must enter cache keys.

Planning runtime: 20–60 minutes for the first full local run, unbenchmarked for this new runner and dependent on cache compatibility and memory. Revise the forecast from measured early stages rather than presenting it as a guarantee. The previous construction-diagnostic run took 10.2 minutes; this run additionally needs split scores and larger IV models.

## 11. Outputs and acceptance checks

Preserve the memo's numbered CSV/LaTeX tables, histograms and first-stage plots, with these additions:

- `00_reproduction.json`: original source authority and full-precision reproduction checks.
- `01_scores.parquet`: private per-query authoritative scores; streamed CSV companion.
- `01_score_identity_checks.json`: partition, pooled reconstruction, boundary/timing/pair-exclusion checks and maximum numerical errors.
- `03_common_controls_manifest.json`: exact row digests, controls and SD reference sample for every panel.
- `03_runD_inference.json`: 2SLS, efficient GMM/J, component contrast and weak-instrument outputs with method labels.
- `VALIDATION.json`: tests and observed runtime; no claimed production success before the laptop run returns results.

Every panel uses Estimator | Estimate | SE | p | 95% interval, with sample and units in the header, and first-stage strength/partial R²/AR set in the footer. Keep full-precision machine-readable numbers alongside manuscript-rounded versions.

Meaningful tests before release: reproduce archived pooled results; split-score reconstruction; exact −300/−100 boundaries; strict timestamp ties; all-pair removal; cross-fit reference identity; zero-count support; unchanged S0 ordering and outcome fields; same-row and same-control comparisons; scaling invariance of IV; independent small-matrix 2SLS/GMM and joint-covariance checks; weak/collinear instruments; unsupported non-positive covariance; cache invalidation and resume. The private production data must not be needed to pass synthetic tests.

## 12. Replacement for the original reading table

| Finding | Defensible reading |
|---|---|
| Estimates similar and their difference precisely bounded | Supports robustness to this historical-state split on the compared sample; does not establish exclusion |
| Estimates similar but difference interval wide / J does not reject | Inconclusive about whether pooling matters |
| Competitive estimate larger | Investigate instrument-specific effects, exclusion, support and precision; not proof of attenuation or a reason to promote it automatically |
| Component estimates differ precisely / J rejects | The common-effect moment model is challenged; exclusion and heterogeneity remain competing explanations |
| Competitive score has weak residual support | Report weak-IV sets and limited information; do not interpret its noisy ratio as a mechanism result |
| First stage concentrated in a tail | Linear prediction is concentrated there; individual monotonicity and a particular complier interpretation require more |
| Non-competitive conditional first stage near zero | Little incremental treatment prediction detectable under the specified controls |
| Competitive placebo remains negative or imprecise | Original placebo concern remains; switching the score did not establish a clean exclusion test |

The README's five-line result summary should state support retained, competitive first stage, reduced form, IV interval, and what the component comparison can and cannot exclude. Do not force the result into a predetermined favorable category.

## Method references

- Hansen, L. P. (1982), *Large Sample Properties of Generalized Method of Moments Estimators*: https://larspeterhansen.org/wp-content/uploads/2016/11/Hansen-econometrica-GMM.pdf
- Imbens, G. W. and Angrist, J. D., *Identification and Estimation of Local Average Treatment Effects*: https://www.nber.org/papers/t0118

Local implementation evidence inspected: `IV_Runs_2_3_v1_0_0/code/common.py`, `author_history.py`, `legacy/iv_numerics.py`, `legacy/followup_logic.py`, `legacy/followup_stats.py`, `legacy/expanded_stats.py`; `Run2_Phase_Analysis_v1_1_0/code/performance_histories.py`; authenticated returned Run 2 summaries `f9717dfb5719` and `e3692bffa003`. These source checks establish a feasible reuse route, not that all laptop caches have been newly verified in this review.
