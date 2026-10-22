# Receipt IV: pull missing API source and retain metadata

This command starts the full API pull immediately after validating the existing input receipts. It targets **5,891,950 already-known game IDs**, with no pilot approval pause and no fixed sleep after successful responses.

| Month | Unresolved IDs | Initial requests, at most 300 IDs each |
|---|---:|---:|
| November 2025 | 1,964,949 | 6,550 |
| December 2025 | 2,092,233 | 6,975 |
| February 2026 | 1,834,768 | 6,116 |
| Total | 5,891,950 | 19,641 |

## Start and resume

Place the ZIP in `~/Desktop/Lichess_Desktop`, verify its checksum, extract to a fresh directory, and execute `RUN_SOURCE_API_PULL.command` using the supplied command. The launcher uses `/Volumes/XT_Pro/lichess_kindness/venv/bin/python` and `caffeinate`.

The default processes every remaining batch. Run the **same command** after a network interruption, restart or Ctrl-C. A new extraction directory is harmless: progress lives on XT_Pro and is bound to the package code and frozen inputs. Completed batches are authenticated and reused. Complete records from an interrupted response are also reused when their response receipt was committed. A process termination before a response receipt is committed may cause that uncommitted request to be repeated; committed requests are not silently discarded.

The public endpoint requires no token. If `LICHESS_API_TOKEN` is already set, the client uses it without printing or saving it. No token setup is necessary. A rejected token can be unset before resuming. Do not paste tokens into chat, scripts, logs or the command below.

## No unnecessary pauses

- HTTP concurrency is **one**, as required by Lichess. Offline DuckDB stages use up to four threads.
- Fixed delay after a successful request: **zero seconds**.
- Successful responses that omit IDs trigger immediate requests for those omitted IDs only, up to three successful-response attempts per missing ID.
- HTTP 429 waits at least 60 seconds and honors a longer `Retry-After`. The cooldown is saved, so restarting does not bypass it.
- Network and server failures use bounded exponential backoff. After eight consecutive transient failures, the process saves the next permitted request time and stops without an extra terminal sleep.
- Checkpoint writes, response validation and required input reads take time; there is no artificial pacing added to those operations.

Progress prints approximately every 20 seconds, and the ETA appears after ten newly completed batches. Throughput depends on the API and local disk. Budget hours for millions of games; the live ETA is more informative than an assumed games-per-second rate. Keep at least 8 GiB free during collection; the script stops safely if free space falls below that threshold. It does not delete completed data to make room.

## Metadata retained

The request uses `POST /api/games/export/_ids`, NDJSON, 300 IDs per batch, `moves=false`, `pgnInJson=false`, `clocks=true`, and no engine evaluations. Every native response is retained as compressed NDJSON with request/response receipts. A normalized Parquet layer contains:

- matchmaking `source`, status, rated flag, variant, speed and performance category;
- creation and last-move timestamps;
- winner, including whether the winner field was absent for a draw;
- player IDs, ratings, rating changes and provisional flags when supplied;
- initial time, increment, total-time metadata and available per-ply clock histories in **centiseconds**;
- arena/Swiss IDs when supplied;
- explicit validation failures and missing-field notes.

Missing optional values remain null. Absence of a provisional flag is not automatically coded false. The native response preserves other fields returned by the API, including fields not flattened into the Parquet. Hidden RD, volatility and latent fractional ratings are not supplied by this export and are not reconstructed here.

The clock histories are retained for later reconciliation. They do not change the existing five-second/missing-clock opportunity rules, and the script does not infer a claim-click timestamp from `lastMoveAt`.

## Validation and input scope

The frozen targets come from the completed cohort extension's source table and authenticated target metadata. Counts must equal the reviewed three-month gaps. Previously recovered games, including February's 1,128 recovered records, are not requested again.

A source label is accepted only when the exact requested game ID, rated/standard status, timeout status, timestamp convention, winner and player structure match the target. The timestamp comparison uses exact API milliseconds where retained, otherwise the already-certified PGN start second. Unknown source codes and inconsistent metadata remain unresolved. Repeatedly omitted IDs remain `not_returned_after_retries`, with no inference about why they were omitted. There is no automatic conversion to non-pool membership or recipient nonresponse.

The collector stops on unexpected/duplicate returned IDs, a changed checkpoint, or a systematic metadata mismatch. Those are data/contract failures; it does not loosen the rules to keep a pull running. Individual mismatches remain recorded for review. The three-attempt omission rule bounds repeated requests; it does not establish permanent API unavailability.

This is an **active-opportunity metadata pull**, not a fresh census of all disconnections. It cannot construct February's complete candidate/API denominator or establish the platform mechanics deployment date. Those require their own identified inputs. It also does not rerun Stockfish, rating reconstruction, chronology, decision histories or instrument scores.

## Outputs and subsequent use

Private work root:

`/Volumes/XT_Pro/lichess_kindness/derived/replication_36m/receipt_iv_source_api_v100_PRIVATE`

It contains the frozen plan, raw API responses, per-request receipts, normalized batch Parquets, checkpoints, and consolidated metadata parts. Final products are listed in:

`final/SOURCE_SUPPLEMENT_READY_PRIVATE.json`

At completion the program also applies the **already-computed adjacency classifications** to these newly labelled games. It writes a source supplement and a membership delta for each month. Existing source/membership files remain unchanged. Unresolved adjacency stays unresolved; observed mutual adjacency stays excluded under the original convention. These deltas make it possible to expand the choice inputs and join the existing all-source scores without repeating the expensive chronology or scoring stages.

The resulting known-main count is not the final IV exposure count. First-pair selection, spacing, complete outcome windows, the frozen censor and estimation remain separate steps.

The launcher writes a log and a result ZIP plus SHA-256 sidecar to `~/Desktop/Lichess_Desktop`. Upload **`RECEIPT_IV_SOURCE_API_RESULT_*.zip` and its `.zip.sha256`** after completion or a stop. Native game/player records remain on XT_Pro. The returned ZIP contains aggregate source coverage, field coverage, membership changes and errors. An early interruption does not require an upload before resuming.

An optional `--max-new-batches N` launcher argument gives an explicitly requested stopping budget. The supplied full-run command does not set it.

## Verification and authority

The release tests cover successful-request pacing, selective retries, partial streams and restart, required rate-limit waits, persisted cooldowns, stopping without a redundant final sleep, target validation, omitted IDs, changed checkpoints, authenticated input preparation, consolidation, membership rules and completed-stage reuse. Tests use local synthetic data and simulated HTTP responses.

A separate live request to the API documentation's three public example games returned HTTP 200, `source`, required metadata and clock histories. This checks the endpoint and request parameters; it is not a live test of the private opportunity dataset or a runtime benchmark for the full pull.

Official API documentation is pinned under `authority/` at commit `25d5921a716df07fbbebc96786ef0ebff4c7f5f9`. The endpoint specifies a maximum of 300 IDs and no required authentication. General guidance requires one request at a time and a cooldown after rate limiting. The reference receipts identify the source URLs and hashes.
