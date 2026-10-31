# Comparison-sample expansion: fixed design, version 1.0.0

Purpose: improve the precision of the ordinary-game exclusion placebo and
entry-selection diagnostics accompanying the expanded 90-day IV. The expanded
IV report f14a1105a9f7 and previous comparison effects have already been read.
This is a prospective specification for additional sampling after those
results, not preregistration of the original research. New game IDs can share
players and subsequent outcomes with earlier data; they are not an independent
outcome holdout.

## Sampling fixed before new retrieval

Use the exact 105 chronology files in the authenticated original sampling
receipt: November 2023 through July 2025; ultrabullet, bullet, blitz, rapid and
classical. Verify full file hashes against the original observed hashes.
Interpret each exact eight-character case-sensitive game ID as a little-endian
unsigned 64-bit integer. XOR with 2026090601 and apply the inherited SplitMix64
function. The original frame selects low 10 bits zero. The expanded frame
selects low 5 bits zero (1 in 32). Thus the original 1,912,023 games must be an
exact subset. Every original frame column, including the chosen recipient,
must reproduce. Use bit 32 of the same hash for orientation as originally.
Preserve every ending type, source and recipient at this stage. No outcome,
receipt, engine evaluation or future exposure is used in frame selection.

The additional sample is low 5 bits zero and low 10 bits nonzero, approximately
31 times the original frame. Report additional-sample diagnostics as the
prespecified new analysis; report the combined old-plus-new frame separately.
The original and expanded IV estimates remain unchanged. Do not change the
new sample size or stopping rule after reading any new diagnostic coefficient.

Request metadata for new games not already recovered from local completed
caches. Sort requests by a separate full SHA-256 hash of
`chooser-comparison-expansion-v100-fetch-order-20260911|` plus game ID, breaking
ties by game ID. Cached availability is not random, so an interrupted retrieval
is NOT certified as a completed random subsample. Preserve its entire frozen
denominator and all remaining IDs. There is no successful-response pause.

## Precision objective and limits

Retain the previously discussed placebo equivalence margin of +/-0.015
percentage points per 0.059411690344000595 units of the historical score.
Use two one-sided 5% tests (a 90% CI inside the margin); also report the 95% CI.
This margin is a diagnostic tolerance, not a proven bound on IV bias. A
secondary +/-0.010 margin can be displayed without changing sample size.

The last placebo SE was 0.028292388191929772 pp in those units. If its SE scaled
with inverse square-root sample size, 31 times as many observations would give
SE about 0.00508 pp and roughly 81% equivalence power if the true placebo effect
were zero. This is a planning approximation, NOT a guarantee. Common accounts,
dates, reused future decisions and estimated historical leniency can limit the
precision gain. No Bernoulli-row-count formula is substituted for the actual
clustered regression variance. Report achieved SE, distinct outcome events,
reuse, account concentration and cluster support before interpreting a null.

## Frozen subsequent analysis (not executed by this retrieval package)

Replicate the entry90_pooled and ordinary90_placebo definitions, controls,
chronology and score construction in the included expanded_config.json and
the reviewed expanded analysis plan. Use the certified pool and observed
previous-nonadjacent definition; keep first observed pairs, real-time games,
lag-7/floor-5 opponent history and complete 97-day prior-history coverage.

For entry, begin with ALL sampled endings. Build prospective risk using only
previously anchored selected exposures and the original 90-day spacing stream,
including early-history and incomplete-follow-up anchors. Do not restrict the
denominator to people who eventually enter the exposure sample. Reconstruct
selected entry from the exact audited stream. Report active timeout and
recipient disconnect separately from entry into the fair-arm analysis sample.

For the ordinary-game placebo, inherit the exact narrow ordinary endings
(mate, resign, stalemate), complete follow-up and other restrictions from the
reviewed code. Keep the primary outcome and reach separately: first later fair
choice against another opponent, game starting strictly after lastMoveAt,
within 90 days. A complete window with no qualifying choice is zero;
administratively incomplete follow-up is not zero. lastMoveAt remains a proxy,
not a certified finish or claim-click time.

Use the existing pair-leave-all-out state-adjusted leniency and predetermined
recipient histories. No post-assignment game-trajectory controls in primary IV
diagnostics. Absorb the inherited assignment cells, date and hour of week.
Use the existing shared-account OR exposure-date covariance, recognizing
players in either role. Historical scores are treated as fixed in that
inference; score-estimation uncertainty is not automatically covered.

Report the 30-day and unspaced entry sensitivities and repeated-recipient
pooled/FE diagnostics on matched rows. Recipient FE is diagnostic, not an
identification repair. Apply Holm adjustment to the two primary association
tests (entry and ordinary-kindness placebo); report the single prespecified
placebo equivalence test separately. No favorable-specification selection.

## Accounting and engineering

Every original and new frame row remains in the work-laptop denominator.
Original metadata is reused from the authenticated reconciled frame. Completed
JSON/NDJSON and recognized normalized Parquet caches are scanned without
executing their source code. Cache inventory and file signatures are frozen;
new files created later are not silently added to that run. Parsing gaps,
unsupported cache formats and conflicting values are reported. They never
justify deleting a sampled game. Raw PGN is not assumed to contain API source.

Only explicit non-pool source or complete consistent pool metadata can avoid
a new request. Missing or conflicting records remain in the API target list.
The downloader preserves all returned game objects and request bindings in a
single SQLite database; each successful request is transactionally committed.
It retries nonreturns in up to three passes per batch, and saves missing IDs
separately. Returned metadata flags remain explicit. Re-fetching does not
erase a prior disagreement: the work-laptop reconciliation must compare all
old and new records before estimation. Global username/account-ID alignment
is a later required check, not claimed by this downloader.

No raw game rows, account identifiers, credentials or private cache paths are
included in the small uploadable reports. Private input/return ZIPs stay on
the user's laptops. Stockfish is never run by this package. The separate A1
trajectory job retains Stockfish 18, 100,000 nodes, 10 one-thread engines.

Lichess permits one API request at a time and requires at least a minute after
HTTP 429; a longer Retry-After is honored. See
[Lichess API tips](https://lichess.org/page/api-tips) and
[API documentation](https://lichess.org/api#tag/Games/operation/gamesExportIds).
