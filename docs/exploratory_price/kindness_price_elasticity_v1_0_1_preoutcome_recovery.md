# Price-elasticity v1.0.2 pre-outcome recovery reconciliation

Date: 2026-08-25

## Status

The v1.0.0 production process failed closed while building its first private
fair-state Parquet. No production validation regression, elasticity model,
nonparametric curve, heterogeneity estimate, or conditional Poisson model was
estimated. The collector retained the failure and created an aggregate bundle.

The observed v1.0.0 QA tuple was:

```text
(17328130, 487169, 2685521, 0, 17328129, 1, 0, 112,
 8575598, 1744916, 0.0, 711.3202490883504, 9.977606860745126,
 5.683610599099763, 22.078653058780247, 0.028114525273461744)
```

## Root causes and corrections

### 1. Chooser-key semantic mismatch

v1.0.0 grouped on the physical `chooser_username_norm` value but then cast its
dimension key and both sides of the join to `VARCHAR`. The physical scan showed
that this was not identity-preserving: four fair-state chooser identities were
collapsed. Compensating duplicate/drop behavior happened to conserve the total
row count while changing the outcome numerator by one. This is another instance
of the project's general lesson that schema equality is not semantic equality.

v1.0.2 carries the physical key unchanged, joins on exact key equality, and
requires all of the following before writing a checkpoint:

- 17,328,130 joined rows;
- 17,328,130 distinct game IDs;
- 487,170 kind draws;
- 2,685,525 chooser identities; and
- zero null game IDs.

### 2. Calendar-window anchor

The 7,980,397 count belongs to the older October-2023--September-2024
Appendix-A11 window. The current Stage07 authority begins in November 2023, so
its first 12 months are November 2023--October 2024. The physical v1.0.0 scan
found 8,575,598 rows; certified Stage08 records 1,744,924 early-period chooser
identities. v1.0.2 freezes those correct anchors and labels the bridge an
openly nonidentical cross-window comparison.

### 3. Row fingerprint

The v1.0.0 DuckDB hash/cast expression yielded 112 null values. The fingerprint
is used only to authenticate model support, not as a scientific variable.
v1.0.2 uses the already deterministic chooser/time/game ordering to assign a
unique sequential 64-bit row fingerprint and requires exactly 17,328,130
distinct, nonnull fingerprints.

### 4. One exactly zero premium

Stage07 has one fair-state row whose certified `chooser_win_premium_v2` equals
zero. v1.0.2 does not rewrite or impute it. The row remains in level-price,
nonparametric, and exact Stage08-validation models. Its logarithm is represented
as missing, so every log-price estimator excludes exactly that row through its
declared finite-support rule. Receipts report the zero count and policy.

## Lineage protection

v1.0.2 writes to `kindness_price_elasticity_v102_PRIVATE` and
`kindness_price_elasticity_v102`. It never reads, modifies, deletes, or resumes
the v1.0.0 private state. Every new estimate remains exploratory (`X`), and all
signs and numerical failures remain reportable.
