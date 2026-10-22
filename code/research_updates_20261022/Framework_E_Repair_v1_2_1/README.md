# Framework Test E — numerical repair v1.2.1

A, B, C, D and F are **not** rerun. Uses the private 2,682,330-row prepared IV Parquet produced by the v1.2.0 run on 2026-10-12. No API calls, PGN processing, new engines, or rating replay. Does not modify any frozen input.

## Reason for repair

The old `absorb_multi` used only 65 sweeps of weighted alternating projections for fixed effects (4,324 assignment cells, 700+ exposure dates, hour of week). It failed its strict convergence check before computing even the original pooled calibration. **No valid Test E treatment effects came from v1.2.0.** The v1.2.1 estimator uses matrix-free Jacobi-preconditioned conjugate gradient for the singular categorical fixed-effects normal equations. Every projected column must pass a direct check on the maximum residual mean across **every** category. It also uses a scaled Frisch–Waugh–Lovell projection for nuisance regressors and a low-memory, exact role-or-date CR0 covariance with dyad and date intersections.

The pooled IV model is run first, **without** the newly added experience-group dummies. It must reproduce the manuscript benchmarks (first stage 6.912 pp per score SD, OLS 0.382 pp, IV 0.295 pp) within predeclared numerical tolerances. If this fails, the script outputs a calibration report and **does not interpret or publish heterogeneity**.

On successful calibration, separate PG (previous giver), PC (previous competitive choice, no grant), NC (no previous competitive choice and no grant) effects and PG–NC, PG–PC, PC–NC contrasts are estimated jointly. Group histories are left-censored at November 2023; group-specific Anderson–Rubin intervals are not included. These are secondary, conditional-IV comparisons, not an automatic demonstration of psychological gate opening.

## Run from a fresh Mac terminal

Place `Framework_E_Repair_v1_2_1.zip` and `.zip.sha256` in `~/Desktop/Lichess_Desktop`, then:

```bash
(
 set -Eeuo pipefail
 cd "$HOME/Desktop/Lichess_Desktop"
 shasum -a 256 -c Framework_E_Repair_v1_2_1.zip.sha256
 ditto -x -k Framework_E_Repair_v1_2_1.zip .
 bash Framework_E_Repair_v1_2_1/RUN_E_REPAIR.command
)
```

You can explicitly set `--prepared <path>` and `--preflight <path>` to reuse equivalent authenticated frozen files. The defaults point to the v1.2.0 run's `/Volumes/XT_Pro/lichess_kindness/output/framework_AE_v120/20261012T043832Z/E_prepared/...`. The launcher verifies the preflight counts, hashes the prepared Parquet, runs all synthetic algebra checks, and writes a fresh output tree `output/framework_E_repair_v121/<UTC timestamp>`.

## Report and interpretation

A successful run produces `FRAMEWORK_E_REPAIRED_REPORT_<timestamp>.zip` and its `.zip.sha256` in `~/Desktop/Lichess_Desktop`, with pooled calibration, subgroup estimates, joint contrasts, covariance cluster counts, and provenance. On failure, a ZIP labeled INCOMPLETE is still produced if the estimator reached its reporting stage. Upload ZIP, checksum, and `framework_E_repair_<timestamp>.log`. Never upload the private Parquet.

**Resource caveat**: The existing 2.68m-row file is loaded once; the HDFE projector uses NumPy/BLAS single-threaded with sequential per-column fixed-effects solves, not 10 concurrent workers. Expected runtime is unbenchmarked and depends on SSD bandwidth and FE connectivity. Memory may reach several GiB. The percentages in terminal output denote logical stages, not elapsed-time proportions.
