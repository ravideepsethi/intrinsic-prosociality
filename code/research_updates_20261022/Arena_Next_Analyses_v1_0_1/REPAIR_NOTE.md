# Repair v1.0.1

The returned v1.0.0 report is intact. Core (52 fits), robustness (24 fits), the
targeted rating-gap repair, B1 episodes (4,999 randomizations), and Patron
(34 models plus four corrected-date sensitivities) completed. Receipt/IV
stopped during historical input authentication, before the chronology scan
or estimation.

The failing check used the rebuilt IV utility's compact JSON serialization:
`json.dumps(config, sort_keys=True, separators=(',', ':'))`.
The older pipeline sources instead use `json.dumps(config, sort_keys=True)`.
These produce different SHA-256 digests for the same configuration object.
Both conventions are documented in the bundled, unchanged repository sources
under `authority/hash_format_sources/`, with provenance in
`authority/HASH_FORMAT_PROVENANCE.json`.

The adapter now checks the unchanged expected digest against those two observed
upstream formats. It accepts a configuration only when one digest matches.
It does not strip keys, replace the expected digest, accept an arbitrary file,
or change the hash format for new run/checkpoint contracts. The IV pilot's
configuration is checked the same way. Projection hashes, lineage hashes,
reference-delta receipts and the canonical chronology checks remain enforced.
Relevant input files also receive pre/post stat checks.

The actual historical comparison configuration was not included in the returned
report. The format incompatibility is reproduced locally against the original
producer's hash function; authentication of the Mac's real configuration still
occurs at run time. A genuinely changed configuration is rejected, with both
observed digests and the failed phase saved in the aggregate report.

The five successful families are imported from the exact returned report:
`ARENA_NEXT_ANALYSES_RESULTS_v100_run_441055dd42cb661a.zip`, SHA-256
`236b172776fdad18c74ded3ea3ded60a70e95a162616232487f1562b4be95c4b`.
The archive, its manifest, all result files and original completion receipts are
checked before import. The current arena input margins must equal the old
report's margins, in addition to the normal v1.0.2 input authentication. The
statistical sources for those families and all shared functions are unchanged;
only the shared version string differs. The old receipts are retained as
`_V100_DONE.json`, and `INHERITED_FROM_V100.json` records their origin.
The new receipt certifies this import, not a fresh execution of old analyses.

All 36 originally bundled repository sources remain unchanged. The two
additional upstream files are hash-format references; they are not substituted
statistical engines. No completed run or private cache is overwritten.

The validation suite passes 15 top-level tests, including the original 16 IV
numerical tests within one of those tests. It covers both hash conventions,
changed-configuration rejection, preservation of lineage checks, diagnostic
output, import/resume of the actual aggregate results, changed-result rejection,
population mismatch rejection, and the prior numerical/integration checks.
No production receipt/IV estimate has been computed in this environment.

The remaining chronology scan reads 852 files containing about 7.76 billion
rows, with a checkpoint per file. Its production duration is unbenchmarked.
The defaults retain four chronology workers, three score-history workers and
a 4 GB DuckDB buffer. Rerunning the same command resumes verified checkpoints.
