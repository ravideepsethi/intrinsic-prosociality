# Verified profile gap fill and next analysis

The ZIP SHA-256 matches its sidecar; CRC is clean; the exact five-member inventory
contains the manifest and four listed files, all of whose hashes and lengths match.
The configuration hash is `2c3aaceee64b55d9efcfd718bc91b4b59ddb0670c36e32a5657700fec066195b`.
Its Wave-3A report, coverage-file and frozen August snapshot authorities agree
with the preceding packages. The report contains no row-level profile records.

| Missing group | Queried now | Recovered | Still unavailable |
|---|---:|---:|---:|
| Previously unqueried controls, all groups | 122 | 122 | 0 |
| Earlier nonreturns, all groups | 163 | 0 | 163 |
| Previously unqueried controls, primary comparison | 77 | 77 | 0 |
| Earlier nonreturns, primary comparison | 130 | 0 | 130 |

Primary rows overlap the corresponding all-group rows and must not be summed.
Three successful request rounds took 144.863 seconds. The earlier coverage gap
from an unqueried target is now closed at the new observation date. The profile
nonreturn gap remains. No unavailable account is classified as a non-Patron.

Proceed to the core Patron estimates. The new package binds the private September
supplement by its report receipts and exact Wave-3A missing-account membership.
It reports August-only estimates and an explicitly labelled supplemented
sensitivity. It does not treat September outcomes as recovered August outcomes.

The most useful comparison will be the main full-control association and the
fair-minus-clearly-worse contrast, including their standard errors, across these
two profile cohorts. Neither has been estimated by the gap-fill run. The next
package also reports full-target outcome bounds, whose locations depend on the
new estimates' observed Patron counts.

Runtime estimate for the next run: 10–30 minutes, offline. The production
estimation runtime has not yet been measured. Use `RUN_COMMAND.txt`; upload the
result ZIP and checksum printed by the launcher.
