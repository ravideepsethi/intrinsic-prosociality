# Fixed-fit color-change prediction update

## Population and evidence

The authenticated November 2023–October 2025 mechanism analysis files are the sole row-level inputs. Regularity is inherited from the completed mechanism run: at least 100 prior same-speed rated starts, at least 365 days of observed same-speed history, and activity in each of the previous four seven-day windows. Primary rows are roughly equal (disconnected-player evaluation −100 to below +100 centipawns), after ply 10, with displayed opponent-minus-own gap in [−575,575), both RDs in [45,110], and the existing certified pool/observed-previous-adjacency restriction.

Regularity here is rolling, measured at each pre-policy opportunity. It is **not** the intended fixed pre-implementation cohort for an event study. Pre-policy support must match 3,236,219 opportunities, 58,298 grants and 778,048 chooser accounts. All source file hashes and payoff identities are checked. Counts of grants are integer events, never multiplied by 100; only probabilities/rates use percentage points.

Coefficient snapshots are copied without account IDs from the reviewed repaired RD audit result, SHA-256 `8bcda7730c8ea1ee994bd6f3884092046dca6c718f7fb8dc6171b3c30d2fb505`. Seven capped full fits are primary. Original full fits for curved utility, framing and displayed gap show the effect of the RD correction on identical target rows. Capped fold-0/fold-1 fits for those three models are parameter-stability sensitivities. These are not new held-out forecasts, independent estimates, bootstrap intervals or an equivalence test.

## Exact mechanical changes

At each stored pregame state, compute both actions under color advantage 0 and 11.782457 inside the expected-score logit, with White receiving the positive adjustment. Use the same anchored calculator as the audited mechanism and color first pass. Both players' premiums, the draw payoff and claim payoff are recomputed. Fractional production ratings, perceived prices and integer feedback are not reconstructed.

With own premium κᵢ, opponent premium κⱼ, draw payoff rG and claim payoff rC, the frozen model index terms are:

- cost: −aκᵢ + bκⱼ;
- loss: −aκᵢ + bκⱼ − ℓ(−rG)₊;
- curved utility: −a[u(rC)−u(rG)] + bκⱼ, with the stored selected curvature;
- framing: −aκᵢ + bκⱼ + frG;
- displayed gap and its two augmented versions: the relevant preceding payoff terms plus the frozen gap basis.

All coefficients, gap values, controls and nuisance offsets stay fixed between counterfactuals. The gap term itself has zero direct policy change; its model can still respond if a fitted payoff coefficient is nonzero. Index component changes are reported as index units, not percentage-point contributions or causal shares. Near ties retain displayed ties separately from strict draw-payoff sign flips. No rounding rule is fitted to observed draw changes.

## Additional baseline model

Conditional chooser logit identifies within-chooser index slopes, not marginal grant probabilities or intercepts for never-granting choosers. A probability forecast therefore needs an additional baseline assumption.

For each coefficient snapshot, evaluate its old-formula index η on all eligible pre-policy rows. Let chooser i have nᵢ opportunities and sᵢ grants and let p̄ be the overall pre-policy grant rate. Primary account calibration solves mean Λ(αᵢ+η)= (sᵢ+20p̄)/(nᵢ+20). Then a common intercept shift c matches the overall eligible pre-policy grant rate exactly. This second calibration prevents changes in the marginal baseline due solely to shrinkage weighting. It was not enforced by the earlier mechanism policy screen, so the updated old-fit predictions need not equal that screen's published numbers.

Counterfactual probabilities are Λ(αᵢ+c+ηold) and Λ(αᵢ+c+ηnew). Both use the same pre-policy offsets and common shift. Outcomes after October 2025 are neither loaded nor used. Sensitivities use shrinkage counts 5 and 100, and a pooled intercept with no account offset, for the three surviving families. These illustrate dependence on the added baseline model; no preferred variant is selected by its policy prediction. Adaptive numerical brackets handle very large nuisance/gap offsets without silent clipping.

Fitted-parameter uncertainty is **not propagated**. Some fits contain binding sign constraints; ordinary Gaussian/Wald draws from their covariance matrices are not a valid substitute. This finite update has no candidate refits. If a matched post-policy test is pursued, prediction uncertainty must be handled with an appropriate constrained refit/bootstrap procedure or explicitly conditional inference. Neither the fold spread nor the baseline sensitivity range is a confidence interval.

## Statistic and transport targets

Let Wₜ and Bₜ be the mean predicted grant probability for White and Black chooser opportunities in complete UTC Monday–Sunday week t. The predicted policy statistic is 100 × meanₜ[(Wnewₜ−Woldₜ)−(Bnewₜ−Boldₜ)]. This is the change in a White-minus-Black contrast, not a single-color relocation and not a symmetric gap triple difference. Its no-policy mechanical pre-period change is zero. Calendar weeks receive equal weight; opportunities within a color-week receive equal weight.

Two frozen targets are reported: all complete weeks inside the certified November 1, 2023–November 1, 2025 half-open coverage, and the final eight such weeks. Entire boundary weeks are excluded by calendar coverage, not by the first/last observed opportunity. Every complete week must have both colors and every interior calendar week must exist. No missing week is filled with zero. These are transport scenarios; neither is the realized post-policy opportunity distribution.

## Planning power

Construct the observed pre-policy White-minus-Black weekly grant-rate series on the same capped rolling cohort. Draw 10,000 moving-block sequences of length 8+H for H=4 or 8 hypothetical post weeks, using contiguous source blocks of 4 or 8 weeks. For each sequence, take the last H weeks' mean minus the first eight weeks' mean. Center the simulated contrasts at zero. The rejection threshold is the empirical 95th percentile of the absolute centered contrasts (higher order statistic; reject strictly above it).

The 80% planning MDE is the smallest searched magnitude whose empirical rejection probability reaches 80% for both positive and negative shifts. It is a two-sided, dependence-aware simulation screen under a stationary transport assumption, not a measured event standard error. The bootstrap preserves short weekly dependence; it does not solve trend, seasonality, policy confounding, fixed-cohort selection or event-specific variance changes. Pre-period weekly data and fixed-date placebo contrasts are exported for review. Placebos are descriptive, overlap, and are not independent randomized tests.

For awareness q in {0.05,0.1,0.2,0.5,1}, use p(q)=(1−q)pold+q pnew. Thus the aggregate mechanical shift is q times the full-awareness shift. This is an exogenous homogeneous responder mixture. Scaling an index coefficient before the logit is a different model and is not done here. Awareness is not measured, and its product with any mechanism prevalence cannot be decomposed by this calculation.

Report both each model's contrast against zero and pairwise differences between full capped candidates, on the exact same statistic and power distribution. Pairwise rows assume the same awareness fraction for both models. Model-specific unrestricted awareness can widen overlap. A detectable nonzero prediction need not distinguish two payoff models. Passing a conditional MDE screen does not authorize a causal conclusion, and failing it does not establish a behavioral null.

## Interpretation

This package answers how the corrected fits change transported policy predictions, and whether those predictions are large relative to the observed pre-policy noise under explicit assumptions. It does not answer whether players changed behavior at implementation or announcement. A post-policy test requires the matched cohort, source restrictions, calibration, calendar window and uncertainty work in `POST_POLICY_DEPENDENCIES.md`.
