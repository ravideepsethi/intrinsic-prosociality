# Intrinsic Prosociality

Replication code and documentation for:

**The Structure of Intrinsic Prosociality: Field Evidence from Online Chess**

This repository is currently under active construction while the empirical analysis is
being expanded to a two-year main sample.

## Current research design

- Main sample: November 1, 2023 through October 31, 2025.
- Setting: discretionary resolution of opponent disconnections in rated games on Lichess.
- Final paper-facing board evaluation: Stockfish 18 at 100,000 nodes.
- Planned deep engine audit: Stockfish 18 at 1,000,000 nodes on a sampled audit.

The repository is being built in parallel with the empirical reconstruction so that the
final paper can be reproduced from a clean, documented pipeline rather than from
exploratory scripts.

## Repository structure

`code/` contains the canonical numbered replication stages currently available.

Current stages include:

- `00_acquire_raw_data.py` — acquire and verify monthly Lichess PGN archives.
- `01_extract_pgn_candidate_parquets.py` — extract PGN time-forfeit candidates.
- `02_extract_rating_replay_inputs.py` — construct compact all-game rating-replay inputs.
- `03_delete_verified_raw_pgns.py` — audited cleanup of verified raw archives.
- `04_enrich_timeout_candidates.py` — enrich candidate games through the Lichess API.
- `04b_normalize_legacy_stage04_late.py` — normalize audited legacy late-period API material.
- `04c_reconcile_stage04_24m.py` — reconcile the 24-month API-enrichment layer.
- `05_build_timeout_opportunity_panel.py` — construct the canonical timeout-opportunity panel.

`operations/` contains operational scripts needed to document or reproduce production
workflows.

`manifests/` contains small provenance and checksum files suitable for version control.

## Data

The full raw and derived datasets are intentionally **not stored in this Git repository**.

Raw Lichess standard-rated PGN archives are publicly reacquirable. The replication
pipeline begins with a checkpointed acquisition script that records and verifies the
source material.

Large API responses, Parquet datasets, engine outputs, caches, and intermediate
analysis products are also kept outside Git. The final replication release will document
which derived materials can be deposited separately and how all remaining inputs can be
reconstructed.

## Reproducibility principles

Canonical production stages are designed to provide, where applicable:

- explicit input and output contracts;
- deterministic ordering and partitioning;
- dry-run versus execution modes;
- restartable checkpoints;
- structured manifests and receipts;
- input, script, and output hashes;
- row-count, coverage, uniqueness, and schema checks;
- software and dependency information; and
- post-run verification.

## Status

**Work in progress.** The repository should not yet be treated as the final replication
archive for the paper.
