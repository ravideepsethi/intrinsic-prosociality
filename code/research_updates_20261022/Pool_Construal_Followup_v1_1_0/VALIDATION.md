# Software validation

Validated on 2026-09-20 in Python 3.12.14 with NumPy 2.3.5, SciPy 1.16.3, pandas 2.3.3, PyArrow 24.0.0, DuckDB 1.5.2 and Numba 0.67.0. Production dependencies are recorded in each run identity.

`OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 test_followup.py --smoke` passed all 18 offline tests and the parallel synthetic integration run.

Ten inherited checks cover exhaustive state/type likelihoods, analytic gradients, forward filtering without current/future outcome leakage, nested restrictions, static filtering, timing and original-partner exclusions, strictly prior histories, checkpoint reuse, and shared-account/date IV covariance against explicit calculations.

Eight follow-up checks cover:

1. Log-domain objective/gradient parity with the original four families, central finite differences with account weights, and exact original-bound reproduction.
2. Extreme-logit likelihoods against exhaustive state-path sums; finite gradients and exact scores below -700 without probability flooring.
3. Receipt entry/staying decomposition against the original receipt-input forecast contrast; no current/future leakage and invariant first-year posteriors.
4. Grant-frequency calibration, seeded reproducibility, simulation expectations and persistent type drawn once per account.
5. Recipient-as-chooser versus recipient-as-disconnected counts, strict future timing, exclusions, zero follow-up and draw counts.
6. Both colors in chronology, timeout versus outoftime, and exclusion of incomplete monthly follow-up windows.
7. Checkpoint tamper detection, budget/worker-independent run identity, and rejection of private identifier columns in exported tables.
8. Actual Parquet I/O through chronology and API source bridges, resumed source parts, API alias-conflict detection and coverage handling.

The synthetic integration run uses 240 fabricated accounts, selects disjoint 100-account development/evaluation groups, and runs all four families at widths 7 and 12 with two worker processes. It completes two refit bootstrap replications, all four recovery scenarios with three competing families, score and parameter reports, checkpoint receipts and aggregate ZIP assembly. Iterations are deliberately capped at 25: nonconvergence is expected in this software fixture and is reported rather than concealed. No confidence intervals are emitted below 100 converged refits.

Shell syntax, Python compilation and CLI help were also checked. The returned v1.0.0 evidence archive and copied-code provenance are checksum-verified during packaging.

These checks validate software behavior on fixtures. The 120-refit / 20-replication-per-scenario production run and large source scans require the user's external drive and have not run here. The launcher repeats offline checks and requires original numerical reproduction on the real histories before accepting follow-up estimates.
