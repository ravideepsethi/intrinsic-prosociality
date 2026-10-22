RECEIPT COHORT TESTS v1.0.0

Runs the revised position and stake heterogeneity specification on the completed
2,682,329-exposure receipt cache, including 64,689 granted draws.

Put Receipt_Cohort_Tests_v1_0_0.zip in ~/Desktop/Lichess_Desktop, verify its
provided SHA-256, extract it, and run RUN_RECEIPT_COHORT_TESTS.command with:
  --workers 10 --memory-gb 10

Default project: /Volumes/XT_Pro/lichess_kindness
Default report destination: ~/Desktop/Lichess_Desktop
Override with --project-root /path or --desktop /path, or the launcher's
RCT_PROJECT_ROOT and RCT_DESKTOP_DIR environment variables.
An existing Python can be selected with RCT_PYTHON. The launcher first reuses
compatible existing environments. SciPy is not needed. Dependency setup can
use pip if no compatible environment exists; the analysis itself is offline.

The package authenticates Receipt Mechanisms v1.0.1 run 08b0e91f184f and reads
its already-built monthly dose files. It does not repeat the old preparation,
matching, API work or Stockfish evaluation. Do not delete that completed cache.

Sequence: source verification; sample/balance tables; joint model; terciles;
two dropped-interaction sensitivities; RD <=110; recipient FE; secondary IV.
Every model estimates both later kindness and reaching an opportunity.
Reports are refreshed after major stages. Interrupted runs resume completed
models automatically. No checkpoint requires user confirmation. --skip-iv is
an optional explicit choice; by default the secondary IV is attempted.

Expect roughly 20–60 minutes on the research Mac, with additional variation
from drive speed, FE convergence and memory pressure. This is a planning
estimate, not a measured production benchmark. Heartbeats print every 30s.

Upload RECEIPT_COHORT_TESTS_REPORT_<key>.zip when complete. Its SHA-256 sidecar
and the timestamped run log are saved beside it. Read READ_RESULTS.txt first.
Results remain exploratory mechanism diagnostics; no paper text is rewritten.

The large external-drive Parquets are not available to the package developer
here. Validation uses independent synthetic fixtures and direct algebraic
comparisons; synthetic coefficients are never empirical results.
