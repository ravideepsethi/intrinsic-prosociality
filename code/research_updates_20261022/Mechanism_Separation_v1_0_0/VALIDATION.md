# Software validation — September 26, 2026

This is a code-delivery validation record, not a production-results receipt.
The external-drive research data were unavailable in this environment. Source
adapters were checked against the supplied producer code and pinned inventories,
and exercised on synthetic files using their documented schemas.

## Completed checks

All **15 automated tests passed**, including:

- Exact conditional log likelihood and analytic gradient against enumerated
  outcomes for groups of sizes 3, 5 and 8, for every nondegenerate outcome count.
- Numerical stability with extreme indices, recovery of a known conditional
  slope, and explicit removal of outcome-invariant accounts.
- Agreement of dense and streamed chooser-FE LPM estimates and covariance.
- Correct additional account-baseline calibration for probability predictions.
- Symmetric but nonconstant premium-versus-gap mechanics, and exact nonzero
  premium changes under the color formula.
- Refusal to label the RD-floor near-tie sample as supplying two separate stakes.
- Strict history interval boundaries, exclusion of the focal game despite a
  500-millisecond API/PGN timestamp difference, and source/chronology joins.
- A miniature source-tree run with two spawned workers, aggregate-only result
  archives, and an immediate restart preserving completed activity checkpoints.
- Historical cue input authentication, preservation of unknown cue values,
  and rejection of a nonhistorical flag declaration.
- An authenticated synthetic post-policy input path with complete preperiod
  support. Flipping every post-policy outcome left the entire prediction and
  pairwise-power tables unchanged.
- Reproducible block-bootstrap draws and a positive minimum detectable effect.

The separate synthetic pipeline used **19,200 opportunities, 800 accounts and
24 months**. It fitted all seven candidate models, scored the two forward
holdouts (84 model-by-month cells), generated the support/surface/index/cost and
policy-planning outputs, and produced the PDF/PNG figures. It also completed
one full recovery refit and confirmed recovery and model-fit checkpoint reuse.
Its elapsed time was about **12 seconds** after compilation in this environment.
That is not a production-scale runtime or memory benchmark. The complete
20-repetition-per-generator recovery exercise is for the user's actual design.

Python compilation, Bash syntax and archive/member checksums are checked before
delivery. The package contains source code and authority inventories; it excludes
generated Python/Numba caches, dependency installations, private fixture data,
and research opportunity rows.

## Environment and limits

Validation used Linux, Python 3.12, NumPy 2.3.5, pandas 2.2.3, SciPy 1.17.0,
Numba 0.67.0, DuckDB 1.5.5, PyArrow 25.0.1 and Matplotlib 3.10.8. The launcher
uses macOS-compatible Bash syntax; process tests explicitly used the spawn
method used by macOS. Native execution on the user's Mac was not performed.

No production coefficient, causal contribution share, historical cue result,
behavioral color estimate, policy GO decision or IV estimate was produced here.
Unavailable historical-cue and policy inputs retain explicit dependency statuses.
Production performance, empirical support and model recoverability remain outputs
of the delivered run, not claims established by these software tests.

## Reproduce the checks

With a compatible Python environment:

```bash
python -m unittest discover -s tests -p 'test_*.py' -q
python tests/synthetic_pipeline.py
```

The launcher runs the first command automatically before touching production
inputs. It does not run the synthetic integration exercise on every restart.
