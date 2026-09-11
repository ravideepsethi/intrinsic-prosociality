# Validation

This package was tested on offline synthetic fixtures. The 47,587,020 private
production observations remain on the user's Mac; the new panel build has not
been executed on those observations here.

`test_main_sample.py` exercises a two-month, 12-game case with all four previous
statuses, multiple non-pool sources, cross-month repeat choosers, exact centipawn
boundaries, missing plies, two-ply games and retained fields outside the summaries.

The 20 tests verify:

1. Original/pool/main/restore counts of 12/10/4/6 and their independent expected
   kind, fair and fair-kind counts.
2. Exactly three global main choosers despite four summed monthly distinct counts,
   and pooled fair-kindness 2/3 rather than averaging monthly rates.
3. All retained Stage07 values and logical schema, including unused fields, survive
   the actual COPY and report workflow.
4. Unknown history remains NULL; the main excludes both missing and ambiguous
   cases, while robustness restores only missing cases.
5. Future re-pairing and start-gap changes do not change main eligibility.
6. Duplicate joined IDs, source-ID changes, exchanged source labels with identical
   marginal totals, provenance mismatches, role mismatches, start mismatches,
   invalid flags, missing outcomes and changed input bytes cause rejection.
7. An interruption after the first month resumes without rewriting that month;
   completed runs check output hashes; damaged files or receipts cause rejection.
8. Existing unrecognized folders and all original input files are preserved.
9. Generated reports pass their own archive/member checksums and contain no fixture
   game IDs or per-game provenance.
10. The bundled completed source authority covers August–October 2025 with the
    documented pool and main counts. The inherited canonical contract digest is
    distinguished from the hash of a pretty-printed JSON file.

The production run independently checks full hashes and schemas for the source map,
128 joined partitions and 24 full Stage07 panels, with exact receipt ancestry to
the uploaded completion reports. It then checks actual per-game source, provenance,
month, chooser/disconnected roles and start times; original/source outcome totals;
the complete written eligibility set; retained-panel ID sets; per-month expected
sample counts; pooled baseline outcomes; and nested-sample conservation. Final
output schemas and hashes are included in the upload report.

The existing Stage07 values are reused. There is no network fetch, raw chronology
rebuild, rating replay or Stockfish run. The observed adjacency status remains the
upstream measure; literal agreed-rematch timing is not validated by this package.

See TEST_RESULTS.txt for the actual environment and test output from packaging.
