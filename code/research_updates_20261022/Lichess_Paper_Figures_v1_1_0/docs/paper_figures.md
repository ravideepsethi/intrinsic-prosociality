# Reproducible manuscript figures

Version 1.1.0, for the main paper and supplement dated October 8, 2026.
The six statistical figures share a restrained publication style: a 5.9-inch
canvas, embedded STIX serif text, thin axes, light guide lines, and dark blue
with a muted rust comparison series. Line styles and filled/open markers
retain the comparisons in grayscale. Captions and detailed specifications
remain in the manuscript.

## Run on the Mac

From the repository root:

```bash
bash code/paper_figures/RUN_FIGURES.command
```

Requires Python 3.11-3.14. `FIGURES_PYTHON=/path/to/python3` selects an
interpreter. The launcher creates a private virtual environment and installs
the pinned dependencies there. It uses one process; the external data drive,
API access, Stockfish, and estimation workers are not needed. Initial setup
usually takes 2-5 minutes, depending on the connection. Subsequent rendering
should take under a minute; the verification environment took about four
seconds. That is a Linux measurement, not a Mac benchmark.

Every run creates `build/paper_figures/<timestamp>/` with:

- six vector PDFs and SVGs, plus 600-dpi PNG exports;
- `figure_review.pdf`, with a title identifying each review page;
- `plot_data/`, containing the exact selected values for every panel;
- input hashes, source-code hashes, dependency versions, output hashes,
  numerical checks, and `_SUCCESS.json`.

Use `--monochrome` for a grayscale proof, `--figure NAME` for one figure,
`--list` for the names, and `--output PATH` for a fresh output directory.
The build refuses an existing destination. A rendering failure cannot create
a success receipt. Selected reference outputs are under
`results/paper_figures_v110/`; ordinary runs are ignored by Git.

## Manuscript mapping

| Figure | PDF | Content |
|---|---|---|
| 2 | `figure_2_board_stage.pdf` | Board position, game stage, equality specifications |
| 3 | `figure_3_evaluation.pdf` | Continuous evaluation, tail categories, support |
| 4 | `figure_4_relative_strength.pdf` | Rating gap, account comparisons, adjacent levels, payoff slopes |
| 5 | `figure_5_first_stage.pdf` | Twenty first-stage bins and a close view of bins 1-19 |
| S1.1 | `figure_S1_1_material.pdf` | Material profiles |
| S3.1 | `figure_S3_1_time.pdf` | Receipt intervals and conditional temporal benchmarks |

Use the PDFs at `width=\textwidth` in the current 5.9-inch text block. This
also applies to S1.1, previously included at 85 percent width. Text is designed
at approximately 8-10 points at this width. The plotting code needs no TeX
installation or separately installed fonts. The interface screenshots in
Figures 1 and A.1 remain documentary screenshots.

Optional caption macros are in `code/paper_figures/FIGURE_CAPTIONS.tex`.
Keep the manuscript's labels and cross-references. The supplied September 3
TeX is older than the current PDFs, so it has not been overwritten.

Two manuscript changes accompany the new presentation:

1. Figure 4 now has four panels. Adjacent-rating levels remain C; local
   draw-payoff slopes are D. References to the slopes should point to 4D.
2. Figure 5 should not claim receipt rises "at every step." Bins 5 and 6
   decline by about 0.00245 percentage points. The figure preserves their
   order and values. Its neutral title is "Receipt and the opponent's score."

Figure 3 uses one vertical scale for the curve and tail categories. The
shaded band belongs to the primary model; the clock and rating variants have
distinct line styles. In S3.1, A shows regression confidence intervals;
B and C show central randomization ranges, not confidence intervals for
an effect. Their axes and caption preserve this distinction.

## Numerical provenance

`code/paper_figures/INPUTS.json` records the seven original archive hashes,
their exact members, original file hashes, and repository paths. The original
archives were verified against the supplied SHA-256 sidecars. Eight inputs
match the existing public repository byte-for-byte. Eight newer files are
preserved under `results/paper_figure_inputs_v110/`. The two original Parquet
tables are read directly with PyArrow; no rounded table transcription or
digitization is used.

The plotted values are unchanged from the preceding standalone v1.0.0
rendering package. Row selections and unit conversions are explicit in
`src/data.py`. Checks include sample and grant totals, the competitive-stage
partition, twenty equal-count bins, the reference rating-gap coefficient,
and the seven-day session partition. The slope-difference interval comes
from the stored joint-covariance estimate.

The IV x-axis uses the paper's fixed reference SD,
`0.059411690344000595`. Multiplying the original raw-score first-stage
coefficient by that SD gives approximately `7.575486` percentage points.
The restricted competitive sample's residual SD is different and is not
substituted for the paper reference scale.

This reproduces the archived estimates used in the manuscript figures.
It is not a new certification of author-account exclusion. The competitive
IV source records `author_included: true`; the later Run 3 source supplies
the display scale and has a different exclusion status. The underlying
sample qualifications remain attached to their sources.

## Repository integration and maintenance

The rendering layer is `code/paper_figures/`. It consumes existing
`results/pool_main_reanalysis_v100/` paths and the added aggregate inputs.
Historical estimation code, results, and their release hashes are unchanged.
The new input manifest governs the figure build independently of the
September 11 release manifest.

When estimates change, replace the relevant aggregate inputs deliberately,
update their source records and hashes, and reconcile the scientific checks
and caption. A hash mismatch stops the build. A style-only change should
leave every file in `plot_data/` unchanged.

PDF dates are omitted, SVG IDs use a fixed salt, and dependencies are pinned.
The build records the font hash and FreeType version. Identical environments
produce identical figure bytes in verification; cross-platform font libraries
can still cause byte differences while preserving the numerical content.

The font/export choices follow the official Matplotlib documentation:
[font embedding](https://matplotlib.org/stable/users/explain/text/fonts.html)
and [figure export](https://matplotlib.org/stable/api/_as_gen/matplotlib.pyplot.savefig.html).
