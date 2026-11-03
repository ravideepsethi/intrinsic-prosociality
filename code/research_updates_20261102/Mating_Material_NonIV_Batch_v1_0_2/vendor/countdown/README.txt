COUNTDOWN ESTIMATION 1.0.0

Reuses the completed COUNTDOWN_FEASIBILITY_7a268eb12b55 run. No additional API
data, Stockfish evaluations, full-panel rebuilding, or receipt-IV estimation.

QUICK START
Save the package ZIP and its .zip.sha256 in ~/Desktop/Lichess_Desktop and use
the accompanying terminal command. The launcher verifies every packaged file,
runs eight synthetic tests, finds an existing Python environment, and uses
caffeinate on macOS. It does not install packages automatically.

Default project: /Volumes/XT_Pro/lichess_kindness
Default results: ~/Desktop/Lichess_Desktop
Resources: --workers 4 --memory-gb 11
Dependencies: Python 3.10+, numpy, scipy, duckdb, pyarrow, matplotlib.
The launcher searches the current, project, and recent author-exclusion Python
environments. Set COUNTDOWN_PYTHON=/absolute/path/to/python if needed.

INPUT AND STORAGE
The exact completed feasibility key, input identity, row count and source
lineage are pinned under authority/. The runner checks monthly receipts,
feature hashes, and upstream source signatures. It accepts only the completed
author-excluded 41,534,289-row source used for the supplied feasibility report.
It never substitutes an older unfiltered main sample.

Expected input root:
  derived/replication/countdown_feasibility_v100_PRIVATE/7a268eb12b55/
Use --reuse-feasibility-root only if this same verified run has another location.

Private working files and fitted-model checkpoints go to:
  derived/replication/countdown_estimation_v100_PRIVATE/<run key>/PRIVATE/
Only aggregate estimates, covariance matrices without account labels, sample
counts, numerical diagnostics, and figures are exported. Account IDs and
cluster contributions remain private. The original inputs are read-only.
At least 16 GiB free project-drive space is required. Temporary columns and
working matrices are deleted after each fitted model is certified; completed
model and cluster-score caches remain available for resume and later review.

WHAT RUNS
1. Verify the feasibility output and write narrow speed-specific numeric files.
2. Benchmark a deterministic 1/64 subset of whole choosers in the largest speed.
   Its fitted coefficients stay private; only timings and counts are reported.
3. Fit the primary adjusted profile separately by speed, jointly across pre/post.
4. Repeat with one-times and two-times fixed long-clock proxy restrictions.
5. Repeat with two alternative calendar windows.
6. Fit monthly profiles and calculate joint preperiod stability diagnostics.

There are up to 145 planned model cells: five speed categories times five
main/robustness families plus five times 24 monthly diagnostics. The supplied
data have no ultraBullet rows; these 29 cells are explicitly recorded as NO_ROWS.
With that coverage, 20 main/robustness and 96 monthly models are potentially fit.
All variants are reported, including unsupported or unidentified comparisons.
Most monthly fits are much smaller than the joint pre/post models.

MODEL
Outcome: draw grant, in percentage points. Sample: non-mate raw evaluation
strictly below -100 cp; material deficits 0..8. Reference deficit: 3.
Main profile is saturated in deficit x period, separately for each speed.
Absorbed effects: chooser, evaluation10 x stage x period, and calendar month.
Numeric controls: log1p of both last-recorded clocks, rating gap/100, and chooser
rating/100, with separate slopes by period. All are implicitly speed-specific.
Stage bands: ply 0-10, 11-20, 21-40, 41-80, 81+. Iterative fixed-effect singleton
removal and all resulting sample counts are reported.

Primary pre: before 2025-07-19. Primary post: from 2025-08-11.
Alternative A: pre before 2025-07-01; post from 2025-08-01.
Alternative B: pre before 2025-07-01; post from 2025-09-01.
All three use unrestricted clocks. Clock variants use the primary dates and
identical cutoffs in both periods: bullet/ultraBullet 40s, blitz 60s, rapid 120s,
classical 300s; then twice those. The inequality is strictly greater.

The primary threshold contrast is an equal-weight linear extrapolation from
adjusted deficits 0..3 to 4. It is 0.5*mu0 - 0.5*mu2 - mu3 + mu4. The quadratic,
symmetric, local-linear, neighboring-step, and same-side placebo contrasts are
also reported. Exact weights and specification are included in the code and
SPECIFICATION.json; no outcome-dependent tuning is performed.

INFERENCE AND INTERPRETATION
Read INTERPRETATION.txt before interpreting coefficients. Main inference uses
chooser-clustered CR0 and joint uncertainty across periods and speeds. Date-only
and chooser-plus-date covariance checks apply to the main and symmetric
contrasts. No independence across repeated players is assumed. Unsupported
contrasts and negative two-way variance estimates are explicitly flagged.

The primary figure shows observed-composition standardized adjusted levels,
95% chooser-clustered intervals, and retained counts. Cross-period levels have
different standardization populations; local contrasts cancel those anchors.
Fixed speed weights are used when pooling pre/post contrasts.

The curvature sensitivity is a conservative bias-expanded normal interval under
an explicit discrete second-difference bound. It is not an implementation of
the optimized Kolesar-Rothe procedure. There is no causal bias correction,
no inferred deployment date, and no decomposition of selection versus behavior.
The specification was fixed after the feasibility report and raw rates were
seen; this is an exploratory analysis, not a preregistration.

CHECKPOINTS — THESE ARE PHASES, NOT EQUAL DURATIONS
025: primary estimates, joint covariance, policy contrasts and figures.
050: both clock sensitivity families added.
075: both alternative calendar windows added.
100: monthly diagnostics and final output complete.
Each checkpoint has a ZIP and SHA256 sidecar. The 025 ZIP can be reviewed while
the remaining analyses run. Return the final 100 ZIP and its sidecar when done.

Report directories primary/, clock_long/, clock_twice/, calendar_august/,
calendar_september/ contain:
  adjusted_profiles.csv, adjusted_profiles.pdf, adjusted_profiles.png
  all_profile_contrasts.csv
  threshold_and_policy_tests.csv
  joint_profile_covariance.npz, joint_contrast_covariance.npz
  curvature_sensitivity.csv
  coefficients_and_support.csv, numerical_checks.json, model_status.csv
The monthly/ directory contains monthly profiles/contrasts, covariance files,
preperiod equality tests, and monthly figures. NPZ files contain named NumPy
arrays and string labels; loading does not require pickle.

SPEED, MEMORY AND ETA
Each speed model uses only 24 explicit regressors; monthly models use 12.
High-dimensional effects are projected with a symmetric conjugate-gradient
algorithm. Every column must pass an original-group residual-mean tolerance of
1e-9 in its original units. Coefficient rank and residual variation are reported.
No ridge regularization or relaxed convergence is used to force completion.

At most four worker processes run, with one numerical thread each. The scheduler
reserves memory by model size and can run fewer workers for large models. The
11 GB option is a scheduling target, not an OS-enforced RSS cap. Sparse counts,
memory-mapped columns, and small matrix solves limit memory use.

The startup benchmark reports a rough on-machine timing estimate. Progress
reports give next-checkpoint and finish estimates, updated from actual fitted
models. Small/empty cells are not used to extrapolate massive runtimes. Shared
drive activity, memory pressure, and projection conditioning can change speed.
There is no production runtime guarantee from the small synthetic benchmark.

RESUME AND ERRORS
Rerun the same command with the same package, project and inputs. Fitted models
are hashed and reused. If a model was interrupted, completed FE columns are
reused after verifying both their hashes and the exact model row/design layout.
One countdown-estimation launcher per project is permitted.

Exit 0 means the planned workflow completed; it does not imply every contrast
was estimable. Inspect model_status.csv and inference_status columns.
Exit 2 means BLOCKED; the latest checkpoint contains STATUS.json with the reason.
The full traceback is kept privately in ERROR.txt. Numerical convergence,
changed inputs, or changed checkpoints stop the run instead of silently changing
the specification. Upload the blocked ZIP if that happens.

VALIDATION
See VALIDATION.txt. Tests compare the numerical estimator against an independent
dense fixed-effect projection, exercise joint covariance with recurring players,
and run authentication, scheduling, report export and resume on synthetic data.
The full private Mac regression sample has not been executed in this session.

Numerical references:
https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.linalg.cg.html
https://pyhdfe.readthedocs.io/en/stable/_api/pyhdfe.create.html
