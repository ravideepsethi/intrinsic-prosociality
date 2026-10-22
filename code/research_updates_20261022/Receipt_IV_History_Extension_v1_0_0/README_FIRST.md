# Receipt IV: 32-month history extension v1.0.0

This package builds the eight added months' all-source IV histories and two extended cross-fit reference-model arrays. It reuses the original 24-month histories and the completed v1.0.3 timestamp finalization. It does **not** certify a 32-month pool/nonadjacent cohort or estimate a new IV effect.

## Run

Put the ZIP and its `.zip.sha256` file in `$HOME/Desktop/Lichess_Desktop`. Use the accompanying launch command, or run `RUN_HISTORY_EXTENSION.command` from a freshly extracted package. The default project is `/Volumes/XT_Pro/lichess_kindness`; Python is the existing `venv/bin/python` under that project. Nothing is installed or downloaded.

The launcher checks package hashes, prevents sleep, limits numerical-library threading and writes a timestamped log to Lichess_Desktop. It uses at most four concurrent month-building processes with one DuckDB thread each; serial DuckDB checks may use ten threads. The default DuckDB memory allocation leaves headroom inside an 8-GiB planning budget. This is not an operating-system RSS limit.

The project drive must be mounted, and the original histories, first-pass outputs and v1.0.3 caches must still be at their recorded paths. Allow space for new private Parquets and possible DuckDB spill files. No old output is overwritten. There is no automatic fallback to a rating replay, Stockfish run, API collection or prior repair producer.

## What the command actually does

1. Authenticates the existing 384 history shards covering November 2023–October 2025, the historical IV analysis file, original pilot reference deltas, normalized opportunity files, full opportunity source panels and saved anchors. Exact fingerprint-matched SHA checks are reusable.
2. Reconstructs November 2023 as a compatibility check. A full multiset comparison must match the original IV projection, including identities, decision times, game order, outcome, training arm and state cell. This bridge is not used to replace the old month's history.
3. Builds 16 history shards and a reusable feature Parquet for each of September–October 2023 and November 2025–April 2026. The expected added-month total is 15,938,535 rows. The expected full history total is 63,525,555 rows. These are all-source opportunities, not eligible IV exposures.
4. Uses the existing November 2025–January 2026 replay targets for global account IDs and archive order. For September–October 2023 and February–April 2026, it reads only the needed identity/order columns from the five known speed partitions per month and retains matched opportunity rows. It does not update rating states. First-run byte hashing still reads the full files; “narrow projection” does not mean zero full-file I/O.
5. Recovers time controls and outcome arms from authenticated Stage05/Stage07 or registered historical panels. Stockfish projections omit these fields. October 2023 uses the explicit API draw/winner fields and chooser color to reproduce the Stage05 chooser-win rule. A non-kindness outcome is never automatically treated as a chooser win. Historical engine evaluations are not substituted for the first pass's normalized 100k-node merit values.
6. Checks observed username/global-ID consistency across the eight new months and the November 2023 bridge. No IDs are invented. This is an observed namespace consistency check, not a claim to have re-audited every account in the global dictionary.
7. Builds two reference universes for the same 32-month target calendar: history starting November 2023, and history starting September 2023. The former must exactly reproduce the original 24 months' reference training counts and grants, and reproduce predictions to absolute tolerance 1e-13. The backfill is kept separately because adding September–October can change historical scores.
8. Performs a read-only check of the existing portable comparison-download checkpoint in Lichess_Desktop if present. It does not start, resume or certify that download. Absence at this Desktop says nothing about another laptop.

## Statistical contracts retained

- `j` is the chooser; `i` is the disconnected player. Histories remain all-source, as in the original IV producer. They are not the main-sample outcome frame.
- Training includes kindness draws or chooser wins with finite merit, ply and rating gap, a recognized live speed and positive base time. Non-kindness draws remain distinct from chooser wins and are not silently put in that training arm.
- Merit, ply, speed and opponent-minus-own rating gap use the unchanged 500-cell definition in the original `iv_numerics.py`.
- The two lag rules are strict: decision time must be **before** the target month's start minus 7 or 30 days. A tied timestamp is not prior history.
- Reference fitting excludes both held-out participant folds in both roles, preserves four folds and the original smoothing strength of 50. Empty reference support stays unavailable.
- The original 24-month history Parquets are reused, not overwritten or silently rebuilt using revised definitions.
- Explicit source labels are retained only if actually present. Generic provenance fields such as `source` or `source_block` are not pool labels. New `extended_pool_nonadjacent_eligible` and `final_iv_eligible` fields remain null.
- The prior main-sample restriction is explicit pool membership plus `previous_classification_status='not_mutually_adjacent_observed'`. It is not an arbitrary rematch-time cutoff.

## Authority limits

Original history files, normalized first-pass outputs, replay targets and full opportunity source panels have hashes in the recovered receipts. The extra chronology partitions were recorded previously by location, part count and row count, not independently certified by that inventory. This package therefore records fresh byte bindings for them, checks exact opportunity ID/start/speed/rating coverage, and reports that distinction. It does not retrospectively claim the fresh hashes were prior producer receipts.

The finalized timing cache keys are reconstructed using the exact v1.0.3 convention and matched to the reviewed aggregate audits. The package consumes those completed corrected anchors; it does not rerun the timing repairs.

An API last-move/end proxy is not the exact moment of a kindness decision. This package preserves the established proxy convention and does not convert it into a stronger observation claim.

## Outputs and restarts

Private work is placed in:

`/Volumes/XT_Pro/lichess_kindness/derived/replication_36m/receipt_iv_history_extension_v100_PRIVATE`

Successful completion produces `READY_FOR_COHORT_EXTENSION.json` there. Its reference root contains:

- `HISTORY_INPUT_MANIFEST_PRIVATE.json`: all 512 old/new shard paths, hashes and row counts.
- `reference_deltas_old_boundary.npz` and `reference_deltas_extended_boundary.npz`.
- `reference_old_boundary.npy` and `reference_extended_boundary.npy`, each shaped `[2, 32, 4, 4, 500]`.
- `REFERENCE_BRIDGE.json`.

Each new month also has `opportunities_PRIVATE.parquet`, `identity_pairs_PRIVATE.parquet`, the matched canonical identity projections, 16 history shards and a completion receipt. All game IDs, usernames and account IDs remain on the project drive.

The aggregate result ZIP and SHA file are written to Lichess_Desktop. Its success status is deliberately:

`HISTORY_EXTENSION_COMPLETE_COHORT_GATES_REMAIN`

Read `SUMMARY.json`, the historical projection/reference bridge files, `HISTORY_COVERAGE`, `ADDED_MONTH_PROJECTION_COUNTS` and `ESTIMATION_GATES`. Return the aggregate ZIP, its SHA file and the launch log. Do not upload the private work directory or a comparison download marked PRIVATE.

If interrupted, use the same launch command again. Completed stage receipts and input fingerprints are checked and reused. Unfinished work stays in uniquely named `.partial_…` directories; the package does not delete it automatically. A changed completed contract or corrupted file stops the run. A lock prevents concurrent runs writing this work tree. Some early environment failures can stop before a result ZIP exists; the launch log still records them.

## What comes after this build

The substantive IV extension is still gated on the following work, in this order:

1. Extend the original source-label and observed-predecessor producers, preserving unknown membership. Use the original 24-month pool cohort as the bridge; do not treat all-source support as main-sample support.
2. Recover the existing February selected-candidate/API denominator lineage, align clock and outcome definitions, and freeze a source-supported mechanics censor with complete breakpoint windows. The January issue date or end of an available file is not a deployment timestamp.
3. Rebuild first-observed-pair and exposure streams with the original ordering/tie conventions. Apply greedy exposure spacing before subsequent history and complete-follow-up cuts. Keep original and backfilled history universes as explicit comparisons.
4. Require every exposure's full 90-day outcome window to end before the exclusive frozen censor. Preserve the later-choice outcome definition and distinguish entry/reaching a choice from granting kindness. A nonreacher can be coded zero only when its full observation window is available; incomplete follow-up is not zero.
5. Compare at least five versus at least ten prior opponent decisions on a common eligible sample as well as separately reported support. Retain the original leave-all-pair-out score construction. Reconcile any changed score standardization rather than calling a rescaling an improved first stage.
6. Apply color × post at the recipient's later choice, not merely at the receipt exposure. Freeze exact policy and announcement timing, the outcome/control specification, placebos and dependence-aware inference before inspecting new behavioral results. Do not force an unmeasured visibility indicator into the model.
7. Re-estimate first stage and reduced form alongside IV estimates, support, balance, entry/specificity diagnostics and exclusion sensitivity. The historical reduced-form benchmark is not a new result. Extra months alone cannot repair an exclusion-restriction problem.

The color-change behavioral diagnostics and calibration reviewed in the first-pass report remain separate from receipt-IV history construction. This package makes no behavioral GO/NO-GO, power, MDE, visibility or threshold claim.

## Validation included

`VALIDATION.json` reports the local synthetic test results. The suite calls the preserved original pilot projector as an oracle, not merely a second reimplementation of the new logic. It covers row/delta equivalence, strict lag boundaries, both-role fold exclusion, complete synthetic 32-month reference construction, legacy API outcome adaptation, unknown membership, duplicate/conflicting inputs, source-cache resolution, restart/corruption handling, identity collisions, read-only comparison inspection and the aggregate-ZIP allowlist.

The tests ran on synthetic data in the development environment. They are not evidence that this code has already run against the user's Mac drive. The production bridges and counts remain runtime requirements.

Optional local test command, from the extracted package:

```bash
/Volumes/XT_Pro/lichess_kindness/venv/bin/python tests/test_extension.py
```

Do not add `--record` on the Mac: that is a release-authoring option that updates the packaged validation file and would invalidate its manifest.
