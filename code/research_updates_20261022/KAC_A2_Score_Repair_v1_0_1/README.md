# A2 score repair

The original A2 run completed, but its score reader discarded many node-limited
searches whose final update was a bound. Do not use its trajectory-adjusted
coefficients as validated paper results. See `REPAIR_NOTES.md` for the audit and
the separate stale-flag hazard, including what the live engine test did and did
not establish.

Put `KAC_A2_Score_Repair_v1_0_1.zip` in `$HOME/Desktop/Lichess_Desktop`.
Run the Terminal command supplied with it. Default settings use the existing
project `/Volumes/XT_Pro/lichess_kindness` and up to 10 workers. The command
resumes completed work and does not fetch games or profiles.

## Expected runtime

Allow roughly **2–5 hours** for planning, plus about **5–15 minutes** for the
inventory, feature projection and regressions. This is not a measured repair
runtime. The last full run took 8h41m. Only unavailable scores are researched,
with repeated FENs deduplicated globally. The inventory first prints the exact
number of required unique positions and a calculation using that earlier run's
throughput. A live ETA then replaces the planning estimate. Cached repair
reruns should take about 5–15 minutes. Preserve the external drive's output
folders so the caches remain available.

The old supported trajectories are 128,578 of 260,863 opportunities. At most
five old scores per unsupported game can need repair; terminal positions remain
unavailable rather than being invented. Raw score-status counts, deduplication
and actual runtime are written into the returned result.

## Output

A new `KAC_A2_REPAIRED_RESULT_<key>.zip` and its `.sha256` sidecar are written
to `$HOME/Desktop/Lichess_Desktop`. Upload both. The ZIP contains aggregate
coverage, score diagnostics, the same 53 model definitions, coefficients,
contrasts and the continuous profile. Private identifiers/FENs/score streams
stay on the external drive. A separate audit ZIP is written before engine work;
it is not the completed empirical result.

The three prior-disconnection-history tests remain pending. This package
repairs the A2 score measurement; it does not run arena, title or history work.
The original result and certified panel are preserved.

For a metadata/raw-score inventory only, append `--audit-only` to the launcher.
That separate audit identity performs no engine searches. For a nondefault
engine location, append `--stockfish /absolute/path/to/the/existing/SF18/binary`.
It must match the already pinned Mac executable hash.

## Files

- `RUN_A2_SCORE_REPAIR.command`: launcher and Python environment reuse.
- `score_stream.py`: individual-message score reader and retained exact score.
- `repair.py`: selective search, global FEN deduplication, authenticated caches
  and small per-unit Parquet replacement shards.
- `run.py`: frozen-lineage checks, audit, repair, regression rerun and export.
- `analysis_runner.py`, `design.py`, `estimate.py`, `report.py`: existing A2
  model machinery, with unchanged specifications and inference.
- `repair_test.py`: UCI protocol/engine, selective repair and resume checks.
- `self_test.py`, `integration_test.py`: original estimator/design tests.
- `verification_evidence/`: public-position live-engine test records.
- `original_evidence/`: the uploaded original aggregate result, preserved.

No Stockfish executable is distributed in this bundle. The production runner
uses the already installed, authenticated SF18 executable.
