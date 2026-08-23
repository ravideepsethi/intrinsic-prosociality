# E1 independent numerical and specification audit

## Purpose

This audit resolves two narrow questions raised by the additional E1 analysis:

1. Does the exact-cell coefficient survive an independent fixed-effect solver that
   removes singleton-chooser numerical dust exactly?
2. What happens when the fixed effect is defined at the full score-assignment unit,
   calendar month by the pool cell at the score's actual coarsening level?

This is a numerical and specification audit of an already observed result. It does not
alter any earlier result table and does not treat repository timing as research evidence.

## Inputs

The audit reuses:

- the locked 24-month Stage 07 Parquet panel;
- the already computed, past-only E1 monthly score Parquets;
- the source E1 aggregate result;
- the completed additional-analysis aggregate result.

It does not rebuild the 7.7-billion-row all-game chronology and does not call any profile
or Patron endpoint.

## Private Parquet cache

The source panel is read once. The audit writes a compact private Parquet model matrix
containing:

- the outcome and re-pair-risk score;
- factor codes for chooser, calendar month, exact pool cell, and score-assignment unit;
- the numerical controls used by the additional E1 specification;
- score-support and coarsening diagnostics.

No raw account identifier is written to the cache. The factor codes and cache remain
private and are never included in the transfer archive. Four worker processes read this
same Parquet cache independently.

## Four parallel fits

### 1. Existing exact two-way Schur solver

The existing Stage 08 exact solver absorbs chooser and exact pool-cell fixed effects.
Calendar-month indicators enter as nuisance columns, which is algebraically equivalent
to absorbing chooser, month, and exact pool-cell effects. This fit reports
chooser-clustered inference and serves as the established-code benchmark.

### 2. Independent Schur solver

A separately implemented small-side Schur complement residualizes chooser and exact
pool-cell fixed effects. Calendar-month indicators again enter as nuisance columns.
Chooser singletons are removed before residualization because their within-chooser
transformed rows are exactly zero. The audit reports chooser-clustered and
chooser-by-score-assignment-unit two-way clustered inference.

The coefficient and chooser-clustered standard error must agree with Fit 1 to tight
numerical tolerance. Disagreement is a hard failure.

### 3. Tighter alternating-projection replication

This fit absorbs chooser, calendar month, and exact pool-cell fixed effects directly.
It recursively removes fixed-effect singleton rows, then cycles the within transforms to
a maximum group mean of `1e-12`, compared with `1e-9` in the additional-analysis run.
It reports chooser and two-way clustered inference.

Its coefficient must agree with the two exact solvers. Its finite-sample correction may
differ slightly because calendar month is absorbed rather than represented by nuisance
columns.

### 4. Full score-assignment-unit identification diagnostic

This diagnostic absorbs:

- chooser fixed effects; and
- calendar month by the pool cell at the score's actual coarsening level.

It therefore asks whether any re-pair-risk variation remains inside the unit that
assigned the score. For a first-ever pair, the leave-pair-out adjustment should be zero,
so the score can be constant within this unit by construction. Singleton observations
are recursively removed and the transform is solved to `1e-12`. If residual risk sum of
squares is at most `1e-8`, the output reports the model as not identified and leaves its
coefficient, standard error, confidence interval, and p-value blank. It never converts
floating-point dust into an estimate.

## Inference and scaling

The audit reports the p90-minus-p10 re-pair-risk contrast used in the earlier E1 tables.
For the independent fits, covariance is reported both by chooser and by the
Cameron-Gelbach-Miller two-way combination of chooser and score-assignment unit.

The audit is interpreted as follows:

- agreement of Fits 1-3 validates the numerical coefficient and clarifies the true
  identifying row count;
- Fit 4 maps the identification boundary by testing whether any within-assignment-unit
  score variation actually exists;
- none of the fits, by itself, proves strategic or non-strategic motivation.

## Public output

Only aggregate model rows, support counts, solver-agreement diagnostics, and file hashes
are archived. Account codes, game codes, the private Parquet matrix, and score rows stay
on the XT_Pro volume.
