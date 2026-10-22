# Rating composition and observed chooser activity

This add-on addresses whether differences in typical chooser rating and preferred observed time control account for the activity-group pattern in state-specific granting. It is a descriptive standardization, not a causal effect of activity, and does not replace the paper's adjusted specifications.

## Source and fixed comparison

Use the certified 24-month pool panel with `source = 'pool' AND previous_classification_status = 'not_mutually_adjacent_observed'`. Its fingerprint is `a17c89d750cb4fdfdf84f950859e45c58b19996efae02045def68285e305cf30`. The screen concerns observed adjacency; it does not certify literal immediate rematches over complete game histories. The underlying panel has 41,534,331 opportunities and 570,091 grants.

The starting population is the same 1,982,345 choosers with F>0 competitive opportunities and L>0 clearly-worse opportunities. The states use the disconnected player's evaluation: competitive >=−100 cp; clearly worse <=−300 cp; intermediate positions excluded. Activity is F+L, with the existing fixed cutoffs 2–6, 7–16, and 17+. This measures qualifying disconnection opportunities, not total games played. All 1,757,864 observed zero-grant accounts in the binary comparison are initially retained. Outcomes never define eligibility, cells, cutoffs, or support.

The program authenticates the existing private chooser census and the 24 monthly panel Parquets by their frozen hashes. Before any new analysis it reproduces the original FE coefficient and reported SE, plus all 16 state-rate rows from the latest return, including their gap SEs and ratio intervals. The new scan reproduces F,L,A,B for every binary-sample chooser before joining covariates. Monthly feature files and their receipts are resumable and stored separately from all existing source data.

## Rating and time-control definition

Each chooser gets one fixed covariate profile:

1. Count binary-comparison opportunities within each `(api_speed,time_control)` pair over the entire panel. Select the pair with the largest count. Ties use ascending speed and then ascending time-control string, with no outcome information.
2. Within that modal pair, average valid positive pre-game `chooser_elo` values. This avoids averaging across speed pools with different ratings. This is mean pre-game rating over the panel, not rating measured before the entire panel began.
3. Assign the mean to 200-point bands with boundaries 1000,1200,...,2600 and open tails below 1000 and at least 2600. The mean may be fractional; intervals are left-closed/right-open. Missing/nonpositive ratings do not enter the mean. If no valid rating exists in the modal pair, assign an explicit missing-rating category. Empty speed or time-control fields are also explicit categories.

The state outcomes remain each chooser's A/F and B/L across all their binary opportunities, including those outside the modal time control. Accordingly, this is adjustment for typical rating and preferred observed time control. It is not focal-game adjustment for changing ratings, actual clocks, opponents, or within-person changes of time control. The report shows modal-time-control exposure shares, rating coverage, ties, and missingness so this interpretation is assessable. Remaining continuous-rating differences within a 200-point band are not eliminated.

## Common support and weights

The joint strata cross rating band with modal `(api_speed,time_control)`. A stratum is supported if it has at least two choosers in each of the three activity groups, allowing within-cell covariance estimation. No minimum number of grants is imposed. Zero-grant cells are supported when chooser counts meet this rule. Missing-rating cells are treated by the same rule.

The three reported comparison rows use exactly the same choosers in the supported joint strata:

- Unadjusted on common support: each chooser has equal weight within their activity group.
- Rating standardized: the three groups receive the same pooled chooser distribution over rating bands; their within-rating time-control composition remains observed.
- Rating and time-control standardized: the three groups receive the same pooled chooser distribution over joint strata.

The target population is the equal-chooser empirical distribution of all retained choosers pooled across activity groups. The heavier group does not supply target mass in proportion to its games. Within a cell, each chooser has equal weight in both states. Across cells, standardized weights deliberately change to balance the specified covariate distribution.

For chooser i, write v_i=(A_i/F_i, B_i/L_i, (A_i+B_i)/(F_i+L_i)). In activity group g and joint stratum s, let n_gs be the chooser count and m_gs the mean of v_i. Let q_s=n_.s/N be the pooled target share and q_r its rating marginal. Each estimator is a sum of joint-cell means with these cell weights:

- Raw: a_gs=n_gs/n_g.
- Rating only: a_gs=q_r n_gs/n_gr, where r is the rating band containing s.
- Rating plus time control: a_gs=q_s.

The same weights multiply the two state means, so their difference is the same weighted mean of individual observed competitive-minus-worse differences. RR is the ratio of the two group means, not a mean of individual ratios. No pseudocount or ever-granter restriction is used. This is equivalent to permitting unrestricted activity-by-rating-by-time-control-by-state cell means, then averaging to the target. Adding a rating intercept alone to a chooser-FE model would not address rating-related state-response heterogeneity.

An additional full-sample baseline reproduces the earlier 1.427 heavy/light ratio of RRs. Its comparison with the common-support raw row isolates sample restriction from adjustment. `common_support_flow.csv` reports retained/excluded choosers, opportunities, observed nongranters, and missing-rating counts. The target changes if support exclusions occur; the standardized estimate is explicitly for common support, not silently for all 1,982,345 choosers.

## Inference

The sampling cluster is the chooser. For the common-support comparison, intervals condition on observed joint stratum/activity counts and the empirical target mix. This targets the standardized finite-sample composition; it does not add uncertainty from resampling that composition. The original full-sample baseline keeps its earlier covariance convention.

For joint cell (g,s), the covariance of its mean is

V_gs = sum_i (v_i−m_gs)(v_i−m_gs)' / [n_gs(n_gs−1)].

For methods j and k in the same group, their cross-covariance is sum_s a_jgs a_kgs V_gs. Thus paired changes use the covariance between raw and adjusted estimates. Disjoint chooser groups are independent under the existing chooser-cluster convention.

The gap uses gradient (1,−1,0). A log RR uses (1/p_F,−1/p_L,0); intervals are exponentiated after applying the normal critical value 1.959963984540054. The heavy/light ratio of RRs uses the difference of group log RRs. Comparisons report medium/light, heavy/light and heavy/medium. Paired adjustment changes report the adjusted/unadjusted ratio of these ratios and the change in the absolute gap difference. The planned descriptive comparisons are not promoted to a new confirmatory family.

If a group-level denominator is zero, the RR is explicitly undefined; rates and gaps remain reported. No chooser is removed to make a ratio finite. No equivalence claim follows from a confidence interval containing one.

## Files

- `rating_activity_summary.csv`, `rating_distribution_by_activity.csv`, and `time_control_composition.csv`: rating/activity association and covariate distributions.
- `within_rating_time_control_rates.csv`: both state rates in every observed joint cell, including unsupported cells and zero-grant cells.
- `joint_cell_support.csv`, `common_support_flow.csv`, `standardization_target.csv`, and `standardization_weights.csv`: support and exact aggregate weights.
- `standardized_state_rates.csv`: all three estimates for each activity group, with levels, pp gaps, ratios, intervals and effective chooser counts.
- `standardized_rate_covariance_pct2.csv`: joint covariance across states and adjustments.
- `standardized_activity_comparisons.csv` and `paired_adjustment_changes.csv`: activity contrasts and paired adjustment changes.
- `baseline_*`: unchanged full-sample reference estimates and their covariance.
- `SUMMARY.md`, `ACTIVITY_RATING_ADJUSTMENT_TABLE.tex`, receipts and manifests: interpretation, manuscript table and reproducibility record.

Private identifiers, counts per chooser, and rating profiles are never included in the return archive. No API downloads, game-history requests, rating replay, or Stockfish computation are required.
