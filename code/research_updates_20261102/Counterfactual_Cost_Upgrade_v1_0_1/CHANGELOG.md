# Version 1.0.1 — October 24, 2026

The production v1.0.0 log authenticated all 24 months and then stopped on
`Claimed win without mating material`. The traceback identified the new
assertion in `worker.py`, not an input authentication or dependency failure.

Review of the earlier work found:

- Stage 05 deliberately preserves the historical piece-count material screen.
  It does not implement the full Lichess side-specific insufficient-material
  predicate.
- The earlier Pool_Rating_Validation defines its claimed-win sample from the
  actual PGN result and chooser color. It does not restrict wins by the cached
  material flag. Its unchanged consume function is now a regression-test
  reference.
- The 2023 and 2025 platform source snapshots allow some lone-bishop and
  lone-knight wins, depending on the opponent's pieces; bishop square colors
  also matter. The pinned claim handler uses this platform predicate.

This release removes the incorrect assertion and restores the earlier
observed-win validation definition. It also repairs v1.0.0's action-cost
classification: the platform predicate determines whether claiming can win.
All hypothetical rating changes still use the same pre-game rating state.

The original material flag and behavioral outcome remain available unchanged.
A separate platform-material flag, candidate draw label, and aggregate audit
show all differences. An observed win still contradicting the source-based
predicate is retained for rating validation, with NULL action costs and a
diagnostic flag. It is not silently assigned zero cost or removed from the
panel. No manuscript results are replaced.

The package version and code checksum create a new run identity, so v1.0.0
outputs are preserved and cannot be reused as corrected outputs. The same
cached input Parquets, author exclusions, 10-worker default, 11-GiB budget,
25/50/75/100% checkpoints, and zero-network computation remain in use.
