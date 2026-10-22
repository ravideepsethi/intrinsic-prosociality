# Software validation — not empirical evidence

Validated in Linux/Python 3.12 with NumPy 2.3.5, SciPy 1.17.0,
pandas 2.2.3, PyArrow 21.0.0, DuckDB 1.5.2 and Numba 0.67.0.
The Mac launcher checks supported dependencies and runs the same tests locally.
The production XT_Pro drive was not available here. No real-data fit, scientific
recovery claim, runtime estimate or paper result is reported by this document.

## Unit and numerical checks

All 22 deterministic tests passed. They cover:

- Analytic gradients against finite differences for every main, calibrated and
  perception family, including account-weighted likelihoods and one-type models.
- Exact normal-bin weights, derivatives, tail stability and zero-noise nesting.
- Two-anchor normalization and probability-preserving nested-model transfers.
- Sequential predictive likelihood equal to the joint account likelihood.
- A changed future outcome cannot change an earlier or current forecast.
- Early-development-only support/scaling; no later-rating borrowing when an
  account's first recorded rating is missing.
- Cost normalization, zero-cost nonidentification and numerical bound expansion.
- Stable extreme log probabilities, Jensen decomposition and persistent simulated
  types, rather than a fresh type draw at every opportunity.
- Projected-gradient convergence, cache-signature rejection and the full DuckDB
  source adapter/payoff reconstruction on a synthetic source-shaped panel.

## End-to-end exercise

A 160-development / 160-evaluation-account synthetic panel, each with 36
opportunities, was run through all seven stages with two worker processes:
audit, main fits, recovery, bootstrap, perception fits, perception recovery,
and perception bootstrap. The grid used one and two support points, ridge .001,
two starts, and an 800-iteration per-pass limit. The numerical parameterization
was revised after this exercise exposed avoidable optimizer stalls; all reported
accepted fits now require the projected-gradient check.

The integration exercise used only one replication per recovery scenario and
two bootstrap refits per family. These are software checks, not scientifically
adequate simulation budgets. Both bootstrap reports correctly withheld intervals
below 100 successful paired refits. Numerical bound hits remained visible.
There were no failed recovery or bootstrap fits in this synthetic exercise.

The default production commands use 25,000 development accounts, 50,000
evaluation accounts, full observed histories, twenty recovery replications per
scenario and 120 bootstrap refits. Those computations must be run on the Mac.
Twenty recovery replications are an initial diagnostic, not a universal adequacy
criterion; increase the budget if model-confusion estimates remain imprecise.

## Required review before a substantive claim

Read retained support, grants, gradients, boundary hits, failure rates and recovery
errors before interpreting scores. Conditional account-cluster SEs do not replace
the population-refit bootstrap. That bootstrap freezes specification complexity,
common support and transformations; it does not correct prior specification
search or validate perception exclusions. A successful process exit only means
the requested computations completed.
