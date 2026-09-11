# Pool-main analysis reset ledger

No estimate from the former 47,587,020-row main sample is current merely because its old output still exists.

| Analysis family | Reset wave | Current status | Dependency |
|---|---:|---|---|
| Sample authentication | wave1 | recomputed | Certified report and all 24 panel files |
| Core tables, desert, game stage, persistence | wave1 | recomputed | Public Stage-08 producer |
| Panel robustness and payoff diagnostics | wave1 | recomputed | Public Stage-09 producer |
| Rating-gap / expected-score / K-RD decomposition | wave1 | recomputed | Surface package v1.0.0 |
| Nonparametric relative-strength closure | wave1 | recomputed | Engineering v1.1.0; same scientific estimands |
| Controlled reference-price diagnostic | wave1 | recomputed | Model v1.1.0 plus corrected display v1.1.1 |
| Equality/FEN commonness audit | wave2 | stale | Must rebuild position-frequency cache |
| First/repeat-meeting and any-repeat-dyad analyses | wave2 | stale | Reuse chronology, rebuild sample joins |
| A1/A3/B1 core dynamics and A1 audits | wave2 | stale | Rebuild first eligible exposure and histories |
| Second-wave and Campaign dynamics | wave2 | stale | Depends on rebuilt dynamic core |
| C7R/C7X targeted memory and C6/C9 retrofits | wave2 | stale | Rebuild focal flags and samples |
| Chooser-leniency IV/placebo | wave2 | stale | Rebuild instruments and ordinary-game placebo samples |
| Patron matching, primary, and addendum | wave3 | stale | Recompute chooser signals and matching; preserve snapshot-date caveat |
| Unified figures, tables, manuscript numbers | wave3 | stale | Only after all upstream receipts pass |

The selected sample is the pool/observed-predecessor-nonadjacent panel. It is not certified as literal end-to-start-rematch-free.
