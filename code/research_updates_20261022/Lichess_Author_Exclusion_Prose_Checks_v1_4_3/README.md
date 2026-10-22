# Author exclusion: manuscript prose checks v1.4.3

Expected runtime: **5–15 minutes** with 10 workers and 11 GiB; allow 20–30 minutes on a slow external drive. The previous original-persistence completion took 3 minutes 20 seconds. This package does not repeat the 20 completed analysis families, IV estimation, engine evaluations, profile acquisition, or temporal randomization.

## What the final v1.4.2 report established

- Original persistence reproduced in all 95 column checks. All 20 scheduled families completed.
- The reviewed report contains 315 aligned paired tables and 283,793 numeric metrics, including 33,696 recognized point-estimate entries. These entries include repeated presentations and are not independent hypotheses.
- The largest recognized change was 0.020969778 included-standard-error units. No recognized estimate changed sign or crossed the approximate 95% zero boundary. This describes the returned estimates, not an equivalence test or a claim of exact numerical equality.
- The main author-excluded sample has 41,534,289 opportunities, 570,090 grants and 3,224,171 chooser accounts. Competitive positions have 15,207,414 opportunities and 419,462 grants. Exclusion removes 42 main-sample games, including one grant.

## Why this follow-up is necessary

The v1.4.2 coverage gate mapped manuscript labels to broad analysis families. Its `all_analyses_excluded: true` field was too broad: the closer prose audit found results that its table exporter or family map did not cover. Do not use that field as blanket publication clearance.

This package handles four exact items:

1. **Material-screen sensitivity:** count the flagged nongrant draws in both authenticated panels and recalculate the sensitivity denominators and rates. The included sample must reproduce the manuscript's 20,902 flagged draws and original denominators. Do not assume the number of flagged draws remains unchanged.
2. **Activity standardization:** use the recovered original September 11 producer to rebuild modal time-control/rating features, activity membership, common support, target weights, standardized rates and joint uncertainty in each sample. Reproduce all 12 original aggregate tables in the included run before accepting the excluded results.
3. **Equal-weight contrast:** use the original chooser-level joint covariance to reproduce the three weighting estimates and their paired differences. Verify the manuscript's 0.646 (0.009), [0.628, 0.664] contrast in the included sample.
4. **Patron missing-outcome bounds:** these were already calculated in the prior run but the CSV-only exporter omitted their JSON output. Recompute only the original bounds from the authenticated existing design and fixed August snapshot, require exact agreement with the completed producer, and export the target/analysis flow and bounds. No Patron regressions are refitted and no missing outcomes are filled.

## Run

Save the ZIP in `~/Desktop/Lichess_Desktop`, verify its SHA256 and extract it into a fresh directory. Run `RUN_PROSE_CHECKS.command --workers 10 --memory-gb 11` under `caffeinate`. The default project is `/Volumes/XT_Pro/lichess_kindness`.

The same Python environment used for v1.4.2 is selected automatically. There are no dependency installations. A minimum of 6 GiB free space is required. Existing scientific inputs and prior results are read only; the new private work is under `derived/replication/author_exclusion_prose_v143_PRIVATE/`.

The command uses four concurrent monthly Parquet scans at 1.5 GB each, then up to ten DuckDB threads for the merge. The variants run sequentially. Intermediates use ZSTD Parquets, BLAS threads are limited to one, monthly feature caches resume, and completed variant outputs are verified and reused. Reports and ETA are exported at 0/25/50/75/100 percent.

Return **`AUTHOR_EXCLUSION_PROSE_<run-id>_100.zip` and its `.sha256`**. If the run stops, return the newest `_000.zip` and its sidecar. The final report retains the entire reviewed v1.4.2 report, adds the new aggregates, and supplies both new and combined Parquet comparisons. Private account-level caches are not exported.

## Manuscript review files

`manuscript_review/` contains 193 source-linked numerical replacements, two review copies of the current TeX sources, and diffs. The edits cover exact sample counts, period sums, persistence counts and verified printed rounding changes. The supplement retains the recovered original persistence methods note from v1.4.2.

These are **review copies, not publication-ready manuscripts**. Pending items are the material-screen paragraph, activity standardization, Patron target flow/bounds and reconciliation of figure assets. The copies propose the consistent exclusion policy and remove the old session exception; the proposed blanket wording must wait for review of the returned checks. Existing figures and bibliography files are not replaced or bundled. The source hashes and detailed edit ledger allow the changes to be applied to the correct manuscript version without overwriting later writing.

The final interpretation should distinguish **unchanged substantive conclusions** from **identical estimates**. Already-excluded IV and audited families have no newly estimated author-included counterfactual.

## Validation

Five focused tests cover both participant roles and flagged nongrants, the original parallel feature/standardization pipeline, changed cohort membership, source corruption, reproduction failure, semantic comparison keys, covariance in the equal-weight contrast, and missing-outcome bounds. The tests use synthetic data; production results require running the command on the Mac.
