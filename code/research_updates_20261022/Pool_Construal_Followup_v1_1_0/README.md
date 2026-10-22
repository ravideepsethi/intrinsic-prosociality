# Construal follow-up v1.1.0

This package implements the next analysis after the returned v1.0.0 run. Use `RUN_TERMINAL.txt` for complete Mac commands. It writes a separate output directory; all original data and results are read-only inputs.

## What it runs

| Question | Follow-up |
|---|---|
| Did optimizer bounds or local fits drive the comparison? | Refit all four switching families at bounds 7, 12 and 20, with eight or more starts, including dispersed starts and nested-model embeddings. Primary comparison is fixed at width 20. |
| Why was old bootstrap draw 6 anomalous? | Reproduce its resampling weights and four returned gains, then reoptimize that same draw at each bound. |
| Does the score gain survive population refitting? | 120 account-refit bootstrap draws, resampling development and evaluation accounts independently; intervals require at least 100 converged paired refits. |
| Can these histories distinguish mechanisms and recover parameters? | 20 simulations each under gate, willingness, unrestricted, and near-collapse generating models; actual 19,939-account / 188,008-opportunity training design, calibrated to 2,477 expected training grants; separate full evaluation histories. |
| What do receipt transition estimates say? | Entry and staying coefficients, their direct contrast, probability changes and a decomposition of the receipt-input forecast contrast, with refit uncertainty. These remain predictive estimates. |
| What does `n_lost` measure? | Reproduce the original count and IV estimate, then distinguish recipient-as-chooser from recipient-as-disconnected, and separate draw from claim counts. |
| Could activity or source selection explain the count change? | Game-start counts in the existing chronology corpus; timeout/outoftime counts in completed broader API source months, with same-subset reference outcomes and explicit coverage checks. |

## Required inputs

The primary comparison reuses authenticated v1.0.0 histories and selected models from:

`/Volumes/XT_Pro/lichess_kindness/output/pool_construal_tests_v100_3035352b8b33d41d`

Keep its `report` and `PRIVATE` directories. The package checks the reviewed result ZIP, local configuration, original report bytes, private cache receipts, reconstructed training arrays, support counts and original scores. A missing or changed required cache stops the affected analysis rather than silently rebuilding a different sample.

Opportunity diagnostics read the certified 41,534,331-row main panel and original IV cache. Broader diagnostics use the existing rating replay chronology and completed canonical or historical curated API sources. Their absence is reported explicitly. The main panel is not the older 47.6-million-row population.

## Run and resume

Put the ZIP and its `.sha256` file in `~/Desktop/Lichess_Desktop`, then use the first block in `RUN_TERMINAL.txt`. Defaults use two worker processes, one hash worker, one numerical thread per process, and a 4 GB DuckDB memory limit. The Python process and workers also use memory outside that DuckDB limit. At least 20 GiB free space is checked for caches and spill.

This is substantially more work than v1.0.0. The chronology scan covers about 43.5 GB across 144 files and 2.23 billion rows. Runtime has not been benchmarked on your Mac. Progress and heartbeats are printed; fits and source parts are checkpointed.

Run the same command to resume. To extend to 200 refits / 40 recovery replications, use the second block in `RUN_TERMINAL.txt`. Budgets are omitted from run identity; completed attempts are reused. Avoid reducing budgets for an already extended run because requested summaries are regenerated to that budget. Bounds, starts, optimizer settings, dependencies and code are part of run identity.

Use `--stages models,bootstrap,recovery` to run numerical work alone, or `--stages opportunities` for the source diagnostics. Earlier stage reports remain in the same run. Source diagnostics cannot invalidate a likelihood computation, and their failure is reported separately while numerical work continues.

Outputs go to `output/pool_construal_followup_v110_<identity>/`. Return only the final `POOL_CONSTRUAL_FOLLOWUP_RESULTS_v110_<identity>.zip` and `.sha256` files printed at completion. They contain aggregate reports and model parameters. Account and game records stay in private local caches. Intermediate ZIPs are also exported after stages so a long run can be inspected before completion; read `RUN_STATUS.json` to distinguish partial from finished work.

## Interpretation to preserve

`n_lost` means the receipt recipient later faced an opponent who disconnected from a losing position and then made a recorded draw/claim choice. It excludes ordinary clock-expired `outoftime` games. It is neither the recipient's own disconnection count nor an unconditional arrival count.

The latent transition estimates support a retention *hypothesis*. They do not establish that receipt causally retains engagement, and the IV subgroup-difference null does not corroborate a causal retention-versus-conversion difference. Keep both transition terms and their uncertainty visible. A lower state with flat emissions is a statistical restriction; psychological construal remains an interpretation.

The evaluation sample has now been inspected. This follow-up is numerical robustness, uncertainty assessment and recovery on that frozen design, not a new untouched confirmation exercise. `METHODS.md` states the inferential scope; `VALIDATION.md` records the software checks. No production fits from v1.1.0 have been run in the package-building environment.
