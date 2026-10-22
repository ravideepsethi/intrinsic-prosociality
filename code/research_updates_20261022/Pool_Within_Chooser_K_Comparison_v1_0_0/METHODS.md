# Within-chooser kindness, relative strength and rating sensitivity

## Purpose and sample

This is an exploratory follow-up to the left-hand upturn in the returned desert/payoff surface. It asks whether that shape persists after removing stable chooser heterogeneity and adjusting flexibly for the rating-update scale K. It is not designed to force a monotone curve or reproduce the older draft's conclusion.

The input is the frozen November 2023–October 2025 pool sample: **41,534,331 opportunities, 570,091 kind draws, 15,207,423 competitive opportunities and 419,463 competitive grants**, involving 3,224,173 chooser accounts. All 24 monthly input hashes, schemas, counts and the sample success receipt are authenticated. The runner does not download games, rerun Stockfish, or change the main sample. The sample authority certifies its observed-predecessor nonadjacency screen; it does not certify a complete census of literal immediate rematches.

The private observation-level panel is required. The previous pooled surface cells cannot identify chooser fixed effects or account-clustered uncertainty.

## Board contexts

Each context is estimated separately. This permits chooser baseline propensities and the coefficients on all other controls to differ across the following contexts:

| Context | Disconnected opponent's engine evaluation |
|---|---|
| Clearly worse | ≤ −300 cp |
| Modestly worse | > −300 and < −100 cp |
| Roughly equal | −100 to +100 cp, inclusive |
| Better | > +100 and < +300 cp |
| Clearly better | ≥ +300 cp |
| Narrow behind slice | [−350, −300) cp |
| Narrow equal slice | [0, +50) cp |
| Narrow ahead slice | [+300, +350) cp |

The first five partition the sample. The last three deliberately overlap them to reproduce the slices discussed in the previous surface review. Never add counts from all eight together. Within the broad contexts the regression also controls for 50-cp evaluation bins over [−600,+600), with separate lower and upper tails. Thus it controls for finer board composition without asserting identical positions or continuous exact-evaluation matching. Engine mate and extreme evaluations remain in their corresponding tail categories.

Accounts observed only once within a context cannot identify its chooser-FE model. They are removed from **every comparative curve in that context**, including the raw comparison. Full-context counts and unfiltered raw cell counts are also exported. An account with repeated choices and no grants remains in every model; there is no positive-outcome selection. The two axes and all three adjusted specifications use identical estimation rows within a context. The plots do not restrict estimation to their display windows.

## Axes and reference bins

**Relative strength** is computed directly as `disconnected_elo − chooser_elo`, using the displayed ratings. This avoids guessing the orientation of the panel's existing `rating_gap` field. Its bins are 50 rating points wide, centered at −600, −550, …, 0, …, +600, with separate overflow categories. The zero-centered reference is **[−25,+25)**. It is a near-equal-rating reference, not an exact equality test.

**Signed draw payoff** is `chooser_draw_payoff_v2`, the chooser's rating change from a draw. Bins retain the earlier surface's 0.4-point grid over [−6,+6], except the two cells around zero are merged into the reference **[−0.4,+0.4)**. The last upper endpoint +6 is included in the final interior bin. Out-of-window values remain separate model categories. Positive payoff means the chooser gains rating from a draw, while still forgoing the higher rating payoff of claiming a win.

Curves show **percentage-point differences relative to the reference bin**, rather than arbitrary chooser-FE probability levels. The two axes have different reference definitions; do not compare their vertical levels as the effect of changing units. Raw differences are likewise normalized to their own reference. Rates, counts and standard errors are also exported as tables.

## Rating sensitivity K

The reconstructed update scale is **K = 2 × chooser_win_premium_v2**. The runner verifies positivity, the identity `win payoff − draw payoff = win premium`, and the implied expected score `E = 0.5 − draw payoff / K` in [0,1]. It does not infer K by dividing draw payoff by a small rating gap.

Quantile cutpoints are computed exactly on the entire frozen sample, before context or singleton restrictions, at the twentieths and fiftieths of the K distribution. Equal K values are never randomly separated to achieve equal group sizes. Duplicate cutpoints collapse, and cutpoints equal to the maximum are removed. Consequently **K20 and K50 denote requested quantile resolutions, not necessarily 20 and 50 occupied bins**. This matters at the heaped lower bound. `K_bin_support.csv` reports the actual occupied groups, counts, minimum, maximum and mean K.

The K-adjusted specifications include the relevant K-bin indicators and a common log-K term to absorb residual within-bin association. This is flexible additive conditioning, not exact same-K matching or chooser-by-K-bin fixed effects. Wide tail bins remain a limitation; the K50 specification checks sensitivity to tighter conditioning. It is not a certification of joint covariate overlap.

## Specification sequence

For each axis and board context, estimate:

1. **Raw:** observed rates on the same repeated-choice-account sample as the adjusted models, shown as differences from the reference bin.
2. **Chooser FE + controls:** all axis-bin indicators, a chooser intercept, spline controls for ply and both players' RD and volatility, month indicators, speed indicators and fine board-evaluation indicators.
3. **Chooser FE + controls + K20:** specification 2 plus K20 indicators and log K.
4. **Chooser FE + controls + K50:** specification 2 plus K50 indicators and log K.

The gap and payoff models are separate; the payoff model does not also condition on the rating gap and vice versa. In a given board context the model is

`kind_it = chooser_intercept_i + axis_bin_effect_it + control_basis_it * beta + K_adjustment_it + error_it`.

The five continuous-control bases are reused unchanged from the earlier surface runner: linear splines in log(1+ply), with knots at 2,5,10,20,40,80,160; each player's log(RD/50), with knots at RD 50,75,110,150,200,300; and each player's log(volatility/.06), with knots .03,.04,.05,.06,.07,.08,.10. Unlike the old surface, these coefficients are fitted separately by board context. Month and speed enter as categorical indicators.

No coefficients are imported from the older sample. All controls and axis effects are jointly fitted. The outcome alone is not demeaned and then regressed on untransformed predictors.

## Estimation and inference

The code streams complete chooser clusters and computes the exact within-chooser cross-products:

`S = X'X − sum_i (sum X_i)(sum X_i)' / n_i`

`b = X'y − sum_i (sum X_i)(sum y_i) / n_i`.

Sparse matrices limit memory use. These sufficient statistics are shared across model specifications. A scaled symmetric eigensolve handles redundant controls. Requested contrasts are checked against the unidentified directions; a contrast that is not estimable is left missing, never set to zero. This catches disconnected-support problems as well as collinearity. Numerical rank and projection diagnostics are exported. Results still rely on the chosen numerical rank tolerance (1e−10 relative eigenvalue threshold after scaling).

A second pass computes chooser-clustered scores using residuals that remove each chooser's fitted intercept. The full curve covariance matrices are saved. Confidence intervals are pointwise 95% intervals with a t critical value at G−1 degrees of freedom. The CR1 multiplier is `G/(G−1) × (N−1)/(N−G−r)` for the FE models, where r is the rank of the demeaned design. For the raw categorical regression it is `G/(G−1) × (N−1)/(N−r_raw)`.

Accounts are never split across covariance clusters. All repeated-choice accounts count in G, including accounts with no variation in kindness. Context-specific inference does not include covariance *between* board contexts; do not test cross-context differences by treating overlapping contexts as independent. Raw-versus-adjusted differences are displayed, but their joint covariance is not supplied as a formal decomposition test.

## Support and exploratory contrasts

Display defaults require each plotted bin to have:

- At least 500 estimation-sample opportunities.
- At least 50 choosers observed in that bin who also visit another bin on the same axis within that context.
- Observations in at least six months.
- An estimable coefficient contrast and available clustered uncertainty.

Every model in a given figure uses the same displayed-bin intersection. Counts of choosers who directly visit both a bin and the reference are separately reported. Direct overlap with the reference is not required: other connected bins can identify a contrast. These thresholds never condition on grants or significance. They are support diagnostics, not an exogeneity argument. All populated bins, including tails and unsupported bins, remain in the CSV and estimation.

The runner reports four pre-coded exploratory differences per context, axis and specification:

| Axis | Left tail, bin centers | Left shoulder | Right tail |
|---|---|---|---|
| Rating gap | −600 to −300 | −200 to −50 | +300 to +600 |
| Draw payoff | −6 to −3 | −2.4 to −1.2 | +3 to +6 |

The differences are left tail minus left shoulder, right tail minus left shoulder, left tail minus reference, and right tail minus reference. Within each region, bins receive fixed opportunity weights from the common estimation sample, unchanged across specifications. An incomplete supported region is reported as insufficient support; it is not silently redefined around surviving significant cells. These ranges were chosen after the earlier surface was viewed. They are exploratory and do not locate the minimum or establish convexity throughout a range.

Unadjusted two-sided p-values and pointwise confidence intervals are supplied. Holm correction is additionally applied to the primary K20 family: four contrasts × two axes × eight overlapping contexts = **64 declared comparisons**. Non-estimable comparisons retain a p=1 place in this family while their displayed adjusted p-values remain missing. No earlier paper family or C13 result is modified.

## Interpretation

If chooser FE and K adjustment reduce the left upturn, that supports an account-composition/rating-sensitivity explanation. This sequence also adds month, speed and finer board controls relative to the prior pooled surface, changes to a common repeated-choice sample, and refits slopes within contexts; differences from the earlier surface cannot all be attributed to chooser FE alone.

If the left upturn persists with support and uncertainty, it remains a nonlinear within-chooser conditional association. That could motivate a behavioral interpretation, but neither the surviving curve nor a disappearing curve identifies a causal price effect. K, relative strength and selection into a disconnect decision remain observational quantities. No quadratic or monotonicity restriction is imposed.

## Outputs and reproducibility

Public report outputs contain curves, raw counts, account-overlap summaries, K-bin support, covariance matrices, aggregate within-chooser sufficient statistics, model diagnostics, exploratory contrasts, figures, input lineage, executed source code, hashes and success receipts. They contain no chooser IDs, usernames or game IDs. Do not upload the `PRIVATE` directory, which contains the local staged observations. The results ZIP includes only the public report.

The runner validates required values instead of silently dropping incomplete observations. Failures stop the run. Sorted input copies, per-context Parquets, first-pass sufficient statistics and completed-context outputs are checkpointed with hashes and run identities. A rerun authenticates the source again, verifies existing checkpoints and continues; an interrupted second pass restarts that context's covariance pass. Runtime versions, package bytes and settings are part of the identity.
