# Development validation

Validated on September 25, 2026, using synthetic temporary data only. The final run used Python 3.12 on Linux with the user's reported DuckDB 1.5.2, NumPy 2.4.4, pandas 3.0.3 and PyArrow 24.0.0 versions. The user's machine uses Python 3.13 on macOS; that OS/interpreter combination was not reproduced here.

- 33 unittest checks ran: **32 passed, 1 skipped**. Optional compiled-loop parity was skipped because Numba was absent from this isolated development environment; the unchanged runtime parity gate remains mandatory before Numba is selected on the Mac.
- The actual foundation inventory function was executed against a checkpoint created by the original Stage06 writer. Its recorded digest equals the Parquet checksum and differs from the metadata-file checksum, reproducing and resolving the v1.0.1 failure.
- A complete synthetic November–January replay ran from that checkpoint, produced all three monthly checkpoints and diagnostic outputs, and reused them on restart. The final saved state matched one uninterrupted kernel sequence exactly.
- Changed checkpoint data, altered declared hashes and policy/identity mismatches stopped authentication. The preflight checked ten checkpoints and fifteen event partitions, and reported multiple missing checkpoints together.
- The pandas 3 date-resolution regression verified that both November 18 and December 22 markers remain on the weekly plot. Dates are converted explicitly to UTC epoch seconds.
- Checkpoint write/read and split-run replay reproduce an uninterrupted sequence exactly in the synthetic fixture.
- Both-null and one-sided-null state policies, the exact implementation cutoff and both color signs were checked.
- Scalar source updates and the vectorized old/new payoff function agreed to the stated numerical tolerance across randomized rating states.
- Monthly normalization, game-ID timestamp joins with reversed row order, chooser-side post-replay joins, duplicate rejection, source-change rejection, self-player exclusion, dose calculation, aggregate reconstruction reports and SVG generation passed synthetic checks.
- The returned failure was reproduced with missing modern timestamp paths. All four historical layouts were then normalized from their registered paths using synthetic Parquets. Unrelated source rows were excluded before checking target-key uniqueness.
- The existing replay-substrate fallback, a wrong source hash, missing/duplicate target timestamps and incorrect epoch units were checked. Invalid inputs stop before replay.
- Both native-timestamp and modern keyed-source v1.0.0 receipts were reused without rewriting their completed output. The current frozen plan equals the actual plan in the returned result bundle.
- A process-spawn test, matching the Mac worker start method, retained the successful month and recorded both failed months. Shared historical shards reused their hash receipt instead of being hashed twice.
- The January-mechanics aggregate window query and missing-February branch were executed separately and passed. Neither branch freezes a censoring date.
- The Bash launcher passed `bash -n`; all Python modules compiled/imported successfully.

No real-data replay, causal estimate, exact visibility count, power decision, or IV estimate has been run in the development environment. The final production Stage06 source must authenticate on the Mac before processing. The bundled earlier reference is used only for tests; production never falls back to it.

The full unit suite completed in 3.1 seconds in the development runtime. Allow 5–30 seconds on the Mac. This is not a production-data runtime benchmark. First-run planning estimate remains 2–6 hours, with per-speed/per-month ETAs reported from actual throughput. All 32 completed normalization partitions from the returned run are reused after verification.
