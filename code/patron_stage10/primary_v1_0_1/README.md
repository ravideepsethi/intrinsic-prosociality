# Patron Stage 10 production recovery v1.0.1

This package estimates the authenticated 24-month patron-status extension after the
complete 2026-08-26 profile acquisition.

## Status

The input inventory and exact mapping review are complete. Production uses the stored
1:3 assignments; it does not reconstruct or search for controls.

Version 1.0.1 is the fail-closed recovery from the v1.0.0 real-data Stage 01
imputation error. It changes no sample, estimand, model, matching rule, or frozen
authority. It converts nullable integer covariates and their within-cell medians to
`float64` before median imputation, preserving fractional medians exactly. See
`RECOVERY_NOTE_v1.0.1.md`.

## Runtime

- Synthetic end-to-end test: approximately 1–5 minutes.
- Chooser feature/cache stage: approximately 15–60 minutes.
- Chooser models and 100 rematches: approximately 30–150 minutes.
- Opportunity-level appendix: approximately 30–180 minutes.
- Total: approximately 1.5–6 hours; most likely 2–4 hours on XT_Pro.

The run is resumable at stage boundaries. It authenticates and reuses the completed
v1.0.0 chooser-design cache, then resumes at the chooser-model stage.
Before skipping a completed stage, the code re-authenticates its frozen inputs,
private cache, receipts, and public-output hashes; a mismatch fails closed rather
than silently recomputing or overwriting the completed stage.

## Environment policy

The launcher requires and verifies exactly:

- DuckDB 1.5.2
- NumPy 2.4.4
- Pandas 3.0.3
- PyArrow 24.0.0

It never invokes `pip`, installs a package, or changes the shared environment.

## Run

Execute `RUN_PATRON_STAGE10_PRODUCTION.command` through the authenticated outer
launcher supplied with the ZIP. The script runs the synthetic test, all production
stages, the independent verifier, and transfer-bundle creation in one invocation.

Production output is stored at:

`/Volumes/XT_Pro/lichess_kindness/output/PATRON_STAGE10_PRODUCTION_V100`

The launcher creates a redacted transfer ZIP and SHA-256 sidecar in:

`/Users/u6025368/Desktop/Lichess_Desktop`

## Analysis contents

1. exact input and stored-match authentication;
2. return/missingness and patron-field QA;
3. broad-role audit and primary fair-kind frozen 1:3 comparison;
4. match-cell-FE HC1 primary and CR1 sensitivity;
5. covariate ladder and common-support analyses;
6. all three stored 1:1 slots and 100 deterministic 1:1 selections;
7. dose response;
8. fair-versus-clearly-worse diagnostic kindness;
9. costly-versus-nonnegative price-side diagnostic; and
10. opportunity-level patron × desert, patron × price, and three-way appendix models.

## Interpretation

Patron status is current as of the 2026-08-26 snapshot. Results are cross-sectional
stable-type associations. Patron adoption timing and a causal effect of kindness on
patronage are not identified.

## Privacy

Private caches can contain normalized account identifiers and stay on XT_Pro. The
transfer ZIP contains aggregate and model outputs only. Never commit or publish the
profile snapshot or private caches.
