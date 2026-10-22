# Pool audience-proxy robustness, v1.0.0

Run the proposed streamer/elite exclusion on the **41,534,331-opportunity, 570,091-kind-draw** main sample, November 2023–October 2025. No Stockfish runs, rating reconstruction, new game downloads, or source-panel changes.

The output answers: **Are kindness and the desert gradient concentrated in games involving identified streamers or elite players?** It does not measure whether a game had spectators.

## Run

Save the ZIP and its `.sha256` in `~/Desktop/Lichess_Desktop`. Mount XT_Pro, then paste `RUN_TERMINAL.txt` into Terminal. The command creates an isolated Python environment, checks the package checksum, runs the synthetic verification, reads the certified panel, and copies the aggregate results ZIP and checksum back to the Desktop folder.

Default panel:

```
/Volumes/XT_Pro/lichess_kindness/derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE/panel
```

Default title source, reused read-only and checked against its certified SHA-256:

```
/Volumes/XT_Pro/lichess_kindness/derived/replication/patron_profile_snapshot_24m_v100_FINAL_CERTIFIED/profile_snapshot_24m_private_lossless.parquet
```

The package defaults to 10 DuckDB threads, 6 GB working memory, and one thread per numerical library. It runs network acquisition with **one request at a time**, caches completed pages, honors HTTP 429 backoff, and makes no bulk profile requests. Keep roughly 15 GB free on XT_Pro for thin-panel caches and temporary disk spill.

For planning, allow roughly **45–120 minutes** for a first run, with substantial uncertainty from disk speed, group aggregation, and directory rate limiting. This is not a benchmark of your full private panel. The directory can require hundreds of small requests. Progress appears in Terminal and in a timestamped log on the Desktop.

## Classifications fixed before seeing outcomes

The rating cutoff is **2400**, with **2200 and 2500** sensitivity checks. The rating is the player's rating at the particular opportunity, in that game's speed category; it is not the current profile rating or an account's maximum rating. Classification is therefore by opportunity, and accounts can cross groups over time.

Three mutually exclusive groups, with streamers taking priority:

1. `known_streamer`: a positive match to the downloaded listing or your documented supplemental list.
2. `elite_not_known_streamer`: not in group 1, but meeting the specified elite rule.
3. `remaining`: neither flag identified.

A fourth diagnostic group isolates known BOT accounts or unusable ratings when necessary. BOT and honorary LM are not treated as competitive chess titles. Recognized human titles are GM, IM, FM, CM, NM, WGM, WIM, WFM, WCM, WNM.

Two parallel elite definitions are always reported:

- **`rating_and_directory`**: high rating plus streamer-directory flags. This definition is independent of selection into the cached profile sample.
- **`rating_directory_known_titles`**: adds positive chess-title flags from the cached profiles and titled streamer cards. This is a broader exclusion, with incomplete and selected title coverage.

Two views are always reported:

- **`chooser`**: groups according to the chooser's flags. This compares the behavior of the three chooser types.
- **`either_player`**: streamer if either player is known to stream; otherwise elite if either player meets the elite rule. Its remainder is the main strict exclusion sample. These are game classifications, not claims about which player had an audience.

The full sample is re-estimated as a baseline. Each three/four-group partition must sum exactly to the main-sample opportunity and draw totals.

## What the code estimates

For every cutoff, definition, and view:

- Opportunity and kind-draw counts and shares of the full sample.
- Chooser and granting-account counts. Account counts across groups need not add to the total because an account may enter more than one group.
- All-position, competitive-position, and clearly-worse-position kindness rates.
- Competitive-minus-clearly-worse difference and rate ratio.
- Within-chooser desert gradient, with chooser-clustered SE and CI.
- Differences between elite/streamer groups and the remainder, with chooser-clustered covariance retained across groups.

Competitive means the disconnected player's engine evaluation is at least −100 cp. Clearly worse means at most −300 cp. The middle region remains in all-position rates and counts, but is omitted from the desert contrasts. The flags and kind-draw outcome come from the certified panel, not new reconstruction.

The FE model is `kind_draw ~ competitive + chooser fixed effects`, fitted separately within each group. In a stacked description this is a chooser-by-group intercept model with group-specific desert slopes. The exact slope is the weighted average of account-level state differences, with weights `n_F*n_W/(n_F+n_W)`. Only accounts observed in both states within that group identify its coefficient. Standard errors use the explicit correction `G/(G−1) × (N−1)/(N−G−1)`, with N and G restricted to those state-switching accounts. This matches the convention used in the earlier below-1600 runner.

Raw rates use the usual cluster influence functions. Raw gradients use the covariance between their two rates. Rate ratios use log-ratio inference and are left undefined if either rate is zero. Group contrasts combine account scores before squaring, so a chooser who enters several groups is never incorrectly treated as independent of themselves.

Intervals use Student t with G−1 degrees of freedom; group differences use the smaller group cluster count minus one. Estimates with fewer than 30 contributing clusters are flagged. This does not make few-cluster inference reliable automatically.

### Adjustment for observed composition

At the primary 2400 cutoff, all four definition/view combinations also get pairwise common-support comparisons. Exact coarse strata combine:

- Both players' ratings, separately in 200-point bins.
- Game speed.
- Calendar quarter.
- Ply: at most 10, 11–30, 31–60, over 60.
- Each clock separately: under 15 seconds, 15–under 60, at least 60.

For a pair of groups, a retained stratum must have at least 10 opportunities in **each of the four group × desert cells**. The same pooled-stratum opportunity weights are used for all four rates. This compares desert gradients on the same covariate distribution. It conditions on observed support and fixed standardization weights for cluster inference. It is not an adjusted full-population kindness rate or an audience treatment effect.

Support shares and sample sizes are reported. They refer to observations with nonmissing control variables in the two desert states. Rating-defined elite and non-elite groups may have **no rating overlap**, especially under the profile-independent definition. The program reports `no_common_support`; it does not force an extrapolating regression. Raw and chooser-FE estimates are still available in that case.

### Similarity

`between_group_contrasts.csv` reports 95% and 90% confidence intervals. It also flags whether the 90% interval lies inside ±0.25 or ±0.50 percentage points. These are **exploratory defaults**, not author-approved substantive equivalence margins, and not evidence that audiences have no effect. Both margins are recorded before the results are computed. Do not choose a preferred margin after seeing the intervals. No multiplicity correction is applied; the threshold and classification sensitivities are not independent confirmatory tests.

## Metadata limitations that matter

1. **Streamer coverage is incomplete.** The public listing includes live cards and paginated approved/listed streamer accounts. Current Lichess source advertises 1000 non-live entries and sorts by recent streaming activity; completing pagination does not census all streamers. Ordering can change during acquisition. The runner stores retrieval times, raw pages, hashes, and the deduplicated count. It does not use the live-only API as a census.
2. **The list is observed now, not in 2023–2025.** A positive match is a proxy for visibility, not evidence a particular game was streamed. Historical streamers can be missing, and accounts may have begun streaming later.
3. **Title profiles are a selected sample.** The August acquisition oversampled granting accounts and matched controls. Profile absence is never described as a verified absence of a title. `metadata_coverage.csv` reports coverage separately by outcome and desert state. The independent rating/directory analysis is essential alongside the title-enriched exclusion.
4. **No historical title assignment is inferred.** Title flags are observed at the profile/directory snapshot date, after the game panel. They can over-exclude later title earners and miss unobserved historical titles.
5. **If the certified title snapshot is missing**, the run still produces the rating/directory results. The report identifies absent title coverage; directory title flags may still be present. It does not silently claim all titles were checked. You can explicitly supply another normalized profile file with the fields `username_norm,title,returned,queried_at_utc`; all supplied files are hashed. `run_audience.py --profile-file FILE` may be repeated for several snapshots. The shell wrapper accepts one override through `LICHESS_AUDIENCE_PROFILE_FILE`.
6. **The remainder can still have an audience.** Friends, unlisted streams, and viewers of the opponent remain possible. Similar behavior across these groups is evidence about concentration, not random assignment of audiences.

## Add known streamers

Optionally save `known_streamers_extra.csv` in `~/Desktop/Lichess_Desktop`, using the bundled template's columns:

```
username,source_url,notes
```

Use the **Lichess account name**, not the Twitch/YouTube channel name. Every nonempty row needs a source URL documenting the account-channel link. The runner does not try to guess matches from display names. It unions your positive list with the directory and records its hash. No supplemental list is required to run.

## Output and resuming

The main report is `RESULTS.md`; `RESULTS.json` contains every estimate and all aggregate provenance. CSV files make the tables easy to inspect. The report deliberately avoids an automated conclusion that the groups are similar or that games were unwatched.

Private directory snapshots, usernames, joined thin-panel Parquets and working files remain under:

```
/Volumes/XT_Pro/lichess_kindness/derived/replication/audience_visibility_v100_PRIVATE
```

Aggregate results are written to a new timestamped directory under `.../output/`. On success, the result ZIP and `.sha256` are copied into `~/Desktop/Lichess_Desktop`. Upload those two files for interpretation. Do not upload the private cache.

An interruption can be resumed by rerunning the same command. Completed directory pages and joined monthly panels are reused only when their hashes and input configuration match. Statistical specifications are recalculated in a fresh output directory; completed aggregate specifications in a failed run remain available in that run's output. The runner will not overwrite certified research inputs or an existing output folder. Do not run multiple instances against the same cache.

To make a new future directory snapshot, invoke `run_audience.py --cache NEW_PRIVATE_DIRECTORY`. Default reruns intentionally retain the original frozen directory list.

## Verification and provenance

`self_test.py` compares compressed-cell FE coefficients and clustered variances against explicit dummy-variable OLS on synthetic rows. It independently checks covariance-aware raw differences, common-support adjustment, no-extrapolation behavior, directory parsing, role joins, and the missing-profile distinction. All production panel files are verified against `panel_authority.json`; the script then rechecks full-sample and below-1600 counts. Production results have not been computed in the assistant workspace, which does not contain the private panel.

The main sample authority and previous FE construction come from the supplied project workflow, repository commit `bf3b2bf9ffedba8f53c61e3e1b55bb457e58a129`. The existing certified profile snapshot SHA is pinned in `run_audience.py`.

Public platform sources inspected September 16, 2026:

- [Streamer directory](https://lichess.org/streamer).
- [Directory pagination implementation](https://github.com/lichess-org/lila/blob/master/modules/streamer/src/main/StreamerPager.scala).
- [Live-streamer endpoint specification](https://github.com/lichess-org/api/blob/master/doc/specs/tags/users/api-streamer-live.yaml).
- [User API title field](https://github.com/lichess-org/api/blob/master/doc/specs/schemas/User.yaml).
- [Bulk-user endpoint and limits](https://github.com/lichess-org/api/blob/master/doc/specs/tags/users/api-users.yaml). No bulk-user acquisition is performed by this package.

The code and exact payload hashes are copied into the returned result bundle. Account-level metadata are not exported.
