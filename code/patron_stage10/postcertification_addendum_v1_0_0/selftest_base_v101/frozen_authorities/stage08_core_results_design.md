# Stage 08 core paper-results design

## Authority and numbering

The current takeover handoff controls the stage numbering. Stage 07 is the
certified joined 24-month analysis panel. The next canonical producer is:

```text
code/08_make_core_paper_results.py
```

The older memo's proposed `08_assemble_analysis_panel.py` is obsolete and must
not be created as a competing stage.

## Input boundary

Stage 08 reads only the certified Stage 07 panel rooted at:

```text
/Volumes/XT_Pro/lichess_kindness/derived/replication/analysis_panel_24m_sf100k
```

It authenticates the frozen Stage 07 summary, producer, selected monthly
Parquet hashes, exact schemas, row counts, and outcome totals before analysis.

## Included results

The panel alone is sufficient for:

- main sample, month, speed, and rating-tier descriptives;
- Table 1: five-bin fairness gradient;
- Table 2: chooser-FE matched-window zero-threshold contrasts;
- Table 3: local piecewise price slopes and threshold term;
- Table 4: flexible linear, cubic, and quantile-bin win-premium controls;
- Table 5: placebo cutoffs around the rating reference;
- Table 6: fairness by favorable/costly price decomposition;
- Table 7: favorable price by capped engine evaluation;
- Table 8: out-of-sample prior-kindness heterogeneity;
- Table 9 and Appendix Tables A1/A2: hashed and temporal split-half persistence;
- analytical plot data for Figures 2, 3, A1, A2, A3, and A4; and
- Appendix Table A12 fine evaluation-bin support.

For the new 24-month sample, prior type is classified in the first 12 months
(November 2023 through October 2024) and evaluated in the second 12 months
(November 2024 through October 2025). The temporal split uses the same boundary.
The random split uses a stable MD5 parity of `game_id`; it does not use Python's
process-randomized `hash()`.

## Definitions frozen in this producer

- favorable/non-loss draw: `chooser_draw_payoff_v2 >= 0`;
- strict-positive draw: retained as a diagnostic, not the paper binary;
- fair/competitive: disconnected-player evaluation `>= -100` cp;
- clearly worse: disconnected-player evaluation `<= -300` cp;
- excluded middle: `-299` through `-101` cp;
- chooser fixed effect and cluster authority: `chooser_username_norm`, mapped
  losslessly to a run-local integer code; and
- Table 7 evaluation: clipped to `[-100, +600]` cp within the fair sample and
  scaled in hundreds of centipawns.

## Explicitly excluded dependencies

The following are not inferred from Stage 07 and are not silently reused from
old 10k outputs:

- patron and profile analyses (main Tables 10-15, Figure 4, Tables A3/A18);
- opening familiarity (Table A19);
- abandonment/reentry (Table A21);
- true post-sample holdouts (old Tables A14-A17 require redesign);
- the November 2025 color-breakpoint diagnostic (Table A5); and
- historical win-update convention validation (Table A9).

Those belong in a later extensions stage after their own inputs are located,
authenticated, and frozen.

## Workflow

1. Run a November 2023 pilot into a versioned pilot root.
2. Inspect all analytical tables, coefficients, row counts, FE identification,
   and output hashes.
3. Commit and push the audited producer plus its script-hash manifest entry.
4. Run all 24 months from the committed producer.
5. Commit small certification/provenance only; never commit Parquet or caches.
