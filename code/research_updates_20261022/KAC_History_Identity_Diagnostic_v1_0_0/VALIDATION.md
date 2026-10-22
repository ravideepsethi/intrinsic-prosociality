# Validation scope

The bundled self-test uses synthetic Parquets to check:

- absent game keys separately from same-key/wrong-player records;
- timestamp and speed mismatches, duplicates, and the original left-join tuple;
- an ordinal-only mismatch not being silently promoted to an original gate;
- a blank-key candidate with matching players/time/ordinal, left unrepaired;
- exact-key matches in a neighboring archive month;
- producer-declared numeric input lookup;
- source-byte preservation, cached diagnostics, and damaged-checkpoint rejection;
- exclusion of literal game identifiers and raw source fields from exported ZIPs;
- the spawned-process execution path used on macOS.

These tests validate the diagnostic implementation, not the three actual
production records. Their cause requires this diagnostic's production output.
No scientific result or sample amendment is introduced by this package.

Validation performed 2026-09-29: all bundled synthetic checks passed under
Python 3.12, DuckDB 1.5.6, and PyArrow 25.0.1. The shell launcher passed
`bash -n`. The August certified-schema columns were checked against the bundled
main-sample authority: the month contains 1,674,961 focal rows. The 15 remaining
analysis months contain 26,073,431 focal rows. Checkpoint receipt and source
lineage checks were also exercised with synthetic files.
