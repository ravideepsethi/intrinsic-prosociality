TEST G v2.1 — CODE PACKAGE 2.1.1

Put Test_G_v2_1_1.zip and Test_G_v2_1_1.zip.sha256 in:
    ~/Desktop/Lichess_Desktop
Then paste TERMINAL_COMMAND.txt into Terminal. Leave that Terminal running.

The launcher verifies the ZIP and its contents, reuses the installed Test G
Python environment (or creates it from the existing project Python), checks its dependencies,
runs the synthetic validation suite, and starts the analysis under caffeinate.

Project:
    /Volumes/XT_Pro/lichess_kindness
Existing Python used to create the new environment:
    /Volumes/XT_Pro/lichess_kindness/venv/bin/python
New environment:
    /Volumes/XT_Pro/lichess_kindness/venv_test_g_v210
Private run directory:
    derived/replication/test_g_v210_PRIVATE/<configuration hash>

It uses the certified sample lineage from repaired A–F, with the author
exclusions in both roles. Test G has its own run directory. R9, run
2a4e617b40bc, original monthly panels and raw histories are read-only inputs.

WHAT THE DEFAULT COMMAND DOES

1. Authenticate the 24 monthly main-panel inputs, inventory surviving PGNs,
   authenticate cached status evidence and validate the ending rule.
2. Verify the exact original Stockfish binary and re-evaluate 10,000 positions.
3. Sample up to 2,000,000 completed-game positions, evaluate them, fit both G1
   models, and enforce calibration and cross-year stability.
4. Build physically complete chooser partitions; fit M0, MR, MU, MRU, MRprime
   and MRUprime; perform G2a–f, numerical checks and a statistical check of the
   2,000-block approximation.
5. Run the combined bootstrap in 50-G1-draw batches, up to 500 G1 draws. Each
   G1 draw has ten chooser-block resamples. Save measured pilot timings.
6. Run G3 when its optional data are authenticated, then the additional G1
   sensitivities and account-overlap exclusion when required.

The first launch has NO permission to download PGNs or make API calls. A failed
coverage or status gate writes an aggregate BLOCKED report and exits with code 2.
Review/return that report before approving additional data acquisition. The
package never makes new Lichess game/profile API requests.

ONLY AFTER APPROVAL, the launcher accepts --approve-missing-pgn-streams.
This creates a different configuration, streams the missing Nov 2023–Oct 2025
standard monthly dumps from the fixed public URL allowlist, verifies the bundled
published checksums, and fills reservoirs without retaining full dump files.
Do not add this option to the first command. Downloads are sequential and may
be substantial. There is no automatic approval or silent fallback.

If all 24 source months are present and cross-year stability fails, the code
fits by year and rechecks held-out calibration within each year. If months are
missing, it stops for the approved source fallback first.

REPORTS

The Desktop folder receives PHASE025, PHASE050, PHASE075, POINT, CORE, bootstrap
batch and PHASE100 ZIPs, each with a SHA256 sidecar. The final sanitized log is
TEST_G_<run id>.log. A BLOCKED or INTERRUPTED ZIP is also accompanied by a hash.

Return the newest report ZIP, its .sha256 sidecar, and the log. Reports contain
aggregate tables, figures and provenance only. Game IDs, usernames, FENs,
private predictions, bootstrap coefficients, row data and private tracebacks
stay in the run directory.

Every requested table has either estimates with their uncertainty or an explicit
not-run/failure status. CORE_COMPLETE_SECONDARY_GATES_REPORTED is not a claim
that G3 or failed sensitivity fits completed. Read COMPLETION_SCOPE.json.

Each CSV starts with a # JSON metadata line containing N, sample, source months,
ending-status coverage and caveats. Read in pandas with comment='#'.

RESUME

Run the same Terminal command again. Completed authenticated checkpoints and
completed G1 bootstrap families are reused. Interrupted PGN reservoir creation
restarts that sampling pass; partial engine chunks alone are repeated. Changing
code, source selection, optional-data manifest, target sample size or bootstrap
maximum creates a distinct configuration. Keep the same ZIP to resume a run.

RESOURCE SETTINGS

Defaults: ten engine-worker slots, 11 GiB declared memory budget, 256 physical
chooser partitions, BLAS/OpenMP one thread per numerical process. The engine
pool is further limited by the original Threads/Hash settings. DuckDB can spill
to the private run directory; large design and block matrices are memory-mapped.
The 11 GiB setting budgets DuckDB and workers, not an OS-enforced RSS ceiling.
Peak requirements and total elapsed time must be assessed on the actual Mac.

Do not assume the earlier one-to-two-day estimate. The timed five-G1-draw pilot
includes year fits and all requested G2 variants. G1 sensitivity bootstraps can
add substantial time and disk I/O. They have their own precision records.

OPTIONS (passed to RUN_TEST_G.command)

--stop-after inventory | g0 | g1 | point | all  (default all)
--engine /absolute/path/to/original/stockfish
--extra-pgn-root /absolute/path/to/additional/raw/months
--optional-manifest /absolute/path/to/reviewed_optional_inputs.json
--positions 500000..2000000
--max-g1-draws 50,100,...,500  (default 500; stopping rule can stop sooner)

OPTIONAL DATA

The arena and replay datasets are not guessed from similarly named files.
Their adapters require a manifest with source hashes and explicit provenance;
OPTIONAL_INPUT_CONTRACT.txt describes the required canonical columns. Without
these inputs, G3 is explicitly marked missing. Source inventory still searches
derived move stores and reports their coverage for the next binding step.

FROZEN CONTRACT AND VALIDATION

FROZEN_PROTOCOL.json and IMPLEMENTATION_NOTES.txt record the executable v2.1
contract and implementation choices before empirical execution. The entire
package is hashed. CODE_PROVENANCE.json records the code snapshot's Git commit
and SHA256; the run records these plus installed package versions and engine
configuration. No manuscript is modified automatically.

The bundled tests use synthetic data and a fake UCI engine. They establish
software invariants, not that your local inputs pass G0, calibration, stability,
or scientific decision thresholds. Those gates run on the Mac and can stop it.

Published checksum source, retrieved 2026-10-12:
https://database.lichess.org/standard/sha256sums.txt

VERSION 2.1.1 REPAIR

The certified 157-column panel does not contain api_source. Version 2.1.0
incorrectly queried it while writing the G1 analysis-game exclusion index.
Version 2.1.1 derives the pool label from the authenticated sample authority
and matching receipt, checks every required input column before projection,
and tests the binding using the exact schema in the certified sample report.
The new configuration starts input preparation again; the failed v2.1.0 run
is retained. Its engine and model stages had not started. The installed
venv_test_g_v210 environment is reused. Scientific specifications are unchanged.

Unexpected-error reports now include package code locations without messages,
query contents, data values or private tracebacks, making future errors diagnosable.
