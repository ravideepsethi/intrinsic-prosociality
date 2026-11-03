# v1.0.1

Fix the false `Comparison configuration changed` error during input authentication.
Comparison tests v1.1.0 hashed sorted JSON with its default spaces; rebuild v1.0.0
incorrectly used compact JSON when checking that previous configuration. The
configuration values could be identical and still fail the check.

The compatibility function now uses the exact original producer format. The
recorded expected SHA is unchanged. No previous configuration, input dataset,
checksum or receipt is edited. A changed setting is still rejected. The new
rebuild's own compact configuration hashes and statistical definitions are unchanged.

The evidence folder includes the original producer configuration reconstructed
from the verified comparison package. Its correct hash exactly reproduces
`2f1de91b97e493c25e1a8791eafcb35d2c8776225838416a71f31cc489bd9366`.
The incorrect compact hash was
`fbf5f1d1c46d45bf76d21e7acedbba11a14c94ee1af4dcc1c40325b36a39661c`.
The reconstruction does not claim to have read the work laptop's local file.

Four regression tests cover the recorded configuration, formatting differences,
genuine setting changes, and preservation of the new run's existing hash format.
The tests use DuckDB's current `to_arrow_table()` method to remove the deprecation
messages shown by v1.0.0. No estimation or sample-selection rule changed.

The reported failed invocation stopped inside authentication, before the new
private run directory or analysis checkpoints were created. There is no completed
IV rebuild from that invocation to preserve or repeat.
