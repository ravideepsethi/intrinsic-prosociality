# Material correction: October 31, 2026 checkpoint

This development checkpoint publishes the material-correction source lineage,
completed aggregate reports, and the latest IV execution repair. **The paper
rerun is not complete.** It contains 16 source packages and eight report groups.
Older dated result trees retain their original samples and estimates.

## Completed work and current boundary

| Component | State at this checkpoint | Evidence |
| --- | --- | --- |
| Corrected main and broad donor inputs | Complete | [Input report](../../results/material_rerun_20261031/inputs/RESULTS.json) |
| Core position/stage/gap models and continuous merit | Complete for the named module | [Core reports](../../results/material_rerun_20261031/core_models) |
| Persistence, Patron, matched receipt, structure | Completed module reports | [Result index](../../manifests/material_rerun_20261031/RESULT_INDEX.json) |
| Consolidated non-IV batch | 11 of 11 families reviewed, with the auxiliary limits below | [Review](../../results/material_rerun_20261031/noniv_batch/PUBLICATION_REVIEW.json) |
| IV batch and selected receipt companions | 14 of 18 execution stages complete | [Latest production status](../../results/material_rerun_20261031/iv_partial/receipt/STATUS.json) |
| IV resume 1.0.2 | Tested repair; no completed production return available | [Validation](IV_VALIDATION.json) |
| Remaining analyses and manuscript reconciliation | Pending | [Coverage ledger](IV_COVERAGE.json) |

The non-IV families are stakes, tenure, rating-state diagnostics (`krd`),
nonparametric profiles, arena, reputation, first/repeat meetings, split-half
persistence, countdown, Patron extensions, and responsibility. Countdown has
29 empty ultrabullet auxiliary cells and 116 supported fits. Three previously
documented nonconverged first/repeat auxiliary models remain unsupported.
The responsibility review reproduced 53 models and passed 67 reference checks.
The producer's original `BATCH_COMPLETE_REVIEW_REQUIRED` status is preserved;
the separate `PUBLICATION_REVIEW.json` records the subsequent review.

The last IV return failed at `comparison_chronology`; `comparison_metadata`,
`comparison_frames`, and `comparison_models` were blocked behind it. The new
resume package replaces two global chronology joins with bounded, checkpointed
joins and authenticates completed reports before reusing them. Its delivered
validation records 62 batch/companion tests and 50 original tests passing. A
5,000,001-row synthetic benchmark reproduced the old out-of-memory failure and
passed with the bounded joins at the same 0.384 GB DuckDB budget. These checks
are not a production completion certificate.

## Corrected sample and interpretation

The correction uses the recorded final position and the published scalachess
material rules, rather than the earlier bare-king/one-minor approximation.
See [the exact rule and audit method](../../results/material_rerun_20261031/inputs/METHOD.json).
It removes 20,570 main opportunities without the required chooser mating
material and adds 332 grants through reclassification. The author-excluded
baseline is 41,534,289 opportunities and 570,090 grants.

| Corrected quantity | Count |
| --- | ---: |
| Main opportunities | 41,513,719 |
| Main grants | 570,422 |
| Chooser accounts | 3,223,436 |
| Accounts with at least one grant | 276,627 |
| Competitive opportunities / grants | 15,186,844 / 419,794 |
| Clearly-worse opportunities / grants | 22,664,787 / 106,556 |
| Broad source opportunities / grants | 47,561,517 / 669,913 |

The material parent run is
`aa7e95f275c18f43d9ad95af523b9b0d769704ddebf4aea4d3655a2e1b07ef5d`.
The factual game chronology and original rating-price layer are preserved;
this correction does not rerun the engine or rating replay. The input audit
explicitly retains the known 65 main and 75 broad chooser-loss anomalies as
non-arms; it does not silently recode them as wins.

The completed primary IV fit in the partial return has 9,736,412 exposures and
1,877,413 recipients, with an estimate of 0.32176 percentage points per receipt
(SE 0.05637; 95% interval 0.21128 to 0.43224). The primary eight-trait balance
test still rejects (chi-squared 39.434 on 8 degrees of freedom,
`p = 4.08e-6`). These values are traceable to
[`model_estimates.csv`](../../results/material_rerun_20261031/iv_partial/receipt/model_estimates.csv)
(`uniform_unspaced`, `iv_y`) and
[`balance_joint.csv`](../../results/material_rerun_20261031/iv_partial/receipt/balance_joint.csv).
Entry, ordinary-ending placebo, and their joint comparisons have not yet
completed on the corrected frame. Historical estimates must not fill those
missing cells or be treated as evidence that the corrected design passed them.

## Source packages and execution

All versions are immutable snapshots for tracing the executed runs. Earlier
patches are retained as history; the current entry points are:

| Task | Current package | Original launcher |
| --- | --- | --- |
| Input correction | `Mating_Material_First_Run_v1_0_2` | `RUN_MATERIAL.command` |
| Core models | `Mating_Material_Models_v1_0_0` | `RUN_MODELS.command` |
| Persistence | `Mating_Material_Persistence_v1_0_0` | `RUN_PERSISTENCE.command` |
| Patron | `Mating_Material_Patron_v1_0_0` | `RUN_PATRON.command` |
| Matched receipt | `Mating_Material_Receipt_v1_0_0` | `RUN_RECEIPT.command` |
| Structure | `Mating_Material_Structure_v1_0_0` | `RUN_STRUCTURE.command` |
| Consolidated non-IV batch | `Mating_Material_NonIV_Batch_v1_0_2` | `RUN_ALL.command` |
| Resume the existing IV batch | `Mating_Material_IV_Resume_v1_0_2` | `RUN_IV_RESUME.command` |

The responsibility standalone 1.0.0/1.0.1 packages and earlier batch/repair
versions document the development path; the completed responsibility results
come from non-IV batch 1.0.2. The IV resume requires its authenticated original
batch and private checkpoints. It is not a fresh-install replacement for them.
The [machine-readable source index](../../manifests/material_rerun_20261031/PACKAGE_INDEX.json)
lists every archive hash and source entry point.

Private account literals and machine-specific paths are replaced with recorded
tokens. Shell launchers are `.in` templates even when no literal was removed.
These snapshots are for review: do not execute the templates directly or edit
their expected hashes. Original archives, private configuration, row-level
data, cached profiles, and private checkpoints are not published. Every omitted
archive member retains its original size and hash in the package manifest.

The [preparation helper](../../operations/material_rerun_20261031/prepare_package.py)
verifies an original local archive, checks every source/template against it,
and restores it into a new directory outside this checkout without executing
code or overwriting an existing directory. For example, from the repo root:

```bash
python3 operations/material_rerun_20261031/prepare_package.py \
  --package Mating_Material_IV_Resume_v1_0_2 \
  --archive "$HOME/Desktop/Lichess_Desktop/Mating_Material_IV_Resume_v1_0_2.zip" \
  --output "$HOME/Desktop/Lichess_Desktop/Mating_Material_IV_Resume_v1_0_2_verified"
```

Expected preparation time: **under one minute** on a local SSD. The output
must not already exist. Read the restored package's README before running its
launcher; its input and checkpoint contracts remain binding. The delivered
resume estimate is **2–4 remaining hours**, provisional, for that existing IV
run only. New chronology scans can extend it. This is not an estimate for
finishing the whole paper, and this publication does not start an analysis.

## Verification and provenance

Run from the repository root with Python 3.10 or newer and Bash:

```bash
python3 operations/material_rerun_20261031/verify_release.py
python3 -m unittest discover -s operations/material_rerun_20261031 -p 'test_*.py'
```

Expected total time: **10–60 seconds**. These offline checks validate the public
inventory, hashes, syntax, report schemas, and checkpoint status. They do not
estimate statistical models or access private data. The
[publication validation receipt](PUBLICATION_VALIDATION.json) distinguishes
checks run for this commit from the delivered repair's earlier tests.

Result manifests retain the original return-archive hash, sealed report
manifest, original/public file hashes, and any literal redaction spans. CSV,
JSON, text, and aggregate figures are published; duplicate Parquet/NPZ tables
and covariance archives are omitted and inventoried. Publication-added review
notes have separate provenance and are not presented as sealed producer files.

The October 22 verifier binds that release's root README and should be run at
commit `561590939aee88832480b42c5fa53428c944ca8b`. The September verifier should
be run at its original commit `bf3b2bf`. Their source and result trees remain
unchanged. The new verifier covers only this checkpoint and the updated root
README, and does not recertify those historical numerical outputs.
