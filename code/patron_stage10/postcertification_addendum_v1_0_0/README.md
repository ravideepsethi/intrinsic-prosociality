# Patron Stage 10 post-certification addendum v1.0.0

This package is a separate, append-only follow-up to the authenticated Patron
Stage 10 production v1.0.1 result. It never changes, deletes, or replaces the
certified output at:

`/Volumes/XT_Pro/lichess_kindness/output/PATRON_STAGE10_PRODUCTION_V100`

## Why this addendum exists

The final result audit authenticated the primary result and all reported
robustness, rematch, diagnostic-kindness, dose, and opportunity analyses. It
also found three limited secondary-contract gaps:

1. missing `created_at_ms` and `seen_at_ms` values had been transformed to zero
   days before the v1.0.1 imputation step, so the rich-control sensitivity did
   not retain their intended missing indicators;
2. the frozen contract requested a chooser-level five-fairness-bin companion,
   while v1.0.1 emitted the distinct opportunity-level patron interaction; and
3. the frozen contract requested count and rate price companions, while v1.0.1
   emitted the ever-kind price indicators and opportunity appendix.

The certified primary match-cell-FE model uses none of these affected date
controls and remains unchanged.

## What this package runs

- explicit missing-date rich-control models, including HC1, match-cell CR1, and
  disabled/TOS exclusions;
- simultaneous chooser-level kindness indicators across the five certified
  fairness bins, with exposure controls, the frozen full control set, common
  min-2/min-4 support, and endpoint/adjacent contrasts;
- standardized `log(1 + count)` and rate price-side companions at min-2/min-4
  support, with HC1 and min-4 match-cell CR1 inference;
- strict RFC JSON generation, independent hash verification, privacy checks,
  and an authenticated public-only transfer bundle.

All addendum estimates are secondary or sensitivity analyses. They describe
current cross-sectional stable-type associations. Patron adoption timing and
causality are not identified.

## Safety and reproducibility

- no API calls;
- no dependency installation or mutation;
- no Git operation;
- no source-data or certified-output mutation;
- exact verification of the canonical Python numerical environment;
- exact authentication of the production snapshot, v1.0.1 public manifest,
  stage receipts, and two private caches;
- checkpointed addendum stage; rerunning the same command authenticates and
  skips a completed stage;
- `PYTHONDONTWRITEBYTECODE=1`, plus a fail-closed source-bundle cleanliness
  check so generated `__pycache__` content is not transferred.

Expected runtime is approximately 10-45 minutes, most likely 15-30 minutes on
XT_Pro. The included end-to-end synthetic self-test ordinarily takes 1-3
minutes.

The `selftest_base_v101/` directory is a synthetic-test harness only. Its
fixture generator deliberately adds missing account dates and independent
five-bin support so the addendum's failure paths are exercised. It is not the
authenticated production v1.0.1 source authority, and its nested launcher must
not be used for production. The top-level addendum launcher is the only entry
point for this package.
