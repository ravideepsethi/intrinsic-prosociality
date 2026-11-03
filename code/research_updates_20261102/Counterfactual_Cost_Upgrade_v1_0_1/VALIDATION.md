# Validation before delivery

Seventeen tests passed on October 24, 2026 using Python 3.12.14, NumPy 2.3.5,
PyArrow 26.0.0 and DuckDB 2.0.0. The production launcher accepts compatible
existing installations, including the earlier project versions.

Checks cover:

- The core rating formula against the byte-identical pinned scalar producer.
- Common K despite different stored outcome volatilities, including a binding
  volatility cap.
- Independent outcome-specific volatility and RD in the additional-period
  sensitivity.
- Gain regulation, bot halving, rating floors, change caps, reset behavior,
  and historical operation order.
- Integer-display brackets, observed zeros, missing values and merged moments.
- Excluding author games in either role, the no-mating-material action cost,
  and independence of counterfactual predictions from realized rating changes.
- Rejection of stored-cost inconsistencies and conflicting bot flags.
- Authentication of the preferred author-excluded manifest and original-panel
  fallback, including rejection of a different parent.
- A complete 24-month synthetic run with spawned workers, all four report
  checkpoints, exact cost summaries and game-ID uniqueness.
- Partial-month-set resume and completed-run reuse.
- Detection of corrupted outputs and changed inputs; report archive checksums.
- The platform material predicate on 21 explicit positions for each chooser
  color, including lone bishop/knight exceptions and same-color bishops.
- A recorded win failing the historical screen is retained with a positive
  action cost when the source-based platform rule permits it.
- Residual material/result conflicts remain in validation with NULL action
  costs, rather than terminating the run or receiving imputed zeros.
- New draw classifications remain separate from the stored kind-draw outcome.
- The unchanged earlier Pool_Rating_Validation `consume` function produces
  identical primary samples and old-formula metrics on the synthetic rows.

Python and shell syntax were checked. Source snapshots were verified against
their Git blob hashes. No production analysis on the user's 41.5 million rows
was run in the development environment; no empirical improvement is claimed
before that run returns.

To run the tests locally from the package directory:

```bash
python3 -m unittest discover -s tests -v
```
