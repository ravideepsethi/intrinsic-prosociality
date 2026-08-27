# Stage 09 extensions design

## Purpose

Stage 09 advances the paper beyond the certified Stage 08 core results without
altering the frozen Stage 07 analysis panel or the Stage 08 estimands. It has
two separable tracks:

1. panel-only robustness using the certified 24-month, Stockfish 18 / 100,000
   node panel; and
2. opening familiarity, using an authenticated legacy seed plus a resumable
   acquisition plan for the missing game metadata.

Patron/profile analysis is a separate external-input extension. Its ongoing API
acquisition is not part of this Stage 09 repository checkpoint.

## Frozen upstream inputs

- Stage 07 status: `STAGE07_24M_CERTIFIED_OK`
- Stage 07 success SHA-256:
  `8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7`
- Stage 07 producer SHA-256:
  `0411d4061ea9831c20449208a9782aaf668e160139918d106a2b7d63aaa56e6e`
- Stage 08 status: `STAGE08_CORE_24M_CERTIFIED_OK`
- Stage 08 success SHA-256:
  `a2fd1a868299cba8499de1e72365dbeb4e49ec77768e01e8af84f58f3ceac958`
- Stage 08 producer SHA-256:
  `e9dd80c52da5ffef3d406c3af25912bd924f6423f123ca535cf4077cb039c41f`
- Stage 08 provenance Git commit:
  `a7ce86a06c406cf7cfbeb4927cdf40ba5bce4bee`

Every Stage 09 producer fails closed if its required upstream authorities
change.

## Panel robustness producer

`09_build_panel_robustness.py` produces:

- running-variable density, local symmetry, support, and heaping diagnostics;
- exact-zero payoff descriptives and sensitivity models;
- speed, chooser-rating-tier, and tournament-status rates and contrasts;
- chooser-fixed-effect, chooser-clustered zero-threshold models by subgroup;
- nonoverlapping engine-evaluation cutoff sensitivity;
- rating-point magnitudes; and
- clearly labeled descriptive excess-kindness counts.

The standard fair definition is disconnected-player evaluation at least -100
centipawns. The paper-facing favorable/non-loss definition is
`chooser_draw_payoff_v2 >= 0`.

Density, heaping, and excess-count results are diagnostics and descriptive
benchmarks, not standalone causal estimands. The Stage 08 placebo-cutoff pattern
and the Stage 09 density evidence do not justify describing the zero threshold
as a uniquely located regression discontinuity.

## Exact-zero policy

The certified panel contains 244,300 standard-fair observations at exactly zero
chooser draw payoff. The primary favorable/non-loss definition remains
substantively appropriate, but exact zero is not silently relied on for the
result. Stage 09 v1.1 adds models that:

1. exclude exact-zero observations; and
2. treat exact zero as a separate category, with strictly negative payoff
   omitted.

This sensitivity is part of the certified panel-robustness output.

## Opening-familiarity producers

### Plan preparation

`09_prepare_opening_familiarity.py` makes no API calls. It authenticates the
legacy one-year mapping, recovers the old inclusion rule by exact game-ID
equality, copies the reusable mapping to the external research volume, and
constructs the full deterministic target and request catalogs.

The certified rule is `ply_count <= 10`. The plan contains 4,737,283 targets:
2,157,351 reusable seed rows and 2,579,932 rows requiring metadata acquisition.
The missing targets form 8,600 requests of at most 300 game IDs and 22 numbered
macro-batches of at most 120,000 IDs.

### Metadata acquisition

`09_fetch_opening_metadata.py` is a single-request, resumable client for
`POST https://lichess.org/api/games/export/_ids`. It preserves exact response
bytes, normalized returned/nonreturned rows, per-request receipts, and a
completion ledger. It supports complete-catalog ascending or descending
traversal and peer ledgers for two-laptop coordination.

The default fixed pause is zero and concurrency is one. On HTTP 429 it honors
`Retry-After` when supplied; otherwise it uses exponential backoff beginning at
60 seconds. Opening acquisition must not run concurrently with the active
patron/profile acquisition.

### Analysis

`09_analyze_opening_familiarity.py` implements prior-calendar-month ECO and
named-opening familiarity. It reports monthly and pooled rates and estimates
pooled, chooser-fixed-effect, and month-fixed-effect linear probability models,
clustered by chooser. The full 24-month result remains pending until the missing
opening metadata are acquired and audited.

## Repository checkpoint rule

This checkpoint freezes the fully certified panel-only Stage 09 output and
versions all four audited Stage 09 producers. It also records a sanitized,
compact certification of the opening target plan. It does **not** certify the
full opening-familiarity result and does not claim that all Stage 09 extensions
are complete.

Only scripts, documentation, compact certified receipts, output hashes, and
key-result summaries belong in Git. Parquet files, target game-ID catalogs, raw
API responses, completion ledgers, caches, and row-level research data remain
on the external research volume.

## Remaining gates

1. Complete and audit the patron/profile acquisition and analysis.
2. After the profile client is inactive, complete and audit opening metadata.
3. Run and certify the full 24-month opening-familiarity analysis.
4. Reconstruct reentry from a separately frozen chronological source contract.
5. Redesign post-sample temporal validation around the current sample end and
   later interface/rule changes.
6. Freeze publication rendering only after the remaining extension estimates
   are final.
