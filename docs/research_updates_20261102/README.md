# Research results and repair update — 2 November 2026

This release follows commit `561590939aee88832480b42c5fa53428c944ca8b`. It adds the completed
material-rule reanalysis sources, aggregate report snapshots, November 2 retained
supplement, corrected receipt companions, and the closing audit. It does not
change or rebuild manuscript files or figures, and it runs no private-data model.

## Results and authority

| Item | Public location | Interpretation |
|---|---|---|
| Corrected material-rule results | [paper source reports](../../results/research_updates_20261102/paper_source_reports) | Eleven source families from the authenticated November 1 integrated inventory. Original report labels and estimates retain their own scope. |
| November 2 supplement | [retained supplement](../../results/research_updates_20261102/retained_supplement) | Completed balance, intent/stakes, and retained table exports; consult each specification. |
| Receipt censor repair and companion results | [remaining results](../../results/research_updates_20261102/remaining_results) | The repaired conditional row supersedes the defective earlier row; other validated outputs are retained. |
| Nullable-integer audit | [audit CSV](../../results/research_updates_20261102/closing_audit/NULL_SENTINEL_AUDIT.csv) | Fourteen consumers reviewed from producer/consumer code and authenticated aggregate returns; not a fresh census of private column nulls. |
| Claim-error validation | [RD bins](../../results/research_updates_20261102/closing_audit/CLAIM_ERROR_BY_RD.csv) | Corrected claimed-win frame; lower RD cells pooled to avoid guessing the distribution of excluded author claims. |
| Post-panel validation | [comparison](../../results/research_updates_20261102/closing_audit/POST_CHANGE_VALIDATION.csv) | All-rated player updates, November 2025–January 2026, outside the paper panel. |
| Censor reconciliation | [old/new row](../../manifests/research_updates_20261102/RECONCILIATION.csv) | N 314,639 → 625,066; 1.025175 → 1.121584 pp. |
| Original package coverage | [package index](../../manifests/research_updates_20261102/PACKAGE_INDEX.csv) | Forty-six verified archives cover the 800-entry paper-source inventory and supplements; archive coverage is broader than the files published here. |

The conditional censor loaded absent integer timestamps as -1 and treated them
as real events. The repaired rule defines a present timestamp as finite and
positive and retains ties. It restores 310,427 rows and removes none; the new
estimate is 1.121584 pp (SE 0.159006), with 95% interval [0.809938, 1.433229].
The zero-coded censored row uses its existing strict-before rule and remains
0.315239 pp (SE 0.047324), N=2,112,426. Reach and any-grant rows are unchanged.
No additional affected output was found in the closing audit.

The existing November 1 and supplement exports are preserved as dated evidence,
not silently edited into a new manuscript. Where an old table conflicts with
the completed repair, the repaired JSON and RECONCILIATION.csv govern.

## Validation distinction

On the corrected claimed-win frame, signed error (predicted minus recorded)/MAE
are +0.018/0.406 for RD≤110, +0.817/1.934 for 110<RD≤200, and +0.169/3.573 for
RD>200; the claim of roughly -2 points does not describe these claimed wins.
The separate post-panel all-rated diagnostic has post/pre MAEs of 0.334/0.338
at the RD floor and 4.826/4.895 at RD≥200. The original rating layer is retained;
the candidate cost-upgrade formulas are not adopted.

## Public source fidelity and reproduction

The source table below contains the latest recovered package for each work
stream, plus the required original IV-batch source. Vendored source is retained
at its original relative path. Original package manifests list every omitted
asset and its hash. Private account literals and personal home paths are replaced
only within those literal spans, and changed code is named `.in`; launchers are
also `.in`. These are reviewable source snapshots, not complete runnable bundles.
No estimator, covariance method, sample rule, or input-validation gate is changed.

Raw data, row-level IDs, profile snapshots, private caches, logs, environment
dumps, manuscript source and rendered figures are excluded. The published NPZ
files contain coefficient/covariance summaries; Parquet files contain stage
status or bootstrap statistics, not game or account records. JSON/text reports
with account literals or machine paths have documented literal substitutions.
Their original and public hashes are recorded separately in RESULT_FILES.json.

The original closing-delivery `checksums.txt` and evidence-hash files describe
the delivered originals, including private-value source literals, and are retained
as provenance. They are not validators for the public redacted copies. Use the
public verifier below for this checkout. Original report README/test/verification
instructions likewise refer to their own original artifact, not this layout.

```bash
python3 operations/research_updates_20261102/verify_release.py
```

The verifier checks the exact public inventory, SHA-256 values, Python/Bash
syntax, result bindings, censor arithmetic, and validation aggregates. A separate
synthetic suite uses NumPy, PyArrow and DuckDB:

```bash
python3 operations/research_updates_20261102/test_sentinels.py
```

Holders of the original package archives can restore an authenticated runnable
package outside the repository, preserving all original input gates:

```bash
python3 operations/research_updates_20261102/prepare_package.py \
  --package Remaining_Results_Consolidated_v1_0_2 \
  --archive /path/to/Remaining_Results_Consolidated_v1_0_2.zip \
  --output /path/to/new-local-package
```

This helper checks the archive, every member, and all published source hashes;
it does not execute an analysis. The original README then governs local inputs.
Publishing these sources does not certify an end-to-end raw-data reproduction.
The October verifier binds the October root README and remains runnable at
commit `5615909`; the September verifier remains runnable at `bf3b2bf`.

## Source packages

| Package | Source files | Templates |
|---|---:|---:|
| [Chooser_IV_Main_Rebuild_v1_0_1](../../code/research_updates_20261102/Chooser_IV_Main_Rebuild_v1_0_1) | 12 | 1 |
| [Counterfactual_Cost_Upgrade_v1_0_1](../../code/research_updates_20261102/Counterfactual_Cost_Upgrade_v1_0_1) | 18 | 4 |
| [Mating_Material_First_Run_v1_0_2](../../code/research_updates_20261102/Mating_Material_First_Run_v1_0_2) | 20 | 6 |
| [Mating_Material_IV_Batch_v1_0_0](../../code/research_updates_20261102/Mating_Material_IV_Batch_v1_0_0) | 449 | 76 |
| [Mating_Material_IV_Resume_v1_0_6](../../code/research_updates_20261102/Mating_Material_IV_Resume_v1_0_6) | 467 | 76 |
| [Mating_Material_Models_v1_0_0](../../code/research_updates_20261102/Mating_Material_Models_v1_0_0) | 23 | 4 |
| [Mating_Material_NonIV_Batch_v1_0_2](../../code/research_updates_20261102/Mating_Material_NonIV_Batch_v1_0_2) | 204 | 29 |
| [Mating_Material_Paper_Closeout_v1_0_2](../../code/research_updates_20261102/Mating_Material_Paper_Closeout_v1_0_2) | 489 | 79 |
| [Mating_Material_Patron_v1_0_0](../../code/research_updates_20261102/Mating_Material_Patron_v1_0_0) | 31 | 7 |
| [Mating_Material_Persistence_v1_0_0](../../code/research_updates_20261102/Mating_Material_Persistence_v1_0_0) | 19 | 7 |
| [Mating_Material_Receipt_v1_0_0](../../code/research_updates_20261102/Mating_Material_Receipt_v1_0_0) | 22 | 6 |
| [Mating_Material_Structure_v1_0_0](../../code/research_updates_20261102/Mating_Material_Structure_v1_0_0) | 27 | 4 |
| [Mating_Material_Three_Runs_v1_0_0](../../code/research_updates_20261102/Mating_Material_Three_Runs_v1_0_0) | 385 | 22 |
| [Remaining_Results_Consolidated_v1_0_2](../../code/research_updates_20261102/Remaining_Results_Consolidated_v1_0_2) | 27 | 3 |
