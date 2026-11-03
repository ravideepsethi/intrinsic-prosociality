# Updated IV placebo and entry diagnostics

This increment follows the completed receipt run `ef68f2376383`. It computes the new cumulative instrument on the unchanged F50 entry sample (7,371,688 rows) and attaches it to the verified O50 ordinary-ending subset (4,764,089 rows). All eligible donor opportunities strictly before exposure start minus 24 hours enter, after complete pair and author exclusion. The frozen monthly nuisance model, history controls, exposure selection, spacing, and outcome definitions remain unchanged.

Expected runtime: **45–90 minutes** on the research Mac. This is a planning estimate, not a full production benchmark. The runner reports measured stage progress and estimated times to the next checkpoint and finish every 30 seconds.

Save the ZIP and its `.zip.sha256` file in **`~/Desktop/Lichess_Desktop`**. Connect XT_Pro. Run the single command supplied with the package. It verifies both the archive and every packaged file, extracts to a unique temporary folder, uses the existing research Python, and prevents sleep. Rerunning that command safely resumes completed checkpoints.

The data root is `/Volumes/XT_Pro/lichess_kindness`; Python is `<project>/venv/bin/python`. Set `IV_PROJECT_ROOT`, `IV_DESKTOP`, or `IV_PYTHON` only if those locations differ. Optional runner arguments include `--workers 1` through `--workers 10`, `--memory-gb 9.5` through `--memory-gb 11`, and explicit `--r7-root` / `--cutoff-root`.

## Analyses

- O50 placebo: later kindness and reaching a later opportunity, with X0 and X0 plus ENV and its availability indicator.
- F50 entry diagnostics: analysis entry, recipient disconnection, and active timeout, with the same two control sets; seven-trait balance and joint balance accompany each fit.
- Receipt minus ordinary-ending reduced-form contrasts: common account/date covariance, using the frozen reference score SD. Archived receipt IV models are not refitted. Receipt reduced-form residuals/influences are reconstructed and checked against the saved coefficients, SEs, and row identities before use.
- Archived old-cutoff R7 models and contrasts are authenticated and included for comparison; their computation is not repeated.

## Ordinary material coverage

The frozen O50 table has no final-position field. The runner audits the frozen O50/F50/Phase50 feature Parquets and the Parquets in the completed R7 move-cache inventory for the documented final FEN, final ply, and full game/role/time identity. Compatible positions are joined and validated. Conflicting or unavailable positions remain unknown.

If enough validated positions exist, the runner fits observed-position and strict `−4 < M < 4` O50 sensitivities and their receipt contrasts. This is an ordinary **material-only** sensitivity: no disconnected-player competitive-cp screen is claimed for ordinary endings. The receipt side retains its original `cp >= −100` screen.

If no directly usable final-position Parquet is present, the core diagnostics still finish and the report states `CORE_COMPLETE_ORDINARY_MATERIAL_PENDING`. This audit does not establish coverage in raw PGN/JSON caches: their replay requires a separate cache and endpoint-identity assessment. It makes no API calls, performs no engine searches, and never treats missing material as balanced.

## Performance and outputs

Projected Parquet reads, one F50 history pass shared by O50, compressed private checkpoints, one BLAS thread per worker, and memory-aware spawned workers are used. Worker reservations share an estimated 11 GiB budget including 1.5 GiB for the parent; large fits run alone when needed. These reservations are estimates rather than an OS-enforced RAM limit.

Private outputs are under `<project>/derived/replication/iv_placebo_entry_v100_PRIVATE/<configuration>/`. Completed upstream runs remain read-only. Reports at 25%, 50%, 75%, and 100%, their SHA256 sidecars, and the run log go to `Lichess_Desktop`. Return the **100% report ZIP and its `.sha256` sidecar**. If it stops, return the log and latest checkpoint.

Reports contain aggregate results only. Row-level influence files remain private. Inference retains shared-account-OR-date CR0, fixed generated instruments, the original reference SD, and nominal intervals. Neither a null placebo nor numerical material neutrality establishes instrument exclusion or eliminates prior sorting, sanctions, rating effects, or post-assignment selection.

No manuscript is modified. This package has synthetic regression and integrity tests; production data and empirical estimates are available only after running it on the research Mac.
