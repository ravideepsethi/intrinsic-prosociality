# A2 history input contract

The retrieved artifacts do not contain a verified feature file covering all frozen A2 rivals. The default run therefore marks this input pending and completes the feasible diagnostics. The source-readiness report inventories existing chronology candidates so the next producer can project and aggregate them once for A2, A5, A8 and B3. It never initiates a 7.76-billion-row scan.

Before producing history, verify the current chronology manifest, ID mapping, coverage, result/status semantics and cutoff convention. A game's eventual disconnection outcome must already be known before the focal game starts; sorting by start time alone can leak outcomes from unfinished games. Restrict the numerator/denominator to the same stated population. Archive boundary gaps and unavailable history must set coverage false. Any history beginning after account activity began yields observed-history totals, not lifetime totals.

The optional argument is `--history-manifest /absolute/path/to/manifest.json`. The manifest must specify:

```json
{
  "contract": "KAC_A2_HISTORY_V1",
  "target_run_key": "c539ba215e708b2218662d0fcbe507655abbb705ed13c5179c6601329036ce40",
  "sample_fingerprint": "a17c89d750cb4fdfdf84f950859e45c58b19996efae02045def68285e305cf30",
  "disconnection_definition": "active_resolution_timeout_all_sources",
  "denominator_definition": "all_rated_standard_live_starts",
  "focal_game_excluded": true,
  "completion_known_before_focal_start": true,
  "window90_days": 90,
  "prepanel_end_utc": "2023-11-01T00:00:00Z",
  "producer_code_sha256": "ACTUAL_PRODUCER_HASH_REQUIRED",
  "source_authentication": {"manifest_sha256": "ACTUAL_SOURCE_MANIFEST_HASH_REQUIRED", "audit_report": "ACTUAL_AUDIT_REFERENCE_REQUIRED"},
  "parquet": "features.parquet",
  "parquet_sha256": "ACTUAL_FEATURE_HASH_REQUIRED"
}
```

These placeholders are documentation, not a ready manifest. Do not make declarations just to pass the adapter.

`features.parquet` must have exactly one row for each of the 260,863 frozen game IDs. Required columns: `game_id`, `asof_start_ms`, `prior90_disconnections`, `prior90_starts`, `prior90_complete`, `prepanel_disconnections`, `prepanel_starts`, `prepanel_complete`. Counts are nonnegative integers; coverage flags are booleans; cutoffs must equal the saved focal start. Zero-start rates receive zero with a separate zero-start flag; uncovered rates remain missing and do not enter supported history comparisons. Per-account IDs need not be exported into this feature file if linkage is audited in the producer.

The adapter verifies file hash, target support, counts, cutoffs and declared construction. These checks cannot independently prove the upstream semantic declarations. Preserve the audited producer and source manifest. A history input changes the A2 analysis identity and writes a new result directory, while reusing the original expensive move/engine checkpoints.
