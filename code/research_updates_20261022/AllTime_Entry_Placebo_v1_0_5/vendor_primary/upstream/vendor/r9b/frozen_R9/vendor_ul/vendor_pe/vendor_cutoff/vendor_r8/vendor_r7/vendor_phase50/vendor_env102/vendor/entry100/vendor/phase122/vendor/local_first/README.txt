Run 2 Local First — version 1.0.1

Version 1.0.1 fixes the macOS self-test's /var versus /private/var path
comparison. Production discovery already resolves aliases correctly. A new
symlink regression test checks discovery and original-cache reuse together.
Read-only SQLite connections now close explicitly, including on errors.
Preparation self-tests have a separate log so their simulated one-game downloads
and temporary reports cannot be mistaken for production work. Tests still gate
preparation, and failures print their full log. Frozen sampling, eligibility,
metadata reconciliation and HTTP rules are unchanged.

The reported version 1.0.0 failure occurred before production preparation.
Existing original Run 2 responses and source Parquets remain reusable. This
version uses a separate output namespace; it does not modify old output folders.
It prepares the full remaining request list. Phased effect estimates are a
subsequent analysis step, not implemented in this repair.

Run RUN_LOCAL_FIRST.command first. It makes ZERO API requests and creates the
reduced request list plus a small aggregate report. The project must be mounted
at /Volumes/XT_Pro/lichess_kindness. Save/unpack this package under
~/Desktop/Lichess_Desktop, as usual. SciPy is not required.

Expected first-run local time: approximately 15–60 minutes, an unbenchmarked
laptop estimate. A large additional cache inventory can take longer. All major
stages use reusable Parquet checkpoints. Up to 10 processes share the memory
budget; each process uses one DuckDB/Arrow/BLAS thread. Joins and sorts that run
alone use the available worker count. A shared mmap avoids copying the game-ID
index into each worker. Local status/heartbeat messages appear during long work.

If the original Run 2 download is active, press Ctrl-C in its terminal first.
Its committed and partially completed successful responses will be reused.
The new package never changes or deletes its SQLite database or target list.
The original downloader's lock is respected; there is no automatic process kill.

What changes
------------
1. Reuse all 61,158,951 frozen sampled games from the existing 21 monthly
   PGN-derived Parquets. Check the exact hash selection, color orientation, old
   frame membership, and every original field. Keep every row in a ledger.
2. Apply only necessary rules already required by the frozen expanded entry
   and placebo design: remove author games; require 97 days of prior panel
   coverage; require at least five opponent decisions before month-start minus
   seven days, excluding every decision involving the focal recipient and either
   author. No future outcomes, giving rates, or new effect estimates choose IDs.
3. Independently reproduce the original lag-7 decision count for ALL 2,682,330
   frozen spaced90 rows before relying on the new count algorithm. Missing
   history input files are errors, never evidence of zero decisions.
4. Reuse the original merged cache and SQLite API responses; preserve prior
   three-pass nonreturns as explicit gaps. Successful responses saved just before
   an interrupted batch commit are reused too. Request and raw-response hashes
   are checked before consumption.
5. Search additional local Parquets and raw API JSON beyond the old folder and
   filename whitelist. Reuse explicit API field aliases and reviewed source
   evidence formats; combine agreeing fields across records. Literal PGN-header
   Parquets can fill ratings, names, and time controls. Generic source columns
   without a supported provenance contract are not interpreted as API source.
6. Produce only the remaining API targets, ordered by the ORIGINAL retrieval
   rank. Report exact savings, remaining missing fields, prior nonreturns,
   unsupported cache formats, and the revised API runtime projection.

Important limits
----------------
This changes retrieval order and accounting, not the frozen eligible comparison
population. All ending types are retained for the entry test. Metadata for games
that provably fail necessary eligibility may remain unobserved; complete raw-frame
source/ending descriptive counts cannot be claimed for those rows.

Passing this prefilter does not certify eligibility. First-observed pair, actual
previous nonadjacency, pool source, identities, exact follow-up, prospective risk,
and finite adjusted scores still require the frozen analysis construction.

Raw PGNs are not reparsed or downloaded. The existing frame and other recognized
Parquets supply reusable information without another scan of billions of games.
Some original monthly PGNs were deleted after verified extraction. Neither a PGN
Event nor Time-forfeit label is substituted for API pool source or timeout status.
Exact API timestamps are not reconstructed from rounded clocks.

New cache inventory is frozen for this preparation. --refresh-caches explicitly
updates it while reusing unchanged history/count stages. Arbitrary SQLite formats
and unopened archives are listed as unconsumed; the known original Run 2 SQLite
format is fully supported. Conflicts are retained even after a new API response;
they are never overwritten by majority vote or a latest-record rule.

Local output
------------
Private data and resumable stages stay under:
  /Volumes/XT_Pro/lichess_kindness/derived/replication/run2_local_first_v101_PRIVATE

The Desktop receives:
  RUN2_LOCAL_FIRST_REPORT_<run>.zip
  RUN2_LOCAL_FIRST_REPORT_<run>.zip.sha256
  RUN2_LOCAL_FIRST_LATEST_PRIVATE.json (local pointer; do not upload)

Upload only the small REPORT ZIP and its checksum for review. It contains
aggregate counts and no game IDs, account IDs, credentials, or private paths.

Downloading the reduced list
---------------------------
Run RUN_REDUCED_DOWNLOAD.command in the SAME extracted package. It reads the
latest private pointer and resumes the reduced list. The local report provides
the remaining-hours projection at the previously observed 29.05 IDs/second;
the live downloader reports an updated observed rate. This can still take days
if many eligible games lack exact source/timestamps. No unmeasured speedup is
promised. Server backoff and Retry-After are preserved; HTTP requests are serial,
with up to 300 IDs per request. Local CPU stages remain parallel.

Use STATUS_REDUCED_DOWNLOAD.command for progress. Run the same download command
after interruption. If the OLD downloader was restarted after preparation, rerun
RUN_LOCAL_FIRST.command first so its new responses can be reused; already
completed local stages are checked and reused.

The download saves a merged metadata file and ANALYSIS_INPUTS_PRIVATE.json. It
does NOT estimate the expanded placebo, change the paper, or clear the abstract
or title gate. The expanded analysis adapter remains a subsequent stage.

Configuration
-------------
Environment overrides: IV_PROJECT_ROOT, IV_DESKTOP, IV_PYTHON.
CLI examples: --workers 10 --memory-gb 24
Extra existing cache folder: --extra-cache-root /absolute/path
No environment installation or system settings are changed.

The statistical rules come from comparison_original/DESIGN.md and the reviewed
expanded_logic.entry_mask. The old retrieval-only instruction requiring metadata
for every uncached row is explicitly amended here, as authorized on Sep 30, 2026.
No new coefficient, outcome, or equivalence result has been used in this amendment.
