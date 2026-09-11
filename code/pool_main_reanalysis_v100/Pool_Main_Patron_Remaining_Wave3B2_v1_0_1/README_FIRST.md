# Pool-main remaining Patron analyses, Wave 3B2 v1.0.1

Run `RUN_COMMAND.txt` after saving the ZIP and sidecar to
`~/Desktop/Lichess_Desktop`.

This release fixes the `Expected a JSON object: .../chooser_models.json`
failure in v1.0.0. The model catalogue is correctly stored as a JSON list;
the new reader validates that format. See `PATCH_NOTES_v1.0.1.md`.
The reported run stopped before rematch estimation. This release creates a
new configuration and repeats the short input stage; earlier files remain
in place. Subsequent runs of v1.0.1 resume its own completed checkpoints.

Expected elapsed compute: **1–3 hours**, excluding any wait for C9. This is a
planning estimate, not a full-data benchmark. It uses the preceding Mac
configuration (8 estimation threads, 10 hash workers, 12 GB DuckDB limit).
Allow 80 GiB free on XT_Pro for private caches and spill files. The 100 draws
run sequentially to avoid multiplying memory use; each fitted model is saved.

Includes five-bin chooser models, 100 deterministic alternative control
draws, price-side count/rate companions, opportunity-level models, ply
sensitivities, and the Patron dyad appendix. See `ANALYSIS_SCOPE.md`.

The launcher discovers the existing Python environment and installs nothing.
It waits if the supplied C9 fresh-randomization package holds its run lock.
You can start this command in a separate Terminal while C9 runs; Patron
computation begins after C9 releases the lock. Do not manually launch other
memory-intensive analysis jobs at the same time.

Outputs on the Desktop:

- `POOL_MAIN_PATRON_WAVE3B2_RESULTS_<UTC>_<config>.zip`
- the matching `.zip.sha256` file

Upload both. A `PARTIAL` archive indicates an interrupted or failed run;
upload it with the log if there is a failure. Repeat the same command to
resume completed fits. Successful runs are authenticated and reused.

Data and checkpoints stay under
`derived/replication/pool_main_reanalysis_v100_PRIVATE/wave3b2_patron`.
Public aggregates also stay under
`output/pool_main_reanalysis_v100/wave3b2_patron`.
No new profile requests, PGN reads, or network calls occur.

Overrides: `POOL_MAIN_PROJECT`, `POOL_MAIN_TRANSFER`, `POOL_MAIN_PYTHON`,
`POOL_MAIN_THREADS` (1–10, default 8), `POOL_MAIN_HASH_WORKERS` (default 10),
and `POOL_MAIN_MEMORY` (default `12GB`). Keeping the same settings permits
checkpoint reuse; different settings produce a separate configuration.
