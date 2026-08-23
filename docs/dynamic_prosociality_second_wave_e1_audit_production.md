# Dynamic prosociality E1 audit v1.0.0

## What this package does

It runs one focused audit of E1 using four parallel workers:

1. the existing exact fixed-effect solver;
2. an independent exact Schur solver;
3. the original exact-cell model with recursive singleton pruning and a tighter
   `1e-12` absorption tolerance;
4. a stricter chooser plus month-by-score-assignment-unit identification diagnostic.

If the fourth specification absorbs the score by construction, it reports the model as
not identified and leaves inferential fields blank; numerical dust is never presented
as an estimate.

The source E1 result is reproduced before the audit matrix is created. The completed
additional E1 result is copied into the final comparison table without being changed.

## Expected runtime

Expected wall time on the source Mac and XT_Pro volume is approximately **20 to 90
minutes**, most likely **30 to 60 minutes**.

- The source panel is projected once into a compact Zstandard-compressed private
  Parquet cache.
- Four independent fits run concurrently with four worker processes.
- BLAS threading is fixed at one thread per worker to avoid oversubscription.
- The 7.7-billion-row chronology is not rebuilt.
- Rerunning authenticates and reuses a completed private Parquet cache and completed
  aggregate output.

## Repository changes

The runner adds four reproducibility files to the existing repository:

- `code/11b_audit_dynamic_second_wave_e1.py`;
- `code/test_dynamic_second_wave_e1_audit_synthetic.py`;
- `docs/dynamic_prosociality_second_wave_e1_audit.md`;
- `docs/dynamic_prosociality_second_wave_e1_audit_production.md`.

The commit is ordinary version control for reproducibility. It is not presented as
proof that the analysis was designed before observing public historical data.

## Outputs

On success, the runner creates:

- an aggregate results directory under
  `/Volumes/XT_Pro/lichess_kindness/output/dynamic_second_wave_e1_audit_v100`;
- one results ZIP on the Desktop;
- one SHA-256 sidecar next to that ZIP.

Upload the results ZIP and its `.sha256` sidecar to the chat. The private cache and all
factor codes remain on XT_Pro and are not archived.

## Safety and resumability

The runner fails closed if the current repository, source scripts, source result
receipts, or completed additional result differ from the expected inputs. It never
overwrites the source second-wave or additional-analysis results.
