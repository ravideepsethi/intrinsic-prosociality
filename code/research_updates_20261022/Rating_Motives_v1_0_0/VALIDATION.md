# Release validation

Status: PASSED on synthetic fixtures, 23 September 2026. No private Lichess empirical estimates were run.

Checks exercised:

- Dense explicit-dummy regression versus streamed chooser-FE point estimates and full-rank CR1.
- Chooser/recipient/pair cluster score aggregation and joint state coefficient reproduction.
- Aliased targets, complete-cluster streaming, exact-zero controls and nine-/nineteen-term polynomial bases.
- Strict completion cutoffs, future leakage, completion ties, RD/status eligibility and all-win/all-loss regularized performance fits.
- Profile linkage/deduplication and missing-history preservation.
- Every monthly projection query and rejection of a tiny synthetic frame at the immutable census-count gate.
- Enriched-history construction, observed peaks, left-truncation flags and row-count-preserving feature joins.
- A nonempty predictive-validation regression and all 91 registered full-history state/specification models.
- The 27 available-file models, report tables/figures, multiprocessing and identical resumed estimates.
- Python compilation and Bash launcher syntax.
- Production-entry-point rejection of missing certified sources and aggregate-only failure-report export.

The certified source receipt ZIP and frozen specification hashes were also verified. Production source checks and sample/support gates still run on the data-owning Mac.

Tested dependency versions:

- python: 3.12.14
- numpy: 2.3.5
- scipy: 1.17.0
- pyarrow: 25.0.1
- duckdb: 1.5.5
- matplotlib: 3.10.8
