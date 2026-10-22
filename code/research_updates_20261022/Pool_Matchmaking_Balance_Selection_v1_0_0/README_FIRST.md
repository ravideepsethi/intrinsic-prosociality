# Pool matchmaking: balance and selection, v1.0.0

This package runs the first outcome-level audit following the returned input probe. It estimates whether the focal player's pre-game kindness history varies with the subsequently realized opponent rating gap after accounting for the observed matching environment, and whether that gap predicts entry into timeout categories and roles. It is an exploratory diagnostic, not a certificate of random assignment.

**Expected runtime:** 5–15 minutes on the previous analysis setup; allow longer if another heavy task is running. This is a planning estimate informed by synthetic benchmarks, not a timed run on the private data. One process and at most two numerical threads; allow approximately 2–4 GB RAM. DuckDB uses one reading thread. No network or Stockfish calls. No full panel or chronology scan.

## Run

Save the ZIP and its sidecar in `~/Desktop/Lichess_Desktop`, then paste all of `RUN_COMMAND.txt` into Terminal. The launcher checks every packaged file, locates the existing analysis Python, runs synthetic tests, authenticates the source comparison file, and estimates the fixed specifications.

Defaults:

- Project: `/Volumes/XT_Pro/lichess_kindness`.
- Source comparison: `derived/replication/chooser_iv_main_rebuild_v100_PRIVATE/ccbc43314875/analysis/comparison.parquet` under the project.
- New private checkpoint directory: `derived/replication/pool_matchmaking_balance_selection_v100_PRIVATE/<configuration prefix>`.
- Result ZIP, sidecar, and launcher log: Desktop/Lichess_Desktop.

Optional environment variables are `MM_BS_PROJECT_ROOT`, `MM_BS_DESKTOP`, and `MM_BS_PYTHON`. No dependency installation is attempted. The packaged code requires NumPy and DuckDB. It was tested with NumPy 2.3.5 / DuckDB 1.5.5; the existing Mac environment previously reported NumPy 2.5.3 / DuckDB 1.5.5. The numerical tests run on that environment before estimation. Python and numerical versions are recorded in each run.

**After completion, upload both `POOL_MATCHMAKING_BALANCE_SELECTION_RESULTS_*.zip` and its `.sha256`.** A stopped run emits a `PARTIAL` archive when possible. Keep that archive and the log if an error occurs. Repeating the same launcher reuses completed, hash-checked model checkpoints. A retained statistical support failure is reported as unsupported, rather than retried with an altered specification. Interrupted models start again; successful models are reused. A process lock prevents duplicate instances of this package.

## What is authenticated

The returned probe ZIP is included byte for byte. Its SHA-256 is `adfa749d47512036835c984525846fb480bbc5c2266f6fd09b6c54a870663fed`. Its CRC and 2/2 internal hashes were verified. The probe took 12.6735 seconds and inspected Parquet metadata; it did not authenticate all Parquet contents.

This runner independently hashes the 173,517,733-byte comparison file and requires SHA-256 `8bc92d15b9a63e4cc1191ab8342aedd918a36bd341d9a8ddc427e93bb9f156ae`. It also checks the predecessor run's canonical configuration and comparison checkpoint receipt, 1,661,563 distinct game/sample keys, and 1,527,795 rows passing observed nonadjacency. Input size and modification time are checked again after estimation.

The main sample remains **41,534,331 pool, observed-nonadjacent opportunities**, fingerprint `a17c89d750cb4fdfdf84f950859e45c58b19996efae02045def68285e305cf30`. This diagnostic is on a separate sampled pool-game comparison frame that includes ordinary endings. Its 1,527,795 retained games must not be described as a census of the 41.5 million opportunities, or as the population of all pool starts. The report gives the comparison frame's actual date coverage and denominators. It does not independently recertify the full main panel.

Inherited numerical and history/role source files are bound byte for byte to the public project's commit `bf3b2bf9ffedba8f53c61e3e1b55bb457e58a129`. See `evidence/SOURCE_BINDINGS.json` and `evidence/ORIGINAL_PACKAGE_MANIFEST.sha256`. The evidence producer files document lineage; this package does not execute the old rebuild or change its outputs.

## Interpretation

Start with `SUMMARY.json`, `INPUT_QA.json`, `LOCAL_CELL_SUPPORT.csv`, and the `local5_primary` estimates. `MODEL_RESULTS.json` contains every coefficient, covariance, contrast, joint test, support count and numerical status. `ESTIMATES.csv` is the flat table. `RAW_GAP_TABLE.csv` supplies descriptive denominators and decompositions. `ANALYSIS_DESIGN.md` specifies interpretation and the distinctions among the 12 models.

The observed matching environment is exact clock, game-start timing, and displayed focal rating. Queue entry, queue wait, conduct score, rating preferences, and pre-game RD are absent from this comparison file. A game-start bin is a proxy for the environment, not a measured queue. Passing these balance checks cannot establish random assignment. Failing them can identify a concrete weakness in that claim.

No current-game grant incidence or new relative-strength kindness gradient is estimated here. Neither a clean balance test nor a clean selection test would, by itself, turn a response conditional on realized game state and disconnection into a causal effect. These results determine the next defensible step for the manuscript argument.
