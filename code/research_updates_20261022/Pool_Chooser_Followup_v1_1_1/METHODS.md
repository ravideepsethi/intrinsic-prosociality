# Specifications and inference

## Full-year optimization repair in v1.1.1

The expanded-grid archive contains a direct nesting violation: both and desert select J=6 and ridge=1e-6, yet the best both full-year objective is higher. The penalty is the mean squared identified state effects, actual cost coefficients and shared controls; repeating a common cost coefficient across types leaves it unchanged. Therefore a desert vector embeds in both with the same penalized objective. The narrower bound-12 desert fit also beats both, so this cannot be attributed to the final wider-bound domain.

The correction freezes the selected complexity, retains the original fit as a candidate, supplies independent starts, and then supplies every available compatible nested fit in dependency order. It evaluates each starting vector at the target model's penalty before optimization. The selected converged result must be no worse than the best supplied feasible start, allowing numerical tolerance 1e-8 in the per-account penalized objective. This is stronger than checking gradient convergence but remains a finite-start optimization diagnostic, not a global optimum proof.

Cross-starts require equal support size; source and target penalties need not match because the start is evaluated at the target penalty. Bounds expand to accommodate source vectors where possible; any transfer/clipping is reflected in the explicit feasible-start objective, rather than assuming an exact embedding. For new static restrictions, the old ten complexity selections are inherited from the repaired parent. Only the four new restrictions receive a new grid search. Bootstrap and recovery also fit restrictions before relaxations and use all compatible cross-starts in addition to their independent starts.

## Static restrictions

The unchanged static index is

\[
A_{bpE}=\frac{f_b g_p h_E-f_0}{1-f_0},
\]

with the reference stage and expected-score factors fixed at one, the board reference factor fixed at one, and two cell anchors fixing the affine index scale. This is the same freely estimated graded index as the returned benchmark, including its normalization. Board/stage/expected-score cell effects are not duplicated in controls.

`board_only` fixes every g and h factor at one. `no_stage` fixes g; `no_expected` fixes h. Each uses the desert-heterogeneity family (heterogeneous intercept and index intensity, common cost). `desert_no_cost` removes both cost terms in that same family. They are compared directly with `desert`, with model complexity selected on the same first-year split. The earlier `both` versus `no_cost` comparison is retained as a separate contrast.

Differences in held-out risk test the usefulness of fitted estimators. They are not likelihood-ratio tests accepting a population null. Increasing flexibility can hurt predictive risk under either a true or false restriction. Common component count is not equal parameter count, so both counts and validation scores are reported. A winning finite mixture is not evidence for literal population atoms or bimodality.

## Persistent types and two states

Let k be the account's persistent type. With c the two explicit cost regressors, the upper-state utility is

\[
U_{1,itk}=\alpha_k+\theta_k A(s_{it})-B'c_{it}+z'_{it}\eta.
\]

Costs B are common across persistent types in all matched dynamic families, as in the static desert specification. The lower-state intercept is alpha_k minus a common nonnegative gap d. Shared controls enter both states. Lower-state restrictions are:

| Family | Index slope | Cost coefficients |
|---|---|---|
| willingness | theta_k, same as upper | B, same as upper |
| gate | zero | zero |
| gatecost | zero | freely estimated common nonnegative pair B0 |
| unrestricted | freely estimated nonnegative theta0_k | freely estimated common nonnegative pair B0 |

The gate is flat in A and the explicit rating-cost regressors **conditional on z**. Shared controls include variables related to ratings and clocks, so it is not a statement of unconditional state or rating insensitivity. The sign restrictions and common gap are restrictions even in the model named `unrestricted`.

The gap orders intercepts at the anchor and reference covariates. State probabilities can cross elsewhere. The label "upper" is not a guarantee that granting is higher in every cell; no state is interpreted as observed moral recognition. Initial upper-state probability q and, in the Markov model, p01 and p11 are common population parameters. They are estimated jointly with persistent type probabilities and emissions.

For the independent-state model, states are drawn independently at every retained opportunity with probability q. Persistent type remains fixed. In its Markov counterpart the state follows the 2x2 transition matrix. Both transitions are constant per retained opportunity: they are not elapsed-time hazards, do not account for omitted opportunities between supported cells, and contain no receipt effect. Static versus switching can therefore reveal serial predictability in this restricted model; it cannot by itself establish construal or rule out omitted time-varying covariates.

The independent-state comparison matters: mixing two logits can improve fit without any state persistence. Markov versus its matched independent-state version tests whether conditioning on the previous latent state helps beyond that emission mixture, under the specified persistent-type distribution. Equal transition rows and q recover independent draws. Zero gap in willingness recovers the static desert model exactly. The unrestricted model also embeds it by equating state slopes and costs. The gate can approach a static upper state as its upper-state probability tends to one; no exact finite-logit nesting is claimed.

For an account, the likelihood sums over type once, and over state paths conditional on type. Numerical evaluation uses a log-domain forward/backward recursion. Evaluation forecasts use the joint type/state posterior **before** the current response, then update with that response for the next opportunity. Year-one history filters evaluation accounts without re-estimating population parameters on those accounts. No smoothed full-history state is used to predict its own past.

Analytic gradients include state occupancy, transition counts, persistent-type posteriors and the index's normalization. The penalty is one half the ridge coefficient times the mean squared state-cell effects across both states, the mean squared cost coefficients across both states, and the squared shared controls. It reduces to the original static penalty when both emissions coincide. It imposes no transition/intercept penalty. All restrictions use the same rule and validation grid; intercept gap, transition logits and mixture priors have explicit numerical bounds. Nested starts are additional starts, not selected fits by assumption.

## Refit bootstrap

Development and evaluation accounts are sampled independently with replacement. Each account keeps its complete chronological sequence. Every compared model in a replication uses the same account weights. Fitted population/index/state parameters are re-estimated on the weighted full first year, then the complete evaluation sequence is filtered again. Per-opportunity gains and equal-account gains use the resampled evaluation weights.

The repair suite fixes the already selected expanded-grid v100 complexity. Other suites fix inherited or newly selected first-year complexity as recorded. Cell support, preprocessing, external calibration if present, and the selected model grids are not reselected in the bootstrap. These intervals therefore exclude model-search, support-selection and cross-account/calendar dependence. They are not fresh confirmation after the evaluation outcomes have been inspected.

At least 100 converged paired draws are required to publish percentile endpoints; request 120 initially, inspect failures, and increase the budget if needed. Draws with failed optimizers are not silently treated as zero effects. Boundary draws are flagged. Component matching uses intercepts and upper-state surfaces; instability of nearly coincident components can remain. Percentile intervals for nonregular mixture parameters, zero costs and collapsed states require special caution; recovery is an empirical diagnostic, not a general coverage proof.

## Recovery

Choices are simulated on the full frozen observed designs and history lengths, separately for development and evaluation accounts. Covariates and arrival histories are treated as fixed. The static suite uses fitted level/desert/cost/both/type-cell generators plus zero-cost and nearly collapsed scenarios. The switching suite uses fitted static, independent unrestricted, Markov willingness, gate and unrestricted generators. Recovery starts do not use the true generating vector. Model complexity remains fixed, so this assesses estimation/model discrimination conditional on the selected complexity, not recovery of the whole selection algorithm.

Inspect grants, failures, matched slopes/costs and, for switching generators, lower slopes and transition probabilities. The number of recovery replications determines Monte Carlo precision; 20 is a useful initial diagnostic, not precise evidence on rare classification errors or nominal interval coverage. Sparse events remain sparse even when account counts are large.

## Perception and Jensen

The optional existing extension integrates the logistic response exactly over probabilities of perceived evaluation bins. Noise in board evaluation generally changes the *mean index* as well as its dispersion. The fixed-type decomposition reports both the curvature component and the change in the mean index. It does not impose that noise raises granting everywhere.

For mean-preserving utility noise wholly in the negative-index region, logistic convexity gives a positive Jensen effect. It is not generally largest at the most negative utilities: logistic curvature tends to zero in the far left tail, is zero at probability one half, and changes sign beyond it. Mean-zero board error need not be mean-preserving utility error. Tests therefore compare estimated noisy and accurate probabilities at fixed type and covariates and report the decomposition, rather than imposing the proposed ranking by rarity. A good fit does not validate the exclusion separating perception from unobserved preferences.

## Causal and theoretical limits

These are interpretable structural restrictions on observed granting and its persistence. They do not identify a moral motive, preferences over rating separately from shock scale, attention as a distinct psychological process, or a causal effect of receipt. A lack of predictive gain is not proof that a channel is absent. A cell-level blame proxy is absorbed by a free cell surface; the chooser design supplies no separately identified test of reciprocity. Verified disconnection indicators, exposure-time denominators and latency timestamps remain separate data requirements.
