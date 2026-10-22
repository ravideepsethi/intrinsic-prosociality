# Joint board-state and ply regressions v1.0.0

This is a new analysis runner, not previously estimated empirical results.
It uses only the certified 41,534,331-row pool/observed-nonadjacent panel,
November 2023–October 2025. It does not use the older 47.6-million sample.

## Fixed task specification

Outcome: `outcome_kind_draw` (Call draw rather than claim victory), conditional
on an observed chooser action. One observation receives one unit of weight.

- M1: chooser fixed effects + four board-state indicators + seven ply indicators.
- M2: same joint indicators + chooser, month and exact API-speed fixed effects
  + forgone-win premium / 10 + both log clocks + any-clock-missing indicator.

Both models use exactly the same observations. Both include the complete
five-state/eight-band classification. Reference board state: clearly losing.
Reference ply band: 0–4. No first/repeat-meeting restriction or regressor.
No ever-granter restriction; no sampling, RD filter or rating-gap restriction.
No new engine evaluation, API queries, Glicko reconstruction or source filtering.
No clock five-second filter is reapplied; that screen is already upstream.
The model is additive: it does not estimate state-by-ply interactions.

Board evaluation is from the disconnected player's perspective:

| Stored state | Evaluation, cp |
|---|---:|
| clearly_worse | <= -300 |
| modestly_worse_excluded | -299 through -101 |
| roughly_equal | -100 through +100 |
| disconnected_better | +101 through +299 |
| disconnected_clearly_better | >= +300 |

The historical name `modestly_worse_excluded` is retained in code; this state
IS INCLUDED in these regressions. Ply bands: 0–4, 5–6, 7–8, 9–10, 11–20,
21–40, 41–80, 81+. The compact table shows four board contrasts and three selected
ply contrasts, but both regressions include all seven ply indicators.

Rows with missing/invalid outcome, chooser, board state, evaluation, ply,
month, API speed or nonfinite win premium are excluded from BOTH models.
Exclusions are tabulated before estimation. Missing/nonfinite clocks are kept:
their log is set to zero and an indicator marks either clock missing.
Valid negative clock records are clamped at zero before log(1+seconds), matching
the existing project's clock-control convention; counts are separately reported.
All five raw state counts and kind-draw counts must exactly reproduce authority.

These regressions show conditional within-chooser associations. The design
does not establish causality or randomly assigned board states/game lengths.
The inherited panel uses observed previous nonadjacency, not a certified
end-to-start immediate-rematch definition, and not a strangers-only restriction.

## Statistics and computation

The code performs exact chooser demeaning in bounded batches of complete
chooser groups. Month/speed effects enter as explicit indicator columns.
Two streamed passes compute normal equations and cluster scores. This avoids
loading the full model matrix and avoids iterative FE convergence tolerances.
DuckDB sorts a narrow private Parquet by chooser first. The reader checks global
sort order and carries groups across Arrow batch and row-group boundaries.

SEs use the chooser-cluster sandwich times G/(G-1), treating absorbed chooser
effects as nested in the clusters. They do not count millions of absorbed FE
parameters in a residual-df correction. Coefficient p-values use t(G-1);
joint tests report both Wald chi-square(q) and F(q,G-1). Covariance files are in
squared percentage points. The point estimates and SEs are in percentage points.
All-observation N and chooser clusters include singletons; such accounts have
zero within-transformed rows. Counts of singleton, zero-grant, board-varying,
and ply-varying choosers are reported. No outcome-history selection occurs.

Zero-within-variation nuisance controls (e.g. a constant missingness indicator)
are explicitly logged and dropped. Unidentified target state/stage terms or
remaining collinearity stop the job. No pseudoinverse silently fills a table.
All dummy-variable covariance comparisons in the self-test are independent of
the production within transformation.

## Data safety and provenance

Default project: `/Volumes/XT_Pro/lichess_kindness`.
Default panel: `derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE`.
Requires `_SUCCESS.json` and the exact 24 monthly `panel/month=*/analysis_panel.parquet` files.
Sample fingerprint: `a17c89d750cb4fdfdf84f950859e45c58b19996efae02045def68285e305cf30`.

`vendor/wave1_common.py`, the sample authority, and the small evidence report
are unchanged copies from the authenticated Wave1 return bundle. This runner
uses the original full SHA256 panel authentication, not just equal row counts.
There is no fallback to another panel. Missing or changed inputs stop the job.
Source data are read-only. Work goes in a fresh uniquely named directory under
`derived/replication/joint_state_ply_v100_PRIVATE/`. A narrow sorted private
cache is retained there. No user files are deleted or overwritten.

Up to 10 threads are used for hashing, DuckDB and BLAS, in sequential phases.
Default DuckDB memory limit is 6 GB, plus bounded NumPy/Arrow batches. Allow
roughly 8–12 GB RAM and 10–25 GB free work space. These are planning allowances,
not measured production peaks. Runtime depends on drive throughput and the
full hash pass; no production timing claim has been made. Progress prints
per authenticated month and approximately every 25 seconds during estimation.

## Running

Requires Python >=3.11 with requirements.txt. A separate virtual environment
is recommended; this package never upgrades a global/Conda environment.

Run `python joint_state_ply.py --self-test` first (also done by the launcher).
Then run `bash RUN_POOL_JOINT_STATE_PLY.command` with `POOL_JOINT_PYTHON` pointing
to your selected Python. The supplied complete Mac command installs an isolated
environment and uses caffeinate. Set `POOL_JOINT_THREADS=10` (default) or lower.
Set `POOL_JOINT_MEMORY=4GB` for a smaller DuckDB budget if necessary.
Use `--sample-root /explicit/certified/root` only if the exact certified panel
was moved. The override is subject to the same authentication gates.

Self-tests compare coefficients AND full cluster covariance to explicit
chooser-dummy least squares, test different batch sizes and large groups,
keep never-granters and singletons, test frozen boundary values, missing data,
the common sample, SQL cache materialization and all table exports.

## Returned outputs

The launcher writes an aggregate-only results ZIP and matching SHA256 sidecar
to `~/Desktop/Lichess_Desktop` (override `POOL_JOINT_TRANSFER_ROOT`). Send back
both files. Outputs include:

- coefficients.csv: all board, stage and nuisance coefficients, clustered SEs,
  p-values and 95% confidence intervals.
- regression_table_full.tex and regression_table_slide.tex: booktabs tables.
- RESULTS.md and TABLE_NOTES.txt: readable table and exact interpretation.
- joint_tests.csv: formal joint state and joint stage tests for each model.
- model_receipts.csv: actual N, G, within R-squared and numerical diagnostics.
- model covariance CSVs; within_variation_support.csv.
- sample_flow.csv, raw_five_state_counts.csv, common_sample_board_by_ply.csv,
  clock_handling.csv, MODEL_SPECIFICATION.json, SAMPLE_LINEAGE.json,
  ENVIRONMENT.json, _SUCCESS.json and REPORT_FILE_HASHES.tsv.

No account IDs, game IDs or observation-level files enter the return archive.
If a run fails, inspect its private FAILED.json and terminal log. It produces
no success archive. Rerunning creates a separate working directory; this first
version deliberately does not reuse potentially partial model caches.

## Source reuse

The unchanged authentication helper and report came from
`POOL_MAIN_REANALYSIS_WAVE1_RESULTS_20260909T211555Z.zip`.
Its inspected public repository was
https://github.com/ravideepsethi/intrinsic-prosociality.git at
`0dc981cbc6da157d365015a95f2b7157ecda4859`.
The new streamed estimator and tests are specific to this package. No existing
regression results are copied into the new coefficient table.
