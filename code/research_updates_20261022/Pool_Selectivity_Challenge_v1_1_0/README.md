# Pool Selectivity Challenge v1.1.0

This is the next exploratory specification check for the returned pilot run
`5de7829248590795`. It reuses the private cached histories on your Mac.

## Question

Does the three-component selectivity model still predict better when the
generosity-only model has a more flexible distribution of player intercepts?

| Model | Person-level and mixing parameters | Common controls |
|---|---:|---|
| Original level-only, K=3 | 6 | Same 89 coefficients |
| Original selectivity, K=3 | 8 | Same 89 coefficients |
| New level-only, K=4 | 8 | Same 89 coefficients |
| New level-only, K=5 | 10 | Same 89 coefficients |

For level-only K components there are K intercepts, one common competitive-state
slope, and K−1 mixing weights. For selectivity K=3 there are three intercepts,
three slopes, and two mixing weights. All models separately estimate their
common coefficients using the same training design and penalty. Equal parameter
counts do not imply equal functional flexibility; this is a useful challenge,
not a formal dimensionality test.

## Run

Put the ZIP and its SHA-256 sidecar in `~/Desktop/Lichess_Desktop` and use the
complete command in `RUN_TERMINAL.txt`. The launcher defaults to two workers
and one numerical thread per worker, and reuses the original Python environment.
The drive must be mounted. It expects:

`/Volumes/XT_Pro/lichess_kindness/output/pool_selectivity_pilot_v100_5de7829248590795/`

The launcher checks the code bundle. The analysis checks the exact completed
parent report, its configuration identity, and the cached pilot data receipt and
checksum. It reproduces the two original models' forecasts before fitting anything.
The 41.5 million source rows are not rescanned or rehashed in this follow-up.
No APIs or engine evaluations are involved. The source panel and parent run are
read-only. Dependencies can be installed if the prior environment is unavailable.

New outputs are under `output/pool_selectivity_challenge_v110_<run_id>/` on the
external drive. Only the aggregate report ZIP and its sidecar are copied to
`~/Desktop/Lichess_Desktop`. Upload those two files. Account data and fit caches
stay in the private output directory. Completed optimizer starts are resumable;
an interrupted optimizer start restarts. Repeating a complete run verifies and
repackages its report. Worker count can change without invalidating checkpoints.

Runtime on the real pilot is not benchmarked. There are eight new fits by default
(four starts each for K=4 and K=5), with at most 900 iterations per fit. This avoids
the full-sample authentication/census stage. The numerical stopping rules are
slightly tighter than v100; the two original models remain frozen.

## Read the result

1. `parent_reproduction.csv`: exact frozen-forecast reproduction to tolerance 1e−9.
2. `optimizer_attempts.csv` and `_SUCCESS.json`: convergence, local solutions,
   tiny classes, boundaries, and failures to improve the nested original model.
3. `parameter_counts.csv`: confirms the equal-parameter comparison.
4. `paired_gains.csv`: positive means K=3 selectivity forecasts better; focus first
   on subgroup `all`, regions `all`, `competitive`, and `clearly_worse`.
5. `heldout_scores.csv`: calibration means, log loss, and Brier score by region
   and first-year history subgroup, including grants observed only in competitive
   states, only in clearly-worse states, or in both.
6. `joint_history_gains.csv`: integrates a fixed type over the entire next-year history.
7. `posterior_diagnostics.csv`: descriptive concentration of first-year membership
   probabilities. Concentration can be caused by a dominant prior class and is
   not evidence that individual preferences are precisely measured.

The new models initialize from exact embeddings of the original level-only
model by splitting component mass, then perturb the starts to break duplicate
components. Four starts split different components and use different perturbation
scales. Restarts are selected by the first-year objective, never by next-year scores.
These starts do not guarantee a global optimum. Numerical warnings require review.

Subgroups overlap and are diagnostic. Zero-grant history means no first-year
grant in the two modeled board regions; it does not include the excluded middle
board range. The grant and non-grant score contributions are divided by all
opportunities in each reported subgroup and sum to its total gain. Comparisons
use the same opportunities and frozen first-year membership probabilities.

## Interpretation limits and next decision

The second-year pilot outcomes have already been inspected. These are exploratory
checks using the same evaluation set, not a new confirmatory test. Standard errors
condition on the fitted models and omit refitting and specification-search uncertainty.
Subgroup intervals are unadjusted diagnostics, not a family of independent tests.

If K=4 or K=5 level-only removes the gain, the current evidence for a varying
competitive-state slope becomes weaker: a more flexible intercept distribution
can forecast comparably. If selectivity retains a gain, the constant-slope model
faces a stronger challenge. Neither result establishes independent psychological
dimensions, stable moral primitives, or a causal fairness mechanism.

After these checks, address correlation between latent heterogeneity and observed
opportunity histories, and preserve disjoint accounts for confirmation of the
chosen specification. Only then extend to a sampling-aware Patron comparison
of model-based generosity alone versus generosity plus selectivity. Patron status
would provide cross-decision evidence, subject to its timing and sampling limits.

## Provenance

`model.py`, `util.py`, and `source/pool_wave1_common.py` are copied byte-for-byte
from the delivered v1.0.0 package. The panel likelihood, gradient, encoder, and
forecasting routines are unchanged. `challenge.py` adds component expansion,
larger level-only models, regional paired diagnostics, and an authenticated cache
workflow. `PARENT_AUTHORITY.json` pins the specific returned results. This is a
new package; it does not alter the identity or contents of the original package.
