# Provenance and scope

The user approved an exploratory ordinary-game placebo in the existing 7.7% metadata-known comparison subset, plus an independently selected smaller comparison pilot. This package implements the local exploratory exercise and freezes/queues the 200k pilot. It does not perform network retrieval and does not represent prepared data as a completed representative-sample test.

## Pinned completed evidence

- Validity-local report: `CHOOSER_LENIENCY_VALIDITY_LOCAL_REPORT_20260906T052017Z_46893.zip`
  - SHA-256: `ff14f791073667bb57324c5c80ca727bcdc2fb72e6d802a9d482386c12de9e7d`
  - Config SHA-256: `f472f94e84149d4ee75626b87977a46457bdb41ea69a29e44c82ab33f83cd46b`
- IV-pilot report: `CHOOSER_LENIENCY_IV_PILOT_REPORT_20260906T034402Z_47553.zip`
  - SHA-256: `e5cdcf5c9e27d858955fdeec3691b901c370a011db912602a6db3b6fc31c93eb`
  - Config SHA-256: `aacbd96652dd4c184e6694975c4fac7d38b028c5357b8bb937ce5c3a4578bc30`
- Stage07 certificate SHA-256: `8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7`

Both report archives are included as aggregate evidence, with their internal manifests verified before use. The original validity-local and IV-pilot source packages supplied in this conversation were read to establish exact file paths, checkpoint formats, metadata field definitions, and score construction. No new schema was inferred from filenames alone.

`iv_numerics.py` is copied unchanged from the completed pilot's code lineage. The runtime checks its SHA-256 against the original pilot config before using it. New functions for repeated recipient exposures, metadata reconciliation, independent sampling, and shared-account/date covariance are explicitly new and have synthetic tests.

## Source-derived facts used by the code

The completed frame has 1,912,023 games; 147,420 have source and minimum metadata, including 133,753 explicit pool games. These counts are reproduced before further analysis. The raw response pass extracted 189,452 metadata rows in 5,877 nonempty files. Reading those small extracted files suffices; the script does not repeat the raw saved-API scan.

The frame retained one pseudorandom recipient orientation per game and did not condition inclusion on source or terminal outcome. The 200k pilot retains that orientation and samples with a new fixed SHA-256 seed based only on exact game IDs. It is a reproducible subsample of the original frame, not a reconstructed risk set of the Lichess matchmaker.

The JSON game exports do not establish an absence of chat, takeback requests, or transient disconnections. The code never invents those variables.

## Validation

`VALIDATION.json` and `VALIDATION_TEST_LOG.txt` distinguish actually executed tests from Arrow integration tests unavailable in the assistant runtime. The production launcher refuses to proceed unless those Arrow tests execute and pass locally. No actual private XT_Pro data were accessible to execute the new analysis here.
