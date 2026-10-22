# December annotation failure and implementation change

Reviewed input: `KAC_REPETITION_SENSITIVITY_PARTIAL_260b8b47b53ba645.zip`, SHA-256 `b66aad78bfddeb8e6de33f16ae3305752dd5b524a40d539eb6f2e91f45b43c2f`. All 19 report-member hashes were verified. The accompanying console log reports successful August, September, October, and November 2024 builds.

December's raw focal match was `[1784921, 0, 0]`. The canonical chooser set was exactly 3,224,173 accounts, with no extra, missing, duplicated, or null identifiers. There were 180,915,635 player events at each reported stage.

Events, ordered, and sessions stages shared identity checksums:

- XOR: `12603672798870590999`
- Sum: `1668770878329773824814429729`

At annotated, these changed to:

- XOR: `6435230944077289763`
- Sum: `1668770485603676152029637141`

The run correctly blocked with `BLOCKED_STAGE_IDENTITY_CONSERVATION`. This localizes the detected mismatch to annotation or its checking. It does not prove a particular DuckDB defect, source corruption, missing games, or which rows differed. Production repetition estimation had not completed.

## Replacement

1. Preserve the previously passing raw/events/ordered/sessions SQL. Retain its row-count and identity checks.
2. Write the complete sessions relation to whole-chooser Parquet partitions, using chooser modulo 512. Compare all-column diagnostic signatures before and after this write, as well as the original identity signatures. Commit an authenticated input checkpoint.
3. Read each partition with Arrow; sort by chooser, start time, archive ordinal, and game identifier. Independently verify predecessor times and session IDs. Compute within-session positions, carry/censoring, and starts using NumPy group operations.
4. Compare all original input columns exactly after annotation. Write and reread the annotated partition and compare every column exactly, including nulls and floating-point NaNs. Save checked last-account and session-summary rows. Commit each partition independently.
5. Close input SQL before launching annotation processes. Finalize from the partition Parquets only after all workers pass. Retain global identity checks, the compact focal join, and the exact multiset comparison of the frozen focal columns after writing.
6. Commit the final month's counts, carry, summaries, and focal features. Only then remove that month's disposable input/annotation work directory.

The two global signatures are accidental-change diagnostics, not cryptographic proofs of multiset equality. Source/output SHA-256 checks and exact Arrow column comparisons provide separate protection. No guard was disabled to force completion.

## Dependency reuse

The first ten monthly checkpoints and initial carry are authenticated against the previously reviewed v1.0.0 chain. The v1.0.1 chain through July must contain the same output-file manifests. August–November are authenticated against the local dependent receipts, source bindings, output hashes, and the exact reviewed PASS reports bundled here. Their receipt hashes were not exported in the partial archive; this procedure does not claim independently pinned hashes for those four receipts. All adopted files use checked symbolic references; original bytes and timestamps remain unchanged.

## Scope

`repetition.py` and `ANALYSIS_AMENDMENT.md` are byte-identical to v1.0.1. This is an implementation-only continuation of the declared sensitivity analysis. The unresolved June 2023 timestamp and other outstanding scientific tasks remain unresolved.
