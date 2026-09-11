# Source-binding and isolation method

The bundled producers begin from public-repository sources inspected at commit
`0dc981cbc6da157d365015a95f2b7157ecda4859`. Version 1.0.1 carries one documented
exception: the dynamic-core producer and its audit-local copy contain the
correction authenticated in `authority/WAVE2B1_V101_CORRECTION.json`. That
correction replaces a prior-sample A3 QA literal and five descriptive B1
coverage denominators. Scientific estimators, samples, treatments, outcomes,
and inference are unchanged. The two A1 audit wrappers change only their
base-producer hash guard so their offline tests authenticate the corrected core.
Version 1.0.2 adds the separately authenticated
`authority/WAVE2B1_V102_CORRECTION.json`. Its sole source override is the A1
evidence-gap wrapper: a post-result sensitivity that does not meet the base
estimator's frozen support gate is retained as an explicit unsupported row with
its exact counts. Supported estimator calls and all primary estimators are
unchanged. All other bundled producers remain byte-identical either to the
inspected public sources or to the v1.0.1 correction authority.

The original modules freeze former Stage-07 row counts, receipt hashes, and run
IDs. Running those files unchanged would either fail closed or silently point
downstream code toward an old sample namespace.

Wave 2B1 therefore creates a separate project view under the Wave 2B1 private
restart directory. Certified pool-main Parquets are exposed there through
read-only symbolic links. No existing project output is overwritten.

Immediately before each stage, `runner/bind_source.py` uses Python's AST to
replace only:

- module-level authority constants (paths, counts, run IDs, and hashes); and
- repository-state guards, which return the recorded inspected public commit.

Every requested symbol must exist exactly at module scope, the rendered file
must parse, and the receipt records both original and generated SHA-256 hashes
plus every changed symbol. Runtime binding does not edit function bodies. The
offline self-test independently compares an unchanged synthetic estimator AST
before and after binding and checks all 13 real binding contracts against the
bundled sources and both versioned correction authorities.

Downstream bindings are delayed until upstream aggregate and private receipts
exist. Consequently each frozen SHA check names the newly rebuilt pool-main
artifact rather than a former-sample file.

Two compatibility authorities are constructed inside the isolated view:

- a frozen design-gate bridge preserving the pre-outcome A3 selection rule; and
- a semantic reentry-contract bridge preserving the authenticated chronology
  and the historical clock rule `disc_clock_s >= 347`.

Neither bridge imports an old effect estimate. The original 7.76-billion-row
chronology is reused only because Wave 2A authenticated its file inventory as
sample-invariant. All sample-dependent caches are newly namespaced.
