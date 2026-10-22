# KAC Repetition Sensitivity v1.0.2

Continues the reviewed v1.0.1 run `260b8b47b53ba645` from **December 2024**, preserving all 14 completed monthly histories through November. December's input matching passed, but the identity-conservation check failed at session annotation. The failure's root cause is not established. This revision replaces that large annotation step with bounded whole-account Arrow/NumPy processing and retains the checks.

## Run

Put the ZIP in `$HOME/Desktop/Lichess_Desktop`, verify the supplied SHA-256, extract into a fresh staging directory, and run:

```bash
bash RUN_REPETITION.command --worker-budget 10 --io-workers 3
```

The launcher uses an existing Lichess Python environment and runs synthetic tests first. It installs nothing. Keep `/Volumes/XT_Pro/lichess_kindness` mounted and retain the original companion, repetition v1.0.0/v1.0.1, and identity-diagnostic outputs. The checked symbolic references need those dependencies on later resumes too.

**No worker-capacity wait.** Ten is this job's worker budget, independent of other jobs. Duplicate/dependency locks remain. Monthly SQL uses at most four threads; Arrow annotation uses at most three processes, reduced with a smaller memory budget; regression passes use whole-account partitions and a memory-based process cap. Numerical-library threads are one per process. SQL and annotation phases run consecutively so their memory allocations do not overlap. The new version does not need the earlier no-wait wrapper.

## Reuse and progress

The runner authenticates all 24 frozen focal projections, the initial count/session carry, October 2023's buffer, and November 2023–November 2024 histories. This avoids all 531 prefix scans and all 14 completed monthly reconstructions. Source bindings, output hashes, receipt dependencies, the complete chooser set, and the four newly completed months' reviewed PASS reports must match. Unused prefix output data are not rehashed; their source bindings and configuration receipts are checked.

December 2024–October 2025 are built in a new v1.0.2 output directory. The raw filtering, predecessors, same-speed prior counts, and session-ID SQL are unchanged. Before annotation, the full monthly session input is checkpointed into 512 chooser partitions. An account belongs to one partition. The replacement computes positions, censoring, and session starts from the sorted account history, independently checks every session ID against the time gaps, and compares all original and written columns exactly. Global identity checks, the compact focal join, and the exact original-focal-column comparison remain active.

Successful annotation partitions are checkpointed individually. Rerunning this same ZIP reuses completed inputs and partitions inside an interrupted month, as well as completed months and regression checkpoints. Disposable expanded-history partitions are removed only after the final monthly checkpoint is committed. Existing sources and prior-run outputs are not modified or removed.

After December passes, `DECEMBER_HISTORY_VERIFIED` is printed and processing continues automatically through October 2025, then through both declared count scenarios. Heartbeats print every 40 seconds. Annotation shows partition progress; completed new months supply a live remaining-history estimate. That estimate excludes regression time.

**Provisional runtime: 4–7 hours**, including authentication, 11 remaining months, and regressions. The previous implementation took roughly 14–16 minutes per newly completed month. This version adds partition read/write checks; its full-data time is not yet measured, and other running jobs or external-drive throughput may lengthen it. Initial verification can take several minutes. At least 40 GiB free space is required.

## Outputs

New outputs: `/Volumes/XT_Pro/lichess_kindness/output/kac_repetition_sensitivity_v102/<id>`.

Only aggregate reports are exported to Desktop. Row-level account/game identifiers and diagnostic rows remain private on the Mac. Upload `KAC_REPETITION_SENSITIVITY_RESULT_<id>.zip` and its `.zip.sha256` when complete. If it stops, upload the new `PARTIAL` ZIP and sidecar. A passing synthetic test is not a production result; successful December checks provide the first production validation of this revision.

## Scientific scope

The ten repetition specifications, both count scenarios, sample, and estimation code are unchanged. One scenario counts valid-timestamp history; the other adds the possible June 2023 bullet start for the single affected chooser. No timestamp is imputed, no source is edited, and no additional focal account or opportunity is excluded. Each scenario has its own covariance calculation. The unchanged `ANALYSIS_AMENDMENT.md` states why these scenarios are not bounds over arbitrary source corruption. Final status remains `SENSITIVITY_COMPLETE_TIMESTAMP_NOT_RECOVERED`.

Completed receipt/IV hour fits, A2 work, and arena results are not rerun. Ordinary-loss ending metadata, platform incident-share adjustment, incident-adjusted clustering, and author-account exclusion remain separate open work.
