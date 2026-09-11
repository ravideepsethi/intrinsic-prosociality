# Dynamic prosociality second wave: source-contract amendment

**Version:** 1.0.1

**Date:** August 22, 2026

**Timing:** after the outcome-blind feasibility audit and before any B2, F2, or E1 outcome estimation

**Parent plan:** `Dynamic_Prosociality_Second_Wave_Analysis_Plan_v1_0_0_2026-08-22.md`

## 1. Reason for the amendment

The authenticated feasibility audit inspected all 852 files in the canonical
7,763,847,245-row all-game chronology. Its schema contains player identifiers,
displayed pre-game ratings, realized rating changes, game identifiers, and timestamps,
but no pre-game rating-deviation field. The compact rating-replay inputs also contain
no RD field and cover only October 2024 through July 2025.

Exact pre-game RD remains available in the certified Stage 07 panel for the locked
timeout-opportunity sample. It is not available for the all-game salience population.
Creating it would require a new full-history hidden-state replay, not a join to an
existing canonical source.

The feasibility receipt states that all families are constructible without an
amendment. That statement is correct for the variables needed to construct B2, F2
thresholds, stopping, and E1 re-pairing risk, but it is incomplete with respect to the
plan's proposed RD screen in the **all-game F2 salience gate**. This amendment resolves
that discrepancy explicitly. No stopping outcome, re-pair outcome, post-event kindness
rate, or new kindness coefficient informed the change.

## 2. F2 salience settled-account screen

For the all-game F2 salience gates only, the unavailable `pre_game_rd <= 110` primary
screen and `pre_game_rd <= 80` sensitivity are replaced as follows.

### 2.1 Round-number gate

The primary round-number salience sample requires, before the focal game:

- at least 50 rated-standard games in the same speed pool;
- at least 365 days since the first observed rated-standard game in that pool; and
- nonmissing positive timestamps, displayed pre-game rating, and realized rating
  change.

Sensitivities require at least 25 and at least 100 prior same-pool games, while retaining
the 365-day history requirement. These screens are computed strictly from history
preceding the focal game.

### 2.2 Personal-best gate

The original personal-best requirements—at least 50 prior same-pool games and at least
365 days since the first observed pool game—remain the primary settled-account screen.
The same 25- and 100-prior-game sensitivities are added for symmetry with the
round-number gate.

These history screens are proxies for a settled, non-novice rating state. They are not
called reconstructed RD and must not be interpreted as exact substitutes for RD.

### 2.3 Downstream kindness models unchanged

The downstream Stage 07 F2-R and F2-P kindness models retain the exact certified
`chooser_pre_rd_v2 <= 110` primary restriction and `<= 80` sensitivity. No downstream
eligibility rule changes.

## 3. Ordinary-game and ordering contract

For the all-game salience and E1 source build:

- included speed pools are `ultrabullet`, `bullet`, `blitz`, `rapid`, and `classical`;
- `correspondence` and `unknown` partitions are excluded because 30-minute stopping and
  pool-liquidity interpretations are not coherent for those categories;
- displayed post-game rating is the integer pre-game rating plus the realized integer
  rating change for the focal color;
- records with `utc_ms <= 0`, missing or nonpositive player identifiers, self-pairs,
  missing ratings, or missing realized rating changes are excluded;
- user-event ties are ordered by `utc_ms`, `archive_ordinal`, `game_id`, and color;
- pair-event ties are ordered by `utc_ms`, `archive_ordinal`, and `game_id`; and
- all running counts, peaks, first-meeting flags, and leave-pair-out quantities use only
  information strictly preceding the focal event.

The primary stopping outcome remains no later included rated-standard game by the same
account within 30 minutes, regardless of included speed pool. Same-speed stopping and
15-/60-minute gaps remain sensitivities.

## 4. E1 past-only training windows

For a focal calendar month beginning at time `M`, the primary re-pairing-risk training
window contains games whose start times lie in `[M - 395 days, M - 30 days)`. Thus every
30-day re-pairing outcome is fully mature before the focal month begins. The focal pair's
own counts and successes are removed before applying the Jeffreys prior. Cell
coarsening, the 1,000-game minimum, first-ever-pair primary sample, and p90-minus-p10
reporting remain as specified in the parent plan.

## 5. Multiplicity and interpretation unchanged

The four-slot Holm family remains B2, E1, F2-R, and F2-P. A failed F2 salience gate still
receives p = 1. The amendment changes no sign prediction, threshold grid, bandwidth,
event horizon, placebo grid, test family, or reporting rule.

F1 remains permanently retired.
