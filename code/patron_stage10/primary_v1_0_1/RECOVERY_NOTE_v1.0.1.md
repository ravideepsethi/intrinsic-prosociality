# Patron Stage 10 recovery note v1.0.1

Created 2026-08-27.

## Status of v1.0.0

The authenticated v1.0.0 production launcher passed package authentication, the
canonical-environment check, and the complete synthetic self-test. On the real data,
chooser-design Stage 00 then completed successfully in 39.206 seconds and wrote its
authenticated cache and success receipt.

Chooser-model Stage 01 stopped before estimating any model. Pandas 3.0.3 raised:

`TypeError: cannot safely cast non-equivalent float64 to int64`

The failure occurred while inserting a potentially fractional within-match-cell
median into a nullable `Int64` profile covariate. The synthetic fixture had missing
values, but it did not contain the decisive combination of an `Int64` source column,
a missing observation, and a fractional cell median.

No opportunity model, final verifier, or production result bundle ran under v1.0.0.
The certified Stage 00 cache is outcome-blind and remains valid.

## Recovery change

Version 1.0.1 casts the numeric source series and its cell-median series to ordinary
`float64` before filling nulls. This preserves a fractional median exactly. It does
not round, truncate, or otherwise change nonmissing values.

The synthetic fixture now contains an explicit nullable-integer regression test:
values `[1, 2, missing]` in one match cell must impute the missing value as `1.5`,
retain a missingness indicator, and produce a `float64` analysis column.

## Unchanged design

Version 1.0.1 changes no frozen input, acquired account, returned-profile rule,
patron definition, matching assignment, treatment definition, support rule,
covariate list, estimator, standard error, rematch seed, opportunity model, privacy
rule, or interpretation.

The production output root remains:

`/Volumes/XT_Pro/lichess_kindness/output/PATRON_STAGE10_PRODUCTION_V100`

The v1.0.1 launcher first re-authenticates the existing v1.0.0 Stage 00 artifacts.
If they match their receipts, it skips Stage 00 without rewriting them and resumes at
Stage 01. Any mismatch fails closed.
