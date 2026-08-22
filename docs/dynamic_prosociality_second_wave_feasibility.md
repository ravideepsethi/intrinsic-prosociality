# Dynamic prosociality second-wave feasibility certification

**Status:** `DYNAMIC_SECOND_WAVE_DESIGN_READY_FOR_PRODUCER_FREEZE`

**Audit run:** `20260822T134125Z`

**Certification date:** August 22, 2026

**Repository authority:** `f0f92fb38efb9dea59d4f41d90049fae3e6c57fa`

## Outcome

The outcome-blind feasibility gate passed. B2, both F2 branches, and E1 have sufficient
support and canonical sources for implementation. The audit estimated no new kindness,
stopping, or re-pairing effect and retained no account-level output.

Before producer execution, the accompanying version 1.0.1 source-contract amendment
must be applied. The reason is narrow but material: the all-game chronology contains no
pre-game rating-deviation field, although the original F2 salience plan proposed an RD
screen. The amendment replaces that unavailable salience-sample screen with strictly
past same-pool experience and observed-history requirements. Exact RD restrictions are
unchanged in the downstream Stage 07 kindness models.

## Authenticated authorities

- Stage 07: 24 Parquet files, 47,587,020 rows, including 17,328,130 fair opportunities.
- B1 private sample: 64,331 repeat granters and 1,017,944 actual opportunities.
- All-game chronology: 852 files and 7,763,847,245 rows, January 2013 through April
  2026.
- Compact rating inputs: 945 files and 939,153,041 rows; useful only for their limited
  October 2024--July 2025 coverage and not an all-history authority.

The feasibility success receipt has SHA-256
`944380e1f8f8d56ab2bcdb15a2461ac9bf6332e1e6d39d3207511dcc535a34cc`.
Its report manifest has SHA-256
`a32971c271e87e24dc9e09da14747b26b8f41ab17950ce567bb094d338f7621f`.

## B2 support

The certified B1 population supplies:

- 5,640 choosers and 6,190 subsequent opportunities within 24 hours of the first
  observed grant;
- 2,792 choosers and 2,925 opportunities within six hours; and
- 20,382 choosers and 28,949 opportunities within seven days.

The primary B2 test therefore remains the 24-hour pooled post-event kindness rate
relative to 4,999 sequence-specific conditional-randomization draws. Six hours and seven
days remain secondary. The estimand is explicitly among repeat granters.

## F2 downstream support

With certified chooser RD at most 110, the round-number action-gap design has 1,138,440
exact pivotal observations across all boundaries and 1,010,743 across the frozen
1000--2600 grid. The ending-50 and +37 placebo grids have 973,281 and 984,334 pivotal
observations in that range. Exact and rounded-visible classifications disagree for
168,195 observations, or about 1.01% of eligible rows; the disagreement will be
reported rather than silently resolved.

Boundary-specific support is ample through the main rating range. The uppermost
thresholds are thinner—1,332 observations at 2500 and 505 at 2600—but the frozen model
pools boundaries with boundary fixed effects and must report threshold-specific support.

## F2 salience source

The chronology has exactly the fields required to reconstruct displayed post-game
ratings and positive rating changes: pre-game rating, realized rating change, user and
opponent identifiers, game identifier, timestamp, and speed/month partitions. It lacks
RD. Under the dated amendment, settled-account history is constructed from the same
strictly prior chronology before any stopping outcome is estimated.

## E1 source

The chronology provides full pair identities, timestamps, displayed ratings, and speed
partitions. It can support:

- past-only 365-day liquidity cells with 30-day outcome maturity;
- leave-focal-pair-out re-pairing risk with a Jeffreys prior;
- first-ever-pair classification from all prior history; and
- the frozen p90-minus-p10 kindness contrast.

The certified dynamic core reports that 92.93% of its corresponding exposure pairs were
first-ever meetings, indicating a large primary E1 sample while preserving a meaningful
repeat-pair secondary sample.

## Engineering decision

The production implementation should be staged and resumable:

1. B2 reuses the authenticated B1 sample and propensity files and checkpoints batches
   of conditional draws.
2. F2/E1 chronology work is sharded by authenticated speed-month input and writes only
   private state to XT_Pro.
3. User-history and pair-history reductions are independently checkpointed so a failure
   does not restart the chronology scan.
4. Only after both state builds authenticate may the downstream Stage 07 kindness
   estimators and four-slot Holm adjustment run.

No Patron/profile input is required or permitted.

## Interpretation guardrail

This gate establishes constructibility and support, not substantive results. The B2
sign, F2 stopping discontinuities, E1 re-pairing gradient, downstream kindness
coefficients, and four-slot adjusted p-values remain unknown at this freeze point.
