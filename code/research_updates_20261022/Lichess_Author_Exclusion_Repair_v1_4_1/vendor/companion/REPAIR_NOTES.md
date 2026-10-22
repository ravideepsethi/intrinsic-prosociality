# Review of resumed result 23716a25c7252fd1 and v1.0.2 changes

Input ZIP SHA256:
8ba38757853bc2781bc18b584993b6643244f274262afc2e1a631e3c78f40a11.
It matches the supplied sidecar. All four saved model JSON checksums match
completion receipts. There are no new completed hour models or repetition
estimates in this result.

## What the returned archive establishes

- All 24 focal projections were adopted and validated.
- June 2023 bullet contains 322 invalid timestamps: 321 null and one zero.
  Exactly one of these game rows involves an analysis chooser, and exactly one
  chooser is affected. The original audit therefore correctly blocked history.
  The exported counts do not reveal whether the affected row is null or zero.
- Receipt last-move-hour projection failed at column 1 after 20,000 conjugate
  gradient iterations. IV failed at column 9 at the same limit. Thus v1.0.1's
  full-data numerical repair was unsuccessful, despite its synthetic tests.
- The four previously completed baseline and start-hour fits remain available.

| Completed association | Baseline pp | Start-hour pp |
|---|---:|---:|
| Receipt, conditional next competitive choice | 0.88166 | 0.85400 |
| Primary IV, unconditional zero-coded next choice | 0.29495 | 0.29345 |

Receipt start-hour SE is 0.10548 pp under original exposure-chooser clustering,
with CI [0.64725, 1.06075]; the extra chooser-or-hour CR0 SE is 0.12651. IV
start-hour SE is 0.12678, with CI [0.04498, 0.54193], under shared-account-or-date
CR0. Neither association identifies a causal receipt effect without additional
assumptions, and the IV exclusion restriction remains unresolved.

## Numerical correction

Version 1.0.1 applied conjugate gradients to a possibly singular dummy normal
system. Normal equations square the design's condition number, and floating
point accumulation can introduce residual components inconsistent with exact
rank deficiencies. The full-data failures show that implementation was not
reliable for these models; the precise spectrum of those failed systems was
not exported.

Version 1.0.2 solves the rectangular weighted dummy least-squares problem using
LSMR, after exact aggregation of identical FE tuples. The original within-tuple
residual remains in each observation. Exactly nested effects may be removed
from the solve only because their span is already included; all original
levels are checked afterward. Weighted group-mean residuals retain absolute
1e-10 tolerance for receipt and the original matrix-scale-relative tolerance
for IV. Solver status alone does not certify a fit. Completed columns are
checked again on resume, and failed systems preserve diagnostics.

This changes numerical computation, not the model, rows, weights, controls,
clustering or predeclared comparisons. Models that fail remain explicitly
unestimated; their independent companions can continue.

## Timestamp correction

Only the one affected game is eligible for recovery. A public export must match
its ID, the chooser identity, ratings, game class, result and archive month.
API createdAt is floored to seconds, matching chronology precision. A one-row
private overlay enters prefix counting; original history files stay unchanged.
The correction and its provenance are bound into that prefix checkpoint.
If any check fails, there is no imputation or sample exclusion.

## Validation completed locally

- Explicit weighted and unweighted dummy-regression parity.
- Nearly nested effects, duplicate effects, calendar dependencies and unequal
  weights, with every original FE level checked.
- Per-column checkpoint reuse without solver calls; corruption rejection.
- Mocked one-game API response, including identity/class/result/month/rating
  checks, source preservation, second precision, cache reuse and restored count.
- Original FE/covariance, cross-month history, strict-prior/tie, cache tests.
- 300,000-row synthetic stress test: 110,849 FE tuples; three columns; 1,757
  maximum iterations; maximum group-mean residual 7.45e-13; about 5 seconds in
  this environment. This is not a Mac/full-data runtime benchmark.

The full-data result must still be checked after execution. This package does
not certify new findings, the ordinary-loss test, incident-share tests, or the
incident-adjusted temporal-concentration benchmark.
