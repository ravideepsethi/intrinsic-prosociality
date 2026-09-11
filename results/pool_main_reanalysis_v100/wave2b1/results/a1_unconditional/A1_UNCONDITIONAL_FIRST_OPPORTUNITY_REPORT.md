# A1 unconditional first-opportunity audit

**Status:** post-result secondary sensitivity; the frozen primary family is unchanged.

## Exact estimand

The sample includes first-pair, arm-eligible recipients with complete 90-day panel coverage. The outcome equals the recipient's first later fair-choice kindness indicator when such an opportunity occurs and zero otherwise.

## Result

- Effect: +0.399242 percentage points.
- SE: 0.057593 percentage points.
- p-value: 4.14688e-12.
- Rows: 2,110,400 (62,237 mercy; 2,048,163 claim).
- Weighted control mean: 1.5642%.

## Distinction from the existing companion

The certified `mandatory_unconditional_kind_companion` is one when a recipient grants at any fair opportunity within 90 days. This audit instead preserves the headline's first-opportunity outcome and changes only the nonreacher rule.

## Authentication

The frozen headline, reach companion, and existing any-grant companion reproduced exactly before the new model.
Stage-07 Parquet hashes verified in this run: `False`.

## Interpretation

This result addresses outcome-observation selection on the same first-opportunity outcome. It remains observational because the focal opponent chooses mercy and mercy also changes the recipient's material game outcome.
