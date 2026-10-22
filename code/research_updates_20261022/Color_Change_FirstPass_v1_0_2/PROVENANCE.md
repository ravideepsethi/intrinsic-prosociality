# Sources and limits

The package was built from the user's current project source documents, the August 18 Stage07 takeover handoff, the corrected C7 v1.0.6 runner, the September 4 36-month foundation and enrichment handoffs, and the September 24/25 completed Stockfish extension receipts.

Production source required on the Mac:

```text
replication_package/code/06_build_glicko2_cost_layer.py
e1a72414b4c4a18dca5b583b704cbbf97e0bff7de2a837e6ad85e078ecf00cca
```

The imported source supplies `inflate_rd`, `update_one`, checkpoint loading and replay-column definitions. The Python loop calls it directly. Optional Numba compiles those authenticated function bodies and must pass a sequential comparison against the scalar implementation before use. The vectorized payoff function is independently compared with scalar source updates in tests. No post-update regulator is removed or reapplied.

The bundled isolated-test reference has SHA-256:

```text
19ad528abb0f9d68bb0d5dcf39d1be529471cad149b064c0f63108a8a330cc1f
```

It is the earlier uploaded Stage06 version, before the finalizer's float32 sigma-ceiling QA repair recorded in the handoff. It is not the final production-source hash and cannot pass the production source check.

Certified Stage07 root receipt:

```text
derived/replication/analysis_panel_24m_sf100k/_SUCCESS.json
8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7
```

Its `monthly_outputs` pins each of the 24 monthly files. The earlier C7 physical authentication may be reused after checking its identity, file sizes, row metadata and modification-time conditions. Engine-extension parts require matching `.done.json` row counts, zero errors and SHA-256 hashes.

October 2023/2025 checkpoint **Parquet data hashes** were recovered from `dictionary_and_stage06_inventory.json` in the completed September 4 foundation bundle and are included in `vendor/checkpoint_authority.json`. The inventory's path points to JSON, but its `sha256` field is copied from that JSON's `sha256` field and identifies the Parquet. v1.0.0/v1.0.1 incorrectly interpreted it as the checksum of the JSON file itself. v1.0.2 corrects the target of the comparison; no checksum requirement is bypassed or weakened.

This interpretation was verified from the actual `inventory_dictionary_and_checkpoints` function in `foundation_36m.py`, SHA-256 `e9489165fe83e2893f7a069029be4bca2d6d816e452be9093aafcfe2dfc4f301`, from `Lichess_36M_Foundation_v1_0_0_20260904.zip`, SHA-256 `8157fd094434908e12345087034e7aacf0148bf6b96fc9569d685369a692abed`. An exact function excerpt is included in `vendor/foundation_inventory_source.txt`. The result inventory itself has SHA-256 `ef8305a3c3639c085f0fd9156cc8b688f2b2de4d4b40f8df5f446e7fbd97738b`.

Authentication now requires the independently recorded data hash, metadata's declared data hash, actual Parquet checksum, fixed formula policy, speed/month, row count and byte size to agree. It records the metadata-file checksum separately. The ten source-checkpoint checks run before replay, and the speed workers reuse the successful physical-authentication receipts when the source fingerprints still agree.

Known extension roots under `derived/replication_36m`:

- `stockfish100k_historical_reuse`: October 2023, November/December 2025, February 2026.
- `stockfish100k_extension_new_api`: September 2023, January/March 2026.
- `stockfish100k_extension_new_api_2026_04`: April 2026.

The v1.0.1 timestamp repair uses `lineage/historical_reuse_SUCCESS.json` from `Lichess_36M_Enrichment_SF_v1_0_1_20260904`. Its SHA-256 is `bf13562dd4b90440605057a7f50d829e4adb9264acbf49fe3120ec3c8bcecc25`. The exact relative paths, sizes and per-file hashes for all four historical-reuse months are reproduced in `vendor/historical_timestamp_sources.json`. Only game IDs and UTC timestamps are selected from these files. The August–December patched 10,000-node files are not a source of rating states or evaluations in this package.

If those original files are unavailable or lack supported timestamp columns, the resolver uses the already-existing `derived/glicko2_replay/rating_events_replay_sorted_v2_time/events_replay_sorted_time/speed=<speed>/month=<month>/part-00000.parquet` files. All five pools must exist. IDs are semi-joined to the target opportunity set; coverage must be exact and target IDs must be unique. This fallback records source path/size/mtime, rather than claiming an externally pinned checksum. Unrelated source rows are excluded before the uniqueness check.

The repair was prompted by `COLOR_FIRSTPASS_RESULT_20260925T171144Z.zip`, SHA-256 `a95e43ded9261f799042eee186daf5b9b85cc98046fd668937d0dab95b2efdc9`. Its failure occurred before replay. Its actual `FROZEN_PLAN.json` is included as `vendor/frozen_plan_v100.json` and checked against the current plan by a regression test. Package version and data-contract version are deliberately separate to preserve completed v1.0.0 outputs.

The checkpoint correction was prompted by `COLOR_FIRSTPASS_RESULT_20260925T185124Z.zip`, SHA-256 `d8e41ee8ef088b2e118cbd7c92f0d3d439c8b7c6ac4210f5688b70c5ac8c0b3f`. Its receipts confirm complete normalization of 32 months and 63,525,555 opportunities, with zero normalization failures. It contains no completed replay or behavioral estimates.

The replay event substrate and user dictionary are reused at their existing documented paths. Event-file SHA-256 values are recorded when months are computed. Restart reuse is bound to their size/mtime fingerprint and the chained checkpoint digest; the original source files are never rewritten.

Institutional dates follow the reviewed conversation: bracketed November 18 implementation convention, December 22 public announcement, January 7 further information, and an unverified January 30 grace-rule issue date. The script does not identify a deployment date from an issue timestamp.

All synthetic test data are created in temporary directories and excluded from the delivered result. Runtime estimates are planning ranges. No real project dataset was available in the development environment; no real-data estimate or validation success is claimed.
