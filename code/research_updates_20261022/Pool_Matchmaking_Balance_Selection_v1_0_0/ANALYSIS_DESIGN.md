# Fixed exploratory analysis design

## 1. Question and unit

Unit: one game in the frozen, randomly oriented pool-game comparison frame. The column `recipient_id` names the original random focal player. It does **not** name the eventual disconnector, the eventual recipient of a kind draw, or a player selected because a timeout occurred. The inherited rebuild retained this orientation while joining the new main-sample roles.

Exposure: `gap = (opponent_rating - recipient_rating) / 100`. Positive means a stronger displayed-rating opponent. Focal rating is held fixed by the specified controls. A slope therefore describes a +100-point difference in opponent strength at fixed focal strength, within the model's observed environment. It does not isolate an opponent's rating from every other opponent characteristic.

All models use one weight per sampled game. They do not select on later kindness, on availability of an opponent leniency estimate, or on an IV score-history floor. The sample is inherited, so representativeness beyond its sampling frame is not established by this audit. In particular, do not infer the pool population distribution from unweighted frame counts without the original inclusion probabilities.

## 2. Pre-game baseline outcomes

The inherited comparison producer computed focal histories using the original all-source Stage07 opportunity histories. For a focal start at t, it includes prior fair-opportunity decision timestamps in **[t − 97 days, t − 7 days)**: a 90-day window with a seven-day buffer. It does not truncate historical experience to the new pool/nonadjacent analysis sample.

Calendar completeness is `t − 97 days >= 2023-11-01 00:00:00 UTC`. This is observation-window completeness, not a claim to observe the account's lifetime. The primary history-complete frame retains players with zero observed prior fair opportunities. It never codes an undefined prior rate as zero.

Three primary baseline outcomes:

1. `has_prior_fair`: at least one observed prior fair chooser opportunity in that window.
2. `log_prior_fair`: log(1 + number of those opportunities), a history-exposure measure; not total chess activity.
3. `prior_kind_ever`: at least one kind grant among those opportunities in that window; not lifetime kindness.

Two companion models use `own_kind90 / own_fair90` among players with at least one or at least five prior fair opportunities. These have different selected-history populations and are not substitutes for the primary balance panel. Identity-lookup status counts and duplicate historical-count-field disagreements are reported. A zero records no observed event in these histories; it is not an estimated latent propensity of zero.

Regressing these baseline outcomes on the subsequently realized gap tests observable sorting. Conditioning on final board state, game length, the timeout role, or a future kindness response would not be an admissible way to establish pre-assignment balance; these are excluded from the baseline specification.

## 3. Selection outcomes and exact decompositions

On the same regression rows, estimate these binary outcomes:

| Field | Meaning |
|---|---|
| active_timeout | Recorded API status `timeout` |
| passive_outoftime | Recorded API status `outoftime` |
| any_candidate | Sum of the two mutually exclusive status flags |
| recipient_disconnect_main | Focal player is the disconnector in a certified new-main opportunity |
| recipient_chooser_main | Focal player is the chooser in a certified new-main opportunity |
| active_other_role_or_screen | Active timeout minus the two main-role flags |
| recipient_fair_arm_main | Focal is the main disconnector in the inherited fair kind-draw/chooser-win arm |
| actual_iv_exposure | Focal and opponent match the rebuilt IV exposure |

API ending categories and certified opportunity roles are distinct. The residual category accounts for active endings not entering the two main-role flags. The aggregate report must retain it rather than forcing all active endings into certified roles. These flags do not directly measure deliberate waits, a common five-second floor, or current-game grants.

The identities `candidate = active + passive` and `active = focal disconnector + focal chooser + residual` hold both for raw counts and for coefficients when all terms use the same model rows and regressors. The runner checks the coefficient identities. It does not compare separately selected regressions as if this algebra still held.

The `active_given_candidate` model conditions separately on `timeout` or `outoftime`. It measures composition within this selected subset. It is a post-assignment diagnostic, not a pre-assignment balance test. The fair-arm and IV-exposure outcomes are progressively selected endpoints; a slope in either is not automatically a behavioral effect of opponent strength.

## 4. Specifications fixed before reading these diagnostic outcomes

Every model includes continuous focal rating, its square and cube (center 1500, scale 500), after absorbing its fixed effects. Collinear continuous controls are dropped by the inherited rank rule, and the retained rank is reported. No results-driven retry or bandwidth selection is implemented.

The **coarse environment** absorbs month × exact clock × 50-point displayed focal-rating bin, UTC start date, and UTC hour of week. The **local environment** instead absorbs the fully interacted start-time bin × exact clock × 50-point focal-rating bin. Exact clock uses both initial seconds and increment seconds; it is not a bullet/blitz label. The within-focal companion adds focal account effects to the coarse environment.

| Specification | Frame and environment | Outcomes/purpose |
|---|---|---|
| coarse_context | Nonadjacent, complete baseline; coarse | Baseline balance + selection |
| local5_primary | Same frame; five-minute local cells | Primary diagnostic; baseline balance + selection |
| local1_sensitivity | Same frame; one-minute local cells | Narrower environment/support check |
| local15_sensitivity | Same frame; fifteen-minute local cells | Broader environment/support check |
| within_focal_sensitivity | Same frame; coarse + focal effects | Within-person companion |
| history_adjusted_selection | Same frame; coarse + the three baseline controls | Whether selection slopes persist after those histories |
| nonlinear_gap_sensitivity | Same frame; coarse, gap/absolute-gap/squared-gap | Nonlinear baseline and selection checks |
| all_dates_nonadj_selection | Nonadjacent, all observed dates; coarse | Avoids calendar-history truncation for selection |
| active_given_candidate | Nonadjacent, complete baseline, candidate endings; coarse | Active vs passive and role composition |
| pool_parent_context | Parent pool frame, complete baseline; coarse | Baseline balance, adjacency retention, ending categories |
| prior_rate_floor1 | Nonadjacent, complete baseline, ≥1 prior fair opportunity; coarse | Prior-kindness rate companion |
| prior_rate_floor5 | Same but ≥5 opportunities | More observed history, more selected population |

The parent frame's `eligible_main` outcome includes all reasons for failing observed nonadjacency, including unresolved classifications. It is not a pure treatment of repeat pairing. Its contextual results use a different population from the restricted models.

There is no automatic promotion of a coarser model if the primary lacks support. The support inventory enumerates 1/5/15-minute cells and 25/50/100-point rating bins, outcome blind. Only the 50-point rating cells enter the fixed models; the other widths show how much support the design could have, not additional fitted specifications.

## 5. Support and inference

The model needs at least 500 rows with non-negligible residual gap variation and 30 identifying UTC dates. These are numerical screening rules, not a guarantee of adequate effective sample size. The report also gives raw cell singleton counts, varying-gap cell counts, model N, identifying-row counts, residual gap SD, identifying dates, the largest date's identifying-row share, an effective date count based on those shares, and account counts.

Standard errors use the inherited shared-account **OR** start-date covariance rule: dependence is allowed when two rows share either player, or a start date. Inclusion–exclusion removes double-counting of shared pairs and dates. The multivariate extension is tested against explicit pairwise covariance sums. All reported covariances are CR0, with normal/chi-square reference inference and no finite-cluster or PSD repair. Singular or nonpositive covariance yields an unsupported inference flag. Point estimates can still be retained; inspect the inference flags.

The joint baseline test tests the three gap coefficients together using their cross-outcome covariance. It does not test all unobserved attributes. Individual p values are exploratory and unadjusted. No new entry is made in the manuscript's confirmatory families or family-D Holm reconciliation.

Linear balance slopes are reported in raw outcome units and unconditional outcome SD on that model sample. Selection slopes are reported in probability units and percentage points, per +100 rating points. For the prior rate, a raw slope of .01 is one percentage point of prior kindness probability. The nonlinear basis reports contrasts for +100 vs zero, −100 vs zero, and +100 vs −100, with the full off-diagonal covariance. These are fitted contrasts, not literal treatment assignments.

A prespecified descriptive tolerance of ±0.05 outcome SD per +100 points is accompanied by a 90% confidence interval and two one-sided equivalence p value in linear balance models. It was fixed for this exploratory diagnostic after the broader research results were already known. It does not become confirmatory by being encoded in this package, and it is not a universal threshold for acceptable omitted-variable bias. A nonsignificant zero test is not evidence of equivalence.

## 6. What this can change in the paper

If narrow-cell balance is precise and within-focal results agree, describe the pool restriction as an institutional design restriction whose observable implications survive those particular diagnostics. Report the covariates, conditioning variables, precision and retained support. If balance fails, identify which pre-game attributes remain sorted. If support is thin, report that limitation rather than treating a large p value as success.

Selection on gap needs its own result. Even exogenous opponent assignment would not generally identify a causal kindness response conditional on realized evaluation and active disconnection, because both arise after assignment. The chosen opponent can affect game evolution, duration and who disconnects. The current main sample also applies an adjacency restriction. Observable balance does not remove all these pathways.

The historical matchmaker audit found inputs beyond displayed rating and time, including conduct-related matching, preferences/blocks, special classes, waiting-wave effects, and internal/provisional-rating mechanisms. Their presence is the reason to audit rather than assume conditional randomization. This runner does not observe those inputs, infer queue waits from game starts, or reconstruct risk sets for exact randomization inference. The dated source audit is in the previously supplied `Pool_Matchmaking_Audit_v1_0_0` package; repository dates do not certify deployment dates.

Current-game grant incidence in the broader game frame and a reestimated conditional kindness surface would be distinct next analyses. This comparison file does not contain a current-game kind-grant flag; its `y` refers to a later outcome and is deliberately not read. This package never substitutes that later outcome for the current grant. No causal conclusion or new manuscript coefficient should be written before reviewing the returned audit results.

## 7. Output scope and reproducibility

New outputs contain aggregates, coefficients, covariance matrices, support summaries, authenticated input identifiers and explicit statuses. Account/game identifiers and username columns are not exported. The runner loads necessary numeric identifiers for joins/covariance and game IDs solely for uniqueness, then excludes them from report payloads. Export uses a fixed whitelist and an internal SHA-256 manifest; each result ZIP has its own sidecar.

All successful specification checkpoints are content-hashed and tied to the design, package manifest, source authority and numerical-library versions. Only the new private state and Desktop results are written. Older authority files, previous waves, active trajectory jobs, and the manuscript remain unchanged.
