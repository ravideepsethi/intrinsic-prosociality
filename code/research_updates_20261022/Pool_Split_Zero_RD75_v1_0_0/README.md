# Add both players RD <= 75 to the split-zero curves

Version 1.0.0. This is a new estimation package, not an already-estimated RD curve.

The earlier stable-rating result combined [-0.4, +0.4) in one payoff bin. The latest full-sample figure separates small losses, exact zero, and small gains. Their reference categories differ. Overlaying the earlier RD<=75 curve on the latest figure would therefore misstate the comparison around zero.

This runner estimates the RD<=75 sample using the split-zero specification and overlays it on the authenticated full-sample curve from run 2994ab11f07eaf09, reused unchanged. No K=11–12 sample restriction is imposed.

## Run

Put this ZIP and its SHA-256 sidecar in ~/Desktop/Lichess_Desktop and paste RUN_TERMINAL.txt into Terminal. Defaults: /Volumes/XT_Pro/lichess_kindness, 10 workers. Runtime is approximately 2–5 minutes with the existing authenticated sorted cache, based on the earlier 127-second full-sample run; rebuilding the cache takes longer. No Lichess API requests are made. The launcher reuses a suitable installed Python environment; it installs listed dependencies only if none is suitable.

## What it produces

- Central and expanded two-panel figures, PNG and vector PDF.
- The same figures without a slide title, suitable for inserting into an existing slide.
- Full-sample blue curve and both-players-RD<=75 orange dashed curve in each panel.
- New dots at payoff -0.2, 0, and +0.2 for both samples, with exact zero as each payoff curve's reference.
- Chooser-clustered confidence intervals, support counts, and the three near-zero contrasts within each sample.
- Raw descriptive curves in CSV, in addition to the displayed adjusted curves.

Reports and private work files go to output/pool_split_zero_rd75_v100/<identity>/ on XT_Pro. Figures are in report/figures/. A shareable POOL_SPLIT_ZERO_RD75_RESULTS_v100_<identity>.zip and checksum are copied to Lichess_Desktop. Upload those result files for interpretation. The success marker is POOL_SPLIT_ZERO_RD75_OK.

## Checks

24 monthly inputs are authenticated against the frozen 41,534,331-opportunity main sample. The RD<=75 sample must reproduce 11,114,912 estimation rows, 268,079 grants and 1,207,782 chooser clusters from the earlier stable-rating run. State-specific counts, the unchanged rating-gap coefficients/SEs, and the partition of the old payoff reference bin must also match. The prior full-sample curve and source files are not overwritten.

These are comparisons of curve shapes relative to each sample's own reference category, not differences in absolute kindness levels. The samples overlap; the package does not treat their estimates as independent or report a between-sample significance test.
