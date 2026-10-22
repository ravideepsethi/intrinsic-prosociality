# Activity-group state rates and proportional desert contrasts v1.0.0

This short add-on supplies the missing state-specific rates needed to distinguish a smaller absolute desert gap from a smaller proportional contrast. It reuses the verified private chooser census and keeps the same 1,982,345 both-state accounts, including every observed nongranter.

It reports the competitive and clearly-worse grant rates, overall binary-sample rate, percentage-point gap, competitive/clearly-worse rate ratio and confidence interval for the existing light (2–6), medium (7–16) and heavy (17+) activity groups. It also compares the heavy and light groups' rate ratios directly.

The primary small table weights choosers equally. Companion tables use common chooser weights reproducing the original FE and inverse-count FE results, plus ordinary pooled state rates. The first three use identical chooser weights in both states, so their state-rate differences reproduce the corresponding previous FE gaps. All zero-grant accounts remain included; no individual ratios or smoothing constants are used.

## Run

Save this ZIP and its `.zip.sha256` sidecar in `~/Desktop/Lichess_Desktop`, connect XT_Pro, and paste the full block:

```bash
/bin/bash <<'BASH'
set -euo pipefail
cd "$HOME/Desktop/Lichess_Desktop"
/usr/bin/shasum -a 256 -c Pool_Activity_State_Rates_v1_0_0.zip.sha256
state_rates_unpack="$(/usr/bin/mktemp -d "$HOME/Desktop/Lichess_Desktop/activity_state_rates_run.XXXXXX")"
/usr/bin/ditto -x -k Pool_Activity_State_Rates_v1_0_0.zip "$state_rates_unpack"
state_rates_log="$HOME/Desktop/Lichess_Desktop/activity_state_rates_$(/bin/date -u +%Y%m%dT%H%M%SZ).log"
/bin/bash "$state_rates_unpack/Pool_Activity_State_Rates_v1_0_0/RUN_ACTIVITY_STATE_RATES.command" 2>&1 | /usr/bin/tee "$state_rates_log"
BASH
```

**Expected elapsed time: approximately 15–45 seconds**, including local report writing with the existing census and environment. First-time dependency installation or competing jobs can add time. The runner does not fetch games, run engines or rescan the monthly panels.

Input:

`/Volumes/XT_Pro/lichess_kindness/derived/replication/pool_chooser_support_v100_PRIVATE/chooser_counts_private.parquet`

The source contract, private census hash, exact sample counts and original FE reference are verified. The census hash must match the verified equal-chooser return. All 12 previous overall/group coefficients and SEs must reproduce before completion. The launcher reuses an existing compatible Python environment and uses eight Arrow read threads by default, within the permitted maximum of ten; native math threads are capped at one.

Optional environment overrides: `STATE_RATES_PROJECT`, `STATE_RATES_SOURCE`, `STATE_RATES_TRANSFER`, `STATE_RATES_PYTHON`, `STATE_RATES_THREADS` (1–10).

## Results

Public output is written beneath:

`/Volumes/XT_Pro/lichess_kindness/output/pool_activity_state_rates_v100/`

Return `POOL_ACTIVITY_STATE_RATES_RESULTS_v100_<timestamp>.zip` and its SHA-256 sidecar from `~/Desktop/Lichess_Desktop`. The success marker is `ACTIVITY_STATE_RATES_COMPLETE`.

The archive includes:

- `state_rates_and_ratios.csv`: four rate conventions for all both-state choosers and the three activity groups; includes a 50/50 state-standardized level.
- `activity_ratio_comparisons.csv`: heavy/light, medium/light and heavy/medium ratios of risk ratios, intervals and absolute-gap differences.
- `state_rate_covariance_pct2.csv`: the joint covariance of the state and overall rates.
- `ACTIVITY_STATE_RATES_TABLE.tex`: the small equal-chooser table for the paper.
- `SUMMARY.md`: readable tables and definitions.
- Methods, interpretation and talk wording, source lineage, reference reproduction, runtime and checksums.

Identifiers and individual records stay on the Mac. The new rate table has been tested synthetically; its production values are not available until the local run returns.

## Wording

Until the proportional comparison is available, say that heavy choosers have a **smaller absolute desert gap**. The earlier results do not establish that heavy choosers are less selective on a relative scale. The new comparison remains descriptive and does not identify the causal effect of activity or reestimate any adjusted paper specification.

For the talk, the existing full-panel figures are 1.37% of qualifying disconnection opportunities granted, 8.58% of observed choosers granting at least once during the panel, and a 2.19% equal-chooser mean observed grant rate. They have different denominators. The first is not a percentage of all Lichess games.

See `docs/INTERPRETATION.md` for concise paper and talk language and `docs/METHODS.md` for the rate and inference formulas.
