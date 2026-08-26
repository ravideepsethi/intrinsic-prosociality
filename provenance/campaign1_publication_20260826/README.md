# Publication provenance

This directory records the authenticated collection inspections and collection
manifests for the four result bundles published in this update:

1. corrected C1 and recovered C9;
2. canonical non-profile recovery v1.0.4;
3. opportunity-cost price elasticity v1.0.2; and
4. reference-dependent demand v1.0.3.

The collection inspections state that no private row-level files were included.
The manifests bind the public aggregates to the executed sources and archived
result bundles. Machine-specific absolute paths are provenance only and are not
expected to exist on a replication machine.

`PUBLICATION_RECEIPT.json` records the required repository base commit, source
bundle hashes, included scopes, and public-data boundary.
`PUBLICATION_INVENTORY.tsv` hashes every overlay file except itself; the outer
authenticated package additionally hashes that inventory.
