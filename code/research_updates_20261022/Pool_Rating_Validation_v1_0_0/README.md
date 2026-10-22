# Current-sample rating validation, version 1.0.0

This package compares the paper's stored reconstructed rating changes with the
recorded PGN changes for the current **41,534,331-opportunity sample**. It uses
November 2023 through October 2025 pool games satisfying the existing observed
predecessor nonadjacency screen. It preserves the existing sample and rating
reconstruction. No Lichess API calls, PGN downloads, Stockfish jobs, or historical
rating replay are performed.

## Run

Save the delivered ZIP in `~/Desktop/Lichess_Desktop`, verify its SHA-256 using
the supplied terminal command, extract into a fresh directory, and invoke
`RUN_VALIDATION.command` under `/usr/bin/caffeinate -dimsu /bin/bash`.

The default project is `/Volumes/XT_Pro/lichess_kindness`. The exact input is:

`derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE/panel/month=*/analysis_panel.parquet`

The containing sample root must have its original `_SUCCESS.json`. The package
bundles the previously authenticated sample report and byte-identical Wave 1
authentication code. It checks all 24 complete file hashes, metadata, sample
fingerprint, and completion receipt before reading analysis columns. It then
recounts the 41,534,331 rows, 570,091 kind draws, 15,207,423 competitive rows,
and 419,463 competitive kind draws. It will not substitute the older all-source
panel or silently accept a different sample version.

Defaults: 10 independent month workers, 2 hash workers, 65,536 rows per batch,
one Arrow/BLAS thread per month worker. These are streaming computations; the
whole panel is never loaded into memory. Workers use the `spawn` process mode
used on macOS. Input files total about 11.72 GiB. Allow
roughly 5-20 minutes on a modern Mac with an external SSD; this is a planning
estimate, not a measured production runtime. There is no large spill database.
Existing Python with compatible NumPy and PyArrow is reused. Otherwise the launcher creates
an isolated environment in `Lichess_Desktop` and installs the two dependencies.

Optional settings: `LICHESS_PROJECT_ROOT`, `LICHESS_TRANSFER_ROOT`,
`LICHESS_VALIDATION_PYTHON`, `LICHESS_VALIDATION_WORKERS`,
`LICHESS_VALIDATION_HASH_WORKERS`, `LICHESS_VALIDATION_BATCH_ROWS`.
An explicit alternate location of the same certified sample can be supplied as
`--sample-root /path/to/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE`.

## Exactly what is validated

| Primary arm | Observed update | Stored prediction |
|---|---|---|
| Kind draw (`outcome_kind_draw=1`) | PGN rating change of the chooser's color | `chooser_draw_payoff_v2` |
| Claimed win (PGN/API-confirmed chooser win) | PGN rating change of the chooser's color | `chooser_win_payoff_v2` |

The observed change is selected from `white_rating_diff_pgn` and
`black_rating_diff_pgn` using `chooser_color`. Nothing is estimated from the
observed outcome to improve the prediction. The code checks that each primary
prediction agrees with the corresponding stored white/black realized-outcome
prediction, and checks the payoff identity separately. That identity is **not**
used as evidence of accuracy against actual updates.

Supplemental series cover all raw chooser draws, draws failing the material
screen, unusual chooser losses, and the disconnected player's actual draw,
loss or win. They use the stored color-specific realized-outcome predictions.
All-draw and kind-draw series overlap. Chooser and disconnected observations
from one game are two player sides, not independent games.

The existing reconstruction is anchored, time-aware Glicko-2 with the
`novol_noreg` convention. This package does not introduce a post-update
regulator, change the reconstruction, or reinterpret it as an exact production
implementation. It measures the predictive error of the fields used in the
paper. Comparison with the realized outcome cannot directly validate the
unchosen outcome or the counterfactual win premium.

Missing observed changes remain missing; recorded zeros remain observed zeros.
A missing change for one player does not exclude an observed change for the
other. Coverage is reported before exclusion. Nonfinite predictions, role or
result disagreements, source mismatches, or input changes cause a failure.

Metrics: Pearson correlation, mean observed and predicted updates, bias, MAE,
RMSE, maximum absolute error, fractions within 0.5/1/2 rating points and above
5 points, and strictly opposite nonzero signs. Predictions are continuous and
observations are integers; no naive rounded-prediction equality is called an
exact match to Lichess's display rules. Correlations are undefined in groups
with zero variance. No misleading iid confidence intervals are reported.

Primary metrics are also reported by month, speed, month by speed, board state,
competitive region, game stage, chooser rating, each player's rating deviation,
both deviations at most 110, signed draw payoff, and distance from zero payoff.
The local-payoff diagnostic selects competitive positions with absolute draw
payoff below one, at every game stage. It does not reproduce additional
regression-specific fixed-effect-cell eligibility restrictions.

## Outputs and resume

Local run folder:
`output/pool_rating_validation_v100/run_<analysis_fingerprint>/`

Monthly aggregate checkpoints are saved atomically with checksums. Re-running
the same command authenticates inputs again, verifies checkpoints, and resumes
unfinished months. Different code, dependency versions, or batch sizes create a
different run fingerprint. A process lock prevents overlapping runs with the
same fingerprint.

The final report includes:

- `SUMMARY.md`: the main table and interpretation notes.
- `validation_primary.csv` and `.parquet`: the two primary outcome arms.
- `validation_all_groups.csv` and `.parquet`: every diagnostic group.
- `validation_by_*.csv`: individual subgroup tables.
- `OUTCOME_AND_MISSINGNESS_COUNTS.json`: complete classification and coverage.
- `METHOD.json`, `INPUT_MANIFEST.json`, hashes, and a completion receipt.

A compact ZIP and SHA-256 sidecar are written directly into `Lichess_Desktop`:
`POOL_RATING_VALIDATION_RESULTS_v100_<fingerprint>.zip`.
Upload those two files for review. The report contains aggregate statistics,
not game IDs, account IDs, usernames, or row-level records.

`POOL_RATING_VALIDATION_COMPUTED_OK` means that the computation and sample checks
completed. It does not automatically certify predictive accuracy. Review the
observed results before replacing the paper's historical validation numbers.

## Verification performed before delivery

`test_validation.py` tests moments against independent NumPy calculations,
white/black role orientation, missing versus zero updates, inclusive grouping
boundaries, preservation of pooled statistics across batches, role/result
failure cases, process workers, checkpoint corruption, report construction,
report ZIP checks, a complete 24-month synthetic run, partial checkpoint resume,
and completed-run reuse. It also checks the frozen authority and field names.
These are synthetic tests. The 41.5 million production rows are on your Mac and
have not been processed in this environment.
