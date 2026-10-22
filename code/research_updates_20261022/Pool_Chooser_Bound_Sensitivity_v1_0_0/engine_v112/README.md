# Chooser benchmark follow-up 1.1.2

This is the performance update to v1.1.1. It keeps the same models, data,
optimizer starts, penalties, stopping rules, bootstrap draws and inference
requirements. It adds a compiled static objective, persistent Mac-compatible
worker processes, read-only memory-mapped arrays, compressed Parquet report
tables and live ETAs. See `PERFORMANCE.md` for measured speed and its limits.

On synthetic data, individual static full fits ran roughly 3–5 times faster at the
same worker count. A planning ETA for repair plus 120 bootstrap refits is
**4–8 hours with 8–10 available workers, or 8–14 hours with four**. These ranges
combine the earlier Mac timings with synthetic measurements here; they are not
a production measurement. The log replaces its initial estimate with observed
replication times. First-use compilation/cache creation adds startup time.

**Repair the full-year fits before bootstrapping them.** It reuses the completed v1.0.0 design and model selections, audits provenance and boundaries, and retains independent full-year starts and cross-starts from nested models. The same safeguard applies to every bootstrap and recovery refit.

The uploaded expanded-grid run exposed the reason: at J=6 and ridge=1e-6, the best full-year desert objective is 0.498777586 and the best both objective is 0.498891771 (smaller is better). The desert parameter vector is feasible in both with exactly the same penalty. The latter fit therefore missed a known better feasible solution despite passing its local gradient check. The previous code's nested starts occurred during validation only. This patch corrects that orchestration gap; it does not promise a global optimum.

It does not recompute the 41-million-row source panel. The default parent is:

`/Volumes/XT_Pro/lichess_kindness/output/pool_chooser_benchmark_v100_d6c2a5c0637024f1`

The parent's `PRIVATE/design`, `PRIVATE/core/SELECTED_FITS.json`, configuration and report must still exist on the drive. The small returned report ZIP alone cannot reproduce the private data. The parent is read only; this package writes a separate `pool_chooser_followup_v112_*` output directory. Supply `--parent-run` if you moved the parent directory. It does not import v1.1.1 fit/draw caches: arithmetic order changed, so v1.1.2 gets its own identified output. If v1.1.1 has already completed substantial work, keep those results and do not start both versions concurrently.

## Run order

Use the complete commands in `RUN_TERMINAL.txt`. The default `--workers auto` chooses up to ten workers from CPU count and estimated available RAM, with one numerical thread per worker. `--workers 4` supplies a lower cap when sharing the Mac with another heavy job. Worker planning is a conservative capacity calculation, not a measured optimum. The plan is saved as `WORKER_PLAN.json`. Stages can be resumed; budgets can be increased without changing completed draws. Do not run two stages of the same configuration at once.

1. `audit,repair,repair-bootstrap`: verify the producer code, fingerprint, cache hashes and public-score reproduction; audit boundaries; repair the full-year fits at the already selected J/ridge; run 120 paired account refits with the same nested-start safeguard. No complexity search is repeated. `repair-recovery` then runs full-design recovery.
2. `challenge`: search support sizes 1–6 and penalties 1e-6, 1e-4, .001, .01 for the four NEW restrictions `board_only`, `no_stage`, `no_expected`, and `desert_no_cost`. The ten old model selections are inherited from repair/. All receive the final-year nesting safeguard before scoring together. Then run `challenge-bootstrap,challenge-recovery`. The completed ten-model expanded grid is not rerun.
3. `switching`: estimate the static desert model, four independent-state alternatives and four Markov-state alternatives on those same observations. Then run `switching-bootstrap,switching-recovery`.
4. Optional `perception,perception-bootstrap,perception-recovery`: retain the earlier exact bin-integration exercise on its matched numeric-score sample. This is separate from the main static/dynamic comparison.

Only audit, repair and its bootstrap run by default. New grids, refits and full-design recovery are substantial jobs; each exports aggregate results and logs progress. A recovery replication uses the full observed development and evaluation histories, not a 1,500-account shortcut. The default is 20 replications per generating scenario; raise `--recovery-reps` after checking event counts and failures.

Every fit uses several optimizer starts, analytic derivatives and a projected-gradient convergence requirement. Restricted starts are passed to relaxations during validation AND full-year fitting, and in resamples. A repaired/resampled result is withheld if it is worse than a supplied feasible start at the target penalty. Training-bound hits trigger a wider-bound fit. A successful run is **computed, requires diagnostic review**, not a result certified for publication.

## What changed in the interpretation

The first run supports a predictive advantage for heterogeneous state responsiveness among the fitted classes. Its conditional SE does not include population refitting. The bootstrap addresses that uncertainty while fixing the chosen complexity, support and transformations. It does not include model-search uncertainty, arbitrary calendar dependence, or the fact that this evaluation cohort has already been examined.

The zero loss coefficient claim was too broad: both, free-index, type-cell and separate-cost specifications include nonzero loss coefficients in the expanded run. The weak predictive role of costs is an empirical finding about these fitted specifications, not proof of identical rating valuations or absence of an economic price response; comparisons involving both need the optimization repair.

The new largest desert component is 84.5%, with slope 1.14. Another 6.7% has a higher level and a lower slope (.40). The previous three-component ordering does not persist. These are mixture weights, not observed account classifications, and remain conditional on unrepaired estimates. The matched switching exercise tests a flat lower emission as a restriction; it does not import that description from the old competitive-dummy fit.

Worse held-out prediction by free cells or type-specific surfaces does not accept separability or a common population surface. It can reflect estimation variance or regularization. Recovery, support and the expanded penalty/support grid are necessary diagnostics. The fitted stage/expected-score surface is not itself a test rejecting a board-only fairness ideal: the new explicit restrictions provide that comparison. There are **63 supported cells** in the supplied production design, not forty.

## Outputs

The top-level report contains `BOUNDARY_AUDIT.json`, raw-versus-reported parameter tables, public-score reproduction and lineage. Each computed suite has:

- `final_nesting_audit.csv`, `REPAIR_STATUS.json`, `repair_optimizer_attempts.csv`: initial objectives, every supplied feasible starting objective, the selected repaired objective, convergence and remaining bounds. Score changes are selected using first-year objective only.
- `comparisons.csv`: sequential held-out score differences, account-clustered conditional SEs, and Holm correction within the table.
- `complexity_selection.csv`, `SEARCH_DIAGNOSTICS.json`, `optimizer_attempts.csv`: first-year choice, search-edge selections and numerical convergence.
- `refit_bootstrap_summary.csv`: opportunity-weighted and equal-account percentile intervals after at least 100 successful paired draws; failed fits and numerical bounds are separately counted.
- `refit_parameter_draws.csv`: population parameters matched to the original component labels by intercept and state surface. Labels are not observed account types; near-coincident components can still match unstably. For tier priors, `share` is the unweighted mean across tier priors.
- `recovery_results.csv`, `recovery_winners.csv`: full-design simulated event counts, matched parameter errors and model rankings; incomplete replications do not get a winner.
- `types.csv`, `state_surfaces.csv`, `scores.csv`, `calibration.csv`: fitted parameters, supported surfaces, state-specific scores and calibration.
- Switching also exports `state_dynamics.csv`. Its entry/retention probabilities are **per retained opportunity**, not receipt effects.

Results ZIPs and SHA256 files appear in `~/Desktop/Lichess_Desktop`, prefixed `POOL_CHOOSER_FOLLOWUP_RESULTS_v112_`. Aggregate tables written by the follow-up have `.parquet` companions with ZSTD compression and 65,536-row groups; CSV remains for reading and compatibility. The original upstream Parquet panel is never scanned again. The optimizer reads numeric memory maps rather than decoding Parquet or NPZ inside each fit. Only aggregate reports are exported; account data and optimizer caches stay in `PRIVATE/` on the drive. Upload each results ZIP together with its checksum.

## Boundary flags

The optimizer uses raw product-index coordinates. For the separable index,

`reported_theta = raw_theta * (1 - f0)`

`reported_alpha = raw_alpha + raw_theta * f0`.

A raw theta at 12 can therefore correspond to a much smaller reported theta. The audit distinguishes validation attempts from final first-year fits and distinguishes numerical caps from admissible zeros. Unlike the earlier three-type run, the expanded run has flags in final-year attempts and four wider-bound attempts. Widening does not establish optimization quality: the decisive diagnostic is the feasible objective comparison. The private audit reports the selected flags directly.

## Scope of the new switching models

See `METHODS.md` for the likelihood, nesting and interpretation limits. Every family shares the same index functional form, controls, cost regressors and training/evaluation sequences. Each estimates its own population/index parameters; "same emissions" means matched functional form and restrictions, not frozen point estimates from another model.

The imported cache has no receipt covariate. This release does not re-estimate the old receipt transition effects. It also does not construct disconnections from `outoftime`, infer a voluntary share without a verified indicator and player-time exposure, or claim to identify reciprocity from a cell-constant proxy.

`base/` is the unchanged archived v1.0.0 producer. Its README documents that old release, not this release's capabilities. Do not use its launcher for the follow-up.
