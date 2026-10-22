# Preflight review — 20 September 2026

The returned v1.0.1 preflight completed successfully in 50.51 seconds. Its ZIP checksum and archive integrity passed; its package manifest exactly matches the delivered release. It deliberately did not run the event scan, so there are no new outage candidates or behavioural estimates in this report.

The directory parser now locates all eleven legacy months. Every table uses `white_name` and `black_name`, which the loader did not yet recognise. These fields are strings in the returned footers. Thus the earlier missing-field message described a mapping omission in the supplied code, not absent player-name columns in the data.

All eleven table row counts match the frozen historical monthly inventory. Their total is 78,512,947. Adding them to the existing ten Stage04 months gives an expected raw input of 149,959,526 records across November 2023–July 2025. Final usable counts and month acceptance remain subject to the full record-level audits. August–October 2025 are still unavailable to the scanner; this report does not establish that the user's wider project lacks those months.

v1.0.2 adds the two legacy aliases and retains conflict detection, identical case/whitespace normalization, the fixed player split, count checks, timing checks and outcome-blind projection. It does not change detection thresholds. Its supplied tests compare synthetic records in the exact returned 14-field legacy schema with equivalent modern records through the actual aggregation pipeline, including identical player folds and minute counts. They also verify that disagreement between legacy and modern name columns is rejected.

Run the full scan next. Additional coverage can change the ranked top 30 and reference baselines; preserve the original candidate list as the first exploratory scan. No incident has been independently confirmed by this preflight. The scientific next step remains incident verification and checking whether players could use the grant/claim interface, followed by board-state and transmission analyses where the sample supports them.

Reviewed input: `DISRUPTION_SCAN_REPORT_20260920T144544626722Z.zip`.

SHA-256: `f109e06d9db1f580e06046e3b33ea52e02fdae08fcb97e42c757e37d07f5c375`.
