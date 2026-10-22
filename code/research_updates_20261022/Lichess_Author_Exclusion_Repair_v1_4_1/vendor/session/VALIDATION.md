# Validation before delivery

Local checks used Python 3.12.14, DuckDB 1.5.5 (the same DuckDB version as the uploaded run), and PyArrow 25.0.1. The Mac uses Python 3.13.9. The launcher runs short tests in the Mac's environment before production. No production repetition coefficients were estimated here.

- The new partial ZIP matches its sidecar; all 19 report-member hashes pass.
- Existing and replacement history implementations produce identical synthetic carry, prior counts, predecessor/tie fields, cross-month/cross-speed session positions, censoring, summaries, and focal-history columns.
- The new annotation was compared on 384,000 synthetic events with both an independent sequential calculation and the prior SQL formula under forced external execution and a 0.2 GB DuckDB budget. Every original and derived column matched. Tests include exact 15/30/60-minute boundaries, ties, null carry starts, censored continuation, and missing rating changes.
- Multiprocess annotation passes exact Parquet round-trip checks. Incorrect session IDs, incorrect predecessors, and damaged annotated caches are rejected.
- A simulated interruption after the first committed partition reuses the unchanged input and shard receipts on resume. Disposable work is removed after the final monthly commit, never before it.
- A synthetic chain authenticates and adopts all 14 completed histories. Original hashes, sizes, modification times, and change times remain unchanged. The resulting checkpoint says December 2024 is next; a rerun keeps the same final receipt. Damage to a newly reused history is rejected.
- Existing checks reject an incomplete chooser set, missing focal identities, intermediate row loss, and altered cached outputs. A one-million-row, 25,000-focal-row forced-spill test passes the compact join and exact focal Parquet round trip.
- Both scenarios match independent explicit-account-dummy least squares for tested coefficients. Whole-account cross-products and cluster-score covariance match full-sample calculations. Each scenario's covariance uses its own coefficients. Never-granters remain in the fixture.
- Full synthetic integration completes all 20 models, 200 contrasts, and 100 paired comparisons, with identical scenario samples. Resume produces a byte-identical coefficient CSV.
- The no-wait test makes any reservation lookup fail and confirms that worker allocation still returns immediately. Duplicate/dependency locks remain in production.
- `repetition.py` and `ANALYSIS_AMENDMENT.md` are byte-identical to the previous package. All Python files parse, the launcher passes Bash syntax checking, and the final package manifest is checked at startup.

The larger annotation test emitted DuckDB deprecation warnings for the test harness's `fetch_arrow_table` calls and exited successfully. No warnings were suppressed. These tests do not establish that December's production failure is solved on the Mac; the successful first rebuilt month and its saved checks establish that next step.

The launcher runs `run.py --self-test`. Optional extended commands are `python test_partitions.py --large`, `python test_resume.py --spill-check`, and `python test_sensitivity.py --integration`. Manual testing before the supplied launch command is unnecessary.
