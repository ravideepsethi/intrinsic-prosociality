# KAC Companion Recovery v1.0.2

Put this ZIP in `$HOME/Desktop/Lichess_Desktop`, extract into a fresh staging
folder, then run `bash RUN_RECOVERY.command --worker-budget 10 --io-workers 3`.
The launcher uses your existing compatible Python environment, runs tests,
and prevents overlap with earlier companion runners. It installs nothing.

## What this version does

1. Reuses all 24 validated focal projections and the four completed baseline
   and start-hour fits. Original outputs remain intact.
2. Audits the history timestamps and resolves the one affected June 2023 bullet
   game through a single public Lichess game export. It verifies the game ID,
   the analysis chooser's username from the certified panel, both players'
   ratings, rated/standard/bullet status, result, and June 2023 creation time.
   The verified time is floored to seconds to match the original chronology.
   A private one-row overlay supplies the correction; source Parquets are
   never modified. No account or opportunity is dropped. The public response
   is cached, so an ordinary resume does not make the request again.
3. Exports KAC_COMPANION_RECOVERY_AUDIT_<id>.zip. Upload this early archive while
   later work continues. If verification fails, history stays blocked and
   independent hour models continue.
4. Runs remaining receipt/IV models with rectangular LSMR least squares.
   This avoids the singular normal-equation solve that failed in v1.0.1.
   Identical fixed-effect tuples are compressed exactly using weights; original
   observations are retained in the fitted regression. Each residual column
   must meet the original fixed-effect orthogonality tolerance. There is no
   ridge or relaxed tolerance. Completed columns are individually checkpointed.
5. If the timestamp is verified, reuses compatible old prefix counts and
   computes the missing count, then builds sessions and repetition models.
   Hour-model failures do not prevent other independent models from running.
6. Exports PARTIAL and RESULT archives. Read STATUS.json: RESULT can contain
   both completed models and explicitly blocked analyses.

## Runtime estimates

- Initial validation and single-game recovery: roughly 2–10 minutes.
- Remaining hour models: roughly 10–60 minutes, provisional. The new solver
  passed small explicit-dummy comparisons and a 300,000-row stress test; it
  has not yet run on this complete Mac dataset.
- Remaining history and repetition, if recovery succeeds: roughly 2–8 hours,
  depending on saved counts, external-drive throughput, and available workers.
- Waiting for other jobs is additional. The budget is 10 total reserved workers;
  up to 3 simultaneous history scans, 4 monthly DuckDB threads, and one
  numerical-library thread per worker. No Stockfish search or full PGN reparse.

## Resume and diagnostics

Repeat the same command after interruption. New output lives under
`/Volumes/XT_Pro/lichess_kindness/output/kac_companion_recovery_v102/<id>`.
Adopted Parquets retain content hashes and explicit parent provenance. Source
state changes or damaged checkpoints are rejected. Timestamp correction
content is part of the repaired prefix checkpoint key.

`--stage hours` runs only the hour models; `--stage repetition` runs only
history/repetition; default is `--stage all`. Stage does not change run identity.
A2 is not rerun. Arena is recovered from its completed authenticated result.

Only the single public game key is sent to Lichess, through its existing game
export endpoint. No profile query, account identifier list, or bulk download is
made. On HTTP 429 the same game can be retried, at most three attempts. A failed
network or validation check leaves the source and sample unchanged.

Private bad rows, response, overlay, and solver column caches remain on the
Mac. Exported reports omit game/account identifiers. If a solver fails, its
unlabelled algebraic normal-system diagnostic is exported so the numerical
problem can be examined without another data scan; this diagnostic is not used
by the rectangular solver and contains no game IDs, usernames, or timestamps.

## Scope still open

Ordinary-loss analysis requires ending type and verified completion metadata.
The platform timeout-share control/exclusion and temporal-concentration incident
adjustment remain open. Exact-hour effects are an additional common-shock check,
not those promised tests. No new coefficient is certified until its returned
result is reviewed. See REPAIR_NOTES.md for the present status and test details.
