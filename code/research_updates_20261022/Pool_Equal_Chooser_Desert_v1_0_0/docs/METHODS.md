# Estimands, inference and activity diagnostics

This is a sensitivity analysis of the **minimal binary chooser-FE desert contrast**, with no additional regressors. It does not change the adjusted relative-strength, price, dynamics or other paper specifications.

## Sample and sufficient statistics

The source is the verified pool/nonadjacent panel used by `POOL_CHOOSER_SUPPORT_RESULTS_v100_20260911T153941Z.zip`. Its private chooser census has one row per chooser and these integer fields:

| Field | Definition |
|---|---|
| `chooser` | Private chooser identifier |
| `n` | All main-panel opportunities, including middle positions |
| `f` | Competitive opportunities: disconnected player's cp >= -100 |
| `l` | Clearly-worse opportunities: disconnected player's cp <= -300 |
| `k` | Grants in all main-panel opportunities |
| `a` | Grants in competitive opportunities |
| `b` | Grants in clearly-worse opportunities |

All three regressions use exactly the same **1,982,345 accounts with f>0 and l>0**, including all **1,757,864 accounts with zero grants in that binary comparison**. This support rule does not use outcomes. The full panel has 3,224,173 choosers; the binary comparison includes 3,150,582, but same-state accounts do not identify its minimal slope.

Write F_i=f_i, L_i=l_i, N_i=F_i+L_i, p_i=F_i/N_i and d_i=a_i/F_i-b_i/L_i. N_i is the count **in the binary estimating sample**, not the `n` column when a chooser also has middle-position opportunities.

## Three distinct weightings

| Estimator | Analytic weight on every observation of chooser i in a FE LPM | Weight on chooser's observed difference d_i |
|---|---|---|
| Original FE | 1 | w_i=F_i L_i/N_i=N_i p_i(1-p_i) |
| Inverse-count FE | 1/N_i | v_i=F_i L_i/N_i^2=p_i(1-p_i) |
| Equal chooser | N_i/(F_i L_i)=1/w_i | 1 |

The resulting coefficients are sum(w_i d_i)/sum(w_i), sum(v_i d_i)/sum(v_i), and mean(d_i), respectively. The code checks all three against the weighted within-FE normal equations. Giving each person unit total observation weight through 1/N_i does **not** make each person's observed state contrast equally weighted: state balance remains in the regression's information weight.

Every outcome history is retained on the common state-support sample. No ever-granter-only regression is fitted. The ever-grant shares requested for slides are calculated descriptively and do not enter sample selection or analytic weights.

## Joint uncertainty and paired comparisons

For estimator j, let a_ij be its normalized chooser weights (sum_i a_ij=1), and b_j=sum_i a_ij d_i. Define the chooser influence contribution u_ij=a_ij(d_i-b_j). The reported joint covariance is

V_jk = [G/(G-1)] sum_i u_ij u_ik,

where G is the number of state-varying choosers. For the equal-chooser estimator, this yields the sample standard deviation of d_i divided by sqrt(G). For a difference b_j-b_k, its SE uses [G/(G-1)] sum_i (u_ij-u_ik)^2. It does not treat the estimates as independent. Confidence intervals use the normal 1.95996398454 critical value. This follows the existing convention of independent chooser clusters; dependence between choosers is not newly addressed by this check.

The current original slope is 2.1744903481070983 percentage points, with source-reported C7R SE 0.009648688363965123 pp. Those values are reproduced as a source gate. C7R's source finite-sample correction counts absorbed chooser effects and uses all binary-sample clusters. The comparison table uses one common chooser-level correction on the state-varying accounts, yielding an original-FE SE near 0.00923864 pp. The old SE remains recorded separately in `BASELINE_REPRODUCTION.json` and `SUMMARY.md`; it is not silently relabeled as the new convention.

All effect and SE columns ending in `_pp` are percentage points. `estimator_covariance_pp2.csv` is in squared percentage points. Interpret the magnitude and interval of changes. A nonsignificant paired difference is not an equivalence test or proof that weighting does not matter.

## Activity diagnostics

`activity_decile_weight_shares.csv` and `activity_top_shares.csv` distinguish three ranking populations:

1. `all_pool_choosers`: all 3,224,173 main-panel choosers, ranked by all main-panel opportunity counts (`n`).
2. `all_binary_comparison_choosers`: all 3,150,582 binary-sample choosers, ranked by F_i+L_i.
3. `state_varying_choosers`: the 1,982,345 accounts common to all three regression estimates, ranked by F_i+L_i.

The files report opportunity shares and identifying-weight shares under **all three** estimators. Same-state choosers have zero weight under each estimator. At a decile or top-fraction boundary, every chooser tied on activity receives the same fractional allocation to the adjacent reporting bins. This preserves exact population fractions without selecting on outcomes, IDs or arbitrary record order. These descriptive bins have `chooser_equivalents`, which can be fractional. Decile shares sum to one; top shares are cumulative tails and overlap.

The earlier observed top-decile opportunity shares are about 51.8% in the full panel and 51.2% in the binary comparison; top-percentile shares are about 12.4% and 12.2%. The new code computes FE weight shares directly rather than inferring them from these opportunity shares.

`activity_tercile_estimates.csv` compares light, medium and heavy accounts **within the same state-varying sample**, using F_i+L_i. Cutoffs are the empirical one-third and two-thirds quantiles. All accounts tied at the first cutoff go to the light group; ties at the second go to the medium group. Identical activity counts are kept together, so group sizes need not be exactly equal. Every nonempty group gets all three estimates and paired comparisons. If ties make a group empty, its zero support is reported instead of inventing an estimate. The group counts and actual cutoffs are recorded separately.

The activity groups and the ever-grant descriptors are specified before reading the new reweighted estimates. These are requested robustness/descriptive checks, not a new claim that the platform assigns states or that activity is exogenous.

## Slide denominators

`granting_rates.csv` reports, for the full panel, the binary comparison and competitive opportunities:

- fraction of opportunities granted: sum_i grants_i / sum_i opportunities_i;
- fraction of observed choosers who grant at least once;
- equal-chooser average of each chooser's observed grant rate.

The three summaries answer different questions. “Ever grants” refers to the observed panel and naturally depends on the number of opportunities observed; it does not classify permanent behavioral types. Use the current pool numerator and denominator rather than the older sample's 1.41% figure.

## Integrity and privacy

The program authenticates the existing census contract against the returned support audit, verifies the census hash and integer sufficient-statistic constraints, checks all current sample and support counts, and reproduces the original FE coefficient and as-reported SE. It reuses that authenticated derived census rather than rereading all 24 monthly Parquets. Account IDs and chooser-level records stay on the Mac. Only explicitly named aggregate files are included in the return archive.
