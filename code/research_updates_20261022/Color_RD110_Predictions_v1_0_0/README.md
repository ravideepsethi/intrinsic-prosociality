# Color predictions from the completed RD≤110 audit

Version 1.0.0, 26 September 2026. This is a finite, cached-data prediction and planning update. It does not estimate the policy's behavioral effect.

Run `bash RUN_COLOR_PREDICTIONS.command`. Defaults point to `/Volumes/XT_Pro/lichess_kindness` and `$HOME/Desktop/Lichess_Desktop`. The launcher checks the package, uses an existing compatible Python environment when available, runs the numerical tests, and keeps the Mac awake. It creates an isolated environment only if no compatible one is found.

The only population input is the completed mechanism cache at `derived/replication/mechanism_separation_v100_PRIVATE/analysis/2023-11.parquet` through `2025-10.parquet`. All 24 files are checked against the reviewed input hashes and sizes. This package contains 16 reviewed, account-free coefficient snapshots: seven capped full fits, three original full fits, and two capped training folds for curved utility, framing, and displayed gap. No model is re-estimated.

The primary sample must reproduce exactly 3,236,219 opportunities, 58,298 grants and 778,048 choosers. It retains the original regular-player, pool and observed-adjacency restrictions and adds both pregame RDs ≤110. Roughly-equal positions after ply 10 are primary. This update uses only that primary state; the completed losing-state audit remains the supporting comparison.

Outputs:

- `PRIMARY_READOUT.csv`: revised full-awareness model predictions on all complete pre-policy weeks and on the final eight complete weeks.
- `same_sample_old_vs_corrected.csv`: original and corrected fits applied to exactly the same capped observations.
- `mechanical_dose_summary.csv`: exact draw, claim and premium shifts, with colors, RD groups, displayed ties and sign-flip bands separate.
- `planning_MDE.csv`, `single_model_power.csv`, `pairwise_power.csv`: moving-block planning thresholds and conditional power at five assumed awareness fractions. A departure from zero and separation of two models are different comparisons.
- `baseline_calibration.csv`, `model_predictions.csv`: account-baseline and training-fold sensitivity results. These are not confidence intervals.
- `pre_policy_weekly.csv`, `fixed_date_placebos.csv`, `monthly_support.csv`: auditable pre-policy noise and support.
- `SUMMARY.json`, `METHODS.md`, input checksums and one figure.

The terminal prints `RESULT_TO_UPLOAD` followed by a result ZIP saved to the Desktop folder, with a SHA-256 sidecar. Send that ZIP and sidecar back. Results are also retained under the project's `output/color_rd110_predictions_v100/` folder. New restart files live separately under `derived/replication/color_rd110_predictions_v100_PRIVATE/`; original caches are read only.

The run checks approximately 2.4 GB of existing monthly files and calibrates predictions on 3.24 million rows. Production runtime has not been measured for this new runner. It uses one prediction process with bounded design-matrix chunks and up to four preparation threads by default; `--threads 8 --memory-gb 4` changes preparation resources. Completed per-fit predictions are reusable after interruption. Do not delete previous caches.

No historical replay, API collection, Stockfish, mechanism refit, new recoverability simulation or color-follow-up rerun is required. No post-policy file is read. The existing color follow-up studies a different cohort and is not substituted for a matched regular-player policy sample. See `POST_POLICY_DEPENDENCIES.md` for what remains before a behavioral test.

The MDE and power calculations condition on fitted coefficients and the added baseline calibration. They assume a pre-policy noise process can be transported to the event. Unknown awareness, coefficient uncertainty, fixed-cohort membership, post-period composition and calibration remain limits. This package deliberately does not produce a formal GO/NO-GO, causal rejection, mechanism share or preference bound.
