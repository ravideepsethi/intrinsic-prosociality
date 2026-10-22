RUN 2 — ENTRY DIAGNOSTICS v1.0.0

Run RUN_ENTRY_DIAGNOSTICS.command after the completed 25% v1.2.2 analysis.
Default data root: /Volumes/XT_Pro/lichess_kindness
Default reports: ~/Desktop/Lichess_Desktop
Run with --workers 10. The runner caps work to physical resources and the memory
budget; large model fits run with fewer concurrent processes than small tasks.
SciPy is not required. The existing research Python environment is reused.

Expected runtime: about 15–40 minutes on the user's laptop, unbenchmarked.
This is based on the completed 25% stage timings, not a measured run of this
new package. Its 64-minute chronology stage is entirely avoided. Competing SSD
work can add time. Reruns reuse completed checkpoints. Self-tests: 10–40 seconds.

WHAT THIS ANSWERS
1. Does the earlier entry association reproduce exactly?
2. Does restricting to accounts with >=5 competitive history decisions change it?
3. On those same rows, does the competitive-only score also predict entry?
4. Is the association already present at observed recipient disconnection,
   at the competitive arm, or only after the final receipt-sample rules?
5. How does it change as fixed groups of pregame controls are added?
6. Is residual instrument variation concentrated above the previously frozen
   ordinary-game top-5% cutoff?

HOW TO READ
Open the returned report's READ_RESULTS.txt and entry_comparison.csv.
For each outcome, compare these five rows:
  pooled_all_X0
  pooled_common_X0
  competitive_common_X0
  pooled_common_XC
  competitive_common_XC
X0 reproduces the original rich design. XC adds competitive-history expected
rate, number of decisions, and number of counterparts to BOTH score regressions.
The principal new row is new_phase25 / competitive_common_XC / analysis_entry_90.

All five entry labels use the same pre-entry all-ending denominator:
  active_timeout
  recipient_disconnect_main
  recipient_fair_arm_main
  selected_entry_90
  analysis_entry_90
They refer to the focal game, not the recipient's later choice. The recorded
main-panel disconnection label is narrower than all physical disconnections.
Four stage-loss outcomes account for differences between adjacent nested labels.
Their coefficient differences are accounting identities, not causal mediation.
The code checks nesting rather than silently recoding contradictory records.

SAMPLE AND INFERENCE
Uses the completed, reviewed 25% run 79bd3599a995, its original first10 and added
10–25 hash bands, and its earlier author-clean/pooled samples. The latter two
are supplemental. Different game bands can still share accounts.
No re-selection, new exclusions, replacement rows or conditioning on realized
entry occurs. The two reviewed metadata quarantines remain unchanged.

Frozen assignment/time fixed effects and shared-account OR exposure-date CR0
covariance. Historical scores are treated as fixed, as in the completed report.
All new diagnostics are post-result analyses with nominal interim intervals.
Holm adjustment covers the five stages x two scores within each common-row
X0/XC family/cohort, not all prior looks or the exploratory control ladder.
A nonsignificant coefficient does not establish equivalence or exclusion.
No main receipt IV, receipt first stage, 2SLS or ordinary-game placebo is rerun.

SCORE DEFINITION AND UNITS
Same author-clean historical residualization and exact pair exclusion as the
25% competitive ordinary-game diagnostic. The history cutoff is seven days
before the exposure MONTH's start (the frozen monthly instrument), not a new
rolling cutoff relative to each game. Competitive means the disconnected
player's audited historical state is at least -100 cp. Minimum five eligible
competitive decisions. All cached state and lag definitions are preserved.

The fixed reference SDs differ between the two scores. coefficient_pp is pp per
that score's fixed SD. coefficient_pp_per_raw_0_10 is pp per identical raw 0.10
score increment. same_row_slope_contrasts uses the latter and accounts for
covariance between the two fitted slopes. It is not a difference of independent
estimates or a comparison of two causal receipt effects.
The original +0.0204 ordinary-outcome benchmark is not reused as an entry margin.

PERFORMANCE AND RESUMPTION
- Reads only completed entry Parquets, cached score definitions/reference and
  sufficient-statistic indexes; never scans raw PGNs or all-game chronology.
- Reuses cached competitive scores and computes only missing entry-game scores.
- Projects required columns into model Parquets; computes all stage outcomes
  together and absorbs fixed effects once per sample for the control ladder.
- Uses up to 10 single-threaded processes, with no nested BLAS oversubscription.
- Budgets concurrent regression memory from input size; schedules smaller jobs
  alongside large jobs only when they fit. No automatic swapping to disk-sized
  dense matrices. Use --memory-gb to supply a deliberate memory budget.
- Atomic Parquet/checksum checkpoints, exclusive run lock, stage timings, and
  small aggregate reports after reproduction, support and final estimation.
- The downloader can continue in another terminal. Zero API calls.

OUTPUT
Desktop: RUN2_ENTRY_DIAGNOSTICS_REPORT_<configuration>.zip and its checksum.
Private resumable work:
derived/replication/run2_entry_diagnostics_v100_PRIVATE/<configuration>/
Reports include CSV, JSON and Parquet tables; no row-level IDs or usernames.
The new score blocks use the existing compatible competitive-score cache.
A moved parent can be supplied with --parent /exact/completed/25percent/folder.
Missing finished inputs cause an explicit stop; this runner does not rebuild
upstream stages or substitute an unreviewed analysis.

VALIDATION
The release is tested from a fresh ZIP extraction, including nested manifests,
synthetic numerical reproduction, common-row controls, clustered contrasts,
rare-event flags, strict cached-score history/pair/author rules, missing inputs,
real spawned fits, full synthetic execution and resumption. This does not mean
it has already run on the private Mac production Parquets.
