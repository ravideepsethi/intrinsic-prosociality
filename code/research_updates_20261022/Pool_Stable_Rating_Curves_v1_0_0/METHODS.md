# Stable-rating curves — methods, v1.0.0

## Question and status

Does the left-tail rebound in the draw-payoff curve persist among opportunities where both players have low pregame rating deviation (RD), and when rating sensitivity K is narrowly restricted? How do unrestricted curves behave near zero? This is a new exploratory follow-up to observed patterns, not a preregistered causal test. All choices below are frozen in this package before its result is observed. The code does not optimize cutoffs, knots, bandwidths, or shape against the outcomes.

The private panel is on the user's Mac. The delivered package has been tested using synthetic data; it contains no newly estimated empirical result. Executing the runner produces those results.

## Source and sample

The frozen, authenticated two-year nonadjacent pool panel has 41,534,331 opportunities, 570,091 kind draws, and 3,224,173 choosers. It covers November 2023–October 2025. The runner verifies the bundled sample authority and all monthly hashes. It retains competitive positions where `engine_eval_cp_disconnected >= -100`, giving 15,207,423 opportunities before singleton removal. Evaluation is from the disconnected recipient's perspective.

Source fields and transformations:

| Analysis variable | Frozen field / definition |
|---|---|
| Kind draw | `outcome_kind_draw` |
| Chooser identifier | `chooser_user_id` |
| Gap | `disconnected_elo - chooser_elo` |
| D: draw payoff | `chooser_draw_payoff_v2` |
| K: rating sensitivity | `2 * chooser_win_premium_v2` |
| W: win payoff | `chooser_win_payoff_v2`; checked against `D + K/2` |
| Normalized payoff | `D/K = 0.5 - E` using frozen payoff fields |
| Chooser RD | `chooser_pre_rd_v2` |
| Opponent RD | `disconnected_pre_rd_v2` |
| Volatilities | `chooser_pre_sigma_v2`, `disconnected_pre_sigma_v2` |
| Game stage | `ply_count` |

The old monthly-source filters are not redefined. Data are validated for finite values, binary outcome, valid month/speed, positive K/RDs/volatilities, the payoff identity, and implied E within [0,1]. Input files are never modified. K is not the old fixed Elo K-factor; it is the implied sensitivity in this panel's Glicko payoff calculation. The pre-existing aggregate counts must reproduce exactly.

Five samples are estimated:

| Sample | Restriction, in addition to competitive position |
|---|---|
| `all` | None: full competitive benchmark |
| `rd75` | Both players' pregame RD ≤75; primary stable-rating sample |
| `rd60` | Both players' pregame RD ≤60 |
| `rd100` | Both players' pregame RD ≤100 |
| `rd75_k11_12` | Both pregame RD ≤75 and 11≤K≤12 |

The RD cutoffs are research definitions, not official provisional-account thresholds. Low RD means relatively precise ratings; high RD does not identify account age and can also reflect inactivity. The narrow K band is around the modal K from the preceding run, selected without examining these new results. It may remove substantial support; that is reported, not repaired by changing the band. K still varies within [11,12] and remains controlled.

Within each sample, remove chooser × broad-board-state units with only one opportunity. Broad states are roughly equal (−100≤cp≤100), better (100<cp<300), and clearly better (cp≥300). Recompute this removal after each sample restriction. Keep all remaining outcomes, including all-zero choosers. Raw and adjusted curves use exactly the same retained rows, as do the gap, D, and D/K regressions. The three axes are fitted separately, not jointly. Singleton removal means raw curves are raw rates in the FE estimation sample, not in the entire original panel.

The full-sample benchmark must reproduce 13,203,811 retained opportunities, 334,458 kind draws, 1,421,546 chooser clusters and 2,444,061 chooser-state units. Restricted-sample counts are outputs, not targets.

## Unrestricted curves and controls

Each curve is an OLS linear probability model with a full set of axis-bin indicators and chooser × broad-board-state fixed effects. No monotonicity, curvature, continuity, sigmoid, or S-shape restriction is imposed. Lines merely connect adjacent supported bin estimates; they are not a fitted sigmoid or smoother. Gaps in support break lines.

Axes and reference bins:

- Gap: 50-point bins bounded at −625,…,+625; reference [−25,+25).
- D: 0.4-point bins bounded at −6,…,+6, with the two central cells merged; reference [−0.4,+0.4).
- D/K: 0.025-unit bins from −0.5 to +0.5, central cells merged; reference [−0.025,+0.025).
- Overflow bins stay in estimation and in output tables. They have no finite midpoint and are not drawn. Final +6 and +0.5 endpoints belong to their last finite bins. The central bins are deliberately broad for the global plots; independent local regressions below inspect behavior around zero.

All adjusted curves include the same nuisance controls:

1. A linear spline in `log(1+ply)`, with knots at ply 2,5,10,20,40,80,160.
2. Separate linear splines in log RD for both players, with knots at RD 50,75,110,150,200,300; transformed scale is log(RD/50).
3. Separate linear splines in log volatility for both players, with knots at σ .03,.04,.05,.06,.07,.08,.10; transformed scale is log(σ/.06).
4. Month fixed effects for the 24 months and speed fixed effects (ultrabullet, bullet, blitz, rapid, classical).
5. Evaluation-bin fixed effects on a 50-centipawn grid from −600 through +600. In the competitive sample only supported upper portions of this grid are relevant; ≥600 is an upper-tail category. Controls therefore hold evaluation approximately fixed, not continuously or exactly.
6. K20 indicators plus log K. K20 cutpoints are empirical full-source K quantiles from all 41,534,331 rows, reused unchanged across restrictions, with duplicate cutpoints removed and ties kept together. Empty/constant categories under stable-rating restrictions are handled as rank-deficient nuisance directions. K20 is a control specification, not a player subgroup. This package does not add another K50 ladder: the substantive sensitivity here is RD restriction and the narrow K band.

Time-invariant chooser heterogeneity is absorbed separately within each broad board state. This does not absorb changes over time in either player's RD/K; hence the restrictions and continuous controls.

For `rd75` and `rd75_k11_12`, an additional specification interacts every axis bin with the three broad board states. This permits separate curve shapes; the nuisance slopes stay common. Joint equality tests across states use their full chooser-clustered covariance. The pooled curve is not assumed sufficient simply because all positions are competitive.

## Inference and support

Fixed effects are absorbed exactly by within-unit demeaning; coefficients are obtained from a scaled symmetric eigensolve. Candidate near-constant columns are directly recentered to avoid cancellation when subtracting sums of squares, before rank determination. Rank and contrast estimability are checked. Unidentified effects are marked. Entire chooser histories remain together in a worker and input block. Covariance is clustered by chooser across all board states, not by chooser-state unit.

CR1 correction for an adjusted model is `G/(G-1) * (N-1)/(N-H-rank)`, where H is the number of absorbed chooser-state units, G is the number of choosers, and rank is the within-design rank. Raw-rate contrasts use `G/(G-1) * (N-1)/(N-rank_raw)`. Intervals use t(G−1). These are pointwise 95% intervals, not simultaneous bands. Uncertainty in scientific identification is not captured by these sampling intervals.

A displayed bin must have at least 500 retained opportunities, 50 choosers with within-chooser-state variation across axis bins, and observations in 6 months; its reference bin must meet the same support rule. Counts of choosers observed directly in both the target and reference bin are also reported. Identification can use connected paths through other bins; direct-reference overlap is not required to be 50. These thresholds are minimum display rules, not a guarantee against weak support.

The primary figure shows each curve's own supported bins. A second figure uses only bins supported in all three displayed samples. Both use identical rows for each sample across axes, but axis bins contain different groupings of those rows. Matching sample membership does not make bin centers represent identical observations or make the normalized-payoff transformation linear. `FIGURE_METADATA.json` records displayed counts. Overflow observations and hidden finite bins stay in estimation.

`tail_contrasts.csv` reports observation-weighted contrasts within predefined axis ranges, including left-tail minus left shoulder. Those weights vary by sample. For D the ranges are centers [−6,−3] versus [−2.4,−1.2]. `common_weight_payoff_tail.csv` additionally compares each restricted sample to the benchmark using the same supported bins and benchmark weights, normalized separately within tail and shoulder. It reports how much baseline tail support is retained. These are separate estimates with CIs, not a formal difference test: cross-sample covariance is not estimated. A significant estimate in one sample and nonsignificant estimate in another does not demonstrate a significant difference.

## Local zero diagnostics

These are supplementary, unrestricted two-sided local linear FE regressions. They are not regression-discontinuity treatment effects. Windows are fixed in advance:

| Axis | Half-bandwidths |
|---|---|
| Gap | 25, 50, 100 rating points |
| D | 0.5, 1, 2 rating points |
| D/K | 0.025, 0.05, 0.10 |

Run every window in `rd75` and `rd75_k11_12`. The primary diagnostic is `rd75_k11_12`, normalized payoff, half-bandwidth 0.05. Each local window has its own retained sample and singleton removal. Unlike the global curves, these axis-specific local windows are not the same rows.

Within a window, include left slope `x*1(x<0)`, right slope `x*1(x>0)`, a positive-side indicator permitting a right-minus-left limit jump, and a separate exact-zero indicator. The zero tolerance is `abs(x) <= 1e-12*max(1,bandwidth)` to avoid numerical noise. Use the same chooser-state fixed effects and nuisance controls. The internal slopes use x/bandwidth for conditioning; outputs convert them back to percentage points per natural axis unit. Equal-rating observations are retained as their own mass point, not assigned arbitrarily to a side. There is no continuity constraint and no smoothing-bandwidth search. A piecewise linear approximation can show a spurious intercept jump when the underlying curve is smooth but curved; compare bandwidths and do not give this coefficient a causal RD interpretation.

Report left slope, right slope, right-minus-left slope, right-minus-left extrapolated limit, and the zero mass point minus the left extrapolated limit. Require ≥500 rows and ≥6 months on each side and ≥50 choosers who cross sides within the same chooser-state unit. The zero-mass-point coefficient additionally requires ≥500 zero observations, ≥6 zero months and ≥50 choosers switching between zero and nonzero within a unit. Supported and unidentified estimates are distinguished; coefficients may be recorded with an insufficient-support status, but no p-value is used for such a test.

Holm adjustment is reported for the five primary diagnostic tests and the full 90 local tests. A separate family covers all 60 adjusted tail contrasts (five samples × three axes × four contrasts); another covers six board-state heterogeneity tests. Unsupported tests enter adjustments conservatively as p=1 but are displayed without a p-value. All families are exploratory; selecting among them after seeing the results requires caution. Raw tail comparisons are descriptive. A positive slope at both sides is not a test of an S-shape, and unequal finite-window slopes are not a structural estimate of loss aversion.

## Outputs, restart and privacy

The runner uses up to 10 workers with numerical-library threads limited to one per worker. It reuses the authenticated prior within-chooser sorted cache when available; otherwise it builds one from the frozen panel. Hashes and a run identity cover code, source authority, dependencies and settings. Moment and covariance checkpoints are verified before reuse. Re-running the same command resumes completed shard/sample tasks. It does not silently accept changed inputs.

Outputs are under `PROJECT/output/pool_stable_rating_curves_v100/IDENTITY/report`. PRIVATE caches stay under that run directory and are not zipped. A results ZIP and SHA-256 file are placed in `~/Desktop/Lichess_Desktop`; only aggregate tables/moments, figures, provenance, and executed code are included. Figures are PNG and vector PDF. No usernames, account IDs or game IDs are in the return archive. Numerical Gram matrices are aggregate sufficient statistics, not anonymization with a formal privacy guarantee.

Interpretation rules and a specified reference-dependent model are in `REFERENCE_MODEL.md`. If the restricted tail has insufficient support, the correct conclusion is that the test cannot distinguish explanations there, not that the rebound disappeared.
