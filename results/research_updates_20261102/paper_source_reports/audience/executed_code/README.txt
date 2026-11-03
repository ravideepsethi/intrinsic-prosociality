Material-corrected audience analysis, v1.0.0

Expected runtime: 5–15 minutes provisionally, plus 1–2 minutes for first-time
setup/tests. This is based on the earlier 4-minute audience run, with time
allowed for input hashing and the additional corrected-material checks.
It has not been timed on the full private sample. Drive I/O can extend it.
The launcher prints Toronto start and finish estimates, accounting for DST.

Save/unzip this folder under ~/Desktop/Lichess_Desktop and run:
bash "$HOME/Desktop/Lichess_Desktop/Mating_Material_Audience_v1_0_0/RUN_AUDIENCE.command"

This fills a discovered gap: the previously completed "reputation" family
covered repeat encounters, not audience visibility. Old audience estimates
were from a different denominator and cannot be relabeled as corrected results.
This package does not repeat the completed paper-closeout or receipt analyses.

Inputs (read-only):
- Corrected material-ready main panel, 24 monthly files, authenticated by the
  exact reviewed manifest and by each full file's SHA-256 and footer count.
- Existing August profile snapshot and audited gap supplement(s).
- Existing frozen streamer directory pages and registry.
The default project root is /Volumes/XT_Pro/lichess_kindness.
There is no historical-panel fallback and no new Lichess/API request.

Checks:
- 41,513,719 opportunities, 570,422 grants, exact regional/account censuses.
- Platform-compatible material rule; grant columns agree on every row.
- AUTHOR_ACCOUNT_1 and AUTHOR_ACCOUNT_2 excluded in both behavioral decision roles.
- Profile and TV missingness remains distinct from known zero.
- Metadata joins preserve monthly row counts; inputs are guarded through export.
- Original chooser-FE estimator is checked against independent row-level OLS.

Analyses:
- Raw grant rates and chooser-FE competitive-minus-clearly-worse gradients.
- Both-player exclusions: rating >=2400/title/streamer; add channel links;
  add positive recorded TV playtime. Threshold sensitivities at 2200/2500.
- Complete-profile and numeric-TV subsets, overlap and coverage diagnostics.
- Disjoint chooser/either-player groups: streamer; elite/title nonstreamer;
  remainder. Sparse groups retain insufficient-support flags.
All are descriptive. Metadata is post-panel, selectively observed and cannot
show that an actual decision was unwatched. No causal audience effect is estimated.

Resources and resume:
Four DuckDB threads, 6 GB DuckDB memory, one BLAS thread, two hash readers.
No full-width global sort. Monthly joined flags are cached and hash-verified;
the same command resumes from completed monthly caches. Completed report files
are hash-verified on rerun. Do not delete the private checkpoint directory.
The cache is under derived/replication/mating_material_audience_v100_PRIVATE.
It is separate from all previous runs. Temporary working files are disposable.

Return the single MATERIAL_AUDIENCE_<id>_RETURN.zip written to Lichess_Desktop.
It contains aggregate tables, checks and executed code, not row-level data.
If a check fails, the same-named diagnostic ZIP is written with FAILED status.
Audience completion is not itself whole-paper certification. The review draft
still needs these results integrated and a final compile/visual check.
