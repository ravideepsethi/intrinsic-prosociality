# Chooser benchmark: paired wider-bound bootstrap, v1.0.0

The bound-sensitivity point estimates are stable. This package checks whether the main refit-bootstrap intervals are also stable. It refits **level, desert, cost, and both** on the same 120 development/evaluation account resamples used by the completed v1.1.2 run. It uses the fixed numerical domains of the completed 4x point fits. It does not select bounds or starts using evaluation scores.

Use the complete commands in `RUN_TERMINAL.txt`. Expected runtime: **4–8 hours at three workers**, subject to convergence and memory pressure. The terminal updates its estimate from completed draws. This is a planning estimate, not a benchmark measured on your production arrays.

## Required completed runs

- `/Volumes/XT_Pro/lichess_kindness/output/pool_chooser_followup_v112_1e5c35a1309c0258`
- `/Volumes/XT_Pro/lichess_kindness/output/pool_chooser_bounds_v100_f14e1be2f5314f2e`

Their PRIVATE directories, numeric maps, and original bootstrap checkpoints must remain available. Reports alone are insufficient. Stop other writers to these two runs before starting. This package acquires read locks and writes to a separate output directory. It verifies source identities, report checksums, producer manifests, dependency versions, and the reproduction of published point scores from private fit vectors.

## Computation and restart

- Four headline models, 120 paired draws: 480 model refits, each with multiple starts. The other six models are not refitted.
- Memory-aware automatic process count; one numerical thread per process. Processes share read-only numeric maps. It reuses the existing columnar data preparation rather than scanning or converting the original panel again.
- Aggregate tables use ZSTD Parquet, with small CSV companions. Private JSON checkpoints hold full selected vectors and optimizer attempts. Replacing 120 small checkpoint files with Parquet would not accelerate the numerical optimization.
- Fixed bound = four times each model's original point-fit bound; no automatic doubling inside a bootstrap draw. Structural parameter boundaries remain structural.
- All draws remain in the report, including capped and failed draws. Intervals require at least 100 successful paired draws. There is no interval obtained by dropping capped draws.
- Every supplied starting vector is evaluated at the target training penalty. A selected fit must be no worse than every feasible starting vector, within 1e-8.
- Re-run the identical command after interruption. Completed draws are reused; at most the unfinished draws need repeating. The old 120-draw run is preserved. Changing workers does not change the run identity; changing starts or maxiter does.

## What is held fixed

The source account arrays, chronology, original RNG seed and draw order, selected support size and penalty for each model, model definitions, index normalization, controls, analytic gradient, convergence standard, and sequential evaluation scoring are unchanged. Complexity is **not** selected again in each resample.

Starting points include the wider-domain point fit, the original point fit, three independent starts by default, and feasible compatible restrictions. Previously fitted bootstrap restrictions are used where available. Fixed wider-domain auxiliary point fits can supply additional feasible starts but are not re-estimated as auxiliary models. The original bootstrap did not save full fitted vectors, so this is a fresh wider-domain/multistart refit on identical resamples, not a continuation from every old bootstrap optimum. New checkpoints save full vectors to enable such continuations later.

## Results to inspect

`refit_bootstrap_summary.parquet` gives wider-domain point gains, refit standard errors, marginal percentile intervals, equal-account intervals, capped-pair counts, and paired changes relative to the old draw. `original_bootstrap_summary.parquet` preserves the old comparison. `refit_bootstrap_draws.parquet` contains every paired score. `refit_model_status`, `refit_optimizer_attempts`, `refit_training_checks`, and `refit_numerical_parameters` report numerical performance. Empty diagnostic tables may have an empty CSV only.

The numerical-parameter table distinguishes a raw theta cap from the reported anchored-index theta. In these separable models, reported theta = raw theta × (1 − index offset); a large raw parameter can coexist with a moderate reported slope. Stable predictions do not imply stable mixture parameters.

The bootstrap is an account-resampling sensitivity calculation with frozen complexity. Its intervals do not cover model search, prior reuse of the evaluation cohort, cross-account dependence, or simulation recovery. Percentile intervals near boundaries remain diagnostic, not a guarantee of nominal coverage. A successful run requires review of failures and remaining caps. `COMPUTATION_OK` means calculation completed, not that inference has passed review.

Upload the newly printed `POOL_CHOOSER_WIDE_BOOTSTRAP_RESULTS_v100_*.zip` and its `.sha256`. The result ZIP contains aggregate reports, not source account records or private fit checkpoints.

The bundled `reference_bounds` tree is an unchanged dependency. Run the top-level launcher; its nested launchers are retained only for provenance.
