# Research source update — 22 October 2026

This release adds source snapshots from 107 recovered research packages to the
September 11 public repository. It includes analysis code, tests, launchers,
methods/readme files, dependency lists, selected scientific specifications, and
file-level provenance. It does not replace the September numerical results or
claim that the current manuscript is reproducible end to end from this checkout.

## Start here

| Work | Source to inspect | Release interpretation |
|---|---|---|
| Receipt IV, uniform 90-day histories | `Receipt_IV_Uniform90_FastResume_v1_0_5` and `Receipt_IV_Model5_Submission_v1_0_0` | Latest recovered parent/resume and supplement code. A final combined production report is not certified by this code release. |
| All-time-five eligibility and entry placebo | `AllTime_IV_Primary_v1_0_3`, `AllTime_Entry_Placebo_v1_0_5` | Predecessor stages and construction dependencies; do not mix their estimates with later Uniform90 output. |
| Author exclusion | `Lichess_Author_Exclusion_v1_0_0`, repair `v1_4_1`, persistence `v1_4_2`, prose checks `v1_4_3` | Remove both author accounts in either role and from affected behavioral reference populations. Later continuations depend on earlier authenticated caches. This is not a blanket clearance of all historical outputs. |
| Structural and mechanism analyses | `R7_Analysis_v1_0_3`, `R10_Two_Questions_v1_0_2`, `R11_Region_Gap_v1_0_0`, and the Pool/Mechanism packages below | Versioned producers and their original method contracts. |
| Receipt reconstruction and diagnostics | `R8_Receipt_Independent_v1_0_4`, `R9_Certified_Leave_Pair_Out_v1_0_0`, `R9_ENV_Memory_Resume_v1_0_1`, `R9b_Remaining_Diagnostics_v1_0_0` | Historical source dependencies for the later receipt pipeline. |
| R12/R13 and comparison sample | `R12_R13_Local_Runner_v1_0_3`, `Run2_Phase100_Final_v1_0_0`, `Comparison_TotalFive_Recovery_v1_0_0` | Preserve separate run identities and any pending comparisons; a filename containing “Final” does not certify a successful run. |
| Recipient Patron analysis | `Patron_TotalFive_Migration_v1_0_1`, `Patron_IV_Coverage_Audit_v1_0_1` | Source only; earlier Patron estimates retain their own sample definitions. |
| Countdown analysis | `Countdown_Feasibility_v1_0_0`, `Countdown_Estimation_v1_0_0` | Exploratory design, including numerical and support checks. Its authenticated input contract has 41,534,289 author-excluded rows, not the unfiltered September count. |
| Framework and counterfactual outcome tests | `Framework_Tests_*`, `Framework_AE_Completion_v1_2_0`, `Framework_E_Repair_v1_2_1`, `Test_G_v2_1_1` | Distinct packages; version numbers across the two Framework branches do not imply a single sequence. No production completion claim for Test G. |
| Figures | `Lichess_Paper_Figures_v1_1_0`, `Lichess_Figures_2_3_4_v1_0_1` | Rendering source is included; bundled figure inputs and rendered figures are not republished in this source update. |
| Pool-main C13 | `Pool_Main_C13_FamilyD_v1_0_0` | The returned September report was recovered: 16 estimated attempts and 3 retained failures. Exact family-D reconciliation still lacks C1/C2/C5 authorities in that report. |

## Source fidelity and private configuration

Unchanged source files retain their exact original bytes. Files containing
private account values or a personal home path are published as `.in` templates;
only those literal spans are replaced. Launchers are also named `.command.in`
or `.sh.in` to avoid accidental execution against incomplete package assets.
The manifests record both original and public hashes and every replacement span.
No estimator, sample rule, covariance calculation, convergence tolerance, or
checkpoint validation was edited for this release.

Original package readmes describe their own dated workflow, including older
inclusion rules or superseded estimates. They are preserved for provenance;
this index does not promote each historical package to current primary status.
The two-account exclusion applies to current analytical samples. Preserve actual
all-game order and rating histories when rebuilding behavioral reference sets.

Raw/derived datasets, row-level identifiers, account/profile snapshots, logs,
private caches, manuscript source, ZIP archives, report copies and most runtime
metadata are excluded from this update. Each package manifest lists the omitted
assets and their original hashes. This is a source publication, not a complete
standalone executable bundle. Do not remove original input or checksum gates to
make an incomplete package run.

## Verify and prepare

From the repository root, verify the public source inventory and Python/shell
syntax (Python 3.10+ and Bash; typically 10–60 seconds):

```bash
python3 operations/research_updates_20261022/verify_release.py
```

For a holder of an original source archive, restore a verified runnable package
outside this public checkout (typically seconds to a minute):

```bash
python3 operations/research_updates_20261022/prepare_package.py \
  --package Receipt_IV_Uniform90_FastResume_v1_0_5 \
  --archive "$HOME/Desktop/Lichess_Desktop/Receipt_IV_Uniform90_FastResume_v1_0_5.zip" \
  --output "$HOME/Desktop/Lichess_Desktop/verified_uniform90_v105"
```

The output directory must not already exist. The helper checks the original
archive and every member, verifies the public sources against those originals,
and restores the original package including locally held private configuration.
It never downloads data or runs an analysis. Use that restored package's README
and launcher with its authenticated local inputs. Runtime depends on the module
and completed caches; the original resource and checkpoint instructions apply.
Readers without the original assets can inspect the full published analysis
source, but cannot bypass the missing private inputs and provenance records.

## Validation limits

Publication checks cover source identity, privacy-template fidelity, the complete
file inventory, Python/shell syntax, and preparation-helper regression tests.
Full-data analyses were not run during publication. Historical test reports and
model output are not newly certified by their presence in an original archive.
There is no release DOI or journal-submission replication-completeness claim.

## Complete package index

Paths are under `code/research_updates_20261022/`. Source counts include vendored
dependencies; repeated bytes are retained in their original relative locations.

| Package | Source files | Python files | Private-value templates |
|---|---:|---:|---:|
| [A1_Trajectory_Build_v1_0_2](../../code/research_updates_20261022/A1_Trajectory_Build_v1_0_2) | 12 | 8 | 0 |
| [AFE_Followups_v1_0_0](../../code/research_updates_20261022/AFE_Followups_v1_0_0) | 20 | 16 | 0 |
| [AllTime_Entry_Placebo_v1_0_5](../../code/research_updates_20261022/AllTime_Entry_Placebo_v1_0_5) | 376 | 290 | 16 |
| [AllTime_IV_Primary_v1_0_3](../../code/research_updates_20261022/AllTime_IV_Primary_v1_0_3) | 351 | 269 | 16 |
| [Arena_Next_Analyses_v1_0_1](../../code/research_updates_20261022/Arena_Next_Analyses_v1_0_1) | 51 | 40 | 0 |
| [Arena_Replication_v1_0_2](../../code/research_updates_20261022/Arena_Replication_v1_0_2) | 28 | 22 | 1 |
| [Chooser_Comparison_Expansion_v1_0_0](../../code/research_updates_20261022/Chooser_Comparison_Expansion_v1_0_0) | 17 | 10 | 0 |
| [Color_Change_FirstPass_v1_0_2](../../code/research_updates_20261022/Color_Change_FirstPass_v1_0_2) | 17 | 13 | 0 |
| [Color_Matched_Cohort_v1_0_0](../../code/research_updates_20261022/Color_Matched_Cohort_v1_0_0) | 36 | 26 | 0 |
| [Color_RD110_Predictions_v1_0_0](../../code/research_updates_20261022/Color_RD110_Predictions_v1_0_0) | 15 | 9 | 0 |
| [Comparison_TotalFive_Recovery_v1_0_0](../../code/research_updates_20261022/Comparison_TotalFive_Recovery_v1_0_0) | 738 | 556 | 36 |
| [Countdown_Estimation_v1_0_0](../../code/research_updates_20261022/Countdown_Estimation_v1_0_0) | 14 | 9 | 2 |
| [Countdown_Feasibility_v1_0_0](../../code/research_updates_20261022/Countdown_Feasibility_v1_0_0) | 9 | 5 | 3 |
| [Country_Profile_First_Pass_v1_0_0](../../code/research_updates_20261022/Country_Profile_First_Pass_v1_0_0) | 11 | 7 | 0 |
| [Country_Profile_Followup_v1_0_0](../../code/research_updates_20261022/Country_Profile_Followup_v1_0_0) | 11 | 5 | 1 |
| [Disruption_Scan_v1_0_2](../../code/research_updates_20261022/Disruption_Scan_v1_0_2) | 12 | 6 | 0 |
| [Framework_Tests_v1_0_1](../../code/research_updates_20261022/Framework_Tests_v1_0_1) | 280 | 216 | 17 |
| [IV_Competitive_Only_v1_0_0](../../code/research_updates_20261022/IV_Competitive_Only_v1_0_0) | 22 | 17 | 0 |
| [IV_Cutoff_Material_v1_0_0](../../code/research_updates_20261022/IV_Cutoff_Material_v1_0_0) | 200 | 149 | 13 |
| [Color_Calendar_Recovery_v1_0_0](../../code/research_updates_20261022/Color_Calendar_Recovery_v1_0_0) | 7 | 3 | 0 |
| [Color_Change_Followup_v1_0_0](../../code/research_updates_20261022/Color_Change_Followup_v1_0_0) | 9 | 6 | 0 |
| [Color_Model_Discrimination_v1_0_2](../../code/research_updates_20261022/Color_Model_Discrimination_v1_0_2) | 15 | 10 | 0 |
| [Framework_AE_Completion_v1_2_0](../../code/research_updates_20261022/Framework_AE_Completion_v1_2_0) | 13 | 11 | 0 |
| [Framework_E_Repair_v1_2_1](../../code/research_updates_20261022/Framework_E_Repair_v1_2_1) | 7 | 5 | 0 |
| [Framework_Tests_v1_0_2](../../code/research_updates_20261022/Framework_Tests_v1_0_2) | 16 | 8 | 0 |
| [IV_Runs_2_3_v1_0_0](../../code/research_updates_20261022/IV_Runs_2_3_v1_0_0) | 39 | 26 | 3 |
| [IV_Slide_Gaps_v1_0_0](../../code/research_updates_20261022/IV_Slide_Gaps_v1_0_0) | 20 | 15 | 0 |
| [KAC_A2_Score_Repair_v1_0_1](../../code/research_updates_20261022/KAC_A2_Score_Repair_v1_0_1) | 40 | 27 | 0 |
| [KAC_A3_Local_Sources_v1_0_1](../../code/research_updates_20261022/KAC_A3_Local_Sources_v1_0_1) | 5 | 3 | 1 |
| [KAC_Companion_Recovery_v1_0_2](../../code/research_updates_20261022/KAC_Companion_Recovery_v1_0_2) | 42 | 37 | 1 |
| [KAC_Continuous_Merit_v1_0_0](../../code/research_updates_20261022/KAC_Continuous_Merit_v1_0_0) | 12 | 9 | 1 |
| [KAC_History_Identity_Diagnostic_v1_0_0](../../code/research_updates_20261022/KAC_History_Identity_Diagnostic_v1_0_0) | 8 | 5 | 0 |
| [KAC_Next_Analyses_v1_0_0](../../code/research_updates_20261022/KAC_Next_Analyses_v1_0_0) | 39 | 24 | 1 |
| [KAC_Repetition_Sensitivity_v1_0_2](../../code/research_updates_20261022/KAC_Repetition_Sensitivity_v1_0_2) | 52 | 42 | 1 |
| [KAC_Timestamp_Diagnostic_v1_0_0](../../code/research_updates_20261022/KAC_Timestamp_Diagnostic_v1_0_0) | 5 | 2 | 0 |
| [Kindness_Taxonomy_v1_0_0](../../code/research_updates_20261022/Kindness_Taxonomy_v1_0_0) | 24 | 19 | 8 |
| [Lichess_Author_Exclusion_Persistence_v1_4_2](../../code/research_updates_20261022/Lichess_Author_Exclusion_Persistence_v1_4_2) | 27 | 16 | 4 |
| [Lichess_Author_Exclusion_Prose_Checks_v1_4_3](../../code/research_updates_20261022/Lichess_Author_Exclusion_Prose_Checks_v1_4_3) | 33 | 25 | 2 |
| [Lichess_Author_Exclusion_Repair_v1_4_1](../../code/research_updates_20261022/Lichess_Author_Exclusion_Repair_v1_4_1) | 1459 | 1111 | 73 |
| [Pool_Desert_Payoff_Surfaces_v1_0_0](../../code/research_updates_20261022/Pool_Desert_Payoff_Surfaces_v1_0_0) | 9 | 6 | 0 |
| [Pool_Rating_Validation_v1_0_0](../../code/research_updates_20261022/Pool_Rating_Validation_v1_0_0) | 7 | 4 | 0 |
| [R10_Two_Questions_v1_0_2](../../code/research_updates_20261022/R10_Two_Questions_v1_0_2) | 12 | 8 | 0 |
| [Rating_Motives_v1_0_0](../../code/research_updates_20261022/Rating_Motives_v1_0_0) | 17 | 10 | 4 |
| [Receipt_Cohort_Tests_v1_0_0](../../code/research_updates_20261022/Receipt_Cohort_Tests_v1_0_0) | 13 | 9 | 2 |
| [Receipt_IV_Model5_Submission_v1_0_0](../../code/research_updates_20261022/Receipt_IV_Model5_Submission_v1_0_0) | 406 | 312 | 18 |
| [Receipt_IV_Uniform90_FastResume_v1_0_5](../../code/research_updates_20261022/Receipt_IV_Uniform90_FastResume_v1_0_5) | 411 | 318 | 18 |
| [Receipt_Mechanisms_v1_0_1](../../code/research_updates_20261022/Receipt_Mechanisms_v1_0_1) | 13 | 10 | 3 |
| [Tenure_Responsibility_v1_0_0](../../code/research_updates_20261022/Tenure_Responsibility_v1_0_0) | 13 | 9 | 0 |
| [Win_Premium_Stakes_v1_0_0](../../code/research_updates_20261022/Win_Premium_Stakes_v1_0_0) | 13 | 8 | 3 |
| [Lichess_36M_Stage05_SF_April_v1_0_0_20260925](../../code/research_updates_20261022/Lichess_36M_Stage05_SF_April_v1_0_0_20260925) | 8 | 5 | 3 |
| [Lichess_36M_Stage05_SF_Through_March_v1_0_0_20260921](../../code/research_updates_20261022/Lichess_36M_Stage05_SF_Through_March_v1_0_0_20260921) | 8 | 5 | 3 |
| [Lichess_Author_Exclusion_v1_0_0](../../code/research_updates_20261022/Lichess_Author_Exclusion_v1_0_0) | 11 | 5 | 4 |
| [Lichess_Desert_Ply_CP_41M_v1_0_0](../../code/research_updates_20261022/Lichess_Desert_Ply_CP_41M_v1_0_0) | 4 | 1 | 0 |
| [Lichess_Desert_Ply_Counts_CP_41M_v1_0_0](../../code/research_updates_20261022/Lichess_Desert_Ply_Counts_CP_41M_v1_0_0) | 4 | 1 | 0 |
| [Lichess_Figures_2_3_4_v1_0_1](../../code/research_updates_20261022/Lichess_Figures_2_3_4_v1_0_1) | 7 | 3 | 0 |
| [Lichess_Paper_Figures_v1_1_0](../../code/research_updates_20261022/Lichess_Paper_Figures_v1_1_0) | 12 | 5 | 0 |
| [Lichess_Reputation_v1_0_0](../../code/research_updates_20261022/Lichess_Reputation_v1_0_0) | 10 | 7 | 3 |
| [Lichess_Social_Contact_v1_0_0](../../code/research_updates_20261022/Lichess_Social_Contact_v1_0_0) | 9 | 6 | 2 |
| [Mechanism_RD_Audit_Resume_v1_0_1](../../code/research_updates_20261022/Mechanism_RD_Audit_Resume_v1_0_1) | 14 | 9 | 0 |
| [Mechanism_RD_Audit_v1_0_0](../../code/research_updates_20261022/Mechanism_RD_Audit_v1_0_0) | 16 | 11 | 0 |
| [Mechanism_Separation_v1_0_0](../../code/research_updates_20261022/Mechanism_Separation_v1_0_0) | 22 | 16 | 0 |
| [Patron_Audience_Cache_Audit_v1_0_0](../../code/research_updates_20261022/Patron_Audience_Cache_Audit_v1_0_0) | 3 | 1 | 0 |
| [Patron_IV_Coverage_Audit_v1_0_1](../../code/research_updates_20261022/Patron_IV_Coverage_Audit_v1_0_1) | 5 | 3 | 2 |
| [Patron_TotalFive_Migration_v1_0_1](../../code/research_updates_20261022/Patron_TotalFive_Migration_v1_0_1) | 745 | 565 | 38 |
| [Pool_Activity_Rating_Adjustment_v1_0_0](../../code/research_updates_20261022/Pool_Activity_Rating_Adjustment_v1_0_0) | 15 | 10 | 0 |
| [Pool_Activity_State_Rates_v1_0_0](../../code/research_updates_20261022/Pool_Activity_State_Rates_v1_0_0) | 11 | 7 | 0 |
| [Pool_Audience_Expanded_v1_0_0](../../code/research_updates_20261022/Pool_Audience_Expanded_v1_0_0) | 12 | 9 | 0 |
| [Pool_Audience_Robustness_v1_0_0](../../code/research_updates_20261022/Pool_Audience_Robustness_v1_0_0) | 8 | 5 | 0 |
| [Pool_Chooser_Benchmark_v1_0_0](../../code/research_updates_20261022/Pool_Chooser_Benchmark_v1_0_0) | 14 | 9 | 0 |
| [Pool_Chooser_Bound_Sensitivity_v1_0_0](../../code/research_updates_20261022/Pool_Chooser_Bound_Sensitivity_v1_0_0) | 36 | 22 | 0 |
| [Pool_Chooser_Followup_v1_1_1](../../code/research_updates_20261022/Pool_Chooser_Followup_v1_1_1) | 27 | 17 | 0 |
| [Pool_Chooser_Recovery_v1_0_0](../../code/research_updates_20261022/Pool_Chooser_Recovery_v1_0_0) | 46 | 25 | 0 |
| [Pool_Chooser_Support_Audit_v1_0_0](../../code/research_updates_20261022/Pool_Chooser_Support_Audit_v1_0_0) | 7 | 4 | 0 |
| [Pool_Chooser_Wide_Bootstrap_v1_0_0](../../code/research_updates_20261022/Pool_Chooser_Wide_Bootstrap_v1_0_0) | 41 | 23 | 0 |
| [Pool_Construal_Followup_v1_1_0](../../code/research_updates_20261022/Pool_Construal_Followup_v1_1_0) | 32 | 27 | 0 |
| [Pool_Construal_Tests_v1_0_0](../../code/research_updates_20261022/Pool_Construal_Tests_v1_0_0) | 26 | 21 | 0 |
| [Pool_Equal_Chooser_Desert_v1_0_0](../../code/research_updates_20261022/Pool_Equal_Chooser_Desert_v1_0_0) | 9 | 6 | 0 |
| [Pool_Joint_State_Ply_v1_0_0](../../code/research_updates_20261022/Pool_Joint_State_Ply_v1_0_0) | 6 | 3 | 0 |
| [Pool_Main_C13_FamilyD_v1_0_0](../../code/research_updates_20261022/Pool_Main_C13_FamilyD_v1_0_0) | 21 | 10 | 0 |
| [Pool_Matchmaking_Audit_v1_0_0](../../code/research_updates_20261022/Pool_Matchmaking_Audit_v1_0_0) | 6 | 1 | 0 |
| [Pool_Matchmaking_Balance_Selection_v1_0_0](../../code/research_updates_20261022/Pool_Matchmaking_Balance_Selection_v1_0_0) | 10 | 6 | 0 |
| [Pool_Pooled_Competitive_K_v1_0_0](../../code/research_updates_20261022/Pool_Pooled_Competitive_K_v1_0_0) | 15 | 10 | 0 |
| [Pool_Rating_Milestones_v1_0_0](../../code/research_updates_20261022/Pool_Rating_Milestones_v1_0_0) | 15 | 10 | 0 |
| [Pool_Selectivity_Challenge_v1_1_0](../../code/research_updates_20261022/Pool_Selectivity_Challenge_v1_1_0) | 9 | 5 | 0 |
| [Pool_Selectivity_Pilot_v1_0_0](../../code/research_updates_20261022/Pool_Selectivity_Pilot_v1_0_0) | 12 | 7 | 0 |
| [Pool_Split_Zero_Curves_v1_0_0](../../code/research_updates_20261022/Pool_Split_Zero_Curves_v1_0_0) | 17 | 12 | 0 |
| [Pool_Split_Zero_RD75_v1_0_0](../../code/research_updates_20261022/Pool_Split_Zero_RD75_v1_0_0) | 20 | 15 | 0 |
| [Pool_Stable_Rating_Curves_v1_0_0](../../code/research_updates_20261022/Pool_Stable_Rating_Curves_v1_0_0) | 20 | 14 | 0 |
| [Pool_Stable_Zero_Followups_v1_0_1](../../code/research_updates_20261022/Pool_Stable_Zero_Followups_v1_0_1) | 20 | 15 | 0 |
| [Pool_Within_Chooser_K_Comparison_v1_0_0](../../code/research_updates_20261022/Pool_Within_Chooser_K_Comparison_v1_0_0) | 11 | 7 | 0 |
| [Pool_Within_Chooser_Suite_v1_0_3](../../code/research_updates_20261022/Pool_Within_Chooser_Suite_v1_0_3) | 15 | 9 | 0 |
| [R11_Region_Gap_v1_0_0](../../code/research_updates_20261022/R11_Region_Gap_v1_0_0) | 15 | 11 | 0 |
| [R12_R13_Local_Runner_v1_0_3](../../code/research_updates_20261022/R12_R13_Local_Runner_v1_0_3) | 336 | 257 | 16 |
| [R7_Analysis_v1_0_3](../../code/research_updates_20261022/R7_Analysis_v1_0_3) | 146 | 112 | 7 |
| [R8_Receipt_Independent_v1_0_4](../../code/research_updates_20261022/R8_Receipt_Independent_v1_0_4) | 9 | 7 | 1 |
| [R9_Certified_Leave_Pair_Out_v1_0_0](../../code/research_updates_20261022/R9_Certified_Leave_Pair_Out_v1_0_0) | 234 | 173 | 14 |
| [R9_ENV_Memory_Resume_v1_0_1](../../code/research_updates_20261022/R9_ENV_Memory_Resume_v1_0_1) | 241 | 174 | 13 |
| [R9b_Remaining_Diagnostics_v1_0_0](../../code/research_updates_20261022/R9b_Remaining_Diagnostics_v1_0_0) | 243 | 178 | 13 |
| [Receipt_IV_Cohort_Assembly_v1_0_0](../../code/research_updates_20261022/Receipt_IV_Cohort_Assembly_v1_0_0) | 15 | 13 | 4 |
| [Receipt_IV_Cohort_Extension_v1_0_0](../../code/research_updates_20261022/Receipt_IV_Cohort_Extension_v1_0_0) | 19 | 15 | 0 |
| [Receipt_IV_Expanded_Estimation_v1_1_0](../../code/research_updates_20261022/Receipt_IV_Expanded_Estimation_v1_1_0) | 21 | 18 | 2 |
| [Receipt_IV_History_Extension_v1_0_0](../../code/research_updates_20261022/Receipt_IV_History_Extension_v1_0_0) | 14 | 11 | 0 |
| [Receipt_IV_Source_API_Pull_v1_0_0](../../code/research_updates_20261022/Receipt_IV_Source_API_Pull_v1_0_0) | 14 | 8 | 0 |
| [Receipt_IV_State_Diagnostics_v1_0_1](../../code/research_updates_20261022/Receipt_IV_State_Diagnostics_v1_0_1) | 9 | 7 | 2 |
| [Run2_Continuous_Download_v1_0_0](../../code/research_updates_20261022/Run2_Continuous_Download_v1_0_0) | 64 | 37 | 1 |
| [Run2_Phase100_Final_v1_0_0](../../code/research_updates_20261022/Run2_Phase100_Final_v1_0_0) | 378 | 282 | 20 |
| [Test_G_v2_1_1](../../code/research_updates_20261022/Test_G_v2_1_1) | 21 | 18 | 3 |
