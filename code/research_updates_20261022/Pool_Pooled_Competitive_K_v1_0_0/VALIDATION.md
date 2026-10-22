# Validation performed before delivery

Date: 2026-09-16. All new numerical verification used explicitly synthetic data. The user's private full panel was not available in this workspace, so this package contains no new empirical estimates.

## Independent estimator checks: passed

The supplied `self_test.py` passed all five checks:

1. Every adjusted model's curve contrasts and full chooser-clustered covariance matched independent least squares with explicit chooser–state dummy variables. The fixture includes repeated choosers across states and detects the erroneous alternative of clustering by chooser–state.
2. Raw bin-mean covariance matched an independent dummy regression. A chooser with no kind draws remained in the estimation sample.
3. Streaming over small row groups and batches, followed by aggregation of three complete-chooser shards, reproduced direct sufficient statistics and support counts.
4. Joint cross-state Wald/F calculations matched direct inversion on a full-rank synthetic restriction covariance.
5. Evaluation boundaries, singleton-unit exclusion, chooser counts, and absorbed-unit counts were checked.

The dense-regression test uses 82 synthetic accounts. It took about 3.2 seconds in the build environment; this does not predict full-panel runtime.

## Complete-run checks: passed

A separate scratch-only harness ran the unchanged production estimator with 5,199 synthetic source rows, including 150 noncompetitive rows, and three worker processes. For that harness only, sample authentication and expected empirical counts were replaced by synthetic receipts. Those replacements are not present in the delivered code.

- Fresh-source staging, competitive restriction, models, covariance, figures, result archive, and checksums completed.
- All saved curve contrasts and covariance matrices matched a serial fit of the same staged data.
- Rerunning reused the existing private checkpoints without changing their bytes.
- A prior-cache fixture with a valid report manifest and cache receipt was reused successfully; it produced the same result CSVs as the fresh-source path.
- A corrupted cache checksum was rejected.
- Source and prior-cache files remained unchanged.
- The result ZIP passed its CRC check, its output manifest verified, and it contained no private Parquet files.
- Main, specification-ladder, and state-interaction figure layouts were visually inspected using synthetic plots. The small synthetic fixture used lowered display thresholds only in a separate QA copy, never in the production runner.

The complete synthetic exercise took approximately 14.7 seconds in the build environment. The macOS wrapper is supplied with shell syntax checks; it was not executed on macOS here.

## Inherited, unchanged components

`fe_engine.py`, `surface_model.py`, the current-sample authentication helper, and the sample authority/report are copied unchanged from the earlier comparison package. `stage_base.prepare_data` is the unchanged full-source preparation function; the new runner requests no separate old contexts. The new pooling, interaction model, chooser–state absorption, and cross-state chooser covariance are in `pooled_engine.py`.

The previous empirical competitive-state counts are bundled solely to check the new runner's retained rows and absorbed units. No test requires empirical coefficients or p-values to match a desired pattern. The results of the new pooled analysis remain unknown until the runner is executed on the private panel.
