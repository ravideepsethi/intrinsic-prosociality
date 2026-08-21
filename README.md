# Intrinsic Prosociality

Replication code and documentation for:

**The Structure of Intrinsic Prosociality: Field Evidence from Online Chess**

This repository is under active construction. The canonical two-year Stage 07
analysis panel, Stage 08 panel-only core results, and Stage 09 panel-robustness
results are now certified. External-input extensions remain in progress.

## Current research design

- Main sample: November 1, 2023 through October 31, 2025.
- Canonical opportunity sample: 47,587,020 unique games, including 669,503 kind draws.
- Stage 07 analysis panel: certified over all 24 months with 157 columns.
- Stage 08 core results: certified Tables 1–9 and analytical figure data.
- Stage 09 panel robustness: certified support, exact-zero, heterogeneity, cutoff, and magnitude results.
- Opening familiarity: target plan certified; metadata acquisition and full analysis remain pending.
- Patron/profile extension: 24-month profile acquisition remains in progress.
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
- `06_build_glicko2_cost_layer.py` — construct the canonical chooser-cost layer.
- `stockfish_100k/080_...py` through `085_...py` — build and certify the 100k-node engine layer.
- `07_build_analysis_panel.py` — join the frozen authorities into the certified 24-month panel.
- `08_make_core_paper_results.py` — produce the certified panel-only core paper results.
- `09_build_panel_robustness.py` — produce the certified Stage 09 panel-only robustness results.
- `09_prepare_opening_familiarity.py` — build and authenticate the 24-month opening target plan.
- `09_fetch_opening_metadata.py` — acquire missing opening metadata with resumable checkpoints.
- `09_analyze_opening_familiarity.py` — estimate opening-familiarity results after acquisition.

`operations/` contains operational scripts needed to document or reproduce production
workflows.

`manifests/` contains small provenance and checksum files suitable for version control.

`docs/` contains human-readable certification and design documentation.

`provenance/` contains small authenticated summaries, schemas, and path manifests; it does not contain research data.

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

**Work in progress.** Stages 00–08, the certified Stockfish 100k layer, the
47,587,020-row Stage 07 panel, the Stage 08 core results, and the Stage 09
panel-only robustness results are complete. The opening target plan is certified,
but opening metadata acquisition, full opening-familiarity analysis, patron/profile
analysis, post-sample holdouts, publication rendering, the planned deep-engine
audit, and final archival-data instructions remain in progress. The large research
datasets are not stored in this repository.
