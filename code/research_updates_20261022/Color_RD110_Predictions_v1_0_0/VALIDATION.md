# Validation performed before delivery

Validation date: 26 September 2026, UTC.

- Twelve numerical tests passed: payoff identities; color signs and both premiums; exact index change against a complete old/new design for all seven models; zero direct change for a pure displayed-gap response; extreme-offset baseline calibration; aggregate baseline matching; calendar boundary and missing-week handling; equal-week weighting; reproducible centered moving blocks; two-sided MDE behavior; and probability-mixture awareness.
- One synthetic end-to-end test passed using 4,386 artificial opportunities over the full 24-month calendar. It exercised all 16 reviewed coefficient snapshots, baseline sensitivities, reports, plots, conditional power and ZIP export. The artificial outcomes are not research estimates.
- The end-to-end test repeated from completed checkpoints, required identical results and byte-unchanged per-fit caches, checked that source files were unchanged, verified grant counts stayed as integer counts, checked public tables for row-level identifiers, and confirmed changed source files fail authentication.
- Python compilation and Bash syntax checks passed.
- Package manifest and ZIP integrity were checked after packaging.

The production Mac dataset has not been run in this environment. Production estimates and runtime are not claimed. The updated output is pre-policy transport and conditional planning; it is not a post-policy behavioral test. No ordinary covariance-based confidence interval is attached to constrained fits.
