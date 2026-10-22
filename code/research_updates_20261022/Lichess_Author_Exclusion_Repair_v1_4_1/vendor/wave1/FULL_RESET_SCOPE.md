# Full analysis-reset scope

Changing the main opportunity sample changes more than denominators. It can change the first eligible exposure, repeat-opportunity order, benefactor/claimer histories, chooser classifications, matching eligibility, and therefore every dependent model. This ledger is the governing reset plan.

| Analysis family | Reset wave | State before rerun | Required rebuild |
|---|---:|---|---|
| Sample authentication | 1 | Ready | Check report, receipt, schema, row totals, byte sizes, and all 24 SHA-256 hashes |
| Core structure, desert, stage, persistence | 1 | Stale | Directly refit from selected panel |
| Panel robustness and payoff diagnostics | 1 | Stale | Directly refit from selected panel and new core receipt |
| Rating-gap / expected-score / K-RD | 1 | Stale | Rebuild private derived cache and all aggregates/models |
| Nonparametric relative-strength closure | 1 | Stale | Rebuild from the new K/RD cache; never reuse the former cache |
| Controlled reference-price diagnostic | 1 | Stale | Restage rows and refit model/display from selected panel |
| Equality/FEN commonness audit | 2 | Stale | Rebuild sample-position joins and position-frequency cache |
| First/repeat opportunity and any-repeat dyad | 2 | Stale | Rebuild opportunity order and dyad flags while retaining full chronology as upstream history |
| A1/A3/B1 dynamics and audits | 2 | Stale | Rebuild first eligible exposure, pre-exposure histories, and focal samples |
| Second-wave and Campaign dynamics | 2 | Stale | Run only after the dynamic core authenticates |
| C7R/C7X targeted memory and C6/C9 retrofits | 2 | Stale | Rebuild focal relationship flags and estimation samples |
| Chooser-leniency IV/placebo | 2 | Stale | Rebuild instruments and ordinary-game placebo samples |
| Patron matching, primary, addendum | 3 | Stale | Recompute chooser signals and matches; preserve the profile-snapshot date caveat |
| Unified figures, tables, abstract, manuscript | 3 | Stale | Replace numbers only after every upstream receipt passes |

No old sample-dependent estimate is current until its row above reaches a successful authenticated receipt. Full all-game histories may remain upstream inputs where chronology requires them; excluded focal opportunities are not erased from history without an explicit design rule.

