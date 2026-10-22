# Frozen R10 specification (as supplied)

Source: `R10_two_questions_regression.md`, October 13, 2026. The original, unedited specification is included in this package for a clear record of timing; methodological clarifications and implementation choices are documented in `README.md` and the output manifests.
# R10. Two questions, one regression

One configuration. It produces the main regression table for Section 4 of the manuscript: the position and stage coefficients from a chooser-fixed-effects model on the full analysis sample. Aggregates only.

## Sample

All 41,534,331 opportunities of the analysis sample (Table 1), author accounts retained as elsewhere in Sections 4 and 5. Outcome: 100 × grant indicator.

## Regressors

- **Position bins** (reference: clearly worse, evaluation ≤ −300): clearly better (≥ +300), better (+101 to +299), roughly equal (−100 to +100), modestly worse (−299 to −101). The same integer-inclusive boundaries as Appendix A.
- **Stage bands** (reference: plies 0–4): 5–6, 7–8, 9–10, 11–20, 21–40, 41–80, 81 or more. The bands of Figure 2 and Table A.3.
- **Fixed effects in every column:** chooser account, speed category (ultrabullet, bullet, blitz, rapid, classical), calendar month.
- **Controls, columns 2–4:** log(1 + seconds) on each player's last recorded clock with missing indicators; the rating-environment set of Table B.1 (piecewise-linear displayed gap capped at ±600, log forgone premium and its square, each player's log rating deviation and its square).

Standard errors clustered by chooser account with the G/(G−1) correction, as in Table B.1.

## Columns

1. Additive: position bins + stage bands + fixed effects.
2. Column 1 + controls.
3. Column 2 with the seven stage bands interacted with a competitive indicator (evaluation ≥ −100). Report the stage profile within competitive positions and within non-competitive positions (modestly worse and clearly worse together), each relative to its own 0–4 band. Position bins stay in the model.
4. Column 2 with the seven stage bands interacted with speed category. Report the stage profile within each of the five speeds, each relative to its own 0–4 band.

## Report

For each column: coefficients and SEs; the number of opportunities, chooser accounts, and opportunities that carry within-chooser variation (choosers with at least two opportunities), and the mean of the outcome.

Contrasts, each with SE and p-value under the shared covariance:
- **Panel A (question 1):** the four position coefficients, and the three adjacent differences (clearly better − better, better − roughly equal, roughly equal − modestly worse). Holm family of 7.
- **Panel B (question 2):** the seven stage coefficients and the six adjacent differences. Holm family of 13.
- **Panel C (column 3):** the 81+ minus 41–80 difference within competitive positions, within non-competitive positions, and the difference of the two. Also the 41–80 minus 0–4 total decline in each region and its ratio to the region's 0–4 grant rate.
- **Panel D (column 4):** the 81+ minus 41–80 difference within each speed, and the 41–80 minus 0–4 decline within each speed, with pairwise differences between adjacent speeds (ultrabullet/bullet vs blitz, blitz vs rapid, rapid vs classical). This is the investment-measure test of Section 3.4: equal per-band declines across speeds favor moves; steeper declines in slow formats favor time spent; steeper declines in fast formats favor the share of a typical game completed.

Descriptive: a 5 × 8 table of the share of each stage band falling in each speed category, and the median plies of all games (not only opportunities) by speed, so that the composition of the 81+ band is documented.

Adjusted grant rates (opportunity-weighted predictions standardized to the sample's composition) for each position bin and each stage band under column 2, as in Table B.1, so that the coefficients can also be read as rates.

## Return

The report ZIP with its SHA256 sidecar and the log. Aggregate tables only.
