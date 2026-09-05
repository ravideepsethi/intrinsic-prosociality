# C7R full-panel pre-focal first/repeat census

This package removes the historical 1-in-50 focal-pair restriction from the
first-versus-repeat rated-meeting robustness analysis.

## What it does

1. Authenticates the certified 47,587,020-row Stage-07 panel and the 852-file,
   7,763,847,245-row all-game chronology manifest.
2. Builds the unordered pair set for **all** Stage-07 opportunities without
   reading the kindness outcome.
3. Scans the C7R-compatible ordinary-speed historical chronology in resumable
   source shards and finds the earliest rated event for every focal pair.
4. Defines `first_rated_meeting` by exact equality of
   `(utc_ms, archive_ordinal, game_id)` to that earliest pair event.
5. Freezes and hashes the full 47.6M first/repeat flags **before** reading
   Stage-07 kindness.
6. Joins outcomes only afterward and produces aggregate-only public results:
   raw first/repeat rates, repeat prevalence, raw desert gaps, and transparent
   minimal chooser-FE census models with chooser-clustered CR1 inference.
7. Leaves the row-level flags private on XT_Pro and creates an aggregate ZIP
   plus SHA-256 sidecar on the Desktop.

## Important scientific distinction

The full-panel flags are the direct census replacement for the sampled C7R
support. The package also estimates a deliberately simple one-way chooser-FE
census model.

The historical manuscript coefficients `+1.5669`, `+1.3342`, and `-0.0087`
came from the frozen C7R v1.0.2 model family. The simple FE census estimates
must **not** be described as an exact re-estimation of that old adjusted model
family unless the old v1.0.2 modeling engine is explicitly rerun on the new
full-sample flags. The private flag file created here is designed to make that
follow-up inexpensive.

## Runtime

Expected: about **6–18 hours** with the existing clean historical Parquets.
The run uses 10 DuckDB threads by default, is sharded/checkpointed, and is safe
to resume by relaunching the command.

## Privacy

Identifier-bearing files remain under:

`/Volumes/XT_Pro/lichess_kindness/derived/replication/c7r_fullpanel_prefocal_v100_PRIVATE`

Only aggregate outputs are transferred.
