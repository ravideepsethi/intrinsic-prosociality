Intrinsic Prosociality: paper figures v1.1.0

Place this ZIP and its SHA-256 sidecar in ~/Desktop/Lichess_Desktop.
Verify the sidecar, unpack with ditto, and run:

  bash Lichess_Paper_Figures_v1_1_0/RUN_FIGURES.command

The first run installs pinned dependencies into its own environment.
Allow 2-5 minutes for setup; figure generation should take under one minute.
It uses one process and does not need the external data drive or API calls.

Output: build/paper_figures/<timestamp>/figures/
Use the vector PDFs in the manuscript. The six-page review PDF is also
included in results/paper_figures_v110/figure_review.pdf.

Read docs/paper_figures.md for the panel mapping and sample qualifications.
All estimates retain their original sample status. This is a figure build,
not a new author-exclusion certification.

The GitHub change is additive. Canonical code: code/paper_figures/.
Existing inputs retain their original results/pool_main_reanalysis_v100/
paths. The added aggregates are in results/paper_figure_inputs_v110/.
