# Stage 08 full-run QA resolution: v1.2.0

## Failure observed

The authenticated Stage 08 v1.1.0 full 24-month run completed input
authentication, the 47,587,020-row core cache, descriptive outputs, and Tables
1 through 7.  It then stopped transactionally when the full-only split-half
module requested:

```text
pandas.Series.corr(..., method="spearman")
```

Pandas delegates that optional method to `scipy.stats.spearmanr`.  SciPy was
not installed in the frozen project environment and was not a declared Stage
08 dependency.  No final Stage 08 output root or success receipt was published.

## Root cause

The one-month pilot correctly omitted Tables 8 and 9 because their definitions
require the full first-12-month/second-12-month sample.  The numerical self-test
covered the regression absorber but did not exercise this full-only split-half
path.  Consequently, pandas' hidden optional SciPy import was not detected
before the production run.

This is an undeclared software-dependency defect.  It is not a problem with the
Stage 07 data, the Stage 08 estimates, or the split-half definition.

## Version 1.2.0 correction

Stage 08 v1.2.0 computes Spearman correlation directly from its definition:

1. discard non-finite pairs;
2. assign average ranks to tied values with `pandas.Series.rank`;
3. compute the ordinary Pearson correlation of those two rank vectors using
   the producer's internal correlation kernel.

This is exactly Spearman's rank correlation with average tie handling.  It
uses only the already declared NumPy and pandas dependencies; SciPy is neither
installed nor added as an implicit requirement.

## Hardened self-test

The `--self-test` path now additionally:

- checks a tied-rank example against the fixed expected value
  `-0.31622776601683794`;
- constructs a synthetic split-half panel;
- runs every minimum-opportunity cutoff used by the paper;
- verifies the correlation and transition grid dimensions; and
- requires finite Spearman correlations.

The existing exact fixed-effect absorber and disconnected-incidence tests
remain unchanged.

## Recovery and provenance policy

- The failed v1.1.0 transactional directory is authenticated and preserved.
- The committed v1.1.0 producer remains available in Git history at commit
  `51bd57a2447b5503e5cb3a72a4829c3b93ad7c62`.
- Version 1.2.0 is committed as a forward fix; published history is not
  rewritten.
- The canonical full output root is created only after every Stage 08 module
  and output QA check passes.
- Research data and generated result tables remain outside Git.
