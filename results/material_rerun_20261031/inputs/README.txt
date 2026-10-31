Mating-Material First Run v1.0.2
Historical-outcome gate repair, 28 October 2026; same material rule and statistical scope.

WHAT THIS EXECUTABLE DOES

This is the mandatory audit and input-reconstruction stage. It does NOT rerun
the paper's regression, IV, persistence or Patron models. It produces the new
certified inputs those producers need, exact accounting, descriptive rates,
position-by-stage figure data and original-price totals. Its completion status
is INPUTS_READY_NOT_FULL_PAPER_RERUN, never "paper complete".

1. Authenticate the 24 main Parquets and 24 all-source SF100k Parquets. If the
   standalone author-excluded manifest exists, use its 41,534,289 main rows.
   If absent, use the checksum-pinned original pool panels (41,534,331 rows),
   apply the exact two-account exclusion during the audit, and require exactly
   42 removed rows and the same 41,534,289-row baseline. All-source inputs have
   47,587,020 rows before author exclusion. No source hashes are weakened.
2. Run the exact side-specific scalachess predicate on both universes, using
   cached counts and final FENs. Drop failing decisions. All remaining draws
   are grants. Reconcile the main sample against the manuscript's old census.
3. Halt if a recorded chooser win fails the rule, stored outcome flags disagree
   with PGN/API results, sources fail authentication, duplicate games occur, or
   the main sample is not an identical subset of the broader universe. The 65
   historical main-sample chooser losses remain non-grants, with their existing
   loss flags, and are reported separately; they are not relabeled as claims.
   Their monthly counts must match the prior audit, and all-source loss counts
   must match the 75 in its certified receipt. Save identifying exception rows
   locally in PRIVATE; no candidate panel is certified after a failed gate.
4. Write NEW full-width monthly Parquets. Recode BOTH outcome_kind_draw and
   its kind_draw alias. Set chooser_has_mating_material=true and the obsolete
   timeout_draw_no_mating_material flag=false on retained rows. Preserve every
   other column, row order, all original files, and the original price layer.
5. Emit aggregate CSVs, a private input manifest, and a compact return ZIP.

DEFAULT MAC COMMAND

Save the ZIP into ~/Desktop/Lichess_Desktop, then paste:

  cd "$HOME/Desktop/Lichess_Desktop" &&
  unzip -n -q "Mating_Material_First_Run_v1_0_2.zip" &&
  bash "Mating_Material_First_Run_v1_0_2/RUN_MATERIAL.command"

If already extracted there, run the last command with the full Desktop path.
Expected first-run runtime: approximately 15-40 minutes for the audit and
input rebuild; the observed full main audit took 3.5 minutes on the Mac, but the remaining
stages are estimates, not measured full-data benchmarks.
The existing MatingMaterial_Env_v100 environment is reused unchanged.
Dependencies are installed only if their exact pinned versions are absent.

The launcher finds Python 3.11–3.13, creates an isolated environment under
~/Desktop/Lichess_Desktop/MatingMaterial_Env_v100, installs three pinned binary
packages once, runs the included tests, and starts the production audit/build.
It never changes another research environment. It does not use sudo. To choose
an interpreter, prefix the command with MMR_PYTHON=/absolute/path/to/python3.13.

Defaults:
  Project: __PRIVATE_VALUE_1__
  Results: ~/Desktop/Lichess_Desktop
  Workers: up to 10 (also capped by CPU count and memory budget)
  Planning memory: 11 GiB; one array-library thread per worker
  Arrow batch: 65,536 rows

Useful alternatives (append to the same command):
  --audit-only              Audits and descriptions, no full-width copies
  --preflight-only          Verify sources/schema/disk, then stop
  --verify-all-fens         Parse every FEN independently; slower
  --workers 4              Lower disk/CPU concurrency; same numerical results
  --memory-gb 8            Lower memory allowance; same material rule
  --project-root /path      Relocated project; paths in the manifest are rebound
  --results-dir /path       Destination for return ZIPs
  --self-test               Synthetic tests only; no mounted drive needed

You can also use the installed Python directly:
  "$HOME/Desktop/Lichess_Desktop/MatingMaterial_Env_v100/bin/python" run.py --help

OUTPUTS

New private files:
  <project>/derived/replication/mating_material_first_run_v100_PRIVATE/<run-id>/
    PRIVATE/audit/{main,all_source}/<month>/decisions.parquet
    PRIVATE/audit/.../exceptions_PRIVATE.parquet   [only when needed]
    PRIVATE/panels/{main,all_source}/month=<month>/analysis_panel.parquet
    MATERIAL_RESTRICTED_INPUTS_READY_PRIVATE.json
    INPUTS_PRIVATE.json, CONFIG_PRIVATE.json, _SUCCESS.json, run.log

Return these two files from the results directory:
  MATERIAL_FIRST_RUN_<run-id>_INPUTS_READY.zip
  MATERIAL_FIRST_RUN_<run-id>_INPUTS_READY.zip.sha256

The ZIP contains aggregate reports, code/tests, build identity and run.log.
Private masks, accounts, game IDs, FENs and raw data stay on the Mac.
With --audit-only the suffix is AUDIT; on failure it is FAILED.

Reports:
  RESULTS.json                         Counts and explicitly limited completion
  RECONCILIATION.csv                    Six handoff checks plus baseline checks
  sample_flow_by_month.csv              Source, author, dropped, added, retained
  old_new_rule_crosstab.csv             Old/new material by recorded result
  dropped_by_case_outcome_state.csv     Three cases × result × board state
  tab_sample.csv                       Updated main counts/rates/accounts
  tab_app_state_ply_cells.csv           All state-by-stage cells
  fig_desert_ply.csv                    Figure 2 export data
  tab_app_stage_raw.csv                 Ply 2, plies 3–10, after ply 10
  tab_app_composition.csv               Descriptive composition
  tab_intro_rating_totals.csv           Original kappa totals/mean/median
  CACHE_POLICY.json                    Safe reuse versus required reconstruction
  DOWNSTREAM_RERUN_REQUIRED.csv         Every model family still to be rerun

RESTART AND DISK USE

Repeat the SAME command after interruption. Each month has a content-hashed
receipt. Completed outputs are checksum-verified and reused; an unfinished
month is recomputed. Worker count and batch size can change without creating
a different semantic run. Corrupt completed files cause a stop, not silent
reuse. A single-run OS lock prevents two terminals writing the same run.

The program checks free space for approximately 1.5 times the compressed input
size plus 12 GiB of masks/spill allowance. This is conservative. It reads only
the audit columns first; full-width copies begin after both audit gates pass.
DuckDB aggregations run separately from the worker pool and can spill to disk.
Actual RAM use also includes Arrow and OS page caches; the planning budget is
not an OS-enforced ceiling. Allow roughly 15-40 minutes on the Mac with the
external SSD available; actual progress and approximate stage ETA use measured
throughput. Heavy disk contention or --verify-all-fens can take longer.

MODEL HANDOFF / AVOID STALE RESULTS

Use mmrerun.consume.authenticated_paths(manifest, "main" or "all_source") in
the next producer adapters. The contract intentionally differs from the old
READY files. It does not impersonate an old sample or update old authorities.
Never feed these replacement data into a launcher that still insists on the
old counts, outcomes, score hashes, or completed model caches.

Both donor histories and reference cells must be rebuilt, along with scores,
support, exposure selection/spacing, behavioral history controls and later
outcomes. A dropped first later choice can change which later game is first.
Reclassified draws also change receipt and grant histories. Filtering the old
regression files is insufficient, even when most row IDs remain unchanged.

Preserve factual all-game chronology, predecessor/first-meeting facts, rating
states, engine outputs, cached API metadata, the Patron acquisition design and
profile snapshot. A dropped decision remains an actual game in chronology.
The five-second audit and historical September audience sample are not rerun.
This package makes no engine calls, metadata downloads, profile queries or
rating replay, and it never swaps in the candidate counterfactual-cost upgrade.

VALIDATION / SOURCES

See TEST_RESULTS.txt and BENCHMARK.json for checks actually run before release.
Synthetic tests cover the nine required boards, both colors, promoted bishops,
opponent-material exceptions, randomized scalar/vector parity, full-width
preservation, aliases, both source families, author filtering, exact accounting,
result-conflict stops, checksum failures, audit-only mode and resumed completion.
The synthetic kernel benchmark is not a full-data or Mac benchmark.

sources/ contains the exact scalachess files at 3050826 and e8133fa and their
license/provenance. BUILD_INFO.json identifies the upstream repo commit and
this standalone producer's commit. SHA256SUMS.txt pins all distributed files.
The production records are on your Mac and were not executed in this build.

V1.0.1 INPUT-DISCOVERY REPAIR (RETAINED IN V1.0.2)

The v1.0.0 launch failure occurred before production auditing or panel writes.
The later author-exclusion repair producers filter the certified original pool
panels directly; they do not require the earlier standalone READY manifest.
V1.0.1 supports that source layout. The audit fuses author exclusion with material
classification, avoiding an extra full-width copy and a separate preparation run.
An explicitly supplied --main-manifest must exist and pass validation; an existing
but invalid default manifest also stops the run rather than invoking the fallback.
Every original input still passes its pinned SHA-256 and schema checks, and the
post-author main sample must reproduce all eight published baseline counts.
New tests cover both source routes, exact author removal in both roles, identical
retained panels, changed metadata/bytes, missing sources, and a complete fallback run.

V1.0.2 HISTORICAL-OUTCOME GATE REPAIR

The returned run c418c69d222f967f authenticated all 48 source files and audited
all 41,534,331 original main rows in about 3.5 minutes. It removed the 42 author
rows and reproduced 41,534,289 old opportunities and 570,090 old grants. The
required zero-win count was zero. Material restriction dropped 20,570 draws
and added 332 grants, yielding provisional main counts of 41,513,719 rows and
570,422 grants. The all-source audit, account census and panel build did not run.

The stop came from an extra gate treating any recorded chooser loss as a new
material/result conflict. There are 65 such records in the existing main sample,
already reported in COST_UPGRADE_8e0de916d036_100, matching the new audit month
by month. The original Stage07 receipt reports 75 in the all-source sample.
V1.0.2 retains their original non-grant coding for this material-only rerun,
preserves their existing recorded results and loss flags, and checks those
counts against the pinned prior evidence. It does not claim to explain their
original chooser-role anomaly, and never reports them as observed win claims.
Historical downstream grant-or-claim eligibility rules must remain in place.

The zero-win test, all source hashes, author exclusion, baseline checks, and
PGN/API/flag consistency gates remain strict. New outputs include recorded
outcome counts and retained chooser-loss counts by month and board state; the
private input contract carries this policy. No option disables these checks.
V1.0.2 uses a new run identity; the failed run is preserved and its main audit
is repeated, about 3.5 minutes at the throughput already observed. Existing
research inputs are not overwritten. Use the same command to resume v1.0.2.
