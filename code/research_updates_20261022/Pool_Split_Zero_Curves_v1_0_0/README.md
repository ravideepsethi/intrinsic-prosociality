# Pool split-zero curves v1.0.0

Re-estimate the slide curves with separate draw-payoff bins at −0.2, exact
zero, and +0.2, using the same full competitive sample, fixed effects and
controls as the prior figures. No RD restriction or narrow-K restriction.

Save the ZIP and its SHA-256 sidecar in `~/Desktop/Lichess_Desktop`, and paste
RUN_TERMINAL.txt into a fresh Terminal. This accepts up to 10 workers and
reuses compatible Python environments and the authenticated sorted cache.

Estimated runtime: roughly 5–15 minutes on the prior-run machine with its
existing cache; rebuilding the sorted cache will take longer. This is an
estimate, not a benchmark of the new production run. The package has been
tested on synthetic data; it has not been run on the private production panel
in this workspace. Budget several GB for the new private shards and use
`LICHESS_SPLIT_ZERO_WORKERS=4` if memory is tight. Numerical libraries use one
thread per worker; monthly authentication uses two hash workers by default.

The prior JSON-list reader error is covered by a test: sample-count evidence
is read as a list while object-only readers remain strict elsewhere.

## Outputs

- `figures/split_zero_central.png` and `.pdf`: central two-panel figure.
- `figures/split_zero_expanded.png` and `.pdf`: expanded two-panel figure.
- Corresponding `_plot_only` versions for slides with an existing title.
- `near_zero_bins.csv`: counts, coefficients and support for the three central bins.
- `near_zero_contrasts.csv`: joint-covariance contrasts and adjusted p-values.
- `curves.csv`, `plotted_data.csv`, `bin_definitions.csv`: exact tabulated results.
- `ZERO_AUDIT.json`, `SAMPLE_REPLICATION.json`, `GAP_REPLICATION.json`: checks.
- `SUMMARY.md`, `METHODS.md`, sample lineage, code and hash manifests.

Return ZIP and its sidecar are written to `~/Desktop/Lichess_Desktop`:

`POOL_SPLIT_ZERO_CURVES_RESULTS_v100_<identity>.zip`

Private work and full reports are saved under:

`/Volumes/XT_Pro/lichess_kindness/output/pool_split_zero_curves_v100/<identity>/`

**Payoff normalization changes:** the old curve was relative to the pooled
[−0.4,+0.4) bin; the new payoff curve is relative to exact zero. The zero dot
is therefore a reference marker. Its separate near-zero contrasts remain
estimated with uncertainty. The rating-gap normalization is unchanged.

Rerun the same Terminal command to resume a failed run with the same settings.
Completed moment and covariance checkpoints are authenticated and reused.
Do not edit code inside an authenticated package to bypass a check.
