# Validation — 2026-09-28

Nine synthetic tests passed in 4.638 seconds in the available Linux execution environment. This is a correctness check on small fixtures, not a production runtime benchmark.

The tests cover exact matching with mixed case and whitespace; both player roles; one-time removal of a game involving both author accounts; retention of similarly named accounts; grant/row conservation; preservation of every retained field and source bytes; reuse of unaffected files; changed-input and changed-output checksum rejection; missing identity rejection; complete and incomplete numeric mappings; refusal to infer a mapping from extension-only IDs; conflicting ID rejection; mixed-schema extension views; and scope restrictions for the game index.

An end-to-end test ran the production inventory, two spawned file workers, report generation, filtered manifests, and the downstream consumer over synthetic fixtures for all 24 core months, all 24 main months, and one extension month. Only the production authority locations/checksums were replaced with explicit synthetic authorities. It confirmed 120 input main rows, 72 excluded rows, 48 retained rows, unchanged source checksums, numeric identity resolution, expected compact-target impact, and report ZIP/checksum creation. **These counts are test fixtures, not findings about the user's accounts.**

The Mac launcher passed `bash -n`. The finished ZIP and internal checksum manifest are verified separately during packaging. The user's row-level Mac data have not been available here, so production removal counts, identity mappings, runtime, and revised estimates are intentionally pending.

Test command:

```bash
python -m unittest discover -s tests -v
```

Dependencies used here: Python 3.12.14, pandas 2.2.3, DuckDB 1.5.5, PyArrow 25.0.1. The runner records the actual production environment in `ENVIRONMENT.json`.
