# Execution ledger: A2 repair

Completed in this review:
- Original ZIP, internal report hashes and executed code signature verified.
- Severe board/stage-dependent trajectory missingness identified.
- True bounded-final-message behavior reproduced with official SF18.
- Stale merged-flag hazard reproduced with the actual python-chess UCI parser.
- Atomic score reader and last-unbounded fixed-budget rule implemented.
- Selective repair, unique-FEN deduplication, raw message retention, small
  Parquet shards, shared cache locking and exact checkpoint resume implemented.
- Default 53-model and optional 62-model synthetic pipelines passed.

Pending on the Mac:
- Inventory the exact original score-status distribution.
- Repair the necessary unique FENs with the pinned Mac SF18 binary.
- Check corrected coverage, selected-score depths and canonical-final agreement.
- Re-estimate the A2 models; assert 18 unaffected models reproduce.
- Review the new empirical result before manuscript use.

Still outside this repair: the three all-game disconnection-history tests,
arena, titles, incidents and other handoff analyses. No claim of completion
covers those items. The original A2 trajectory-adjusted results are on hold.
