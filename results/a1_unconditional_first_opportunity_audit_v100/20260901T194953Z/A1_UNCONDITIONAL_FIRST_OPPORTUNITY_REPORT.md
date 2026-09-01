# A1 unconditional first-opportunity audit

**Status:** post-result secondary sensitivity; the frozen primary family is unchanged.

## Exact estimand

The sample includes first-pair, arm-eligible recipients with complete 90-day panel coverage. The outcome equals the recipient's first later fair-choice kindness indicator when such an opportunity occurs and zero otherwise.

## Result

- Effect: +0.458260 percentage points.
- SE: 0.057765 percentage points.
- p-value: 2.13654e-15.
- Rows: 2,185,073 (65,085 mercy; 2,119,988 claim).
- Weighted control mean: 1.6243%.

## Distinction from the existing companion

The certified `mandatory_unconditional_kind_companion` is one when a recipient grants at any fair opportunity within 90 days. This audit instead preserves the headline's first-opportunity outcome and changes only the nonreacher rule.

## Authentication

The frozen headline, reach companion, and existing any-grant companion reproduced exactly before the new model.
Stage-07 Parquet hashes verified in this run: `True`.

## Interpretation

This result addresses outcome-observation selection on the same first-opportunity outcome. It remains observational because the focal opponent chooses mercy and mercy also changes the recipient's material game outcome.
