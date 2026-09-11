# Authenticated review of pool-main Wave 1

## Verdict

The returned Wave-1 bundle is authentic, complete, disclosure-safe, and suitable as an upstream authority for the next reset wave.

- Returned ZIP SHA-256: `33c7caf28302b866944b4f21567100c1977ab2e1a6249a35295be86aca238569`
- Selected-sample fingerprint: `a17c89d750cb4fdfdf84f950859e45c58b19996efae02045def68285e305cf30`
- Outer manifest: 256 files, all hashes and byte counts verified
- Production panel: all 24 monthly Parquets fully hashed
- Stages: all seven completed in 1,223.529 seconds
- Nonparametric fits: 33 `MODEL_OK`, zero failures
- Controlled model and figure: both internal manifests verified; visual inspection passed
- Privacy scan: passed

One non-substantive bookkeeping artifact remains: `parallel_progress.json` was snapshotted with `status: RUNNING` even though it records `completed=33`, `total=33`. The canonical nonparametric settings receipt is complete and all 33 individual model receipts are `MODEL_OK`. Returned evidence is preserved unchanged.

## Main Wave-1 results on the selected sample

| Result | Estimate |
|---|---:|
| Overall kindness | 1.372578% |
| Disconnected clearly better | 3.576342% |
| Disconnected better | 2.390879% |
| Roughly equal | 2.605005% |
| Modestly worse | 1.203466% |
| Clearly worse | 0.470138% |
| Fair minus clearly worse | +2.288140 pp |
| Fair / clearly worse rate ratio | 5.86695 |

The “kindness desert” remains large in the new sample: fair positions have a 2.758278% kindness rate versus 0.470138% when the chooser is clearly worse.

Prior kindness strongly predicts later kindness. The new-sample later rate is 16.0975% among ever-kind choosers versus 0.9986% among never-kind choosers. Under the temporal minimum-four design the rates are 15.8237% versus 0.9383%; split-half Pearson correlations are 0.600417 (hash) and 0.545303 (temporal), with weighted correlations 0.689786 and 0.617820.

The increases relative to the former sample are descriptive. Because the new predicate jointly changes pairing source and observed predecessor adjacency, they cannot be attributed causally to removing one class of pairing.

The controlled payoff diagnostic is not a simple monotone “price of kindness” result. Within absolute payoff below one rating point, the loss-side slope is +0.324712 pp per point (SE 0.112718), the gain-side slope is -0.167191 (SE 0.112471), and their difference is 0.491903 (SE 0.076315). There is also a conditional exact-zero elevation: zero-minus-left is +0.142531 pp (SE 0.035306), zero-minus-right is +0.088116 (SE 0.035415), and right-minus-left is +0.054415 (SE 0.020715). These estimates concern reconstructed draw payoff and do not reproduce the manuscript's adjacent displayed-gap Panel A. Until Wave 2A v1.0.1 rebuilds that estimand and separates displayed-1500/high-RD support, Section 4.4's broad no-level-jump wording is not authorized. The defensible interim description is an asymmetric inverted-V/exact-zero association, not a causal monotone price curve.

Rating-gap diagnostics confirm that the payoff and rating geometry are related but not interchangeable: correlation of absolute payoff with absolute rating gap is 0.468332, with expected-score distance 0.366678, and with log K-factor 0.461557. Log K is especially tied to chooser RD (0.897077).

The nonparametric relative-strength pattern survives common-support controls. In the canonical roughly-equal contrast, the weaker side is -0.474329 pp (SE 0.081280) and the stronger side +0.560478 pp (SE 0.100421); the primary K=20, ply>10 central-bin estimates preserve the same gradient.

## Scope

These findings supersede their former-main-sample counterparts. They do not make the old equality/FEN, dyad, dynamics, chooser-leniency, Patron, or manuscript-wide outputs current; those require their own new-sample rebuild receipts.
