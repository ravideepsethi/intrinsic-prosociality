# Dynamic prosociality second wave: implementation amendment

- **Version:** 1.0.2
- **Date:** August 22, 2026
- **Timing:** after the outcome-blind feasibility/design freeze and before any second-wave outcome is read
- **Parent authorities:** analysis plan v1.0.0 and source-contract amendment v1.0.1

## 1. Purpose

The canonical all-game chronology contains 7,763,847,245 rows. Exact construction of
running user and unordered-pair histories for every account would require a multi-
terabyte sort and would not change the frozen estimands. This amendment freezes a
deterministic cluster-sampling implementation before the producer can read stopping,
re-pairing, or kindness outcomes.

No B2 post-event choice, F2 stopping outcome, E1 rematch outcome, or downstream
kindness outcome informed this amendment.

## 2. Deterministic samples

DuckDB 1.5.2 `hash` is part of the source contract. The modulus denominator is 50.

- The **user sample** contains every account satisfying
  `hash(user_id, 2026082202) % 50 = 0`. Every rated-standard chronology event for a
  sampled account is retained. F2 salience and both downstream F2 branches use this
  same user-cluster sample.
- The **pair sample** contains every unordered pair `(low_id, high_id)` satisfying
  `hash(low_id, high_id, 2026082203) % 50 = 0`. Every rated-standard chronology event
  for a sampled pair is retained. E1 training, first-ever classification, and the E1
  downstream model use this same pair-cluster sample.

Sampling therefore occurs on the unit whose history must be complete, never on games
within a selected user or pair. The confirmatory targets are the corresponding
deterministic 2-percent cluster samples. B2 remains on the full certified B1 sample.
Only a priori identifiers enter either hash.

The producer must report full and sampled Stage 07 support, hash-balance summaries by
month and speed, and the fraction of eligible observations retained. It must not
describe the samples as random draws in a design-based sense; deterministic
pseudorandom cluster samples is the precise term.

## 3. E1 sample-rate scaling and cell hierarchy

For E1, sampled cell successes and trials are multiplied by 50 before applying the
Jeffreys prior. The minimum full-population-equivalent support of 1,000 games is
implemented as at least 20 sampled games before scaling. Leave-focal-pair-out
subtraction occurs in sampled counts before scaling.

The coarsening hierarchy is frozen as:

1. speed x 100-point average-rating band x UTC six-hour block x weekend;
2. drop weekend;
3. speed x 200-point average-rating band x UTC six-hour block;
4. drop the hour block; and
5. speed only.

The first level with at least 20 sampled leave-pair-out trials is used. The training
window remains `[M - 395 days, M - 30 days)`. The score is
`(50 * successes + 0.5) / (50 * trials + 1)`.

## 4. Salience regression implementation

Round-number and personal-peak gates use the frozen triangular local-linear design.
Round-grid models include boundary fixed effects; personal-peak models include speed
and focal-month fixed effects. Standard errors cluster by account.

The true grid and its two placebo grids are fit separately, while cluster influence
functions are retained. Covariances between grid estimates are obtained from shared
account influence functions, so the true-minus-average-placebo gate uses a joint
cluster-robust standard error. The conventional gate and the prespecified discrete
integer-bin comparison are both reported.

## 5. Downstream model implementation

F2-R, F2-P, and E1 use linear probability models on their frozen deterministic cluster
samples. The models absorb chooser and month fixed effects, include the controls named
in the parent plan, and cluster by chooser. Continuous controls enter as centered
linear and quadratic terms; categorical speed and tournament indicators are explicit.
The exact contrast covariance—not a sum of marginal standard errors—is used for the
two F2 true-minus-average-placebo contrasts.

F2-R and F2-P retain the primary `chooser_pre_rd_v2 <= 110` screen. RD <= 80 is a
reported sensitivity. E1 retains first-ever-pair as its primary sample.

## 6. Checkpoint and execution contract

The chronology is projected once into an authenticated selected-game layer and is not
rescanned independently by hypothesis. Source-file extraction checkpoints are
parallel, one-thread DuckDB workers; user and pair windows are then independently
partitioned by 16 identifier buckets. Every checkpoint records the configuration hash,
input authority, row count, bytes, and SHA-256. Account-level files remain private on
XT_Pro.

The committed producer and this amendment must be present in a clean Git commit that
descends from `55124c10f746a6de6e5c186c8ddf7796fef5fb2a` before execution. The final
four-slot Holm family and all sign predictions are unchanged.
