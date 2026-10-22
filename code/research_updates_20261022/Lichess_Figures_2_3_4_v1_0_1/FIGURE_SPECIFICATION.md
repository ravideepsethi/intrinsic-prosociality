# Figure production specification

For `main_manuscript.tex` as built 13 September 2026 (80 pages, plainnat bibliography). Every value below is from the approved numerical authority and matches the caption and notes already fixed in the manuscript. **Do not compute, interpolate, or round differently from what is given here.** If a figure cannot be drawn from these values alone, stop and ask rather than filling the gap.

## Global requirements

| Item | Requirement |
|---|---|
| File paths | Exactly `figures/fig1_decision_screen.png`, `figures/fig2_merit_stage_equality.pdf`, `figures/fig3_relative_strength.pdf`, `figures/fig4_time_profile.pdf`, `figures/figA1_decision_mobile.png`. The `\IfFileExists` guards key on these names. |
| Format | Screenshots as PNG at no less than 200 dpi effective. Plots as vector PDF. No rasterized plots. |
| Width | Figures 2–4 are included at `\textwidth`; design for 6.0 in wide. Figure 1 at `0.7\textwidth` (4.2 in). Appendix A figure at `0.42\textwidth` (2.5 in). |
| Type | Serif, matching the body text (Palatino via `mathpazo`). Axis and tick labels no smaller than 8 pt at final size. |
| Colour | Must remain legible in greyscale. Distinguish series by marker shape and fill as well as hue. |
| Titles | No titles inside the image. The LaTeX caption supplies the title. Panel letters A, B, C inside each panel, upper left, bold. |
| Rounding shown | Two decimals for rates and percentage points on plot labels; the underlying plotted position uses the full value given. |
| Gridlines | Light horizontal only, or none. No boxes around panels beyond a thin axis rule. |

## Figure 1 — The disconnect decision (`fig1_decision_screen.png`)

Not a plot. A cropped screenshot of the Lichess desktop interface as it appears to the connected player after an opponent's disconnection countdown has elapsed.

What must be visible:

- The two action controls, **Claim victory** and **Call draw**, with their platform wording intact.
- Enough surrounding context to show these are the options presented in a live game.

What must be removed or masked:

- Both account names, avatars, and any user identifiers.
- Any chat contents.

The caption states that *Claim victory* claims a win subject to the platform's material rules and that leaving both unpressed lets the disconnected player's clock continue to run. The image must not contradict this; if the captured interface shows a countdown or clock, that is helpful rather than a problem.

## Figure 2 — Board merit, game stage, and equality (`fig2_merit_stage_equality.pdf`)

Three panels side by side, or A and B side by side above C. Panels A and B share a vertical axis.

### Panel A — Kind-draw rate by the disconnected player's board state

Five bars, left to right in evaluation order, with the engine evaluation taken from the disconnected player's side:

| Board state (centipawns) | Rate (%) |
|---|---|
| Clearly better (≥ +300) | 3.576342 |
| Better (+101 to +299) | 2.390879 |
| Roughly equal (−100 to +100) | 2.605005 |
| Modestly worse (−299 to −101) | 1.203466 |
| Clearly worse (≤ −300) | 0.470138 |

- y-axis: kind-draw rate, percent, 0 to 5. Shared with Panel B.
- x-axis: the five bin names with their centipawn ranges beneath.
- Annotation: a bracket spanning the first three bars labelled "Competitive, 2.76%", the pooled competitive rate 2.758278. The clearly-worse bar is the comparison; the modestly-worse bar belongs to neither region and should be visually de-emphasised (lighter fill, no bracket).
- **No confidence intervals.** These are raw rates. Do not add error bars to imply otherwise.
- The plot must let a reader see that the middle three bars are not monotonic: the roughly-equal bar is taller than the better bar. Do not reorder the bars to hide this.

### Panel B — Kind-draw rate within competitive positions, by game stage

Three bars:

| Stage | Rate (%) |
|---|---|
| Ply 2 | 4.568305 |
| Plies 3–10 | 3.480475 |
| After ply 10 | 2.469315 |

- y-axis shared with Panel A.
- Dashed horizontal reference line at 2.758278, labelled "All competitive positions".
- **No confidence intervals.**

### Panel C — The equality control ladder

Horizontal coefficient plot, four rows top to bottom, with 95 percent confidence intervals:

| Row label | Estimate (pp) | SE |
|---|---|---|
| Raw difference | 0.214126 | 0.010962 |
| Chooser fixed effects | 0.066262 | 0.009225 |
| Chooser, month, and speed fixed effects; rating premium and clocks | −0.016130 | 0.009249 |
| Plus draw-payoff and game-stage controls | −0.400392 | 0.009437 |

- Intervals are estimate ± 1.96 × SE. These are narrow; if a marker would hide its interval, use a smaller marker rather than widening the interval.
- x-axis title: "Roughly-equal minus better-position kindness rate (percentage points)", range about −0.5 to +0.3, with a vertical rule at zero.
- The row labels above are the reader-facing specification names and must be used verbatim.

## Figure 3 — Relative strength and the rating consequences of granting a draw (`fig3_relative_strength.pdf`)

Three panels. Panel C contains two separately labelled blocks with different units; they must not share an axis.

### Panel A — Adjusted rating-gap series

A series of 22 estimated bin coefficients plus a marked reference, joined by line segments for readability. **This is not a smoothed curve and not a set of raw rates.** Plot only these rows; interpolate nothing.

| Gap centre | Coefficient (pp) | SE | 95% interval |
|---:|---:|---:|---|
| −550 | −1.052986 | 0.509862 | [−2.052315, −0.053657] |
| −500 | −0.534284 | 0.585717 | [−1.682289, 0.613721] |
| −450 | −1.229410 | 0.560881 | [−2.328737, −0.130082] |
| −400 | −0.696773 | 0.595455 | [−1.863865, 0.470319] |
| −350 | −0.881316 | 0.362810 | [−1.592424, −0.170208] |
| −300 | −0.012687 | 0.362897 | [−0.723965, 0.698591] |
| −250 | −0.647449 | 0.221730 | [−1.082040, −0.212858] |
| −200 | −0.394624 | 0.139116 | [−0.667292, −0.121956] |
| −150 | −0.580280 | 0.043704 | [−0.665941, −0.494619] |
| −100 | −0.469306 | 0.023339 | [−0.515051, −0.423561] |
| −50 | −0.294577 | 0.014762 | [−0.323511, −0.265644] |
| 0 | 0 (reference) | — | — |
| +50 | 0.152681 | 0.015574 | [0.122155, 0.183207] |
| +100 | 0.245277 | 0.026541 | [0.193256, 0.297297] |
| +150 | 0.430912 | 0.056301 | [0.320561, 0.541263] |
| +200 | 0.436560 | 0.173181 | [0.097125, 0.775995] |
| +250 | 0.747361 | 0.322145 | [0.115956, 1.378766] |
| +300 | 0.428489 | 0.340212 | [−0.238327, 1.095304] |
| +350 | 1.319912 | 0.555829 | [0.230488, 2.409337] |
| +400 | 1.432845 | 0.749352 | [−0.035885, 2.901574] |
| +450 | 0.311623 | 0.752848 | [−1.163959, 1.787205] |
| +500 | 0.082641 | 0.868870 | [−1.620344, 1.785625] |
| +550 | 1.238646 | 1.032214 | [−0.784494, 3.261786] |

- x-axis: displayed rating gap, opponent minus chooser, in rating points, −550 to +550. The caption states that a bin centred at *c* covers gaps from *c*−25 to below *c*+25.
- y-axis: difference in the kind-draw rate relative to the reference bin, percentage points.
- The reference row at 0 is a **normalization**, not an estimate. Mark it with a distinct open symbol and **no interval bar**.
- Plot the stored intervals. The tails are wide and several cross zero; that is the point of the panel and must be visible. Do not truncate the y-axis to hide them — if the tails compress the centre, add a light inset or note the axis range, but do not clip.
- Horizontal rule at zero.

### Panel B — Same-chooser comparisons with equal account weights

Six points, grouped by evaluation band, with 95 percent intervals as estimate ± 1.96 × SE:

| Band (centipawns) | Comparison | Difference (pp) | SE | Accounts |
|---|---|---:|---:|---:|
| [−100, 100) | Weaker opponent | −0.474329 | 0.081280 | 25,527 |
| [−100, 100) | Stronger opponent | 0.560478 | 0.100421 | 22,466 |
| [100, 300) | Weaker opponent | −0.410176 | 0.157355 | 8,257 |
| [100, 300) | Stronger opponent | 0.525494 | 0.161054 | 9,650 |
| [300, 600] | Weaker opponent | 0.112071 | 0.202565 | 6,890 |
| [300, 600] | Stronger opponent | 0.408424 | 0.182235 | 9,160 |

- x-axis: within-account difference in raw kind-draw rates relative to near-equal opponents, percentage points, with a rule at zero.
- Group the three bands on the vertical axis, with weaker and stronger distinguished by marker shape.
- The `[300, 600]` weaker-opponent point is positive with an interval crossing zero. It must be plotted as it stands; the manuscript relies on this exception.
- Band labels must use these exact intervals, which differ from Panel A's descriptive bins at the boundaries.

### Panel C — Two blocks, separate units

**Block 1, "Adjacent displayed-rating levels" (percentage points):**

| Contrast | Estimate | SE |
|---|---:|---:|
| Equal ratings vs gap −1 | 0.011691 | 0.065946 |
| Gap +1 vs gap −1 | −0.030794 | 0.068752 |

**Block 2, "Local draw-payoff slopes" (percentage points per rating point of signed draw payoff):**

| Quantity | Estimate | 95% interval |
|---|---:|---|
| Loss-side slope | 0.324712 | [0.103789, 0.545634] |
| Gain-side slope | −0.167191 | [−0.387631, 0.053249] |
| Loss-side minus gain-side | 0.491903 | [0.342328, 0.641478] |

- Two stacked sub-blocks with their own x-axes and their own axis titles, separated by a visible rule or gap. **They must not be plotted on a common scale**; the units differ.
- Block 1 intervals are estimate ± 1.96 × SE. Block 2 uses the stored intervals above, which for the difference already incorporate the joint covariance of the two slopes — do not recompute it from the separate standard errors.
- Zero rule in each block.

## Figure 4 — The time profile of kindness (`fig4_time_profile.pdf`)

Three panels. **Panel A shows regression confidence intervals; Panels B and C show benchmark distributions. These must look different from each other**, since the caption states they differ in kind. Use error bars for A and a shaded band or distinct bracket for B and C, with a legend that names each.

### Panel A — Receipt association by interval since exposure

Five points at ordered categorical positions, with 95 percent intervals as estimate ± 1.96 × SE:

| Interval | Estimate (pp) | SE |
|---|---:|---:|
| Up to 6 hours | 1.494225 | 0.674254 |
| 6 hours to 1 day | 1.141627 | 0.532562 |
| 1 to 7 days | 1.077226 | 0.236457 |
| 7 to 30 days | 0.685656 | 0.159081 |
| 30 to 90 days | 0.500784 | 0.138543 |

- y-axis: association in percentage points, with a rule at zero.
- x-axis: the five intervals as ordered categories. **Do not place them on a continuous time scale**, which would imply a decay curve; the caption says explicitly this is not a causal decay rate, and the samples overlap across intervals.
- Do not connect the points with a line.

### Panel B — Observed and benchmark rates by horizon

Paired markers at three cumulative horizons:

| Horizon | Observed (%) | Benchmark mean (%) | Benchmark 2.5th–97.5th percentile |
|---|---:|---:|---|
| Within 6 hours | 51.567798 | 34.826311 | [33.049945, 36.655031] |
| Within 24 hours | 50.632411 | 34.019074 | [32.813304, 35.278198] |
| Within 7 days | 44.573040 | 32.696677 | [32.163200, 33.223311] |

- y-axis: grant rate over eligible post-anchor competitive opportunities, percent. Panels B and C should share this axis; a range of 30 to 55 is adequate.
- The percentile range attaches **only to the benchmark marker**, never to the observed marker.
- Legend must distinguish "Observed" from "Conditional benchmark (central 95% of reallocations)".

### Panel C — Same session and other sessions, within seven days

| Partition | Observed (%) | Benchmark mean (%) | Benchmark 2.5th–97.5th percentile |
|---|---:|---:|---|
| Same session | 52.756508 | 35.408126 | [33.003826, 37.896665] |
| Other sessions | 44.097083 | 32.549610 | [32.003903, 33.095381] |

- Same construction as Panel B. Labels must read "Same session" and "Other sessions".
- Optional annotation: the excesses, 17.35 and 11.55 percentage points. If shown, label them as excesses over the benchmark, not as effects.

## Appendix A figure — Mobile decision screen (`figA1_decision_mobile.png`)

The same disconnection decision as presented on the mobile interface, with account names removed. Include it only if it shows something the desktop capture does not; its `\IfFileExists` guard omits the entire environment when the file is absent, and no text cross-references it, so leaving it out costs nothing.

## Checks before delivery

1. Every plotted value appears in the tables above. No figure introduces a quantity absent from them.
2. Panels A and B of Figure 2 carry no error bars; Panel C does.
3. Figure 3 Panel A's reference bin has no interval and is visually distinct from the estimated bins.
4. Figure 3 Panel C's two blocks have separate axes and axis titles.
5. Figure 4's regression intervals and benchmark ranges are visually distinguishable and named in a legend.
6. No panel title duplicates the LaTeX caption.
7. Greyscale print remains legible.
8. Files carry the exact names listed at the top; once dropped into `figures/`, the placeholders disappear on the next build with no LaTeX change required.
