> **Measurement amendment, 28 September 2026:** `REPAIR_NOTES.md` supersedes
> the old score-extraction rule. Finite evaluations use the last unbounded
> score message available at completion of a 100,000-node search. The selected
> score message can precede the final reported search node count. Model
> definitions and inference below are unchanged; trajectory support is rebuilt
> from the corrected measurement.

# A2: specified responsibility follow-up

This is an amended analysis specified after the earlier binned results, the tenure screen and the September 28 continuous-profile result. It is not a preregistration. This package implements the trajectory, clock and material part of A2, plus an explicit adapter for independently audited history features. It does not claim to implement the other fourteen analyses.

## Sample and source identity

Reuse the frozen responsibility target: 20,000 choosers, 260,863 opportunities, 3,755 grants and 1,292,336 requested adjacent positions. The target is a uniform deterministic chooser sample with complete opportunity histories from the certified pool/nonadjacent panel, not a new outcome-selected sample. Its legacy run key is `c539ba215e708b2218662d0fcbe507655abbb705ed13c5179c6601329036ce40`; the parent sample fingerprint is `a17c89d750cb4fdfdf84f950859e45c58b19996efae02045def68285e305cf30`.

Verify the original package manifest, frozen run identity, target receipt, row/account/grant/position counts and engine hash. Each replay/engine unit is keyed by the frozen run, ordered game IDs and pinned SF18 binary. Preserve the existing target order and unit boundaries. Never rebuild the census, resample accounts, refetch creation dates or launch chooser recovery.

The old engine acquisition is used byte-for-byte, in a separate process. It checks legal moves, final FEN, side to move, timestamps and recorded result, and evaluates each requested FEN with SF18, 100,000 requested nodes, one thread and 64 MB hash. It reads cached API responses before issuing serial missing-game requests. Up to ten engine processes run; numerical libraries use one thread per process. Network retry behavior and game nonreturns remain visible in the original report. Acquisition completion does not mean every requested game was returned or every position has a usable score.

## Variables

- Outcome: `100 × grant`. Keep never-granting accounts and singletons; singletons add no slope information. Canonical final evaluation determines competitive (≥−100 cp), losing (≤−300 cp) and middle-region membership throughout. Re-evaluated final scores are a diagnostic, not a sample reclassification.
- Last own move: if the recorded final ply is n, the rival moved at n−1. Own-move loss is evaluation(n−2) minus evaluation(n−1), from the rival's perspective. Final two/four-ply losses use (n−2,n) and (n−4,n). Positive loss means the rival's evaluated position worsened. Clip signed finite differences to ±1,000 cp; regressors are per 100 cp. The main blunder threshold is own loss ≥200 cp, with 100/300 companions, using finite own-move endpoints only.
- Mates: never turn them into ±10,000-cp move losses. Finite/positive-mate/negative-mate transitions are separate categories, with unavailable endpoints separate. Exact mate scores may finish before 100,000 nodes and are retained as mates; bounded scores and short finite searches are unavailable. Same-sign mate-to-mate endpoints have their own categories, without interpreting mate distance as centipawns.
- Clocks: recover the saved last recorded seconds from log(1+seconds), rounded to 1e−8 seconds to remove numerical roundoff; preserve saved missingness. The clock block has log(1+rival seconds), rival/chooser seconds and a trouble indicator below 10% of the time-control base. Zero chooser seconds give a missing ratio, and zero/unknown base gives a missing fraction. These are last recorded clocks, not reconstructed exact departure times. Increment is not added to the initial base. No data-dependent winsorization is applied to ratios.
- Material: rival-minus-chooser balance, pawn=1, knight/bishop=3, rook=5, queen=9, reconstructed from the saved FENs. Four-ply swing is final balance minus balance four plies earlier, so positive means the rival gained material. It has the opposite favorable-direction convention from positive CP loss. Unavailable early-game swings have a missing indicator.
- History: requires a separate all-rated-game chronology input. The numerator is the rival's own active disconnection events across sources; the denominator is rated standard live starts, measured strictly before focal start. The 90-day version and a version ending before November 1, 2023 have separate coverage flags. Do not equate no data with zero disconnections. Do not construct this from the restricted pool opportunity panel. The supplied-history adapter's audit contract is in `HISTORY_INPUT.md`.

## Specifications

Primary stage is ply >10; all-stage rows are companions. All regressions absorb chooser fixed effects and include the A1 month, speed and ply-band controls. Competitive proxy models use A1's eight final-evaluation categories. Losing proxy models use A1's unrestricted full-range evaluation spline, with extreme finite losses and negative mates separate. The losing specification is explicitly a new design choice; no arbitrary losing bin boundaries are selected using outcomes.

1. In each region, fit own-move loss, two-ply loss, four-ply loss, each of the three clock readings and material swing separately, then jointly. Missing numeric values are zero-filled only with explicit missing/category controls. All finite proxy slopes have named units. Mate-category and missingness coefficients are descriptive adjustment terms, not claims about blame.
2. Refit the unconstrained A1 competitive spline. Knots remain −100, 0, 100, 300, 600 cp, with finite ≥600 and positive mate as separate categories. Report 0→100, 100→300 and 300→500. Baseline and adjusted comparisons use exactly the same trajectory-supported rows. Also retain a baseline on the entire frozen target. A trajectory-supported row has a verified replay and usable finite or exact-mate scores for every requested position. Early positions missing because a game has not reached four plies retain structural missing indicators.
3. Add A1 clock/rating controls to the adjusted late-game profile on the same rows. The rival's log clock already in the proxy block is not entered twice. Rating controls retain gaps, premium and rating deviations with missingness indicators. Opportunity-standardized levels preserve the observed proxy/control distribution.
4. Estimate the competitive-minus-losing contrast before/after proxies on the same supported rows, omitting the middle region. These models cannot simultaneously absorb unrestricted final-evaluation effects; they do not.
5. Fit pooled late/all-stage models with each proxy interacted with competitive status, region-specific evaluation functions, and region interactions with month/speed/stage. Chooser effects remain common. These directly estimate conditional slope differences; they are a pooled specification, not the arithmetic difference of two separately fitted regressions. Never infer asymmetry just because one region's p-value crosses .05 and the other's does not.
6. Fit the low-own-loss (<100 cp) and ample-clock (>10% base) subset profile. Without history, call it exactly that. The additional no-prior-disconnection profile runs only with covered history and zero prior-90-day disconnections. Neither restriction identifies departures as accidental.
7. Within late competitive opportunities with finite own-move endpoints, regress the blunder indicator on rival-minus-chooser rating gap per 100 points, with chooser/month/speed/stage/evaluation controls. Fit 100/200/300-cp thresholds. These outcomes are `100 × blunder`, not `100 × grant`.

With a history manifest, add history models by region, history-adjusted joint models and common-history curve comparisons; lead interpretation with the prepanel history association because the rolling history may overlap the behavioral panel. Without it, finish all other models and mark the history tests pending. No automatic successful-completion claim covers missing tests.

## Estimation and inference

Adapt the already tested A1 two-pass estimator. Put every chooser's complete history into one of 256 Parquet buckets. All model matrices are generated from the same deterministic design. First pass accumulates within-chooser moments, second pass accumulates chooser-cluster scores and standardization influences. Column scaling precedes rank detection. Nonestimable contrasts are labeled, not given an arbitrary pseudoinverse interpretation.

Chooser-clustered covariance uses G/(G−1). Report unadjusted 95% intervals and named Holm p-values. Families are: all finite single-proxy tests across both regions within stage; joint-proxy tests across both regions within stage; pooled asymmetry interactions within stage; all threshold-by-region blunder tests; the three rating-gap/blunder-threshold tests; the two cross-region ladder coefficients; and the three planned steps separately for each explicitly named curve. Nonestimable planned tests retain a place in the family with p=1 for adjustment, but are displayed as unavailable. This does not control all exploratory interpretation across models. No family is redefined after seeing its estimates.

Coverage tables report replay nonreturns/invalids, mate/missing endpoint categories, finite final-engine discrepancies, clock support, each model's N and chooser count, retained singletons and never-outcome accounts, rank and hashes of each model's row set. Identifiers and raw rows remain private. The exported ZIP contains aggregate statistics and source metadata only.

## Interpretation gate

These proxies are noisy and may capture perceived merit, time pressure or unobserved player circumstances as well as blame. A null association does not validate zero blame; a nonzero association does not identify deliberate departure. Report intervals and the remaining precision. Stable curves after adjustment support descriptive robustness, not a decomposition into causal shares of merit and blame. The net-swing measures mechanically share the final evaluation; prioritize the own-last-move reading when discussing behavior. Do not impose monotonicity in order to preserve the A1 conclusion.
