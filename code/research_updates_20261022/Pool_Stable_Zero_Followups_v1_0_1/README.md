# Stable-rating zero follow-ups — v1.0.1

This package runs the two authorized follow-ups to the returned stable-rating curves: local slope changes allowing smooth curvature, and separate local estimates by board state. The extra K-scaling mechanism exercise is not included.

Save the package ZIP and its SHA-256 sidecar in `~/Desktop/Lichess_Desktop`, then paste `RUN_TERMINAL.txt` into Terminal. The launcher uses up to ten worker processes, one numerical thread per process, and reuses a compatible Python environment from the earlier runs. It installs dependencies in an isolated environment only if necessary.

**Expected runtime:** roughly 10–25 minutes on the machine used for the prior six-minute stable-rating run, with its authenticated sorted cache. This is an estimate, not a benchmark on the private data. Source hash checks, external-drive speed and other running jobs matter. Allow 25–60 minutes if the sorted cache must be rebuilt. Dependency installation can add a few minutes.

## Repair in v1.0.1

The prior sample-count artifact is a JSON list. Version 1.0.0 incorrectly passed it to the shared object-only reader and stopped after the first sample's moments. This version reads and validates that list explicitly, verifies its schema before any panel work, and exercises the production count check against the actual bundled evidence in the launcher self-tests. Count mismatches still fail. The estimates, controls, samples, and uncertainty calculations are unchanged.

The corrected code uses a new run identity and output directory. It reuses the authenticated earlier sorted base but rebuilds follow-up shards and moments; the failed v1.0.0 run stays untouched. Subsequent v1.0.1 restarts reuse their own completed checkpoints.

## What runs

- Two frozen samples: both players' pregame RD ≤ 75; and the same restriction with 11 ≤ K ≤ 12.
- Three axes: normalized draw payoff D/K, draw payoff D in rating points, and opponent-minus-chooser displayed rating.
- Three declared bandwidths per axis, with both local linear and local quadratic estimates.
- Exact rating-tie exclusion sensitivities.
- Local quadratic polynomials, jumps, and cutoff atoms interacted with the three competitive board states, with joint and pairwise tests.
- Normalized-payoff placebo cutoffs −0.10 and +0.10, using the same ±0.05 window width as the primary zero-cutoff fit. Zero-versus-placebo contrasts account for shared chooser clusters.
- Replication gates for the stable sample counts and all 90 earlier local-linear coefficient/SE rows.

There are 60 local fits. They are batched into two streamed passes per sample over chooser-partitioned Parquets. Completed moment and score shards are checked and reused after interruption; rerun the same command to resume.

The primary follow-up is a local quadratic fit on |D/K|≤0.05 in the both-RD≤75, K∈[11,12] sample. The design is declared before this follow-up run but follows inspection of earlier outcomes, so the results remain exploratory.

## Files and locations

Input authority: the frozen pool, nonadjacent-rematch-excluded panel of 41,534,331 opportunities in `derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE` under `/Volumes/XT_Pro/lichess_kindness`.

The runner authenticates the source and attempts to reuse the existing within-chooser K comparison's `PRIVATE/sorted_base.parquet`. A changed sample fingerprint or a corrupt checkpoint stops the run. It does not refresh API data, recompute ratings, or change source files.

Outputs:

```
/Volumes/XT_Pro/lichess_kindness/output/pool_stable_zero_followups_v101/<identity>/report
~/Desktop/Lichess_Desktop/POOL_STABLE_ZERO_FOLLOWUPS_RESULTS_v101_<identity>.zip
~/Desktop/Lichess_Desktop/POOL_STABLE_ZERO_FOLLOWUPS_RESULTS_v101_<identity>.zip.sha256
```

The report contains five PNG/PDF figure pairs, result tables in CSV and compressed Parquet, support counts, moment matrices, coefficient/covariance arrays, provenance, and the executed code. The export contains aggregates, not account or game identifiers. Numerical tables, not the prose summary, are the authoritative results.

Completion is indicated by `POOL_STABLE_ZERO_FOLLOWUPS_OK`. Return the results ZIP and sidecar for interpretation. If the command stops, return the final error and the log printed by the launcher.

See `METHODS.md` for exact controls, normalization, support and inference. See `VALIDATION.md` for the checks performed before delivery.
