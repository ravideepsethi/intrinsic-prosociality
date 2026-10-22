# Mechanism RD audit v1.0.0

Run the targeted RD influence check using the completed mechanism cache. No historical reconstruction or recoverability simulations are rerun.

## Run on the Mac

Put the ZIP and its SHA-256 sidecar in `~/Desktop/Lichess_Desktop`, then:

```bash
cd "$HOME/Desktop/Lichess_Desktop" &&
shasum -a 256 -c Mechanism_RD_Audit_v1_0_0.zip.sha256 &&
ditto -x -k Mechanism_RD_Audit_v1_0_0.zip . &&
bash Mechanism_RD_Audit_v1_0_0/RUN_RD_AUDIT.command
```

Keep XT_Pro connected. The launcher reuses a compatible Python environment, checks package integrity, runs the small validation tests, and prevents idle sleep on macOS. If no compatible environment is found, it creates an isolated one inside this package.

Expected existing input:

`/Volumes/XT_Pro/lichess_kindness/derived/replication/mechanism_separation_v100_PRIVATE`

This is the private cache left by the completed September 26 mechanism run. The returned results ZIP alone does not contain the analysis rows needed to refit. This package stops with an explicit error if the cache or its receipts are missing or inconsistent; it does not rebuild them.

## What runs

1. Authenticate the 24 cached analysis Parquets and the original model fits. Keep the original primary regular-player activity rule. Compare that sample with the same sample restricted to **both pregame RDs ≤110**. Roughly-equal positions are primary; clearly-losing positions are supporting.
2. Reuse the original seven candidate models. Refit those candidates on the restricted sample. Reproduce the original held-out scores, then compare original and refitted predictions on identical restricted held-out chooser-month groups.
3. Report support, account retention, high-RD contributions to conditional scores, common-sample index profiles, conditional allocation by gap, and separate unrestricted-sign diagnostics. Correct the old cost-table grant counts and combine coincident curves in the old M2 figure.

The two-tier activity definitions are not substituted for this comparison. It changes only the RD restriction within the original primary activity definition. Removing observations can still change which accounts identify conditional logit; that change is reported.

## Runtime and restart

Production runtime is not benchmarked. This omits the expensive chronology and 160-simulation stages. The remaining time depends on the drive read speed, conditional-logit convergence, and inference on the restricted sample. Progress messages appear every 45 seconds.

Defaults: up to eight preparation threads, two simultaneous model fits, and a 6 GB DuckDB preparation limit. Numerical-library threads are set to one per fit. The DuckDB limit is not a cap on total process memory. For a lower-memory run:

```bash
bash Mechanism_RD_Audit_v1_0_0/RUN_RD_AUDIT.command --fit-workers 1 --memory-gb 3
```

Rerun the same command after an interruption. Completed preparations and fits are reused after receipt checks. The original cache is read only. New restart files live in `derived/replication/mechanism_rd_audit_v100_PRIVATE`; reports also live in `output/mechanism_rd_audit_v100`.

## Return

Upload the newly created `MECHANISM_RD_AUDIT_RESULT_*.zip` and its `.zip.sha256` sidecar from `~/Desktop/Lichess_Desktop`. The ZIP contains aggregate tables, figures, model coefficients and covariances, methods, checksums, and status. It excludes cached account-level rows and account IDs.

A failed input or fit is recorded explicitly. Inspect `SUMMARY.json` and `MODEL_COMPARISON_STATUS.json` before interpreting rankings. A partial result is still packaged for diagnosis.

Read `METHODS.md` for exact estimands and limits. This audit does not estimate causal mechanism shares, update the recoverability experiment, or perform the post-change behavioral analysis.
