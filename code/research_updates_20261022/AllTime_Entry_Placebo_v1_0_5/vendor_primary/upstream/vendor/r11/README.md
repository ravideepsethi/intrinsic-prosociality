# R11: main regression with the rating gap by region

Run `RUN_R11.command --workers 10 --memory-gb 11`. Defaults are the original certified sample on `/Volumes/XT_Pro/lichess_kindness` and reports on `~/Desktop/Lichess_Desktop`. Author accounts are retained, as explicitly requested for R11. Earlier author-exclusion instructions do not define this run's sample.

The production data remain on your Mac. This package has been tested on synthetic observations and against R10's model parameterization; it does not contain new production estimates.

## Runtime and resuming

- Expect roughly 15–35 minutes for the three regressions with 10 workers and an 11 GiB budget. The completed R10 run took about 20 minutes. This is an estimate, not a benchmark of R11 on the Mac.
- All three models share the same two passes over chooser-complete partitions. The pooled-gap appendix model therefore adds little work and is included by default.
- When available, the exact R10 run `6bb9fb7c3d51` supplies reusable projections and partitions. The runner verifies its producer-code fingerprint, sample binding, row counts and file SHA-256 values before reading them. R10 files are not modified. Otherwise R11 builds its own inputs from the authenticated originals.
- Workers are capped at 10 and may be reduced to honor the memory budget. Each uses one BLAS thread. Private numerical and projection caches are resumable.
- Checkpoints 25%, 50%, 75% and 100% produce aggregate ZIPs with SHA-256 sidecars. At 75%, all regressions and their inference are ready. The all-game PGN scans can take hours, potentially overnight. Progress reports next-checkpoint and finish estimates where throughput permits, plus 45-second heartbeats.
- Rerunning the same package/environment verifies and reuses a completed regression report, then refreshes the all-game descriptive. Adding PGN files does not change the regression key. `--allgames-only` requires that the regression already be complete.
- Package code and numerical-package versions are part of the regression key. Keep the package unchanged for reuse.

## Models and outputs

1. `column1` is Table 2: position bins, stage by region, gap by region, chooser/speed/month fixed effects and all x_g controls.
2. `column2` removes all x_g controls and their missing indicators, retaining the gap and its region-specific missing indicator.
3. `column3` pools the gap and keeps all other column-1 terms. Its model space is exactly R10 column 3. Production completion requires 34 equivalent estimates and clustered standard errors to reproduce the archived, checksum-verified R10 report within tight numerical tolerances.

`main_table.tex` contains column 1. `appendix_comparison.tex` compares the three columns. The complete requested results, including tests omitted from the compact LaTeX layouts, are in `contrasts.csv` and `table2_all_contrasts.csv`, with parallel Parquet files. `stage_profiles`, `adjusted_rates_column1`, `gap_region_support`, `gap_contrast_weights`, `position_at_zero_gap`, `model_summary`, and the original forty position-stage cells are supplied separately.

Every `covariance_column*.npz` saves `beta`, `beta_names`, full joint `covariance`, aligned `names`, empirical `moment_means` and `moment_names`, plus the estimability scaling and null space. The top-left `len(beta)` square is the coefficient covariance. Additional rows carry the uncertainty in sample composition and raw baseline rates, including their covariance with coefficients.

The report contains only aggregates. Chooser-complete rows, hashes used to group choosers and source paths remain in the private run directory. No API requests, Stockfish work, downloads, source deletion or source edits are performed. The launcher installs Python dependencies only if necessary.

## Literal hinge definition

Let r be the disconnected player's displayed pre-game rating minus the chooser's. Let g = clip(r, −600, +600)/100. For each region R:

    h_R(r) = gamma_g,R * g
           + gamma_-3,R * max(g + 3, 0)
           + gamma_-1,R * max(g + 1, 0)
           + gamma_0,R  * max(g, 0)
           + gamma_1,R  * max(g - 1, 0)
           + gamma_3,R  * max(g - 3, 0)
           + gamma_low,R  * 1[r < -600]
           + gamma_high,R * 1[r > 600].

Nonfinite gaps use the r=0 basis plus a region-specific missing indicator, matching R10. In the returned R10 production sample the gap and control missing counts were zero; R11 reports them again rather than assuming this.

For example:

    h_R(+100) - h_R(-100)
      = 2*gamma_g,R + 2*gamma_-3,R + 2*gamma_-1,R + gamma_0,R.

The hinges are uncentered, exactly as requested. Consequently h_R(0) = 3*gamma_-3,R + gamma_-1,R. A raw competitive-position beta is not by itself the cross-region board effect at zero rating gap: at stage 0–4 that comparison also adds h_C(0) − h_L(0). Panel A reports the requested raw beta coefficients; `position_at_zero_gap.csv` makes the translation explicit. No silent re-centering changes the requested parameterization.

The six slopes are derivatives per 100 points on the six open segments inside [-600,+600]. Beyond the clipping limits the slope is zero, with possible level jumps from the tail indicators. Derivatives at the knots are not asserted.

## Standardization and inference

Adjusted position rates set a position bin for every opportunity. This also changes C and BOTH its stage and gap interactions. Adjusted stage rates change stage while retaining each opportunity's position, C, gap, clocks, rating environment and chooser effect. Calculations use mean(Y) + mean(X_counterfactual − X_observed) beta. Predictions are not clipped. They standardize to the full opportunity distribution, so a counterfactual can require extrapolation beyond a particular bin's observed joint support.

Chooser-clustered covariance uses G/(G−1), without an additional residual-degrees-of-freedom correction. Singleton choosers remain in sample descriptions and standardized rates; their within-transformed regression scores are zero. Joint delta-method calculations include empirical weights and denominator uncertainty. P-values are two-sided asymptotic normal Wald; 95% intervals are pointwise.

Within each column, multiplicity families are exactly:

- Panel A: four raw position betas and three adjacent differences, family of 7.
- Panel B: seven baseline contrasts and six adjacent contrasts of the opportunity-weighted pooled stage profile, family of 13.
- Panel C: five requested gap contrasts within each region, two separate families of 5.

Regional stage coefficients, regional rebounds and their difference, baseline ratios, cross-region gap differences, segment slopes, adjusted rates, and zero-gap translations are unadjusted and explicitly labeled. In column 3, cross-region gap differences equal zero by model restriction. Rank-deficient columns are retained in the saved representation; every reported focal contrast passes an estimability check or is explicitly marked unavailable.

The six raw-gap support segments use left-inclusive internal boundaries: r < −300; −300 ≤ r < −100; −100 ≤ r < 0; 0 ≤ r < 100; 100 ≤ r < 300; r ≥ 300. The two strict tails, r < −600 and r > 600, are overlapping subsets of the outer segments. Do not add the tails to the six segment counts. Missing gaps are counted separately.

## All-game quartiles and medians

The default search includes both documented locations:

    /Volumes/XT_Pro/lichess_kindness/raw/lichess_pgn_standard
    /Volumes/XT_Pro/lichess_kindness/data/raw/lichess_standard_rated_pgn_zst

Add `--pgn-dir '/path/to/another/archive/root'` for another location; the flag can be repeated. Original filenames must match `lichess_db_standard_rated_YYYY-MM.pgn` with optional `.zst`, `.gz` or `.bz2` compression. Alternatives for a month are attempted if the preferred source fails.

Only successful monthly all-game scans enter the pooled histograms. Each source is parsed through EOF and hashed; an adjacent `.sha256` is checked when present. Broken/truncated sources are rejected, with other months retained. Rated standard live games include all matching sources and endings, with no opportunity or author restriction. Casual, variant/setup, and untimed/correspondence records are counted as exclusions. The target speed categories remain ultrabullet, bullet, blitz, rapid and classical. Missing categories produce unavailable values rather than zeros.

`all_games_plies_by_speed.csv` gives N, the 25th percentile, median and 75th percentile, and the months used. Quantiles pool games across available months, using exact histogram order statistics and linear interpolation at (N−1)*p (type 7). They are not averages of monthly quantiles. `all_games_month_coverage.csv` lists every requested month as included, missing or failed. `ALL_GAMES_STATUS.json` distinguishes 24-month, available-month and no-source cases.

When at least one month succeeds, a 100% report contains the available-month descriptive and explicitly identifies incomplete coverage. If none succeeds, the 75% report retains completed regressions, gives unavailable descriptive values, and the command exits with code 2. No sample-only median is substituted. Existing chronology tables lacking ply counts cannot answer this calculation.

## Return

Return the latest `R11_REPORT_*_100.zip` (or the 075/000 ZIP if stopped), its `.zip.sha256` sidecar and the `R11_LAUNCH_*.log`. The 75% regression ZIP is already usable while the all-game scans continue. Package integrity is checked on launch, followed by synthetic numerical tests.
