# Inputs, provenance, and restart contracts

## Pinned provenance

| Input | SHA-256 |
| --- | --- |
| Corrected Color_RD110 prediction result, 26 September | `d1e0e507b80c2c12cc969cd14c6dec51ae1934691adc4ad4aa38f69e21577a99` |
| Repaired mechanism/RD audit result | `8bcda7730c8ea1ee994bd6f3884092046dca6c718f7fb8dc6171b3c30d2fb505` |
| Original mechanism package identity | `93131d964e8e01891f9094cf0482124465bf90079dd6b0b5b531c0aaa2d6e4fc` |
| Unchanged shared Receipt_IV_Cohort_Extension_v1_0_0 ZIP | `226906ee03b0cec00234b4b86f74197ac2b2ced377999c13ab16ed0d6080308c` |
| Parallel Color_Model_Discrimination_v1_0_2 ZIP inspected for context | `e6be23fe944571b0b10b182f3c92cafb16afb2ccbc1460ba8e6ec2eb474f273e` |

The corrected prediction result is a provenance reference, not an input that must be unpacked on the Mac. This package embeds the necessary frozen full-fit coefficients, pre-policy input hashes, and compatibility diagnostics. The parallel discrimination package is not executed and its caches are not overwritten.

## Required completed project products

All paths below are relative to `/Volumes/XT_Pro/lichess_kindness`.

| Product | Contract |
| --- | --- |
| `derived/replication/mechanism_separation_v100_PRIVATE/analysis/YYYY-MM.parquet` | 24 monthly 2023-11–2025-10 files pinned by bytes and SHA in `authority/mechanism_reference.json`; producer RUN_IDENTITY must match. |
| Same root `needed_users.parquet` and `history_summary/` | Original receipt and needed-user stamp bind each reusable summary; selected cached counts are copied, never edited. |
| `derived/replication_36m/color_change_firstpass_v100/dose/month=YYYY-MM/opportunities.parquet` | November–January local completion receipts bind dose files. |
| Same first-pass root `replay/speed=.../month=.../targets.parquet` | Five speed-specific completion receipts per month; actual-stratum payoff and game identity checks run on the joined narrow states. No replay is performed. |
| `derived/replication_36m/receipt_iv_history_extension_v100_PRIVATE` | Reviewed ready contract and completed opportunity projections; the original shared producer validates history/namespace/bridge contracts when needed. |
| `derived/replication_36m/receipt_iv_cohort_extension_v100_PRIVATE` | Original source, chronology, adjacency, and membership checkpoints; the wrapper uses the producer's original code signature and key construction. |
| Canonical rated-game chronology | Historical partitions inventoried in `authority/chronology.tsv`; new months in the shared metadata; schemas, row counts, byte counts, and consumption fingerprints checked. |

The ready-history and first-pass local receipt chains bind bytes on the user's machine. The new package does not pretend that a public aggregate ZIP independently pins every local receipt. Completion identities, one-to-one IDs, player roles, start times, speed, evaluation, stage, displayed ratings, grants, and actual-stratum predictions are checked before use.

The fixed roster is built by the new color code. Shared IV membership by itself is not a regular cohort. The output private manifest is `COLOR_MATCHED_COHORT_BUILD_V1`; it does not mint a `MECHANISM_COLOR_INPUTS_V2` certification. Its formal mechanics censor remains null.

## Restart behavior

The new cache is separate from every prior analysis. Checkpoints commit atomically and bind the code signature and input snapshots. Output bytes are verified. A mismatch stops for review; a missing receipt permits an unfinished stage to be rerun. File authentication reuses hashes only when the recorded local fingerprint is unchanged. The inherited original history summaries use their producer's original path/size/mtime lineage plus their stored byte hashes; this is not an independent rehash of every previously reviewed chronology archive.

The shared IV `run.lock` is held while using or finishing membership. A completed current membership chain is reused; otherwise the unchanged source/adjacency producer resumes in its original directory. The wrapper never runs IV score jobs. At least 32 GiB free space is required before completing unfinished shared chronology projection; additional new-color scratch space depends on cohort scope and spill behavior. Completed old caches are not removed.

Aggregate results include code/plan identity, environment versions, gating decisions, cohort and sample counts, matched predictions, and permitted conditional comparisons. Account IDs, game IDs, matched rows, roster files, and detailed errors remain private. Package checksums verify distributed code; they do not validate scientific assumptions.
