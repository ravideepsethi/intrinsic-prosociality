# Pool Selectivity Pilot v1.0.0

This is the first empirical feasibility run for the generosity/selectivity model. It uses the **certified 41,534,331-row pool / observed-nonadjacent sample** for November 2023–October 2025. It does not rebuild the sample, run Stockfish, call the Lichess API, or modify certified inputs.

The package runs two analyses:

1. **Census information audit:** account history lengths; coverage of competitive and clearly-worse states; all-zero histories; 40 board-by-stage cell counts; and which first-year accounts have second-year observations.
2. **Capped prediction pilot:** a three-class panel mixture with persistent granting levels versus the same model allowing the competitive-state response to vary by class. A separately smoothed state-rate benchmark is included. Parameters, control categories, mixture selection across starts, and account posteriors use year one only. Year two scores frozen predictions.

This pilot uses a fixed competitive indicator and common board-by-stage controls. **It does not estimate the proposed free warrant surface W.** It tests whether heterogeneous competitive-state sensitivity is worth developing further. It is not an identification proof, a claim of two independent moral traits, a causal receipt model, or a Patron analysis.

## Run

Download the ZIP and its SHA-256 sidecar to Downloads. The complete extraction command is in RUN_TERMINAL.txt. Default execution uses two fitting workers and one hash worker, with one numerical-library thread per worker. This is intended to coexist with the already-running Stockfish job. The command is a foreground job protected with `caffeinate -i`; keep Terminal open.

The launcher verifies the package hashes, finds a compatible Python or creates a dedicated environment under Desktop/Lichess_Desktop, runs synthetic correctness checks, and starts the analysis. Python 3.10+ is required. Dependencies are installed only in that dedicated environment when needed.

Default input:

`/Volumes/XT_Pro/lichess_kindness/derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE`

The existing `_SUCCESS.json`, report identity, 24 Parquet hashes, schema, row counts, and basic source definitions are checked. A copied main panel is accepted only with its unchanged certification and bytes. The script does not fall back to the older all-sources panel or guess a schema from another file.

Defaults: 100,000 randomly selected first-year accounts (complete histories), K=3, three starts per model, up to 700 L-BFGS-B iterations per start, DuckDB memory limit 4GB. No year-two participation or first-year kindness requirement is imposed for pilot selection. Accounts must have at least one first-year competitive or clearly-worse opportunity because those are the fitted states. Middle states remain in the census audit but are excluded from the binary pilot.

## Resource expectations

Reserve at least 10 GiB of free external-drive space for private caches and database spill. DuckDB's memory setting is not a cap on total Python/NumPy/process memory. With two workers, budget several additional GiB of RAM. No runtime has been benchmarked on the production data: allow a few hours for a first run, with disk hashing, account aggregation, and optimizer convergence determining elapsed time. The log reports each monthly input verified and each 50 fitting iterations. If competing jobs make the machine sluggish, use one worker and a 2GB DuckDB setting.

## Resume and outputs

Re-running the **same extracted package and options** reuses completed, checksum-verified preparation and model-attempt checkpoints. An interrupted individual model attempt starts again; completed attempts do not. A package/configuration/dependency change produces a new run identity. Two identical runs cannot execute concurrently.

Everything is written under a new deterministic run directory:

`/Volumes/XT_Pro/lichess_kindness/output/pool_selectivity_pilot_v100_<run_id>/`

- `PRIVATE/`: account IDs, account-cell counts, model arrays, optimizer checkpoints, and first-year posteriors. Keep these private.
- `report/`: aggregate diagnostics, fits without account identifiers, calibration tables, lineage, and completion receipt.

The transferable ZIP and sidecar are copied to Desktop/Lichess_Desktop:

`POOL_SELECTIVITY_PILOT_RESULTS_v100_<run_id>.zip`

**Send back that ZIP and its sidecar, not PRIVATE/.** Report contents are allowlisted by construction: only files from report/ are packaged. The public lineage excludes machine paths and account identifiers. Numerical support points describe estimated components, not named people.

The completion marker means the computation finished; convergence/boundary warnings are separate and must be read. It does not certify structural identification. Re-running a completed configuration verifies and repackages its report without repeating the analysis.

## Read the report in this order

1. `support_in_both_regions.csv`: how many accounts have 1, 2, 3, 5, 8, 10, or 20 first-year choices in each region?
2. `support_by_history_length.csv`: rich histories, all-zero accounts, and later observation.
3. `optimizer_attempts.csv`: convergence, local solutions, bounds, and training likelihoods.
4. `heldout_comparisons.csv`: log-score improvement from heterogeneous selectivity. Positive means better prediction; includes both opportunity and account weighting.
5. `heldout_scores.csv`, `heldout_calibration.csv`: whether predictions are calibrated separately in competitive and clearly-worse positions.
6. `heldout_by_training_support.csv`: whether the gain holds among accounts with richer first-year histories.
7. `MODEL_DESIGN.json` and `SUMMARY.md`: interpretation and any unsupported year-two categories.

A model that predicts better may still reflect preferences, attention, understanding, perception, or unmodeled persistent states. The main empirical question is whether heterogeneous selectivity adds predictive information. Do not interpret a negative pilot result as proof that everyone has the same preferences.

## Optional settings

Export these before the launch command, or pass the corresponding argument to RUN_SELECTIVITY.command:

- `LICHESS_STRUCTURAL_WORKERS=1` through `10` (default 2).
- `LICHESS_STRUCTURAL_HASH_WORKERS=1` through `10` (default 1).
- `LICHESS_STRUCTURAL_MEMORY=4GB` (DuckDB only).
- `LICHESS_STRUCTURAL_PILOT_ACCOUNTS=100000`.
- `LICHESS_PROJECT_ROOT=/Volumes/XT_Pro/lichess_kindness`.
- `LICHESS_STRUCTURAL_PYTHON=/absolute/path/to/python` for an already compatible interpreter.
- `--sample-root /absolute/path/to/certified_sample` if the certified copy has moved.
- `--audit-only` for census support without fitting. A later full run with the same other options reuses the census checkpoints.

The user-facing command already specifies the default resource settings; edit them there if needed. Changing worker counts does not invalidate statistical checkpoints. Changing sample cap, random seed, fitting options, package bytes, or dependencies does.
