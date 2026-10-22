#!/usr/bin/env python3
"""Rebuild manuscript figures directly from checked repository aggregates."""

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".mplconfig"))
sys.path.insert(0, str(ROOT / "src"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump_rows(path, rows):
    if not rows:
        return
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def check_text_bounds(fig):
    """Catch clipped text in the fixed-size canvas; visual QA checks overlaps."""
    from matplotlib.text import Text

    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    box = fig.bbox
    problems = []
    for text in fig.findobj(match=Text):
        if not text.get_visible() or not text.get_text().strip():
            continue
        b = text.get_window_extent(renderer)
        if (
            b.x0 < box.x0 - 2
            or b.x1 > box.x1 + 2
            or b.y0 < box.y0 - 2
            or b.y1 > box.y1 + 2
        ):
            problems.append(text.get_text())
    if problems:
        raise ValueError("Text outside figure canvas: " + repr(problems))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, help="New output directory; must not already exist."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=ROOT.parent.parent,
        help="Repository or portable package root (normally detected).",
    )
    parser.add_argument(
        "--png-dpi",
        type=int,
        default=600,
        choices=[300, 600],
        help="Raster export resolution; PDFs and SVGs remain vector.",
    )
    parser.add_argument(
        "--figure", default="all", help="all, or a registry key; use --list."
    )
    parser.add_argument(
        "--monochrome",
        action="store_true",
        help="Grayscale proof using distinct markers/line styles.",
    )
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    import matplotlib
    import numpy as np
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib import pyplot as plt, font_manager, ft2font
    import data, figures, style

    if args.list:
        for k, (title, _) in figures.REGISTRY.items():
            print(k, ":", title)
        return
    if args.figure != "all" and args.figure not in figures.REGISTRY:
        parser.error("Unknown figure key.")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    out = args.output or args.repo_root / "build" / "paper_figures" / stamp
    if out.exists():
        parser.error("Output directory already exists; choose a fresh path.")
    started = time.monotonic()
    d = data.load(args.repo_root, ROOT / "INPUTS.json")
    style.configure(args.monochrome)
    out.mkdir(parents=True)
    (out / "figures").mkdir()
    (out / "plot_data").mkdir()
    for key, rows in d.items():
        if isinstance(rows, list):
            dump_rows(out / "plot_data" / f"{key}.csv", rows)
    dump_rows(out / "plot_data" / "iv_bins.csv", d["iv"]["bins"])
    (out / "plot_data" / "iv_scale.json").write_text(
        json.dumps({k: v for k, v in d["iv"].items() if k != "bins"}, indent=2) + "\n"
    )
    chosen = list(figures.REGISTRY) if args.figure == "all" else [args.figure]
    print(f"Inputs verified. Rendering {len(chosen)} figures.", flush=True)
    meta = {
        "Creator": "Lichess Paper Figures 1.1.0",
        "Author": "Ravideep Sethi",
        "CreationDate": None,
        "ModDate": None,
    }
    manifest = []
    with PdfPages(out / "figure_review.pdf", metadata=meta) as proof:
        for i, key in enumerate(chosen, 1):
            title, draw = figures.REGISTRY[key]
            fig = draw(d)
            check_text_bounds(fig)
            for ext in ["pdf", "svg", "png"]:
                path = out / "figures" / f"{key}.{ext}"
                if ext == "pdf":
                    fig.savefig(path, metadata={**meta, "Title": title})
                elif ext == "svg":
                    fig.savefig(
                        path,
                        metadata={
                            "Date": None,
                            "Creator": "Lichess Paper Figures 1.1.0",
                            "Title": title,
                        },
                    )
                else:
                    fig.savefig(
                        path,
                        dpi=args.png_dpi,
                        metadata={"Software": "Lichess Paper Figures 1.1.0"},
                    )
                manifest.append(
                    dict(
                        file=path.relative_to(out).as_posix(),
                        sha256=sha(path),
                        bytes=path.stat().st_size,
                    )
                )
            # Titles belong to the manuscript caption. The review PDF labels each page.
            heading = fig.text(0.105, 0.965, title, ha="left", va="top", fontsize=11)
            check_text_bounds(fig)
            proof.savefig(fig)
            heading.remove()
            plt.close(fig)
            print(f"[{i}/{len(chosen)}] {key}: PDF, SVG, PNG", flush=True)
    font = Path(font_manager.findfont("STIXGeneral"))
    environment = dict(
        python=platform.python_version(),
        platform=platform.platform(),
        matplotlib=matplotlib.__version__,
        numpy=np.__version__,
        freetype=ft2font.__freetype_version__,
        font_name="STIXGeneral",
        font_sha256=sha(font),
        monochrome=args.monochrome,
    )
    checks = dict(
        status="FIGURES_REPRODUCED_FROM_ARCHIVED_AGGREGATES",
        figure_count=len(chosen),
        input_hashes_verified=True,
        scientific_cross_checks_passed=True,
        text_within_canvas=True,
        fitted_models_reestimated=False,
        api_calls=0,
        stockfish_calls=0,
        reference_score_sd=d["iv"]["reference_sd"],
        first_stage_pp_per_reference_sd=d["iv"]["slope"],
        strict_monotonicity_of_iv_bins=False,
        iv_bin_6_minus_bin_5_pp=d["iv"]["bins"][5]["estimate"]
        - d["iv"]["bins"][4]["estimate"],
        sample_status="Preserves each source archive; no new author-exclusion certification.",
        seconds=round(time.monotonic() - started, 2),
    )
    (out / "ENVIRONMENT.json").write_text(json.dumps(environment, indent=2) + "\n")
    (out / "INPUT_RECEIPT.json").write_text(
        json.dumps(d["input_receipt"], indent=2) + "\n"
    )
    (out / "CHECKS.json").write_text(json.dumps(checks, indent=2) + "\n")
    (out / "OUTPUT_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (out / "SOURCE_CODE_HASHES.json").write_text(
        json.dumps(
            {
                p.relative_to(ROOT).as_posix(): sha(p)
                for p in sorted([ROOT / "build.py", *ROOT.glob("src/*.py")])
            },
            indent=2,
        )
        + "\n"
    )
    (out / "_SUCCESS.json").write_text(
        json.dumps(dict(status=checks["status"], figures=chosen), indent=2) + "\n"
    )
    print(
        f"OK: {len(chosen)} figures in {time.monotonic()-started:.1f} seconds.\n{out.resolve()}",
        flush=True,
    )


if __name__ == "__main__":
    main()
