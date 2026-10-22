# Validation record

Completed September 26, 2026 UTC. Ten tests passed, including a complete synthetic 27-month run followed by a resumed run using multiprocessing with the macOS-style spawn start method. Test suite elapsed time: 4.553 seconds on small synthetic inputs; this is not a production runtime benchmark.

Environment: Python 3.12.14, DuckDB 1.5.2, PyArrow 24.0.0, NumPy 2.3.5, Pandas 2.2.3.

Validated exact timestamp boundaries; month preparation and unchanged-file restart reuse; rejection of duplicate auxiliary game IDs and altered cached outputs; realized prediction parity; separation of missing observed rating changes; pre-only pool membership; competitive/returning calibration summaries; singular-control fixed-effect projection against direct dense least squares; pre-period power under simulated serial dependence; Arrow microsecond timestamp handling; twelve complete placebo dates; API/candidate key and result reconciliation; observed versus missing clock frames; kindness versus other draws; withheld incomplete seven-day contrasts; report bundling and completion-status semantics.

The launcher passes bash syntax checking. Package files are covered by PACKAGE_MANIFEST.sha256. Tests can be rerun with the existing project interpreter:

```bash
/Volumes/XT_Pro/lichess_kindness/venv/bin/python -m unittest discover -s tests -v
```

Expected test runtime: 10–30 seconds on the laptop. Production estimate: 30–90 minutes with 10 workers; completed restart: 5–15 minutes. The actual project drive was unavailable here, so the new real-data output remains to be reviewed after the run.
