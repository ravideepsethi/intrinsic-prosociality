# Disruption_Scan_v1_0_2

Run the full disruption scan with the launcher and no extra argument. The returned v1.0.1 preflight established that all eleven legacy monthly files contain `white_name` and `black_name`. This release adds those two observed aliases; no new API calls or chess-engine work are needed.

Save the ZIP and its SHA-256 sidecar in `~/Desktop/Lichess_Desktop`. Verify the checksum, extract into a fresh staging directory, and execute `RUN_DISRUPTION.command`. The launcher reuses the AFE Python environment with pinned dependency versions. Defaults are four threads and a 6GB DuckDB limit. Initial dependency setup may download packages if that environment is missing or incompatible.

## What the preflight established

- The month-directory fix works: November 2023–September 2024 are all located.
- All eleven old tables have the same 14-field schema, including named players, `createdAt`, `lastMoveAt`, terminal status, speed, variant and rated status.
- Their monthly row counts exactly match the frozen historical inventory: 78,512,947 records in total.
- Together with the ten Stage04 months, the expected raw input is 149,959,526 records across November 2023–July 2025. This is an input count, not the final number passing filters.
- August–October 2025 still have no eligible canonical source located by this scanner. They are reported as unavailable rather than treated as zero events.

The earlier diagnostic message meant the loader lacked aliases, not that those files lacked player names. The correction is in `support.py`; the returned schema evidence is in `evidence/legacy_schema_report.json`. The full run still checks record identities, alias conflicts, timestamps, accounts and coverage before accepting a month.

## Analysis and safeguards

Detection thresholds, same-time weekly references, predetermined traffic adjustment and the discovery/validation player split are unchanged. Player names are lowercased and trimmed identically for both source formats. Conflicting non-null aliases fail the audit. Outcome fields are not projected into the detector.

This is an exploratory screen of a saved broad API time-forfeit frame, including ordinary clock expirations. It is not a census of physical disconnections. Neither replicated bursts nor last-move timestamps establish that an outage occurred or that kindness receipt was randomly assigned. See `DESIGN.md`.

The expanded list may differ from the original ten-month top 30 because additional months supply candidates and comparison periods. Match episodes by UTC time and window, not their rank-based E-number. The first scan remains a separate, frozen exploratory result. Its review and figures are retained as historical context.

## Outputs and reruns

Private monthly caches and timestamped attempts go under:

`/Volumes/XT_Pro/lichess_kindness/derived/replication/disruption_scan_v102_PRIVATE/`

This release writes a new cache tree. It preserves older results. Subsequent identical v1.0.2 runs verify and reuse its completed monthly caches.

Upload the two files printed with `UPLOAD:`:

- `DISRUPTION_SCAN_REPORT_<timestamp>.zip`
- its `.zip.sha256` sidecar.

The report contains candidate rankings and plots, a frozen discovery list, disjoint-account validation, timestamp and account audits, source coverage, available main-panel choice counts and an incident-review template. It contains no player names, game IDs, grant-rate estimates or transmission estimates. Source and private cache records stay on the Mac.

Optional arguments: `--preflight-only`, `--skip-traffic`, `--no-main-overlay`, `--top 50`. The recommended next run uses none of them. A heartbeat prints every 40 seconds during long operations.
