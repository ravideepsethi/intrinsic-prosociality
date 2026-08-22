# Dynamic prosociality second wave: structural-empty-bucket recovery

- **Recovery version:** 1.0.3
- **Date:** August 22, 2026
- **Affected producer:** `10g_build_dynamic_second_wave_histories.py`
- **Affected producer version:** 1.0.0, repaired by 1.0.1
- **Frozen run ID:** `20260822T150914Z`
- **Timing:** after B2 completed, but before the shared history receipt or any E1/F2 model existed

## Failure observed

The authenticated second-wave v1.0.2 run completed B2 and both large event-layer
reductions. The history producer then stopped fail-closed at the first absent user
partition:

```text
USER_HISTORY_BUCKETS existing=0 pending=16 workers=4
DYNAMIC_SECOND_WAVE_HISTORY_FAIL_CLOSED:
RuntimeError: No user event files for bucket 3
```

No history `_SUCCESS.json`, second-wave results directory, or E1/F2 estimate was
created. The existing B2 aggregate completed successfully and is not affected by this
recovery.

## Deterministic cause

The frozen design retains a user or pair when its deterministic hash satisfies

```text
H mod 50 = 0.
```

The event-layer implementation then reused the same `H` to assign one of sixteen
processing buckets:

```text
bucket = H mod 16.
```

Because `gcd(50, 16) = 2`, every retained hash is even and therefore every attainable
bucket is even. Odd buckets `1, 3, 5, ..., 15` are mathematically impossible. DuckDB
correctly omitted those empty partition directories; producer v1.0.0 incorrectly
treated their absence as evidence of a damaged event layer.

The eight even buckets contain the complete frozen sample. No identifier, game,
opportunity, or event is missing.

## Recovery rule

Producer v1.0.1 preserves all frozen sampling hashes, sample membership, source
checkpoints, target checkpoints, and event-layer bytes. It makes only the following
operational changes:

1. An absent odd bucket is recognized as structurally empty.
2. The producer writes a typed zero-row Parquet checkpoint for that bucket so later
   `union_by_name` reads receive the same schema across all sixteen paths.
3. An absent even bucket remains a fatal error.
4. Structural-empty receipts record zero input files, zero output rows, and the exact
   output hash.
5. Existing v1.0.0 private checkpoints are accepted only after their complete legacy
   configuration is reconstructed and authenticated. Their checkpoint namespace is
   retained; the final aggregate receipt separately records the v1.0.1 producer
   configuration and recovery mode.

## Claim and design invariance

This recovery changes no estimand, sample, treatment, outcome, control, fixed effect,
randomization, salience gate, bandwidth, threshold, model, multiplicity family, or
execution seed. It does not inspect E1 or F2 outcomes. It repairs only the representation
of partition values that are provably outside the support of the frozen sampling rule.

## Required validation

The package integration test now verifies that:

- the congruence restriction implies exactly the odd structural-empty buckets;
- a missing even partition still fails closed;
- structural-empty user and pair checkpoints contain zero rows;
- their Parquet schemas exactly match the corresponding populated outputs; and
- the authenticated v1.0.0 private state is reentered without rewriting prior
  checkpoint receipts.

The recovery producer and this note must be committed and pushed before history
processing resumes. Aggregate results remain unfrozen until a separate semantic and
numerical audit passes.
