# Split-zero RD<=75 overlay: methods

## Scope and source

The authenticated parent sample is the 41,534,331 pool, non-adjacent-rematch opportunities from November 2023 through October 2025. Competitive positions have recipient-oriented evaluation >= -100 centipawns. Timeout, material and clock rules are unchanged. The prior authenticated within-chooser sorted cache is reused; otherwise it is rebuilt from the same monthly source files. No games or player profiles are downloaded.

The full-sample split-zero result is copied without modification from completed run 2994ab11f07eaf09. Its aggregate results and provenance are bundled in evidence/ALL_SPLIT_ZERO. Both baseline and new estimate must have the same source fingerprint. The newly fitted sample requires both pregame RD values <=75. Apply that filter before recomputing chooser-by-board-state singletons; require at least two retained observations per absorbed unit. Preserve accounts with no grants. There is no narrow-K filter.

Expected RD75 source counts: 12,644,084 competitive rows, 327,699 grants, 1,908,125 choosers. Expected retained counts: 11,114,912 choices, 268,079 grants, 1,207,782 chooser clusters and 2,085,192 absorbed units. Every state-specific count must match the prior RD75 run.

## Estimation

Separate linear probability models for rating gap and draw payoff. Absorb chooser-by-broad-board-state fixed effects: roughly equal [-100,100], better (100,300), and clearly better [300,infinity). Include the inherited spline in log(1+ply), separate RD and volatility splines for both players, month, speed, fine 50-centipawn board categories, frozen full-panel K20 categories and log K. K=2 times the chooser win premium. No outcome-dependent sample selection or shape restrictions are used.

The rating-gap model retains the previous 50-point bins and reference [-25,25). Its coefficients, SEs and counts must reproduce the earlier RD75 estimates. The draw-payoff model replaces the old [-0.4,+0.4) category with [-0.4,0), {0}, (0,0.4), plotted at -0.2, 0, +0.2. These coordinates are bin midpoints; exact zero is an atom. All other bins and the controls are unchanged. Exact equality to the stored unrounded payoff defines zero, with no tolerance. The split must reproduce the old RD75 reference-bin count (5,147,294) and grants (122,641).

Cluster covariance by chooser, including across board states. CR1 uses the number of absorbed units and within-design rank; t critical values use chooser clusters minus one degrees of freedom. The three adjusted near-zero contrasts use the full curve covariance matrix and Holm adjustment separately within each sample. They are exploratory finite-bin comparisons, not derivative-kink or causal-threshold tests.

## Presentation

Each sample's payoff curve is normalized to its own exact-zero group; each gap curve is normalized to its own near-equality bin. Hollow diamonds at payoff (0,0) are reference markers, not absolute kindness rates or perfectly precise estimates of them. Similar-looking curves do not imply equal absolute granting rates. Samples are nested, and the overlay is not a formal test of their difference.

No smoothing, interpolation, monotonicity or sigmoid restriction is applied. Signed payoff curves are connected separately, without a line through the exact-zero atom. The plotting break does not establish a discontinuity. Plot only identified bins with at least 500 observations, 50 switching choosers and six months; preserve unsupported holes. Overflow categories remain in estimation. Figures report displayed coverage; full support and moments are retained in the report.

The output contains aggregate results and executed code only; individual records remain on XT_Pro.
