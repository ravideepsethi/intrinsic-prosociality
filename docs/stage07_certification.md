# Stage 07 24-month analysis-panel certification

**Certification status:** `STAGE07_24M_CERTIFIED_OK`
**Canonical sample:** November 2023 through October 2025
**Certification timestamp:** `2026-08-19T02:30:44Z`

## Scope

Stage 07 joins the three frozen one-row-per-game authorities by unique `game_id`:

- Stage 05 for opportunity, role, outcome, clock, speed, and mating material;
- Stage 06 for Glicko-2 hidden state and chooser cost/payoff variables; and
- certified Stockfish 18 at 100,000 requested nodes for engine evaluation and fairness.

The canonical machine-specific output root is:

```text
/Volumes/XT_Pro/lichess_kindness/derived/replication/analysis_panel_24m_sf100k
```

## Producer identity

- Script: `code/07_build_analysis_panel.py`
- Version: `1.3.0`
- SHA-256: `0411d4061ea9831c20449208a9782aaf668e160139918d106a2b7d63aaa56e6e`
- Production Git commit: `b73a7fbaf25ecd063d842bbc36f4efed7cd9ab24`
- Base authenticated commit: `86fbc10c6a255a62b4e071a1ee99bfd6539e85c8`

## Certified totals

| Quantity | Certified value |
| --- | ---: |
| Rows | 47,587,020 |
| Unique game IDs | 47,587,020 |
| Months | 24 |
| Output columns | 157 |
| Certified Stockfish parts | 489 |
| Kind draws | 669,503 |
| Chooser-loss rows retained | 75 |
| Both-ratingDiff-null rows retained | 268,386 |
| Fair rows (`eval >= -100`) | 17,328,130 |
| Clearly-worse rows (`eval <= -300`) | 26,090,163 |
| Excluded-middle rows | 4,168,727 |
| Draw payoff nonnegative | 22,737,519 |
| Draw payoff strictly positive | 22,075,834 |
| Draw payoff costly | 24,849,501 |
| Output size | 14,133,235,220 bytes (13.16 GiB) |

All asserted identity, uniqueness, coverage, join, FEN, turn, perspective,
engine, requested-node, evaluation, fairness, cost, and output-schema failure
counts are zero. The 24 outputs have one exact 157-column schema and 47,587,020
unique cross-month game IDs.

## Determinism and hashes

- Global certification summary SHA-256: `8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7`
- Combined ordered monthly-output manifest SHA-256: `86055e64c2dfcd7c4c631d67872f4448d43f7c15fb385e516c8ec9aa62b2302e`
- November 2023 canonical output SHA-256: `f156ac22c7a58f91e1cd32769bd68b12458e27dc5204a1a1ca0d371ee52c4645`
- November 2023 exactly reproduced the independently reviewed pilot output.

The combined manifest hash is calculated over canonical month and output-hash
pairs in month order. Individual monthly hashes are in
`provenance/stage07/month_status_stage07_24m.csv`.

## Repository-copy normalization

The certified production `month_status.csv` uses standard CSV CRLF line endings
and has source SHA-256 `ef6932bc39872e890232660cf2287d8ba1cafb724ff758945c64579f0627988e`. The repository copy normalizes only
those line endings to LF for clean text diffs; its SHA-256 is
`fd72f86b41fbc21ff8c5378c606fa6c07d2847f45589233aac26558400321fff`. All 25 parsed rows and every field value are identical.

## Terminal `Mate(0)` policy

Eleven terminal `Mate(0)` rows were retained. Each was parsed independently
with python-chess and required `chess.Board(FEN).is_checkmate()`, matching side
to move, disconnected-player perspective, mate ply zero, and disconnected-player
evaluation `-10000`. Missing searched-node/depth telemetry is permitted only
inside this validated set.

- `2023-11` — `Ae9kvUYD`
- `2023-12` — `EYRzyiO0`
- `2024-01` — `A7JP2D9Q`
- `2024-04` — `CoNNFmJG`
- `2024-04` — `jMbZNX59`
- `2024-04` — `umPSxK5u`
- `2024-06` — `8w2FSQX2`
- `2025-01` — `CeBMpkCH`
- `2025-01` — `QLhtmI0D`
- `2025-01` — `WBNv4l8K`
- `2025-10` — `s0IoNbk6`

## Optional Stockfish duplicate diagnostics

Stockfish carried optional convenience copies of a few non-engine fields. They
were not used for evaluation and never overwrite Stage 05, which remains the
authority. The full-sample field-row diagnostics are:

| Optional duplicate field | Mismatch rows | Observed value pair |
| --- | ---: | --- |
| `api_speed` | 225 | Stage 05 `ultrabullet`; duplicate `ultraBullet` |
| `api_status` | 0 | None |
| `chooser_has_mating_material` | 46 | Stage 05 `true`; duplicate `false` |
| `outcome_kind_draw` | 1 | Stage 05 `true`; duplicate `false` |
| `timeout_draw` | 0 | None |

These discrepancies are retained in monthly receipts and the consolidated QA
details. No row was dropped, imputed, or re-evaluated because of them.

## Paper-facing conventions

- Favorable/non-loss draw: `chooser_draw_payoff_v2 >= 0`.
- Strict-positive draw is retained as a diagnostic.
- Fair/competitive: disconnected-player evaluation `>= -100`.
- Clearly worse: disconnected-player evaluation `<= -300`.
- The interval `-299` through `-101` is the excluded middle.
- Chooser-cluster field: `chooser_username_norm`.
- Sample-specific bins, z-scores, fixed-effect codes, and bandwidth/donut
  indicators must be created downstream for the relevant analysis sample.

## Repository boundary and next step

Only small code, schema, hash, receipt-summary, and certification artifacts are
versioned. The 13.16 GiB Stage 07 Parquet panel is not stored in GitHub. The
machine-specific path list is provenance rather than a portable data deposit.

Stage 07 is frozen. Paper-facing results may now be built only from this
certified panel. The repository remains a work in progress until those results,
the planned deep-engine audit, and the final archival-data instructions are
complete.
