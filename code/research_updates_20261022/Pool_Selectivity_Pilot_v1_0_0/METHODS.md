# Statistical design and boundaries

## Population and split

The input is the authenticated pool / observed-nonadjacent panel, fingerprint a17c89d750cb4fdfdf84f950859e45c58b19996efae02045def68285e305cf30. Its operational filter is source='pool' and previous_classification_status='not_mutually_adjacent_observed'. This does not certify literal immediate-rematch timing, random opponent assignment, or absence of earlier relationships. The outcome is the certified `outcome_kind_draw` indicator, without redefining rows.

The census uses all 41,534,331 observations. The pilot includes cp>=-100 or cp<=-300 from the disconnected player's perspective; -299 through -101 are excluded from this two-region contrast. First-year training is November 2023–October 2024. Second-year testing is November 2024–October 2025. Pilot accounts are selected by ordering MD5(account_id + ':' + fixed seed), among accounts with at least one first-year modeled opportunity, capped at 100,000. Whole histories are preserved. Selecting accounts with second-year activity is prohibited; lack of second-year activity is recorded in the census. Prediction metrics condition on observed year-two opportunities.

## Model

For row j belonging to account i and component k,

V_ijk = alpha_k + theta_k F_ij + X_ij beta,

where F=1 for competitive states and 0 for clearly-worse states. K=3 is fixed for both models. The level-only model constrains all theta_k equal. The selectivity model frees them. Mixture probabilities are common across accounts, and the model is conditional on observed opportunity sequences. Correlation of account type with exposure composition and temporary serial dependence remain interpretation risks.

X contains common effects for the original five-board/eight-stage cells (middle-board cells absent in the fitted sample), with clearly-worse and roughly-equal at plies 21–40 omitted. Their baseline indices are alpha_k and alpha_k+theta_k. It also contains training-observed categorical indicators for speed, month-of-year, color, displayed rating gap, chooser rating, both RDs, rating premium, draw-loss magnitude, both clocks, and both volatilities. Bin boundaries are fixed in prepare.py. The two baseline state cells must be present in training; otherwise fitting stops.

A common category is omitted for each other categorical control. A year-two category absent from training receives zero common coefficient, with the number of affected opportunities explicitly reported. No year-two outcome is used to fit a calendar effect or intercept. Seasonality is month of year, not an unknowable future calendar-month fixed effect.

Repeated observations with identical account, period, and model covariates are represented as binomial counts. This is exact for the specified model. The account likelihood sums over the latent component **outside** the product of that account's observation likelihoods. Binomial combinatorial constants are omitted; they are parameter-independent and cancel in comparisons.

Three starting values per model maximize the account marginal likelihood using an analytic gradient and bounded L-BFGS-B. Selectivity starts are initialized near the fitted level-only model. The selected restart minimizes the training objective among converged attempts; if none converge, diagnostic outputs are written with an explicit warning. A tiny common L2 penalty (1e-6 times beta'beta/2 on the per-account average objective) stabilizes nuisance coefficients and is identical across models. Bounds and near-empty component warnings are reported; these are numerical restrictions, not estimated preference constraints. The package does not report chi-square likelihood-ratio p-values for this nonregular mixture problem or class labels as psychological categories.

## Forecasts and uncertainty

Account type posteriors use first-year outcomes only. Second-year marginal probabilities keep those posteriors fixed. Main scores are log loss and Brier score, overall and by board region. Paired gains have opportunity-weighted and equal-observed-account versions. Their standard errors cluster over accounts **conditional on the estimated models**, so they do not cover estimation, tuning, or specification-search uncertainty. A supplementary joint held-out sequence score integrates each fixed account type once over the entire second-year history; no per-opportunity redrawing of type occurs.

The simple benchmark fits beta-binomial priors using first-year account counts separately in 2 board regions × 3 stage bands (<=10, 11–40, >40 plies). It predicts from smoothed account-cell rates, giving finite probabilities to all-zero histories and prior predictions where an account has no first-year observations in a cell. Prior parameters do not see year two. This is a deliberately useful benchmark rather than unsmoothed rates that predict impossible zeros.

## What this run does not identify

- A free common warrant surface W, its invariance, or a joint distribution of deep preference primitives.
- Whether selectivity arises from fairness, attention, beliefs, perception, or other behavioral channels.
- Independent latent psychological dimensions, true never-granters, or a causal own-grant effect.
- Causal receipt dynamics, opportunity-arrival effects, cumulative-grant effects, or policy counterfactuals.
- Patron associations. Private first-year posteriors are retained for a later properly authenticated, sampling-aware Patron join.

This is the first feasibility/prediction run. If results warrant a full structural exercise, the next steps are exposure-correlated heterogeneity, parameter-recovery and misspecification experiments on actual histories, stronger benchmarks, full nuisance/specification sensitivity, and explicit Patron incremental-prediction comparisons.

## Sources used for implementation

- The sample authentication helper, authority, and report are carried over byte-for-byte from the previously delivered Pool_Rating_Milestones_v1_0_0 package. CODE_PROVENANCE.json records their hashes. They authenticate the existing main sample; no old scientific estimates are imported.
- Panel-mixture likelihood: Kenneth Train, Discrete Choice Methods with Simulation, 2nd ed., Chapter 6: https://eml.berkeley.edu/books/choice2nd/Ch06_p134-150.pdf
- SciPy L-BFGS-B stopping conventions: https://docs.scipy.org/doc/scipy/reference/optimize.minimize-lbfgsb.html
