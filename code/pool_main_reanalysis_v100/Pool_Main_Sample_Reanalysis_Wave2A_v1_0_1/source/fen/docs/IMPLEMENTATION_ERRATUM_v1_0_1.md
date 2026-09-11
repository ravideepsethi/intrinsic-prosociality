# Equality/FEN audit v1.0.1 implementation erratum

## Scope

Version 1.0.0 authenticated successfully and then stopped in its end-to-end
synthetic self-test before any production run ID, production cache, or
production output was created. No production analysis of Stage 07 began and no
certified input was modified.

## Root cause

The v1.0.0 fixture used `chooser = row mod 1200` and selected engine evaluation
with `row mod 20`. Because 1,200 is divisible by 20, every repeated observation
for a synthetic chooser had the same evaluation and therefore the same
roughly-equal indicator. Chooser fixed-effect absorption correctly removed the
indicator completely. The synthetic run failed closed at E1 with zero
identifying rows.

This was a fixture-construction defect, not a defect in Stage 07 or evidence
about the production estimand.

## Corrections

Version 1.0.1:

1. constructs repeated observations so engine evaluation, month, speed, draw
   payoff, clock values, short-game status, and terminal position vary within
   synthetic chooser;
2. includes exact support at every frozen engine placebo knot;
3. creates deliberately unequal terminal-position frequencies so the FEN4 and
   board-commonness interactions have within-chooser support; and
4. adds component assertions for equality switchers, short-game equality
   switchers, commonness variation, exact placebo-knot support, and successful
   one-way and multiway fixed-effect fits.

## Frozen-analysis status

The v1.0.0 analysis plan remains frozen and unchanged. Version 1.0.1 changes no
sample definition, outcome, estimand, fixed effect, control, bandwidth, knot,
multiple-testing rule, interpretation threshold, privacy boundary, or
production authority. It writes to new `V101` public and private roots.
