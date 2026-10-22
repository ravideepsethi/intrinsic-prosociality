# History identity diagnostic 1.0.0

The repetition sensitivity stopped in August 2024 at the identity check
`(1674961, 3, 3)`: 1,674,961 rows in the left join, three unmatched
chooser/game pairs, and three rows failing the time/speed comparison because
the joined history fields were missing. The last two counts are not evidence
of six different failures. The partial archive SHA-256 is
`324ae1fd300e3b765ebe154991ce869911dbd0cc44822f9ff2edc53868de102a`;
its six report hashes were verified.

This is a diagnostic, not a repaired repetition estimate. Do not restart the
unchanged repetition runner: it will reach the same gate with unchanged inputs.

## Run

Put this ZIP in `~/Desktop/Lichess_Desktop`, extract it into a fresh directory,
and run `bash RUN_DIAGNOSTIC.command --worker-budget 10 --io-workers 3`.
The launcher locates the existing Python environment; it installs nothing.

Expected runtime: provisionally **10–30 minutes on the existing SSD**, with
substantial uncertainty until the first narrow-column scans finish. Slower or
busy storage can take longer. The command prints a measured scan ETA after
later months start finishing. Unlike the earlier 13–15 minute monthly session
builds, these scans do not construct or sort full player histories.

## Work performed

1. Bind to the exact reviewed sensitivity run `2a9e72ad1104dd1e`, certified
   sample, and chronology inventory. Inventory completed history receipts and
   file sizes without rehashing/rebuilding all those outputs.
2. Reproduce the August 2024 chooser/game identity check directly on narrow
   columns. Distinguish absent game keys, wrong chooser membership, duplicate
   matches, and timestamp/speed disagreements. Ordinal disagreements are
   reported separately because the original identity gate did not test them.
3. For failures, authenticate the original certified monthly source, compare
   the focal projection, and look for the same keys in neighboring months or
   candidate records with the same archive ordinal or player/time tuple.
   Candidate similarities never authorize a replacement automatically.
4. Check all 14 remaining months, September 2024 through October 2025, before
   another long history run. Failed identities get the same targeted probe.
5. Where a producer-declared numeric Parquet partition still exists inside
   the project, inspect matching keys/ordinals there. Absence at that path
   is not proof that no other copy exists.

The diagnostic defaults to at most three concurrent month queries, two threads
each, within the ten-worker total limit. Existing unrelated jobs reduce that
allocation. This avoids launching ten competing scans of the same SSD. Arrow
and numerical libraries use one thread. Completed diagnostic scans are
checksummed and resumable. A new run of this same package reuses them.

Existing data and completed history are read only. The diagnostic acquires the
related run locks and writes only its separate output and desktop exports.
No account or focal game is excluded, no key is normalized, no timestamp is
imputed, no model is fitted, and no Stockfish, API, or raw-PGN job is started.
The June 2023 timestamp uncertainty remains unresolved.

## Return files

Upload `KAC_HISTORY_IDENTITY_DIAGNOSTIC_RESULT_<run>.zip` and its `.zip.sha256`
from `~/Desktop/Lichess_Desktop`. An `EARLY` ZIP is written after August; the
final `RESULT` includes later-month checks. If the diagnostic itself stops,
upload the `PARTIAL` ZIP and sidecar instead.

Raw identifiers and candidate rows remain under
`/Volumes/XT_Pro/lichess_kindness/output/kac_history_identity_diagnostic_v100/<run>/PRIVATE`.
Only aggregate JSON reports are exported. A `DIAGNOSTIC_COMPLETE_REPAIR_NOT_APPLIED`
status means the inspection finished, not that repetition estimation finished.

The completed October 2023 buffer and November 2023–July 2024 history from the
previous run are preserved. Their reuse in a subsequent corrected runner will
depend on what the diagnostic finds and on retaining valid carry-forward inputs.
