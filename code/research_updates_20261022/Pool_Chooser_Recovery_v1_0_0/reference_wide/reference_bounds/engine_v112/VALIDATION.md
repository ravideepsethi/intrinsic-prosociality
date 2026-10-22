# Software validation for v1.1.2

These checks use synthetic observations. No new production fit or empirical
finding has been computed here; the XT_Pro private data are needed for that.

## Numerical equivalence

All 22 tests in the unchanged benchmark and all 19 follow-up tests pass.
The latter include:

- Every static specification's compiled objective and gradient against the
  archived implementation, at one and three types, weighted and unweighted.
- Extreme utilities, signed costs and zero account weights; skipping zero-weight
  accounts agrees with physically omitting those accounts and retaining weights.
- Read-only memory-map values and derivatives, source/output checksums and
  detection of a corrupted numeric cache.
- Parquet round trips, removal of stale output for an empty table, and worker caps.
- All earlier switching gradients, exact nested embeddings, sequential likelihood
  equality, no future-outcome leakage, simulation reproducibility, index anchors,
  manifest validation and full-year feasible-start checks.

The larger synthetic objective comparisons use 240,000 opportunities and six
types. Maximum discrepancies at identical parameter vectors are approximately
1.6e-13 for objective values and 1.7e-14 for derivatives. The two full-fit timing
comparisons both converge, with final objective differences below 2.2e-9.
See `PERFORMANCE.md` and `SYNTHETIC_SPEED.json` for timings and their limits.

## Pipeline, multiprocessing and restart

A complete synthetic parent with 160 development and 160 evaluation accounts
and 36 opportunities per account was authenticated, with archived public scores
reproduced. Its original producer and cache files remain unchanged.

The repair, new index restrictions, switching and perception suites all run
under explicit macOS-compatible `spawn` multiprocessing with two workers and
shared read-only arrays. New complexity checks use J=1, ridge=.001, two starts
and maxiter=800; inherited static selections include J=2. This is a software
integration check, not a recovery assessment at production scale.

The four suites pass all 120 full-year feasible-start comparisons: 31 repair,
39 challenge, 38 switching and 12 perception. Each suite completes two paired
bootstrap draws and one recovery replication per generating scenario (7, 7, 5
and 4 scenarios respectively), with no failed refits/recovery fits. Numerical
boundary flags remain visible, and no percentile intervals appear below 100
successful paired draws.

Restarting each suite reuses its cached fits and draws without changing their
bytes or modification times. Rewriting SELECTED_FITS preserves its bytes.
Increasing the repair bootstrap budget adds exactly the requested new draw,
without changing earlier draws. The incremental check was repeated.

All 60 Parquet companion tables in the integration reports agree with their
CSV companions after accounting for CSV's loss of the empty-string/null
distinction. Parquet retains the original typed values. The launcher passes
Bash syntax validation. The release archive's manifest and unchanged base
producer are checked after extraction; the extracted numerical tests and
small command-line repair/bootstrap check are also run.

Worker count planning is a conservative CPU/RAM calculation, not a benchmark
proving an optimal count. Production elapsed time, memory pressure and model
discrimination still need assessment from the user's actual run.
