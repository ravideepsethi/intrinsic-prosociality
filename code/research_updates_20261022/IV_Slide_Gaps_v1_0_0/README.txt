IV Slide Gaps v1.0.0

Run RUN_SLIDE_GAPS.command from Terminal. It uses the frozen historical cohort
on XT_Pro and, if present, the completed author-clean Run 3 cache.

Produces:
  outcome_levels.csv: all, claim recipients, and grant recipients; Y, R, Y|R.
  score_distribution.csv: zero-grant shares; p10/p50/p90; explicit populations.
  score_histogram.csv plus PNG/SVG histograms (when Matplotlib is available).
  first_stage_bands.csv plus PNG/SVG charts; raw and adjusted score-band means.
  first_stage_model.json: reproduction check, exact design and linearity test.
  profile_audit.csv/json: whether retained caches contain country/flag fields.
  run2_status_snapshot.json: local receipts and recognized live processes.
  READ_RESULTS.txt: plain-English result summary and limitations.

The aggregate report is zipped into ~/Desktop/Lichess_Desktop and its full path
is printed after success. Return IV_SLIDE_GAPS_REPORT_*.zip for interpretation.
It contains no row-level data, usernames, profile values or private input paths.

Mac launch:
  /bin/bash /path/to/IV_Slide_Gaps_v1_0_0/RUN_SLIDE_GAPS.command

Python selection checks IV_PYTHON, the existing project venv, active Conda,
common Conda locations, and python/python3 on PATH. It prefers a Python with
NumPy, PyArrow, DuckDB and Matplotlib. Without Matplotlib, all tables and tests
still run and the report explicitly marks plots unavailable. No packages are
installed automatically. Python 3.10+ is required; SciPy is not required.

Overrides:
  IV_PYTHON=/absolute/path/to/python /bin/bash RUN_SLIDE_GAPS.command
  IV_PROJECT_ROOT=/path/to/lichess_kindness /bin/bash RUN_SLIDE_GAPS.command
  IV_DESKTOP=/path/to/output /bin/bash RUN_SLIDE_GAPS.command
  /bin/bash RUN_SLIDE_GAPS.command --bands 5
  /bin/bash RUN_SLIDE_GAPS.command --headline-only
  /bin/bash RUN_SLIDE_GAPS.command --profile-path /path/to/profile_snapshot.parquet

Offline validation only:
  /bin/bash RUN_TESTS.command

Resource use: one cohort at a time, BLAS restricted to one thread. Plan for
several GB of RAM. The source cohort is about 295 MB. The default real-data run
is roughly 5–20 minutes as an UNBENCHMARKED planning estimate, plus external
drive access. Completed cohort diagnostics are hash-bound and reused; profile
and status scans are refreshed. A 45-second heartbeat is printed during fits.

The run never calls Lichess, reconstructs histories, changes old outputs,
starts/stops Run 2, or reestimates the headline IV. It writes only a new
iv_slide_gaps_v100_PRIVATE tree and a new aggregate report/log on the Desktop.
Read METHODS.txt for definitions, particularly opponent weighting and the
distinction between a functional-form diagnostic and IV identification.
