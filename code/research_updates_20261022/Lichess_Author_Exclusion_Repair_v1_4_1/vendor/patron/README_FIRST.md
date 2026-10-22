# Patron Wave 3B1 v1.0.1: core paper estimates after the profile gap fill

Save the ZIP and its `.sha256` sidecar in `~/Desktop/Lichess_Desktop` and run the full command in `RUN_COMMAND.txt`.

**Expected runtime: 10–30 minutes**, estimated for the Mac that completed Wave 3A in 65 seconds. This job adds regressions and a second profile cohort; its full-data runtime has not yet been measured. It uses the existing Python environment, at most ten hashing workers, eight DuckDB threads by default, and single-threaded BLAS. No dependency changes or API calls are made.

The package uses the completed Wave-3A chooser histories and fixed new matches. It authenticates the September 11 gap-fill report and private supplement: all 122 previously unqueried controls returned, including 77 primary controls; 163 prior nonreturns remain unavailable, including 130 in the primary comparison. The frozen August snapshot is preserved. Missing profiles are handled explicitly under `ANALYSIS_SCOPE_AND_MISSINGNESS_AMENDMENT.md`; the earlier August coverage gate remains incomplete.

The August-only run rebuilds rich chooser features and estimates the main Patron contrast, covariate ladder, HC1/CR1 inference, the fair-versus-clearly-worse diagnostic, dose, price-side comparisons, and focused support/missingness sensitivities (34 fits). Four corrected-date fits remain separate. The supplemented sensitivity adds the 122 recovered profiles with their actual dates and repeats the main FE/full-control models and threshold-four state diagnostic with HC1/CR1, plus corrected dates (10 fits). There are 48 fits total. The inherited statistical functions are included unchanged and bound by SHA-256.

Both the cache and individual model results are checkpointed. Interrupted models restart; completed models are authenticated and reused. Covariance matrices are retained so resumed contrasts use their off-diagonal terms. All private Parquets stay on your machine. Only aggregate coefficients, support tables, bounds and receipts enter the return ZIP.

The primary group rule excludes controls whose focal kind profile did not return, matching the original v1.0.1 model family. The anticipated August-only primary sample is 851,131 accounts; supplementation raises it to 851,208 by adding 77 controls. Full-target bounds cover all 851,428 planned primary accounts in each cohort. Never code the remaining 130 missing primary profiles as non-Patrons. See the amendment for denominators and interpretation.

August-only files retain their original names. Supplemented outputs begin with `supplemented_`. `CORE_PATRON_COMPARISON.csv` places the core estimates from both cohorts together with explicit cohort labels. September observations never masquerade as recovered August outcomes.

Outputs:

- Private state: `/Volumes/XT_Pro/lichess_kindness/derived/replication/pool_main_reanalysis_v100_PRIVATE/wave3b1_patron/`
- Aggregate output: `/Volumes/XT_Pro/lichess_kindness/output/pool_main_reanalysis_v100/wave3b1_patron/`
- Result ZIP and sidecar: `~/Desktop/Lichess_Desktop/POOL_MAIN_PATRON_WAVE3B1_RESULTS_*.zip` and `.zip.sha256`.

Upload the two paths printed at completion. The 100 rematches, five-bin addendum, opportunity-level/ply/dyad appendices and integrated paper figures remain for later runs. Their old-sample numbers are not certified by this package.

This supersedes the unrun Wave-3B1 v1.0.0 launcher for the next analysis. Its new configuration uses a separate checkpoint directory; existing results and the certified snapshots are not overwritten.
