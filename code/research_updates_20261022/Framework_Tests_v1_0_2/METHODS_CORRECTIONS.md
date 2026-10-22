# Interpretive and statistical corrections to the Oct 11 framework-test handoff

These edits are proposed **before real-data execution**. They do not change the previously observed results.

## A — Flags and the negative Patron association

- Closed/flagged account selection is an important competing explanation. Preserve profile missingness separately from known false flags. A missing JSON field on a returned profile can be false; an unavailable profile is not a known unflagged non-Patron.
- The published comparison's matching groups and original controls must be reused, not recreated from a different pool. Excluding focal granters changes matched-group support; report exact attrition and use identically supported comparisons where feasible.
- Persistence of a negative coefficient after flag exclusions only excludes one **observed mechanical mechanism**; it does not establish a latent preference interpretation. Attenuation also cannot by itself prove flags caused the original sign.
- Read `disabled` and `tosViolation` as August 2026 states, not states at each grant in 2023–2025.

## B — Holdout group heterogeneity

- Distinguish the nominal **win-minus-draw cost** `kappa = K/2` from the signed **draw payoff** `rG = K(1/2-E)`. A slope in `rG` can reflect how much a draw improves the chooser's rating or the opponent's inferred strength, not the cost of choosing draw rather than win. This dataset cannot cleanly separate them, because displayed rating gap and draw payoff are mechanically linked.
- P1 BOTH vs CO is not a verified high-desert/low-price-sensitivity split. The probability of being BOTH rises with the number of earlier opportunities and with generic granting propensity. Requiring four in each state limits, but does not remove, classification error or selection.
- Proportional derivatives by group are useful descriptive quantities. Avoid treating the pair of fixed `rho_gap` and `rho_pos` cutoffs as a model-selection proof, even if declared before this run. Report confidence intervals for the interaction/difference and its descriptive size.
- Use P2 accounts actually retained, and report P1 activity by group and P2 survival. The conditional logit drops accounts whose P2 outcome never varies and is therefore a selected subset—report its retention and do not regard it as identical to the chooser-FE LPM estimand.
- The handoff requests a **group-specific stage 41–80 coefficient** while specifying common stage FE. The code corrects this by allowing stage-by-group interactions.
- The handoff's power note needs a realized support/variance calculation; do not rely on stated assumed group sizes or standard errors.

## C — Statistical zero inflation vs psychological gate

- Every chooser in the 41.5m analysis sample has experienced at least one observed active choice. The accurate observation is *most chooser accounts never grant*, not *most accounts never see a choice*.
- A mixture with a point mass at zero is an observational *statistical model*. A continuous distribution with density near zero or a drifting propensity can produce similar high-`E` zeros. The two-component likelihood does not identify an awareness or construal mechanism.
- The structural-zero mixture weight is `1-gamma` and the conditional active weight is `gamma`. The null is `gamma=1` (boundary), so use the 50:50 mixture LR reference. Normal-Wald intervals for gamma near 1 may be unreliable.
- P1-to-P2 holdout predictions for persistent zero granters are necessary. Even good predictive fit is not evidence of learning the option's existence.
- Do not infer a b-parameter shift solely because zero inflation is unsupported.

## D — Secondary proxy if essential

- RD>110 indicates rating uncertainty / provisional rating, not necessarily low weight on ratings. Higher RD is mechanically associated with a larger `K`; conditioning or normalizing does not make the provisional indicator an exogenous price-treatment proxy.
- A high casual-game share could indicate less attachment to rated stakes or simply a different population, game speed, tenure and experience. Avoid a causal interpretation. Retrieval from source PGNs may be necessary; no API work is implied.

## E — Receipt prior-experience groups

- Define mutually exclusive groups (strictly before exposure): PG = ≥1 previous observed chooser grant in **any** state; PC = zero previous observed grants and ≥1 competitive chooser choice; NC = neither. The handoff's literal descriptions overlap if an account previously granted only in lost positions.
- Pre-exposure histories are **left censored** at November 2023; NC does not mean unaware or historically inexperienced.
- A PG effect distinguishable from zero tests a response *among previous observed granters*, but does not directly identify whether the treatment shifted `b`, attention, gratitude, or external conditions.
- A confidence interval *including* zero is not an equivalence test. Predeclare a practical margin and examine PG−NC and its CI; a joint LPM/IV interaction test should use the design's original clustered covariance and the same cohort's first stages.
- The IV group interactions inherit the identifying assumptions of the score and add subgroup overlap/selection concerns. Preserve index-game start times for pre-exposure classification and exclude pair-history leakage.
- Do not use the proposed mechanistic text changes in the manuscript automatically based on p-value alone.

## Real-data provenance note

The accessible project handoffs report the all-source Stage 07 production panel at 47,587,020 opportunities, but the user's current paper uses the **pool/nonadjacent** sample of 41,534,331 opportunities, with 570,091 grants. Stage 10 matching snapshots, test-E receipt cohort, and the specific private pool sample Parquets are not uploaded here. Where exact private input columns or matched-group IDs are unknown, fail closed rather than silently substitute alternate sources.

## F — Across-year persistence in different board states

- **Do not pool modestly-worse with clearly-worse silently.** Primary states are C (`v >= -100`) and L (`v <= -300`), with M (`-300 < v < -100`) separate. The pooled all-noncompetitive (L+M) variant is explicitly a sensitivity.
- **"Neither" is not "never granted."** NEI means no grants in the two primary categories within that particular year; an M-region grant may still occur.
- **A transition from CO to CO depends strongly on opportunity counts.** Restrict exposure eligibility in both years and report P1 eligibility-to-P2 retention, but do not interpret transitions as a type estimate.
- **The 0.545 and 0.618 published correlations use a different, broader C-only returning cohort.** Reproduce that cohort as an input check, then separately report the stricter two-state balanced cohort. Never copy its headline correlation onto the stricter population.
- **Sparse L grants attenuate observed account-level persistence and widen intervals.** Compare like-for-like and cross-state prediction with opportunity controls, but do not interpret a null L coefficient as absence of stable L behavior.
- **Year-two rating, state and speed summaries are post-P1 characteristics.** They provide descriptive adjustment, not a causal or predetermined control design.
- The two cross-outcome predictive contrasts scale each estimate by that outcome's own P2 mean. Treat their two Holm-adjusted p-values as exploratory evidence of persistence specificity, not an automatic verdict on desert, attention, generosity or low concern for ratings.

## F production collinearity correction (Oct 12, 2026)

The first actual Test F v1.0.1 run validated the exact 41,534,331-row paper
sample but failed when the cross-state year-two regression detected a singular
weighted design. The balanced sample may have no observations in one of the
complementary speed categories: then the four included speed shares sum to
one and are collinear with the intercept. The dataset from the Mac is not
available here, so the precise redundant column cannot be established without
the new collinearity audit. v1.0.2 drops only nuisance columns which are
redundant in the weighted fit, preserves all focal grant-history terms,
records the omitted columns, and uses weighted QR for coefficient estimation.
Do not infer from the previous failure that an economically meaningful
predictor is unidentifiable.
