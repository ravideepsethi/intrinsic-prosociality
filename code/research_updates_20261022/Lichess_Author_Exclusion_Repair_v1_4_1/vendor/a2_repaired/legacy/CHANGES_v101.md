# v1.0.1 — preparation SQL repair

- Fix the DuckDB parser failure caused by the unquoted `names` alias.
- Quote the `month` projection alias, fixing a second failure in the next query.
- Obtain census totals from the already authenticated bundled authority; the authenticated production authority still requires exactly 3,224,173 choosers, 41,534,331 rows and 570,091 grants.
- Add an integration test that executes account aggregation, fixed sample selection, all 24 monthly projections, trajectory target preparation, and a second invocation that verifies checkpoint reuse.
- Preserve the data, sample seed, sample sizes, analysis specifications, profile semantics, engine settings and source authentication.
- Reuse the existing installed Python environment; keep v1.0.0 and its failed-run output intact. The corrected code receives a new run identity. Input verification is repeated; no API requests or Stockfish computation had begun at the reported failure.

Eight tests pass on DuckDB 1.5.5. Tests use synthetic data. This does not certify results on the user’s private dataset or benchmark its runtime.

The `v100` directory/report naming remains compatible; the version recorded by the executable code and new run identity is 1.0.1.
