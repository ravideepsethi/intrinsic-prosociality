# R10 v1.0.2 — identified contrasts; reuse previous successful stages

This is a **numerical identification repair**, not a new empirical specification. The unedited R10 handoff remains in `FROZEN_R10_SPEC.md`.

## What failed in v1.0.1

The full 41,534,331-opportunity preflight, monthly-file hashes, all 64 chooser-sorted buckets, and the first-pass within-chooser cross-products completed. Model 1, 2, and 3 design matrices were estimable after the usual nuisance-collinearity check. Model 4 stopped at `stage_5_6_X_classical`, with relative residual variance `-6.73e-14` (numerical zero). This means the term is linearly dependent on the other included columns after chooser fixed effects; it **does not establish** whether the underlying speed-stage cell has zero raw observations. The current runner reports the raw 5×8 support inventory so this can be diagnosed.

## Repair rules

The full frozen models and all 41.5 million observations remain unchanged. The program solves the original (potentially rank-deficient) within-account normal equations in the identified subspace. For every requested coefficient, difference, and standardized adjusted rate, it tests the estimand against the design's numerical nullspace. Identified contrasts receive estimates and cluster-robust standard errors; nonidentified contrasts receive **empty values** and `NOT_ESTIMABLE`, never zero imputation. The output includes `R10_nonidentification_audit.csv` and `R10_speed_stage_support_all40.csv`. For Holm families, a nonestimable planned test consumes p=1 in the original family size, with that test's own adjusted p left missing.

This specifically allows an 81+ vs 41–80 classical contrast to be reported when identified, even if classical 5–6 vs 0–4 is not. It also allows class 41–80 vs 0–4 to be marked unavailable when the classical 0–4 reference is absent. No games, position bins, or stage bands are merged or dropped.

## Terminal command (REUSE THE SUCCESSFUL FIRST PASS)

Place this package's ZIP and SHA sidecar in `~/Desktop/Lichess_Desktop`. Then paste:

```bash
(
  set -Eeuo pipefail
  cd "$HOME/Desktop/Lichess_Desktop"
  shasum -a 256 -c R10_Two_Questions_v1_0_2.zip.sha256
  ditto -x -k R10_Two_Questions_v1_0_2.zip .
  bash R10_Two_Questions_v1_0_2/RUN_R10.command \
    "$HOME/Desktop/Lichess_Desktop/FRAMEWORK_F_INPUT_20261012T030343Z" \
    --reuse-from "/Volumes/XT_Pro/lichess_kindness/output/r10_two_questions_v101/20261013T190547Z"
)
```

Preflight verifies SHA-256 hashes for the 24 inputs, exact paper sample totals, the old `INPUT_FILES.json`, exact v1.0.1 producing-code SHA-256, old bucket schema, all 64 completed sorted files and all 64 pass-one files, and the 41,534,331-row total of the sorted cache. It reads the old data but **never changes that run**; all second-pass files and outputs are written to a new `r10_two_questions_v102/<timestamp>` root.

You can also run the package without `--reuse-from` for a complete fresh run; that recreates the old first pass and is not recommended unless the old cache is absent.

## Outputs

`R10_TWO_QUESTIONS_REPORT_<UTCstamp>.zip` and `.zip.sha256` on Desktop, plus the Terminal log `r10_two_questions_<UTCstamp>.log`. Aggregate public files include:

- `R10_MAIN_REGRESSION_TABLE.tex` and `R10_all_coefficients.csv`
- `R10_panel_A_positions.csv`, `R10_panel_B_stage.csv`, `R10_panel_C_region_stage.csv`, `R10_panel_D_speed_stage.csv`
- `R10_adjusted_rates.csv`, `R10_model_metadata.csv`, `R10_SUMMARY.json`
- `R10_speed_stage_support_all40.csv` (including zero-support cells)
- `R10_nonidentification_audit.csv`
- `R10_CACHE_REUSE_PROVENANCE.json` (if reused)
- `sample_preflight.json` and `R10_raw_5x8x5.csv`

Only aggregate data, code/method provenance, and test status are in the public ZIP. Account identifiers, row-level histories, and sorted buckets remain on XT_Pro.

## Tests and limitations

The synthetic numerical checks, grouped-moment tests, and full reporting checks passed on the patch. Additional simulations with **no classical stage 5–6** and **no classical stages 0–4 or 5–6** passed: nonidentifiable contrasts were blank; remaining late-stage contrasts matched least squares. The launcher also executes the existing real-DuckDB/Parquet synthetic smoke test on the Mac. This container lacks DuckDB and PyArrow and cannot execute that specific smoke test; real-data run remains unverified until Mac execution.

This package does not infer medians of plies in all rated games, which require a corpus of all games including move counts. The all-game rating replay files discovered earlier contain no move counts. Do not replace all-game medians with timeout-only medians.

The original R10 test specification was written after earlier results; no new tests or interpretations are preregistered by this repair. Late-stage/speed interactions remain descriptive and should not be interpreted causally as hours or effort invested.
