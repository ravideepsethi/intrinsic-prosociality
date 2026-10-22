# AFE follow-up analyses, version 1.0.0

Prepared September 20, 2026 after the conference and after earlier results were known. These are exploratory extensions. This file is frozen by the package manifest before the new run; it is not a retrospective preregistration.

## Sources and scope

The main population is exactly 41,534,331 automated-pool, observed-nonadjacent opportunities, November 2023–October 2025, with 570,091 grants and 15,207,423 competitive opportunities. The 24 main files are checked against their recorded SHA-256 and row counts. The observed-start nonadjacency classification is not literal proof that every immediate rematch has been removed.

The original 47,587,020-row panel is used only for prior opportunity/receipt histories and the restricted recovery design. Its coverage and file metadata are checked and its content hashes are recorded when building transmission histories. It is never silently substituted for the main outcome sample.

The expanded-IV cohort is the exact `f14a1105a9f7` 90-day-spaced analysis: 2,682,330 exposures. Its file SHA-256 is checked. Complete-window nonreachers have zero outcomes; administrative censoring is excluded upstream. The seven-day lag, historical score construction, cross-fitting, recipient history controls, assignment fixed effects and inference convention are inherited from the reviewed code. Historical scores are treated as fixed for inference.

## 1. Payoff accounting

Report reconstructed draw payoff, claim payoff and their difference; verify the stored premium identity and positive premium. Show actual means by relative rating, state, and month, and compare realized reconstructed rating changes with PGN rating updates. Report missing observed updates and reconstruction error distributions. The unchosen payoff cannot be separately validated from its unobserved realization. A fixed-update-scale table illustrates the distinction between draw payoff and forgone claim payoff. No causal cost response or loss-aversion parameter is estimated.

## 2. Recipient-side Patron association

Join the certified August 2026 profile snapshot by the disconnected player's recorded normalized username. Preserve unavailable profiles as missing. Report coverage, opportunity-weighted rates and equal-recipient rates, and the within-chooser variation supporting fixed effects.

Estimate pooled adjusted and chooser-FE linear probability models on all eligible known-profile rows in competitive or clearly-worse positions. Separate recipient-Patron coefficients are estimated for the two state groups. Controls: chooser rating and its square; displayed relative rating and its square; log game stage and its square; competitive indicator and clipped continuous board evaluation; both players' log RD and clocks with missing indicators; time-control base/increment; month and speed indicators. The pooled model includes an intercept; the chooser-FE model removes it through demeaning. Models use full-row sufficient statistics on disk, not a statistical sample. Singular nuisance columns are removed by a rank-revealing eigendecomposition; target coefficients that are not separately identified are withheld. CR0 covariance allows observations sharing an account in either role or a date.

This is current-status association in a selected profile-acquisition population. No current status is backdated. No inference about a causal badge effect, historical adoption, or personal payment follows. Population reweighting is not attempted without sampling probabilities. Middle positions are reported descriptively.

## 3. Transmission and recorded experience

Keep the reviewed IV exposure population fixed. For 7, 30 and 90 days, count opportunities and grants in competitive and clearly-worse states. Also measure any competitive grant and a grant at the first competitive opportunity within the horizon. A future game must start strictly after the exposure anchor, finish by the horizon, and face someone other than the original opponent. `lastMoveAt` remains the existing timing proxy, not a newly certified claim-click timestamp. The new 90-day first-competitive outcome must reproduce the reviewed `reached`, `y`, game ID and timing exactly before any new IV results are produced.

Full-cohort outcomes: six outcomes × three horizons. Each subgroup uses the three 90-day competitive outcomes: next-choice grant, cumulative grants, and opportunity count. Predetermined grouping families:

- Reviewed recent histories: no competitive opportunities, opportunities but no grants, prior grants, in the original `[start−97 days,start−7 days)` history window.
- All-source observed histories strictly before the current game's start: no recorded qualifying opportunity, opportunities with no recorded grant, prior grants. The observation boundary is retained; these are not lifetime types.
- Known creation date: account age ≤30 days, 31–365 days, >365 days. These use the selected profile snapshot; missing age is not coded as old or new. Account creation does not establish a new human player or first rated game.

Each group gets its own first stage and IV estimates with uncertainty. Groups are not compared just by comparing their p-values; reported differences in point estimates alone are not formal interaction tests. Unsupported groups remain visible. Holm adjustment spans the declared 45 outcome/group tests (18 full-cohort plus 9 groups × 3), assigning unsupported cases p=1 for family size; descriptive and first-stage outputs are not members of that outcome family. Structural/motive labels are not assigned from subgroup results.

Cumulative effects include natural subsequent receipts and own-action responses. Intervening experience is not controlled away. Opportunity counts describe exposure to later choices; a ratio of giving and opportunity effects is not a separately identified willingness effect. Separate state counts do not condition the cohort on a post-receipt state, and do not by themselves isolate a change in selectivity conditional on opportunity composition. These are recipient responses, not a network multiplier.

## 4. IV exclusion sensitivity and placebo precision

Use the original controls/FEs and a grid of known additive direct effects of the historical score on the outcome, expressed in pp per common score SD. Subtract the corresponding direct component and recompute 2SLS and shared-account/date CR0 variance at each grid point. The zero-direct-effect coefficient and SE must reproduce the reviewed primary estimates. The intervals condition on a specified violation magnitude; the violation is not estimated. If private IV inputs are missing, a clearly marked point-only calibration from authenticated aggregate results is produced, with no invented intervals.

Produce a precision plan for the existing ordinary-game placebo using its reviewed SE and count, several equivalence margins, a normal approximation and inverse-square-root sample-size scaling. Dependence may prevent these gains. This does not download the expanded comparison frame, estimate new placebo regressions, or transfer the placebo coefficient into a bound on the IV population's direct effect.

## 5. Blackout feasibility

Inventory geography and timing fields. The program does not manufacture outage links from profile flags. It reports the external exposure and location requirements. No outage instrument or effect estimate is produced.

## 6. Restricted structural parameter recovery

Deterministically sample 3,000 accounts independently of observed giving. Use their actual opportunity states/times and observed receipt times, with simulated choices. Fit a two-intercept finite-mixture logit with an estimated type share, common receipt loading and exponential decay. Static state/cost offsets are fixed. Initial stocks are known in this simulated DGP. Ten simulations are the default exploratory check; use `--simulations 50` for a more stable assessment. Report convergence, bias and RMSE.

This tests a restricted model only. It does not establish recovery of the full forty-cell warrant model, own-grant feedback, correlated session shocks, type-dependent responses, or endogenous receipt and matching processes. No real structural estimates or causal interpretation are produced by this module.

## Run behavior

Source inputs are read-only. New private caches live under `derived/replication/afe_followups_v100_PRIVATE`. Each completed module has a hash-checked checkpoint. Rerunning identical code, environment and inputs reuses completed modules; changed inputs cannot silently reuse them. Failed modules do not prevent independent modules from reporting. The final ZIP contains aggregates, figures, specifications and status only. No raw profiles, usernames, game IDs or exposure-level rows are included. Missing prerequisites and failed identification/numerical checks are explicit; computational completion never implies a preferred effect sign.
