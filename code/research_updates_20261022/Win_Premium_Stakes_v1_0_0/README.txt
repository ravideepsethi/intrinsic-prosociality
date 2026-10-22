WIN PREMIUM STAKES v1.0.0

Unzip onto the Mac. Run in Terminal:

bash "$HOME/Downloads/Win_Premium_Stakes_v1_0_0/RUN_STAKES.command"

The default project is /Volumes/XT_Pro/lichess_kindness. It reads the existing
24-month main panel, global user dictionary/author-exclusion receipt, and sorted
rating-event Parquet files. It does not contact Lichess or repeat engine/replay work.
Both author usernames are excluded. The original panel and histories stay intact.

Output to upload here:
$HOME/Desktop/Lichess_Desktop/Win_Premium_Stakes_Report.zip

The ZIP contains an overall table; breakdowns by rating, speed, standing decile
and RD; coverage audits; equal-account and same-sample sensitivities; and a chart.
It contains aggregate data, not individual usernames or game rows.

Expect a multi-hour run, potentially overnight on an external SSD. This has not
been benchmarked on your production disk. The frozen default catalog covers 135
files, 2,511,470,596 games and 45.6 GiB of source Parquet, before temporary/derived
data. It scans the study period plus three warm-up months. File counts/row counts
print at startup; stage timings are saved. Keep substantial free disk space for
spill files and current/previous history states. Five speed workers each have a
2 GB DuckDB budget plus additional NumPy memory. Up to ten CPU threads are used
for the history stage. For a memory-constrained machine use --workers 2.

Completed speed/months are checksummed and reused by rerunning the same command.
Only the latest 101 history observations per relevant account carry forward.
History starts in August 2023; missing full 100-observation windows are reported.
To improve early/inactive-player coverage at the cost of extra scanning, use e.g.
--history-start 2023-01. That deliberately creates a distinct run/cache.

Read-only preflight without a full scan:
bash "$HOME/Downloads/Win_Premium_Stakes_v1_0_0/RUN_STAKES.command" --preflight-only

The launcher reuses a compatible existing Python environment or creates an
isolated one in the package. Package installation may require internet access.
The analysis itself reads only local files. Python 3.10+ and DuckDB 1.5 are required.

Important limitation: usual gains from completed wins are not calculated because
the reusable chronology lacks authenticated completion timestamps. Prior rating
levels and the lagged population CDF need only starts and can be measured safely.

This package was validated with synthetic data here. The production panel is on
your Mac and has not been processed in this environment. METHODS.txt freezes the
definitions and interpretation limits. No rating-stakes result is claimed yet.
