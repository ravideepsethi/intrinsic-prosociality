# Country/profile first pass v1.0.0

This is an exploratory, cache-only extension of the certified 41,534,331-decision pool/observed-nonadjacent panel (November 2023–October 2025). It makes no Lichess API calls and changes no source data. No population country rankings, causal in-group estimate, or residence assignments are produced.

## Profiles and cleaning

The August snapshot is authenticated against SHA-256 f42f28a6540a65c0a83f0da488663b4adddf60d1001daeed556f1ffbb961e238. The optional September supplement must match 39a9c911bb0030d2dacc7c73f77d0bb94bc27981be347dd3e03f30af8b0482aa. Returned and unreturned records remain distinct; nonreturn row counts across sources are not unique-account counts. Multiple returned snapshots trigger an error rather than an implicit change of query date.

Four disagreement checks precede cleaning: normalized flag versus normalized country, raw flag versus raw country, raw versus normalized flag, and raw versus normalized country. Empty strings are missing; comparisons ignore case. The chosen-code precedence is explicit: raw JSON profile.flag, normalized profile_flag, raw JSON profile.country, normalized profile_country. All four values contribute to a conflict indicator. Conflicting accounts stay in the flag-presence audit but are excluded from primary geographic comparisons.

Original strings are preserved. Primary geographic support uses ISO alpha-2 country/territory codes, excluding AQ, BV, HM, TF, GS and UM as a prespecified exception sensitivity category. This is not a list of sovereign states or proof of residence. Subnational/regional, non-ISO geographic/legacy, symbolic/identity, supranational and unrecognized codes stay separate. An underscore is not evidence of a joke: several such codes represent political or regional identity. Unknown codes are reported for review, not guessed. The bundled catalog was obtained from https://github.com/lichess-org/lila/blob/master/modules/user/src/main/Flags.scala on 2026-09-23; ISO labels were frozen from pycountry 26.2.16. Historical codes absent from today's catalog remain unrecognized unless ISO-listed.

Exact-flag pair tables retain subdivisions as distinct identities. A separate parent-code sensitivity maps explicitly recognized GB-, CA-, ES-, PT- and RU- subdivision codes to the two-letter prefix. Other disputed/regional mappings are not inferred. Primary ISO comparisons do not automatically merge subdivision setters into countries.

The snapshot is observed after the games. Flags are mutable; the data do not identify game-time flags or whether a chooser saw a recipient's flag. API field absence in closed profiles is not evidence of a voluntary decision not to set a flag.

## Selection and current outcomes

Current opportunity counts, competitive/losing histories, account ratings and volume are rebuilt from the certified current panel. The old acquisition role and match cell are retained solely as design labels. Never substitute an old stored ever-kind indicator for the recomputed current outcome. Non-acquired, unreturned, closed-profile, conflicting, active non-setter and setter statuses are reported separately.

All rate tables are opportunity weighted unless explicitly labeled as account-level ever-granter shares. They describe the acquired/observed strata indicated, not the population of a country. The August cohort was selected using kindness on the older full panel. No acquisition weights are invented. Exact population weights require authenticating the original eligible reservoir and allocation, including inclusion support. Exhausted reservoirs imply probability 1 when every eligible control was acquired; empty allocation in an eligible cell implies probability 0. Reconstructing only the current pool panel does not reproduce the older acquisition frame. Acquisition weights cannot eliminate voluntary flag-reporting selection.

The historical +0.907 pp coefficient is not itself a relative-rate estimate. Dividing it by the current full-panel competitive rate mixes samples and specifications. The historical raw setter/non-setter rates were 5.490%/5.124%, a roughly 7.1% relative raw difference in the selected sample. This package reports current raw rates and adjusted percentage-point coefficients separately.

## Models and uncertainty

Three opportunity-level linear-probability models estimate flag presence in competitive positions, flag presence in clearly losing positions, and positive recorded TV time in competitive positions. All use August returned non-disabled accounts with an acquisition match cell. Controls are additive fixed effects for acquisition match cell, month, speed, chooser rating tier, five board bins, six ply bins and seven displayed-rating-gap bins, plus reconstructed draw payoff/10, win premium/10, both RDs/100, log(1+both clocks), separate clock-missing indicators, and log(1+current chooser opportunity volume). Missing, nonfinite or negative clocks receive log value zero and their missing indicator is one. TV requires an observed nonnegative TV value. Required numeric data must be finite. There is no chooser fixed effect: the profile flag is constant within account. Missing categories/covariates cannot silently drop rows.

These are newly specified exploratory models, not an exact re-estimation of the historical profile-marker regression. The fourth model is an account-level current ever-competitive-granter indicator on flag presence and original acquisition match-cell fixed effects, among accounts with a competitive opportunity. It is an acquisition-conditioned diagnostic.

Sparse normal equations are accumulated in month partitions. Target estimability is checked in the normalized moment matrix. Rank-deficient nuisance columns are handled through a generalized inverse; a nonestimable target receives no coefficient. Standard errors sum influence scores by chooser across all batches and months, then apply the CR1 finite-sample correction. Four exploratory p-values receive a common Holm adjustment (unsupported tests count as p=1). Descriptive rate and board-gradient standard errors also cluster by chooser, including covariance between competitive and losing decisions.

No same-country regression is run before support is reviewed. Tables report both-player coverage, same/different pair counts and grant events, and how many choosers supply both same- and different-country competitive opportunities. A fixed numerical cutoff such as 'tens of thousands is insufficient' is not imposed: event counts, independent chooser support and identifying variation matter.

## Visibility and moderation

Positive recorded TV time means the account has accumulated playing time for games featured on Lichess TV; zero means zero recorded time, not verified lifetime non-exposure. Rating-tier and current opportunity-volume tables are descriptive. The exposure was recorded after the panel, and the snapshot contains no spectator count or game-specific audience measurement. The code retains unavailable TV time separately. Source: https://github.com/lichess-org/lila/blob/master/modules/round/src/main/Finisher.scala .

The public tosViolation mark corresponds in current Lichess code to engine OR boosting marks, not all abuse categories. The snapshot does not separate boosting from engine use. Recipient tables are exploratory sensitivities; no abandonment-intent measure is constructed. Closed or unreturned profiles do not become unmarked recipients. Sources: modules/user/src/main/JsonView.scala and modules/core/src/main/user.scala in lichess-org/lila.

## All-game activity proxy

The second phase reads the saved ordinary-game chronology, both player roles, within the same two-year window. It filters to current chooser IDs and uses only UTC game times and IDs; no kindness outcome or country label enters the proxy. The bundled chronology manifest authenticates expected file sizes, row counts and schema, not a newly computed source-body SHA-256. Files that differ stop this stage; the completed core report remains available.

Each chooser's activity phase is the circular mean of UTC hour-bin centers. It is classified only with at least 50 games, at least three active months, and circular concentration at least 0.15. These are declared screening choices, not validated location thresholds. Sparse, absent or diffuse activity remains unclassified; the program does not assign a location to every chooser. All chooser accounts remain in coverage tables.

An illustrative offset is 20:00 minus the UTC activity phase, wrapped onto [-12,+12) and rounded to three-hour bands. This assumes an evening local activity phase. Sensitivities use 18:00 and 22:00. These are activity bands under a convention, not real civil time zones or longitude bands. No country validation model is trained on flags.

Year 1 and year 2 are evaluated separately. A stable-years subset requires both years to meet the support thresholds and phases to differ by at most three hours. The full-window proxy uses all games and is descriptive; a held-out companion uses only year-1 activity to classify year-2 decisions. Flag-country versus activity-band counts are a crosscheck, not a deception detector. Similar setter/non-setter gradients within these activity groups do not prove geographic representativeness. Time zones, chronotypes, schedules, travel and daylight-saving changes remain confounded.

## Outputs and computation

The report ZIPs contain aggregate results only. IDs, slim opportunity caches, regression scores and individual activity proxies remain under PRIVATE. The core ZIP is written before all-game scanning. Month-level model/projection checkpoints and file-level activity checkpoints are checksummed and reused. Inputs are never overwritten. A failed checkpoint stops rather than being silently reused. The package creates a separate virtual environment and does not install into the shared research environment.
