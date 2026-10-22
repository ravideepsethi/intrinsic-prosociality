# Identity diagnostic review and guarded continuation

## Reviewed evidence

Final archive: `KAC_HISTORY_IDENTITY_DIAGNOSTIC_RESULT_f307aab0156f7aff.zip`

SHA-256: `3d6f18a22fbe9ee3aa6664675f89f6f41cdaf762c2475b0cc6f70e2aad56417d`.

Early archive SHA-256: `b7659c722e0932ba72f21e997c10f20ed0f84e77d34aef1dae101cd7667bf5d3`.

The final diagnostic covers all 15 months from August 2024 through October 2025 and 26,073,431 frozen focal games. It reports zero missing game keys, missing chooser/game pairs, wrong choosers, duplicate matches, timestamp/speed mismatches, or ordinal mismatches. The failed August check was `[1674961, 3, 3]`; the direct raw-history check is `[1674961, 0, 0]`. No records were edited or excluded and no models were run.

The direct lookup establishes that the required raw records exist and agree with the focal data. It does not reproduce the complete history build, prove every intermediate operation correct, identify source corruption, or establish a DuckDB defect. The failure's cause remains unresolved.

## Implementation changes

The final join first materializes candidates for focal game IDs and then matching chooser-side features. It joins the focal Parquet against that compact relation. The needed chooser list is also materialized, and player events use separate white-side and black-side semi-joins. Old and new expressions are tested for equal output on controlled histories.

New guards compare the complete needed chooser set, validate every raw focal identity, and check the player-event count plus two identity checksums at the events, ordered, sessions, and annotated stages. These intermediate checksums diagnose accidental changes; they are not cryptographic proofs of equality. Focal identity validation is exact, as is the final multiset comparison of all original focal columns after the Parquet write. SHA-256 validation remains for authenticated checkpoints and newly consumed raw sources. A failed guard blocks the run and saves an aggregate report plus private diagnostics.

The earlier 24 focal projections and ten completed history checkpoints are reused after dependencies, receipts, and data hashes pass. The canonical chooser set must equal the old set before history reuse. The initial carry is reused; the 531 unused individual prefix outputs are not copied or rehashed. Their source snapshots and configuration keys are checked, and the reviewed June source is rehashed. Checked symbolic references preserve parent bytes and metadata. Parent and diagnostic runs are locked during this continuation.

Reconstruction begins in August 2024 in a separate v1.0.1 directory. The old failed month's files stay intact. Later successful monthly outputs and regression partitions remain resumable.

## Scientific scope

`ANALYSIS_AMENDMENT.md` and `repetition.py` are byte-identical to v1.0.0. The frozen sample, ten specifications, within-chooser transformation, clustering, count scenarios, and multiplicity rules are unchanged. This is an implementation change with added validation, not a new sample or recovered timestamp. Completion remains labeled as sensitivity analysis; the strict parent timestamp condition remains unresolved.

Integrity summaries are exported under `report/history_integrity/`. Raw keys and any failed-key extracts stay private. The package includes authenticated diagnostic reports and the archived original history implementation for provenance and parity testing.
