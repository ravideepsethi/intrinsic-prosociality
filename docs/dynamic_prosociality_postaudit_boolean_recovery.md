# Dynamic Prosociality post-audit Boolean-recovery note

Producer version: 1.0.1  
Date: 2026-08-22 UTC  
Scope: implementation-only recovery after the v1.0.0 post-audit stopped  

## Incident

The authenticated v1.0.0 execution completed all 24 Stage 07 Parquet hash checks and
atomically created a 1,543,725-row private recipient pre-trend checkpoint. It then
stopped while converting the checkpoint's three non-null Boolean `pre_any_kind_*`
columns to NumPy arrays. PyArrow 24 refuses a zero-copy conversion for Boolean arrays,
raising:

`ArrowInvalid: Zero copy conversions not possible with boolean types`

No statistical estimate or aggregate result had been produced when the run stopped.

## Correction

Version 1.0.1 changes only those Boolean conversions by passing
`zero_copy_only=False` before casting the returned arrays to `float64`. It also adds a
synthetic regression test that exercises this exact conversion under PyArrow when that
dependency is available.

The analysis plan, samples, outcomes, support rules, weights, controls, fixed effects,
clustering, multiple-testing rules, and output definitions are unchanged.

## Checkpoint compatibility

The v1.0.1 producer recognizes exactly one prior resume configuration: the authenticated
v1.0.0 configuration SHA-256
`cf16f75cf04fb376b612a55f88506517dd4ecaac3f9ba4a3f41ae0aa670935eb`.
It accepts the prior private state only after authenticating both its configuration and
the saved pre-trend receipt against the checkpoint's actual SHA-256. The checkpoint is
then reused byte-for-byte; it is not rebuilt or rewritten.

This recovery remains API-free, reads no Patron/profile data, does not reopen any
primary result, and performs no Git mutation.
