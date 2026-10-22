# RD audit: one-fit numerical repair v1.0.1

The returned audit completed in 13 minutes 7 seconds. One of 42 newly requested capped candidate fits failed its convergence gate: roughly-equal positions, gap plus draw framing, first forward training fold (training through October 2024). The optimizer stopped after 24 iterations on its objective-change criterion, with a projected gradient of 0.000944, above the unchanged 0.000020 acceptance threshold. All full-sample fits, all other candidate folds, and all eight unrestricted diagnostic fits succeeded.

This package retries **only that failed training fit**, starting from the already-converged nested gap model with a zero framing coefficient. The likelihood at that start must reproduce the nested fit. The exact likelihood, rows, regressors, signs, folds and scoring rule are unchanged. The iteration allowance rises to 1,000; objective-change tolerance is tightened only if necessary. The original projected-gradient acceptance gate is never relaxed. An accepted fit must achieve at least the nested model's training likelihood, within numerical tolerance.

The returned nested gap fit already has a higher training log likelihood (−18,641.7406) than the failed expanded fit (−18,642.4688). Embedding that nested solution is therefore a strictly better feasible starting point, with no change to the statistical model.

The parent audit cache remains read only. New files are stored in `derived/replication/mechanism_rd_audit_resume_v101_PRIVATE`. The package authenticates the reviewed parent package, parent score/fit files, and the two prepared training/validation Parquets. It copies the aggregate parent report, replaces only the failed fold's fit/coefficients/scores/calibration, and regenerates comparisons and figures. It does not reconstruct any history, refit the other candidates, rerun unrestricted diagnostics or simulations, or touch the original mechanism cache.

## Command

Put the ZIP and sidecar in `~/Desktop/Lichess_Desktop`, keep XT_Pro connected, then:

```bash
cd "$HOME/Desktop/Lichess_Desktop" &&
shasum -a 256 -c Mechanism_RD_Audit_Resume_v1_0_1.zip.sha256 &&
ditto -x -k Mechanism_RD_Audit_Resume_v1_0_1.zip . &&
bash Mechanism_RD_Audit_Resume_v1_0_1/RUN_RD_AUDIT_RESUME.command
```

The launcher reuses an installed compatible Python environment, runs small validation tests and prevents idle sleep. The numerical fit uses one worker. Runtime for this retry has not been measured on the production data; it should require only the one 59,187-row training fit plus report assembly, rather than the full audit. Progress is printed every 45 seconds. A completed repair is cached for restart.

Upload `MECHANISM_RD_AUDIT_REPAIRED_RESULT_*.zip` and its `.zip.sha256` sidecar from the Desktop folder. The repaired output includes all parent aggregate results for convenience. `PARENT_SUMMARY.json` and `PARENT_ENVIRONMENT.json` retain the earlier run metadata; `SUMMARY.json` states the repair outcome. If the retry still fails the gate, a diagnostic result is packaged without manufacturing a successful coefficient or ranking.

## Scientific interpretation

The six already-converged candidates can be compared pairwise now. On capped common validation support, curved utility and draw framing are not distinguishable from the displayed-gap model by the frozen descriptive two-monthly-SE rule. The earlier global rejection of payoff-only mechanisms does not survive this RD sensitivity. The complete seven-candidate retained set remains pending until this one fit succeeds. The numerical repair itself does not provide new identifying variation or authorize causal mechanism shares.

Monthly-score standard errors and resampling intervals are descriptive across 12 validation months. Their dependence and model-selection limitations remain as described in the parent methods. The inherited methods and all other scientific specifications are unchanged.
