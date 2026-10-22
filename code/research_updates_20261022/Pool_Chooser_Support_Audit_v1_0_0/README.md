# Pool chooser-support audit v1.0.0

This audit supplies the missing Design I support counts and checks singleton removal for the current minimal binary chooser-FE desert contrast. It uses the certified pool/nonadjacent 24-month panel already on the Mac. It does not download games, rerun engines, rebuild the panel, or restrict regressions to ever-granters.

Read `docs/DESIGN_I_REVISION_NOTE.md` for the corrected estimand and manuscript language. Production counts require the local run; the included tests use synthetic observations only.

## Run

Save this ZIP and its `.zip.sha256` sidecar in `~/Desktop/Lichess_Desktop`. Connect XT_Pro, then paste the full block into Terminal:

```bash
/bin/bash <<'BASH'
set -euo pipefail
cd "$HOME/Desktop/Lichess_Desktop"
/usr/bin/shasum -a 256 -c Pool_Chooser_Support_Audit_v1_0_0.zip.sha256
chooser_support_unpack="$(/usr/bin/mktemp -d "$HOME/Desktop/Lichess_Desktop/chooser_support_run.XXXXXX")"
/usr/bin/ditto -x -k Pool_Chooser_Support_Audit_v1_0_0.zip "$chooser_support_unpack"
/bin/bash "$chooser_support_unpack/Pool_Chooser_Support_Audit_v1_0_0/RUN_CHOOSER_SUPPORT.command"
BASH
```

Expected runtime: approximately **2–5 minutes**, plus any first-time dependency installation; competing jobs or a slow disk can add time. The launcher reuses a compatible existing Wave1/Wave2/RD environment when available. Defaults: two monthly census workers, eight hashing threads, one merge using eight threads, 2 GB per monthly DuckDB connection and 4 GB for the merge. At least 5 GB free is required. Native BLAS threads are capped at one. Interrupted work resumes from checksum-verified private aggregates.

Default project: `/Volumes/XT_Pro/lichess_kindness`.

Default input: `derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE` beneath that project. All 24 source hashes, source authority, row totals and outcome aliases are checked. The minimal FE coefficient and clustered standard error must reproduce the current Wave2B1 C7R table before completion is reported.

Environment overrides are `CHOOSER_SUPPORT_PROJECT`, `CHOOSER_SUPPORT_SAMPLE`, `CHOOSER_SUPPORT_TRANSFER`, `CHOOSER_SUPPORT_PYTHON`, `CHOOSER_SUPPORT_WORKERS`, `CHOOSER_SUPPORT_HASH_WORKERS`, `CHOOSER_SUPPORT_MERGE_THREADS`, `CHOOSER_SUPPORT_WORKER_MEMORY`, `CHOOSER_SUPPORT_MERGE_MEMORY`, and `CHOOSER_SUPPORT_MIN_FREE_GB`. Interpreter overrides must point to Python 3.11+.

## Outputs

The launcher prints the completed count paragraph and puts `POOL_CHOOSER_SUPPORT_RESULTS_v100_<timestamp>.zip` and its SHA-256 sidecar on `~/Desktop/Lichess_Desktop`. Return both files.

Public output is also written to the project's `output/pool_chooser_support_v100`:

- `chooser_opportunity_summary.csv`: full panel, binary contrast and competitive-only chooser counts, exact median, mean, singleton count, count with more than one opportunity, percentiles and maximum.
- `opportunities_per_chooser_distribution.csv`: full frequency distribution for those samples.
- `DESERT_SUPPORT.json`: number observed in both states and the opportunities/identifying weight they supply.
- `singleton_invariance.csv`: minimal FE slope and clustered inference before/after removing singleton choosers; separate covariance conventions are labeled.
- `DESIGN_I_COUNT_PARAGRAPH.txt` and `DESIGN_I_REPLACEMENT.tex`: computed manuscript language.
- `SUMMARY.md`, provenance, environment, reference reproduction, completion receipt and internal checksums.

Chooser IDs and private aggregates remain under `derived/replication/pool_chooser_support_v100_PRIVATE` and are excluded from the returned archive. The audit fits the same binary contrast on samples defined by state support; no model selects accounts using whether they grant.

## Interpreting singleton checks

The coefficient is invariant under singleton deletion. The currently reported C7R finite-sample covariance correction can change, so the audit reports whether its standard error also agrees to four decimal places in percentage points. A separately labeled correction compatible with the Stage08 minimal identifying-row approach is included for comparison. Do not generalize this audit into a claim that every Design I model and every standard error has been rerun.

The counts use cp ≥ −100 for competitive and cp ≤ −300 for clearly worse. The main-panel distribution also includes the middle positions. The binary contrast support therefore differs from the full-panel support.
