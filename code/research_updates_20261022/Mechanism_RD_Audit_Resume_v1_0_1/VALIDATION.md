# Validation

September 26, 2026. Three focused tests passed in 3.51 seconds on synthetic rows:

1. Adding a zero framing term to the nested gap model preserves its conditional likelihood exactly; unexpected feature mappings stop the repair.
2. A warm-started expanded-model fit meets the unchanged projected-gradient gate and reaches at least the nested likelihood. Replacing its failed validation fold preserves the other fold and unrelated model files, produces complete monthly scores, and omits switcher account IDs from exported fits.
3. A changed training population is rejected before fitting.

The synthetic tests use actual exact conditional-logit fitting and informative chooser-month validation groups. They do not run production data or the full Mac workload. Production convergence remains to be checked when the package runs against the user's cached 59,187-row training sample.

Python source syntax, shell syntax, archive CRC and archive-member SHA-256 checks pass. The delivered package pins the parent audit manifest and the reviewed parent score/fit hashes. Existing audit and mechanism cache directories are read only; repair outputs use a separate directory. No source account-level records are included in this ZIP.

The launcher runs the short test suite before starting. To repeat manually from this folder:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```
