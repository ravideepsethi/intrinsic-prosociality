MODEL 5: FINAL PRE-SUBMISSION COMPUTATIONS — v1.0.0

RUN THIS IN A NEW TERMINAL. LEAVE THE UNIFORM90 ENTRY/PLACEBO JOB RUNNING.

    bash RUN_SUBMISSION.command

Defaults are already set for the existing project and run:
  Parent: /Volumes/XT_Pro/lichess_kindness/derived/replication/receipt_iv_uniform90_v100_PRIVATE/af114813b1ad
  New workspace: ~/Desktop/Lichess_Desktop/Model5_Submission_PRIVATE/<configuration>
  Reports: ~/Desktop/Lichess_Desktop

What happens, without another manual stage
----------------------------------------
1. Verify this package, run the regression tests, and authenticate the completed
   075 receipt-model stage, its original producer, input dependencies and row set.
2. Snapshot its completed source and score files onto the internal drive. The
   parent remains read-only, including its configuration, checkpoints and lock.
3. Produce S7 counts; refit the primary model alongside same-frame OLS (S4) and
   the optional transformed-outcome diagnostics (S5); reproduce all four primary
   coefficients and standard errors before accepting these results.
4. Fit recipient-weighted IV (S1), then calculate dependent-sample contrasts using
   joint influences and the inherited shared-account-OR-date covariance formula.
5. If necessary, wait for the existing Uniform90 100 ZIP. No model arrays are kept
   in RAM while waiting. Verify its checksum, manifest, scientific definition,
   completed entry/placebo models, and unchanged primary result.
6. Produce ONE final MODEL5_SUBMISSION_<configuration>_100.zip containing all
   agreed analyses, CSV and LaTeX tables, provenance, and READ_RESULTS_FIRST.txt.
   No manual merge, follow-up fit, or routine upload of intermediate files is needed.

The 100 suffix is written only after BOTH jobs' agreed computations are complete.
The log ends with ALL_AGREED_PRE_SUBMISSION_COMPUTATIONS_COMPLETE.
Check report/STATUS.json and report/COMPLETION.json in the ZIP for COMPLETE.
Use report/tables/ for the manuscript; the unchanged parent aggregate reports are
preserved under report/parent100/. Private rows and influence files are excluded.
Interpretation flags do not launch additional analyses. Finishing computation
does not certify causal identification or replace updating the manuscript.

Scientific definitions
----------------------
Fixed primary frame: 9,736,182 exposures; 1,877,395 recipients. No spacing or caps.
History: [exposure game start minus 90 days, exposure game start), with no gap.
Outcome, complete-follow-up rule, all-time leave-focal-pair-out Score A, author
exclusions, controls and three fixed-effect families are unchanged.

S1: w_it=1/n_i, where n_i counts ALL retained Model 5 rows for recipient i.
Each recipient has total weight one. Weights enter fixed-effect projection,
control residualization, regression moments, and influence functions. This is
weighted 2SLS on the existing frame, not a recipient fixed-effect regression.
The report includes weighted first stage, RF(y), RF(reached), IV(y), first-stage
Wald F, and the IV/first-stage/RF(y) differences from exposure weighting with
their actual joint covariance.

S4: unweighted OLS of y on received using exactly Model 5's rows, controls and
fixed effects. OLS-minus-IV inference retains within- and across-account/date
covariance. Outcome coefficients are in percentage points per receipt.

S5: IV with YD, and negative IV with Y(1-D), formed BEFORE any projection.
These are probability-unit transformed-outcome diagnostics, not a certification
of monotonicity. Complier-mean interpretation requires additional exogeneity,
exclusion, monotonicity and weighting/specification assumptions. The identity is
mu1 - mu0 = IV/100 when the main IV is reported in percentage points. No estimate
or variance is clipped. S5 alone is not a submission gate.

S7: exact integer histogram, recipient-count quantiles (linear interpolation),
shares above 1/10/20/50/100 rows, singleton share, mean and maximum; cross-checked
against the parent overlap audit.

Inference: inherited CR0 accounts - unordered pairs + dates - account/date +
pair/date, including role overlap. Scores are treated as fixed. Partitioning
preserves full grouping keys. Reused outcomes/repeated recipients remain in all
calculations. The unweighted producer's control transforms are reused; weighted
FWL is invariant to their existing affine standardization.

Included parent results: all receipt bridge specifications and balance, expanded
entry, ordinary-game placebo, their balance, receipt-minus-ordinary contrasts,
and the inherited ordinary-game equivalence test. S2 caps, S3 row creation,
S6 new control-deletion fits, S8 donut scores and a first-row model are not added.

Concurrent execution and resources
----------------------------------
The active parent keeps its own hardware policy. This independent process uses
the internal SSD for memory-mapped designs and spill files, one model fit at a
time, one BLAS/Arrow/SQL thread, and partitioned covariance. Its SQL working limit
is 1 decimal GB per connection; that is NOT a total process or system RAM cap.
It has lower scheduling priority and yields at allocation boundaries when macOS
reports less than 1.5 GiB of free/inactive/speculative memory. This is a scheduling
hint, not a promise of an exact RSS ceiling. Completed data are copied only once.
Do not start a second copy of this supplement runner; its own lock prevents it.

Allow roughly 20 GiB free on the internal drive, or input size plus 18 GiB if
larger; the launcher checks before beginning. No raw-history scan, API lookup or
new outcome construction is performed. The 25/50/75 checkpoints are milestones,
not percentages of elapsed time. Per-column and covariance progress is logged.
Full-data elapsed time depends on contention with the parent; it has not been
benchmarked here on the private 9.7-million-row frame or the user's Mac.

Interruptions, waiting and options
---------------------------------
Rerun the SAME command after an interruption. Hash-verified completed phases and
covariance leaves are reused. A crash during a fit repeats that fit's projection;
already completed covariance leaves remain reusable. A completed supplement run
only reassembles the final report on restart. Never remove parent locks.

If the parent fails, this runner logs that the parent needs resuming and continues
waiting; it cannot manufacture a valid entry/placebo result. Resume the parent
with its existing v1.0.2 command. The supplement picks up its 100 ZIP automatically.

Optional arguments:
  --parent-root PATH   Existing Uniform90 run directory (scientific identity fixed)
  --parent-report ZIP  Override the location of the Uniform90 100 ZIP
  --work-dir PATH      New private workspace, outside the parent project tree
  --result-dir PATH    Report destination, outside the parent project tree
  --preflight-only     Stop after authentication, design and counts (025)
  --self-test          Run the included tests and exit

The default launcher reuses an installed compatible environment without modifying
it. Only if none is available does it create its own .venv. Set IV_PYTHON to an
existing Python executable if needed. macOS caffeinate keeps the process awake.

Validation shipped with this package
------------------------------------
Nine tests cover independent dense weighted dummy-variable IV/OLS, weight scaling,
raw-product S5 and its identity, frozen baseline coefficients and standard errors,
exact covariance against the pairwise OR rule including role overlap/duplicates,
joint row alignment, source snapshots while the parent lock is held, original
dependency receipts, corruption rejection, complete-report verification, waiting,
and an end-to-end small synthetic run followed by a no-refit resume.
The actual run also must reproduce the private Model 5 baseline before finishing.
