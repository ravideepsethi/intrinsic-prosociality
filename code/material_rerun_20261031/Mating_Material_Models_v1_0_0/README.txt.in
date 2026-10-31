MATING MATERIAL — MAIN AND CONTINUOUS MODELS v1.0.0

Save the ZIP in ~/Desktop/Lichess_Desktop, then paste:

cd "$HOME/Desktop/Lichess_Desktop" &&
unzip -n -q "Mating_Material_Models_v1_0_0.zip" &&
bash "Mating_Material_Models_v1_0_0/RUN_MODELS.command"

EXPECTED RUNTIME
45–120 minutes on the documented 12-core Mac, provisionally:
  authenticate and project the new inputs: 5–15 minutes;
  three main regression specifications: 5–25 minutes;
  23 continuous-evaluation/material specifications: 30–80 minutes.
The first isolated model-environment setup adds about 1–3 minutes.
Estimates are planning ranges, not measurements of a production model run.
The returned first-stage log covered 10 minutes 53 seconds, after initial input
hashing; that was an input audit/build and does not benchmark these regressions.
Progress and measured per-stage ETAs are printed during execution. Repeating
the exact command resumes verified projections and chooser-partition moments.

WHAT THIS PACKAGE RUNS
1. R11's original three models: the main equation with region-specific stage
   and rating-gap terms and x_g controls; the same model without x_g; and the
   comparison with a pooled rating-gap profile. Chooser, speed and month fixed
   effects, all original missing-data indicators and original covariance rules.
2. All 23 original Continuous Merit specifications, including the primary
   competitive/after-ply-ten spline, full-range spline, alternative knots,
   clock/rating sensitivities, material profiles and joint evaluation/material
   models. The original specification-specific samples and knots are unchanged.
3. Paper-facing Table 2 uses standardized position rates and adjacent
   differences, calculated with their joint covariance. Raw position beta
   coefficients remain separate and explicitly labelled.
4. Extra +300 minus +100 and -100 minus -300 centipawn contrasts are calculated
   from their fitted covariance, not by combining marginal standard errors.
   All coefficients, coefficient orderings and covariance matrices are included.
5. Figure profile data are exported for the author's re-export. No image renderer
   or plotting dependency is needed to run this package.

OUTPUTS
~/Desktop/Lichess_Desktop/MATERIAL_MODELS_<runid>_MODELS_READY.zip
and the same filename with .sha256 appended. Return both files.

The ZIP contains report/tab_main.csv, report/tab_app_main_spec.csv,
report/tab_app_merit_continuous.csv, report/fig_merit_profiles.csv, the complete
aggregate model outputs in report/r11 and report/merit, a coverage ledger,
executed source, input lineage, and run.log. It contains no game-level or
account-level data. Estimates use percentage-point outcomes unless labelled.
Non-estimable terms are explicitly marked; they are not silently treated as zero.

This is the NEXT STAGE, not the whole-paper rerun. It does not yet run the
region-interacted clock extension, stage-by-speed extension, equal-account
weighting, responsibility, countdown, tenure/arena/repeat, stakes, persistence,
Patron, matched receipt, IV, entry/placebo, or receipt-kind/Patron analyses.
report/DOWNSTREAM_STATUS.csv retains all of those outstanding families.
No new statistical estimates are available until this runs on the Mac data.
Do not overwrite the manuscript using the earlier unrefreshed model estimates.

THE VERIFIED FIRST STAGE
Parent run: aa7e95f275c18f43d9ad95af523b9b0d769704ddebf4aea4d3655a2e1b07ef5d
Both returned archives and all 34 manifest-listed files in each were checked.
All 52 audit/reconciliation checks passed.

Main input frame:
  opportunities                    41,513,719
  recorded draws/grants               570,422
  chooser accounts                  3,223,436
  accounts with at least one grant     276,627
  competitive opportunities        15,186,844
  competitive grants                  419,794
  competitive grant rate             2.7641951152 percent
  clearly-worse opportunities      22,664,787
  clearly-worse grants                106,556
  clearly-worse grant rate            0.4701389870 percent
  excluded opportunities              20,570
  newly recognised grants                 332
  newly granting accounts                 146
  accounts losing all opportunities       735
  total original-price rating points forgone 6,881,716.431561

Broader all-source input: 47,561,517 opportunities; 669,913 grants.
Its 25,458 excluded rows and 411 additional grants will also affect rebuilt
IV decision histories and reference populations in the subsequent IV package.
Recorded chooser wins failing the new material rule: ZERO in both datasets.
All dropped rows were in the competitive region; clearly-worse counts unchanged.
The 65 historical main chooser-loss records (75 all-source) retain their old
non-grant coding and loss flag. They are not identified as claimed wins; their
original anomaly is not resolved by the material audit. Models preserve their
original eligibility rules. This stage uses the original whole-main-frame fits.

INPUT AND STORAGE CONTRACT
The default is the exact reviewed ready manifest, not a search for old READYs:
__PRIVATE_VALUE_1__/derived/replication/
  mating_material_first_run_v100_PRIVATE/aa7e95f275c18f43/
  MATERIAL_RESTRICTED_INPUTS_READY_PRIVATE.json

It is bound to the completed first-stage receipt and returned results, rule,
author exclusions, original price layer, all 24 monthly counts in both families,
and the historical-loss policy. The 24 main files are individually SHA256
checked and independently counted before estimation. The all-source files are
not scanned for this main-model stage. No old author-only READY file is needed.

New private model caches are written under:
__PRIVATE_VALUE_1__/derived/replication/
  mating_material_models_v100_PRIVATE/<content-derived-run-id>/

Defaults: at most 10 worker processes, one BLAS/OpenMP thread each, 11 GB
planning budget, 256 chooser-complete partitions. The largest partition sizes
determine the number of simultaneous estimation workers; the memory budget is
a planning cap, not an OS-enforced hard limit. Allow at least 24 GiB free space.
Source hashing uses two threads; projection uses at most four processes.
All observations for one chooser stay together across all months, preserving
the original chooser-cluster covariance. Both passes are separately checkpointed.
Fresh input hashes are calculated once per launch; projection workers check
the authenticated file signatures before and after reading each source.

The existing first-stage environment is untouched. This model stage uses:
~/Desktop/Lichess_Desktop/MatingMaterial_Models_Env_v100
Python 3.11–3.13; NumPy 2.3.5, pandas 2.3.3, PyArrow 20.0.0,
DuckDB 1.3.2 and SciPy 1.16.3. Only first-time environment installation needs
network access. Production analysis makes no network requests.

Optional commands (same launcher, add an argument):
  --estimate-only    Print the planning runtime range without reading data.
  --self-test        Run synthetic numerical/integration checks only.
  --preflight-only   Verify the ready inputs and independent counts; fit nothing.
  --workers 6        Reduce maximum simultaneous processes.
  --memory-gb 8     Lower the memory planning budget.
  --shards 512      Use smaller chooser partitions; creates a new run identity.
  --manifest PATH   Explicitly locate the same reviewed material-ready manifest.

CODE AND VALIDATION
The 10 files under vendor/ are byte-for-byte copies of the reviewed R11 and
Continuous Merit producers from the author-exclusion repair package. Their
source hashes are in authority/UPSTREAM_FILES.json. The adapter rebinds fixed
historical census expectations to independently counted new-input totals.
It does not replace the design, coefficient solver or covariance estimator.
Synthetic checks compare against dense fixed-effect OLS, chooser-cluster
covariance, explicit counterfactual predictions and numerical influence
derivatives; test all 23 continuous designs; check input-policy failures;
and exercise projection, partition, report, corruption and resume paths.
TEST_RESULTS.txt records the actual development checks. Synthetic test datasets
are not production estimates. BUILD_INFO.json records the pipeline commit.

No Stockfish runs, rating replay, profile queries, replacement matching or
metadata acquisition are performed. Original panels, factual chronology,
profiles and completed first-stage outputs remain intact.
