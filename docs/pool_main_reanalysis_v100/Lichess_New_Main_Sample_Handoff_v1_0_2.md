> Repository edition of the corrected September 11 handoff. The narrative below
> was prepared for the complete handoff bundle and describes that bundle's paths.
> For the public subset and repository path mapping, read [README.md](README.md).
> Historical drafts, the old repository snapshot, runtime logs and the full handoff
> ZIP are not part of this repository edition. The active sample is 41,534,331.

# Lichess kindness paper: comprehensive handoff for the new main sample

Evidence cutoff: the 11 September 2026 C9 ply return dated 18:14 UTC. Revision v1.0.2 applies Ravi's subsequent clarification that the new sample is primary. Author: Ravideep Sethi. This is a research and writing handoff, not a revised manuscript or a declaration that every analysis is complete.

## 0. Main sample: confirmed by Ravi

**The main sample is the new 41,534,331-opportunity pool / observed-nonadjacent panel.** Ravi clarified: “to be clear, its the new 41 million sample that should be main.” This instruction supersedes the earlier handoff's mistaken treatment of the old sample as primary. The old September 3 draft is the text to rewrite; its 47,587,020-opportunity sample is historical comparison only.

The practical instruction to the next writer is:

> Rewrite the September 3 TeX draft using the certified 41,534,331-opportunity main sample and the completed new-sample reports. The main panel has 570,091 kind draws; its competitive subset has 15,207,423 opportunities and 419,463 kind draws. Use the new results throughout the abstract, main text, tables, figures and retained appendix analyses. Preserve model-specific estimation samples and history contracts. Use old-sample evidence only when explicitly labeled as historical comparison. An old result must not fill a missing new-sample result, and an old figure must not be relabeled with the new N. Begin writing supported sections now; keep unresolved claims out of the final narrative until they are estimated or removed.

Main-sample fingerprint: `a17c89d750cb4fdfdf84f950859e45c58b19996efae02045def68285e305cf30`. The operational predicate is `source = 'pool' AND previous_classification_status = 'not_mutually_adjacent_observed'`. This is the observed nonadjacency screen; it does not certify literal end-to-start rematches or lifetime stranger status.

The substantive implications are already reflected in the new-result sections below: use the exact C7R interaction-derived first/repeat gradients; report the C7X support failure instead of the old adjusted effect; retain the IV selection diagnostics; use the completed C6/C9 ply and Patron results. New-sample C13 has code but no returned result. Exact full family-D reconciliation remains open, although conservative five-slot C6/C9 decisions are available. The supplied old figures and old closeout are provenance and layout references, not current main-sample exhibits.

### Files supplied with this handoff

- `Lichess_New_Main_Sample_Handoff_v1_0_2.md`: this main document, with definitions, findings, caveats, decisions, and next actions.
- `MANUSCRIPT_CHANGE_MAP.md`: every section/table/figure label in the supplied draft, with the replacement authority and action.
- `RESULT_CATALOG.md` and `RESULT_CATALOG.json`: searchable inventory of the extracted aggregate results, including exact relative paths, hashes, and table dimensions.
- `SELECTED_RESULTS.json` and `SELECTED_RESULT_TABLES.md`: exact selected result rows; these complement, rather than replace, the unabridged reports.
- `ARCHIVE_VERIFICATION.json`: supplied ZIP identities, sidecar checks, CRC results, and manifest accounting.
- `RUN_COMMANDS.md`: complete Mac commands, expected runtime, and restart guidance.
- `SOURCE_PACKAGE_INDEX.md`: delivered runner packages and their SHA-256 values, plus the local repository snapshot used for historical source recovery.
- `draft_source/`: unchanged supplied TeX and the September 1 state/index documents.
- `old_sample_closeout/`: extracted September 2 closeout, including all five original-sample main figures, exact Holm table, compact framework replacement, appendix table bodies, source audit, and merge instructions.
- `old_repository_snapshot/`: relevant public results, documentation, and source code from the locally available repository checkout; this is a historical source snapshot, not a statement about the current remote HEAD.
- `results/`: complete extracted current result bundles, identified by short aliases below.
- `evidence_archives/`: original supplied ZIPs, including superseded returns retained as provenance.
- `source_packages/`: delivered analysis runners, including the prepared C13/family-D package. Their presence does not mean they have been run.
- `prior_reviews/`: earlier review notes and draft fragments, retained with their dates. Their lists of “remaining” work must be reconciled against this handoff.
- `VERIFY_HANDOFF.py` and `HANDOFF_MANIFEST.sha256`: offline byte verification of this delivery. No private analysis is rerun by the verifier.

The evidence includes aggregate coefficient Parquets. These are public model/table outputs, not the 41.5- or 47.6-million-row private panel. Account/game histories, profile snapshots, private randomization arrays, and matching identities remain on XT_Pro.

## 1. Decisions and priorities inherited from the conversation

1. Ravi wants to start writing soon. Prioritize analyses that could change the central claims; do not initiate another broad mechanism campaign to postpone drafting.
2. The original task was to redo every analysis after restricting the main sample. That work progressed through Waves 1, 2A, 2B1, 2B2A, 2B2B1, and Patron Waves 3A/3B1/3B2, with separate IV, C7R covariance, C9, and C9-ply branches.
3. Ravi has confirmed that the new 41,534,331-opportunity sample is primary. Rewrite the old draft using this numerical authority throughout. Retain the old 47,587,020-opportunity results only as historical or explicitly labeled comparison evidence.
4. C13 and Campaign family-D reconciliation were explicitly requested. A tested package has been delivered, but **no completed new-sample C13 return is available in this conversation**. Do not describe it as estimated.
5. Do not reopen quarantined C1 lineages merely to fill a Holm table. The genuine corrected historical C1 and its documented receipt are a separate authority from invalid Run A/Run B. The new C13 package does not estimate C1, C2, or C5.
6. Always provide complete Terminal commands and an expected runtime when asking Ravi to run something. Files are saved to `~/Desktop/Lichess_Desktop`; data/output roots are on `/Volumes/XT_Pro/lichess_kindness`.
7. Use up to ten workers where the algorithm supports it. Respect existing job locks. Preserve successful checkpoints, failed model attempts, and original certified outputs.
8. No raw-data acquisition, new profile fetch, 36-month expansion, chat/takeback acquisition, or separate rating-redesign research is necessary to prepare this rewrite handoff.
9. This handoff performs read-only verification and compilation of existing evidence. It does not execute a new private-data regression, change a sample definition, edit the supplied draft, push Git, or publish the paper.

## 2. Evidence hierarchy and status language

Use this order when sources disagree:

1. The exact result file and its sample, estimand, support gate, execution receipt, manifest, and source bindings.
2. Later corrections or numerical/serialization-only closure receipts for that same result.
3. The appropriate sample certificate and authenticated input histories.
4. The September 2 old-sample manuscript closeout, final Patron authority ledger, and later result-specific reviews.
5. The September 1 `LICHESS_KINDNESS_CURRENT_STATE.md` and pipeline index.
6. The TeX draft and comments from other AIs.

The September 1 documents are valuable but no longer a live completion ledger. In particular, the September 2 old-sample closeout supplies the Figure 2 authentication, exact old Holm table, A3 continuation numbers, S/T dispositions, and count corrections that the September 1 memo still calls open. The subsequent pool-sample returns supersede many new-sample “pending” notes in earlier reviews.

Use distinct statuses:

| Status | Meaning |
|---|---|
| Original-sample result | Applies to the original 47,587,020-opportunity population or an explicitly described subset of it. |
| New-sample result | Rebuilt under the certified pool / observed-nonadjacent sample and its relevant history design. |
| Completed with retained failures | The planned attempts finished; one or more fits were unsupported/nonconvergent and remain so. |
| Post-hoc / exploratory / X | Outcome-informed diagnostic or analysis outside the specified confirmatory family. |
| Prepared, not returned | Code and tests exist; there is no completed private-data result in hand. |
| Historical or superseded | Useful provenance, but not an active numerical authority for the chosen manuscript population. |
| Invalid | A known semantic or numerical failure; not a robustness estimate to be interpreted. |

Checksums establish byte identity, not scientific validity. A success marker can legitimately accompany retained unsupported models. The report verifier checks transferred aggregates; it cannot independently recompute private row-level joins or 4,999 private draw arrays that were not transferred. Execution receipts can attest to those checks and must be described as receipts, not as a new independent local reproduction.

## 3. Setting, measurement, and dictionary

### 3.1 Window, units, and outcome

- Window: **1 November 2023 through 31 October 2025 UTC**, 24 months.
- Production engine: **Stockfish 18, 100,000 nodes** at the final observed position. The 10,000- and 2,000-node layers are historical; million-node work is an audit rather than the full production panel.
- Unit: a rated standard game ending through the relevant disconnect-resolution path. Rates over opportunities are game/opportunity weighted. Do not call them equal-account average propensities.
- API `status = timeout` identifies the active-resolution opportunity set. A PGN `Time forfeit` label is only a candidate screen. API `outoftime` is a different outcome path and is excluded from the behavioral opportunity panel.
- Five-second floor: the disconnected account had at least five seconds on the last observed clock. The historical audit of sub-five-second candidates is not a fresh 24-month/new-sample certification.
- Chooser: the connected account, the last mover. Disconnected account: the other player, on move after the final observed move.
- Kind draw: a draw through this path while the connected chooser retained the relevant mating material. Preserve the actual producer's material/role/status screens; do not relabel every draw after a clock-related termination as a kind draw.
- A timeout result is not literally a perfectly binary claim/grant variable in every source accounting table: the old closeout records 75 other chooser-loss outcomes. Preserve these in accounting rather than force row conservation by inventing claims.
- Account identity is observed; unique human identity is not. Prefer “accounts” or “choosers” where this matters.
- `api_last_move_at_ms` is a decision/exposure timing anchor used by many models. The all-rated-game chronology has game-start ordering. Distinguish last-move time, start time, and actual game end.

### 3.2 Board merit

Evaluation is from the **disconnected opponent's perspective**, not the chooser's.

| Label | Centipawn range |
|---|---:|
| Clearly better | ≥ +300 |
| Better | +101 to +299 |
| Roughly equal | −100 to +100 |
| Modestly worse | −299 to −101 |
| Clearly worse | ≤ −300 |
| Competitive / fair | ≥ −100; the first three bins combined |

“Competitive versus clearly worse” excludes the modestly-worse middle region from that two-category contrast. “Equal versus better” in the rebuilt equality ladder compares roughly equal with the adjacent +101 to +299 bin; it is not a comparison with all positive-evaluation positions pooled. The new ladder's 12,164,174 rows equal 9,244,704 roughly-equal plus 2,919,470 better opportunities.

Engine evaluation zero, equal displayed ratings, and zero reconstructed draw payoff are different variables. They must never share a count or label merely because each is called “zero.”

### 3.3 Rating variables and the price distinction

The notation in the draft is:

- `x = opponent displayed rating − chooser displayed rating`; positive x means the disconnected opponent was stronger.
- `r_G = K(1/2 − E)`: chooser's nominal rating change from a draw, where E is the chooser's expected score.
- `r_C = K(1 − E)`: chooser's nominal win payoff.
- `κ = r_C − r_G = K/2`: forgone-win premium.
- Pre-game rating deviations and reconstructed payoff fields belong to the v2 cost layer. Preserve the exact replay/rounding/update definitions.

Do not call `r_G` the cost relative to claiming; the relevant forgone increment is κ. Do not call either a randomized monetary price or a measured welfare loss. Rating accuracy, sportsmanship, dislike of hollow wins, and account uncertainty can all matter. `K` is strongly linked to the chooser's rating uncertainty, so its association with kindness is not a causal cost elasticity.

An adjacent displayed-gap level contrast and a fitted slope difference against the payoff axis answer different questions. A small tie-versus-minus-one estimate is not a test that all payoff slopes are equal. Section 8 below is essential for the rewrite.

### 3.4 Privacy, defaults, and external supports

The setting is private in a bounded sense: the disconnect action has no dedicated public prosocial badge and is taken while the opponent is absent. It is not permanently unknowable: game records, ratings, persistent usernames, and prior acquaintance can reveal information. Chat history, prior requests, takebacks, off-platform relationships, and unique-person identity have not been certified absent by these analyses.

Do not describe every `outoftime` as a deliberate choice to wait, every non-grant as selfish intent, or the entire platform population as having actively refused kindness. Waiting can end with reconnection and continued play; clock expiration does not by itself reveal attention or intent. The original sample includes non-pool sources, so it cannot be introduced as if every game came from anonymous pool matching.

Patron status is a current same-platform supporter marker. It may be self-funded, gifted, or platform-awarded. It is not observed personal donation expenditure, an adoption date, or generosity outside Lichess.

## 4. Main-sample authority and historical comparison

### 4.1 Confirmed main sample: pool / observed-nonadjacent

Certificate: `POOL_MAIN_SAMPLE_24M_CERTIFIED_OK`.

Exact predicate:

```sql
source = 'pool'
AND previous_classification_status = 'not_mutually_adjacent_observed'
```

Root:

`/Volumes/XT_Pro/lichess_kindness/derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE/panel`

Certified sample-report ZIP SHA-256:

`917aa14ed8a8dbb7e82f9af1424aae079797edf4b1b06a4c27de084aca102c57`

Sample fingerprint:

`a17c89d750cb4fdfdf84f950859e45c58b19996efae02045def68285e305cf30`

| Quantity | New pool / observed-nonadjacent sample |
|---|---:|
| Opportunities | 41,534,331 |
| Kind draws | 570,091 |
| Kindness rate | 1.372577784% |
| Competitive opportunities | 15,207,423 |
| Competitive kind draws | 419,463 |
| Competitive kindness | 2.758277980% |
| Choosers | 3,224,173 |
| Competitive-state choosers | 2,442,576 |
| Ever-kind accounts | 276,482 |
| Ever competitive-kind accounts | 212,859 |
| Mean chooser / opponent rating | 1448.803 / 1444.874 |
| Mean ply | 40.8135 |

The transition table is important:

| Population | Opportunities | Kind draws | Kindness | Fair kindness |
|---|---:|---:|---:|---:|
| Original | 47,587,020 | 669,503 | 1.40690% | 2.81144% |
| Pool only | 44,138,221 | 606,657 | 1.37445% | 2.77159% |
| Pool / observed-nonadjacent | 41,534,331 | 570,091 | 1.37258% | 2.75828% |
| Pool / restore missing predecessor records | 41,889,951 | 575,873 | 1.37473% | 2.76495% |

Mutually exclusive exclusions from the original panel: 3,448,799 not-pool; 2,247,688 pool adjacency candidates; 582 pool ambiguous-order records; 355,620 pool missing-predecessor records. Retained plus exclusions sums to 47,587,020. These are construction/descriptive counts. The restored-missing variant has not received every downstream regression/history/Patron rerun.

### 4.2 Historical original sample: comparison only

Root on the Mac:

`/Volumes/XT_Pro/lichess_kindness/derived/replication/analysis_panel_24m_sf100k`

Certificate: `STAGE07_24M_CERTIFIED_OK`. The later descriptive closeout validates 24 monthly Parquets and the input-manifest SHA-256 `45dcbfbf2817680d5dc76295a5464c2deb3651befa0c1a9d88bba41750f61da6`.

| Quantity | Original sample |
|---|---:|
| Opportunities / distinct game IDs | 47,587,020 |
| Kind draws | 669,503 |
| Kindness rate | 1.406902555% |
| Competitive opportunities | 17,328,130 |
| Competitive kind draws | 487,170 |
| Competitive kindness | 2.811440127% |
| Choosers | 3,556,701 |
| Competitive-state choosers | 2,685,525 |
| Ever-kind accounts | 326,468 |
| Exactly one kind draw | 220,714 |
| Ever competitive-kind accounts in Stage 07 | 248,963 |
| Exactly one competitive kind draw | 169,591 |
| Mean chooser / opponent displayed rating | 1459.549 / 1450.409 |
| Mean ply | 41.1014 |

The Patron main matched sample has **248,930** fair-kind accounts, not 248,963: these are different populations because of profile availability. Do not substitute the matched count into the panel description.

Original active-resolution accounting in the September 2 closeout: 170,648,691 clock-screened disconnect candidates = 47,587,020 active timeouts + 123,061,671 outoftime. Active share 27.88596%; kind draws are 1.406903% of active opportunities and 0.392328% of all screened candidates. The draft's approximate “three times as many” passive endings refers to this old construction. It is not a certified corresponding ratio for the new restricted sample or all rated games.

The old count of 2.23 billion rated games is an upstream contextual denominator in the manuscript. Preserve its documented window/source and do not treat it as the new pool/nonadjacent universe. Never equate all-game chronology records with final opportunity counts.

### 4.3 What “nonadjacent” does and does not certify

Ravi defines a rematch as the same players playing again immediately after their previous game ends. The certified predicate uses **observed predecessor adjacency**, not a certified end-to-start timing definition. Therefore:

- Say “pool games passing the observed nonadjacency screen,” or explain the operational rule once before using a short label.
- Do not say “all rematches removed,” “only strangers,” “never met before,” or “random pairing certified.”
- Pre-focal first/repeat flags use earlier rated history and differ from this adjacency screen.
- Whole-window singleton-dyad restrictions use meetings both before and after the focal event; they are descriptive sample restrictions, not purely pre-focal recognition tests.
- Changes between original and new estimates reflect joint source/adjacency/population selection. They do not identify why a coefficient became larger or smaller, and the nested rerun is not an independent replication.

## 5. Historical original-sample inventory: never use as a missing main-sample replacement

This section records the old draft's evidence and corrections for provenance and explicit comparisons. The active manuscript authority is the new sample in §§6–15. Imperatives describing old specifications below concern accurate historical reporting; they do not authorize retaining those numbers as current main results.

### 5.1 Board merit and game stage

| Disconnected opponent's position | Opportunities | Kind draws | Kindness |
|---|---:|---:|---:|
| Clearly better | 3,517,357 | 128,259 | 3.6465% |
| Better | 3,314,026 | 80,471 | 2.4282% |
| Roughly equal | 10,496,747 | 278,440 | 2.6526% |
| Modestly worse | 4,168,727 | 51,492 | 1.2352% |
| Clearly worse | 26,090,163 | 130,841 | 0.5015% |

Competitive versus clearly-worse: +2.30994 pp; ratio about 5.606. The ordering of the raw roughly-equal and better bins is not itself an equality preference.

Original equality ladder as reported in the draft/structural authorities: raw +0.224 pp; chooser FE +0.087; speed/month/premium/clocks +0.003; game stage −0.411; long games −0.374; short games with exact-ply FE −0.207. These estimates come from particular specifications; do not describe sequential coefficient changes as an identified causal decomposition of the original premium.

Original competitive ply ≤4: 1,815,903 opportunities, 80,321 kind draws, 4.423199%. The closeout's ply=2 count **788,526 / 39,970** is all states. The sample-comparison report gives **786,565 / 39,869** competitive ply=2 opportunities, rate 5.068748%. The draft's statement treating 788,526 as a competitive-only count requires correction. Original fair ply >10: 13,198,918 opportunities, 330,651 draws, 2.505137%. Use the source's exact bins rather than recomputing a short-game count by rounding a percentage.

Original roughly-equal raw rates by ply in the draft: 4.43% at ≤4, 3.52 at 5–6, 3.22 at 7–8, 2.98 at 9–10, 2.53 at 11–20, 1.84 at 21–40, 1.41 at 41–80, and 1.96 beyond 80. The old within-chooser ply-band coefficients, clock coefficients, and terminal-position explanation must remain tied to their old source table. The claim that long nominally drawable positions fully explain the final-band rebound is a measurement interpretation, not an independently established causal decomposition.

### 5.2 Later old-sample census of first/repeat meetings

The September 3 draft uses a 1-in-50 sample of 951,517 opportunities, repeat share 12.60%, and frozen C7R v1.0.2 adjusted contrasts: first +1.567 pp, repeat +1.334, interaction −0.009 (p≈.94). The standalone first/repeat fits and the pooled interaction are not the same regression: subtracting the two standalone coefficients need not equal the pooled interaction.

A **September 5 full-panel census exists** in `old_repository_snapshot/results/c7r_fullpanel_prefocal_v100/20260905T122501Z/`. It was completed on the old 47.6-million panel and is historical comparison evidence:

| Old full-panel census | First meetings | Repeat meetings |
|---|---:|---:|
| Opportunities | 41,597,026 | 5,989,994 |
| Overall kindness | 1.397987% | 1.468816% |
| Competitive opportunities | 15,150,556 | 2,177,574 |
| Competitive kindness | 2.796736% | 2.913747% |
| Clearly-worse kindness | 0.493517% | 0.556353% |

Overall repeat share 12.587453%; competitive 12.566699%; clearly-worse 12.696912%.

The old census's **minimal chooser-FE** interaction model uses 43,418,293 competitive/clearly-worse rows and 3,475,075 chooser clusters. First gradient +2.172249 pp (SE .009121); repeat +2.202755 (SE .016556); repeat-minus-first +.030507 (SE .014987, normal p=.04179). This is a tiny positive gap at repeats, not the new sample's negative interaction. Do not call these coefficients an exact reproduction of the v1.0.2 control-rich sampled family.

For a historical comparison, the old control-rich sampled table and old full-panel census must be labeled as distinct specifications. The rewritten main table uses the new +1.59/+1.28 interaction-derived gradients and the new panel description, with its minimal-FE census as a separate check (§9). Neither observed-history definition establishes lifetime stranger status.

### 5.3 Relative strength and rating benchmarks

Old nonparametric roughly-equal, ply>10 curve relative to the near-equal displayed-rating bin: −.293 pp at −50; −.440 at −100; −.518 at −150; +.150 at +50; +.278 at +100; +.451 at +150; +.492 at +200; +.700 at +300. The old same-chooser common-support weaker/stronger contrasts are about −.401 (SE .055) and +.638 (SE .073).

The September 2 closeout authenticates the two-panel Figure 2 and its source data. The exact adjacent-gap results are tie versus −1 +.018984 pp (t=.2983), +1 versus −1 −.009358, and tie versus −1 after ply 10 +.061334 (t=.8648). Twenty-three of 24 nonreference contrasts lie within .14 pp. Gap +8 is +.206789 pp, raw p=.014284, Holm p=.342820. The old Figure 2 authority excludes a year-two inset because that source recovery gate was not certified; do not restore that inset from an older plotting folder.

Old K associations are approximately +.61 and +.65 pp per log unit; own-RD coefficients +.82 to +.89; opponent RD about −.06 (t≈−1.9); visible-magnitude slopes −.074/+.130; a separate framing comparison about +.02 (p≈.85). Preserve specification and units. These are conditional associations and shape diagnostics, not causal rejection of every cost motive. Section 8 gives additional reasons to revise the draft's categorical “no kink” wording even if retaining the old sample.

### 5.4 Persistence and receipt

Use the draft's **temporal** split, minimum four total competitive opportunities, for the headline original correlation: about .532 unweighted and .607 weighted by total opportunities. The draft incorrectly describes the cutoff as four in each half: the producer filters on `total_n >= 4` among accounts observed in both halves. Correct this for both sample branches. The September 1 memo's .590 is not an interchangeable temporal statistic. A hash/random split, a different opportunity threshold, and harmonic weighting produce other legitimate numbers; label each.

Old temporal prior-granter comparison: about 14.95% versus 1.04%, roughly 14.4 times. These are pooled later-opportunity kindness rates in groups defined by prior behavior, not the fraction of accounts who ever grant again.

Original A1 conditional next-competitive-choice association: +1.0047 pp, SE .1228, raw p≈2.81×10⁻¹⁶, N=1,029,558; weighted control mean 3.470%. The zero-for-nonreachers first-opportunity companion: +.458260 pp, SE .057765, p≈2.14×10⁻¹⁵, complete-follow-up N=2,185,073, 65,085 receipt / 2,119,988 claim, control mean 1.6243%.

The old exact A3 continuation numbers are already available: 30-day log game volume +.00337 (SE .00582, p=.563); rapid rated-game reentry +.8820 pp at 10 minutes, +1.0049 at 30 minutes, +.9660 at 60 minutes. These are resolved historical A3 values, not replacements for a missing new-sample reentry estimate.

Old A1 robustness reported in the closeout/draft includes state controls, overlap, finer cells, within-switcher comparisons, subsequent-ply restrictions, exposure-ply comparisons, nonbenefactor outcomes, censoring at a subsequent exposure, and a singleton-dyad check. Retain exact source and subgroup definitions. In particular, the old salience values +.50 / +.74 / +5.22 pp and bases 4.4% / 2.1% / 21.2% are not on a common proportional scale. A raw p=.11 cannot be a significant Holm result. The closeout explicitly rejects assigning the unrelated .0036/.0056/.0075 adjusted sequence to those three subgroup rows.

Old receipt lag-bin estimates are +1.669, +.892, +1.200, +.798, +.487 pp at ≤6h, >6h–1d, >1–7d, >7–30d, and >30–90d. They are not monotone. Horizon conditions on a post-exposure arrival process, so neither this profile nor a within-switcher result identifies a common causal decay parameter.

Old A1/salience/ply closure artifact: `KINDNESS_A1_SALIENCE_INVESTMENT_CLOSURE_RESULTS_20260831T165103Z.zip`, SHA-256 `f4596f5c283dc9f771b75499271bf89f4a0bf52a4d88cbde88588f1a06c91826`. The historical closeout documents it; do not pretend its entire original private execution has been independently repeated by this handoff.

### 5.5 Old targeted memory and S/T

The old selected relationship sample contains 2,208 benefactor-facing opportunities with 915 grants (41.4%) and 25,419 claimer-facing opportunities with 1,247 grants (4.9%). Approximate old controlled differences: pooled +34.7 pp; chooser FE +14.6 (SE≈2.0, 370 identifying accounts); directed-pair FE +13.0 (SE≈3.1, 160 identifying pairs). Horizon raw benefactor rates: 43.9%, 45.7%, 41.4%, 32.6%.

These are **exploratory/post-gate** results on selected re-meetings. They do not identify gratitude, causal reciprocity, or permanence. Sparse identification and concentrated repeated dyads are substantive limitations, not just footnotes.

The September 2 closeout records completed S/T work:

- S: deterministic 2% pair sample, 43,584 exposures, 1,283 receipt and 42,301 claim; 757 90-day re-encounters. Receipt-minus-claim re-encounter probability −.304 pp, SE .305, p=.318353. Only eight first role-reversed opportunities, all claim-arm; conditional transmission contrast unestimable.
- T: strict-stranger comparison has nine episodes/nine account clusters and is not estimated. Different-opponent companion has 428 episodes, 765 controls, N=1,193: +16.344 pp, account-clustered SE 2.020, p≈5.91×10⁻¹⁶. “Another opponent” is not equivalent to “a stranger.”
- Artifact: `SECTION5_ST_CLOSURE_V102_NUMERICAL_RECOVERY_RESULTS_20260901T202453Z.zip`, SHA-256 `47436c180de8ee763dc3d084e8f977d87768b6d2a75738e094f06d9c5e3f7b76`.

The new panel's support failure does not invalidate these old-sample estimates. It does show that this result is sensitive to the observed population and should not be used to characterize pool/nonadjacent encounters without qualification.

### 5.6 Old episodes, C6, C13, and Campaign family D

Old B1: 64,331 repeat granters, 1,017,944 opportunities, 273,483 grants. The 24-hour weighted grant-pair statistic is about 11,003 against a benchmark mean 8,408, raw p=.0004. B2 pooled subsequent-opportunity rates at 6h/24h/7d are about 51.7/49.7/43.2% against 33.9/33.1/31.6%. Correct the draft's “probability an account grants again” language and uniform-shuffle description; these are pooled opportunity-level rates under the implemented conditional-Bernoulli benchmark.

Old C9 later-session seven-day primary excess: **11.105202 pp**, raw p=.0004; approximate observed/null rates 42.55/31.44%. Old C6 primary: **−1.793743864 clearly-losing timeouts per 1,000 rated games**, raw p=5.3348432×10⁻⁷. The original-sample closeout retains explicit C6/C9 ply caveats. Newly completed restricted-sample ply checks do not erase those caveats for the original population.

Old C13 is available in `old_repository_snapshot/results/campaign1/nonprofile_recovery_v104/C13/`. Primary 28-day, leave-one-chooser-out, speed×rating-cell association: **+.082115256 pp per +1 pp ambient kindness**, SE .053335239, p=.1236564; N=17,101,141, chooser clusters 2,656,510. Adjusted fourth-minus-first quartile: +.075354113 pp, SE .044791765, p=.0925067. Nineteen model attempts: sixteen estimated, three retained failures. The old full run took 16,763.856 seconds. The coefficient is an imprecise conditional association, not proof of no ambient or observation mechanism. The conventional 95% primary interval is about [−.0224,+.1867] using the exact coefficient/SE; the closeout's [−.0219,+.1859] used rounded .082/.053. Use exact arithmetic in the rewrite and label a two-sided interval, not an equivalence test.

The old signed family-D table is present in the September 2 closeout:

| Member | Original raw p | Original Holm p | 5% rejection |
|---|---:|---:|---|
| C6 | 5.334843209911397e−7 | 2.667421604955698e−6 | Yes |
| C9 | .0004 | .0016 | Yes |
| Corrected C1 | .006046717201351934 | .018140151604055802 | Yes |
| C2 | .0363121 | .0726242 | No |
| C5 absent slot | 1 by documented closure rule | 1 | No |

Receipt: `CAMPAIGN_FAMILY_D_HOLM_SIGNED_OK`; CSV SHA-256 `f87d17e34aef11e4ebe3668da0f96b512575dfc51238cf7da6a28a99d95ca4ef`. This is an old-sample table. Do not reuse its adjusted values with new C6/C9/C1 coefficients.

Corrected old C1 is +.176413 pp and belongs only to corrected v1.0.5. The exposed +.245 and −.831713 lineages misread chronology result codes and are invalid. C2 is approximately −.134742 pp, opposite its prespecified sign and not significant after Holm. The signed old table does not authorize restarting a quarantined analysis or claiming a new-sample C1 estimate.

### 5.7 Original Patron evidence

Maintain the certified primary v1.0.1 and post-certification addendum v1.0.0 as separate old-sample lineages.

| Original Patron quantity | Value |
|---|---:|
| Planned profiles / returned profiles | 1,305,872 / 1,305,683 |
| Missing outcomes | 189 |
| Current Patrons among returned profiles | 4,896 |
| Main matched fair-kind accounts / controls | 248,930 / 746,676 |
| Matched total / matching cells | 995,606 / 37 |
| Patrons among fair-kind / controls | 1,577 / 2,448 |
| Rates | .6335% / .3279% |
| Raw difference | +.305658 pp |
| Match-cell FE difference | +.305661 pp; HC1 SE .017211; CR1 SE .038582 |
| Fully adjusted main association | About +.2701 pp |
| Two-state fair-kind / clearly-worse-kind coefficients | +.3835 / −.1804 pp |
| Two-state contrast | +.5638 pp; HC1 SE .0424; CR1 SE .0662 |
| Five-bin min-four endpoint, secondary addendum | About +.4532 pp |

The old 100 alternative-control-draw adjusted mean is +.2663 pp, range +.2456 to +.2907. Dose rates are .3141%, .4783%, .8492%, 1.3561%, 1.3002%, not strictly increasing at the last category. Do not confuse 326,468 panel ever-kind accounts with 326,427 returned any-state-kind profiles.

Old primary ZIP SHA-256: `84c3067272a5adec9a4bfdfb5b84ffb7d7df8c6230b8ca49b5e1c696107768fd`. Old addendum result ZIP SHA-256: `4a4b233b4d1a6ccb58f7668c8c00c7448d0c47c129eb93390cb75741f7f7ef5e`. The final old Patron ledger and results are in the included historical repository snapshot.

## 6. New-sample completion ledger

This is the active completion ledger for the rewritten manuscript. Use the new-sample authorities listed here; the old completion ledger cannot certify their replacements.

| Module | Latest returned authority | Disposition |
|---|---|---|
| Panel, counts, flow | `sample` | Certified operational screen; no literal end-to-start rematch certification. |
| Core structure, persistence, K/RD, relative-strength curves, controlled payoff plots | `wave1` | Rebuilt. Do not confuse module figures with the final assembled paper figures. |
| Equality/FEN, adjacent displayed gaps, 1500/RD diagnosis | `wave2a` late 03:16:57 return | Rebuilt; supersedes earlier 03:14:44 return for completion scope. |
| A1/A3/B1/B2, histories, E1/F2, audits, census C7R | `wave2b1` | Completed with module-specific labels and support restrictions. |
| Chooser-leniency IV and ordinary-game comparison | `iv` | Rebuilt; causal identification explicitly not certified. |
| Candidate entry and active-given-candidate | `iv_selection` | Complete post-hoc selection diagnostic. |
| Exact C7R family | `c7r` plus `c7r_cov` | Interaction and its repeat-gradient linear combination available; standalone failed fits retained. |
| C7X targeted memory | `c7r`, then dyad diagnostic in `c6_c12` | Failed parent support gate; no adjusted new-sample result. |
| C6/C10, C6 ply, C12 | `c6_c12` | Complete; C12 highest-rating subgroup unestimable. |
| C9 fresh primary | `c9` | Original 30-minute-session benchmark rerun with fresh 4,999 draws. |
| C9 ply | `c9_ply` | Complete; original arrays reproduced by execution receipt; new conditional benchmark and masks estimated. |
| Patron design, missingness, core, remaining families | `patron3a`, `patron_gap`, `patron3b1`, `patron3b2` | Scheduled Patron analysis gaps closed; August headline and September sensitivity kept distinct. |
| C13 | Prepared `Pool_Main_C13_FamilyD_v1_0_0` | Not yet returned. |
| Campaign family D | Same prepared package | C6/C9 guaranteed decisions from conservative five-slot bounds; exact full new-family closure open. |
| New integrated TeX, all main figures/tables, abstract | No final integrated return | Writing/assembly remains. |
| Old A1 salience/ply-specific/singleton rows | No corresponding authenticated new replacement located in these returns | Do not carry them over merely because A1 core completed. |
| C9 15/60-minute session and singleton appendix cells | No new return | Rebuild if retained, otherwise omit or explicitly label historical. |

The last two rows are important. Neither a broad “all dynamics completed” label nor a keyword match to “salience” proves completion of the old receipt-salience subgroup family. F2 round-number/personal-best salience is a different module. This handoff found no new naive/experienced-decliner/prior-granter A1 table, nor the exact old A1 ply-threshold/singleton family, among the returned aggregate tables. Treat them as unverified/unreplaced rather than asserting they were never run anywhere on Ravi's machine.

## 7. New-sample structure, persistence, and relative strength

These are the main-sample replacements for the old draft. All percentages below are opportunity rates; differences are percentage points (pp).

| Board merit | Opportunities | Kind draws | Kind rate |
|---|---:|---:|---:|
| Clearly better | 3,043,249 | 108,837 | 3.576342% |
| Better | 2,919,470 | 69,801 | 2.390879% |
| Roughly equal | 9,244,704 | 240,825 | 2.605005% |
| Modestly worse | 3,662,090 | 44,072 | 1.203466% |
| Clearly worse | 22,664,818 | 106,556 | .470138% |
| All competitive bins | 15,207,423 | 419,463 | 2.758278% |
| All opportunities | 41,534,331 | 570,091 | 1.372578% |

Source: `results/wave1/modules/core_stage08/tables/table01_fairness_bins.csv`. The competitive/clearly-worse ratio is about 5.87. The raw roughly-equal rate exceeds the adjacent better rate, so do not describe every raw bin as strictly ordered. The clearly-better peak and clearly-worse trough remain large.

Competitive game-stage accounting: ply 2 has 677,538 opportunities and 30,952 grants (4.5683%); plies 3–10 have 2,939,426 and 102,306 (3.4805%); past ply 10 has 11,590,459 and 286,205 (2.4693%). The game-stage composition is substantively important, not a cosmetic control.

### 7.1 Persistence

For the temporal split, at least four fair opportunities in total and observations in both halves, there are 666,131 choosers, 10,071,691 fair opportunities, and 245,374 grants in the selected rows. The unweighted correlation is **.545303391**; weighting by total opportunities gives **.617820266**; the harmonic-weight version is **.646977504**. The hash split with the corresponding threshold gives **.600417130**, a separate design. The old .532/.607 pair must not be replaced with two differently defined new weights.

Among previously non-granting accounts, the second half has 4,415,514 fair opportunities and 41,430 grants, rate **.938282610%**. Among prior granters, it has 465,662 and 73,685, rate **15.823709042%**. The ratio is about **16.9**, versus about 14.4 in the old draft. This is the later opportunity-weighted kindness rate grouped by prior behavior, not the probability that an account will ever grant again.

Sources: `results/wave1/modules/core_stage08/tables/tableA01_split_half_full_statistics.csv` and `table09_second_half_by_first_half_behavior.csv`. More persistent estimates under the new restriction do not identify whether source selection, adjacency removal, exposure composition, or another component caused the difference. The earlier claim that removing nonrandom pairings “should” sharpen persistence was too strong.

### 7.2 Relative strength within chooser

The common-support, equal-chooser-weight comparison is distinct from the smoothed FE curve. In roughly-equal positions:

| Comparison with similarly rated opponents | Estimate | SE | Choosers |
|---|---:|---:|---:|
| Weaker opponent | −.474329 pp | .081280 | 25,527 |
| Stronger opponent | +.560478 pp | .100421 | 22,466 |

In the adjacent better-position band, weaker/stronger effects are −.410176/.525494 pp (SE .157355/.161054). In the higher positive-evaluation comparison they are +.112071/.408424 pp (SE .202565/.182235); the weak-opponent estimate is imprecise. Preserve the support restrictions and band identifiers in the source table instead of claiming a universal signed effect in every state.

For the primary K≤20, ply>10, roughly-equal smoothed model, the curve relative to zero is −.469306 pp at −100 displayed-gap points (SE .023339), +.245277 at +100 (SE .026541), and +.430912 at +150 (SE .056301). These curve values are not the coarse same-chooser comparison estimates above.

Sources: `results/wave1/modules/rating_gap_nonparametric/common_support_chooser_equal_differences.parquet` and `fe_nonparametric_curves.parquet`. Other K/RD, node-budget, common-support, and payoff-surface tables are retained in the full module. Use them to document descriptive robustness, not to manufacture exogenous price variation.

## 8. Equality, the crossing, and the correction to the other-AI comments

### 8.1 The equality control ladder

The rebuilt contrast is roughly equal minus the adjacent better bin, 12,164,174 rows before model-specific restrictions.

| Specification | Equality coefficient, pp | SE, pp |
|---|---:|---:|
| Raw | +.214126 | .010962 |
| Chooser FE | +.066262 | .009225 |
| Modern analogue | −.016130 | .009249 |
| Added price controls | −.010694 | .009247 |
| Game-stage controls | −.400392 | .009437 |
| Interaction model, long-game component | −.383254 | See full table |
| Short-game interaction | +.664174 | .031351 |
| Short-game-only model | +.219088 | .033800 |
| Long-game-only model | −.371607 | .009843 |

The modern-analogue p is .0812; the price-control p is .2475. The raw equality bump is not a stable positive residual under the full game-stage adjustment. It is defensible to say that equal-looking board states are not an invariant special category. It is not defensible to claim that a particular psychological mechanism has been causally explained by the controls.

Source: `results/wave2a/modules/equality_fen/tables/equality_fe_models.csv`. The old appendix's exact-ply short-game specification is not automatically replaced by the new short-game-only row. Verify the specification before putting the numbers in the same row label. Engine-evaluation-zero placebo knots also reject away from zero; the exact-zero pattern is not descriptively unique. Position commonness/FEN models remain descriptive. An engine-zero result is not an equal-rating result.

### 8.2 Adjacent displayed-rating gaps: the level question

Rebuilt joint adjacent-gap model, baseline N=591,108, chooser clusters=106,964:

| Level contrast | Estimate, pp | SE | p |
|---|---:|---:|---:|
| Equal displayed ratings minus gap −1 | +.011691 | .065946 | .8593 |
| Gap +1 minus gap −1 | −.030794 | .068752 | .6542 |
| Equal ratings minus −1, ply>10 | +.064671 | .073461 | .3787 |
| Equal ratings minus −1, established ratings | −.004520 | .066939 | .9462 |

The full ±12 schedule has 23 of 24 contrasts within approximately ±.13 pp. Gap +8 is approximately +.251 pp with raw p≈.005, but Holm p≈.117. It occurs at the same location in a nested sample, so it is not independent replication of the old +8 anomaly. Preserve the multiplicity adjustment.

These estimates do not detect a discrete step at the displayed-rating crossing. A statistically nonsignificant contrast is not an equivalence result or proof that the exact population step is zero. The baseline tie estimate's approximate 95% interval is [−.118,+.141] pp, which conveys its precision better than “levels are flat” without qualification.

### 8.3 Controlled payoff model: a different estimand

The local controlled spline inside |r_G|<1 has N=10,116,759 and 1,223,918 chooser clusters. Its fitted side lines and separate exact-zero term give:

| Quantity | Estimate | SE | p |
|---|---:|---:|---:|
| Loss-side slope | +.324711772 | .112717664 | .00397 |
| Gain-side slope | −.167191273 | .112471395 | .1371 |
| Loss minus gain slope | +.491903046 | .076314993 | 1.15×10⁻¹⁰ |
| Fitted right limit minus left limit | +.054415442 pp | .020714533 | .00862 |
| Exact zero minus fitted left limit | +.142531170 pp | .035306447 | 5.41×10⁻⁵ |
| Exact zero minus fitted right limit | +.088115728 pp | .035414681 | .01284 |

Slope units are pp per unit of reconstructed nominal draw payoff; retain the source table's axis definition. Excluding both-displayed-1500 pairs gives a slope difference .491448302 (SE .076312965); restricting to established ratings gives .455126150 (SE .079399249).

The fitted limits extrapolate side functions to zero; they are not immediate-neighbor comparisons. The model has a condition number around 3.5×10⁷ and omits unsupported hinges within the narrow window. Report these properties as specification limitations, not as a license to discard its estimates because they are inconvenient. Conversely, do not announce a discontinuity in adjacent ratings from a fitted payoff limit.

**Correction to the quoted AI review:** it said the side slopes were “negatively correlated” and individually imprecise in a way suggesting both were insignificant. The supplied SEs imply covariance **+.009765554** and correlation **+.770305**, using Var(loss−gain)=Var(loss)+Var(gain)−2Cov. The covariance is positive, and the loss-side slope individually rejects zero at p≈.004. The gain-side slope is not statistically clear. The precise difference is consistent with positive covariance. Copying the prior sentence would introduce a mathematical error.

A defensible synthesis is: immediate displayed-gap comparisons do not reveal a discrete jump, while the controlled payoff model shows asymmetric side slopes and specification-dependent fitted level differences. The slope asymmetry is still not separated from relative strength. A K-scaling design would address that distinction more directly, but it is not a completed causal separation in these returns.

### 8.4 Defaults and rating uncertainty

The post-hoc exact-zero decomposition has 227,407 opportunities and 6,469 grants (2.844679%). Both displayed ratings equal 1500 in 2,315 cases, **1.017999%** of exact-zero mass. Exactly one high-RD account accounts for **3.294973%**, both high-RD accounts **.913780%**, so **any high RD is 4.208753%**, not 3.3%. Neither is high RD in **95.791247%**. The established, nondefault combination has **95.682191%** of exact-zero mass.

The broad nondefault/established majority retains the elevation against the fitted left limit. The default-account explanation therefore does not remove the fitted feature. This diagnostic was requested after observing the Wave-1 spike; label it post-hoc. The raw zero-versus-all-negative comparison also averages over a much broader relative-strength window and does not isolate a tie-specific effect.

Sources for §§8.2–8.4: `results/wave2a/modules/crossing_default_audit/tables/`, its report and model receipts; the original controlled execution is also in Wave 1. Keep adjacent-level, spline-slope, exact-zero, engine-zero, and default-account tests in separate rows and prose.

## 9. First/repeat meetings and targeted memory on the new panel

### 9.1 Exact C7R family and the covariance closure

The exact v1.0.2 interaction fit uses **757,646 rows and 533,531 chooser clusters**. The original standalone repeat-only fit did not converge after its allowed iterations. It remains failed. The subsequent covariance closure reproduced the frozen interaction fit to full precision and serialized the covariance needed for a legitimate linear combination.

| Adjusted fair minus clearly-worse gradient | Estimate, pp | SE | 95% interval |
|---|---:|---:|---:|
| First recorded meetings | +1.594334079 | .054655624 | [1.487209,1.701459] |
| Repeat recorded meetings | +1.279362238 | .134317283 | [1.016100,1.542624] |
| Repeat minus first | −.314971841 | .137517746 | [−.584507,−.045437] |

Interaction p=.0219976. Repeat gradient = β_fair + β_fair×repeat, using the full covariance. The off-diagonal covariance is −1.928617621×10⁻⁷ in probability units. Adding squared SEs without this term is wrong. The repeat gradient is about a fifth smaller, but the point estimate's ratio is descriptive rather than a separately estimated ratio effect.

Within the pooled interaction model, repeat versus first in clearly-worse states is +.132314 pp (SE .066715, p=.04734). A separate within-fair fit gives +.128136 pp (SE .161438, p=.42736). These two repeat effects are from different model specifications; do not claim that subtracting them reproduces the interaction above.

The sampled pair-sequence rows are 772,371 first, 40,919 second, 14,709 third–fifth, 2,290 sixth–tenth, and 702 eleventh or later. They describe that sampled table, not all 41.5 million rows or the 757,646-row estimation subset.

Sources: `results/c7r/results/c7r/first_meeting_models.csv` and `results/c7r_cov/c7r_linear_combination.json`. Use the interaction-derived row as the exact-family Panel B replacement. Do not conceal the standalone fit failure, retry it after inspecting the answer, or report its last iterate as an estimate.

### 9.2 Full-panel census is a separate check

There are 2,934,486 repeat opportunities, approximately **7.065%** of the new panel. Raw first/repeat rates are:

| Outcome set | First | Repeat |
|---|---:|---:|
| All | 1.400876% | 1.000346% |
| Competitive | 2.817079% | 2.025148% |
| Clearly worse | .482820% | .296874% |

The minimal-FE census gradient is +2.210687 pp at first meetings (SE .009589), +1.726536 at repeats (SE .020331), difference −.484151 (SE .018238). This agrees on ordering with the exact-family model, but uses fewer controls and a different sample. The old full-panel census has the opposite small interaction sign; do not attribute the change to one component of the composite new restriction.

Suggested new-sample wording: “The desert gradient is fully present at first recorded meetings and is somewhat sharper there than at repeats.” First recorded meeting is not certified first-ever encounter or proof of no recognition. A tendency toward state-insensitive repeat effects is consistent with relationship accounts; the regressions do not identify that psychological mechanism.

### 9.3 C7X cannot retain the old adjusted claim

The full-panel targeted-memory reconstruction yields only **125 benefactor re-encounter rows, 4 grants (3.2%)**, versus **10,356 claimer re-encounters, 174 grants (1.680%)**. The unadjusted gap is about +1.52 pp. The prespecified 1,000-per-arm support gate fails. There is no supported adjusted replacement for the old +14.6/+13.0 pp effects.

The dyad diagnostic confirms the scarcity: only six benefactor re-encounters in the ≥10 category, with no grants; 79 in the exactly-two category, with three grants. Tiny cells are diagnostics of support, not precision estimates or evidence of zero targeted reciprocity.

Withdraw the old quantitative C7X claim from the rewritten main results; give the new support failure in the appendix or explain that the screen leaves too few relevant repeats. An optional old-sample comparison must retain its selected-relationship and noncausal qualification. “Targeted memory disappears” would confuse lack of estimability with a measured null.

## 10. New-sample dynamics: receipt, persistence, sessions, and salience

### 10.1 A1, different outcomes and denominators

| A1 estimand | Estimate, pp | SE | N / qualification |
|---|---:|---:|---|
| Next fair-opportunity kindness among reachers, primary | +.881658361 | .122403192 | 993,762; 644,491 chooser clusters |
| Same, state-conditioned companion | +.898314650 | .122456920 | See companion support |
| Reach a subsequent fair opportunity | −.197330517 | .194173450 | 2,110,400; p=.3095 |
| Any grant within 90 days | +.468450761 | .071500076 | Complete-follow-up outcome |
| First subsequent fair-opportunity grant, nonreachers coded zero | +.399242376 | .057593418 | 2,110,400; p=4.15×10⁻¹² |

Primary receipt/claim counts are 28,729/965,033. Weighted comparison-group kindness is 3.330768%, treated 4.385812%; the adjusted .881658 pp coefficient is about 26.47% of the weighted comparison rate. It is not the raw rate difference. The complete follow-up cohort has 62,237 receipts and 2,048,163 claims. Distinguish nonreachers coded zero from conditioning on future opportunity; they are not interchangeable answers to selection.

Excluding the benefactor from the recipient's next choice gives +.881884 pp; retargeting to the first nonbenefactor opportunity gives +.881803. There were only 84 immediate next choices against the benefactor, three in the treated arm, so no precise benefactor-specific subgroup claim follows. Censoring at the next exposure gives +1.095141 pp (SE .158560), a different risk set.

Implemented elapsed-time models include ≤6 hours +1.494225 pp (SE .674254), 6 hours–1 day +1.141627 (.532562), 1–7 days +1.077226 (.236457), 7–30 days +.685656 (.159081), and 30–90 days +.500784 (.138543). Their sample construction changes with the horizon/window. Do not turn these regression points into a causal half-life or assume they are a balanced trajectory for identical accounts.

Sources: `results/wave2b1/results/dynamic_core/results/a1_primary_and_companions.csv`, the A1 decay and audit tables, and `results/wave2b1/results/a1_unconditional/results/unconditional_first_opportunity.csv`. The old naive/experienced-decliner/prior-granter salience effects, receipt ply cutoffs, and singleton-specific estimates have no authenticated new replacements located in these returns. Do not silently carry the old Table A1/A2 entries forward.

### 10.2 A3 continuation

The new 30-day log(1+games) effect is **+.007548200**, SE .005861515, p=.197831, N=2,294,012, chooser clusters=1,127,372. This is a log outcome, not a .7548 pp effect. Any game within 30 days is +.074203 pp (SE .093644, p=.42813). The raw game-count effect is −.022929 games (SE .772369, p=.97632).

These do not establish meaningful changes in total later volume. A short-horizon return/re-entry effect is a distinct outcome and needs its own returned row if retained. The original closeout's 10/30/60-minute numbers are old-sample values.

### 10.3 B1 concentration and B2 first-grant timing

The rebuilt repeat-granter set contains **55,359 choosers, 832,948 opportunities, and 234,993 grants**. B1 observed within-account concentration exceeds the static-propensity conditional reference:

| Window | Observed statistic | Null mean | Null SD |
|---|---:|---:|---:|
| 6 hours | 3,856.651097 | 2,898.898690 | 35.667752 |
| 24 hours | 9,030.940388 | 6,979.556730 | 50.865242 |
| 168 hours | 41,240.766867 | 34,009.906393 | 105.104621 |

Each raw Monte Carlo p is .0004; the three-window B1 Holm value is .0012. For the separate three-primary family A1/A3/B1, adjusted p values are approximately 1.7683×10⁻¹²/.197831/.0008. These are different families, not conflicting versions of one correction.

B2 first-grant follow-on rates:

| Horizon | Observed grants / opportunities | Observed % | Null % | Excess pp |
|---|---:|---:|---:|---:|
| 6 hours | 1,217 / 2,360 | 51.567797 | 34.826311 | 16.741486 |
| 24 hours | 2,562 / 5,060 | 50.632411 | 34.019074 | 16.613338 |
| 7 days | 10,591 / 23,761 | 44.573040 | 32.696677 | 11.876363 |

All raw p=.0004. B3's costly-minus-favorable excess is −1.958818 pp, p=.1232. Do not claim a strong difference between cost sides from that companion.

These tests reject a particular conditional benchmark. Heterogeneity controlled by the sampler is not the same as all conceivable latent heterogeneity, time-varying circumstances, or a causal mood state. The first observed grant is data-dependent and must be recomputed under the null.

### 10.4 E1 and F2

E1 repair risk, p90 minus p10: **−.946864 pp**, SE .458366, raw p=.038853. Raw rows=282,189, identifying rows=71,723, choosers=32,188. Family-adjusted p=.116560, so do not call it a confirmed negative repair effect.

F2 round-number threshold primary: **−.188975 pp**, SE .135128, raw p=.161965, adjusted p=.323930. Personal-best F2 fails the required salience support gate and occupies its reserved p=1 slot under that family's rule; this is not an estimated zero effect. A narrower RD≤80 round-number companion has raw p≈.0194, but it is not the primary result.

The four-slot B2/E1/F2R/F2P family yields .0016/.116560/.323930/1. Do not mix this with Campaign family D or the A1/A3/B1 family. Full model receipts are retained under `results/wave2b1/`.

## 11. Chooser-leniency IV and the selection addendum

This is an encouragement/IV design with explicit identification limitations, not a random-assignment certificate. Full sources are `results/iv/` and `results/iv_selection/`.

### 11.1 Design and sample

The eligibility frame has 2,112,795 exposures and 62,304 receipts before the stricter history requirements. Primary IV N=**1,071,174**, receipt exposures=25,288, chooser clusters=510,827, assignment cells=4,634, exposure dates=611. The first future fair nonbenefactor opportunity must start after the focal last-move anchor; follow-up is 90 days, complete, with nonreachers coded zero for the unconditional grant outcome.

The instrument uses pre-exposure chooser history, month-start information with seven-/30-day exclusion variants, pair leave-all-out removal, and four-fold state-adjusted propensity estimation. The historical instrument source remains the all-source Stage-07 history when specified by the frozen design; mechanically truncating that history to selected new-panel events changes the instrument. Bind source and outcome population separately.

The primary score SD is **.059411690344**. The current IV report scales effects per one score SD; older core encouragement rows may use a whole unit of the score. They must not be placed side by side without rescaling.

### 11.2 Estimates

| Primary quantity | Estimate | SE / interval |
|---|---:|---|
| Receipt first stage per score SD | +6.521910 pp | SE .048738; F≈17,906.9 |
| Reduced form, unconditional next grant per score SD | +.026071 pp | SE .012776; p=.04128 |
| 2SLS receipt effect | +.399740 pp | SE .195758; 95% [.016061,.783418] |
| Same-sample OLS receipt association | +.554424 pp | SE .089015 |
| Reduced form for reaching the next fair opportunity | −.025711 pp | SE .045928; p=.5756 |

The Anderson–Rubin interval is approximately [.015819,.783260] pp after converting the stored probability units. Primary inference uses chooser/date two-way CR0. A large first-stage F does not establish the exclusion restriction. Do not report the within-reacher observational A1 effect as the IV reduced form, or equate its sample with this one.

### 11.3 Ordinary-game comparison and role selection

The all-game comparison frame has 1,661,563 pool games before the new adjacency screen; 1,527,795 remain nonadjacent; the primary history-supported comparison has 986,869. The selection inference uses shared-account-or-date CR0, not just the primary IV cluster formula.

| Outcome per score SD | Effect, pp | SE | p |
|---|---:|---:|---:|
| Active timeout candidate | −.123044 | .014894 | 1.44×10⁻¹⁶ |
| Passive outoftime candidate | −.081643 | .046068 | .07636 |
| Recipient was disconnector in active timeout | −.039434 | .011611 | .000683 |
| Recipient was chooser in active timeout | −.083453 | .009075 | 3.72×10⁻²⁰ |
| Actual IV exposure | +.000041 | .002564 | .9873 |
| Ordinary-game later-grant placebo | +.001273 | .019159 | .9470 |
| Any candidate: active + passive | −.204687 | .047157 | 1.42×10⁻⁵ |
| Active given candidate | −.339364 | .048534 | 2.70×10⁻¹² |

The last conditional model has 318,231 candidate games; mean active-given-candidate is 6.745414%. Candidate prevalence in the full supported comparison is 32.246529%. The candidate coefficient exactly decomposes into active plus passive coefficients when fitted on the same rows and design. The role-specific active coefficients must also retain the residual/other-role accounting in the source table rather than be rounded into a false exact identity.

The placebo is near zero but imprecise relative to very small equivalence margins. Selection associations are not near zero. Do not summarize this package as “all placebo/balance tests pass,” or claim that an insignificant actual-exposure association proves random assignment. Missing pregame RD, prior-30-day all-game volume, and internal conduct classifications remain design limitations. The score is generated; the recorded covariance procedure and its treatment of first-stage estimation uncertainty govern any inferential claim.

For a main-text presentation, say the IV estimate is consistent with a small positive effect under its assumptions, then state that candidate selection and role composition vary with the instrument and limit a causal reading. The ordinary-game placebo is useful supporting evidence, not proof of exclusion. The addendum is a post-hoc diagnostic requested after reviewing selection concerns.

## 12. C6 non-exploitation, C10 decline, and C12 experience

### 12.1 C6 outcome definitions matter

The complete pre-outcome cohort is 2,110,400 exposures. The primary rate model uses 2,018,635 returning exposures and 1,024,721 exposure-chooser clusters. Grant receipt is associated with **−1.593383212 clearly-losing timeout events per 1,000 later rated games**, SE .332627292, p=1.665353948×10⁻⁶. Weighted comparison rate is about 27.5543 per 1,000.

Other estimands:

- Clearly-losing timeout count: −.1344, SE .0210, p≈1.43×10⁻¹⁰.
- Later rated-game volume: −.8327 games, SE 1.9696, p=.6724.
- Rate with nonreturners set to zero: −1.5150 per 1,000, SE .3204, p≈2.27×10⁻⁶.
- Losing-position share among relevant timeout outcomes: −1.4375 pp, SE .1839.

The primary rate is a weighted mean of individual rates. The ratio of weighted outcome sums to weighted game sums gives a different contrast, approximately −.1827 per 1,000; do not substitute that number or describe the primary as a pooled ratio. Conditioning on returning or having later timeouts changes the population, and the companion outcomes expose that selection.

The new ply retrofit gives exposure-ply>10 rate −2.4959 (SE .3572), outcome-ply>10 rate −1.5590 (SE .3251), both-long count −.1399 (SE .0256), and a relevant share contrast −1.6666 pp (SE .2314). In the long-outcome rate model, the denominator remains **all later rated games**, not only later long games. The source is already pool-only, so a tournament-exclusion companion may be numerically redundant; do not count it as independent evidence.

Interpretation: no evidence that recipients exploit kindness by subsequently generating more of the specified losses; several measures move downward. This does not establish a causal deterrence or rule out every strategic channel. The new ply results close a new-sample concern; they do not retrofit the old sample's unscreened C6 estimate.

### 12.2 C10 and C12

C10 claimed-arm pre/post contrasts at 7/14/30/60/90 days are approximately −.510/−.462/−.444/−.448/−.445 pp. The trajectory is fairly flat after the early window; its level is not a null effect. Receipt-minus-claim contrasts are 1.369/1.070/1.039/.761/.707 pp (SE .475/.365/.285/.226/.200). Changing risk sets and adjustment mean this is not a balanced experimental decay curve.

C12 primary low-minus-high experience interaction is **+.1184 pp**, SE .2548, p=.6421, 95% [−.3811,.6179]. The main interaction fit has 120,938 rows and 112,030 clusters within a broader 302,357-row sample. Eight of nine fits estimated; the highest-rating subgroup has only 372 rows and 360 clusters and remains unestimable. A secondary p≈.0289 is not a replacement for this primary null. Sources: complete C6/C10/C12 and ply outputs under `results/c6_c12/`.

## 13. C9 fresh randomization and the completed ply extension

### 13.1 Provenance and benchmark

The source probe's initial C9 keyword hits were not the genuine producer. The correct producer was subsequently recovered, SHA-256 **e553af77d16cf944a956b4ae266c3468806e08257a4aa1bff6fb953c619d8830**, and a fresh run was returned. The initial “producer still missing” warning is historical. An old recovery script that merely collects existing draw arrays is not itself a new-panel randomization producer.

Primary C9 reuses the rebuilt B1 repeat-granter set (55,359/832,948/234,993) and makes **4,999 fresh conditional draws**. The sampler conditions on chooser grant counts with fitted static-propensity weights; it is not an arbitrary uniform shuffle except in special equal-weight cases. Every draw recomputes the pseudo-first grant and both partitions. Reusing old-sample draws, holding the observed first grant fixed in the reference distribution, or recomputing only one side would be wrong.

Sessions use a 30-minute gap between **all-rated-game starts**, not a 30-minute idle period after the previous game's end. The session cache covers 183,785,933 records in 150 chronology files. Its receipts distinguish file/manifests and metadata verification from a fresh full-byte rehash of all ~45 GB. Do not overstate authentication.

### 13.2 Primary results

| Seven-day / speed partition | Observed % | Null % | Excess, pp | Raw p |
|---|---:|---:|---:|---:|
| Later session, 9,902/22,455 | 44.097083 | 32.549610 | 11.547473 | .0004 |
| Same session, 689/1,306 | 52.756508 | 35.408126 | 17.348383 | .0004 |
| Same api_speed, 24 hours | 50.6872 | 33.7072 | 16.980010 | .0004 |
| Different api_speed, 24 hours | 49.8489 | 38.1489 | 11.700067 | .0008 |

Same-minus-later excess is 5.800910 pp, p=.0004. Same-minus-different-speed excess is 5.279943 pp, p=.034. This last p is weaker than the historical .0012; retain the change. C9's “same pool” label refers to the time-control/speed category in this analysis; all new-panel rows already pass the source=`pool` screen. Explain the two uses of “pool.”

Fresh config digest: `55d5cbb276393949039b72b65ffb2dd9cb57ed5dbff15b4ed012ecda4d6f88bd`. Recorded core runtime about 193 seconds; authentication/session-cache construction and package overhead are separate from this timer.

### 13.3 Ply extension

The completed extension preserves the event set and provides both outcome masks and a stronger null conditioning on chooser×ply-band grant totals. Bands are ≤4, 5–10, 11–20, 21–40, 41–80, >80, plus a missing category; actual missing ply was absent here.

| Later-session seven-day outcome | Excess under original benchmark, pp | Excess under ply-conditioned benchmark, pp |
|---|---:|---:|
| All | 11.547473 | 9.367956 |
| Outcome ply>4 | 10.589132 | 9.328014 |
| Outcome ply>10 | 9.579302 | 8.830671 |
| Outcome ply>20 | 9.432663 | 8.186243 |
| Anchor and outcome ply>10 | 10.937607 | 9.359138 |

Every listed component has raw p=.0004. With 4,999 draws and the implemented two-sided plus-one tail rule, this is a Monte Carlo resolution floor, not p=0 or an exact population probability. Preserve the original observed/pseudo-first anchor; in the both-long mask, exclude short anchors rather than reanchoring to the first long grant.

The ply-conditioned all-outcome excess is about 19% smaller than the original benchmark. That is a change in a conditional descriptive reference, not “19% of the causal effect explained by ply.” Same-session excess under this conditioning is 13.971946 pp, versus later-session 9.367956; difference 4.603990, p=.0004.

The run receipt records reproduction of the original arrays, zero unsupported cells, nine workers, 20 batches, no network, no raw-chronology reread, and ~207 seconds. Those private arrays were not uploaded for independent local reproduction. Fifteen-/60-minute alternative session definitions and the old singleton-only appendix cell are not replaced by this ply package. Either rebuild them on the chosen population, remove them, or label the old values as historical.

Sources: `results/c9/` and `results/c9_ply/`; ply config `24c6d608556a8378246863e9ab4ff78e8b48ea1ccc01a1c00d3847d7e8223762`.

## 14. Patron: acquisition, core findings, all remaining models, and limits

The new Patron sequence is complete for its scheduled estimable families: Wave 3A design, the gap fill, Wave 3B1 estimation, and Wave 3B2 remaining models. Do not keep an earlier “Patron pending” gate solely because it appears in the September 1 memo or a Wave-1 ledger.

### 14.1 Preserve observation date and missingness

Wave 3A found 207 primary design gaps: 77 never queried and 130 queried but not returned. In the broader design, 285 gaps comprised 122 never queried and 163 unavailable. The gap fill queried the 122 previously unqueried accounts on September 11 and obtained responses for all; 163 other outcomes remained unavailable. It did not recover what those accounts' Patron status had been in August.

The headline sample retains the fixed August snapshot. The primary target is 851,428 profiles, with 851,221 returned; removing 90 controls whose focal kind account lacked an outcome gives **851,131** matched accounts: **212,829 fair-kind** and **638,302 controls**. Patron counts are **1,369/2,114**, approximately .643%/.331%. There are 36 matching cells.

The September mixed-date sensitivity adds the 77 recovered primary controls, giving 851,208. All newly returned relevant controls are non-Patrons at their September observation, but that does not prove they were non-Patrons in August. The main adjusted coefficient shifts by less than .00005 pp; this small numerical movement is useful sensitivity evidence, not date equivalence.

The August fields `count_all`, `count_rated`, `win`, `loss`, and `draw` are all missing in this snapshot. Constant imputations are collinear and dropped. A paper cannot claim meaningful adjustment for observed lifetime game counts just because the design matrix originally requested those column names.

### 14.2 Core new results

| Quantity | New-sample result |
|---|---|
| Raw fair-kind/control Patron gap | +.31208 pp |
| Fully adjusted main gap | +.276884 pp; HC1 SE .018685; cell CR1 SE .034799 |
| Two-state horse race | N=599,045; at least four opportunities in both states; 24 cells |
| Fair-kind coefficient | +.388434 pp; HC1 SE .028415; CR1 SE .031681 |
| Clearly-worse-kind coefficient | −.194593 pp; HC1 SE .030526; CR1 SE .033370 |
| Fair minus clearly-worse contrast | +.583027 pp; HC1 SE .046021; CR1 SE .058810 |
| Binary costly minus nonnegative-payoff contrast, min-four | Approximately −.090 pp; SE .084; p≈.282 |

The matched two-state category rates are fair-only .902% (908/100,671), both .492% (89/18,098), neither .431% (1,957/454,045), clearly-worse-only .259% (68/26,231). These are separate raw categories from the adjusted two-state coefficients.

Dose categories 0/1/2–4/5–9/10+ grants have rates approximately .316/.490/.840/1.382/1.257%. Do not claim strict monotonicity at the last category. The new binary price-side contrast is not statistically clear; the old p≈.027 should not survive in a new-sample table.

The mixed-date adjusted coefficient is +.276932 and the two-state contrast +.583045. August missing-outcome bounds on the raw gap are approximately [.284378,.326190] pp; FE-only bounds [.284383,.326195]. These are bounds under specified missing-outcome assignments, not confidence intervals for the fully adjusted regression.

Wave 3B1 returned 48 model fits across headline, corrected-date, and supplemental variants. Use the final version's dates and model labels rather than count all variants as independent corroboration.

### 14.3 Wave 3B2 closes the remaining scheduled families

Completion marker: `PATRON_WAVE3B2_REMAINING_COMPLETE`. Recorded run ~1,778 seconds (29.6 minutes), versus the earlier conservative 1–3-hour planning range. It reports 232 models: 200 alternate-control fits, seven five-bin models, ten price/count/rate models, three opportunity models, twelve ply models; also two core reproduction checks, four dyad tables, and 130 covariance-based contrasts. No unsupported scheduled model remained.

**Alternative controls.** Across 100 independent matching seeds, the adjusted gap averages +.271714 pp, with range +.249629 to +.304632. Each draw has approximately 212,753–212,783 pairs; 46–76 pairs are omitted because of the selected control slot's missing outcome. The range is a matching sensitivity range, not a confidence interval or 100 independent samples of the population.

**Five-bin simultaneous model.** At least four opportunities per bin, N=77,751 accounts, 379 Patrons, 16 cells:

| Ever-kind indicator | Coefficient, pp | HC1 SE |
|---|---:|---:|
| Clearly better | +.249020 | .112269 |
| Better | +.166501 | .141696 |
| Roughly equal | +.151072 | .106556 |
| Modestly worse | +.120543 | .177823 |
| Clearly worse | −.206824 | .079161 |

The clearly-better minus clearly-worse contrast is **+.455844 pp**, HC1 SE .138762, 95% [.183876,.727812], p≈.00102. Point estimates are ordered, but adjacent HC1 contrasts all have p≥.104. Do not advertise a precisely estimated five-step monotone gradient. Cell CR1 can be much smaller for particular contrasts, with only 16 cells; do not choose the covariance estimator after seeing which p is attractive. The endpoint CR1 SE is about .051788 and must be labeled alongside its limited cluster count.

**Opportunity-weighted reverse regressions.** Returned August accounts: 1,105,634; opportunities: 26,492,238. This is not the entire panel. Patron/non-Patron kindness gaps by board bin are +5.811162/+3.244686/+3.086193/+.529840/−.270658 pp; corresponding SEs .563021/.415138/.514178/.212555/.058245. The negative clearly-worse association survives outcome-ply>4, >10, >20 and ply-band adjustment (approximately −.270174/−.271209/−.257412/−.264442 pp). The modestly-worse >20 effect is +.341692, SE .183762, p≈.063, so not every positive intermediate effect is individually precise.

Opportunity-weighted fair kindness gaps by price side are +2.727765 pp for costly and +4.190068 for nonnegative draw payoff, difference +1.462302, SE .264621. This uses a joint covariance, not independent-error subtraction.

**Count/rate price models.** Standardized count coefficients give costly .068/nonnegative .133 pp, difference −.065, p≈.110. Rate coefficients give costly .028/nonnegative .154, difference −.127, p≈.0143; the costly coefficient itself has p≈.302. These regressions differ from the binary ever-kind model. Do not swap the rate-model p=.0143 into the binary row that has p≈.282.

**Dyad screens and rematching.** Raw rematched gaps: all +.310086 pp (N=851,229), singleton +.296284 (822,027), frequency<3 +.306564 (844,476), frequency<5 +.307984 (849,674). These are four descriptive sensitivity points without SEs in that table. The all-sample rematching benchmark differs from the +.31208 primary match; maintain the correct denominator and label.

Sources: `results/patron3a/`, `results/patron_gap/`, `results/patron3b1/`, and `results/patron3b2/`, plus the earlier Patron paper-update and closure notes bundled under `prior_reviews/`.

### 14.4 What the Patron evidence can say

Kindness in competitive positions predicts current same-platform Patron status, whereas kindness in clearly-losing positions is negatively associated in the joint model. This is a cross-behavior pattern consistent with a stable prosocial component whose expression depends on board state. It is not a causal effect of granting on donation, a measured donation amount, a temporal adoption result, or evidence of generosity outside the platform. Patron timing/churn were not estimated. Do not put the profile snapshot date before all exposure behavior if the data chronology does not support that claim.

## 15. C13 and family-D: ready code, incomplete new-sample closure

### 15.1 C13 scope and status

`Pool_Main_C13_FamilyD_v1_0_0.zip` is a delivered, tested runner. **It has not produced a returned new-sample result in this conversation.** The old C13 estimate in §5.6 is historical only and cannot supply the main-sample ambient coefficient. Estimate the new version if retaining this claim, or omit the claim while preserving the pending analysis in the ledger.

The governing producer is `campaign1_c13_v104.py`, SHA-256 `2b8e19fe130c5387ea9097eb011332918ef4761ea67afd7df30f91e2f69c535d`; shared common source SHA-256 `f629876216c797180265d1b848a4424f211fe9a43cffa4dabdb3de67acbc5f1c`. Nineteen model attempts preserve the frozen primary 28-completed-UTC-day ambient exposure, alternative lags/windows and denominator/numerator authority amendments. The local chooser is removed from its exposure cell's numerator and denominator, with the specified minimum other-opportunity support. Primary and quartile results are attempted first.

The new C13 construction rebuilds denominators from the selected panel's 15,207,423 fair opportunities, using UTC decision day, speed, and chooser-rating bands <1600, 1600–1999, 2000–2399, and 2400+. Before opening the kindness numerator, it freezes support with at least 5,000 other-chooser fair opportunities in the lag window. It then joins the certified 419,463 fair grants and verifies 0 ≤ numerator ≤ denominator. Normalized username identifies leave-one-out exposure; numeric chooser ID defines FE and clustering. The primary controls are chooser, speed×rating band, calendar week, evaluation bin, hour of week, and tournament FE, plus draw payoff, win premium, both clocks, both ratings, and both RDs with the original missingness rules. Inference is one-way chooser-clustered with normal-reference p values. The 19 attempts are seven linear exposures (cell 14/28/56 days, cell 28 days with a seven-complete-day washout, and speed-only 14/28/56 days), a quadratic companion, four rating-band splits, six speed splits, and adjusted quartiles. The washout window is t−35 through t−8. Do not improvise a platform-wide daily rate, include current-day events, or borrow the all-source IV instrument-history rule: C13 has its own numerator/denominator contract.

Strict absorption tries 2,000 iterations at 1e−9; the documented extended numerical retry permits 25,000 at 1e−7 for absorption only. It does not authorize changing rows, controls, or hypotheses. Failed models remain in the report. Seven synthetic/lineage tests passed; these are not a private-data production completion certificate.

Expected elapsed compute: **4–8 hours**, based on the old 4.66-hour run, with variation from disk and convergence. SQL/hash work can use ten workers; model attempts are sequential and the 8 GB DuckDB setting is not a hard cap on every NumPy allocation. The runner is checkpointed and has a fast `--holm-only` mode. See `RUN_COMMANDS.md` for the complete command.

### 15.2 Exact families must stay separate

| Family | Membership / governing role | Current handling |
|---|---|---|
| A1/A3/B1 primary dynamics | Three predeclared primary outcomes | New adjusted values available in Wave 2B1. |
| B1 windows | 6/24/168-hour concentration | Three-window adjustment available. |
| B2/E1/F2R/F2P | Four reserved second-wave slots | Preserve unsupported personal-best slot under its rule. |
| Adjacent rating-gap family | Joint schedule around zero | Use the rebuilt schedule's Holm p values. |
| Campaign family D | C1, C2, C5, C6, C9 | Old signed table available; exact new five-member table not complete. |
| C13 | Exploratory X, outside family D | Report its own status; do not add/remove it from D. |
| Post-hoc zero/RD, IV selection, ply diagnostics | Their documented diagnostic role | Do not retroactively promote them into a confirmatory family. |

For new family D, C6 raw p=1.6653539481830944e−6 and C9 raw p=.0004. New C1/C2/C5 inputs are not authenticated in hand. Keeping all five slots yields conservative upper adjusted values **8.326769740915472e−6 for C6** and **.0016 for C9**. Both reject at 5% regardless of the three missing p values. This establishes those two decisions, not the exact complete family table. Possible lower values are approximately 3.330707896366189e−6 and .0004, respectively.

Do not silently assign p=1 to missing new results merely because the old closeout used that rule for a documented absent C5 slot. The prepared package distinguishes conservative bounds from exact closure and checks sample/source authority. It does not estimate new C1/C2/C5 or reopen invalid C1 results. If the paper only needs the C6/C9 decisions, explicitly reported conservative bounds can be enough; if it claims the complete family's exact p values, the remaining authenticated inputs are required.

## 16. How to rewrite the paper without overstating the evidence

### 16.1 Narrative architecture

The defensible argument is a triangulation: private discretionary kindness varies strongly with the opponent's board position, persists across an account's opportunities, responds to prior experienced treatment in observational and qualified IV designs, shows temporal clustering beyond a frozen conditional benchmark, and predicts a separate same-platform supporter marker. Each piece narrows some alternatives. None alone uniquely identifies an intrinsic-prosociality parameter, and the whole package does not eliminate all time-varying states, reputational information, or concerns about rating fairness.

Preserve four conceptual layers:

1. **Observed structure:** granting tracks board merit and relative strength; equal board positions are not a universal privileged category after stage adjustment.
2. **Stable heterogeneity:** repeated behavior and Patron associations reveal persistence across opportunities/behaviors, subject to selection and measurement.
3. **Dynamic associations:** experienced treatment, episodes, and same-/later-session patterns are compatible with a transient component but not a unique causal emotional mechanism.
4. **Boundaries:** broad participation, targeted-memory support, price identification, candidate selection, missing profiles, and low-support cells limit what can be claimed.

Writing can begin now from the completed new-sample authorities. The new sample is the main branch, with its own N, source screen, estimation populations and changed conclusions. Withdraw unsupported old-only claims. Old-sample results can appear as explicit comparisons, but neither their figures nor their numbers should silently remain in the main narrative.

### 16.2 Framework and proof repairs already signaled by the old closeout

The provided TeX contains propositions and appendix proofs that imply more than the empirical designs establish. The old closeout's `manuscript/FRAMEWORK_REPLACEMENT.tex` is a useful starting point for a compact organizing framework, not a license to paste it without checking sample-dependent prose.

- Continuity of a rating-cost function does not imply differentiability or absence of a kink. State the smoothness assumptions needed for a derivative conclusion.
- A positive autoregressive or transient state can imply decay of a latent impulse under a specified model; it does not automatically imply that every cumulative, selected, or changing-risk-set empirical excess decreases monotonically.
- A constant latent relationship contribution need not generate a constant effect on observed grant probabilities under a nonlinear link.
- An “ever granted” indicator is a noisy, exposure-dependent transformation of a latent propensity. An association with Patron status is not a direct regression of one measured latent type on another.
- Conditional randomization permits weighted assignments under the specified model; unequal opportunity propensities are not exchangeable under uniform permutations. The draw conditioning, first-event recomputation, and selected repeat-granter population belong in the methods.
- Recognition/reputation channels are least plausible at first recorded meetings but not logically absent. A stronger desert gradient there supports the section's argument without claiming anonymity is proven.
- State-insensitive associations can be consistent with relationships, but their signs alone do not identify relationships as the cause.

Prefer a concise framework that motivates observable contrasts and explicit alternative explanations. Remove mathematical claims whose assumptions are neither justified nor needed. If retaining formal propositions, repair them and map each to the exact measured estimand; do not infer a theorem from a plotted regression.

### 16.3 Sentence-level restrictions

| Avoid | More defensible formulation |
|---|---|
| “All games were anonymous pool matches” in the old paper | Define the original source mix; report the new pool screen separately. |
| “Equal ratings have no discontinuity” as a proven zero | “Adjacent displayed-rating contrasts do not detect a step,” with estimate/interval. |
| “No price effect” | Separate nominal draw payoff, forgone-win premium, relative strength, and K/RD associations. |
| “The IV validates causality” | State its assumptions, strong first stage, positive estimate, and selection limitations. |
| “Targeted memory vanishes on the new sample” | Frozen support gate fails; an adjusted new effect is not estimated. |
| “Persistence strengthened because pairings became random” | Report the change; the joint screen does not identify its cause. |
| “All five Patron coefficients form a significant monotone ordering” | Point estimates are ordered; the endpoint contrast is clearer than adjacent contrasts. |
| “Null C13 proves no ambient influence” | Report its interval and exploratory conditional association. |
| “p=0” for C9 | Report the implemented Monte Carlo p=.0004 and draw count. |
| “Patrons donated because they were kind” | Current same-platform supporter status is associated with prior observed kindness. |
| “Every analysis completed” | Distinguish completed fits, retained failures, missing replacements, and prepared code. |

### 16.4 Numbers, tables, and figure discipline

Maintain one machine-readable numerical ledger for the chosen sample. Every displayed estimate should identify sample, outcome, model, SE convention, cluster count where material, multiplicity family, and source row. Use the selected row export only as a navigation aid; final tables must retain the original specification labels.

Round descriptive percentages consistently, usually three decimals in tables and two in prose. Use pp for probability differences and retain native units for rates per 1,000, log outcomes, and counts. Do not compare standardized-score IV coefficients with unstandardized historical encouragement coefficients without conversion. Calculate linear combinations with the joint covariance, as the C7R and Patron closures do.

The September 2 package supplies all five old main figures in PDF/PNG/SVG. The new modules supply component figures and tables, not a final audited five-figure manuscript. Rebuild the integrated main figures from the new aggregate outputs and ensure all panels in a figure share the intended sample/specification. Avoid an old main panel with a new caption or a new overall N attached to old appendix estimates.

The old TeX references two screenshot assets and two bibliography files not located in the present source inventory. This handoff preserves the TeX but does not fabricate those dependencies or claim a successful LaTeX compilation. The next writer needs the actual assets or must revise the references.

## 17. Implementation, provenance, and failure history

### 17.1 Stable locations on Ravi's Mac

- Desktop exchange directory: `$HOME/Desktop/Lichess_Desktop`.
- Project: `/Volumes/XT_Pro/lichess_kindness`.
- Original panel: `derived/replication/analysis_panel_24m_sf100k`.
- New panel: `derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE`.
- Reanalysis private state: `derived/replication/pool_main_reanalysis_v100_PRIVATE/`, with wave-specific subdirectories.
- Public aggregate reanalysis output: `output/pool_main_reanalysis_v100/`.
- C13/family-D private/public suffix: `c13_family_d_v100`.
- Reused Python environment observed in logs: `~/Desktop/Lichess_Desktop/pool_main_wave1_python.KT7f8H/bin/python`. Treat the launcher's discovery as authoritative rather than assuming the temporary-looking suffix is permanent.

The available local repository snapshot is commit **0dc981cbc6da157d365015a95f2b7157ecda4859**, dated September 5, with the full-panel C7R census addition. Repository URL recorded in source material: `https://github.com/ravideepsethi/intrinsic-prosociality.git`. This handoff did not verify a live remote HEAD. The included code/docs/results snapshot is more reproducible than telling the next writer to fetch an unspecified latest branch.

The September 1 index's list of missing early-stage scripts is historical: the local repository contains producers for timeout opportunities, Glicko cost reconstruction, the analysis panel, and Stage 08 results. Existence of a filename is not proof that it is the latest governing implementation. Bind the exact producer hash and amendment lineage, especially for C7R/C7X, C9, C13, and Patron.

### 17.2 Resolved failures versus retained statistical failures

| Incident | Disposition |
|---|---|
| IV selection v1.0.0 created an already-created temporary report directory | Packaging bug fixed in v1.0.1; successful report returned. No new interpretation follows from the bug. |
| Wave 2B2B1 tried writing a C6 private Parquet before creating its parent directory | Runtime setup fixed; later complete C6/C10/C12 return is authoritative. |
| Patron remaining v1.0.0 read a JSON array with an object-only helper | Serialization reader fixed in v1.0.1; completed 3B2 report supersedes partial return. |
| C7R repeat-only model failed absorption | Retained failed fit; interaction-derived repeat gradient supplied with covariance. |
| C7X parent support gate failed | Retained unsupported analysis; dyad diagnostics do not override the gate. |
| F2 personal-best salience gate and C12 extreme-rating support failed | Retained unsupported cells, with each family's specified treatment. |
| Source probe classified keyword hits as C9 executables | Later genuine producer recovery and fresh run close the source gap. |

Do not edit a signed source in place and recompute its manifest to make a failure disappear. Preserve the source version, make any necessary amendment explicit, test the changed behavior, and record the binding. Do not rerun finished multi-hour stages merely to refresh a zip timestamp. Successful checkpoints should be reused only after their source/input/config bindings match.

### 17.3 Verification already performed for this handoff

All 21 supplied result/source ZIPs in the archive inventory passed SHA-256 comparison with their corresponding sidecars and ZIP CRC tests. Their report-manifest checks are detailed in `ARCHIVE_VERIFICATION.json`; the package builder additionally validates the historical closeout and any JSON-based manifest it can independently resolve. Whole-archive identity authenticates the included bytes even when a report is a deliberate subset of its source package.

Wave 1's source-package manifest lists `FULL_RESET_SCOPE.md`, `PACKAGE_BUILD_VALIDATION.json`, and `RUN_WAVE1.command` that were deliberately not transferred in the result report. Their absence is not evidence of a corrupted result transfer. The 256 transferred report files are checked against the report-level hashes. Similar nested manifests must be resolved relative to their own roots; do not count a source-package omission as a failed data result.

The 03:16:57 Wave 2A return is the later, broader authority and adds the crossing/default audit. The earlier 03:14:44 return is retained as provenance. Inspect exact same-name bytes when asserting a strict superset; completion scope can expand even if a status/manifest file changes.

## 18. Remaining work for the confirmed new-main-sample rewrite

### 18.1 Start writing the supported results now

The completed new-sample structure, equality/crossing, persistence, receipt, C7R, C6/C9 and Patron authorities support immediate drafting. Rewrite the old TeX using their exact results and model-specific Ns. Use the framework repairs in the old closeout as conceptual editing input, while replacing its old empirical claims. Do not wait for another broad mechanism search before writing.

1. Set the abstract and sample description to 41,534,331 opportunities, 570,091 kind draws, 15,207,423 competitive opportunities and 419,463 competitive grants, with the operational source/adjacency screen. Keep the 24-month window unchanged.
2. Replace Table 2's first/repeat rows with the new exact C7R interaction-derived gradients and covariance-based repeat SE; retain the new minimal-FE census as a separate check.
3. Withdraw the old adjusted targeted-memory claim. The new C7X support gate fails; do not interpret this as a zero effect.
4. Use the new IV and selection results together. Keep observational, unconditional and IV estimands distinct, and preserve their identification limitations.
5. Use the completed new C6/C9 ply checks and Patron families. Preserve the August headline snapshot and September profile sensitivity as separate observation-date designs.
6. Assemble all five main figures, main/appendix tables, abstract and conclusion from a single new-sample ledger. The original figures are layout references only. Recover bibliography/screenshot dependencies, compile the revised TeX, and inspect the rendered output.

### 18.2 Outstanding analyses and reconciliation

1. **C13:** the prepared runner has no returned new-sample result. Run it if retaining the ambient section, with its complete attempt ledger; otherwise omit the claim from the draft and record it as pending. The planning estimate is 4–8 hours, not a prerequisite for writing unrelated sections.
2. **Campaign family D:** new C1/C2/C5 inputs are not authenticated in hand. Report conservative five-slot C6/C9 bounds if those are the decisions the paper needs, or obtain the missing authorities before claiming a complete exact family table. C13 does not belong in D.
3. **Old-only appendix cells:** receipt-salience subgroups, exact A1 ply/singleton cells, alternate C9 session/singleton cells and any other retained specification need an authenticated new result. Rebuild only those actually needed, or omit them and explain the scope. Never fill them with old numbers under a new N.
4. **Manuscript-wide validation:** check units, clusters, covariance-based contrasts, table denominators, p-value families and figure source paths after assembly. A completed core module is not a blanket certificate for every old appendix row.

No new C7X rescue search, extra C12 subgroup retry, fresh profile acquisition or expansion to 36 months is required to start this rewrite. Prioritize missing estimates only when a retained claim depends on them.

### 18.3 Historical material retained in this bundle

The old 47.6-million closeout, September 5 census, old C13, signed old family-D table and original figures remain included for provenance, conceptual repairs and explicitly labeled comparisons. They are not the active manuscript population and do not close missing new-sample estimates. Source reports and numerical tables have not been re-estimated or altered by this sample-instruction correction.

## 19. Copyable instruction for the next writer or AI

> Rewrite `draft_source/SIP_Sept3_original.tex` using the new certified 41,534,331-opportunity pool/observed-nonadjacent main sample. The main panel contains 570,091 kind draws; the competitive subset contains 15,207,423 opportunities and 419,463 grants. This decision is confirmed by Ravi and supersedes earlier handoff instructions that treated the old sample as primary. Use the new authorities in §§6–15 and the main-sample action under every label in `MANUSCRIPT_CHANGE_MAP.md`. Keep the old 47,587,020-opportunity material as historical comparison only. Work on a new TeX copy and build a source-to-number ledger identifying each estimate's sample, model, units, inference convention and exact file. Replace every retained main-text, figure, table and appendix number with an authenticated new result; omit or mark an unresolved object rather than borrowing its old value. Regenerate integrated figures from the new aggregate data. Preserve C7R covariance-based contrasts, C7X support failure, IV selection limitations, weighted B2/C9 randomization, the distinction between displayed-rating levels and payoff slopes, and Patron snapshot dates. New C13 is prepared but not returned; exact full family D lacks C1/C2/C5, while conservative C6/C9 decisions are available. Do not revive invalid C1 or treat unsupported models as null estimates. Prioritize writing supported sections and analyses necessary for retained central claims. Supply complete Terminal commands and expected runtime for local runs. Deliver revised TeX, a change log, a source-to-number ledger and remaining issues; claim compilation only after it succeeds.

This handoff intentionally includes both the exact evidence and its limitations. The bundled historical notes remain useful source records, but this document's sample distinction and completion ledger govern their interpretation at the handoff date.
