# Source provenance

The authority is the completed targeted repair result, not the incomplete parent audit.

- Repaired result: `MECHANISM_RD_AUDIT_REPAIRED_RESULT_20260926T192953066013Z.zip`.
- SHA256: `8bcda7730c8ea1ee994bd6f3884092046dca6c718f7fb8dc6171b3c30d2fb505`.
- Status: `RD_AUDIT_COMPLETE_AFTER_TARGETED_REPAIR`; zero fit/comparison failures.
- The repair refitted only roughly-equal, capped `strength_framing/fold0`. This package refits nothing.
- Original calculator/design package: `Mechanism_Separation_v1_0_0.zip`, SHA256 `5a9d030a5847eda7d1b2d8d32f26de952766b84a4b5d5d440ec872722af5e2a0`.

The 21 aggregate capped fit JSON files are bundled under `authority/fits`. Source monthly-cache hashes, completed model comparisons and repaired status accompany them. They contain coefficients and aggregate fit diagnostics, not chooser identifiers. The two original uncapped policy tables are retained only for historical comparison; no runtime code reads them.

## Unmodified audited calculation files

- `vendor/common.py`: `df8b25d7197dabcaaf04534a00d2c930bd41450891b2c40e513b39a10d6dbb0c` (byte-identical to original).
- `vendor/design.py`: `ea5eb3d9eda3513521a4bc03f35a2622c3f0c07f1bde7a286b8566b04f37c5d5` (byte-identical to original).

New code projects and authenticates the existing Parquets, reuses these transformations, adds capped forecasts, the stated pre-only baseline/calendar amendments, calendar-gapped block power, temporal diagnostics, and an evidence-gated actual-target adapter. The actual cohort producer, exact fractional rating/display recovery, entry analysis, and prediction-parameter bootstrap are not implemented by this narrow pass.

The old review's request for a targeted fold repair is superseded by the completed repair above. No other unfinished source work is represented as complete.
