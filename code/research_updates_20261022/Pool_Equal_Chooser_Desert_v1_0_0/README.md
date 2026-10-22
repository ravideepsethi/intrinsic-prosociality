# Equal chooser and activity-weighting sensitivity v1.0.0

This runner compares the original minimal chooser-FE desert estimate with two reweightings over the same **1,982,345 choosers observed in both states**. It retains all **1,757,864 observed nongranters** in that support sample.

| Version | Weight on each chooser's observed competitive-minus-clearly-worse grant-rate difference |
|---|---|
| Original FE | F L/(F+L) |
| FE with observation weight 1/N, N=F+L | F L/(F+L)^2 |
| Equal chooser | 1 |

The second removes the activity factor but retains state-balance weighting. The third gives each chooser's observed within-person difference equal weight. Results include SEs, 95% confidence intervals and paired differences accounting for covariance.

The package also reports exact FE weight shares by activity decile, slopes for light/medium/heavy choosers, the observed share of choosers who ever grant, and their mean individual grant rate. No regression is restricted to ever-granters.

## Run on the Mac

Save this ZIP and its `.zip.sha256` sidecar in `~/Desktop/Lichess_Desktop`, connect XT_Pro, and paste the complete block:

```bash
/bin/bash <<'BASH'
set -euo pipefail
cd "$HOME/Desktop/Lichess_Desktop"
/usr/bin/shasum -a 256 -c Pool_Equal_Chooser_Desert_v1_0_0.zip.sha256
equal_chooser_unpack="$(/usr/bin/mktemp -d "$HOME/Desktop/Lichess_Desktop/equal_chooser_run.XXXXXX")"
/usr/bin/ditto -x -k Pool_Equal_Chooser_Desert_v1_0_0.zip "$equal_chooser_unpack"
equal_chooser_log="$HOME/Desktop/Lichess_Desktop/equal_chooser_$(/bin/date -u +%Y%m%dT%H%M%SZ).log"
/bin/bash "$equal_chooser_unpack/Pool_Equal_Chooser_Desert_v1_0_0/RUN_EQUAL_CHOOSER.command" 2>&1 | /usr/bin/tee "$equal_chooser_log"
BASH
```

**Expected runtime: approximately 15–45 seconds** with the existing census and compatible environment; this is an estimate, not a production benchmark. First-time dependency installation or competing jobs can add time. The previous support audit took 77 seconds; this runner reuses its chooser aggregates and does not scan all 24 monthly panels again.

It reads:

`/Volumes/XT_Pro/lichess_kindness/derived/replication/pool_chooser_support_v100_PRIVATE/chooser_counts_private.parquet`

It checks that file against its saved SHA-256 receipt and the contract from your returned support audit, verifies the sample/support counts, and reproduces the original coefficient and source-reported SE before calculating the new results. No API calls, engine runs or source-data changes are made. It uses up to eight Arrow read threads by default and caps native math threads at one. A duplicate run or simultaneous source-census writer is blocked by file locks.

The launcher reuses a compatible existing Python environment, including the Wave1 environment that ran your support audit. Environment overrides: `EQUAL_CHOOSER_PROJECT`, `EQUAL_CHOOSER_SOURCE`, `EQUAL_CHOOSER_TRANSFER`, `EQUAL_CHOOSER_PYTHON`, `EQUAL_CHOOSER_THREADS` (1–10).

## Return files

The runner writes a timestamped output directory under:

`/Volumes/XT_Pro/lichess_kindness/output/pool_equal_chooser_desert_v100/`

It exports `POOL_EQUAL_CHOOSER_DESERT_RESULTS_v100_<timestamp>.zip` and its SHA-256 sidecar to `~/Desktop/Lichess_Desktop`. Return both. The completion marker is `EQUAL_CHOOSER_DESERT_COMPLETE`.

The return ZIP contains only aggregate results:

- `estimates.csv`: the three coefficients, common chooser-cluster SEs and 95% intervals.
- `paired_differences.csv`: inverse-count minus original, equal-chooser minus original, and equal-chooser minus inverse-count, with paired SEs and intervals.
- `estimator_covariance_pp2.csv`: their joint covariance in squared percentage points.
- `activity_decile_weight_shares.csv`, `activity_top_shares.csv`: opportunity and identifying-weight shares, with explicit ranking populations and tie handling.
- `activity_tercile_estimates.csv`, `activity_tercile_differences.csv`, `activity_tercile_support.csv`, `ACTIVITY_TERCILE_DEFINITION.json`: all three specifications for light, medium and heavy accounts on the common state-support sample.
- `granting_rates.csv`: opportunity grant rates, fractions of observed choosers who ever grant, and equal-chooser mean grant rates.
- `SUMMARY.md`, `MANUSCRIPT_SNIPPET.tex`, methods, provenance, original-result reproduction, environment and checksums.

Chooser identifiers and individual counts stay on the Mac.

## Interpretation details

The inverse-count weight uses the number of opportunities **in the binary contrast**, N=F+L; it is not the full-panel count when a chooser has middle-position opportunities. The exact equal-chooser version is equivalent to a weighted FE regression using observation weight N/(F L), and is computed directly from the chooser-level differences.

All new inference uses a common chooser-level sandwich correction over the same state-varying accounts. The source C7R SE uses a different finite-sample correction; it is reproduced and reported separately. The paired comparison accounts for common data, rather than subtracting independently estimated SEs. See `docs/METHODS.md` for the formulas.

Activity deciles allocate boundary ties fractionally and equally. Activity terciles instead retain equal opportunity counts together; group sizes may therefore differ. Rates in the slide table use their stated denominators and observed ever-grant status is descriptive, never a regression selection rule.

The code is tested on synthetic data, including literal weighted fixed-effect regressions and joint cluster covariance calculations. The new production reweighted estimates are not known until this runs on the Mac.
