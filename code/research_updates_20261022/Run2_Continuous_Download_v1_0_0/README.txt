Run 2 continuous download, version 1.0.0

Run RUN_TO_100.command. It continues the existing phased download through 100%,
saves cumulative reports at 25%, 50%, 75% and 100%, and proceeds automatically
after each report. The already completed 10% and all later saved responses are
reused. The old downloader must not run simultaneously; the shared locks check
this before another API request. The completed local-first preparation is reused.

Expected runtime after the completed 10%
--------------------------------------
Initial local verification and 75% setup: approximately 5–20 minutes,
an unbenchmarked laptop estimate. Existing Parquets are read with up to 10
workers subject to memory limits; no full history rebuild or broad cache search.

At the previous 29.05 IDs/second, approximate remaining download time:
25%: 47 hours from now; 50%: 125 hours; 75%: 203 hours; 100%: 282 hours.
These are retrieval estimates, not total wall-clock guarantees. Retries and
local exports/reports add time. Report work can take minutes to hours depending
on SSD speed, available memory and checkpoint size; it has not been benchmarked
on the Mac. The terminal reports that work while it is in progress.

The terminal prints ETA to the next unsaved checkpoint and to 100% every
30 seconds, including during network waits. ETAs begin at the prior rate, then
use newly accounted IDs per active retrieval second in the current invocation.
Previously saved IDs do not inflate the measured speed. Local export/report time
is excluded from the rate. The completion estimate also shows the local date/time.
Use --eta-seconds 15 for more frequent updates (allowed range 5–60 seconds).

Persistence and fixed sample
----------------------------
The original SHA-256 rank, request order, 300-ID batches, target Parquets,
SQLite journals, API normalization and server-backoff policy are unchanged.
Each successful response is committed immediately. Ctrl-C, sleep, disconnection,
or retry exhaustion can be resumed with the SAME RUN_TO_100.command.
Reports and completed Parquet stages are reused after verification.

The original 50-to-100% request list remains intact. At its exact 75% rank
boundary, the program writes a cumulative snapshot. If the boundary falls inside
a request, up to 299 later IDs can be returned in the same request; those records
are excluded from the 75% report and remain saved for 100%. The 100% report uses
the full original final band once, never both the 75% prefix and its parent.

Network requests remain serial. Local preparation and metadata reconciliation
use Parquet and the available thread/process budget, at most 10 workers. With
the previously observed 11 GiB budget, seven local workers are permitted. Do
not raise the memory budget merely to force ten. SciPy is not required.

Outputs on ~/Desktop/Lichess_Desktop
-----------------------------------
RUN2_PHASE_025_REPORT_<existing-run>.zip and .zip.sha256
RUN2_PHASE_050_REPORT_<existing-run>.zip and .zip.sha256
RUN2_PHASE_075_REPORT_<existing-run>.zip and .zip.sha256
RUN2_PHASE_100_REPORT_<existing-run>.zip and .zip.sha256

These are small aggregate reports suitable for returning in chat while the
download continues. Private metadata stays on XT_Pro. Checkpoints are retrieval
reports, not new placebo estimates. They preserve all ending types, the full
denominator, missing responses, flags, and subsequent analysis requirements.
Formal final sample membership and specifications remain unchanged.

STATUS.command: read-only verification and status, approximately 1–5 minutes.
RUN_TESTS.command: offline synthetic checks, approximately 10–90 seconds.
Environment overrides: IV_PROJECT_ROOT, IV_DESKTOP, IV_PYTHON.
Options: --workers 10, --memory-gb, --eta-seconds, --plan, --phase-pointer.
Use caffeinate through the launcher and keep XT_Pro connected. Closing the
terminal stops the job; rerunning the same command resumes saved work.
