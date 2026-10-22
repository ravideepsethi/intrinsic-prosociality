Competitive-only instrument runner v1.0.0

Runs the reviewed competitive/non-competitive score analysis on the ORIGINAL
2,682,330-row headline IV cohort, INCLUDING author accounts, and the original
307,863-row ordinary placebo. It does not consume the separate expanded receipt
cohort or the expanded ordinary-game frame. See SPECIFICATION.md.

Expected runtime: 20–60 minutes for the first full local run, unbenchmarked for
this package. Offline tests approximately 5–30 seconds. Time depends on available
caches, memory and concurrent SSD work. Stage ETA and measured peak RSS are logged.

Put the ZIP in ~/Desktop/Lichess_Desktop and use the accompanying SHA-verified
terminal command. RUN_COMPETITIVE_IV.command accepts --workers 10, --memory-gb,
--project-root and --desktop. IV_PYTHON selects the existing project Python.
Dependencies: NumPy, PyArrow and DuckDB only. SciPy and matplotlib are not required.
PNG figures are rendered locally by a small NumPy/stdlib plotting module.

The production inputs are private Parquets on /Volumes/XT_Pro/lichess_kindness.
No network requests, new Stockfish work, all-game chronology reconstruction,
exposure reselection or future-outcome reconstruction. The downloader may continue.
The package first reproduces original headline and original placebo results.
It authenticates historical projections and reuses compatible existing Run 2
score indexes. Missing indexes are built once with narrow Parquet projections.
The original fitted state probabilities are algebraically reconstructed from
authenticated original deltas. They are not refit on competitive decisions.

Up to ten local workers are requested; score workers reserve about 1.5 GiB each,
dense model workers reserve 4.5 GiB each plus a 2 GiB overall reserve. Thus an
11 GiB budget permits six score workers and two simultaneous model workers.
Each worker uses one numerical/Arrow thread. Atomic stages reuse completed work.
Unrecognized final checkpoints, changed inputs, unsupported covariances and
failed source reproductions are not silently repaired.

Outputs:
  Project: derived/replication/iv_competitive_only_v100_PRIVATE/<run>/
  Desktop: IV_COMPETITIVE_ONLY_REPORT_<run>.zip and .zip.sha256

Upload only the small aggregate report and checksum. Per-exposure score CSV and
Parquet remain PRIVATE under assembled/. Reports are emitted after support,
after the core models, and during remaining diagnostics; the final summary says
COMPETITIVE_ONLY_COMPLETE. Partial reports are explicitly labeled.

X0 = original controls. XC = X0 plus competitive expected rate, decision count
and counterpart count; applied identically to each instrument in a comparison.
S1 uses >=5 competitive decisions. S2 also requires >=5 non-competitive decisions.
S1_3 is the >=3 competitive support sensitivity. No spacing is repeated.

Runs A–D include matched pooled/component IVs, joint 2SLS, distinct efficient-GMM
Hansen J, joint-covariance difference and full-real-line weak-IV sets. E–I include
binned first stages, balance with/without recipient controls, matched ordinary
placebo, joint first-stage partial R2, and raw/adjusted subgroup first stages.
Historical scores are treated as fixed. Binned uncertainty additionally conditions
on fitted residuals and quantile boundaries. The support sensitivity is descriptive.
No result automatically promotes an instrument or changes the paper's headline.

Small implementation clarifications are recorded in the report definitions and
methods: non-competitive SD reference is S2, GMM and 2SLS remain distinct, and
OLS-implied RF in displayed pp units divides their product by 100.

Validation is synthetic/local until the production report is returned. If the
production drive is unavailable, the runner stops with the exact missing path;
it never manufactures a sample or treats the test fixture as real results.
