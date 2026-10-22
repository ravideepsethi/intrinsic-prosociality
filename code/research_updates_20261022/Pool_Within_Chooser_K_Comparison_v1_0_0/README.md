# Within-chooser rating-gap and payoff comparison

This package extends the current kindness-surface analysis with chooser fixed effects and clustered uncertainty. It provides **code to run on your Mac**, not newly estimated paper results.

## Run

Put the package ZIP and its `.zip.sha256` file in `~/Desktop/Lichess_Desktop`. Run the full command in `RUN_TERMINAL.txt` supplied alongside the ZIP. The launcher defaults to:

- Input project: `/Volumes/XT_Pro/lichess_kindness`.
- Frozen main panel: `derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE`.
- Transfer/results ZIPs: `~/Desktop/Lichess_Desktop`.
- Up to 10 workers: up to eight context-estimation workers, and ten threads during staging. Each estimation worker uses one BLAS thread.
- DuckDB staging memory limit: 6 GB; disk spilling is enabled. Estimation has additional per-worker memory use and runs after staging.

The launcher uses a compatible active Python environment when available, or creates a separate environment under the Desktop transfer folder and installs the listed dependencies. It runs the included synthetic numerical tests before scanning the real panel.

Allow roughly **20–60 minutes** on a Mac with a fast external SSD, but this is an unbenchmarked production estimate. Sorting and external-drive speed can make it longer. A development check processed 97,604 synthetic rows through all six adjusted estimators' moment and cluster-score passes in about two seconds, excluding sorting, source authentication and plotting; that is not a timing guarantee for your data or machine. Allow approximately 15–25 GB of free external-drive space for private caches and sort spill. Actual usage depends on compression and account distribution.

If memory is tight, use `LICHESS_K_WORKERS=4` and `LICHESS_K_MEMORY=3GB` in the command. That change produces a distinct run identity. For an interrupted job, rerun with the same settings to reuse verified checkpoints. No source panel is edited.

## What comes back

For the five paper board-state bands and the three narrow slices already discussed, the runner estimates rating-gap and draw-payoff curves with:

1. Raw rates on the common repeated-choice sample.
2. Chooser FE plus ply, both players' RD/volatility, month, speed and fine board-evaluation controls.
3. The same plus K20 conditioning.
4. The same plus K50 conditioning.

K is twice the win premium. K20/K50 use pooled quantile cutpoints (ties collapse) plus log K. These are additive controls, not exact same-K matches. Curves show percentage-point differences from a near-zero reference bin, with chooser-clustered intervals. The reference is [-25,+25) rating gap or [-0.4,+0.4) draw payoff. Full definitions, estimators and limitations are in `METHODS.md`.

The finished ZIP and checksum are written to the Desktop folder:

`POOL_WITHIN_CHOOSER_K_COMPARISON_RESULTS_v100_<run-id>.zip`

Upload those two files for review. The report includes:

- `curves.csv`: estimates, clustered SEs, confidence intervals, raw rates and bin/account support.
- `shape_contrasts.csv`: exploratory tests of the left and right upturns; Holm correction for the primary 64-comparison family.
- `K_bin_support.csv`: actual bin widths and counts after ties collapse.
- `MODEL_DIAGNOSTICS.json`: ranks, normalization/estimability checks and attrition.
- `figures/comparison_roughly_equal.pdf` and `.png`: a useful starting point for the talk.
- `figures/comparison_narrow_equal.pdf` and `.png`: the exact narrow board range in the prior surface discussion.
- Corresponding figures for the other board states and `ladder_*` figures showing all specifications.
- Per-context covariance matrices and aggregate sufficient statistics, plus manifests and lineage.

The public results exclude account identifiers. The separate `PRIVATE` cache stays on the external drive. The code does not access the Lichess API or rerun Stockfish.

## Technical validation

`self_test.py` checks the within-chooser coefficients and clustered covariance against an independent dense regression with explicit chooser dummies, under all six adjusted specifications. It also checks account boundaries across Parquet chunks, singleton handling, exact bin endpoints, frozen state-band partitioning, checkpoint round-trips and rejection of an unidentified contrast. Development additionally exercises synthetic Parquet staging, count/identity validation, context estimation, resumption and rendering.

These tests validate the implementation. They do not determine whether the empirical left-hand upturn survives.
