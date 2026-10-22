PATRON IV COVERAGE AUDIT 1.0.1

Purpose
Verify whether the existing August profile snapshot can support a Patron-outcome
analysis on the reviewed leniency-IV frames. This package produces coverage,
original design-sampling fractions, weight diagnostics, and timing checks.
It does not estimate a leniency–Patron association or certify a causal effect.

Correction in 1.0.1
The certified model frames store tc_base_s and tc_inc_s, not speed. Speed
is derived exactly as in R9b: base seconds + 40 times increment seconds,
with cuts at 180/480/1500. Codes 0/1/2/3 label bullet/blitz/rapid/classical.
All three source frames use this rule. Exact-cutoff values go in the higher
category. Missing/nonfinite/negative time controls stop with a clear error.
The 25% report now records frame schemas to make any subsequent source
mismatch diagnosable. No exposure or score definition changes.

Inputs and frozen samples
- R9 4028bf3e1857, completed certified leave-pair-out scores and original Phase 75
  comparisons. A later Phase 100 run is deliberately not selected automatically.
- R9b e7eb600d6199, author-clean expanded exposures with original selection flags.
- S0: 2,682,329 exposure rows, original 90-day spacing.
- First reference: 967,594 original first_recipient rows. This is not constructed
  by taking the first retained S0 row for each person.
- Unspaced: 7,432,709 exposure rows, including the existing S0 and first flags.
- F75: 11,057,763 comparison rows; O75: its 7,146,627 ordinary rows.
- Original chooser universe: 3,556,701 accounts. Acquisition includes all 326,468
  original any-kind accounts plus 979,404 original hash-selected controls.
- Certified snapshot: 1,305,872 planned, 1,305,683 returned, 4,896 Patrons.
  The 189 nonreturned accounts have missing Patron outcomes, not false outcomes.
- The explicit-ID dictionary from the completed comparison identity audit links
  recipient IDs to usernames; numeric IDs are never guessed from usernames.

Run on the Mac
Save the ZIP and its SHA256 file in ~/Desktop/Lichess_Desktop. Use the supplied
Terminal command to verify, extract into a new temporary directory, and run under
caffeinate. It uses /Volumes/XT_Pro/lichess_kindness/venv/bin/python, up to ten
DuckDB threads, a 9-GiB database budget within an 11-GiB planning envelope, and
one thread for numerical libraries. No dependency installation is attempted.
The reported 5–20 minute runtime is provisional: external-drive throughput and
spill can make it longer. Heartbeats appear every 30 seconds, with rough ETAs.

Only new audit files are written under:
  derived/replication/patron_iv_coverage_v100_PRIVATE/<configuration-prefix>
Upstream inputs are read and hashed. No API requests or engine analyses run.
Private account maps and projected frames stay on the Mac in that new directory.

Resuming
Run the same command again. Input hashes are rechecked. Completed stages are
reused only when their configuration and every output digest match. A failed
partial stage is rebuilt. Corrupt completed stages stop the run rather than being
silently accepted. A lock prevents simultaneous audit runs.

What to return
The *_100.zip aggregate report, its .zip.sha256 sidecar, and the run log appear
on the Desktop folder. If a required source fails authentication, return the
BLOCKED report and log. Do not return recipient_profiles_PRIVATE.parquet or the
private projected frames; those contain account or game identifiers.

Reading the results
READ_RESULTS.txt: frame-level coverage and interpretation.
coverage_summary.csv: exposure and unique-recipient coverage and Patron counts.
coverage_status.csv: observed, selected nonreturn, eligible not selected,
  zero sampling fraction, outside the original chooser universe, unresolved ID.
original_sampling_cells.csv: original reservoir and selected-control counts.
weight_diagnostics.csv: inverse design fractions, weight tails, and Kish effective
  units, separately at exposure and distinct-recipient levels. Kish counts only
  describe weight concentration; they are not clustering-adjusted sample sizes.
snapshot_lags.csv: observed snapshot dates relative to exposure game starts.
coverage_breakdowns.csv: coverage by month, speed, rating, original own-kind status,
  receipt/reach where available, and raw Score A deciles.
recipient_multiplicity.csv: how often recipients recur in each frame.
readiness.json: specific coverage/timing checks, not an overall causal approval.
provenance.json: input hashes, frozen configurations, and runtime versions.

Interpretation and next estimation decision
Design fraction = 1 for original any-kind accounts; selected controls / original
control reservoir for original never-kind accounts within each original cell.
The package exactly reproduces deterministic hash-ranked control membership.
Treating these fractions as sampling probabilities requires exchangeability of
the hash ranking with relevant outcomes within the original strata. These weights
do not fix nonresponse, zero support, selection into disconnect exposures, or IV
exclusion violations. Later pool/rematched own-kind labels must not replace the
original acquisition labels when calculating these fractions.

Returned disabled/TOS-flagged accounts remain in coverage; applying post-exposure
flag exclusions could itself change the target sample. No outcome-by-score table
or regression is produced at this stage. Repeated exposure rows repeat one Patron
snapshot and do not create independent account outcomes. A future model must
state its exposure-weighted versus account-weighted estimand and dependence rule.
A single snapshot also does not establish that Patron status began after the
leniency exposure. Positive association alone is not evidence of that transition.

Validation provided with package
Tests use synthetic data with known membership, six coverage statuses, unequal
sampling, repeated recipients, missing outcomes, and intentional corruptions.
They verify the score bridge, source IDs, explicit identity uniqueness, original
hash selection, null-vs-false outcomes, resume integrity, aggregate export, and
row-digest convention. Production data are not available in the build environment;
actual overlap and timing must be determined by running this audit on the Mac.

Files
code/audit_core.py       Project, join, and tabulate.
code/run_audit.py        Authenticate, checkpoint, resume, and export.
evidence/authority.json Frozen source configurations and report/file digests.
tests/test_audit.py      Synthetic scientific-contract checks.
VALIDATION.txt          Build-environment test results.
PACKAGE_MANIFEST.sha256 Every packaged member's SHA256 (except this manifest).
