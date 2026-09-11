# New main sample: September 11, 2026 release

The main sample is **41,534,331 pool/observed-nonadjacent opportunities**, with
570,091 kind draws. The competitive subset contains 15,207,423 opportunities and
419,463 grants. The window is November 1, 2023 through October 31, 2025 UTC.

The selection predicate is `source = 'pool' AND previous_classification_status =
'not_mutually_adjacent_observed'`. The sample fingerprint is
`a17c89d750cb4fdfdf84f950859e45c58b19996efae02045def68285e305cf30`.
The sample authority is
[MAIN_SAMPLE_REPORT.json](../../results/pool_main_reanalysis_v100/sample/MAIN_SAMPLE_REPORT.json).
The previous 47,587,020-opportunity sample is historical comparison only.

## What this release contains

| Area | Current main-sample authority and limitation |
|---|---|
| Sample, descriptive rates, persistence, rating gap and controlled payoff | Completed sample report and Wave 1; Wave 2A crossing/equality/FEN checks |
| Dynamics and census first/repeat meetings | Completed Wave 2B1 |
| Exact C7R family | Completed Wave 2B2A and covariance-based first/repeat contrasts; the standalone repeat-only fit did not converge |
| C7X targeted memory | Parent support gate failed; no adjusted main-sample effect; retained dyad diagnostic does not override the gate |
| C6/C10, C12 and C6 ply | Completed Wave 2B2B1; retained failures and gate limitations remain in the reports |
| C9 | Fresh 4,999-draw randomization and subsequent ply sensitivities completed |
| Chooser IV | Main rebuild and role/active-given-candidate selection addendum completed; selection limitations remain |
| Patron | Wave 3A, gap fill, Wave 3B1 and Wave 3B2 completed for the scheduled estimable models; current-status associations, not adoption effects |
| C13 | Prepared code only; no returned main-sample estimate |
| Campaign family D | Exact new C1/C2/C5 inputs missing; five-slot conservative C6/C9 decisions available; complete exact table remains open |
| Manuscript | Detailed corrected handoff and 80-label change map available; integrated new-sample manuscript figures, tables and compilation remain to be completed |

Read [the detailed handoff](Lichess_New_Main_Sample_Handoff_v1_0_2.md), then
[MANUSCRIPT_CHANGE_MAP.md](MANUSCRIPT_CHANGE_MAP.md). Results, their own receipts
and executed source govern numerical claims. Older status memos are historical.
No models were re-estimated to prepare this Git publication.

## Paths in the complete handoff and this repository

| Complete handoff path | Repository location |
|---|---|
| `results/ALIAS/...` | `results/pool_main_reanalysis_v100/ALIAS/...` |
| `source_packages/...` | `operations/pool_main_reanalysis_v100/source_packages/...` |
| Current analysis source inside a package | `code/pool_main_reanalysis_v100/PACKAGE_NAME/...` |
| `SAMPLE_DECISION.json` and archive verification | `manifests/pool_main_reanalysis_v100/` |
| `old_repository_snapshot/...` | Historical repository content at commit `0dc981cbc6da157d365015a95f2b7157ecda4859` |
| `draft_source/`, `old_sample_closeout/`, `prior_reviews/`, full evidence archives | Retained in the complete handoff; not copied into this public subset |

Original aggregate files and source packages are byte-preserved, including their
original manifests. Runtime logs are deliberately omitted from the public result
directories. Therefore an original *complete-report* manifest may refer to an
omitted log. Use the release's `REPO_FILE_HASHES.sha256` for this public subset;
`OMITTED_RUNTIME_LOGS.json` records the omissions and original hashes. A source
package's embedded old-sample evidence is an input/provenance reference, not a
replacement main-sample result. The full handoff's file counts describe the full
handoff, not this subset.

The 67 small Parquet files under the new results directory contain aggregate
counts, model coefficients, plotting tables and model-plan/receipt metadata.
Their exact paths, hashes, row counts and schemas are inventoried in
`manifests/pool_main_reanalysis_v100/AGGREGATE_PARQUET_AUDIT.json`. Row-level panels,
user profiles, PGNs and private checkpoints are excluded.

## Verify and run

From the repository root:

```bash
python3 operations/pool_main_reanalysis_v100/verify_public_release.py
```

Expected verification time: **5–30 seconds**, with no model execution or network
access. See [the package/run index](../../operations/pool_main_reanalysis_v100/README.md)
for launchers and runtime guidance. Packages retain their original private input
contracts and dependencies; this aggregate release alone is not a raw-data deposit.
