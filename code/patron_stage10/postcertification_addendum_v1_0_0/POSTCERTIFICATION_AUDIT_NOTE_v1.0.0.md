# Patron Stage 10 post-certification audit note v1.0.0

## Preserved authority

The authoritative v1.0.1 status is
`PATRON_STAGE10_PRODUCTION_CERTIFIED_OK`. Its primary fair-kind coefficient is
0.3056613950 percentage points (HC1 SE 0.0172112698), and the raw matched gap is
0.3056583842 pp. This addendum does not rerun, overwrite, or reinterpret that
primary estimand.

## Exact audit findings addressed

### Account-date missingness

In DuckDB, the v1.0.1 construction using `greatest(0.0, expression)` returned
zero when the timestamp expression was NULL. Consequently, 69,094 returned
profiles missing `created_at_ms` and `seen_at_ms` did not activate the intended
date missingness indicators. The addendum uses an explicit `CASE`: absent raw
timestamps remain NULL, observed timestamps alone are converted to nonnegative
days, and treatment-blind within-cell imputation follows.

### Five-bin chooser companion

The v1.0.1 opportunity appendix correctly estimates patron-by-desert
interactions at the opportunity level. The implementation contract separately
requested chooser-level patron prediction from where kindness occurred across
all five certified fairness bins. The addendum supplies that distinct model
family on outcome-blind, frozen support.

### Price count and rate companions

The v1.0.1 price diagnostic correctly reports the two ever-kind indicators.
The addendum supplies the requested continuous count and rate companions. Each
reported coefficient is a one-standard-deviation association, estimated
jointly for costly and nonnegative fair-state kindness and conditioned on the
corresponding exposure volumes.

### Other audit notes

The snapshot's typed total/rated/win/loss/draw count fields are unavailable for
all returned profiles. The addendum records that missingness and preserves the
v1.0.1 fail-closed deterministic dropping of unsupported regressors. Per-speed
games, playtime, active months, opportunity volume, and skill controls remain
available.

The transferred v1.0.1 executed-source copy contained one generated `.pyc`
file outside its source manifest. It had no analytical or privacy effect. This
package disables bytecode generation and refuses to transfer any generated
cache file.

## Interpretation boundary

The addendum is a transparency and contract-completion exercise. It is not a
new confirmatory family, it does not amend results after inspecting their
signs, and it does not identify patron adoption or causality.

