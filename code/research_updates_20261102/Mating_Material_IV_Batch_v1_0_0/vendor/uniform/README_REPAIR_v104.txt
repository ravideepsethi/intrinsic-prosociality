Receipt IV Uniform90 — independently verified chronology repair v1.0.4

START
Leave the Model5 supplement waiting terminal open. The prior Uniform90 terminal
has returned to its prompt. Run this replacement in another terminal:

bash RUN_FAST_RESUME.command \
  --project "/Volumes/XT_Pro/lichess_kindness" \
  --resume-root "/Volumes/XT_Pro/lichess_kindness/derived/replication/receipt_iv_uniform90_v100_PRIVATE/af114813b1ad"

WHY v1.0.3 STOPPED
The new log passed storage preflight and reused all 798 saved chronology scans.
Scan 711 has 139 missing sample_row and role fields. The strict-time reconstruction
also disagreed with some identified original rows. v1.0.3 correctly stopped rather
than assuming either version was correct. The log does not reveal which fields
or how many identified rows differ, or prove an engine-specific cause.

WHAT v1.0.4 CHANGES
1. Keeps every byte in original/ and the scientific configuration unchanged.
2. Audits saved scan keys and reconstructs only affected scans, in a separate
   chronology_scan_repair104 directory. Originals remain untouched.
3. Compares the reconstruction to the original, recording differing row and
   field counts. Every identified original key must still be represented.
4. Independently verifies EVERY added or changed candidate row against physical
   raw games from that shard. This uses Arrow grouped counts and NumPy binary
   searches over all valid event times: no ASOF, SQL window, or history thinning.
   It verifies predecessor time, multiplicity, game ID, opponent, focal counts,
   focal-game matches, and [start-30 days,start) game counts. This 30-day field is
   a legacy chronology diagnostic; the model histories remain uniform90.
5. Accepts changed values only when the strict-time reconstruction and the
   independent raw calculation agree exactly. If they disagree, it stops and
   exports aggregate failure information; it does not disable validation.
6. Keeps the strict equality check for pair minima. Rejects unexpected or
   duplicated identified original keys. Preserves query-role coverage.
7. Reuses valid completed partitions. A corrected source affecting an already
   completed partition gets a separate branch, with old output preserved.
8. Continues all remaining entry/placebo stages. The waiting supplement runner
   detects the verified Uniform90 100 report and builds the combined report.

The raw verifier reads ONE affected shard per repair, not all 798 raw shards.
There are two raw reads of that shard: reconstruction and independent checking.
Oracle events are partitioned into 64 groups on disk. Its own temporary groups
are removed only after successful verification. Original checkpoints are never
removed. Completed repairs and verifications resume without repeating the scan.
The public audit contains counts and hashes; row-level differences stay private.

WHAT IS ALREADY DONE
S1 recipient-weighted IV, S4 OLS, S5 transformed-outcome diagnostics, S7 recipient
counts, and baseline coefficient/SE reproduction passed. The newly uploaded
supplement report is WAITING_PARENT, with no supplement error. These fits are
not repeated. No new substantive specification is introduced.

COMPLETION
Leave the Model5 waiter open until it reports:
ALL_AGREED_PRE_SUBMISSION_COMPUTATIONS_COMPLETE
The combined file is MODEL5_SUBMISSION_384bab3c77d7_100.zip, with its .sha256.
The Uniform90 100 report alone is not the combined submission bundle.

RUNTIME AND STORAGE
Full-data v1.0.4 has not run on your Mac. Remaining chronology classification,
metadata, features and comparison fits can still take hours. The old two-minute
ETA described partitioning only. Checkpoint verification also takes time.
This version reports actual free space before the unchanged 100 GiB startup
threshold. That threshold is a precaution, not a measured remaining-space claim.
Hardware detection, model parallelism and the existing run locks are unchanged.

VALIDATION
The test suite includes the original estimator and chronology checks plus
independent raw-game checks against a brute-force reference, simultaneous
missing-key and non-missing-value damage, refusal of incorrect reconstructions,
private-original preservation, repair resume, and separate merge checkpoints.
See evidence/validation_v104.json and evidence/test_results_v104.txt for the
actual local test result. Earlier evidence files describe their earlier versions.
