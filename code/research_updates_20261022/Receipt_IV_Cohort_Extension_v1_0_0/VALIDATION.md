# Validation

Validated in the development workspace on September 26, 2026 with Python 3.12.14, DuckDB 1.5.2, PyArrow 24.0.0 and NumPy 2.3.5. The reviewed Mac runtime used Python 3.13.9 with the same DuckDB and PyArrow versions. The production data are on the user's Mac and were not executed here.

Thirteen package tests and eighteen tests from the original source-recovery and adjacency producers passed. Tests cover actual compressed/archive reading, malformed and truncated input, changed input/output detection, checkpoint reuse, source conflicts, missing labels, exact versus second-level timestamp checks, omitted native API winners, and source-target outcome consistency.

The new tests compare compact chronology with a full event stream across multiple months and speed-file segments, including tied starts. They exercise real file projection, user-side construction, exact November-status bridge comparison and rejection of a changed status. An integrated fixture assembles membership and instrument-support products and verifies that missing-source and mutually adjacent games do not enter the known main sample. Score checks exercise strict cutoff exclusion, removal of the focal pair, both lags and the five/ten common support rule. The original numerical scoring and adjacency SQL modules are unchanged.

The launcher passes Bash syntax validation. All Python files parse. The release is checksummed; the runtime verifies package files before reading project data. The return writer uses an explicit allowlist, so private row-level outputs are not added to the result ZIP.

These are implementation tests, not production-data validation or econometric identification. The actual run must pass the complete 2,015,809-row November 2023 adjacency bridge. Coverage, runtime, disk footprint, instrument support and unresolved source counts remain unknown until the Mac run returns. No new IV estimate, power claim or censor date is certified.
