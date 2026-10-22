# April 2026 execution contract

## Scope

- Process only `2026-04`.
- Make no API requests.
- Do not modify the certified 24-month panel or the completed through-March
  Stockfish output root.
- Fail closed unless April's Stage-01 and API outputs are final and complete.

## Scientific invariants

- Opportunity membership requires API `status == timeout`; `outoftime` is
  excluded.
- The exact Stage-01/API target-ID sets must agree.
- The chooser is the PGN last mover; the disconnected player is the side to
  move after the final recorded move.
- The disconnected player must have at least five seconds remaining, or a
  missing recorded clock, under the locked Stage-05 definition.
- API outcome is derived from `winner` for timeout rows because the native
  enrichment's stored `is_draw` field encodes terminal status rather than
  timeout resolution.
- A kind draw is a timeout draw when the chooser retains mating material.
- Stockfish uses Stockfish 18, exactly 100,000 requested nodes, one engine
  thread per worker, 64 MiB hash per worker, and disconnected-player
  perspective.

## Authentication and restartability

- Stage-01 and API sources are read-only.
- The target count must agree across the API success receipt, API plan,
  Stage-01 Parquet, API Parquets, and distinct request ordinals.
- Every API unit checkpoint and response-Parquet hash is verified.
- Stage-05 is written to an isolated partial directory, audited, and atomically
  published.
- Existing checkpoints are reused only when source and output hashes match.
- Stockfish output uses 100,000-row ZSTD Parquet parts with individual success
  receipts and SHA-256 hashes.
- Interrupted or inconsistent Stockfish parts are quarantined on restart.
- Finalization rehashes every part and checks every Parquet footer row count.

## Worker policy

- Stage-05 uses up to ten DuckDB threads.
- Stockfish uses ten worker processes by default, each with one engine thread.
- Numerical-library thread counts are fixed at one.
- The Lichess API is never parallelized.

