"""Six figures for the 8 October 2026 main paper and supplement."""

import numpy as np
from matplotlib import pyplot as plt
from matplotlib.lines import Line2D
import style as s


def col(rows, key):
    return np.array([r[key] for r in rows], dtype=float)


def ci(ax, rows, x=None, y=None, horizontal=False, **kw):
    if horizontal:
        return s.errorbar(
            ax,
            col(rows, "estimate"),
            y,
            col(rows, "lo"),
            col(rows, "hi"),
            horizontal=True,
            **kw,
        )
    return s.errorbar(
        ax, x, col(rows, "estimate"), col(rows, "lo"), col(rows, "hi"), **kw
    )


def board_stage(d):
    fig = plt.figure(figsize=(5.9, 4.9))
    a = fig.add_axes([0.105, 0.565, 0.535, 0.32])
    b = fig.add_axes([0.755, 0.565, 0.215, 0.32], sharey=a)
    c = fig.add_axes([0.545, 0.14, 0.41, 0.245])
    colors = [s.BLUE] * 3 + ["#b7b7b7", s.GREY]
    a.bar(np.arange(5), col(d["board"], "percent"), color=colors, width=0.64, zorder=3)
    a.set_xticks(
        range(5),
        [
            "Clearly\nbetter\n≥ 300",
            "Better\n101–299",
            "Roughly\nequal\n−100–100",
            "Modestly\nworse\n−299–−101",
            "Clearly\nworse\n≤ −300",
        ],
    )
    a.tick_params(axis="x", labelsize=8.5, length=0)
    a.set_ylabel("Grant rate (%)")
    a.set_ylim(0, 5.25)
    a.set_yticks(range(6))
    for i, r in enumerate(d["board"]):
        a.text(i, r["percent"] + 0.12, f"{r['percent']:.2f}", ha="center", fontsize=8.5)
    a.plot([-0.3, -0.3, 2.3, 2.3], [4.16, 4.3, 4.3, 4.16], lw=0.65, color=s.INK)
    comp = (
        100
        * sum(r["grants"] for r in d["board"][:3])
        / sum(r["n"] for r in d["board"][:3])
    )
    a.text(1, 4.46, f"Competitive positions: {comp:.2f}%", ha="center", fontsize=8.5)
    s.title(a, "A", "Board position")
    s.finish(a)
    b.bar(range(3), col(d["stage"], "percent"), color=s.BLUE, width=0.6, zorder=3)
    b.set_xticks(range(3), ["Ply 2", "Plies\n3–10", "After\nply 10"])
    b.tick_params(axis="x", length=0)
    b.tick_params(axis="y", labelleft=False)
    for i, r in enumerate(d["stage"]):
        b.text(i, r["percent"] + 0.12, f"{r['percent']:.2f}", ha="center", fontsize=8.5)
    s.title(b, "B", "Game stage")
    s.finish(b)
    rows = d["equality"]
    y = np.arange(4)[::-1]
    ci(c, rows, y=y, horizontal=True)
    c.set_yticks(y, [r["label"] for r in rows])
    c.tick_params(axis="y", length=0, labelsize=8.5)
    c.set_xlim(-0.48, 0.29)
    c.set_xticks([-0.4, -0.2, 0, 0.2])
    c.set_ylim(-0.5, 3.6)
    c.set_xlabel("Grant-rate difference (pp)", fontsize=9)
    c.spines["left"].set_visible(False)
    s.zero(c, "v")
    s.finish(c, "x")
    fig.text(0.105, 0.435, "C. Roughly equal minus better positions", fontsize=10)
    return fig


def merit(d):
    fig = plt.figure(figsize=(5.9, 4.0))
    a = fig.add_axes([0.11, 0.365, 0.585, 0.49])
    b = fig.add_axes([0.80, 0.365, 0.175, 0.49], sharey=a)
    h = fig.add_axes([0.11, 0.14, 0.585, 0.135], sharex=a)
    settings = [
        ("primary_competitive_late", s.BLUE, "-", 1.25),
        ("competitive_late_clocks", s.RUST, (0, (5, 3)), 1.0),
        ("competitive_late_rating", s.GREY, (0, (1, 2)), 1.2),
    ]
    for model, color, ls, lw in settings:
        r = sorted(
            [x for x in d["curves"] if x["model"] == model], key=lambda x: x["cp"]
        )
        a.plot(
            col(r, "cp"),
            col(r, "estimate"),
            color=color,
            ls=ls,
            lw=lw,
            label=r[0]["label"],
            zorder=4,
        )
        if model == "primary_competitive_late":
            a.fill_between(
                col(r, "cp"),
                col(r, "lo"),
                col(r, "hi"),
                color=s.BLUE,
                alpha=0.15,
                lw=0,
                zorder=2,
            )
    a.set_ylim(1, 5.2)
    a.set_yticks([1, 2, 3, 4, 5])
    a.set_xlim(-100, 600)
    a.tick_params(axis="x", labelbottom=False)
    a.set_ylabel("Adjusted grant rate (%)")
    a.legend(loc="upper left", handlelength=2.5, labelspacing=0.35)
    s.title(a, "A", "Competitive positions after ply 10")
    s.finish(a)
    ci(b, d["tails"], x=np.arange(2))
    b.set_xticks([0, 1], ["Finite\n≥ 600", "Positive\nmate"])
    for i, r in enumerate(d["tails"]):
        b.text(i, r["hi"] + 0.13, f"{r['estimate']:.2f}", ha="center", fontsize=8.5)
    b.set_xlim(-0.5, 1.5)
    b.tick_params(axis="y", labelleft=False)
    b.tick_params(axis="x", length=0, labelsize=8)
    s.title(b, "B", "Upper tail")
    s.finish(b)
    h.bar(
        col(d["support"], "cp") + 25,
        col(d["support"], "n") / 1e6,
        width=48,
        color="#b5b5b5",
        zorder=3,
    )
    h.set_xticks([-100, 0, 100, 200, 300, 400, 500, 600])
    h.set_ylim(0, 2.15)
    h.set_yticks([0, 1, 2])
    h.set_ylabel("Opportunities\n(millions)", fontsize=8)
    h.set_xlabel("Rival's evaluation (centipawns)")
    s.finish(h)
    return fig


def relative_strength(d):
    fig = plt.figure(figsize=(5.9, 6.2))
    a = fig.add_axes([0.125, 0.72, 0.845, 0.178])
    b = fig.add_axes([0.125, 0.387, 0.845, 0.1605])
    c = fig.add_axes([0.245, 0.089, 0.225, 0.132])
    e = fig.add_axes([0.74, 0.089, 0.23, 0.132])
    rows = d["gap"]
    a.plot(col(rows, "x"), col(rows, "estimate"), color=s.BLUE, lw=0.65, zorder=3)
    nonref = [r for r in rows if not r["reference"]]
    ci(a, nonref, x=col(nonref, "x"), markersize=3)
    a.plot(
        [0],
        [0],
        marker="D",
        mfc="white",
        mec=s.INK,
        ms=4,
        zorder=6,
        ls="none",
        label="Reference bin",
    )
    a.set_xlim(-590, 590)
    a.set_xticks([-500, -250, 0, 250, 500])
    a.set_ylim(-2.65, 3.65)
    a.set_yticks([-2, 0, 2])
    a.set_xlabel("Displayed rating gap: rival minus chooser", labelpad=3)
    a.set_ylabel("Grant-rate difference\n(pp)", labelpad=5)
    a.legend(loc="upper left", fontsize=8.5)
    s.zero(a)
    s.finish(a)
    s.title(a, "A", "Adjusted differences by rating gap")
    for side, dx, color, marker, label in [
        ("weaker", -0.065, s.BLUE, "o", "Weaker rival"),
        ("stronger", 0.065, s.RUST, "s", "Stronger rival"),
    ]:
        r = [
            next(x for x in d["within"] if x["band"] == band and x["side"] == side)
            for band in ["m100_p100", "p100_p300", "p300_p600"]
        ]
        ci(
            b,
            r,
            x=np.arange(3) + dx,
            color=color,
            marker=marker,
            mfc="white" if side == "stronger" else color,
            label=label,
        )
    b.set_xticks(range(3), ["[−100, 100)", "[100, 300)", "[300, 600]"])
    b.set_xlim(-0.5, 2.5)
    b.set_ylim(-0.9, 1.12)
    b.set_yticks([-0.5, 0, 0.5, 1])
    b.set_ylabel("Within-account\ndifference (pp)")
    b.set_xlabel("Rival's evaluation (centipawns)", labelpad=3)
    b.legend(
        loc="lower left",
        bbox_to_anchor=(0, 1.13),
        borderaxespad=0,
        ncol=2,
        fontsize=8.5,
        handletextpad=0.4,
        columnspacing=1.8,
    )
    s.zero(b)
    s.finish(b)
    fig.text(
        0.125,
        0.621,
        "B. Within-account differences relative to near-equal rivals",
        fontsize=10,
    )
    ci(c, d["adjacent"], y=[1, 0], horizontal=True)
    c.set_yticks([1, 0], [r["label"] for r in d["adjacent"]])
    c.tick_params(axis="y", length=0)
    c.set_xlim(-0.2, 0.2)
    c.set_xticks([-0.2, 0, 0.2])
    c.set_ylim(-0.65, 1.65)
    c.set_xlabel("Grant-rate difference (pp)", fontsize=8.5)
    s.zero(c, "v")
    s.finish(c, "x")
    c.spines["left"].set_visible(False)
    ci(e, d["slopes"], y=[2, 1, 0], horizontal=True)
    e.set_yticks([2, 1, 0], [r["label"] for r in d["slopes"]])
    e.tick_params(axis="y", length=0)
    e.set_xlim(-0.48, 0.72)
    e.set_xticks([-0.4, 0, 0.4])
    e.set_ylim(-0.55, 2.55)
    e.set_xlabel("pp per rating point\nof signed draw payoff", fontsize=8.5)
    s.zero(e, "v")
    s.finish(e, "x")
    e.spines["left"].set_visible(False)
    fig.text(0.125, 0.2725, "C. Adjacent ratings", fontsize=10)
    fig.text(0.585, 0.2725, "D. Local payoff slopes", fontsize=10)
    return fig


def first_stage(d):
    fig = plt.figure(figsize=(5.9, 3.45))
    a = fig.add_axes([0.11, 0.23, 0.385, 0.61])
    b = fig.add_axes([0.605, 0.23, 0.365, 0.61])
    for ax, rows, xlim, ylim, letter, title in [
        (a, d["iv"]["bins"], (-0.65, 3.15), (-5, 26), "A", "All twenty bins"),
        (b, d["iv"]["bins"][:19], (-0.63, 0.67), (-3.5, 4.4), "B", "Bins 1–19"),
    ]:
        ci(ax, rows, x=col(rows, "x"), color=s.INK, markersize=3.5)
        xx = np.array(xlim)
        ax.plot(
            xx, d["iv"]["slope"] * xx, color=s.GREY, ls=(0, (4, 3)), lw=0.9, zorder=1
        )
        ax.set_xlim(*xlim)
        ax.set_ylim(*ylim)
        s.zero(ax)
        s.zero(ax, "v")
        s.finish(ax)
        s.title(ax, letter, title)
    a.set_ylabel("Residual receipt of a draw (pp)")
    a.set_xticks([0, 1, 2, 3])
    b.set_xticks([-0.5, 0, 0.5])
    a.set_yticks([-5, 0, 5, 10, 15, 20, 25])
    b.set_yticks([-3, -2, -1, 0, 1, 2, 3, 4])
    a.annotate(
        "Bin 20",
        xy=(d["iv"]["bins"][-1]["x"], d["iv"]["bins"][-1]["estimate"]),
        xytext=(-8, -13),
        textcoords="offset points",
        ha="right",
        fontsize=8,
    )
    a.annotate(
        "Bin 19",
        xy=(d["iv"]["bins"][-2]["x"], d["iv"]["bins"][-2]["estimate"]),
        xytext=(7, -5),
        textcoords="offset points",
        fontsize=8,
    )
    line = Line2D(
        [],
        [],
        color=s.GREY,
        ls=(0, (4, 3)),
        lw=0.9,
        label=f"Linear first stage: {d['iv']['slope']:.2f} pp per SD",
    )
    fig.legend(
        handles=[line], loc="lower center", bbox_to_anchor=(0.54, 0.025), fontsize=8.5
    )
    fig.text(
        0.54,
        0.108,
        "Residualized opponent score (paper reference SD units)",
        ha="center",
        fontsize=9,
    )
    return fig


def material(d):
    fig, ax = plt.subplots(figsize=(5.9, 3.2))
    fig.subplots_adjust(left=0.11, right=0.97, bottom=0.20, top=0.80)
    for model, color, marker, ls in [
        ("material_competitive_late_base", s.BLUE, "o", "-"),
        ("material_full_late_base", s.RUST, "s", (0, (4, 3))),
    ]:
        r = sorted(
            [r for r in d["material"] if r["model"] == model],
            key=lambda r: r["material"],
        )
        x = np.arange(8)
        ax.plot(x, col(r, "estimate"), color=color, ls=ls, lw=1)
        ci(
            ax,
            r,
            x=x,
            color=color,
            marker=marker,
            mfc="white" if marker == "s" else color,
            label=r[0]["label"],
        )
    ax.set_xticks(range(8), ["≤ −2", "−1", "0", "1", "2", "3", "4", "≥ 5"])
    ax.set_xlabel("Rival minus chooser material (pawn equivalents)")
    ax.set_ylabel("Adjusted grant rate (%)")
    ax.set_ylim(0, 5.05)
    ax.set_yticks(range(6))
    ax.set_xlim(-0.3, 7.3)
    ax.legend(
        loc="lower left",
        bbox_to_anchor=(0, 1.01),
        ncol=2,
        handlelength=2,
        borderaxespad=0,
        columnspacing=2,
    )
    s.finish(ax)
    return fig


def time_profile(d):
    fig = plt.figure(figsize=(5.9, 4.75))
    a = fig.add_axes([0.11, 0.60, 0.86, 0.265])
    b = fig.add_axes([0.11, 0.14, 0.46, 0.28])
    c = fig.add_axes([0.705, 0.14, 0.265, 0.28], sharey=b)
    ci(a, d["receipt"], x=np.arange(5))
    a.set_xticks(range(5), ["0–6 h", "6 h–1 d", "1–7 d", "7–30 d", "30–90 d"])
    a.set_xlim(-0.5, 4.5)
    a.set_ylim(0, 3.15)
    a.set_yticks([0, 1, 2, 3])
    a.set_ylabel("Receipt association (pp)")
    a.set_xlabel("Interval since exposure")
    s.zero(a)
    s.finish(a)
    s.title(a, "A", "Granting after receiving a draw")
    for ax, rows, labels in [
        (b, d["concentration"], ["Within\n6 h", "Within\n24 h", "Within\n7 d"]),
        (c, d["sessions"], ["Same\nsession", "Other\nsessions"]),
    ]:
        x = np.arange(len(rows))
        ax.plot(
            x - 0.065,
            col(rows, "observed"),
            ls="none",
            marker="o",
            color=s.INK,
            ms=3.7,
            zorder=4,
        )
        s.errorbar(
            ax,
            x + 0.065,
            col(rows, "benchmark"),
            col(rows, "lo"),
            col(rows, "hi"),
            color=s.RUST,
            marker="s",
            mfc="white",
            ms=3.6,
        )
        ax.set_xticks(x, labels)
        ax.set_xlim(-0.5, len(rows) - 0.5)
        ax.set_ylim(30, 56)
        ax.set_yticks([30, 40, 50, 55])
        ax.tick_params(axis="x", length=0)
        s.finish(ax)
    b.set_ylabel("Grant rate (%)")
    c.tick_params(axis="y", labelleft=False)
    s.title(b, "B", "After the first observed grant")
    s.title(c, "C", "Within seven days")
    handles = [
        Line2D([], [], marker="o", color=s.INK, ls="none", label="Observed"),
        Line2D(
            [],
            [],
            marker="s",
            mfc="white",
            color=s.RUST,
            ls="none",
            label="Conditional benchmark",
        ),
    ]
    fig.legend(
        handles=handles,
        loc="lower center",
        bbox_to_anchor=(0.54, 0.013),
        ncol=2,
        handletextpad=0.4,
        columnspacing=1.8,
    )
    return fig


REGISTRY = {
    "figure_2_board_stage": (
        "Figure 2. Board position, game stage, and equality",
        board_stage,
    ),
    "figure_3_evaluation": (
        "Figure 3. Granting and the rival’s board advantage",
        merit,
    ),
    "figure_4_relative_strength": (
        "Figure 4. Relative strength and rating consequences",
        relative_strength,
    ),
    "figure_5_first_stage": ("Figure 5. Receipt and the opponent’s score", first_stage),
    "figure_S1_1_material": (
        "Figure S1.1. The material profile after ply ten",
        material,
    ),
    "figure_S3_1_time": ("Figure S3.1. The time profile of granting", time_profile),
}
