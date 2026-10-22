# Pool matchmaking, relative strength, and identification

Prepared 13 September 2026. This is a source audit and proposed empirical design; no new balance, selection, or causal-effect estimate has been computed.

## 1. Recommendation

Make the pool restriction an explicit design choice and explain the assignment mechanism. The suggested claim that rating-and-time adjustment converts the relative-strength gradient into a causal effect is not justified by the code or by the current sampling structure.

Two separate issues matter. First, the matchmaker uses more than rating and queue timing, including behavioral information directly relevant to disconnections. Second, the paper observes kindness after a sequence of events potentially affected by opponent assignment: game play, board position, disconnection, which player stays connected, and active resolution. Even an initially randomized opponent would not automatically randomize opponent strength within those selected states.

The highest-value next analysis is an assignment-and-selection audit using existing files. It should precede any change from “conditional association” to causal language. It does not require another Stockfish run. Drafting the paper can proceed while the diagnostic runs.

The main sample remains **41,534,331 pool/observed-nonadjacent opportunities**, with **570,091 kind draws** and **15,207,423 competitive opportunities**. Its predicate is `source = 'pool' AND previous_classification_status = 'not_mutually_adjacent_observed'`. Fingerprint: `a17c89d750cb4fdfdf84f950859e45c58b19996efae02045def68285e305cf30`. The former 47.6-million sample is historical only. The broader game-start frame proposed below is a diagnostic denominator, not a replacement main sample.

## 2. What the historical source establishes

The audit inspected the latest pool-module commit before the sample began, `b97c085329f525271887c3bb44ae4a1c8c772ea0` (12 July 2023), and the latest pool-module commit in the sample window, `35beaea23b15e98d83a1ed43720c68ec3264b3f6` (18 August 2025). The intervening pool-module commit listing and selected substantive changes were retrieved. This establishes historical source evidence. It is not an exhaustive audit of every dependency, mobile client, runtime setting or production deployment date.

| Code feature | Verified behavior | Identification implication |
|---|---|---|
| Rating proximity | The main pairing routine scores pairs using absolute internal rating distance, with a rating-dependent admissibility threshold. | Rating sorting is intentional. A broad rating band is not automatically sufficient adjustment. |
| Missed waves | A member's missed-wave count lowers a pair score; the bonus also depends on its conduct score. | Game-start time does not supply waiting duration or the set of alternatives actually available. |
| Rating-range preferences | Each participant's selected range can forbid a pairing; mutually compatible selected ranges receive a bonus. | Users influence the strength of potential opponents even without choosing an identified opponent. |
| Blocking | Either participant's block list can exclude a pairing. | The set of eligible opponents differs across accounts. |
| Conduct score | `ragesitBonus` favors pairs with similar good/bad stalling scores and penalizes some dissimilar pairs. | Matching can sort on behavior correlated with disconnect propensity and potentially kindness. This is a concrete omitted assignment input, not just a generic unobservable. |
| Separate account classification | The routine partitions on `lame`; one partition is paired by rating order, while the other uses the weighted routine with a rating-order fallback on error. | There is more than one assignment path. The code does not establish that the paper observes this historical classification or the fallback frequency. |
| Provisional accounts | A 17 January 2025 commit adds a pairing bonus when both accounts are provisional. | The sample spans an assignment-rule change; both-displayed-1500 is not an adequate substitute for the provisional flag. |
| Internal pairing rating | Later `LobbySocket.toJoinRating` uses the established rating when available; otherwise a randomized value depends on uncertainty and a trust flag. | Displayed rating is not universally the internal number used for pairing. This random component is not an observed randomized instrument in the current files. |
| Pool composition | Pool actors can add compatible lobby hooks to the pairing candidates. August 2025 changes extend API-seek integration. | `source=pool` identifies a game creation route, not necessarily a unique front-end queue-entry experience. |
| Wave timing | The inspected PoolList specifies clock-specific waves; the earlier actor uses timer jitter and also runs full waves. | Nearby game starts are imperfect proxies for common assignment batches, not reconstructed queue membership. |

Primary sources: [earlier MatchMaking](https://github.com/lichess-org/lila/blob/b97c085329f525271887c3bb44ae4a1c8c772ea0/modules/pool/src/main/MatchMaking.scala), [later MatchMaking](https://github.com/lichess-org/lila/blob/35beaea23b15e98d83a1ed43720c68ec3264b3f6/modules/pool/src/main/MatchMaking.scala), [earlier PoolMember](https://github.com/lichess-org/lila/blob/b97c085329f525271887c3bb44ae4a1c8c772ea0/modules/pool/src/main/PoolMember.scala), [PoolActor](https://github.com/lichess-org/lila/blob/b97c085329f525271887c3bb44ae4a1c8c772ea0/modules/pool/src/main/PoolActor.scala), [later LobbySocket](https://github.com/lichess-org/lila/blob/35beaea23b15e98d83a1ed43720c68ec3264b3f6/modules/lobby/src/main/LobbySocket.scala), [provisional-pairing commit](https://github.com/lichess-org/lila/commit/2c80390b2e53f11edc1ceb07d176ac03ba9a8ce0), and [PoolList](https://github.com/lichess-org/lila/blob/35beaea23b15e98d83a1ed43720c68ec3264b3f6/modules/pool/src/main/PoolList.scala).

The conduct score is tied to actual play behavior: `PlaybanApi` updates it following classified rage quits, long waits before flagging, and related events; ordinary play can improve it. The observed study variables may approximate aspects of this history, but they are not a certified reconstruction of the internal state. See [PlaybanApi](https://github.com/lichess-org/lila/blob/b97c085329f525271887c3bb44ae4a1c8c772ea0/modules/playban/src/main/PlaybanApi.scala) and [RageSit](https://github.com/lichess-org/lila/blob/b97c085329f525271887c3bb44ae4a1c8c772ea0/modules/playban/src/main/RageSit.scala).

A separate trust-related change was committed on 17 January 2025. Its implementation can use account history and supporter/title information as part of trust assessment for accounts lacking established ratings. This is another reason not to treat all opponent attributes as independently assigned. A commit timestamp is not a verified deployment timestamp. Use these changes to organize source checks and era sensitivities; they are not automatically natural experiments. See [trust and pool-join change](https://github.com/lichess-org/lila/commit/5ee5c06e8c915068e69c4673348a4b72f31bfa07).

The code supports a stronger argument about reduced deliberate selection of a named opponent. It does not support an unconditional claim that opponent personality, conduct, rating, or supporter status is randomly assigned. A possible correlation between the conduct score and kindness is an inference to test; this audit does not show that the matchmaker explicitly uses kind-draw history.

## 3. The estimand must be stated before the tests

Let `X` be the assigned opponent's displayed rating minus the focal player's pre-game displayed rating. At game start, refer to a **focal player**, because the future chooser/disconnector role has not yet been realized. Let `S` denote reaching a screened active disconnect opportunity, `B` the final board state, and `Y` granting conditional on having that opportunity.

The existing relative-strength surface concerns `E[Y | X, S=1, B, chooser controls]`. An assignment argument would initially concern `X` among game starts, conditional on the pre-assignment environment. These are different populations and conditioning sets.

For example, an unobserved game-specific state could affect both disconnection and willingness to grant. If opponent strength also affects disconnection, restricting to disconnections can associate strength with that state even when strength was initially independent of it. Conditioning on a competitive final position can create the same problem: a stronger opponent who nevertheless reaches an equal position may have experienced a different game trajectory.

Therefore:

1. Passing pre-game balance tests would improve the assignment argument. It would not prove balance on unobserved assignment inputs.
2. Null measured selection differences would constrain particular selection channels. They would not prove that the selected populations have identical counterfactual membership.
3. A game-start outcome such as “the focal player ultimately makes an eligible kind grant in this game,” coded zero for all other starts, avoids conditioning on `S`. Under credible assignment assumptions it could support an assignment effect on realized grant incidence. It combines the effects on creating an opportunity and responding to it; it does not isolate generosity conditional on an identical opportunity.
4. A causal claim about kindness at the same board state would require additional mediation/selection assumptions, a defensible principal-stratum design, or exogenous variation applied after that state exists. More fixed effects alone do not supply this.
5. Even credible assignment of a stronger opponent identifies an opponent bundle—ability, style and other correlated attributes—not the isolated effect of changing an otherwise identical person's displayed rating, nor a pure respect/desert mechanism or price effect.

Opponent characteristics need not balance against each other across rating groups: stronger opponents naturally differ in experience and other attributes. The central balance question is whether the **focal player's pre-assignment characteristics** predict the strength of the assigned opponent after the intended conditioning.

## 4. What we have and what remains unverified

The private files reside on the Mac; they were not inspected in this session. The published sources document:

| Resource | Useful information | Limitation |
|---|---|---|
| New main opportunity panel | Ratings, reconstructed uncertainty/payoff fields, game and role information, board state, outcome, monthly partitioning | Already selected on active opportunities; cannot alone test entry into those opportunities. |
| IV ordinary-game comparison | 1,661,563 pool-game records; recipient/opponent ratings, exact clock base/increment, archive start time, eligibility and active/passive flags are explicitly loaded by the published addendum | 1,527,795 pass the new nonadjacency restriction; 986,869 enter the primary history-supported analysis. It is a selected comparison frame, not all pool games. Full schema, cohort selection timing and additional history linkage must be checked. |
| All-game chronology | Earlier game-start ordering and account/game keys for activity histories | Start time is not end time or queue time. Confirm its source labels, game coverage and result-code authority before new use. Do not assume the full chronology is pool-only. |
| Earlier opportunity histories | Prior grants/claims, receipt and disconnect-role measures, subject to their contracts | Only observations known before the focal start are legitimate baseline covariates; missing history is not zero. |
| Queue-entry logs and internal matching state | Not established in the provided data contracts | Queue entry, missed waves, contemporaneous rating preferences, blocking, conduct score, trust flag and candidate sets remain unverified. “You already have the data” is too strong for a reconstruction of actual assignment probabilities. |

Documented comparison path:
`derived/replication/chooser_iv_main_rebuild_v100_PRIVATE/ccbc43314875/analysis/comparison.parquet`.
Published size: 173,517,733 bytes; SHA-256: `8bc92d15b9a63e4cc1191ab8342aedd918a36bd341d9a8ddc427e93bb9f156ae`.
See the [selection addendum source](https://github.com/ravideepsethi/intrinsic-prosociality/blob/bf3b2bf9ffedba8f53c61e3e1b55bb457e58a129/code/pool_main_reanalysis_v100/Chooser_IV_Selection_Addendum_v1_0_1/run_addendum.py) and its [source authority](https://github.com/ravideepsethi/intrinsic-prosociality/blob/bf3b2bf9ffedba8f53c61e3e1b55bb457e58a129/code/pool_main_reanalysis_v100/Chooser_IV_Selection_Addendum_v1_0_1/evidence/source_authority.json).

The earlier selection results cannot be described as uniformly clean. The published new-sample handoff reports an active-timeout association of −0.123044 percentage points per SD of the leniency score, and an active-given-candidate association of −0.339364 pp. These are score-selection results, **not tests of relative-strength assignment**. They motivate checking selection against `X` rather than borrowing a reassuring conclusion from a different regressor. See [the handoff, section 11](https://github.com/ravideepsethi/intrinsic-prosociality/blob/bf3b2bf9ffedba8f53c61e3e1b55bb457e58a129/docs/pool_main_reanalysis_v100/Lichess_New_Main_Sample_Handoff_v1_0_2.md). Its later C13 status is now stale and is not used here.

## 5. Proposed analysis in priority order

This is a new diagnostic prompted by an observed result. Freeze it before examining its estimates, label it as such, and keep it outside the prior confirmatory families.

### A. Establish the game-start frame and pre-game fields

Start with the existing comparison frame to establish feasibility. Inspect the producer's sampling rule: a hash sample of games, a sample conditional on future receipt or ever becoming a disconnector, and a baseline-fixed cohort imply different populations. Preserve that scope in every table. Do not recast an outcome-selected cohort as representative assignment data.

Where feasible, define a cohort using information available at a month boundary and follow its subsequent eligible pool-game starts. If constructing that requires unavailable source labels or new acquisition, report the limit and keep the first audit scoped to the existing comparison.

Use one focal orientation fixed before outcomes, or both player perspectives with game duplication and shared-account dependence handled explicitly. Do not orient ordinary games by the eventual chooser role. Confirm unique keys, color conventions, rating-gap sign and source/nonadjacency joins. Analyze the pool parent frame and the operationally selected frame separately to reveal changes introduced by the adjacency screen. Prior pair history can be a baseline attribute, but selecting particular realized pairings on that history still changes the assignment distribution.

### B. Test pre-game balance

Test whether assigned relative strength predicts the focal player's prior kindness rate and its denominator, prior received kindness, prior active timeouts in each role, prior ordinary clock expirations, recent game volume, recent rating changes and available pre-game uncertainty. Include missing-history indicators and support counts. Use only histories completed before game start; earlier game starts alone do not certify that their outcomes were already observed. A lagged month-start or completed-day construction is preferable when end timing is uncertain.

Condition on exact time control, own pre-game rating flexibly, calendar conditions and chooser effects where supported. A proposed timing grid is 1-, 5- and 15-minute game-start bins; a proposed rating grid is 25-, 50- and 100-point own-rating bins, with 5 minutes × 50 points as a candidate primary specification. Freeze the final grid based on outcome-blind support, not which specification gives the best balance. Report sparse cells, loss of support and overlap. These are start-time strata, not observed queues.

Report standardized differences or regression slopes per +100 rating points, confidence intervals, a joint test for a fixed baseline block, and an optional out-of-fold incremental prediction check. Report balance relative to substantively chosen equivalence margins rather than treating `p > .05` as success. Conditioning variables balanced by construction are not independent validation. With millions of observations, tiny differences can be statistically detectable; magnitude and precision both matter.

Do not include final centipawns, focal-game ply, final clocks, disconnection duration or focal-game trajectory features as pre-assignment balance covariates. They occur after assignment. The A1 trajectory build concerns a different treatment timing and does not solve this problem.

### C. Test opportunity and role selection against relative strength

On the same game-start frame, estimate associations of `X` with: any screened candidate ending; active timeout; passive outoftime; the focal player becoming chooser; the focal player becoming disconnector; and an eligible kind grant made by the focal player. Show any residual/unclassifiable role category required by the actual schema. Then report active-given-candidate as an explicitly conditional diagnostic, with its own denominator.

Use only status/clock/role definitions actually observed. If the frame has candidate flags but lacks final-clock screens for ordinary games, do not fabricate those screens or claim it reproduces the main selection event. A time-forfeit candidate is not necessarily an observed deliberate disconnect or deliberate wait.

Retain the existing shared-account-or-date inference where the sample and estimator permit it; document any change. Both player perspectives or repeated opponents require more than treating rows as independent. Candidate = active + passive is an exact coefficient identity only when flags are exhaustive/disjoint and the same rows, weights and design are used. Do not force the role decomposition to sum exactly if the source retains residual roles.

Present unconditional grant incidence per game start alongside the conditional kindness surface, with distinct labels. This is the most useful bridge from assignment to the paper's observed decisions.

### D. Re-estimate the existing relative-strength surface with the audited controls

Retain its frozen rating-gap specification and board-state definitions. Add feasible pre-game histories and tighter timing/own-rating adjustment on a common row set; show the original specification on precisely those rows. Report support and failures rather than silently changing bins to obtain convergence.

Show established-account and source-era sensitivities because of the documented pairing changes. Restricting both players to established ratings must be specified as a selected subpopulation, not a cure for conduct sorting or subsequent opportunity selection. Do not identify era boundaries solely from commit dates as if they were deployment receipts.

Persistence of the surface after these checks strengthens a conditional behavioral fact. It does not by itself identify a controlled direct effect at a fixed realized board state.

### E. Stop before an unsupported randomization claim

Do not uniformly shuffle opponents within approximate rating/time cells and describe that as the platform's assignment distribution. The actual optimizer uses pair-specific constraints and a shared candidate set. A permutation may be an explicitly hypothetical benchmark, but it is not exact randomization inference for this algorithm without the relevant state and an authenticated sampler.

If historical queue snapshots, candidate sets, internal ratings and assignment draws become available, evaluate a separate design around them. Any request to Lichess for such information would require its own authorized outreach. No outreach is required to run the current local probe.

## 6. Wording usable now

Suggested paragraph for the setting/design section:

> The main sample comprises 41.5 million active disconnect decisions in games assigned through Lichess's pool system and passing an observed nonadjacency screen. This restriction makes the assignment mechanism explicit and reduces the scope for selecting a particular opponent or repeatedly choosing the same pairing. The platform's source code shows that pairing depends on rating proximity, waiting across matching waves, rating-range preferences, blocking, and behavioral classifications. Pool assignment therefore provides a structured setting for comparisons, while its conditional randomness remains an empirical assumption. We estimate how the same chooser responds to relative opponent strength within observed decision states and assess observable sorting and entry into those states separately.

The last sentence's “assess” should be future tense until the proposed audit returns, or replaced with “distinguish” if the paper does not retain the new diagnostic. Add the actual balance and selection findings after they exist. Do not assert that the checks passed in advance.

Suggested current relative-strength sentence:

> Among competitive positions, the same chooser is more likely to grant a draw to a stronger-rated opponent. Pool assignment limits deliberate opponent selection, while behavioral sorting and selection into active disconnect decisions constrain a causal interpretation of this gradient.

If diagnostics are favorable, a supported upgrade would describe the gradient as robust to measured pre-game sorting and the measured selection checks. A statement that stronger opponents *cause* greater generosity at an identical board state would still require the additional identification argument described above.

## 7. Runnable next step and runtime

`RUN_PROBE.command` reads only Parquet schemas and footer row counts at the three documented roots. It exports no account IDs, game IDs or other row values. It does not estimate a model, modify private inputs, use the network, or start Stockfish. It samples at most eight chronology footers and inspects up to 32 main-panel footers plus the comparison footer. Missing fields in those inspected files are not proof that the fields are unavailable everywhere.

Expected probe runtime: **5–30 seconds**, allowing **1–2 minutes** if XT_Pro is busy. A full regression runtime is not yet measured; quote it after the schema and required joins are fixed and a pilot has been timed. The current 35-hour recovery/74-hour engine planning figures do not apply to this metadata probe.

Save the ZIP and its sidecar to `~/Desktop/Lichess_Desktop` and run the command in `RUN_COMMAND.txt`. Return the two newly printed `POOL_MATCHMAKING_INPUT_PROBE_...` files. Their result will establish what the next estimator can use; it will not itself certify random assignment.
