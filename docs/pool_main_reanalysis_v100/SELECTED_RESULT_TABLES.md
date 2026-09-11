# Selected exact result rows

This companion exposes full-precision cells from selected tables. Numeric CSV cells are preserved as strings in SELECTED_RESULTS.json. It is a source extract, not a new estimation run. For long tables, the JSON and original table contain every selected record; this Markdown preview limits display to 24 rows and key coefficient columns. Labels, units and controls must be read with the source receipt.

## old_repository_snapshot/results/c7r_fullpanel_prefocal_v100/20260905T122501Z/first_repeat_raw_rates.csv

SHA-256: `a975ebc600f432e5d0fc12ba46bd6723521ee937309d0a0b5b36bde1270beb8e`

| state | rows | kindness_rate_pct |
|---|---|---|
| overall | 47587020 | 1.406902554520119 |
| competitive | 17328130 | 2.8114401265456803 |
| clearly_worse | 26090163 | 0.501495525344169 |
| overall | 41597026 | 1.3979869618563596 |
| competitive | 15150556 | 2.7967356445532428 |
| clearly_worse | 22777518 | 0.49351733582210316 |
| overall | 5989994 | 1.468816162420196 |
| competitive | 2177574 | 2.913747133277675 |
| clearly_worse | 3312645 | 0.5563530049250675 |

9 records in the exact extract; 5 fields in its first row.

## old_repository_snapshot/results/c7r_fullpanel_prefocal_v100/20260905T122501Z/minimal_chooser_fe_desert.csv

SHA-256: `53c9bb59ea008c2a188ac0d0f08631ad55eb4bf0bb0fe209d717f94055c68635`

| sample | estimate_pp | se_cr1_pp | p_normal | rows | finite_sample_correction | specification |
|---|---|---|---|---|---|---|
| all | 2.176520385565518 | 0.009087386365779014 | 0.0 | 43418293 | 1.0870006913616008 | y_pp ~ fair + chooser FE; chooser-clustered CR1 |
| first | 2.1750335765479 | 0.009201337671153076 | 0.0 | 37928074 | 1.098566084376399 | y_pp ~ fair + chooser FE; chooser-clustered CR1 |
| repeat | 1.9131053253143269 | 0.019787609053695428 | 0.0 | 5490219 | 1.291530170755611 | y_pp ~ fair + chooser FE; chooser-clustered CR1 |

3 records in the exact extract; 10 fields in its first row.

## old_repository_snapshot/results/c7r_fullpanel_prefocal_v100/20260905T122501Z/minimal_chooser_fe_interaction.csv

SHA-256: `2a2d3d8259656abe2fbba3518272d7a887ea2b2814b53d65dcd7e7e6ee4b42d3`

| term | estimate_pp | se_cr1_pp | p_normal | rows | finite_sample_correction | specification |
|---|---|---|---|---|---|---|
| fair | 2.172248742725846 | 0.009121419228405765 | 0.0 | 43418293 | 1.087000745788902 | y_pp ~ fair + repeat + fair×repeat + chooser FE; chooser-clustered CR1 |
| repeat | 0.2937787070976175 | 0.005748194090790043 | 0.0 | 43418293 | 1.087000745788902 | y_pp ~ fair + repeat + fair×repeat + chooser FE; chooser-clustered CR1 |
| fair_x_repeat | 0.03050668764058822 | 0.01498653760708964 | 0.04178992296515273 | 43418293 | 1.087000745788902 | y_pp ~ fair + repeat + fair×repeat + chooser FE; chooser-clustered CR1 |
| repeat_fair_gradient=fair+fair_x_repeat | 2.2027554303664343 | 0.016555681198177123 | 0.0 | 43418293 | 1.087000745788902 | linear combination from interaction model |

4 records in the exact extract; 9 fields in its first row.

## old_repository_snapshot/results/c7r_fullpanel_prefocal_v100/20260905T122501Z/raw_desert_gaps.csv

SHA-256: `218421b78a86e77b1013828b2d361d6cd364793877c9c26b473e059c9b08bf49`

| raw_desert_gap_pp |
|---|
| 2.3099446012015115 |
| 2.3032183087311395 |
| 2.3573941283526074 |

3 records in the exact extract; 2 fields in its first row.

## old_repository_snapshot/results/c7r_fullpanel_prefocal_v100/20260905T122501Z/repeat_prevalence.csv

SHA-256: `1e1664570bce75ba5e7b2d095b7385381926fb4d9e0ea65f7d79b1b45c1dc9aa`

| state | repeat_rows | rows |
|---|---|---|
| overall | 5989994 | 47587020 |
| competitive | 2177574 | 17328130 |
| clearly_worse | 3312645 | 26090163 |

3 records in the exact extract; 4 fields in its first row.

## old_repository_snapshot/results/campaign1/nonprofile_recovery_v104/C13/c13_adjusted_quartile_model.csv

SHA-256: `7d8bb78fdcc28aea98d196c6a556bb934e989550de502e4537893eb143084687`

| model | rows | outcome_mean | exposure_means | sample_specification_sha256 | term | coefficient | p_value_two_sided |
|---|---|---|---|---|---|---|---|
| C13_primary_adjusted_ambient_quartiles | 17101141 | 0.02809303776864947 | {"ambient_quartile_2_vs_1":0.24996560171043558,"ambient_quartile_3_vs_1":0.25002799520803903,"ambient_quartile_4_vs_1":0.25000647617606336} | e65c3468848fb35e9ce7755bec55f625ed8b9ed44c1bd22a3ea26e0411f3beb6 | ambient_quartile_2_vs_1 | 0.00023490017554991775 | 0.4544759947419186 |
| C13_primary_adjusted_ambient_quartiles | 17101141 | 0.02809303776864947 | {"ambient_quartile_2_vs_1":0.24996560171043558,"ambient_quartile_3_vs_1":0.25002799520803903,"ambient_quartile_4_vs_1":0.25000647617606336} | e65c3468848fb35e9ce7755bec55f625ed8b9ed44c1bd22a3ea26e0411f3beb6 | ambient_quartile_3_vs_1 | 0.00028787523067301996 | 0.4077350382977537 |
| C13_primary_adjusted_ambient_quartiles | 17101141 | 0.02809303776864947 | {"ambient_quartile_2_vs_1":0.24996560171043558,"ambient_quartile_3_vs_1":0.25002799520803903,"ambient_quartile_4_vs_1":0.25000647617606336} | e65c3468848fb35e9ce7755bec55f625ed8b9ed44c1bd22a3ea26e0411f3beb6 | ambient_quartile_4_vs_1 | 0.0007535411253007282 | 0.09250667576439166 |

3 records in the exact extract; 27 fields in its first row.

## old_repository_snapshot/results/campaign1/nonprofile_recovery_v104/C13/c13_descriptive_quartiles.csv

SHA-256: `b967bec8e1aba085db314651cc8fea987d1b9c7700dacde81671f9452805a4a4`

| choosers | kind_rate_pct | ambient_rate_pct_mean | ambient_rate_pct_min | ambient_rate_pct_max |
|---|---|---|---|---|
| 713719 | 2.2403423959671454 | 2.2329838627265786 | 1.6888150609080843 | 2.459189714962361 |
| 1132346 | 2.792244690091485 | 2.7748271441380767 | 2.4591984012434773 | 2.9056897105294284 |
| 1098988 | 2.9562436093292335 | 2.9704962687977887 | 2.9056940337041732 | 3.0779963722617554 |
| 1125180 | 3.2483540705936944 | 3.2617622915568725 | 3.0779974215728405 | 4.7087642896026125 |

4 records in the exact extract; 8 fields in its first row.

## old_repository_snapshot/results/campaign1/nonprofile_recovery_v104/C13/c13_model_attempts.csv

SHA-256: `fdaa59af40c98cfba21102e396081d31c00be82241cf9da63550ebe0fc2488a6`

| model | requested_rows | numerical_estimate_emitted |
|---|---|---|
| C13_primary_cell_28d | 17101141 | True |
| C13_sensitivity_cell_14d | 16533936 | True |
| C13_sensitivity_cell_56d | 17192224 | True |
| C13_sensitivity_cell_28d_washout7 | 16934163 | True |
| C13_sensitivity_speed_14d | 17266455 | True |
| C13_sensitivity_speed_28d | 17294093 | True |
| C13_sensitivity_speed_56d | 17294093 | True |
| C13_exploratory_quadratic_primary_ambient_rate | 17101141 | True |
| C13_exploratory_primary_by_chooser_rating_band_0 | 10998686 | True |
| C13_exploratory_primary_by_chooser_rating_band_1 | 4962536 | True |
| C13_exploratory_primary_by_chooser_rating_band_2 | 1139919 | True |
| C13_exploratory_primary_by_chooser_rating_band_3 | 0 | False |
| C13_exploratory_primary_by_speed_code_0 | 0 | False |
| C13_exploratory_primary_by_speed_code_1 | 1734797 | True |
| C13_exploratory_primary_by_speed_code_2 | 9887434 | True |
| C13_exploratory_primary_by_speed_code_3 | 5285524 | True |
| C13_exploratory_primary_by_speed_code_4 | 193386 | True |
| C13_exploratory_primary_by_speed_code_5 | 0 | False |
| C13_primary_adjusted_ambient_quartiles | 17101141 | True |

19 records in the exact extract; 19 fields in its first row.

## old_repository_snapshot/results/campaign1/nonprofile_recovery_v104/C13/c13_models.csv

SHA-256: `3a78cda2237358ca0b53a6d6b429ba205bad837c9c4693625eb53431f793f830`

| model | rows | outcome_mean | exposure_means | sample_specification_sha256 | term | coefficient | p_value_two_sided |
|---|---|---|---|---|---|---|---|
| C13_primary_cell_28d | 17101141 | 0.02809303776864947 | {"ambient_kindness_percentage_points":2.8100260626862115} | 9fc75a0dd2100b0faa095a172964387dc8dff35ac149c96987cf7e59be1c0990 | ambient_kindness_percentage_points | 0.0008211525616534293 | 0.12365640985825642 |
| C13_sensitivity_cell_14d | 16533936 | 0.02801244664307398 | {"ambient_kindness_percentage_points":2.801285823296027} | ab4cd8fb0465d3e9a8b9e7653a5f81b93c60315215d12e6e271db8e605db8543 | ambient_kindness_percentage_points | 7.72204069036636e-05 | 0.8714032851182605 |
| C13_sensitivity_cell_56d | 17192224 | 0.028119340464619353 | {"ambient_kindness_percentage_points":2.81427251293854} | 09d148d8508213c1f7fe6238be7e1d60e05c186b28f6ae3b9c33696798f7d895 | ambient_kindness_percentage_points | 0.001467015828953941 | 0.027695457277685995 |
| C13_sensitivity_cell_28d_washout7 | 16934163 | 0.02809143859073519 | {"ambient_kindness_percentage_points":2.8108567320947873} | 713fc4f220bb7d49e9d67686d06952452dc98cb6d11661211a8eade167aaeb67 | ambient_kindness_percentage_points | 0.0012717826606979381 | 0.017616278641776614 |
| C13_sensitivity_speed_14d | 17266455 | 0.028102583883026364 | {"ambient_kindness_percentage_points":2.8098607937521796} | db41a53bacc8fd33e4b880476b245096a3f7dceb685e5c0335f51fc1429377c8 | ambient_kindness_percentage_points | -0.0004990694259752493 | 0.4732552799095702 |
| C13_sensitivity_speed_28d | 17294093 | 0.028112489044669762 | {"ambient_kindness_percentage_points":2.811680181221544} | 23dc52c1aacb4929ab19d7832823ba3980f2de839e6205e3ce6d1825aa765796 | ambient_kindness_percentage_points | 0.0014775019470155283 | 0.11332044492626596 |
| C13_sensitivity_speed_56d | 17294093 | 0.028112489044669762 | {"ambient_kindness_percentage_points":2.8133221646098105} | 37ca7bbdf1fe003b79ea831313065d96f113f4da3e665ae41c95e4f3acbad7b0 | ambient_kindness_percentage_points | 0.004153275048916611 | 0.0007647878808790244 |
| C13_exploratory_quadratic_primary_ambient_rate | 17101141 | 0.02809303776864947 | {"ambient_pp_centered_linear":-2.1926135114226237e-16,"ambient_pp_centered_squared":0.15948617151778327} | 793c9aa9573c0b0da24c5cb71bacb518ee2bda0b4a50d398dba7f44aa320f633 | ambient_pp_centered_linear | 0.0008198940919613057 | 0.12409459032749846 |
| C13_exploratory_quadratic_primary_ambient_rate | 17101141 | 0.02809303776864947 | {"ambient_pp_centered_linear":-2.1926135114226237e-16,"ambient_pp_centered_squared":0.15948617151778327} | 793c9aa9573c0b0da24c5cb71bacb518ee2bda0b4a50d398dba7f44aa320f633 | ambient_pp_centered_squared | 0.0004513101065664365 | 0.33973784067396734 |
| C13_exploratory_primary_by_chooser_rating_band_0 | 10998686 | 0.030583289676603186 | {"ambient_kindness_percentage_points":3.0580940237317518} | 2f84e12f2aa57cc5ae7c82ab65f1722bf39b270391fb2e0b95ba2af1a6055245 | ambient_kindness_percentage_points | 0.0012812137454681761 | 0.21107668323753778 |
| C13_exploratory_primary_by_chooser_rating_band_1 | 4962536 | 0.0240403293799783 | {"ambient_kindness_percentage_points":2.4048431826452727} | d84b38f4b9b0ecc3069621fa2155252818f61bac5cc062dae70c6f9bffbbdcf7 | ambient_kindness_percentage_points | 0.0015475489873537853 | 0.1295278799880134 |
| C13_exploratory_primary_by_chooser_rating_band_2 | 1139919 | 0.021708559994175026 | {"ambient_kindness_percentage_points":2.180431344628794} | 20020e34ed23986df4109d866d2df07aec3b25262b1f9e1c92c5be6b408011f2 | ambient_kindness_percentage_points | -3.962257362412705e-05 | 0.9747143314318876 |
| C13_exploratory_primary_by_speed_code_1 | 1734797 | 0.02778480709846743 | {"ambient_kindness_percentage_points":2.7787088266670996} | acc1d1cca7ad4597cf0640cde73853edb2e6d4da9451de9ad6b9eacd44ca157a | ambient_kindness_percentage_points | 0.000281963096009245 | 0.8209531964832254 |
| C13_exploratory_primary_by_speed_code_2 | 9887434 | 0.02654976002873951 | {"ambient_kindness_percentage_points":2.656521553457674} | dc4fb4673d3357606aed7cd41805f1764f634cf601403486db74c4016bb49bf7 | ambient_kindness_percentage_points | -0.001616813596404665 | 0.12992070256053143 |
| C13_exploratory_primary_by_speed_code_3 | 5285524 | 0.03060718293966691 | {"ambient_kindness_percentage_points":3.0599774002260385} | 7ed8f935e78bdf7fabc112e9a1927f7b56289c37cfe0e3e5c6449ee1967443b3 | ambient_kindness_percentage_points | -0.0027928757090379735 | 0.015451769117269526 |
| C13_exploratory_primary_by_speed_code_4 | 193386 | 0.04104743880115417 | {"ambient_kindness_percentage_points":4.107798173360925} | 88e6985e2089431153528a27fa61d6851694fbf3e05195446835858dabef3ecb | ambient_kindness_percentage_points | -0.03498209699895242 | 1.0390738364482126e-08 |

16 records in the exact extract; 32 fields in its first row.

## old_repository_snapshot/results/campaign1/nonprofile_recovery_v104/C13/c13_support_by_cell.csv

SHA-256: `0b6de03bc29cc7114728787a3073475cdf7d2f682a52947af0ef6e7d958538cf`

| chooser_rating_band | focal_rows | supported_rows |
|---|---|---|
| 0 | 270 | 0 |
| 1 | 131 | 0 |
| 2 | 28 | 0 |
| 3 | 2 | 0 |
| 0 | 1005779 | 1000251 |
| 1 | 537888 | 532558 |
| 2 | 207196 | 201988 |
| 3 | 22888 | 0 |
| 0 | 6123324 | 6114483 |
| 1 | 3059753 | 3051212 |
| 2 | 726799 | 721739 |
| 3 | 28583 | 0 |
| 0 | 3700416 | 3690566 |
| 1 | 1384690 | 1378766 |
| 2 | 221445 | 216192 |
| 3 | 4481 | 0 |
| 0 | 198657 | 193386 |
| 1 | 96209 | 0 |
| 2 | 9435 | 0 |
| 3 | 156 | 0 |

20 records in the exact extract; 5 fields in its first row.

## old_repository_snapshot/results/patron_stage10/primary_v1_0_1/chooser_model_contrasts.csv

SHA-256: `eda53da37c698d5b2fcbaeba45c498629cafbcb5522de0d1189e1371a95f69bf`

| model | contrast | se_pp | p_two_sided_approx | estimand_class |
|---|---|---|---|---|
| diagnostic_horse_race_min2_exposure_match_cell_fe_HC1 | fair_minus_clearly_worse | 0.035890480197716186 | 1.3136802978960397e-71 | secondary |
| diagnostic_horse_race_min2_full_match_cell_fe_HC1 | fair_minus_clearly_worse | 0.03533573812343145 | 3.399600277435074e-46 | secondary |
| diagnostic_horse_race_min4_exposure_match_cell_fe_HC1 | fair_minus_clearly_worse | 0.04296173331011593 | 1.4723768652097786e-59 | confirmatory |
| diagnostic_horse_race_min4_full_match_cell_fe_HC1 | fair_minus_clearly_worse | 0.042351951483451625 | 1.9492696594710932e-40 | confirmatory |
| diagnostic_horse_race_min4_full_match_cell_fe_CR1 | fair_minus_clearly_worse | 0.06617688947494596 | 1.5960152298749317e-17 | sensitivity |
| diagnostic_horse_race_min5_exposure_match_cell_fe_HC1 | fair_minus_clearly_worse | 0.04629366789763864 | 4.1679411741637015e-55 | secondary |
| diagnostic_horse_race_min5_full_match_cell_fe_HC1 | fair_minus_clearly_worse | 0.04566268440349577 | 1.35392072862163e-38 | secondary |
| diagnostic_horse_race_min10_exposure_match_cell_fe_HC1 | fair_minus_clearly_worse | 0.06172182694458939 | 1.959612670578494e-34 | secondary |
| diagnostic_horse_race_min10_full_match_cell_fe_HC1 | fair_minus_clearly_worse | 0.06099271224417132 | 4.731973186825179e-25 | secondary |
| price_side_horse_race_min2_match_cell_fe_HC1 | costly_minus_nonnegative | 0.05549405832125552 | 0.011481322379449795 | secondary |
| price_side_horse_race_min2_full_match_cell_fe_HC1 | costly_minus_nonnegative | 0.05514470403820002 | 0.12356887436815012 | secondary |
| price_side_horse_race_min4_match_cell_fe_HC1 | costly_minus_nonnegative | 0.07545570068214638 | 0.0032943989229983683 | secondary |
| price_side_horse_race_min4_full_match_cell_fe_HC1 | costly_minus_nonnegative | 0.07495801395792326 | 0.02731773807763475 | secondary |

13 records in the exact extract; 14 fields in its first row.

## old_repository_snapshot/results/patron_stage10/primary_v1_0_1/raw_matched_patron_comparisons.csv

SHA-256: `fe5aebfef93509f1cf2b3369cef5ab7a0c1155078619d2be305fcbc9aa6ae627`

| sample | estimand_class | treated_rate_pct | control_rate_pct | gap_pp | unpooled_se_pp | pooled_p_two_sided |
|---|---|---|---|---|---|---|
| broad_any_state_acquisition_roles | qa_secondary | 0.5339631831925669 | 0.3219791351801776 | 0.2119840480123892 | 0.013981373048455856 | 5.212288150966212e-66 |
| main_fair_kind_stored_1to3_available_cases | confirmatory | 0.6335114289157595 | 0.3278530446940842 | 0.3056583842216753 | 0.01722341266817126 | 3.290252480323096e-96 |
| main_fair_kind_complete_four_account_groups | sensitivity | 0.6338016847791139 | 0.3278192184854136 | 0.30598246629370024 | 0.0172303757610625 | 2.321680832304647e-96 |
| main_fair_kind_stored_1to3_exclude_bot | sensitivity | 0.6335343341863483 | 0.3278618265975228 | 0.3056725075888255 | 0.017224009785692353 | 3.269185828777541e-96 |
| main_fair_kind_legacy_2_20 | sensitivity | 0.6791728008833272 | 0.3416489643166637 | 0.3375238365666635 | 0.02128863060067394 | 3.8140585392439337e-78 |
| main_fair_kind_duration_2_40 | sensitivity | 0.7070160078141211 | 0.36140431390546124 | 0.34561169390865987 | 0.020397178171100722 | 2.4232186905126476e-88 |
| main_fair_kind_overlap_cells_min20 | sensitivity | 0.6331783867611077 | 0.3278886143089627 | 0.30528977245214506 | 0.01722064887040784 | 5.515449453256869e-96 |
| main_fair_kind_control_slot_1_1to1 | sensitivity | 0.6336005142730871 | 0.3358846099760943 | 0.2977159042969927 | 0.019683737048043215 | 1.1686029318385418e-51 |
| main_fair_kind_control_slot_2_1to1 | sensitivity | 0.633603059937162 | 0.3129846440653451 | 0.32061841587181694 | 0.0194502205880313 | 5.146378255890767e-61 |
| main_fair_kind_control_slot_3_1to1 | sensitivity | 0.6336208801584655 | 0.33469004005833974 | 0.2989308401001257 | 0.01967214504945569 | 3.988279046567368e-52 |

10 records in the exact extract; 19 fields in its first row.

## old_sample_closeout/holm/campaign_family_d_holm_signed.csv

SHA-256: `f87d17e34aef11e4ebe3668da0f96b512575dfc51238cf7da6a28a99d95ca4ef`

| p_raw | holm_multiplier | p_holm_unmonotone | p_holm | spec_version |
|---|---|---|---|---|
| 5.334843209911397e-07 | 5 | 2.667421604955698e-06 | 2.667421604955698e-06 | Campaign1 C6/C10 v1.0.0, metadata correction v1.0.1 |
| 0.0004 | 4 | 0.0016 | 0.0016 | Campaign1 C9 recovery v1.0.1; 4,999 reallocations |
| 0.006046717201351934 | 3 | 0.018140151604055802 | 0.018140151604055802 | Campaign1 C1 corrected v1.0.5 |
| 0.0363121 | 2 | 0.0726242 | 0.0726242 | Campaign1 Wave1 C2 v1.0.0 r3 |
| 1.0 | 1 | 1.0 | 1.0 | Campaign1 frozen family; closeout rule 2026-09-02 |

5 records in the exact extract; 18 fields in its first row.

## results/c6_c12/results/c12/c12_descriptive_deciles.csv

SHA-256: `7d25bffb108a4454aa2a2096c49150704a588a477f14d27b565d3400be3a14e7`

| kind_rate_pct | prior_games_mean |
|---|---|
| 3.022386825832479 | 109.1207301345855 |
| 2.873677248677249 | 474.95343915343915 |
| 2.886904761904762 | 1031.8829034391536 |
| 2.7745626508813124 | 1791.173451503026 |
| 2.75481182617898 | 2806.0764270123686 |
| 2.6292290901875184 | 4115.323841650958 |
| 2.6757954620625783 | 5810.646292253754 |
| 2.5768251132943005 | 8253.336012702193 |
| 2.54060670217341 | 12227.149128320487 |
| 2.65316924705571 | 26720.1015945481 |

10 records in the exact extract; 7 fields in its first row.

## results/c6_c12/results/c12/c12_model_attempts.csv

SHA-256: `a4544b9e5fe27733cce952f3b85a4db2f7403b1b1df5941b7d4814b6beefd263`

| model | numerical_estimate_emitted | requested_rows | rating_band_definition |
|---|---|---|---|
| C12_primary_recipient_experience_extremes | True | 120938 |  |
| C12_full_recipient_experience_decile_profile | True | 302357 |  |
| C12_continuous_prior_all_rated_games | True | 302357 |  |
| C12_same_speed_recipient_experience_extremes | True | 120938 |  |
| C12_continuous_prior_same_speed_games | True | 302357 |  |
| C12_primary_by_chooser_rating_band_0 | True | 77136 |  |
| C12_primary_by_chooser_rating_band_1 | True | 35421 |  |
| C12_primary_by_chooser_rating_band_2 | True | 8009 |  |
| C12_primary_by_chooser_rating_band_3 | False | 372 | 2400+ |

9 records in the exact extract; 19 fields in its first row.

## results/c6_c12/results/c12/c12_models.csv

SHA-256: `a75af28de0a61d4692263764107bc824cf5968b833e5a4be29943a07735067c2`

| coefficient | exposure_means | model | outcome_mean | p_value_two_sided | rows | sample_specification_sha256 | term |
|---|---|---|---|---|---|---|---|
| 0.0011843422596562716 | {"low_deciles_1_2_minus_high_deciles_9_10":0.5000992243959715} | C12_primary_recipient_experience_extremes | 0.02772494997436703 | 0.6421308086748219 | 120938 | 8332d5068340bf944ba87687674ca8f571eefe354aaff1692cd5a4bba60b6f8d | low_deciles_1_2_minus_high_deciles_9_10 |
| 0.0017069747250408284 | {"experience_decile_10_vs_1":0.09997453341579655,"experience_decile_2_vs_1":0.10001422159897075,"experience_decile_3_vs_1":0.10001422159897075,"experience_decile_4_vs_1":0.10001091425037291,"experience_decile_5_vs_1":0.1 | C12_full_recipient_experience_decile_profile | 0.027388153738792224 | 0.4984133942598814 | 302357 | 12acec64b49b05e5d777a5d22148d57aa98ef31543d16d9d1a4a53eaf48449b3 | experience_decile_2_vs_1 |
| 0.0016131014725648313 | {"experience_decile_10_vs_1":0.09997453341579655,"experience_decile_2_vs_1":0.10001422159897075,"experience_decile_3_vs_1":0.10001422159897075,"experience_decile_4_vs_1":0.10001091425037291,"experience_decile_5_vs_1":0.1 | C12_full_recipient_experience_decile_profile | 0.027388153738792224 | 0.5212416559392945 | 302357 | 12acec64b49b05e5d777a5d22148d57aa98ef31543d16d9d1a4a53eaf48449b3 | experience_decile_3_vs_1 |
| -0.0005283679834334415 | {"experience_decile_10_vs_1":0.09997453341579655,"experience_decile_2_vs_1":0.10001422159897075,"experience_decile_3_vs_1":0.10001422159897075,"experience_decile_4_vs_1":0.10001091425037291,"experience_decile_5_vs_1":0.1 | C12_full_recipient_experience_decile_profile | 0.027388153738792224 | 0.8412412813950515 | 302357 | 12acec64b49b05e5d777a5d22148d57aa98ef31543d16d9d1a4a53eaf48449b3 | experience_decile_4_vs_1 |
| 0.0012457241940113477 | {"experience_decile_10_vs_1":0.09997453341579655,"experience_decile_2_vs_1":0.10001422159897075,"experience_decile_3_vs_1":0.10001422159897075,"experience_decile_4_vs_1":0.10001091425037291,"experience_decile_5_vs_1":0.1 | C12_full_recipient_experience_decile_profile | 0.027388153738792224 | 0.6177629598339713 | 302357 | 12acec64b49b05e5d777a5d22148d57aa98ef31543d16d9d1a4a53eaf48449b3 | experience_decile_5_vs_1 |
| -0.0029657357423431333 | {"experience_decile_10_vs_1":0.09997453341579655,"experience_decile_2_vs_1":0.10001422159897075,"experience_decile_3_vs_1":0.10001422159897075,"experience_decile_4_vs_1":0.10001091425037291,"experience_decile_5_vs_1":0.1 | C12_full_recipient_experience_decile_profile | 0.027388153738792224 | 0.2415937041585685 | 302357 | 12acec64b49b05e5d777a5d22148d57aa98ef31543d16d9d1a4a53eaf48449b3 | experience_decile_6_vs_1 |
| -0.0021389397824681223 | {"experience_decile_10_vs_1":0.09997453341579655,"experience_decile_2_vs_1":0.10001422159897075,"experience_decile_3_vs_1":0.10001422159897075,"experience_decile_4_vs_1":0.10001091425037291,"experience_decile_5_vs_1":0.1 | C12_full_recipient_experience_decile_profile | 0.027388153738792224 | 0.4031537852489719 | 302357 | 12acec64b49b05e5d777a5d22148d57aa98ef31543d16d9d1a4a53eaf48449b3 | experience_decile_7_vs_1 |
| 0.0006697790522557771 | {"experience_decile_10_vs_1":0.09997453341579655,"experience_decile_2_vs_1":0.10001422159897075,"experience_decile_3_vs_1":0.10001422159897075,"experience_decile_4_vs_1":0.10001091425037291,"experience_decile_5_vs_1":0.1 | C12_full_recipient_experience_decile_profile | 0.027388153738792224 | 0.7961328121089919 | 302357 | 12acec64b49b05e5d777a5d22148d57aa98ef31543d16d9d1a4a53eaf48449b3 | experience_decile_8_vs_1 |
| -0.000335176460234614 | {"experience_decile_10_vs_1":0.09997453341579655,"experience_decile_2_vs_1":0.10001422159897075,"experience_decile_3_vs_1":0.10001422159897075,"experience_decile_4_vs_1":0.10001091425037291,"experience_decile_5_vs_1":0.1 | C12_full_recipient_experience_decile_profile | 0.027388153738792224 | 0.8936353417726568 | 302357 | 12acec64b49b05e5d777a5d22148d57aa98ef31543d16d9d1a4a53eaf48449b3 | experience_decile_9_vs_1 |
| 0.0014151933800391273 | {"experience_decile_10_vs_1":0.09997453341579655,"experience_decile_2_vs_1":0.10001422159897075,"experience_decile_3_vs_1":0.10001422159897075,"experience_decile_4_vs_1":0.10001091425037291,"experience_decile_5_vs_1":0.1 | C12_full_recipient_experience_decile_profile | 0.027388153738792224 | 0.5706667293236511 | 302357 | 12acec64b49b05e5d777a5d22148d57aa98ef31543d16d9d1a4a53eaf48449b3 | experience_decile_10_vs_1 |
| -9.966697096593044e-05 | {"log1p_prior_all_rated_games":7.428664649019697} | C12_continuous_prior_all_rated_games | 0.027388153738792224 | 0.7687595878350746 | 302357 | 0f97d0e6cb53d0464019e991febd631e3da15c99425c611e2e737732bbe471bf | log1p_prior_all_rated_games |
| 0.002219695552138701 | {"low_same_speed_deciles_1_2_minus_high_9_10":0.5000992243959715} | C12_same_speed_recipient_experience_extremes | 0.027973010964295754 | 0.4219827298277832 | 120938 | 9774f113c3c1d5d067b20a1a8091460d92ba3a9735d128bbeaaba265a88923ce | low_same_speed_deciles_1_2_minus_high_9_10 |
| -0.00020754811902077853 | {"log1p_prior_same_speed_games":6.995751099402493} | C12_continuous_prior_same_speed_games | 0.027388153738792224 | 0.5390056625557014 | 302357 | 34eddd485f0cd637cdfd0280e6a33f726234e427645673c6317dc4276b8c3656 | log1p_prior_same_speed_games |
| 0.00808608067339544 | {"low_deciles_1_2_minus_high_deciles_9_10":0.5102805434557146} | C12_primary_by_chooser_rating_band_0 | 0.030232316946691557 | 0.028944589500978918 | 77136 | 3abadba4c0bad55f7b039591e911e5d89660c7eedd078ea745df0d77255c674c | low_deciles_1_2_minus_high_deciles_9_10 |
| -0.005900136960919318 | {"low_deciles_1_2_minus_high_deciles_9_10":0.48299031647892493} | C12_primary_by_chooser_rating_band_1 | 0.024392309646819682 | 0.13831902234498966 | 35421 | 9f075fa8a4cbc5d76294ff7d901b9e0492c5339dc5e3c4c91ac708563aa2628b | low_deciles_1_2_minus_high_deciles_9_10 |
| -0.01322566206526274 | {"low_deciles_1_2_minus_high_deciles_9_10":0.47833687102010236} | C12_primary_by_chooser_rating_band_2 | 0.018229491821700586 | 0.2187773440377828 | 8009 | 2f7cb52259c4ae711e23259a9db443dbe80e2043e3959ce4ba7814f42abb8a17 | low_deciles_1_2_minus_high_deciles_9_10 |

16 records in the exact extract; 26 fields in its first row.

## results/c6_c12/results/c12/c12_support_by_cell_decile.csv

SHA-256: `c0db14ee57ebedb61c2ff697d88b60a53da5ace56c92011cc0b5166f6e46f353`

| recipient_rating_band |
|---|
| 0 |
| 0 |
| 0 |
| 0 |
| 0 |
| 0 |
| 0 |
| 0 |
| 0 |
| 0 |
| 0 |
| 0 |
| 0 |
| 0 |
| 0 |
| 0 |
| 0 |
| 0 |
| 0 |
| 0 |
| 0 |
| 0 |
| 0 |
| 0 |

150 records in the exact extract; 5 fields in its first row.

## results/c6_c12/results/c6_c10/c10_decay_clock.csv

SHA-256: `cd4b41939d0e2c835c0f086ae8d8b7846d9a64631360cdda4e07607c9709456a`

| sample_definition | mean | p_value_two_sided | rows | mean_change_percentage_points | weighted_pre_kind_rate | weighted_post_kind_rate | model | outcome_mean | exposure_means | sample_specification_sha256 | term |
|---|---|---|---|---|---|---|---|---|---|---|---|
| common_90d_endpoint_cohort | -0.005102626431627203 | 1.458964476089382e-09 | 51210 | -0.5102626431627203 | 0.032937198427579084 | 0.027834571995951882 |  |  |  |  |  |
| common_90d_endpoint_cohort | 0.007649897675555149 | 0.10218158798084247 | 1559 | 0.764989767555515 | 0.03249946546931793 | 0.040149363144873086 |  |  |  |  |  |
| common_90d_endpoint_cohort | 0.0012540204218783242 | 0.5970073473305897 | 52769 | 0.1254020421878324 | 0.032719005244141834 | 0.03397302566602016 |  |  |  |  |  |
| common_90d_endpoint_cohort |  | 0.003957906044203251 | 52769 |  |  |  | C10_decay_mercy_minus_claim | 0.0012540204218783242 | {"mercy_minus_claim":0.49846185743929694} | 8427064d668907f9bbcff89f2a3b3f2aa13c5c69636fe25cd151290fea3f7c23 | mercy_minus_claim |
| common_90d_endpoint_cohort | -0.010927585026806292 | 0.10917051769583683 | 192 | -1.0927585026806292 | 0.02492803559955284 | 0.014000450572746547 |  |  |  |  |  |
| common_90d_endpoint_cohort | 0.0 | nan | 9 | 0.0 | 0.0 | 0.0 |  |  |  |  |  |
| common_90d_endpoint_cohort | -0.0044182745913717136 | 0.12898756860183747 | 201 | -0.44182745913717136 | 0.010078979576194904 | 0.00566070498482319 |  |  |  |  |  |
| horizon_specific_7d_endpoint_cohort | -0.004430122584425849 | 1.4663686709149742e-11 | 77653 | -0.44301225844258485 | 0.029996645273322565 | 0.02556652268889671 |  |  |  |  |  |
| horizon_specific_7d_endpoint_cohort | 0.008348106037451352 | 0.022549643103935514 | 2337 | 0.8348106037451352 | 0.02891884181999715 | 0.037266947857448496 |  |  |  |  |  |
| horizon_specific_7d_endpoint_cohort | 0.0019122723437869024 | 0.300556430157203 | 79990 | 0.19122723437869024 | 0.02946168417986725 | 0.031373956523654156 |  |  |  |  |  |
| horizon_specific_7d_endpoint_cohort |  | 0.00024545760746308594 | 79990 |  |  |  | C10_decay_mercy_minus_claim | 0.0019122723437869024 | {"mercy_minus_claim":0.49634382948463907} | 0dcbed919d314b0e30d1943ac2786ff6ee6280866417a58fde57cf973a77233b | mercy_minus_claim |
| horizon_specific_7d_endpoint_cohort | -0.008378452479819673 | 0.11511742399908294 | 258 | -0.8378452479819674 | 0.019790892634443898 | 0.011412440154624226 |  |  |  |  |  |
| horizon_specific_7d_endpoint_cohort | 0.0 | nan | 13 | 0.0 | 0.0 | 0.0 |  |  |  |  |  |
| horizon_specific_7d_endpoint_cohort | -0.0032091810511472247 | 0.1299490439057664 | 271 | -0.32091810511472246 | 0.007580464027303703 | 0.004371282976156479 |  |  |  |  |  |
| common_90d_endpoint_cohort | -0.00461603950718444 | 1.4255441881946638e-14 | 98187 | -0.461603950718444 | 0.033083349010090815 | 0.02846730950290638 |  |  |  |  |  |
| common_90d_endpoint_cohort | 0.003323923392007084 | 0.3616047083063441 | 3011 | 0.3323923392007084 | 0.03512122218532049 | 0.038445145577327575 |  |  |  |  |  |
| common_90d_endpoint_cohort | -0.000635052942070734 | 0.7315930393948884 | 101198 | -0.0635052942070734 | 0.03410511017383895 | 0.03347005723176821 |  |  |  |  |  |
| common_90d_endpoint_cohort |  | 0.0033902285714133692 | 101198 |  |  |  | C10_decay_mercy_minus_claim | -0.000635052942070734 | {"mercy_minus_claim":0.5013860411764725} | 7d0022df5aa5a789b202c9b24188702f2d5cbdeb89a0e7e2ba5a1e28f8b759f5 | mercy_minus_claim |
| common_90d_endpoint_cohort | -0.003285041631814405 | 0.20274707893296182 | 1174 | -0.3285041631814405 | 0.02412794205679976 | 0.02084290042498536 |  |  |  |  |  |
| common_90d_endpoint_cohort | 0.01130952380952381 | 0.3306641711544709 | 42 | 1.130952380952381 | 0.02142857142857143 | 0.03273809523809524 |  |  |  |  |  |
| common_90d_endpoint_cohort | 0.004466095736007572 | 0.47472978022427875 | 1216 | 0.44660957360075726 | 0.022694313037137547 | 0.02716040877314512 |  |  |  |  |  |
| common_90d_endpoint_cohort |  | 0.024943535427030376 | 1216 |  |  |  | C10_decay_mercy_minus_claim | 0.004466095736007572 | {"mercy_minus_claim":0.5310975101641159} | d0f7fd4e0c280af364e7e83b9cf39006d5feb28724393538d06917c038ef69c7 | mercy_minus_claim |
| horizon_specific_14d_endpoint_cohort | -0.0039340257824935655 | 2.2250455394402254e-16 | 143928 | -0.39340257824935654 | 0.03068347910611577 | 0.026749453323622205 |  |  |  |  |  |
| horizon_specific_14d_endpoint_cohort | 0.0025378028884582115 | 0.3775430906303105 | 4349 | 0.25378028884582116 | 0.03180534112932365 | 0.034343144017781865 |  |  |  |  |  |

54 records in the exact extract; 35 fields in its first row.

## results/c6_c12/results/c6_c10/c10_personal_slight.csv

SHA-256: `baa523935b608e497cf17cbf794c60747ebc90e849c347015a629dacb7c4e15b`

| model | sample_definition | rows | outcome_mean | exposure_means | sample_specification_sha256 | term | coefficient | p_value_two_sided | effect_pp_change_per_1pp_denier_propensity | se_pp_change_per_1pp_denier_propensity | interaction_pp_change_per_1pp_denier_propensity |
|---|---|---|---|---|---|---|---|---|---|---|---|
| C10_personal_slight_claimed_arm_slope | common_90d_endpoint_cohort | 15536 | -0.00391071998355327 | {"denier_pair_excluded_propensity":0.01268436086072222} | fc9782531ebb4c3422e23226936acd086bc96e588f26f23d9f0db709d43dfbef | denier_pair_excluded_propensity | -0.007480711648251049 | 0.6810231811030025 | -0.007480711648251049 | 0.018198264629668483 |  |
| C10_personal_slight_pooled_interaction | common_90d_endpoint_cohort | 15800 | -0.000689255988582021 | {"claim_by_centered_denier_propensity":-0.07298582837532179} | 40b563fc84c6b9758938f34cdcaae0967f3f6ebfac4afc895dd7859421a47fc8 | claim_by_centered_denier_propensity | -0.07396219336434609 | 0.037182750105688056 |  | 0.03549472327140356 | -0.07396219336434609 |
| C10_personal_slight_claimed_arm_slope | horizon_specific_7d_endpoint_cohort | 18448 | -0.0038890217814958952 | {"denier_pair_excluded_propensity":0.012647673452751647} | ab3f9e3d756e69b4f84298792d4435458ceb0c805ee6c50fd628a2a9f7139ef5 | denier_pair_excluded_propensity | -0.014164401157420797 | 0.40777497242996746 | -0.014164401157420797 | 0.017110576533636523 |  |
| C10_personal_slight_pooled_interaction | horizon_specific_7d_endpoint_cohort | 18763 | 0.00018467171933119977 | {"claim_by_centered_denier_propensity":-0.0714500168270065} | f6716544db9f2a918c26c1df3f1471318806ae64ea692ef5852c03a03039d67f | claim_by_centered_denier_propensity | -0.055148735008120196 | 0.11219160685580205 |  | 0.03471926008901936 | -0.055148735008120196 |
| C10_personal_slight_claimed_arm_slope | common_90d_endpoint_cohort | 29740 | -0.002962014660146414 | {"denier_pair_excluded_propensity":0.01272134584786253} | 58f6f4b807cb4e16a280f4732d95bd9566cf6439f634a57689093f5db0643715 | denier_pair_excluded_propensity | -0.0058199082388915805 | 0.7117322714675082 | -0.0058199082388915805 | 0.015749462394900104 |  |
| C10_personal_slight_pooled_interaction | common_90d_endpoint_cohort | 30267 | -0.0009315185191556266 | {"claim_by_centered_denier_propensity":-0.071508189678524} | 1b346297d8a4dfcd9effab954c653c03c6bc2618afcbd444f2fc68faa1288151 | claim_by_centered_denier_propensity | -0.02677056719526122 | 0.388616129448198 |  | 0.03105166898439857 | -0.02677056719526122 |
| C10_personal_slight_claimed_arm_slope | horizon_specific_14d_endpoint_cohort | 34972 | -0.003128928586143954 | {"denier_pair_excluded_propensity":0.012936336458124158} | 4bbc3136d1e2271be487ca1a886c113c528b444df10ff119e7a0d6ad1418fea2 | denier_pair_excluded_propensity | -0.00576986755337896 | 0.6789338843654792 | -0.00576986755337896 | 0.013939626419205523 |  |
| C10_personal_slight_pooled_interaction | horizon_specific_14d_endpoint_cohort | 35603 | -0.000871577252173011 | {"claim_by_centered_denier_propensity":-0.07189909409684522} | 574a740361f3ef7aed296f40695e22ec357e743f852016a073ad84f5b416eaf2 | claim_by_centered_denier_propensity | -0.0358441996025837 | 0.21615840619908092 |  | 0.02898121804006589 | -0.0358441996025837 |
| C10_personal_slight_claimed_arm_slope | common_90d_endpoint_cohort | 51356 | -0.003713224230812839 | {"denier_pair_excluded_propensity":0.012811932423864253} | 70dddaac6a28dcaa78bdf1a3218ae73d8dbbee0c0bfaae954f04beb3eec0fc63 | denier_pair_excluded_propensity | 0.008207833994368427 | 0.5990659856471905 | 0.008207833994368427 | 0.015611840920601031 |  |
| C10_personal_slight_pooled_interaction | common_90d_endpoint_cohort | 52246 | -0.0008570175941375615 | {"claim_by_centered_denier_propensity":-0.07365605304026168} | 989797f3d648d37c3a26e88f07f7d834eb96c620d9ab2de3a9ad781e74eca32a | claim_by_centered_denier_propensity | -0.006688406828712784 | 0.8012576360889716 |  | 0.026570839078734868 | -0.006688406828712784 |
| C10_personal_slight_claimed_arm_slope | common_90d_endpoint_cohort | 1643 | -0.0012359367863482215 | {"denier_pair_excluded_propensity":0.01257781525066505} | 5a07933ed7145cc6c99550b9b483bcd84471cb78232b4c4456e49012ded53b8c | denier_pair_excluded_propensity | -0.0481897423061796 | 0.3096357209928325 | -0.0481897423061796 | 0.04743146972410464 |  |
| C10_personal_slight_pooled_interaction | common_90d_endpoint_cohort | 1674 | -0.006989228807186873 | {"claim_by_centered_denier_propensity":-0.06355147932749625} | d64ca192f133dd0e6c92887911e17c4ed9cd0e2a8cee7005fc1153c308e06fd5 | claim_by_centered_denier_propensity | -0.07571116418550776 | 0.13482400141208184 |  | 0.05063117986878961 | -0.07571116418550776 |
| C10_personal_slight_claimed_arm_slope | common_90d_endpoint_cohort | 72792 | -0.0035363248530927965 | {"denier_pair_excluded_propensity":0.012609707391284775} | 72afd5fd15b0ea4b1ca9fa1cefed3385f458175392846a1c9828d114f0228e11 | denier_pair_excluded_propensity | 0.013446967740440446 | 0.24685772690704955 | 0.013446967740440446 | 0.011612079622314477 |  |
| C10_personal_slight_pooled_interaction | common_90d_endpoint_cohort | 74034 | -0.002857732337015012 | {"claim_by_centered_denier_propensity":-0.07397822735731692} | 3aed6f53c2d6288ad978118350433d21b32ef32e649635cc275eef9816f11a4b | claim_by_centered_denier_propensity | 0.004591637810996539 | 0.8304089277866622 |  | 0.02143850631032268 | 0.004591637810996539 |
| C10_personal_slight_claimed_arm_slope | common_90d_endpoint_cohort | 4641 | -0.0027856503975489566 | {"denier_pair_excluded_propensity":0.012699397783476243} | e0a60000ed684000db60560eb716044225069981c7b3666e00459b273c35d42d | denier_pair_excluded_propensity | -0.013998674280803357 | 0.6165342062222097 | -0.013998674280803357 | 0.02795439450639465 |  |
| C10_personal_slight_pooled_interaction | common_90d_endpoint_cohort | 4716 | -0.0055406281684830675 | {"claim_by_centered_denier_propensity":-0.06253343806283962} | b6f574cb90fe703339072ef002e686853e943887a8244fce4173dcecb76975bf | claim_by_centered_denier_propensity | -0.015181711336326427 | 0.6194170173029045 |  | 0.030566583189484724 | -0.015181711336326427 |
| C10_personal_slight_claimed_arm_slope | common_90d_endpoint_cohort | 84972 | -0.0038392720288275397 | {"denier_pair_excluded_propensity":0.012653058663461711} | fdcc02e0f0e131c073a9a9dda7403fbd065c3fd8da74a3fa46e269a174cf2f0a | denier_pair_excluded_propensity | 0.008192512286487093 | 0.430670258893261 | 0.008192512286487093 | 0.010395992682983492 |  |
| C10_personal_slight_pooled_interaction | common_90d_endpoint_cohort | 86457 | -0.0037344918752944536 | {"claim_by_centered_denier_propensity":-0.07269632672001272} | 85e3610973aae438da0b2bb37a4eb52b7d179e824e214fd2f6315447fae6df15 | claim_by_centered_denier_propensity | 0.015062554741741804 | 0.43462945809483056 |  | 0.019278978396875573 | 0.015062554741741804 |
| C10_personal_slight_claimed_arm_slope | common_90d_endpoint_cohort | 7587 | -0.0029278709888093373 | {"denier_pair_excluded_propensity":0.012110913440332683} | 3d94c609909c6d73c6048e854f77fdf7ba50c1abd8a65c43e5dc37a3ae00cf67 | denier_pair_excluded_propensity | 0.016258534304040083 | 0.44218224361283714 | 0.016258534304040083 | 0.021155824595413937 |  |
| C10_personal_slight_pooled_interaction | common_90d_endpoint_cohort | 7717 | -0.005307173457394262 | {"claim_by_centered_denier_propensity":-0.06820628373878745} | 2e70bdf9daa35bf8b0f0bcc75a333e5e96cfeea8f613c6f8cb463c73044ce481 | claim_by_centered_denier_propensity | 0.02644701584014567 | 0.3354830947307415 |  | 0.02745949142166264 | 0.02644701584014567 |

20 records in the exact extract; 28 fields in its first row.

## results/c6_c12/results/c6_c10/c6_models.csv

SHA-256: `aa334d6a94c3665e1eb1a9cc286dbfa4a6a037b5d26331b47f076a5cad9f1c90`

| estimand | state_conditioned | rows | treated_rows | control_rows | coefficient | p_value_raw | weighted_treated_mean | weighted_control_mean | effect_relative_to_control_mean | coefficient_percentage_points | sample_specification_sha256 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| C_primary_positive_rated_game_denominator | False | 2018635 | 59327 | 1959308 | -1.5933832123669505 | 1.6653539481830944e-06 | 27.303738217636177 | 27.554252734485452 | -0.057827124826098295 |  | b172d4328afd8fc4046ee7fd5b4b514b978a8daebdcf47230fbf2f556f2c8b4a |
| C_mandatory_unnormalized_count | False | 2110400 | 62237 | 2048163 | -0.13443330302015274 | 1.4245057873126457e-10 | 2.3774442855536098 | 2.5821579336584746 | -0.052062385986469784 |  | e190819e8e70da1669f8adaac7e863d39c5fcf4233a42468c54fa2d2d61cbe62 |
| denominator_diagnostic | False | 2110400 | 62237 | 2048163 | -0.8327072342481695 | 0.6724488592167062 | 297.30539711104325 | 315.69174996813086 | -0.00263772250726296 |  | 6b100110cffd24284783e0f9aeeb54e617bd758f11d2064d10cdb5a0adb79fa1 |
| S_zero_coded_nonreturner_rate_contribution | False | 2110400 | 62237 | 2048163 | -1.5150213162041182 | 2.266625245492097e-06 | 26.027104089813157 | 26.3251210327988 | -0.05755040268633652 |  | 6c08fda16dbfbba73a57b4fa6e7ab17aeb2abbe6a3b86134f9866e534491f67c |
| S_all_timeout_rate | False | 2018635 | 59327 | 1959308 | -1.6683072144035622 | 0.00024335683345358755 | 49.93014442863074 | 49.113635562602475 | -0.03396831033363559 |  | ae57abd814c77d802eb35d94deda587167b6b5958c67567ba0cf4acd640ce7c5 |
| S_all_timeout_count | False | 2110400 | 62237 | 2048163 | -0.13813301974723488 | 3.784215381858678e-05 | 4.5536256567636615 | 4.80137206542172 | -0.028769488776350893 |  | a5b29be89f019449423b652521b5f8deeef5e358c29d45f204367088b63c0399 |
| S_any_timeout | False | 2110400 | 62237 | 2048163 | -0.00635519340044721 | 0.0007454334686779057 | 0.6751771454279608 | 0.6847007904389527 | -0.009281708870779861 | -0.635519340044721 | f9a41ad09b6d274ed9c4586e827c92bebbe6655e84e4b8122b67739b96efd3d9 |
| S_any_clearly_losing_timeout | False | 2110400 | 62237 | 2048163 | -0.01424320655257785 | 2.592318895533779e-12 | 0.5079936372254447 | 0.5244194357964375 | -0.027159951711070066 | -1.424320655257785 | 15e856c32c0930f678372cff72fc2f38675a543b99c7efa597d78c2d2d93f267 |
| S_clear_share_conditional_any_timeout | False | 1448272 | 42021 | 1406251 | -0.014374873953113865 | 5.450633642181312e-15 | 0.4775201084274695 | 0.4915766935364766 | -0.02924238301392782 |  | 878713ad69382c79ab3e1b9c24de372743522584c8cb9b004b297485622862ad |
| S_no_tournament_clear_rate | False | 2018635 | 59327 | 1959308 | -1.5933832123669505 | 1.6653539481830944e-06 | 27.303738217636177 | 27.554252734485452 | -0.057827124826098295 |  | 20c5818a19fa4f689a32ec1844188c2eb3545f7fdca4bafafdb9901fb34c8a61 |
| S_no_tournament_clear_count | False | 2110400 | 62237 | 2048163 | -0.13443330302015274 | 1.4245057873126457e-10 | 2.3774442855536098 | 2.5821579336584746 | -0.052062385986469784 |  | f501ee61786e8e3712999d17d33cef5552b76ee023215c1bbdad81d7b1ffe57f |
| S_no_tournament_all_timeout_rate | False | 2018635 | 59327 | 1959308 | -1.6683072144035622 | 0.00024335683345358755 | 49.93014442863074 | 49.113635562602475 | -0.03396831033363559 |  | ed94cfaa5a37092c3010e2f433c6fa29df92e59bb5c5db93a08f045766669d5a |
| S_no_tournament_clear_share | False | 1448272 | 42021 | 1406251 | -0.014374873953113865 | 5.450633642181312e-15 | 0.4775201084274695 | 0.4915766935364766 | -0.02924238301392782 |  | 7a40afd8dda237cecfb3a0a6d55ef6a6905f944bce953284f8ad50bd32b10d7a |

13 records in the exact extract; 32 fields in its first row.

## results/c6_c12/results/c6_ply/c6_ply_model_attempts.csv

SHA-256: `8ff5cf7209d50e28a3623902aa95e6e4a1dd27bb83af71b79ad866e5dee23d0e`

| estimand | requested_rows_before_common_support | holm_family_member |
|---|---|---|
| S_ply_retrofit_exposure_ply_gt10_original_primary_outcome | 1545040 | False |
| S_ply_retrofit_exposure_ply_gt10_unnormalized_count | 1545040 | False |
| S_ply_retrofit_later_event_ply_gt10_per_all_rated_games | 2112804 | False |
| S_ply_retrofit_both_exposure_and_later_event_ply_gt10_count | 1545040 | False |
| S_ply_retrofit_both_ply_gt10_clear_share_conditional_timeout | 1039924 | False |
| S_ply_retrofit_both_ply_gt10_clear_share_no_tournament | 1039924 | False |

6 records in the exact extract; 8 fields in its first row.

## results/c6_c12/results/c6_ply/c6_ply_models.csv

SHA-256: `bf22fac355538c074aa4763da9b9caffb623728034181046bb6cc04590dd42a8`

| estimand | state_conditioned | rows | treated_rows | control_rows | coefficient | p_value_raw | weighted_treated_mean | weighted_control_mean | effect_relative_to_control_mean | coefficient_percentage_points | sample_specification_sha256 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| S_ply_retrofit_exposure_ply_gt10_original_primary_outcome | False | 1488153 | 38984 | 1449169 | -2.495928989495743 | 2.7831678014884e-12 | 23.85582810035952 | 25.686645978177186 | -0.09716834932891705 |  | 471967187f9b6096320727c9c09dce76c2b712851f20f0537b37e8804a721e37 |
| S_ply_retrofit_exposure_ply_gt10_unnormalized_count | False | 1543448 | 40511 | 1502937 | -0.14267341852950882 | 3.247036564997723e-08 | 2.4048283182345536 | 2.6294833537260383 | -0.054259106956253335 |  | 79f74e4f1c0cba79080f62264afcc7d465f810fead714d41dc3309d68cfb1dd8 |
| S_ply_retrofit_later_event_ply_gt10_per_all_rated_games | False | 2018635 | 59327 | 1959308 | -1.5590473398191464 | 1.6177122061917138e-06 | 26.45416883993649 | 26.825062802626345 | -0.058119056469329335 |  | e00f3354ae23cf5954b70c8d7838987fa86ec020fea519bc5cff65c4069d9f49 |
| S_ply_retrofit_both_exposure_and_later_event_ply_gt10_count | False | 1543448 | 40511 | 1502937 | -0.13986200130911733 | 4.5108304778815845e-08 | 2.376687813186542 | 2.6000460063603903 | -0.05379212558815437 |  | 913c5e3bc1e708c42e2d88a2d2bd5d3514c6c4a83f2f72cd17af07cc7359300a |
| S_ply_retrofit_both_ply_gt10_clear_share_conditional_timeout | False | 1039924 | 26878 | 1013046 | -0.016666434070764714 | 5.976822196651648e-13 | 0.5156175678003501 | 0.5333742114360506 | -0.03124716889834662 |  | d69832e4b6914a0d060766c59bf7f9f2944e593fde310c6a9fd6a2817b8d0984 |
| S_ply_retrofit_both_ply_gt10_clear_share_no_tournament | False | 1039924 | 26878 | 1013046 | -0.016666434070764714 | 5.976822196651648e-13 | 0.5156175678003501 | 0.5333742114360506 | -0.03124716889834662 |  | 0e44227d805df90e5b1e650ba060469d87c5bdd9214c0ea358b593c236b4e4c2 |

6 records in the exact extract; 32 fields in its first row.

## results/c6_c12/results/c7x_dyad/c7x_frequent_dyad_raw_contrasts.csv

SHA-256: `9dca573787505f89df9259a7e248d6ae5e4d1e1e8cdf09e62441950d3d0b444e`

| sample | sample_definition | benefactor_rows | benefactor_kind_rate_pct | claimer_rows | claimer_kind_rate_pct | controlled_model_status |
|---|---|---|---|---|---|---|
| all | All current C7X rows | 125 | 3.2 | 10356 | 1.6801853997682503 | NOT_ESTIMABLE_PARENT_C7X_SUPPORT_GATE_FAILED |
| dyad_pair_games_eq_1 | No other in-window dyad game | 0 |  | 0 |  | NOT_ESTIMABLE_PARENT_C7X_SUPPORT_GATE_FAILED |
| dyad_pair_games_lt_3 | Exclude dyads with 3+ games | 79 | 3.7974683544303796 | 6491 | 1.5868125096287167 | NOT_ESTIMABLE_PARENT_C7X_SUPPORT_GATE_FAILED |
| dyad_pair_games_lt_5 | Exclude dyads with 5+ games | 109 | 3.669724770642202 | 9032 | 1.5389725420726306 | NOT_ESTIMABLE_PARENT_C7X_SUPPORT_GATE_FAILED |
| dyad_pair_games_lt_10 | Exclude dyads with 10+ games | 119 | 3.361344537815126 | 9929 | 1.561083694229026 | NOT_ESTIMABLE_PARENT_C7X_SUPPORT_GATE_FAILED |
| dyad_pair_games_eq_2 | Exactly two in-window dyad games | 79 | 3.7974683544303796 | 6491 | 1.5868125096287167 | NOT_ESTIMABLE_PARENT_C7X_SUPPORT_GATE_FAILED |
| dyad_pair_games_3_4 | Three or four dyad games | 30 | 3.3333333333333335 | 2541 | 1.4167650531286895 | NOT_ESTIMABLE_PARENT_C7X_SUPPORT_GATE_FAILED |
| dyad_pair_games_5_9 | Five to nine dyad games | 10 | 0.0 | 897 | 1.7837235228539576 | NOT_ESTIMABLE_PARENT_C7X_SUPPORT_GATE_FAILED |
| dyad_pair_games_ge_10 | Ten or more dyad games | 6 | 0.0 | 427 | 4.4496487119437935 | NOT_ESTIMABLE_PARENT_C7X_SUPPORT_GATE_FAILED |
| either_player_max_lt_2 | Neither player has a repeated in-window dyad | 0 |  | 0 |  | NOT_ESTIMABLE_PARENT_C7X_SUPPORT_GATE_FAILED |
| either_player_max_lt_3 | Neither player has a 3+ game dyad | 0 |  | 14 | 7.142857142857143 | NOT_ESTIMABLE_PARENT_C7X_SUPPORT_GATE_FAILED |
| either_player_max_lt_5 | Neither player has a 5+ game dyad | 8 | 12.5 | 477 | 2.3060796645702304 | NOT_ESTIMABLE_PARENT_C7X_SUPPORT_GATE_FAILED |
| either_player_max_lt_10 | Neither player has a 10+ game dyad | 49 | 6.122448979591836 | 3161 | 1.8981335020563113 | NOT_ESTIMABLE_PARENT_C7X_SUPPORT_GATE_FAILED |

13 records in the exact extract; 11 fields in its first row.

## results/c7r/results/c7r/c7x_relationship_models.csv

SHA-256: `9e69f892b14c5f3491c9e35ef87543cbfc0b64032a45723d0fee983fe764faac`

| model | rows_requested | rows |
|---|---|---|
| X_C7R_C7X_primary_exact_replication | 10481 |  |
| X_C7R_C7X_chooser_switchers_only | 16 |  |
| X_C7R_C7X_chooser_and_opponent_fe | 10481 |  |
| X_C7R_C7X_directed_pair_fe_chooser_cluster | 10481 |  |
| X_C7R_C7X_directed_pair_fe_unordered_pair_cluster | 10481 |  |
| X_C7R_C7X_directed_pair_fe_ply_gt10 | 8201 |  |
| X_C7R_C7X_le7d_exact_chooser_fe | 1996 |  |
| X_C7R_C7X_le7d_directed_pair_fe | 1996 |  |

8 records in the exact extract; 12 fields in its first row.

## results/c7r/results/c7r/first_meeting_models.csv

SHA-256: `8bdff4dc90a0c8599d68ffe4bb4a054f724ff513653de5c173cf0b5b38fbd61f`

| model | rows_requested | rows | term | coefficient | p_value_two_sided |
|---|---|---|---|---|---|
| X_C7R_fair_vs_clearly_worse_all_meetings | 757646 | 757646 | fair_minus_clearly_worse | 0.015631764768450185 | 2.501761543941127e-192 |
| X_C7R_fair_vs_clearly_worse_first_meetings | 704242 | 704242 | fair_minus_clearly_worse | 0.016157518061178457 | 3.3515223396694243e-174 |
| X_C7R_fair_vs_clearly_worse_repeat_meetings | 53404 |  |  |  |  |
| X_C7R_fair_repeat_interaction_all_meetings | 757646 | 757646 | fair | 0.015943340790702507 | 4.5863060425501315e-187 |
| X_C7R_fair_repeat_interaction_all_meetings | 757646 | 757646 | repeat | 0.001323140961929891 | 0.0473361449549783 |
| X_C7R_fair_repeat_interaction_all_meetings | 757646 | 757646 | fair_x_repeat | -0.0031497184121758058 | 0.021997636204636968 |
| X_C7R_repeat_association_within_fair | 304729 | 304729 | repeat_meeting | 0.0012813552466203462 | 0.42736114056675695 |
| X_C7R_nonnegative_vs_costly_all_meetings | 304729 | 304729 | nonnegative_minus_costly | -0.0008437231836919495 | 0.5491703159192661 |
| X_C7R_nonnegative_vs_costly_first_meetings | 282189 | 282189 | nonnegative_minus_costly | -0.0016538229209880875 | 0.31329532168946905 |
| X_C7R_nonnegative_vs_costly_repeat_meetings | 22540 |  |  |  |  |
| X_C7R_positive_vs_negative_all_meetings | 300137 | 300137 | positive_minus_negative | -0.000825841625820879 | 0.5659819138779094 |
| X_C7R_positive_vs_negative_first_meetings | 278000 | 278000 | positive_minus_negative | -0.0017716381232670043 | 0.2886173109531122 |
| X_C7R_positive_vs_negative_repeat_meetings | 22137 |  |  |  |  |

13 records in the exact extract; 19 fields in its first row.

## results/c7r/results/c7r/pair_sequence_bands.csv

SHA-256: `61178bb737149af88120373e808584fccfe0fb9f405cd9aaee1db416ab779d75`

| pair_sequence_band | rows | fair_rows | clearly_worse_rows |
|---|---|---|---|
| 1 | 772371 | 282189 | 422053 |
| 2 | 40919 | 15600 | 21679 |
| 3-5 | 14709 | 5789 | 7630 |
| 6-10 | 2290 | 879 | 1188 |
| 11+ | 702 | 272 | 367 |

5 records in the exact extract; 4 fields in its first row.

## results/c7r/results/c7r/repeat_kindness_rates.csv

SHA-256: `068aa5c491b7bbc007183ce1b5e37904168ce866380ea9d49863d794ddbd5a82`

| rows | kind_rate_pct |
|---|---|
| 772371 | 1.4182303582086846 |
| 58620 | 1.0235414534288638 |
| 422053 | 0.4795606239026852 |
| 422053 | 0.4795606239026852 |
| 30864 | 0.29484188698807673 |
| 30864 | 0.29484188698807673 |
| 54426 | 2.5043177892918824 |
| 4264 | 1.9699812382739212 |
| 57298 | 3.6947188383538694 |
| 3675 | 2.802721088435374 |
| 282189 | 2.860494207782727 |
| 22540 | 2.09849157054126 |
| 68129 | 1.2593755962952633 |
| 5216 | 0.6901840490797546 |
| 170465 | 2.6938081131023965 |
| 14601 | 1.958769947263886 |

16 records in the exact extract; 5 fields in its first row.

## results/c7r/results/c7r/repeat_pair_prevalence.csv

SHA-256: `198499ae56a2d0ef29e24550c90c0aa16988e37ce88ba3efb4c664683a6c445f`

| rows | first_meeting_rows | repeat_meeting_rows |
|---|---|---|
| 830991 | 772371 | 58620 |
| 452917 | 422053 | 30864 |
| 304729 | 282189 | 22540 |
| 452917 | 422053 | 30864 |
| 58690 | 54426 | 4264 |
| 60973 | 57298 | 3675 |
| 73345 | 68129 | 5216 |
| 185066 | 170465 | 14601 |

8 records in the exact extract; 5 fields in its first row.

## results/c7r_cov/c7r_linear_combination.json

SHA-256: `9b81e0d8d00a65904ace415d873de3253ccd774d6cada2e8a3c1be9979011c12`

```json
{
  "created_at_utc": "2026-09-11T04:42:21.934131+00:00",
  "estimand_note": "The repeat-meeting fairness gradient is beta_fair + beta_fair_x_repeat. Its variance uses the chooser-clustered covariance from the unchanged frozen model.",
  "exposure_covariance": {
    "fair": {
      "fair": 2.98723719140079e-07,
      "fair_x_repeat": -1.928617621234487e-07,
      "repeat": 5.404688836060561e-08
    },
    "fair_x_repeat": {
      "fair": -1.928617621234488e-07,
      "fair_x_repeat": 1.8911130541883756e-06,
      "repeat": -4.5424351583749744e-07
    },
    "repeat": {
      "fair": 5.404688836060563e-08,
      "fair_x_repeat": -4.5424351583749786e-07,
      "repeat": 4.4508616718048916e-07
    }
  },
  "fair_fair_x_repeat_covariance": -1.928617621234487e-07,
  "first_meeting_gradient": {
    "ci95": [
      0.014872090568089448,
      0.017014591013315566
    ],
    "ci95_percentage_points": [
      1.4872090568089449,
      1.7014591013315568
    ],
    "coefficient": 0.015943340790702507,
    "coefficient_percentage_points": 1.5943340790702507,
    "contrast": "fairness_gradient_first_meetings",
    "p_value_two_sided": 4.5863060425501315e-187,
    "standard_error": 0.0005465562360270706,
    "standard_error_percentage_points": 0.054655623602707065,
    "t_cluster": 29.170540449039617,
    "weights": {
      "fair": 1.0
    }
  },
  "interpretation": "The fairness gradient remains positive at repeat meetings but is smaller than at first meetings; the interaction is descriptive, not causal.",
  "model": "X_C7R_fair_repeat_interaction_all_meetings",
  "model_diagnostics": {
    "absorption_iterations": 299,
    "absorption_last_adjustment": 9.59812003034974e-10,
    "absorption_maximum_iterations": 2000,
    "absorption_tolerance": 1e-09,
    "cluster_correction": 1.0000150733014281,
    "clusters": 533531,
    "matrix_rank": 11,
    "rows": 757646,
    "sample_specification_sha256": "dece314a44d3aa2873442254e096c25ea34933d15beb30f05867c75d84ee0d31",
    "smallest_singular_value": 47.648816991493355
  },
  "model_results": [
    {
      "coefficient": 0.015943340790702507,
      "p_value_two_sided": 4.5863060425501315e-187,
      "standard_error": 0.0005465562360270706,
      "t_cluster": 29.170540449039617,
      "term": "fair"
    },
    {
      "coefficient": 0.001323140961929891,
      "p_value_two_sided": 0.0473361449549783,
      "standard_error": 0.000667147785112481,
      "t_cluster": 1.9832801538969507,
      "term": "repeat"
    },
    {
      "coefficient": -0.0031497184121758058,
      "p_value_two_sided": 0.021997636204636968,
      "standard_error": 0.001375177462798302,
      "t_cluster": -2.2904086907929324,
      "term": "fair_x_repeat"
    }
  ],
  "original_repeat_only_nonconvergence_preserved": true,
  "private_row_level_files_transferred": false,
  "repeat_meeting_gradient": {
    "ci95": [
      0.010161003633308983,
      0.015426241123744418
    ],
    "ci95_percentage_points": [
      1.0161003633308983,
      1.5426241123744417
    ],
    "coefficient": 0.0127936223785267,
    "coefficient_percentage_points": 1.2793622378526701,
    "contrast": "fairness_gradient_repeat_meetings",
    "p_value_two_sided": 1.651588676270791e-21,
    "standard_error": 0.001343172829192713,
    "standard_error_percentage_points": 0.1343172829192713,
    "t_cluster": 9.524926428281049,
    "weights": {
      "fair": 1.0,
      "fair_x_repeat": 1.0
    }
  },
  "repeat_minus_first_gradient": {
    "ci95": [
      -0.005845066239260477,
      -0.0004543705850911339
    ],
    "ci95_percentage_points": [
      -0.5845066239260477,
      -0.04543705850911339
    ],
    "coefficient": -0.0031497184121758058,
    "coefficient_percentage_points": -0.3149718412175806,
    "contrast": "repeat_minus_first_fairness_gradient",
    "p_value_two_sided": 0.021997636204636968,
    "standard_error": 0.001375177462798302,
    "standard_error_percentage_points": 0.1375177462798302,
    "t_cluster": -2.2904086907929324,
    "weights": {
      "fair_x_repeat": 1.0
    }
  },
  "repeat_only_model_retried": false,
  "reproduction": {
    "checks": [
      {
        "coefficient_absolute_difference_from_frozen_constant": 0.0,
        "coefficient_absolute_difference_from_returned_wave2b2a": 0.0,
        "pass": true,
        "standard_error_absolute_difference_from_frozen_constant": 0.0,
        "standard_error_absolute_difference_from_returned_wave2b2a": 0.0,
        "term": "fair"
      },
      {
        "coefficient_absolute_difference_from_frozen_constant": 0.0,
        "coefficient_absolute_difference_from_returned_wave2b2a": 0.0,
        "pass": true,
        "standard_error_absolute_difference_from_frozen_constant": 0.0,
        "standard_error_absolute_difference_from_returned_wave2b2a": 0.0,
        "term": "repeat"
      },
      {
        "coefficient_absolute_difference_from_frozen_constant": 0.0,
        "coefficient_absolute_difference_from_returned_wave2b2a": 0.0,
        "pass": true,
        "standard_error_absolute_difference_from_frozen_constant": 0.0,
        "standard_error_absolute_difference_from_returned_wave2b2a": 0.0,
        "term": "fair_x_repeat"
      }
    ],
    "status": "FROZEN_WAVE2B2A_MODEL_REPRODUCED_OK",
    "tolerance": 5e-10
  },
  "sample_fingerprint": "a17c89d750cb4fdfdf84f950859e45c58b19996efae02045def68285e305cf30",
  "script_version": "1.0.0",
  "status": "C7R_LINEAR_COMBINATION_CLOSURE_OK"
}
```

## results/c9/c9_partition_components.csv

SHA-256: `2c325121f91ee2d781cac88b10f402d3a0ec8127ed5d311863ab6aa1af11c966`

| observed_numerator | observed_denominator | observed_rate | observed_rate_pct | null_mean_rate | null_mean_rate_pct | excess_percentage_points | effect_relative_to_null_mean_pct | randomization_p_two_sided | null_p025 | null_p975 | holm_adjusted_p_value |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 689 | 1306 | 0.5275650842266463 | 52.75650842266463 | 0.354081256741066 | 35.4081256741066 | 17.348382748558027 | 48.99548456258622 | 0.0004 | 0.33003825712926776 | 0.37896665347359076 |  |
| 9902 | 22455 | 0.44097083054998887 | 44.09708305499889 | 0.32549609930156315 | 32.549609930156315 | 11.547473124842572 | 35.476533050997205 | 0.0004 | 0.3200390283076606 | 0.33095380599013247 | PENDING_NEW_SAMPLE_COMPLETE_FAMILY_RECONCILIATION |
| 2397 | 4729 | 0.5068724888982872 | 50.687248889828716 | 0.3370723928681326 | 33.70723928681326 | 16.980009603015457 | 50.37496384243568 | 0.0004 | 0.32432553655023755 | 0.3498887981236657 |  |
| 165 | 331 | 0.4984894259818731 | 49.848942598187314 | 0.3814887597877825 | 38.14887597877825 | 11.70006661940906 | 30.669492401080607 | 0.0008 | 0.3333333333333333 | 0.42941356910862505 |  |

4 records in the exact extract; 19 fields in its first row.

## results/c9/c9_primary_later_session.json

SHA-256: `9e05b8844ecdce4265d6c9d336190eb6faaab8ee740abe17d12ea7c0431a07e8`

```json
{
  "category": "later_session_7d",
  "effect_relative_to_null_mean_pct": 35.476533050997205,
  "epistemic_label": "C",
  "epistemic_role": "C_primary",
  "excess_percentage_points": 11.547473124842572,
  "holm_adjusted_p_value": "PENDING_NEW_SAMPLE_COMPLETE_FAMILY_RECONCILIATION",
  "interpretation": "Timing association beyond the initiating observed session; not a causal effect or unique mechanism identification",
  "lower_tail_plus_one": 1.0,
  "null_mean_rate": 0.32549609930156315,
  "null_mean_rate_pct": 32.549609930156315,
  "null_p025": 0.3200390283076606,
  "null_p975": 0.33095380599013247,
  "observed_denominator": 22455,
  "observed_numerator": 9902,
  "observed_rate": 0.44097083054998887,
  "observed_rate_pct": 44.09708305499889,
  "randomization_p_two_sided": 0.0004,
  "randomizations": 4999,
  "upper_tail_plus_one": 0.0002
}
```

## results/c9/c9_secondary_contrasts.csv

SHA-256: `da9fa5f6cf48fb10a4fea068486ee96ed205d0a4321079086f52ccd872f36415`

| contrast | observed_rate_difference | observed_rate_difference_pp | null_mean_rate_difference | null_mean_rate_difference_pp | excess_difference_pp | randomization_p_two_sided | null_p025 | null_p975 |
|---|---|---|---|---|---|---|---|---|
| same_session_minus_later_session_excess_7d | 0.0865942536766574 | 8.65942536766574 | 0.028585157439502774 | 2.8585157439502775 | 5.800909623715463 | 0.0004 | 0.003477020632958961 | 0.05392611777708472 |
| same_pool_minus_cross_pool_excess_24h | 0.008383062916414052 | 0.8383062916414052 | -0.044416366919649855 | -4.441636691964986 | 5.279942983606391 | 0.034 | -0.09323149728665747 | 0.004913236929622526 |

2 records in the exact extract; 14 fields in its first row.

## results/c9_ply/c9_ply_components.csv

SHA-256: `6f72b6f68e7fbfa056c0ca95b02cd823c23bfa13b2197298a6dcec50bb7912ee`

| observed_numerator | observed_denominator | observed_contributing_choosers | observed_eligible_anchor_choosers | null_mean_denominator | null_mean_contributing_choosers | finite_null_rates | observed_rate_pct | null_mean_rate_pct | excess_pp | raw_randomization_p_two_sided | null_distribution_p025_pct |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 689 | 1306 | 1259 | 55359 | 1202.1896379275854 | 1150.3034606921385 | 4999 | 52.75650842266463 | 35.4081256741066 | 17.348382748558027 | 0.0004 | 33.003825712926776 |
| 9902 | 22455 | 16200 | 55359 | 22137.67793558712 | 15822.62452490498 | 4999 | 44.09708305499889 | 32.549609930156315 | 11.547473124842572 | 0.0004 | 32.003902830766066 |
| 591 | 1154 | 1119 | 55359 | 1071.1070214042809 | 1032.4306861372274 | 4999 | 51.21317157712305 | 34.807205030100505 | 16.405966547022544 | 0.0004 | 32.22585761699248 |
| 8462 | 19958 | 14862 | 55359 | 19719.647129425884 | 14551.79775955191 | 4999 | 42.399037979757495 | 31.809905539181898 | 10.589132440575593 | 0.0004 | 31.2281480401312 |
| 463 | 944 | 924 | 55359 | 892.0968193638728 | 865.3104620924184 | 4999 | 49.04661016949153 | 34.06225248514632 | 14.984357684345213 | 0.0004 | 31.24299473543754 |
| 6688 | 16475 | 12866 | 55359 | 16339.551910382077 | 12646.092618523704 | 4999 | 40.5948406676783 | 31.015539005782074 | 9.579301661896228 | 0.0004 | 30.373765934550324 |
| 315 | 660 | 654 | 55359 | 618.7907581516304 | 606.7827565513103 | 4999 | 47.72727272727273 | 32.87792043147506 | 14.849352295797669 | 0.0004 | 29.48717948717949 |
| 4535 | 11474 | 9615 | 55359 | 11400.579915983197 | 9463.144628925786 | 4999 | 39.52414153738888 | 30.091478532895323 | 9.432663004493557 | 0.0004 | 29.322375701874293 |
| 311 | 617 | 606 | 37159 | 613.3256651330266 | 594.8425685137028 | 4999 | 50.405186385737444 | 34.13788461563864 | 16.2673017700988 | 0.0004 | 30.704273213830596 |
| 4638 | 11069 | 8637 | 37159 | 11501.767953590717 | 8902.911182236447 | 4999 | 41.90080404733942 | 30.9631971639872 | 10.937606883352219 | 0.0004 | 30.194330728951297 |
| 689 | 1306 | 1259 | 55359 | 1227.8513702740547 | 1175.130226045209 | 4999 | 52.75650842266463 | 38.78456275392556 | 13.971945668739066 | 0.0004 | 36.70552975535685 |
| 9902 | 22455 | 16200 | 55359 | 22309.85797159432 | 16008.287057411482 | 4999 | 44.09708305499889 | 34.72912724512418 | 9.367955809874706 | 0.0004 | 34.260708490466115 |
| 591 | 1154 | 1119 | 55359 | 1088.3662732546509 | 1048.745949189838 | 4999 | 51.21317157712305 | 37.101940582872 | 14.111230994251056 | 0.0004 | 34.90718939160767 |
| 8462 | 19958 | 14862 | 55359 | 19873.770154030804 | 14689.771154230846 | 4999 | 42.399037979757495 | 33.07102393164633 | 9.32801404811116 | 0.0004 | 32.567808304596035 |
| 463 | 944 | 924 | 55359 | 892.9553910782156 | 867.3448689737947 | 4999 | 49.04661016949153 | 35.677838884506485 | 13.368771284985042 | 0.0004 | 33.33153735632184 |
| 6688 | 16475 | 12866 | 55359 | 16427.008801760352 | 12734.015803160632 | 4999 | 40.5948406676783 | 31.76417007954806 | 8.830670588130241 | 0.0004 | 31.203588189381186 |
| 315 | 660 | 654 | 55359 | 612.6759351870375 | 601.252450490098 | 4999 | 47.72727272727273 | 34.33282203840634 | 13.394450688866389 | 0.0004 | 31.414473684210524 |
| 4535 | 11474 | 9615 | 55359 | 11440.714142828565 | 9522.07201440288 | 4999 | 39.52414153738888 | 31.33789844673702 | 8.186243090651857 | 0.0004 | 30.674607328346287 |
| 311 | 617 | 606 | 37159 | 592.1308261652331 | 575.4692938587717 | 4999 | 50.405186385737444 | 37.18078021200786 | 13.224406173729585 | 0.0004 | 34.14592094196804 |
| 4638 | 11069 | 8637 | 37159 | 11066.518903780756 | 8585.721544308863 | 4999 | 41.90080404733942 | 32.54166556482175 | 9.35913848251767 | 0.0004 | 31.87353136661915 |

20 records in the exact extract; 22 fields in its first row.

## results/c9_ply/c9_ply_session_contrasts.csv

SHA-256: `b0ebfdb60c78c295eb55cefa097d62ab2385ade9c29771a0951e13cd697fbd91`

| contrast | difference_in_excess_pp | raw_randomization_p_two_sided |
|---|---|---|
| same_minus_later_excess_7d | 5.800909623715463 | 0.0004 |
| same_minus_later_excess_7d | 5.8168341064469455 | 0.0004 |
| same_minus_later_excess_7d | 5.4050560224489885 | 0.0008 |
| same_minus_later_excess_7d | 5.416689291304108 | 0.0044 |
| same_minus_later_excess_7d | 5.329694886746582 | 0.0048 |
| same_minus_later_excess_7d | 4.603989858864362 | 0.0004 |
| same_minus_later_excess_7d | 4.783216946139899 | 0.0004 |
| same_minus_later_excess_7d | 4.538100696854805 | 0.0012 |
| same_minus_later_excess_7d | 5.208207598214532 | 0.0008 |
| same_minus_later_excess_7d | 3.865267691211913 | 0.0164 |

10 records in the exact extract; 8 fields in its first row.

## results/c9_ply/summary.json

SHA-256: `e8914bf8fee950e16c689bd8bbef057e5bb07ab40729a7f26d44332a1570f7a0`

```json
{
  "config_sha256": "24c6d608556a8378246863e9ab4ff78e8b48ea1ccc01a1c00d3847d7e8223762",
  "created_utc": "2026-09-11T18:14:24Z",
  "draws_per_law": 4999,
  "exact_original_C9_and_B2_reproduction": true,
  "inference_limit": "New post-outcome sensitivity; fixed ply-band grant totals are descriptive conditioning, not a causal design.",
  "laws": [
    "original",
    "ply_band_conditioned"
  ],
  "new_chronology_or_API_requests": false,
  "new_sensitivities_added_to_Holm_family": false,
  "original_confirmatory_estimate_changed": false,
  "outcome_rules": [
    "all",
    "outcome_gt4",
    "outcome_gt10",
    "outcome_gt20",
    "anchor_and_outcome_gt10"
  ],
  "remaining": [
    "C13 if retained",
    "global Holm reconciliation",
    "C9 alternative session cutoffs and singleton appendix if retained",
    "integrated manuscript updates"
  ],
  "row_level_outputs_transferred": false,
  "runtime_seconds_this_invocation": 207.21407212503254,
  "sample_fingerprint": "a17c89d750cb4fdfdf84f950859e45c58b19996efae02045def68285e305cf30",
  "session_cache_reused": true,
  "status": "C9_PLY_SENSITIVITIES_COMPLETE",
  "unsupported_rows": 0,
  "version": "C9-PLY-1.0.0"
}
```

## results/iv/comparison_estimates.csv

SHA-256: `82b9d7fcd3d0fa2901a3bd902161d9a9217e579080a2736d9d8f066cc22d64e9`

| MDE80_percent_of_outcome_mean | MDE80_pp_per_current_IV_SD | ci90_high_pp_per_current_IV_SD | ci90_low_pp_per_current_IV_SD | ci95_high_pp_per_current_IV_SD | ci95_low_pp_per_current_IV_SD | coefficient_per_unit_score | coefficient_pp_per_current_IV_SD | coefficient_pp_per_native_SD | outcome_mean | p_value_asymptotic | sample_rule |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1.893327669459753 | 0.041182945003463534 | -0.09886482425356206 | -0.14722310086034457 | -0.09423274222989507 | -0.1518551828840116 | -0.020710395857198218 | -0.12304396255695334 | -0.11041096830243088 | 0.02175162052916851 | 5.741795999683445e-17 | not_mutually_adjacent_observed |
| 1.918305291797992 | 0.04172624876628579 | -0.09854584228612562 | -0.14754208282778103 | -0.09385265177220985 | -0.1522352733416968 | -0.020710395857198218 | -0.12304396255695334 | -0.11041096830243088 | 0.02175162052916851 | 1.4394728305681266e-16 | not_mutually_adjacent_observed |
| 0.44163941129314194 | 0.13280700872396362 | -0.00367005190046936 | -0.15961611313170682 | 0.011267514067081588 | -0.17455367909925776 | -0.013741922177834893 | -0.0816430825160881 | -0.07326074037662847 | 0.3007136712167471 | 0.08501990209933946 | not_mutually_adjacent_observed |
| 0.429191645291857 | 0.1290637953112702 | -0.005867749874643152 | -0.15741841515753302 | 0.008648795411695512 | -0.1719349604438717 | -0.013741922177834893 | -0.0816430825160881 | -0.07326074037662847 | 0.3007136712167471 | 0.07635725576832958 | not_mutually_adjacent_observed |
| 2.7515638596534564 | 0.03232889365526916 | -0.020452849251713937 | -0.058414427318587994 | -0.01681663316437437 | -0.06205064340592756 | -0.006637353365444682 | -0.039433638285150965 | -0.03538496401020925 | 0.011749279792961375 | 0.0006325151076397259 | not_mutually_adjacent_observed |
| 2.768661370804596 | 0.03252977709754718 | -0.02033490750341757 | -0.05853236906688436 | -0.01667609690318559 | -0.06219117966711634 | -0.006637353365444682 | -0.039433638285150965 | -0.03538496401020925 | 0.011749279792961375 | 0.0006833555743472991 | not_mutually_adjacent_observed |
| 2.601220568176854 | 0.02599984363121801 | -0.06818770360262823 | -0.09871751709570872 | -0.06526335207089125 | -0.1016418686274457 | -0.01404649655075763 | -0.08345261034916847 | -0.07488448294854155 | 0.009995247596185511 | 2.420076433877013e-19 | not_mutually_adjacent_observed |
| 2.543633707252475 | 0.02542424869799174 | -0.06852564421119905 | -0.0983795764871379 | -0.06566603314284776 | -0.10123918755548919 | -0.01404649655075763 | -0.08345261034916847 | -0.07488448294854155 | 0.009995247596185511 | 3.717662391768955e-20 | not_mutually_adjacent_observed |
| 4.345349457442949 | 0.01866942998468703 | -0.009508269119243004 | -0.031430486173281424 | -0.007408411252912519 | -0.03353034403961191 | -0.0034453451042618277 | -0.020469377646262214 | -0.018367774895300847 | 0.004296416241669361 | 0.002128504829595326 | not_mutually_adjacent_observed |
| 4.412062217537887 | 0.018956055770685515 | -0.009339986726607102 | -0.031598768565917326 | -0.007207890414222521 | -0.03373086487830191 | -0.0034453451042618277 | -0.020469377646262214 | -0.018367774895300847 | 0.004296416241669361 | 0.0024843210336381928 | not_mutually_adjacent_observed |
| 13.268302828853525 | 0.007004765347612182 | 0.0041535704934224085 | -0.004071639729327483 | 0.004941436626938386 | -0.004859505862843462 | 6.895171945162324e-06 | 4.0965382047462424e-05 | 3.675944276132827e-05 | 0.0005279322787522964 | 0.9869278239980522 | not_mutually_adjacent_observed |
| 13.604403993759654 | 0.007182204001492376 | 0.0042577474470661065 | -0.004175816682971181 | 0.00506557112365903 | -0.004983640359564104 | 6.895171945162324e-06 | 4.0965382047462424e-05 | 3.675944276132827e-05 | 0.0005279322787522964 | 0.9872507484644611 | not_mutually_adjacent_observed |
| 1.983302408641224 | 0.04241983445423678 | -0.09203992831017428 | -0.14185059843052106 | -0.08726872623596918 | -0.14662180050472617 | -0.019683880847897274 | -0.11694526337034768 | -0.1048086166545115 | 0.021388485320954626 | 1.1312518498275353e-14 | not_mutually_adjacent_observed |
| 2.0150383692349494 | 0.04309861858154206 | -0.0916414037439763 | -0.14224912299671905 | -0.08679385492589997 | -0.14709667181479538 | -0.019683880847897274 | -0.11694526337034768 | -0.1048086166545115 | 0.021388485320954626 | 2.9177586161625054e-14 | not_mutually_adjacent_observed |
| 0.45766632883374225 | 0.13847019494021195 | 0.03575690372906196 | -0.12683904437884308 | 0.05133144073078147 | -0.1424135813805626 | -0.007665338262756448 | -0.045541070324890555 | -0.040814791844984266 | 0.30255709501957795 | 0.35683879513698336 | not_mutually_adjacent_observed |
| 0.4428467403913723 | 0.1339864233117028 | 0.03312441267439292 | -0.12420655332417403 | 0.04819463416499735 | -0.13927677481477846 | -0.007665338262756448 | -0.045541070324890555 | -0.040814791844984266 | 0.30255709501957795 | 0.34097543921884244 | not_mutually_adjacent_observed |
| 2.906565337542347 | 0.033579530136092675 | -0.013031024454007724 | -0.05246113821858651 | -0.009254142108816088 | -0.05623802056377814 | -0.00551172355923447 | -0.03274608133629712 | -0.02934767417509314 | 0.011552993391328998 | 0.006294168991301097 | not_mutually_adjacent_observed |
| 2.915469435632366 | 0.03368239912248241 | -0.012970628495223381 | -0.05252153417737084 | -0.009182175885141548 | -0.05630998678745267 | -0.00551172355923447 | -0.03274608133629712 | -0.02934767417509314 | 0.011552993391328998 | 0.006455403130761768 | not_mutually_adjacent_observed |
| 2.6956457703631553 | 0.026492107036521547 | -0.06846581138712075 | -0.09957365566248415 | -0.0654860921668801 | -0.10255337488272478 | -0.01414195304633119 | -0.08401973352480246 | -0.07530011723970388 | 0.00982774047235166 | 6.378911289159412e-19 | not_mutually_adjacent_observed |
| 2.6425563415047124 | 0.025970357907875396 | -0.06877213829842223 | -0.09926732875118267 | -0.06585110319510092 | -0.10218836385450397 | -0.01414195304633119 | -0.08401973352480246 | -0.07530011723970388 | 0.00982774047235166 | 1.2605835888998332e-19 | not_mutually_adjacent_observed |
| 4.62289779553617 | 0.019611542866332838 | -0.008166036851228126 | -0.031194511734122864 | -0.005960214145739839 | -0.03340033443961116 | -0.003312525561673876 | -0.019680274292675496 | -0.01763784410373705 | 0.004242261830938502 | 0.004932584314388139 | not_mutually_adjacent_observed |
| 4.61271845724542 | 0.019568359448037777 | -0.008191390498066194 | -0.0311691580872848 | -0.0059904248793061195 | -0.03337012370604487 | -0.003312525561673876 | -0.019680274292675496 | -0.01763784410373705 | 0.004242261830938502 | 0.004838284432277077 | not_mutually_adjacent_observed |
| 13.709506966346929 | 0.0069074627372918765 | 0.003204392413807989 | -0.00490656210080749 | 0.003981314364675479 | -0.005683484051674979 | -0.00014325208365085557 | -0.0008510848434997502 | -0.0007627587687783838 | 0.0005038447228078879 | 0.7299515737015252 | not_mutually_adjacent_observed |
| 13.843112674354355 | 0.00697477926820843 | 0.0032439149810017383 | -0.004946084668001239 | 0.004028408408186134 | -0.005730578095185635 | -0.00014325208365085557 | -0.0008510848434997502 | -0.0007627587687783838 | 0.0005038447228078879 | 0.7324574751663926 | not_mutually_adjacent_observed |

80 records in the exact extract; 39 fields in its first row.

## results/iv/iv_primary.json

SHA-256: `a31e09da6336e296fc33e6ffb4bf62880b3ae6fd4716d77452460aab7f1b3bbc`

| choosers | coefficient | coefficient_pp | estimator | p_value_asymptotic | post_assignment_state_controls | specification |
|---|---|---|---|---|---|---|
| 510827 | 0.06521909519207189 | 6.521909519207189 | first_stage_receipt_per_SD_Z | 0.0 | False | PRIMARY_main_adjusted_7d_floor5 |
| 510827 | 0.00026070649189139755 | 0.026070649189139754 | reduced_form_kindness_per_SD_Z | 0.04128439792089716 | False | PRIMARY_main_adjusted_7d_floor5 |
| 510827 | 0.0055442350432006425 | 0.5544235043200643 | same_sample_OLS | 4.711443207057046e-10 | False | PRIMARY_main_adjusted_7d_floor5 |
| 510827 | -0.0002571099918697155 | -0.025710999186971548 | reduced_form_reach_per_SD_Z | 0.5756123662768936 | False | PRIMARY_main_adjusted_7d_floor5 |
| 510827 |  |  | candidate_2SLS |  | False | PRIMARY_main_adjusted_7d_floor5 |

5 records in the exact extract; 27 fields in its first row.

## results/iv/summary.json

SHA-256: `e800e77fdf2fc6f00634a3fa87802cdc364c5bb85b1d1211bf2bbc89400e51fa`

```json
{
  "causal_identification_certified": false,
  "chronology_manifest_sha256": "1d4648bb17cafd9e58c14ab78d32abe855f0bc62a6fb75ac88e02494a73337cd",
  "chronology_rows": 7763847245,
  "chronology_verification": "pinned original manifest, file size/row-group/row counts and run-time change detection; no pre-existing full-byte hashes in chronology manifest",
  "comparison_classification_counts": {
    "ambiguous_start_order": 9,
    "left_boundary_unresolved": 4588,
    "mutual_adjacency_candidate_timing_unresolved": 129171,
    "not_mutually_adjacent_observed": 1527795
  },
  "comparison_games_before_history_and_adjacency_cuts": 1661563,
  "config_sha256": "ccbc4331487512b8b7ce41b620a8699ed056f6961a25b49c65ad52c2c0da013c",
  "current_iv_score_sd": 0.059411690344000595,
  "elapsed_note": "No estimated data results are bundled in the code package.",
  "eligibility_timing": "observed previous nonadjacency, not verified end-to-start rematch status",
  "first_exposures_reselected_from_new_main_sample": true,
  "first_pairs_observed_in_canonical_history_not_lifetime_certified": true,
  "full_earlier_histories_preserved": true,
  "instrument": "all-source historical Stage07; month-start minus7/30days; pair leave-all-out, four-fold cross-fitted state adjustment",
  "iv_exposures": 2112795,
  "iv_receipts": 62304,
  "main_opportunities": 41534331,
  "network_requests": 0,
  "old_IV_cohort_used": false,
  "outcome": "first later fair main-sample choice against a different opponent; start strictly after focal lastMoveAt anchor, decision within90d; zero only with complete90",
  "primary_iv": [
    {
      "assignment_cells": 4634,
      "causal_identification_certified": false,
      "choosers": 510827,
      "ci_high": 0.06617433620561759,
      "ci_high_pp": 6.617433620561759,
      "ci_low": 0.06426385417852619,
      "ci_low_pp": 6.426385417852619,
      "clustering": "chooser_and_exposure_date_CR0",
      "coefficient": 0.06521909519207189,
      "coefficient_pp": 6.521909519207189,
      "conditional_on_reaching_opportunity": false,
      "estimator": "first_stage_receipt_per_SD_Z",
      "exposure_dates": 611,
      "inference_small_cluster_warning": false,
      "lag_days": 7,
      "minimum_history": 5,
      "n": 1071174,
      "outcome": "other_started_after_y",
      "p_value_asymptotic": 0.0,
      "post_assignment_state_controls": false,
      "receipts": 25288,
      "residual_instrument_sd": 0.059411690344000595,
      "specification": "PRIMARY_main_adjusted_7d_floor5",
      "standard_error": 0.00048737681971735923,
      "standard_error_pp": 0.048737681971735926,
      "supported": true,
      "wald_F_one_df": 17906.874889791725
    },
    {
      "assignment_cells": 4634,
      "causal_identification_certified": false,
      "choosers": 510827,
      "ci_high": 0.0005111032952294062,
      "ci_high_pp": 0.05111032952294062,
      "ci_low": 1.030968855338896e-05,
      "ci_low_pp": 0.001030968855338896,
      "clustering": "chooser_and_exposure_date_CR0",
      "coefficient": 0.00026070649189139755,
      "coefficient_pp": 0.026070649189139754,
      "conditional_on_reaching_opportunity": false,
      "estimator": "reduced_form_kindness_per_SD_Z",
      "exposure_dates": 611,
      "inference_small_cluster_warning": false,
      "lag_days": 7,
      "minimum_history": 5,
      "n": 1071174,
      "outcome": "other_started_after_y",
      "p_value_asymptotic": 0.04128439792089716,
      "post_assignment_state_controls": false,
      "receipts": 25288,
      "residual_instrument_sd": 0.059411690344000595,
      "specification": "PRIMARY_main_adjusted_7d_floor5",
      "standard_error": 0.00012775581863396808,
      "standard_error_pp": 0.012775581863396808,
      "supported": true,
      "wald_F_one_df": 4.1643029165286904
    },
    {
      "assignment_cells": 4634,
      "causal_identification_certified": false,
      "choosers": 510827,
      "ci_high": 0.007288897480293944,
      "ci_high_pp": 0.7288897480293944,
      "ci_low": 0.0037995726061073403,
      "ci_low_pp": 0.37995726061073404,
      "clustering": "chooser_and_exposure_date_CR0",
      "coefficient": 0.0055442350432006425,
      "coefficient_pp": 0.5544235043200643,
      "conditional_on_reaching_opportunity": false,
      "estimator": "same_sample_OLS",
      "exposure_dates": 611,
      "inference_small_cluster_warning": false,
      "lag_days": 7,
      "minimum_history": 5,
      "n": 1071174,
      "outcome": "other_started_after_y",
      "p_value_asymptotic": 4.711443207057046e-10,
      "post_assignment_state_controls": false,
      "receipts": 25288,
      "residual_instrument_sd": 0.059411690344000595,
      "specification": "PRIMARY_main_adjusted_7d_floor5",
      "standard_error": 0.0008901502531959653,
      "standard_error_pp": 0.08901502531959653,
      "supported": true,
      "wald_F_one_df": 38.79329130914485
    },
    {
      "assignment_cells": 4634,
      "causal_identification_certified": false,
      "choosers": 510827,
      "ci_high": 0.0006430716962751409,
      "ci_high_pp": 0.0643071696275141,
      "ci_low": -0.0011572916800145717,
      "ci_low_pp": -0.11572916800145717,
      "clustering": "chooser_and_exposure_date_CR0",
      "coefficient": -0.0002571099918697155,
      "coefficient_pp": -0.025710999186971548,
      "conditional_on_reaching_opportunity": false,
      "estimator": "reduced_form_reach_per_SD_Z",
      "exposure_dates": 611,
      "inference_small_cluster_warning": false,
      "lag_days": 7,
      "minimum_history": 5,
      "n": 1071174,
      "outcome": "other_started_after_y",
      "p_value_asymptotic": 0.5756123662768936,
      "post_assignment_state_controls": false,
      "receipts": 25288,
      "residual_instrument_sd": 0.059411690344000595,
      "specification": "PRIMARY_main_adjusted_7d_floor5",
      "standard_error": 0.0004592848109686579,
      "standard_error_pp": 0.04592848109686579,
      "supported": true,
      "wald_F_one_df": 0.3133817800600444
    },
    {
      "AR95_intervals": [
        [
          0.00015819475209530613,
          0.007832597189868926
        ]
      ],
      "AR95_reason": null,
      "AR95_unbounded": false,
      "AR_covariance_psd": true,
      "MDE_caveat": "conditional large-sample approximation; does not include first-stage estimation uncertainty",
      "approx_MDE80_IV_pp": 0.5487945086615604,
      "assignment_cells": 4634,
      "causal_identification_certified": false,
      "choosers": 510827,
      "cluster
... [preview truncated; complete object in SELECTED_RESULTS.json]
```

## results/iv_selection/estimates.csv

SHA-256: `65daf1a2e6f6a3c8519185f2e1566481b802a5703679a4cfdf77551981d35d80`

| specification | sample | estimand | coefficient_per_unit_score | coefficient_pp_per_current_IV_SD | coefficient_pp_per_native_SD | outcome_mean | outcome_mean_pp | standard_error_pp_per_current_IV_SD | ci95_low_pp_per_current_IV_SD | ci95_high_pp_per_current_IV_SD | p_value_asymptotic |
|---|---|---|---|---|---|---|---|---|---|---|---|
| primary | eligible_main_and_history_supported | probability_point_change_per_current_primary_IV_score_SD | -0.03445231803503393 | -0.20468704507304628 | -0.18367170867906374 | 0.3224652917459156 | 32.24652917459156 | 0.04883919124316427 | -0.3004101009437122 | -0.10896398920238033 | 2.7767766753774317e-05 |
| primary | eligible_main_and_history_supported | probability_point_change_per_current_primary_IV_score_SD | -0.03445231803503393 | -0.20468704507304628 | -0.18367170867906374 | 0.3224652917459156 | 32.24652917459156 | 0.04715710129010125 | -0.2971132652169521 | -0.11226082492914051 | 1.421362747151138e-05 |
| primary | eligible_main_history_supported_and_timeforfeit_candidate | probability_point_change_per_current_primary_IV_score_SD | -0.057120771751407846 | -0.33936416035049793 | -0.2863660114956825 | 0.0674541449450242 | 6.745414494502421 | 0.04738346059134893 | -0.4322340365724148 | -0.24649428412858104 | 7.946171887075578e-13 |
| primary | eligible_main_history_supported_and_timeforfeit_candidate | probability_point_change_per_current_primary_IV_score_SD | -0.057120771751407846 | -0.33936416035049793 | -0.2863660114956825 | 0.0674541449450242 | 6.745414494502421 | 0.048533889431859 | -0.43448883566659074 | -0.24423948503440512 | 2.7039022292989997e-12 |
| lag30 | eligible_main_and_history_supported | probability_point_change_per_current_primary_IV_score_SD | -0.027349219110654105 | -0.1624863336952405 | -0.1456234084994978 | 0.3239455803405326 | 32.39455803405326 | 0.05092261678148104 | -0.26229282858547825 | -0.0626798388050027 | 0.0014185585278795754 |
| lag30 | eligible_main_and_history_supported | probability_point_change_per_current_primary_IV_score_SD | -0.027349219110654105 | -0.1624863336952405 | -0.1456234084994978 | 0.3239455803405326 | 32.39455803405326 | 0.04959487117841147 | -0.25969049502283054 | -0.06528217236765048 | 0.0010518685923267045 |
| lag30 | eligible_main_history_supported_and_timeforfeit_candidate | probability_point_change_per_current_primary_IV_score_SD | -0.05658564547028845 | -0.3361848846596177 | -0.2842318551652606 | 0.06602493325721864 | 6.6024933257218645 | 0.04824191706049196 | -0.43073730464335036 | -0.2416324646758851 | 3.198152727956559e-12 |
| lag30 | eligible_main_history_supported_and_timeforfeit_candidate | probability_point_change_per_current_primary_IV_score_SD | -0.05658564547028845 | -0.3361848846596177 | -0.2842318551652606 | 0.06602493325721864 | 6.6024933257218645 | 0.048623678943703244 | -0.43148554418511464 | -0.2408842251341208 | 4.711226544626844e-12 |
| floor1 | eligible_main_and_history_supported | probability_point_change_per_current_primary_IV_score_SD | -0.015060307989481625 | -0.08947583547563605 | -0.1102366245554603 | 0.3269558785552371 | 32.69558785552371 | 0.031970600935005575 | -0.15213706187234954 | -0.026814609078922535 | 0.00513102014996594 |
| floor1 | eligible_main_and_history_supported | probability_point_change_per_current_primary_IV_score_SD | -0.015060307989481625 | -0.08947583547563605 | -0.1102366245554603 | 0.3269558785552371 | 32.69558785552371 | 0.0311712981032291 | -0.15057045710932676 | -0.028381213841945307 | 0.0040988041087284205 |
| floor1 | eligible_main_history_supported_and_timeforfeit_candidate | probability_point_change_per_current_primary_IV_score_SD | -0.04061503498374444 | -0.24130078817649758 | -0.2871943288819643 | 0.06709035416179109 | 6.709035416179108 | 0.029274770469826447 | -0.29867828395303414 | -0.18392329239996102 | 1.684809840490784e-16 |
| floor1 | eligible_main_history_supported_and_timeforfeit_candidate | probability_point_change_per_current_primary_IV_score_SD | -0.04061503498374444 | -0.24130078817649758 | -0.2871943288819643 | 0.06709035416179109 | 6.709035416179108 | 0.028911892623801165 | -0.29796705644403715 | -0.18463451990895804 | 7.056974818148944e-17 |
| floor10 | eligible_main_and_history_supported | probability_point_change_per_current_primary_IV_score_SD | -0.03971276582985333 | -0.23594025461870538 | -0.18843847704520023 | 0.31787260518680543 | 31.787260518680544 | 0.060705290845041435 | -0.3549204383460156 | -0.1169600708913951 | 0.0001016368843016111 |
| floor10 | eligible_main_and_history_supported | probability_point_change_per_current_primary_IV_score_SD | -0.03971276582985333 | -0.23594025461870538 | -0.18843847704520023 | 0.31787260518680543 | 31.787260518680544 | 0.06161142822803045 | -0.3566964349817195 | -0.11518407425569126 | 0.0001284098940158932 |
| floor10 | eligible_main_history_supported_and_timeforfeit_candidate | probability_point_change_per_current_primary_IV_score_SD | -0.06948930252543489 | -0.41284769238617164 | -0.30704574291558273 | 0.06928867909172295 | 6.928867909172295 | 0.061679995729435666 | -0.5337382625824498 | -0.2919571221898934 | 2.180728408597456e-11 |
| floor10 | eligible_main_history_supported_and_timeforfeit_candidate | probability_point_change_per_current_primary_IV_score_SD | -0.06948930252543489 | -0.41284769238617164 | -0.30704574291558273 | 0.06928867909172295 | 6.928867909172295 | 0.06288008305547371 | -0.5360903905197874 | -0.28960499425255587 | 5.1811486915213695e-11 |

16 records in the exact extract; 32 fields in its first row.

## results/iv_selection/summary.json

SHA-256: `280fabcba46e0ba6a28fca28f89c7b1788bbfe9a62e04c312ce5bf5fa93a77cc`

```json
{
  "active_and_passive_mutually_exclusive": true,
  "candidate_definition": "active_timeout OR passive_outoftime",
  "causal_identification_certified": false,
  "config_sha256": "4f96d54f47af44d490440791632ba644af3234a66c448cfcb159bb206586bb1d",
  "existing_selection_estimates_reproduced": true,
  "interpretation": "Post-hoc selection decomposition. The candidate-incidence model is fit on the full eligible comparison sample. The active-given-candidate model is refit within time-forfeit candidates and is descriptive, not a causal effect.",
  "network_requests": 0,
  "primary": [
    {
      "absorb_iterations": 7,
      "assignment_cells": 4111,
      "causal_identification_certified": false,
      "ci95_high_pp_per_current_IV_SD": -0.11226082492914051,
      "ci95_low_pp_per_current_IV_SD": -0.2971132652169521,
      "clustering": "shared_account_OR_date_CR0",
      "coefficient_per_unit_score": -0.03445231803503393,
      "coefficient_pp_per_current_IV_SD": -0.20468704507304628,
      "coefficient_pp_per_native_SD": -0.18367170867906374,
      "continuous_control_rank": 7,
      "continuous_controls": [
        "recipient_rating",
        "rating_gap",
        "rating_gap_square",
        "abs_rating_gap",
        "log_opponent_prior_decisions",
        "log_opponent_prior_counterparts",
        "opponent_history_expected_rate"
      ],
      "controls": "pregame_export_W_common",
      "current_IV_score_sd": 0.059411690344000595,
      "estimand": "probability_point_change_per_current_primary_IV_score_SD",
      "family": "selection_decomposition_posthoc",
      "floor": 5,
      "historical_scores_treated_as_fixed": true,
      "inference": "normal_approximation_conditional_on_recorded_history",
      "lag": 7,
      "n": 986869,
      "native_residual_score_sd": 0.05331185799814437,
      "outcome": "timeforfeit_candidate",
      "outcome_mean": 0.3224652917459156,
      "outcome_mean_pp": 32.24652917459156,
      "p_value_asymptotic": 1.421362747151138e-05,
      "positive": 318231,
      "sample": "eligible_main_and_history_supported",
      "specification": "primary",
      "standard_error_pp_per_current_IV_SD": 0.04715710129010125,
      "supported": true,
      "unavailable_controls": [
        "pregame_RD",
        "all_game_prior_30d_volume",
        "internal_conduct_category"
      ],
      "variance_correction": "CR0"
    },
    {
      "absorb_iterations": 9,
      "assignment_cells": 3511,
      "causal_identification_certified": false,
      "ci95_high_pp_per_current_IV_SD": -0.24423948503440512,
      "ci95_low_pp_per_current_IV_SD": -0.43448883566659074,
      "clustering": "shared_account_OR_date_CR0",
      "coefficient_per_unit_score": -0.057120771751407846,
      "coefficient_pp_per_current_IV_SD": -0.33936416035049793,
      "coefficient_pp_per_native_SD": -0.2863660114956825,
      "continuous_control_rank": 7,
      "continuous_controls": [
        "recipient_rating",
        "rating_gap",
        "rating_gap_square",
        "abs_rating_gap",
        "log_opponent_prior_decisions",
        "log_opponent_prior_counterparts",
        "opponent_history_expected_rate"
      ],
      "controls": "pregame_export_W_common",
      "current_IV_score_sd": 0.059411690344000595,
      "estimand": "probability_point_change_per_current_primary_IV_score_SD",
      "family": "selection_decomposition_posthoc",
      "floor": 5,
      "historical_scores_treated_as_fixed": true,
      "inference": "normal_approximation_conditional_on_recorded_history",
      "lag": 7,
      "n": 318231,
      "native_residual_score_sd": 0.05013342829854614,
      "outcome": "active_given_timeforfeit_candidate",
      "outcome_mean": 0.0674541449450242,
      "outcome_mean_pp": 6.745414494502421,
      "p_value_asymptotic": 2.7039022292989997e-12,
      "positive": 21466,
      "sample": "eligible_main_history_supported_and_timeforfeit_candidate",
      "specification": "primary",
      "standard_error_pp_per_current_IV_SD": 0.048533889431859,
      "supported": true,
      "unavailable_controls": [
        "pregame_RD",
        "all_game_prior_30d_volume",
        "internal_conduct_category"
      ],
      "variance_correction": "CR0"
    }
  ],
  "reproduction_checks": 16,
  "source_IV_config_sha256": "ccbc4331487512b8b7ce41b620a8699ed056f6961a25b49c65ad52c2c0da013c",
  "source_report_zip_sha256": "04315ee80b96700498d7c0bf6c016f856d3ca68c9f4916ef3af33889f8ebf31e",
  "status": "CHOOSER_IV_SELECTION_ADDENDUM_COMPLETE",
  "version": "1.0.1"
}
```

## results/patron3b1/CORE_PATRON_COMPARISON.csv

SHA-256: `276c9e589e10d13ca9afb38247aab4cff73fe1bc9a9ca017049311f240dcbb07`

| coefficient_pp | estimand_class | model | p_two_sided_approx | se_pp | drop_reason |
|---|---|---|---|---|---|
| 0.3120822390136273 | frozen_primary_family_new_sample | main_fair_kind_1to3_01_match_cell_fe_only_HC1 | 3.363379561306433e-62 | 0.0187508030156693 |  |
| 0.276884175883009 | frozen_primary_family_new_sample | main_fair_kind_1to3_08_all_controls_HC1 | 1.1149556372759006e-49 | 0.0186852277196831 |  |
| 0.3120822390136273 | sensitivity | main_fair_kind_match_cell_fe_only_CR1 | 4.515857273104919e-16 | 0.0384155105620244 |  |
| 0.276884175883009 | sensitivity | main_fair_kind_all_controls_CR1 | 1.7674441353397076e-15 | 0.0347990423954182 |  |
| 0.3884338501687823 | frozen_primary_family_new_sample | diagnostic_horse_race_min4_full_match_cell_fe_HC1 | 1.537944606006629e-42 | 0.0284154517412459 |  |
| -0.1945927321458224 | frozen_primary_family_new_sample | diagnostic_horse_race_min4_full_match_cell_fe_HC1 | 1.8339884355497048e-10 | 0.0305260964630148 |  |
| 0.3884338501687823 | sensitivity | diagnostic_horse_race_min4_full_match_cell_fe_CR1 | 1.473371323913614e-34 | 0.0316813760030988 |  |
| -0.1945927321458224 | sensitivity | diagnostic_horse_race_min4_full_match_cell_fe_CR1 | 5.4956772366346255e-09 | 0.0333696839377358 |  |
| 0.276860596083766 | postcertification_date_sensitivity_reset | corrected_dates_main_full_HC1 | 1.1412859641477268e-49 | 0.0186856138657875 |  |
| 0.3883516439325835 | postcertification_date_sensitivity_reset | corrected_dates_diagnostic_min4_full_HC1 | 1.5976696674324094e-42 | 0.0284152016099354 |  |
| -0.194669100716471 | postcertification_date_sensitivity_reset | corrected_dates_diagnostic_min4_full_HC1 | 1.8057343135009207e-10 | 0.0305266833382826 |  |
| 0.276860596083766 | postcertification_date_sensitivity_reset | corrected_dates_main_full_CR1 | 1.6988370879520265e-15 | 0.0347746669720578 |  |
| 0.3883516439325835 | postcertification_date_sensitivity_reset | corrected_dates_diagnostic_min4_full_CR1 | 1.5218899160681403e-34 | 0.0316814557066144 |  |
| -0.194669100716471 | postcertification_date_sensitivity_reset | corrected_dates_diagnostic_min4_full_CR1 | 5.348523391025282e-09 | 0.0333568882242265 |  |
| 0.3120987839751499 | mixed_date_profile_gap_fill_sensitivity | main_fair_kind_1to3_01_match_cell_fe_only_HC1 | 3.2934886073193136e-62 | 0.0187503808393199 |  |
| 0.2769318755626337 | mixed_date_profile_gap_fill_sensitivity | main_fair_kind_1to3_08_all_controls_HC1 | 1.0691210710294688e-49 | 0.0186848910769898 |  |
| 0.3884544059481891 | mixed_date_profile_gap_fill_sensitivity | diagnostic_horse_race_min4_full_match_cell_fe_HC1 | 1.5219627776677228e-42 | 0.0284153754124772 |  |
| -0.1945905351605087 | mixed_date_profile_gap_fill_sensitivity | diagnostic_horse_race_min4_full_match_cell_fe_HC1 | 1.8347618874164923e-10 | 0.0305260612814187 |  |
| 0.3120987839751499 | mixed_date_profile_gap_fill_sensitivity | main_fair_kind_match_cell_fe_only_CR1 | 4.470622333078543e-16 | 0.038411773137796 |  |
| 0.2769318755626337 | mixed_date_profile_gap_fill_sensitivity | main_fair_kind_all_controls_CR1 | 1.7178932738043924e-15 | 0.034789650376641 |  |
| 0.3884544059481891 | mixed_date_profile_gap_fill_sensitivity | diagnostic_horse_race_min4_full_match_cell_fe_CR1 | 1.379135463959317e-34 | 0.031669221596109 |  |
| -0.1945905351605087 | mixed_date_profile_gap_fill_sensitivity | diagnostic_horse_race_min4_full_match_cell_fe_CR1 | 5.499346043854917e-09 | 0.0333699443112524 |  |
| 0.2769088963343569 | mixed_date_profile_gap_fill_sensitivity_corrected_dates | corrected_dates_main_full_HC1 | 1.093867918183524e-49 | 0.0186852784779394 |  |
| 0.3883722766025972 | mixed_date_profile_gap_fill_sensitivity_corrected_dates | corrected_dates_diagnostic_min4_full_HC1 | 1.5810144584095402e-42 | 0.0284151255410702 |  |

28 records in the exact extract; 17 fields in its first row.

## results/patron3b1/chooser_contrasts.csv

SHA-256: `047af6390a0269954eb587373a4e4120871b6c44154ee403fc60b111dc6b7ec5`

| model | contrast | se_pp | p_two_sided_approx | estimand_class |
|---|---|---|---|---|
| diagnostic_horse_race_min2_exposure_match_cell_fe_HC1 | fair_minus_clearly_worse | 0.0389585894400487 | 1.0908389575436252e-63 | secondary |
| diagnostic_horse_race_min2_full_match_cell_fe_HC1 | fair_minus_clearly_worse | 0.038325770930953025 | 9.169000873758866e-42 | secondary |
| diagnostic_horse_race_min4_exposure_match_cell_fe_HC1 | fair_minus_clearly_worse | 0.046720523481903774 | 1.3297578808422307e-52 | frozen_primary_family_new_sample |
| diagnostic_horse_race_min4_full_match_cell_fe_HC1 | fair_minus_clearly_worse | 0.046020576556180914 | 8.802417962278713e-37 | frozen_primary_family_new_sample |
| diagnostic_horse_race_min4_full_match_cell_fe_CR1 | fair_minus_clearly_worse | 0.05880991419579083 | 3.6278142364981e-23 | sensitivity |
| diagnostic_horse_race_min5_exposure_match_cell_fe_HC1 | fair_minus_clearly_worse | 0.050459873894803324 | 6.85260400600359e-48 | secondary |
| diagnostic_horse_race_min5_full_match_cell_fe_HC1 | fair_minus_clearly_worse | 0.049761153681876516 | 2.158289527906575e-34 | secondary |
| diagnostic_horse_race_min10_exposure_match_cell_fe_HC1 | fair_minus_clearly_worse | 0.06691039670202172 | 2.4585428700687773e-27 | secondary |
| diagnostic_horse_race_min10_full_match_cell_fe_HC1 | fair_minus_clearly_worse | 0.06614158234072313 | 3.2179530580348007e-20 | secondary |
| price_side_horse_race_min2_match_cell_fe_HC1 | costly_minus_nonnegative | 0.061080152434267704 | 0.046437811430193675 | secondary |
| price_side_horse_race_min2_full_match_cell_fe_HC1 | costly_minus_nonnegative | 0.06067412378884265 | 0.2859357747189383 | secondary |
| price_side_horse_race_min4_match_cell_fe_HC1 | costly_minus_nonnegative | 0.08425945803973085 | 0.07080917785782674 | secondary |
| price_side_horse_race_min4_full_match_cell_fe_HC1 | costly_minus_nonnegative | 0.08364895575244986 | 0.28199224121710964 | secondary |

13 records in the exact extract; 14 fields in its first row.

## results/patron3b1/diagnostic_kindness_raw_groups.csv

SHA-256: `81417e3a93457a2664ef168a8571e0f3053beb1a459eb9d3bb65a6d62304276b`

| diagnostic_group | patron_rate_pct | minimum_opportunities_each_state |
|---|---|---|
| both | 0.4597803767520757 | 2 |
| fair_only | 0.8179547403347873 | 2 |
| losing_only | 0.22911211616281837 | 2 |
| neither | 0.3927806054111974 | 2 |
| both | 0.49176704608244004 | 4 |
| fair_only | 0.9019479293937678 | 4 |
| losing_only | 0.2592352559948153 | 4 |
| neither | 0.4310145470162649 | 4 |
| both | 0.5051427180329864 | 5 |
| fair_only | 0.9294036702421637 | 5 |
| losing_only | 0.2688516195109461 | 5 |
| neither | 0.4386859824525607 | 5 |
| both | 0.583452893352463 | 10 |
| fair_only | 0.9631524258652386 | 10 |
| losing_only | 0.2738038195632829 | 10 |
| neither | 0.4913092473705778 | 10 |

16 records in the exact extract; 5 fields in its first row.

## results/patron3b1/missing_outcome_bounds.json

SHA-256: `0f5201be3dcab2083e7d1c76b1f012f434924323a7e14f22576e80cf0034785c`

```json
{
  "assumptions": "Unknown Patron indicators lie in {0,1}; all target memberships and new match cells are fixed.",
  "by_cell": [
    {
      "control_missing": 8,
      "control_target": 48360,
      "kind_missing": 1,
      "kind_target": 16120,
      "lower_gap_pp": 0.22125723738626962,
      "match_cell": "01__blitz",
      "upper_gap_pp": 0.24400330851943758,
      "weight": 12090.0
    },
    {
      "control_missing": 2,
      "control_target": 11415,
      "kind_missing": 2,
      "kind_target": 3805,
      "lower_gap_pp": 0.11388523872098116,
      "match_cell": "01__bullet",
      "upper_gap_pp": 0.18396846254927723,
      "weight": 2853.75
    },
    {
      "control_missing": 18,
      "control_target": 3606,
      "kind_missing": 0,
      "kind_target": 1202,
      "lower_gap_pp": -0.11092623405435384,
      "match_cell": "01__classical_or_long",
      "upper_gap_pp": 0.3882418191902385,
      "weight": 901.5
    },
    {
      "control_missing": 38,
      "control_target": 46257,
      "kind_missing": 3,
      "kind_target": 15419,
      "lower_gap_pp": -0.019456514689668584,
      "match_cell": "01__rapid",
      "upper_gap_pp": 0.08214972868971183,
      "weight": 11564.25
    },
    {
      "control_missing": 9,
      "control_target": 36831,
      "kind_missing": 1,
      "kind_target": 12277,
      "lower_gap_pp": 0.016290624745459024,
      "match_cell": "02__blitz",
      "upper_gap_pp": 0.04887187423637698,
      "weight": 9207.75
    },
    {
      "control_missing": 0,
      "control_target": 8388,
      "kind_missing": 0,
      "kind_target": 2796,
      "lower_gap_pp": 0.15498330948974728,
      "match_cell": "02__bullet",
      "upper_gap_pp": 0.15498330948974728,
      "weight": 2097.0
    },
    {
      "control_missing": 5,
      "control_target": 1512,
      "kind_missing": 0,
      "kind_target": 504,
      "lower_gap_pp": -0.13227513227513227,
      "match_cell": "02__classical_or_long",
      "upper_gap_pp": 0.1984126984126984,
      "weight": 378.0
    },
    {
      "control_missing": 14,
      "control_target": 28125,
      "kind_missing": 3,
      "kind_target": 9375,
      "lower_gap_pp": 0.1706666666666667,
      "match_cell": "02__rapid",
      "upper_gap_pp": 0.25244444444444447,
      "weight": 7031.25
    },
    {
      "control_missing": 4,
      "control_target": 29364,
      "kind_missing": 1,
      "kind_target": 9788,
      "lower_gap_pp": 0.3133088135131453,
      "match_cell": "03__blitz",
      "upper_gap_pp": 0.3371475275847977,
      "weight": 7341.0
    },
    {
      "control_missing": 0,
      "control_target": 6678,
      "kind_missing": 0,
      "kind_target": 2226,
      "lower_gap_pp": 0.41928721174004185,
      "match_cell": "03__bullet",
      "upper_gap_pp": 0.41928721174004185,
      "weight": 1669.5
    },
    {
      "control_missing": 1,
      "control_target": 780,
      "kind_missing": 0,
      "kind_target": 260,
      "lower_gap_pp": -0.38461538461538464,
      "match_cell": "03__classical_or_long",
      "upper_gap_pp": -0.2564102564102564,
      "weight": 195.0
    },
    {
      "control_missing": 8,
      "control_target": 21111,
      "kind_missing": 0,
      "kind_target": 7037,
      "lower_gap_pp": 0.23684335180711472,
      "match_cell": "03__rapid",
      "upper_gap_pp": 0.27473828809625306,
      "weight": 5277.75
    },
    {
      "control_missing": 2,
      "control_target": 24150,
      "kind_missing": 1,
      "kind_target": 8050,
      "lower_gap_pp": 0.31055900621118016,
      "match_cell": "04__blitz",
      "upper_gap_pp": 0.33126293995859213,
      "weight": 6037.5
    },
    {
      "control_missing": 0,
      "control_target": 5682,
      "kind_missing": 0,
      "kind_target": 1894,
      "lower_gap_pp": 0.35198873636043637,
      "match_cell": "04__bullet",
      "upper_gap_pp": 0.35198873636043637,
      "weight": 1420.5
    },
    {
      "control_missing": 0,
      "control_target": 552,
      "kind_missing": 1,
      "kind_target": 184,
      "lower_gap_pp": -0.3623188405797102,
      "match_cell": "04__classical_or_long",
      "upper_gap_pp": 0.18115942028985502,
      "weight": 138.0
    },
    {
      "control_missing": 5,
      "control_target": 15504,
      "kind_missing": 1,
      "kind_target": 5168,
      "lower_gap_pp": 0.06449948400412794,
      "match_cell": "04__rapid",
      "upper_gap_pp": 0.11609907120743033,
      "weight": 3876.0
    },
    {
      "control_missing": 12,
      "control_target": 82995,
      "kind_missing": 5,
      "kind_target": 27665,
      "lower_gap_pp": 0.42050725947346235,
      "match_cell": "05_09__blitz",
      "upper_gap_pp": 0.45303933971926025,
      "weight": 20748.75
    },
    {
      "control_missing": 2,
      "control_target": 17220,
      "kind_missing": 0,
      "kind_target": 5740,
      "lower_gap_pp": 0.7897793263646922,
      "match_cell": "05_09__bullet",
      "upper_gap_pp": 0.8013937282229966,
      "weight": 4305.0
    },
    {
      "control_missing": 0,
      "control_target": 1440,
      "kind_missing": 0,
      "kind_target": 480,
      "lower_gap_pp": 0.3472222222222222,
      "match_cell": "05_09__classical_or_long",
      "upper_gap_pp": 0.3472222222222222,
      "weight": 360.0
    },
    {
      "control_missing": 24,
      "control_target": 48129,
      "kind_missing": 5,
      "kind_target": 16043,
      "lower_gap_pp": 0.1911529431319994,
      "match_cell": "05_09__rapid",
      "upper_gap_pp": 0.27218516902491224,
      "weight": 12032.25
    },
    {
      "control_missing": 0,
      "control_target": 570,
      "kind_missing": 0,
      "kind_target": 190,
      "lower_gap_pp": -0.1754385964912281,
      "match_cell": "101_plus__blitz",
      "upper_gap_pp": -0.1754385964912281,
      "weight": 142.5
    },
    {
      "control_missing": 0,
      "control_target": 21,
      "kind_missing": 0,
      "kind_target": 7,
      "lower_gap_pp": 0.0,
      "match_cell": "101_plus__bullet",
      "upper_gap_pp": 0.0,
      "weight": 5.25
    },
    {
      "control_missing": 0,
      "control_target": 9,
      "kind_missing": 0,
      "kind_target": 3,
      "lower_gap_pp": 0.0,
      "match_cell": "101_plus__classical_or_long",
      "upper_gap_pp": 0.0,
      "weight": 2.25
    },
    {
      "control_missing": 0,
      "control_target": 309,
      "kind_missing": 0,
      "kind_target": 103,
      "lower_gap_pp": 0.32362459546925554,
      "match_cell": "101_plus__rapid",
      "upper_gap_pp": 0.3236245954
... [preview truncated; complete object in SELECTED_RESULTS.json]
```

## results/patron3b1/raw_matched_patron_comparisons.csv

SHA-256: `ea4c527338739964d54a26b12397f330d1b0906ea6f66c3f8b0e78880c1d108d`

| sample | estimand_class | treated_rate_pct | control_rate_pct | gap_pp | unpooled_se_pp | pooled_p_two_sided |
|---|---|---|---|---|---|---|
| primary_available_outcomes_with_returned_kind_focal | frozen_primary_family_new_sample | 0.6432394081633612 | 0.33119119163029415 | 0.3120482165330671 | 0.01876175179256308 | 6.313497425799183e-85 |
| complete_four_account_groups | missingness_sensitivity | 0.6437990256014747 | 0.33138328223070795 | 0.31241574337076683 | 0.018777227470274493 | 5.307579091358238e-85 |
| all_available_target_outcomes_including_unreturned_focal_groups | missingness_sensitivity | 0.6432394081633612 | 0.3311445005576511 | 0.3120949076057101 | 0.018761363869684723 | 5.804278199243287e-85 |
| broad_any_kind_target_roles | qa_secondary | 0.5451355604188899 | 0.32405157328425727 | 0.22108398713463254 | 0.015332118782729892 | 2.852764373536333e-60 |

4 records in the exact extract; 19 fields in its first row.

## results/patron3b2/dyad/dyad_patron_rematches.csv

SHA-256: `ca9410e83f2cbdc1cae8e4b037c051419c99b7cf71252f88f749b3e867b76a17`

| kind_patron_rate_returned_pct | control_patron_rate_returned_pct | raw_gap_pp | cell_fe_gap_pp | returned_rows |
|---|---|---|---|---|
| 0.6432394081633612 | 0.3331766917293233 | 0.31006271643403793 | 0.31008609809725085 | 851229 |
| 0.6271651551126853 | 0.33090078004992707 | 0.29626437506275827 | 0.2962838450954988 | 822027 |
| 0.6379623095467011 | 0.33142018047320926 | 0.3065421290734918 | 0.3065644454068523 | 844476 |
| 0.6406514780643946 | 0.3326878352379189 | 0.3079636428264757 | 0.3079837787446947 | 849674 |

4 records in the exact extract; 13 fields in its first row.

## results/patron3b2/opportunity/opportunity_linear_combinations.csv

SHA-256: `3ee17f897696a1ab549ce1ca262a957a9d44b70ec751a61e5a0e6d0c4ba44447`

| model | contrast | coefficient_pp | se_pp | p_two_sided_approx |
|---|---|---|---|---|
| patron_by_five_bin_desert_gradient__all | patron_gap_disconnected_clearly_better | 5.811161760036406 | 0.5630207917520869 | 5.639585813739939e-25 |
| patron_by_five_bin_desert_gradient__all | patron_gap_disconnected_better | 3.2446860878899244 | 0.41513751679882754 | 5.455836020019402e-15 |
| patron_by_five_bin_desert_gradient__all | patron_gap_roughly_equal | 3.0861930625190155 | 0.5141782998607626 | 1.9468020343365714e-09 |
| patron_by_five_bin_desert_gradient__all | patron_gap_modestly_worse | 0.5298398982851182 | 0.21255509945209725 | 0.012676952453687046 |
| patron_by_five_bin_desert_gradient__all | patron_gap_clearly_worse | -0.27065773641207613 | 0.058244620803894115 | 3.3693775713279474e-06 |
| patron_by_five_bin_desert_gradient__all | patron_gap_clearly_better_minus_clearly_worse | 6.081819496448482 | 0.5492085496867584 | 1.6813821069972222e-28 |
| patron_by_five_bin_desert_gradient__all | patron_gap_disconnected_clearly_better | 5.811161760036406 | 0.3517730980159322 | 2.650146737566797e-61 |
| patron_by_five_bin_desert_gradient__all | patron_gap_disconnected_better | 3.2446860878899244 | 0.265077789249137 | 1.8885318143829038e-34 |
| patron_by_five_bin_desert_gradient__all | patron_gap_roughly_equal | 3.0861930625190155 | 0.13580620843359628 | 2.537580387076335e-114 |
| patron_by_five_bin_desert_gradient__all | patron_gap_modestly_worse | 0.5298398982851182 | 0.1294911834507189 | 4.2821066389662155e-05 |
| patron_by_five_bin_desert_gradient__all | patron_gap_clearly_worse | -0.27065773641207613 | 0.025499337909517864 | 2.5569154477191384e-26 |
| patron_by_five_bin_desert_gradient__all | patron_gap_clearly_better_minus_clearly_worse | 6.081819496448482 | 0.35269449029053346 | 1.2441222101951193e-66 |
| patron_by_favorable_price_in_fair_states__all | patron_gap_costly | 2.7277654186978824 | 0.40023895451650005 | 9.403967638954424e-12 |
| patron_by_favorable_price_in_fair_states__all | patron_gap_nonnegative | 4.190067828183701 | 0.5000132678226143 | 5.2966709346874386e-17 |
| patron_by_favorable_price_in_fair_states__all | additional_nonnegative_response | 1.4623024094858188 | 0.26462109566459513 | 3.2757015949266504e-08 |
| patron_by_favorable_price_in_fair_states__all | patron_gap_costly | 2.7277654186978824 | 0.15232127859222677 | 1.0218888057509378e-71 |
| patron_by_favorable_price_in_fair_states__all | patron_gap_nonnegative | 4.190067828183701 | 0.17442239698130754 | 1.617280910838679e-127 |
| patron_by_favorable_price_in_fair_states__all | additional_nonnegative_response | 1.4623024094858188 | 0.23154982355378723 | 2.6966945487242265e-10 |
| patron_by_fair_state_by_favorable_price__all | patron_gap_clearly_worse_costly | -0.3180727381157489 | 0.06236213468250074 | 3.3891039104911827e-07 |
| patron_by_fair_state_by_favorable_price__all | patron_gap_clearly_worse_nonnegative | -0.22645379940889043 | 0.06654298622152485 | 0.0006662089573014982 |
| patron_by_fair_state_by_favorable_price__all | patron_gap_fair_costly | 2.7501048261224383 | 0.39938207221625655 | 5.742350653751131e-12 |
| patron_by_fair_state_by_favorable_price__all | patron_gap_fair_nonnegative | 4.20009212420527 | 0.49917190843990855 | 3.958567737524179e-17 |
| patron_by_fair_state_by_favorable_price__all | patron_gap_clearly_worse_costly | -0.3180727381157489 | 0.03306620586525683 | 6.630047406464823e-22 |
| patron_by_fair_state_by_favorable_price__all | patron_gap_clearly_worse_nonnegative | -0.22645379940889043 | 0.03946992347314444 | 9.615451872196372e-09 |

26 records in the exact extract; 12 fields in its first row.

## results/patron3b2/ply/ply_linear_combinations.csv

SHA-256: `a05050094d3da4625f8d455e6e1e2b02f051490be1e775d765058aa0458424ff`

| model | contrast | coefficient_pp | se_pp | p_two_sided_approx |
|---|---|---|---|---|
| patron_by_five_bin_desert_gradient__ply_gt4 | patron_gap_disconnected_clearly_better | 5.807760988461631 | 0.5631112203525767 | 6.110170752346812e-25 |
| patron_by_five_bin_desert_gradient__ply_gt4 | patron_gap_disconnected_better | 3.214037578776079 | 0.4144938637353366 | 8.895408664437856e-15 |
| patron_by_five_bin_desert_gradient__ply_gt4 | patron_gap_roughly_equal | 2.7708926463179395 | 0.4702616399022218 | 3.810040961474204e-09 |
| patron_by_five_bin_desert_gradient__ply_gt4 | patron_gap_modestly_worse | 0.5130874194029502 | 0.211450359374871 | 0.015244629929064227 |
| patron_by_five_bin_desert_gradient__ply_gt4 | patron_gap_clearly_worse | -0.27017421681961196 | 0.05813900120760318 | 3.367332191712025e-06 |
| patron_by_five_bin_desert_gradient__ply_gt4 | patron_gap_clearly_better_minus_clearly_worse | 6.077935205281243 | 0.5492308931527993 | 1.8286205898720753e-28 |
| patron_by_five_bin_desert_gradient__ply_gt4 | patron_gap_disconnected_clearly_better | 5.807760988461631 | 0.3517739195417775 | 3.112704981073429e-61 |
| patron_by_five_bin_desert_gradient__ply_gt4 | patron_gap_disconnected_better | 3.214037578776079 | 0.2649412325647072 | 7.224209958056892e-34 |
| patron_by_five_bin_desert_gradient__ply_gt4 | patron_gap_roughly_equal | 2.7708926463179395 | 0.13828580361842183 | 2.598218829931557e-89 |
| patron_by_five_bin_desert_gradient__ply_gt4 | patron_gap_modestly_worse | 0.5130874194029502 | 0.1289388437010487 | 6.911604583773879e-05 |
| patron_by_five_bin_desert_gradient__ply_gt4 | patron_gap_clearly_worse | -0.27017421681961196 | 0.02549437468877629 | 3.063628419086047e-26 |
| patron_by_five_bin_desert_gradient__ply_gt4 | patron_gap_clearly_better_minus_clearly_worse | 6.077935205281243 | 0.3526949486402395 | 1.5057656521388958e-66 |
| patron_by_favorable_price_in_fair_states__ply_gt4 | patron_gap_costly | 2.5977861234054727 | 0.3627609683973787 | 8.000238222043996e-13 |
| patron_by_favorable_price_in_fair_states__ply_gt4 | patron_gap_nonnegative | 3.8953130418160695 | 0.4711843976396156 | 1.37294671920793e-16 |
| patron_by_favorable_price_in_fair_states__ply_gt4 | additional_nonnegative_response | 1.2975269184105969 | 0.2718970490889432 | 1.822915948987863e-06 |
| patron_by_favorable_price_in_fair_states__ply_gt4 | patron_gap_costly | 2.5977861234054727 | 0.15609225564878204 | 3.422331170366282e-62 |
| patron_by_favorable_price_in_fair_states__ply_gt4 | patron_gap_nonnegative | 3.8953130418160695 | 0.17747410870674418 | 8.925629491307975e-107 |
| patron_by_favorable_price_in_fair_states__ply_gt4 | additional_nonnegative_response | 1.2975269184105969 | 0.23632896658603902 | 4.011555620736058e-08 |
| patron_by_fair_state_by_favorable_price__ply_gt4 | patron_gap_clearly_worse_costly | -0.31708307835990723 | 0.062292972242247224 | 3.577044902806003e-07 |
| patron_by_fair_state_by_favorable_price__ply_gt4 | patron_gap_clearly_worse_nonnegative | -0.2252099467117148 | 0.0664376818112646 | 0.0006994557911502941 |
| patron_by_fair_state_by_favorable_price__ply_gt4 | patron_gap_fair_costly | 2.6254223472150997 | 0.36211814981154583 | 4.162131988385683e-13 |
| patron_by_fair_state_by_favorable_price__ply_gt4 | patron_gap_fair_nonnegative | 3.909041009938271 | 0.4706451866484772 | 9.922683841363271e-17 |
| patron_by_fair_state_by_favorable_price__ply_gt4 | patron_gap_clearly_worse_costly | -0.31708307835990723 | 0.033064430758398475 | 8.820936231256363e-22 |
| patron_by_fair_state_by_favorable_price__ply_gt4 | patron_gap_clearly_worse_nonnegative | -0.2252099467117148 | 0.03946647943494395 | 1.1541763262114662e-08 |

104 records in the exact extract; 12 fields in its first row.

## results/patron3b2/postcertification/five_bin_contrasts.csv

SHA-256: `6c0d17c56423cf6e76063b6753b5ad12b58b49bc319d99f4b9f1e8ff2f90cbf3`

| model | contrast | se_pp | p_two_sided_approx | estimand_class |
|---|---|---|---|---|
| five_bin_chooser_min0_exposure_HC1 | ever_kind_eval_clearly_better_minus_ever_kind_eval_better | 0.05136488898220897 | 0.1707262371890346 | postcertification_secondary |
| five_bin_chooser_min0_exposure_HC1 | ever_kind_eval_better_minus_ever_kind_eval_roughly_equal | 0.04814390704425469 | 0.22995459110204733 | postcertification_secondary |
| five_bin_chooser_min0_exposure_HC1 | ever_kind_eval_roughly_equal_minus_ever_kind_eval_modestly_worse | 0.052855707832819336 | 1.040335988596851e-06 | postcertification_secondary |
| five_bin_chooser_min0_exposure_HC1 | ever_kind_eval_modestly_worse_minus_ever_kind_eval_clearly_worse | 0.049565975202791775 | 5.879451417096192e-05 | postcertification_secondary |
| five_bin_chooser_min0_exposure_HC1 | clearly_better_minus_clearly_worse | 0.03883683035013074 | 2.3935846404952195e-51 | postcertification_secondary |
| five_bin_chooser_min0_full_HC1 | ever_kind_eval_clearly_better_minus_ever_kind_eval_better | 0.05217939391051748 | 0.4628516591635404 | postcertification_secondary |
| five_bin_chooser_min0_full_HC1 | ever_kind_eval_better_minus_ever_kind_eval_roughly_equal | 0.04865296879236435 | 0.5612444309172409 | postcertification_secondary |
| five_bin_chooser_min0_full_HC1 | ever_kind_eval_roughly_equal_minus_ever_kind_eval_modestly_worse | 0.05719895434471138 | 0.0001876508891591663 | postcertification_secondary |
| five_bin_chooser_min0_full_HC1 | ever_kind_eval_modestly_worse_minus_ever_kind_eval_clearly_worse | 0.05543472569913253 | 0.001234087441168761 | postcertification_secondary |
| five_bin_chooser_min0_full_HC1 | clearly_better_minus_clearly_worse | 0.04046064038691112 | 7.224024696187093e-30 | postcertification_secondary |
| five_bin_chooser_min2_exposure_HC1 | ever_kind_eval_clearly_better_minus_ever_kind_eval_better | 0.11973374859492433 | 0.2547136979022971 | postcertification_secondary |
| five_bin_chooser_min2_exposure_HC1 | ever_kind_eval_better_minus_ever_kind_eval_roughly_equal | 0.11449643330601326 | 0.13632820884762797 | postcertification_secondary |
| five_bin_chooser_min2_exposure_HC1 | ever_kind_eval_roughly_equal_minus_ever_kind_eval_modestly_worse | 0.12463607384622054 | 0.03053405190248531 | postcertification_secondary |
| five_bin_chooser_min2_exposure_HC1 | ever_kind_eval_modestly_worse_minus_ever_kind_eval_clearly_worse | 0.11133247487367907 | 0.5728898010498616 | postcertification_secondary |
| five_bin_chooser_min2_exposure_HC1 | clearly_better_minus_clearly_worse | 0.09133453307345986 | 2.568620327018477e-12 | postcertification_secondary |
| five_bin_chooser_min2_full_HC1 | ever_kind_eval_clearly_better_minus_ever_kind_eval_better | 0.11923865701859943 | 0.3654935017203708 | postcertification_secondary |
| five_bin_chooser_min2_full_HC1 | ever_kind_eval_better_minus_ever_kind_eval_roughly_equal | 0.11406461670723803 | 0.17205924884206492 | postcertification_secondary |
| five_bin_chooser_min2_full_HC1 | ever_kind_eval_roughly_equal_minus_ever_kind_eval_modestly_worse | 0.12429565464781386 | 0.05564885602931372 | postcertification_secondary |
| five_bin_chooser_min2_full_HC1 | ever_kind_eval_modestly_worse_minus_ever_kind_eval_clearly_worse | 0.11103471791303132 | 0.6336603734829318 | postcertification_secondary |
| five_bin_chooser_min2_full_HC1 | clearly_better_minus_clearly_worse | 0.09028404031547763 | 8.183242998058288e-10 | postcertification_secondary |
| five_bin_chooser_min4_exposure_HC1 | ever_kind_eval_clearly_better_minus_ever_kind_eval_better | 0.19051500860438533 | 0.5647135139609247 | postcertification_secondary |
| five_bin_chooser_min4_exposure_HC1 | ever_kind_eval_better_minus_ever_kind_eval_roughly_equal | 0.19131142138555668 | 0.9222730110063778 | postcertification_secondary |
| five_bin_chooser_min4_exposure_HC1 | ever_kind_eval_roughly_equal_minus_ever_kind_eval_modestly_worse | 0.2224557169808665 | 0.8112918520468264 | postcertification_secondary |
| five_bin_chooser_min4_exposure_HC1 | ever_kind_eval_modestly_worse_minus_ever_kind_eval_clearly_worse | 0.2017670313892058 | 0.11182611955806393 | postcertification_secondary |

35 records in the exact extract; 14 fields in its first row.

## results/patron3b2/postcertification/price_count_rate_contrasts.csv

SHA-256: `d467329dfb94f75e5a9f0a49fa55bbd6a747ffeb2efaa384cf5c4c19dc2f216f`

| model | contrast | se_pp | p_two_sided_approx | estimand_class |
|---|---|---|---|---|
| price_count_min2_exposure_HC1 | standardized_costly_minus_nonnegative_count | 0.02778798062586602 | 0.0018506120533490747 | postcertification_secondary |
| price_count_min2_full_HC1 | standardized_costly_minus_nonnegative_count | 0.02759043789449977 | 0.03782914768771858 | postcertification_secondary |
| price_rate_min2_exposure_HC1 | standardized_costly_minus_nonnegative_rate | 0.02751140172074902 | 0.00011184259347085631 | postcertification_secondary |
| price_rate_min2_full_HC1 | standardized_costly_minus_nonnegative_rate | 0.02732715837693139 | 0.005267396285829288 | postcertification_secondary |
| price_count_min4_exposure_HC1 | standardized_costly_minus_nonnegative_count | 0.041054531954455166 | 0.015063642268863645 | postcertification_secondary |
| price_count_min4_full_HC1 | standardized_costly_minus_nonnegative_count | 0.04071886555887194 | 0.11001024993608016 | postcertification_secondary |
| price_count_min4_full_CR1 | standardized_costly_minus_nonnegative_count | 0.034687940647214796 | 0.06065465018088967 | postcertification_sensitivity |
| price_rate_min4_exposure_HC1 | standardized_costly_minus_nonnegative_rate | 0.05210665533486089 | 0.0012181948238575366 | postcertification_secondary |
| price_rate_min4_full_HC1 | standardized_costly_minus_nonnegative_rate | 0.05172111448821461 | 0.014341921838822836 | postcertification_secondary |
| price_rate_min4_full_CR1 | standardized_costly_minus_nonnegative_rate | 0.05077657096750654 | 0.012626563186817739 | postcertification_sensitivity |

10 records in the exact extract; 14 fields in its first row.

## results/patron3b2/rematches/rematch_contrasts.csv

SHA-256: `01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b`

```json
[]
```

## results/patron3b2/rematches/rematch_summary.csv

SHA-256: `b9ee6e93bb34b19efa629f38ab71286e92a285634a4aca84c2e7e4760b9e7433`

| estimand | mean_pp | share_positive_p_below_0_05 |
|---|---|---|
| raw | 0.3126275288578925 | 1.0 |
| fe | 0.3126275288578935 | 1.0 |
| full | 0.2717136611185971 | 1.0 |

3 records in the exact extract; 11 fields in its first row.

## results/sample/ATTRITION_COUNTS.json

SHA-256: `cfc9cb56e35d3985f2bb7f8545bf4c111ded2498791556ff5cdb1ae10bec57a9`

| fair_rows | rows |
|---|---|
| 15207423 | 41534331 |
| 1286596 | 3448799 |
| 724564 | 2247688 |
| 416 | 582 |
| 109131 | 355620 |

5 records in the exact extract; 8 fields in its first row.

## results/sample/BOARD_STATE_PLY_COUNTS.json

SHA-256: `b7d3ec304d42ab441cb3d42a2c53d954495b5f57f3206013f158626ac755b3d8`

| board_state | fair_rows | rows | sample |
|---|---|---|---|
| better | 16365 | 16365 | main_pool_nonadjacent |
| better | 279725 | 279725 | main_pool_nonadjacent |
| better | 2623380 | 2623380 | main_pool_nonadjacent |
| clearly_better | 45052 | 45052 | main_pool_nonadjacent |
| clearly_better | 2998197 | 2998197 | main_pool_nonadjacent |
| clearly_worse | 0 | 278154 | main_pool_nonadjacent |
| clearly_worse | 0 | 22386664 | main_pool_nonadjacent |
| modestly_worse | 0 | 1504 | main_pool_nonadjacent |
| modestly_worse | 0 | 240643 | main_pool_nonadjacent |
| modestly_worse | 0 | 3419943 | main_pool_nonadjacent |
| roughly_equal | 661173 | 661173 | main_pool_nonadjacent |
| roughly_equal | 2614649 | 2614649 | main_pool_nonadjacent |
| roughly_equal | 5968882 | 5968882 | main_pool_nonadjacent |
| better | 18930 | 18930 | original |
| better | 317041 | 317041 | original |
| better | 2978055 | 2978055 | original |
| clearly_better | 52241 | 52241 | original |
| clearly_better | 3465116 | 3465116 | original |
| clearly_worse | 0 | 324648 | original |
| clearly_worse | 0 | 25765515 | original |
| modestly_worse | 0 | 1961 | original |
| modestly_worse | 0 | 281462 | original |
| modestly_worse | 0 | 3885304 | original |
| roughly_equal | 262 | 262 | original |

53 records in the exact extract; 10 fields in its first row.

## results/sample/MAIN_SAMPLE_REPORT.json

SHA-256: `0ef50e424e004c5698c0c3dbc9815748627e5f23e6504fdaedfd526225ee184e`

```json
{
  "algorithm": "pool-observed-nonadjacency-main-sample-20260909-v100",
  "attrition_counts": [
    {
      "fair_kind_draws": 419463,
      "fair_kindness_pct": 2.758277980431004,
      "fair_rows": 15207423,
      "fair_share_pct": 36.614103643561755,
      "kind_draws": 570091,
      "kindness_pct": 1.3725777839060416,
      "main_exclusion_reason": "included_main",
      "rows": 41534331
    },
    {
      "fair_kind_draws": 42564,
      "fair_kindness_pct": 3.3082645989883384,
      "fair_rows": 1286596,
      "fair_share_pct": 37.30562436372778,
      "kind_draws": 62846,
      "kindness_pct": 1.8222575453078014,
      "main_exclusion_reason": "not_pool",
      "rows": 3448799
    },
    {
      "fair_kind_draws": 21099,
      "fair_kindness_pct": 2.9119580878983773,
      "fair_rows": 724564,
      "fair_share_pct": 32.23596869316382,
      "kind_draws": 30770,
      "kindness_pct": 1.368962240310933,
      "main_exclusion_reason": "pool_adjacent_candidate",
      "rows": 2247688
    },
    {
      "fair_kind_draws": 12,
      "fair_kindness_pct": 2.8846153846153846,
      "fair_rows": 416,
      "fair_share_pct": 71.47766323024055,
      "kind_draws": 14,
      "kindness_pct": 2.4054982817869415,
      "main_exclusion_reason": "pool_ambiguous_order",
      "rows": 582
    },
    {
      "fair_kind_draws": 4032,
      "fair_kindness_pct": 3.6946422189845234,
      "fair_rows": 109131,
      "fair_share_pct": 30.687531634891176,
      "kind_draws": 5782,
      "kindness_pct": 1.6258928069287442,
      "main_exclusion_reason": "pool_missing_previous",
      "rows": 355620
    }
  ],
  "behavioural_models_reestimated": false,
  "code_sha256": {
    "audit_io.py": "f1a2cc45180ae74791ec36dd737f0db9d046586da4ddb2ec84e69a52e1dd810a",
    "build_main_sample.py": "7c54b775194916308f861129ddece3bca52ebea4aad0af3284322d1ac6172fb4",
    "sample_rules.py": "60f7edd9a06ef084f1435f0ed96db740dbcae47739bde16d0ea82b3592561d39"
  },
  "contract_sha256": "74cb5efd7dcb3f6a92710991b8d45cc7f09544e91d5dd2434664a90f732f99dc",
  "elapsed_seconds": 257.18537970795296,
  "eligibility_pattern": "eligibility/parts/partition_month=*/*.parquet",
  "eligibility_qa": {
    "invalid_ids": 0,
    "invalid_joined_rows": 0,
    "rows": 47587020,
    "source_mismatches": 0,
    "unique_ids": 47587020
  },
  "environment": {
    "duckdb": "1.5.4",
    "platform": "macOS-26.4.1-arm64-arm-64bit-Mach-O",
    "pyarrow": "21.0.0",
    "python": "3.13.9 | packaged by Anaconda, Inc. | (main, Oct 21 2025, 19:11:29) [Clang 20.1.8 ]"
  },
  "evidence_sha256": {
    "PANEL_AUTHORITY_REPORT.zip": "0a1a62f6efda4746f034a45c7fc82f2f44735cf1c98bde77ea3a3ddbca4f8d10",
    "SOURCE_JOIN_REPORT.zip": "3a661bae8d5a912e197c22d35ebc6c6c750505760fbc6b516cbabba4a3596254",
    "SOURCE_UNION_REPORT.zip": "a801d1000109124d888874c1d4bfdaca95045c5f150b7398a86a0bb55db7b680"
  },
  "expected_counts": {
    "main_pool_nonadjacent": 41534331,
    "original": 47587020,
    "pool": 44138221,
    "pool_restore_missing_previous": 41889951
  },
  "files": [
    {
      "relative_path": "RUN_CONTRACT.json",
      "sha256": "74cb5efd7dcb3f6a92710991b8d45cc7f09544e91d5dd2434664a90f732f99dc",
      "size_bytes": 84539
    },
    {
      "relative_path": "INPUT_FILES.json",
      "sha256": "f384e53c8bfb51b5b80d87f016fe316fe6e8b54bac95df12b53ba6ab3a186516",
      "size_bytes": 330999
    },
    {
      "relative_path": "SAMPLE_DEFINITION.json",
      "sha256": "deb109c9a40ca20e44842bc0fe7286ab6bf14486c6345fd23f4648796bec704d",
      "size_bytes": 966
    }
  ],
  "input_files_hashed": 288,
  "inputs_unchanged": true,
  "limits": [
    "Sample eligibility uses observed previous adjacency, not a validated end-to-start rematch flag.",
    "The retained sample is not certified as strangers or randomly assigned opponents.",
    "Missing/ambiguous history is excluded in main; the stated robustness restores only missing predecessors.",
    "Master panels contain all board states. Competitive restrictions remain analysis-specific.",
    "Source labels cover timeout opportunities; all-game activity denominators remain separate.",
    "Receipt sequences, exposure histories, chooser signals, Patron matches and figures need rebuilding downstream.",
    "Full histories remain necessary for prior behaviour, ratings, meetings and censoring; discarded opportunities are not erased.",
    "These tables are unadjusted descriptions, not causal estimates or controlled price effects."
  ],
  "literal_immediate_rematches_certified": false,
  "main_panel_pattern": "panel/month=*/analysis_panel.parquet",
  "main_predicate": "source = 'pool' AND previous_classification_status = 'not_mutually_adjacent_observed'",
  "monthly_counts": [
    {
      "chooser_rating_mean": 1456.506411569747,
      "chooser_rating_missing_or_nonfinite": 0,
      "chooser_rating_n": 2015809,
      "chooser_rating_sum": 2936038733.0,
      "choosers": 711155,
      "disconnected_clock_seconds_mean": 272.8728955615118,
      "disconnected_clock_seconds_missing_or_nonfinite": 10,
      "disconnected_clock_seconds_n": 2015799,
      "disconnected_clock_seconds_sum": 550056910.0,
      "disconnected_rating_mean": 1447.103308398762,
      "disconnected_rating_missing_or_nonfinite": 0,
      "disconnected_rating_n": 2015809,
      "disconnected_rating_sum": 2917083873.0,
      "draw_payoff_mean": -0.32900956102519835,
      "draw_payoff_missing_or_nonfinite": 0,
      "draw_payoff_n": 2015809,
      "draw_payoff_sum": -663220.434200644,
      "fair_choosers": 421892,
      "fair_kind_choosers": 17474,
      "fair_kind_draws": 20702,
      "fair_kindness_pct": 2.8287913072945705,
      "fair_rows": 731832,
      "fair_share_pct": 36.30463005175589,
      "game_plies_mean": 40.8073498034784,
      "game_plies_missing_or_nonfinite": 0,
      "game_plies_n": 2015809,
      "game_plies_sum": 82259823.0,
      "kind_choosers": 22702,
      "kind_draws": 28217,
      "kindness_pct": 1.3997853963346725,
      "month": "2023-11",
      "opponent_minus_chooser_rating_mean": -9.403103170984949,
      "opponent_minus_chooser_rating_missing_or_nonfinite": 0,
      "opponent_minus_chooser_rating_n": 2015809,
      "opponent_minus_chooser_rating_sum": -18954860.0,
      "rows": 2015809,
      "sample": "original"
    },
    {
      "chooser_rating_mean": 1448.9910139426588,
      "chooser_rating_missing_or_nonfinite": 0,
      "chooser_rating_n": 1860549,
      "chooser_rating_sum": 2695918782.0,
      "choosers": 655700,
 
... [preview truncated; complete object in SELECTED_RESULTS.json]
```

## results/sample/MONTHLY_ATTRITION_COUNTS.json

SHA-256: `044de24c0be2e5326e26abc82e3ac15db2266f89ff44a21262b30836d017117a`

| fair_rows | rows |
|---|---|
| 9 | 12 |
| 56515 | 155260 |
| 633507 | 1732360 |
| 33009 | 100850 |
| 8792 | 27327 |
| 653331 | 1811457 |
| 34075 | 106218 |
| 7253 | 23002 |
| 58474 | 160407 |
| 18 | 26 |
| 23 | 34 |
| 57392 | 157684 |
| 636666 | 1768148 |
| 6085 | 19619 |
| 33246 | 103807 |
| 52780 | 145217 |
| 30589 | 95110 |
| 606130 | 1674269 |
| 5170 | 16521 |
| 20 | 26 |
| 55100 | 151645 |
| 630770 | 1753915 |
| 31712 | 100225 |
| 4887 | 15986 |

120 records in the exact extract; 6 fields in its first row.

## results/sample/MONTHLY_COUNTS.json

SHA-256: `e5a675e37052d423530c202beef50bc1d697f968ae284d382232efa76f661da5`

| chooser_rating_mean | choosers | disconnected_clock_seconds_mean | disconnected_rating_mean | draw_payoff_mean | fair_choosers | fair_kind_choosers | fair_rows | game_plies_mean | kind_choosers | opponent_minus_chooser_rating_mean | rows |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1456.506411569747 | 711155 | 272.8728955615118 | 1447.103308398762 | -0.32900956102519835 | 421892 | 17474 | 731832 | 40.8073498034784 | 22702 | -9.403103170984949 | 2015809 |
| 1448.9910139426588 | 655700 | 255.73481268163323 | 1444.7415359659972 | -0.22724082548517266 | 389105 | 15869 | 675317 | 40.67723881499493 | 20440 | -4.249477976661727 | 1860549 |
| 1445.3800030016855 | 633879 | 254.92754508300814 | 1441.4404165415965 | -0.19059096308559728 | 373604 | 14863 | 633507 | 40.50778764229144 | 19087 | -3.939586460089127 | 1732360 |
| 1443.9737288506421 | 642508 | 257.2009806289414 | 1439.9739834413733 | -0.22402711589583527 | 378196 | 15130 | 642299 | 40.39917496691173 | 19452 | -3.9997454092688076 | 1759687 |
| 1453.8978092532043 | 730986 | 274.5199222310272 | 1444.2722879811147 | -0.34768286583729263 | 431293 | 17893 | 753151 | 40.95024915401859 | 23488 | -9.625521272089514 | 2101110 |
| 1445.7483190369676 | 674372 | 257.64629209106187 | 1441.3338666452312 | -0.25295355430361066 | 397660 | 16242 | 694677 | 40.82585176608683 | 21156 | -4.414452391736397 | 1940703 |
| 1441.5145117990655 | 653740 | 257.2880984754261 | 1437.3944294565092 | -0.21274838599932147 | 383025 | 15270 | 653331 | 40.63604877178978 | 19818 | -4.120082342556296 | 1811457 |
| 1440.707639691048 | 660979 | 259.1619763646939 | 1436.5325831757482 | -0.2485535368494811 | 386780 | 15472 | 660584 | 40.55106001278851 | 20091 | -4.175056515299606 | 1834459 |
| 1456.3606474821547 | 723377 | 274.0986853437864 | 1446.6436691306071 | -0.3469873885933443 | 424427 | 17832 | 733412 | 41.130111765429234 | 23338 | -9.716978351547754 | 2049292 |
| 1448.5755653391188 | 667397 | 257.1831743151858 | 1444.0723019779996 | -0.24518050800917515 | 391287 | 16133 | 676020 | 41.01183173257884 | 20913 | -4.503263361119217 | 1891608 |
| 1443.9588399839834 | 647892 | 257.0056675119956 | 1439.780606600805 | -0.20531262140000572 | 377104 | 15181 | 636666 | 40.81261014349477 | 19599 | -4.178233383178331 | 1768148 |
| 1443.4540994436077 | 653924 | 258.7271271927494 | 1439.223960952406 | -0.24039180560750156 | 380307 | 15367 | 642751 | 40.73347925093147 | 19850 | -4.230138491201594 | 1787767 |
| 1455.9672339127656 | 696083 | 272.66783023049646 | 1446.3695738741253 | -0.34082899428408575 | 406428 | 16578 | 694689 | 41.17737008600606 | 21747 | -9.597660038640328 | 1931143 |
| 1448.512554831499 | 642637 | 255.9347223793147 | 1444.0557083552173 | -0.24263223785005475 | 375231 | 15107 | 641909 | 41.072866400959505 | 19604 | -4.456846476281772 | 1785926 |
| 1443.8278514384488 | 624628 | 255.785126523874 | 1439.678961385536 | -0.20195885258107163 | 361853 | 14283 | 606130 | 40.877867893391084 | 18469 | -4.148890052912645 | 1674269 |
| 1443.4685626245719 | 629835 | 257.3879121594048 | 1439.282872503386 | -0.23222614553947662 | 364631 | 14431 | 611300 | 40.80481195180951 | 18680 | -4.185690121185955 | 1690790 |
| 1458.5652829807923 | 709242 | 272.3161472084583 | 1448.8364262898667 | -0.3507957155709402 | 415800 | 17099 | 722489 | 41.242731469711615 | 22570 | -9.728856690925602 | 2021798 |
| 1451.2445901485066 | 654689 | 255.47002197146438 | 1446.745045993563 | -0.25129480128628917 | 383674 | 15555 | 667389 | 41.13767697081469 | 20313 | -4.4995441549434725 | 1870153 |
| 1446.4557512764302 | 636980 | 255.44932508131808 | 1442.258759974115 | -0.21347953405811834 | 370537 | 14720 | 630770 | 40.92235598646457 | 19107 | -4.196991302315107 | 1753915 |
| 1446.2080206746027 | 641820 | 256.98652636503397 | 1441.974013800772 | -0.2416573100895405 | 373181 | 14862 | 635657 | 40.851558929002245 | 19311 | -4.234006873830796 | 1769901 |
| 1462.7849730013938 | 689893 | 270.1483014445037 | 1453.3812921983626 | -0.3392081598630397 | 405717 | 16625 | 695170 | 41.1484766860567 | 21730 | -9.403680803031188 | 1917136 |
| 1456.0889643564835 | 637790 | 254.4970428928352 | 1451.7627129142497 | -0.23861536420094867 | 374939 | 15186 | 642989 | 41.06170874225952 | 19661 | -4.326251442233786 | 1775891 |
| 1451.5354519721473 | 620583 | 254.55133546361148 | 1447.4867311589778 | -0.20490666411545816 | 362090 | 14405 | 607989 | 40.8530738041784 | 18571 | -4.048720813169487 | 1666762 |
| 1451.3635670903998 | 625153 | 255.99044191566188 | 1447.2843922693014 | -0.22931442020318826 | 364493 | 14537 | 612337 | 40.79085295849717 | 18743 | -4.079174821098216 | 1681090 |

96 records in the exact extract; 37 fields in its first row.

## results/sample/SAMPLE_COUNTS.json

SHA-256: `343869bd2253cd57321041eddf1b4913d57474079bd804f1a10fa0b20721602f`

| chooser_rating_mean | choosers | disconnected_clock_seconds_mean | disconnected_rating_mean | draw_payoff_mean | fair_choosers | fair_kind_choosers | fair_rows | game_plies_mean | kind_choosers | opponent_minus_chooser_rating_mean | rows |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1459.5492032491213 | 3556701 | 269.9461505446536 | 1450.4088344889005 | -0.3864334697616569 | 2685525 | 248963 | 17328130 | 41.10144226303727 | 326468 | -9.140368760220749 | 47587020 |
| 1453.083888927014 | 3310656 | 254.2621797557269 | 1448.9608926014484 | -0.28583572964936715 | 2499462 | 223442 | 16041534 | 41.01196137923184 | 290930 | -4.122996325565546 | 44138221 |
| 1448.8032735136628 | 3224173 | 254.2787608881915 | 1444.8741058089993 | -0.23535331229866818 | 2442576 | 212859 | 15207423 | 40.81347731350241 | 276482 | -3.9291677046634024 | 41534331 |
| 1448.5974274832645 | 3279885 | 255.69187705662392 | 1444.7234614096349 | -0.2816324469010552 | 2471747 | 215268 | 15316554 | 40.74946919847197 | 279651 | -3.8739660736294486 | 41889951 |

4 records in the exact extract; 36 fields in its first row.

## results/sample/SPEED_COUNTS.json

SHA-256: `b70e02831efdc3bf3c870c69823294ecfaf85a89378aa87748e543ed60b2ad59`

| fair_rows | rows | sample |
|---|---|---|
| 8834781 | 23435814 | main_pool_nonadjacent |
| 1635499 | 5295054 | main_pool_nonadjacent |
| 180305 | 442028 | main_pool_nonadjacent |
| 4556838 | 12361435 | main_pool_nonadjacent |
| 9938459 | 26530507 | original |
| 1773751 | 5785170 | original |
| 304457 | 751656 | original |
| 5311032 | 14519097 | original |
| 431 | 590 | original |
| 9342789 | 24984066 | pool |
| 1716426 | 5582621 | pool |
| 194146 | 481606 | pool |
| 4788173 | 13089928 | pool |
| 8874514 | 23567534 | pool_restore_missing_previous |
| 1645748 | 5325211 | pool_restore_missing_previous |
| 187031 | 462727 | pool_restore_missing_previous |
| 4609261 | 12534479 | pool_restore_missing_previous |

17 records in the exact extract; 9 fields in its first row.

## results/wave1/modules/core_stage08/tables/table01_fairness_bins.csv

SHA-256: `4c8252a0b2b373e34515ed196f5ca083025ae03075a64aa0753caf282aa5533d`

| rows | kind_rate | kind_rate_pct | binomial_se_pp |
|---|---|---|---|
| 3043249 | 0.0357634225789608 | 3.57634225789608 | 0.0106449247124492 |
| 2919470 | 0.0239087916642404 | 2.39087916642404 | 0.00894070995024359 |
| 9244704 | 0.0260500498447544 | 2.60500498447544 | 0.00523873094289294 |
| 3662090 | 0.0120346578046962 | 1.20346578046962 | 0.00569801018531262 |
| 22664818 | 0.00470138343930227 | 0.470138343930227 | 0.00143685657223468 |

5 records in the exact extract; 6 fields in its first row.

## results/wave1/modules/core_stage08/tables/table09_second_half_by_first_half_behavior.csv

SHA-256: `e88d131bf3594ed6975acf8be6a1606c912eb768e0a97d992704637a34b87aea`

| choosers | second_half_kind_rate_pct |
|---|---|
| 920820 | 0.907222534295989 |
| 85535 | 17.8611539317737 |
| 603597 | 0.938282609906797 |
| 62534 | 15.8237090421808 |

4 records in the exact extract; 9 fields in its first row.

## results/wave1/modules/core_stage08/tables/tableA01_split_half_full_statistics.csv

SHA-256: `b5d6f1d5ae0b40e8530b92a27e10890c4d54695f0b8d76fb5528ae03a6659a53`

| choosers | pearson_unweighted | pearson_weighted_total_opportunities | pearson_weighted_harmonic_half_opportunities |
|---|---|---|---|
| 1365368 | 0.497497692183602 | 0.63521540359832 | 0.643477242316863 |
| 1006355 | 0.600417129508345 | 0.689785612795246 | 0.702741045451666 |
| 861419 | 0.644488506039055 | 0.71643256342033 | 0.728395709342156 |
| 447778 | 0.775307607325314 | 0.803998884479816 | 0.808671501718379 |
| 793363 | 0.484370288712089 | 0.593522701590548 | 0.615869704509472 |
| 666131 | 0.545303390638795 | 0.617820265785493 | 0.646977504238847 |
| 602695 | 0.570348884958054 | 0.630945509153381 | 0.662078138195367 |
| 367719 | 0.662671658065292 | 0.689232094102932 | 0.721576162373819 |

8 records in the exact extract; 9 fields in its first row.

## results/wave1/modules/rating_gap_nonparametric/common_support_chooser_equal_differences.parquet

SHA-256: `1c55133255f0203e89a4fbafb10105f1560f11a0234b1a31d1366a1a13cc6c12`

| eval_band | choosers | equal_rows | side_rows | se_pp |
|---|---|---|---|---|
| m100_p100 | 25527 | 126931 | 28511 | 0.08128020683598774 |
| m100_p100 | 22466 | 115108 | 24315 | 0.10042096774662425 |
| p100_p300 | 8257 | 25262 | 8669 | 0.15735543069696664 |
| p100_p300 | 9650 | 29455 | 10175 | 0.16105437222626853 |
| p300_p600 | 6890 | 20967 | 7141 | 0.20256499175954637 |
| p300_p600 | 9160 | 26799 | 9737 | 0.18223540064799473 |

6 records in the exact extract; 7 fields in its first row.

## results/wave1/modules/rating_gap_nonparametric/fe_nonparametric_curves.parquet

SHA-256: `9d668aac74011e4eb384d599721c07b277dbafccd6228a3bba189f636b84bdf4`

| model_id | term | se_pp | gap_bin50 | gap_mid |
|---|---|---|---|---|
| k50__ply_gt_10__m100_p100 | gap_m11 | 0.5092032022560828 | -11 | -550.0 |
| k50__ply_gt_10__m100_p100 | gap_m10 | 0.586923635761306 | -10 | -500.0 |
| k50__ply_gt_10__m100_p100 | gap_m9 | 0.5611996035271283 | -9 | -450.0 |
| k50__ply_gt_10__m100_p100 | gap_m8 | 0.5949693459840387 | -8 | -400.0 |
| k50__ply_gt_10__m100_p100 | gap_m7 | 0.3636373979245914 | -7 | -350.0 |
| k50__ply_gt_10__m100_p100 | gap_m6 | 0.36270901149540963 | -6 | -300.0 |
| k50__ply_gt_10__m100_p100 | gap_m5 | 0.2222562536089859 | -5 | -250.0 |
| k50__ply_gt_10__m100_p100 | gap_m4 | 0.13950259028505257 | -4 | -200.0 |
| k50__ply_gt_10__m100_p100 | gap_m3 | 0.043889677010586506 | -3 | -150.0 |
| k50__ply_gt_10__m100_p100 | gap_m2 | 0.023502988960923635 | -2 | -100.0 |
| k50__ply_gt_10__m100_p100 | gap_m1 | 0.014808318725067311 | -1 | -50.0 |
| k50__ply_gt_10__m100_p100 | gap_0 | 0.0 | 0 | 0.0 |
| k50__ply_gt_10__m100_p100 | gap_p1 | 0.015623778723002399 | 1 | 50.0 |
| k50__ply_gt_10__m100_p100 | gap_p2 | 0.026706749223655523 | 2 | 100.0 |
| k50__ply_gt_10__m100_p100 | gap_p3 | 0.05641697041719166 | 3 | 150.0 |
| k50__ply_gt_10__m100_p100 | gap_p4 | 0.17359880259843782 | 4 | 200.0 |
| k50__ply_gt_10__m100_p100 | gap_p5 | 0.32271173730500335 | 5 | 250.0 |
| k50__ply_gt_10__m100_p100 | gap_p6 | 0.3402464553965331 | 6 | 300.0 |
| k50__ply_gt_10__m100_p100 | gap_p7 | 0.5564963042498916 | 7 | 350.0 |
| k50__ply_gt_10__m100_p100 | gap_p8 | 0.7494773639035576 | 8 | 400.0 |
| k50__ply_gt_10__m100_p100 | gap_p9 | 0.7527814337413324 | 9 | 450.0 |
| k50__ply_gt_10__m100_p100 | gap_p10 | 0.8680886887047727 | 10 | 500.0 |
| k50__ply_gt_10__m100_p100 | gap_p11 | 1.031829097127789 | 11 | 550.0 |
| k50__ply_gt_10__p100_p300 | gap_m11 | 0.9404807112942837 | -11 | -550.0 |

621 records in the exact extract; 10 fields in its first row.

## results/wave2a/modules/crossing_default_audit/tables/controlled_local_crossing_coefficients.csv

SHA-256: `375676a2f0528b3c36e75c785f71c8cfaae445482cb8769ffc94ef1fa6f1334a`

| specification | term | estimate |
|---|---|---|
| baseline_all | left | 0.324711772362441 |
| baseline_all | right | -0.167191273291115 |
| baseline_all | jump | 0.0544154421001233 |
| baseline_all | tie | 0.142531169666606 |
| split_exact_zero_1500_rd | left | 0.324556121074671 |
| split_exact_zero_1500_rd | right | -0.167366179755961 |
| split_exact_zero_1500_rd | jump | 0.0544107306348156 |
| split_exact_zero_1500_rd | tie_1500_any_high_rd | -0.684900740958708 |
| split_exact_zero_1500_rd | tie_1500_neither_high_rd | 1.65376811904808 |
| split_exact_zero_1500_rd | tie_non1500 | 0.141635857405015 |
| exclude_both_1500 | left | 0.329212476605413 |
| exclude_both_1500 | right | -0.162235825293036 |
| exclude_both_1500 | jump | 0.0545230706903745 |
| exclude_both_1500 | tie | 0.14185319302847 |
| both_established_nondefault | left | 0.357119699852269 |
| both_established_nondefault | right | -0.0980064500272211 |
| both_established_nondefault | jump | 0.0508105161390455 |
| both_established_nondefault | tie | 0.139835075299545 |

18 records in the exact extract; 4 fields in its first row.

## results/wave2a/modules/crossing_default_audit/tables/controlled_local_crossing_contrasts.csv

SHA-256: `6f610a2d856240a7511e81c23e886d0b778b24b7fb0f1720c22f840e6ab0fdc1`

| specification | estimand | estimate_pp | se_pp | p_value_two_sided | rows |
|---|---|---|---|---|---|
| baseline_all | loss_side_slope | 0.324711772362441 | 0.112717663602358 | 0.00396726130436042 | 10116759 |
| baseline_all | gain_side_slope | -0.167191273291115 | 0.112471395251754 | 0.137140937923974 | 10116759 |
| baseline_all | loss_minus_gain_slope | 0.491903045653556 | 0.0763149929053867 | 1.15073086361868e-10 | 10116759 |
| baseline_all | right_minus_left_level | 0.0544154421001233 | 0.0207145332072633 | 0.00861613372988228 | 10116759 |
| baseline_all | exact_zero_minus_left_limit | 0.142531169666606 | 0.0353064472898688 | 5.41453287339151e-05 | 10116759 |
| baseline_all | exact_zero_minus_right_limit | 0.0881157275664828 | 0.0354146805615547 | 0.0128422916531472 | 10116759 |
| split_exact_zero_1500_rd | loss_side_slope | 0.324556121074671 | 0.112713178450073 | 0.00398322842609277 | 10116759 |
| split_exact_zero_1500_rd | gain_side_slope | -0.167366179755961 | 0.112467036589369 | 0.136715186411468 | 10116759 |
| split_exact_zero_1500_rd | loss_minus_gain_slope | 0.491922300830632 | 0.0763150664491926 | 1.14886491893755e-10 | 10116759 |
| split_exact_zero_1500_rd | right_minus_left_level | 0.0544107306348156 | 0.0207145268318841 | 0.00862187400658319 | 10116759 |
| split_exact_zero_1500_rd | 1500_any_high_rd_minus_left_limit | -0.684900740958708 | 1.2254361271968 | 0.576227468997245 | 10116759 |
| split_exact_zero_1500_rd | 1500_any_high_rd_minus_right_limit | -0.739311471593524 | 1.22556603898008 | 0.546348490863728 | 10116759 |
| split_exact_zero_1500_rd | 1500_neither_high_rd_minus_left_limit | 1.65376811904808 | 1.1406862529525 | 0.147114008650325 | 10116759 |
| split_exact_zero_1500_rd | 1500_neither_high_rd_minus_right_limit | 1.59935738841327 | 1.14068737790769 | 0.160885487636829 | 10116759 |
| split_exact_zero_1500_rd | non1500_minus_left_limit | 0.141635857405015 | 0.0353197489239566 | 6.06920753175145e-05 | 10116759 |
| split_exact_zero_1500_rd | non1500_minus_right_limit | 0.0872251267701998 | 0.0354239959611986 | 0.0138042388347701 | 10116759 |
| split_exact_zero_1500_rd | 1500_any_high_rd_minus_non1500_exact_zero | -0.826536598363724 | 1.22587913726605 | 0.500158821265727 | 10116759 |
| split_exact_zero_1500_rd | 1500_neither_high_rd_minus_non1500_exact_zero | 1.51213226164307 | 1.14081130515386 | 0.185009182343386 | 10116759 |
| exclude_both_1500 | loss_side_slope | 0.329212476605413 | 0.112683871545044 | 0.0034828531905025 | 10116025 |
| exclude_both_1500 | gain_side_slope | -0.162235825293036 | 0.112419644948193 | 0.148984697878097 | 10116025 |
| exclude_both_1500 | loss_minus_gain_slope | 0.491448301898449 | 0.0763129649788504 | 1.19547715004132e-10 | 10116025 |
| exclude_both_1500 | right_minus_left_level | 0.0545230706903745 | 0.0207141746302762 | 0.00848433079445588 | 10116025 |
| exclude_both_1500 | exact_zero_minus_left_limit | 0.14185319302847 | 0.0353211090915455 | 5.91685402497167e-05 | 10116025 |
| exclude_both_1500 | exact_zero_minus_right_limit | 0.0873301223380953 | 0.0354255713092745 | 0.0136947539343332 | 10116025 |

30 records in the exact extract; 12 fields in its first row.

## results/wave2a/modules/crossing_default_audit/tables/displayed_gap_m12_p12_schedule.csv

SHA-256: `cdd643df5c0e0b5dfbdbd0afd68356fe5c775205a29869b4a9bbfac2bae5d759`

| estimate_pp | se_pp | p_value_two_sided | p_value_holm_24 | target_rows | reference_rows | rows |
|---|---|---|---|---|---|---|
| -0.0804738471578545 | 0.0908967643414866 | 0.375977400156383 | 1 | 136317 | 182158 | 318475 |
| -0.0149454631226634 | 0.0881514401270067 | 0.865369521468476 | 1 | 140356 | 182158 | 322514 |
| -0.132946666202956 | 0.0859095163727857 | 0.121737985702513 | 1 | 143481 | 182158 | 325639 |
| -0.110901186302294 | 0.0906504834304773 | 0.22118121508096 | 1 | 147622 | 182158 | 329780 |
| -0.0587956278306942 | 0.086747373268529 | 0.497911243676492 | 1 | 151547 | 182158 | 333705 |
| -0.0799094390991025 | 0.0853577474021199 | 0.34918520399046 | 1 | 155084 | 182158 | 337242 |
| -0.122738177105429 | 0.0852660751603637 | 0.150016673675999 | 1 | 160729 | 182158 | 342887 |
| 0.0235560162678147 | 0.0830736346023481 | 0.776750764380776 | 1 | 162708 | 182158 | 344866 |
| 0.00899677964358159 | 0.0841120410493907 | 0.914819244176303 | 1 | 168073 | 182158 | 350231 |
| -0.027841200130266 | 0.0816075291160267 | 0.732983360176962 | 1 | 172082 | 182158 | 354240 |
| 0.0839689141027655 | 0.0839948805606816 | 0.317460138263861 | 1 | 176968 | 182158 | 359126 |
| 0 |  |  |  | 182158 | 182158 | 182158 |
| -0.0239234514561756 | 0.0734901053013825 | 0.744777741925872 | 1 | 227407 | 182158 | 409565 |
| -0.00828427192184553 | 0.0784851160308662 | 0.915937699615897 | 1 | 181543 | 182158 | 363701 |
| -0.0570485929347937 | 0.0823191630203308 | 0.488298779857292 | 1 | 177433 | 182158 | 359591 |
| 0.050719099623118 | 0.0842613090718737 | 0.547223183985963 | 1 | 172918 | 182158 | 355076 |
| -0.108501806312997 | 0.0840300134271517 | 0.196625040596059 | 1 | 167904 | 182158 | 350062 |
| 0.0851869456152499 | 0.0863533273636242 | 0.323891290357488 | 1 | 163378 | 182158 | 345536 |
| 0.0391050547936616 | 0.0846776601044988 | 0.644217032085321 | 1 | 159698 | 182158 | 341856 |
| 0.0248785157307504 | 0.086648236124031 | 0.774019783385082 | 1 | 155700 | 182158 | 337858 |
| 0.251400512994298 | 0.0893055045258695 | 0.00487678569166621 | 0.117042856599989 | 152093 | 182158 | 334251 |
| 0.067140170289771 | 0.091342228714876 | 0.462315277049837 | 1 | 148123 | 182158 | 330281 |
| 0.0461165981087367 | 0.0915845028226166 | 0.614583609099798 | 1 | 143980 | 182158 | 326138 |
| -0.0277964367002853 | 0.0912780705480136 | 0.760728097333607 | 1 | 139790 | 182158 | 321948 |

25 records in the exact extract; 13 fields in its first row.

## results/wave2a/modules/crossing_default_audit/tables/exact_zero_1500_rd_decomposition.csv

SHA-256: `bfe80dbac9dc79659ee8b71efeeede32adf591742a680cef0f85d59b106bb5cc`

| rows | kind_rate_pct |
|---|---|
| 227407 | 2.84467936343208 |
| 2315 | 5.65874730021598 |
| 0 |  |
| 225092 | 2.8157375650845 |
| 2078 | 6.20789220404235 |
| 7493 | 3.77685840117443 |
| 217836 | 2.78053214344736 |
| 1812 | 6.34657836644592 |
| 255 | 1.96078431372549 |
| 248 | 4.43548387096774 |
| 266 | 5.26315789473684 |
| 7238 | 3.84084001105278 |
| 217588 | 2.77864588120668 |

13 records in the exact extract; 7 fields in its first row.

## results/wave2a/modules/crossing_default_audit/tables/joint_adjacent_gap_models.csv

SHA-256: `a93777276fc5bd1f2ab91959a58780e513a7bfbf80484e8be1f02552a81b2ff2`

| model | term | estimate_pp | se_pp | p_value_two_sided | rows |
|---|---|---|---|---|---|
| joint_gap_m1_0_p1__all__all | gap_0_minus_gap_m1 | 0.011690864722979 | 0.0659464214279749 | 0.859289851592076 | 591108 |
| joint_gap_m1_0_p1__all__all | gap_p1_minus_gap_m1 | -0.0307939884119039 | 0.0687518897859816 | 0.654225190179331 | 591108 |
| joint_gap_m1_0_p1__long_ply_gt_10__all | gap_0_minus_gap_m1 | 0.0646714843021001 | 0.0734611288622215 | 0.378669885039996 | 456191 |
| joint_gap_m1_0_p1__long_ply_gt_10__all | gap_p1_minus_gap_m1 | 0.00689096830541863 | 0.0776602554919812 | 0.929294711032435 | 456191 |
| joint_gap_m1_0_p1__all__exclude_both_1500 | gap_0_minus_gap_m1 | 0.00862027857713756 | 0.0659191591005403 | 0.895956893965671 | 588793 |
| joint_gap_m1_0_p1__all__exclude_both_1500 | gap_p1_minus_gap_m1 | -0.0268664455633962 | 0.0687300319214823 | 0.695872486680297 | 588793 |
| joint_gap_m1_0_p1__long_ply_gt_10__exclude_both_1500 | gap_0_minus_gap_m1 | 0.0642696728480167 | 0.0734797774430582 | 0.381760036430421 | 454925 |
| joint_gap_m1_0_p1__long_ply_gt_10__exclude_both_1500 | gap_p1_minus_gap_m1 | 0.0076411606230288 | 0.077670822596405 | 0.921631525527419 | 454925 |
| joint_gap_m1_0_p1__all__both_established_nondefault | gap_0_minus_gap_m1 | -0.00451988567576984 | 0.0669387696374564 | 0.946165600609342 | 566712 |
| joint_gap_m1_0_p1__all__both_established_nondefault | gap_p1_minus_gap_m1 | -0.0366232392300388 | 0.0696172129451787 | 0.598842445844296 | 566712 |
| joint_gap_m1_0_p1__long_ply_gt_10__both_established_nondefault | gap_0_minus_gap_m1 | 0.0580133842498894 | 0.0746935104009458 | 0.437344203258714 | 439425 |
| joint_gap_m1_0_p1__long_ply_gt_10__both_established_nondefault | gap_p1_minus_gap_m1 | 0.00194943281100367 | 0.0788489327992626 | 0.980275397006855 | 439425 |

12 records in the exact extract; 11 fields in its first row.

## results/wave2a/modules/crossing_default_audit/tables/model_support.csv

SHA-256: `c09b5e44f9f244492227f11bbe6bc8b03d28d3534123778b04e2ace70f8985f9`

| model | rows | gap_m1_rows | gap_0_rows | gap_p1_rows | specification | dropped_terms |
|---|---|---|---|---|---|---|
| joint_gap_m1_0_p1__all__all | 591108 | 182158 | 227407 | 181543 |  |  |
| joint_gap_m1_0_p1__long_ply_gt_10__all | 456191 | 140649 | 175380 | 140162 |  |  |
| joint_gap_m1_0_p1__all__exclude_both_1500 | 588793 | 182158 | 225092 | 181543 |  |  |
| joint_gap_m1_0_p1__long_ply_gt_10__exclude_both_1500 | 454925 | 140649 | 174114 | 140162 |  |  |
| joint_gap_m1_0_p1__all__both_established_nondefault | 566712 | 174841 | 217588 | 174283 |  |  |
| joint_gap_m1_0_p1__long_ply_gt_10__both_established_nondefault | 439425 | 135477 | 168847 | 135101 |  |  |
|  | 10116759 |  |  |  | baseline_all | ['gap_hinge_m600', 'gap_hinge_m400', 'gap_hinge_m250', 'gap_hinge_p250', 'gap_hinge_p400', 'gap_hinge_p600', 'gap_below_m800', 'gap_above_p800', 'expected_imbalance_hinge_m0p75', 'expected_imbalance_hinge_m0p5', 'expecte |
|  | 10116759 |  |  |  | split_exact_zero_1500_rd | ['gap_hinge_m600', 'gap_hinge_m400', 'gap_hinge_m250', 'gap_hinge_p250', 'gap_hinge_p400', 'gap_hinge_p600', 'gap_below_m800', 'gap_above_p800', 'expected_imbalance_hinge_m0p75', 'expected_imbalance_hinge_m0p5', 'expecte |
|  | 10116025 |  |  |  | exclude_both_1500 | ['gap_hinge_m600', 'gap_hinge_m400', 'gap_hinge_m250', 'gap_hinge_p250', 'gap_hinge_p400', 'gap_hinge_p600', 'gap_below_m800', 'gap_above_p800', 'expected_imbalance_hinge_m0p75', 'expected_imbalance_hinge_m0p5', 'expecte |
|  | 9620080 |  |  |  | both_established_nondefault | ['gap_hinge_m600', 'gap_hinge_m400', 'gap_hinge_m250', 'gap_hinge_m150', 'gap_hinge_m100', 'gap_hinge_p100', 'gap_hinge_p150', 'gap_hinge_p250', 'gap_hinge_p400', 'gap_hinge_p600', 'gap_below_m800', 'gap_above_p800', 'ex |

10 records in the exact extract; 15 fields in its first row.

## results/wave2a/modules/equality_fen/tables/equality_fe_models.csv

SHA-256: `84e1e8a3b30b7b5d0cbd739a5004b00ef8b2d7812141c8b1163dd5e8dd8f364d`

| model_id | sample | coefficient_pp | se_pp | p_normal_approx | rows_raw | rows_identifying | absorption_max_scaled_group_mean |
|---|---|---|---|---|---|---|---|
| E0_raw | all_equal_or_better | 0.21412581805139297 | 0.010961678911691948 | 5.640205017844514e-85 | 12164174 | 12164174 | 0.0 |
| E1_chooser_fe | all_equal_or_better | 0.0662615761452881 | 0.009224604107184725 | 6.813079079173932e-13 | 12164174 | 9743927 | 1.4315373647139013e-15 |
| E2_primary_modern_analogue | all_equal_or_better | -0.016130329097723994 | 0.00924919441592643 | 0.08116410411313046 | 12164174 | 12164174 | 8.213131202408284e-09 |
| E3_price_adjusted | all_equal_or_better | -0.010694378424922102 | 0.009247351653747023 | 0.24748482323824247 | 12164174 | 12164174 | 8.213131202408284e-09 |
| E4_game_stage_adjusted | all_equal_or_better | -0.40039199318510665 | 0.009437342660859303 | 0.0 | 12164174 | 12164174 | 8.213131202408284e-09 |
| E5_short_interaction | all_equal_or_better | -0.3832537544216563 | 0.009791020714905542 | 0.0 | 12164174 | 12164174 | 8.213131202408284e-09 |
| E5_short_interaction | all_equal_or_better | 0.6641741767931393 | 0.03135087190405548 | 1.3079719297829191e-99 | 12164174 | 12164174 | 8.213131202408284e-09 |
| E6_short_only | E6_short_only | 0.21908789713749457 | 0.033800432034900026 | 9.063017013548334e-11 | 3571912 | 3571912 | 9.482708373922853e-09 |
| E7_long_only | E7_long_only | -0.37160745499717984 | 0.009843391443409734 | 6.981473149943e-312 | 8592262 | 8592262 | 9.10865016081016e-09 |
| E8_first_half | E8_first_half | -0.0011972184823570153 | 0.013302106267655335 | 0.9282854872702434 | 5982741 | 5982741 | 9.552655996041503e-09 |
| E8_second_half | E8_second_half | -0.027778961587902176 | 0.013151298182029671 | 0.03466415152027525 | 6181433 | 6181433 | 9.815045940452825e-09 |
| E9_speed_0 | E9_speed_0 | 0.03854831411357111 | 0.031661577788374175 | 0.22340991528950163 | 1452552 | 1452552 | 3.3984664801503427e-09 |
| E9_speed_1 | E9_speed_1 | -0.012296559123320103 | 0.0117022279073618 | 0.29335602863350463 | 7100822 | 7100822 | 3.3926237178403835e-09 |
| E9_speed_2 | E9_speed_2 | -0.06655760279221706 | 0.018048952399891006 | 0.00022636505078139053 | 3471685 | 3471685 | 7.818121426434662e-09 |
| E9_speed_3 | E9_speed_3 | -0.2141827813176422 | 0.11227875137614393 | 0.056443125011980365 | 139115 | 139115 | 8.218757322166577e-09 |

15 records in the exact extract; 17 fields in its first row.

## results/wave2b1/results/a1_unconditional/results/unconditional_first_opportunity.csv

SHA-256: `75564ebc00e0479b1bcf0378a57a68ea103b487142e5d309279bbc6bf39a8d8b`

| estimand | state_conditioned | rows | treated_rows | control_rows | coefficient | p_value_raw | weighted_treated_mean | weighted_control_mean | effect_relative_to_control_mean | coefficient_percentage_points | sample_specification_sha256 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| post_result_unconditional_first_opportunity_zero_nonreacher | False | 2110400 | 62237 | 2048163 | 0.0039924237579717905 | 4.146875299321257e-12 | 0.02024519176695535 | 0.015641973845999423 | 0.25523784896193835 | 0.399242375797179 | cccd800ed3f229df41d38e09364242acd2ae4353d377c65d676964a1da83c0dd |

1 records in the exact extract; 35 fields in its first row.

## results/wave2b1/results/dynamic_core/results/a1_primary_and_companions.csv

SHA-256: `f2023290b3e76e87470b054048cf1b222b38ed63fe803f56a0515cd0c8561921`

| estimand | state_conditioned | rows | treated_rows | control_rows | coefficient | p_value_raw | weighted_treated_mean | weighted_control_mean | effect_relative_to_control_mean | coefficient_percentage_points | sample_specification_sha256 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| primary_total_path_conditional_choice | False | 993762 | 28729 | 965033 | 0.008816583609166886 | 5.894375563666858e-13 | 0.043858122454662536 | 0.033307678448130366 | 0.26470123466866186 | 0.8816583609166886 | d4607e746d1f78fa334bd247fddf2311807195bfd9952dfe4dbf90bd88c8e7c9 |
| mandatory_state_conditioned_conditional_choice | True | 993762 | 28729 | 965033 | 0.008983146502187364 | 2.204657434690609e-13 | 0.043858122454662536 | 0.033307678448130366 | 0.26970197025820053 | 0.8983146502187364 | 430900fc0d7e6a008c8bcbb778c9a3a3b51544770b12d44f96e5e9caf15fa6b3 |
| mandatory_reach_companion | False | 2110400 | 62237 | 2048163 | -0.0019733051710519667 | 0.3095060659114585 | 0.4616064398990954 | 0.4696206573015431 | -0.004201913055508775 | -0.19733051710519667 | 26ef743c66905ced40a060326786cd0b47a512e089092287fdfcaefb7b9ea6e0 |
| mandatory_unconditional_kind_companion | False | 2110400 | 62237 | 2048163 | 0.004684507610103043 | 5.686596516170824e-11 | 0.0316371290389961 | 0.025898869806027635 | 0.18087691259071015 | 0.4684507610103043 | 4f4c86099a3874be100c4d924af8ad346cc736ef861eddeffb7b533107de0533 |
| natural_path_crossover_count | False | 2110400 | 62237 | 2048163 | 0.0016479502961242413 | 0.11365251135689164 | 0.05451740925815833 | 0.05109889118333114 | 0.032250216354240885 |  | 3a5e12ddaa56a2440a77f38d242642bb07806649b9fb291370c55920a2dc68af |

5 records in the exact extract; 29 fields in its first row.
