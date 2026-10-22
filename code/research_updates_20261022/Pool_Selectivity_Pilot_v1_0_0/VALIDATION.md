# Validation completed before delivery

These are synthetic software checks, not results from the user's Lichess panel.

- The bundled sample report matched its SHA-256 and internal manifest; its main-sample fingerprint and 41,534,331-row authority were recovered. The authentication helper is byte-identical to the previously delivered helper.
- Analytic gradients agreed with central numerical differences to better than 1e-6 for both model specifications.
- Account-level marginal likelihood agreed with an explicit loop that integrates type once per account.
- The two models have identical likelihoods when component slopes are equal.
- Modifying all held-out outcomes left predicted probabilities and first-year posteriors unchanged, while changing scores.
- Checkpoints rejected both a changed configuration and changed bytes.
- Smoothed benchmark produced finite strictly interior probabilities for zero histories and missing account-cell histories.
- End-to-end fixtures included 2,400 synthetic accounts, 172,800 observations over 24 months, source audits, census aggregation, capped sampling, nuisance encoding, two optimizer starts per model, holdout prediction, report packaging, and checkpoint reuse. Count conservation was checked for the full census and selected pilot.
- In the heterogeneous-slope fixture, the opportunity-weighted held-out log-score gain over the level-only model was +0.001126 per opportunity (conditional account-clustered SE 0.000225). One level-only fitted component had very small weight and was flagged.
- In the common-slope fixture, that gain was -0.00002452 (SE 0.00003115). The joint-sequence gain was also close to zero. This is a single null fixture, not a Monte Carlo size study.
- All optimizer attempts in those fixtures converged; no fitted parameter hit a numerical bound. Both fixtures passed the complete execution path used by the pilot after source authentication.
- Python compilation and shell syntax checks passed.

Tested environment: Python 3.12.14 runtime; NumPy 2.3.5, SciPy 1.16.3, DuckDB 1.5.2, PyArrow 24.0.0. Actual production dependency versions are recorded separately at run time. The source Parquets reside on the user's Mac and were not available in this workspace; no real-data estimate or runtime is claimed.

To rerun the quick unit checks with a compatible Python:

    python self_test.py

To rerun either full synthetic fixture (temporary output directory printed at completion):

    OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python validation_fixture.py --scenario heterogeneous
    OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python validation_fixture.py --scenario level-only

Both fixtures use fixed random seeds. Small numerical differences across library versions may occur.
