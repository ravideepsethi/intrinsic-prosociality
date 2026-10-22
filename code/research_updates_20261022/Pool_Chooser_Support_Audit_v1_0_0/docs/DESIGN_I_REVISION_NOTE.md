# Design I: chooser support and the within estimand

Prepared 11 September 2026. The reporting request is right; parts of the proposed interpretation need qualification. The existing Design I paragraph already calls the estimates conditional within-chooser associations. It should now explain support and weighting explicitly.

## Use the current sample

The main panel is `source = 'pool' AND previous_classification_status = 'not_mutually_adjacent_observed'`, using the existing certified exclusion. This is an observed mutual-adjacency exclusion, not an exclusion of every repeated dyad.

| Quantity | Current authenticated result |
|---|---:|
| Main-panel opportunities | 41,534,331 |
| Main-panel choosers | 3,224,173 |
| Mean opportunities per chooser | 12.8822 |
| Competitive-or-clearly-worse opportunities | 37,872,241 |
| Choosers represented in that binary contrast | 3,150,582 |
| Minimal chooser-FE desert gap | 2.174490 pp |
| Later competitive-opportunity grant rate, prior-period granters | 16.0975% |
| Later competitive-opportunity grant rate, prior-period nongranters | 0.9986% |

The 47.6M/3.56M sample totals and 14.95% prediction rate in the comment are from the older sample. The latest minimal desert coefficient rounds to **2.17 pp** at two decimal places, not 2.18 pp. It is the binary chooser-FE-only result in the current Wave2B1 C7R table; do not transfer that label to a different adjusted specification.

The returned Wave1 and Wave2B1 archives do not provide the main-panel median, number with more than one opportunity, or number observed in both desert states. In particular, 3,150,582 is the number represented in the binary contrast, not the number with identifying state variation. A singleton-heavy distribution cannot be deduced from the mean alone.

The audit computes those missing quantities from the existing local panel, with separate summaries for the full panel, the binary desert sample, and competitive opportunities. The state definition is the disconnected player's evaluation: competitive means at least −100 cp; clearly worse means at most −300 cp. Middle positions are omitted only from the binary contrast.

## What the within coefficient averages

For the minimal binary model with chooser fixed effects and no other controls, let chooser i have F_i competitive opportunities and L_i clearly-worse opportunities. Then

\[
\widehat\beta = \frac{\sum_i w_i(\bar Y_{Fi}-\bar Y_{Li})}{\sum_i w_i},
\qquad w_i=\frac{F_i L_i}{F_i+L_i}.
\]

Accounts observed in only one state have weight zero. Accounts observed in both states receive positive weight, including accounts that never grant in the contrast sample: their observed difference is zero. This is a within-variation-weighted contrast, not an equal-person average over every chooser. Additional controls change the residualized state regressor and its weighting; the simple formula is specific to the minimal binary specification. Same-state accounts can then help estimate nuisance coefficients, so the both-state count is a direct-support diagnostic, not a complete description of every adjusted estimator.

Call this a conditional association, consistent with the paper. Zero observed grants do not establish a zero individual causal effect or an intrinsically non-granting type. Short histories also make observed all-zero outcomes more common.

Keep all outcome histories in the estimating sample. Re-estimating on full-window ever-granters would select on the outcome. The audit does not fit that model. It reports, descriptively, the identifying-weight share supplied by state-varying accounts with no grants in the binary contrast; this makes their contribution visible without selecting a new regression sample.

## Singleton wording

For a one-way chooser-FE LPM, singleton observations have zero demeaned regressors and contribute nothing to its slope normal equations. Removing them leaves the slope estimates unchanged algebraically. Do not extend that statement automatically to clustered standard errors: finite-sample corrections can change when the observation and cluster counts change. See [Correia (2015), Singletons, Cluster-Robust Standard Errors and Fixed Effects: A Bad Mix](https://scorreia.com/research/singletons.pdf).

The current C7R result uses the correction G/(G−1) × (N−1)/(N−G−1), counting absorbed chooser effects in the degrees of freedom. The Stage08 estimator drops rows without within-regressor variation and uses a different correction for chooser clustering. The audit reproduces C7R as reported and labels the alternative separately; it does not overwrite either source result. It checks singleton invariance for this minimal desert coefficient and the rounding of its standard error separately. It does not certify all other Design I models.

Safe wording now: “Singleton choosers have zero demeaned regressors and therefore do not contribute to the within-chooser slope estimates.”

After the audit passes, its generated paragraph adds the actual counts and the verified statement that explicitly dropping singleton choosers leaves the minimal desert coefficient unchanged to four decimal places in percentage points. Use the standard-error sentence only if its separate check passes.

## Manuscript language available now

Replace the conceptual part of Design I with:

> The primary specifications are linear probability models with chooser fixed effects and standard errors clustered by chooser. They compare opportunities faced by the same account, holding the other included state variables fixed. The estimand is a conditional within-chooser association, with weighting determined by the available within-person covariate variation. Choosers remain in the sample regardless of whether they ever grant a draw. In the minimal competitive-versus-clearly-worse specification, the coefficient is a weighted average of the observed within-chooser grant-rate differences, with positive weight only for choosers observed in both states. The state is not assigned, so these estimates do not identify causal effects.

The runner writes a completed count paragraph and a LaTeX replacement after calculating the missing support statistics. It does not put guessed counts into the manuscript.

For the persistence discussion:

> The within-chooser desert contrast and the persistence results describe different features of behavior. The former measures how granting varies with the position within a chooser, retaining accounts with no observed grants whenever they supply state variation. The latter shows that granting is concentrated and predicts subsequent granting: in the current temporal prediction sample, later competitive-opportunity grant rates are 16.10% among choosers who granted in the earlier period and 1.00% among those who did not. Together these findings document state dependence and persistent heterogeneity in granting. They do not identify the size of individual desert responses among a latent prosocial subgroup.

The prediction comparison groups choosers using the earlier 12 months and evaluates behavior in the later 12 months; it is distinct from restricting an estimation sample using grants observed anywhere in the full window. Its rate denominator is later competitive opportunities, not persons. Additive chooser fixed effects and split-half correlations concern levels and persistence, not chooser-specific desert slopes.

If updating the split-half numbers too, preserve the cohort rule: the current temporal table's cutoff 4 means at least four competitive opportunities **in total**, with both halves represented. It does not mean four in each half. That row has Pearson correlation 0.5453 and total-opportunity-weighted correlation 0.6178 across 666,131 accounts. The 16.10%/1.00% headline prediction comparison uses the broader cohort observed in both halves (minimum total two), so these are not identical samples.

## Evidence and remaining step

The current sample authority and three relevant returned tables are bundled under `authority/` and `evidence/`, with source paths and hashes in `authority/REFERENCE.json`. Both returned result archives passed their outer hashes and all 427 internal report-manifest entries before these extracts were used.

Run the supplied audit on the Mac holding the certified 24 monthly Parquets. Expected runtime is about 2–5 minutes with an existing compatible environment; this is an estimate, not a production benchmark. No production support counts were computed in this workspace. Return the resulting ZIP and SHA-256 sidecar so the final numerical paragraph can be checked against the completed run.
