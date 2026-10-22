# R8 Current Data v1.0.0

Run the next analyses from the existing Mac data. This package covers R8 items 1, 2, 4, and 3(2), with author exclusions applied to the affected analyses. It does not claim to complete all R8 work.

## Run on the R7 Mac

Put `R8_Current_Data_v1_0_0.zip` and `R8_Current_Data_v1_0_0.zip.sha256` in `~/Desktop/Lichess_Desktop`, then paste:

```bash
(
  set -euo pipefail
  cd "$HOME/Desktop/Lichess_Desktop"
  shasum -a 256 -c R8_Current_Data_v1_0_0.zip.sha256
  r8_unpack="$(mktemp -d "$HOME/Desktop/Lichess_Desktop/r8_current_data.XXXXXX")"
  ditto -x -k R8_Current_Data_v1_0_0.zip "$r8_unpack"
  /bin/bash "$r8_unpack/R8_Current_Data_v1_0_0/RUN_R8_CURRENT_DATA.command" --workers 10 --memory-gb 11
)
```

Expected wall time: **3–6 hours**, provisional and not benchmarked on the Mac. R7 took about 2 h 49 min; this run avoids its expensive cross-fitted calibration refits but adds all-source history authentication, subgroup IVs, Patron fits and clock controls. External-disk hashing and SQL scans can dominate. Plan for at least 20 GiB free on XT_Pro; new retained narrow projections and checkpoints are expected to use roughly 5–10 GiB, with additional temporary spill possible.

The launcher uses `/Volumes/XT_Pro/lichess_kindness/venv/bin/python`, the same research environment as R7. It needs installed NumPy, pandas, SciPy, PyArrow and DuckDB, Python 3.10+. It downloads nothing. Set `IV_PYTHON` to another already installed research Python if necessary. `IV_PROJECT_ROOT` and `IV_DESKTOP` override the two standard paths. `/usr/bin/caffeinate -i` prevents idle sleep during the analysis.

Up to 10 workers, one numerical-library thread per worker. Modules run sequentially. Clock workers are reduced automatically using the largest chooser-complete partition and the 11 GiB working budget. This is a memory plan, not an OS-enforced RSS limit. Receipt R² checks on all 7,371,688 F50 rows require a 10–11 GiB budget. No new Stockfish searches, API calls, profile queries or game downloads occur.

Logs and a timestamped `R8_CURRENT_DATA_RESULT_*.zip` plus `.sha256` are written to `~/Desktop/Lichess_Desktop`. Return those **three files**. A failed module is marked `BLOCKED`; independent modules still run, and the result ZIP records the partial state. Only successfully verified module reports enter the ZIP. Private account/game rows remain on XT_Pro.

Paste the same command after interruption. It unpacks a fresh copy but binds the same code/configuration key and reuses certified checkpoints. Changed source signatures or output hashes stop reuse. The launcher rejects a duplicate concurrent run of the same configuration. It does not change the completed R7/Patron source directories. Uncommitted generated clock partitions are replaced after interruption; certified partitions and completed model shards are retained.

Optional isolated runs, from the unpacked package directory:

```bash
/bin/bash RUN_R8_CURRENT_DATA.command --modules receipt --memory-gb 11
/bin/bash RUN_R8_CURRENT_DATA.command --modules patron --memory-gb 11
/bin/bash RUN_R8_CURRENT_DATA.command --modules clocks --workers 10 --memory-gb 11
/bin/bash RUN_R8_CURRENT_DATA.command --status
```

Runs share module checkpoints across selections. `--r7-root PATH` permits an explicit completed R7 root, but it must match the exact reviewed configuration and aggregate hashes.

## Input contracts and baseline gates

| Input | Frozen contract |
| --- | --- |
| Completed R7 v1.0.3 | Config `7ab926c925a48b25bb2fe8bfcc170059e4601d912f9fc3099b846c8f7310110d`; 34 models; all nine original/ENV/phase-50 reproduction checks passed |
| R7 state | `derived/replication/r7_analysis_v103_PRIVATE/7ab926c925a4` |
| S0 | Archived author-clean 2,682,329 exposure rows; original 2,682,330 retained for baseline authentication only |
| F50 / O50 | 7,371,688 / 4,764,089 frozen rows; completed later-outcome attachment required |
| Main gradient/Patron source | 24 months, 41,534,331 main pool/nonadjacent opportunities; fingerprint `a17c89d750cb4fdfdf84f950859e45c58b19996efae02045def68285e305cf30` |
| All-source chronology | The 24 authenticated Stockfish-100k source panels bound through the original main manifest: 47,587,020 rows, including adjacent pairs and all sources |
| August Patron snapshot | 1,305,872 rows; SHA256 `f42f28a6540a65c0a83f0da488663b4adddf60d1001daeed556f1ffbb961e238` |
| Patron matches / cache | Original Wave-3A `f9dfa2718056` matching state and Wave-3B1 `9a64f1f9b8f8` August-only design checkpoint |

R7’s attached ZIP and all 61 report-manifest entries were authenticated during preparation. The package pins those same aggregates. On the Mac, receipt binds their completed source/checkpoint contracts and reproduces every trait-prediction coefficient before adding R². Patron must reproduce 851,131/599,045 accounts, 36/24 cells, the full-control coefficient/SE pairs 0.276884, 0.388434 and −0.194593, their 0.583027 contrast, and exact main raw numerator/denominator counts. Clocks must reproduce 11,590,459 rows and all three full-precision spline contrast/chooser-cluster SE pairs before any new gradient fit.

## What each module produces

**Receipt, R8-2 and R8-4.** Reuse R7’s in-sample and account-excluding cross-fitted predicted-Y/predicted-D calibrations, with their original full first-order uncertainty. Add the incremental partial R² from T15 beyond FE and NH, and the full FE+NH+T15 R²; label both as in-sample fit statistics. Do not infer out-of-sample predictive accuracy from them.

The reviewed S0 predicted-Y NH calibration is 0.003879 pp (SE 0.001922), about 19% of the 0.020387 pp headline reduced form. It does **not** satisfy the specification’s “below about a tenth” heuristic. The full-control outer calibration is separately labelled; it does not replace the specified NH outer model. Observed-trait calibration is not identified bias from all sources of selection.

The primary experience indicator uses the recipient’s first completed competitive grant-or-claim chooser event in the complete recorded all-source chronology, strictly before the exposure `anchor_ms`. Games involving either author are excluded. Also report how many classifications change if exposure game start is used instead. “Never faced” means no earlier event in November 2023–October 2025; it is left-censored, not a lifetime assertion. The secondary 90-day counts must reproduce 1,319,101 / 1,291,893 / 71,335 exactly and nest inside the primary history.

Each group reports receipt prevalence, FS/RF per exact frozen reference SD 0.059411690344000595, 2SLS, Wald and null-restricted AR intervals, first-stage F and row-set hash. Separately fitted group differences include shared-account/date covariance across groups. The conservative AR-type difference set projects two marginal 97.5% AR sets by Bonferroni. A distinct pooled common-X0/FE interacted IV reports the joint Wald difference. The conservative AR set is **not** labelled as the pooled common-nuisance AR interval.

**Patron, R8-1.** From the fixed August snapshot, flag stored `tos_violation OR disabled`. Keep `queried_nonreturn` and `not_planned_in_august` distinct. Report counts and rates in all four state groups, unflagged Panels A/B/C, joint fair/lost difference, HC1 and match-cell CR1. Optional absent flags retain the original snapshot semantics. CR1 uses a normal approximation with few matching cells.

Before R8 fits, remove all main-panel games with either author on either side. Rebuild the affected third-party histories using the unchanged original summary/cache producers; recompute group labels after merging; remove author accounts and groups lacking a retained focal. Keep original matching cells and selected control slots; no replacement matching or refreshed profiles. Profile imputation is recomputed on author-clean returned accounts before flag exclusion, then held fixed.

Sharp binary-outcome bounds optimize each coefficient’s signed OLS weights. They are identification bounds, not confidence intervals; lower/upper outcomes for different coefficients need not be the same completion. Full-profile-design bounds treat flagged **returned** profiles as unknown. A separately labelled joint FE/exposure-volume design includes flagged and unavailable outcomes, since nonreturning profiles cannot supply full profile covariates. Main raw/cell-FE bounds also retain unavailable outcomes.

**Clocks, R8-3(2).** Keep the original unconstrained natural spline (boundary −100/+600; knots 0/+100/+300; finite ≥600 and positive mate separate), chooser/month/speed/stage controls and chooser-cluster CR1. Fit author-clean baseline, both players’ clock-share categories by four speed groups, and both players’ `log1p(seconds)` plus missing indicators by speed. Ultrabullet/bullet share an interaction group; the original five speed fixed effects remain. Categories are `[0,.10)`, `[.10,.25)`, `[.25,.50)`, `[.50,1]` reference, `(1,∞)`, missing. Negative/nonfinite clocks and nonpositive/missing base are missing categories. Log-clock fits need only an observed nonnegative clock. All three models retain identical rows, including missing clocks, singleton and never-grant choosers. Report own/opponent category coefficients, all three contrasts, SEs and Holm p values. Nonestimable terms are explicitly unsupported.

## Work that remains open

| R8 item | Remaining dependency |
| --- | --- |
| 3(1), winning chances | New 2,000,000-position Stockfish-18/100k evaluation run and verified out-of-fold multinomial calibration; not an offline reuse task |
| 3(3), whole-game performance | Exact 20,000-chooser / 260,863-opportunity replay producer and score cache remain unbound. No guessed source or substitute ACPL estimate is used. Signed finite-budget evaluation changes need not be nonnegative move losses; the eventual producer must verify its best-versus-played convention and endpoint decomposition. |
| 5, paper-wide author claim | This package supplies affected Patron and gradient reruns and relies on author-clean R7 receipt inputs. Table 2 persistence, Table 4 diffusion and full Table 1 displayed-precision checks still need their exact producers. Keep the “all reported values unchanged” claim unresolved. |

No manuscript TODOs are automatically deleted, and no submission/causal-identification gate is cleared. The result ledger always keeps these dependencies visible.

## Validation and source handling

The new numerical tests use independent explicit dummy-variable least squares, explicit pair-indicator covariance, exhaustive binary outcome assignments, full-versus-incremental author-history reconstruction, and complete-chooser partition comparisons. Production counts are never bypassed for synthetic fixtures. Tests include a spawned two-pass worker path, input/output tampering, offline socket rejection, and aggregate-only ZIP export.

Validation on the build machine is synthetic and operational. The large data are on XT_Pro; production baseline gates and new estimates run there. `VALIDATION.json` records the checks actually executed. Frozen R7, merit and Patron producers are vendored unchanged; `PACKAGE_MANIFEST.sha256` authenticates all delivered code and evidence. The standalone ZIP checksum authenticates the complete download.
