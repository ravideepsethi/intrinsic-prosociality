# v1.0.3 post-outcome correction: the operative price margin

Date: 2026-08-25

Status: frozen after the successful v1.0.2 opportunity-cost analysis and before
the v1.0.3 production reference-demand run.

## Why this correction exists

The successful v1.0.2 module estimated kindness with respect to the
`chooser_win_premium_v2`: the rating gain forgone by granting a draw instead of
claiming the timeout win. Its declared primary estimate was 0.1570280092 with a
95 percent interval of [0.1352348825, 0.1788211360]. That result is retained
unchanged. It is exploratory, associational, and now described precisely as an
opportunity-cost-premium elasticity.

After seeing that result, the conceptual target was revisited against the paper
and the consolidated handoff. Both distinguish two objects:

1. The forgone-win premium is the true economic opportunity cost.
2. The draw payoff is the drawn outcome's location relative to the chooser's
   pre-game rating and is the paper's operative, reference-dependent price
   margin.

The v1.0.2 premium elasticity therefore answers a legitimate secondary
question but not the central price-margin question developed in the paper. No
v1.0.2 file, checkpoint, output, estimate, or label is deleted or rewritten.
v1.0.3 opens a separate private state and public output lineage.

## Mathematical consequence

The draw payoff is signed. It is negative when granting the draw lowers the
chooser's rating, zero at the reference, and positive when granting the draw
raises the chooser's rating. A global quantity of the form

`d log Pr(kind) / d log(draw payoff)`

is not real-valued on this support. An elasticity at zero is also undefined.
v1.0.3 will not shift the variable by an arbitrary constant, take an absolute
value across both sides, delete zero mechanically, or otherwise manufacture a
global elasticity.

Instead, it reports:

- the signed draw-payoff demand schedule;
- the slope on the rating-loss side and the slope on the favorable side;
- matched-window and local-polynomial contrasts around zero;
- a conventional elasticity with respect to strictly positive loss magnitude,
  `max(-draw payoff, 0)`, estimated only on negative-payoff rows;
- gain-side responsiveness separately, explicitly not called a price
  elasticity;
- nonparametric signed bands and adjacent arc elasticities on each side; and
- the v1.0.2 premium elasticity as an immutable secondary result.

## Epistemic status

This correction was made after the v1.0.2 premium results were observed. Every
new v1.0.3 estimate is therefore exploratory (`X`). The certified Stage08 model
is reproduced as validation (`V`) before new results are interpreted. All
requested favorable, null, adverse, low-support, and numerical-failure results
are retained. Nothing is selected by sign or significance.

The module estimates a reduced-form within-chooser reference-dependent demand
schedule. It does not claim a causal price elasticity. It also does not impose
a prospect-theory or Kőszegi--Rabin value function. A structural subjective
cost would require identifying `v(win payoff) - v(draw payoff)`; this module
does not pretend that primitive has been recovered.

## Immutability and disclosure

- v1.0.2 remains the complete opportunity-cost-premium analysis.
- v1.0.3 may authenticate and read the successful v1.0.2 private model Parquet,
  but writes nothing to the v1.0.2 state.
- If that cache is absent, v1.0.3 builds a separate ZSTD-compressed Parquet in
  its own private state from the certified Stage07 authority.
- No private row-level Parquet enters the public result bundle.
- No API, profile, Patron, chronology, Git, or earlier-output mutation occurs.

