MATING MATERIAL IV RESUME 1.0.6
Prepared 31 October 2026, Toronto

SAVE AND RUN
Save Mating_Material_IV_Resume_v1_0_6.zip in ~/Desktop/Lichess_Desktop.
Run these lines together:

  iv_dir="$HOME/Desktop/Lichess_Desktop"
  unzip -n -q "$iv_dir/Mating_Material_IV_Resume_v1_0_6.zip" -d "$iv_dir" &&
  bash "$iv_dir/Mating_Material_IV_Resume_v1_0_6/RUN_IV_RESUME.command"

EXPECTED RUNTIME
Allow 2–3 hours after restart, provisionally. Startup tests take about
1–2 minutes. External-drive I/O, verification and any newly missing factual
opponent histories can extend this estimate. This is not a full-size Mac
benchmark or an estimate for completing the entire paper.

Only comparison_frames and comparison_models remain in this batch. All
sixteen completed stages are skipped. The completed metadata reconciliation,
16 history workers, 31.8-million-row history attachment, factual volume
(including the 852 scans), 24 role workers and final labels are verified and
reused. No metadata download, Stockfish evaluation or rating replay runs.

XT_Pro must be mounted. The existing MatingMaterial_IV_Env_v100 is reused.
Defaults remain 10 workers maximum, 11 GiB total compute allowance, one BLAS
thread, at most two heavy data tasks and sequential model fits. Allow at
least 160 GiB free for frames, isolated partitions and spill files.
Caffeinate prevents idle sleep on macOS; keep the Mac plugged in.

WHY THE LAST RUN STOPPED
Version 1.0.5 passed the previous memory bottleneck and completed the history,
volume and label attachments. At 2:02 p.m. Toronto on 31 October, the next
step failed while checking agreement among the cached opponent-environment
records. The original query grouped all cache keys at once and maintained
separate distinct-value states for several columns. DuckDB exhausted its
8.3 GiB allowance. This was another large aggregation in the supplied code.
The returned report contains no evidence that completed results were damaged.

WHAT THIS REPAIR CHANGES
The environment caches are read once into 128 partitions by person ID.
Every copy of a person/partner/month key goes to the same partition, including
copies in different caches. The original value agreement, floating tolerance,
mixed-null check and cache priority are preserved. Nonfloating scalar
agreement uses min/max rather than a separate distinct-value hash table.
Each partition is checked and committed independently with a 3 GiB SQL cap.

The same partitioning covers the following environment request anti-joins,
material-event corrections and narrow row lookups. The unused intermediate
wide attachment of uncorrected environment values is omitted. The final
corrected environment is attached to the unchanged wide comparison rows by
a streaming merge with exact row-ID coverage checks.

Right-hand Parquet row groups are bounded across all open readers, not just
per reader: at 128 shards each group is at most 8,192 rows; the total ceiling
is 1,048,576 rows. Oversized groups are normalized one input at a time into
temporary files. Source caches and their checksum receipts remain untouched.

STATISTICAL DEFINITIONS
The sample definitions, author exclusions in both roles, five-decision support
rule, first-pair rule, time windows, zero-coded outcomes, environment arithmetic,
estimators and shared-account-or-date CR0 covariance are unchanged. All-game
environment denominators remain factual; the same removed decision events
are subtracted from their numerators. The original chronology scanner handles
any missing factual histories. This repair does not relax a failed data check.

Completed estimates are authenticated and not recomputed. All frozen vendor
files and model kernels are byte-identical to the prior package. The new
execution paths are tested against the original SQL and on larger synthetic
inputs. VALIDATION.json records the actual results and benchmark limitations.

RESUMING AND PROVENANCE
This continuation targets reviewed run 12093d55b7ee9f73 at:
  /Volumes/XT_Pro/lichess_kindness/derived/replication/
  mating_material_iv_batch_v100_PRIVATE/12093d55b7ee9f73
It requires the sixteen-stage checkpoint and the newly completed comparison
substeps. It cannot start a new full rerun. The statistical configuration and
original package identity remain unchanged; REPAIR_V106.json records this
execution repair. Earlier REPAIR_V101 through REPAIR_V105 receipts remain.

Rerun the same command after an interruption. Committed stages and partition
outputs are verified and reused. Analytical execution blocks network access.
Environment installation can contact the package index only if the existing
pinned environment needs installation. Startup synthetic test messages go to
Lichess_Desktop/Logs; production begins after the explicit startup notice.

WHAT THE PAPER STILL NEEDS
This batch finishes the entry diagnostic, ordinary-ending opponent-score
placebo, their balance tests and the joint reduced-form comparison. These
support central identification claims in the current paper.

Afterward, retain the separate ordinary-draw-versus-loss comparison, one
material-threshold sensitivity, and any further balance checks needed for
specifications retained in the paper. Several detailed appendix exercises
can be omitted if their claims and tables are removed consistently.
PAPER_COMPLETION_PLAN.json records this recommendation. It is a recommendation,
not an instruction that deletes manuscript content or suppresses results.

Every numerical result retained in the corrected-sample paper must be rerun
or explicitly verified as unaffected. No old estimate is silently substituted
for unfinished work. The manuscript's material definitions, numerical text,
tables and figures still need reconciliation and a complete compile/review.

RETURN THESE
The consolidated desktop outputs are updated after each stage:
  MATERIAL_IV_BATCH_12093d55b7ee9f73_RETURN.zip
  MATERIAL_IV_BATCH_12093d55b7ee9f73_RETURN.zip.sha256
Return that ZIP and checksum. Private Parquets and game records stay on XT_Pro.
BATCH_COMPLETE certifies these eighteen stages, not the entire paper.
COVERAGE.json retains the full unfinished-work inventory.

Optional verification without running unfinished analysis:
  bash "$HOME/Desktop/Lichess_Desktop/Mating_Material_IV_Resume_v1_0_6/RUN_IV_RESUME.command" --preflight-only
