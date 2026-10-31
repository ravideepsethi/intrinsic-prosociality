# Tenure and responsibility screening protocol — v1.0.0

Prepared 23 September 2026. This is runnable code and a frozen screening design,
not completed empirical evidence. Full private data remain on the user's Mac.

## Population and sampling

Authenticate the exact 41,534,331-row certified pool / observed-nonadjacent main
panel (570,091 grants; 3,224,173 chooser accounts), including all monthly hashes.
The observation window is November 2023–October 2025. Do not use the older
47,587,020-row panel or the receipt-exposure frame as the population.

Primary tenure models use all observed main-panel opportunities of 100,000
accounts selected by the first values in a fixed MD5 ordering of account ID
and seed 2026092301. Responsibility uses the nested first 20,000 accounts.
Account selection ignores grant outcomes, age, future return and board state.
This is a reproducible approximation to simple random sampling of accounts;
all opportunities have the same first-order inclusion probability. Ordinary
opportunity-weighted models therefore target the main opportunity population,
subject to finite-sample ratio behavior and missing profile/trajectory data.
This is a screening sample, not an exact census rerun of every regression.
Full histories preserve within-chooser comparisons. All SEs cluster on chooser
except the account-level Patron models (match-cell clustering).

Sample sizes may be increased before looking at outcomes. Any change creates
a different output identity. Do not repeatedly increase N until significance.
Sparse or imprecise estimates are inconclusive, not a failure of the paper.

## 1. Tenure

Account age is `(game.api_created_at_ms - user.createdAt)/86400000`, in days.
Using game start makes it predetermined for that game's resolution. Creation
date obtained later still describes an earlier event; it is not current game
count, current rating or current RD. It measures account age, not chess skill,
human age or prior experience with a disconnect choice. Multiple accounts per
person cannot be resolved. Current profile availability can still select rows.

Use the authenticated lossless August profile snapshot, optionally its pinned
September gap supplement, then fetch missing creation dates for the selected
accounts. The old cache deliberately oversamples granters. Consequently,
unweighted cache-only chooser rates are not population estimates. The primary
probability sample and explicit coverage audit address acquisition selection;
they do not magically correct unavailable/closed accounts.

Bins: [0,7), [7,30), [30,90), [90,365), and 365+ days, plus unknown.
Core restrictions: account age at the opportunity at least 30, 90 or 365 days.
Negative/inconsistent dates are excluded from age classification and counted.
Unknown ages never count as established.

Outputs:

* Board-bin grant rates and eight-bin stage profiles, with chooser-cluster SEs.
* Competitive (eval >= -100) minus clearly worse (eval <= -300), excluding the
  middle region: minimal and controlled chooser-FE LPMs. Both use the same
  complete-control rows. Full controls: month, speed, rating tier, ply band,
  200-point rating-gap bins, draw payoff, forgone premium, both RDs and clocks.
* Within competitive positions: stage 11–40 and 41+ versus <=10 plies, adjusting
  for board category and controls; and rating-gap slope per 100 points.
* First-year/second-year persistence among competitive opportunities only.
  Freeze cohort age at the first competitive opportunity in year one. Report
  returner selection and thresholds of 1, 5 and 10 opportunities in each year.
  Correlations are equal-account and harmonic-opportunity weighted, the latter
  using n1*n2/(n1+n2). Also correlate account-level residual means after removing
  within-year board-category × stage × speed rates estimated excluding that
  account. These are descriptive, noisy and not an identified latent type.
* Share of grants at ages below 7/14/30/90/365 days, in the probability sample
  and census. Report observed-date share and bounds: known young grants / all
  grants is the lower bound; add grants with unknown birth dates that could
  still be young for the upper bound. Time since the first observed main-panel
  opportunity supplies an age lower bound even when creation date is missing.
  Bounds address missing ages, not uncertainty of the probability sample.

### Patron comparison

Use a homogeneous August current-status snapshot on the historical acquired
profile frame; never blend it with today's Patron status. Rebuild ever-kind
indicators from current-main-panel opportunities. Report all four combinations
of ever competitive-kind and ever clearly-worse-kind, by baseline tenure, and
repeat using only decisions made after 30, 90 and 365 days. Require at least
1 or 4 opportunities in each state. The horse race absorbs original match
cells and controls for log opportunity counts in each state, mean rating and
log baseline age. This is a new tenure sensitivity, not byte-identical
reproduction of every control in the prior Patron regression.

The original acquired frame is outcome selected. The model is explicitly a
conditional association in that frame. Its raw Patron percentage is not the
platform's unconditional Patron rate. Current badge status does not identify
personal expenditure, adoption time, gifted status or a causal effect.

## 2. Responsibility / final-ply trajectories

Let n be final ply and E_p the evaluation after ply p, always from the
disconnected player's perspective. That player is on move at n; the chooser
just moved. Compute:

| Measure | Definition; positive means deterioration |
|---|---|
| Net final two plies | E_(n-2) - E_n |
| Net final four plies | E_(n-4) - E_n |
| Disconnected player's last own move | E_(n-2) - E_(n-1) |
| Disconnected player's preceding own move | E_(n-4) - E_(n-3) |
| Own-move sum / maximum | Sum / maximum of the preceding two signed losses |

The net measures include the chooser's replies. Keep negative values, rather
than silently truncating them to zero. Own-move loss is the closer proxy for
an avoidable blunder. Opponent mistakes, engine horizon effects, tactical
sequences and position-level error can still affect it. Neither measure
reveals why a player left or what the chooser believed.

Reuse existing A1 raw move-response records if available, but select targets
from the independent full-state main-panel account sample. The old 2,110,400
A1 exposures are a selected receipt sample and cannot identify the full-state
desert gradient. Re-export only missing target moves. Validate ID, status,
variant, rated/source, timestamps, result, legal moves, ply count, final FEN
and disconnected color. Keep nonreturns and failures in coverage accounting.

For uniform engine provenance, evaluate all final five positions afresh with
the existing pinned SF18 binary, 100,000 nodes, 1 thread, Hash=64 MB, standalone
FEN/new game, up to 10 workers. Reuse exact positions within each batch.
Existing A1 Stockfish scores are not silently pooled. Save raw CP, mate,
node/depth and bound/short-search status. No mate-to-finite-CP substitution.
This costs at most about five engine evaluations per selected game, not a full
trajectory. Actual count and a runtime ETA are printed. It may take hours.

Main ladder uses identical rows with all proxy scores finite/unbounded/full
budget, no original mate evaluations, and complete controls. Thus it excludes
games with fewer than four plies. Report full-sample and same-row baseline
separately via the coverage tables and tenure models; do not attribute changes
caused by row loss to adjustment. Use bins <0, 0–49, 50–99, 100–199, 200+ cp.

Estimate gradient and rating-gap models before adjustment, with two-ply loss,
four-ply loss, own-move loss bins, and all proxies. Repeat at account age >=90
and >=365. Report gradient among games without own-move loss >=100/200 cp.
For rating gap, condition on final evaluation in 50cp bins capped at +/-1200.
Do NOT add those final-evaluation fixed effects to the competitive/clearly
worse gradient: they mechanically determine and absorb its target indicator.
Check whether the recipient's rating gap predicts own-move blunders at a
comparable final state. Signs are defined explicitly: positive gap means the
disconnected player was stronger than the chooser.

## Decision discipline

Read magnitudes, intervals, common-sample changes and support, not whether one
p-value crosses .05. Robustness among established accounts and within blunder
categories would weaken two alternative descriptive explanations. It would
not identify intrinsic preferences, disconnection intent, causal transmission,
or establish a journal placement. Failure of a noisy proxy to attenuate a
gradient is weaker than showing comparable gradients across well-supported
responsibility categories. Strong attenuation can reflect correlated proxies
and selection; examine the tables before choosing a revised interpretation.

## Execution, output and privacy

The default run first writes TENURE_READY with an aggregate ZIP, then runs
trajectory recovery/evaluation and writes the COMPLETE aggregate ZIP. Source
files are read-only. New checkpoints and row-level records stay in PRIVATE;
only the report directory enters returned ZIPs. Successful computation is
not a substantive robustness pass. Each model retains unsupported fits.

Use only one Lichess API client at a time across your processes. This package
uses sequential requests, batches <=300, TLS verification, retry/backoff and
at least 60 seconds after HTTP 429 (honoring longer Retry-After). The package
does not stop or interfere with another running job. API guidance checked at
https://lichess.org/page/api-tips on 23 September 2026; endpoint documentation:
https://lichess-org.github.io/api/ . An optional LICHESS_TOKEN is never logged.

Full monthly input hashes are recomputed on each invocation. Completed local
projections, raw requests and engine batches have input-bound checksums. Resume
with the same command; statistical summaries may be recomputed. Changing code,
sample size or seed gives a new output identity. No private data or large engine
job was run in ChatGPT; included validation is synthetic numerical/software QA.
