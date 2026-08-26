# Dynamics Paper 2 Campaign 1 v1.0.8 numerical-recovery record

**Written after the authenticated v1.0.1 fail-closed run and after C7 and C12
outcomes had been processed.** This is therefore a post-outcome computational
correction, not a preregistration. The correction does not select models by
sign, magnitude, or significance.

## Authenticated triggering event

The returned v1.0.1 result ZIP has SHA-256
`805e7b19a5aff4bca5a86880cee6aae12342ba4ceba85d8491d65c841fbd3100`
and matched its uploaded sidecar. Its internal public-result manifest and all
54 collected files authenticated exactly.

The run completed and publicly preserved C6/C10 and C7. C12 then:

- exactly reproduced 345,138 focal rows;
- exactly reproduced storage buckets `[0,2,4,6,8,10,12,14]`;
- completed all eight recipient-history partitions;
- froze the full outcome-blind support;
- completed the outcome-model Parquet; and
- successfully fit the five models preceding its chooser-rating-band loop.

It stopped in a chooser-rating-band model with:

`HDFE absorption did not converge: iterations=2000 last_adjustment=6.411e-06`

The v1.0.1 code did not print the band before fitting, so the failure record
does not identify which eligible band triggered the exception. v1.0.2 prints a
begin/end record for every model and therefore removes that ambiguity.

## Root cause

The estimator uses cyclic weighted demeaning across several high-dimensional
fixed effects. Its original numerical contract required a maximum absolute
demeaning adjustment no larger than `1e-9` within 2,000 cycles. A slow
exploratory subgroup missed that contract. The exception propagated through
the C12 module, so none of the already-computed C12 estimates were serialized
and C13 never began.

This was an orchestration defect. A numerical failure in one exploratory split
should be visible, but it should not delete other estimates or prevent later
authorized analyses.

## Frozen numerical-recovery policy

The same policy is applied without reference to any estimated sign, magnitude,
standard error, or p-value:

1. Attempt each model under the original strict settings: tolerance `1e-9`,
   maximum 2,000 absorption cycles.
2. Only if the error is specifically absorption nonconvergence, restart the
   same model once with tolerance `1e-7` and a maximum of 25,000 cycles.
3. Export the tolerance, iteration budget, realized iteration count, and final
   adjustment with every successful estimate.
4. If the retry still fails, export both error messages, requested rows,
   requested chooser clusters, model role, and epistemic label; then continue.
5. Also retain genuine model-level nonidentification (no residual exposure
   variation, rank deficiency, insufficient rows/clusters, or singular linear
   algebra) and continue.
6. Any unexpected exception, authority mismatch, row-conservation failure,
   corrupt checkpoint, or I/O/programming error still fails the run closed.

The relaxed retry is a numerical recovery, not a change in estimand, sample,
outcome, covariates, fixed effects, clustering, or causal interpretation. C12's
planned models had already passed the strict setting in v1.0.1; the observed
failure occurred only after those fits in the exploratory band loop. All C13
models were already labeled exploratory (`X`).

## Checkpoint and evidence preservation

C6/C10 and C7 are imported from the authenticated v1.0.1 aggregate result and
are not recomputed. C12 uses the existing v1.0.1 private Parquets because their
construction completed before the exception. v1.0.2 authenticates the v1.0.1
state configuration and checkpoint contents before estimation and recomputes
the full checkpoint manifest afterward; any byte change is fatal.

C13 uses a new v1.0.2 private state. Its large tables are Zstandard-compressed
Parquet, its DuckDB construction uses eight threads, and its checkpoints are
resumable. Model fits are serial to avoid duplicating the 17.3-million-row
in-memory arrays.

## Reporting rule

Every authorized model is attempted in source order and appears either in the
estimate table or the model-attempt table. Extended successes and retained
failures are counted in module summaries. No result is omitted because it is
favorable, null, adverse, imprecise, low-support, or inconvenient. The C7 gate
remains failed, C7 remains exploratory/low-support, C13 remains associational,
and C12 remains a recipient-selection/targeting association rather than a
causal experience effect.
