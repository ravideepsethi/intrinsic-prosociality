# Author exclusion repair v1.4.1

This continuation repairs the v1.4.0 run `3447163634d6d358`. It preserves the 12 earlier paired families, the completed responsibility, arena, and temporal families, and the verified current IV, entry-placebo, recipient-Patron, reputation, stakes, and Framework audits. It does not rerun the 4,999 temporal randomizations.

## What the returned run establishes

The report ZIP SHA256 is `e40a58c2e7355590c4df82dc462446a7ea668f085f91549ecfe178d3041de3a5`. All 688 report manifest entries verified. The run took 99.83 minutes. Nine variant stages failed across five families; a 100% report denotes completion of attempted work, not successful completion of every analysis.

The corrected comparison covers 256 aggregate tables across 15 completed paired families, with 27,041 point estimates and 222,669 numeric metrics. There are no unresolved table alignments, row-membership mismatches, identification-status changes, coefficient sign changes, or crossings of the approximate 95% zero boundary. The largest coefficient change is 0.0209698 included-sample standard errors. This is evidence of very small effects in completed comparisons, not an automatic equivalence test or a paper-wide clearance.

The 53 corrected responsibility models have zero author-game hits. The full analytical and nuisance-training temporal sample has zero author-game hits, so its original 4,999 draws remain valid. Current receipt-IV audits cover 134 models and four distinct frames, plus the already verified author-clean donor/nuisance construction. All four entry/ordinary-placebo frames are author-clean. Those audits do not create a new author-included IV counterfactual.

## Repairs

1. Patron sensitivities and C6 now follow copied completion receipts back to the authenticated original v100 private caches. The original configuration, copied receipt, and original aggregates must agree; no arbitrary directory fallback is permitted. Leaf receipts continue to authenticate cache bytes.
2. Tenure quotes the `month` SQL alias. The projection, sample, estimation functions, factual ages, frozen account roster, and no-replacement policy otherwise remain the same.
3. First/repeat retains the original status of three repeat-only auxiliary models that did not converge in the original producer. These are not the manuscript's repeat gradient, which comes from a successful pooled interaction model and its covariance. Every previously successful model must remain successful, all three recorded failures must be the same convergence-error class, and the manuscript's pooled gradients and within-competitive estimate must reproduce in the included pass. Failure diagnostics are saved before validation.
4. The comparator uses `horizon_hours` for temporal tables and treats `competitive` as a measured count in the merit monthly validation table. All 256 available tables now align.
5. Persistence uses one explicitly declared reconstruction candidate: outcome-specific second-year opportunity weights with joint account-level HC1 covariance, while retaining equal-account OLS as a diagnostic. This is motivated by the manuscript's pooled outcome means; the original producer has not been recovered. The candidate is not accepted unless the included pass reproduces the printed means, counts, coefficients, standard errors, contrasts, and correlation checks. A mismatch remains a failed stage and prevents paper-wide clearance. No search across specifications or relaxed tolerances is performed.

The persistence correlation/cohort checks already reproduced in v140; the regression mismatch existed in the included baseline, so it was not an effect of author exclusion. Printed after-ply-10 transition counts also sum to 266,399 whereas the positive-exposure correlation cohort has 265,901 accounts. That manuscript distinction still needs review; no silent recoding of an unobserved rate to zero is authorized by this package.

## Run

Save the ZIP in `~/Desktop/Lichess_Desktop`, verify its SHA256 from the chat command, extract to a new temporary directory, and run `RUN_REMAINING.command --workers 10 --memory-gb 11` under `caffeinate`.

Expected runtime: approximately **2–7 hours**, provisional. The ten new variant jobs are first/repeat, persistence reconstruction, tenure, remaining Patron, and C6, each included and excluded. Authentication and final reporting are included. No new API requests, engine searches, all-game chronology scans, or temporal randomizations are scheduled. The full original project caches must remain available. The launcher still requires at least 40 GiB free on the project volume.

The runner uses ZSTD Parquets, up to 10 workers or DuckDB threads within a single active family, single-threaded BLAS, and four concurrent readers for main-input authentication. It writes a separate v141 run directory, locks the reviewed parent and current runs, and retains successful stage receipts on restart. It authenticates the exact returned v140 report before reusing completed work. A failed stage does not prevent other families from proceeding.

Reports are written at 0/25/50/75/100 percent with estimated time to the next checkpoint and finish. Return the new `AUTHOR_EXCLUSION_REPORT_<run-id>_100.zip` and `.sha256`, even if the terminal says that some stages require review. Do not rerun the v140 launcher as the repair.

## Limits

Production data are on the user's Mac. Local tests exercise the reported failure modes and statistical calculations on synthetic data. They do not demonstrate that all new production stages will pass. In particular, the persistence reconstruction remains conditional. `CLAIM_STATUS.json` will not automatically establish substantive invariance; manuscript counts, notes, and every retained result still require review.
