# Corrections after the first empirical run

The v1.0.0 run `bb37d1b1d1a3` finished with three failed stages. Its raw persistence estimates are unaffected by the errors below. No v1.0.1 empirical results have yet been produced on the user's Mac.

1. **Complete chooser histories for Test B.** DuckDB's partitioned COPY produced 2,381 physical files across 128 account buckets. More than one file could contain the same chooser. The old B worker classified and demeaned each physical file separately. Version 1.0.1 consolidates all fragments of a bucket into exactly one file, checks the chooser hash assignment and total row count, and re-estimates every B model, profile and conditional logit. The old B estimates and B-based D trigger must not be used. D is reconsidered after corrected B.
2. **Adjusted persistence aggregation.** Nuisance fits and opportunity residuals do not need whole-account physical files: moments and residual sums are additive. The error was in concatenating fragment-level account summaries without adding their counts and residual sums. The repair sums by chooser/year/state/stage restriction and requires exact agreement with the valid raw opportunity counts. Saved nuisance fits and scores are authenticated and reused. Duplicate account cells now fail explicitly.
3. **Subgroup IV follow-up validation.** Frozen S0 does not contain the F50-only `complete90` column. Its producer checks `anchor_ms + 90 days < PANEL_END`. The repair uses exactly that strict timestamp rule, checks anchors and binary outcomes, and preserves the original S0 cohort and controls. No rows are substituted or dropped to pass the check.
4. **Conditional logit convergence.** The identified design is whitened; an exact Newton refinement follows L-BFGS. Convergence requires the largest proposed change in any fitted log-odds to be below 0.00001. Singular information or failed stationarity remains a failure. No ridge, likelihood approximation or relaxed significance test is introduced.

## Reuse and limits

The supplied command binds the original configuration and package hash, validates saved source/output receipts and the returned aggregate report manifest, and writes a separate v1.0.1 run. It retains A, A3, C, matched E and raw F; it does not overwrite the parent or stop other processes. Private chooser/game data stay on the external drive. Exported checkpoints contain only aggregate reports.

The existing C forward high-exposure zero-granter cohort was empty. Reusing C preserves that limitation; it does not create a forward-validation result. The C mixture comparison is sensitive to whether the population mean is preserved and does not establish a psychological gate. The E subgroup IV remains the original frozen R7 score specification, not a replacement for separately developed leave-pair-out IV analyses.

Bootstrap intervals for adjusted persistence condition on the saved nuisance fits. Account retention and state-dependent measurement precision still limit comparisons of raw correlations. Positive correlation does not identify a psychological preference parameter.
