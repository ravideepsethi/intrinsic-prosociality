# Campaign 1 C7X full-Stage-07 exploratory reciprocity plan v1.0.1

**Dated:** 2026-08-27  
**Epistemic label:** X throughout  
**Status:** outcome-informed exploratory extension, written after the
prespecified C7 2% support gate and its focal outcomes were observed

## 1. Why this is a separate analysis

The prespecified C7 analysis remains the deterministic 2% pair-cluster sample.
It found 33 benefactor-facing fair opportunities, below its frozen threshold of
1,000, and therefore remains a failed-gate descriptive result. Nothing in C7X
changes, replaces, rescales, or upgrades that result.

C7X asks the narrower follow-up question that can be answered from the complete
certified Stage 07 panel: among focal fair opportunities for which Stage 07
itself records an earlier reversed-role mercy or claim by the current opponent,
is focal kindness associated with the latest such action? This is a post-gate,
post-outcome analysis. Every estimate is exploratory, retained regardless of
sign, and excluded from Holm family D.

## 2. Certified universe and limitation

The only row-level scientific input is the authenticated 24-month Stage 07
panel: 47,587,020 unique opportunities from November 2023 through October 2025,
including 17,328,130 fair opportunities. No profile, Patron, API, PGN,
Stockfish, or rebuilt chronology input is read.

Stage 07 does not contain every game in the 7.764-billion-game rated chronology.
C7X can therefore identify prior actions only when both the prior timeout
opportunity and the focal opportunity are in Stage 07. It is not a census of
all repeat pairs or all prior interactions. The estimand is explicitly
conditional on an observed earlier reversed-role Stage 07 arm decision.

## 3. Temporal and role rules

An unordered pair is `(low_id, high_id)`. Version 1.0.0 failed closed after an
outcome-blind scan found that distinct games can share `(utc_ms,
archive_ordinal)` within a pair-role history. It never joined the new focal
kindness outcome. Version 1.0.1 therefore runs a dedicated aggregate collision
diagnostic and freezes its branch before continuing. Event order is the exact
original-C7 lexicographic key `(utc_ms, archive_ordinal, game_id)`. Repeated
game IDs, null order fields, or any unclassified collision still fail closed.
A prior
action must be strictly earlier than the focal action. To qualify as reciprocity, roles must reverse:
the current opponent was the chooser in the prior event and the current chooser
was the disconnected player.

Prior arm decisions are:

- benefactor: `kind_draw = true`;
- claimer: `timeout_chooser_win = true`.

Rows satisfying both definitions are prohibited by QA. The primary exposure is
the latest earlier reversed-role arm-eligible Stage 07 action. The focal sample
contains only certified `fair_competitive` opportunities.

## 4. Outcome-blind construction and exact old-sample validation

Before reading or joining the focal `outcome_kind_draw` field, production will:

1. authenticate the Stage 07 success receipt and every physical monthly
   Parquet;
2. create ZSTD-compressed private Parquets for prior arms, fair focal rows, the
   latest reversed arm, and the final exposure classification;
3. publish the aggregate duplicate-source-order diagnostic, select only the
   documented game-ID tertiary-key branch, and mark classifications that depend
   on that tie-break;
4. freeze counts for the latest-arm, same-speed, exclusive-history, recency,
   chooser-cluster, pair-cluster, and within-chooser-overlap supports; and
5. apply the historical pair predicate
   `hash(low_id, high_id, 2026082203) % 50 = 0` to the full classification.

The historical restriction must exactly reproduce all already observed C7
support facts: 33 latest benefactor and 557 latest claimer rows; 29 and 534 in
the same-speed version; 28 benefactor-only and 543 claimer-only rows in the
exclusive-history version; and 19 conflicting-history focal rows. Failure of
any equality stops the run before the focal outcome join. This validates the
new full-panel machinery against the certified old implementation without
using its kindness outcomes.

Because the old 2% outcomes are already known, this checkpoint is described as
blind to the *new full-panel focal-outcome join*, not as an ex-ante design.
After that join, a separate validation must reproduce the already published
old-sample outcome counts (12 kind draws among 33 benefactor-facing rows and 25
among 557 claimer-facing rows). This is a replication audit, not a model or
selection rule.

## 5. Models

The focal outcome is `outcome_kind_draw`. The exposure is coded one for latest
benefactor and zero for latest claimer, so every reported contrast is
benefactor minus claimer.

The primary C7X model is the adjusted specification applied to the full Stage
07 classification, amended before the first successful full-panel outcome join
to incorporate the certified game-length finding:

- chooser fixed effects;
- current evaluation bin, speed, month, hour-of-week, and the eight certified
  ply-band fixed effects (`0--4`, `5--6`, `7--8`, `9--10`, `11--20`, `21--40`,
  `41--80`, `81+`);
- current draw payoff, win premium, chooser and opponent clocks, Elo ratings,
  rating deviations, and tournament indicator as numeric controls; and
- chooser-clustered standard errors.

All models are linear-probability associations. Missing numeric controls use
the common frozen median-plus-missing-indicator rule. The primary attempt is
made when each arm has at least 1,000 rows and there are at least 100 chooser
clusters; estimator or rank failures are retained rather than suppressed.

The following planned exploratory companions are all attempted and retained:

- the exact v1.0.0 planned primary without ply bands as a recovery benchmark;
- the ply-adjusted primary with unordered-pair clustering;
- a ply-adjusted pooled model without chooser fixed effects;
- same-speed and exclusive-history ply-adjusted models;
- a tie-independent sensitivity excluding any focal row sharing its source key
  with an eligible prior or whose selected prior source key is duplicated;
- a `ply_count > 10` model and a non-tournament model;
- ply-adjusted latest-arm gaps of at most 7, 30, 180, and 365 days; and
- separate descriptive rows for 0--7, 8--30, 31--180, and over-180-day gaps.

Raw arm counts and rates are reported without treating opportunity-level Fisher
or iid normal tests as valid inference. The clustered adjusted attempts are the
inferential records.

## 6. Interpretation and reporting boundary

C7X is not randomized. Prior mercy versus prior claiming can reflect stable
pair relationships, selection into repeat interaction, opponent type, or
unobserved game history. Chooser fixed effects remove stable chooser level
differences but do not make the prior action exogenous. The result can sharpen
the paper's descriptive evidence about recognizable direct reciprocity; it
cannot establish a causal effect of receiving mercy.

Every favorable, null, adverse, low-support, rank-deficient, or numerically
failed result is public. No account-level rows, IDs, private Parquets, or model
arrays enter the result bundle or Git. All large private checkpoints are
resumable and live outside the public tree.
