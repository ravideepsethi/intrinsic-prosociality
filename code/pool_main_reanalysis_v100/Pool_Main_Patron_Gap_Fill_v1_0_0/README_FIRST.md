# Fill the remaining Patron profile coverage gaps

This package queries the 285 accounts in the completed Wave-3A matching frame
whose August profiles were unavailable. It keeps their frozen matching assignments.
No account with an observed August profile is refreshed. No models are estimated.

| Gap in the fixed matching frame | All groups | Primary fair-kind groups |
|---|---:|---:|
| Controls not queried in August | 122 | 77 |
| Controls queried but not returned in August | 126 | 100 |
| Kind accounts queried but not returned in August | 37 | 30 |
| Total targeted accounts | 285 | 207 |

Save the ZIP and its `.sha256` sidecar in `~/Desktop/Lichess_Desktop`, connect
XT_Pro and run the complete command in `RUN_COMMAND.txt`.

Expected elapsed time is **2-5 minutes**, estimated from the earlier Wave-3A
authentication time and two possible 60-second omission retry waits. No private
production data or live account fetch was available in the build environment.
API rate limiting, transient failures, or a slower drive can extend this estimate.
The launcher uses the existing Wave-1 Python; it installs nothing. Network access
to the public Lichess users endpoint is required. No API token is required.
Do not run another Lichess profile acquisition concurrently.

## What runs

1. Verify the package and the bundled certified sample and Wave-3A reports.
2. Authenticate the Mac's Wave-3A matching/history/coverage checkpoints and fixed
   August snapshot. Read only the coverage file to select the exact 285 gaps.
   The 41.5-million-row game panel is not scanned.
3. Query those 285 accounts in one serial bulk request. Query only omissions
   again, at most twice, waiting at least 60 seconds between successful rounds.
4. Save raw responses, normalized profiles, timestamps, and request receipts on
   XT_Pro. Keep the first successful response for each account.
5. Export an aggregate coverage report ZIP and sidecar to the Desktop folder.

HTTP 429 and retryable server/transport errors have persisted cooldowns. Each
round has at most four transport attempts per invocation. The same command
resumes after interruption without refreshing accounts already returned. A
completed run with three successful response rounds is not re-queried on resume.

## Dates and remaining missingness

These new observations measure Patron status at their actual request dates.
They cannot recover an account's August status. The certified August snapshot
is never overwritten; its SHA-256 is checked before and after the fetch.

The 207 primary and 285 total missing August outcomes remain missing in the
August-only analysis. A later estimator must explicitly bind the separately
dated supplement and show the August-only result alongside it. The existing
Wave-3B1 estimator does not automatically use this supplement. Hold that run
until the gap-fill report has been reviewed.

An account absent from all three successful responses stays unavailable. It is
not labelled deleted, disabled, or non-Patron without an actual profile response.
For a returned account, the frozen normalizer treats an omitted optional Patron
flag as false and records the flag's absence separately. A non-boolean flag
stops the run for schema review.

## Outputs

Private files remain below:

`/Volumes/XT_Pro/lichess_kindness/derived/replication/pool_main_reanalysis_v100_PRIVATE/patron_gap_fill_v100/<configuration>/`

The principal file is `current_profile_gap_supplement_private.parquet` (285 rows).
Its explicit observation dates, missingness flags, request counts, and August-gap
reasons are retained. Raw JSON and account names are private. Output file hashes
and aggregate counts are included in the transferable report.

Upload the two files printed at completion:

`POOL_MAIN_PATRON_GAP_FILL_RESULTS_<timestamp>_<configuration>.zip`

and its `.sha256` sidecar. Do not upload the private profile Parquets or requests.

Possible statuses:

- `ALL_GAPS_HAVE_CURRENT_PROFILES`: every targeted account returned a current profile.
- `COMPLETE_WITH_UNAVAILABLE_ACCOUNTS`: all three successful rounds completed;
  some accounts remain unavailable. This is not complete outcome coverage.
- `REQUESTS_INCOMPLETE_RESUME_REQUIRED`: temporary request failures exhausted
  this invocation. The report reflects partial coverage; repeat the command.

Contradictory, malformed or unauthenticated responses stop certification and
retain a detailed error privately. The Desktop log prints counts and error
types, without account identifiers.

## Source lineage and API behavior

The original acquisition producer is bundled unchanged at
`source/profile_fetcher_v100.py`, SHA-256
`549d2d7f2102ed7458173c7e45df02a34d36544fb118989c0cb66c3fdf70a0e9`.
`runner/normalizer.py` loads its original schema and a named set of pure
normalization helpers through the Python AST, without changing their bodies.
It does not run the old multi-machine acquisition plan. The new transport uses
Python's verified HTTPS client, rejects redirects, and uses the same bulk endpoint.

The [official Lichess API tips](https://lichess.org/page/api-tips), checked during
this build, specify one request at a time and waiting a full minute after HTTP 429.
The runner also obeys a longer Retry-After value. Its 300-user maximum request
size and conservative rolling user ceilings are inherited from the frozen
producer, not represented as newly verified platform guarantees. This run
starts with only 285 users and decreases the request size on each retry.

The offline tests cover omission-only retries, observation dates, checkpoint
replay, response corruption, malformed payloads, missing-outcome semantics,
interrupted requests, persistent rate-limit waits, and aggregate-only reporting.
