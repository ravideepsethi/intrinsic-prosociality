# Patron Wave 3B2 v1.0.1 repair

The reported v1.0.0 run authenticated its sources and completed the input
stage, then failed before any rematch model was estimated. The frozen
Wave 3B1 producer writes `chooser_models.json` as a list of model objects.
Wave 3B2 incorrectly read it with the shared authority loader, which requires
a JSON object.

`runner/families.py` now reads that catalogue with a dedicated, validated
list-of-objects reader. The authority loader continues to require objects.
The two core-model reproduction checks remain mandatory and retain their
original coefficients, standard errors, sample-size and specification checks.

The nine-test suite now includes:

- Authentication of the bundled Wave 3B1 result archive and its listed files,
  loading all 34 actual model records, and rejecting invalid catalogue shapes.
- Running the frozen Wave 3B1 producer on synthetic data, then exercising
  both Wave 3B2 core reproduction fits and checkpoint reuse. Altering a
  reference coefficient must still fail the numerical reproduction check.

All frozen source modules, authority files, evidence archives and analysis
scope are byte-identical to v1.0.0. Only the catalogue reader, tests, release
version and packaging documentation change. `ANALYSIS_SCOPE.md` retains the
v1.0.0 scope heading intentionally. No additional analysis family is added.

The new package manifest and version generate a new configuration under the
existing `wave3b2_patron` state directory. The short input stage is repeated;
the failed v1.0.0 configuration is preserved. Once v1.0.1 has completed a fit,
rerunning the same v1.0.1 command and settings reuses that checkpoint.

Expected compute remains 1–3 hours, excluding time waiting for a C9 lock.
This is a planning estimate for the prior Mac configuration, not a full-data
benchmark. The private panel is unavailable in the build environment.

The superseded v1.0.0 ZIP SHA-256 is
`e51f59cd29aa962d6da6903efed4343aea67cd19cea9f9116e14c7229356148c`.
