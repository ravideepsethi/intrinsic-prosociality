# Software validation

Validated on 20 September 2026 in a Linux container with Python 3.12.14,
NumPy 2.3.5, SciPy 1.16.3, pandas 2.3.3, PyArrow 24.0.0, DuckDB 1.5.2,
and Numba 0.67.0. The Mac shell scripts were syntax checked; macOS itself
was not available for execution.

## Independent numerical checks: 10 passed

- The HMM likelihood agrees with exhaustive enumeration of state paths and
  account-level persistent types.
- Analytic gradients for all seven model families agree with central finite
  differences, including nonuniform account weights.
- Sequential forecasts sum to the joint sequence likelihood; later outcomes
  cannot alter earlier forecasts or first-year posteriors.
- Static models update account beliefs correctly and reproduce their joint
  likelihoods.
- Gate and willingness parameters embed exactly into the unrestricted model.
- Receipt-input contrasts reproduce the forecast for the observed input and
  do not use the current or later outcome.
- Shared-account OR date covariance agrees with an explicit pairwise
  dependency calculation.
- Follow-up construction excludes the original giver, games beginning before
  exposure, and events beyond the horizon; complete nonreachers retain zero
  event counts.
- Receipt-history construction uses strict prior timestamps, excludes events
  at exposure-game start, reproduces the toy outcome bridge, and resumes from
  certified cache files.
- IV coefficients, standard errors, and influence scores agree with an
  independent explicit dummy-variable fixed-effect projection on 3,000
  artificial exposures.

## Synthetic integration run: passed

The fixture contains 600 artificial accounts across 24 months, with 250
development and 250 evaluation accounts. It exercises preparation, cache
reuse, timing exclusions, chronological validation, all seven model families,
two separate fitting processes using the spawn method, held-out scoring,
one bootstrap refit, the three recovery scenarios, the ply-2 fixed-effect
interaction, all four Patron prediction fits, and aggregate report packaging.

A game archived in October but recorded in November verifies that later
giving does not enter the first-year prior-grant classification. A separate
test verifies the reviewed-IV extension's strict history join.

The synthetic integration run caps optimisation at 25 iterations to exercise
the workflow and the reporting of nonconvergence. It is **not** evidence of
statistical identification, production convergence, adequate empirical power,
or support for the construal mechanism. The production default permits 600
iterations per fit and reports convergence and numerical bounds explicitly.

The embedded main-sample authority and report fingerprint were verified.
Package extraction, file checksums, Python syntax, shell syntax, and the
extracted package's offline tests were also checked before delivery.

## What has not been run here

The private 41,534,331-row production panel and reviewed IV/profile inputs are
on the user's Mac/XT_Pro drive. Production fits, source-file authentication,
runtime and memory use at that scale, and reproduction of the reviewed real
IV coefficient remain to be checked by the supplied launcher. This package
contains no new real-data findings. It refuses to publish receipt extensions
if the reviewed outcome, coefficient, or covariance bridge fails.
