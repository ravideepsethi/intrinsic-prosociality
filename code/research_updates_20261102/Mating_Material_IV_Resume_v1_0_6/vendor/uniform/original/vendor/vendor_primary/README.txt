AllTime_IV_Primary_v1_0_3

v1.0.3 repairs a cross-platform self-test fixture. The previous full-model
fixture set reached=1 for every row; after absorbing fixed effects that outcome
is zero up to roundoff. Its CR0 variance may then be nonpositive, in which case
the estimator intentionally omits the standard error. The old test incorrectly
assumed that a standard error was always available. The replacement fixture
gives reached real variation, retains y<=reached, and requires supported finite
standard errors in both independent fits. A separate test verifies that zero
or negative covariance remains explicitly unsupported. The solver, estimator,
covariance, tolerances, cache keys and launcher test gate are unchanged.

This release accelerates the two last-move-hour models using an equivalent
sparse fixed-effect basis and adds active-model progress messages.
The memory budget and model definitions are unchanged. Completed fits are
reused under the same cf6b3d8b4d65 configuration. See RELEASE_NOTES.txt.

Previous repair for the wider-stage SQL parser failure at CREATE VIEW primary.
The view is now named primary_frame. The sample and statistical specification
are unchanged. This release retains v1.0.0 configuration/cache keys, so the
default existing run remains cf6b3d8b4d65. Completed primary fits, histories,
volume and environment tasks are authenticated and reused. The actual release
manifest is recorded separately in execution_package.json. The restart still
reads and checks cached files; it does not skip validation.

The aggregate report now omits inherited Anderson-Rubin fields, consistent
with the requested Wald-only output. Stored estimates and fit caches are unchanged.

Purpose: make the completed rebuilt total-five receipt cohort primary and rerun
its dependent R9/R9b/R12 tables. Read REPORT_METHODS.txt for each table's sample
and model, including separately retained comparison and Patron populations.

Save the ZIP and SHA256 sidecar in ~/Desktop/Lichess_Desktop.
Use the accompanying terminal command. It verifies the ZIP, extracts to a fresh
directory, verifies all package files, runs synthetic tests, and prevents idle sleep.
Default: /Volumes/XT_Pro/lichess_kindness, 10-worker ceiling, 11 GiB planning budget.
Large fits run serially or in memory-admitted groups; donor/history/ENV workers
are limited to two. The memory budget is not an OS-enforced cap.

Planning estimate: 6–12 hours for the full receipt migration, depending on missing
wider-row chronology and the absolute-hour fixed-effect fits. This is not a timed
production benchmark. Authentication and cached reruns can be much quicker.
Heartbeats appear during long stages. Model progress shows active model names and elapsed times; a whole-run ETA
is withheld when heterogeneous model runtimes make it unreliable. Aggregate checkpoints are
written at 25/50/75/100 percent and additional intermediate stages.

First 25% checkpoint: R12 primary reproduction, old reference, ladder, balance
contrasts, main receipt/OLS estimates and freshly fitted first-stage bins.
No PGN downloads, game API calls or Stockfish evaluations. If no compatible
existing Python contains all dependencies, the launcher creates an isolated
.venv inside its extracted folder and installs requirements there. It does not
upgrade the project's environment.

R12 cache expected:
derived/replication/r12_r13_followups_v100_PRIVATE/4df83f1178f3
R9 cache expected:
derived/replication/r9_certified_leave_pair_out_v100_PRIVATE/4028bf3e1857
R9b caches are reused when the completed e7eb600d6199 run is present.
Ordinary-comparison contrast uses the completed b625b6c6b4f3 Phase-100 Score A run.

Options:
--project PATH             project root
--result-dir PATH          aggregate results (default Desktop/Lichess_Desktop)
--workers 10               maximum concurrent workers
--memory-gb 11             10.5–11 GiB planning budget
--r12-root PATH            explicit completed R12 run root
--r9-root PATH             explicit completed certified R9 root
--comparison-root PATH     completed Phase-100 Score A run root
--preflight-only           authenticate caches without fitting models
--only-primary             produce 25% checkpoint; full command resumes remaining work

Resume: rerun the same terminal command. A fresh extraction still binds to the
same external-drive configuration and verifies/reuses completed stages and fits.
Do not run two copies of this configuration simultaneously; a lock prevents it.
Require at least 40 GiB free for wider-frame output and temporary spill.

Return ALLTIME_IV_PRIMARY_<configuration>_100.zip, its .zip.sha256, and the log.
If interrupted, return the latest checkpoint and log. The report's
migration_status.csv distinguishes updated receipt analyses from the separate
comparison/Patron population work. No manuscript is edited automatically.

Validation here uses synthetic data and authenticated aggregate output contracts.
Production estimates require running the package on the research Mac.
