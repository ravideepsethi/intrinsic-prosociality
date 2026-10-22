# Figures 2, 3 and 4 — specification revision 1.0.1

This revision follows the supplied `FIGURE_SPECIFICATION.md` and supersedes the
earlier v1.0.0 graphics. It uses the exact numerical precision in that document.

## Install the supplied figures

Copy these PDFs into your manuscript's `figures/` directory, keeping their names:

| Figure | File |
| --- | --- |
| 2 | `fig2_merit_stage_equality.pdf` |
| 3 | `fig3_relative_strength.pdf` |
| 4 | `fig4_time_profile.pdf` |

The existing `IfFileExists` guards pick them up on the next manuscript build.
No LaTeX, caption, or notes edits are needed. Each PDF is a vector figure exactly
6 inches wide. All labels are at least 8.4 pt at that width (8.26 pt at the
5.9-inch width in the available manuscript source). P052, a Palatino-compatible
font, is embedded. Screenshots for Figure 1 and Appendix A are outside this
revision's requested scope.

## What changed

- Exact specification values replace the extra source-table precision used in
  v1.0.0. Raw rates are copied, not recomputed from counts. The only interval
  arithmetic is the explicitly requested estimate plus/minus 1.96 SE.
- The plots use six-inch layouts, larger Palatino-style text, panel letters
  without panel titles, and horizontal gridlines only (or no gridlines).
- Figure 2 adds centipawn ranges, uses the shared 0–5 percent scale, labels the
  competitive reference, and preserves the four verbatim equality-model names.
- Figure 3 marks the normalized reference with an open diamond. It retains all
  22 estimates and their full stored intervals. The six comparisons have the
  exact evaluation-band labels, with filled circles and open squares. Panel C
  has the exact block names and two separate axes with their own unit titles.
- Figure 4 uses ordered categories on the horizontal axis and associations on
  the vertical axis in A. B/C share a 30–55 percent vertical scale. Open diamonds
  and shaded percentile bars identify the conditional benchmark; observed
  markers have no intervals. Its legend names the central 95% of reallocations.
  Compact time labels use `h` for hours and `d` for days; the exported data retain
  the full interval and horizon labels from the specification.

The grayscale proofs retain differences in marker shape and fill. The PDF
layouts were also inspected with the unchanged approved captions and notes.

## Files and numerical authority

- `FIGURE_SPECIFICATION.md`: the supplied file, unchanged and hash-checked.
- `plotdata/`: all ten panel/block tables, including the full rating-gap series,
  reference normalization, confidence limits and benchmark percentiles.
- `code/make_figures.py`: reads those ten tables directly from the Markdown
  specification and renders all outputs. No API requests, model fitting,
  interpolating, smoothing, new randomizations or raw-data scans are performed.
- `SOURCE_MANIFEST.json`: hashes the specification, authority receipt and fonts.
- `FIGURE_PROVENANCE.json`: input/output hashes and panel-to-table mapping.
- `verification/VALIDATION.json`: the 69 source, numerical and plotting checks.
- `verification/QA_REPORT.json`: font, PDF, grayscale and integration checks.
- `verification/`: grayscale and manuscript page proofs.
- `manuscript/`: verbatim approved figure environments, for reference only.
- `figures/`: the three PDFs and corresponding SVG and 300-dpi PNG exports.
- `Figures_2_3_4_Preview.pdf`: all three figures in one file for inspection.
- `fonts/`: embedded Palatino-compatible font files, original font sources and
  license. The optional `code/convert_fonts.py` documents the outline-format
  conversion used for reliable TrueType embedding; it never reads plot data.

The available local September 13 manuscript uses `aer`, while the supplied
specification describes an 80-page `plainnat` build. Integration was tested with
the available source's unchanged figure environments and captions; this package
does not claim to rebuild the unseen 80-page bibliography version. Existing
missing bibliography citations are outside this figure revision.

## Complete macOS rebuild commands

The prebuilt PDFs are ready to use; rebuilding is optional. Save the ZIP and
checksum into `~/Desktop/Lichess_Desktop`, then paste this entire block:

```bash
/bin/bash <<'BASH'
set -euo pipefail
task_root="$HOME/Desktop/Lichess_Desktop"
cd "$task_root"
/usr/bin/shasum -a 256 -c Lichess_Figures_2_3_4_v1_0_1.zip.sha256
task_ready="$(/usr/bin/mktemp -d "$task_root/figures_234_v101.XXXXXX")"
/usr/bin/ditto -x -k Lichess_Figures_2_3_4_v1_0_1.zip "$task_ready"
task_package="$task_ready/Lichess_Figures_2_3_4_v1_0_1"
(
    cd "$task_package"
    /usr/bin/shasum -a 256 -c MANIFEST.sha256
)
task_log="$task_root/figures_234_v101_$(/bin/date -u +%Y%m%dT%H%M%SZ).log"
/usr/bin/caffeinate -dimsu /bin/bash "$task_package/RUN_FIGURES_234.command" 2>&1 | /usr/bin/tee "$task_log"
/usr/bin/open "$task_package/figures"
printf '\nFigures: %s\nLog: %s\n' "$task_package/figures" "$task_log"
BASH
```

The runner requires Python 3.11–3.13, creates an isolated environment, and
installs pinned dependencies on its first run. Fonts are bundled; LaTeX is not
needed to regenerate the figure PDFs. Rendering takes seconds in the tested
Linux environment; initial dependency installation may take a few minutes.
The Mac command block is syntax-compatible with Bash 3.2 but was not executed
on a Mac here.

Success ends with `FIGURES_2_3_4_REPRODUCED_OK: 69 checks passed`.
The renderer updates only generated outputs in its own package. It leaves the
manuscript and raw-data drives untouched. To rebuild in an existing compatible
Python environment, run `python code/make_figures.py`.

`python code/verify_package.py` checks the delivered files against their original
manifest. Run it before local edits or rebuilds. Afterwards,
`python code/verify_package.py --sources-only` verifies only frozen inputs.
