# Price-elasticity v1.0.2 pre-outcome recovery reconciliation

Date: 2026-08-25

## Status

The v1.0.1 production process failed closed while authenticating its first
private fair-state Parquet. No production validation regression, elasticity
model, nonparametric curve, heterogeneity estimate, or conditional Poisson
model was estimated. The collector retained the failure.

The observed v1.0.1 QA tuple was:

```text
(17328130, 487170, 2685525, 0, 17328129, 0, 0, 0, 0, 0, 0,
 0, 0, 17328130, 8575710, 1744924, 3.092656860295989,
 711.3202490883504, 9.977606383043538, 5.68361059282762,
 22.07866213756655, 0.028114401265456803)
```

## What the tuple establishes

The corrected exact-key cache reproduced:

- 17,328,130 fair rows;
- 487,170 kind draws;
- 2,685,525 chooser identities;
- sequential row IDs from 0 through 17,328,129;
- zero invalid price or draw-payoff rows;
- zero nonpositive, zero, or negative premium rows;
- zero malformed categorical codes;
- zero null row fingerprints and 17,328,130 distinct fingerprints;
- 8,575,710 fair rows and 1,744,924 choosers in November 2023--October 2024;
- a minimum premium of 3.092656860295989 rating points.

Thus the exact join and full-panel certified support were correct. The only
failed comparisons were two constants that v1.0.1 had inferred from v1.0.0's
lossy selected cache: 8,575,598 first-half rows and one nonpositive premium.

## v1.0.2 correction

v1.0.2 freezes the exact physical values of 8,575,710 first-half fair rows and
zero nonpositive premiums. It also adds a source-level preflight before chooser
dimension construction. The physical source and exact-key joined cache must
independently reproduce rows, distinct game IDs, outcomes, chooser identities,
null keys, price validity, first-half support, and premium sign. No value is
imputed, clipped, rewritten, or selected using an estimated coefficient.

The synthetic-Parquet test still injects one zero price deliberately so the
generic level-versus-log support guard remains tested even though production
support is strictly positive.

## Lineage protection

v1.0.2 writes to `kindness_price_elasticity_v102_PRIVATE` and
`kindness_price_elasticity_v102`. It never reads, modifies, deletes, or resumes
the v1.0.0 or v1.0.1 private states. Every new estimate remains exploratory
(`X`), and all signs and numerical failures remain reportable.

Expected runtime remains approximately 1–4 hours, with up to 8 hours allowed
under unusual external-drive contention.
