# Reference dependence: what this analysis can test

Let D be the chooser's rating change from a draw, K the rating sensitivity, and W=D+K/2 the rating change from claiming a win. Both are measured relative to the pregame rating. This uses the panel's audited payoff identity; the runner does not replace its producer.

An explicit illustrative choice model is:

```
grant iff B + epsilon >= v(W) - v(D)
v(z) = z^alpha                  for z >= 0
       -lambda * (-z)^alpha    for z < 0
0 < alpha <= 1, lambda >= 1
```

B is the non-rating benefit of granting, including concern for the recipient and perceived desert. The distribution of B+epsilon determines the grant probability. This is a specified reference-dependent utility model for comparison with diagnostics, not an estimated or identified structural model. The runner imposes none of its shape restrictions on the data.

For fixed K, the relevant sacrificed rating utility is `C(D,K)=v(D+K/2)-v(D)`. It is not simply v(D), D, or abs(D). If `P(grant)=1-F(C-B)` with a smooth distribution F and B locally fixed, derivatives of the grant curve depend on both C and the density of F. An S-shaped value function is not itself an S-shaped choice-probability prediction.

Under the piecewise-linear case alpha=1 with loss aversion lambda>1, C=K/2+(1-lambda)D for D<0 (where W>0), and C=K/2 for D>=0. Conditional on constant B, K and F, this predicts an increasing grant probability just to the left of zero and a flat probability to the right, with continuity at zero. It does not predict a symmetric sigmoid.

For 0<alpha<1, on either side of zero where W>0:

```
dC/dD = alpha*(D+K/2)^(alpha-1) - lambda*alpha*(-D)^(alpha-1), D<0
dC/dD = alpha*(D+K/2)^(alpha-1) - alpha*D^(alpha-1),           D>0
```

Close enough to zero this derivative is negative on both sides, so the grant probability rises as D rises if the other terms are locally fixed. The loss side has a lambda-scaled singular marginal-value term. This does not make finite-bandwidth slope ratios estimates of lambda: gain curvature, window width, K variation, the benefit distribution, controls and selection all matter. Far into the negative tail, as W approaches zero, the first derivative term can dominate. This model can itself permit a left-tail upturn in granting; one should not label every upturn contamination.

A smooth value function with the same gain and loss curvature and lambda=1 can also generate strong behavior near the reference point. Conversely, smooth changes in the non-rating benefit with relative strength can generate an S-looking choice curve without rating reference dependence. These mechanisms are not separated by plotting alone.

The unrestricted local diagnostics ask about continuity, slope direction, and finite-window slope asymmetry. For the primary narrow-K sample, a clearly estimated jump is inconsistent with the simple continuous model under smooth B and F, but could instead reflect model approximation, a tie norm, discrete rating support, or changes in composition. The separate exact-zero coefficient helps distinguish equality mass points from one-sided limits. A null jump is necessary under that simple model, not sufficient evidence for it. Null slope differences are not evidence of no reference dependence. Read the windows together rather than selecting the most favorable p-value.

The normalized axis D/K=0.5-E removes the payoff's K scale. With Glicko's expected score, at fixed opponent RD it is a monotone transformation of opponent-minus-chooser rating gap, and zero coincides with equal ratings. Thus after holding K and RD nearly fixed, the payoff and relative-strength plots are expected to look more alike mechanically. Agreement between them is not an independent identification test. Any model comparison needs additional restrictions or variation distinguishing the rating-utility cost from recipient-relative-strength preferences; it cannot be obtained simply by simultaneously controlling flexibly for both mechanically linked axes.

Read the returned figures as follows:

1. If the payoff rebound attenuates in the stable samples on well-populated common bins, the result is consistent with an RD/K-composition explanation. It does not establish that the excluded players were new or that composition is the sole explanation.
2. If the tail vanishes because the RD/K restrictions remove observations there, report lack of support. Do not claim the effect vanished.
3. If the rebound survives with adequate within-chooser variation and clustered precision, treat it as a substantive descriptive pattern. It can reflect heterogeneous rating sensitivity, residual selection, preferences, or other mechanisms.
4. If an increasing S-looking curve remains, describe that empirical shape. Claiming reference dependence additionally requires the specified utility-and-choice assumptions. These diagnostics do not identify prospect-theory parameters or a causal price response.

Source for the rating mechanics and interpretation of RD: [Mark Glickman, *Example of the Glicko-2 system*, March 22, 2022](https://www.glicko.net/glicko/glicko2.pdf). The piecewise power value function above is an explicitly stated modeling choice. The empirical code uses frozen panel fields and does not fetch live ratings.
