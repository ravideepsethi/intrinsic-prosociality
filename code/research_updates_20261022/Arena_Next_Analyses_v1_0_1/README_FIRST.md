# Arena Next Analyses v1.0.1

Download the ZIP and its `.sha256` file, then run the complete command in
TERMINAL_COMMAND.txt. No manual edits or local package changes are needed.

The default input is the completed run:
`/Volumes/XT_Pro/lichess_kindness/output/arena_replication_v102/20260913T202346Z_96523`.
This package reuses its completed sample. It does not repeat the source-union
build or change the pool main sample.

Five completed analysis families are imported, byte for byte, from the verified
v1.0.0 report you returned. Their original receipts and configuration identifiers
are preserved. Only receipt/IV runs anew. Downloading the old report again is
unnecessary; its verified aggregate files are included in this package.

New results go under `output/arena_next_analyses_v101/` on XT_Pro. Aggregate
reports and checksums go to `~/Desktop/Lichess_Desktop/`. Rerunning the same
command resumes verified checkpoints. Local Python dependencies are checked;
if needed the launcher creates a separate environment on the Desktop.

Read REPAIR_NOTE.md for the configuration-hash fix and validation limits. The
original expected historical checksums remain mandatory. If authentication
fails, the report includes HISTORY_AUTHENTICATION.json with the failed phase
and observed hashes; historical configuration values are not exported.

Read ANALYSIS_SCOPE.md for the six included families, exact outcome definitions,
support rules and remaining analyses. In particular, the receipt/IV chronology
scan is large and can take substantially longer than the panel-only stages.
There is no production runtime benchmark for this new runner.

The sources were recovered from your public GitHub repository and are bundled
with Git blob IDs and SHA-256 hashes. The package works offline once its Python
dependencies are installed. VALIDATION.json describes the actual local tests;
synthetic validation is not a production result.
