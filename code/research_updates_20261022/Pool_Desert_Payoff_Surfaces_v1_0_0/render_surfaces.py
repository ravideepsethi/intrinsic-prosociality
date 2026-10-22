#!/usr/bin/env python3
"""Render matched 3D surfaces and heatmaps from public aggregate cells."""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import colors, cm, tri
from matplotlib.ticker import MaxNLocator, FuncFormatter
from surface_model import Settings, require


def grids(rows, settings):
    shape = (len(settings.dedges) - 1, len(settings.xedges) - 1)
    raw = np.full(shape, np.nan)
    adjusted = raw.copy()
    n = np.zeros(shape)
    for row in rows:
        if not row["inside_display_window"]:
            continue
        di, xi = row["desert_bin"] - 1, row["payoff_bin"] - 1
        n[di, xi] = row["opportunities"]
        if row["display_supported"]:
            raw[di, xi] = row["raw_percent"]
            adjusted[di, xi] = row["adjusted_percent"]
    require(np.array_equal(np.isfinite(raw), np.isfinite(adjusted)), "Plot support differs")
    return raw, adjusted, n


def supported_triangles(mask):
    ny, nx = mask.shape
    out = []
    for d in range(ny - 1):
        for x in range(nx - 1):
            if mask[d:d+2, x:x+2].all():
                a, b, c, e = d*nx+x, d*nx+x+1, (d+1)*nx+x, (d+1)*nx+x+1
                out.extend([(a,b,c), (b,e,c)])
    return np.asarray(out, dtype=np.int32).reshape(-1, 3)


def signed(value, _=None):
    return "0" if abs(value) < 1e-10 else f"{value:+g}"


def export(fig, stem):
    for suffix in ("png", "pdf", "svg"):
        fig.savefig(stem.with_suffix("."+suffix), dpi=240, facecolor="white",
                    bbox_inches="tight", pad_inches=0.20)
    plt.close(fig)


def decorate_3d(ax, settings, limits, title):
    ax.set_title(title, fontsize=19, loc="center", pad=24, weight="medium")
    ax.set_xlabel("Draw payoff $r_G$ (rating points)", labelpad=13, fontsize=12)
    ax.set_ylabel("Opponent board evaluation (cp)", labelpad=15, fontsize=12)
    # Matplotlib's tight bounding box can omit rotated 3D z labels. A 2D label
    # is reliably included in PDF/PNG/SVG exports, including the left panel.
    ax.set_zlabel("")
    ax.text2D(-0.045, 0.47, "Kindness (%)", transform=ax.transAxes,
              rotation=90, ha="center", va="center", fontsize=12)
    ax.set_xlim(settings.payoff_min, settings.payoff_max)
    ax.set_ylim(settings.desert_min, settings.desert_max)
    ax.set_zlim(*limits)
    ax.xaxis.set_major_locator(MaxNLocator(5))
    ax.yaxis.set_major_locator(MaxNLocator(5))
    ax.zaxis.set_major_locator(MaxNLocator(5))
    ax.xaxis.set_major_formatter(FuncFormatter(signed))
    ax.yaxis.set_major_formatter(FuncFormatter(signed))
    ax.tick_params(labelsize=10, pad=3)
    ax.view_init(elev=29, azim=-127)
    ax.set_box_aspect((1.20, 1.05, 0.65))
    ax.set_proj_type("ortho")
    for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
        axis.pane.set_facecolor((0.985, 0.985, 0.985, 1))
        axis.pane.set_edgecolor((0.8, 0.8, 0.8, 1))
        axis._axinfo["grid"]["color"] = (0.84, 0.85, 0.86, 0.7)
    ax.plot([0,0], [settings.desert_min,settings.desert_max],
            [limits[0],limits[0]], color="#777777", linestyle="--", linewidth=0.8)


def draw_3d(ax, xx, dd, values, triangles, norm):
    triangulation = tri.Triangulation(xx.ravel(), dd.ravel(), triangles)
    # Only triangles with four supported corner cells were constructed.
    # Fill unused vertices solely to satisfy matplotlib's finite-value parser.
    ax.plot_trisurf(triangulation, np.nan_to_num(values, nan=0).ravel(),
        cmap="viridis", norm=norm, linewidth=0.07, edgecolor=(0,0,0,0.08),
        antialiased=True, shade=False)


def render(rows, settings, destination, *, synthetic=False):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family":"DejaVu Sans", "pdf.fonttype":42,
        "svg.fonttype":"none", "axes.spines.top":False, "axes.spines.right":False})
    raw, adjusted, counts = grids(rows, settings)
    mask = np.isfinite(raw)
    require(mask.any(), "No supported display cells; inspect counts or revise grid thresholds")
    values = np.concatenate([raw[mask], adjusted[mask]])
    limits = (min(0.0, np.floor(values.min()*2)/2),
              max(0.5, np.ceil(values.max()*2)/2))
    norm = colors.Normalize(*limits)
    x = (settings.xedges[:-1]+settings.xedges[1:])/2
    d = (settings.dedges[:-1]+settings.dedges[1:])/2
    xx, dd = np.meshgrid(x,d)
    triangles = supported_triangles(mask)
    require(len(triangles) > 0, "No adjacent supported cells for a 3D surface; see cell-count table")
    watermark = "SYNTHETIC TEST DATA — NOT STUDY RESULTS" if synthetic else ""
    titles = ["Raw kindness", "Adjusted for ply, RD and volatility"]
    for data, title, stem in zip([raw, adjusted], titles, ["surface_raw", "surface_adjusted"]):
        fig = plt.figure(figsize=(12.8, 8.0))
        ax = fig.add_subplot(111, projection="3d")
        draw_3d(ax,xx,dd,data,triangles,norm)
        decorate_3d(ax,settings,limits,title)
        fig.subplots_adjust(left=0.02,right=0.88,bottom=0.03,top=0.92)
        colorbar = fig.colorbar(cm.ScalarMappable(norm=norm,cmap="viridis"),
            ax=ax, shrink=0.56, pad=0.08, fraction=0.028)
        colorbar.set_label("Kindness (%)", fontsize=12)
        if watermark: fig.text(0.5,1.04,watermark,ha="center",va="top",color="#b32c35",weight="bold")
        export(fig,destination/stem)
    fig = plt.figure(figsize=(18.0, 7.5))
    axes = []
    for i,(data,title) in enumerate(zip([raw,adjusted],titles)):
        ax = fig.add_subplot(1,2,i+1,projection="3d")
        axes.append(ax)
        draw_3d(ax,xx,dd,data,triangles,norm)
        decorate_3d(ax,settings,limits,title)
    fig.subplots_adjust(left=0.01,right=0.93,bottom=0.04,top=0.90,wspace=0.10)
    cax = fig.add_axes([0.953,0.25,0.012,0.45])
    cb = fig.colorbar(cm.ScalarMappable(norm=norm,cmap="viridis"),cax=cax)
    cb.set_label("Kindness (%)",fontsize=12)
    if watermark: fig.text(0.5,0.98,watermark,ha="center",color="#b32c35",weight="bold")
    export(fig,destination/"surface_comparison")
    fig,axes = plt.subplots(1,2,figsize=(16,6.7),sharex=True,sharey=True)
    for ax,data,title in zip(axes,[raw,adjusted],titles):
        ax.set_facecolor("#eeeeee")
        ax.pcolormesh(settings.xedges,settings.dedges,np.ma.masked_invalid(data),
            cmap="viridis",norm=norm,shading="flat",rasterized=False)
        ax.set_title(title,fontsize=17,pad=17)
        ax.set_xlabel("Draw payoff $r_G$ (rating points)",fontsize=13,labelpad=10)
        ax.axvline(0,color="white",linewidth=0.8,alpha=0.8)
        ax.set_yticks([t for t in [-600,-300,-100,0,100,300,600]
                      if settings.desert_min <= t <= settings.desert_max])
        ax.yaxis.set_major_formatter(FuncFormatter(signed))
        ax.xaxis.set_major_formatter(FuncFormatter(signed))
        ax.tick_params(labelsize=11)
    axes[0].set_ylabel("Opponent board evaluation (cp)",fontsize=13,labelpad=10)
    fig.subplots_adjust(left=0.075,right=0.90,bottom=0.13,top=0.89,wspace=0.10)
    cax=fig.add_axes([0.925,0.22,0.012,0.57])
    cb=fig.colorbar(cm.ScalarMappable(norm=norm,cmap="viridis"),cax=cax)
    cb.set_label("Kindness (%)",fontsize=12)
    if watermark: fig.text(0.5,0.98,watermark,ha="center",color="#b32c35",weight="bold")
    export(fig,destination/"heatmap_comparison")
    return {"common_rate_limits_percent":list(limits),"supported_cells":int(mask.sum()),
        "surface_triangles":len(triangles),"projection":"orthographic", "view_elevation":29,
        "view_azimuth":-127,"smoothing":"none; planar facets join adjacent supported cell centers",
        "unsupported_cells":"blank in both figures; no outcome-based support filtering",
        "negative_adjusted_display_cells":int((adjusted[mask]<0).sum()),
        "matplotlib_version":matplotlib.__version__,"synthetic":synthetic}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--report",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    a=p.parse_args()
    settings=Settings(**json.loads((a.report/"SETTINGS.json").read_text()))
    with (a.report/"surface_grid.csv").open(newline="") as f:
        rows=list(csv.DictReader(f))
    for r in rows:
        for k in ["cell_id","payoff_bin","desert_bin","opportunities","kind_draws","months_observed"]: r[k]=int(r[k])
        for k in ["inside_display_window","display_supported","adjusted_outside_0_100"]: r[k]=r[k].lower()=="true"
        for k in ["raw_percent","adjusted_percent"]: r[k]=float(r[k]) if r[k] else None
    print(json.dumps(render(rows,settings,a.out),indent=2))


if __name__ == "__main__":
    main()
