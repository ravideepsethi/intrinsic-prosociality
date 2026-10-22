# Patron audience cache audit 1.0.0

This local audit answers whether the already downloaded Patron profiles contain
title, streamer, streaming, or streaming-link information. It makes no Lichess
requests and does not rerun models or modify the certified inputs.

It reads the certified August lossless Parquet and, if present, the separately
dated September gap-fill supplement. The August file must match its known
SHA-256. Additional normalized files can be supplied with repeated `--profile`
arguments; these are reported as explicitly supplied, not certified August data.

The aggregate results ZIP is copied to Desktop/Lichess_Desktop. Upload that ZIP
and its .sha256 sidecar. Identifiers, URLs, the DuckDB database and candidate
review text remain under derived/replication/patron_audience_cache_audit_v100_PRIVATE.

Private outputs:

- audience_profile_evidence.parquet: one row per returned account with evidence flags and dates.
- positive_streamer_evidence.csv: accounts with structured streamer channels or streaming=true in a saved response.
- streamer_candidates_for_review.csv: profile text mentioning Twitch, YouTube, youtu.be or Kick domains. These are leads only, not automatically verified owned channels.

Absent streamer fields do not mean non-streamer. streaming=false does not mean
non-streamer. Recorded TV time is a separate profile field, not a spectator count.
The saved Patron profile sample is selected and is not the full paper sample.
Counts here must not be used as population prevalence estimates.

Run RUN_CACHE_AUDIT.command via the supplied full terminal command. It reuses the
audience runner environment. If unavailable, it creates a separate environment
and installs DuckDB 1.5.5. Only this fallback dependency installation needs network.

The raw profile data are on your Mac and have not been examined in this workspace.
The supplied audit was checked using synthetic profiles with titles, structured
channels, missing fields, live flags, duplicate snapshots, and misleading bio links.

## Further coverage work

1. Verify candidate channel ownership and account links before merging candidates.
2. Recover title evidence from existing full game API exports, where available;
   preserve the export/retrieval dates and do not assume title was held at game time.
3. Construct fixed elite-account flags from all observed in-panel ratings in both roles.
4. If additional public profiles are needed, query a probability sample of remaining
   accounts independent of kindness, plus a separately labelled targeted search.
   Use the individual user endpoint for structured streamer metadata, respect its
   rate limits, and keep query dates. Do not try to enumerate all site users.
5. Unknown audience status remains unknown; none of these sources observes whether
   a particular historical disconnect decision had spectators.

## Sources inspected 2026-09-16

- Original downloader: https://github.com/ravideepsethi/intrinsic-prosociality/blob/main/code/pool_main_reanalysis_v100/Pool_Main_Patron_Gap_Fill_v1_0_0/source/profile_fetcher_v100.py
- Bulk versus individual profile handling: https://github.com/lichess-org/lila/blob/master/app/controllers/Api.scala
- Extended streamer fields: https://github.com/lichess-org/lila/blob/master/modules/api/src/main/UserApi.scala
- Game JSON preservation: https://github.com/ravideepsethi/intrinsic-prosociality/blob/main/code/04_enrich_timeout_candidates.py
