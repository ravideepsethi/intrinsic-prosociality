# Validation performed before delivery

- Exact K=4 and K=5 embeddings preserve every account's K=3 level-only likelihood
  and the penalized objective, for each of the three possible split components.
- Parameter-count arithmetic, regional score conservation, grant/non-grant score
  decomposition, and account-cluster standard errors pass independent checks in
  `self_test.py`.
- The complete new driver ran on the existing synthetic v100 integration fixture
  (2,400 accounts and 172,800 original fixture rows). A separate scratch copy of
  this package was bound to that synthetic parent; the production authority file
  was not changed. Both parent models' regional and overall forecasts reproduced.
  Three starts each of K=4 and K=5 converged; report packaging and all diagnostics
  completed. A second invocation verified and repackaged the completed run.
- Altering the synthetic cached-data receipt's checksum caused authentication to
  refuse the input. The original synthetic receipt was restored afterward.
- The Mac launcher passes shell syntax validation. Production source modules are
  byte-identical to v100. Archive and package manifests are checked before delivery.

These are software and numerical checks. They do not establish identification,
real-data convergence, statistical test size, or the substantive outcome of the
K=4/K=5 challenge. The real pilot cache exists on the user's Mac and has not been
run through this follow-up here. No real-data result is inferred from the synthetic
fixture. Real-data runtime is not benchmarked.
