Patron_TotalFive_Migration_v1_0_1

STARTUP REPAIR 1.0.1 — 2026-10-16
This release has distinct v1_0_1 archive and folder names. Download both
the v1_0_1 ZIP and its matching checksum together. It removes the unused
matplotlib dependency from the launcher and runtime version inventory. No plots
are produced by this migration. The observed 1.0.0 failure occurred before any
analysis stage; source data and existing upstream results were not changed.
The analysis definition and statistical producers are unchanged. The repaired
package has its own manifest/configuration hash. No dependency installation is
needed for this missing-matplotlib error.

This package implements the Patron receipt-sample part of the October 16 memo
and audits a newly identified upstream dependency for the comparison rebuild.
It DOES NOT rebuild the ordinary/entry comparison populations or produce the
corrected Patron placebo. A 100% report means the listed tasks completed, not
that every task in the memo is finished. Read REPORT_METHODS.txt.

Save this ZIP and its SHA256 sidecar to ~/Desktop/Lichess_Desktop. Use the
provided Terminal command. The existing research environment and completed
R12/R9/Patron coverage caches are required. No dependencies are installed.

Output stages:
25%: original badge acquisition reconstructed on the new primary roster;
     old/new row and recipient overlap, coverage, weights and timestamps.
50%: old Patron fits and new R12 receipt estimate reproduced; new primary
     Patron FS/RF/2SLS, unweighted and prior-chooser fits, selection diagnostics.
75%: corrected first-observed-candidate sensitivity; B and same-row A fits
     on before-supported primary rows. Main A population stays unchanged.
100%: full 61,158,951-game comparison acquisition denominator audited for
      newly count-supported games and missing/conflicting cached metadata.

The default continues through all stages. --primary-only stops at the 50%
checkpoint. Rerun without that option to finish, reusing verified work.
Primary estimate planning range: 10–30 minutes. Full run: 1–6 hours, potentially
longer if missing first-reference chronology is expensive. These are forecasts,
not production benchmarks. Long stages print 30-second heartbeats.
10-worker ceiling, 11-GiB planning budget, one BLAS thread. Fits are serial;
donor/history workers are bounded. Keep at least 40 GiB free on XT_Pro.

Inputs are read-only. New private outputs stay under:
derived/replication/patron_totalfive_migration_v100_PRIVATE/<configuration>
Only aggregate JSON/CSV/methods files go into the returned ZIP. Account names,
row identities, candidate ledgers and influence vectors stay on XT_Pro.

Return PATRON_TOTALFIVE_<configuration>_100.zip, its .zip.sha256, and the log.
If using --primary-only, return the 050 report. If interrupted, return the
latest checkpoint and log. No manuscript is changed automatically.
