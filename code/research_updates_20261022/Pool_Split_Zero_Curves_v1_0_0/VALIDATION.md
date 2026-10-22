# Validation performed before delivery

All checks used synthetic observations or bundled aggregate evidence. No new
empirical results have been estimated on the user's private production data.

Passed:

1. Exact-zero atom and signed-bin endpoints, including arbitrarily small
   representable nonzero values and the closed finite endpoint at +6.
2. Adjusted coefficients and chooser-clustered covariance against independent
   dense OLS with the full chooser × board-state dummy matrix.
3. Raw means and their covariance against a separate dummy-regression
   calculation; near-zero contrasts use cross-bin covariance.
4. Streaming record boundaries and worker-shard aggregation preserve complete
   chooser histories, sample counts, moments and singleton handling.
5. The prior sample-count JSON array is loaded correctly; all expected totals
   and board-state counts match the bundled prior evidence.
6. Two-process integration through moments, score accumulation, tables and all
   four figure variants. Restart reuses authenticated checkpoints and produces
   byte-identical curve and contrast CSVs.
7. Frozen sample-report archive authentication: 41,534,331 opportunities in
   24 monthly files. This checks the bundled authority; the production command
   must still authenticate the actual monthly files on the mounted volume.
8. Prior rating-gap replication comparison path and shell syntax.
9. Visual inspection of the synthetic central figure for labels, spacing,
   reference marker, separate signed lines and confidence bands.

The production runner additionally requires exact prior sample counts,
conservation of the old central bin's observations and grants, sufficient
support for the three new central bins, and replication of unchanged
rating-gap estimates and standard errors within 0.00002 percentage points.

Local test environment: Python 3.12; NumPy 2.3.5; SciPy 1.17.0; PyArrow 25.0.1;
DuckDB 1.5.5; Matplotlib 3.10.8. Requirements retain the previous runner's
compatible version bounds.
