# Validation

Passed in the development environment on September 28, 2026:

1. Original result checksum, all 30 internal hashes and original executed-code
   signature (`bf78172eb6b9ae486308a6d6abb4d8691917062c62387ded28530648609815b6`).
2. Actual python-chess parser reproduction of retained stale bound flags.
3. Seventeen live official SF18 Linux searches at 100,000 requested nodes:
   twelve bounded final updates; five directly usable under the original rule;
   all seventeen usable with the last-unbounded rule. Selected depth lag 0–1.
   This validates the reader, not the production Mac result.
4. Deterministic UCI process tests: stale flags, genuinely bounded final
   messages, no exact score, node-only messages, mate/CP separation and signs.
5. Selective inventory, global FEN deduplication, repaired Parquet projection,
   cache resume without rewrite, original-file preservation and damaged-source
   rejection. Repeated with the live SF18 binary.
6. Original A2 self-tests: all model designs, move orientation, finite/mate
   separation, clock cutoffs, material signs, fixed effects, cluster covariance
   and whole-chooser partition parity.
7. Full synthetic integration: 53 default and 62 optional-history models,
   exact regression checkpoint resume, and wrong history-cutoff rejection;
   elapsed 25.1 seconds.
8. Python compilation, launcher shell syntax and package checksums.

Production results cannot be recomputed here because the private raw-score
checkpoints are on the user's external drive. The Mac run performs its own
pinned-binary/source checks and an empirical reproduction check for the eighteen
models unaffected by the measurement correction. No new empirical A2 estimates
are claimed in this delivery.
