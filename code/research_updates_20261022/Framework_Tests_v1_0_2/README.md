# Lichess framework tests — local analysis starter v1.0.2 (Oct 12, 2026)

**Status: code compiled and synthetic mathematical checks passed. No real Lichess data were present in this environment, so NO real-data analysis was executed or certified.**

This is a conservative partial execution of the handoff (`handoff_framework_tests.md`). **Version 1.0.2 repairs the Test F regression introduced in v1.0.1: read [`README_F.md`](README_F.md) and use the independent `RUN_F.command`; the v1.0.0 scripts for A1, B/C and E are unchanged.** It deliberately does **not** assign "price," "merit," or "gate" as mechanisms from model-selection thresholds. See `METHODS_CORRECTIONS.md`.

## What the files actually do

- `src/run_bc.py`: **Test B primary holdout model** (P1 account classifications from ≥4 competitive and ≥4 clearly-worse opportunities; P2 competitive choices after ply 10; chooser-FE joint LPM with group-specific draw-payoff, natural spline, and stage interactions; chooser-cluster covariance and contrasts). Output includes a numerical B model table and *raw*, explicitly unadjusted gap/evaluation curves. **NOT YET INCLUDED**: the proposed conditional-logit, alternate payoff, full-panel classifications, flagged exclusions, or delta-method inference including uncertainty in estimated group means. The reported proportional slope SEs condition on group means.
- `src/run_bc.py`: **Test C parametric diagnosis** from competitive-position opportunities using the 500-cell grid; full-sample and P1-only gamma-Poisson/zero-inflated gamma-Poisson fits with the boundary LR test; observed/fitted zero share by exposure bins; genuine P1-to-P2 prediction for accounts with year-one zero grants and E1≥8. The gamma active-share Wald CI is an observed-information approximation and may be unreliable near boundary. None of these estimate a psychological gate.
- `src/build_a_flag_inventory.py`: **Test A1 only**, four-group disabled/TOS/patron inventory, provided the original **599,045-account state cohort** and August profile snapshot are supplied. It DOES NOT re-estimate the original controlled matched Panel A/B or recipient side (A2/A3). Those require original Stage 10 matching groups, controls, and production code.
- `src/build_e_groups.py`: **Test E groups only**, using an existing matched/IV exposure cohort and the main 41.5m panel. It makes mutually exclusive prior-experience groups with an ASOF join that requires choices to precede the exposure game's **start**, with the history based only on observed events in the panel. **Does not estimate matched or IV treatment effects**; those require exact original design matrices, covariance and historical score construction.
- **Test F**: `src/run_f.py` (and `RUN_F.command`) computes region-specific two-year transitions, C/L persistence, cross-state predictiveness and sensitivities on the original paper sample. It is a separate scan and does not rerun B/C. See `README_F.md`.
- **Test D is deliberately not launched.** Reuse existing RD (provisional) diagnostics first; casual games require an additional PGN extraction if genuinely necessary.

## Absolute prerequisite: use the right data lineage

The certified `derived/replication/analysis_panel_24m_sf100k` contains **47,587,020** all-creation-source active resolutions. It is **not** the paper's 41,534,331-row POOL, observed-nonadjacent sample. The B/C script refuses to proceed unless the exact main sample has **41,534,331 rows, 570,091 grants, 15,207,423 competitive opportunities, November 2023–October 2025**, unless explicit alternative expected totals are provided. Do **not** simply alter expectations to make a different data population pass.

To inspect likely sample locations (names/metadata only), use:

```bash
bash "$HOME/Desktop/Lichess_Desktop/Framework_Tests_v1_0_1/RUN_BC.command" --discover
```

On the user's Mac, use the external-drive main Parquet path verified by its own provenance receipt. The original paper sample still includes the author's accounts; any author-clean re-estimation must record a new lineage and justified new expected totals, never just change counts to fit.

## Installation + launch (in a fresh macOS Terminal)

Place `Framework_Tests_v1_0_1.zip` and its `.sha256` file in `~/Desktop/Lichess_Desktop`. Then paste:

```bash
(
  set -Eeuo pipefail
  cd "$HOME/Desktop/Lichess_Desktop"
  shasum -a 256 -c Framework_Tests_v1_0_1.zip.sha256
  ditto -x -k Framework_Tests_v1_0_1.zip .
  bash "$HOME/Desktop/Lichess_Desktop/Framework_Tests_v1_0_1/RUN_BC.command" --discover
)
```

After examining the listed candidates and verifying which path has the 41.5m POOL/NONADJACENT sample, set `MAIN` to its exact Parquet **file or directory** and launch:

```bash
(
  set -Eeuo pipefail
  MAIN="/Volumes/XT_Pro/lichess_kindness/REPLACE_WITH_VERIFIED_MAIN_SAMPLE_PATH"
  bash "$HOME/Desktop/Lichess_Desktop/Framework_Tests_v1_0_1/RUN_BC.command" \
    --main "$MAIN"
)
```

For `.duckdb` input, add `--view EXACT_VIEW_NAME`. The chosen input path is not an output guess and must come from a manifest or confirmed local source. The script will print why it fails rather than silently use the Stage 07 all-source panel.

B/C outputs are in a new timestamped folder:

- `$ROOT/output/framework_BC_v100/<timestamp>/private/` — normalized rows, private account labels, full model sample, account-level exposure data, logs and spill. **Never upload these files.**
- `$ROOT/output/framework_BC_v100/<timestamp>/public/` — aggregate-only tables, figures, hashes, success receipt.
- `~/Desktop/Lichess_Desktop/FRAMEWORK_BC_REPORT_<timestamp>.zip` and `.zip.sha256` — aggregate-only transfer packages.

Both use local DuckDB and Parquet. No API requests, Stockfish evaluation, downloads, or rating replay. Defaults: 10 DuckDB workers and 11 GiB memory budget (override environment variables `WORKERS` and `MEMORY_GB` for the wrapper). Requires installed Python packages `duckdb`, `numpy`, `pandas`; `matplotlib` is optional for the figures. It does not require SciPy. Its execution time depends heavily on available disk and Parquet locality; the costly parts are the 41.5m-row scan/export and the chooser-FE regression. The private Parquet caches can take several GB.

## Test A1 flags (after locating the original matched cohort)

```bash
bash "$HOME/Desktop/Lichess_Desktop/Framework_Tests_v1_0_1/RUN_A1.command" \
  --state "/path/to/EXACT_ORIGINAL_PANEL_B_C_599045.parquet" \
  --profiles "/path/to/AUGUST_2026_PROFILES.parquet" \
  --state-user-col chooser_user_id \
  --state-comp-col ever_competitive_grant \
  --state-lost-col ever_clearly_worse_grant \
  --profile-user-col id --profile-patron-col patron
```

Those column names are **examples**: use the actual source fields from its authenticated schema. If the cohort isn't present, do not substitute a new random match. Source fields / exact original controls need provenance audit before attempting A2/A3.

## Test E experience groups (only after locating the existing exposure sample)

```bash
bash "$HOME/Desktop/Lichess_Desktop/Framework_Tests_v1_0_1/RUN_E_GROUPS.command" \
  --main "$MAIN" \
  --exposures "/path/to/EXACT_RECEIPT_EXPOSURE_COHORT.parquet" \
  --recipient-col recipient_user_id \
  --start-ms-col exposure_start_ms \
  --exposure-id-col exposure_game_id
```

Again, exposure field names above are **illustrations**, not verified schema claims. The original IV cohort has 2,682,330 exposures in the manuscript. If starting from an author-excluded cohort or matched exposure cohort, document its actual counts and override `--expect-exposures` explicitly. The E output is an internal variable-building artifact, not a causal effect estimate.

## Validation performed

`python3 tests/test_synthetic.py` passed checks for:

1. natural spline shape and natural boundaries;
2. negative-binomial/gamma-Poisson likelihood against `math.lgamma`;
3. zero-inflated likelihood recovery under simulated data;
4. within-account sufficient statistics and account-cluster covariance algebra.

Real DuckDB end-to-end execution could not be tested here because the runtime did not have DuckDB or private Lichess data; **synthetic mathematical checks are not production certification**.

## Checks before interpreting results

- Confirm exact source, checksum, 24 months, counts and modified/excluded-author population.
- Confirm group retention, support, unique chooser and group counts. A large difference in group size can make raw profiles misleading.
- For B, test significance of a **difference**, not merely the difference between two separate significance decisions. Treat ratio SEs as preliminary and avoid the handoff's mechanism thresholds.
- For C, report Gamma-Poisson versus mixture fit, *and* held-out P2 forecasts. Distinguish zero propensity from very-low propensity and selective sample survival.
- For E, distinguish prior *observed in the 24-month panel* from prior ever. Any grant before exposure supersedes the PC/NC classification.
- Re-use the original IV and Patron regression producers once found to maintain comparison with paper tables.


## October 12 Test F regression repair

Use `Framework_Tests_v1_0_2/RUN_F.command` for Test F; do not run v1.0.1 for Test F. The new `tabF5_collinearity_audit.csv` documents dropped nonidentified nuisance controls without dropping or rotating first-year focal persistence regressors. See `README_F.md`.
