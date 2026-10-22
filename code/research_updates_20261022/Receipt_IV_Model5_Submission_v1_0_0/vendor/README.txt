Receipt IV Uniform90 — optimized continuation v1.0.2

VERSION 1.0.2 FIX
Fix the resume-test fixture to store the canonical temporary project path,
matching the original producer. On macOS, /var/folders can resolve through
/private/var/folders; the old fixture incorrectly treated them as different.
An explicit symlink-path regression test is included. All 24 tests also pass
locally with a symlinked temporary directory, reproducing that path condition.
The numerical engines, hardware policy, checkpoint keys, strict production
resume validation, and all original package files are unchanged from v1.0.1.
A self-test failure happens before the actual analysis starts.

PURPOSE
Continue the existing v1.0.0 run, including configuration af114813b1ad.
The complete original package is included byte-for-byte in original/.
This is an execution optimization: the 90-day rules, no-spacing sample,
author exclusions, all-time leave-pair-out score, controls, outcomes, eight
balance traits and shared-account-OR-date CR0 formula remain unchanged.
All bridge fits and expanded entry/ordinary placebo analyses remain included.

START
1. Stop the old terminal with Ctrl-C once and wait for its shell prompt.
2. Extract this ZIP to a new directory and run RUN_FAST_RESUME.command with:
   --project /Volumes/XT_Pro/lichess_kindness
   --resume-root /Volumes/XT_Pro/lichess_kindness/derived/replication/receipt_iv_uniform90_v100_PRIVATE/af114813b1ad
No --workers or --memory-gb is needed: the launcher detects physical RAM
and CPU count. On the supplied M3 Pro / 18 GB machine, it targets 13.5 GiB
for computation, leaving about 4.5 GiB for macOS and other applications.
Optional overrides remain available. The memory setting is a scheduling
and allocation estimate, not an operating-system hard RSS limit.

CHECKPOINT REUSE
The existing config.json, original producer manifest and scientific rule
must authenticate. Its original source bindings are read from that config.
The data configuration hash and run directory stay unchanged. The new
execution manifest is recorded separately in report/execution.json and
PRIVATE/execution_versions/. Completed outputs retain their original bytes
and receipts. Existing volume parts are checksum-verified and summed; only
unfinished files are scanned. An interrupted in-flight file/fit restarts.
Do not run the old and new commands simultaneously. The same RUN.lock
prevents concurrent writers. Other active research runs are also checked.

WHAT IS FASTER
- Volume lookups encode (account rank, millisecond timestamp) as an exact,
  order-preserving uint64. Bounds and duplicate timestamps retain their
  original semantics. Unsupported integer ranges use the original lookup.
- Volume workers scale to detected CPUs and the estimated working memory;
  there is no blanket two-worker cap on this stage.
- FE columns are projected independently in up to four parallel threads,
  using the existing sorted group means, energy checks, tolerance and final
  orthogonality certificate. In-memory fits avoid repeated disk flushing.
  Larger fits use bounded private column buffers and serialized disk writes.
- Standard errors use the earlier R9 grouped NumPy implementation when it
  fits, with no duplicated two-role score matrix. Larger jobs retain exact
  partitioned CR0, with a partition count matched to input size. Existing
  compatible disk-covariance leaves are reused when that path is selected.
- Independent fits are scheduled concurrently only when their estimated
  peak allocations fit together. BLAS stays at one thread per worker to
  avoid nested oversubscription. The main IV runs immediately after the
  mandatory legacy coefficient/SE replay; then balance and bridge fits run.

OUTPUT AND PROGRESS
Existing 25/50/75/100 checkpoint filenames are retained, under
~/Desktop/Lichess_Desktop. Their percentages denote completed stages,
not elapsed-time fractions. MAIN_IV_READY prints the new main coefficient
and standard error before the remaining diagnostics finish. The final
report is UNIFORM90_IV_af114813b1ad_100.zip with its SHA256 sidecar.
The report records both scientific and execution identities.

TESTS AND TIMING
The launcher runs the included tests before starting. They check original
scientific rules, exact volume boundaries and repeated rows, reuse of old
per-file checkpoints, coefficients/SEs/balance and contrasts against v1.0.0,
parallel and disk projections, concurrent fits and partial-export handling,
hardware settings, routing, and rejection of mismatched configurations.
The original private-data legacy replay also remains a mandatory run gate.

evidence/benchmark.json reports synthetic kernel timings from Linux here:
about 4.0x faster volume lookup, 4.6x faster covariance and 2.1x faster
projection, with matching outputs. These are not full-run Mac timings.
Private-data end-to-end runtime has not been measured. New entry/placebo
metadata requests, if necessary, can still dominate overall elapsed time.
All completed metadata caches are reused under the original rules.
Use --offline to stop with a needs report rather than fetching missing IDs.

To repeat the optional synthetic benchmark (not needed to run the analysis):
  python benchmark_kernels.py
