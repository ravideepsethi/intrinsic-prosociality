# Validation

Performed on 23 September 2026 using synthetic account panels and the unchanged bundled v1.1.2 numerical engine. The production account arrays are not available in this workspace; no production wider-bound bootstrap has been run here.

- End-to-end execution with two spawned workers, two paired bootstrap draws and all four headline models: 8/8 selected fits successful; 38 optimizer attempts stored; all feasible-start guards pass.
- Independent reconstruction of each development/evaluation account-weight sequence matches the saved RNG fingerprint. All six comparisons per draw point to the matching original checkpoint score, and paired changes equal wider score minus original score.
- Source private point fits reproduce the published point scores; the completed point-bound sensitivity passes its lineage and checksum checks.
- All nonempty Parquet/CSV table pairs agree, allowing for CSV's representation of empty strings and nulls.
- Known-score aggregation with 120 synthetic result records reproduces sample standard errors, percentile endpoints and paired-change intervals, including a flagged capped draw. A two-draw report withholds intervals.
- Six-component instances of all four model restrictions have the expected raw and reported theta arrays. The common-theta models therefore support component-level reporting without incorrectly indexing a scalar.
- Restarting the completed two-draw run with one worker reuses both signed checkpoints. All 313 snapshotted source/checkpoint files retain identical bytes and modification times.

These checks validate execution, pairing, reporting and reuse. They do not establish statistical identification, optimizer global optimality, nominal bootstrap coverage near boundaries, or recovery on the real sample. Those remain empirical diagnostics.
