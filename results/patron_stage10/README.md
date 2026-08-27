# Patron Stage 10 aggregate results

These directories contain public aggregate outputs only.

- `primary_v1_0_1/`: certified current-Patron matched analysis, rematching,
  dose, diagnostic-kindness, price-side, and opportunity-level results.
- `postcertification_addendum_v1_0_0/`: separately certified corrected-date,
  simultaneous five-state, and continuous price count/rate sensitivities.

The v1.0.1 transfer used three non-strict JSON `NaN` placeholders for absent
metadata. The publication copy deterministically changes only those tokens to
strict JSON `null`. `report_file_hashes.tsv` authenticates the publication
copy; `report_file_hashes_CERTIFIED_ORIGINAL.tsv` retains the original
certified manifest. See
`docs/patron_stage10/STRICT_JSON_PUBLICATION_CORRECTION.md`.

No username, row-level profile record, raw profile JSON, Parquet file, or
private cache is included. Current Patron status is cross-sectional; the
analysis does not identify Patron adoption timing or causality.

