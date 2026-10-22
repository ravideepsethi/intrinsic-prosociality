# Validation performed before delivery

2026-09-16. These are synthetic software/numerical checks, not empirical Lichess results.

- Verified the bundled original main-sample report, its member hashes, the report checksum and the fixed 41,534,331/15,207,423 source/competitive counts.
- Checked loss/gain crossing definitions, equality at thresholds, zero/near-zero changes, explicit half-up rounding, and Holm arithmetic against hand-worked expectations.
- Compared exact streaming within-chooser coefficients and cluster score covariance with an independent dense regression using explicit chooser dummies, on a 2,800-row synthetic panel. Agreement: coefficient tolerance 2e-7; uncorrected cluster covariance tolerance 1e-8.
- Recovered a known synthetic linear signal of -0.025 and -0.015 on the loss/gain indicators to tolerance 1e-8. These planted numbers are only a unit test.
- Confirmed constant and collinear treatment directions are flagged as unidentified.
- Exercised the actual SQL source audit, competitive staging, clock-missingness logic, raw aggregate outputs, complete-chooser block streaming and chooser partitioning on a 2,400-row, 24-month synthetic fixture.
- Confirmed a deliberately corrupted checkpoint is rejected and unchanged caches are reused.
- Compared moment matrices under different block boundaries; complete chooser clusters are preserved.
- Ran the full estimation/reporting path on 30,000 synthetic rows with two spawned worker processes: 13 specifications and 84 coefficient/bin attempts, including the fixed 72-test secondary family. Generated and visually inspected the proximity figure.
- Re-ran moments and covariance through checkpoint recovery and obtained identical result records.

Development environment: Python 3.12.14; NumPy 2.3.5; SciPy 1.17.0; DuckDB 1.5.5; PyArrow 25.0.1. Exact environment information is written by each production run. The actual Mac filesystem and source Parquets are not accessible in this session. The production launcher therefore performs full source authentication and validation before estimating anything.
