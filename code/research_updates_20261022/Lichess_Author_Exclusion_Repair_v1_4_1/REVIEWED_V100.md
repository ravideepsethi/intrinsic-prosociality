# Review of the returned v1.0.0 final report

Reviewed run: **48e64c24eaf7e401**. ZIP checksum and all 228 report-file checksums matched. Recorded elapsed time: **9,566 seconds (2 h 39 min 26 s)**.

Seven paired families completed: core; panel robustness; controlled reference; continuous merit; R11; primary Patron; matched receipt. Rating-gap failed during aggregate export after the producer completed. Session failed; the exact traceback was not in the returned report. Their excluded variants, and both dependent nonparametric variants, were not completed.

The revised comparator now aligns **all 106 returned paired tables**, with **zero unaligned tables, unmatched rows, or status changes**. It compares 58,520 numeric fields, including 7,229 estimates/descriptive measures. Of these, 3,624 have a positive included standard error that permits a standardized change. These counts include repeat presentations and descriptive points; they are not counts of independent tests.

There are **no sign changes** among the compared measures and **no changes in the approximate 95% zero-boundary classification** where corresponding standard errors are available. The largest absolute change is **0.017919 included standard errors**, in the secondary 10-minute reentry coefficient. Its change is about **0.000030 percentage points**. This is a descriptive stability assessment, not an independent-samples significance test or a formal equivalence test.

| Quantity | Included | Excluded |
|---|---:|---:|
| Analytical opportunities | 41,534,331 | 41,534,289 |
| Grants | 570,091 | 570,090 |
| Choosers | 3,224,173 | 3,224,171 |
| Competitive opportunities | 15,207,423 | 15,207,414 |
| Competitive grant rate (%) | 2.758277980 | 2.758273037 |
| Primary matched-receipt coefficient (pp) | 0.881658360917 | 0.881658365142 |

Thus the main analytical panel loses **42 opportunities and one grant**. The completed comparisons support negligible numerical changes for these families. This report does not establish exclusion or stability for the entire manuscript.

The original comparison missed 43 tables. The repair recognizes pandas nullable string columns, registers numeric bin/cutoff dimensions explicitly, excludes mutable sample hashes from matching keys, and pairs multiple coefficients with their corresponding standard errors. It never aligns by row order. Recomputed comparison CSVs and ZSTD Parquets are in `evidence/reviewed_comparison/`.

Provisional remaining runtime for the continuation: **1½–6 hours**, depending on SSD/cache availability and the audits. Actual Mac production execution remains to be completed.
