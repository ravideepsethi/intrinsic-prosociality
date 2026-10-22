# Unrestricted leave-pair-out chooser leniency

This reruns the IV with **all eligible recorded grant/claim decisions by the focal chooser against other players, both before and after the exposure**. There is no exposure-relative time restriction on the primary score. Every focal-pair decision is removed, including repeats before and after the focal game. The source is the existing authenticated 24-month donor inventory, not unlimited lifetime history or the separately expanding comparison sample. Ordinary games do not enter the grant-propensity denominator.

The new residualized score is mean(grant minus expected grant) over those decisions. The 500-cell author-clean cross-fitted state model, its monthly indexing, all historical count/expected-rate controls, fixed effects, outcome definitions and exposure rows remain fixed. Thus the chooser's donor history is unrestricted in time, while the nuisance model remains the previously fitted monthly model. This isolates the donor-eligibility change. Both author accounts remain excluded from exposure and donor/reference populations. The original minimum of five donor decisions remains; every originally supported primary row must still be supported.

## What runs

1. Receipt IV on all original S0 exposures and strict neutral material exposures (`-4 < M < 4`), each with X0 and X0 plus ENV/availability controls: four new models.
2. Ordinary-ending later kindness and reach placebo on frozen O50, plus focal entry/disconnection/timeout tests on frozen F50, with the same two control specifications: four new models. Balance and joint balance accompany the fits.
3. Before-only, after-only and full-time receipt IV on exactly the same S0 subset having at least five decisions on each side: six sensitivity models. Before means donor event time strictly before focal game start. After means strictly after the focal cached anchor. Events between start and anchor, including endpoint ties, remain in the unrestricted primary score but not either timing diagnostic. These sensitivities select on future history support; report their sample size and do not present them as new primary estimates or proof against feedback.
4. Receipt minus ordinary-ending reduced-form contrasts with common account/date covariance, for both control sets.

S0 has 2,682,329 rows, F50 has 7,371,688, and O50 has 4,764,089. O50 is checked as an exact F50 subset, including frozen outcomes. New primary receipt models must match the reviewed receipt row hashes; comparison models must match the reviewed placebo/entry row hashes. No new exposure cohort or follow-up window is assembled. Newly supported exposures would be a separate extension.

## Completed objects reused

- R7 `7ab926c925a4` authenticates exact inputs, controls and inference producers.
- Cutoff/material receipt run `ef68f2376383` supplies validated material flags, 24-hour benchmark scores and completed receipt results.
- Placebo/entry run `15a254020647` supplies 24-hour comparison scores, completed diagnostics, and the already completed ordinary-material coverage assessment.
- Prior result tables are copied to `*_reference` tables without repeating their estimation. The donor scan performed here computes new unrestricted and timing scores. S0 and F50 share the scan; O50 requires no separate donor scan.

The material-restricted **receipt** IV runs. The material-restricted **ordinary placebo** remains pending because the reviewed cache audit found no directly usable final-position Parquet. That audit is reused, not repeated. This package does not replay raw moves or acquire missing games. Zero API requests and zero Stockfish searches.

## Estimator audit and interpretation

This is a precisely pair-excluded instrument estimated with the same R7 single-score 2SLS and shared-account-OR-date CR0 as the prior results. It is **not labeled UJIVE**. The state-reference producer excludes both focal player folds in both roles, so the focal pair does not enter its reference fit. Cross-fitting the state model is separate from regression residualization.

The new scorer independently checks direct row masks against aggregate subtraction, including all-time counts, grants, distinct counterparts and residual scores. These checks exclude direct reuse of focal-pair choices in the instrument. They do not certify that regression residualization eliminates all many-control own-observation bias. No UJIVE correction or full donor-score uncertainty correction has been implemented. Inference treats the generated score and nuisance model as fixed and retains the original reference SD, so effects are comparable to the archived estimates. Intervals are nominal and diagnostics follow earlier results.

Future choices may respond to the focal decision through ratings, subsequent opponents or behavior. Pair exclusion does not eliminate these channels or broader network dependence. The updated placebo and entry/balance tests help assess the new specification but cannot establish the exclusion restriction. The source time is the archived event/last-move timestamp, not a newly observed button-click time.

## Run and resume

Save the package ZIP and SHA256 sidecar in `~/Desktop/Lichess_Desktop`. The supplied command verifies the ZIP, extracts to a unique `mktemp` directory using `ditto`, checks all packaged files, runs the offline self-tests and launches the analysis with the existing project Python. `caffeinate` prevents idle sleep during the analysis. Nothing is installed on the Mac.

Project: `/Volumes/XT_Pro/lichess_kindness`. Python: `/Volumes/XT_Pro/lichess_kindness/venv/bin/python`.

Expected runtime: **35–75 minutes**, a planning estimate. The previous cached placebo/entry job took about 20 minutes; this job adds receipt fits and timing sensitivities. Heartbeats every 30 seconds report stage throughput, estimated RAM reservations, ETA to the next checkpoint and ETA to finish. There are 25/50/75/100 percent report ZIPs with sidecars. Large numerical fits run alone where required; the 10-worker setting is a ceiling, with a total estimated 11 GiB budget and one BLAS thread per worker. Reservations are estimates, not an OS-enforced memory limit.

Private checkpoints: `<project>/derived/replication/iv_leave_pair_out_v100_PRIVATE/<configuration>/`. Package bytes and authenticated input lineage determine the configuration. Completed stages validate dependencies and hashes before reuse. Rerunning the same command resumes them. Changed input signatures fail closed; completed upstream runs remain read-only. No manuscript is changed.

Return the **`IV_LEAVE_PAIR_OUT_REPORT_<configuration>_100.zip` and its `.zip.sha256` sidecar**. If it stops, return the log and latest checkpoint. The completed status is `CORE_COMPLETE_ORDINARY_MATERIAL_PENDING`, which means this package's core job is finished while the separately documented ordinary-material task remains unresolved. Reports contain aggregate results only; row-level scores and influences remain private on XT_Pro.

Environment overrides: `IV_PROJECT_ROOT`, `IV_DESKTOP`, `IV_PYTHON`. Runner options: `--workers 1` to `10`, `--memory-gb 9.5` to `11`, `--r7-root`, `--cutoff-root`, `--placebo-root`.

The delivered package is tested using synthetic data and authenticated code/report contracts. Empirical estimates require running it on the research Mac; no production result is claimed in the package.
