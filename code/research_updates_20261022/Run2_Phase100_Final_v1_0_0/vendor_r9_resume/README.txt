R9 ENV MEMORY REPAIR AND RESUME — v1.0.1

Purpose
Resume the stopped 4028bf3e1857 certified leave-pair-out run. This is an
execution repair, not a new scientific configuration. It carries the exact
original R9 package and changes only ENV memory scheduling and log rendering.
It does not edit the manuscript or the completed baseline 2a4e617b40bc.

What happened
The run stopped on 2026-10-12 at 20:15:32 UTC in env_rates.chronology_job
while writing an aggregate Parquet result. DuckDB had a 1 GB decimal limit
(953.6 MiB); it could not pin another 256 KiB block. The R9 launcher allowed
five ENV workers with a 1.6 GiB reservation each. That per-query DuckDB limit
was too low. Reducing --workers alone would not raise the 1 GB query limit.

What the returned checkpoint certifies
- ZIP SHA256 matches its sidecar:
  daacbc4a25b64b4443563fa2cabdca5679726f2f770e3d7036588e61ef360229
- Every member in REPORT_MANIFEST.json matches its byte count and SHA256.
- All 14 baseline models pass, with maximum absolute numerical difference 0.
- Saved S0 and F50 scores pass all replay checks.
- The 16 donor shards, score combination, ordinary subset and learning flags
  completed before the failure. Full S0 has 2,682,329 rows; no row lacks five
  strictly-before donors. The timing-common sample has 2,313,179 rows.
- This run selected Phase 075: F=11,057,763; O=7,146,627. A resume keeps that
  original snapshot, even if Phase 100 becomes available later.
- The report is STOPPED_RETURN_LOG at 25%. No new receipt, entry, placebo,
  paired timing or balance estimates are certified yet.

Descriptive score diagnostics already available
                    S0 full             F75
Mean donors         72.6726             62.3850
Median donors       52                  45
Donor links after   47.3120%            47.1562%
Different month     93.0582%            93.7148%
Corr with old score 0.9999898432         0.9999901489
These are score diagnostics, not results for the new IV specification.

Repair
- Normal ENV tasks: at most 2 workers, each with a 3 GB decimal DuckDB limit
  and a 4.5 GiB scheduler reservation. Reservations include non-DuckDB memory.
- If a task raises DuckDB OutOfMemoryException, all normal workers finish and
  exit before only the failed tasks retry with 1 worker, an 8 GB DuckDB limit
  and a 9 GiB reservation. A second OOM stops with the log preserved.
- Non-memory errors stop normally. Hash, identity, dependency, cohort and
  scientific checks remain in place. No failure is converted into success.
- The total default planning budget remains 11 GiB, including 1.5 GiB reserved
  by the original scheduler for the parent. This is a planning reservation,
  not an operating-system memory cap.
- SQL, authors, windows, pair exclusion, counts, controls, samples, estimators,
  covariance, scaling and adoption rule remain byte-for-byte frozen.
- Projected Parquet reads, ZSTD output, spill directories, one DuckDB/BLAS
  thread per worker and the original scheduler for non-ENV tasks are retained.
- DuckDB progress bars are suppressed. Stage and throughput ETAs remain.
- Failed partial directories are retained for diagnosis; they are not used as
  completed checkpoints. Successfully completed ENV parts are verified/reused.

Run from a fresh Terminal after downloading ZIP and SHA256 to:
  ~/Desktop/Lichess_Desktop

  cd "$HOME/Desktop/Lichess_Desktop" &&
  shasum -a 256 -c R9_ENV_Memory_Resume_v1_0_1.zip.sha256 &&
  r9_resume_tmp="$(mktemp -d "${TMPDIR:-/tmp}/r9-resume.XXXXXX")" &&
  ditto -x -k R9_ENV_Memory_Resume_v1_0_1.zip "$r9_resume_tmp" &&
  bash "$r9_resume_tmp/R9_ENV_Memory_Resume_v1_0_1/RESUME_R9.command" \
    --workers 10 --memory-gb 11

The launcher uses /Volumes/XT_Pro/lichess_kindness/venv/bin/python and
caffeinate when available. IV_PROJECT_ROOT, IV_DESKTOP and IV_PYTHON retain
their existing override meanings. No new dependencies, API calls or Stockfish
searches are requested. The package is self-contained: the original extracted
temporary R9 folder is not needed.

ETA
Roughly 1.5–3 hours for the remaining run; possibly longer if many large parts
require serial retry or drive contention is high. The first phase verifies
existing checkpoints and reads hashes; it should not refit completed baseline
models or rescan completed donor shards. Log lines may still name those stages
while their saved outputs are checked. ENV scheduling prints measured ETAs
every 30 seconds; outer preparation/merge ETAs are planning estimates.

Provenance and resume contract
Scientific configuration:
  4028bf3e185783a17679ed3d5fee5b376028f37141e1e5ce09b93b068a6a6e0b
Original scientific package-manifest SHA256:
  450837fec023b0b4157345b640d9997b2779da71daa7f003d7562d17867e8874
Run root:
  /Volumes/XT_Pro/lichess_kindness/derived/replication/
  r9_certified_leave_pair_out_v100_PRIVATE/4028bf3e1857

The wrapper verifies its own manifest and the complete frozen package, then
requires this exact configuration and its passed baseline/score gate. It pins
the saved comparison root and calls the original R9 runner. That runner still
obtains RUN.lock and rechecks all ordinary input and checkpoint contracts.
Before report regeneration, a timestamped runtime_repairs subdirectory stores
the preceding aggregate report and existing exported report ZIPs. Execution
metadata identifies the repair manifest, unchanged scientific package, actual
memory plan and retry counts. This metadata is included in subsequent report
summaries. config.json and completed stage receipts are not rewritten to
pretend they came from a different scientific implementation.

Outputs and what to return
The usual 25/50/75/100 report ZIPs and SHA256 sidecars remain in Lichess_Desktop,
with configuration prefix 4028bf3e1857. The new run log begins R9_ENV_RESUME_.
Return the 100% ZIP, its sidecar and the log. If another error occurs, return
the latest checkpoint ZIP, sidecar and new log. The wrapper can be rerun to
resume; it exits without modifying a run already at 100%.

Validation limits
The bundled original estimator tests and targeted repair tests run before
resume. Repair checks cover independent exact counts across memory limits,
author/role/time boundaries, checkpoint reuse without SQL, dependency-change
rejection, process spawning, selective OOM retry, fail-closed retry exhaustion,
and preserved report/audit routing. The production Parquets exist on the Mac;
the repaired full production scan has not been executed in this workspace.
