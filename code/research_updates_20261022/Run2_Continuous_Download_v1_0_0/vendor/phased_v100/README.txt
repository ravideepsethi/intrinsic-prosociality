Run 2 Phased Download, version 1.0.0

Start RUN_PHASE_10.command. It checks and reuses the completed local-first run
21715769dd17, inspects the existing SQLite inventory, builds the fixed phases,
downloads only the first 10% phase, exports Parquets and an aggregate report,
then stops automatically. The 103-minute history/count/cache search is not
repeated. Keep XT_Pro connected; use ~/Desktop/Lichess_Desktop as usual.

Expected time: 5–30 minutes for initial local setup, an unbenchmarked estimate.
Large reusable SQLite stores can take longer. The first phase is projected to
need about 3.27 million lookups and 31 download hours at 29.05 IDs/second,
before retries/export. The exact count prints before networking starts.
Reused SQLite responses can reduce it further. Subsequent status/resume checks
read hashes and completed Parquets, not the full original cache inventory.

Local work uses up to 10 workers with a shared memory budget and one thread
per worker; large final sorts use the available thread budget. On the observed
11 GiB budget, the safe process cap is seven. Do not increase the memory budget
just to force ten processes. API requests remain serial, with up to 300 IDs per
request, the inherited retry rules, and at least 60 seconds after a 429.

What is reused
--------------
- All 61,158,951 fixed frame rows, recipient orientation and monthly coverage.
- Completed author-clean local eligibility and historical-count validation.
- Previously recovered PGN-derived and exact API fields, including disagreements.
- The original comparison sample, retained separately from the new sample.
- Completed AND partially saved requests from bound compatible SQLite stores.
- Explicit supported API metadata tables in the three previously unread SQLite
  files, if present. Schema discovery is read-only; arbitrary game tables are
  not interpreted as API evidence. Unsupported schemas remain reported as
  unconsumed. A recognized API checkpoint with an unverifiable target binding
  stops before any new API requests. --extra-sqlite can name another existing
  database; no broad disk crawl or archive unpack is performed.

The upstream package hash, plan identity, receipts and file hashes are checked.
New outputs have a separate namespace. No old source, target list or checkpoint
database is edited. The launchers respect the old downloader locks and shared
one-request lock. Pause any old Run 2 downloader before starting this one.

Phase definition
----------------
For each NEW frame game, use its already frozen full SHA-256 retrieval rank.
Cumulative thresholds are floor(2^256 * p/100), for p=10,25,50. A rank strictly
below the threshold belongs to that cumulative phase; 100 includes all new
frame rows. Phase selection includes cached, uncached, locally ineligible,
nonpool and nonreturned games. Preserve all ending types for the entry analysis.
The original 1,912,023-game comparison frame remains separate and fully available.
This fixes membership before any new coefficient is calculated.

Four disjoint retrieval bands have immutable target Parquets and separate
transactional SQLite journals. RUN_PHASE_25.command completes/reuses 10 and
fetches only the next band. The 50 and 100 commands work the same way. Rerun
the SAME phase command after Ctrl-C or a network failure; received responses
survive even when interruption occurs before a batch is marked complete.

Cumulative estimates at the previous rate, before retries/export:
10%: 31 hours; 25%: 78 hours; 50%: 156 hours; 100%: 313 hours.
These are download projections, not guarantees or total analysis runtimes.

Output and interpretation
-------------------------
The Desktop receives RUN2_PHASE_PLAN_REPORT_<run>.zip and, when a phase ends,
RUN2_PHASE_010_REPORT_<run>.zip (or 025, 050, 100), each with a checksum.
Upload these small aggregate ZIPs. Never upload files marked PRIVATE.

The private ANALYSIS_INPUTS_PRIVATE.json references the full frozen denominator,
the exact cumulative selection predicate, recovered metadata and all nonreturns.
It requires the complete historical/prospective anchor streams for subsequent
analysis; phase selection must not recompute true history or the exposure stream.

These commands retrieve metadata and produce analysis inputs. They do not yet
compute the expanded entry or ordinary-game placebo regressions. Identity
alignment, frozen outcomes, author-clean score fits and clustered estimation
remain required. Partial retrieval alone is not a placebo result. Interim
estimates should describe stability and achieved precision; retain the planned
100% sample and frozen specification for formal manuscript claims. Do not stop
or change the final sample because an interim coefficient or interval is favorable.

Other commands
--------------
PREPARE_PHASES_ONLY.command: local preparation and report, zero API requests.
STATUS.command: fixed phase counts and completed download progress.
RUN_TESTS.command: synthetic/offline tests, approximately 5–45 seconds.
Environment overrides: IV_PROJECT_ROOT, IV_DESKTOP, IV_PYTHON.
CLI options: --workers 10; --memory-gb; --plan; --extra-sqlite /absolute/path.
No dependencies are installed and SciPy is not required.

Source for the unchanged serial/backoff policy, checked October 1, 2026:
https://lichess.org/page/api-tips
