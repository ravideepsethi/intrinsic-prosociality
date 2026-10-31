Mating Material: Position and Stage Checks v1.0.0

Save the ZIP and its SHA-256 sidecar to ~/Desktop/Lichess_Desktop.
Run from Terminal:

cd "$HOME/Desktop/Lichess_Desktop"
shasum -a 256 -c Mating_Material_Structure_v1_0_0.zip.sha256
unzip -oq Mating_Material_Structure_v1_0_0.zip
bash Mating_Material_Structure_v1_0_0/RUN_STRUCTURE.command

EXPECTED RUNTIME
10–20 minutes on the 12-core MacBook Pro with XT_Pro; allow 30 minutes
if the external drive is busy. This is a planning estimate, not a full-data
benchmark: the prior material-core run took 22 minutes for 26 models.
This package fits three joint regressions plus account-level summaries.
The tests take about 6–10 seconds locally. First-time environment installation,
if needed, adds approximately 1–3 minutes. The existing five-package environment
at ~/Desktop/Lichess_Desktop/MatingMaterial_Models_Env_v100 is reused.
Reports include actual total and per-stage runtime. The launcher prints measured
progress and remaining-stage estimates as partitions complete.

INPUTS AND OUTPUTS
Project: __PRIVATE_VALUE_1__
Input ready manifest:
  derived/replication/mating_material_first_run_v100_PRIVATE/
  aa7e95f275c18f43/MATERIAL_RESTRICTED_INPUTS_READY_PRIVATE.json
New private outputs:
  derived/replication/mating_material_structure_v100_PRIVATE/<run hash>/
Return files in ~/Desktop/Lichess_Desktop:
  MATERIAL_STRUCTURE_<run hash>_STRUCTURE_READY.zip
  MATERIAL_STRUCTURE_<run hash>_STRUCTURE_READY.zip.sha256
  MATERIAL_STRUCTURE_LATEST_PRIVATE.json
If the run stops, return the *_FAILED.zip and its sidecar instead.
Original panels, engine scores, rating reconstruction and profile snapshots are
read-only. No author-exclusion-ready manifest from the superseded pipeline is
required. There are no API calls or downloads during the production analysis.

SCOPE
1. Three original weightings for the within-chooser competitive-minus-clearly-
   worse contrast: F*L/(F+L), F*L/(F+L)^2, and equal chooser. Original estimator,
   joint chooser covariance, paired differences, activity-weight diagnostics,
   and raw granting denominators are recomputed from fresh account counts.
2. R11 column 1 with pooled clocks, reproduced as a numerical control against
   the already-reviewed material-core report. Its coefficient/SE check must
   pass before this package can report completion.
3. The same R11 specification plus the two log-clock terms interacted with the
   competitive-region indicator. This implements the manuscript's clock table.
   Its second region is ALL noncompetitive positions (< -100), as in R11:
   it includes the modestly-worse region. Logs are log(1 + seconds).
   Original missing indicators remain pooled. The reviewed material frame has
   zero invalid clocks; a change in that fact stops the run for review.
4. The exact R10 column-4 design behind Table app_stage_speed, with pooled
   five-knot rating gap and speed-specific stage profiles. The source was
   recovered from the original 141,169-byte R10 package; every recorded producer
   hash matches run 6bb9fb7c3d51. It is different from the smaller older R10
   package found in the repository. Its unchanged source is vendored here.
   The four observed formats are reported; absence of ultrabullet is never
   interpreted as an estimated zero effect. Additional joint tests are clearly
   labelled as supplementary tests across the observed formats.
5. Raw game-stage rows: ply 2, plies 3–10, by plies 4 and 10, after ply 10,
   and the eight roughly-equal bands. Every row uses the new author-excluded,
   material-restricted frame. Board-by-stage cells and speed composition are
   also supplied for the author's figure/table exports.

The stage-by-speed output includes the profile, late-game rebound, cumulative
decline, adjacent-format contrasts, full covariance and composition. Regression
uncertainty uses chooser-cluster CR0 multiplied by G/(G-1), including singleton
choosers in G; there is no additional (N-1)/(N-K) factor. Equal-weight models
use the original correction over state-varying accounts. No regression selects
accounts based on whether they granted.

OPTIMIZATION AND RESUME
Full SHA-256 authentication of the 24 input panels; narrow projections once
per month; integer-modulo partitions keep each chooser complete. Three models
share one union-design crossproduct pass and one chooser-covariance pass.
Up to 10 worker processes, one numerical thread each, bounded by the 11 GB
total budget (2 GB reserved for overhead). Defaults are 256 chooser partitions.
The program requires 16 GiB free on the output drive for caches and spill.

Every month, partition set and regression shard has a checksum-bound atomic
checkpoint. Rerun the same command after an interruption. Completed checkpoints
are verified and reused; altered inputs or caches stop the run. A fully completed
resume verifies private caches and report files and does not refit models.
Failed reports are explicitly labelled and cannot overwrite a completed result.

OPTIONAL COMMANDS
bash RUN_STRUCTURE.command --preflight-only
bash RUN_STRUCTURE.command --estimate-only
bash RUN_STRUCTURE.command --self-test
Resource overrides: --workers 1..10 --memory-gb 4..32 --shards 4..1024
Paths: --project-root PATH --results-dir PATH --manifest PATH
Python launcher override: MMR_PYTHON. Environment override: MMSTRUCTURE_ENV.

RETURN REPORT CONTENTS
tab_app_equalweights.csv, equalweight_paired_differences.csv,
equalweight_covariance_pp2.csv, tab_app_clocks.csv, tab_app_stage_speed.csv,
tab_app_state_ply.csv, speed_composition.csv, board_stage.csv,
stage_speed_joint_tests.csv, all_coefficients.csv, models/*.json,
CORE_REPRODUCTION.csv, STAGE_BEFORE_AFTER.csv, RESULTS.json,
INPUT_LINEAGE.json, RESOURCE_PLAN.json, and DOWNSTREAM_STATUS.csv.
Individual account rows stay in PRIVATE and are not included in the return ZIP.
The old/new stage comparison is descriptive: its old source predates both
material restriction and author exclusion. It is not a paired test of change.

The complete paper rerun remains unfinished. This package does not clear IV,
responsibility, countdown, tenure/arena/repeat, rating-gap/stakes, or remaining
Patron and persistence checks. DOWNSTREAM_STATUS.csv preserves that distinction.
