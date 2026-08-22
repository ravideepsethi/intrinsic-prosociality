# Dynamic prosociality second-wave production recovery v1.0.3

This package resumes frozen second-wave run `20260822T150914Z` after a deterministic
partition-support failure in the shared-history producer. It supersedes recovery
launcher v1.0.2 for this run.

## Preserved completed work

The package authenticates and preserves:

- producer commit `1418976974e1b7857407f1b2a717a5c11f9c88a1`;
- the fixed private run authority and run ID;
- the completed B2 aggregate;
- all 686 selected-source checkpoints;
- the 685,731-row sampled Stage 07 target checkpoint;
- the 309,961,276-row user event layer; and
- the 154,693,194-row pair event layer.

None of those artifacts is rebuilt or overwritten.

## Repair

Sampling used `H % 50 == 0` and event bucketing reused the same `H % 16`. Since
`gcd(50,16)=2`, only even event buckets can exist. Producer v1.0.0 stopped when it did
not find odd bucket 3. Producer v1.0.1 creates typed, zero-row checkpoints only for the
mathematically impossible odd buckets and continues to fail closed if an attainable
even bucket is missing.

The recovery changes no sample, estimand, model, statistical test, or result contract.
The package commits and pushes the repaired history producer, expanded integration
test, recovery note, and production protocol before history processing resumes.

## Remaining runtime

Expected remaining wall time is approximately **6--36 hours**, depending on XT_Pro
throughput. The expensive chronology projection and event-layer reductions have
already completed. The remaining work processes the populated history buckets, builds
E1 monthly scores, estimates E1/F2 models, and writes compact aggregate outputs.

Rerunning the same launcher resumes authenticated checkpoints. It does not rerun the
completed B2 randomizations.

## Storage and privacy

Account identifiers, sampled games, event layers, running rating peaks, pair histories,
and score assignments remain private under:

```text
/Volumes/XT_Pro/lichess_kindness/derived/replication/dynamic_second_wave_*_PRIVATE
```

Only compact aggregate outputs are included in the transfer ZIP. No Patron/profile
input or API request is used.

## After completion

The run does not commit its results. The next gate is an aggregate semantic and
numerical audit. Only an audited compact receipt should later be frozen in GitHub.
