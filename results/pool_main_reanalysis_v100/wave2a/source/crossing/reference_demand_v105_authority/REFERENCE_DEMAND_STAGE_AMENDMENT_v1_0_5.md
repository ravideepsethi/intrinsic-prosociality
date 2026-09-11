# Kindness reference-demand game-stage amendment v1.0.5

**Frozen:** 2026-08-27, after certification of reference-demand v1.0.4 and
before executing any v1.0.5 model on physical data.

**Status:** append-only exploratory closure. Nothing in v1.0.5 rewrites,
relabels, or replaces the certified v1.0.4 estimates. The package first
reproduces all 141 v1.0.4 models from a newly augmented cache before any new
game-stage estimate may be interpreted.

## 1. Why this amendment exists

The Equality/FEN audit established that kindness falls steeply with game
length and that very short games are unevenly distributed over fairness
states. Before v1.0.4 was executed, this implied a clear additional
constraint: every near-zero rating-payoff analysis required explicit game-stage
adjustment and a long-game replication. The v1.0.4 package nevertheless reused
the immutable v1.0.2 private cache, whose schema did not retain `ply_count`.

That omission does not make the v1.0.4 estimands or execution invalid. It makes
v1.0.4 a certified no-ply baseline rather than the final closure. This
amendment records the omission directly and adds only the targeted analyses
needed to resolve it.

The separate costly-side and favorable-side `K`/`M` decompositions are labeled
post-v1.0.4 exploratory diagnostics. They were motivated by the pooled v1.0.4
finding that the association with `K` was much larger than the association
with expected-score distance.

## 2. Inputs and immutable authorities

The package authenticates:

1. all 24 certified Stage 07 Parquets and the Stage 07 success receipt;
2. the immutable v1.0.2 private fair-state cache;
3. the complete certified v1.0.4 aggregate transfer authority and executed
   source; and
4. the exact schema, row order, row count, outcome count, chooser count, and
   selected exposure fingerprints used to attach `ply_count`.

The original cache and Stage 07 inputs are opened read-only. A new private
v1.0.5 cache is written under a separate versioned root. No row-level file is
included in the transfer ZIP or Git-authorized output.

## 3. Deterministic ply attachment

The builder reconstructs the exact v1.0.2 ordering:

- chooser indices are assigned by the lossless physical chooser key;
- within chooser, rows are ordered by decision timestamp, archive ordinal,
  and game ID; and
- global row IDs are assigned by chooser index and chooser sequence.

Before attaching ply, the reconstructed mapping must agree row by row with the
immutable cache on row ID, chooser index, chooser sequence, month, price, draw
payoff, engine evaluation, and both displayed ratings. Any mismatch fails
closed. Ply must be a nonnegative integer on every fair-state row.

The eight bands are exactly those used by the Equality/FEN audit:

`0-4`, `5-6`, `7-8`, `9-10`, `11-20`, `21-40`, `41-80`, and `81+`.

Long games are defined prospectively as `ply_count > 10`.

## 4. Exact v1.0.4 replication gate

Using the augmented cache but ignoring its new ply columns, the package reruns
all 141 v1.0.4 models with the exact executed v1.0.4 code. For every model it
requires the same model name, support, cluster count, estimand inventory,
coefficient, and clustered standard error as the frozen v1.0.4 authority,
within `5e-10` percentage points. No new model is interpreted unless this gate
passes.

## 5. Common stage-adjusted controls

New models retain the v1.0.4 current-state controls: quadratic engine
evaluation, chooser and opponent clocks plus missingness, tournament status,
speed indicators, and the applicable calendar controls. They add seven
indicators for the eight frozen ply bands. Exact-zero and local models absorb
chooser and premium-20-bin fixed effects and use standardized linear and
quadratic month trends. E1-E5 and displayed-gap models retain their original
fixed-effect structures.

All uncertainty is clustered by chooser. All new estimates carry exploratory
label `X` and remain outside the Campaign 1 Holm family.

## 6. Frozen new model family

### 6.1 Exact-zero contrasts

For each `|D| <= w`, with `w` in `{0.5,1,2,4,6}`, estimate the three mutually
exclusive categories `D<0`, `D=0`, and `D>0`. Run both parameterizations needed
to recover exact-minus-costly, favorable-minus-costly, and
favorable-minus-exact clustered standard errors. Repeat on all fair rows and
on `ply_count > 10`.

### 6.2 Local piecewise shape

Within each window estimate separate loss- and gain-magnitude slopes plus
separate exact-zero and strictly-positive intercept terms. Repeat on all rows
and long games. These are descriptive local linear schedules, not regression
discontinuity designs.

### 6.3 Stage-adjusted E1-E5

Repeat every frozen E1-E5 model after adding ply-band indicators. Repeat the
same seven-model family on long games.

### 6.4 Side-specific magnitude decomposition

On costly and favorable rows separately, estimate `log K` and
`log|0.5-E|` jointly with chooser and month fixed effects, current-state
controls, and ply bands. Repeat in long games. Companion models use
`log|D|` with chooser and premium-bin fixed effects to preserve the scalar
loss/gain summaries. These side-specific models are explicitly
post-v1.0.4 exploratory diagnostics.

### 6.5 Displayed rating-gap schedules

Repeat the complete `-30` through `+30` pairwise schedule against `g=-1`
after adding ply bands, with and without `log K`. In long games, repeat the
targeted `-5` through `+5` neighborhood. Finally estimate one joint
`g in {-1,0,+1}` model on all rows and one on long games.

## 7. Interpretation boundary

Permitted claims concern robustness or non-robustness of a reduced-form signed
rating-payoff schedule to observed game stage. Even a stable long-game result
does not identify causal price effects: before November 2025 payoff sign and
displayed relative rating are mechanically equivalent.

The package cannot establish structural loss aversion, a causal regression
discontinuity, a unique zero kink, or a causal effect of playing longer.

## 8. Computation and mutation boundary

- DuckDB workers: 8.
- Memory ceiling: 16 GB.
- All 335 required models are checkpointed and resumable.
- Expected production runtime: approximately 60-150 minutes, most likely
  75-110 minutes.
- No API call, PGN download, dependency installation, Git mutation,
  certified-input write, or row-level transfer is authorized.
