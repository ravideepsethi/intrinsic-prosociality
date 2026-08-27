# Patron Stage 10 replication code

This directory contains the exact authenticated source lineages used for the
current-profile Patron analysis.

- `primary_v1_0_1/` is the certified primary lineage. Its package manifest
  authenticates 16 source files. A generated, unmanifested Python bytecode file
  present in the transfer archive is intentionally excluded here.
- `postcertification_addendum_v1_0_0/` is the separately certified
  secondary/sensitivity lineage. It authenticates the unchanged primary result
  and adds corrected missing-date controls, chooser-level five-state models,
  and continuous price count/rate companions.

The two lineages are intentionally separate. The addendum does not replace or
retroactively modify the primary estimand. Neither directory contains profile
rows, usernames, or private chooser/opportunity caches.

