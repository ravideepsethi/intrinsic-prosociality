# Chooser model recovery, v1.0.0

This package asks whether the fitted chooser model classes can be distinguished at the actual sample size and observed history lengths. It follows the completed wider-bound bootstrap without repeating or modifying that run.

The default is **100 independent simulations under each of three generators**: level-only, desert heterogeneity, and cost heterogeneity. All four candidate classes—level, desert, cost, and both—are fitted to each simulation. That is 300 simulated datasets and 1,200 selected model fits, with multiple optimizer starts per fit.

The generators are the authenticated 4x-bound point fits. The production run uses the full existing development and evaluation designs: 25,000 development accounts and 50,000 evaluation accounts, with the actual observed histories. It does not take a smaller recovery subsample. Counts and simulated grant totals are reported explicitly.

## Run

Put the ZIP and checksum in `~/Desktop/Lichess_Desktop`, then use the complete block in `RUN_TERMINAL.txt`. The existing Python environment is reused, and its versions must match the completed source run. No package upgrade or new installation is needed.

**Planning ETA: roughly 9–18 hours at four workers**, or 12–24 hours at three workers. This extrapolates the observed wider-bootstrap optimizer timings; independent recovery starts may behave differently. Automatic worker selection respects available RAM and uses at most ten processes with one numerical thread each. The terminal updates ETA after completed datasets. Closing other memory-intensive jobs can permit more workers; forcing ten workers on an 18 GiB machine can be slower due to memory pressure.

Completed model fits and simulation reports are signed checkpoints. Re-run the same command after interruption. An unfinished dataset reuses its completed model fits and regenerates exactly the same synthetic choices. Changing worker count preserves the run identity. Increasing `--recovery-reps` adds simulations without changing existing ones; lowering a started report's requested budget is rejected. Changing starts or maxiter creates a separate run.

Required inputs on XT_Pro:

- `pool_chooser_followup_v112_1e5c35a1309c0258`, including PRIVATE design and numeric maps.
- `pool_chooser_bounds_v100_f14e1be2f5314f2e`, including PRIVATE 4x point vectors.
- `pool_chooser_wide_bootstrap_v100_19717dce14d9dd9d`, including its report and lock file.

The program checks checksums, producer identities, dependency versions, source relationships, and reproduction of public point scores. It takes shared read locks on these runs and writes to a new `pool_chooser_recovery_v100_<identity>` directory. Do not run another writer to these sources while recovery is active.

## What is simulated

For each generator and replication, one latent type is drawn for every development and evaluation account. That type remains fixed throughout the account's history. Granting outcomes are drawn from the generating model at each observed opportunity. Development and evaluation use independent random streams; replication identities remain stable when workers or simulation budgets change.

Observed board states, stage, cost variables, controls, account-history lengths and chronology are held fixed. All evaluation outcomes, including the first-year history used to filter type probabilities, are simulated. The code fits on simulated development-year outcomes and scores simulated evaluation year two sequentially. It never filters evaluation types using their future outcomes.

This is conditional model recovery. It does not simulate opportunity arrivals, causal treatment assignment, receipt dynamics, perception, or a switching process. It does not establish that the generating model is true in the real world.

## Estimation and starts

The likelihood, analytic gradient, fixed numerical domains, selected support sizes, penalties, index normalization, controls and sequential scorer match the wider-bound analysis. The four production templates have fixed J values 5, 6, 4 and 6 for level, desert, cost and both, respectively. Complexity is **not selected again** in a simulation, so recovery assesses these selected candidates, not the entire earlier model-search procedure.

The recovery fitter receives only model specification, J, penalty, bound, synthetic development outcomes and independently fitted compatible restrictions. It never receives the generating vectors as starting values. The default six independent starts alternate across ordinary and near-additive parameter regions using a fixed generic rule. Feasible fitted restrictions from the same synthetic dataset supply additional starts where support sizes agree. Starts are selected by penalized development likelihood, never by evaluation scores.

The empirical bootstrap used observed-data point fits as warm starts; doing that here would give the optimizer the generating truth. Recovery therefore uses independent generic starts. This difference is intentional and disclosed: the objective and domains match, while initialization excludes oracle information.

Every selected result must converge and improve on all its supplied feasible starts, within 1e-8. After fitting, the true generating vector is evaluated in the training objective of its own model. A worse fitted objective is flagged as a numerical diagnostic; the truth is never used to repair that fit. Full fitted vectors and all optimizer attempts are saved privately. Neither strict caps nor near-cap fits are discarded.

## Main outputs

All nonempty aggregate tables are ZSTD Parquet with small CSV companions. Numerical work reuses existing shared memory-mapped arrays; it does not reread the original game panel or convert numerical arrays to Parquet on every simulation. Small JSON checkpoints retain full fitted vectors and allow exact restart.

| File stem | Purpose |
|---|---|
| `recovery_selection_summary` | Frequency each class has the best score; frequency desert beats both alternatives or reaches both observed margins; Wilson Monte Carlo intervals |
| `recovery_comparison_summary` | Pairwise gain distributions and frequencies, under opportunity and equal-account weighting |
| `recovery_comparisons` | Every simulation's six paired comparisons |
| `recovery_events` | Actual account/opportunity counts and simulated/expected grants |
| `recovery_fits` | Forecast recovery, known-model score gap, parameter errors, and caps |
| `recovery_outcomes` | Per-dataset winner, joint headline criteria, and truth-objective diagnostic |
| `recovery_model_status` | Convergence and strict/near-cap counts by generator and fitted class |
| `recovery_parameter_draws` | Matched latent parameters, only for the correctly specified generating class |
| `recovery_by_board` | Calibration and scores by board band |
| `recovery_optimizer_attempts` | Every start's convergence, objective, time and bound status |
| `recovery_training_checks` | Feasible-start objective guards |

The known-model forecast uses the generating population distribution filtered on simulated past choices. It does not pretend that the analyst observes each account's true type. Its forecast-probability RMSE and conditional Bernoulli KL divergence provide prediction-recovery diagnostics in addition to winner counts.

## Interpretation

The central question under level and cost generators is whether desert produces gains as large as the real-data gains: approximately 0.000766 per opportunity against level and 0.000902 against cost. The program records those paired exceedances and their joint occurrence. Under desert generation, it measures discrimination power and parameter recovery. All thresholds are copied from the authenticated point comparison before simulations run.

Winning by a tiny score difference is not equivalent to a false scientific conclusion. Winner frequency is **not** the rejection rate of the real bootstrap confidence interval: the program does not run a nested bootstrap inside every simulated dataset. Observed-margin exceedance frequencies are conditional on particular fitted generators, not composite-null p-values. They do not account for uncertainty in the generating parameters or redo empirical tuning selection.

With 100 replications per generator, zero observed occurrences still has an upper 95% Wilson limit of about 3.7%; do not report a zero error probability. The standard error of an estimated simulation probability can be as large as five percentage points. The reported 2.5th/97.5th percentiles describe the simulated gain distribution and are withheld below 100 completed pairs; they are not confidence intervals for the real-data effect. Denominators exclude failed fits only where a score is unavailable, with failures separately reported. Capped successful fits stay in every applicable comparison.

Inspect `RECOVERY_STATUS.json` for failures and fitted training objectives worse than the feasible generating truth before interpreting selection frequencies. Large parameter errors with small forecast errors indicate that prediction is better determined than the mixture's latent parameters. More numerical caps or unstable estimates should not be interpreted as recovered psychological types.

After `COMPUTATION_OK`, upload the newly printed `POOL_CHOOSER_RECOVERY_RESULTS_v100_*.zip` and matching `.sha256`. The archive contains aggregate reports; private account arrays and full fit vectors remain on your drive.

The nested `reference_wide` package is unchanged and retained for numerical provenance. Use only the top-level recovery launcher for this exercise.
