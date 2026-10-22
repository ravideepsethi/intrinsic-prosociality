# Framework A/E source-specific continuation — v1.2.0

**Created 2026-10-12. No real XT_Pro analysis has been performed by this package's authoring environment.** Synthetic numerical tests pass. This bundle is read-only with respect to the existing sources; private derived account/exposure records stay under `/Volumes/XT_Pro/lichess_kindness/output/framework_AE_v120/...`.

## Intended purpose

Execute the *remaining* framework tests without recomputing B/C/D/F or using the Lichess API. Source paths below are **candidates authenticated by their metadata in the provided `AE_SOURCE_SHORTLIST.json`**, not authenticated estimators. Every study-population identity check happens locally before estimation.

### A — August 2026 Patron flag robustness

* August-only profile snapshot (1,305,872 accounts), includes `patron`, `disabled`, `tos_violation`:
  `derived/replication/patron_profile_snapshot_24m_v100_FINAL_CERTIFIED/profile_snapshot_24m_private_lossless.parquet`.
* Original processed Panel A/B candidate: `derived/replication/pool_main_reanalysis_v100_PRIVATE/wave3b1_patron/9a64f1f9b8f8/design/chooser_design_features_private.parquet` (1,105,919 selected accounts, matching cells, grant history and model covariates).
* The preflight MUST reproduce: 1,105,634 August-available accounts; 599,045 state-specific Panel B (24 matching cells), with group counts CO 100,671 / BOTH 18,098 / LO 26,231 / NEI 454,045; Panel A 212,829 competitive-position granters and 638,302 controls (851,131 accounts, 36 cells).
* For each group, report `%disabled`, `%tos_violation`, `%either`, Patron rate among flagged and unflagged, August profile missingness; estimate Panel A and B LPMs excluding `disabled`, excluding `tos_violation`, and excluding either. Unmatched controls are NOT replenished; focal accounts removed by a flag carry their associated controls out of the matched Panel A comparison.
* **Important**: The control engineering is reconstructed from frozen source columns and may not exactly equal the executed manuscript code. Baseline coefficients are explicitly compared against the paper's Panel A `+0.277 pp`, Panel B `+0.388 pp` and `−0.195 pp`. The summary labels an unmatched control specification as **alternative-control sensitivity only**, not an exact replication. Panel A/B estimates use HC1 and matching-cell cluster SEs.
* The recipient-side opportunity regression (Test A3) is **not included**; it requires the original 22.5m-row dyadic model and opponent flag joins.

### E — Receipt effect by prior experience (IV)

* Original frozen cohort candidate: `derived/replication/chooser_iv_expanded_v100_PRIVATE/f14a1105a9f7/analysis/spaced90.parquet` (2,682,330 exposures, 1,625,389 recipient accounts, 4,324 expected assignment cells).
* Construct prior groups strictly from the 41,534,331-opportunity, pool/nonadjacent sample, based on **decisions before the exposure game began**: PG = any earlier chooser-side grant; PC = no earlier grant, but a prior competitive choice; NC = neither. Left-censored at November 2023.
* Reconstruct instrument `adjusted_7d/0.0594`, fixed cells of month, exact time control and mean displayed-rating bin, exposure UTC date and hour-of-week effects, and the paper's specified pre-exposure controls. Do not control for the index game's eventual board position, clock readings, or length.
* **Required pooled reproduction** before publishing any new subgroup coefficient: first stage `6.912 pp / score SD`, OLS `0.382 pp`, IV `0.295 pp` on 2,682,330 rows, within explicit numerical tolerance. If the original score or FE interpretation differs, the run writes calibration diagnostics and fails closed.
* If calibration succeeds, estimate the 3 receipt-by-prior-group effects via just-identified 2SLS and the same shared-account-or-date CR0 covariance inclusion-exclusion as the paper. Output first-stage coefficients and Wald intervals. **Subgroup-specific Anderson–Rubin and weak-identification robust inference are NOT implemented**; do not treat borderline subgroup comparisons as established until checked.
* The **matched 2,110,400-exposure receipt estimator** is not run: the frozen matched cohort remains unidentified. An earlier competitive-only IV file is not a substitute for the main pooled-score IV.

## One-shot command (fresh Mac Terminal)

After placing the ZIP and sidecar on your Desktop:

```bash
(
 set -Eeuo pipefail
 cd "$HOME/Desktop/Lichess_Desktop"
 shasum -a 256 -c Framework_AE_Completion_v1_2_0.zip.sha256
 ditto -x -k Framework_AE_Completion_v1_2_0.zip .
 WORKERS=10 MEMORY_GB=11 \
 bash Framework_AE_Completion_v1_2_0/RUN_A_E.command \
    --mode all \
    --main "$HOME/Desktop/Lichess_Desktop/FRAMEWORK_F_INPUT_20261012T030343Z"
)
```

For independent reruns, replace `--mode all` with `--mode a` or `--mode e`. Both default to 10 DuckDB worker threads, an 11 GB DuckDB memory limit where DuckDB is used, single OpenBLAS/VECLIB thread, `caffeinate`, and timestamped new output namespaces. No API, PGN downloads, Stockfish, or rating replay. Input files are never modified.

Reports and SHA-256 sidecars appear as:
- `FRAMEWORK_A_REPORT_<timestamp>.zip`, `FRAMEWORK_A_PREFLIGHT_REPORT_<timestamp>.zip`
- `FRAMEWORK_E_results_REPORT_<timestamp>.zip`, `FRAMEWORK_E_prepared_REPORT_<timestamp>.zip`, `FRAMEWORK_E_groups_REPORT_<timestamp>.zip`
- `framework_AE_<timestamp>.log`

Transfer all report ZIPs, sidecars, and log. ZIPs contain only aggregate CSV/JSON/status receipts; **never upload the private Parquets on XT_Pro**. A step may legitimately fail closed because the recovered sources do not reproduce the published cohorts. In that case its report is labeled `INCOMPLETE`, and the next step is to inspect the diagnostics rather than to bypass the gates. A failure in A does not block E and vice versa.

**Compute estimate:** With cached data on an external SSD, allow substantial variation depending on Mac memory bandwidth and disk speed. E requires a 41.5m-row ordered history scan, a 2.68m-row as-of join, and a high-dimensional FE fit; it can be notably heavier than Test F. Stage markers indicate logical milestones, **not percentages of elapsed time**. No network calls are made.
