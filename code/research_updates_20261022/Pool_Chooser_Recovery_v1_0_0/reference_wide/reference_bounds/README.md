# Chooser numerical-bound sensitivity 1.0.0

This is a separate sensitivity run for the completed v1.1.2 bootstrap. It reads the authenticated cached design and fitted vectors; it never rescans the 41.5-million-row source panel, changes the completed follow-up, or overwrites its bootstrap draws.

Default stages:

1. Audit all saved bootstrap signatures and report cap counts by model, pair, and draw.
2. Refit the ten point-estimate specifications at their existing numerical bounds (`polish`), twice the source bounds, and four times the source bounds. The first step controls for additional optimization at existing bounds. Each step uses a previous-fit start, three independent starts by default, compatible nested-model starts, and an additional original-fit start in the wider steps. It checks that the selected converged fit is no worse than every supplied feasible start at the target penalty.

All starts are selected by first-year penalized likelihood. No model, numerical bound, or start is selected by evaluation score. Support sizes, penalties, controls, histories, and model specifications remain fixed. The same cold-start seeds are used across bound steps. Each model's target is exactly its source bound times 1, 2, or 4. Compatible-source starts are projected into that model's domain if necessary; the safeguard compares their objective after transfer at the target penalty, not a source objective from a different domain. Every numerical coordinate governed by the original bound parameter expands, including raw theta, intercept, mixture-logit, and index-factor caps; admissible economic zeros remain admissible. Reported theta need not equal raw theta.

The unchanged v1.1.2 code is bundled under `engine_v112/`. Its compiled objective, likelihood, gradients, stopping rules, and data transformations remain unchanged. This package does not add a new substantive model or claim that cap hits are fitting failures. Numerical convergence does not establish a global optimum.

## Run and ETA

Put this folder in `~/Desktop/Lichess_Desktop`, alongside the existing v1.1.2 folder. Use `RUN_TERMINAL.txt` for complete commands. Default source:

`/Volumes/XT_Pro/lichess_kindness/output/pool_chooser_followup_v112_1e5c35a1309c0258`

The source must have completed repair and its bootstrap. Keep its private cache. The original package files alone or the small results ZIP cannot replace that private data. This script uses the existing chooser Python environment and refuses dependency-version changes relative to the source; it does not install or upgrade anything.

Planning ETA: **15–30 minutes with three workers**, based on the production v1.1.2 repair timings, with potentially longer optimization after widening bounds. `--workers auto` chooses up to ten processes within a conservative memory budget. Each process has one numerical thread. Independent starts run in parallel, using the source's authenticated read-only numeric memory maps. Aggregate tables are ZSTD Parquet plus CSV companions. Cached attempts resume without recomputation; changing worker count preserves run identity.

The source lock is held in shared mode; the output gets its own exclusive lock. Do not run this while the source follow-up is writing another stage. The sensitivity writes a new `pool_chooser_bounds_v100_*` directory on the external drive. It exports only aggregate reports to the Desktop as `POOL_CHOOSER_BOUND_SENSITIVITY_RESULTS_v100_*.zip` plus SHA-256.

## How to read it

- `bootstrap_caps_by_model`: confirms the supplied 33 desert, 25 level, 18 cost, 5 both, 29 no-cost, 32 premium-only, 3 separate-cost, 5 signed-cost, and zero free-index/type-cell cap counts.
- `bootstrap_caps_by_pair`: gives the overlap and successful counts needed for the primary contrasts. No capped draw is deleted.
- `point_fit_changes`: first-year objectives and held-out changes for each bound step, including remaining numerical flags.
- `point_model_comparisons`: the original, polished, 2x, and 4x point-estimate comparisons together. Its SEs remain conditional on population fits.
- `point_numerical_parameters`: names and raw values of every remaining selected numerical cap, with the reported theta and index offset where applicable.
- `point_training_checks` and `point_optimizer_attempts`: feasible-start safeguards, convergence, and timing.
- `original/`, `polish/`, `bounds_x2/`, `bounds_x4/`: full aggregate score, surface, type, and calibration tables.

Review both optimization sensitivity (original versus polish) and bound sensitivity (polish versus wider steps). Stability would strengthen the numerical case; continued movement or persistent caps requires further investigation, potentially a better parameterization. Repeated cap expansion alone is not proof of identification.

**This package does not re-estimate the bootstrap.** The old draw caches contain scores and parameter summaries, not the complete optimizer vectors. Reusing their exact resample IDs in a subsequent wider-bound bootstrap is possible, but affected optimizer vectors must be reconstructed. Do not attach the old bootstrap intervals to changed point estimates. A uniform paired bootstrap under the wider numerical procedure may be needed after this diagnostic; dropping capped draws is not a valid substitute. Recovery comes after the numerical procedure is settled.

The evaluation accounts were already inspected. These are follow-up sensitivities, not an untouched confirmation. No causal interpretation of cost, literal latent-group interpretation, or observed-construal interpretation follows from a predictive ranking.
