"""One style, sized at the manuscript's 5.9-inch text width.

STIXGeneral is distributed with Matplotlib, so no system font or TeX
installation is needed. Set PDF fonts to embedded TrueType, not Type 3.
"""

import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot as plt
from matplotlib.ticker import FuncFormatter

INK = "#202020"
BLUE = "#244f69"
RUST = "#9b4a27"
GREY = "#707070"
LIGHT = "#d6dde1"


def configure(monochrome=False):
    global BLUE, RUST, GREY
    BLUE, RUST, GREY = "#244f69", "#9b4a27", "#666666"
    if monochrome:
        BLUE, RUST, GREY = "#151515", "#656565", "#888888"
    plt.rcParams.update(
        {
            "font.family": "STIXGeneral",
            "mathtext.fontset": "stix",
            "font.size": 9.5,
            "axes.labelsize": 9.5,
            "axes.titlesize": 10,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "legend.fontsize": 8.5,
            "legend.frameon": False,
            "text.color": INK,
            "axes.labelcolor": INK,
            "xtick.color": INK,
            "ytick.color": INK,
            "axes.edgecolor": "#555555",
            "axes.linewidth": 0.55,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "xtick.direction": "out",
            "ytick.direction": "out",
            "xtick.major.width": 0.5,
            "ytick.major.width": 0.5,
            "xtick.major.size": 3,
            "ytick.major.size": 3,
            "lines.linewidth": 1.1,
            "lines.markersize": 3.5,
            "axes.axisbelow": True,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "svg.fonttype": "path",
            "svg.hashsalt": "lichess-paper-figures-1.1.0",
            "path.simplify": False,
        }
    )


def finish(ax, grid="y"):
    ax.grid(axis=grid, color="#e7e7e7", linewidth=0.4)
    if grid == "y":
        ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:g}"))
    ax.tick_params(pad=3)


def title(ax, letter, text):
    ax.set_title(f"{letter}. {text}", loc="left", pad=9, fontweight="normal")


def zero(ax, orientation="h"):
    if orientation == "h":
        ax.axhline(0, color="#8d8d8d", linewidth=0.6, zorder=1)
    else:
        ax.axvline(0, color="#8d8d8d", linewidth=0.6, zorder=1)


def errorbar(ax, x, y, lo, hi, horizontal=False, color=None, marker="o", **kwargs):
    import numpy as np

    center = np.asarray(x if horizontal else y, dtype=float)
    err = np.array([center - np.asarray(lo), np.asarray(hi) - center])
    if (err < -1e-9).any():
        raise ValueError("Interval does not contain its reported estimate.")
    err = np.maximum(err, 0)
    return ax.errorbar(
        x,
        y,
        **({"xerr": err} if horizontal else {"yerr": err}),
        fmt=marker,
        color=color or BLUE,
        capsize=2,
        elinewidth=0.7,
        capthick=0.7,
        zorder=4,
        **kwargs,
    )
