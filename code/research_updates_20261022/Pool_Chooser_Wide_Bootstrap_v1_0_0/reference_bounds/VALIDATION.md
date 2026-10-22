# Validation performed before delivery

These are synthetic software checks, not production estimates or evidence that the economic model is identified.

- Full CLI run on the existing authenticated synthetic v1.1.2 source, with two explicitly spawned workers, all ten models, and all three bound steps.
- All 113 supplied feasible-start comparisons passed in the two-start fixture. Every selected training objective was no worse than its preceding fit. Production defaults to four starts plus compatible-source starts.
- Every model's actual bound equaled exactly its source bound times 1, 2, or 4. The polish step therefore retained the original domain.
- For all ten model specifications, both wider domains contained the original domain; likelihood, penalty, and analytic gradient at the same original vector were unchanged to 1e-12 (20 comparisons).
- All 32 populated Parquet tables in the fixture agreed with CSV companions after normalizing CSV null representations.
- Repeating the run with one worker reused all 113 cached optimizer attempts, preserving their bytes and modification times.
- All 116 source-run files in the source snapshot retained their bytes and modification times across the resume and numerical checks.
- An active output lock rejected a second writer without changing any report file. An active source writer also blocked the sensitivity.
- The archived v1.1.2 producer was copied without changes and is checked against the source producer manifest on every run. Public source scores are reproduced before any sensitivity is fitted.

The source fixture had one completed bootstrap draw. The audit verified its signature, totals, and pair inventory. On production the same audit uses the source's recorded requested count (120 for the supplied run); it does not assume the synthetic count or discard capped draws.

The ZIP and internal SHA-256 manifest are generated after validation. Both launcher and supplied terminal block are checked for Bash syntax. Production numeric arrays are unavailable in this workspace; the actual wider-bound estimates must be run on the user's Mac.
