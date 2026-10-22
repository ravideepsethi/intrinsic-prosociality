# v1.0.2 — Compact download plan and progress

The work-Mac status snapshots showed 1,474 to 1,508 plan files in 74 seconds,
with only about 0.38 seconds of additional CPU time. The run was progressing,
but creating thousands of small files was slow. The underlying filesystem or
device cause was not diagnosed; no drive-format assumption is made here.

Changes:

- Write one Parquet per nonempty source month: 22 instead of 7,047 files.
- Retain the exact old per-month hash sort, 300-game boundaries and API order.
- Store one row group per API batch and a digest of all decoded target values.
- Keep one monthly file open in recovery; check its full hash on first use,
  its signature around reads, and every batch's value digest before use.
- Continue authenticating the full plan checkpoint and the original inputs.
- Reuse complete full-move API responses independently of code/plan format.
- Print progress during plan preparation and for every recovery batch, with
  a heartbeat during longer plan and recovery operations.

This is a file-layout and progress-reporting change. The dataset, weights,
node budget, engine settings and interpretation remain fixed. DESIGN.md is
kept byte-for-byte from the original release. Old incomplete plan files remain
untouched. New code has a new configuration; no old replay/engine completion
receipt is relabelled as a new-code result.

All 27 tests pass on Python 3.12.14 and 3.13.15, using synthetic exports and a
fake UCI engine. Added tests compare batch contents to an independent old-order
reference, include an empty month and both partial/full batches, reject pointer
and snapshot corruption, and verify reuse of original-format response caches.
No private Mac frame, real API request or real Stockfish search was run here.

## v1.0.1 — Python 3.13 worker cleanup

Python 3.13's multiprocessing bootstrap joins threads before exit finalizers.
The old initializer kept python-chess's non-daemon UCI thread alive until a
multiprocessing finalizer ran. That circular wait stalled pool shutdown.

Source checked: CPython v3.13.9,
https://github.com/python/cpython/blob/v3.13.9/Lib/multiprocessing/process.py .
The behavior was also reproduced with the unmodified v1.0.0 full parallel test
on Python 3.13.15. A diagnostic stack showed ProcessPoolExecutor.shutdown
waiting for worker joins. The harness stopped that test after 12 seconds.
The corrected identical test finished in 0.663 seconds on the same interpreter.

Changes:

- Keep only the engine command and score cache in the pool initializer.
- Open an engine lazily when a batch needs an uncached position score.
- Close and await its subprocess explicitly in the batch's finally block.
- Preserve the 4,096-entry per-worker FEN/color cache across batches.
- Add regression coverage for thread-first shutdown and a failed-batch retry.
- Bound offline tests at 180 seconds, with stack diagnostics after 45 seconds.
- Print the verified Stockfish identity and requested worker/node settings.

Stockfish 18, 100,000 requested nodes per search, one engine thread, Hash=64 MB,
the fixed target frame, score definitions and API request policy are unchanged.
The standard launch uses ten workers. No real API or Stockfish run was performed
in this validation environment; synthetic exports and a UCI fixture were used.

DESIGN.md is preserved byte-for-byte from v1.0.0: this is a lifecycle fix, not a
change to the frozen analysis design. New code gets a new output configuration;
exact full-move API responses can still be reused independently of that code.
