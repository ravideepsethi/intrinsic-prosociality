# Pool-main reanalysis — Wave 2B2B1 v1.0.0

This checkpointed, offline runner rebuilds the next bounded tranche on the
certified 41,534,331-row pool/observed-nonadjacent main panel:

- the frozen C6 non-exploitation model and C10 denial-decay diagnostics;
- a separately labeled C6 ply > 10 robustness retrofit;
- C12 recipient pre-opportunity experience from a fresh deterministic 2% user
  sample, including the v1.0.3 2400+ attempt; and
- an aggregate-only frequent-dyad diagnostic for the current C7X classification.

The exact full-history dyad index is authenticated and reused read-only. Its
2,229,237,137-game census depends on the date window and all-game chronology,
not on which timeout observations enter the selected main sample. Rebuilding
that invariant census would add roughly 5–12 hours without changing the index.

The current C7X benefactor arm has only 125 observations. It therefore remains
below the frozen 1,000-per-arm parent gate. This runner reports raw dyad-stratum
counts and rates but deliberately does not fit subset fixed-effect models.

## Runtime and resources

Expected elapsed time is **35–75 minutes** on the previously used 10-core,
12-GB configuration, plus ordinary disk-speed variation. The run requires at
least 80 GiB free by default, makes zero network requests, and keeps all
account/game-level checkpoints on the external project volume.

The run is restartable. If interrupted, invoke `RUN_WAVE2B2B1.command` again;
authenticated checkpoints are reused and inconsistent partial state stops
fail-closed.

## Output

On success, the runner writes these two uploadable files to
`~/Desktop/Lichess_Desktop`:

- `POOL_MAIN_REANALYSIS_WAVE2B2B1_RESULTS_<UTC>.zip`
- `POOL_MAIN_REANALYSIS_WAVE2B2B1_RESULTS_<UTC>.zip.sha256`

Only aggregate tables, receipts, and executed source are transferred.

