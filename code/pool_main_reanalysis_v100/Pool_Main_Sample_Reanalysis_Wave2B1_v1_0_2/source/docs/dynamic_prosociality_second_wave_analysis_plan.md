# Dynamic prosociality: second-wave analysis plan

**Version:** 1.0.0  
**Frozen date:** August 22, 2026  
**Status:** outcome-blind design for feasibility review; no second-wave effect has been estimated  
**Main panel:** November 1, 2023 through October 31, 2025

## 1. Purpose and relationship to the certified results

The certified dynamic core established three facts in the locked 24-month sample:

1. receipt of mercy predicts a 1.0047-percentage-point increase in later kindness at
   the recipient's first subsequent fair opportunity;
2. mercy predicts immediate reentry but not 30-day engagement; and
3. kind actions among repeat granters are more temporally clustered than the frozen
   conditional static-propensity null predicts.

This plan does not reopen those estimates or their Holm family. It follows the
pre-existing gates in `docs/dynamic_prosociality_analysis_plan.md` and asks what the B1
rejection means, whether player-salient rating reference points matter, and whether the
empirically measured shadow of future interaction predicts kindness.

The second wave has exactly four confirmatory slots:

| Slot | Hypothesis | Confirmatory outcome or statistic |
|---|---|---|
| B2 | First-observed-grant dynamics | Excess 24-hour post-event kindness relative to the conditional-randomization null |
| E1 | Shadow of the future | Kindness difference associated with a p90-to-p10 increase in past-only re-pairing risk |
| F2-R | Round-number reference point | Kindness contrast for action gaps spanning a displayed 100-point boundary, admitted only if round-number salience passes |
| F2-P | Personal-best reference point | Kindness contrast for action gaps spanning the chooser's prior speed-pool peak, admitted only if personal-best salience passes |

Holm adjustment will use all four slots. A downstream F2 branch whose salience gate
fails receives p = 1 in the four-slot family. This prevents a smaller multiplicity
penalty from being selected after seeing the salience results.

Session profit/loss, previous-result tilt, fatigue, lifecycle learning, and moral hazard
are not part of this family. They remain candidates for a later mechanism paper.

## 2. Authorities and privacy

The paper-facing kindness authority remains the certified Stage 07 panel:

```text
/Volumes/XT_Pro/lichess_kindness/derived/replication/analysis_panel_24m_sf100k
```

The all-game chronology authority is the authenticated 7,763,847,245-row replay event
layer represented by the certified A3 chronology manifest. The extracted PGN-header
replay inputs may be used for displayed ratings and realized rating changes only after
their month coverage and schema are authenticated.

The certified B1 sample and cross-fitted static propensities are reused without
refitting:

```text
/Volumes/XT_Pro/lichess_kindness/derived/replication/dynamic_prosociality_core_v102_PRIVATE/b1_repeat_granter_private.parquet
/Volumes/XT_Pro/lichess_kindness/derived/replication/dynamic_prosociality_core_v102_PRIVATE/b1_crossfit_propensity_private.parquet
```

Account identifiers, pair histories, running peaks, session histories, and event-level
predictions remain private on XT_Pro. Only aggregate support, models, figures, receipts,
and hashes may enter Git. Patron/profile data are neither required nor permitted as an
input to this second wave.

## 3. Outcome-blind feasibility gate

Before second-wave outcomes are estimated, a dated feasibility audit will:

- authenticate Git HEAD, the Stage 07 authority, the certified dynamic-core receipt,
  the B1 private checkpoints, and the chronology manifest;
- report B2 event-window support without tabulating post-event kindness;
- count F2 action-gap support without reading `kind_draw`;
- inspect chronology and replay-input schemas, date coverage, row counts, and proposed
  checkpoint shards;
- determine whether round-number salience, personal-best salience, and E1 are
  technically constructible; and
- write no account-level output.

Support-based amendments are allowed after this gate and before any salience or
kindness outcome is estimated. Any amendment must be dated, hashed, and committed with
the final producer before execution. Effect signs, rates, test statistics, and
threshold-specific stopping behavior may not inform an amendment.

## 4. B2: first-observed-grant dynamics

### 4.1 Scope

B2 uses the certified B1 population: 64,331 repeat granters with 1,017,944 actual fair
opportunities, 273,483 kind draws, at least four opportunities, at least two kind draws,
and at least one non-kind choice. The estimand therefore concerns repeat granters, not
all choosers.

The event is the chooser's **first observed kind draw within the locked panel**. It is
not described as the chooser's first lifetime grant. Left and right censoring remain
part of both the observed and simulated statistics.

### 4.2 Conditional null

For chooser i and actual opportunity j, let p_ij be the already-certified cross-fitted
static propensity and K_i the chooser's observed total number of kind draws. Under the
null, a binary sequence is redrawn across the chooser's actual opportunity times with
probability proportional to

```text
product_j p_ij^y_ij (1 - p_ij)^(1 - y_ij), conditional on sum_j y_ij = K_i.
```

Every simulated sequence defines its own first observed grant. It is invalid to compare
the observed event study with a flat zero line or to hold the observed event date fixed
under the null.

### 4.3 Statistic and inference

For horizon h, define S_h as the pooled kindness rate over actual opportunities strictly
after the sequence-specific first grant and no more than h later. Choosers with no
opportunity in that window contribute neither numerator nor denominator. The reported
effect is

```text
Delta_h = S_h(observed) - mean_b S_h(simulation b).
```

The primary horizon is 24 hours. Six hours and seven days are prespecified secondary
horizons. The producer will use 4,999 conditional draws and the plus-one two-sided
randomization p-value. The seed and the exact sampler will be frozen in code before
execution. Simulations reuse the B1 probabilities and do not refit the static model.

The interpretation is localization of the certified non-exchangeability around the
first observed grant. A positive Delta is consistent with habit, activated identity,
mood, or self-signaling; a negative Delta is consistent with licensing. B2 alone does
not identify one mechanism.

### 4.4 Secondary B3 contrast

The first grant is classified by its chooser draw payoff as costly, exact zero, or
favorable. The costly-versus-favorable difference in Delta_24h is secondary and will be
reported with a confidence interval. It is not a fifth confirmatory test.

## 5. F2 salience gates

The November 2025 color-advantage relocation design is permanently retired. It is not
an F2 input, placebo, or robustness exercise.

F2 uses a sequential gate: player behavior in all-game chronology must first show that
the proposed threshold is salient on Lichess. No kindness estimate is run for a branch
that fails its own gate.

### 5.1 Sessions and stopping

The primary stopping outcome is no subsequent rated-standard game by the same account
within 30 minutes, regardless of speed pool. Same-speed stopping is secondary. Sessions
are therefore separated by gaps greater than 30 minutes; 15- and 60-minute definitions
are sensitivities.

Games with a pre-game rating deviation above 110 are excluded from the primary
salience analysis. RD <= 80 is a stability sensitivity. Only ordinary rated-standard
games with nonmissing displayed ratings, realized rating changes, and timestamps enter.

### 5.2 Round-number salience (F2-R gate)

The primary sample consists of positive-rating-change games that approach a 100-point
boundary from below. Boundaries from 1000 through 2600 are pooled with boundary fixed
effects. The running variable is displayed post-game rating minus the approached
boundary. The primary local window is +/-10 rating points with local-linear terms on
each side and triangular weights; +/-5, +/-15, and +/-20 are sensitivities.

The estimand is the discontinuity in 30-minute stopping just above versus just below
the boundary. Placebo grids are boundaries ending in 50 and boundaries shifted by 37
points. F2-R passes only if:

1. the 100-point discontinuity is positive with two-sided p < 0.05; and
2. the 100-point discontinuity exceeds the average of the two placebo-grid
   discontinuities with two-sided p < 0.05.

Density, exact-rating support, threshold-specific estimates, and pre-rating-distance
balance are mandatory diagnostics. Because the running variable is discrete, the
producer must report integer-bin support and a randomization-style window comparison
alongside conventional local-linear inference.

### 5.3 Personal-best salience (F2-P gate)

The prior peak is the maximum displayed post-game rating in the same speed pool strictly
before the focal game. The primary sample requires at least 50 prior rated games in that
pool and at least 365 days between the first observed pool game and the focal game.
Positive-rating-change games approaching the prior peak from below are analyzed around

```text
displayed post-game rating - prior peak = 0.
```

The same stopping outcome, bandwidths, RD restrictions, and discrete-running-variable
diagnostics apply. Pseudo-peaks at prior peak + 37 and prior peak + 50 are placebos.
F2-P passes only if the true-peak discontinuity is positive at p < 0.05 and exceeds the
average placebo discontinuity at p < 0.05.

### 5.4 Downstream kindness contrasts

For a fair Stage 07 opportunity, define the action gap as the interval between the
chooser's reconstructed post-draw and post-win ratings. F2-R treatment equals one when
that interval spans a displayed 100-point boundary:

```text
post_draw < boundary <= post_win.
```

The exact Glicko reconstruction is primary. A rounded visible heuristic is mandatory,
and exact/heuristic disagreement is reported rather than silently resolved. Ending-50
and +37 grids are included as placebo indicators. The primary coefficient is the
100-point pivotal contrast net of the average placebo-grid contrast.

F2-P treatment equals one when the action gap spans the chooser's prior speed-pool peak.
The primary coefficient is the true-peak pivotal contrast net of the average +37/+50
pseudo-peak contrast.

Both models use fair opportunities, exclude provisional chooser states, include chooser
fixed effects, month fixed effects, speed and tournament indicators, smooth current
rating, exact draw payoff, win premium, board evaluation, clocks, and current-game
controls. Standard errors cluster by chooser. Negative coefficients are predicted.

Round-number results test a salient current-state reference point. Only the personal-
best branch is genuinely history-dependent.

## 6. E1: the shadow of future interaction

### 6.1 Past-only re-pairing score

For every focal calendar month, re-pairing risk is trained only on games whose focal
dates precede that month and whose 30-day rematch outcomes are fully observed before
the month begins. The primary training window contains the preceding 365 eligible
focal days.

The pool cell is:

```text
speed x 100-point average-rating band x UTC six-hour block x weekday/weekend.
```

For a training game, the target is whether its unordered pair plays another rated-
standard game within 30 days. The cell estimate is the empirical rate with a fixed
Jeffreys shrinkage prior. Cells with fewer than 1,000 training games are coarsened in a
prespecified order: drop weekday/weekend, then widen rating to 200 points, then drop
the hour block. No cell is chosen using kindness.

The focal pair's own prior observations are subtracted from its cell numerator and
denominator. Thus the assigned score is past-only and leave-focal-pair-out. A separate
all-history pass flags whether the focal pair has ever met before.

### 6.2 Primary sample and estimand

The primary E1 sample consists of fair Stage 07 opportunities at a pair's first-ever
meeting. The model includes chooser fixed effects, month fixed effects, speed, rating
band, UTC block, weekday/weekend, board evaluation, draw payoff, win premium, ratings,
RD, clocks, tournament status, and current-game controls. Standard errors cluster by
chooser.

The confirmatory estimand is the fitted kindness difference from the observed p10 to
the observed p90 of the past-only re-pairing score. A positive difference is predicted
by instrumental future-return motives. A flat estimate is compatible with intrinsic
motives but is not proof of them. A substantively informative null additionally
requires the upper 95% confidence limit to be below +0.30 percentage points.

Direct reciprocity among previously paired opponents is secondary E2 evidence and is
not a fifth confirmatory test.

## 7. Execution and checkpoint contract

The full producer will be API-free, resumable, and deterministic.

- Chronology work is sharded by speed-month and writes authenticated Parquet
  checkpoints on XT_Pro.
- Full-history peak and first-pair state is carried forward only in private state.
- E1 rolling-cell aggregates are built without Stage 07 kindness, frozen, and hashed
  before the kindness join.
- B2 simulations checkpoint disjoint draw ranges and aggregate in ascending draw order.
- Each checkpoint authenticates its input footer signature, configuration hash, row
  count, bytes, and SHA-256.
- A rerun must reuse valid checkpoints and fail closed on a partial or mismatched one.
- DuckDB/Arrow scans use explicit projected columns; no 7.76-billion-row materialized
  all-column table is permitted.

The feasibility pass may estimate runtime and disk demand but may not relax the
identification or privacy rules above.

## 8. Reporting and packaging

Every reported estimate includes the raw unit, percentage-point magnitude where
applicable, control mean, relative magnitude, confidence interval, raw p-value, and
Holm-adjusted p-value. Figures show effect sizes and null distributions, not only
significance markers.

The current paper receives B2, E1, or F2 only if the result is unusually decisive and
clarifies the paper's core interpretation without displacing the certified A1/B1
results. Otherwise these analyses form the opening of a separate dynamics paper.

No second-wave result may be called preregistered. The accurate description is:
"design and code frozen before the corresponding second-wave outcomes were
estimated," supported by Git hashes and certified receipts.
