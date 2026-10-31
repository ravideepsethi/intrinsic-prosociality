# Version 1.0.2: restore the certified missing-clock rule

The v1.0.1 terminal log confirms that the UTC fix resolved all 138,986 apparent
month mismatches. All 153 input-file checks and source-mask validation passed,
and the source partitions were built. The run then stopped at the monthly
opportunity check before producing analysis results.

The monthly check I added in v1.0.0/v1.0.1 incorrectly treated a missing
`disconnected_clock_last_obs_s` as an invalid observation. The frozen Stage 05
rule is explicitly:

```sql
disconnected_clock_last_obs_s IS NULL
OR disconnected_clock_last_obs_s >= 5.0
```

This is established by the exact original Stage 05 producer, recovered from
the project repository. Its SHA-256 is
`eb8f7e7629c323ee8d5a9f7d4a96b5f9982980189cf27500289582457f0dfe80`, matching the
producer hash recorded in the original Stage 07 certificate. The recovered
Stage 07 producer and certificate also match the hashes already required by
the arena input authenticator. This restores the original sample rule; it
does not redefine the study sample or waive an original production check.

The v1.0.1 log combines all monthly failure predicates into one generic error,
so it does not supply the number of missing clocks or separate counts for the
other predicates. Version 1.0.2 writes `validation/opportunities_YYYY-MM.json`
before accepting or rejecting each month. It records missing clocks, missing-
clock grants, and each failure condition. Recorded clocks below five seconds,
wrong timeout/rated status, wrong requested node budgets, missing outcomes or
evaluations, kind-draw alias mismatches, and kind draws without mating material
remain fatal checks. No observation is filtered to make validation pass.

New tests confirm that a missing-clock kind draw survives into both the
all-source narrow file and the arena full-width file, while a recorded clock
of 4.999 seconds is rejected and exactly five seconds passes. Other simultaneous
failures are individually named. Producer and certificate hashes are also
tested. The complete suite contains 19 passing tests.

The adjusted suppression/structural models retain their explicit complete-case
rules; these exclude unavailable controls from those models and report the
corresponding sample counts. This repair changes the erroneous build check,
not those regression specifications or any inherited structural estimator.

The new output namespace is `output/arena_replication_v102/`. Previous runs are
preserved. The first run repeats input authentication and builds fresh derived
files; later v1.0.2 invocations resume their own verified checkpoints. No API
downloads, Stockfish recomputation, or source-data edits are required.
