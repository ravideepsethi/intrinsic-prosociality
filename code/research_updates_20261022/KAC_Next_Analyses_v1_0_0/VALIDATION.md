# Validation performed before delivery

## Code and inference checks

- Verified every bundled legacy v1.0.1 file against its original manifest and reproduced its manifest signature, frozen sample fingerprint and run key. The original acquisition code is unchanged.
- Verified own-last-move endpoints for both disconnected-player colors; signed loss direction; ±1,000-cp capping; exact mate versus finite/bounded/short scores; and material-balance sign.
- Verified reconstruction of saved clock logs, exact 10%-base boundary treatment, zero chooser-clock denominators, missing clocks and zero-base controls.
- Verified that an authenticated score-conversion checkpoint is reused without rewriting it; nonreturn games remain nonreturn, not fabricated finite observations.
- Generated every default design, including empty data and aliased mate/tail directions; matrices were finite and term names/shapes consistent.
- Compared within-chooser OLS coefficients and G/(G−1) clustered covariance against an explicit chooser-dummy regression.
- Verified that partitioning whole choosers reproduces unpartitioned moments and cluster-score covariance, and that baseline/proxy curve samples contain identical row IDs.
- Ran the complete synthetic 53-model workflow on 1,920 opportunities across 64 choosers with four spawned workers, including both estimator passes, aggregate tables and profile figure.
- Repeated that workflow and confirmed exact numerical equality and unchanged estimator-checkpoint timestamps.
- Exercised the optional history adapter and complete 62-model branch on synthetic history, including noncoverage and zero-start cases. A mismatched focal history cutoff was rejected. The full integration/resume/history check took 21.6 seconds in the preparation environment; it is not a benchmark of the Mac or actual engine workload.
- Python compilation and shell syntax checks passed. The lightweight tests run before a normal launch; the larger `integration_test.py` is optional and takes roughly 15–40 seconds.

## Existing empirical outputs and presentation checks

- Verified the exact SHA-256 and ZIP integrity of the supplied A1 result, frozen tenure result and corrected color-prediction result; source archives are included under `evidence/`.
- Rebuilt the evaluation/material figure, all 23 model summary rows, all planned contrasts and heterogeneity files from those aggregate results. No empirical regression was rerun or result invented.
- Reconciled the recovered tenure and Patron tables to their source model definitions. Corrected the five-band tenure range and the Patron age/control/inference description.
- Checked the primary color planning MDE against its exact scenario and retained the alternate scenarios.
- Rendered and visually inspected the figure and appendix tables. Compiled the appendix LaTeX and Section 3.2/figure insertion under the draft's Palatino font and 1.3-inch margins. Final isolated compilation had no undefined references or overfull/underfull box warnings. This is not a compile of the complete current manuscript.

## Not executed here

The external Mac drive is unavailable in the preparation environment. Actual missing-game retrieval, the pinned Mac Stockfish executable, current checkpoint availability, production Parquet schemas beyond the saved authorities, and new A2 empirical estimates therefore remain to be exercised by the supplied Terminal command. No claim of production completion is made. The source-readiness inventory is metadata discovery, not authentication of every proposed next-stage input. The history adapter validates its input contract; the all-game producer still needs its own semantic audit.

The default run leaves the prior-disconnection-history tests explicitly pending. A3 and later analyses have a work ledger and source gates, not newly computed results. No manuscript publication or external submission occurred.

## Checksums

`PACKAGE_HASHES.json` authenticates executable code, design documentation, legacy sources and immutable evidence. Generated files under `completed/` are excluded from that runtime code manifest so rebuilding them does not invalidate a run. `DELIVERY_SHA256SUMS.txt` records all delivered files, including completed exhibits, as packaged. Estimation identity includes the runtime code manifest, frozen target digest and optional history-manifest digest. Source/result ZIP digests are also listed in `evidence/RESULT_HASHES.json`.
