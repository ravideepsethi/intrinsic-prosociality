# Dynamics Paper 2 Campaign 1 v1.0.9 C13 denominator reconciliation

**Date:** 2026-08-25  
**Timing:** written after C12 outcomes were seen, but before any C13 ambient-kindness
numerator or rate was read.  
**Classification:** post-C12, pre-C13-numerator computational correction; not a
preregistration.

## Triggering event

The authenticated v1.0.2 result ZIP has SHA-256
`e7df2a259ce3ea2a6392a8f0528e11fc4430ddea98bfb75cc7adb29d56327e76`.
Its package, collection manifest, and public-result manifest authenticated
exactly. C12 completed. C13 then stopped at its outcome-blind support assertion,
before its ambient-kindness numerator was read:

| Quantity | Wave 0 | v1.0.2 reconstruction | Difference (Wave 0 − v1.0.2) |
|---|---:|---:|---:|
| Fair focal rows | 17,328,130 | 17,328,130 | 0 |
| Supported rows | 17,104,149 | 17,101,141 | 3,008 |
| Thin excluded rows | 223,981 | 226,989 | −3,008 |
| Prior-28 minimum | 0 | 0 | 0 |
| Prior-28 p10 | 27,902 | 28,081 | −179 |
| Prior-28 median | 136,108 | 136,490 | −382 |

Both calculations leave more than 98.6% of fair focal rows supported.

## Provenance finding

The Wave-0 files are authentic. `c13_support_only.json` has SHA-256
`1f69ab4663c92a8246f0617acf824c03c598a7849e1c74b1ce324644cca763fe`;
its result manifest has SHA-256
`08aaadd8cde1c70c717c41fd38a35f16c1428d9b30281c4e2d610164e32703cf`.
The result names Git commit `c0d7cb3da145b7702a6020c09f8eaf19db6fe8c1` and maps the
time and chooser fields to `api_last_move_at_ms` and
`chooser_username_norm`.

However, neither the authenticated Wave-0 public result tree nor the collected
repository tree at that commit preserves the executable producer for
`c13_support_only.json`. The aggregate can therefore be authenticated, but its
exact implementation cannot be audited or rerun from preserved source.

By contrast, the v1.0.2 source is preserved and its reconstruction is explicit:

- certified Stage-07 fair opportunities only;
- UTC day from `api_last_move_at_ms`;
- frozen speed pools and chooser-rating bands `<1600`, `1600–1999`,
  `2000–2399`, and `2400+`;
- the preceding 28 complete UTC days, days −28 through −1;
- cell defined by speed pool × chooser rating band;
- the focal chooser's own opportunities subtracted using normalized chooser
  identity; and
- support at 5,000 other-chooser fair opportunities.

This construction matches the governing design text. Its exact output was
observed before the C13 numerator was accessed.

## Correction rule

Campaign 1 v1.0.3:

1. retains the Wave-0 aggregate and hashes as superseded provenance;
2. freezes 17,101,141 as the corrected reproducible C13 support authority;
3. requires exact reproduction of the corrected count and distribution before
   any numerator read;
4. does not search implementation variants for one that merely recreates the
   old aggregate;
5. records that the correction changes no hypothesis, estimand, cell,
   lag-window, support threshold, covariate, fixed effect, cluster, or causal
   interpretation; and
6. proceeds with C13 only after the reconciliation record is written.

This choice is based on auditable provenance and frozen design semantics, not
on a C13 sign, magnitude, standard error, or p-value.

## Complete-attempt policy

The v1.0.2 C12 results are retained. Because its eligibility guard silently
skipped the 2400+ chooser-rating-band split, v1.0.3 explicitly attempts that
model and retains a low-support or nonidentification failure if necessary.

C13 likewise attempts every rating-band and speed subgroup, including those
below conventional support thresholds. The common estimator may reject a
model with fewer than 1,000 rows or fewer than 100 chooser clusters, but the
requested sample size, cluster count, and error then remain in the public
model-attempt table. No analysis disappears silently.

## Interpretation and multiplicity

C13 remains exploratory (`X`) and associational. Leave-one-chooser-out lagging
removes mechanical self-inclusion; it does not identify a causal peer effect.
C12 remains a secondary recipient-selection/targeting association.

No C12 or C13 result enters Holm family D. That family remains C1, C2, C5, C6,
and C9, with final adjustment pending C5.
