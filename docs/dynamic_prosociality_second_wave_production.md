# Dynamic prosociality second-wave production recovery v1.0.2

This recovery package supersedes launcher package v1.0.0. That launcher passed all
pre-mutation tests, copied the frozen producers into the repository, and then stopped
at `git diff --check` because three metadata lines in the implementation amendment
used Markdown hard-break spaces. It stopped before staging, committing, pushing, or
reading any second-wave outcome.

The original launcher had already staged those seven package-controlled changes when
its cached-diff whitespace check stopped. Recovery v1.0.1 incorrectly expected the
same contents to be unstaged and therefore also stopped before any mutation. Recovery
v1.0.2 authenticates the exact staged state: six added files and the modified script-
hash manifest, with both working-tree and Git-index bytes checked against the failed
v1.0.0 package. It then replaces only those package-controlled files and changes the
three metadata lines to a Markdown list. Because the producers authenticate the
amendment by SHA-256, their embedded amendment hash and the script-hash manifest are
re-frozen accordingly. No estimand, sample, model, test, execution setting, or output
contract changes.

This authenticated package freezes and runs the four-slot second-wave family:

- **B2:** first-observed-grant dynamics relative to 4,999 exact conditional draws;
- **E1:** the past-only, leave-focal-pair-out shadow of future interaction;
- **F2-R:** a round-number reference-point contrast, gated by Lichess stopping salience;
- **F2-P:** a prior personal-peak contrast, gated by Lichess stopping salience.

The producer does not use Patron/profile data. F1 remains retired.

## Pre-outcome freeze

The launcher first authenticates either clean Git HEAD
`55124c10f746a6de6e5c186c8ddf7796fef5fb2a` or the exact staged v1.0.0 state at that
HEAD. It installs the three producers, synthetic integration test, production
protocol, and dated v1.0.2 implementation amendment, updates
`manifests/script_hashes.tsv`, commits, and pushes. It makes no second-wave outcome
read unless that push succeeds. On a later invocation, it accepts the already-
committed identical producers and resumes.

## Runtime and resource use

Expected first-run wall time is approximately **12--48 hours**, depending primarily on
XT_Pro sustained throughput. The broad range is deliberate: the source projection must
scan the canonical 7.76-billion-row chronology once. B2 and the chronology projection
run concurrently. The downstream salience, E1 monthly scores, and kindness models run
after their private histories authenticate.

The launcher requires at least 300 GiB free on XT_Pro. It uses four one-thread source
workers, three B2 workers, 16 user/pair history buckets, projected Parquet columns,
Zstandard checkpoints, DuckDB 1.5.2, and single-threaded BLAS inside workers. This is
designed for the work Mac plus XT_Pro rather than a high-memory server.

## Resumption

Run the same command again after an interruption. A private run authority on XT_Pro
fixes the production Git commit and run ID. Valid source-file, event-layer,
identifier-bucket, B2-randomization, and E1-month checkpoints are reused. A partial or
hash-mismatched checkpoint fails closed rather than being silently overwritten.

## Storage and privacy

All important files are on XT_Pro:

```text
/Volumes/XT_Pro/lichess_kindness/derived/replication/dynamic_second_wave_*_PRIVATE
/Volumes/XT_Pro/lichess_kindness/output/dynamic_second_wave_*
/Volumes/XT_Pro/lichess_kindness/logs/dynamic_second_wave
```

Only compact aggregate outputs are copied into a transfer ZIP under
`/Users/u6025368/Desktop/Lichess_Desktop`. Account identifiers, selected-game rows,
running peaks, pair histories, and score assignments remain private on XT_Pro and must
not be committed or uploaded.

## After completion

The production run does not commit results. The next step is an aggregate semantic and
numerical audit. Only after that audit passes should compact results, receipts,
documentation, and hashes be frozen in GitHub.
