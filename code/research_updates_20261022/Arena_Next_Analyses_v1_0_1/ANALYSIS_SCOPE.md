# Arena next analyses 1.0.1

Version 1.0.1 imports the five completed v1.0.0 analysis families from the
authenticated returned report and runs only the remaining receipt/IV family.
Each imported family retains its original receipt, contract and result bytes.
The new completion receipt records the import explicitly. The table below
describes the analyses in the combined report, including the inherited work.
See REPAIR_NOTE.md for the historical configuration-hash compatibility repair.

This runner continues the completed arena v1.0.2 analysis. It uses the same
1,892,835 screened arena opportunities, including 730,717 competitive
opportunities and 12,829 competitive kind draws. The 41,534,331-row pool main
sample remains the main sample.

Read RUN_STATUS.json and each family's support and numerical audit before using
any estimates. Completion means the listed families were attempted and their
outputs checked. An unsupported estimate is missing, not a zero effect. This
runner does not certify causal identification or completion of the entire paper.

## What runs

| Family | Producer reused | New work |
|---|---|---|
| Core | Stage 08 | Tables 1–9 and associated analytical figure data, including original hashed-game and temporal split-half definitions. |
| Panel robustness | Stage 09 | Payoff density/heaping, cutoff and subgroup models, exact-zero sensitivity, and economic magnitudes. |
| Four flagged curves | Rating-gap nonparametric closure | Rebuild original derived variables from authenticated arena inputs; rebase the active year-two month categories, scale the design, and check rank. The short-game curve is unsupported if its full specification exceeds available within-chooser variation. |
| Episodes | Stage 10c B1 | Five-fold chooser cross-fitting and all 4,999 conditional randomizations, with the original 6-hour, 24-hour and 7-day kernels, fixed seed, batch boundaries, and Holm adjustment. |
| Patron | Wave 3A matching and Wave 3B1 estimation | Rebuild arena chooser summaries and up-to-1:3 matching, then run the original 34 chooser models and four corrected-date sensitivities where supported. Report fixed-snapshot coverage and binary missing-outcome bounds. |
| Receipt / chooser-history IV | Stage 10c A1 functions and Chooser IV Main Rebuild | Construct new first arena exposure recipients; scan canonical all-game history for first observed pairs and pregame volume; reuse all-source, leave-all-pair-out historical score and IV engines, first-stage diagnostics, balance tests, weak-instrument intervals and reach models. |

## Repository reuse and changes

Source files are byte-for-byte copies from `ravideepsethi/intrinsic-prosociality`
at commit `bf3b2bf9ffedba8f53c61e3e1b55bb457e58a129`. REPOSITORY_SOURCES.json
records their Git blob IDs, repository paths and SHA-256 hashes.

The adapters call the original statistical producers with arena inputs and
independently counted arena margins. They do not impersonate the old all-source
certificate, assert a fictitious clean Git working tree, or reuse pool estimates
as arena estimates. No original source files or earlier results are overwritten.

Core regression inputs are scaled and expressed in an independent basis before
calling the original fit functions. Full-design null-space checks suppress
nonidentifiable individual coefficients. Original covariance conventions are
retained. Contrasts that require a suppressed coefficient remain unavailable.
Patron fits have an additional full-design estimability and outcome-variation
audit. A loss of support is recorded instead of being presented as a zero effect.

This is a new subsample analysis. Any inherited `confirmatory` or `primary`
labels identify a source model family; they are not a claim of new preregistration.

## Receipt and IV definitions

The first competitive screened arena exposure is ranked for each recipient
before the grant-versus-claim, realtime, first-pair, valid-clock and complete
90-day follow-up restrictions. A rejected first exposure is not replaced by a
later arena event. Pair history uses the original canonical all-game universe;
"first observed pair" does not establish that the players never met elsewhere.

For later outcomes, first select the earliest competitive opportunity against a
different opponent whose game started after the exposure's lastMoveAt proxy,
within 90 days, across all original sources. Then classify its format.

The primary arena outcome is the joint event that this next opportunity is in
the screened arena sample and the recipient grants a kind draw. It is zero if
the next opportunity is elsewhere or no opportunity is reached during complete
follow-up. Arena reach is estimated separately. A next opportunity in the pool
is never skipped to manufacture an arena-to-arena transition. The conditional
arena-choice estimate selects on post-exposure reach and is labelled accordingly.
The any-source later-outcome sensitivity uses the same arena exposure cohort.

Historical chooser propensity training and expanding nuisance references retain
all 47,587,020 original opportunities, the original 7/30-day lags, focal-pair
exclusion, history thresholds, folds and score definitions. The original
first-stage, reduced-form, same-sample OLS, 2SLS and Anderson–Rubin procedures
are reused. Weak or unidentified instruments do not establish a null effect.

The direct receipt models reuse the original A1 exposure-cell ATT weighting
and chooser-clustered estimator. Their risk set and outcomes are the explicitly
documented arena adaptation above; they are not a claim to reproduce every A1
specification exactly. The original requirement to retain at least 90% of grant
recipients in cells with at least five grants and twenty claims is enforced. If
that gate fails, the direct receipt family is marked unsupported without
loosening its cells. IV support checks are independent of this A1 gate.

## Patron timing and missingness

Match selection uses arena behavior before profile outcomes or availability are
read. The fixed August 2026 snapshot is reused. New matching can select accounts
whose August profile was never queried. They remain unknown; they are not coded
as non-Patrons. Available-profile estimates and full-target binary bounds are
reported separately. The bounds are not confidence intervals or bounds on the
fully controlled regressions. No present-day profile queries are mixed into the
August outcome snapshot.

## Remaining scope and interpretation

The ordinary-game comparison dataset available to the original IV runner is a
pool dataset. It is not substituted for an arena ordinary-game control group.
Building that arena comparison remains separate work. The full Stage10 A3
reentry models and later dynamics families, opening-familiarity analyses, and
lower-priority Patron rematching/opportunity extensions are also outside this
runner. Those require further authenticated inputs or separate adapters.

The arena screen remains backward observed nonadjacency, as in the pool main
sample. It does not certify literal game-end-to-next-start rematches. lastMoveAt
is an event-time proxy, not a verified resolution time. The historical claim/draw
interface, arena point/streak costs, and a tournament identifier fixed effect are
not audited here. Arena participation and active resolution remain selected.

The tournament suppression evidence should be interpreted alongside these
checks. Arena-only estimates by themselves do not identify suppression; the
arena–pool comparisons already completed in v1.0.2 provide that contrast.

## Resources, integrity and resuming

The runner never downloads games, calls Stockfish, queries profiles, or changes
the pool main sample. It verifies the pinned v1.0.2 public receipts and all 24
monthly private checksums. Missing disconnected clocks remain in the source
sample; original model-specific finite-row rules apply later. UTC is explicit.

The receipt/IV family scans 852 canonical chronology files containing about
7.76 billion rows. It runs after the other families, with a checkpoint per file.
It may be the slowest stage; production runtime is not benchmarked. Historical
opportunity projection files have content hashes. The canonical chronology
inherits the original manifest/metadata and pre/post stat checks; this is not a
claim of original full-content hashes for all historical game files.

The default is a 4 GB DuckDB buffer, at most eight database threads, four
chronology workers and three score-history workers. Other memory-heavy stages
run one at a time. DuckDB's buffer cap does not include Python/Arrow arrays.
Ten workers/threads is an absolute ceiling. At least 12 GiB free disk is required
as an initial allowance; actual spill use depends on the data.

Rerun the same downloaded command to resume the same configuration. Completed
family outputs and the original internal checkpoints are verified before reuse.
Incomplete work is retained for diagnosis. An aggregate-only report ZIP and its
checksum are refreshed on the Desktop after every family and on ordinary errors.
Send the final ZIP and checksum back for interpretation. Preserve the terminal
log if any family fails. The private caches stay on your drive.
