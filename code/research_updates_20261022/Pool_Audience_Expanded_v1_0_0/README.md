# Expanded audience exclusions — v1.0.0

Runs the proposed expanded audience robustness analysis on the frozen 41,534,331
pool, non-adjacent-rematch opportunities, November 2023–October 2025. It reuses
the completed audience run's streamer directory and the profiles authenticated
by the returned Patron cache audit. No Lichess API requests or new scraping.
The environment setup may download Python dependencies from PyPI.

## Run

Save `Pool_Audience_Expanded_v1_0_0.zip` and its `.sha256` sidecar in
`~/Desktop/Lichess_Desktop`. Mount XT_Pro. Paste the complete command from
`RUN_TERMINAL.txt`. The command verifies the archive, unpacks to a fresh folder,
verifies its internal manifest, builds a dedicated Python environment, runs
synthetic verification, and launches the analysis with 10 DuckDB threads and a
6 GB DuckDB memory limit. This is SQL parallelism, not 10 API workers.

Python 3.11 or newer is required. The dedicated environment does not modify the
base/Conda environment. Set `LICHESS_AUDIENCE_PYTHON` to an appropriate Python
executable before the command if the default `python3` is older.

The terminal command uses `caffeinate` while running. Source inputs are opened
read-only. New flags, compact monthly Parquets, and spill files are on XT_Pro.
The compact joins are reused on subsequent runs if their hashes and input/code
fingerprints still match. Estimates are recomputed from those joins. No existing
source cache is deleted or repaired automatically.

## Fixed inputs and provenance

1. `derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE/panel/`
   — the exact 24 monthly Parquets in `panel_authority.json`. All file sizes,
   SHA-256 values and the main-sample counts are checked.
2. `derived/replication/patron_profile_snapshot_24m_v100_FINAL_CERTIFIED/profile_snapshot_24m_private_lossless.parquet`
   — SHA-256 `f42f28a6540a65c0a83f0da488663b4adddf60d1001daeed556f1ffbb961e238`.
3. The existing gap supplement under
   `derived/replication/pool_main_reanalysis_v100_PRIVATE/patron_gap_fill_v100/`
   with SHA-256 `39a9c911bb0030d2dacc7c73f77d0bb94bc27981be347dd3e03f30af8b0482aa`.
   Other supplement versions are not silently substituted.
4. `derived/replication/audience_visibility_v100_PRIVATE/directory_snapshot/`
   — existing HTML page hashes are verified and the 260-account positive list
   must reproduce registry hash
   `d3a1eda22a632afb2cc595112b354fd70d507d7051c68f9ea7cd401334d60f0f`.

The combined profile sources must reproduce 1,305,805 returned accounts,
1,509 chess-title accounts, 2,534 channel-link candidates, and 189,164 accounts
with positive TV time, along with all other audit quality counts. The code
reads the original profile fields again because the earlier audit's compact
boolean TV flag did not retain the distinction between missing and zero.

If `~/Desktop/Lichess_Desktop/known_streamers_extra.csv` exists, the launcher
adds its positive accounts. It must have `username,source_url` columns containing
Lichess handles and supporting URLs. Ownership is not independently verified by
this runner. This optional list is hashed and declared in the results. Without
extras, the original either-player exclusion must reproduce exactly 41,297,479
remaining opportunities / 567,613 kind draws and 236,852 flagged opportunities /
2,478 kind draws.

## Exclusions

Flags apply if **either player** qualifies:

1. **Original flag:** game-time rating at least 2400, a known chess title, or a
   known streamer from the frozen directory / structured profile evidence.
2. **Add channel links:** any profile bio/link containing a Twitch, YouTube,
   youtu.be or Kick domain. These are candidates; a link need not be the
   account owner's channel.
3. **Add recorded TV time:** a numeric account `playTime.tv` value greater than
   zero, from the audited saved profile(s).

The recognized chess titles are GM, IM, FM, CM, NM, WGM, WIM, WFM, WCM and WNM.
LM is reported by the profile audit but is not included as a competitive title.
Known bots and invalid/missing game-time ratings form a separate category in
the exclusion estimates. The full-sample benchmark retains the frozen sample.
Primary rating threshold is 2400; 2200 and 2500 are reported as sensitivities.

The main row includes all available metadata. At threshold 2400, two additional
sets repeat the analysis (each with its own no-exclusion benchmark):

- Both players have returned cached profiles.
- Both players have returned profiles and numeric TV measurements.

These are coverage diagnostics. Because the Patron acquisition oversampled
granters, restricting to observed profiles does not make the sample random or
eliminate selection. The report includes coverage by both current outcome and
account-level ever-granting status. An observed zero TV value remains distinct
from missing TV and from having no profile.

## Estimation and controls

Each group reports overall kindness, competitive and clearly-worse rates,
their raw difference and ratio, and the chooser fixed-effect difference.
Raw rates retain all opportunities in their respective categories, including
accounts that never grant. The intermediate board-evaluation category remains
in overall kindness rates but is excluded from the desert contrast.

The FE model is `kind_draw = chooser intercept + beta * competitive`, estimated
separately within each exclusion group and metadata scope. **No other controls
are added**: no month, speed, clocks, ply, rating, RD, volatility, payoff or
Patron terms. This directly extends the previous audience desert-gradient
exercise; it is distinct from the within-chooser payoff-curve analysis.

For chooser i, let F_i and W_i be competitive and clearly-worse counts.
The FE coefficient is the weighted average of that chooser's rate difference,
with weight `F_i * W_i / (F_i + W_i)`. Only accounts with F_i>0 and W_i>0
identify that coefficient; outcome switching is not required. FE observation
and chooser counts refer to this identifying sample.

SEs cluster by chooser, with CR1 correction
`G/(G-1) * (N-1)/(N-G-1)` for FE. Intervals use Student t with G-1 degrees of
freedom. Between-flag-group contrasts include covariance from choosers appearing
in both groups. No test compares nested exclusion estimates to their shared full
sample, and no equivalence conclusion is automated. Fewer than 30 clusters are
flagged in the estimate tables.

## What the TV field establishes

Lichess credits TV playing time when a finished game is in its recent-TV record.
This is not time spent watching other users. It does not measure an actual
viewer, number of viewers, or whether the draw decision was seen. The credited
duration need not equal precise broadcast duration. TV channels include more
than the highest-rated standard games.

Primary code references (pinned current implementation):

- [Finisher.scala](https://github.com/lichess-org/lila/blob/a558015505da237d46c335f669cd033370a05955/modules/round/src/main/Finisher.scala)
- [RecentTvGames.scala](https://github.com/lichess-org/lila/blob/a558015505da237d46c335f669cd033370a05955/modules/round/src/main/RecentTvGames.scala)
- [UserRepo.scala](https://github.com/lichess-org/lila/blob/a558015505da237d46c335f669cd033370a05955/modules/user/src/main/UserRepo.scala)

The profile snapshots are from August–September 2026, after the 2023–2025 panel.
TV time is cumulative and may arise outside the paper's period or game types.
Recorded zero is not proof of never being featured; unrecorded audiences and
off-platform streams remain possible. The remaining group is called
`not_flagged_by_available_sources`, never “unwatched.”

## Outputs

Public aggregate results are written to:

`/Volumes/XT_Pro/lichess_kindness/output/POOL_AUDIENCE_EXPANDED_RESULTS_v100_<timestamp>/`

An aggregate ZIP and SHA-256 sidecar are copied to `~/Desktop/Lichess_Desktop`.
Upload those two files. They contain results, tables, a PDF/PNG figure, executed
code, manifests and a success receipt. They contain no account-level IDs,
profile text, streamer membership lists or row-level Parquets.

Private derived flags and monthly joins stay under:

`/Volumes/XT_Pro/lichess_kindness/derived/replication/audience_expanded_v100_PRIVATE/`

Main report files:

- `RESULTS.md`, `RESULTS.json`, `primary_exclusion_summary.csv`.
- `group_summary.csv`, `estimates.csv`, `between_flag_groups.csv`.
- `metadata_coverage_by_opportunity.csv`, `metadata_coverage_by_chooser.csv`.
- `individual_flag_coverage.csv`, `flag_overlap.csv`, `recorded_tv_duration.csv`.
- `exclusion_metadata_partition.csv`.
- `audience_exclusion_robustness.pdf` and `.png`.

## Validation

The launcher runs six synthetic tests before accessing research inputs:

1. Missing profiles, missing TV and recorded zero remain separate.
2. Flags work for either player and exclusions are nested.
3. FE point estimates and cluster SEs match independent row-level dummy OLS.
4. Raw between-group SEs retain shared-chooser covariance.
5. Counts, archive/manifest integrity and aggregate-only exports are checked.
6. Cache reuse preserves monthly files; changed cache/profile/directory hashes
   are rejected.

The synthetic tests are not empirical results. Production analysis requires the
private inputs on the user's XT_Pro drive.
