# A2 score-reader correction, September 28, 2026

The uploaded original result is `KAC_A2_RESULT_6147f8e2098bf816.zip`, SHA-256
`9522a443e2ea761e409d0befdc761639460a748a017f0b71c72f660737011f90`.
Its ZIP, report checksums and executed code signature all verified. The frozen
sample has 260,863 opportunities, 20,000 choosers and 3,755 grants. The run took
31,276 seconds (8 hours 41 minutes). All game replays verified.

## Why the A2 estimates need replacement

The original code retained finite scores only when the merged final engine
information was unbounded and its reported nodes reached 100,000. It saved no
sequence of preceding exact scores. A node-limited search can terminate while
its current iteration has reported only a bound. Discarding these searches
selects positions according to engine-search behavior. Only 15,869 of 72,575
competitive opportunities after ply 10 (21.87%) passed all five score checks,
against 106,899 of 141,029 losing opportunities (75.80%). Before/at ply 10,
only 122 of 22,435 competitive opportunities (0.54%) passed. The retained late
competitive opportunities grant at 3.81%, versus 2.56% in the full frozen late
competitive sample. These are substantial selection differences.

A separate, reproducible hazard affects the use of the merged information:
python-chess merges successive info dictionaries with `dict.update`. An earlier
bound flag can remain after a later score message has no such flag. The correct
reader attaches flags to their own score message. The synthetic protocol test
reproduces this hazard. In the 17 live SF18 opening-position searches used here,
the observed loss instead came from genuinely bounded final updates: 12 of 17;
no stale flags were observed in those 17 searches. We do not attribute the full
empirical coverage loss to stale flags without the Mac raw-status audit.

## Corrected measurement rule

Search each required FEN with the same pinned SF18 binary, one thread, 64 MB
hash, a new game/cleared search state and 100,000 requested nodes. Wait for
bestmove. Select the last unbounded score message received during that search.
Never use a bound as a point estimate. Retain the complete score-message sequence,
the selected score's nodes and depth, total reported search nodes, the final
message's bound flags and whether the selected point precedes a final bound.
An unbounded UCI score is an engine estimate, not proof of the position's value.

This uses all available information at completion of the fixed-budget search.
The selected exact iteration can have a smaller node count than the completed
search. That is reported explicitly; it is not falsely described as an exact
score message emitted at node 100,000. Exact mates remain separate from CP.
Unusable terminal/no-score results remain visibly unavailable. A finite search
that truly does not reach the budget remains SHORT and is not admitted.

This is a documented measurement correction after seeing the first A2 output,
not a preregistered change. In 17 live SF18 tests the corrected rule retained all
17 fixed-budget evaluations. Twelve used the preceding unbounded message.

## Work reused and recomputed

- Authenticate the original frozen target and every original replay/score unit.
- Inventory BOUNDED/NO_SCORE/unusable SHORT records; retain usable scores.
- Deduplicate required searches by full FEN, including its counters; evaluate
  each unique FEN once with white-oriented scores and restore the rival's sign
  when projecting the original rows.
- Use up to ten workers, one engine/BLAS thread per worker, 128-position atomic
  engine checkpoints and compressed Parquet. Each feature worker receives only
  its own small replacement shard. Completed searches resume by content hash.
- Preserve all original files and the original empirical result. New scores,
  raw score-message traces, features and estimates have a new identity.
- Refit the unchanged 53 A2 specifications, same sample rules, controls, chooser
  fixed effects, clustering, contrasts and Holm families. Assert that the 18
  unaffected full-sample curve/clock/material models reproduce their previous
  estimates and standard errors.
- Do not fetch games/profiles, rebuild the certified panel, resample accounts,
  or scan the all-game chronology. History tests remain pending.

## Interpretation

Do not put the original trajectory/proxy-adjusted A2 coefficients into the paper
as validated results. The original own-loss coefficient in competitive positions
was negative, so even that selected result did not support the proposed blanket
absence-of-blame claim. Its corrected magnitude and inference remain unknown.
A nonsignificant proxy coefficient would not establish that blame is absent;
a nonzero one would not identify intentional departure.

The existing full-panel A1 continuous profile is a separate analysis of canonical
final evaluations and does not use this rejected A2 trajectory support. This
repair does not change those canonical evaluations or certify their upstream
reader. No new causal claim or monotonicity constraint is introduced.

Read the repaired coverage and score-depth diagnostics before interpreting new
regressions. Upload the new REPAIRED_RESULT ZIP and SHA-256 sidecar after the run.

Primary implementation source: https://python-chess.readthedocs.io/en/latest/_modules/chess/engine.html
(AnalysisResult.post, Protocol.analyse and the UCI info parser).
Live-engine test: official SF18 Ubuntu x86-64 AVX2 binary, public opening FENs;
the production Mac runner separately requires the existing pinned Mac binary.
