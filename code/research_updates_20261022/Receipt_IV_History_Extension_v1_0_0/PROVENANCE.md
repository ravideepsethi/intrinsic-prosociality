# Recovered-producer provenance

Prepared September 26, 2026. Runtime package version 1.0.0.

The runtime numerical module is copied unchanged from `Chooser_Leniency_IV_Pilot_v1_0_0` and is byte-identical to the one shipped with `Chooser_IV_Expanded_v1_0_0`:

`ef709b4ff6b37e410ecb4ad549f5bfdc0b798a4627dcfdd6cc4a757f982d2066`

The preserved pilot `run_iv_pilot.py` and `t0_reference.py` under `tests/original` are used only for offline synthetic projection tests. The package does not invoke their earlier collection or estimation workflows. Original file hashes are recorded in `authority/pins.json` and the package manifest.

The recovered expanded-IV `prior_authority.json` supplies the original history lineage and pilot reference-run identities. `reviewed_iv.json` binds the historical spaced-90-day analysis file; it is checked for preservation, not used as a new result.

The first-pass receipts supply normalized opportunity and November–January replay-target hashes. The reviewed repair input manifest supplies full opportunity-source hashes and observed schemas. The completed v1.0.3 result supplies monthly-cache hashes, diagnostic-cache identities and the three finalized timestamp audits.

Reviewed v1.0.3 result ZIP SHA-256:

`92bfd7bc5064a6e6de9b23d7ac35e513b2f1df525213bf1d730c4f42d3d32fac`

The new chronology inputs use separately labelled fresh byte bindings at inventoried locations; those should not be described as independently pinned producer hashes. No new source labels, display phases, mechanics deployment times or incident denominators are inferred.

`PACKAGE_MANIFEST.sha256` binds every distributed file other than itself. The separate ZIP checksum binds the archive. Private production data are not included.
