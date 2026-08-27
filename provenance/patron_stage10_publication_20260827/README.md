# Patron Stage 10 publication provenance

This directory binds the GitHub overlay to two immutable authenticated result
archives:

1. Patron Stage 10 primary v1.0.1; and
2. Patron Stage 10 post-certification addendum v1.0.0.

`PUBLICATION_RECEIPT.json` records the required repository base commit, source
archive hashes, included scopes, exclusions, and public-data boundary.
`PUBLICATION_INVENTORY.tsv` hashes every overlay file except itself.
`PUBLICATION_PRIVACY_AUDIT.json` records the final path, extension, JSON,
identifier-header, and private-artifact scan.

The `primary_run_receipts/` and `addendum_run_receipts/` directories retain the
aggregate/cached-hash production receipts shipped in the authenticated
transfers. No private cache bytes are included.

The primary transfer's exact non-strict JSON receipt bytes and certified
original report manifest are retained here for auditability. Strict JSON files
under `results/patron_stage10/primary_v1_0_1/` are the publication-facing
copies. See the correction note under `docs/patron_stage10/`.

