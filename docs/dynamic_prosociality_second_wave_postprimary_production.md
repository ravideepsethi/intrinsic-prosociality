# Dynamic second-wave additional analyses v1.0.2

This package runs additional robustness, descriptive, and mechanism analyses
using the completed dynamic second-wave outputs and their authenticated private
checkpoints.

## What it runs

- E1 with chooser, month, and interacted pool-cell fixed effects, using both
  chooser-clustered and chooser-by-assignment-unit two-way clustered inference;
- E1 support, coarsening, and risk-decile diagnostics;
- B2 at ten horizons under 4,999 conditional randomizations, with both
  opportunity-weighted and chooser-equal estimands;
- B2 contributor, chooser-distribution, and payoff-group diagnostics;
- a personal-peak salience offset curve over eleven offsets;
- personal-peak kindness models at RD limits 110 and 80; and
- individual round-number coefficients and threshold descriptives.

All requested specifications are exported, including null and contradictory
results.

## Runtime and resumability

Expected wall time is approximately **30 minutes to 3 hours** on the source Mac
and XT_Pro volume. The 7.7-billion-row chronology is not rebuilt. Cached
histories and E1 scores are reused. B2 randomizations checkpoint in 250-draw
batches; rerunning the launcher authenticates and resumes them. Other bounded
phases rerun if interrupted.

## Repair and resume from v1.0.1

Version 1.0.1 correctly repaired and committed the earlier partial installation,
then stopped at the first E1 reproduction guard. The source and recomputed row
counts, identifying sample, chooser clusters, coefficient, and standard error
had already matched; only a separately recomputed derived p-value triggered the
stop.

Version 1.0.2 compares the primitive estimates and independently verifies that
each reported p-value is consistent with its own coefficient and standard
error. This avoids requiring two valid floating-point recomputations to produce
an identical derived value. The same correction is applied to the later
personal-salience and round-number reproduction guards.

The launcher accepts only the exact clean v1.0.1 repository commit (or its exact
v1.0.2 repair child). It also migrates only the exact empty private startup state
left by the v1.0.1 stop: `CONFIG.json`, an empty `b2_randomizations` directory,
and at most the empty `duckdb_temp/model_E1` directory created while assembling
the first model. Any data file, additional checkpoint, or unrelated repository
change causes a fail-closed stop. The analysis definitions are unchanged, so the
v1.0.1 analysis document is retained without alteration.

## Repository files

The launcher installs and pushes:

- `code/11a_estimate_dynamic_second_wave_postprimary.py`;
- `code/test_dynamic_second_wave_postprimary_synthetic.py`;
- `docs/dynamic_prosociality_second_wave_postprimary_analysis.md`;
- `docs/dynamic_prosociality_second_wave_postprimary_production.md`; and
- the corresponding entries in `manifests/script_hashes.tsv`.

The retained `postprimary` filenames are internal compatibility names. The
documents and exported results describe the work simply as additional analyses.

## Privacy and output

No Patron or profile input is used. Account identifiers, pair identifiers, game
identifiers, histories, and score assignments remain under private XT_Pro
derived-data roots.

On success, the launcher writes one compact aggregate ZIP and SHA-256 sidecar to
`/Users/u6025368/Desktop/Lichess_Desktop`.
