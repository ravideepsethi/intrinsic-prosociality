# KAC companion analyses 1.0.0

Put the ZIP in `~/Desktop/Lichess_Desktop`, extract it, and run `bash RUN_COMPANION.command --worker-budget 10 --io-workers 3` from its folder. Use the complete Terminal command supplied alongside the ZIP if preferred.

What this does:

- Includes the completed arena-gradient result and a manuscript paragraph. No new arena run is needed.
- Runs matched receipt and primary IV comparisons with exact-hour effects on their authenticated existing Parquets, including checks that the original results reproduce.
- Runs the within-account repetition/experience models and state interactions, using a shared chronological history extraction with parallel file processing and whole-chooser regression partitions.
- Preserves private immediate-predecessor links for the ordinary-loss test and reports which source fields are still missing.

The ordinary-loss regression, the specifically promised timeout-share control/exclusion, and incident-adjusted temporal concentration are **not completed by this version**. `SOURCE_READINESS.json` explains the source gaps. Exact-hour comparisons are an additional common-shock check, not a substitute with the same name. The readiness ZIP is produced before the heavy stages, so it can be uploaded immediately to continue resolving those sources.

## Running alongside the repair

The latest process list shows a 10-worker repair and a separate 4-thread job. This runner checks the Python parent commands and waits for capacity within a total budget of 10; it does not kill or alter either job. It performs light preflight/report preparation immediately. It checks capacity again before each heavy stage/month. If another job is launched later, the runner cannot retroactively reduce an already-running stage.

Expected runtime: readiness and tests usually 1–3 minutes. Receipt/IV hour checks provisionally 15–60 minutes. Full historical counts, monthly sessions and repetition provisionally 2–8 hours on the external drive, **after worker capacity becomes available**. These are unbenchmarked planning ranges, not measured times on your Mac. Live stage progress supplies elapsed time and a throughput-based estimate for file passes. Resuming skips authenticated completed stages. No Stockfish work is repeated. Have at least 40 GiB free; actual temporary use depends on history and DuckDB spilling.

## Output

New files live under `/Volumes/XT_Pro/lichess_kindness/output/kac_companion_analyses_v100/<run-id>/`. Existing project products are read only. Aggregate upload ZIPs are copied to `~/Desktop/Lichess_Desktop`:

- `KAC_COMPANION_READINESS_<run-id>.zip` immediately;
- `KAC_COMPANION_PARTIAL_<run-id>.zip` as stages finish or on an error;
- `KAC_COMPANION_RESULT_<run-id>.zip` after available stages finish.

Upload READINESS first if a source is missing, and RESULT or PARTIAL when it appears. Private Parquets and identifiers stay on your drive. The final status lists unresolved analyses; the word RESULT does not mean every manuscript TODO is finished.

Options: `--preflight-only`, `--stage hours`, `--stage repetition`, `--worker-budget 10`, `--io-workers 3`, `--memory-gb 8`. Normal reruns resume automatically. The statistical run ID does not change when resource limits change. A lock rejects simultaneous duplicate companion runs.

The launcher reuses an existing compatible Lichess Python environment. It changes no installed environment. Before new substantive results, synthetic tests check resource counting, FE/cluster inference, exact-hour absorption, strict historical ordering, cross-month session carry, color/result orientation, and cache integrity. Real data cannot be tested remotely: baseline and source gates execute on your Mac and stop a component if they disagree.
