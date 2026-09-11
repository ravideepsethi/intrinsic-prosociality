# E1 independent numerical and specification audit, recovery v1.0.1

## Recovery scope

The first audit attempt stopped before estimating any audit model. Its compact private
Parquet cache was built successfully, but the first parallel worker asked the Stage 08
exact two-way absorber to process 671 exact pool-cell levels. That established solver
has a deliberate 512-level applicability guard for its smaller fixed effect and failed
closed as designed.

The recovery does not raise or remove that guard and does not alter Stage 08. It removes
only the inapplicable Stage 08 benchmark from the audit's worker plan. The audit now
uses two independent, applicable implementations for the exact-cell coefficient plus
the pre-existing assignment-unit identification diagnostic. It writes to new v1.0.1
private-state and aggregate-output directories, leaving the failed v1.0.0 state intact.

## Purpose

The recovered audit addresses two narrow questions raised by the additional E1
analysis:

1. Does the exact-cell coefficient survive an independent fixed-effect solver that
   removes singleton-chooser numerical dust exactly?
2. What happens when the fixed effect is defined at the full score-assignment unit,
   calendar month by the pool cell at the score's actual coarsening level?

This is a numerical and specification audit of an already observed result. It does not
alter any earlier result table and does not treat repository timing as research
evidence.

## Inputs

The audit reuses:

- the locked 24-month Stage 07 Parquet panel;
- the already computed, past-only E1 monthly score Parquets;
- the source E1 aggregate result;
- the completed additional-analysis aggregate result.

It does not rebuild the 7.7-billion-row all-game chronology and does not call any
profile or Patron endpoint. Stage 08 is still authenticated and used for the applicable
source-E1 reproduction and numerical self-test before the audit cache is created.

## Private Parquet cache

The source panel is read once. The recovery writes a new compact,
Zstandard-compressed private Parquet model matrix containing:

- the outcome and re-pair-risk score;
- factor codes for chooser, calendar month, exact pool cell, and score-assignment unit;
- the numerical controls used by the additional E1 specification;
- score-support and coarsening diagnostics.

No raw account identifier is written to the cache. The factor codes and cache remain
private and are never included in the transfer archive. Three worker processes read
the same projected Parquet cache concurrently. BLAS is limited to one thread in each
worker to avoid oversubscription.

## Three parallel fits

### 1. Independent exact Schur solver

A separately implemented small-side Schur complement residualizes chooser and exact
pool-cell fixed effects. Calendar-month indicators enter as nuisance columns. Chooser
singletons are removed before residualization because their within-chooser transformed
rows are exactly zero. The 671 by 671 Schur system is within this solver's design. The
fit reports chooser-clustered and chooser-by-score-assignment-unit two-way clustered
inference.

### 2. Tight alternating-projection replication

This independently implemented fit absorbs chooser, calendar month, and exact
pool-cell fixed effects directly. It recursively removes fixed-effect singleton rows,
then cycles the within transforms to a maximum group mean of `1e-12`, compared with
`1e-9` in the additional-analysis run. It reports chooser and two-way clustered
inference.

Its risk coefficient must agree with Fit 1 within `1e-8` per unit of risk or the run
fails. Its finite-sample covariance correction may differ slightly because calendar
month is absorbed rather than represented by nuisance columns; the standard-error
difference is reported as a diagnostic and is not subjected to a false equality rule.

### 3. Full score-assignment-unit identification diagnostic

This diagnostic absorbs:

- chooser fixed effects; and
- calendar month by the pool cell at the score's actual coarsening level.

It asks whether any re-pair-risk variation remains inside the unit that assigned the
score. For a first-ever pair, the leave-pair-out adjustment should be zero, so the
score can be constant within this unit by construction. Singleton observations are
recursively removed and the transform is solved to `1e-12`. If residual risk sum of
squares is at most `1e-8`, the output reports the model as not identified and leaves
its coefficient, standard error, confidence interval, and p-value blank. It never
converts floating-point dust into an estimate.

## Inference and scaling

The audit reports the p90-minus-p10 re-pair-risk contrast used in the earlier E1
tables. For the independent fits, covariance is reported both by chooser and by the
Cameron-Gelbach-Miller two-way combination of chooser and score-assignment unit.

The completed additional-analysis exact-cell result is included as a reference row,
not as a numerical equality target. This is intentional: the recovered audit is meant
to reveal whether tighter tolerance and recursive singleton removal change the result.

The audit is interpreted as follows:

- agreement of Fits 1 and 2 validates the independently recovered exact-cell
  coefficient and clarifies the identifying row count;
- Fit 3 maps the identification boundary by testing whether any
  within-assignment-unit score variation actually exists;
- none of the fits, by itself, proves strategic or non-strategic motivation.

## Public output

Only aggregate model rows, support counts, solver-agreement diagnostics, and file
hashes are archived. Account codes, game codes, the private Parquet matrix, and score
rows stay on the XT_Pro volume.
