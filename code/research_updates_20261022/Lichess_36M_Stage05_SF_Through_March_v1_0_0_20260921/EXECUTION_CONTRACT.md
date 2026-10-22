# Execution contract

## Scientific invariants

- Opportunity membership requires API `status == timeout`; `outoftime` is
  excluded.
- The exact Stage-01/API target-ID sets must agree for every month.
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

## Safety and restartability

- Stage-01 and API source files are read-only.
- Every monthly Stage-05 output is written to an isolated partial directory,
  fully audited, and atomically published.
- Existing checkpoints are reused only if source-set and output hashes match.
- Stockfish output is written in 100,000-row ZSTD Parquet parts with individual
  success receipts and SHA-256 hashes.
- Interrupted or inconsistent Stockfish parts are quarantined on restart.
- Certified 24-month outputs are not modified.
- Outputs use new `derived/replication_36m` roots.

## Worker policy

- Stage-05 uses up to ten DuckDB threads.
- Stockfish uses ten worker processes by default, each with one engine thread.
- Numerical-library thread counts are fixed at one to prevent oversubscription.
- The Lichess API is never parallelized.

