# Start repetition without waiting for worker capacity

This launcher implements the explicit request to stop waiting for capacity reserved by other jobs. It bundles the unmodified KAC Repetition Sensitivity v1.0.1 analysis and replaces only its worker-slot function in memory. The same checked checkpoints, scientific cache keys, model specifications, data checks, memory caps, and duplicate-run locks are used. It does not edit the earlier installed package or stop any other process.

If the earlier terminal is displaying `Waiting for worker capacity`, press Control-C once and wait for its shell prompt before launching this package. This releases its run locks. Completed Parquets remain available; only an interrupted, uncommitted phase may need to restart.

Put the ZIP in `~/Desktop/Lichess_Desktop`, verify the supplied checksum, extract to a fresh directory, and run `bash RUN_NOW.command --worker-budget 10 --io-workers 3`. Existing Python dependencies are reused without installation. Keep prior output folders and the external drive available.

Here `--worker-budget 10` caps this job only. Other jobs are not subtracted from it, so combined usage can exceed the earlier global ten-worker budget. The unchanged history phase uses up to four DuckDB threads; regression processes are additionally limited by memory. Duplicate attempts on the same analysis output still stop rather than run concurrently.

The launcher preserves the exact v1.0.1 manifest and cache namespace to reuse any work already completed by that version. Its separate manifest and executed wrapper are exported under `report/resource_policy/` along with an explicit no-wait policy record. The original package README describes the original scheduling default; this README and the policy record document the requested override.

Expected remaining runtime is still provisionally 4–8 hours from the July checkpoint, excluding queue waiting. Already completed later months reduce this. Simultaneous workloads can increase computation and I/O time. Progress supplies measured history ETA; full-data regression time remains unmeasured.

Upload the resulting `KAC_REPETITION_SENSITIVITY_RESULT_<id>.zip` and its `.zip.sha256`, or the PARTIAL pair if it stops. The June timestamp uncertainty remains labeled as sensitivity analysis; no scientific completion claim is added by this launcher.
