# Dynamic prosociality core: parallel execution note

Version: 1.0.0  
Date: 2026-08-22  
Applies to producer version: 1.0.2

## Scope

This note changes execution scheduling only. It does not revise the frozen
v1.0.1 analysis plan, the dated v1.0.2 arm-partition amendment, any estimand,
sample definition, model, randomization count, randomization-batch boundary,
seed, or multiplicity correction.

## Chronology scheduling

The 852 authenticated chronology Parquet files may be scanned concurrently.
Each worker reads only the three frozen columns (`utc_ms`, `white_id`, and
`black_id`) and writes the same file-specific activity and pair-minimum
checkpoints as the serial producer. Every checkpoint remains independently
authenticated by its input footer signature, output byte counts, and SHA-256
hashes. Final aggregation consumes checkpoints in canonical file-index order.

Parquet's internal scan threading is disabled inside a concurrent chronology
worker to prevent nested oversubscription. The launcher uses four file workers
by default. A rerun authenticates and skips completed files.

## B1 scheduling

The five frozen B1 randomization batches are independent because each batch has
its own already-frozen seed components `(20260821, start, stop)`. They may be
computed in separate processes. Each process loads the same certified B1
sample and cross-fitted propensity vector, uses one numerical-library thread,
and writes the same batch-specific NPZ and receipt. The parent authenticates
all five checkpoints and concatenates them in frozen start-index order.

The launcher uses five B1 processes by default. A rerun authenticates and skips
completed batches. Parallel and serial paths are required to be exactly equal
in the synthetic randomization self-test.

## Resource policy

DuckDB stages retain eight threads and a 12 GB memory limit. Chronology and B1
parallel phases do not overlap with DuckDB model stages. Private checkpoints
and account-level data remain on XT_Pro. No API request, Patron-data read, Git
mutation, or research-data transfer is introduced by this revision.
