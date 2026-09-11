# Chooser-IV selection addendum v1.0.1

Version 1.0.1 corrects a report-staging error in v1.0.0. All four requested
specifications in the reported v1.0.0 attempt finished estimating, but report
assembly stopped because the already-created temporary directory was created a
second time without `exist_ok=True`. No estimator, sample, variable, control,
fixed effect, covariance calculation, or source authority changed. The corrected
runner uses a new configuration fingerprint and leaves the failed v1.0.0 private
directory untouched.

This small offline addendum uses the completed chooser-IV main rebuild. It does
not rebuild histories. It supplies the requested decomposition that was absent
from the returned report:

1. whether the historical chooser score predicts entry into the time-forfeit
   candidate set (`active_timeout OR passive_outoftime`); and
2. whether it predicts `active_timeout` after conditioning on membership in that
   candidate set.

It reruns the primary 7-day/floor-5 specification plus lag-30, floor-1, and
floor-10 sensitivities. Models use the same pregame controls, fixed effects,
current-IV scaling, and shared-account/date CR0 covariance as the completed main
IV comparison models. Before releasing results, the runner must reproduce all 16
existing active/passive estimates (four specifications by two outcomes by two
covariance choices) from the authenticated source report.

## Run

Put this package ZIP and SHA file in `~/Desktop/Lichess_Desktop`, then paste:

```bash
/bin/bash <<'BASH'
set -euo pipefail
cd "$HOME/Desktop/Lichess_Desktop"
/usr/bin/shasum -a 256 -c Chooser_IV_Selection_Addendum_v1_0_1.zip.sha256
/usr/bin/ditto -x -k Chooser_IV_Selection_Addendum_v1_0_1.zip .
export IV_SELECTION_PROJECT_ROOT="/Volumes/XT_Pro/lichess_kindness"
export IV_SELECTION_DESKTOP="$PWD"
/bin/bash "$PWD/Chooser_IV_Selection_Addendum_v1_0_1/RUN_ADDENDUM.command"
BASH
```

Expected runtime: **1–3 minutes** on the same work laptop; the reported v1.0.0
attempt reached report assembly in 34 seconds. The job reads and hashes a 174 MB
private Parquet, then reruns the same fixed-effect models. It makes zero network
requests and leaves both the completed chooser-IV source run and the failed
v1.0.0 staging directory unchanged.

At completion, upload the reported `CHOOSER_IV_SELECTION_ADDENDUM_REPORT_*.zip`
and matching `.sha256` file. This is a requested post-hoc selection diagnostic,
not a confirmatory test or causal-identification certification.
