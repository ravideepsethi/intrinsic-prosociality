# Stable-rating curves — ready-to-run package

This package tests the proposed RD/K composition explanation without imposing the desired curve shape. It runs on the frozen private two-year panel on your Mac. No live Lichess requests are made.

Download the ZIP and its `.zip.sha256` file to `~/Desktop/Lichess_Desktop`. Paste the complete command in `RUN_TERMINAL.txt`. Defaults: project `/Volumes/XT_Pro/lichess_kindness`, 10 workers. The launcher reuses a compatible Python environment or creates one, verifies package checksums, runs numerical self-tests, and starts the analysis. Installing missing Python packages requires an Internet connection; the subsequent panel analysis is offline. Keep the external drive connected.

## What it estimates

- All competitive opportunities, both-player RD≤75, RD≤60, RD≤100, and RD≤75 with K∈[11,12].
- Gap, draw payoff D, and normalized payoff D/K on matched observations within each sample.
- Raw and adjusted curves. Adjusted models absorb chooser × broad-board-state fixed effects; uncertainty is clustered by chooser.
- Controls: ply, both players' RD and volatility, month, speed, 50-cp board evaluation bins, K20 indicators and log K.
- Separate state curves for the primary RD≤75 sample and its narrow-K subset.
- Unrestricted local slopes on either side of zero, a possible jump, and an exact-zero effect; three fixed bandwidths on each axis. No shape restriction or data-chosen bandwidth.

Global plots show differences from a reference bin, in percentage points; they are not utility values or absolute probabilities. The raw rates in levels are also available in `bin_composition.csv`.

The five main figure files are exported as PNG and PDF. Tables include sample attrition, within-chooser support, K/RD composition, tail comparisons using common bins and weights, and local near-zero diagnostics with clustered SEs/CIs and multiplicity adjustments. `RESULTS.md` summarizes the outputs automatically.

## Where results go

The report is under:

```
/Volumes/XT_Pro/lichess_kindness/output/pool_stable_rating_curves_v100/<run identity>/report
```

At completion, upload both files created in `~/Desktop/Lichess_Desktop`:

```
POOL_STABLE_RATING_CURVES_RESULTS_v100_<identity>.zip
POOL_STABLE_RATING_CURVES_RESULTS_v100_<identity>.zip.sha256
```

The ZIP contains aggregate results, figures, methods, executed source code and checksums. Private panel rows remain on your drive. The final terminal lines print the exact ZIP, figures and private-cache paths. If interrupted, rerun the same command; completed, verified shard/sample checkpoints are reused. Runtime depends on your disk, CPU and available cache; no timing estimate has been measured on the private panel.

## How to interpret the result

Compare the unrestricted stable-sample curves with the full benchmark only where both have adequate support. Inspect the support/K figure and `common_weight_payoff_tail.csv` before concluding that a tail rebound has disappeared. Restrictions can remove the very observations that identify a tail.

`REFERENCE_MODEL.md` specifies the reference-dependent utility comparison `v(D+K/2)-v(D)` and explains the role of the zero diagnostics. A smooth increasing S-like grant curve would be a descriptive finding, not by itself identification of reference dependence or loss aversion. The code does not estimate structural prospect-theory parameters.

`METHODS.md` gives exact fields, filters, controls, support rules, coefficient units and inference. `VALIDATION.md` distinguishes tests completed here from the empirical analysis that will run on your machine.
