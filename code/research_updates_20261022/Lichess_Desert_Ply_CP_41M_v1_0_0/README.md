# Board merit and game stage — percentages only

This version shows the kind-draw percentage in each heatmap cell, board-state
names at the row centers, and +300, +100, −100 and −300 at the row boundaries.
Observation counts and bottom notes are omitted from the graphic. The earlier
version with counts and notes remains available separately.

The figure uses the current certified pool main sample: 41,534,331 opportunities
and 570,091 kind draws, November 2023–October 2025. All 40 stored rates and the
0–5.6% color scale are retained. Rates are plotted at full precision and labeled
to one decimal place. The source tables retain the counts used as denominators.

## Files

- `figures/fig1_desert_ply_41M_cp.pdf`: vector PDF, 8.4 × 4.25 inches.
- `figures/fig1_desert_ply_41M_cp.png`: 300 dpi preview.
- `figures/fig1_desert_ply_41M_cp.svg`: vector alternative.
- `plotdata/`: every plotted value, including the underlying observation counts.
- `source_data/`: the two original current-sample source tables.
- `code/make_desert_ply.py`: plotting code and validation.
- `verification/`: numerical checks and PDF export review.

## Sample and bins

Evaluations are from the disconnected player's perspective, using Stockfish 18
at 100,000 nodes. The five frozen bins are ≥+300, +101 to +299, −100 to +100,
−299 to −101, and ≤−300 centipawns. Final-position ply bands are 0–4, 5–6, 7–8,
9–10, 11–20, 21–40, 41–80, and 81+.

The sample predicate is
`source = 'pool' AND previous_classification_status = 'not_mutually_adjacent_observed'`.
This is the observed adjacency screen; it does not certify the exclusion of
every literal immediate rematch. The source fingerprint is
`a17c89d750cb4fdfdf84f950859e45c58b19996efae02045def68285e305cf30`.
`SOURCE_MANIFEST.json` hashes the inputs and `SAMPLE_AUTHORITY.json` retains
the authority receipt. No models are refitted.

## Reproduce on a Mac

Save the ZIP and its `.sha256` file in `~/Desktop/Lichess_Desktop`, then paste
the entire block below into Terminal. Python 3.11–3.13 must be installed.
The first run downloads the pinned dependencies into an isolated environment;
rendering from these supplied tables takes seconds after installation.

```bash
(
set -euo pipefail
cd "$HOME/Desktop/Lichess_Desktop"
shasum -a 256 -c Lichess_Desert_Ply_CP_41M_v1_0_0.zip.sha256
task_run="$(mktemp -d "$HOME/Desktop/Lichess_Desktop/desert_ply_cp_41M.XXXXXX")"
ditto -x -k Lichess_Desert_Ply_CP_41M_v1_0_0.zip "$task_run"
caffeinate -dimsu bash "$task_run/Lichess_Desert_Ply_CP_41M_v1_0_0/RUN_DESERT_PLY.command"
open "$task_run/Lichess_Desert_Ply_CP_41M_v1_0_0/figures"
)
```

Successful reproduction prints `DESERT_PLY_41M_REPRODUCED_OK`.
