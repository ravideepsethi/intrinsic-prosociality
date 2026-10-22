# Stage 10 patron/profile extension: frozen implementation contract v1.0.0

Prepared 2026-08-26 after completion of the 24-month profile acquisition and
before any chooser-level patron models on that snapshot were estimated.

## 1. Status and purpose

The certified input is the current-profile snapshot created on 2026-08-26 for
the November 2023 through October 2025 chooser panel. The acquisition audit
already disclosed aggregate patron counts by acquisition role. This document is
therefore an implementation contract, not an outcome-blind preregistration.

The production analysis asks whether the stable chooser heterogeneity revealed
by private kind-draw behavior is associated with a second costly decision on the
same platform: current paid patron status. It does not identify patron adoption
timing or a causal effect of kindness on patronage.

## 2. Frozen authorities

The production package must fail closed unless it authenticates all of the
following:

- Stage 07 status `STAGE07_24M_CERTIFIED_OK`;
- Stage 07 sample: 47,587,020 unique games, 24 months, 669,503 kind draws;
- Stage 07 producer SHA-256
  `0411d4061ea9831c20449208a9782aaf668e160139918d106a2b7d63aaa56e6e`;
- Stage 07 success receipt SHA-256
  `8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7`;
- profile-snapshot status `PROFILE_SNAPSHOT_24M_CERTIFIED_OK`;
- profile plan: 1,305,872 unique users, comprising 326,468 kind-role and
  979,404 control-role users;
- returned profiles: 1,305,683, with exactly 189 explicit nonreturns;
- current patrons in the audit: 4,896;
- snapshot SHA-256
  `f42f28a6540a65c0a83f0da488663b4adddf60d1001daeed556f1ffbb961e238`;
- plan-success SHA-256
  `2838aa942e20027561763855c387a454d74bb0a92d0a8b62ca47343511897e57`;
- audit-file-hashes SHA-256
  `be1b69ac46d2a0e44180868e0ccead43ad0043299cffeb0203346c6c0c28aa3e`.

No June-2026 or April-2026 profile snapshot may be substituted. Older 10k-node
patron estimates are historical benchmarks only.

## 3. Unit, outcome, and exposure

- Unit: normalized chooser account.
- Outcome: current patron status in the fixed 2026-08-26 profile snapshot.
- Main exposure: ever granted a kind draw in a fair/competitive Stage 07 state,
  where `fair_competitive = true` and `kind_draw = true`.
- Main comparison: acquired non-kind controls selected under the certified
  acquisition plan.
- Username authority: `chooser_username_norm` in Stage 07, joined losslessly to
  the plan/snapshot normalized username field identified by the inventory.
- Fair state: disconnected-player Stockfish evaluation at least -100 cp.
- Clearly-worse state: disconnected-player evaluation at most -300 cp.
- Favorable/non-loss draw: `chooser_draw_payoff_v2 >= 0`.

The inventory must establish whether the acquisition plan stores the original
match cell and match-set/control-rank fields. Production must use those stored
fields when present. It must not silently reconstruct different matches.

## 4. Missingness and exclusions

- The 189 explicit nonreturns are missing patron outcomes. They must never be
  coded as non-patrons.
- Report return rates and return-rate differences by acquisition role and match
  cell before outcome analysis.
- Report the number of kind draws and opportunities attached to nonreturning
  accounts.
- For returned profiles, missing account-age, recency, playtime, or game-count
  covariates are retained using missing indicators and within-match-cell median
  imputation; global median is the fallback only for cells with no observed
  value.
- Detect BOT-title accounts. Report the count. The primary patron comparison
  excludes BOT-title accounts if the historical acquisition plan did so;
  otherwise report both include-BOT and exclude-BOT versions without changing
  the acquired match assignment.
- Duplicate normalized usernames, unplanned users, wrong-role rows, ambiguous
  patron fields, or non-lossless joins are fatal errors.

## 5. Main matched comparison

The precision-oriented primary comparison is one kind chooser to three matched
non-kind controls, using the certified acquisition plan. Report:

1. group counts, patron counts, rates, the kind-minus-control gap in percentage
   points, relative lift, two-proportion z statistic, and confidence interval;
2. a match-cell fixed-effects linear probability model with HC1 standard errors;
3. the same model with CR1 standard errors clustered by match cell as a
   conservative sensitivity; and
4. a one-to-one result holding the kind set fixed.

If stored match-set and control-rank fields exist, one-to-one uses rank 1. If
they do not, controls are drawn deterministically within the original match
cells using SHA-256 of `seed || normalized_username`, with the rule and seed
recorded in the receipt.

One-to-three remains primary because patron status is rare and the control
group carries substantial sampling variance.

## 6. Repeated rematching

Hold the eligible kind set fixed and construct 100 valid one-to-one control
draws within the certified match cells. Use deterministic seeds 1 through 100
under the fixed root seed `20260826`. For raw and full-control estimates report
mean, standard deviation, minimum, P10, median, P90, maximum, share positive,
and share with two-sided p below 0.05.

If the acquisition plan stores an immutable three-control set per kind chooser,
also report all three leave-two-out one-to-one selections before drawing from a
larger reservoir.

## 7. Covariate ladder

Every model retains match-cell fixed effects. The prespecified ladder is:

1. match-cell fixed effects only;
2. plus exposure volume: log fair opportunities, log total opportunities;
3. plus profile tenure/recency: account age, days since last seen, log playtime,
   and their missing indicators;
4. plus board-state composition: five-bin evaluation shares, mean capped
   evaluation, and clearly-worse/fair shares;
5. plus price composition: fair favorable share, fair costly share, mean draw
   payoff, and mean win premium;
6. plus engagement: active months, speed mix, modal speed, tournament-like
   share, profile `count.all`, and available per-pool game counts;
7. plus skill/stability: mean chooser rating, rating standard deviation, rating
   tier, and available current per-pool ratings;
8. all controls together; and
9. all controls on common support.

Continuous controls are standardized within the estimation sample. Missing
indicators are not standardized. Perfectly collinear columns are removed by a
deterministic rank-revealing rule and recorded.

Common-support results must include both the legacy 2-20 fair-opportunity
restriction and the duration-scaled 2-40 restriction, plus an overlap-cell
sample defined before patron outcomes are read.

The full-control logit is not a primary or required result because rare-outcome
separation is plausible. A parsimonious logit with exposure volume and match
cells may be reported as a sensitivity.

## 8. Dose response

The directly comparable primary bins are fixed at:

- 0 kind draws;
- 1;
- 2-4;
- 5-9; and
- 10 or more.

Report raw rates and match-cell-FE lifts relative to zero. Before patron values
are read, the inventory may additionally define support-respecting bins from
the fair-kind-count distribution. Any such bins are secondary and must be
recorded in a frozen support receipt.

Also report continuous companions based on `log(1 + fair_kind_count)` and the
fair-state kind rate, controlling flexibly for fair-opportunity exposure.

## 9. Diagnostic kindness

Restrict the primary horse race to choosers with at least four fair and at least
four clearly-worse opportunities. Estimate patron status on:

- ever kind in fair states; and
- ever kind in clearly-worse states.

Report the fair coefficient, losing coefficient, and their difference under:

1. match cells plus log opportunity counts in both states; and
2. the full activity, profile, skill/stability, board-state, and price controls.

Use HC1 inference for the paper-facing full-control model and report match-cell
clustered inference as a sensitivity. Repeat the result at minimum-opportunity
thresholds 2, 5, and 10. Also report the four raw groups: fair only, losing only,
both, neither.

Estimate the graded companion across the five certified fairness bins. The
negative clearly-worse coefficient, if present, is descriptive and is not a
framework prediction.

## 10. Price-side diagnostic

This is new and secondary. After exposure and desert are controlled, estimate
patron status on separate indicators for:

- ever kind in fair states when the chooser's draw payoff was costly; and
- ever kind in fair states when the draw payoff was nonnegative.

Report their difference, support, and overlap at minimum fair opportunity
thresholds 2 and 4 on each price side. Also report count and rate versions. Do
not describe a difference as causal or as evidence of patron adoption.

## 11. Patron structure at the opportunity level

As an appendix analysis, join patron status back to the matched-chooser Stage 07
opportunities and reproduce:

- patron by desert-gradient interactions on all opportunities;
- patron by favorable-price interactions in fair states; and
- the full patron by desert by price interaction.

Use the Stage 07 controls for event type, clocks, rating gap, speed, and month,
with standard errors clustered by chooser. This conditions on patron status and
asks how patrons behave; it is distinct from predicting patron status from where
kindness occurs.

## 12. Output and privacy contract

Private XT_Pro outputs may contain normalized account identifiers only when
required for resumable joins. Public/transfer outputs must contain aggregates,
schemas, hashes, model receipts, coefficients, support tables, and redacted
diagnostics only. They must never contain usernames, raw profile JSON, account
IDs, game IDs, country/location/free-text fields, or row-level profile data.

The production run must emit:

- input-authority receipt and software versions;
- complete matching, exclusion, missingness, and join ledgers;
- chooser-feature cache manifest and hashes;
- Tables 10-15 replacements and appendix support tables;
- 100-rematch summaries;
- dose-response and graded-diagnostic plot data;
- JSON and CSV model tables with coefficient, SE, t/z, p, N, ranks, clusters,
  and exact sample rules;
- a disclosure audit;
- a file-hash manifest; and
- `_SUCCESS.json` only after an independent verifier passes.

No API request, Git mutation, source-data mutation, or publication of the raw
profile snapshot is authorized by this analysis.
