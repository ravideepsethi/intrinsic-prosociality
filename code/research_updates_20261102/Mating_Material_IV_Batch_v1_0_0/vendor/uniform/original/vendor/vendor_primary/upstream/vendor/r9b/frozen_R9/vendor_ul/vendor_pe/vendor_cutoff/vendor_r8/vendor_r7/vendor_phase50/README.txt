Run 2 — fixed 50% comparison analysis, version 1.0.1

Put this ZIP in ~/Desktop/Lichess_Desktop and use the supplied terminal command.
Leave the continuous downloader running. This runner makes zero API requests.

Expected runtime: 1–5 minutes to reused coverage and the metadata audit and approximately 2–6 hours for the
full first run, including the competitive-entry control ladder. This is an
unbenchmarked laptop estimate based on earlier project runs. The SSD and
concurrent disk work matter. Completed stages resume after interruption.
Self-tests: approximately 30–120 seconds on a laptop.

WHAT IT ANSWERS
1. Does an opponent's past kindness predict later kindness after an ordinary
   game? This is the enlarged ordinary-game comparison (placebo).
2. Does the same opponent score predict whether the focal game enters the
   receipt sample? All ending types stay in that starting denominator.
3. Do these associations persist with a score based only on competitive
   positions? Compare the two scores on exactly the same supported rows.
4. Are the cumulative 50% results similar to the earlier 25% and to the added
   25–50% games? The new games can share players and later outcomes with the
   old games; these are not independent replications.

This package repeats the frozen primary specifications and adds the existing
competitive entry control ladder. It does not rerun the environment-rate
controls or the receipt IV. Their completed 25% results remain separate.
A receipt-minus-ordinary contrast with joint uncertainty is not implemented.
No causal/title/abstract gate is automatically cleared by an interim result.

FIXED INPUTS AND MEANING
The exact CHECKPOINT_050_SAVED publication is verified against the uploaded
report. The live download journal and later phases are never used as analysis
inputs. The 21 exposure months are November 2023 through July 2025.
The reported 29,625,961 additional frame games are BEFORE analytical filters;
1,912,023 original frame games are retained separately. API request count and
regression sample size are different quantities.

The failed v1.0.0 report is authenticated and contains three unresolved focal
records: April 2024, January 2025 and June 2025. The earlier runner allowed
exactly the two old records and correctly stopped before regressions.
This release reuses all 21 completed coverage Parquets and explicitly audits
the January record in the new 25–50% hash band. It records the saved response,
pre-download cache flag, differing/missing field names and whether those
sources explain the final metadata flag. It never chooses conflicting values.
A clean new response does not automatically erase an inherited conflict.
The two old identities, fixed hash bands and June response flag remain checked.

This is an explicit available-case amendment before any 50% estimates:
three focal records stay in frame accounting but contribute no regression
rows, and no replacements are added. The earlier 25% cohort still has its two
quarantines; the added 25–50% band has one. Factual histories and exposure
spacing are preserved. Any further or changed unresolved record stops.
The number excluded is not a bound on coefficient bias.

Earlier 25% games must reproduce all saved features, allowing only row-ID
rebinding. Earlier primary estimates and competitive-entry estimates must
reproduce within the existing numerical tolerances. Scores, controls,
cluster covariance, score units and the 25% upper-tail cutoff remain fixed.
Confidence intervals are nominal interim intervals. Holm corrections within
a phase do not correct repeated looks across phases.

PERFORMANCE AND RELIABILITY
- Reads only required Parquet columns for each model.
- Up to 10 local workers, bounded by physical CPUs and the memory budget.
- Memory-weighted model scheduling; a large fit runs alone when necessary.
- BLAS threads are capped to prevent process/thread oversubscription.
- Reuses unchanged monthly score/history indexes and immutable game-feature
  blocks from 10%, 25% and entry diagnostics. Computes only missing features.
- Applies cheap eligibility before costly chronology/follow-up work.
- Uses bounded chronology merging; no global sort of all game history.
- No API calls, Stockfish searches or PGN reparsing.
- Uses the checked solver from the successful environment v1.0.2 release.
  It checks finite values, convergence and FE orthogonality; no row deletion,
  ridge or covariance repair is used to force a result.
- Atomic, authenticated stage checkpoints; current-stage timings/ETAs and
  model memory reservations are printed. A reused stage may finish quickly.
- New output namespace: derived/replication/run2_phase50_analysis_v100_PRIVATE.
  Source data, older result folders and the downloader are not modified.

REQUIRED EXISTING INPUTS
The completed 25% v1.2.2 analysis at 79bd3599a995 and its authenticated sources,
plus the completed 50% download snapshot. Prior cached history/score features
are reused by their exact original definitions. SciPy is not required.
The default project is /Volumes/XT_Pro/lichess_kindness and Python is its
venv/bin/python. Optional flags: --workers 10, --memory-gb N, --project-root
PATH, --desktop PATH, --plan PATH. Only increase memory if physical RAM allows.

OUTPUT TO RETURN
RUN2_PHASE_050_ANALYSIS_REPORT_<run>.zip and its .sha256 sidecar, from the
Desktop folder. Coverage-only and partial-model reports use the same name
and are replaced as the run progresses. The final status is
PHASE_050_AVAILABLE_CASE_ANALYSIS_COMPLETE.

Read estimates.csv for primary ordinary90_placebo/y and entry90_pooled entry
outcomes, cohort new_phase50. Compare increment_25_50 and new_phase25.
Read secondary_competitive_estimates.csv for ordinary-game score comparisons
and the fixed upper-tail sensitivity. Read competitive_entry_estimates.csv,
competitive_entry_support.csv, competitive_entry_contrasts.csv and
competitive_entry_transitions.csv for entry support and the control ladder.
The report includes numerical audits, performance, author exclusions,
quarantine accounting, sample flow and the 25% feature/numerical bridges.

VALIDATION LIMIT
The release is tested here on synthetic data and its actual ZIP launcher.
Private Mac production inputs and 50% behavioral estimates are not available
here. Production checks run before interpreting any new result.

VERSION 1.0.1 VALIDATION
The regression, score and chronology code is unchanged from v1.0.0. New tests
cover three-record accounting, a clean response conflicting with cached data,
changed/extra flags, invalid phase membership, missing/duplicate responses,
retained flagged rows, exact coverage reuse, and tampered source rejection.
