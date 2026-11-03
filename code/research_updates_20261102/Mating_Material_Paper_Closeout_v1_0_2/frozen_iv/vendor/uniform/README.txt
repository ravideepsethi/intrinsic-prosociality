Receipt IV Uniform90 — checkpoint-compatible parallel resume v1.0.5

RUN
Download the ZIP to ~/Desktop/Lichess_Desktop.
If the Uniform90 parent is still running, press Ctrl-C in THAT terminal once and
wait for the shell prompt. Leave the separate Model5 supplement waiting terminal
open. Do not run two Uniform90 parents against the same resume directory.

After extracting this package, run:

bash RUN_FAST_RESUME.command \
  --project "/Volumes/XT_Pro/lichess_kindness" \
  --resume-root "/Volumes/XT_Pro/lichess_kindness/derived/replication/receipt_iv_uniform90_v100_PRIVATE/af114813b1ad"

The launcher verifies package hashes, reuses an installed Python environment,
runs the tests, and prevents sleep. No dependency upgrade is required if the
existing environment passes. Existing locks are respected, never removed.
If the parent has already produced a verified 100 report, no rerun is needed.

WHAT IS REUSED
- The same scientific configuration and original v1.0.0 producer manifest.
- Completed receipt selection, 90-day features, models, and all later valid stages.
- All sealed chronology scans; no new raw scan for a completed scan job.
- The independently verified v1.0.4 repair, using its existing path and identity.
- Completed query partitions, scan partitions and first-pair groups.
- Every valid completed classification leaf, including leaves within a partly
  finished group and smaller leaves created by a previous memory retry.
- Existing metadata, later features and fitted comparisons when their unchanged
  dependency/checksum checks pass.

The Model5 S1/S4/S5/S7 results remain in their separate completed run. This update
finishes the parent entry/placebo pipeline; its waiting finalizer then assembles
the combined submission report without refitting completed supplements.
Only unsealed work can need repeating. Nothing is inferred from a partial file.

WHAT IS FASTER
1. Completed chronology scans are authenticated in parallel in the main stage
   process, avoiding worker-process handoffs for jobs that need no computation.
2. Independent first-pair and classification groups run concurrently. On the
   observed 18 GiB / 12-core Mac, the default is three groups, up to four SQL
   threads each, with a 3.5 decimal GB SQL limit per group and additional RAM
   reserved for Arrow/Python. A smaller machine automatically uses fewer groups.
3. Completed leaves are recognized before reading candidate payloads.
4. Each unfinished group's needed candidate payload is read once into a spillable
   table. Each bounded leaf is materialized once for the repeated adjacency and
   volume calculations. Memory pressure falls back to bounded reads/smaller leaves.
5. Within each process, SHA256 digests are reused only while resolved path,
   device, inode, size, nanosecond modification time and change time remain equal.
   Every process/restart hashes a file on first use. Expected output hashes and
   original dependency guards still apply; no persistent hash cache is trusted.

The original 90-day histories, no-gap/no-spacing rule, support, score, exclusions,
outcome definitions, estimator, covariance and adjacency SQL remain unchanged.
Every file under original/ remains byte-identical to v1.0.4. The repair/oracle,
feature and estimation engines are also unchanged.

LOGS AND FINISH
CLASSIFICATION_RESUME reports already-complete groups, reused leaves and groups
still requiring work. The following ETA covers ONLY unfinished classification.
Startup still verifies saved files; progress through old stages is not refitting.
Metadata retrieval, subsequent feature construction and comparisons remain part
of the total runtime. The fixed 100 GiB storage threshold is unchanged.

Expected parent output:
  ~/Desktop/Lichess_Desktop/UNIFORM90_IV_af114813b1ad_100.zip
Expected combined output from the separate waiting supplement runner:
  ~/Desktop/Lichess_Desktop/MODEL5_SUBMISSION_384bab3c77d7_100.zip
Its success marker is ALL_AGREED_PRE_SUBMISSION_COMPUTATIONS_COMPLETE.
Keep the ZIPs and their generated .sha256 files for final result review.
If the supplement waiter was closed, rerun its existing Model5 launch command;
its completed fits are checkpointed and reusable. This ZIP runs the parent only.

VALIDATION
50 local tests passed, including exact frozen-output comparisons, concurrent
connections, mid-group v104 restart, old memory-split reuse, memory fallback,
large unsigned IDs, missing candidates, checksum tamper rejection, physical
repair verification, history boundaries, and covariance/estimator parity.

Synthetic restart/classification benchmark: 64,000 query rows and 2,048,000
candidate summaries, 64 leaves. v104: 8.158 s; v105: 1.402 s (5.82x); all output
fields identical. This uses Linux, synthetic data and a warm filesystem cache;
it is not a measured speedup or total ETA for the private Mac/SSD data.
See evidence/validation_v105.json and evidence/benchmark_v105.json.
The private full-data run has not been executed in this environment.
