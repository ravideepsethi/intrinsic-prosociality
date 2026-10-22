"""Explicit transformations from archived aggregate outputs to plotted values.

No estimation, smoothing, digitization, API requests or individual observations.
All rates use percentage units. Differences use percentage points (pp).
"""

import csv
import hashlib
import json
from pathlib import Path


class InputBundle:
    """Read original aggregate files using their repository paths and hashes."""

    def __init__(self, repo_root, manifest_path):
        self.repo_root = Path(repo_root).resolve()
        self.manifest = json.loads(Path(manifest_path).read_text())
        self.paths = {}
        for name, item in self.manifest["inputs"].items():
            path = (self.repo_root / item["path"]).resolve()
            if not path.is_relative_to(self.repo_root):
                raise ValueError(f"Input escapes repository root: {name}")
            if not path.is_file():
                raise FileNotFoundError(f'Missing aggregate input: {item["path"]}')
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != item["sha256"]:
                raise ValueError(
                    f"Input hash mismatch: {name}. Update its provenance explicitly."
                )
            self.paths[name] = path

    def read(self, name):
        path = self.paths[name]
        if path.suffix == ".parquet":
            import pyarrow.parquet as pq

            return pq.read_table(path).to_pylist()
        with path.open(newline="") as f:
            return list(csv.DictReader(f))


def read(root, name):
    return root.read(name)


def num(row, name):
    return float(row[name])


def one(rows, **conditions):
    selected = [
        r for r in rows if all(str(r[k]) == str(v) for k, v in conditions.items())
    ]
    if len(selected) != 1:
        raise ValueError(f"Expected one row for {conditions}; found {len(selected)}.")
    return selected[0]


def interval(estimate, se):
    return estimate - 1.96 * se, estimate + 1.96 * se


def load(repo_root, manifest_path):
    root = InputBundle(repo_root, manifest_path)

    raw = read(root, "merit_raw_board_stage_rating.csv")
    board = []
    for b, label in [
        (4, "Clearly better"),
        (3, "Better"),
        (2, "Roughly equal"),
        (1, "Modestly worse"),
        (0, "Clearly worse"),
    ]:
        rows = [r for r in raw if int(r["board_bin"]) == b]
        n, g = sum(int(r["n"]) for r in rows), sum(int(r["grants"]) for r in rows)
        board.append(dict(board_bin=b, label=label, n=n, grants=g, percent=100 * g / n))
    stages = []
    for label, stageset in [
        ("Ply 2", {1}),
        ("Plies 3-10", {2, 3, 4, 5}),
        ("After ply 10", {6, 7, 8, 9}),
    ]:
        rows = [
            r for r in raw if int(r["board_bin"]) >= 2 and int(r["stage"]) in stageset
        ]
        n, g = sum(int(r["n"]) for r in rows), sum(int(r["grants"]) for r in rows)
        stages.append(dict(label=label, n=n, grants=g, percent=100 * g / n))
    equality = []
    models = read(root, "equality_models.csv")
    for model, label in [
        ("E0_raw", "Raw difference"),
        ("E1_chooser_fe", "Chooser fixed effects"),
        ("E2_primary_modern_analogue", "+ Month, speed, premium, clocks"),
        ("E4_game_stage_adjusted", "+ Draw payoff and game stage"),
    ]:
        r = one(models, model_id=model, variable="roughly_equal")
        e, s = num(r, "coefficient_pp"), num(r, "se_pp")
        lo, hi = interval(e, s)
        equality.append(
            dict(label=label, estimate=e, se=s, lo=lo, hi=hi, n=int(r["rows_raw"]))
        )

    profiles = read(root, "merit_adjusted_profiles.csv")
    curves = []
    tails = []
    material = []
    for model, label in [
        ("primary_competitive_late", "Primary"),
        ("competitive_late_clocks", "Plus clocks"),
        ("competitive_late_rating", "Plus rating controls"),
    ]:
        for r in profiles:
            if r["model"] != model:
                continue
            item = dict(
                model=model,
                label=label,
                cp=num(r, "cp"),
                estimate=num(r, "adjusted_percent"),
                se=num(r, "se"),
                lo=num(r, "lo"),
                hi=num(r, "hi"),
            )
            if r["estimable"] != "True":
                raise ValueError("Unestimable spline row.")
            if r["mate"] == "False" and -100 <= item["cp"] < 600:
                curves.append(item)
            elif model == "primary_competitive_late" and item["cp"] >= 600:
                item["category"] = (
                    "Positive mate" if r["mate"] == "True" else "Finite >=600"
                )
                tails.append(item)
    for model, label in [
        ("material_competitive_late_base", "Competitive positions"),
        ("material_full_late_base", "All board positions"),
    ]:
        for r in profiles:
            if r["model"] == model:
                material.append(
                    dict(
                        model=model,
                        label=label,
                        category=r["label"],
                        material=num(r, "material"),
                        estimate=num(r, "adjusted_percent"),
                        lo=num(r, "lo"),
                        hi=num(r, "hi"),
                        se=num(r, "se"),
                    )
                )
    support = {x: 0 for x in range(-100, 600, 50)}
    for r in read(root, "merit_raw_continuous_support.csv"):
        try:
            cp = float(r["eval50"])
        except ValueError:
            continue
        if int(r["stage"]) >= 6 and cp in support:
            support[int(cp)] += int(r["n"])

    gap = []
    for r in read(root, "rating_gap_curves.csv"):
        if r["model_id"] != "primary_k20__ply_gt_10__m100_p100":
            continue
        gap.append(
            dict(
                x=num(r, "gap_mid"),
                estimate=num(r, "coef_pp"),
                se=num(r, "se_pp"),
                lo=num(r, "ci_lo_pp"),
                hi=num(r, "ci_hi_pp"),
                reference=num(r, "gap_mid") == 0,
            )
        )
    within = []
    for r in read(root, "rating_gap_within_account.csv"):
        e, s = num(r, "chooser_equal_diff_pp"), num(r, "se_pp")
        lo, hi = interval(e, s)
        within.append(
            dict(
                band=r["eval_band"],
                side=r["side"],
                estimate=e,
                se=s,
                lo=lo,
                hi=hi,
                accounts=int(r["choosers"]),
            )
        )
    adjacent = []
    a = read(root, "adjacent_models.csv")
    for term, label in [
        ("gap_0_minus_gap_m1", "Equal vs. -1"),
        ("gap_p1_minus_gap_m1", "+1 vs. -1"),
    ]:
        r = one(a, model="joint_gap_m1_0_p1__all__all", term=term)
        e, s = num(r, "estimate_pp"), num(r, "se_pp")
        lo, hi = interval(e, s)
        adjacent.append(
            dict(label=label, estimate=e, se=s, lo=lo, hi=hi, n=int(r["rows"]))
        )
    slopes = []
    for estimand, label in [
        ("loss_side_slope", "Loss side"),
        ("gain_side_slope", "Gain side"),
        ("loss_minus_gain_slope", "Difference"),
    ]:
        r = one(read(root, "draw_payoff_slopes.csv"), estimand=estimand)
        slopes.append(
            dict(
                label=label,
                estimate=num(r, "estimate"),
                se=num(r, "se"),
                lo=num(r, "ci95_low"),
                hi=num(r, "ci95_high"),
            )
        )

    scale_rows = read(root, "iv_scale_reference.csv")
    scales = {num(r, "reference_score_SD") for r in scale_rows}
    if len(scales) != 1:
        raise ValueError("Ambiguous reference scale.")
    reference_sd = scales.pop()
    bins = []
    for r in read(root, "iv_bins.csv"):
        if (r["sample"], r["control_family"], r["instrument"]) != (
            "S1",
            "X0",
            "pooled",
        ):
            continue
        bins.append(
            dict(
                bin=int(r["bin"]),
                n=int(r["n"]),
                x=num(r, "mean_residual_score") / reference_sd,
                raw_score=num(r, "mean_residual_score"),
                estimate=num(r, "estimate"),
                lo=num(r, "ci_low"),
                hi=num(r, "ci_high"),
                se=num(r, "se"),
            )
        )
    first_stage = one(
        read(root, "iv_first_stage.csv"),
        sample="S1",
        control_family="X0",
        instrument="pooled",
        estimator="First stage: receipt",
        units="pp per raw score unit",
    )
    iv = dict(
        bins=sorted(bins, key=lambda r: r["bin"]),
        reference_sd=reference_sd,
        slope=num(first_stage, "estimate") * reference_sd,
        intercept=0.0,
        note="Uses the paper reference SD, not this restricted sample residual SD.",
    )

    receipt = []
    for outcome, label in [
        ("decay_6h_kind", "0-6 h"),
        ("decay_1d_kind", "6 h-1 d"),
        ("decay_7d_kind", "1-7 d"),
        ("decay_30d_kind", "7-30 d"),
        ("decay_90d_kind", "30-90 d"),
    ]:
        r = one(read(root, "receipt_intervals.csv"), outcome=outcome)
        e, s = num(r, "coefficient_percentage_points"), num(
            r, "standard_error_percentage_points"
        )
        lo, hi = interval(e, s)
        receipt.append(
            dict(label=label, estimate=e, se=s, lo=lo, hi=hi, n=int(r["rows"]))
        )
    concentration = []
    for h, label in [(6, "Within 6 h"), (24, "Within 24 h"), (168, "Within 7 d")]:
        r = one(read(root, "grant_concentration.csv"), horizon_hours=float(h))
        concentration.append(
            dict(
                label=label,
                observed=100 * num(r, "observed_rate"),
                benchmark=100 * num(r, "null_mean_rate"),
                lo=100 * num(r, "null_p025"),
                hi=100 * num(r, "null_p975"),
                grants=int(r["observed_numerator"]),
                n=int(r["observed_denominator"]),
            )
        )
    sessions = []
    for category, label in [
        ("same_session_7d", "Same session"),
        ("later_session_7d", "Other sessions"),
    ]:
        r = one(read(root, "grant_session_components.csv"), category=category)
        sessions.append(
            dict(
                label=label,
                observed=100 * num(r, "observed_rate"),
                benchmark=100 * num(r, "null_mean_rate"),
                lo=100 * num(r, "null_p025"),
                hi=100 * num(r, "null_p975"),
                grants=int(r["observed_numerator"]),
                n=int(r["observed_denominator"]),
            )
        )

    result = dict(
        board=board,
        stage=stages,
        equality=equality,
        curves=curves,
        tails=tails,
        material=material,
        support=[dict(cp=k, n=v) for k, v in support.items()],
        gap=sorted(gap, key=lambda r: r["x"]),
        within=within,
        adjacent=adjacent,
        slopes=slopes,
        iv=iv,
        receipt=receipt,
        concentration=concentration,
        sessions=sessions,
    )
    validate(result)
    result["input_receipt"] = root.manifest
    return result


def validate(d):
    """Scientific cross-checks independent of the plotting layout."""
    assert sum(r["n"] for r in d["board"]) == 41534331, "Main sample drift."
    assert sum(r["grants"] for r in d["board"]) == 570091, "Grant total drift."
    assert (
        sum(r["n"] for r in d["stage"]) == 15207423
    ), "Stage partition does not exhaust competitive positions."
    assert (
        sum(r["grants"] for r in d["stage"]) == 419463
    ), "Competitive grant total drift."
    assert d["stage"][-1]["n"] == 11590459, "After-ply-10 sample mismatch."
    assert (
        len(d["iv"]["bins"]) == 20 and sum(r["n"] for r in d["iv"]["bins"]) == 1914886
    )
    assert (
        max(r["n"] for r in d["iv"]["bins"]) - min(r["n"] for r in d["iv"]["bins"]) <= 1
    )
    assert len(d["gap"]) == 23 and sum(r["reference"] for r in d["gap"]) == 1
    assert one(d["gap"], reference=True)["estimate"] == 0
    assert abs(d["iv"]["slope"] - 7.57548) < 0.001, "IV scale mismatch."
    assert [round(r["estimate"], 3) for r in d["equality"]] == [
        0.214,
        0.066,
        -0.016,
        -0.400,
    ]
    assert [round(r["estimate"], 3) for r in d["slopes"]] == [0.325, -0.167, 0.492]
    assert len(d["material"]) == 16
    assert sum(r["n"] for r in d["sessions"]) == d["concentration"][-1]["n"]
    assert sum(r["grants"] for r in d["sessions"]) == d["concentration"][-1]["grants"]
    for key in [
        "curves",
        "tails",
        "material",
        "gap",
        "within",
        "adjacent",
        "slopes",
        "receipt",
        "equality",
    ]:
        for r in d[key]:
            assert r["lo"] <= r["estimate"] <= r["hi"], f"Invalid interval: {key}"
    # These rates are raw pooled rates; no regression intervals are fabricated.
    for r in d["board"] + d["stage"]:
        assert 0 <= r["grants"] <= r["n"] and 0 <= r["percent"] <= 100
    # Do not sort receipt estimates to manufacture a monotone graph.
    assert d["iv"]["bins"][5]["estimate"] < d["iv"]["bins"][4]["estimate"]
