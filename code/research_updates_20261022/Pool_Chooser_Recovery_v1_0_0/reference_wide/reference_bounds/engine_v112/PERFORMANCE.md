# Performance changes and ETA

The v1.1.1 run already consumed an authenticated numeric cache derived from
Parquet and already parallelized independent bootstrap replications. Converting
that cache back to Parquet would not accelerate thousands of optimizer steps.
The main improvement here is the repeated computation, with storage and worker
setup improved alongside it.

- **Numeric input:** decode each certified NPZ once into uncompressed `.npy`
  files in `PRIVATE/<suite>/design/MAPPED/`. Spawned workers open them read only
  and share the operating system's page cache. Shapes, dtypes, source hashes
  and output hashes are checked. Subsets are cached once per worker and stage.
- **Parquet output:** follow-up aggregate tables get ZSTD-compressed Parquet
  companions with 65,536-row groups. Small CSV companions preserve compatibility.
  No private opportunity or account file is exported. The source Parquet pipeline
  and archived base producer remain unchanged.
- **Computation:** a Numba loop evaluates the same account-mixture log likelihood
  and analytic gradient while avoiding multiple opportunity-by-type temporaries.
  An account with bootstrap weight zero is skipped exactly. The original model
  remains the reference; perception and Markov likelihoods retain their existing
  implementations. No fast-math, reduced precision, likelihood approximation,
  fewer starts or smaller sample is used.
- **Processes:** one persistent process pool per suite, explicit macOS-compatible
  `spawn`, bounded submission queue, one numerical thread per process. Completed
  caches are validated without dispatch and excluded from live rate estimates.
  `--workers auto` caps at ten and reduces that cap when RAM is limited. It cannot
  anticipate thermal throttling or all competing CPU use; `--workers 4` is a useful
  cap while another large job runs.
- **ETA:** print counts every 30 seconds while awaiting a task. Initial bootstrap
  estimates use fitted-model timings and are deliberately broad. Completed tasks
  then supply the rate. Late difficult fits can make an early estimate optimistic.

## Measurements made here

These are synthetic software measurements in this execution environment,
not timings observed on the user's Mac or estimates from the chess data.
`benchmark_speed.py --full-fits` reproduces the design and comparison.

| Comparison | Reference | Compiled | Speed ratio |
|---|---:|---:|---:|
| Desert objective, 240,000 opportunities, 6 types, bootstrap weights | 0.119 s | 0.020 s | 6.0× |
| Both objective, same size and weights | 0.114 s | 0.021 s | 5.5× |
| Type-cell objective, same size and weights | 0.111 s | 0.020 s | 5.5× |
| Desert full fit, 24,000 opportunities, 3 types, bootstrap weights | 0.670 s | 0.155 s | 4.3× |
| Both full fit, same size and weights | 1.467 s | 0.314 s | 4.7× |

Unweighted objective speed ratios were 3.7–4.0×. Earlier runs of the same
comparison gave full-fit ratios of 3.3–3.7×, illustrating timing variability.
Compilation is excluded from
the timed comparisons. Objective differences at identical parameter vectors
were at most 1.6e-13 and gradient differences at most 1.7e-14 in these larger
checks. Both full-fit comparisons converged; final objective differences were
2.4e-14 and 2.2e-9. Floating-point accumulation order can change an optimizer
path in a mixture model; new cache/run identities keep this release distinct.

## Planning the production run

The earlier estimate of 25–40 hours with four workers used the actual archived
Mac fitting times and roughly 47 fits per replication across 120 replications.
Combining those times with the synthetic improvement, with allowance for
overhead and harder starts, suggests **8–14 hours at four workers**, or
**4–8 hours at eight to ten workers** when CPU and memory are available.
The repair stage should usually take minutes rather than hours. These are
planning ranges; observed completed replications take precedence. The same speed
ratio is not claimed for perception or switching, whose core likelihoods were
not rewritten. Their logs estimate time from their own completed tasks.

Changing worker count or increasing simulation budgets within v1.1.2 preserves
the run identity and reuses completed v1.1.2 fits/draws. This release does not
consume partial v1.1.1 fits. Keep that run if it is already well advanced.
