# Pool matchmaking audit v1.0.0

The design note reviews historical Lichess matchmaking code and proposes the next empirical checks. The runnable component inventories existing input schemas and footer counts only. It does not run those empirical checks.

Read `DESIGN_NOTE.md` for the argument, source links, specific tests and manuscript language. `SOURCE_INDEX.json` records the selected historical source snapshots and their hashes; source authors retain their copyrights and the included Lila code remains AGPL v3 or later under `sources/lila/LICENSE` and `sources/lila/COPYING.md`.

Run `RUN_COMMAND.txt` from Terminal after placing this ZIP and its sidecar in `~/Desktop/Lichess_Desktop`. The launcher verifies the package and reuses an existing Python containing DuckDB. It installs nothing.

Expected runtime: 5–30 seconds, or 1–2 minutes on a busy disk. One thread, no network, no game-row reads, no Stockfish work. No private inputs or current analysis checkpoints are changed. The output ZIP and its sidecar appear in the Desktop folder; upload the two paths printed by the probe.

Optional environment overrides: `MM_AUDIT_PYTHON`, `MM_AUDIT_PROJECT_ROOT`, and `MM_AUDIT_DESKTOP`. Missing documented inputs are reported explicitly; the probe does not crawl the rest of the disk.

The target main sample remains the certified 41,534,331-opportunity pool/nonadjacent panel. Agreement of metadata counts is not a new sample certificate or a full-byte rehash. Field-name matches are suggestions for manual semantic review, not evidence that queue histories or internal conduct states were observed.
