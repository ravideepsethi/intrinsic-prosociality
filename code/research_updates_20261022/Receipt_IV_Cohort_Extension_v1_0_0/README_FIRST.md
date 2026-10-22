# Receipt IV cohort extension 1.0.0

This package performs the next offline data-building stages. It requires the completed history extension from September 26, 2026. Put the ZIP in `~/Desktop/Lichess_Desktop` and use the supplied terminal command.

It recovers explicit game-source labels from existing API archives and Parquets, extends the observed-adjacency screen, builds the added months' membership records, preserves the original 24-month main sample, and computes the original pair-excluded IV scores using the completed 32-month histories. It writes aggregate diagnostics and reusable private inputs. It does not estimate a behavioral effect.

## Work performed

1. Authenticate the completed 512 history shards, cross-fit reference arrays, November bridge and original main-sample membership. No successful history, timestamp, rating replay or Stockfish producer is rerun.
2. Scan the existing API locations on XT_Pro, the existing home output locations and Lichess_Desktop. The scanner handles native raw files and ZIP/TAR containers. Only an explicit top-level source on a matched game record can establish `pool`; `source_block`, event descriptions and rating-pool labels cannot. Check status, winner and creation time against the existing target metadata. When exact API creation milliseconds were not retained, check the PGN start second and disclose that weaker precision. Unknown, conflicting and malformed evidence remains unresolved. No network collection is performed.
3. Make a narrow pass over the 160 inventoried speed-month chronology partitions: 2,957,732,699 games in September 2023–April 2026. Include any additional speed partitions found in that same canonical root, matching the original census scope, and report them. This is an identity/start-order scan, not a rating replay. Preserve the original extraction filter for valid starts and nonmissing player IDs. For focal user-months, keep all events across speeds. For other user-file segments, retain the first and last two events. These boundary records preserve both nearest neighbours and the second-neighbour timestamps needed to detect tied ordering. Require file timestamps to lie in their stated month before using this compression. Then apply the original adjacency SQL unchanged in 128 user buckets.
4. Require exact agreement with all 2,015,809 original November 2023 previous-adjacency statuses using the original October 2023–November 2025 chronology scope. Compare recovered November source labels with the pinned original label layer wherever recovered. A disagreement stops assembly. The new months use the explicitly documented September 2023–April 2026 scope; missing predecessors stay unresolved. The original 24-month membership remains unchanged.
5. Write new membership records, unresolved-ID files and a uniform choice spine containing the original 41,534,331 main rows plus the added months' known eligible rows. New rating-state columns are deliberately left unattached, rather than filling unavailable RD values. The original target-state Parquets remain the source for a later authenticated attachment and targeted calibration.
6. Compute the original 7- and 30-day-lag scores for all competitive, realtime, arm-eligible candidate decisions, then report support among known main-sample candidates. Use strict month-start-minus-lag cutoffs, remove all history involving the focal pair, and reuse the completed references that exclude both roles' folds. The history boundary is September 2023; these extended scores do not replace the old IV analysis. Floors of five and ten refer to minimum prior decisions; the common sample has at least ten and finite scores. Both scores use all qualifying previous decisions, not just the last five or ten.

## Resources and restart

- Uses the project virtual environment, at most ten computational workers/threads, and an 8 GiB memory budget with two heavy processes. NumPy/Arrow auxiliary threading is capped. DuckDB may spill to XT_Pro. Python and OS overhead are outside DuckDB's allocation, so this is a budget rather than an RSS hard limit.
- Requires at least 32 GiB free before the chronology stage. Allow additional space for retained chronology witnesses, private outputs and spill; the production footprint and elapsed time have not been measured here. The scan is substantial. Logs show completed files, buckets and score shards, with a heartbeat every 30 seconds.
- Checkpoints are immutable and keyed by code, input fingerprints and hashes. Rerun the same command after interruption; completed stages are verified and reused. An interrupted partial directory is preserved. Never delete successful history/replay directories.
- A changed input or a failed November bridge stops the affected run. It still returns an aggregate status ZIP when the report directory can be written. Preserve the log. The package does not install dependencies or alter existing datasets.
- Optional additional existing source locations can be passed to `code/run.py` with repeated `--extra-source-root /absolute/path` arguments. No API token is needed.

## Outputs

Private work stays at `/Volumes/XT_Pro/lichess_kindness/derived/replication_36m/receipt_iv_cohort_extension_v100_PRIVATE`.

The final handoff is `READY_FOR_IV_COHORT_ASSEMBLY_PRIVATE.json`. It points to source, adjacency, membership and score receipts, including unresolved private IDs. The command places `RECEIPT_IV_COHORT_EXTENSION_<UTC>.zip` and its `.sha256` file in `~/Desktop/Lichess_Desktop`, beside the log. Return those files for review. They contain counts and diagnostics, not account IDs or raw API records.

## What still determines IV eligibility

These candidate inputs are not a final IV cohort. Complete source coverage must be assessed from the returned scan. First-observed-pair membership, the exposure stream and spacing must be constructed in their original order before administrative censoring. Targeted rating-state calibration, the broader incident denominator, a source-informed deployment censor, complete 90-day windows, and the later-choice color × post/nonreacher rule remain open. An issue date, merge date or archive endpoint does not establish deployment. No IV, reduced-form coefficient, exclusion-sensitivity estimate, power decision or MDE is generated by this package.

The completed first-pass review and history extension remain authoritative. The original 24-month estimates remain historical benchmarks; additional candidate rows alone do not establish a stronger or valid instrument.
