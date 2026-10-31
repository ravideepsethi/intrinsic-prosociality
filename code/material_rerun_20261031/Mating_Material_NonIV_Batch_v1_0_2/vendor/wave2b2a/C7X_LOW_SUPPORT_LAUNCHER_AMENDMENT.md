# C7X low-support launcher amendment

## Trigger

The first v1.0.0 execution completed C7X correctly on the selected
pool/non-adjacent panel and froze 10,481 classified focal rows: 125 in the
benefactor arm and 10,356 in the claimer arm. The C7X primary therefore failed
its prespecified minimum of 1,000 rows in each arm and was retained as
`NOT_ESTIMABLE_RETAINED_LOW_SUPPORT`.

## Outer-launcher defect

The v1.0.0 outer launcher incorrectly assumed that every successful C7X run
must produce a primary coefficient and standard error. It stopped before
launching C7R when those values were correctly absent. This coupled C7R's
independent first/repeat-meeting family to the C7X support outcome even though
the frozen C7R contract treats the two questions separately.

## Version 1.0.1 disposition

Version 1.0.1:

- adopts and authenticates the completed C7X output and private outcome-free
  classification;
- preserves the C7X failed support gate and does not estimate or impute a C7X
  primary;
- runs the exact C7R first/repeat-meeting family;
- retains C7R's frozen relationship-model attempts, but marks every one with
  the parent C7X low-support status;
- marks same-run C7X numerical reproduction as not applicable; and
- keeps the historical old-sample coefficient and standard error only as an
  explicitly labeled diagnostic reference.

No sample definition, outcome, exposure, covariate, fixed effect, clustering
rule, model inventory, minimum-support threshold, or Holm family is changed.
