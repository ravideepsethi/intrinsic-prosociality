# Pooled competitive-position curves, v1.0.0

This is runnable analysis code, not a new set of empirical results. It pools competitive positions and estimates kindness against (1) the opponent-minus-chooser rating gap and (2) the chooser's rating payoff from a draw. Each model absorbs a separate intercept for every chooser–broad-board-state pair. Standard errors cluster by chooser across all three board states.

## Run on your Mac

Save `Pool_Pooled_Competitive_K_v1_0_0.zip` and its `.zip.sha256` beside each other in `~/Desktop/Lichess_Desktop`, then paste the complete command in `RUN_TERMINAL.txt` into Terminal. The project default is `/Volumes/XT_Pro/lichess_kindness`. Ten workers, two checksum workers, and a 6 GB DuckDB memory budget are used. Each estimator worker uses one BLAS thread.

The wrapper reuses a compatible existing Python environment, including the previous within-chooser K environment. Otherwise it installs the listed packages into a separate environment. Dependencies can require internet access; the analysis makes no API requests.

The source sample is authenticated against its frozen authority and all monthly Parquet hashes. A successfully completed, matching previous within-chooser K run can supply the sorted base cache. The old report manifest and the cache SHA-256 are verified before reuse. If there is no suitable cache, the runner builds a new sorted slim copy from the source. Allow space for several GB of new private intermediates; a fresh sorted copy requires additional space. A corrupted matching cache stops with an error; use `--no-reuse-previous-cache` to build afresh after checking the error.

Runtime is hardware and disk dependent. The earlier run took approximately 5.2 minutes on your machine. Budget roughly 10–20 minutes for this version, with more time if it must build the sorted base or install dependencies. This is an estimate, not a benchmark of the new full-sample run.

## Outputs

The terminal prints `POOL_POOLED_COMPETITIVE_K_OK` when all checks, estimation, figures, and packaging complete. It places these two files directly in `~/Desktop/Lichess_Desktop`:

- `POOL_POOLED_COMPETITIVE_K_RESULTS_v100_<run-id>.zip`
- the matching `.zip.sha256`

Upload those two files for interpretation. The report includes:

- `figures/pooled_main.pdf` and `.png`: the main two-panel pooled comparison, raw and adjusted. The rating-gap display focuses on −200 to +200 rating points; all observations remain in estimation.
- `figures/pooled_full_range.*`: the complete supported rating-gap display.
- `figures/pooled_specification_ladder.*`: controls, K20, and K50 comparisons.
- `figures/board_state_interactions.*`: separate curves within the pooled interaction model.
- `HETEROGENEITY_TESTS.json` and `.csv`: joint tests of whether the normalized curves differ across the three competitive board states.
- `shape_contrasts.csv`: left-tail-versus-shoulder and other fixed contrasts, including clustered SEs and exploratory multiplicity corrections.
- `curves.csv`, `curve_covariances.npz`, `SAMPLE_COUNTS.json`, `MODEL_DIAGNOSTICS.json`, `RESULTS.md`, and sample/cache/code provenance.

Private row-level caches remain under `/Volumes/XT_Pro/lichess_kindness/output/pool_pooled_competitive_k_v100/<run-id>/PRIVATE`. The result archive contains aggregate counts, moments, estimates, and executed code; it does not contain account/game identifiers or row-level data. It can contain your local filesystem paths in provenance.

Rerunning the same package with unchanged dependencies, options, and source resumes hash-verified shard checkpoints. A new package, environment, worker count, or batch setting gets a distinct run identity. Original panel and prior cache files are only read.

## Interpretation

The main curve assumes a common conditional rating-gap or payoff response across competitive board states; the interacted model checks that assumption. It is estimated jointly, not constructed by averaging the earlier curves. A statistically insignificant interaction test does not establish equivalence. An upturn in the pooled curve is a conditional association, not a causal price effect. Read `METHODS.md` before using estimates in the paper.

The supplied synthetic tests compare fixed-effect estimates and chooser-clustered covariance matrices with independent full dummy regressions. They also check raw uncertainty, singleton handling, preservation of never-granters, streamed/sharded account histories, and cross-state covariance in the joint test.
