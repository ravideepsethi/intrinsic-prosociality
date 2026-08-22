# Dynamic prosociality second wave: additional analyses v1.0.1

## 1. Scope

This package extends the dynamic second-wave analysis with robustness,
descriptive, and mechanism-oriented specifications. It evaluates the sensitivity
of the re-pairing result, maps the timing and weighting of first-grant dynamics,
and examines personal and round-number rating reference points. Every listed
specification is written to the aggregate output, including null, unstable, and
contradictory results.

The package does not alter the existing second-wave results. It reads their
authenticated aggregate outputs and private computational checkpoints so that
expensive history construction and score estimation do not need to be repeated.

## 2. Inputs, integrity, and privacy

The launcher validates the required source outputs, installed source programs,
cached histories, Stage 07 target bundle, and E1 monthly score files before
estimation. It also verifies that the repository contains only the expected
package installation or the exact recoverable partial installation left by the
v1.0.0 whitespace failure.

No Patron or profile input is read. No account identifier, game identifier,
pair history, or row-level score is written to the aggregate output or transfer
archive.

## 3. E1 robustness

The original E1 specification is first reproduced as a numerical consistency
check. The principal robustness specification then uses:

- first-ever focal pairs;
- the same past-only leave-pair-out re-pair score;
- chooser fixed effects;
- calendar-month fixed effects;
- a fully interacted pool-cell fixed effect defined by speed, 100-point
  average-rating band, six-hour UTC block, and weekend status;
- the original numerical controls other than additive indicators absorbed by
  the interacted cell effect; and
- the same p90-minus-p10 re-pair-risk scaling.

Two covariance estimates are reported for the principal specification:

1. chooser-clustered; and
2. Cameron-Gelbach-Miller two-way clustering by chooser and score-assignment
   unit, where assignment unit is calendar month by the pool cell at the
   score's actual coarsening level.

The two-way-clustered specification is also reported for:

- coarsening level 1 only; and
- leave-pair-out cell support of at least 50, 100, and 500 sampled
  observations.

All specifications are reported regardless of sign, magnitude, or precision.

## 4. B2 estimand and horizon robustness

The conditional-Bernoulli reference distribution is rerun with 4,999
randomizations, holding fixed each chooser's kindness total and using the
existing cross-fitted propensities.

The following horizons are reported: 1, 3, 6, 12, 24, 48, 72, 168, 336, and
720 hours. At each horizon the output reports:

- opportunity-weighted continuation rate;
- chooser-equal continuation rate among choosers with a follow-up opportunity;
- share of contributing choosers with a subsequent kind draw;
- number of distinct contributing choosers; and
- randomization mean, 95% reference interval, excess, and plus-one two-sided
  p-value.

At 24 hours, chooser-equal results are also reported separately for costly,
exact-zero, and favorable first-grant payoff groups, together with the
costly-minus-favorable contrast. The sparse exact-zero group is retained and
clearly labeled.

Aggregate quantiles of per-chooser follow-up counts and continuation shares
show how strongly the pooled statistic weights highly active choosers. These
remain sequence-dependence analyses: they do not identify a causal effect of a
first lifetime kind act. Here, first means the first observed grant in the
locked B1 panel.

## 5. Personal-peak reference points

The initial personal-peak comparison provided limited evidence that the zero
offset was distinctive relative to the +37 and +50 offsets. The additional
analysis therefore maps a wider threshold grid relative to the prior same-pool
peak.

The all-game stopping analysis estimates the same local-linear specification at
offsets

`-100, -75, -50, -37, -25, 0, 25, 37, 50, 75, 100`

rating points from the prior peak. It uses bandwidth 10, at least 50 prior
same-pool games, at least 365 days of observed pool history, a 30-minute
stopping outcome, triangular weights, speed and month controls, and
chooser-clustered inference.

The zero-offset coefficient is contrasted with the equal-weight average of
nonzero offsets whose regression-row count lies between one-half and twice the
zero-offset count. This support rule depends only on sample counts. The complete
offset curve and Holm- and Benjamini-Hochberg-adjusted pointwise p-values are
reported.

The downstream kindness analysis reports:

- the original zero-minus-average(+37,+50) contrast at RD limits 110 and 80;
- a joint offset-grid model at RD limits 110 and 80;
- the zero-offset coefficient and its difference from the average of
  support-comparable offsets; and
- treated support for every offset.

## 6. Round-number follow-up

The original round-number stopping and downstream specifications are reproduced
as numerical consistency checks. The package additionally reports:

- individual downstream coefficients for the true, +37, and +50 pivotal
  indicators;
- aggregate kindness rates and support by crossed round-number threshold; and
- the RD-at-most-80 sensitivity beside the RD-at-most-110 result.

The result is interpreted as a discrete threshold and stopping pattern, not as
a textbook continuous regression-discontinuity design. Density and balance
diagnostics remain part of the evidence.

## 7. Outputs

The aggregate directory contains:

- source-integrity checks;
- E1 robustness specifications;
- B2 horizon, weighting, payoff-group, and chooser-distribution results;
- personal-peak offset salience results and downstream contrasts;
- round-number downstream decomposition;
- a machine-readable summary;
- a manifest hashing every report file; and
- an atomic success receipt.

The launcher prints the principal estimates, archives only aggregate files,
writes a SHA-256 sidecar, and leaves private computational state on XT_Pro.
