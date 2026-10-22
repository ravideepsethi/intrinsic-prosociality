# Activity-group state rates and proportional contrasts

## Frozen source and support

The source is the existing private chooser census from the certified pool/nonadjacent sample. Its exact SHA-256 is anchored to the verified equal-chooser return. Every account has F competitive opportunities, L clearly-worse opportunities, A competitive grants and B clearly-worse grants, plus full-panel counts. Competitive means the disconnected player's evaluation >= -100 cp; clearly worse means <= -300 cp.

Only the same previously used accounts with F>0 and L>0 enter this comparison. The fixed activity cutoffs are F+L <= 6 (light), 7–16 (medium), and >=17 (heavy). All zero-grant accounts are retained. The program must reproduce the prior 12 overall/group desert coefficients and their common-covariance standard errors before completing.

## Four rate conventions

Let f_i=A_i/F_i, l_i=B_i/L_i and t_i=(A_i+B_i)/(F_i+L_i). For the first three conventions, use the same normalized chooser weights h_i in both states:

| Convention | Unnormalized chooser weights | Competitive rate | Clearly-worse rate |
|---|---|---|---|
| Original FE | F_i L_i/(F_i+L_i) | sum h_i f_i | sum h_i l_i |
| Inverse-count FE | F_i L_i/(F_i+L_i)^2 | sum h_i f_i | sum h_i l_i |
| Equal chooser | 1 | mean f_i | mean l_i |
| Raw pooled opportunities | State-specific opportunity counts | sum A_i / sum F_i | sum B_i / sum L_i |

For each of the first three conventions, p_F-p_L reproduces its earlier within coefficient. Their overall rate is sum h_i t_i. The raw pooled overall rate is sum(A_i+B_i)/sum(F_i+L_i). Rates refer to the binary estimating sample; the full-panel talk statistics have broader denominators.

The standardized level (p_F+p_L)/2 represents a common 50/50 state mix. The observed overall level instead retains the realized state mix and need not equal that standardized level.

The proportional comparison is **R=p_F/p_L**, the ratio of group rates under the stated convention. The program never averages individual f_i/l_i ratios: individual denominators are frequently zero, and dropping those accounts would select on observed outcomes. No pseudocounts, smoothing constants or ever-granter restrictions are introduced.

## Covariance and intervals

For common chooser weights, define u_i = h_i [(f_i,l_i,t_i) − (p_F,p_L,p_T)]. The rate covariance is [G/(G−1)] sum_i u_i u_i'. For raw pooled rates, each column uses its ratio-estimator influence contribution; for example u_Fi=(A_i−p_F F_i)/sum F_i. Both state outcomes for a chooser therefore contribute to the same cluster and their covariance is retained.

The absolute gap uses gradient (1,−1,0). The standardized level uses (1/2,1/2,0). The log risk ratio uses gradient (1/p_F,−1/p_L,0). Its delta-method interval is exponentiated to give the RR interval. Ordinary normal intervals for probability levels are not artificially clipped; ratios use log-scale intervals.

Comparisons between the disjoint activity groups use the existing independent-chooser-cluster convention. The heavy/light ratio of RRs is exp(log R_heavy − log R_light), with variance on the log scale equal to the sum of their variances. Its null is 1. Absolute-gap differences are also reported. These are requested descriptive robustness comparisons, not a newly declared confirmatory family or a causal test of how activity changes behavior.

If a group-level clearly-worse rate is zero, its RR is undefined and explicitly flagged. If its competitive rate is zero but the worse rate is positive, the RR point estimate is zero and log inference is unavailable. No accounts are removed to make these quantities finite. Rate levels and gaps remain reported. A group with only one chooser gets no cluster-based interval.

## Files and privacy

`state_rates_and_ratios.csv` contains the four rate conventions for all both-state choosers and the three activity groups. Rates are percentages; gaps are percentage points; RR is dimensionless. Covariances in `state_rate_covariance_pct2.csv` are squared percentage points. `activity_ratio_comparisons.csv` contains between-group ratios of RRs and differences in absolute gaps.

The LaTeX table presents the equal-chooser version, with clearly labeled denominators. The summary also displays the original-FE, inverse-count and raw pooled conventions. Identifiers and chooser-level records remain on the Mac; the return archive includes only named aggregate files. The previous coefficient and inference convention are reproduced, and no adjusted paper model is reestimated.
