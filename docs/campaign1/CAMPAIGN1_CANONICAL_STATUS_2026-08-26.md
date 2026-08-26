# Campaign 1 canonical status through 2026-08-26

This document identifies the canonical public Campaign 1 lineages after the
August 25--26 corrective and recovery work. It is a results-status record, not
a new analysis plan. The frozen plans and amendments remain authoritative for
the scientific specifications.

## Canonical lineages

| Module | Canonical lineage | Status |
|---|---|---|
| C1 | `c1_corrected_v105` | Corrected, authenticated, usable |
| C2 | previously certified Campaign 1 result | Usable; Holm pending |
| C3 | previously certified Campaign 1 result | Exploratory |
| C4 | none | Blocked on the full 24-month profile authority |
| C5 | none | Blocked on the full 24-month profile authority; final family-D Holm pending |
| C6 | `campaign1_c6_c10_v100`, published through `nonprofile_recovery_v104` | Confirmatory gate passed; usable |
| C7 | `campaign1_c7_v101`, published through `nonprofile_recovery_v104` | Prespecified 2% support gate failed; descriptive/exploratory only |
| C8 | previously certified Campaign 1 result | Exploratory |
| C9 | `c9_recovery_v101` | Recovered from all 20 authenticated checkpoints; usable |
| C10 | `campaign1_c6_c10_v100`, published through `nonprofile_recovery_v104` | Exploratory |
| C11 | none | Blocked on the full 24-month profile authority |
| C12 | `campaign1_c12_v102` plus `campaign1_c12_supplement_v103` | Secondary; all rating-band attempts retained |
| C13 | `campaign1_c13_v104` | Exploratory; completed after denominator and numerator-scope corrections |
| C14A | previously certified Campaign 1 result | Exploratory |
| C14B | none | Blocked on the full 24-month profile authority |

## Invalid and superseded lineages

- Both earlier C1 result lineages are scientifically invalid because they did
  not explicitly decode the physical `result_code` support `0, 1, 2` as
  `0=Black win`, `1=draw`, and `2=White win` before constructing chooser-side
  results. They remain historical evidence only and are excluded from every
  interpretation and family-D calculation.
- C9 v1.0.0 failed during publication after completing the randomizations.
  `c9_recovery_v101` authenticated the 20 existing checkpoints, drew zero new
  randomizations, and exactly reproduced B2 before serializing the result.
- The first non-profile production and intermediate recoveries failed closed.
  Their completed C6/C10, C7, and C12 aggregate outputs were preserved and
  authenticated. `nonprofile_recovery_v104` is the canonical collected lineage.
- C13's outcome-blind support denominator was corrected from 17,104,149 to
  17,101,141 rows before the ambient-kindness numerator was read. A later QA
  assertion had compared the 487,170 fair-sample kind draws with the 669,503
  all-Stage-07 kind draws. That sample-scope assertion was repaired before any
  C13 exposure or model was estimated. No C13 estimate selected either repair.
- Price-elasticity v1.0.0 and v1.0.1 failed closed before estimation. The
  successful opportunity-cost lineage is v1.0.2. The reference-dependent
  demand schedule is the separate v1.0.3 exploratory lineage.

## Family D

The five effective members remain C1, C2, C5, C6, and C9. C5 is still missing,
so the final step-down Holm table is not yet computed. Regardless of the
eventual C5 p-value, C1, C6, and C9 necessarily reject at 5% under the fixed
five-member family because each survives the five-test Bonferroni bound.

The C6 effect is in the opposite direction from the prespecified exploitation
prediction. It is a valid two-sided family-D result, but it rejects the proposed
positive exploitation mechanism rather than supporting it.

## Current headline aggregates

- **C1:** preceding loss minus win = +0.176413 percentage points; raw
  `p=0.0060467`.
- **C6:** mercy minus claim = -1.793744 clearly-losing timeout-disconnections
  per 1,000 rated games over 90 days; raw `p=5.3348e-7`. The mandatory
  unnormalized count and denominator diagnostics are published beside it.
- **C9:** later-session excess = +11.105202 percentage points; exact
  randomization `p=0.0004`.
- **C12:** low- minus high-recipient-experience contrast = +0.516804 percentage
  points; secondary raw `p=0.03371`.
- **C13:** focal kindness change per +1 percentage point ambient kindness =
  +0.082115 percentage points; exploratory raw `p=0.12366`.
- **C7:** only 33 benefactor-facing opportunities appeared in the frozen 2%
  pair sample versus the prespecified gate of 1,000. This is a support failure,
  not a null estimate.

## Claim boundaries

- C1, C2, C3, C10, C12, and C13 are not randomized causal effects.
- C6 inherits the A1 first-exposure design and may use only the same disciplined
  conditional/quasi-random assignment language defended for A1. Mercy versus
  claim does not separately identify a benefit of mercy from a harm of denial.
- C7's failed-gate counts do not support adjusted or clustered inference.
- C13 is an ambient association, not contagion or a causal peer effect.
- The price modules are exploratory. The opportunity-cost coefficient is not a
  causal price elasticity, and the reference-dependent object is a reduced-form
  demand schedule rather than one global signed-log elasticity.

## Public-data boundary

The committed results contain only code, documentation, receipts, hashes, and
aggregate CSV/JSON outputs. They contain no account-level rows, user IDs,
private Parquet checkpoints, raw PGNs, API objects, or Stockfish row-level data.

