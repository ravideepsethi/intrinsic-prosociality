# Pooled competitive-position specification

## Source and analysis sample

The only eligible source is the frozen current two-year main pool/nonadjacent panel, November 2023–October 2025: 41,534,331 opportunities, 570,091 kind draws, and 3,224,173 chooser accounts. The bundled sample authority and every monthly input hash are checked. No new requests to Lichess are made and no historical input is overwritten.

Keep positions with the **disconnected opponent's** engine evaluation at least −100 centipawns (cp). This gives 15,207,423 opportunities, 419,463 kind draws, and 2,442,576 chooser accounts before fixed-effect singleton exclusion. Positive evaluation means a better board position for the disconnected player.

The broad states are:

| State | Opponent evaluation |
|---|---|
| Roughly equal | −100 ≤ cp ≤ +100 |
| Better | +100 < cp < +300 |
| Clearly better | cp ≥ +300 |

The absorbed unit is chooser × broad state. Units observed only once are removed from every fitted curve, including raw curves, because they contribute no within-unit slope information. A chooser can remain in one state while being removed in another. Never-granting choosers and units are retained if they have at least two observations. There is no selection on the outcome or on estimated effects. All models use the same retained rows.

The previous authenticated separate-state run implies 13,203,811 retained opportunities, 334,458 kind draws, and 2,444,061 absorbed chooser–state units. These are row-count checks; no coefficients are matched to prior results. The distinct number of retained chooser accounts is calculated anew and is smaller than the number of absorbed units.

## What is estimated

For chooser i, broad board state s, and opportunity t, each axis is estimated separately by linear least squares:

`kind_draw_ist = alpha_is + sum_j beta_j * 1(axis_ist in bin j) + controls_ist' gamma + error_ist`.

The intercept `alpha_is` is unrestricted for every retained chooser–state pair. Thus the relationship is identified by comparisons within the same chooser and broad board state. It is not identified by comparing different choosers, or by that chooser moving between broad board states. The common curve is the pooled least-squares projection, weighted by available within-unit variation and covariate residualization; it is not a simple or necessarily convex average of the earlier estimates.

The two axes are:

- Rating gap: `disconnected_elo − chooser_elo` from displayed pregame ratings; 50-point bins with reference [−25,+25).
- Draw payoff: `chooser_draw_payoff_v2`; 0.4-point bins over −6 to +6, with the two central bins combined into reference [−0.4,+0.4).

The x-axis is the chooser's rating change from accepting a draw, not the win-versus-draw sacrifice. K is `2 × chooser_win_premium_v2`; the input identity `win_payoff − draw_payoff = win_premium` is checked. The gap and payoff are fitted in separate regressions, not entered together as independent treatments. At approximately fixed K and opponent rating uncertainty, they are closely related transformations of relative strength. Their comparison is descriptive.

All observations outside plotted ranges remain in the model in separate overflow bins. Rating-gap finite-bin edges run from −625 through +625; the main plot shows bin centres −200 through +200. Payoff values outside −6 to +6 have separate overflow bins. +6 is included in the last displayed payoff bin. No observations are winsorized or assigned to a plotted tail cell. The figure reports the actual share of estimation rows in the displayed central rating-gap bins.

## Controls and K approximation

All adjusted specifications include:

- Piecewise-linear spline controls for log(1 + ply count), log chooser RD, log opponent RD, and each player's log volatility. The unchanged `surface_model.py` supplies the exact knots; these are the same controls as in the earlier run.
- Calendar-month indicators and speed indicators.
- Fine evaluation-bin indicators on a 50-cp grid. This grid extends from −600 to +600 cp; evaluation ≥+600 shares a tail indicator. The competitive restriction removes the negative lower tail. These are level controls, not separate slopes for every fine evaluation bin.

The specification ladder is (1) raw bin means on the retained sample; (2) chooser–state FE plus the above controls; (3) the same plus K20 indicators and log K; and (4) the same plus K50 indicators and log K. K20 is the primary adjusted display. K50 checks sensitivity to finer K categories.

K20 and K50 cutpoints are exact empirical quantiles from all 41,534,331 source opportunities before the competitive or singleton restrictions, as in the previous comparison. Duplicate cutpoints are collapsed and equal K values are never divided by rank. Categories include their upper cutpoint (`K <= cutpoint`); the last category is open-ended. `K_bin_support.csv` reports each category's count, minimum, maximum, and mean. High-K categories may span a large range.

These additive categories plus log K control for K approximately. They neither exactly hold K fixed nor allow arbitrary K-by-axis interactions. RD and volatility are separate controls. Persistence of a pattern under K50 is a robustness check, not proof that residual K-related confounding is absent. These models also do not establish causal effects of rating incentives, opponents, or merit.

## Board-state heterogeneity

For each axis, one additional pooled model replaces its common bin indicators with axis-bin × broad-state indicators. All nuisance-control slopes, including K terms, remain common across states. The same chooser–state intercepts, sample, and chooser clusters are used. This is more restrictive than fitting three completely separate regressions with separate slopes for every control.

Curves are normalized to the reference bin separately within each state. The joint null is that every tested nonreference bin contrast is equal in all three states. It is a test of the shape of the normalized conditional response, not equality of average kindness levels across states; the intercepts already permit different levels.

The test uses all finite displayed nonreference bins meeting the fixed support rules below in **each** state. It includes two differences per bin, better minus roughly equal and clearly better minus roughly equal, and the full cross-state covariance. A rank-aware Wald statistic divided by its covariance rank is compared with an F distribution with that rank and G−1 degrees of freedom. Rank, included bins, estimates, and uncertainty are saved. Unidentified contrasts, degenerate variances, or covariance-nullspace incompatibility are flagged rather than assigned a misleading p-value.

There are two exploratory joint tests, one for rating gap and one for payoff; their p-values receive a two-test Holm correction. This is a new exploratory family, distinct from the earlier 64 tests. Failure to reject does not establish equivalence. Rejecting the null means the common pooled curve masks differences under this specification; inspect the interacted curves before deciding what to present.

## Fixed effects, clustering, and numerical checks

Fixed effects are absorbed exactly by subtracting each chooser–state unit's regressor and outcome means. All rows of a chooser remain together across record batches and worker shards. The covariance sums scores by **chooser**, across that chooser's board states. The absorbed unit count H is not the cluster count G.

For adjusted models, the CR1 factor is `G/(G−1) × (N−1)/(N−H−r)`, where r is the rank of the within-unit design. Raw bin-mean regressions use `G/(G−1) × (N−1)/(N−r_raw)`. Curve pointwise 95% confidence intervals use the t critical value with G−1 degrees of freedom. The package saves full curve covariance matrices. Shading is pointwise, not a simultaneous confidence band.

Rank-deficient designs are solved with scaled symmetric eigendecomposition. Every requested bin contrast is checked for estimability. Synthetic self-tests compare point estimates and full cluster covariances with independent dummy-variable least squares, including cross-state dependence. They explicitly detect the incorrect alternative of clustering by chooser–state instead of chooser.

## Support and fixed tail contrasts

A bin is displayed or used in a tail test only if it has at least 500 retained opportunities, 50 chooser accounts that vary across axis bins **within at least one retained broad state**, and observations in six calendar months. Interacted state curves use the same rules within each state and common supported bins for comparison. These count thresholds are display and test safeguards, not statistical guarantees. Counts of direct within-state reference-bin connections are also saved. All finite bins and overflow rows still enter estimation regardless of display status; unidentified contrasts are flagged.

For each axis the four fixed pooled contrasts are left minus shoulder, right minus shoulder, left minus reference, and right minus reference. Components average bin contrasts using retained observation counts, and their covariance includes covariances across bins. Rating-gap centres define left [−600,−300], shoulder [−200,−50], and right [+300,+600]. Payoff centres define left [−6,−3], shoulder [−2.4,−1.2], and right [+3,+6]. If any nonzero-weight bin lacks support or identification, the contrast is not reported. These are comparisons of regions, not formal tests of a globally U-shaped function.

The eight K20 contrasts (two axes × four comparisons) form one new exploratory Holm family. Unevaluable tests retain their position in that family. Unadjusted p-values for the raw, no-K, and K50 comparisons are supplementary. None of these families is described as prespecified or confirmatory, and no earlier multiplicity correction is silently replaced.

The curves are relative percentage-point differences. Their reference is zero by normalization, with zero variance for that self-contrast. They are not probability levels, forecasts for a representative chooser, or treatment effects. The pooled design can improve precision but does not resolve all time-varying selection or motivation mechanisms.
