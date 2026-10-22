# AFE Follow-ups v1.0.0

Run on the work Mac with XT_Pro mounted. No Lichess API requests and no Stockfish searches are made. This package reads existing certified files and writes an isolated analysis directory.

## What runs

1. Payoff accounting and observed rating-update validation.
2. Whether current Patrons receive more kindness, including full-row chooser-FE models and coverage checks.
3. Exclusion sensitivity for the reviewed IV; precision planning for the ordinary-game placebo.
4. Cumulative transmission and predetermined experience subgroups on the exact expanded IV cohort.
5. Blackout-data feasibility inventory (not an outage instrument).
6. Restricted two-type dynamic parameter-recovery simulations (not full structural estimation).

The finer substantive and identification limits are in ANALYSIS_PLAN.md. In particular, a profile snapshot cannot backdate a badge, and first observed in a panel does not mean first ever.

## Run

Save the ZIP and `.sha256` beside each other in `~/Desktop/Lichess_Desktop`, then run the full command supplied with the download. The launcher creates a dedicated Python environment without changing the existing project environment. It runs small offline correctness tests before reading the production data.

Default: four threads and a 6GB DuckDB memory limit. This leaves more room while the separate Stockfish job is active, but the jobs still compete for CPU/RAM and disk. The memory limit applies to DuckDB, not the entire Python process; the 2.7M-row IV fits additionally allocate NumPy arrays. On an idle machine with adequate memory, set `AFE_WORKERS=10`. All large models run sequentially; there is no uncontrolled ten-process multiplication of the data.

The first run installs dependencies and verifies roughly 12GB of existing main-panel files, then builds disk-backed analysis caches. Keep substantial free space on XT_Pro for temporary features and DuckDB spill (tens of GB). The full Patron and transmission runs can take hours; there is no measured production ETA. Heartbeats are printed every 45 seconds. Keep the drive connected; `caffeinate` prevents idle sleep during the process.

When finished, upload the two `AFE_FOLLOWUPS_REPORT_*.zip` and `.zip.sha256` paths printed after `UPLOAD:`. They appear in `Lichess_Desktop`. Logs are under `Lichess_Desktop/logs`.

## Separate runs and resumption

The default launcher runs all modules. You can supply:

```bash
/bin/bash "$HOME/Desktop/Lichess_Desktop/AFE_Followups_v1_0_0/RUN_AFE.command" --modules payoffs,patron,iv
/bin/bash "$HOME/Desktop/Lichess_Desktop/AFE_Followups_v1_0_0/RUN_AFE.command" --modules transmission
/bin/bash "$HOME/Desktop/Lichess_Desktop/AFE_Followups_v1_0_0/RUN_AFE.command" --modules recovery --simulations 50
```

The same command resumes completed verified modules; an interrupted module restarts its stage. Changing simulations, workers or numerical environment creates a separate run signature. Missing optional prerequisites are reported and never filled with fabricated data. Failed stages generate a report and a nonzero exit code. A `--preflight-only` option checks inputs and emits a diagnostic report.

## Required existing inputs

- `derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE/panel/month=*/analysis_panel.parquet`
- `derived/replication/chooser_iv_expanded_v100_PRIVATE/f14a1105a9f7/analysis/spaced90.parquet`
- `derived/replication/patron_profile_snapshot_24m_v100_FINAL_CERTIFIED/profile_snapshot_24m_private_lossless.parquet`
- For broad pretreatment histories: `derived/replication/analysis_panel_24m_sf100k/month=*/analysis_panel.parquet`

The old broad panel is history only. Main outcomes always use the 41,534,331-row sample.

## Validation and provenance

New numerical tests compare the full-row fixed-effects coefficient with an explicit dummy-variable least-squares fit and its covariance with explicit row-pair dependence. Future-event timing/exclusion tests include empty follow-up, prior-start games and the original benefactor. Additional tests cover profile missingness, payoff identities, IV units and the analytic mixture-likelihood gradient. Package provenance records exact hashes of vendored code recovered from the previously executed IV package.

These tests use synthetic data. The user's full private panel is not present in this workspace, so production results are generated only when the Mac command is run.
