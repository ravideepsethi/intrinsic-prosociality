# Frozen implementation decisions

**Version 1.0.1 correction:** the original design below is retained. REPAIR_NOTES.md documents the physical-fragment aggregation bug, its consequences for all B estimates, the adjusted-score aggregation correction, and the S0/logit repairs. These implementation corrections do not change the frozen state/year definitions or estimands.

Prepared 12 October 2026 UTC for the supplied A–F handoff. These decisions are recorded before running the new empirical models. Synthetic validation is not empirical estimation. The original handoff is preserved verbatim in HANDOFF_SPEC.md; this note documents operational clarifications and corrections.

## Shared sample and provenance

The reviewed pool/nonadjacent panel is exactly the existing 24 monthly files totaling 41,534,331 rows before author exclusions. Their source hashes, schemas, engine orientation, requested 100,000 nodes, timeout/clock/rated/standard conditions and within-month game uniqueness are checked. Analyses use the author's two exclusions on either side before aggregation, reference-cell calculation, P1 classification, nuisance training or new estimating samples. Counts are refreshed. Existing original-sample results are used only for labeled reproduction/provenance checks.

The fixed years are the supplied archive-month blocks, Nov 2023–Oct 2024 and Nov 2024–Oct 2025. They are not account-specific halves. State membership uses the original disconnected-side signed evaluation/mate mapping. Only evaluated finite positions and mapped mates are classified. Reconstructed payoff, premium and displayed-rating gap must be finite; the premium must be positive. Clock missingness gets the specified indicators. RD/premium nuisance control construction also has explicit missing/nonpositive indicators; this is recorded instead of silently deleting those rows. No API refresh or engine work is done.

The code vendors the recovered R8 v1.0.0, R7 v1.0.3, AFE Followups v1.0.0 and KAC Companion Recovery v1.0.2 sources unchanged. Version-specific authority files identify the current data and August profile snapshot. The R7 bind requires the reviewed completed 34-model run at `derived/replication/r7_analysis_v103_PRIVATE/7ab926c925a4`. Source packages may contain historical launchers; only the top-level framework launchers are used.

## A: flags and Patron status

The original August chooser design must reproduce its archived 851,131-account main and 599,045-account state sample, coefficients and standard errors before author-clean fits. Counts in new outputs can differ after exclusions. Main-analysis flag shares use available profiles in retained focal-returned groups; availability uses the corresponding acquisition cohort and reports its denominator separately. Unavailable profiles are not non-Patrons. A flagged focal removes its stored matched group; flagged controls are removed without replacement. Already unavailable focal groups are not newly removed from a state-sample design merely because a flag rule is applied.

Recipient-side models are the exact AFE `patron_features` and `streaming_lpm` specification. Both the author-clean baseline and author-clean exclusion of either recipient flag are estimated with chooser FE and the original shared-account-or-date CR0 covariance. Archived original coefficients are included only as labeled provenance, not as newly reproduced author-clean results. The later August snapshot does not establish a badge visible at the game, who paid, or a causal effect.

## B: slopes, profiles and conditional likelihood

The four histories are classified on all-stage P1 choices with at least four C and four L opportunities. P2 estimation retains zero-grant accounts. Chooser FE make the fitted group mean standardized to its own observed P2 composition equal the raw group mean. Its chooser-level influence is estimated jointly with the slope influence, so proportional slopes, BOTH−CO differences and ratios use a joint covariance. Ratio outputs flag a denominator interval containing zero; Wald ratio intervals then require particular care.

The primary model has common stage effects, as written in B3. The requested group-specific stage check is therefore a separately labeled group×stage sensitivity. The figure uses group-interacted displayed-gap bins with reference [−25,25), and pools gaps below −525 and at least 525 in endpoint bins. The eight evaluation bins are recovered from the continuous-merit producer: [−100,−50), [−50,0), [0,50), [50,100], (100,200], (200,300), [300,600), and ≥600/positive mate. Curves are standardized to each group's own composition and include pointwise chooser-clustered intervals. The evaluation profile controls for group-specific rG slopes.

Conditional logit conditions exactly on each account's grant count using the elementary-symmetric-polynomial likelihood, with a fast exact formula for one success/failure. It is not a dummy-variable logit. The sample is a deterministic uniform 1-in-5 account hash before dropping outcome-constant groups, which contain no conditional-likelihood information. The covariance is the chooser score sandwich. Rank, convergence and stationarity are checked; a failed fit is reported, never silently regularized. Optimizer iterates are atomically saved every five iterations.

A nonsignificant BOTH−CO difference is not evidence of equality. The package reports the prespecified numbers without automatically rewriting the framework.

## C: zero inflation

The 500-cell endpoints are copied from the current IV producer (five evaluation bands, four ply bands, five speeds, five displayed-gap bands). Full-sample cell rates are used for full-sample exposure. P1-only cell rates and P1-only fitted parameters are used for the forward check; P2 opportunity composition is observed, but P2 outcomes do not enter the predictions. Accounts with P2 exposure to unsupported P1 cells are excluded from that forecast and the rule is disclosed.

The literal handoff mixture fixes the mean propensity of active accounts at one, so its unconditional expected count is gamma×E. A second, explicitly labeled sensitivity sets the active mean to 1/gamma so the unconditional expectation stays E. Both are retained. ML uses analytic gradients; gamma intervals profile out k with the chi-square(1) cutoff. The requested 50:50 boundary LR reference is reported. A shape parameter at its numerical search boundary is flagged; boundary/asymptotic results are not an automatic psychological-gate finding. The Poisson limit and underdispersed synthetic cases are covered by tests. Forward posterior expectations are computed stably even for extreme exposure.

## D: one unavailable input, one estimable proxy

The handoff says standard monthly PGN dumps include casual games. The official database description says they contain rated games: https://database.lichess.org/ (checked 12 October 2026). A share of casual games cannot be constructed by treating absent casual records as zero. If B triggers D, the runner fits RD > 110 versus RD ≤ 110 with group×normalized-payoff and group×evaluation effects plus the time-varying proxy main effect. It explicitly records the casual-share branch as unavailable. Completing that branch needs an independently complete standard-game chronology containing both rated and casual games before the focal opportunities; it is not obtained by this package. The RD proxy is not proof of game-time display or low concern for rating.

## E: prior history and exposure

PG means at least one observed grant in any state strictly before the exposure anchor. PC means an earlier competitive active choice and no earlier grant; NC means neither. PG takes priority, so the groups are mutually exclusive. History uses the authenticated all-source 24-month active-decision parent (47,587,020 rows before exclusions), not just a 90-day history or the screened outcome panel. It is left-censored at November 2023, not lifetime history.

The original matched receipt Parquet is hash-bound to the KAC current-pool receipt source. Original support/follow-up counts are verified. Author exclusions preserve the original index exposure cohort without selecting replacement exposures. The original exposure cells and >=5 treated/>=20 control support rule are retained; ATT weights are recomputed after exclusions, before outcome selection. The first later competitive choice is rebuilt from the author-clean main panel with the original timestamp/archive-ordinal/game-ID tie order. The thirteen exposure-game controls retain their original median imputation, standardization, square and missing-indicator construction, with exposure-cell/month FE. PG/PC group main effects accompany the three receipt interactions. Primary standard errors cluster by exposure-opponent account with the original matched-model finite-sample correction. Interval estimates are weighted descriptive comparisons conditional on the first choice being in the interval, not randomized timing effects.

Secondary IV retains authenticated author-clean R7 S0 rows, X0 controls, fixed effects and frozen pooled `adjusted_7d` score. Receipt×group is jointly instrumented by score×group, with group main effects. It reports original shared-account-or-date CR0 inference plus exposure-opponent-cluster sensitivity, joint excluded-instrument diagnostics and within-group first stages. The subgroup 2SLS intervals are Wald intervals; weak instruments or different subgroup complier populations can prevent a mechanism conclusion. Generated scores are treated as fixed.

## F: the new persistence question

C/N is the direct comparison; C/L is separately labeled and never treated as all noncompetitive play. The same account sample supplies all four main correlations for a given comparison, minimum and stage restriction. A cell with no opportunities is missing; a cell with zero grants remains eligible when opportunity support is sufficient. Raw and adjusted scores use exactly the same cells. P1-cohort retention is calculated before restricting to P2 support; any P2 opportunity includes intermediate states even in C/L tables.

Primary correlations are unweighted Pearson. Harmonic-exposure Pearson and Spearman are secondary. The 999 bootstrap draws resample entire account records, with shared draws across matrix entries, diagonal differences and C−N/C−L selectivity correlations. Spearman ranks are recalculated under each resampled account multiplicity. Zero-variance or poorly supported bootstrap statistics remain not estimable. Pair-specific samples are separately labeled.

Composition adjustment uses five deterministic chooser folds, shared across years; separate LPMs by year and C/N on other folds; baseline controls and the frozen evaluation/gap bins. L uses the N-model residual in its clearly-lost subset. Held-out rows outside the identified training design stop the adjustment rather than receiving an arbitrary generalized-inverse prediction. Adjustment has no chooser FE or granting-history predictors. Bootstrap intervals condition on these nuisance fits; they do not include refitting uncertainty. Returning-account correlations do not identify a stable preference primitive or persistence among unobserved nonreturners.

## Reuse and exports

Scientific configuration and package hashes determine the run ID; CPU/RAM caps do not. Parent and model outputs have hash receipts, external report files are bound where final caching is used, and input identities are checked on resume. Independent worker results are aggregated in input order for deterministic numerical reconstruction. Existing nuisance fits are verified and retained on a resumed scoring pass, so their timestamps do not invalidate completed score checkpoints.

Only aggregate report directories are exported. The synthetic tests and their logs describe validation, not results on the user's data. No manuscript text is changed automatically.
