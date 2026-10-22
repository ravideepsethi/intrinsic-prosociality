# Same-country follow-up methods

## Scope and estimand

The main question is whether an acquired flag-setting chooser grants more often to a recipient declaring the same country, conditional on chooser identity, recipient country and the established opportunity controls. The underlying panel is the certified 41,534,331-opportunity pool/non-adjacent sample, November 2023–October 2025. This follow-up uses the saved projections from the completed first pass, rather than constructing a new main panel.

The primary equation is

\[
Y_{ig}=\alpha_i+\beta\,1\{C_i=C_{j(g)}\}+\rho_{C_{j(g)}}+X_{ig}'\gamma+\varepsilon_{ig}.
\]

Here i is the chooser, g the opportunity, j(g) the disconnected recipient, Y the draw-grant indicator, and C the declared country/territory code. Chooser effects absorb stable chooser attributes, including declared chooser country, acquisition match cell, and full-panel chooser opportunity volume. Recipient-country effects account for average differences by the recipient's declared country. Full chooser-country × recipient-country effects are not included: they would absorb the same-country indicator.

The coefficient is an opportunity-weighted linear-probability association, expressed in percentage points. It is not an equal-chooser average, a causal estimate, or a population country effect. Outcome-based profile acquisition, optional flags, profile censoring and the retrospective snapshot remain limitations. Chooser effects do not resolve outcome-based acquisition selection.

## Sample and country definitions

Profiles must have been returned, not disabled, have a nonempty flag and no recorded flag-field conflict, on both sides. August profiles and the small September supplement retain the first pass's source resolution. Competitive positions have the disconnected player's evaluation at least −100 cp. Clearly losing positions have evaluation at most −300 cp.

The primary sample requires both codes in the first pass's primary ISO country/territory category. That rule excludes AQ, BV, HM, TF, GS and UM, symbolic/identity flags, subdivisions, supranational flags and other legacy categories. It includes territories retained by the original primary rule. It does not infer residence or validate an individual's nationality.

Two sensitivities change the flag definition:

- Parent-country mapping uses the existing recognized subdivision mappings to GB, CA, ES, PT and RU, in addition to primary countries. It retains the primary geographic exclusions. The first-pass raw parent-code table also assigned parent codes to the excluded geographic exceptions; that original table is reconciled for input integrity, but these exceptions are excluded from the new parent-country model.
- Exact-flag matching allows any returned, unconflicted, nonempty flag. Recipient-flag effects replace recipient-country effects. This includes symbolic affiliation and is explicitly broader than a country comparison.

No flag values are re-queried. Neither a null profile nor an unacquired account is reclassified as an observed non-setter.

## Controls

The main adjusted model includes month, speed, chooser rating tier, disconnected-player board-state bin, game-length bin, and recipient-minus-chooser rating-gap bin. It also includes draw payoff/10, win premium/10, both pre-game RDs/100, log(1 + each last observed clock), and the inherited clock-missingness indicators. Missing/invalid clock values were imputed to zero only with the corresponding indicator in the first pass. Other nonfinite continuous covariates cause an explicit stop.

Rating tiers are below 1600, 1600–1999, 2000–2399 and 2400+. Game-length bins are ≤4, 5–10, 11–20, 21–40, 41–80 and >80 plies. Rating-gap intervals use cutoffs −400, −200, −50, 50, 200 and 400. Board bins preserve the first-pass boundaries −300, −100, 100 and 300. Exact definitions are carried in the certified saved panel.

Acquisition match cell and log chooser volume are time invariant and already absorbed by chooser effects. They are not added as separate regressors. No estimated control is used to infer country or to alter flag values.

## Model family

| Model | Definition |
|---|---|
| iso_chooser_only | Competitive primary-country sample; chooser effects only |
| iso_chooser_recipient_country | Adds recipient-country effects |
| iso_primary | Adds all opportunity controls; designated primary model |
| iso_switchers_only | Primary specification restricted to choosers with both same- and different-country opportunities |
| iso_excluding_russia | Primary specification after excluding RU flags on either side |
| parent_country_sensitivity | Adjusted model using the cleaned parent-country definition |
| exact_flag_sensitivity | Adjusted exact-flag model, including symbolic affiliations |
| iso_excluding_marked_recipients | Primary specification after excluding recipients with a public engine-or-boost mark |
| iso_clearly_losing | Primary-country adjusted specification for clearly losing positions |

The moderation sensitivity does not select specifically for boosting and does not measure intent at the game. It uses the later public engine-or-boost mark. Missing marks, if present, are not treated as confirmed unmarked; the filter excludes only a known true mark.

Singleton choosers are excluded separately within each specification because they contribute no within-chooser variation. Choosers who never grant remain in the sample and can contribute identifying variation. Except for the explicit switcher-only sensitivity, choosers without same-country variation remain when they have multiple eligible opportunities, since they may help estimate the controls. Reported support distinguishes treatment switchers, outcome switchers, and those with both kinds of variation.

## Estimation and uncertainty

The estimator uses sparse regressors X and chooser sums. It computes X'MX and X'MY exactly for the loaded sample, where M subtracts chooser means. It solves the normalized symmetric cross-product matrix using an eigenvalue decomposition, retaining eigenvalues above max(10⁻¹¹, 10⁻¹⁰ times the largest eigenvalue). Collinearity in nuisance controls is accommodated. If the same-country coefficient is not identified, the model reports that status instead of a coefficient.

Standard errors use observation-level influence scores based on the within-transformed regressors and fitted within residuals. Scores are summed across every month before clustering. The primary CR1 covariance clusters by chooser. It uses G/(G−1) × (N−1)/(N−K), where K is the rank of the complete model, including absorbed chooser effects. This explicit full-rank convention may differ from software defaults that omit nested fixed effects from the small-sample correction. Primary p values and intervals use t with G−1 degrees of freedom.

The report also computes recipient clustering and two-way chooser/recipient clustering. The two-way variance is Vchooser + Vrecipient − Vchooser-recipient-pair, with the CR1 correction for each component. Its t approximation uses min(Gchooser, Grecipient)−1 degrees of freedom. A nonpositive two-way variance is reported as unsupported, not clamped to zero. These clusters treat chooser and recipient roles separately and do not implement a more general network dependence estimator.

The primary coefficient and unadjusted primary p value are identified in advance by `iso_primary`. As an exploratory safeguard, the report also applies Holm's procedure to chooser-cluster p values over all nine specifications; unsupported or unfinished models count conservatively as p = 1. Specifications are related sensitivity checks, not nine independent replications.

Per-model output records sample counts, grant counts, matching counts, model ranks, residual degrees of freedom, numerical conditioning, and the largest chooser residual sum. The reported simple within-weight share from never-granters uses ns × nd / (ns + nd); it describes the chooser-only comparison and is not claimed to be the adjusted model's complete leverage decomposition.

## Reused presentation results

`ready_results` contains the completed first-pass flag-selection and TV tables, not new estimates from this estimator. Their first-pass clustering and degrees-of-freedom conventions remain unchanged. Their source sample, controls and interpretations are documented beside the tables.

The activity figure relabels the existing 20:00-convention offset bands as actual UTC activity-phase centers. This is a deterministic relabeling: phase center = (20 − offset) modulo 24. It does not change membership or retrain the proxy. The figure shows known flag setters and known active non-setters among classified acquired accounts. All status groups and unclassified rows remain in the CSVs. Error bars are 1.96 times the reported chooser-cluster SE for the raw competitive-minus-clearly-losing rate difference.

The full-panel pooled CSV sums reported opportunities and grants across acquisition statuses, including unacquired accounts. It reports raw point estimates only. Its covariance is not reconstructed from aggregate tables. Neither similar activity curves nor their labels establish geographic generalizability.

## Input integrity and privacy

The frozen uploaded report anchors the first-pass run identity and source-support totals. The follow-up checks the completed report files, source-run identity, and the certified SHA-256 receipts on the saved profile and 24 panel files. Reconstructed ISO, exact-flag and original parent-code counts, grants and chooser counts must reproduce the frozen public tables in every board-state cell before modeling.

Monthly both-player projections and model-result checkpoints have new follow-up identities and hashes. The original first-pass run is read under a shared lock. Follow-up files are written only under a separate output directory. The public report contains aggregate outputs, methods and relative checkpoint references. It excludes private game/account records and usernames.

The code's numerical and integration checks are synthetic. The new production within-chooser estimates are produced only when the package is run against the private first-pass checkpoints on the Mac.
