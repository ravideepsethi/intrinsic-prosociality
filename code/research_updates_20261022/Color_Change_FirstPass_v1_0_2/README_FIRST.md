# Color change first pass — v1.0.2

This corrects a checkpoint-verification bug in v1.0.0/v1.0.1. The foundation inventory records the checkpoint **Parquet data checksum**, copied from its metadata. The previous code incorrectly compared that checksum with the metadata JSON file. The correction preserves the independently recorded data hashes and verifies the actual Parquets against them. It also retains v1.0.1's historical timestamp repair.

Your `COLOR_FIRSTPASS_RESULT_20260925T185124Z.zip` confirms that all **32 months, 63,525,555 opportunities**, completed normalization; the checkpoint check then stopped the run after 88.3 seconds. **Run this version against the existing project. All completed preparation is reused. Keep the `color_change_firstpass_v100` folder.** The frozen scientific plan and data contract remain exactly version 1.0.0. Package identity is recorded separately in `IMPLEMENTATION.json`.

This package runs the reconstruction gate and prepares the first diagnostic tables. **It does not implement or release the later continuous DiD, threshold DDD, power decision, or receipt-IV estimates.** Those depend on the output of this run, the grace-rule censoring decision, and inputs that the current replay does not contain.

Expected remaining run time on the MacBook: **approximately 2–6 hours**. If Numba is already installed and disk throughput is good, **30–120 minutes** is a plausible faster range. These are planning estimates, not measurements on your extension data. The terminal prints a measured remaining-time estimate for each speed/month after the first 100,000 games and thereafter. A fully completed rerun should usually take 5–30 minutes to verify and reuse outputs. Local synthetic tests took about three seconds in the development environment; allow 5–30 seconds on the Mac.

Use the ZIP and command supplied in the chat. Download the ZIP into `$HOME/Desktop/Lichess_Desktop`. The launcher defaults to `/Volumes/XT_Pro/lichess_kindness` and its existing `venv/bin/python`; it never installs, upgrades, or downgrades packages. Requirements already used in this project: DuckDB, NumPy, pandas and PyArrow. Optional Numba is used only after numerical parity with the authenticated producer passes. No network access, API calls or Stockfish jobs are started.

## What runs

1. Authenticate the installed Stage06 producer. Before starting replay, check all ten required checkpoint Parquets (October 2023 and October 2025 in five speeds) against the foundation inventory, plus metadata identity, policy, row counts and byte sizes. Check the fifteen November–January event partitions for presence and required columns. Collect all failures in one preflight report. Checkpoint hashing uses up to ten I/O workers and normally takes 10–120 seconds on an SSD. Separately authenticate the certified Stage07 root receipt and reuse completed normalization after verifying its fingerprints and output hashes. The source adapters use only the documented project paths.
2. Read the 32 completed months, September 2023–April 2026. Create narrow typed ZSTD Parquets from the 24 certified Stage07 files and eight completed engine-extension months. Extension timestamps are joined by exact game ID to existing Stage05 or candidate Parquets, the recorded historical source files, or the existing all-rated-game replay Parquets. The latter is a narrow ID/time lookup, not a new rating replay. Historical sources are pinned by the enrichment handoff's file sizes and SHA-256 hashes; their old payoffs and engine evaluations are not imported. Duplicate target IDs, missing timestamps or changed engine hashes stop the run. Existing self-player records are counted and excluded downstream; identities are not recovered or replaced.
3. Authenticate the **October 2025** checkpoint in each of five independent rating pools. Resume **November 2025–January 2026 only**, carrying RD, volatility, previous-update time and rated-update count. The actual post-change formula is applied from November 18 at 07:22 UTC. Games with both rating differences missing do not change hidden state or last-update time; a one-sided missing difference still permits the update. All rated games enter replay; only opportunity states and aggregate validation cells are retained.
4. Calculate factual errors and the old-formula comparator at the same reconstructed state. Report month, outcome, speed, color, RD and gap cells, signed error, MAE, RMSE, >1 and >2 point tail shares, and near-equality draw-sign disagreement. The 07:15–07:22 implementation bracket is separate. Floor/nearest-integer matches are explicitly labeled diagnostic conventions.
5. Calculate draw and win payoffs under both formulas at a fixed pregame state: `d_G`, `d_C`, `delta_kappa=d_C-d_G`, and signed/absolute premium-change ratios. Create opportunity-level Parquets plus aggregate dose distributions, near-equality comparisons and returning-account support.
6. Prepare descriptive weekly grant rates. The conservative established cohort has at least 100 same-speed rated updates by October 2023. It is a fixed cohort, not a tenure reconstruction. These are **all-source diagnostic series**, not the final pool/non-immediate-rematch A2 specification. The completed pool identity work is not repeated.
7. Where complete January/February candidate/API pairs exist at documented paths, compute daily active-resolution rates and claim outcomes by speed, color and material class. Report seven-day changes around candidate dates without selecting a censoring date or using grant outcomes to choose it. Missing or ambiguous source branches are reported explicitly.

## What the source material changes about the plan

The certified replay **does not carry fractional ratings**. Its source states that it anchors ratings to the displayed PGN rating at every game and reconstructs only hidden RD/volatility/time. Consequently this package cannot honestly calculate an exact factual display-visibility share or cumulative informative-feedback history. `visibility_status.json` records that gap. Rounding a payoff is not substituted for a source-pinned display conversion applied to a validated fractional pregame rating.

The 32-month API/Stockfish coverage also **does not establish 32-month certified rating-state coverage**. This first run reuses the 24-month certified states and extends only the three months needed for the November–January gate. September/October 2023 and February–April 2026 remain explicitly missing in the dose coverage report. They are retained in descriptive board/outcome coverage. No unaudited old color-patch payoff is promoted into the certified cost layer.

The matching pre-policy validation baseline here is **November 1–18 07:15 UTC**, not a claim that every historical pre-period cell has MAE 0.34–0.46. It is generated by the same continuation, without replaying earlier years. Post months are compared within the specified cells; sparse/unmatched cells remain visible. No automatic scientific PASS is inferred from pooled MAE.

API-enriched >=5-second time-forfeit candidates are not a census of all disconnections or all platform timeouts. Candidate-frame active-resolution rates are labeled accordingly. They cannot silently become B2's platform-wide incident control. The January 30 issue date is not frozen as the production date. The exact grace-rule source/deployment evidence and the required broader denominator still need reconciliation before censoring or IV eligibility can be certified.

## Execution and restart behavior

`LICHESS_36M_WORKERS=10` uses ten independent processes for monthly normalization and dose calculations. Each process has one numeric/Arrow thread and one DuckDB thread with a bounded SQL-memory budget. Replay uses up to **five** processes because rating history is sequential within a speed pool. Adding workers inside a pool would change the historical dependence; the package instead uses an optional compiled numerical loop. Aggregate SQL uses up to ten threads.

Large output root:

```text
/Volumes/XT_Pro/lichess_kindness/derived/replication_36m/color_change_firstpass_v100
```

Allow roughly 35–60 GiB of free space for narrow datasets, checkpoints and temporary SQL spill; the launcher checks at least 35 GiB. Files are compressed with ZSTD. Per-month outputs are installed atomically. Replaying resumes from the last completed, hash-verified month. Completed normalization and dose months are reused only when their source fingerprint and output digest agree. An interrupted month is recomputed from its preceding checkpoint. A file lock prevents duplicate copies of this job.

The launcher leaves certified inputs unchanged and does not repeat full-history replay, engine evaluation, API enrichment or identity recovery. The optional compiler does not change the installed source file.

Timestamp resolution normally adds roughly 1–10 minutes; allow 5–20 minutes if it must scan the ID/time columns of the replay substrate. November and December share upstream shards: a process lock and hash receipt prevent duplicate full-file authentication. Every source-selection probe is recorded. Successful and failed months are collected across the worker pool before a failure bundle is written, so a second missing source does not remain hidden behind the first exception.

## Outputs to review

The compact result ZIP is created in `Lichess_Desktop` as `COLOR_FIRSTPASS_RESULT_<UTC>.zip`, with a `.sha256` sidecar. It contains only aggregate reports, configuration and source receipts. A failure also produces a result ZIP with the tracebacks, source catalog, timestamp-source probes, checkpoint metadata and observed hashes, worker status and receipts for completed normalization/replay months; completed checkpoints stay available for the next run. The terminal log is beside the ZIP, named `COLOR_FIRSTPASS_<UTC>.log`.

- `READ_ME_FIRST.md`, `SUMMARY.json`, `FROZEN_PLAN.json`.
- `IMPLEMENTATION.json`, `replay_preflight.json`, and checkpoint-authentication records if execution stops.
- `reconstruction_cells.csv/.parquet`, `matched_reconstruction.csv/.parquet`, and raw monthly diagnostic-cell Parquets.
- `dose_distribution.csv/.parquet`, `premium_near_equality.csv/.parquet`, `state_coverage.csv/.parquet`.
- `returning_stratum_support.csv/.parquet`, weekly aggregate Parquets, CSVs and an SVG plot.
- `visibility_status.json`, `grace_and_iv_dependencies.json`, and available daily/grace-date diagnostic Parquets.
- `hourly_rated_games.parquet`: rated-game counts, not a platform-timeout numerator.

Upload the result ZIP for the next decision. `FIRST_PASS_COMPUTATION_COMPLETE` means the computation finished. It does not mean reconstruction, grace censoring, visibility, power or causal identification has passed. All later statistical claims remain gated. The frozen plan records the main-effect requirement for continuous DiD, distinct threshold/relocation predictions, awareness scenarios, dependence-aware power requirement, common-sample five/ten history comparison and recipient-choice color × post control for the IV.

## Optional code checks

From the extracted package directory, expected runtime 5–30 seconds:

```bash
/Volumes/XT_Pro/lichess_kindness/venv/bin/python -B -m unittest discover -s tests -v
```

The included `vendor/stage06_reference_19ad.py` is the recovered pre-finalizer source used for isolated tests. It is **never a production fallback**. Production requires the installed final producer SHA-256 listed in `PROVENANCE.md`. Tests cover independent scalar/vector formula agreement, both colors and thresholds, the exact cutoff, null-difference policy, keyed Parquet joins, duplicate rejection, self-player exclusion and output status/denominator semantics. The checkpoint regression executes the original foundation inventory function and the original Stage06 checkpoint writer, then runs a complete synthetic three-month replay and verifies its restart. Real-data scientific validation can only occur on your drive.
