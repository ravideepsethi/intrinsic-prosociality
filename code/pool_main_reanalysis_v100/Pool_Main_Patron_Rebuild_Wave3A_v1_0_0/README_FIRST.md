# Patron Wave 3A: new histories, matches, and August coverage

Run `RUN_WAVE3A.command` using the command in `RUN_COMMAND.txt`. Expected elapsed time is **15–40 minutes**, an estimate for the previous 10-core machine, 12-GB DuckDB limit and external SSD. The full panel is only on your computer; this package has been tested on synthetic data, not timed on the full panel.

This is the first stage of the Patron rebuild. It completes reusable chooser histories and deterministic target matches on the new 41,534,331-row sample. It then checks which target accounts were covered by the fixed August profile acquisition. It **does not estimate Patron coefficients**, use the API, or substitute new profile dates.

The August snapshot was collected for the old matched sample. It contains all old any-kind accounts and selected never-kind controls, not every chooser. Some old kind accounts become never-kind under the new predicate. Simply rematching within the cached profiles would therefore change the control population. The coverage and old-to-new role tables make that issue measurable before the outcome analysis is specified.

## What runs

1. Authenticate the bundled main-sample authority, all 24 exact monthly files, the fixed profile snapshot, its audit manifest, and the old acquisition success receipt.
2. Invoke the original acquisition producer's chooser-summary and matching functions unchanged, using its original SHA-256 seed. The new certified sample replaces the old Stage-07 input authority; the old producer's full-panel entry point is not called.
3. Freeze all-any-kind and never-kind target matches within fair-opportunity-bin × modal-speed cells, up to three controls without replacement. Identify the fair-kind-focal subset intended for the primary comparison. Accounts without three controls remain explicitly counted.
4. Decode only six profile columns: normalized identity, return flag, acquisition role, match cell, stored focal identity, and control rank. Report target coverage, queried nonreturns, old/new roles, match support and retention of original groups. No Patron status or profile covariate column is decoded.
5. Return aggregate tables and receipts in a checksummed ZIP. All chooser-level files remain in private project state.

The original Stage-10 contract is included as provenance. Its old-sample numbers are not applied to the reset. This is a post-result sample reset and design/coverage diagnostic, not a preregistration or a certification of new Patron results.

## Reading the gate

`BLOCKED_INCOMPLETE_AUGUST_PROFILE_COVERAGE` means at least one target account was never queried in August. It is a completed diagnostic, not a script failure. We must define a justified historical-cohort analysis or a separately dated new acquisition before proceeding; silently dropping unqueried accounts is not equivalent to the planned new-population comparison.

`PASS_PLANNED_MEMBERSHIP_ONLY` means the target accounts were all included in the August acquisition plan. It does not certify the models or make nonreturns non-Patrons. Returned-profile attrition, remaining covariate construction and the frozen estimation family still follow.

`original_group_retention_diagnostic.tsv` describes original acquired groups with a focal chooser still fair-kind under the new predicate. It measures potential retained-cohort support without selecting that alternative as the main analysis.

## Restart and outputs

Successful stages are checksum-verified and reused. An interrupted current stage restarts; its unfinished directory is retained. Concurrent execution of the same configuration is prevented. This run creates its own `wave3a_patron` directories and preserves prior-wave files.

- Private: `derived/replication/pool_main_reanalysis_v100_PRIVATE/wave3a_patron/<configuration>/`
- Aggregate: `output/pool_main_reanalysis_v100/wave3a_patron/<configuration>/`
- Return ZIP and sidecar: `~/Desktop/Lichess_Desktop/POOL_MAIN_PATRON_WAVE3A_RESULTS_*.zip` and `.zip.sha256`.

Upload the two files printed when the command completes. The existing Wave-1 environment is preferred; dependencies are not installed or changed. Tested here with DuckDB 1.5.5 and PyArrow 25.0.1, matching the versions reported in the preceding successful Mac run. Runtime versions and source hashes are recorded in every checkpoint configuration.
