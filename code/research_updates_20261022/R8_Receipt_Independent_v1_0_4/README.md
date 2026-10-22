# R8 Receipt Independent v1.0.4

Your returned v1.0.3 report passed its checksum, ZIP integrity check and all 77 report-file hashes. All 45 independent A1 coefficients and all 45 standard errors agree with the current original-R7 fit. The core S0 IV reproduction passed. Completed Patron and clock outputs were reused. The archived A1 coefficients still differ; item 2 remains open.

The experience construction then stopped at an invalid nesting assumption. The frozen historical producer counts every `fair` competitive opportunity, without requiring its separate `arm` indicator. The primary experience definition requires a competitive grant or claim. A recent competitive opportunity can therefore coexist with no prior qualifying grant/claim. The previous error reported no discrepancy count.

This update preserves the primary grant/claim definition, the frozen 90-day groups, the estimation rows and the score. It replaces the nesting assertion with independent source validation:

- Authenticate the original 24 all-source Stage07 panels and all 384 historical projection files through their pinned lineage.
- Reconstruct every exposure's frozen `fair_90` and `kind_90` count, on the original half-open window `[game start-97 days, game start-7 days)`, excluding both author accounts on both sides.
- Check focal role identities and event times; independently compare earliest competitive and grant/claim event times between the two source representations.
- Require every recent-opportunity/no-prior-grant-or-claim exposure to be explained by the event-definition difference. Recent grant/claim events must still be nested within the full grant/claim history.
- Write aggregate crosswalk, source census and actual discrepancy counts before any failure. If these checks fail, the experience fits remain blocked and the aggregate diagnostic is returned. Private account rows remain on your drive.

The complete v1.0.3 independent A1 audit is adopted only after its configuration, output hashes and dependencies verify. Its fit is not repeated when that checkpoint is available and valid. Patron and clock estimation is also reused after verification. New private state is under `derived/replication/r8_receipt_independent_v104_PRIVATE/`; existing R7, R8 and v1.0.3 state is read-only. Export verification now prints 35-second progress messages.

After history validation, the same separate-group IV fits, shared-account/date contrast covariance, conservative AR projection, pooled interacted-IV comparisons and frozen three-group 90-day analysis run. Reports explicitly describe the differing primary and secondary event scopes. No recent-history flag is used to fill the primary flag. No coefficient tolerance, input score or author rule is changed.

## Run

Put this ZIP and its SHA sidecar in `~/Desktop/Lichess_Desktop`. Keep the original `R8_Current_Data_v1_0_0.zip` there. Use the same XT_Pro research environment as the successful audit. Paste:

```bash
(
  set -euo pipefail
  cd "$HOME/Desktop/Lichess_Desktop"
  shasum -a 256 -c R8_Receipt_Independent_v1_0_4.zip.sha256
  r8_scope_unpack="$(mktemp -d "$HOME/Desktop/Lichess_Desktop/r8_receipt_scope.XXXXXX")"
  ditto -x -k R8_Receipt_Independent_v1_0_4.zip "$r8_scope_unpack"
  /bin/bash "$r8_scope_unpack/R8_Receipt_Independent_v1_0_4/RUN_RECEIPT_INDEPENDENT.command" --memory-gb 11
)
```

The launcher checks the package and runs 21 numerical/operational tests before production. It uses one process, one numerical-library thread and the existing Python environment. No installation, profile API, new game download or engine search is performed. `IV_PYTHON`, `IV_PROJECT_ROOT` and `IV_DESKTOP` overrides remain supported. Hashing the source files and verifying completed clock checkpoints can take several minutes on the external drive; remaining production runtime is unbenchmarked. Successful history and per-fit checkpoints are reusable.

Return `R8_RECEIPT_INDEPENDENT_REPORT_*.zip`, its `.sha256`, and the new `r8_receipt_independent_*.log`. Look for `A1_AUDIT_REUSED` and `HISTORY_SCOPE_VALIDATED`. Item 4 is complete only when `SUMMARY.json` says `item4: COMPLETE`; item 2 remains open on the archived A1 discrepancy. The winning-chances, per-ply replay and remaining paper-wide author checks remain open. “Never faced” describes the recorded November 2023–October 2025 grant/claim chronology; it makes no lifetime assertion.

The new source validation has been tested on synthetic data, including genuinely differing event scopes and failed-source diagnostics. It has not yet been run against your private Mac data. The returned v1.0.3 proof is recorded separately in `evidence/V103_RETURNED_AUDIT_PROOF.json`.
