# Country Profile First Pass v1.0.0

Run from the Mac connected to XT_Pro. Python 3.10+ is required. The launcher creates its own virtual environment and installs DuckDB, PyArrow, NumPy and SciPy. It makes no Lichess requests. Package checksums and certified source checksums are enforced.

```bash
bash RUN_FIRST_PASS.command --phase all --threads 8 --workers 4
```

Default project: `/Volumes/XT_Pro/lichess_kindness`.

Default output: `/Volumes/XT_Pro/lichess_kindness/output/country_profile_first_pass_v100/run`.

To review the first pass before the slower chronology scan:

```bash
bash RUN_FIRST_PASS.command --phase core --threads 8
bash RUN_FIRST_PASS.command --phase activity --threads 8 --workers 4
```

Re-run the same command to resume. For another disk mount use `--project /absolute/project/path`. For a relocated chronology use `--chronology-root /absolute/events_replay_sorted_time`. The source data must still match the bundled authority. A different package/input identity requires a new `--output` directory.

## What arrives

1. `00_*`: all flag/country and extraction disagreement counts, including code pairs, before fallback.
2. `01_*`: profile/flag/disabled coverage by acquisition role and snapshot source.
3. `02_*` and `model_flag*`: current chooser selection, board-state rates/gradients, match-cell comparisons and adjusted flag associations.
4. `03_*`: code distribution, explicit cleaning decisions and selected-sample country rates.
5. `04_*`: both-player support, country pair counts, same/different variation within choosers, and the chooser/recipient account union inventory.
6. `05_*` and `model_tv*`: TV visibility by rating tier, volume and state; recipient moderation descriptive sensitivity.
7. `06_*`: ordinary-game activity support, stable-year/offset sensitivities, setter/non-setter gradients and year-1-proxy/year-2-outcome comparisons.

The process prints `CORE_READY` and writes `COUNTRY_PROFILE_CORE_REPORT_v100.zip` before the activity phase. At full completion it writes `COUNTRY_PROFILE_COMPLETE_REPORT_v100.zip`. Both have SHA-256 sidecars. Upload the ZIP and its sidecar; do not upload PRIVATE.

## Runtime and space

The initial profile counts should finish well before the panel regressions. Core work hashes the certified panel and performs multiple projected scans and cluster-score passes: allow tens of minutes to several hours, depending on SSD and Mac. The ordinary-game phase is a separate large scan, potentially several hours or longer. It prints a byte-based ETA after completed files. Resume ETAs include reused files and can be optimistic. These are planning ranges, not benchmarked production timings.

Have at least 30 GB of free space on XT_Pro, with additional room for DuckDB spill. Default main memory limit is 6 GB; four chronology workers each have a 2 GB limit. Use `--workers 2 --worker-memory 2GB` on a machine under memory pressure. DuckDB memory limits do not encompass every allocation. No Stockfish evaluations are performed.

## Important boundaries

- No flag coverage, both-player sample size, or geographic conclusion is assumed.
- Primary adjusted models use August profiles. September profiles add coverage and pair-support sensitivity; observation dates are retained.
- No population weights are produced without the original eligible acquisition frame and rule. Exhausting a reservoir means inclusion probability 1 when all controls were acquired, not 0.
- The activity proxy is explicitly uncertain and cannot prove country or residence; incomplete histories remain unclassified.
- `tosViolation` does not expose boosting separately from engine marks.
- The +0.907 pp historical result is not a 'one-third more' estimate on this sample.
- See METHODS.md for exact bins, estimands, classification, uncertainty and limitations.

## Validation

`TEST_REPORT.json` records the synthetic integration tests executed before release. Tests cover flag conflicts/fallback, missing-versus-disabled profiles, current history rebuilding, same/different pair support, sparse LPM estimates and chooser-cluster standard errors against a dense calculation, activity circular wraparound, held-out phase construction and corrupted checkpoint rejection. Production regressions are not claimed to have been run here; the private source data remain on the Mac.
