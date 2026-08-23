# Dynamic prosociality E1 audit recovery v1.0.1

## What failed and what this repairs

The v1.0.0 run stopped at the first audit fit because the Stage 08 exact two-way
absorber deliberately supports at most 512 levels in its smaller fixed effect, while
the E1 exact-cell model has 671. The stop occurred after the private Parquet cache was
built and before any audit result was written. It does not indicate damaged data or a
bad cache.

This recovery leaves Stage 08 unchanged and removes only that inapplicable audit
benchmark. It runs three applicable fits in parallel:

1. an independent exact small-side Schur solver for chooser and all 671 exact cells;
2. an independent recursive-singleton, `1e-12` alternating-projection replication of
   the same chooser, month, and exact-cell coefficient;
3. a stricter chooser plus month-by-score-assignment-unit identification diagnostic.

The two independent exact-cell implementations must agree on the risk coefficient
within `1e-8` per unit or the run fails. If the third specification absorbs the score
by construction, it reports the model as not identified and leaves inferential fields
blank; numerical dust is never presented as an estimate.

The source E1 result is reproduced before the new audit matrix is created. The
completed additional E1 result is copied into the final comparison table as a reference
without being changed.

## Expected runtime

Expected wall time on the source Mac and XT_Pro volume is approximately **20 to 75
minutes**, most likely **25 to 50 minutes**.

- The source panel is projected once into a new compact Zstandard-compressed private
  Parquet cache. The 29.8 MB cache from the failed run is left intact rather than
  silently relabeled under a changed analysis configuration.
- Three applicable fits run concurrently with three worker processes.
- BLAS threading is fixed at one thread per worker to avoid oversubscription.
- The 7.7-billion-row chronology is not rebuilt.
- Rerunning authenticates and reuses a completed v1.0.1 private cache or aggregate
  output.

## Repository changes

The recovery replaces the four E1-audit reproducibility files already installed by
v1.0.0 and updates their script hashes:

- `code/11b_audit_dynamic_second_wave_e1.py`;
- `code/test_dynamic_second_wave_e1_audit_synthetic.py`;
- `docs/dynamic_prosociality_second_wave_e1_audit.md`;
- `docs/dynamic_prosociality_second_wave_e1_audit_production.md`.

It requires the authenticated v1.0.0 audit commit as its parent and creates one narrow
repair commit. The commit is ordinary version control for reproducibility, not evidence
that the analysis was designed before observing public historical data.

## Outputs

On success, the runner creates:

- an aggregate results directory under
  `/Volumes/XT_Pro/lichess_kindness/output/dynamic_second_wave_e1_audit_v101`;
- one recovery-results ZIP on the Desktop;
- one SHA-256 sidecar next to that ZIP.

Upload the recovery-results ZIP and its `.sha256` sidecar to the chat. The failed v1.0.0
state, all private caches, and all factor codes remain on XT_Pro and are not archived.

## Safety and resumability

The runner fails closed unless the repository is exactly at the authenticated v1.0.0
audit commit or its exact recovery child. It verifies the pre-repair audit files,
source scripts, source result receipts, and completed additional result before making
changes. It never edits the Stage 08 solver and never overwrites source second-wave,
additional-analysis, or failed v1.0.0 audit files.
