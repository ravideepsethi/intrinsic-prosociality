# Crossing-audit source provenance

- `reference_price_model_v110.py` is the executed controlled model source returned in authenticated pool-main Wave 1. Its packaged SHA-256 is checked by the top-level manifest; the production baseline must reproduce all six returned local contrasts within `1e-7` percentage points before any restricted model is accepted.
- `kindness_price_elasticity_common_v102.py` is the public-repository exact two-way fixed-effect and chooser-clustered LPM utility inspected at repository commit `0dc981cbc6da157d365015a95f2b7157ecda4859` (`https://github.com/ravideepsethi/intrinsic-prosociality.git`).
- `reference_demand_v105_authority/` contains the exact archived v1.0.5 executed source, frozen contract, and amendment used to resolve the old Panel A specification. The adapter authenticates all four files against hard-coded SHA-256 values before fitting anything.
- `runner/crossing_audit.py` is the v1.0.1 pool-main adapter. Its displayed-gap model ports the archived `run_gap_schedule`/`run_adjacent_gap` and `stage_controls` specification: chooser and month fixed effects, chooser-clustered inference, current engine/clock/tournament/speed controls, and eight frozen ply bands. It adds a post-Wave-1 displayed-1500/high-RD diagnostic.

The historical API `provisional` boolean is not present in the certified analysis panel. The adapter therefore retains displayed rating 1500 as its own measured category and labels pre-game RD greater than 110 as a high-RD/provisional proxy. It does not infer provisional status from rating 1500.
