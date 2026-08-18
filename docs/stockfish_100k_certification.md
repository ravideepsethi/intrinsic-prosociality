# Stockfish 100k fairness layer certification

## Status

The full locked 24-month Stockfish 100k fairness layer is certified complete.

Main sample:

- 2023-11 through 2025-10
- 24 months
- 47,587,020 timeout opportunities
- Stockfish 18
- 100,000 requested nodes
- 489 Parquet parts
- 47,587,020 successful evaluations
- 0 engine-error rows
- 47,587,020 distinct `game_id` values
- 0 duplicate `game_id` rows

The engine-design invariant is:

`sf100k_nodes_requested == 100000`

in every certified Parquet file.

`sf100k_nodes_searched` is engine telemetry and is not required to equal
exactly 100,000.

## Certified block totals

| Block | Months | Rows |
|---|---|---:|
| Early | 2023-11–2024-09 | 21,600,308 |
| Bridge | 2024-10–2025-07 | 20,175,915 |
| Late | 2025-08–2025-10 | 5,810,797 |
| **Total** | **2023-11–2025-10** | **47,587,020** |

## Production and audit code

Exact historical production/audit scripts are preserved under:

`code/stockfish_100k/`

The principal production runner is:

`080_stockfish100k_existing_11m_resumable.py`

The final full-sample audit and corrective review scripts are:

- `084_audit_full_24m_sf100k.py`
- `085_review_full_24m_sf100k_audit_no_duckdb.py`

## Certification provenance

The exact certification receipt used to close the layer is preserved at:

`provenance/stockfish_100k/summary_sf100k_full_24m_CERTIFIED.json`

The historical machine-specific Parquet path list is preserved at:

`provenance/stockfish_100k/sf100k_full_24m_parquet_paths_MACHINE_SPECIFIC.txt`

That path list documents the production machine layout. It is provenance rather
than a portable replication interface.

## Important interpretation

An earlier audit returned `needs_review`. This did **not** indicate an engine or
data failure.

The earlier audit incorrectly treated all node-like fields, including
`sf100k_nodes_searched`, as if they had to equal exactly 100,000.

The final certification uses the correct design invariant:

`sf100k_nodes_requested == 100000`

All 489 files satisfy that invariant.

## Downstream status

The Stockfish layer is closed and should not be recomputed for the locked
24-month main sample.

Paper-facing analyses should use this certified 100k layer rather than older
10k or partial 14-month layers.
