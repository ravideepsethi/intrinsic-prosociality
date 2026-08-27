# Patron Stage 10 strict-JSON publication correction

**Date:** 2026-08-27  
**Scope:** deterministic serialization correction only  
**Scientific values changed:** no

The immutable certified primary transfer is:

```text
PATRON_STAGE10_PRODUCTION_V101_RESULTS_20260827T011828Z.zip
SHA-256: 84c3067272a5adec9a4bfdfb5b84ffb7d7df8c6230b8ca49b5e1c696107768fd
```

Its public results contain three Python-JSON `NaN` tokens used for absent
metadata:

| File | Field | Certified token | Publication token |
|---|---|---|---|
| `_SUCCESS.json` | `primary_model.clusters` | `NaN` | `null` |
| `_SUCCESS.json` | `primary_model.drop_reason` | `NaN` | `null` |
| `chooser_primary_interpretation.json` | `primary_result.drop_reason` | `NaN` | `null` |

No coefficient, standard error, confidence interval, p-value, sample count,
status, interpretation, or privacy statement changes. The corrected
`chooser_primary_interpretation.json` has SHA-256
`dd28be4abd8f46b5c49e36da41b00d3236bfae5ec5f47930614d46391ff0fa4f`.
The publication report manifest has SHA-256
`d369d56bc24d38a3859b7071236d7e0fbe9577c8b3b4e171731d1cb2047be686`.

The certified original manifest and exact original non-strict receipt bytes
are retained under `provenance/patron_stage10_publication_20260827/` with
explicit `.txt` or `CERTIFIED_ORIGINAL` labels. The certified archive itself is
unchanged.

The transfer also contained one generated, unmanifested bytecode file:

```text
executed_package_source/code/__pycache__/patron_stage10_common.cpython-313.pyc
SHA-256: 7962031e1b15d86ba8b4ca3fda64cd5b191ceaf14d5beb70b5ffb7b219837f06
```

It is excluded from publication. All 16 files in the primary executed-source
manifest remain byte-identical to the certified transfer.

