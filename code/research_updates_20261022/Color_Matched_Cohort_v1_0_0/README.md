# Color Matched Cohort v1.0.0

Build the fixed regular-player roster, join reviewed rating states to the observed pool/nonadjacency sample, and produce matched model forecasts and conditional descriptive color contrasts. This is a new cohort producer, not an adapter requiring a pre-existing certified regular cohort.

## Run on the Mac

Place the ZIP and its `.sha256` sidecar in `~/Desktop/Lichess_Desktop`. In Terminal:

```bash
cd "$HOME/Desktop/Lichess_Desktop" &&
shasum -a 256 -c Color_Matched_Cohort_v1_0_0.zip.sha256 &&
task_unpack="$(mktemp -d "$HOME/Desktop/Lichess_Desktop/color_matched_v100.XXXXXX")" &&
ditto -x -k Color_Matched_Cohort_v1_0_0.zip "$task_unpack" &&
bash "$task_unpack/Color_Matched_Cohort_v1_0_0/RUN_MATCHED_COHORT.command"
```

The launcher uses `/Volumes/XT_Pro/lichess_kindness/venv/bin/python`, keeps the Mac awake, caps the shared producer at ten workers and the new heavy stages at two processes, and writes a terminal log. It does not install or upgrade packages. NumPy, pandas, DuckDB, PyArrow, and zstandard must already be available in that environment. SciPy and Numba are not needed by this package.

Return the two `COLOR_MATCHED_RESULT_<timestamp>.zip` and `.zip.sha256` files printed at the end, including when a stage stops. Individual game records, account IDs, and the roster stay in the private project directory. A successful run produces aggregate tables only.

## Existing work reused

- November–January target replay and payoff products from `color_change_firstpass_v100`.
- Completed pre-policy mechanism panel and its per-user monthly history summaries.
- The repaired RD110 full fits, including the corrected opponent premium.
- Source recovery and observed adjacency from the unchanged `Receipt_IV_Cohort_Extension_v1_0_0` producer. If that job is active, this runner waits on its existing lock. If it has completed membership, this runner authenticates and reuses it without repeating the recovery. If it stopped earlier, the runner resumes its immutable checkpoints and stops before IV scoring.

No rating replay, Stockfish search, new API requests, or candidate-model refit is run. The color job adds an implementation-date roster and post-opportunity histories. Previously counted accounts reuse monthly summaries; only accounts missing from the earlier history scope require an additional old-chronology count scan. All five November–January speed partitions are used for new local histories. That extraction can still be substantial.

The shared producer retains its original September 2023–April 2026 chronology scope so that its checkpoint identities remain reusable. April is not added to the color outcome comparison. If the shared producer is unfinished, completing that existing stage can dominate runtime. No runtime benchmark for the user's archive is claimed.

## Outputs and interpretation

Read `SUMMARY.json`, `window_status.csv`, `roster_counts.csv`, `sample_selection.csv`, `coverage_gates.csv`, and `calibration_cells.csv` before comparing models. Then use `matched_predictions.csv`, `matched_MDE.csv`, `matched_pairwise_power.csv`, and, if gates pass, `matched_behavioral_contrasts.csv` and `conditional_point_fit_comparisons.csv`.

The primary event window is the four complete weeks between implementation and announcement. January 7 and January 30 are named truncation sensitivities; neither is asserted to be a certified later-mechanics deployment censor. Forecasts hold the earlier fitted coefficients fixed. The conditional point-fit comparisons do not establish causal mechanism rejection or motive shares. See `METHODS.md` for the exact assumptions and weights.

Rerun the same launcher to resume. Keep the private caches. An input or output checksum mismatch stops for review instead of deleting completed work. The separate color cache is `derived/replication_36m/color_matched_cohort_v100_PRIVATE`. Results are also retained in `output/color_matched_cohort_v100`.

The package's `FROZEN_PLAN.json` records the specification before this new matched comparison is computed. It is not a claim of historical preregistration or complete blindness to earlier aggregate color results.
