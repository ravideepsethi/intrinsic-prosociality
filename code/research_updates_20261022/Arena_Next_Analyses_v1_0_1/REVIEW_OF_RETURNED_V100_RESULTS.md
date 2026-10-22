# Arena analyses: review of the September 14 results

The new results strengthen the case that kindness in arena games contains
systematic behavior. Persistence, excess temporal clustering, board-state
sensitivity and the Patron association survive in the tournament subsample.
Local price-kink evidence remains inconclusive. Receipt/IV has not yet run.
Together with the earlier within-player arena–pool suppression estimates,
these findings weigh against a simple, context-independent misclick explanation.
They do not exclude every context-dependent error mechanism or establish a
causal effect of tournament participation.

The uploaded archive's SHA-256 and every one of its 83 manifest entries match.
It contains 84 files including the manifest. The production run took about
7.3 minutes before stopping in receipt/IV authentication.

| Analysis family | Completed work | Qualification |
|---|---|---|
| Original core analysis | 52 fits and original split-half tables | Two fits have aliased clock controls; their nonidentifiable individual coefficients are suppressed. |
| Panel robustness | 24 fits | No nonestimable terms flagged. |
| Targeted rating-gap repair | Three year-two curves reestimated | The early-game full specification remains unsupported. |
| Episodes | 4,999 conditional randomizations | Selected repeat granters; not all arena players. |
| Patron | 34 models plus four date-corrected sensitivities | Fixed August 2026 snapshot; observational association. |
| Receipt / chooser-history IV | No estimates | Failed before the history scan on a configuration-hash check. |

The screened arena sample contains **1,892,835 opportunities and 20,325 kind
draws**, including **730,717 competitive opportunities and 12,829 competitive
kind draws**, from 278,151 players with competitive opportunities. The pool
main sample remains unchanged.

**The clearest new findings**

| Finding | Result | Interpretation |
|---|---|---|
| Persistence across years | Among players with at least four competitive opportunities in total and observations in both years, second-year kindness is **11.07%** after any first-year kindness versus **0.695%** after none. | Behavior persists; this descriptive comparison is not a treatment effect. |
| Original split-half correlation | Hashed-game split: **r = .456**, 44,026 players. First-year/second-year split: **r = .377**, 31,371 players. Both use the four-opportunity total cutoff. | The original producer's definitions replicate persistence within arenas. These are not the earlier adapter's minimum-per-half definitions. |
| Episode clustering | At the primary 24-hour kernel, observed statistic **73.34**, conditional-null mean **55.78**; **Holm-adjusted p = .0012**. All three kernels have adjusted p = .0012. | Kindness clusters more than the fitted conditional null predicts, after fixing each chooser's opportunity and kindness totals and accounting for current-state propensities. |
| Raw Patron comparison | **87/9,998 = 0.870%** among competitive arena granters; **170/29,972 = 0.567%** among matched controls. Difference **+0.303 percentage points**, reported 95% CI **[+0.102, +0.504]**. | Arena kindness is associated with the external Patron indicator. |
| Patron with available controls | **+0.417 percentage points**, HC1 95% CI **[+0.212, +0.622]**; match-cell CR1 sensitivity **[+0.139, +0.696]**, 31 clusters. | The association survives the available adjustment set. Corrected-date estimates are virtually identical. |

The episode sample consists of **857 players, 10,725 opportunities and 2,977
kind draws**. It represents 0.31% of competitive arena players, 1.47% of
competitive opportunities and 23.21% of competitive grants. Its result is
about sequencing among repeat granters. It is not a population-wide estimate
of how many people experience a kindness episode, and the randomization test
is conditional on the fitted propensity model.

For Patron missingness, one of 9,999 primary target granters and seven of
29,982 target controls have unknown outcomes. Allowing all possible binary
values gives a match-cell-adjusted gap between **+0.274 and +0.312 percentage
points**. These are missing-outcome bounds, not confidence intervals and not
bounds for the fully controlled model. Some requested profile count variables
are entirely missing and several nuisance controls are aliased; “available
controls” should not be described as complete observed engagement adjustment.

The joint Patron model distinguishes kindness in competitive and clearly lost
positions. At the original minimum-four-opportunities-in-each-state rule, the
competitive-minus-lost association is **+1.132 percentage points** with HC1
95% CI **[+0.310, +1.953]**. The clustered sensitivity has only 19 match-cell
clusters and a borderline normal-approximation p value of .046. This is useful
supporting evidence; it should not be presented as a uniformly strong result
under every inference choice.

**Board merit and price: separate what survives from what is uncertain**

Kindness rises with the disconnected player's board position: **0.611%** when
clearly worse, **1.354%** when roughly equal, **1.613%** when better and
**2.914%** when clearly better. These are raw rates. In the chooser fixed-effects
model with available controls, the board-evaluation coefficient is **+0.201
percentage points per 100 centipawns** (SE .0139), and the favorable-price
coefficient at zero evaluation is **+0.550 percentage points** (SE .0434).
The price-by-evaluation interaction is small and imprecise: **+.0061** (SE .0187).

The simple chooser fixed-effects comparison of nonnegative versus negative
draw-rating consequences depends on the payoff window:

| Absolute draw-payoff window | Favorable-minus-costly estimate, percentage points | Clustered SE |
|---|---:|---:|
| 0.5 rating points | −0.015 | 0.101 |
| 1 rating point | +0.137 | 0.068 |
| 2 rating points | +0.233 | 0.049 |
| 4 rating points | +0.445 | 0.041 |
| 6 rating points | +0.617 | 0.040 |

Excluding exact-zero payoffs preserves the two-point-window premium
(**+.229**, SE .049). But the flexible local piecewise model at the one-point
window gives a threshold jump of **−.026** (SE .121) and slope asymmetry
**+.0207** (SE .2337). The local slope-asymmetry tests at the reported 0.5-, 1-
and 2-point windows do not establish a kink at the 5% level. Broad favorable
price sensitivity should therefore not be described as a sharply identified
local discontinuity or loss-aversion kink. A favorable rating consequence from
a draw also does not make granting it costless: the chooser still forgoes the
win premium.

**The earlier suppression result remains the direct tournament comparison**

These are retained v1.0.2 results, not estimates newly generated in this run:

| Arena-minus-pool comparison, competitive positions | Estimate, percentage points | 95% CI |
|---|---:|---:|
| Within chooser, with time-control/month and other controls | −0.977 | [−1.045, −0.909] |
| Within the same chooser × exact time control × month | −0.816 | [−0.962, −0.670] |
| Games after ply 10 | −0.838 | [−0.912, −0.763] |

The new arena-only findings complement that suppression evidence. They show
that the remaining arena kindness retains several behavioral patterns found in
the broader analysis. An arena-only regression cannot itself estimate the
arena–pool suppression contrast.

**What the repair does next**

The old hash check used compact JSON, while earlier repository producers use
sorted JSON with spaces. The revised adapter supports both observed formats
against the unchanged expected digest. The actual historical configuration was
not returned in this archive, so the Mac must still verify it. Changed
configuration content remains an error. The report will now record the failed
authentication phase and both observed hashes if neither matches.

Version 1.0.1 imports the verified results for all five completed families,
retains their original receipts and runs only receipt/IV. The unfinished step
scans 852 canonical history files containing about 7.76 billion rows and has a
checkpoint per file. Its runtime has not been benchmarked for this arena cohort.
The repair passes 15 top-level local tests, including the original IV numerical
tests and checks of the actual completed-results import; this is not a claim
that the production receipt/IV stage has completed.

The primary receipt outcome selects the next competitive opportunity against
a different opponent across all sources first, then asks whether it was a
screened arena opportunity with a kind grant. It never skips an intervening
pool opportunity to create an arena-to-arena transition. Arena reach is reported
separately. First-stage strength, common support and weak-instrument intervals
still need to be assessed from the forthcoming output.

The arena sample supports many central analyses, but not literally every full
specification. The unsupported early-game rating-gap model has only 43
within-chooser dimensions for 67 varying terms. Arena ordinary-game controls,
the full A3/reentry and later dynamics families, and other extensions are also
outside this runner. Missing or unsupported estimates must remain missing.

**Sources**

The numeric sources are the uploaded report's `RUN_STATUS.json`, `INPUT_QA.json`,
`core/tables/`, `core/NUMERICAL_AUDIT.json`, `robustness/tables/`,
`episodes/RESULTS.json`, `patron/` and `rank_repair/TARGETED_REPAIR.json`.
Suppression estimates come from the earlier verified v1.0.2 report's
`suppression/competitive_full.json`, `competitive_within_player_tc_month.json`
and `competitive_long.json`. `ARENA_NEXT_V100_REVIEW_AUDIT.json` records the
archive identity and supporting file hashes.

The unchanged statistical sources are pinned to repository commit
`bf3b2bf9ffedba8f53c61e3e1b55bb457e58a129`. The legacy JSON hash definition
is visible in the [original preliminary producer](https://github.com/ravideepsethi/intrinsic-prosociality/blob/bf3b2bf9ffedba8f53c61e3e1b55bb457e58a129/code/pool_main_reanalysis_v100/Pool_Main_Sample_Reanalysis_Wave2A_v1_0_1/source/chooser_leniency/run_preliminary.py);
the incompatible compact definition is in the [rebuild I/O utility](https://github.com/ravideepsethi/intrinsic-prosociality/blob/bf3b2bf9ffedba8f53c61e3e1b55bb457e58a129/code/pool_main_reanalysis_v100/Chooser_IV_Main_Rebuild_v1_0_0/local_io.py).
