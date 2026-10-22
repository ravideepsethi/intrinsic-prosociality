# New Test F — what kind of granting persists? (v1.0.2)

**Status:** The F script compiles and synthetic tests pass. The 41.5-million-opportunity private Parquet is not present in this environment, so **no Lichess Test F estimate has been run or validated on real data here**.

This is an add-on to the existing v1.0.0 analysis bundle. The B/C and A1/E-group programs are unchanged; `RUN_F.command` runs **independently**, so you do not need to rerun B/C to calculate the year-to-year persistence results.

## Question and comparison

The manuscript already reports year-to-year persistence of **competitive** granting (666,131 accounts, unweighted correlation 0.545, total-opportunity-weighted correlation 0.618). That does **not** establish whether grants in clearly-worse positions persist, whether both persist, or whether generosity generalizes between states.

Test F divides the panel into November 2023–October 2024 (P1) and November 2024–October 2025 (P2). It compares (C) competitive positions (`v>=-100` cp), (L) clearly-worse positions (`v<=-300`), and (M) modestly-worse positions (`-300<v<-100`). The primary comparison of C and L excludes M from the **category definition**; another comparison uses all noncompetitive (M+L) positions. Any M-only grant makes an account `NEI` (neither focal category), not necessarily a never-granter.

Primary balanced sample requires **at least four C opportunities and four L opportunities in *each* year**. Group an account separately in P1 and P2 as CO (only C grant), LO (only L grant), BOTH, or NEI (neither C nor L grant). The study reports account retention to the balanced cohort from the P1-only eligibility pool, avoiding survival claims for accounts that stop playing. Sensitivities use one and ten opportunities per state/year, all noncompetitive positions, and after-ply-10 granting.

Outputs:

- **Year-specific opportunities and grant rates** in C, L, M;
- **The 4×4 transition matrix** from P1 group to P2 group, with raw counts and row percentages;
- **P2 rates separately in C, L and M, conditional on P1 group** (pooled and equal-account rates);
- **Four cross-year correlations**: C1–C2, L1–L2, C1–L2, L1–C2 (equal-account and harmonic-opportunity-weighted), plus the persistence of the **selectivity index** (C grant rate minus L grant rate);
- **Two cross-prediction models** for P2 C/L grant rates, jointly estimating the effect of P1 C/L histories conditional on opportunity exposure and P2 state composition, with chooser-clustered robust variance and cross-outcome covariance;
- **Sensitivity to defining noncompetitive as `v < -100`,** including noncompetitive transition probabilities, P2 rates, and correlations.

Do not infer causal effects, structural moral types, or lack of concern for ratings from these observational correlations. A failure to find L persistence may reflect the rarity of lost-position grants and limited statistical power rather than a genuine zero association.

## Installation

Place these exact files in `~/Desktop/Lichess_Desktop` on the Mac:

- `Framework_Tests_v1_0_1.zip`
- `Framework_Tests_v1_0_1.zip.sha256`

Run from a fresh Terminal:

```bash
(
  set -Eeuo pipefail
  cd "$HOME/Desktop/Lichess_Desktop"
  shasum -a 256 -c Framework_Tests_v1_0_1.zip.sha256
  ditto -x -k Framework_Tests_v1_0_1.zip .
  bash "$HOME/Desktop/Lichess_Desktop/Framework_Tests_v1_0_1/RUN_F.command" --discover
)
```

**After confirming the true 41,534,331-row pool/nonadjacent analysis sample from its input manifest**, replace the path below:

```bash
(
  set -Eeuo pipefail
  MAIN="/Volumes/XT_Pro/lichess_kindness/REPLACE_WITH_VERIFIED_POOL_NONADJACENT_INPUT"
  bash "$HOME/Desktop/Lichess_Desktop/Framework_Tests_v1_0_1/RUN_F.command" \
    --main "$MAIN"
)
```

If `MAIN` is a DuckDB database file, also pass `--view EXACT_VIEW_NAME`; for Parquet file/directory no `--view` is required. The program refuses to run against the 47.59-million-row all-creation-source Stage 07 panel. It checks the paper's exact row, grant, competitive and lost-region counts and the 24-month dates. Do not override those definitions or silently change the expected counts.

Dependencies: Python 3 with `duckdb`, `numpy`, and `pandas`; optional `matplotlib` for one PDF heatmap. **No API calls, PGN downloads, engine evaluations, or rating-state replay.** The first full scan and 3.2-million-account aggregation may take several minutes or longer depending on the external drive. The launcher uses at most 10 DuckDB threads and a default 11-GB DuckDB memory budget, and prints stage checkpoints at 25%, 50%, 75%, and 100% (stage markers, **not calibrated percentages of runtime**).

## Where outputs are written

- `$LICHESS_ROOT/output/framework_F_v102/<UTC timestamp>/private` — account-level Parquets, source path, mapping audit and log. **Keep private.**
- `$LICHESS_ROOT/output/framework_F_v102/<UTC timestamp>/public` — aggregate CSVs, optional heatmap, SHA-indexed `_SUCCESS.json`.
- `~/Desktop/Lichess_Desktop/FRAMEWORK_F_REPORT_<UTC timestamp>.zip` and `.zip.sha256` — aggregate-only transfer report. Upload these two files and the log, **not** the private Parquets.

Existing certified folders are not overwritten. Check source checksum/manifests independently before running. Successful script exit is accompanied by a `_SUCCESS.json` file; its status covers only this local Test F computation, not causal identification or formal manuscript readiness.

### Published statistic cross-check

The first report to inspect is `tabF0_original_competitive_reconciliation.csv`. It reconstructs the competitive-only persistence cohort from the paper. Its diagnostics should be consistent with 666,131 accounts and correlations 0.545/0.618. A discrepancy is reported as a warning; do not interpret F results before reconciling such a discrepancy with the manuscript's original source and definitions.

## v1.0.2 repair after first production attempt

The 2026-10-12 03:03 UTC production attempt passed all source checks, built
the account-year summaries, and failed at the first P2 cross-prediction model
with rank deficiency in the weighted regression. In v1.0.1, the model included
all four bullet/blitz/rapid/classical shares plus an intercept (ultrabullet
was the implicit reference). When the omitted-speed share has no variance on
the balanced account sample, those columns sum exactly to the intercept.
Other redundant nuisance compositions can create the same problem.

v1.0.2 keeps the intercept and every predefined P1 persistence predictor. It
uses weighted twice-reorthogonalized Gram-Schmidt to omit **only nonidentifiable
nuisance controls**, with the exact omitted columns in
`tabF5_collinearity_audit.csv`; weighted QR estimates the original coefficients
without inverting unstable normal equations. A genuinely unidentified focal
predictor still fails closed. The paper's preflight restrictions, sample
selection, estimands and cluster covariance have not been changed.

To run on the verified 24-month file links already created by the first run:

```bash
(
  set -Eeuo pipefail
  cd "$HOME/Desktop/Lichess_Desktop"
  shasum -a 256 -c Framework_Tests_v1_0_2.zip.sha256
  ditto -x -k Framework_Tests_v1_0_2.zip .
  WORKERS=10 MEMORY_GB=11 bash \
    Framework_Tests_v1_0_2/RUN_F.command \
    --main "$HOME/Desktop/Lichess_Desktop/FRAMEWORK_F_INPUT_20261012T030343Z"
)
```

Do not reuse or report files under the failed v1.0.1 output root as finished
results. The next run gets a new immutable `framework_F_v102` output root.
