# Pool-main Wave 2B2A — C7R linear-combination closure

This bounded addendum closes one reporting gap in the completed Wave 2B2A C7R
result. The frozen interaction model estimates the first-meeting fairness
gradient and the repeat-minus-first interaction, but its public serializer does
not expose the covariance needed to report the repeat-meeting gradient's exact
clustered standard error.

The addendum authenticates the existing 64 MB private model cache and the Wave
2B2A public result, then re-estimates only that unchanged interaction model. It
requires exact reproduction of all three returned coefficients and standard
errors before serializing the exposure covariance and the linear combination
`fair + fair_x_repeat`.

It does not retry or overwrite the standalone repeat-only model that failed to
converge under the frozen 2,000-iteration policy. It does not rebuild histories,
read the 41.5-million-row panel, access Patron/profile data, or use the network.

## Expected runtime

Approximately **2–6 minutes** on the configured Mac/XT_Pro setup. Most of the
time is the single 757,646-row absorbed model. The run is safe to repeat and
creates a timestamped aggregate-only result archive each time.

## Output

On success, `~/Desktop/Lichess_Desktop` receives:

- `POOL_MAIN_WAVE2B2A_C7R_LINEAR_COMBINATION_<UTC>.zip`
- the matching `.zip.sha256` sidecar

Upload both files for verification.
