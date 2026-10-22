# Paper figure renderer

Version 1.1.0. Run from the repository root:

```bash
bash code/paper_figures/RUN_FIGURES.command
```

The launcher creates an isolated environment with pinned dependencies. Allow
2-5 minutes for its first installation; rendering the six figures normally
takes less than one minute. The checked Linux build took about four seconds.
Mac execution has not yet been observed.

Full instructions, manuscript mapping, and sample qualifications:
[docs/paper_figures.md](../../docs/paper_figures.md).

- `build.py`: verify inputs, select panels, export figures and receipts.
- `src/data.py`: row selections, units, and numerical checks.
- `src/figures.py`: the six figure layouts.
- `src/style.py`: shared publication style.
- `INPUTS.json`: source archives, exact members, repository paths, and hashes.
- `FIGURE_CAPTIONS.tex`: optional manuscript caption macros.

The build reads the existing public aggregate tables directly, including two
Parquet tables, plus eight newer aggregate inputs under
`results/paper_figure_inputs_v110/`. No individual observations are needed.

After setup:

```bash
code/paper_figures/.venv/bin/python code/paper_figures/build.py --list
code/paper_figures/.venv/bin/python code/paper_figures/build.py --monochrome
```

`--figure NAME` selects one figure. `--output PATH` selects a fresh output
directory. `--repo-root PATH` overrides the detected repository root.
`--png-dpi 300` creates lighter previews; the default is 600 dpi. PDF/SVG
exports are vector at either setting. Every successful run includes the exact
plotting rows, an input receipt, dependency versions, hashes, and `_SUCCESS.json`.
