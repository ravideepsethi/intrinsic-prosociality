# Raw and adjusted kindness surfaces — current pool sample

This package computes two matched surfaces on the frozen **41,534,331-opportunity**
November 2023–October 2025 sample, with **570,091 kind draws**. Production data remain
on your Mac; this delivery contains code and frozen sample authority, not new estimates.

## Run

Run `RUN_SURFACES.command` from your usual conda/Python Terminal. Defaults:

- Project: `/Volumes/XT_Pro/lichess_kindness`
- Input: `derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE`
- Transfer: `$HOME/Desktop/Lichess_Desktop`
- Ten parallel monthly workers; two input-hash workers; one BLAS thread per worker.

```bash
/usr/bin/caffeinate -dimsu /bin/bash /path/to/Pool_Desert_Payoff_Surfaces_v1_0_0/RUN_SURFACES.command
```

The launcher verifies its package, checks Python 3.10+, and uses NumPy, PyArrow and
Matplotlib from your active environment when compatible. If needed, it creates a
separate `surface_python_v100` environment under the transfer directory and installs
`requirements.txt`. It runs seven short synthetic checks before scanning production data.

Plan for roughly **5–20 minutes**, an unbenchmarked estimate that depends on external-drive
speed and the Mac. Ten workers may use several GB of RAM. If memory is tight, prefix the
command with `LICHESS_SURFACE_WORKERS=4`. Input data are read only. Completed month
checkpoints are reused after an interruption; rerun the same command.

The runner authenticates all 24 monthly Parquets against the bundled current sample
report and local success receipt, including file SHA-256, schema and row counts.
It independently reconciles all four published row/outcome counts during scanning.
It will not silently substitute the older 47.6-million-row sample, drop rows with missing
controls, skip a month, or declare a partial run complete.

## What is plotted

| Axis | Field | Interpretation |
|---|---|---|
| X | `chooser_draw_payoff_v2` | Signed draw payoff r_G, in rating points. Negative means the chooser loses rating from a draw; positive means a gain. |
| Y | `engine_eval_cp_disconnected` | Opponent's board evaluation in centipawns. Positive means the disconnected opponent is ahead. This is the desert proxy. |
| Z | `outcome_kind_draw` | Kind-draw rate in percent. |

The X axis is the signed reference-dependent draw payoff, not the always-positive
forgone win premium. Labels say **draw payoff** because adjustment does not make it
an externally assigned causal price.

**Raw:** observed kind draws divided by opportunities within each desert × payoff cell.

**Adjusted:** a linear probability model with a separate intercept for every joint
desert × payoff cell, plus additive spline controls for:

- `ply_count`;
- `chooser_pre_rd_v2` and `disconnected_pre_rd_v2`;
- `chooser_pre_sigma_v2` and `disconnected_pre_sigma_v2`.

The controls use piecewise-linear splines in log(1 + ply), log(RD/50), and
log(volatility/0.06). Knots in original units are:

| Control | Knots |
|---|---|
| Ply | 2, 5, 10, 20, 40, 80, 160 |
| Each player's RD | 50, 75, 110, 150, 200, 300 |
| Each player's volatility | .03, .04, .05, .06, .07, .08, .10 |

The joint surface and controls are estimated together using exact sufficient statistics
and Frisch–Waugh–Lovell absorption. The adjusted cell rate is:

`raw rate + 100 × (overall mean control basis − cell mean control basis) × beta`.

Thus each cell is standardized to the **same full-sample empirical control distribution**;
it is not set to zero controls or to an arbitrary representative person. The opportunity-
weighted adjusted mean equals the raw overall mean. The code verifies that identity.
This common additive model does not allow control effects to differ by surface cell.

The two surfaces use **identical rows and support**, not different complete-case samples.
There are no additional rating-gap, month, speed or chooser fixed effects. No standard
errors or significance claims are supplied. This is a descriptive covariate-adjusted
surface, not a within-chooser analysis or a causal identification strategy.

Adjusted LPM levels can be negative or exceed 100%. They are retained without clipping
and counted in the diagnostics. Such levels are model-adjusted estimates, not empirical
frequencies. Near-collinear control directions are handled with a scaled eigensolve;
if they make standardized cell levels unidentified, the run stops with an explanation.

## Display and support

The default figure uses payoff **−6 to +6** in **0.4-point bins** and evaluation
**−600 to +600 cp** in **50-cp bins**. Zero is a cell edge; exact-zero payoffs enter the
nonnegative bin. The figure does not estimate a discontinuity at zero.

All finite rows enter the model. Observations outside the display range, including
extreme engine values, have their own underflow/overflow cells. They are never piled
onto displayed edge cells. Interior bins include the lower edge and exclude the upper
edge, except the final upper edge is included.

Only cells with at least **500 opportunities**, observed in at least **6 months**, are
displayed. The criterion never depends on the number of kind draws. A well-populated
zero-kindness cell remains visible. These are count criteria, not a certification of
overlap in the entire covariate distribution.

Both surfaces have the same camera, color scale and vertical range. No smoothing is
applied. Triangular facets connect adjacent cell centers only where all four neighboring
cells pass support. Holes are left blank; isolated supported cells appear in the heatmap.
The heatmap is often easier to read on a presentation slide than a rotated surface.

For a wider view, run the same launcher with:

```bash
--payoff-min -20 --payoff-max 20 --payoff-step 1
```

These options change the estimation grid as well as the view, so they start a separately
identified run. Additional flags appear with `python run_surfaces.py --help`.

## Outputs

The runner prints the report folder and writes a results ZIP plus SHA-256 sidecar to
`$HOME/Desktop/Lichess_Desktop`:

`POOL_DESERT_PAYOFF_SURFACES_RESULTS_v100_<run-id>.zip`

The report includes:

- `figures/surface_raw.{png,pdf,svg}` — raw 3D surface;
- `figures/surface_adjusted.{png,pdf,svg}` — adjusted 3D surface;
- `figures/surface_comparison.{png,pdf,svg}` — paired 3D view;
- `figures/heatmap_comparison.{png,pdf,svg}` — paired top-down view;
- `surface_grid.csv` and `.parquet` — every cell, support, counts, both rates and control means;
- `monthly_cell_counts.parquet` — monthly counts for every populated cell;
- `MODEL.json`, `control_coefficients.csv`, `pooled_moments.npz` — reproducible model quantities;
- `SUMMARY.json` — exact counts, coverage, fitted ranges and out-of-range diagnostics;
- `FIGURE_NOTES.md` — definitions and interpretation, kept off the figures;
- sample lineage, run settings, source hashes, output manifest and success receipt.

No usernames or game IDs are written to these outputs. The current sample's observed
predecessor nonadjacency screen is certified; literal immediate non-rematches are not.

To rerender a completed report without accessing private game rows:

```bash
python render_surfaces.py --report /path/to/report --out /path/to/new_figures
```

## Verification

`test_surfaces.py` checks the streaming adjusted estimates against an independently
constructed dense joint regression; partition equivalence; constant-volatility handling;
exact edge/tail assignment; missing-covariate rejection; checkpoint resume/corruption;
and identical support without selecting on the outcome. Development also exercises
parallel Parquet scans, report construction and figure rendering on clearly labeled
synthetic data. These tests do not establish what the production surfaces will show.
