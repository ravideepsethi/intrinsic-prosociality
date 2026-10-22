# Validation record — v1.0.0

Validated in the build environment using Python 3.12, NumPy 2.3.5, SciPy 1.17.0, PyArrow 25.0.1, DuckDB 1.5.5 and Matplotlib 3.10.8. The production Mac launcher verifies supported dependency versions before running.

Eight numerical self-tests passed:

1. All six adjusted global models (three axes, pooled and state-interacted) agree with independent regressions using explicit chooser-state dummy variables, including chooser-clustered covariance and finite-sample correction.
2. Joint board-state tests use the cross-state covariance and agree with independent Wald calculations.
3. Raw-rate covariance agrees with an independent dummy regression; zero-grant accounts remain included.
4. Splitting into account shards and small Parquet record batches preserves complete chooser clusters and reproduces pooled moments/counts.
5. Competitive-state endpoints and singleton removal are correct.
6. Local left/right slopes, jump, exact-zero indicator and covariance agree with an explicit-dummy regression; window-specific singleton removal, account-shard aggregation and saved moments agree. This fixture includes constant K and RD.
7. Normalized-payoff bin endpoints and empty local windows are handled without inventing identified estimates.
8. Inclusive RD/K cutoffs and payoff normalization select the intended observations.

The constant-K fixture exposed cancellation in a nearly zero within-variance. The implementation now directly recenters candidate near-constant columns before rank determination. The dense-regression checks pass with the corrected rank and covariance; tolerances were not relaxed to bypass that issue.

An end-to-end synthetic test also passed using two process workers, all five sample definitions, all three axes, state interactions, local diagnostics, result tables, five PNG/PDF figure pairs, and restart from verified checkpoints. The restarted curves and local-diagnostic CSVs were byte-identical. Figures were visually inspected for layout. Synthetic support thresholds were reduced only inside that test to exercise rendering; the production thresholds remain 500 observations, 50 switching choosers and six months.

The launcher passes Bash syntax validation and the Python CLI help entrypoint loads successfully. Package and ZIP manifests are checked at packaging.

No new empirical estimates were computed here: the private source panel is on the user's Mac. Production sample-hash authentication and the full-panel analysis occur when the delivered command runs. The synthetic tests do not establish any empirical curve shape or theory result.
