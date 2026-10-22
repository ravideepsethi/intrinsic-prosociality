# Validation scope

This maintenance release fixes runtime compatibility, not the scientific specification. No private-data forecast, MDE or behavioral estimate has been computed here. Both reported failures occurred in launcher checks before private-data processing.

The prior missing-SciPy fix remains: a stable NumPy logistic fallback, numerically checked against SciPy. Version 1.0.2 replaces a datetime storage-unit assumption with integer Unix-millisecond arithmetic for UTC Monday grouping.

The scientific checks cover account calibration, payoff identities and all seven model index changes, post-outcome invariance, restart receipts, authentication, policy-input evidence checks, fixed calendar windows, directional MDEs, synthetic power, and optional descriptive output. The new regression check compares 1,008 timestamps, including midnight boundaries and negative epochs, with both Python's standard-library UTC calendar and DuckDB. It also checks that invalid bootstrap offsets fail explicitly.

`COMPATIBILITY_RESULTS.json` records the cross-version execution results for this repair. All tests are synthetic; passing them does not certify the still-unresolved actual policy cohort or censor date. The Mac-specific idle-sleep prevention branch is not exercised in the Linux test environment.

Estimated runtime: 10–40 minutes for the user's first private-data run, 2–8 minutes for a completed restart. Tests take roughly 5–20 seconds on a laptop. Existing Parquets and repaired fits are reused; up to ten workers are available.
