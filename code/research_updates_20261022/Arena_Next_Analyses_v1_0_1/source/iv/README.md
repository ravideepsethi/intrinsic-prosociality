# Chooser IV main-sample rebuild v1.0.0

Run on the **work laptop**, with `/Volumes/XT_Pro/lichess_kindness` mounted.
This is a new analysis run. It uses the certified September 9 main sample:
`source='pool' AND previous_classification_status='not_mutually_adjacent_observed'`.
The verified sample contains **41,534,331 opportunities**, including **570,091 kind draws**.

## Run

Put this package ZIP and its SHA file in `~/Desktop/Lichess_Desktop`, then paste:

```bash
/bin/bash <<'BASH'
set -euo pipefail
cd "$HOME/Desktop/Lichess_Desktop"
/usr/bin/shasum -a 256 -c Chooser_IV_Main_Rebuild_v1_0_0.zip.sha256
/usr/bin/ditto -x -k Chooser_IV_Main_Rebuild_v1_0_0.zip .
export IV_MAIN_PROJECT_ROOT="/Volumes/XT_Pro/lichess_kindness"
export IV_MAIN_DESKTOP="$PWD"
export IV_MAIN_WORKERS=10
/bin/bash "$PWD/Chooser_IV_Main_Rebuild_v1_0_0/RUN_IV_MAIN.command"
BASH
```

The launcher checks the package and runs the offline tests first. It uses the
existing Python environment if NumPy, PyArrow and DuckDB 1.5.4 are available;
otherwise it prepares a separate environment. Analysis makes **no API requests**.
It reads the saved canonical game-history Parquets, so this is a substantial local
job. Keep the drive connected and the laptop open. `caffeinate` prevents idle sleep.
There are no deliberate work pauses. It requests up to ten workers and limits the
actual number to fit the laptop's RAM. An optional `IV_MAIN_MEMORY_GB` caps RAM;
by default the calculation reserves about 35% for the system and other applications.

Run the same command to resume. Completed stages and files are checked and reused.
An interrupted in-progress file is recomputed. Keep the Desktop log if there is an
error. Do not remove checkpoints or bypass an input mismatch.

## What it rebuilds

1. Select each recipient's first fair, non-tournament-like exposure **within the
   new main sample**. Rank before the arm, realtime, first-pair and follow-up cuts.
   A person whose first qualifying exposure fails a later cut is not moved forward.
2. Recompute first observed pair and preceding 30-day game volume from all 852
   files in the pinned canonical history manifest. Earlier excluded games still
   count as history. “First observed” is not a lifetime no-contact guarantee.
3. Apply grant-versus-claim, realtime, first-observed-pair and complete 90-day
   follow-up requirements. No receipt-dependent ATT support cut or ATT weights.
4. Score the newly selected chooser using full original Stage07 histories,
   retaining all sources and excluded opportunities. Rebuild the expanding state
   reference from authenticated training deltas and recompute scores for the new
   queries. The 7/30-day cutoffs precede the first day of the exposure month.
   Remove **all** earlier chooser decisions against the focal recipient. The
   four-fold reference excludes both participants' account folds in both roles.
5. Rebuild the first later fair choice from the **new main sample**, against a
   different opponent, in a game started strictly after the focal last-move anchor.
   Its decision must be within 90 days. Skip excluded games and original-chooser
   re-encounters. A nonreacher is zero only when the full window is observed.
6. Rerun the first stage, reduced form, candidate 2SLS, weak-IV Anderson–Rubin
   confidence sets, balance tests, history support and sensitivity specifications.
   Check first-stage signs across speed, calendar period and descriptive board slices.
7. Reclassify the existing **1,661,563 pool comparison games** using the same
   observed-predecessor rule. Keep the original random orientation and all ending
   types for selection tests. Check exact agreement with the certified eligibility
   ledger wherever the comparison game belongs to the original timeout panel.
   Rebuild ordinary-game later outcomes, selection and role-specific checks.
   Recomputed earlier comparison scores must match the authenticated previous scores.

The ordinary comparison is never produced by joining games only to the timeout
eligibility table: that would delete its non-timeout denominator. Its predecessor
search uses the original rule's October 2023 lower boundary. Missing predecessors,
ties and exclusions are retained as explicit categories. Temporary per-file
predecessors are combined across speed and month files before classifying a game.

## Files and interpretation

New private outputs and checkpoints are under:

`derived/replication/chooser_iv_main_rebuild_v100_PRIVATE/<configuration hash>/`

Existing analyses and source datasets are read only. The code does not estimate
the new IV by filtering the old IV cohort. It does reuse authenticated full-history
projections and the repaired comparison identities; there is no reason to download
those games again. Full historical score training remains separate from focal and
future-outcome sample eligibility, as required by the main-sample report.

At completion, the Desktop receives:

`CHOOSER_IV_MAIN_REBUILD_REPORT_<hash>.zip` and `.zip.sha256`.

Upload those two files. The report contains aggregate results only. Keep all files
under the private run directory on the project drive. `cohort_flow.json` shows the
new counts; `iv_primary.json` and `iv_estimates.csv` give the IV results;
`balance.csv`, `joint_balance.csv`, `first_stage_strata.csv`, and
`comparison_estimates.csv` provide the main validity checks.

IV effects use one residual SD of the instrument within each specification.
Comparison results also report a common scale tied to the **new primary IV**;
this is not the old pilot's SD. The ordinary-game regression has fewer available
pregame controls than the IV regression. Main IV inference clusters on chooser,
and chooser plus exposure date. Comparison inference permits dependence from
either shared account role, and from shared account or date. Historical scores
are treated as fixed; this is not a full generated-instrument bootstrap.

This remains a **candidate IV**. A strong first stage or a nonsignificant placebo
does not establish exclusion, random matching, or absence of selection. The prior
selection warning must be evaluated with the new estimates. The sample proxy
measures observed game-start adjacency, not literal end-to-start rematches.
`lastMoveAt` is a last-move anchor, not an observed terminal click time.

The canonical chronology's inherited manifest provides file sizes, row counts,
row-group counts and footer-signature records, not original full-content hashes.
The runner authenticates that manifest, checks these structural counts and records
input signatures for change detection and resume. It does not claim full-byte
historical authentication that the original manifest cannot supply. Main panels,
eligibility files, score projections and repaired comparison inputs are SHA-256
checked against their recorded authorities.

This package is tested on synthetic data, including an end-to-end Parquet fixture.
The full private dataset is on the work laptop and has not been executed here.
The previously chosen 2020/prehistory expansion is not folded into this rerun:
the score history starts in November 2023, as in the verified pilot. A longer
score-history version requires its own authenticated opportunity pipeline.
