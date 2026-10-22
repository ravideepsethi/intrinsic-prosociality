All-time-five entry and ordinary-game placebo: finish repair v1.0.5

Run RUN_ALLTIME_ENTRY_PLACEBO.command. It invokes run_finish.py.

MACOS SELF-TEST REPAIR
The v1.0.4 launcher stopped in a synthetic handoff test before it could start
production. The fixture stored /var/... paths while the runner correctly
resolved them to /private/var/... . The fixture now canonicalizes its temporary
root before creating the configuration, matching production. A new end-to-end
regression creates that directory alias explicitly on every platform. All
checksum, parent-identity and data validation checks remain enabled. The
covariance algorithm and estimators are byte-for-byte unchanged from v1.0.4.

WHAT THIS FINISHES
The reviewed v1.0.3 run stopped on 2026-10-20 at 00:20:32 UTC (October 19,
8:20:32 p.m. Toronto). All earlier stages, all eight comparison fits, the
ENV-indicator receipt fit, and the first joint contrast were complete.
The next calculation exceeded its 4-decimal-GB DuckDB allowance while grouping
account/date influences for the new-entry minus old-entry contrast.

This release reuses that work. It makes zero new API requests, scans no raw
games, rebuilds no frames, and refits none of the eight comparison models.
It finishes five remaining joint contrasts and the smaller receipt X0 fit.

KEEP ALL EARLIER PROJECT DIRECTORIES
The parent is:
  derived/replication/alltime_entry_placebo_v103_PRIVATE/5eca56c416c5
Its full configuration is:
  5eca56c416c537930e86893b4a061420ec3cbc5f232dce83fa218ac70f4ad8c5
The reviewed 75% report manifest and original package identity are pinned.
Completed frames, fits, influences and their recorded input hashes are checked.
Original legacy-model replay checks and the accepted main IV check run again.
The saved fits must regenerate the reviewed aggregate CSV tables exactly.
Missing or changed inputs stop the repair; there is no fallback reconstruction.

The parent and previous runners must be stopped. Shared locks protect the old
runs while the finish command runs. Original data and stage receipts are read
only. New files go under alltime_entry_placebo_v105_PRIVATE with a new package
configuration and explicit provenance. The eight model paths continue to name
their original certified outputs. The completed first contrast is imported with
its original configuration recorded, rather than being labeled as newly computed.

MEMORY REPAIR AND SCIENTIFIC AGREEMENT
The formula remains exactly:
  accounts - canonical pairs + dates - account/date + canonical pair/date
This is the original shared-account OR date CR0 covariance, with generated
scores treated as fixed. The original coefficient, scaling, Wald inference,
eligibility, score and control definitions do not change.

Both samples are stacked before partitioning. All records for an account go to
the same account bucket; both orientations of a pair go to the same canonical
pair bucket. Thus overlapping samples, cross-role accounts, and common dates
retain their cross-equation covariance. Bucket outer products are summed only
after complete group scores have been summed.

The writer streams to 128 files per family using a 64 MiB Arrow buffer limit,
plus the current input batch and encoder workspaces. Covariance SQL runs one
partition at a time, with one thread and a 4-decimal-GB allowance. An allocation
failure splits the full grouping key further. Completed partition/leaf receipts
are SHA checked and resumable. Intermediate data are private and retained.
At least 40 GiB free disk is required for the finish checkpoints and spill space.

TIMING AND RESUME
Allow roughly 30-60 minutes as a provisional planning range on the user's
machine, including file authentication. This is not a production measurement
or guarantee. Drive throughput and the size of stored inputs affect timing.
The log reports each contrast, partition progress, and remaining time for the
current covariance term. The 75% marker denotes completed stages, not time.
Rerun the same terminal command after an interruption. It verifies and reuses
completed comparison fits, the remaining receipt fit, completed contrasts and
covariance leaves whose input content matches. Keep all source directories.

OUTPUT AND PATRON SCOPE
Return ALLTIME_ENTRY_PLACEBO_<new-key>_100.zip and its .sha256 after success.
The final report contains both control levels, the corrected entry and ordinary
placebo estimates, balance/equivalence checks, overlap audits, and all six joint
contrasts. It exports aggregate results only; influence rows remain private.
The main IV estimate is checked, not changed. This run finishes the entry and
main ordinary-game placebo diagnostics.

The Table 6/Appendix D legacy-eligibility caveat can be removed once this final
100% comparison report is checked. This package does not edit the manuscript.

VALIDATION
See VALIDATION.txt and COVARIANCE_BENCHMARK.json for local test evidence and
limits. The private production dataset was not available in this environment.
The original scientific/method details are retained in
METHODS_AND_RUNNER_v103_ARCHIVE.txt; its old launch/download instructions are
historical. run_rebuild.py is retained as a report-format helper only.
