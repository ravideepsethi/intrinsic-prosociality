#!/usr/bin/env python3
"""Render public plots from Parquet-first v1.1.0 closure outputs."""

from pathlib import Path
import argparse

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

LABELS = {
    "m600_m300": "-600 to -300 cp",
    "m300_m100": "-300 to -100 cp",
    "m100_p100": "-100 to +100 cp",
    "p100_p300": "+100 to +300 cp",
    "p300_p600": "+300 to +600 cp",
}

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--out-root", type=Path, required=True)
    return p.parse_args()

def main():
    a = parse_args()
    out = a.out_root
    plotdir = out / "plots"
    plotdir.mkdir(exist_ok=True)

    c = pd.read_parquet(out / "fe_nonparametric_curves.parquet")

    for stage in ["all", "ply_le_10", "ply_gt_10"]:
        fig, ax = plt.subplots(figsize=(9.0, 5.8))
        anyline = False
        for eb in LABELS:
            mid = f"primary_k20__{stage}__{eb}"
            d = c[c.model_id == mid].sort_values("gap_mid")
            if len(d):
                ax.plot(d.gap_mid, d.coef_pp, marker="o", markersize=3, linewidth=1.25, label=LABELS[eb])
                anyline = True
        if not anyline:
            plt.close(fig)
            continue
        ax.axhline(0, linewidth=.8)
        ax.axvline(0, linewidth=.8)
        ax.set_xlabel("Disconnected minus chooser rating (Elo)")
        ax.set_ylabel("Adjusted kindness difference vs ±25 Elo bin (pp)")
        ax.set_title(f"Nonparametric chooser-FE relative-rating curve — {stage}")
        ax.legend(frameon=False, fontsize=8)
        ax.grid(alpha=.2)
        fig.tight_layout()
        fig.savefig(plotdir / f"primary_nonparametric_{stage}.png", dpi=220, bbox_inches="tight")
        fig.savefig(plotdir / f"primary_nonparametric_{stage}.pdf", bbox_inches="tight")
        plt.close(fig)

    for eb in ["m100_p100", "p100_p300", "p300_p600"]:
        fig, ax = plt.subplots(figsize=(8.7, 5.5))
        specs = [
            (f"primary_k20__ply_gt_10__{eb}", "K20 primary"),
            (f"k50__ply_gt_10__{eb}", "K50"),
            (f"stableRD_K95__ply_gt_10__{eb}", "RD≤100 & K≤p95"),
        ]
        for mid, label in specs:
            d = c[c.model_id == mid].sort_values("gap_mid")
            if len(d):
                ax.plot(d.gap_mid, d.coef_pp, marker="o", markersize=3, linewidth=1.25, label=label)
        ax.axhline(0, linewidth=.8)
        ax.axvline(0, linewidth=.8)
        ax.set_xlabel("Disconnected minus chooser rating (Elo)")
        ax.set_ylabel("Adjusted kindness difference vs ±25 Elo bin (pp)")
        ax.set_title(f"K/RD closure, >10 plies — {LABELS[eb]}")
        ax.legend(frameon=False)
        ax.grid(alpha=.2)
        fig.tight_layout()
        fig.savefig(plotdir / f"krd_closure_long_{eb}.png", dpi=220, bbox_inches="tight")
        plt.close(fig)

    for eb in ["m100_p100", "p100_p300", "p300_p600"]:
        fig, ax = plt.subplots(figsize=(8.7, 5.5))
        for yr, label in [("year1", "Year 1"), ("year2", "Year 2")]:
            d = c[c.model_id == f"{yr}__ply_gt_10__{eb}"].sort_values("gap_mid")
            if len(d):
                ax.plot(d.gap_mid, d.coef_pp, marker="o", markersize=3, linewidth=1.25, label=label)
        ax.axhline(0, linewidth=.8)
        ax.axvline(0, linewidth=.8)
        ax.set_xlabel("Disconnected minus chooser rating (Elo)")
        ax.set_ylabel("Adjusted kindness difference vs ±25 Elo bin (pp)")
        ax.set_title(f"Adjusted year replication, >10 plies — {LABELS[eb]}")
        ax.legend(frameon=False)
        ax.grid(alpha=.2)
        fig.tight_layout()
        fig.savefig(plotdir / f"year_replication_long_{eb}.png", dpi=220, bbox_inches="tight")
        plt.close(fig)

    print("RATING_GAP_NONPARAMETRIC_RENDER_V110_OK")
    print("Plot directory:", plotdir)

if __name__ == "__main__":
    main()
