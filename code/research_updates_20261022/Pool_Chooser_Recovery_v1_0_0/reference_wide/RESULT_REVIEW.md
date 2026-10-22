# Review of the completed bound-sensitivity run

23 September 2026. Source: `POOL_CHOOSER_BOUND_SENSITIVITY_RESULTS_v100_f14e1be2f5314f2e.zip`.

The archive checksum matches: `5aa09227dc9589faab8e86f118651f19d371b1be643e966c580085decbd32bcd`. All 75 report-manifest entries and the producer files verify. It is linked to the reviewed v1.1.2 source run. It contains the point sensitivity, not a wider-bound bootstrap, recovery, or a new switching comparison.

## Predictive result

The headline ordering survives wider numerical domains. Gains below are mean sequential held-out log-score differences per opportunity.

| Comparison | Original | 2x bounds | 4x bounds |
|---|---:|---:|---:|
| Desert − level | +0.000732763 | +0.000766608 | +0.000766046 |
| Desert − cost | +0.000868099 | +0.000903123 | +0.000901829 |
| Both − desert | −0.000033840 | −0.000057389 | −0.000049168 |
| Cost − level | −0.000135336 | −0.000136515 | −0.000135783 |

Polishing at the original bounds changes no selected vector or score. All 161 optimizer attempts converge, all 161 feasible-start checks pass, and the largest projected gradient is about 0.000020. The point-estimate exercise provides reassurance about the predictive ordering under these numerical relaxations. It does not itself update the bootstrap intervals.

Desert also improves the equal-account point score against level and cost at 4x bounds, by roughly 0.000955 and 0.000985 respectively. Both minus desert has a small positive equal-account point gain (about 0.000021), unlike its negative opportunity-weighted gain. State which weighting is being used.

## What remains at a cap

Only the cost model has a numerical cap at 4x bounds. Its raw common theta rises from 48 at 2x to 96 at 4x; its reported anchored-index slope barely moves, from 1.700 to 1.696, as the index offset approaches one. This is consistent with poorly conditioned raw coordinates. It is not evidence that the substantive responsiveness is 96, or proof that the cap is harmless.

The desert fit at 4x is exactly its 2x vector and score. Its former cap disappears because the allowed domain expands; it should not be described as new optimization movement away from that point. Some index cells in other models move more than aggregate predictive scores. Predictive stability and parameter stability are different checks.

## Why the next run is focused

The original 120-draw bootstrap put desert minus level at +0.000733, with bootstrap SE 0.000191 and marginal percentile interval [0.000330, 0.001087]. That interval is encouraging. However, 54 of the 120 paired draws had a numerical cap in desert or level; 44 desert-versus-cost pairs were similarly affected. A stable full-sample point estimate does not show that these resample fits are stable.

The next package therefore refits only the four headline models on those same account resamples using the fixed 4x domains. All capped draws remain. It compares the new interval and each paired draw with the old result. The procedure also uses additional feasible warm starts, so any difference is a wider-domain/multistart sensitivity, not a pure causal attribution to the numerical bound alone.

If the positive desert-versus-level and desert-versus-cost intervals survive with acceptable convergence, the defensible finding is that these specified models predict granting better when persistent heterogeneity includes responsiveness to the shared state index. It does not establish psychological motives, equal valuations of rating, a discrete set of personality types, or a flat non-construing majority. Recovery and a switching comparison with the same emissions remain separate next steps.
