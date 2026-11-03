# Run the two decision checks

This bundle is prepared and synthetically tested. It does not contain new
estimates from Ravi's private data. It is designed for the Mac with the existing
project at `/Volumes/XT_Pro/lichess_kindness`.

Run `bash RUN_ALL.command`. It checks dependencies, creates a local virtual
environment only if needed, runs synthetic self-tests, and uses caffeinate on
macOS. No source data are edited. Run when no other Lichess API client is active.
Tenure runs first, then responsibility; both can be resumed with the same command.

## What this run actually does

1. Authenticates the current 41,534,331-row sample against its certified receipt
   and exact monthly file hashes.
2. Uses 100,000 uniformly hash-selected choosers and their full histories for
   the primary tenure models. Existing outcome-selected profile acquisitions
   alone would be an unsuitable population sampling frame. Missing creation
   dates are fetched for the fixed probability sample.
3. Reports novice grant shares and missing-date bounds over **all 41.5 million
   decisions**, alongside age-stratified gradients, stage, persistence and a
   conditional Patron comparison on the large historical August profile frame.
4. Takes a nested 20,000-account sample for responsibility, spanning every
   board state. Reuses applicable A1 move records, gets only missing moves,
   and evaluates the final five positions. Estimates before/after controls
   use exactly the same games.

This is an explicitly sampled screening analysis, not a full-census rerun of
every model. Default sample selection ignores outcomes. Increase sample sizes
before looking at results if a larger run is preferred. The Patron models are
new tenure sensitivities on the historical matched acquisition frame; they do
not exactly reproduce the old full-control regression.

## Commands

Full run (default 8 DuckDB threads, up to 10 single-threaded engines):

```bash
bash RUN_ALL.command
```

Tenure only (produces the most important first report without engine work):

```bash
bash RUN_ALL.command --phase tenure
```

Responsibility after a completed tenure run, with the same settings:

```bash
bash RUN_ALL.command --phase responsibility
```

Preflight only: authenticate inputs, freeze samples, report the exact number of
target games/positions. No API requests or Stockfish search are made:

```bash
bash RUN_ALL.command --phase prepare
```

If the already installed Stockfish binary is outside the usual project engine
directories, append `--stockfish /absolute/path/to/stockfish`. It must match the
existing A1 SF18 binary; the checksum is pinned. Do not substitute a new binary
without changing and reviewing the engine design.

If needed, choose the existing Python explicitly:

```bash
LICHESS_PYTHON=/absolute/path/to/python3 bash RUN_ALL.command
```

## Expected work and outputs

The exact projected sample size is printed after preparation. At the census
mean, 20,000 accounts imply about 258,000 games and up to 1.29 million engine
positions. At the previously observed ~44 positions/second this is roughly
8 hours of engine time, before downloads and validation. That is a planning
calculation, not a benchmark of this package or a guarantee. Position reuse and
short games reduce it; machine load can increase it. Engine ETA updates by batch.

The default output is
`/Volumes/XT_Pro/lichess_kindness/output/tenure_responsibility_v100/<identity>/`.
The exact path is printed. An explicit `--output /absolute/path` can simplify
location; keep settings fixed if resuming that directory.

* At `TENURE_READY`, upload `TENURE_RESPONSIBILITY_TENURE_REPORT_v100.zip`.
* At final `TENURE_RESPONSIBILITY_OK`, upload
  `TENURE_RESPONSIBILITY_COMPLETE_REPORT_v100.zip`.
* If it stops, upload `TENURE_RESPONSIBILITY_PARTIAL_REPORT_v100.zip` and paste
  the terminal error. Completed inputs and engine batches remain reusable.

Each archive has a `.sha256` sidecar. Reports contain aggregates, model support,
standard errors/intervals, coverage, methods, source lineage and a readable
`RESULTS_OVERVIEW.md`. Individual account/game records remain under PRIVATE and
are excluded from report ZIPs. Do not upload the PRIVATE directory.

## Read the evidence before deciding

First assess the novice-grant-share bounds and established-account gradients.
Next assess established-account stage, persistence and Patron patterns. Then
compare the responsibility gradient on identical rows, the no-large-own-blunder
subsamples, and the conditional rating-gap results. Inspect support and interval
widths, not just p-values. Read METHODS.md for exact estimands and limitations.

Robustness weakens specific alternatives; it neither establishes quitting
intent nor settles a journal destination. Null or attenuated results require
checking precision and selection before changing the paper's conclusion.
