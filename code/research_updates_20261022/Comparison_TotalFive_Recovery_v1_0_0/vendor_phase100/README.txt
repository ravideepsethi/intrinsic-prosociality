RUN 2 — FULL 100% COMPARISON, CURRENT CERTIFIED SCORE A — v1.0.0

The download is finished. This package performs the final local analysis.
Save the ZIP and its .sha256 file in ~/Desktop/Lichess_Desktop.

Expected runtime
About 3–6 hours on the existing laptop/XT_Pro setup for the first full run.
This is a planning estimate based on the completed 75% and R9 runs, not a
measured 100% benchmark. Missing chronology/ENV keys and SSD contention can
add time. Offline self-tests should take about 1–3 minutes. Reruns verify and
reuse completed stages. Each stage reports progress; the Score A scheduler
also prints estimated time to the next checkpoint and finish.

Run
cd "$HOME/Desktop/Lichess_Desktop"
shasum -a 256 -c Run2_Phase100_Final_v1_0_0.zip.sha256
r2_final_stage="$(mktemp -d "$PWD/run2_phase100_final.XXXXXX")"
ditto -x -k Run2_Phase100_Final_v1_0_0.zip "$r2_final_stage"
bash "$r2_final_stage/Run2_Phase100_Final_v1_0_0/RUN_FINAL_100.command" \
  --workers 10 --memory-gb 11

Inputs
The completed CHECKPOINT_100_SAVED snapshot and all original 10/25/50/100
request-band exports. The downloader's exact 75% prefix is not counted twice.
The authenticated completed Phase75 analysis 9e46500403a4, the existing
history/chronology Parquet caches, and completed R9 4028bf3e1857 must remain
on the project drive. Earlier source files and the original completed
baseline are authenticated through their existing producer contracts.
Default project: /Volumes/XT_Pro/lichess_kindness.
Python: that project's venv/bin/python. Existing IV_PROJECT_ROOT, IV_DESKTOP
and IV_PYTHON overrides are honored. SciPy is not required.

What it does
1. Builds the full fixed comparison frames using the original eligibility,
   chronology, 90-day follow-up, author exclusions and outcome definitions.
   Verifies the complete earlier 75% membership, metadata and features by
   game identity. Integer/null Arrow types are preserved in streamed batches.
   It carries the exact three reviewed exclusions only after their identity
   and metadata checks pass. Any new unresolved identity stops with a report;
   it is not silently dropped or replaced.
2. Uses the exact scientific R9 implementation carried inside the verified
   R9 ENV repair package. Its scientific manifest is
   450837fec023b0b4157345b640d9997b2779da71daa7f003d7562d17867e8874.
   This differs from an older same-named R9 package; the successful producer
   is bundled here unchanged.
3. Fits the ordinary-game check and three entry outcomes in both the full
   sample and the added 75–100% band. Primary controls are X0_ENV_indicator;
   X0 is reported beside it. There are eight new fit jobs.
4. Reuses the certified S0 receipt coefficients and row-level influences.
   These models are not reestimated. Saved input hashes and newly reproduced
   S0 scores must agree before reuse. All 75% comparison scores, history
   controls and ENV values must reproduce before their old fits are reused.
5. Computes receipt-minus-ordinary and added-quarter-minus-earlier-75%
   contrasts using actual shared accounts and dates, including covariance.
   The added band has different games, but can share players and outcomes.

Scientific definition
Score A uses all donor times. The opponent is the chooser; every decision
involving the focal pair is removed. At least five donors are required on
the fixed rows. Reference predictions use donor-event UTC month with the
certified fallback and both-player-fold exclusion. The three opponent-history
controls use that same donor set. Post-focal donors remain allowed by the
certified definition. Generated scores are treated as fixed.

All reduced forms and entry/placebo slopes use the existing common Score A
SD 0.04979005187533171. The original +/-0.015 pp margin at fixed SD 0.0594 is
converted to the same native-score margin, about +/-0.01257325 pp per current
common SD. Its numerical width is not held fixed after restandardization.
The final fixed-sample intervals are nominal CR0 intervals, not sequential
confidence sequences. The earlier phases did not stop the download.

The entry outcomes are analysis_entry_90, recipient_disconnect_main and
active_timeout, with the certified meanings. An observed disconnection does
not establish anger or an opening-trap motive. The opening hypothesis needs
separate move/position evidence. This package updates current all-donor Score A;
it does not add a new competitive-only-score specification or rerun November
color-change analyses, receipt subgroups, learning splits, or the manuscript.
No automatic abstract/title approval is inferred from a small placebo.

Performance
- Zero API calls and zero Stockfish searches.
- Projected Parquet reads, ZSTD checkpoints and 131072-row assembly batches.
- Reuses the existing phase-independent feature/history indexes. Only missing
  chronology keys are calculated. Ordinary scores are an exact subset of
  entry scores, avoiding another donor scan.
- Reuses the completed R9 75% ENV rate cache and scans only for missing
  pair/month requests, with the unchanged numerator/denominator rules.
- Up to 10 workers within an 11 GiB planning budget; currently six scan
  workers, fewer large fit workers. BLAS/DuckDB threads are bounded to avoid
  oversubscription. Finished fit processes exit to release their allocations.
- ENV uses the tested two-worker/3 GB DuckDB plan; only failed OOM tasks retry
  serially at 8 GB after other workers exit. Other errors stop normally.
- Old completed data are read-only. New outputs use separate versioned roots.
  Completed shared feature-cache blocks may be added under the existing
  content-derived keys. Their definitions and source identities are unchanged.

Outputs
RUN2_PHASE_100_FRAMES_REPORT_<configuration>.zip is sample accounting only.
RUN2_PHASE_100_SCORE_A_REPORT_<configuration>.zip contains the estimates.
Return the latter ZIP, its .sha256 sidecar and run2_phase100_final_analyze_*.log.
If stopped before models, return the latest frames report and log instead.

The result ZIP contains aggregate tables only. Original identifiers and
influence rows remain on the Mac. Read READ_RESULTS.txt, ordinary.csv,
receipt_minus_ordinary.csv and entry.csv first. certified75.csv and
added_band_minus_75.csv show the phase comparison. A reused receipt-IV value
is explicitly marked reused, not presented as a new estimate.

Validation limits
Synthetic end-to-end frame construction, typed batches, source-cache reuse,
full-hash boundary checks, exclusion checks, actual spawned model fits,
joint covariance, score/environment bridges, report completion and resume
are tested locally. The original certified estimator and ENV memory-repair
tests are also included. Production Parquets are on the Mac, so this package
has not estimated the 100% production effects in the assistant workspace.
