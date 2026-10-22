COMPARISON TOTAL-FIVE METADATA RECOVERY 1.0.0

Purpose
Continue the completed Patron migration / full-denominator comparison audit
144d4ae19d09. The audit found 9,654,945 games newly passing the all-time
pair-excluded five-decision count requirement. That is an upper bound, not
the final API target count and not an analytic sample size.

This release computes finite Score A, applies the rebuilt 90-day receipt
cooldown, recovers cached and legacy metadata, reconstructs factual
first-pair/previous-game chronology, and retrieves remaining game metadata.
The default command proceeds through the authorized API retrieval without
another prompt. No Patron/profile API calls are made in this release.

Prerequisites
- /Volumes/XT_Pro/lichess_kindness mounted, with its existing venv/bin/python.
- Completed migration 144d4ae19d09 and its original authenticated inputs.
- At least 150 GiB free initially for chronology outputs and temporary spill.
  This is a preflight floor, not a guaranteed peak disk bound. Once the target
  list is complete, a resumed invocation needs at least 20 GiB free instead.
- Existing numpy, pandas, pyarrow, duckdb, scipy and chess. No matplotlib.

Run after placing ZIP and SHA sidecar in ~/Desktop/Lichess_Desktop:

cd "$HOME/Desktop/Lichess_Desktop" && /bin/bash <<'BASH'
set -euo pipefail
shasum -a 256 -c Comparison_TotalFive_Recovery_v1_0_0.zip.sha256
recovery_dir="$(mktemp -d "${TMPDIR:-/tmp}/comparison_totalfive.XXXXXX")"
ditto -x -k Comparison_TotalFive_Recovery_v1_0_0.zip "$recovery_dir"
caffeinate -dimsu /bin/bash \
  "$recovery_dir/Comparison_TotalFive_Recovery_v1_0_0/RUN_RECOVERY.sh"
BASH

Rerun the same command after an interruption. Verified stages and committed
responses resume. Parent inputs and the August badge snapshot stay read-only.
To stop before HTTP requests, append --offline-only to RUN_RECOVERY.sh.
Rerun without that option to download the frozen list.

Progress and time
25%: scores validated against 4,096 deterministic R12 rows, plus direct
pair-exclusion/own-month-reference oracle checks in each of 16 donor shards.
50%: caches reconciled, chronology screened, exact API target list frozen.
75%: half of the requested IDs accounted for (including nonreturns).
100%: all target batches accounted for; returns reconciled with old evidence.
Percentages denote stages, not equal portions of elapsed time.

This is larger than the earlier 28-minute audit. Canonical chronology can
scan billions of rows and can take hours. The run prints source-row progress,
heartbeats every 30 seconds, and throughput-based ETAs. The API target count
is unknown until 50%; download time is learned from actual request speed.
At the historical planning rate of 29.05 games/second, one million requested
games would take about 9.6 hours before retries; this is not a promised rate.
The 9,654,945-game upper bound would take about 92 hours at that rate, before
the eligibility/cache reductions performed here. Interrupt/resume is safe.

Resource plan
Up to 10 allowed workers; the large score/chronology stages use two workers
to fit an 11 GiB planning budget. DuckDB spills to disk; a chronology memory
failure retries serially with 8 GiB. This is not an operating-system memory
cap. BLAS and Arrow per-process thread settings are one. API requests are
serial, up to 300 IDs/request, with server cooldowns and bounded retries.

What to return
Upload only COMPARISON_TOTALFIVE_RECOVERY_<key>_100.zip and its .sha256,
plus the RUN log if needed. If blocked, return the latest _BLOCKED.zip and
its .sha256 with the log. These reports contain aggregates, not row IDs.
Do not upload the PRIVATE directory, target lists, or response database.

Meaning of completion
100% completes this metadata-recovery package. It does not complete the
full comparison sample, global account-identity reconciliation, entry
outcome reconstruction, comparison fits, or Patron placebo. Nonreturns and
metadata conflicts remain explicit and may produce RECOVERY_COMPLETE_WITH_GAPS.
The private CONTINUATION.json records all verified inputs for those steps.

The retrieval gates cover the primary 90-day comparison entry/ordinary
placebo populations. Additional 0/30-day cooldown sensitivities may need
further metadata; this release does not claim to cover them.

A new Patron wave should be collected once the corrected receipt/comparison
account union is frozen, using a common new observation window. A current
profile pull cannot reconstruct the August 2026 badge or historical adoption.
