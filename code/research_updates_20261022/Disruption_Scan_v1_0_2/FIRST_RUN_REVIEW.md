> Historical review of the first ten-month scan. The subsequent preflight resolved the schema question: player names are present under legacy names. See PREFLIGHT_REVIEW.md and README.md for the current v1.0.2 instructions.

# Disruption scan: first results and next steps

Your proposed pattern is visible in the data. The scan found large bursts across unrelated games, replicated in disjoint sets of player accounts, and several coincide with a collapse in archived game starts. This is promising evidence of shared disruptions. It is not yet independent verification of particular outages, or evidence that receiving kindness was randomly assigned.

## What ran

The returned run completed in **438.4 seconds**. It analysed **71,278,329** eligible real-time game records from **October 2024 through July 2025**, using the broader API time-forfeit frame rather than only the kindness-choice panel. The screen found 1,964 overlapping threshold crossings and retained its prespecified top 30 episodes. **All 30 replicated in disjoint player accounts.** Neither kindness outcomes nor later transmission entered their selection.

The report ZIP checksum passed, archive integrity passed, and its package manifest exactly matches the delivered v1.0.0 package. Accepted source months passed the game-ID, duplicate-ID, timestamp-alias and creation-month checks. No selected episode triggered the account-concentration flag. The largest account share across the discovery/validation candidate samples is 1.08%; no candidate-sample timestamp falls exactly on a minute boundary. These diagnostics reduce concern about a few repetitive accounts or simple timestamp rounding, but cannot rule out a shared recording artifact.

The 1,964 crossings are not 1,964 distinct incidents. The top 30 are a selected list, not an estimate of outage frequency. Replication confirms the temporal pattern across accounts; both groups still share the same platform and archival sources.

## The distinction that matters for this paper

| Candidate, UTC | What the returned data show | Main-sample choices in screen window | Competitive choices |
|---|---|---:|---:|
| E001: 20 May 2025, 05:58 | 4,796 broad-frame records in one minute; 4,773 are `outoftime`. Zero archived starts for 19 consecutive minutes afterwards. | 18 | 10 |
| E002: 30 October 2024, 13:23 | 10,253 records in the five-minute screen window; 5,540 are `timeout`. Discovery and validation counts are 9.42 and 9.20 times baseline. | 4,720 | 3,248 |
| E003: 18 January 2025, 17:12 | Large burst followed by 12 consecutive minutes of zero archived starts. Mostly `outoftime` records. | 63 | 24 |
| E011: 16 December 2024, 23:43 | 1,641 records in one minute, including 1,039 `timeout` records. | 872 | 631 |
| E013: 30 October 2024, 09:28 | 1,714 records in one minute, including 921 `timeout` records. | 819 | 524 |
| E017: 22 December 2024, 15:53 | 1,706 records in one minute, including 934 `timeout` records. | 814 | 547 |

Counts in the table cover all speeds in each frozen time window, even where the detection series was rapid only. `outoftime` is the clock-expiration category; `timeout` supplies the paper's recorded claim/draw resolutions. A terminal status alone does not establish who remained connected or whether the interface worked normally during an incident.

**E002 is the strongest immediate lead for studying kindness choices.** Its frozen window is 13:21:00–13:26:00 UTC. Archived starts fall to 737 per minute against a same-time weekly baseline of 2,715 at the trough. Within its main-sample choices, median remaining clocks are 223 seconds for choosers and 220 seconds for disconnected players. The count, activity decline and clock availability make this a useful incident to investigate. They do not prove all 4,720 choices were caused by a common outage.

**E001 is particularly striking evidence about platform activity, but supplies very few kindness choices.** The zero-start interval is 05:59–06:17 UTC inclusive. Its 18 main-sample observations could include ordinary background disconnections. Severe shared outages can prevent both sides from acting; their very severity can make them less useful for identifying kindness behaviour.

Three other candidate plots remain at zero starts at the end of their available +60-minute context: E004, E012 and E016. Their observed zero spans are lower bounds within those plots, not complete outage durations.

Across the 30 non-overlapping screen windows there are **12,872 main-sample choices**, including **8,399 competitive** and **2,941 clearly-worse** choices. These are availability counts, not grant counts or treatment effects. E002 alone accounts for 38.7% of competitive choices, so eventual estimates need an explicit check excluding this episode. Narrow screen windows also need not capture every game affected by an incident.

## What this can establish

The useful research question is whether the paper's patterns persist among games exposed to a verified shared interruption, where a player's decision to abandon a bad position is a less compelling explanation for the disconnect. Exposure during an incident can still be selective; a timestamp window contains background events as well as incident-induced ones.

Board position should remain in the analysis. Knowing that an interruption was accidental does not make granting a draw equally justified in an equal position and a clearly lost position. There is also no unconditional prediction that choosers become more generous: they may never learn about the disruption.

For transmission, a verified incident could provide a different sample for the existing receipt design. It does **not** randomise the opponent's grant decision. Using the outage itself as an instrument for kindness receipt would require addressing direct effects on frustration, subsequent activity and later choice opportunities. Those channels are especially plausible in the episodes with collapsed game starts.

## Next research steps

1. **Verify incidents and decision availability.** Begin with E002 and the other episodes with substantial recorded choices, while retaining the frozen list. Obtain independent incident timing and distinguish planned restarts, unexpected platform failures and regional connectivity problems. Check whether surviving/reconnected players could actually use grant/claim and whether server-side resolution rules changed. Public-source searches in this review did not yield usable independent confirmation; no episode is certified here.
2. **Define exposure before examining grant rates.** Use corroborated incident boundaries and, where available, games active immediately before onset. Keep the narrow detection window and broader incident exposure window distinct. Audit whether outcomes are human choices; identify ordinary background events in the window as an unresolved mixture rather than assuming all exits are involuntary.
3. **Retain board position and compare composition.** Examine board-state, ply, clocks, speed and rating distributions around verified incidents versus comparable ordinary periods. Then report grant rates by board state, with matching/controls and chooser effects where supported. Show individual episodes and pooled results, with uncertainty accounting for shared shocks and repeated accounts. A changed gradient is informative; an unchanged gradient is informative too.
4. **Assess transmission feasibility before promising an estimate.** Count actual receipts, later opportunities and instrument support within the verified sample. Apply the existing opponent-prior-grant design only if its first stage and exclusions remain defensible. Report subsequent participation as well as later kindness, and show leave-one-incident-out sensitivity. Thousands of choices do not necessarily yield many kindness receipts or precise transmission estimates.

The structural model can eventually use verified disruption exposure to model selection into opportunities separately from the grant decision and from subsequent receipt responses. It should not set the involuntary-exit probability to one solely because the screen detected a spike, or force the board-position effect to disappear.

## Coverage issue and supplied correction

The requested panel is November 2023–October 2025, but this run covered ten months. Nine earlier monthly paths were wrongly rejected because v1.0.0 interpreted date ranges in parent folder names as competing month labels. That is a parser bug in the supplied code. **v1.0.1 fixes it by using the explicit monthly lookup directory.**

There is a separate schema limitation: February and June 2024 were located but their legacy tables lack recognised white/black player fields. Other old months may have the same limitation. August–October 2025 had no eligible canonical API sources found by the scanner. Fixing the parser alone therefore does not guarantee full coverage. The ten accepted months and their reported events are unaffected by that parsing error.

Run the supplied v1.0.1 package with `--preflight-only` first. It records exact legacy field names/types and monthly footer counts without reading data rows, scanning the large chronology, contacting the API, or repeating the event search. The resulting report will show what remains necessary to extend coverage. Missing account fields are not guessed, and no choice-only source is substituted for the broad frame.

The correction passes 16 tests, including the returned parent-directory naming pattern, explicit reporting of missing legacy player fields, and the original screening/validation safeguards. Production re-execution must take place on the Mac holding the source data. v1.0.1 preserves the original run and writes a separate cache tree.

## Evidence

Reviewed report: `DISRUPTION_SCAN_REPORT_20260920T044816426331Z.zip`.

SHA-256: `28b34f16b2c7514493ebabdc643034cb6d96da0a1826b0067e92ab054cb6057b`.

Numerical sources: `RUN_STATUS.json`, `ranked_candidates.csv`, `episode_plot_data.csv`, `episode_timestamp_and_pair_audit.csv`, `episode_account_support.csv`, `main_sample_choice_availability.csv`, `api_month_coverage.csv`, `input_discovery.json` and `traffic_coverage.json`. Original figures E001–E003 and a derived 30-episode metrics table are included in v1.0.1. No kindness-outcome analysis was run in this review.
