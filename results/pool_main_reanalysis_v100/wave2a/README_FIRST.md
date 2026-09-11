# Pool-main reanalysis — Wave 2A v1.0.1

This package supersedes Wave 2A v1.0.0 before production execution. Wave 1 passed return-bundle authentication. v1.0.1 fully recomputes the equality/FEN analyses, restores the manuscript's missing adjacent displayed-gap crossing analysis, decomposes the exact-zero payoff mass by displayed-1500 and high-RD status, and freezes the new-sample support/dependency contract needed for Wave 2B.

## Selected main sample

The authenticated predicate is:

```text
source = 'pool' AND previous_classification_status = 'not_mutually_adjacent_observed'
```

| Quantity | Certified value |
|---|---:|
| Opportunities | 41,534,331 |
| Kind draws | 570,091 |
| Fair-region opportunities | 15,207,423 |
| Fair-region kind draws | 419,463 |
| Choosers | 3,224,173 |
| Months | 24 (2023-11 through 2025-10) |
| Sample fingerprint | `a17c89d750cb4fdfdf84f950859e45c58b19996efae02045def68285e305cf30` |

This sample certifies the observed mutual-adjacency screen. It does not certify removal of every literal end-to-start immediate rematch. Every receipt preserves that distinction.

## What Wave 2A does

1. Authenticates every package byte, the selected sample receipt and Parquet footers, and the returned Wave-1 Stage-08/09 authorities.
2. Inventories the canonical 7.764-billion-event all-game chronology and the old dynamic inputs without treating old sample-dependent caches as current.
3. Authenticates the exact archived reference-demand v1.0.5 executed source, then rebuilds the plotted displayed-gap schedule from -12 to +12 relative to -1, its 24-test Holm correction, and the joint -1/0/+1 models for all games and games past ply 10.
4. Reports how much exact-zero payoff support is displayed 1500-vs-1500 and separately classifies pre-game RD above 110; it refits the controlled local crossing after splitting/excluding those rows. This decomposition is explicitly post-Wave-1 diagnostic work.
5. Computes new-sample cohort/support counts for A1/A3/B1 and deterministic second-wave targets. This is dependency evidence, not a dynamics estimate. The Wave-2B contract now also requires chooser-role timeout, disconnector-role timeout, and active-resolution-given-candidate selection components for the chooser-leniency comparison frame.
6. Rebuilds the outcome-blind short-position FEN4/board-frequency cache from the new sample.
7. Re-estimates the full equality, position-commonness, short-game, engine-zero, and placebo-knot model grid and independently verifies all aggregate outputs.
8. Creates an aggregate-only return ZIP and checksum sidecar.

The scientific FEN design comes from `Kindness_Equality_FEN_Audit_v1_0_1_20260827`; only its frozen input authority was reset. Public dynamics scripts inspected at repository commit `0dc981cbc6da157d365015a95f2b7157ecda4859` are bundled as the rewrite source inventory for Wave 2B. Old dynamics, dyad, Campaign, chooser-leniency, Patron, and manuscript estimates remain stale.

## Run on the Mac with XT_Pro attached

Double-click `RUN_WAVE2A.command`, or run:

```bash
cd /Users/u6025368/Desktop/Lichess_Desktop/Pool_Main_Sample_Reanalysis_Wave2A_v1_0_1
chmod +x RUN_WAVE2A.command
./RUN_WAVE2A.command
```

The launcher reuses the compatible Wave-1 Python environment when available. Otherwise it creates an isolated environment. It runs a complete synthetic FEN smoke test before touching production data, caps concurrency at ten, requires 80 GiB free by default, and makes no Lichess/API request.

Wave 2A can take several hours because it hashes all 24 panel files once, scans 41.5 million rows for dependency counts and FEN frequencies, and fits the adjacent-gap, restricted crossing, and FEN clustered fixed-effect models. It is resumable: preserve both output folders and rerun the same launcher after interruption. If v1.0.0 created valid FEN or inventory outputs at these same roots, v1.0.1 authenticates and reuses them while adding the missing crossing stages.

Successful outputs are written under:

```text
/Volumes/XT_Pro/lichess_kindness/output/pool_main_reanalysis_v100/wave2a
/Volumes/XT_Pro/lichess_kindness/derived/replication/pool_main_reanalysis_v100_PRIVATE/wave2a
```

Then upload both new files from the desktop work folder:

```text
POOL_MAIN_REANALYSIS_WAVE2A_RESULTS_<UTC>.zip
POOL_MAIN_REANALYSIS_WAVE2A_RESULTS_<UTC>.zip.sha256
```

The return ZIP excludes game/user identifiers, FEN hashes, row-level FEN/crossing model caches, checkpoints, and DuckDB spill.

## Scope boundary

Wave 2A intentionally does not re-label chronology-dependent estimates as current. It also does not choose manuscript wording automatically: the returned adjacent-gap and 1500/high-RD crossing results must be reviewed together before Section 4.4 is changed. If its dynamics receipt is `POOL_MAIN_WAVE2B_PREFLIGHT_READY`, the returned support counts and physical-input inventory become the frozen authority for a dedicated Wave-2B history rebuild. If it is blocked, the ZIP records the exact missing or changed dependency while still returning the completed crossing and FEN analyses.
