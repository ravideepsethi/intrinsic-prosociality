# Pool main sample, 24 months — v1.0.0

Run this package on the work Mac with XT_Pro connected. It uses the completed
source/adjacency join to create the agreed main sample and initial descriptive
comparisons. The terminal command is in TERMINAL_COMMAND.txt.

## The sample decision

The main eligibility predicate is:

```sql
source = 'pool'
AND previous_classification_status = 'not_mutually_adjacent_observed'
```

This is a conservative screen based on the preceding observed games. Mutually
consecutive same-pair candidates are excluded regardless of their start-time gap.
Missing predecessors and ambiguous start order are also excluded from main.
Whether a pair plays again after the focal game does not determine eligibility.
No exact clock or end-to-start threshold is applied. The screen does not certify
literal immediate rematches, strangers, or random opponent assignment.

| Sample | Expected opportunities |
|---|---:|
| Original Stage07 | 47,587,020 |
| Pool | 44,138,221 |
| Main: pool and observed non-adjacency | 41,534,331 |
| Robustness: main plus missing predecessors | 41,889,951 |

Pool exclusions: 2,247,688 mutually adjacent candidates; 355,620 missing previous
classifications; 582 ambiguous-order cases. The robustness restores only the
355,620 missing-predecessor cases. These categories are mutually exclusive.

The main panel retains all board states. Use the existing analysis-specific
competitive restriction where required; do not apply it to the master panel.

## Completed source authority, including late 2025

| Month | Stage07 | Pool | Main |
|---|---:|---:|---:|
| 2025-08 | 1,930,170 | 1,791,836 | 1,695,692 |
| 2025-09 | 1,881,564 | 1,754,805 | 1,660,248 |
| 2025-10 | 1,999,063 | 1,860,545 | 1,761,386 |

All 24 months use the completed source union. The older recovery report is
included solely for its 24 original Stage07 file identities; its incomplete
source classifications are never consumed. The completed join's private
checkpoint ledger and source Parquet are authenticated against the uploaded
completion reports before analysis.

## Inputs

Under `/Volumes/XT_Pro/lichess_kindness`:

- `derived/replication/analysis_panel_24m_sf100k/month=YYYY-MM/analysis_panel.parquet`
- `derived/replication/game_source_24m_PRIVATE/complete_v100/source_by_game_id_24m.parquet`
- `output/rematch_source_join_v100/20260908T031408Z_6459_source_union_20260909`

The join input includes its SUMMARY, SUCCESS, authentication JSON, private
contract, checkpoint ledger, and 128 saved joined partitions. These exact inputs
must already exist. A mismatch stops the build with its cause; no substitute
input is silently chosen. Existing Stage07 columns and retained values are copied
directly. Existing evaluations and rating values are reused.

## Outputs

Private output root:

```text
/Volumes/XT_Pro/lichess_kindness/derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE
```

- `panel/month=YYYY-MM/analysis_panel.parquet`: 24 main panels, preserving all
  157 Stage07 columns and logical types. Row order is not an output contract.
- `eligibility/parts/partition_month=YYYY-MM/*.parquet`: exactly one row per
  original Stage07 game, with actual source/provenance, previous status, nullable
  adjacency flags, all three restricted-sample masks and main exclusion reason.
- `panel/month=YYYY-MM/_audit/chooser_presence.parquet`: private intermediate
  account membership needed for exact global distinct chooser counts.
- Per-stage `_DONE.json`, input receipts, sample definition and `_SUCCESS.json`.

Read the main panels using the exact pattern below, with Hive inference disabled:

```sql
SELECT * FROM read_parquet(
  '/Volumes/XT_Pro/lichess_kindness/derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE/panel/month=*/analysis_panel.parquet',
  hive_partitioning=false
);
```

Do not use a recursive wildcard for every Parquet in the output root: eligibility
and account audit files have different schemas. To construct a robustness panel,
join the all-ID eligibility mask to the original Stage07, not the main-only panel.

## The report to upload

The runner prints a report ZIP and its SHA256 sidecar, under:

```text
/Volumes/XT_Pro/lichess_kindness/output/pool_main_sample_24m_v100
```

Upload those two files. The report includes aggregate JSON and Parquet tables:

- Original/pool/main/robustness counts, kindness rates, competitive counts and
  kindness rates, distinct choosers, and means for ratings, opponent-minus-chooser
  rating, draw payoff, game plies and disconnected clock.
- The same measures by month.
- Board-state by game-stage counts/rates, speed counts/rates, and exclusion counts.
- Exact input/output hashes, logical schemas, sample definition and QA results.

Rates pool numerators and denominators. Continuous means use each variable's
finite observations, with missing/nonfinite counts reported. Global chooser
counts deduplicate across all months; monthly distinct counts are not summed.
Competitive/fair means `engine_eval_cp_disconnected >= -100`. Board-state bins
are <=-300, -299..-101, -100..100, 101..299, >=300 centipawns. Ply bins distinguish
0–1, exactly 2, 3–10 and >10 plies; they are not labelled “one move each.”

The ZIP contains aggregate results and file/schema receipts, not private game or
account records. These are unadjusted descriptions. No behavioural regression,
receipt sequence, propensity match, Patron analysis or production figure is rebuilt
by this package. Those are downstream steps after inspecting this sample report.
Full histories remain available for ratings, prior meetings, exposure construction,
censoring and activity denominators; opportunity filtering does not erase them.

## Runtime and restart

The launcher searches for an existing Python with DuckDB 1.5.4–1.5.x and PyArrow
18–25. If needed it creates a separate environment and installs the two packages;
it does not change the active conda environment. Set `POOL_MAIN_PYTHON` to an
absolute Python path to select an interpreter. The fixture tests run before the
production files are opened.

Defaults: 4 hashing workers, 8 DuckDB threads, 6GB DuckDB buffer limit, one monthly
panel at a time. Hashing and query phases are sequential; BLAS libraries use one
thread. DuckDB buffers do not represent a hard whole-process RAM ceiling. An
18 GiB Mac should have room for the process and the operating system with other
heavy jobs stopped. Smaller write buffers limit partition-writer memory.

Planning estimate: 30–120 minutes on an external SSD, with substantial uncertainty
from input size, drive speed and disk spill. This has not been timed on the work
Mac. The runner reports elapsed progress every 30 seconds during long stages.
It computes a conservative free-space budget from actual original-panel sizes
before starting large writes: 1.25 times their combined bytes plus 20 GiB, adjusted
for already completed output, with a 12 GiB minimum. The panels are full-schema
copies and require substantial disk space. No new Lichess requests are made.

Rerun the same terminal command to resume. Completed eligibility and monthly stages
are verified by hash and reused. An interrupted partial stage may leave a hidden
staging directory and is rebuilt separately; completed stages are not overwritten.
Do not edit inputs during the run. A second simultaneous builder for the same
output root is rejected by a lock. Changing code, input identities or dependency
versions requires a new output root; the old result is preserved.

Optional launcher settings: `POOL_MAIN_WORKERS`, `POOL_MAIN_THREADS`,
`POOL_MAIN_MEMORY`, `POOL_MAIN_OUTPUT`, `POOL_MAIN_REPORT_ROOT`, `POOL_MAIN_PROJECT`,
`POOL_MAIN_DESKTOP`. Settings for workers and threads accept 1–10. The default
output uses a new dedicated directory and does not replace the certified Stage07.

`POOL_MAIN_SAMPLE_24M_CERTIFIED_OK` certifies the stated source and observed
adjacency sample and its accounting, not the literal rematch interpretation.
