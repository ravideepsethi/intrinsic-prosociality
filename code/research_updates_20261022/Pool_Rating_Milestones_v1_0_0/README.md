# Pool rating milestones v1.0.0

Run the round-number milestone analysis on the existing 41,534,331-decision pool sample. The bundle contains the code, verified sample authority, test definitions, synthetic validation and a Mac launcher. It contains no empirical milestone findings or private row-level data.

## Run

Download `Pool_Rating_Milestones_v1_0_0.zip` and its `.zip.sha256` file to `~/Desktop/Lichess_Desktop`, mount XT_Pro, and paste `RUN_TERMINAL.txt` into Terminal. Use your usual conda Terminal. The launcher reuses a compatible Python environment when available; otherwise it creates an isolated environment under Lichess_Desktop and installs the listed dependencies.

The command uses ten processes, a 6 GB DuckDB memory limit during staging, and single-threaded numerical libraries in each process. Runtime is approximately 30-120 minutes on a modern Mac/external SSD, potentially 2-3 hours on a slower drive; this has not been benchmarked on your actual sample. Reserve about 15-25 GB of free disk space for caches and spill. No Lichess API requests or Stockfish evaluations are required.

The primary analysis uses competitive positions within 25 rating points of a hundred-point milestone. It tests protecting a milestone already held and reaching one with a claimed win. Individual milestones, established-rating restrictions, a no-1500 restriction, alternate windows, game-stage and rounding checks, weaker milestones and offset placebos are included. The complete model/control list is in `METHODS.md`.

## Outputs to return

At completion, upload these two files from Lichess_Desktop:

- `POOL_RATING_MILESTONES_RESULTS_v100_<identity>.zip`
- `POOL_RATING_MILESTONES_RESULTS_v100_<identity>.zip.sha256`

The launcher prints the exact paths and the primary results table. The result ZIP contains aggregate tables, figures, all attempted tests, provenance and executed code. Logs are named `pool_rating_milestones_v100_<timestamp>_<pid>.log` in Lichess_Desktop. Slim input caches remain on XT_Pro in the run's `PRIVATE/` directory and are not included in the result ZIP.

On interruption, paste the same terminal command again. With the same code, worker count, settings and dependency versions, completed checkpoints are verified and reused. An altered or corrupt source/checkpoint stops the run. Existing certified source data are read only.

Optional environment settings, if needed, are `LICHESS_PROJECT_ROOT`, `LICHESS_TRANSFER_ROOT`, `LICHESS_MILESTONE_WORKERS` (1-10), `LICHESS_MILESTONE_MEMORY`, `LICHESS_MILESTONE_BATCH_ROWS`, `LICHESS_MILESTONE_HASH_WORKERS`, and `LICHESS_MILESTONE_PYTHON`. The defaults match the existing project. The Python CLI also accepts `--sample-root` and `--output-root`; there is no skip-authentication production option.

This is an exploratory conditional-association analysis. Personal-best tests require the all-game prior chronology within each speed pool and are not included here.
