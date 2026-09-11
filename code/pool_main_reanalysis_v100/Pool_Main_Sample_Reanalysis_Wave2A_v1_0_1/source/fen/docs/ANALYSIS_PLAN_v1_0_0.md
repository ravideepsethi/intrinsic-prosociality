# Equality/FEN audit: frozen analysis plan v1.0.0

**Frozen:** 2026-08-27, before running this package on the physical Stage 07
rows. The already certified five-bin raw rates are known; the new short-game,
FEN-commonness, and engine-zero results are not.

## 1. Questions and distinct zeroes

This audit addresses zero **engine evaluation** and the roughly-equal fairness
bin. It does not reopen the separate zero **rating payoff** question.
Reference-demand v1.0.4 remains the next independent package for exact-zero
rating-payoff rows, displayed integer rating gaps, and the E1–E5
sign-versus-magnitude/RD decomposition.

The questions are:

1. Does the raw roughly-equal minus disconnected-better bump persist in the
   current 24-month/100k-node panel?
2. Does it persist with chooser, month, and speed fixed effects plus the
   legacy-analogue win-premium and clock controls?
3. Is any bump larger among opportunities with `ply_count <= 10`?
4. Within short opportunities, is it related to exact terminal-position
   commonness?
5. Is there a local level change, exact-zero spike, or slope change at zero
   engine evaluation, and is zero unusual relative to placebo knots?

All results are descriptive associations. Engine evaluation is neither
randomly assigned nor manipulable by the chooser at the timeout decision, and
the local models are not presented as regression-discontinuity estimates.

## 2. Frozen definitions

- Outcome: `100 * kind_draw`, measured in percentage points.
- Roughly equal: `-100 <= engine_eval_cp_disconnected <= 100`.
- Disconnected better: `101 <= engine_eval_cp_disconnected <= 299`.
- Short/legacy opening-stage rule: `ply_count <= 10`.
- Temporal halves: Nov 2023–Oct 2024 and Nov 2024–Oct 2025.
- Speed tiers: bullet/ultrabullet, blitz, rapid, classical/correspondence,
  and other/missing.
- Chooser fixed-effect and cluster authority: `chooser_username_norm`, mapped
  only inside private run state to a deterministic dense integer.

Clock controls are `log(1 + max(clock_seconds, 0))` separately for chooser
and disconnected player, plus a joint-missing indicator. Missing clocks are
set to zero only after that indicator is constructed. The legacy-analogue
adjusted model includes win premium but not draw payoff; a separately labeled
price-adjusted sensitivity also includes draw payoff and the nonnegative-draw
indicator.

## 3. Outcome-blind FEN design

The design stage scans only `game_id`, `month`, `ply_count`, and
`fen_after_last_move`; it is forbidden from selecting `kind_draw` or any other
outcome. It validates exactly 4,737,283 rows with `ply_count <= 10`.

Two terminal-position signatures are counted across all short opportunities:

1. FEN4: piece placement, side to move, castling rights, and en-passant target
   (the first four FEN fields).
2. Board: piece placement only (the first FEN field).

Only each row's leave-one-out frequency and tier are retained in the private
cache; no FEN string enters public output. Frequency tiers are frozen as:
singleton, 2–9, 10–99, 100–999, and 1,000+ occurrences. Continuous models use
`log1p(total_frequency - 1)`.

These are position-frequency proxies, not opening-path measures. A common
position may be reached by transposition; an uncommon position can belong to
an otherwise common ECO family; and the measures contain no chooser-specific
prior-exposure history.

## 4. Equality-bump estimands

The canonical raw contrast is roughly equal minus disconnected better. The
model grid is frozen as:

- E0: raw difference with chooser-clustered uncertainty;
- E1: chooser fixed effects;
- E2 (primary modern analogue): chooser, month, and speed fixed effects;
  win premium and clock controls;
- E3: E2 plus draw payoff and favorable/nonnegative draw;
- E4: E3 plus log ply, log-ply squared, and tournament status;
- E5: E2 with short, roughly-equal × short, and the short main effect;
- E6/E7: E2 separately for short and longer games;
- E8: E2 separately by temporal half; and
- E9: E2 separately by speed tier when support permits.

Raw rates are also tabulated by the five certified fairness bins and frozen
ply bands: 0–4, 5–6, 7–8, 9–10, 11–20, 21–40, 41–80, and 81+.

Within short equality/better rows, the commonness models use chooser, month,
speed, and exact-ply fixed effects:

- C0: adjusted roughly-equal coefficient without commonness;
- C1: C0 plus FEN4 log commonness and its interaction with roughly equal;
- C2: C0 plus board log commonness and its interaction; and
- C3: C1 with the price-adjusted E3 controls.

The package reports equality effects implied by C1/C2 at the observed 10th,
50th, and 90th percentiles. It does not use a post-result attenuation cutoff
to declare that commonness “explains” the bump.

## 5. Engine-zero estimands

Raw outputs include exact-centipawn support from -300 to +300, 25-cp display
bins with exact zero separate, heaping modulo 5/10/25/50, symmetric left/right
counts, and exact-zero mass.

The fixed-effect local model uses strict-negative evaluation as the omitted
side and includes positive distance, negative distance, a strict-positive
indicator, an exact-knot indicator, draw payoff, win premium, and clock
controls. It absorbs chooser, month, and speed fixed effects and clusters by
chooser. Reported functions are:

- right slope;
- left-distance slope;
- derivative change (`right slope + left-distance slope`);
- strict-positive level shift; and
- exact-knot spike.

Primary zero windows are ±25, ±50, ±100, ±200, and ±300 cp. Donut checks use
±100 and ±200 with |evaluation| <= 5, 10, or 25 removed. Placebo knots are
-200, -100, 0, +100, and +200 cp with a ±100-cp window. Normal-approximation
two-sided p-values and Holm adjustments are reported across the five knots,
separately for slope-change and positive-side level-shift statistics.

The ±100 model is repeated by temporal half and short/long status. Speed-tier
raw curves are reported; subgroup fixed-effect models fail closed rather than
silently changing specification when support or rank is inadequate.

## 6. Interpretation rules

- “Raw bump present” means the canonical raw equality-minus-better estimate is
  positive. It is not an adjusted or causal statement.
- “Adjusted bump detected” requires a positive E2 coefficient with |t| >=
  1.96. Otherwise report no adjusted evidence; do not equate that with proof
  of equality.
- “Short-game concentration detected” requires the E5 interaction to be
  positive with |t| >= 1.96. This is heterogeneity, not mechanism.
- FEN commonness is summarized through C1/C2 point estimates and uncertainty.
  No causal-explanation label is generated.
- Zero is not called unique unless its Holm-adjusted diagnostic rejects while
  every nonzero placebo knot fails to reject in the same family. Even then the
  language is descriptive uniqueness, not causal identification.

## 7. Privacy and publication boundary

Public output contains no username, game ID, FEN string, account identifier,
or row-level cache. The transfer ZIP contains aggregate CSV/JSON/Markdown,
receipts, verification, and executed package source. The private design and
model checkpoint roots never enter the transfer ZIP or Git.
