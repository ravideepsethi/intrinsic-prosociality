# Pool-main C9 ply sensitivity v1.0.0

Save the ZIP and SHA-256 sidecar to `~/Desktop/Lichess_Desktop` and paste
`RUN_COMMAND.txt` into Terminal. The launcher discovers the existing Wave 1
Python environment and installs nothing.

Expected compute: **5–20 minutes**, excluding any C9/Patron queue time.
This is a planning estimate. The completed all-game session cache is reused;
there is no chronology rebuild or network request. Up to ten workers run,
with a data-based memory estimate reducing that count if necessary.

The package performs strict >4, >10 and >20 ply outcome checks, a both-anchor-
and-outcome >10 check, and a conditional randomization that fixes each chooser's
grant count within seven ply bands. It regenerates all 4,999 original C9/B2
sequences as a mandatory exact reproduction check before publishing results.
These are new sensitivities, outside the original confirmatory/Holm family.
See `ANALYSIS_SCOPE.md` for the anchor, sample, null and inference definitions.

Successful output on the Desktop:

- `POOL_MAIN_C9_PLY_RESULTS_<UTC>_<configuration>.zip`
- The matching `.zip.sha256` file.

Upload both. A `PARTIAL` archive is a failure report, not completed evidence;
retain it and the dated log. Repeat the same command after an interruption:
completed batches are authenticated and reused. No old results are deleted.

New private state:
`/Volumes/XT_Pro/lichess_kindness/derived/replication/pool_main_reanalysis_v100_PRIVATE/c9_ply_v100`.
Public results:
`/Volumes/XT_Pro/lichess_kindness/output/pool_main_reanalysis_v100/c9_ply_v100`.

Optional overrides: `POOL_MAIN_PROJECT`, `POOL_MAIN_TRANSFER`,
`POOL_MAIN_PYTHON`, `POOL_MAIN_C9_PLY_WORKERS` (1–10, default 10), and
`POOL_MAIN_C9_PLY_MEMORY_GB` (default 12). Worker changes preserve the same
randomization streams and permit checkpoint reuse.
