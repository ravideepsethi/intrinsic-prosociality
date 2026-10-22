# Board merit and game stage — rates, counts and centipawn boundaries

This version labels each row by board state and marks the four internal centipawn boundaries,
retaining the exact observation counts in the standalone five-by-eight heatmap.
It uses the current certified pool main sample:
**41,534,331 opportunities and 570,091 kind draws**, November 2023–October 2025.
The prebuilt figure is ready to use; reproducing it requires no game-level data.

## Deliverables

- `figures/fig1_desert_ply_41M_counts_cp.pdf`: one-page vector PDF with embedded fonts,
  8.4 × 4.85 inches. The heatmap and color scale remain vector geometry.
- `figures/fig1_desert_ply_41M_counts_cp.png`: 300 dpi preview.
- `figures/fig1_desert_ply_41M_counts_cp.svg`: vector alternative.
- `plotdata/board_merit_by_ply.csv`: all 40 heatmap rates and their counts.
- `plotdata/heatmap_rates_wide.csv`: the complete five-by-eight rate matrix.
- `source_data/`: the two unmodified current-sample source tables.
- `code/make_desert_ply.py`: plotting code and data checks.
- `verification/`: numerical validation and export review records.

The heatmap plots the stored full-precision rates and labels them to one decimal
place, as in the reference. It retains the reference's 0–5.6% color scale.
Each cell places the percentage above the exact, comma-separated observation
count. Observation counts are the denominators used to calculate the rates.
The wider layout provides room for all counts, including 11,115,024 in the
largest cell. No models are refitted or rates estimated from a graphic.

The board-state order is clearly better, better, roughly equal, modestly worse,
clearly worse, always from the disconnected player's perspective. Centipawn
boundaries are ≥300, 101–299, −100–100, −299–−101, and ≤−300 respectively.
The left axis shows +300, +100, −100 and −300, in that order from top to
bottom, at the four boundaries between rows. The five board-state names sit
at the row centers. The frozen descriptive bins match `FIGURE_SPECIFICATION.md` and
the manuscript's `sec:desert_measure` subsection.
The final-position ply bands are 0–4, 5–6, 7–8, 9–10, 11–20, 21–40, 41–80,
and 81+.

## Sample and source authority

The sample predicate is
`source = 'pool' AND previous_classification_status = 'not_mutually_adjacent_observed'`.
This is the observed adjacency screen; it does not certify the exclusion of
every literal immediate rematch. Evaluations use Stockfish 18 at 100,000 nodes.

The source fingerprint is
`a17c89d750cb4fdfdf84f950859e45c58b19996efae02045def68285e305cf30`.
`SOURCE_MANIFEST.json` identifies and hashes the exact current-sample inputs;
`SAMPLE_AUTHORITY.json` retains the authority receipt. The 40 cells sum to the
sample totals, and all eight ply cells within each state sum to that state's
counts in the separate marginal source table.

## Reproduce on a Mac

Save the ZIP and its `.sha256` file in `~/Desktop/Lichess_Desktop`, then paste
this entire block into Terminal. It verifies the download, extracts into a
fresh directory, creates an isolated Python environment, and renders the figure.
Python 3.11–3.13 must be installed; the first run downloads the pinned Python
packages. Rendering from the supplied tables takes seconds after installation.

```bash
(
set -euo pipefail
cd "$HOME/Desktop/Lichess_Desktop"
shasum -a 256 -c Lichess_Desert_Ply_Counts_CP_41M_v1_0_0.zip.sha256
task_run="$(mktemp -d "$HOME/Desktop/Lichess_Desktop/desert_ply_counts_cp_41M.XXXXXX")"
ditto -x -k Lichess_Desert_Ply_Counts_CP_41M_v1_0_0.zip "$task_run"
caffeinate -dimsu bash "$task_run/Lichess_Desert_Ply_Counts_CP_41M_v1_0_0/RUN_DESERT_PLY.command"
open "$task_run/Lichess_Desert_Ply_Counts_CP_41M_v1_0_0/figures"
)
```

Successful reproduction prints `DESERT_PLY_41M_REPRODUCED_OK`.
The `_counts_cp` filenames identify this additional version of the standalone
heatmap. The earlier versions remain available separately.
