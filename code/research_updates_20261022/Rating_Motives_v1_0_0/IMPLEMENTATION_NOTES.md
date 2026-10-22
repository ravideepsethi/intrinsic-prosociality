# Implementation record — v1.0.0

This release implements the revised 23 September 2026 v1.1 specification. The included specification is unchanged; its SHA-256 is `8bdfe7dfbb0f69ca2cf1fbe75ba9fd4a9a6fa7c434ed5d933d6714cb5cdd5497`.

## Readiness and scope

The certified 41,534,331-row outcome panel and its monthly hashes are bound to the bundled main-sample authority. The older 47.6-million-row frame is not accepted. Account creation comes from the lossless August profile snapshot, plus the exact audited gap supplement when present. The sample requires a positive valid creation timestamp and at least 365 elapsed days at the API game-start timestamp. Acquisition-role and board-state counts expose the selected linkage sample. No inclusion weights are claimed.

The certificate's existing eligibility decisions are retained. The main counts and competitive counts are independently reproduced after projection. Missing/invalid required main fields and inconsistent finite payoff identities stop preparation. Missing recipient payoff/RD fields are counted; missing target fields are excluded from the corresponding model. T5 is blocked if the effective-E validation fails. Other independently available models can still run.

Both sides' reconstructed win/draw payoffs and premiums exist in this panel. Recipient stake uses the recipient's own side-specific premium. Under the verified common-scale representation, draw-minus-loss equals win-minus-draw; an implied loss update is `2*recipient_draw - recipient_win`. This is not the chooser's stake or an observed realized update. The recipient role identity and its win-minus-draw identity are checked. Expected score is reconstructed as `0.5 - chooser_draw/(2*chooser_premium)` and compared with the pre-state opponent-RD Glicko expectation. The maximum permitted discrepancy for the precise threshold test is 1e-6; exact-zero and threshold-boundary tolerances remain those in the frozen note.

The common scale is the certified replay representation; this package does not recalibrate K from realized outcomes or import a current platform rating regime. It records displayed/replay rating disagreements. The mathematical payoff identities do not by themselves establish that every unchosen counterfactual equals the platform's historical displayed update.

Absent the enriched history, T1/T2 **diagnostic_no_prior_count** fits omit only the unavailable recipient-volume control and retain their own remaining specification and exact-zero restriction. They are exploratory diagnostics outside the five primary tests. Missing-history tests are explicit unsupported entries, not zeros. T1's later responsibility-control sensitivity remains pending external output under its separate plan; it is not generated here.

Section 9's reference to history-closure receipts applies to this kindness history and its coding. It does not import the separate 2013 Rating Redesign closure/disposition project. No producer receipt from that unrelated project is bundled as authority.

## Construction details

- Histories are filtered by **completion < current start**, separately by account and speed. End-time ties cannot be resolved with game IDs. Counts/peaks are order invariant; performance windows crossing ambiguous ordering are excluded. Missing ordinary-game data invalidate that window rather than selectively dropping difficult records.
- The penalized performance score equation is strictly decreasing. A rigorous bracket is current rating ± `(tau^2 * sum(a_h) + 1)`, where `a_h = g(RD_opp/173.7178)/173.7178`. Bisection reaches a 1e-6-point interval, including all-win and all-loss histories.
- The last-15 and last-60 alternatives may change the performance-eligible sample; paired `common15` / `common60` rows estimate the primary proxy on their intersections. `common200` / `common800` provide analogous primary comparators for regularization changes. At least 30 observed prior games and a valid peak remain required for T3/T4.
- Missing observed post-game updates do not erase an available pre-game rating from the peak. They do not create an imputed post-game rating. The 365-day peak is computed separately. The rounding sensitivity uses nearest integer with half points rounded upward, explicitly an approximation rather than a recovered historical display.
- Predictive validation hashes normalized chooser usernames (the API's canonical account identifiers), not the project's numeric ID assignment. It selects the first eligible ordinary start per account/speed/month in November 2023–October 2025, then the next ordinary start strictly after anchor completion within 30 days. An ordinary validation game must have finite ratings/RDs and a valid score. Simultaneous starts are excluded as unresolved. Future scores do not select the anchor or its tuning constants.
- Invalid/nonfinite/negative clocks use zero inside `log1p` and a separate missing indicator, matching the existing clock convention. Other missing covariates are not imputed to zero.
- T2 cubic sensitivities report full-covariance predicted doubling contrasts K=10→20, 20→40, 40→80. Their observed support and any extrapolation are labeled. These fixed reporting points are implementation choices made before any new empirical estimate, not selected favorable regions.
- T3's interaction sensitivity uses the exact estimation-sample average of log K to report the average performance-gap contrast. It does not report the isolated main term as the whole effect.
- E profiles use nine bins over [0.50,0.95], with the last including 0.95 and [0.70,0.75) as adjusted reference. Values outside this range appear in raw descriptive tables. Adjusted coefficients are bin contrasts in their own FE model, not threshold-estimator bins or absolute fitted rates.

## Estimator and inference

Every model applies its restrictions before removing fixed-effect singletons. Never-granters remain. Files are partitioned by numeric chooser ID modulo 16 and sorted so an account cannot be split across estimation shards or Arrow blocks. All months contribute to one chooser cluster score.

The first pass accumulates within-FE normal equations. The second pass forms residuals and cluster influence sums. A scaled symmetric eigensolve uses a documented deterministic rank convention: columns with within sum of squares at most max(`max_diagonal*1e-13`, `1e-12`) are inactive; normalized eigenvalues must exceed max(`largest*1e-10`, `1e-12`). Requested contrasts must lie in the estimable subspace to relative tolerance 1e-6. Unidentified targets are withheld, while aliased nuisance directions are handled with the generalized inverse. Invariant/negligible columns, rank, eigenvalue condition and contrast estimability are reported.

Full model rank is the number of absorbed nonempty fixed-effect groups plus within-design rank. Chooser CR1 is `G/(G-1) * (N-1)/(N-full_rank)`, with t(G-1) intervals. Joint competitive/losing fits use chooser-by-state effects, state-specific nuisance columns, and chooser cluster scores spanning states. Their individual point estimates must reproduce the separate fits to 1e-6 probability units before the difference is reported.

Primary fits additionally get a chooser/recipient two-way covariance sensitivity: chooser component + recipient component − ordered chooser/recipient-pair component, with the corresponding cluster-count corrections and common full-rank residual correction. Recipient scores are aggregated across all shards on disk. The t degrees of freedom use min(chooser clusters, recipient clusters)−1. A negative/nonfinite variance is reported unsupported, never clamped into a favorable standard error. These are role clusters, not a general shared-account/network covariance correction.

Primary discovery, primary equivalence and secondary state-difference families each retain five slots. Missing or unidentified tests enter each applicable adjustment with p=1. Equivalence is a TOST at ±0.10 pp for the declared primary reporting contrast, followed by a separate Holm adjustment. Sensitivities have raw intervals and p-values; no nine-model or all-sensitivities Holm family is imposed.

Support diagnostics include all age/state input rows, selected rows before singleton removal, retained N/grants/choosers/recipients, exact focal quantiles/range, target and outcome switchers, joint switchers, clock missingness, K range, raw within-target variation and target residual information after nuisance projection. The simple never-granter share is a chooser-demeaned first-target diagnostic, not the fraction of fully adjusted identifying information. For binary targets the positive/nonpositive counts are exposed/unexposed counts. For continuous targets they are sign counts, not treatment groups.

Exact recipient counts and target quantiles use small-column private Parquet ledgers written during estimation. These and row-level cluster influence files never enter the report ZIP. The generalized-inverse quadratic form gives contrast information; for a single estimable coefficient its reciprocal is the target residual sum of squares after the nuisance projection. Quantiles for multi-contrast profiles refer to the first raw focal column; each profile's bin support is separately supplied.

## Validation and operational limits

The release checks the FE estimates and full-rank chooser covariance against an independent dense regression with explicit dummy variables. Tests also cover two-way score aggregation, joint state reproduction, aliased targets, block boundaries, exact-zero nuisance exclusions, the polynomial bases, future leakage, completion ties, missing post updates, stable-RD/status restrictions, finite performance optimization, profile deduplication, the immutable census-count failure gate, enriched history construction, nonempty predictive validation, all registered model variants, aggregate reporting, multiprocessing and byte-identical resumed estimates.

These are synthetic checks. They do not establish empirical support, historical source completeness or success on private production files not available here. Input authentication, population counts and post-join conservation are therefore runtime gates. A scientific null is never inferred from a construction failure or unavailable input.

The full panel needs disk space for projection/sorting, checkpoints and private support ledgers. Optional enriched history may be much larger; it is built once and reused. DuckDB can spill to the PRIVATE temporary directory. The runner gives heartbeat and shard progress rather than an unmeasured completion-time promise.

No API requests, emails, messages, new profile pulls, engine runs, outage matching or deletion of earlier analyses are performed. Python package installation is the only network step in the Mac launcher. Temporary files belonging to an incomplete current-run shard can be rebuilt; certified sources are untouched.
