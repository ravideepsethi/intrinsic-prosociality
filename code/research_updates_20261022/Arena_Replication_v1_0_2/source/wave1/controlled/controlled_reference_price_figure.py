#!/usr/bin/env python3
"""Rebuild the controlled draw-payoff figure from a completed v1.1.0 run.

All local points and fitted lines use the same opportunity-level model.
Private rows are read in batches; only aggregate results are exported.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import time

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import MaxNLocator, FormatStrFormatter
import numpy as np
import pandas as pd

import reference_price_model_v110 as engine

VERSION = "1.1.1"
ENGINE_SHA256 = "a7cb4e723599705e3aae7416431d5b46fad27ea0bbd8a92671f1390f132b178f"
PRICE_TERMS = ["left", "right", "jump", "tie"]
Z95 = engine.Z95


def local_bin_codes(r: np.ndarray, bandwidth: float, width: float) -> np.ndarray:
    if not np.all(np.isfinite(r)) or np.any(np.abs(r) >= bandwidth):
        raise ValueError("Local cache must contain finite actual draw payoffs with |r_G| < h.")
    sides = int(round(bandwidth / width))
    codes = np.full(len(r), sides, dtype=int)
    negative, positive = r < 0, r > 0
    codes[negative] = np.clip(np.floor((r[negative] + bandwidth) / width).astype(int), 0, sides - 1)
    codes[positive] = sides + 1 + np.clip(np.floor(r[positive] / width).astype(int), 0, sides - 1)
    return codes


def payoff_design(r: np.ndarray) -> np.ndarray:
    return np.column_stack((r * (r < 0), r * (r > 0), r > 0, r == 0)).astype(float)


def build_local_plot_data(factory, model: dict, bandwidth: float = 1.0,
                          width: float = 0.25, design_builder=engine.make_local_design):
    """Binned partial residuals with chooser-clustered linear-functional SEs.

    a_i = ybar + u_i + g_i beta_price - mean(g) beta_price.
    The payoff coordinate is the bin mean of the original r_i, never a residual.
    Confidence intervals condition on the sample design and ybar normalization.
    See METHOD_NOTE.md for the influence-function derivation.
    """
    spec = engine.bin_spec(bandwidth, width)
    bin_count = len(spec["rows"])
    names, beta = model["names"], model["beta"]
    if names[:4] != PRICE_TERMS:
        raise ValueError("Expected the frozen local price design in its original order.")
    p = len(names)
    kept = np.asarray(model["kept"], dtype=int)
    count = np.zeros(bin_count, dtype=np.int64)
    r_sum = np.zeros(bin_count)
    y_sum = np.zeros(bin_count)
    residual_sum = np.zeros(bin_count)
    g_sum = np.zeros((bin_count, 4))
    xwithin_sum = np.zeros((bin_count, p))
    gram = np.zeros((p, p))
    payoff_score = np.zeros(4)
    totals = {"n": 0, "n_fe": 0, "clusters": 0}

    print("Building local adjusted bins from the local model residuals.", flush=True)
    for frame in factory():
        x, current_names = design_builder(frame)
        if current_names != names:
            raise RuntimeError("Local design differs from the fitted model.")
        xw, yw, _, stats = engine.within_transform(frame, x)
        u = yw - xw[:, kept] @ beta[kept]
        r = frame["r"].to_numpy(float)
        y = frame["y"].to_numpy(float)
        if not np.all(np.isin(y, [0.0, 100.0])):
            raise ValueError("Outcome must be coded 0 or 100 percentage points.")
        codes = local_bin_codes(r, bandwidth, width)
        g = payoff_design(r)
        if not np.array_equal(g, x[:, :4]):
            raise AssertionError("Actual draw payoff differs from the model price columns.")
        gram += xw.T @ xw
        count += np.bincount(codes, minlength=bin_count)
        r_sum += np.bincount(codes, weights=r, minlength=bin_count)
        y_sum += np.bincount(codes, weights=y, minlength=bin_count)
        residual_sum += np.bincount(codes, weights=u, minlength=bin_count)
        for b in range(bin_count):
            mask = codes == b
            g_sum[b] += g[mask].sum(axis=0)
            xwithin_sum[b] += xw[mask].sum(axis=0)
        payoff_score += g.T @ u
        for key in totals:
            totals[key] += stats[key]
    if np.any(count == 0):
        raise RuntimeError("A local payoff bin is empty; the fixed figure specification cannot be drawn.")
    for key, value in totals.items():
        if value != model["stats"][key]:
            raise AssertionError(f"Local plotting and fitting samples differ: {key}.")
    n = int(count.sum())
    if not np.isclose(y_sum.sum(), model["stats"]["sum_y"], atol=1e-8, rtol=0):
        raise AssertionError("Local outcome totals differ from the fitted model.")
    ybar = float(y_sum.sum() / n)
    gbar = g_sum.sum(axis=0) / n
    anchor = ybar - float(gbar @ beta[:4])
    adjusted = anchor + g_sum @ beta[:4] / count + residual_sum / count
    mean_r = r_sum / count

    # Same selected inverse as the frozen model, recomputed from its cache.
    scale = np.sqrt(np.diag(gram)[kept])
    gram_scaled = gram[np.ix_(kept, kept)] / np.outer(scale, scale)
    bread_kept = np.linalg.inv(gram_scaled) / np.outer(scale, scale)
    c = -xwithin_sum / count[:, None]
    c[:, :4] += g_sum / count[:, None] - gbar
    c_bread = c[:, kept] @ bread_kept
    bin_meat = np.zeros((bin_count, bin_count))

    print("Computing chooser-clustered uncertainty for the adjusted local bins.", flush=True)
    for frame in factory():
        x, _ = design_builder(frame)
        xw, yw, starts, _ = engine.within_transform(frame, x)
        u = yw - xw[:, kept] @ beta[kept]
        codes = local_bin_codes(frame["r"].to_numpy(float), bandwidth, width)
        scores = np.add.reduceat(xw[:, kept] * u[:, None], starts, axis=0)
        bin_u = np.column_stack([
            np.add.reduceat(np.where(codes == b, u, 0.0), starts) / count[b]
            for b in range(bin_count)
        ])
        influence = bin_u + scores @ c_bread.T
        bin_meat += influence.T @ influence
    bin_cov = model["cr1"] * bin_meat
    bin_cov = (bin_cov + bin_cov.T) / 2
    if np.any(np.diag(bin_cov) < -1e-10):
        raise ArithmeticError("Negative local-bin variance.")
    se = np.sqrt(np.maximum(0.0, np.diag(bin_cov)))
    table = pd.DataFrame(spec["rows"])
    table["payoff_mean"] = mean_r
    table["n"] = count
    table["adjusted_rate_pct"] = adjusted
    table["clustered_se_pp"] = se
    table["ci95_low_pct"] = adjusted - Z95 * se
    table["ci95_high_pct"] = adjusted + Z95 * se
    table["local_fitted_at_bin_mean_pct"] = anchor + g_sum @ beta[:4] / count
    table["mean_model_residual_pp"] = residual_sum / count
    table["raw_rate_pct_diagnostic_only"] = y_sum / count
    table["normalization"] = "local ybar + local residual + local payoff component - local mean payoff component"
    table["horizontal_axis"] = "bin mean of actual chooser draw payoff r_G in rating points"
    grid = make_local_fit_grid(model, bandwidth, ybar, gbar)
    zero = int(spec["zero_code"])
    exact_fit = grid.loc[grid["side"] == "zero"].iloc[0]
    checks = {
        "local_sample": totals,
        "local_mean_outcome_pct": ybar,
        "local_mean_price_design": gbar,
        "display_anchor_pct": anchor,
        "weighted_adjusted_mean_error_pp": float(np.average(adjusted, weights=count) - ybar),
        "max_price_normal_equation_per_row": float(np.max(np.abs(payoff_score)) / n),
        "exact_zero_point_minus_fit_pp": float(adjusted[zero] - exact_fit["fitted_rate_pct"]),
        "exact_zero_se_minus_fit_se_pp": float(se[zero] - exact_fit["clustered_se_pp"]),
        "local_bin_count": bin_count,
        "x_is_actual_payoff_bin_mean": True,
        "adjustment_model_is_local_fit": True,
        "bin_and_fit_uncertainty_conditions_on_display_normalization": True,
    }
    if abs(checks["weighted_adjusted_mean_error_pp"]) > 1e-7:
        raise AssertionError("Local adjusted values do not have the local sample mean.")
    if checks["max_price_normal_equation_per_row"] > 1e-7:
        raise AssertionError("Local residuals fail the price normal equations.")
    if abs(checks["exact_zero_point_minus_fit_pp"]) > 1e-6:
        raise AssertionError("The exact-zero adjusted dot and fitted level disagree.")
    if not np.isclose(se[zero], exact_fit["clustered_se_pp"], rtol=2e-5, atol=1e-7):
        raise AssertionError("The exact-zero bin and fitted uncertainty disagree.")
    return table, grid, bin_cov, checks


def make_local_fit_grid(model: dict, bandwidth: float, ybar: float, gbar: np.ndarray) -> pd.DataFrame:
    # Include the one-sided limits at x=0 without treating them as zero-payoff observations.
    loss_r = np.linspace(-bandwidth, 0, 161)
    gain_r = np.linspace(0, bandwidth, 161)
    r = np.r_[loss_r, 0.0, gain_r]
    side = np.array(["loss"] * len(loss_r) + ["zero"] + ["gain"] * len(gain_r))
    g = np.zeros((len(r), 4))
    g[side == "loss", 0] = r[side == "loss"]
    g[side == "gain", 1] = r[side == "gain"]
    g[side == "gain", 2] = 1
    g[side == "zero", 3] = 1
    vectors = g - gbar
    fitted = ybar + vectors @ model["beta"][:4]
    variance = np.einsum("ij,jk,ik->i", vectors, model["covariance"][:4, :4], vectors)
    if np.any(variance < -1e-9):
        raise ArithmeticError("Negative fitted-curve variance.")
    se = np.sqrt(np.maximum(0, variance))
    return pd.DataFrame({
        "r_G": r, "side": side, "fitted_rate_pct": fitted,
        "clustered_se_pp": se, "ci95_low_pct": fitted - Z95 * se,
        "ci95_high_pct": fitted + Z95 * se,
        "display_anchor_pct": ybar - float(gbar @ model["beta"][:4]),
    })


def verify_manifest(root: Path) -> dict[str, str]:
    manifest = root / "OUTPUT_MANIFEST.sha256"
    expected = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            raise RuntimeError(f"Invalid source manifest entry: {relative}")
        if engine.sha256(path) != digest:
            raise RuntimeError(f"Source checksum failed: {relative}")
        if relative in expected:
            raise RuntimeError("Duplicate source manifest entry.")
        expected[relative] = digest
    return expected


def validate_source(source: Path, allow_synthetic: bool) -> tuple[dict, dict]:
    checksums = verify_manifest(source)
    needed = ["receipts/completion_receipt.json", "receipts/executed_controlled_reference_price_figure.py",
              "tables/controlled_reference_price_bins.csv", "tables/controlled_local_h1_coefficients.csv"]
    if not set(needed).issubset(checksums):
        raise RuntimeError("Required source outputs are not covered by its manifest.")
    receipt = json.loads((source / needed[0]).read_text(encoding="utf-8"))
    if receipt["version"] != "1.1.0" or receipt["status"] != "CONTROLLED_REFERENCE_PRICE_FIGURE_COMPLETE":
        raise RuntimeError("This display correction requires a completed v1.1.0 run.")
    synthetic = bool(receipt.get("synthetic_smoke_test"))
    if synthetic != allow_synthetic:
        raise RuntimeError("Synthetic source requires --synthetic-validation; production source forbids it.")
    if checksums[needed[1]] != ENGINE_SHA256 or receipt["code_sha256"] != ENGINE_SHA256:
        raise RuntimeError("Source model code does not match the frozen v1.1.0 engine.")
    if engine.sha256(Path(engine.__file__)) != ENGINE_SHA256:
        raise RuntimeError("Bundled frozen model code checksum failed.")
    settings = receipt["settings"]
    for key, value in {"payoff_limit": 5.0, "bin_width": 0.25, "local_bandwidth": 1.0}.items():
        if settings[key] != value:
            raise RuntimeError(f"Unexpected source specification: {key}.")
    if not synthetic:
        if receipt["authentication"]["status"] != "LOCAL_H1_BRIDGE_AUTHENTICATED":
            raise RuntimeError("Source lacks the authenticated local data bridge.")
        for key in ["n", "n_fe", "clusters", "kinds"]:
            if receipt["local_model"]["stats"][key] != engine.AUTHORITY[f"local_h1_{key}"]:
                raise RuntimeError(f"Unexpected production local sample: {key}.")
    return receipt, checksums


def authenticate_refit(source: Path, receipt: dict, model: dict, contrasts: dict) -> dict:
    old = pd.read_csv(source / "tables/controlled_local_h1_coefficients.csv").set_index("term")
    new = engine.coefficient_table(model).set_index("term")
    if list(old.index) != list(new.index) or model["dropped"] != receipt["local_model"]["dropped_terms"]:
        raise RuntimeError("Refitted control columns differ from the completed run.")
    for key, value in receipt["local_model"]["stats"].items():
        if model["stats"][key] != value:
            raise RuntimeError(f"Refitted sample differs from the completed run: {key}.")
    old_values = old[["estimate", "clustered_se"]].to_numpy(float)
    new_values = new[["estimate", "clustered_se"]].to_numpy(float)
    difference = np.abs(new_values - old_values)
    if not np.allclose(old_values, new_values, rtol=2e-6, atol=2e-6):
        raise RuntimeError(f"Refitted coefficients/SEs differ; maximum absolute discrepancy {difference.max():.6g}.")
    for name, values in receipt["local_model"]["contrasts"].items():
        for key in ["estimate", "se", "ci95_low", "ci95_high"]:
            if not np.isclose(contrasts[name][key], values[key], rtol=2e-6, atol=2e-6):
                raise RuntimeError(f"Refitted contrast differs: {name}/{key}.")
    return {"status": "V110_LOCAL_MODEL_REPRODUCED", "coefficient_count": len(new),
            "max_absolute_coefficient_or_se_difference": float(difference.max()),
            "absolute_tolerance": 2e-6, "relative_tolerance": 2e-6,
            "all_sample_totals_identical": True, "all_retained_and_dropped_terms_identical": True}


def figure_style() -> None:
    engine.configure_figure_style()
    mpl.rcParams.update({"font.size": 8, "axes.labelsize": 8.3, "axes.titlesize": 8.7,
                         "xtick.labelsize": 7.5, "ytick.labelsize": 7.5,
                         "legend.fontsize": 7.3, "svg.hashsalt": "controlled-payoff-v111"})


def format_axis(ax, bandwidth: float) -> None:
    ax.axvline(0, color="#737B83", lw=0.8, ls=(0, (3, 3)), zorder=0)
    ax.grid(axis="y", color="#E6E9EC", linewidth=0.55, zorder=0)
    ax.set_axisbelow(True)
    ax.set_xlabel(r"Draw payoff, $r_G$ (rating points)", labelpad=6)
    ax.set_ylabel("Adjusted kind-draw rate (%)", labelpad=6)
    ax.set_xlim(-bandwidth * 1.025, bandwidth * 1.025)
    ax.set_xticks(np.linspace(-bandwidth, bandwidth, 5))
    ax.yaxis.set_major_locator(MaxNLocator(nbins=5, min_n_ticks=4))
    ax.yaxis.set_major_formatter(FormatStrFormatter("%.1f"))
    ax.tick_params(length=3, width=0.65)


def draw_local(ax, bins: pd.DataFrame, fit: pd.DataFrame, bandwidth: float):
    blue, ink = "#0072B2", "#242B32"
    format_axis(ax, bandwidth)
    nonzero, zero = bins.loc[~bins["exact_zero"]], bins.loc[bins["exact_zero"]]
    ax.errorbar(nonzero["payoff_mean"], nonzero["adjusted_rate_pct"],
                yerr=Z95 * nonzero["clustered_se_pp"], fmt="o", color=blue,
                ecolor=blue, elinewidth=0.75, capsize=2.0, ms=4.1,
                markerfacecolor="white", markeredgewidth=0.95, zorder=4)
    ax.errorbar(zero["payoff_mean"], zero["adjusted_rate_pct"],
                yerr=Z95 * zero["clustered_se_pp"], fmt="D", color=ink,
                ecolor=ink, elinewidth=0.8, capsize=2.0, ms=4.3,
                markerfacecolor="white", markeredgewidth=0.95, zorder=5)
    for side, color, style in [("loss", "#D55E00", "-"), ("gain", "#009E73", (0, (4, 2)))]:
        part = fit.loc[fit["side"] == side]
        ax.plot(part["r_G"], part["fitted_rate_pct"], color=color, lw=1.6, ls=style, zorder=3)
    low = min(bins["ci95_low_pct"].min(), fit["fitted_rate_pct"].min())
    high = max(bins["ci95_high_pct"].max(), fit["fitted_rate_pct"].max())
    padding = max(0.025, (high - low) * 0.12)
    ax.set_ylim(low - padding, high + padding)
    return [
        Line2D([0], [0], color=blue, marker="o", mfc="white", ms=4, lw=0, label="Adjusted local bins (95% CI)"),
        Line2D([0], [0], color=ink, marker="D", mfc="white", ms=4, lw=0, label="Exact zero payoff"),
        Line2D([0], [0], color="#D55E00", lw=1.6, label="Loss-side fit"),
        Line2D([0], [0], color="#009E73", lw=1.6, ls=(0, (4, 2)), label="Gain-side fit"),
    ]


def draw_broad(ax, bins: pd.DataFrame, limit: float, bandwidth: float) -> None:
    format_axis(ax, limit)
    ax.axvspan(-bandwidth, bandwidth, color="#F2F4F6", zorder=0)
    for exact, marker, color, size in [(False, "o", "#0072B2", 2.8), (True, "D", "#242B32", 4.0)]:
        part = bins.loc[bins["exact_zero"] == exact]
        ax.errorbar(part["payoff_center"], part["adjusted_rate_pct"],
                    yerr=Z95 * part["clustered_se_pp"], fmt=marker, color=color,
                    ecolor=color, elinewidth=0.6, capsize=1.1, ms=size,
                    markerfacecolor="white", markeredgewidth=0.7, zorder=3)
    low, high = bins["ci95_low_pct"].min(), bins["ci95_high_pct"].max()
    padding = max(0.03, (high - low) * 0.12)
    ax.set_ylim(low - padding, high + padding)


def save_figure(figure, root: Path, stem: str, synthetic: bool) -> list[Path]:
    if synthetic:
        figure.text(0.5, 0.52, "SYNTHETIC VALIDATION — NOT PAPER DATA", ha="center",
                    va="center", rotation=12, fontsize=12, color="#9A1B1B", alpha=0.25,
                    transform=figure.transFigure, zorder=20)
    paths = [root / (stem + ext) for ext in [".pdf", ".png", ".svg"]]
    meta = {"Title": "Controlled draw-payoff profile: consistent local adjustment",
            "Author": "Intrinsic Prosociality figure build", "Creator": f"controlled_reference_price_figure.py v{VERSION}"}
    figure.savefig(paths[0], metadata=meta)
    figure.savefig(paths[1], dpi=600, metadata={"Software": meta["Creator"]})
    figure.savefig(paths[2], metadata={"Creator": meta["Creator"]})
    plt.close(figure)
    return paths


def draw_figures(broad_bins, local_bins, fit, root: Path, synthetic: bool) -> list[Path]:
    figure_style()
    root.mkdir(parents=True, exist_ok=True)
    # The standalone local figure is the paper-facing fitted figure.
    figure, ax = plt.subplots(figsize=(6.0, 3.65))
    handles = draw_local(ax, local_bins, fit, 1.0)
    figure.subplots_adjust(left=0.115, right=0.985, bottom=0.285, top=0.96)
    figure.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.53, 0.025),
                  ncol=2, columnspacing=2.8, handlelength=2.7, labelspacing=0.7)
    outputs = save_figure(figure, root, "figure_controlled_draw_payoff_local", synthetic)
    # Separate model/sample labels make clear this is not a magnification of A.
    combined, (a, b) = plt.subplots(1, 2, figsize=(7.0, 3.72))
    draw_broad(a, broad_bins, 5.0, 1.0)
    draw_local(b, local_bins, fit, 1.0)
    a.set_title("A. Broad adjusted profile", loc="left", pad=17)
    b.set_title("B. Local adjusted data and fit", loc="left", pad=17)
    for ax, window, n in [(a, 5, int(broad_bins["n"].sum())), (b, 1, int(local_bins["n"].sum()))]:
        ax.text(0, 1.015, rf"$|r_G|<{window}$; $N={n:,}$", transform=ax.transAxes,
                ha="left", va="bottom", fontsize=7.0, color="#66717B")
    combined.subplots_adjust(left=0.084, right=0.982, bottom=0.27, top=0.86, wspace=0.30)
    handles[0].set_label("Adjusted bins (95% CI)")
    combined.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.52, 0.01),
                    ncol=2, columnspacing=2.8, handlelength=2.7, labelspacing=0.6)
    outputs += save_figure(combined, root, "figure_controlled_reference_price", synthetic)
    return outputs


def write_captions(out: Path) -> None:
    controls = r"""The opportunity-level linear probability model includes chooser-by-speed-pool
fixed effects, continuous piecewise-linear splines in the displayed rating gap
and expected-score imbalance (with no knot at zero), a spline in the log
forgone-win premium, game-stage bands, both players' rating deviations, board
evaluation, chooser rating, both clocks and missing-clock indicators, month,
and tournament status."""
    local = r"""\caption{\textbf{Kindness and the reference-dependent draw payoff near zero.}
The horizontal axis is the chooser's actual draw payoff,
$r_G=K(1/2-E)$, in rating points. The sample comprises competitive positions
(chooser-oriented board evaluation at least $-100$ centipawns) with $|r_G|<1$,
using the established complete-case and non-singleton chooser-by-pool sample.
CONTROLS
Circles are means of adjusted observations in 0.25-point payoff bins,
positioned at the within-bin mean of actual $r_G$; the diamond denotes exact
zero payoff. Each adjusted observation equals the residual from the local
model plus its fitted payoff component, centered and shifted so the sample
mean equals the observed local kind-draw rate. Lines are the separate loss-
and gain-side payoff components from that same model and normalization.
The model allows a level difference between sides and a separate exact-zero
level; neither line is connected to the zero-payoff point. Bars are pointwise
95\% chooser-clustered CR1 intervals that account for estimated controls and
fixed effects, conditional on the finite model and the sample-mean display
normalization. These binned partial residuals visualize the specified local
model; they do not independently estimate an unrestricted dose-response
function. Estimates are conditional associations, not causal elasticities.}
""".replace("CONTROLS", controls)
    (out / "CAPTION_LOCAL.tex").write_text(local, encoding="utf-8")
    combined = r"""\caption{\textbf{Controlled draw-payoff profiles.}
The horizontal axis is the chooser's draw payoff, $r_G=K(1/2-E)$, in rating
points. Panel A reports the existing jointly estimated 0.25-point payoff-bin
effects on the $|r_G|<5$ sample, centered at that sample's mean outcome.
Exact zero is estimated separately. The shaded range marks $|r_G|<1$.
Panel B uses its own $|r_G|<1$ sample and local-model adjustment: points are
binned partial residuals (residual plus fitted payoff component, centered at
the local outcome mean), plotted against actual mean draw payoff in each bin.
Separate loss- and gain-side lines use that same local model and normalization.
Panel B is not a magnification of Panel A; its controls are estimated in the
local sample. CONTROLS
Bars are pointwise 95\% chooser-clustered CR1 intervals conditional on each
finite model and sample-mean display normalization. The exact-zero local
estimate is displayed once. These are conditional associations under the
specified relative-strength adjustment, not causal price elasticities.}
""".replace("CONTROLS", controls)
    (out / "CAPTION_DRAFT.tex").write_text(combined, encoding="utf-8")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--source-private", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--memory", default="8GB")
    parser.add_argument("--batch-rows", type=int, default=32768)
    parser.add_argument("--synthetic-validation", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 1 <= args.threads <= 10 or args.batch_rows < 4096:
        raise SystemExit("Require 1-10 threads and batch-rows >= 4096.")
    paths = [getattr(args, key).resolve() for key in ["source_run", "source_private", "out", "scratch"]]
    for i, p in enumerate(paths):
        for q in paths[i + 1:]:
            if p.is_relative_to(q) or q.is_relative_to(p):
                raise SystemExit("Source run, source cache, output, and scratch directories must be disjoint.")
    for path in [args.out, args.scratch, Path(str(args.out) + ".zip"), Path(str(args.out) + ".zip.sha256")]:
        if path.exists():
            raise SystemExit(f"Choose a fresh run ID; destination already exists: {path}")
    started = time.monotonic()
    started_at = engine.utc_now()
    print(f"CONTROLLED_REFERENCE_PRICE_FIX_START version={VERSION} at {started_at}", flush=True)
    receipt, checksums = validate_source(args.source_run, args.synthetic_validation)
    cache = args.source_private / "controlled_reference_price_local_h1_private.parquet"
    if not cache.is_file():
        raise FileNotFoundError(f"Existing private local cache is required: {cache}")
    cache_stat = cache.stat()
    args.out.mkdir(parents=True)
    args.scratch.mkdir(parents=True)
    tables = args.out / "tables"
    tables.mkdir()
    print("Source checksums passed. Refitting the unchanged v1.1.0 local model from cache.", flush=True)
    factory = engine.frame_factory(cache, args.batch_rows, args.memory, args.scratch / "model_spill")
    model = engine.fit_within_model(factory, engine.make_local_design, lambda names: PRICE_TERMS,
                                   "controlled_local_h1_reference_price", must_retain_names=engine.CORE_CONTROLS_REQUIRED)
    results, contrasts = engine.local_summary(model)
    authentication = authenticate_refit(args.source_run, receipt, model, contrasts)
    print("V110_LOCAL_MODEL_REPRODUCED: sample, coefficients, and clustered SEs agree.", flush=True)
    local_bins, fit, local_cov, checks = build_local_plot_data(factory, model)
    if (cache.stat().st_size, cache.stat().st_mtime_ns) != (cache_stat.st_size, cache_stat.st_mtime_ns):
        raise RuntimeError("Source cache changed during the run.")
    # Copy only a fixed aggregate-table allowlist, never a private cache or an old figure.
    reused = []
    for stem in ["controlled_reference_price_bins", "controlled_reference_price_bin_coefficients",
                 "sample_flow", "source_identity_checks", "source_month_inventory",
                 "legacy_v101_bridge_h1_results", "legacy_v101_bridge_h1_coefficients"]:
        for suffix in [".csv", ".parquet"]:
            rel = "tables/" + stem + suffix
            if rel in checksums:
                shutil.copy2(args.source_run / rel, tables / (stem + suffix))
                reused.append(rel)
    broad_bins = pd.read_csv(tables / "controlled_reference_price_bins.csv")
    if int(broad_bins["n"].sum()) != receipt["bin_model"]["stats"]["n"]:
        raise RuntimeError("Source broad-bin counts disagree with the completed receipt.")
    engine.export_frame(local_bins, tables, "controlled_local_h1_adjusted_bins")
    engine.export_frame(fit, tables, "controlled_local_h1_display_fit")
    engine.export_frame(results, tables, "controlled_local_h1_results")
    engine.export_frame(engine.coefficient_table(model), tables, "controlled_local_h1_coefficients")
    covariance_rows = pd.DataFrame([
        {"row_bin_code": i, "column_bin_code": j, "covariance_pp2": float(local_cov[i, j])}
        for i in range(len(local_bins)) for j in range(len(local_bins))])
    engine.export_frame(covariance_rows, tables, "controlled_local_h1_adjusted_bin_covariance")
    outputs = draw_figures(broad_bins, local_bins, fit, args.out / "figures", args.synthetic_validation)
    write_captions(args.out)
    receipts = args.out / "receipts"
    receipts.mkdir()
    shutil.copy2(args.source_run / "receipts/completion_receipt.json", receipts / "source_v110_completion_receipt.json")
    shutil.copy2(Path(__file__), receipts / "executed_controlled_reference_price_figure.py")
    shutil.copy2(Path(engine.__file__), receipts / "reference_price_model_v110.py")
    engine.write_json(receipts / "local_plot_consistency_checks.json", checks)
    new_receipt = {
        "version": VERSION, "status": "CONTROLLED_REFERENCE_PRICE_FIX_COMPLETE",
        "synthetic_validation": args.synthetic_validation,
        "started_at": started_at, "completed_at": engine.utc_now(),
        "elapsed_seconds": time.monotonic() - started,
        "source_run": str(args.source_run.resolve()), "source_private_cache": str(cache.resolve()),
        "source_cache_bytes": cache_stat.st_size, "source_cache_mtime_ns": cache_stat.st_mtime_ns,
        "source_manifest_sha256": engine.sha256(args.source_run / "OUTPUT_MANIFEST.sha256"),
        "source_files_verified": len(checksums), "reused_aggregate_tables": reused,
        "local_model_authentication": authentication, "local_model_stats": model["stats"],
        "local_model_contrasts": contrasts, "local_plot_checks": checks,
        "scientific_specification_changed": False,
        "local_adjusted_data": "local model residual + local payoff component, centered at local outcome mean",
        "horizontal_axis": "actual chooser draw payoff r_G, in rating points; local dots at bin means",
        "private_rows_exported": False, "private_cache_modified": False,
        "settings": {"threads": args.threads, "memory": args.memory, "batch_rows": args.batch_rows,
                     "local_bandwidth": 1.0, "local_bin_width": 0.25},
        "figure_files": [str(p.relative_to(args.out)) for p in outputs],
        "code_sha256": engine.sha256(Path(__file__)), "frozen_model_sha256": ENGINE_SHA256,
        "python": sys.version, "versions": {"numpy": np.__version__, "pandas": pd.__version__,
                                                "matplotlib": mpl.__version__, "duckdb": engine.duckdb.__version__},
    }
    engine.write_json(receipts / "completion_receipt.json", new_receipt)
    engine.write_manifest(args.out)
    archive, sidecar = engine.package_output(args.out)
    print("CONTROLLED_REFERENCE_PRICE_FIX_COMPLETE", flush=True)
    print(f"Elapsed: {time.monotonic() - started:.1f} seconds", flush=True)
    print(f"Paper figure: {args.out / 'figures/figure_controlled_draw_payoff_local.pdf'}", flush=True)
    print(f"ZIP: {archive}\nSHA256: {sidecar}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
