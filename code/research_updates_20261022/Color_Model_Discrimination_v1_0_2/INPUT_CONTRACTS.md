# Actual policy-target adapter

This is a contract for an existing evidence-backed producer. It is not an instruction to create a manifest by setting flags to true. The known handoff does not establish that this target already exists.

The default planning run needs only the authenticated 24 monthly mechanism Parquets. This additional contract applies only to actual-target prediction/power and optional behavior output.

## Manifest

Recognized `format` values: `MECHANISM_COLOR_INPUTS_V1` and `MECHANISM_COLOR_INPUTS_V2`. Either must include the explicit coverage and scope fields below; the earlier V1's Boolean flags alone are insufficient for this capped comparison.

| Field | Required meaning |
|---|---|
| `pool_and_previous_adjacency_certified` | True, backed by the sample producer's receipt |
| `cohort_uses_only_preimplementation_information` | True, with pre-policy same-speed history and activity defining fixed eligibility |
| `actual_stratum_calibration_reviewed` | True, backed by a capped-target reconstruction review |
| `missing_clock_and_material_rules_aligned` | True, backed by aligned definitions |
| `calibration_rd_cap` | 110, covering both players and the actual target |
| `payoff_convention` | `anchored_novol_noreg_old_formula` |
| `cohort_information_cutoff_utc` | Explicit timezone; no later than `2025-11-18T07:22:00Z` |
| `coverage_start_utc`, `coverage_end_utc` | Explicit timezone, exhaustive source-coverage interval; not inferred from first/last observed opportunity |
| `censor_utc` | Source-supported mechanics cutoff, after implementation, within source coverage |
| `chronology_through` | `YYYY-MM`, covering the last included observation's month and necessary prior boundary history |
| `producer_receipt`, `calibration_review`, `censor_source` | Objects with `path` and `sha256`, referring to real existing evidence |
| `files` | Nonempty list of objects with `path`, `sha256`, and exact Parquet `rows` |

Relative paths resolve against the manifest directory. SHA256 and row counts are checked. Source chronology need only cover the required window; April is not imposed when the outcome window ends in January.

The producer must document the accepted regularity rule, membership boundaries and missing-value handling in its receipt. An account remains in the fixed cohort regardless of later activity. The upstream pool predicate was pool source plus `not_mutually_adjacent_observed`; a last-rated-game lookup alone is not equivalent to that certification.

Calibration evidence must compare observed changes and reconstructed changes by outcome, speed, color, RD and gap, including signed errors and near-zero draws. A pooled all-account MAE does not certify this target. The censor source must state the underlying source/event evidence and the observed concentrated mechanics changes; an issue date alone is insufficient.

## Parquet columns

`game_id`, `chooser`, `t`, `speed`, `color`, `y`, `cp`, `ply`, `rating`, `opp_rating`, `g`, `rd`, `opp_rd`, `rg`, `rc`, `ki`, `kj`, `clock`, `opp_clock`, `month`, `history_days`, `prior_starts`, `inactivity_days`, `opp_prior_starts`, `fixed_regular_cohort`, `pool_main`.

- `t`: integer UTC Unix milliseconds. `month`: matching `YYYY-MM`.
- `chooser` and `game_id`: the existing stable keys. One decision opportunity per game; duplicates across source files fail.
- `y`: 1 for grant, 0 for claim. Unknown outcomes cannot be coded as 0.
- `color`: `white` or `black`, the chooser's color at the decision.
- `speed`: the audited five-speed encoding.
- `cp`: the existing audited evaluation convention; the adapter inherits roughly-equal `−100≤cp<100` and ply>10.
- `g = opp_rating − rating`; supported gap `−575≤g<575`. Both RDs must be positive and ≤110.
- `rg`, `rc`: chooser's **old-formula** draw/claim payoffs at the stored state, even after implementation.
- `ki = rc − rg`; `kj`: opponent's corresponding old-formula premium. All four are checked against the audited calculator.
- History counts/durations: finite, nonnegative, using the existing mechanism feature definitions. Clock missingness retains the audited missing-value convention.
- `fixed_regular_cohort`, `pool_main`: Boolean producer-certified flags, not inferred by this runner.

The files must cover the fixed cohort before and after implementation, with at least 32 consecutive complete pre weeks, all eight baseline weeks, and both colors in every included complete week. The runner never fills missing color/week cells with zero. It applies the factual-state RD/gap/board screen identically to both counterfactual formulas. Post-policy changes in which eligible opportunities arise remain a composition issue.

Predictions read no target `y` column. Schema validation checks that outcomes are binary without calculating post-period rates. Auto mode aggregates outcomes only before implementation. Explicit behavior mode opens post-period aggregate statistics only after prediction and power files have been sealed.
