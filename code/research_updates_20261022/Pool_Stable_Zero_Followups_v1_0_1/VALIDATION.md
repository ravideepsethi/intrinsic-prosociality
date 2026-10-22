# Validation before delivery

The private 41.5-million-row opportunity panel is not present in the assistant workspace. No new empirical estimates are claimed here. The package runs the new estimates on the user's Mac and gates success on source authentication and reproduction of the preceding analysis.

Eight numerical, production-evidence, and data-handling tests pass:

1. The nuisance matrix equals the preceding stable-rating runner's selected control matrix exactly.
2. Pooled and state-interacted quadratic coefficients and chooser-clustered covariance match independent full dummy-variable OLS. The explicit-dummy benchmark also verifies the joint cross-state Wald statistic.
3. Cross-window covariance matches independently constructed chooser influence scores, including off-diagonal covariance from shared accounts.
4. Complete chooser clusters are preserved across Parquet record batches and worker shards; merged moments and support counts match a single-block calculation; local singleton and exact-tie exclusions are recomputed correctly.
5. Empty or unidentified windows produce explicit unavailable results, not estimated zeros.
6. The declared model grid and treatment of unavailable tests in Holm adjustment are verified.

7. The actual bundled prior sample-count list passes the production count validator for both stable samples; changed counts, missing fields, duplicate samples, missing samples, and malformed JSON structures fail. This directly covers the reported v1.0.0 failure.
8. The actual prior local-linear CSV produces all 90 replication checks, and a deliberately changed SE is detected. This validates the production evidence join, not a new empirical re-estimation.

The initial synthetic two-worker integration test ran all 60 specifications and generated all five figure pairs plus six aggregate Parquet tables. Restart reused completed moment/score checkpoints without rewriting them and reproduced identical result CSV bytes. The initial test took 12.45 seconds in the assistant environment. This tiny synthetic runtime does not predict private-panel runtime. An additional retained synthetic run supports visual inspection of the report figures.

Synthetic validation outputs are kept outside the delivered package. The launcher runs the numerical self-tests before the real job; the standalone integration test remains available for replication.

On real data, the runner additionally requires:

- The same authenticated panel fingerprint as the prior stable-rating results.
- Exact source and retained sample-count replication in each stable sample, including board-state counts.
- Reproduction of all 90 preceding local-linear term rows, including clustered SEs, to the documented numerical tolerance.
- Read-only source signatures and valid package/checkpoint checksums.

No new polynomial result, significance level, direction, curvature, jump, or state pattern is required to pass a gate.

## v1.0.1 repair verification

The v1.0.0 failure was reproduced by calling its object-only loader on the actual list-valued prior count artifact. The replacement uses a dedicated schema-checked list reader and an early preflight. The mathematical estimator files are unchanged. The complete synthetic 60-fit integration/restart check is rerun for this release. The Mac private-panel gates remain required before success.

Repair verification passed: 8 self-tests; 60-fit two-worker synthetic integration and restart in 14.13 seconds; shell syntax; original-error reproduction; unchanged estimator/report source files.
