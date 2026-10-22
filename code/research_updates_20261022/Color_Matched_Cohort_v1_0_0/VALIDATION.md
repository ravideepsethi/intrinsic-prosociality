# Validation — 26 September 2026

All 45 automated tests passed: 14 new matched-color tests, 13 unchanged shared-producer tests, and 18 inherited source/adjacency tests. These are executable synthetic and fixture tests, not a run on the user's archive.

The new tests cover UTC week resolution; omitted implementation/announcement weeks; preserved calendar gaps; strict fixed-roster activity boundaries; reuse of earlier monthly counts plus missing-account counts; corruption rejection; focal/simultaneous-start exclusion; zero prior history; needed-user union; rated-start exposure counts; joined player/state identity; old/new payoff parity; checkpoint reuse; all 14 state/model frozen-fit designs; color-reversal behavior; pre-rate calibration; forecast invariance to changed post outcomes; mechanical versus composition forecasts; conditional-only comparison labels; unknown-source window withholding; clock and missing-week gates; and ignoring the older rolling-regular flag when selecting the fixed roster.

The new shared-checkpoint test verifies the original membership key, reuse without rewriting its output, rejection of a different code identity, and rejection of corrupted output. The unchanged producer's 30 manifest entries were verified against its original package manifest. Its tests exercise real local source recovery, compression, missing/conflicting evidence, start-order ties, compressed/full adjacency equivalence, previous-status bridge checks, restart behavior, and membership construction.

The Mac launcher passed `bash -n`; the Python entry point's argument parser ran successfully. Package and ZIP member checksums were verified after assembly. The Mac-only `caffeinate` command and the actual mounted-volume run were not executed here. The remaining production gate is running the delivered launcher against the existing archive and reviewing its aggregate result ZIP.

Test environment: Python 3.12.14, NumPy 2.3.5, pandas 2.2.3, DuckDB 1.5.5, PyArrow 25.0.1, zstandard 0.25.0. Test dependencies were installed only in the isolated build environment; the Mac launcher installs nothing. SciPy is not imported by the new runner.

Initial development checks caught missing SQL `AS` aliases for reserved names; those were corrected before the passing run. No real matched-cohort counts, observed color effects, power values, or new deployment censors are claimed by this validation.

## Reproduce the tests

From the unpacked package, using a Python environment with `requirements.txt` dependencies:

```bash
python -m unittest discover -s tests -v
python -m unittest discover -s vendor/Receipt_IV_Cohort_Extension_v1_0_0/tests -v
PYTHONPATH="$PWD/vendor/Receipt_IV_Cohort_Extension_v1_0_0/vendor${PYTHONPATH:+:$PYTHONPATH}" \
  python -m unittest discover -s vendor/Receipt_IV_Cohort_Extension_v1_0_0/tests/original -v
bash -n RUN_MATCHED_COHORT.command
```
