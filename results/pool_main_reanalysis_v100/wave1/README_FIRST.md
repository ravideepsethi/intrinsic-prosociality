# Pool-main reanalysis — Wave 1

This package re-estimates the analyses that can be rebuilt directly from the newly selected 24-month panel. It does **not** treat any former-sample result as current merely because an old output exists.

## Selected sample

The bundled certified report fixes the main predicate as:

```text
source = 'pool' AND previous_classification_status = 'not_mutually_adjacent_observed'
```

| Quantity | Certified value |
|---|---:|
| Opportunities | 41,534,331 |
| Kind draws | 570,091 |
| Fair-region opportunities | 15,207,423 |
| Fair-region kind draws | 419,463 |
| Choosers | 3,224,173 |
| Months | 24 (2023-11 through 2025-10) |

This certifies an **observed mutual-adjacency screen**. It does not certify that every literal end-to-start immediate rematch has been removed. Outputs preserve that distinction.

## What this wave rebuilds

1. Stage-08 core descriptive tables, board-merit/desert results, game-stage models, favorable/costly reduced forms, chooser persistence, and split-half outputs.
2. Stage-09 panel robustness, density/support, subgroup, cutoff, exact-zero, and economic-magnitude diagnostics.
3. Rating-gap, expected-score, K/RD decomposition and diagnostic plots.
4. Parquet-first nonparametric relative-strength closure and plots.
5. Controlled reference-price diagnostic using the v1.1.0 model and corrected v1.1.1 display.

The public Stage-08 and Stage-09 producers are byte-identical to the scripts inspected at repository commit `0dc981cbc6da157d365015a95f2b7157ecda4859`. The later structural packages retain their exact supplied bytes. The adapters replace only former-sample authority constants and attach the new sample receipt; they do not change estimands.

## Run on the Mac that has XT_Pro attached

Double-click `RUN_WAVE1.command`, or run:

```bash
cd /Users/u6025368/Desktop/Lichess_Desktop/Pool_Main_Sample_Reanalysis_Wave1_v1_0_0
chmod +x RUN_WAVE1.command
./RUN_WAVE1.command
```

Defaults are eight DuckDB/hash threads, four model workers, a 12 GB coordinator limit, a 2.5 GB per-worker limit, and a 45 GiB free-space gate. Every concurrency setting is capped at ten. Override with environment variables such as `POOL_MAIN_THREADS=10` only if the machine has enough memory.

The launcher checks every package byte, selects or creates an isolated compatible Python environment, runs deterministic offline tests, authenticates all 24 panel Parquets, and then starts the resumable stages. No Lichess or other API request is made.

Planning range: several hours on an external SSD. Hashing, fixed-effect models, available RAM, and disk spill can move the total substantially. The K/RD producer is the least granular restart point; preserve any stopped folder and rerun with a fresh `--private-base` if that stage stops before its receipt.

On success, upload these two newly created files from `/Users/u6025368/Desktop/Lichess_Desktop`:

```text
POOL_MAIN_REANALYSIS_WAVE1_RESULTS_<UTC>.zip
POOL_MAIN_REANALYSIS_WAVE1_RESULTS_<UTC>.zip.sha256
```

The transfer ZIP contains aggregate/public results, executed source, receipts, manifests, and the reset ledger. It excludes chooser/game-level private caches and DuckDB work files.

## Important scope boundary

The chronology-dependent dynamics, repeat/dyad work, Campaign/C7 analyses, chooser-leniency design, Patron matching, and manuscript-wide figures/tables remain stale after Wave 1. They need rebuilt histories or matches under the selected sample and are intentionally blocked from inheriting old estimates. See `FULL_RESET_SCOPE.md`.

