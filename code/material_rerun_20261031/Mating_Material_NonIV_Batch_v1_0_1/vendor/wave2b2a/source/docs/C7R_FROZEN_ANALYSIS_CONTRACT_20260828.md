# Campaign 1 C7R closure: frozen analysis contract

Scientific contract frozen in version 1.0.0 on 2026-08-28 before any C7R focal
outcomes were read. Versions 1.0.0 and 1.0.1 both failed closed before pair
Parquet rows, outcomes, or models were read. Implementation release 1.0.2
corrects two authority-layer errors: the frozen physical history run is labeled
`DYNAMIC_SECOND_WAVE_HISTORY_V100_OK`, and 154,693,194 is the raw sampled
pair-event count rather than the filtered processed-history count. It uses
isolated v1.0.2 roots; no estimand, model, control, or threshold changes.

## Purpose

C7R is an append-only, exploratory closure analysis. It does not alter C7,
C7X, Stage 07, Stage 08, or any prespecified family. It answers two questions:

1. How often do focal Stage 07 opportunities involve opponents who have met in
   the certified rated-game chronology before?
2. Do the core fairness and rating-price comparisons survive when the analysis
   is restricted to first rated meetings, and does the C7X relationship survive
   stronger player-pair controls?

No C7R estimate is causal. “First meeting” means no earlier rated meeting in
the certified Lichess chronology beginning in 2013. It cannot rule out casual,
off-platform, or pre-2013 relationships.

## Authorities and immutability

- Stage 07: 47,587,020 rows; 17,328,130 fair rows; its certified receipt and all
  24 physical Parquet files must authenticate.
- Pair history: the existing deterministic whole-pair 2% sample, selected by
  `hash(low_id, high_id, 2026082203) % 50 = 0`. The 154,693,194-row raw sampled
  event layer, its directory receipt, all 16 filtered processed bucket files,
  their receipts, and the fixed public success/summary hashes must authenticate.
  The processed layer retains fair Stage 07 targets plus its original training
  support and therefore is not the authority for the full 24-month focal count.
- Pair sequence: recomputed over the raw sampled rated chronology ordered by
  `utc_ms`, `archive_ordinal`, and `game_id`, then joined to every sampled Stage
  07 focal game. Every fair focal sequence must match the independently
  certified processed-history value exactly.
- C7X: the previously certified v1.0.1 result and the outcome-free private
  classification Parquet must authenticate to SHA-256
  `998b6087806b8300718897537b67828cc893259d96023a92d91de9ed64e331ed`.
- C7 and C7X outputs and private checkpoints are read-only authorities.

## Outcome-blind support freeze

The sampled Stage 07 focal cache is built with game, pair sequence, identities,
fairness/price classifications, game stage, and current-state covariates, but
without `kind_draw` or `outcome_kind_draw`. Before the focal outcome is joined,
C7R freezes:

- total sampled focal rows and unique games;
- first-meeting and repeat-meeting counts;
- repeat prevalence overall, within fair opportunities, within clearly-worse
  opportunities, and by the five frozen fairness bins;
- counts in pair-sequence bands 1, 2, 3–5, 6–10, and 11+;
- chooser, unordered-pair, and directed-pair support;
- C7X chooser, opponent, unordered-pair, and directed-pair arm-switcher support.

The direct 2% sample count must equal the Stage 07 row count selected by the
same deterministic pair hash. Sampled focal rows and event-derived sequences
must be unique by game and conserve exactly. Fair sampled focal rows must
conserve one-for-one against processed-history target rows, with zero sequence
mismatches.

## C7R model inventory

All models are linear probability models, reported in percentage points, with
chooser-clustered standard errors unless a companion pair-cluster result is
explicitly named. Continuous controls are median-imputed, standardized, and
receive missing indicators when needed. All attempts, including low-support or
numerical failures, are retained.

### First-meeting robustness in the deterministic 2% pair sample

Fairness models use fair versus clearly-worse opportunities, hold fixed chooser,
speed, month, hour-of-week, and eight ply bands, and control for current rating
payoffs, clocks, ratings, rating deviations, and tournament status:

- all sampled meetings;
- first meetings only;
- repeat meetings only;
- pooled fair, repeat, and fair-by-repeat interaction.

A fifth model estimates the repeat-meeting association within fair opportunities
with evaluation-bin fixed effects and the same current-state controls.

Price models use fair opportunities and hold fixed chooser, evaluation bin,
speed, month, hour-of-week, and ply band, plus current-state controls excluding
the payoff whose sign defines the exposure:

- nonnegative versus costly draw payoff, all/first/repeat meetings;
- strictly positive versus strictly negative draw payoff (exact zero excluded),
  all/first/repeat meetings.

### C7X relationship closure

Using the certified outcome-free C7X classification joined anew to Stage 07:

- exact re-estimation of the certified chooser-FE primary model;
- chooser-arm-switcher-only version;
- chooser plus opponent fixed effects;
- directed chooser-opponent-pair fixed effects, chooser clustered;
- the same directed-pair estimate clustered by unordered pair;
- directed-pair estimate restricted to ply greater than 10;
- exact chooser-FE recovery for prior-arm gaps of at most 7 days;
- directed-pair companion for gaps of at most 7 days when estimable.

For these modest C7X samples, small context fixed effects are explicit dummies
and the one high-dimensional identity effect is removed exactly in one pass.
The two-player model uses alternating projections. The certified primary
coefficient and standard error must reproduce within `1e-6`.

## Multiplicity, interpretation, and privacy

C7R has epistemic label X, is outside Holm families, and is descriptive and
exploratory. Friendship, stable pair traits, selection into repeated play, and
unobserved interaction remain alternative explanations. Public output contains
only aggregate counts, rates, model estimates, QA receipts, executed source,
and hashes. No row-level IDs or private Parquet files are transferred.

## Frozen performance policy

DuckDB scans and sorts use eight workers; PyArrow is used only for metadata
authentication. Large HDFE models are run sequentially to
keep memory bounded; the small C7X models use exact vectorized reductions.
Stage 07, raw pair-event, and processed-history files are physically
authenticated once per run and their authentication receipt is reused within
that run. The 154.7-million-row event layer is scanned once with only pair IDs,
chronology keys, and game ID projected. Parquet reads are column-pruned and
persistent private caches are ZSTD-compressed.
