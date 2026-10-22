"""Streaming joint-cell OLS and marginal standardization for two surfaces.

No row-level identifiers, coefficient fitting to historical results, or invented
observations. Raw and adjusted surfaces use exactly the same current-sample rows.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
import numpy as np

VERSION = "1.0.0"
EXPECTED = {"rows": 41534331, "kind_draws": 570091,
            "fair_rows": 15207423, "fair_kind_draws": 419463}
X = "chooser_draw_payoff_v2"
D = "engine_eval_cp_disconnected"
Y = "outcome_kind_draw"
CONTROL_SPECS = (
    ("ply_count", "log1p", 1.0, (2, 5, 10, 20, 40, 80, 160)),
    ("chooser_pre_rd_v2", "log", 50.0, (50, 75, 110, 150, 200, 300)),
    ("disconnected_pre_rd_v2", "log", 50.0, (50, 75, 110, 150, 200, 300)),
    ("chooser_pre_sigma_v2", "log", 0.06, (0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.10)),
    ("disconnected_pre_sigma_v2", "log", 0.06, (0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.10)),
)
CONTROL_COLUMNS = tuple(s[0] for s in CONTROL_SPECS)
READ_COLUMNS = [X, D, Y, "month", *CONTROL_COLUMNS]


def require(ok, message):
    if not bool(ok):
        raise RuntimeError(message)


@dataclass(frozen=True)
class Settings:
    payoff_min: float = -6.0
    payoff_max: float = 6.0
    payoff_step: float = 0.4
    desert_min: float = -600.0
    desert_max: float = 600.0
    desert_step: float = 50.0
    min_cell_n: int = 500
    min_cell_months: int = 6
    batch_rows: int = 65536

    def validate(self):
        for prefix in ("payoff", "desert"):
            lo, hi, step = (getattr(self, prefix + s) for s in ("_min", "_max", "_step"))
            require(np.isfinite([lo, hi, step]).all() and lo < 0 < hi and step > 0,
                    f"Invalid {prefix} grid")
            bins = (hi - lo) / step
            require(abs(bins - round(bins)) < 1e-8 and 4 <= round(bins) <= 100,
                    f"{prefix} grid must have an integer number of 4..100 bins")
        require(self.min_cell_n >= 1 and 1 <= self.min_cell_months <= 24,
                "Invalid support thresholds")
        require(1024 <= self.batch_rows <= 262144, "batch_rows must be 1024..262144")
        require(self.cells <= 11000, "Grid is too large")

    @property
    def xedges(self):
        return np.linspace(self.payoff_min, self.payoff_max,
            round((self.payoff_max - self.payoff_min) / self.payoff_step) + 1)

    @property
    def dedges(self):
        return np.linspace(self.desert_min, self.desert_max,
            round((self.desert_max - self.desert_min) / self.desert_step) + 1)

    @property
    def shape(self):
        return (len(self.dedges) + 1, len(self.xedges) + 1)

    @property
    def cells(self):
        return self.shape[0] * self.shape[1]

    def dictionary(self):
        return asdict(self)


def term_names():
    result = []
    for name, transform, reference, knots in CONTROL_SPECS:
        result.append(f"{name}:{transform}")
        result.extend(f"{name}:hinge_at_{k:g}" for k in knots)
    return result


def controls(values):
    cols = []
    for name, transform, reference, knots in CONTROL_SPECS:
        raw = np.asarray(values[name], dtype=float)
        require(np.isfinite(raw).all(), f"Missing or nonfinite control: {name}")
        if transform == "log1p":
            require((raw >= 0).all(), "Negative ply_count")
            t = np.log1p(raw)
            knots_t = np.log1p(knots)
        else:
            require((raw > 0).all(), f"Nonpositive RD/volatility: {name}")
            t = np.log(raw / reference)
            knots_t = np.log(np.asarray(knots) / reference)
        cols.append(t)
        cols.extend(np.maximum(t - k, 0.0) for k in knots_t)
    return np.column_stack(cols)


def axis_bins(values, edges):
    # Real tails get separate overflow cells. They are never piled onto a
    # displayed edge. Interior cells are [lo, hi), with final upper edge closed.
    bins = np.searchsorted(edges, values, side="right")
    bins[values == edges[-1]] = len(edges) - 1
    return bins


def cell_ids(payoff, desert, settings):
    require(np.isfinite(payoff).all() and np.isfinite(desert).all(),
            "Nonfinite surface coordinate")
    return axis_bins(desert, settings.dedges) * settings.shape[1] + axis_bins(payoff, settings.xedges)


class Moments:
    def __init__(self, settings):
        g, k = settings.cells, len(term_names())
        self.n = np.zeros(g, dtype=np.int64)
        self.events = np.zeros(g, dtype=np.int64)
        self.zsum = np.zeros((g, k))
        self.ztz = np.zeros((k, k))
        self.zty = np.zeros(k)
        self.control_sum = np.zeros((g, len(CONTROL_COLUMNS)))
        self.counts = {key: 0 for key in EXPECTED}

    def add(self, ids, y, z, original_controls, desert):
        g = len(self.n)
        require(np.isin(y, [0, 1]).all(), "Kind-draw outcome is not binary")
        self.n += np.bincount(ids, minlength=g)
        self.events += np.bincount(ids, weights=y, minlength=g).astype(np.int64)
        for j in range(z.shape[1]):
            self.zsum[:, j] += np.bincount(ids, weights=z[:, j], minlength=g)
        self.ztz += z.T @ z
        self.zty += z.T @ y
        for j in range(original_controls.shape[1]):
            self.control_sum[:, j] += np.bincount(ids, weights=original_controls[:, j], minlength=g)
        self.counts["rows"] += len(y)
        self.counts["kind_draws"] += int(y.sum())
        self.counts["fair_rows"] += int((desert >= -100).sum())
        self.counts["fair_kind_draws"] += int(y[desert >= -100].sum())

    def merge(self, other):
        for name in ("n", "events", "zsum", "ztz", "zty", "control_sum"):
            getattr(self, name)[:] += getattr(other, name)
        for key in self.counts:
            self.counts[key] += other.counts[key]

    def arrays(self):
        return {name: getattr(self, name) for name in
                ("n", "events", "zsum", "ztz", "zty", "control_sum")}

    @classmethod
    def restore(cls, settings, arrays, counts):
        obj = cls(settings)
        for name, empty in obj.arrays().items():
            value = np.asarray(arrays[name])
            require(value.shape == empty.shape, f"Checkpoint shape mismatch: {name}")
            require(np.isfinite(value).all(), f"Nonfinite checkpoint: {name}")
            setattr(obj, name, value.copy())
        obj.counts = {key: int(counts[key]) for key in EXPECTED}
        require(int(obj.n.sum()) == obj.counts["rows"] and
                int(obj.events.sum()) == obj.counts["kind_draws"], "Checkpoint totals mismatch")
        return obj


def consume(batch, month, settings, stats):
    values = {}
    for name in READ_COLUMNS:
        c = batch.column(batch.schema.get_field_index(name))
        require(c.null_count == 0, f"Nulls in {name}; raw and adjusted samples must agree")
        values[name] = c.to_numpy(zero_copy_only=False)
    require((values["month"] == month).all(), "Partition month mismatch")
    payoff = np.asarray(values[X], dtype=float)
    desert = np.asarray(values[D], dtype=float)
    y = np.asarray(values[Y], dtype=float)
    z = controls(values)
    ids = cell_ids(payoff, desert, settings)
    raw = np.column_stack([values[name] for name in CONTROL_COLUMNS])
    stats.add(ids, y, z, raw, desert)


def estimate(stats):
    """Exact FWL of joint cell dummies, then standardize to global covariates.

    y_i = a_cell(i) + Z_i b + e_i.
    adjusted_cell = mean(y|cell) + (mean(Z) - mean(Z|cell)) b.
    Binned desert and payoff are included JOINTLY while estimating b.
    """
    n = stats.n
    ok = n > 0
    total = int(n.sum())
    require(total > 1 and ok.sum() > 1, "Insufficient data for surface")
    means = np.zeros_like(stats.zsum)
    means[ok] = stats.zsum[ok] / n[ok, None]
    reference = stats.zsum.sum(axis=0) / total
    covariance = stats.ztz - total * np.outer(reference, reference)
    global_var = np.maximum(np.diag(covariance) / total, 0.0)
    scale = np.sqrt(global_var)
    # Subtracting raw moments leaves tiny positive/negative residues for constant
    # hinge columns. Do not amplify those residues by dividing by a near-zero SD.
    variance_floor = 1e-12 * np.maximum(np.diag(stats.ztz) / total, 1.0)
    active = global_var > variance_floor
    require(active.any(), "Every requested control is constant")
    within = stats.ztz - means[ok].T @ stats.zsum[ok]
    within = (within + within.T) / 2
    rhs = stats.zty - means[ok].T @ stats.events[ok]
    w = within[np.ix_(active, active)] / np.outer(scale[active], scale[active]) / total
    b = rhs[active] / scale[active] / total
    eigenvalues, vectors = np.linalg.eigh(w)
    largest = max(float(eigenvalues.max()), 1e-15)
    require(eigenvalues.min() >= -largest * 1e-7, "Within-cell covariance is not positive semidefinite")
    keep = eigenvalues > largest * 1e-9
    require(keep.any(), "No within-cell control variation")
    standardized_beta = vectors[:, keep] @ ((vectors[:, keep].T @ b) / eigenvalues[keep])
    # Collinear spline columns are harmless only when the standardized surface
    # is invariant to their unidentified coefficient directions.
    contrast = (reference - means[ok])[:, active] / scale[active]
    null_projection = 0.0
    if (~keep).any():
        null_projection = float(np.abs(contrast @ vectors[:, ~keep]).max())
    require(null_projection < 1e-4,
            "Controls are confounded with surface cells: standardized levels are not identified")
    beta = np.zeros_like(reference)
    beta[active] = standardized_beta / scale[active]
    raw = np.full(len(n), np.nan)
    adjusted = raw.copy()
    raw[ok] = stats.events[ok] / n[ok]
    adjusted[ok] = raw[ok] + (reference - means[ok]) @ beta
    require(np.isfinite(adjusted[ok]).all(), "Nonfinite adjusted surface")
    require(abs(float(np.dot(n[ok], adjusted[ok] - raw[ok]))) < max(1e-7, total * 1e-10),
            "Standardization failed to preserve overall mean")
    sse = float(stats.events.sum() - np.dot(stats.events[ok], raw[ok])
                - 2 * np.dot(beta, rhs) + beta @ within @ beta)
    require(sse > -max(1e-7, total * 1e-9), "Negative regression residual sum of squares")
    info = {
        "model": "joint desert-by-payoff cell intercepts and additive linear splines in transformed controls",
        "control_specs": [{"column": s[0], "transform": s[1], "reference": s[2], "knots": list(s[3])}
                          for s in CONTROL_SPECS],
        "standardization": "average over the full current sample's empirical distribution of control basis terms",
        "formula": "adjusted[g] = raw[g] + (overall_mean_basis - cell_mean_basis[g]) @ beta",
        "sample_rows": total, "nonempty_cells_including_tails": int(ok.sum()),
        "control_terms": len(beta), "globally_variable_terms": int(active.sum()),
        "constant_term_variance_tolerance": "1e-12 * max(E[Z_j^2], 1)",
        "identified_control_rank": int(keep.sum()),
        "retained_condition_number": float(eigenvalues[keep].max() / eigenvalues[keep].min()),
        "nullspace_surface_projection": null_projection,
        "residual_sum_squares": max(sse, 0.0),
        "raw_overall_percent": 100 * stats.events.sum() / total,
        "weighted_adjusted_overall_percent": 100 * float(np.dot(n[ok], adjusted[ok])) / total,
        "reference_basis_means": dict(zip(term_names(), reference.tolist())),
        "coefficients": dict(zip(term_names(), beta.tolist())),
        "chooser_fixed_effects": False, "additional_controls": [],
        "inference": "Descriptive surfaces only. No iid p-values or confidence intervals.",
        "interpretation": "Controls are additive and common across cells. This is a conditional association, not an exogenous price effect.",
        "out_of_unit_interval": "Adjusted linear-probability levels are retained without clipping; see diagnostics.",
    }
    return 100 * raw, 100 * adjusted, info


def make_grid(stats, settings, raw, adjusted, month_counts):
    rows = []
    ny, nx = settings.shape
    xe, de = settings.xedges, settings.dedges
    for g in range(settings.cells):
        di, xi = divmod(g, nx)
        interior = 0 < xi < nx - 1 and 0 < di < ny - 1
        n = int(stats.n[g])
        months = int((month_counts[:, g] > 0).sum())
        supported = bool(interior and n >= settings.min_cell_n and months >= settings.min_cell_months)
        row = {"cell_id": g, "payoff_bin": xi, "desert_bin": di,
            "payoff_low": None if xi == 0 else float(xe[xi - 1]),
            "payoff_high": None if xi == nx - 1 else float(xe[xi]),
            "desert_low": None if di == 0 else float(de[di - 1]),
            "desert_high": None if di == ny - 1 else float(de[di]),
            "payoff_mid": float((xe[xi - 1] + xe[xi]) / 2) if 0 < xi < nx - 1 else None,
            "desert_mid": float((de[di - 1] + de[di]) / 2) if 0 < di < ny - 1 else None,
            "opportunities": n, "kind_draws": int(stats.events[g]), "months_observed": months,
            "inside_display_window": interior, "display_supported": supported,
            "raw_percent": float(raw[g]) if n else None,
            "adjusted_percent": float(adjusted[g]) if n else None,
            "adjustment_pp": float(adjusted[g] - raw[g]) if n else None,
            "adjusted_outside_0_100": bool(n and (adjusted[g] < 0 or adjusted[g] > 100))}
        for j, name in enumerate(CONTROL_COLUMNS):
            row[f"mean_{name}"] = float(stats.control_sum[g, j] / n) if n else None
        rows.append(row)
    return rows
