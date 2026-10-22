#!/usr/bin/env python3
"""Render diagnostic plots from the rating-gap/K-RD decomposition aggregate outputs."""

from pathlib import Path
import argparse, json
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def parse_args():
    p=argparse.ArgumentParser()
    p.add_argument("--out-root",type=Path,required=True)
    p.add_argument("--min-n",type=int,default=500)
    return p.parse_args()


LABELS={
 "m600_m300":"-600 to -300 cp",
 "m300_m100":"-300 to -100 cp",
 "m100_p100":"-100 to +100 cp",
 "p100_p300":"+100 to +300 cp",
 "p300_p600":"+300 to +600 cp",
}


def main():
    a=parse_args()
    out=a.out_root
    pdst=out/"plots"
    pdst.mkdir(exist_ok=True)

    gap=pd.read_csv(out/"rating_gap_curves.csv")
    score=pd.read_csv(out/"expected_score_curves.csv")

    # Main current-24m curves, one plot per stage.
    for stage in ["all","ply_le_10","ply_gt_10"]:
        fig,ax=plt.subplots(figsize=(8.5,5.5))
        g=gap[(gap.stage==stage)&(gap.year_half=="all")]
        for eb in LABELS:
            d=g[(g.eval_band==eb)&(g.n>=a.min_n)].sort_values("x_mid")
            if len(d):
                ax.plot(d.x_mid,d.rate_pct,marker="o",markersize=2.5,linewidth=1.3,label=LABELS[eb])
        ax.axvline(0,linewidth=.8)
        ax.set_xlabel("Disconnected minus chooser displayed rating (Elo)")
        ax.set_ylabel("Kindness rate (%)")
        ax.set_title(f"Kindness by displayed rating gap — {stage}")
        ax.legend(frameon=False,fontsize=8)
        ax.grid(alpha=.2)
        fig.tight_layout()
        fig.savefig(pdst/f"rating_gap_curves_{stage}.png",dpi=210,bbox_inches="tight")
        fig.savefig(pdst/f"rating_gap_curves_{stage}.pdf",bbox_inches="tight")
        plt.close(fig)

    # Year replication for positive-board bands, long games.
    for eb in ["m100_p100","p100_p300","p300_p600"]:
        fig,ax=plt.subplots(figsize=(8.2,5.2))
        for yh,label in [("year1","Year 1"),("year2","Year 2")]:
            d=gap[(gap.stage=="ply_gt_10")&(gap.eval_band==eb)&(gap.year_half==yh)&(gap.n>=a.min_n)].sort_values("x_mid")
            if len(d):
                ax.plot(d.x_mid,d.rate_pct,marker="o",markersize=2.5,linewidth=1.3,label=label)
        ax.axvline(0,linewidth=.8)
        ax.set_xlabel("Disconnected minus chooser displayed rating (Elo)")
        ax.set_ylabel("Kindness rate (%)")
        ax.set_title(f"Year replication, >10 plies — {LABELS[eb]}")
        ax.legend(frameon=False)
        ax.grid(alpha=.2)
        fig.tight_layout()
        fig.savefig(pdst/f"rating_gap_year_replication_long_{eb}.png",dpi=210,bbox_inches="tight")
        plt.close(fig)

    # Expected-score distance plots: negative and positive rating-gap sides separately
    # are not encoded in this aggregate, so show board-state profiles of distance itself.
    for stage in ["all","ply_gt_10"]:
        fig,ax=plt.subplots(figsize=(8.5,5.5))
        g=score[(score.stage==stage)&(score.year_half=="all")]
        for eb in LABELS:
            d=g[(g.eval_band==eb)&(g.n>=a.min_n)].sort_values("x_mid")
            if len(d):
                ax.plot(d.x_mid,d.rate_pct,marker="o",markersize=2.5,linewidth=1.3,label=LABELS[eb])
        ax.set_xlabel("|Expected score - 0.5|")
        ax.set_ylabel("Kindness rate (%)")
        ax.set_title(f"Kindness by expected-score distance — {stage}")
        ax.legend(frameon=False,fontsize=8)
        ax.grid(alpha=.2)
        fig.tight_layout()
        fig.savefig(pdst/f"expected_score_distance_{stage}.png",dpi=210,bbox_inches="tight")
        plt.close(fig)

    print("RATING_GAP_KRD_RENDER_OK")
    print("Plots:",pdst)


if __name__=="__main__":
    main()
