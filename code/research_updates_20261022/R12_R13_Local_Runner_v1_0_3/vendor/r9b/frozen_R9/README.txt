R9 — Certified leave-pair-out rerun, v1.0.0
=========================================

This is the offline execution package, not an empirical results report.
Production data are on the research Mac. The package has synthetic numerical
tests; production certification occurs only when Step 0 passes on that Mac.

RUN

Put this ZIP and its SHA256 sidecar in ~/Desktop/Lichess_Desktop. Verify the
sidecar, extract into a fresh temporary directory with ditto, and run
RUN_R9.command. The supplied chat command does all three. Expected first-run
time: roughly 1–3 hours; missing ENV pair/month histories and external-drive
throughput can extend this. The log updates estimates every 30 seconds during
long stages. Repeating the same command resumes completed stages.

Default project: /Volumes/XT_Pro/lichess_kindness
Default Python: project/venv/bin/python
Default output folder: ~/Desktop/Lichess_Desktop
Options: --workers 1..10, --memory-gb 10.5..11, --skip-learning,
--baseline-root PATH, --comparison-root PATH.
IV_PROJECT_ROOT, IV_PYTHON and IV_DESKTOP can change the corresponding defaults.

The launcher verifies every package hash, runs self-tests, prevents idle sleep,
and records stdout/stderr in R9_CERTIFIED_analyze_TIMESTAMP_PID.log. It installs
nothing and uses the existing numpy, pyarrow, duckdb and pandas environment.
No API requests, downloads, Stockfish searches, or manuscript edits occur.

IDENTITY AND REPLAY

The prior run 2a4e617b40bc is read-only. A separate configuration digest binds
the R9 code manifest, donor reference, exact comparison frame and definitions.
New private checkpoints live in:
derived/replication/r9_certified_leave_pair_out_v100_PRIVATE/CONFIG_PREFIX

The reviewed R7, cutoff/material, placebo/entry, and leave-pair-out report
manifests are authenticated. All 14 prior models are rerun using unchanged
vendored code and saved inputs. Entire nested numerical results are compared:
absolute tolerance 2e-10 plus relative tolerance 1e-8; strings, schema and flags
must match exactly. Both S0 and F50 saved score tables must also reproduce;
integer fields are exact, floating score tolerance is absolute 2e-10.

To avoid rereading 384 source donor partitions, the saved-score replay and
provisional A/B/C calculations share a single decoded donor pass. No R9 model
is fitted until all baseline model and score checks have passed. Failure stops
the run; no looser tolerance or alternate cohort is tried automatically.

FRAMES

S0 full: 2,682,329. S0 neutral: 2,452,682, using the exact saved material flags.
The existing neutral definition is strict abs(material)<4; endpoints are not
reclassified in this rerun. Missing material is never imputed neutral.

Default comparison frames are the reviewed Phase 075 configuration
9e46500403a4: F75 11,057,763 and O75 7,146,627. This preserves its availability
and quarantine decisions. If completed, compatible Phase 100 frame stages
exist at startup, use those instead, even if unrelated Phase 100 model fitting
is still running. A live download journal or an incomplete frame is not a
completed analysis frame. The selected snapshot is fixed for the whole run.
Multiple completed Phase 100 roots require --comparison-root to disambiguate.
An incompatible completed Phase 100 frame causes an explicit stop, not silent
fallback to Phase 75.

The comparison source donor/author/panel lineage must match the baseline. Every
F50/O50 game must remain in the larger frame with its frozen relevant inputs
and outcomes unchanged. These joins use game identity, because Phase 75/100
rebind row IDs. All analysis frames exclude both author accounts in both roles.

DONORS, STATE ADJUSTMENT, AND CONTROLS

There are 24 monthly source partitions in each of 16 chooser shards: 384 files,
47,587,020 source rows before eligibility/author filters. The same arm-eligible
j-as-chooser decisions as the old run are used, with both author roles removed.
Every decision j made against i is removed, before or after the focal game.
Other-role decisions cannot enter j's chooser history.

A: all donor times, with at least five donors.
B: donor decision time strictly before focal game's start, no 24-hour buffer.
C: donor decision time strictly after focal anchor.

Each donor's UTC event month selects the unchanged lag-7 monthly state model,
with the same two focal players' fold exclusions and existing EB cell shrinkage.
The reference is reindexed, not reestimated. If that month/fold-pair model is
unavailable, use the latest usable model at or before the donor month. If none
exists, use the earliest usable model. In particular, this accommodates the
first month's empty expanding reference and games resolving beyond the final
archive month. No zero prediction or missing-donor deletion is used. The report
lists fallback mappings and counts, both by recipient fold in the source and
as affected donor-query links in each analysis frame. Donor-month mismatch
shares use donor-query links as their denominator, not unique source games.

Each variant has its own three rebuilt history controls: log1p(number of
donors), log1p(distinct remaining counterparts), mean donor expected grant rate.
log1p is the frozen X0 count transform. All other X0 and ENV-indicator terms,
recipient histories, FE labels, outcomes, rows, and covariance are unchanged.
Before/after distinct-counterpart counts use first/last eligible event times,
with the focal pair removed from counts and breadth.

F50 scores are replayed from the larger frame by exact game/role/time identity;
they do not create duplicate donor queries. O reuses its verified subset of F.
Its prospective outcomes stay those of the authenticated ordinary frame; F
does not need prospective Y to fit its three entry labels.

ENV CONTROLS

Phase 75 raw frames do not include the primary ENV rates. R9 finds the existing
rates through O50's original prepared cache (F50 moved when later outcomes were
attached). Existing rates are reused exactly. Only missing opponent/pair/month
requests are computed from the unchanged author-clean canonical game chronology,
using the frozen 90-day pre-month window, pair subtraction, numerator matching,
and availability coding. This can require a separate large chronology scan; it
is not another donor-score scan. All output joins preserve frame identities.

ESTIMATION AND OUTPUTS

ENV-indicator is primary; X0 accompanies every model block. Figure 5 is the
explicitly requested primary-only figure. Both controls are also provided for
the implied-bias row and learning split. There are 16 core model fits, two
calibration fits, four paired-contrast jobs, and up to eight optional split
fits plus four split-contrast jobs. A triggered adoption rule adds four fits.

A_receipt: A on S0 full/neutral, FS, RF(Y/reached), 2SLS Wald/AR 95%, F, partial R2.
B_before: B on identical full S0 rows, with its own controls. Unsupported donor
  rows are counted and make this full-row specification unsupported, never
  silently dropped. The saved old supported histories should imply B support.
C_timing: A/B/C on the same rows with >=5 before and >=5 after donors.
C_paired_timing: after minus before RF(Y/reached) and 2SLS with actual stacked
  shared-account-OR-date covariance, its covariance matrix, SE and p-value.
D_placebo: ordinary RF(Y/reached), 95% and 90% intervals.
D_receipt_minus_placebo: S0 minus ordinary RF(Y/reached), joint covariance.
E_entry: analysis_entry_90, recipient_disconnect_main, active_timeout, base
  rates and share of base per common SD and fixed 0.0594.
F_balance / F_joint_balance: seven T30 traits and joint test on S0 full/neutral,
  entry and ordinary frames. Holm across the seven traits within each model.
G_implied_bias: 15 standardized traits fitted jointly with FE and the seven
  X0-NH controls; predict the trait part only and project it on the score under
  the outer model. Both Y-hat and D-hat, beside observed RF/FS. SE includes
  uncertainty in fitted trait coefficients. This is calibration, not identified
  causal bias. ENV terms are not included in the X0-NH training regression.
H_figure5: 20 equal-count bins of primary residual score, residual receipt mean
  and 95% CR0 intervals, plus linear FS. Bins differ in size by at most one;
  ties use stable row-ID order. Intervals condition on fitted residuals/bins.
I_score_diagnostics: correlation with the old focal-month score on S0 and the
  larger F frame, donor mean/median, link-weighted and mean-row shares after the
  anchor, different-month shares, fallback counts, and timing support counts.

All FS/RF/entry/placebo and corresponding contrasts use the ONE residual Score A
SD in full S0 under ENV-indicator. Native probability-per-unit coefficients stay
in coefficient/standard_error. *_pp fields use that common SD. Additional
*_pp_per_fixed_0_0594 columns implement the exact requested 0.0594 bridge;
*_pp_per_legacy_SD also retain the original exact 0.059411690344000595 scale.
2SLS, Wald/AR IV intervals and paired IV differences remain pp per receipt.
Balance is trait SD per each model's native residual-score SD.

Covariance remains shared-account-OR-date CR0, conditional on generated scores.
No small-sample adjustment, ridge, PSD repair, or score-correlation substitute
is introduced. Baseline numerical code is untouched. R9's model input projects
one Parquet column at a time into one owned Fortran FWL buffer and uses the
same solver/standardization. Worker reservations prevent launching oversized
jobs together. Up to ten workers are used when the 11 GiB planning budget
allows; larger frame models normally run alone. BLAS/Arrow threads are one.

LEARNING AND ADOPTION

Full chronology: whether the recipient previously had an author-clean chooser
fair/competitive event in the entire observed 24-month stream, strictly before
the focal start. This uses the certified historical fair flag, not an inferred
grant/claim outcome. This is observed-panel history, not lifetime experience.
The secondary 90-day flag is the frozen fair_90>0 with its original R7 cutoff.
Each definition fits Model A in both strata, with experienced-minus-unexperienced
RF and IV contrasts under joint shared covariance. A positive coefficient in
one subgroup alone is not a formal difference test or proof of transmission.
Use --skip-learning only to omit this explicitly optional block.

If abs(primary 2SLS - 0.281) exceeds its new SE/3, adoption is put on hold.
The run then fits the same-row 2x2 combination of old/new score and old/new
history controls, in both control sets, and reports separate changes and their
interaction. This diagnoses which implementation changes account for the shift.
It does not automatically approve adoption. Even without a trigger, the package
does not change the manuscript. Certification covers inputs and reproduction,
not exclusion, monotonicity, post-focal feedback, or causal identification.

RETURN

The desktop folder receives 025/050/075/100 aggregate report ZIPs and SHA256
sidecars. Return the 100 ZIP, its .sha256 sidecar and R9_CERTIFIED_analyze_*.log.
If the run stops, return the log and latest checkpoint instead. The ZIP contains
JSON, CSV and Parquet aggregates, a manifest, definitions, reproduction checks,
adoption diagnostic, and no game/account/row-level or influence-function files.
Private projected inputs, influence Parquets and resumable stages stay on the
project drive. Do not delete them if you want to resume or audit the run.
