# A1 post-result audits

This directory contains the two authenticated, post-result A1 sensitivity
audits executed on September 1, 2026. They do not alter or reopen the frozen
primary family.

- `a1_evidence_gap_audit_v100.py` reproduces the certified headline and
  evaluates direct reciprocity, short-window/session proxies, reach,
  downstream opportunity composition, support, and temporal stability.
- `a1_unconditional_first_opportunity_audit_v100.py` reproduces the certified
  headline and companions, verifies all 24 Stage-07 Parquet authorities when
  requested, and estimates the first-later-opportunity outcome with complete-
  follow-up nonreachers coded zero.

Both scripts authenticate the frozen v1.0.2 core producer by SHA-256. Supply
the project root and input overrides shown by `--help`; raw and account-level
inputs remain outside this repository. The public aggregate outputs from the
executed runs are under `results/a1_evidence_gap_audit_v100/` and
`results/a1_unconditional_first_opportunity_audit_v100/`.
