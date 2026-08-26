# Campaign 1 aggregate results

These directories contain the canonical public aggregate outputs through
2026-08-26. See
`docs/campaign1/CAMPAIGN1_CANONICAL_STATUS_2026-08-26.md` for lineage and claim
boundaries.

- `c1_corrected_v105`: explicitly decoded chooser-perspective prior-result
  analysis. Earlier C1 estimates are invalid and are not included here.
- `wave0_c8_c14a_v100`: the previously certified C8 and C14A aggregate
  outputs, together with their schema and support receipts. Its
  `SERIALIZATION_CORRECTION.md` records a byte-preserving repair of one JSON
  receipt and retains the exact malformed original for auditability.
- `wave1_c2_c3_v100`: the previously certified C2 and C3 aggregate outputs.
  The included C1 files are status/schema receipts only; no superseded C1
  estimate is included or interpreted.
- `c9_recovery_v101`: serialization-only recovery from 20 authenticated
  randomization checkpoints; zero new randomizations.
- `nonprofile_recovery_v104`: canonical collection of C6/C10, failed-gate C7,
  C12, C13, and current family-D status.

Only aggregates are committed. The private row-level Parquet checkpoints remain
outside Git.
