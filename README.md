# Intrinsic Prosociality

Replication code, aggregate results and documentation for **The Structure of
Intrinsic Prosociality: Field Evidence from Online Chess**.

## Current main sample

**41,534,331 pool/observed-nonadjacent opportunities**, November 1, 2023 through
October 31, 2025 UTC. The sample contains **570,091 kind draws**; the competitive
subset contains **15,207,423 opportunities and 419,463 grants**. The previous
47,587,020-opportunity sample is historical comparison only.

Selection: `source = 'pool' AND previous_classification_status =
'not_mutually_adjacent_observed'`. This jointly restricts source and observed
adjacency; changes relative to the old sample do not identify the contribution of
either restriction separately. Observed nonadjacency is not proof that players
never met or never recognized each other.

Start with [the current release and analysis status](docs/pool_main_reanalysis_v100/README.md),
[the detailed rewrite handoff](docs/pool_main_reanalysis_v100/Lichess_New_Main_Sample_Handoff_v1_0_2.md),
and [the runnable package index](operations/pool_main_reanalysis_v100/README.md).
The governing [sample report](results/pool_main_reanalysis_v100/sample/MAIN_SAMPLE_REPORT.json)
and [sample decision](manifests/pool_main_reanalysis_v100/SAMPLE_DECISION.json) provide
the exact authority.

## Reanalysis status

The repository now includes the new-sample core results, crossing/equality
diagnostics, rebuilt dynamics, C7R covariance-based contrasts, C6/C10/C12, fresh
C9 randomization and ply checks, the chooser IV and selection addendum, and the
completed Patron analysis sequence. The C7X parent support gate fails, so there is
no adjusted main-sample targeted-memory estimate.

**Still open:** C13 has prepared code but no returned main-sample estimate; exact
full Campaign family-D reconciliation lacks new C1/C2/C5 inputs. Conservative
five-slot C6/C9 decisions are available. The integrated manuscript, its final
figures/tables, and compilation are still being updated. Old estimates must not
fill missing main-sample cells. Existing old-sample results remain preserved as
historical authorities.

The Patron analyses use a fixed current-profile snapshot and estimate conditional
associations; they do not identify Patron adoption effects. Failed or unsupported
models remain documented in their own report ledgers.

## Repository structure

- `code/`: original numbered replication stages and versioned extensions;
  `code/pool_main_reanalysis_v100/` adds the 16 pool-main/IV source packages.
- `operations/pool_main_reanalysis_v100/`: 32 immutable source archives, sidecars,
  package instructions, and an offline release verifier.
- `results/pool_main_reanalysis_v100/`: 15 new-sample report groups with aggregate
  estimates, plots, source bindings and execution receipts.
- `docs/pool_main_reanalysis_v100/`: current status, corrected detailed handoff,
  selected results, and the manuscript change map.
- `manifests/pool_main_reanalysis_v100/`: sample decision, original archive checks,
  exact publication inventory, omitted-log record and release hashes.
- Existing `docs/`, `results/`, `provenance/` and source paths retain the historical
  replication lineage. Dates, hashes and sample identities determine authority.

## Data and reproduction

Full raw/derived datasets, PGNs, API responses, user profiles and private
checkpoints are held outside Git. The small Parquet files in the new public
results are audited aggregate count/coefficient/plot/model-metadata tables; their
schemas and hashes are inventoried separately. Large research datasets remain
excluded. Public source packages also include small aggregate input certificates.

Production packages retain their original source bindings, input contracts,
checkpoints and runtime guidance. They require the authenticated local inputs;
publishing this repository does not rerun the models or certify an unavailable
raw-data reconstruction. Source acquisition starts with the existing numbered
replication stages. The paper-facing board evaluation is Stockfish 18 at 100,000
nodes. Other exploratory extensions retain their own status and prerequisites.

From the repository root, verify the new release without running analyses:

```bash
python3 operations/pool_main_reanalysis_v100/verify_public_release.py
```

Expected time: **5–30 seconds**. See the release README for the distinction
between original complete-report manifests and this public subset's manifest.
