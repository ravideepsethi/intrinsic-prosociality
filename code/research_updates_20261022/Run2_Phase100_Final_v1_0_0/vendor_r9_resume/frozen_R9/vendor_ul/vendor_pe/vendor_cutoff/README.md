# IV cutoff and material robustness — v1.0.0

11 October 2026. New code; not new empirical results. Requires the completed, reviewed R7 v1.0.3 run and its original local caches. Run 2 retrieval and R8 are neither launched nor modified.

## Specification

This is a fixed-cohort first pass on the 2,682,329 author-clean headline exposures. It does not expand the sample to newly supported recipients or refit the entry model.

The old instrument uses history strictly before exposure-month start minus seven days. The new instrument uses **all recorded eligible grant/claim decisions** with `api_last_move_at_ms < archive_start_ms − 24 hours`. This is a cumulative history with a one-day gap, not the preceding 24-hour window. Ordinary games do not enter as refusals. Timestamp semantics are preserved from the original pipeline; no exact claim-button time is inferred.

Exclude both author accounts on either side of every donor event and all historical decisions involving the current recipient–opponent pair. Retain at least five decisions. The frozen author-clean monthly state probabilities retain the original cross-fitting that holds out both players' folds. They were trained before the new cutoff. Neither those probabilities nor the old X0 and environment controls are refreshed in this first comparison: changing these too would mix changes in instrument information and adjustment. Historical donor scores are never material-filtered.

The exposure robustness retains the existing competitive-position definition (recipient evaluation at least −100 cp) and additionally requires **−4 < material balance < 4**. Endpoints are excluded. Material is the final-position piece census with values 1/3/3/5/9, not Stockfish evaluation and not material change over the last four plies. White-minus-black sign is sufficient because the screen is symmetric. The authenticated final FEN must be valid and its turn/fullmove information must match the recorded ply count.

Missing or invalid FENs are not coded neutral. The report separates the original cohort, material-observed cohort, and material-neutral cohort. It compares old/new instruments within each, under X0 and X0 plus the frozen environment controls and explicit availability indicator: up to twelve model cells. This indicator specification keeps the same rows in each control comparison. The original baseline is reproduced numerically before any new fit is accepted. The new scorer must also reproduce every archived old-cutoff score, count, and counterpart count before proceeding.

All outcomes, spacing, chronology conventions, and recipient selection remain frozen. Complete-window nonreachers retain their archived zero outcomes; unknown outcomes are never imputed. Report first stage and F, reduced forms for later granting and reach, 2SLS with Wald/AR intervals, and the existing seven-trait joint and individual balance tests. Reference score units, shared-account-or-date CR0, nominal inference, and fixed generated scores match R7.

## Interpretation

The material restriction targets the immediate material-based numerical `rageSit` increment. It does **not** remove disciplinary outcomes, rating consequences, earlier matchmaking selection, or selection induced by conditioning on the final position. A stable IV estimate would be evidence against that specific numerical-update explanation, not proof of the exclusion restriction.

Source checks at two commits bracketing the sample:

- [RageSit, October 2023](https://github.com/lichess-org/lila/blob/4443a238352bc10aab12df6e9ffe5806ec5b68ca/modules/playban/src/main/RageSit.scala)
- [RageSit, October 2025](https://github.com/lichess-org/lila/blob/6d667d47636031bc4087f07d81bd91bfdcc5336a/modules/playban/src/main/RageSit.scala)
- [Finisher, October 2025](https://github.com/lichess-org/lila/blob/6d667d47636031bc4087f07d81bd91bfdcc5336a/modules/round/src/main/Finisher.scala)
- [PlaybanApi, October 2025](https://github.com/lichess-org/lila/blob/6d667d47636031bc4087f07d81bd91bfdcc5336a/modules/playban/src/main/PlaybanApi.scala)

These endpoint source checks are not a claim to have exhaustively audited every intermediate deployment.

## Run and resume

Use the same research Python and connected XT_Pro drive as R7. Save the ZIP and SHA-256 file in Downloads. In Terminal:

```bash
cd "$HOME/Downloads" && shasum -a 256 -c IV_Cutoff_Material_v1_0_0.zip.sha256 && iv_stage=$(mktemp -d /tmp/iv_cutoff_material.XXXXXX) && ditto -x -k IV_Cutoff_Material_v1_0_0.zip "$iv_stage" && bash "$iv_stage/IV_Cutoff_Material_v1_0_0/RUN_IV_CUTOFF_MATERIAL.command" --workers 10 --memory-gb 11
```

The launcher checks package hashes and runs offline self-tests first. It never installs software. The default project is `/Volumes/XT_Pro/lichess_kindness`; `IV_PROJECT_ROOT`, `IV_PYTHON`, and `IV_DESKTOP` override defaults. `--r7-root` selects a relocated completed R7 v1.0.3 root, subject to the same identity checks.

History workers are limited by the requested RAM budget; numerical fits run sequentially in fresh processes. The 11 GiB limit is an estimated application budget, not an operating-system hard cap. Actual Mac runtime is not benchmarked. Measured ETAs appear after completed units, with heartbeats during long stages. Avoid running this concurrently with another memory-heavy analysis if the combined workload would exceed physical RAM.

New private checkpoints live under `derived/replication/iv_cutoff_material_v100_PRIVATE/<configuration>/`. Completed stages and fits are hash-checked and reused by the same command. Inputs and upstream runs are never overwritten. Incomplete temporary directories are retained for diagnosis, not silently treated as completed checkpoints.

Aggregate report ZIPs and SHA-256 files appear in `~/Desktop/Lichess_Desktop` at 25%, 50%, 75%, and 100%. Private identities and FEN rows stay out of those reports. Return the 100% report and launcher log. If the process stops, return the latest checkpoint and log; do not delete or rewrite old caches.

If the certified source panels do not contain the documented final-FEN column, the score comparison still runs and the final report explicitly says `COMPLETE_WITH_MATERIAL_UNAVAILABLE`. That is not a completed material robustness check. There is no guessed-column, missing-as-neutral, network, move-download, or engine fallback.

## Boundaries

No API requests, Stockfish, manuscripts, new raw data, or upstream chronology rebuilds. The recorded donor history remains November 2023–October 2025, not lifetime account history. The fixed-cohort comparison cannot measure the effect of newly supported exposures. Updating history controls/nuisance estimates and extending the entry/placebo frames are separate follow-on specifications.

Vendored R7/R8 code and evidence are unchanged and covered by the package manifest. Only the new `code/` entry point runs; vendored launchers are not invoked.
