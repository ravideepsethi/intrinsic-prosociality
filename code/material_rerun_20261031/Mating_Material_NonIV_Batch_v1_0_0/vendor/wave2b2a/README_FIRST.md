# Pool-main reanalysis — Wave 2B2A v1.0.1

This bundle runs the exact recovered Campaign-1 C7X v1.0.1 and C7R v1.0.2
producer families on the certified pool/non-adjacent 24-month main sample.

It reuses—but fully authenticates—the Wave 2B1 pair histories. It does not
rebuild them and does not access Patron/profile data. C7X private checkpoints
and C7R model caches remain on `XT_Pro`; only aggregate outputs are returned.

The former 2% sample support/outcome cells are preserved as historical
diagnostics. They are not equality gates because the selected panel changed.
On the selected panel, C7X retained its primary as not estimable because the
benefactor arm has 125 rows, below the frozen 1,000-per-arm threshold. Version
1.0.1 preserves that disposition and fixes the outer launcher so it no longer
blocks the scientifically separate C7R first/repeat-meeting family. C7R's
relationship attempts remain exploratory and are explicitly labeled with the
failed parent-C7X support gate; no selected-panel C7X reproduction claim is
made.

## Expected runtime

Approximately **15–30 minutes when resuming the completed v1.0.0 C7X stage**,
or **20–40 minutes from a fresh state**, on the configured Mac/XT_Pro setup.
The stages are checkpointed and safe to resume by rerunning the same command.

## Resources

- 8 analysis threads by default (never more than the producer's frozen limit)
- 12 GB DuckDB memory limit
- at least 70 GiB free on the Wave 2B2A private-state volume
- zero network requests during analysis when an existing compatible Python
  environment is reused

## Output

On success, the launcher creates both:

- `POOL_MAIN_REANALYSIS_WAVE2B2A_RESULTS_<UTC>.zip`
- the matching `.zip.sha256` sidecar

in `~/Desktop/Lichess_Desktop`.

Wave 2B2B (the frequent-dyad sensitivity, remaining Campaign
C1/C6/C9/C12/C13, and family-wide reconciliation) and Wave 3 (Patron and
manuscript-wide finalization) remain after this bundle.
