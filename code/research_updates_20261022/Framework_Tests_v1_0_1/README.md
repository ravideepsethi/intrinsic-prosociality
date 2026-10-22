# Framework tests A–F, version 1.0.1

This repair follows the returned `bb37d1b1d1a3` run. The raw persistence results are valid. All v1.0.0 Test B estimates/profiles and its Test D trigger must be replaced: physical Parquet fragments did not always contain a chooser's full history. The adjusted persistence and subgroup IV stages failed without exporting estimates. See REPAIR_NOTES.md.

This package implements the attached six-test handoff, including the new comparison of year-to-year persistence in competitive and noncompetitive states. It estimates on the existing local Parquet files. No empirical results have been generated on your Mac by preparing this package.

## Run

Place the ZIP and its SHA-256 sidecar in `~/Desktop/Lichess_Desktop`, as usual. Run:

```bash
bash <<'BASH'
set -euo pipefail
cd "$HOME/Desktop/Lichess_Desktop"
shasum -a 256 -c Framework_Tests_v1_0_1.zip.sha256
fw_unpack="$(mktemp -d "${TMPDIR:-/tmp}/framework-tests.XXXXXX")"
ditto -x -k Framework_Tests_v1_0_1.zip "$fw_unpack"
bash "$fw_unpack/Framework_Tests_v1_0_1/SETUP_AND_RUN.command" \
  --workers 10 --memory-gb 11 \
  --reuse-framework-root "/Volumes/XT_Pro/lichess_kindness/derived/replication/framework_tests_v100_PRIVATE/bb37d1b1d1a3"
BASH
```

The launcher uses `/Volumes/XT_Pro/lichess_kindness/venv/bin/python` as the base and creates a separate `venvs/framework_tests_v100` environment. Working scientific dependencies, including NumPy, remain pinned; missing SciPy or plotting dependencies install into the separate environment. Setup needs package-index access if anything is missing. The analysis itself blocks network access. `IV_PYTHON`, `IV_PROJECT_ROOT`, and `IV_DESKTOP` override the existing research interpreter and locations; `FW_PYTHON` selects an already prepared interpreter and bypasses setup.

The input drive must be mounted. Allow at least 60 GiB free for projections and model caches; exact peak disk use is unbenchmarked. The run uses at most 10 worker processes, with one numerical-library thread per worker and a requested 11 GiB working-memory budget. This is a scheduling budget, not an operating-system hard memory limit. It does not stop or change Run2, download new PGNs, call the Lichess API, or invoke Stockfish.

The repair first completes adjusted persistence from saved residual sums, then fixes subgroup IV, and re-estimates B and its dependent D decision with complete account histories. A, A3, C, matched E, and raw F reports are retained with checked provenance. The original run is opened read-only. To run only adjusted persistence, append `--stage F`. Repeat the same command to resume. `--preflight-only` checks reuse without estimating; `--status` prints the new run status. Omit the reuse option only for a completely new full run.

## Outputs

Result ZIPs and their checksum files appear in `~/Desktop/Lichess_Desktop`, alongside `framework_tests_*.log`. There are 25%, 50%, 75%, and 100% checkpoint ZIPs and a final `FRAMEWORK_TESTS_FINAL_<run-id>.zip`. The percentages denote completed stages, not equal fractions of runtime. Upload the final ZIP and sidecar for interpretation; if a stage fails, return the latest ZIP and terminal log. Independent tests continue after a model-specific failure. The final status lists every unfinished or unavailable component.

The private run and resumable Parquet caches live at:

```
/Volumes/XT_Pro/lichess_kindness/derived/replication/framework_tests_v101_PRIVATE/<configuration-hash>/
```

Only explicit aggregate report folders are included in result ZIPs. Account IDs, names, game IDs, row-level histories, fitted private model matrices and private caches remain on the drive. Each package and result ZIP includes an integrity manifest. Source hashes are authenticated on first projection; resume validates checkpoint hashes and unchanged source identities. A modified source or completed output stops the affected stage instead of silently overwriting it.

## What runs

| Test | Implementation and outputs |
|---|---|
| A | August profile flags/availability; three chooser-side flag exclusions using the original matching groups and original HC1/cell-clustered models; recipient-Patron sensitivity using the exact AFE chooser-FE specification and shared-account-or-date CR0 covariance. |
| B | P1 history groups; P2 chooser-FE group slopes and evaluation splines; jointly clustered proportional contrasts and ratios; displayed-gap and normalized-payoff sensitivities, equal positions, flag exclusion, secondary full-panel classification, group stage effects, two-panel PDF, exact conditional logit on a fixed 20% account sample. |
| C | The frozen 500-cell population exposure grid; gamma–Poisson and zero-inflated fits, profile intervals, expected-grant zero-share curves and PDF; P1-only fits and population rates used for the P2 forecast. A mean-calibrated mixture is separately labeled as a sensitivity. |
| D | Runs only when B's BOTH position contrast is uninformative. Implements the RD > 110 proxy using normalized payoff. The casual-share proxy is explicitly unavailable without a complete rated-and-casual history. |
| E | Full observed prior-history PG/PC/NC groups with no look-ahead; original matched receipt cells, ATT weighting, controls and exposure-month FE; joint group receipt effects for conditional and zero-coded outcomes, clustered by exposure opponent; interval descriptions; joint group IV on authenticated R7 S0 with first stages. |
| F | Raw and cross-fitted composition-adjusted C/N and C/L persistence matrices, joint within-state differences, persistence of C minus comparison-state selectivity, P1-group forward rates/retention, minimum 4/10/20 opportunities, all-stage and after-ply-10 versions, common and pair-specific samples, 999 whole-account bootstraps. |

`results/report/PERSISTENCE_READOUT.md` gives the main answer in words and a compact table. `tabF2_persistence_matrix_raw.csv` and its adjusted counterpart provide the full estimates and confidence intervals. Zero-grant accounts remain; no-opportunity account/state/year cells remain missing. The readout distinguishes evidence of positive persistence from an inconclusive interval. It does not infer absence of persistence from a failure to reject zero.

## Runtime and testing

Allow roughly 10–30 minutes for adjusted persistence after source checking and roughly 1–4 hours for the complete repair; these are planning estimates, not measured Mac benchmarks. The old run took 5 hours 40 minutes. The repair reuses projections, histories and nuisance scores, but B must be re-estimated. Full-account conditional logit can take longer. The terminal reports measured stage ETAs and heartbeats, with 25/50/75/100% stage checkpoints. Changing a CPU/RAM cap does not change the analysis configuration ID.

Numerical tests run before production. The package was also exercised on a synthetic end-to-end panel, including plots and restarts. Actual data authentication, original Patron reproduction, input availability, and full-scale memory/runtime are checked locally when you run it. See `VALIDATION.md` and `IMPLEMENTATION_NOTES.md` for the precise validation boundary and specification decisions.
