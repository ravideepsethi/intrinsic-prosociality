# Color change: calendar planning recovered from completed results

**No further laptop run is needed for this planning calculation.** The delivered `results/` folder has already been computed. It uses authenticated weekly exports from the completed `COLOR_RD110_PREDICTIONS_RESULT_20260926T195410754692Z.zip`, with the calendar gaps in the later color-model plan.

The color change produces almost the same predicted response under framing and curved rating utility. It is therefore uninformative about that distinction at the available noise level. Comparing either with a displayed-gap model has limited power in the four-week announced window, even under full updating. These are conditional planning results, not observed post-policy behavior or a causal decomposition.

## What happened to the uploaded run

`COLOR_MODEL_RESULT_20260926T200849711930Z.zip` passes its SHA256 check. Its status is `FAILED_WITH_COMPLETED_STAGES_PRESERVED`. It ran for 92.7 seconds, authenticated all 24 monthly inputs and built the audited capped population of 3,236,219 opportunities, 58,298 grants and 778,048 choosers. Its only reported forecast failure was `strength/fold0`, during account baseline calibration.

The failed routine searched account intercepts only between −80 and +80. That training fold has a coefficient of 352.3665 on the outer positive-gap basis, so sufficiently large fitted offsets can require intercepts outside the search bracket. The numerical search restriction was unsuitable. It is not evidence that the displayed-gap model fits worse or that players respond to the policy.

The same fold's own-premium and opponent-premium coefficients are both exactly zero. Since the displayed gap is unchanged by the formula counterfactual, its predicted mechanical policy shift is exactly zero regardless of the baseline intercept. That fact does not identify motives.

The uploaded failed ZIP contains no published forecast/power tables or post-policy statistic. The inference here does not treat it as a completed result. Its local input caches and completed forecast jobs need not be discarded.

## Why another private-data run is unnecessary here

Your separate prediction package had already completed the relevant forecasts, including adaptive calibration for the difficult fold. Its archive checksum matches its sidecar. Its 24 upstream Parquet hashes match the repaired audit, its seven full model coefficient vectors match, and its six relevant forward-fit vectors also match.

That completed package exports 103 complete pre-policy weeks with both colors, event counts and weekly predictions. These suffice to recompute the calendar-aware planning noise and power without reading private accounts, recovering identities, replaying ratings, refitting models or calling Stockfish.

**The baseline distinction is explicit.** The completed package calibrates shrunken account rates and then adds a common intercept adjustment to match the overall pre-policy grant rate. The failed color-model branch did not impose that final adjustment. This recovery extends the successful package's documented calibration; it does not silently substitute its numbers as completed output of the failed branch. Its forward-fit variants also use its own documented pre-policy calibration scheme and are sensitivities, not held-out policy forecasts.

## Predictions to take forward

Primary transport target: all 103 complete source weeks; account shrinkage count 20 followed by the global pre-policy rate match; full effective updating.

| Fitted model | Predicted change in White-minus-Black granting |
|---|---:|
| Reference-payoff framing | −0.1898 percentage points |
| Curved utility over rating changes | −0.1831 percentage points |
| Displayed rating gap | 0.0000 percentage points |

These are changes in a **color contrast**, not the change in overall granting. The two payoff models differ by only 0.0067 pp. At the available pre-period noise, power to distinguish that pair is about 5%, essentially the nominal rejection rate.

The original completed run's baseline sensitivities put the framing prediction between approximately −0.168 and −0.197 pp and the curved-utility prediction between −0.163 and −0.189 pp. These ranges are not confidence intervals. They reinforce the need to state the baseline model.

## Calendar correction and power

Implementation is bracketed at November 18, 2025, 07:22 UTC. Announcement is December 22, 2025, 22:35 UTC. The baseline comprises eight complete weeks before implementation. Weeks crossing either event are omitted. The bootstrap preserves those omitted weeks and the announcement delay.

The January 30 cutoff remains an **illustrative planning scenario, not a certified mechanics censor**. This calendar yields four unannounced weeks, four announced weeks and an eight-week pooled secondary window. The two separate post windows are the main planning comparisons.

| Window | Pre-period block length | Negative-shift 80% MDE, pp | Framing vs gap: full updating | Framing vs gap: 50% updating |
|---|---:|---:|---:|---:|
| Unannounced, 4 weeks | 4 weeks | 0.2729 | 48.7% | 16.7% |
| Unannounced, 4 weeks | 8 weeks | 0.2492 | 56.3% | 20.6% |
| Announced, 4 weeks | 4 weeks | 0.2738 | 48.8% | 16.2% |
| Announced, 4 weeks | 8 weeks | 0.2524 | 54.4% | 18.0% |
| Pooled secondary, 8 weeks | 4 weeks | 0.2207 | 67.2% | 22.8% |
| Pooled secondary, 8 weeks | 8 weeks | 0.1865 | 81.5% | 29.4% |

The pooled framing comparison reaches 80% power in only the eight-week-block scenario, under full updating. The corresponding curved-utility comparison is 78.7%. At 50% updating, even pooled framing power is only 23–29%. This is a fragile conditional planning screen, not a robust authorization for a causal mechanism test.

Both positive and negative MDEs, all seven full candidates, both transport scopes and all five updating scenarios are in the tables. The second transport scope uses the last eight complete **source** weeks, ending with the week of October 20, 2025. It is not the actual eight-week event baseline, which extends into November.

Inference follows the copied v1.0.2 calendar routine: 10,000 pre-only moving-block draws; block lengths four/eight; centered pre-period series; a two-sided 5% absolute critical value; separate positive/negative 80% MDE inversion. No fitted-parameter uncertainty is propagated. The exported null mean is retained, and no outcome-driven tuning is applied. The scenarios assume stationary transport of the pre-period noise, fixed fitted parameters and the same homogeneous updating fraction for both compared models.

Pre-period temporal checks and twelve fixed, overlapping placebo dates are retained as descriptive diagnostics. The slope and autocorrelations do not certify parallel color trends. Neither high conditional power nor a future failure to reject would establish a psychological mechanism.

## Implication for the paper

This color change can potentially constrain a specified payoff-responsive component relative to a displayed-gap prediction under explicit updating and transport assumptions. Its strongest surviving payoff models make nearly identical policy predictions, and the short announced window has limited power even for the broader payoff-versus-gap comparison.

It cannot allocate the observed relative-strength gradient among opportunity cost, reference-dependent price and deference. Unknown updating creates an additional ambiguity: a small response can reflect weak payoff sensitivity, little updating, or both. The displayed-gap association itself also does not uniquely establish deference.

The completed repaired pre-policy comparison, rather than this failed run, remains the authority for which specified models predict the observational pattern well. The linear-cost and piecewise loss models are benchmark candidates; power against an already-disfavored benchmark is not discrimination among surviving explanations.

The next substantive dependency is the matched fixed pre-implementation chooser-by-speed cohort with the required source/adjacency history, capped-target reconstruction review, source-supported censor and entry/denominator checks. Earlier all-source post results have already been inspected. Any new behavioral test is an amended analysis, and still needs matched prediction uncertainty or explicitly conditional inference.

## Files and reproducibility

- `SOURCE_LINEAGE.json`: authenticated source identities, source-file hashes and copied calendar-code hashes.
- `source/`: completed parent methods, aggregate Parquets, fit coefficients and failed-branch diagnostic summary.
- `results/reused_primary_predictions.*`: the completed predictions, explicitly labeled by source calibration.
- `results/calendar_MDE.*`, `calendar_pairwise_power.*`, `calendar_single_model_power.*`: newly calculated calendar-aware planning results.
- `results/calendar_windows.*`: exact included weeks.
- `results/pre_diagnostics/`: temporal diagnostics and the fixed placebo schedule.
- `code/recompute_calendar.py`: reproducible calculation with input, count, calendar and prediction-identity checks.

**Expected reproduction runtime:** under 30 seconds. It reads only the bundled aggregate Parquets and uses up to six independent bootstrap workers. The calculations were run here; rerunning is optional.

After extracting the package in your Desktop folder, its command is:

```bash
bash <<'BASH'
set -euo pipefail
cd "$HOME/Desktop/Lichess_Desktop"
RECOVERY_STAGE="$(mktemp -d "$PWD/color_calendar_recovery.XXXXXX")"
ditto -x -k "Color_Calendar_Recovery_v1_0_0.zip" "$RECOVERY_STAGE"
bash "$RECOVERY_STAGE/Color_Calendar_Recovery_v1_0_0/RUN_REPRODUCE.command"
BASH
```

The launcher uses the existing project Python. It verifies the package and writes a separate `reproduced_results/` folder. It installs nothing, requires no SciPy, and reads only the bundled aggregate data.
