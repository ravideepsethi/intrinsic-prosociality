# Optional historical information and policy inputs

The main pre-policy analyses automatically use the existing certified panel and
chronology. The following optional inputs are required only for the historical
cue tests and the actual post-policy prediction/power comparison. Their absence
is recorded explicitly; it does not block the available pre-policy analyses.
Hashes establish the supplied bytes, not the truth of a producer declaration.

## Historical opponent cues

Default manifest:
`derived/replication/mechanism_cues_v100/manifest.json` under the project root.
Override with `--cue-manifest /absolute/path/manifest.json`.

The manifest has `format: MECHANISM_GAME_TIME_CUES_V1`, `key: game_id`,
`role: disconnected_opponent`, `unknown_is_false: false`, a `producer_receipt`
object `{path, sha256}`, and `files: [{path, sha256, rows}, ...]`.
Paths can be absolute or relative to the manifest. Each Parquet has unique
`game_id` and any of `provisional`, `title`, `patron`: 0, 1, or null.
There must be one key across all files. Null never becomes zero.

For each supplied cue, `semantics[cue].historical_at_game` must be true and the
producer receipt must document why it captures the information at the focal
game. A title retrieved from a present-day LightUser object is not necessarily
historical. The existing August 2026 Patron snapshot is inadmissible for this
purpose. API acquisition time is not game-time visibility evidence by itself.

The optional local provisional-threshold test additionally requires
`semantics.provisional.historical_threshold_rd: 110`,
`rd_threshold_calibration_reviewed: true`, and a nonempty
`no_other_cutoff_rule_source`. The code also checks observed flag/reconstructed
threshold agreement in RD 90–130. Failing this gate leaves the broad observed-
flag comparison available but does not release a threshold estimate.

Cue availability and within-sample support are reported before estimation.
The same cue-complete rows enter each baseline/augmented held-out comparison.
Title and Patron tests are observational information/profile associations.

## Actual post-policy prediction and power

Default manifest:
`derived/replication_36m/mechanism_color_inputs_v100/manifest.json`.
Override with `--policy-manifest /absolute/path/manifest.json`.

Required declarations:

- `format: MECHANISM_COLOR_INPUTS_V1`
- `pool_and_previous_adjacency_certified: true`
- `chronology_through: 2026-04`
- `cohort_uses_only_preimplementation_information: true`
- `actual_stratum_calibration_reviewed: true`
- `missing_clock_and_material_rules_aligned: true`
- `censor_utc`: source-supported timestamp, not the issue-opening date
- `producer_receipt`, `calibration_review`, `censor_source`: `{path, sha256}`
- `files`: `[{path, sha256, rows}, ...]`

Parquets use the prepared analysis schema documented in METHODS.md and add
`fixed_regular_cohort` and `pool_main` booleans. All four payoff fields `rg`,
`rc`, `ki`, `kj` must contain old-formula counterfactual values evaluated at the
stored pregame states, including after implementation. The calculator recomputes
both formulas at those same states, preserving exact premium changes.

The producer receipt must show the same observed-previous-adjacency predicate
before and after the change, completeness of relevant chronology through April,
the fixed preimplementation regularity eligibility date and source, and exclusion
of any post-policy activity from cohort eligibility. Post-pool membership cannot
be inferred from an event label or replaced with all-source opportunities.

Supply a continuous preperiod with at least 32 complete weeks for the bootstrap,
plus the post periods before the certified censor. Policy outcome `y` may be
present, but this package uses it only on preimplementation rows. It does not
compute an event-study coefficient. Complete unannounced and announced weeks
are analyzed separately; mixed implementation/announcement weeks are omitted.

If these inputs are absent, the package still writes exact model predictions
transported over the pre-policy regular sample and a clearly labeled preperiod
planning screen. That is not the actual post-cohort policy test. Fitted-parameter
uncertainty is not propagated in this release, so neither output is an automatic
GO decision or a preference bound. No IV is estimated.
