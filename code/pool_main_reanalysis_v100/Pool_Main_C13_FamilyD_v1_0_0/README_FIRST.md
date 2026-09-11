# Pool-main C13 and family D, v1.0.0

Save the ZIP and sidecar to `~/Desktop/Lichess_Desktop`. Paste
`RUN_COMMAND.txt` into Terminal. The existing Wave 1 Python environment is
used; nothing is installed.

**Expected runtime: 4–8 hours for C13**, excluding any wait for an active
C9, C9-ply or Patron job. The historical C13 run took about 4.7 hours.
The primary and adjusted-quartile models run first. All 19 planned model
attempts are retained, and each completed attempt is checkpointed.

The family-D report is a reconciliation of the available new-sample evidence.
C6 and C9 have valid current inputs. C1/C2/C5 are missing from the bound
new-sample reports; all five slots are retained and conservative Holm bounds
are reported. This is not falsely labeled a complete exact family closure.
See `ANALYSIS_SCOPE.md` for the precise estimands and missing-slot treatment.

Upload the Desktop files beginning `POOL_MAIN_C13_FAMILYD_RESULTS_`:
the result ZIP and its `.zip.sha256` sidecar. If the job stops, keep the log
and any `PARTIAL` archive. Repeat the same command to resume.

For **family reconciliation only**, append `--holm-only` to the launcher;
expected runtime is under one minute. This mode does not start C13.

Optional environment overrides:

- `POOL_MAIN_PROJECT`: project root (default `/Volumes/XT_Pro/lichess_kindness`).
- `POOL_MAIN_TRANSFER`: Desktop transfer folder.
- `POOL_MAIN_PYTHON`: previously used compatible Python.
- `POOL_MAIN_C13_THREADS`: 1–10 threads, default 10.
- `POOL_MAIN_C13_MEMORY`: DuckDB memory setting, default `8GB`.

Estimation is sequential. The DuckDB memory setting does not impose a hard
limit on the original NumPy estimator's memory use. Thread/memory changes
do not change the scientific specification and allow checkpoint reuse.
