# Validation receipt

September 26, 2026. Validation used synthetic rows and the already returned aggregate result files. No XT_Pro production data or new empirical estimates were run in this environment.

- Eight focused unit tests passed: exact conditional probabilities against enumeration; regularity/RD restrictions and fold chronology; cache authentication and tamper detection; conditional scoring and RD score partition identities; failed-fit handling on common support; no selection with zero informative validation groups; boundary labels and unchanged duplicate-curve values; correction of all four old grant-count tables without changing estimates.
- A full synthetic primary-state audit passed on 6,480 generated opportunities, 6,120 eligible rows. It fitted all seven original candidates and all seven capped candidates, with two forward folds each, then ran the six unrestricted-sign diagnostics for that state. All fits converged. It produced 252 model × validation-month × comparison score cells with informative repeated chooser-month groups and nonzero conditional likelihoods.
- The end-to-end exercise used the production preparation, two-worker spawned model process pool, common-test scoring, reporting, archive creation and restart paths. Only the pinned external reference and package identity were replaced with synthetic fixtures; the production source-result pin remains unchanged in the delivered package.
- A second invocation reused every completed fit. Source file hashes remained identical. Both result ZIPs passed CRC and sidecar-hash checks; exported fit JSONs contained no switcher-ID arrays.
- The generated common-index figure and the repaired prior M2 figure were visually inspected. Coincident curves share a legend entry; numerical values are not offset.
- The synthetic exercise including restart took 15.08 seconds on this environment. This is not a production runtime estimate. The full losing-state workload and production-scale memory use have not been benchmarked here.
- Python syntax, shell syntax, the package manifest, and every archive-member checksum are checked before delivery.

Local validation environment: Python 3.12; NumPy 2.3.5; pandas 2.2.3; SciPy 1.17.0; Numba 0.67.0; DuckDB 1.5.5; PyArrow 25.0.1; Matplotlib 3.10.8. The launcher reuses a compatible installed environment and records its actual versions in the returned report.

To repeat the short validation suite:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

To repeat the generated end-to-end exercise separately:

```bash
python3 tests/synthetic_audit.py
```

The launcher runs only the short suite. It does not add the synthetic exercise to the production workload.
