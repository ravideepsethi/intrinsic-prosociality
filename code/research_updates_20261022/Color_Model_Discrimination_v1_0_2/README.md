# Color model discrimination — corrected prediction and power pass

This run asks whether the November color change is large enough to distinguish the surviving mechanism models. It reuses the completed, repaired RD≤110 audit and existing monthly Parquets. The default run computes predictions and power without aggregating post-policy choices.

**Expected laptop runtime:** 10–40 minutes on the first run; 2–8 minutes after completion when caches are reused. A valid additional post-cohort input can add approximately 10–25 minutes. These are estimates, not timings measured on your private data. The included synthetic tests generally take under 20 seconds.

## Repair in version 1.0.2

The previous UTC-week helper assumed that casting pandas datetimes to integers always yielded nanoseconds. With newer pandas datetime resolutions, that assumption produced invalid week keys and thousands of spurious calendar weeks. Version 1.0.2 computes Monday starts directly from integer Unix milliseconds. Forecast grouping and DuckDB outcome grouping are independently checked against Python's UTC calendar. Negative or unordered bootstrap offsets now fail explicitly.

The self-tests remain mandatory. The launcher labels synthetic test output, prints the actual dependency versions, and prints `SELF_TESTS_OK` before starting private-data work. Your reported v1.0.1 failure was confined to these tests; it did not create private analysis caches. The scientific specification and original source Parquets are unchanged.

## Repair in version 1.0.1

The original launcher assumed the project Python had SciPy installed. This version makes SciPy optional: it uses its logistic function when present and a numerically stable NumPy implementation otherwise. It installs nothing and leaves the repaired models, analysis sample, windows, inference and source Parquets unchanged. The selected logistic backend and interpreter path are recorded in the result. The reported v1.0.0 failure occurred during imports, before any private-data analysis or cache creation.

## Run

Save this ZIP in `~/Desktop/Lichess_Desktop`, verify its supplied SHA256, extract with `ditto` into a fresh directory, and run:

```bash
bash /absolute/path/Color_Model_Discrimination_v1_0_2/RUN_COLOR_MODEL.command
```

The launcher uses `/Volumes/XT_Pro/lichess_kindness/venv/bin/python`. It validates the existing environment and package, runs the small synthetic checks, prevents idle sleep, and records a terminal log. It does not install packages or modify the existing environment.

There are up to ten independent monthly workers. Forecast jobs use up to six workers with the default 12 GB memory budget, or up to ten with `COLOR_MEMORY_GB=20`. Each process uses one Arrow/BLAS thread; DuckDB threads and memory are explicitly bounded. Increase the budget only if the laptop has enough free RAM. Column projection, ZSTD Parquet, row groups, source authentication, and persistent per-stage receipts avoid repeated upstream work.

Optional environment variables: `COLOR_PROJECT_ROOT`, `COLOR_DESKTOP_ROOT`, `COLOR_PYTHON`, `COLOR_WORKERS`, `COLOR_MEMORY_GB`.

## Inputs and exact scope

The 24 existing mechanism analysis Parquets cover November 2023–October 2025:

`derived/replication/mechanism_separation_v100_PRIVATE/analysis/YYYY-MM.parquet`

Their SHA256 values are pinned to the repaired audit. The runner projects the required fields and selects `regular`, roughly equal positions, and **both players' RD≤110**. It verifies the audited totals: 3,236,219 opportunities, 58,298 grants, and 778,048 chooser accounts. The original regularity definition and existing sample certification are inherited, not recomputed.

The repair is already finished. The runner does not repeat model estimation, identity recovery, rating replay, API collection, or engine evaluation. It does not use the earlier all-source post-policy series as a matched comparison. The bundled original power/prediction tables are historical references only and are never read by the calculation.

Planning transports the capped pre-period opportunity distribution to the policy scenario. Its regular sample varies with pre-period eligibility; it is **not** the still-unresolved account cohort frozen immediately before implementation. Planning figures must carry that label.

## What changes in this calculation

- The repaired capped fits replace the old uncapped fits. All seven full candidate models are forecast; framing, curved utility, and the displayed-gap model also receive the two existing forward-fit sensitivities.
- The old/new action payoffs and both players' premiums are recalculated at the same recorded state. The reference term, loss term, nonlinear utility cost, own premium and opponent premium all change where applicable. The displayed gap stays fixed.
- A fitted logit-index change is converted to a probability change **for each opportunity**, before aggregation. It is never reported directly as percentage points.
- Account baseline calibration uses only pre-policy outcomes, with the audited pseudo-count of 20. The global fallback for unseen accounts solves for the fitted offset instead of using an unadjusted logit of the mean. The last fitted month effect is carried forward beyond each fit's training period. These two probability-calibration choices are explicit amendments to the original forecast routine.
- Opportunity means are calculated within color and calendar week, followed by equal weighting of complete weeks. Prediction and outcome statistics use these same weights.
- The block bootstrap preserves the omitted transition weeks and the additional delay to the announcement window. It uses the capped pre-period weekly series, not millions of independent opportunities.
- Twelve fixed overlapping placebo dates, descriptive time slopes and autocorrelations accompany the noise calculation. These are diagnostics, not proof of parallel color trends.

The calculator is the same audited **anchored, no-volatility/no-regulator convention** used to estimate the models. Its arithmetic is exact within that convention. It is not a claim that fractional latent production ratings or exact integer-display histories have been recovered.

## Windows and power

Implementation: November 18, 2025, 07:22 UTC. Announcement: December 22, 2025, 22:35 UTC. Use eight complete pre-implementation weeks. Omit weeks crossing implementation or announcement.

The planning calendar tentatively ends before January 30, 2026; that is a **scenario, not a certified mechanics cutoff**. It yields four unannounced weeks, four announced weeks and an eight-week pooled secondary window. Actual-target windows instead use the source-supported censor in an accepted manifest.

The pre-period resampling uses 10,000 moving-block repetitions, blocks of four and eight weeks, a two-sided 5% critical value and 80% power. Negative and positive MDEs are separately inverted. Each pair of model predictions is compared at effective updating of 5%, 10%, 20%, 50% and 100%.

For the main question, use rows with `both_models_pre_policy_compatible=True`. These compare models retained by the repaired capped pre-policy comparison. The standalone linear-cost and loss models remain as benchmarks; power against them does not demonstrate discrimination among the surviving models.

Effective updating is a homogeneous mixture scenario, not measured awareness. Fitted-parameter uncertainty is not propagated; forward-fit ranges are sensitivity checks, not confidence intervals. Power is conditional on the fitted models, baseline calibration, transport and the pre-period resampling process. There is **no automatic GO decision**, unconditional model rejection, causal price elasticity or estimated share of each motive.

## Post-cohort dependency

The default `--phase auto` inventories existing first-pass caches and looks for:

`derived/replication_36m/mechanism_color_inputs_v100/manifest.json`

If absent or invalid, corrected planning completes and the result records the exact missing dependency. If accepted, actual-cohort forecasts and pre-only power are added. **Auto mode still does not aggregate post-policy outcomes.**

This package includes an adapter, not a producer for the unresolved cohort. The manifest must reference real evidence for pool/observed nonadjacency membership, pre-implementation regularity, calibration in the capped target, aligned missing-value definitions, and a mechanics censor. File checksums authenticate that evidence; they cannot independently establish its scientific validity. See `INPUT_CONTRACTS.md`.

After reviewing actual-cohort prediction and power output, `--phase behavior` can produce the frozen descriptive color statistic and conditional point-fit compatibility table using that accepted input. This optional output remains conditional on transport, parallel color evolution and opportunity composition. Entry/denominator checks and fitted-parameter uncertainty are not solved here, so it is not the final causal adjudication.

## Results and restarting

The terminal prints `RESULT_TO_UPLOAD`. Upload both files placed on the Desktop:

- `COLOR_MODEL_RESULT_<UTC>.zip`
- `COLOR_MODEL_RESULT_<UTC>.zip.sha256`

The result includes `READ_ME_FIRST.md`, capped model predictions, forward-fit sensitivities, pairwise power, directional MDEs, weekly pre-period aggregates, placebo/temporal diagnostics, input status, the frozen amended plan and environment/checksum receipts. Each quantitative table is saved as Parquet and CSV. Public result bundles contain aggregate outputs, not account-level predictions.

New private caches and account calibration values remain under:

`derived/replication_36m/color_model_discrimination_v100_PRIVATE/`

Rerunning the same launcher verifies and reuses completed stages. Interrupted stages are recomputed atomically. A lock prevents concurrent writers; an upstream read lock protects against an active source-cache writer. Changed scientific inputs or damaged receipts stop the affected cache rather than silently replacing its provenance. Preserve the result ZIP and error text if that happens. Changing only worker count or memory does not invalidate results.

## Interpretation

The repaired pre-policy comparison retains framing, curved utility and displayed-gap models on common capped support. This run asks whether their **different policy predictions are distinguishable with the available calendar information**, at stated updating scenarios. A weakly informative result does not establish deference or rule out payoff sensitivity. It also cannot assign percentages of behavior to opportunity cost, reference dependence and deference.

This is an amended plan: earlier all-source post-policy results have already been inspected. It must not be described as an untouched preregistered policy test.
