#!/usr/bin/env python3
"""Independent synthetic integration checks for additional second-wave analyses."""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "11a_estimate_dynamic_second_wave_postprimary.py"


def load() -> object:
    spec = importlib.util.spec_from_file_location("postprimary_under_test", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load additional-analysis estimator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    module = load()
    module.self_test()

    # Two simulated sequences verify that the first observed kind draw is located
    # independently for each draw-preserving randomization.
    hour = module.HOUR_MS
    times = np.array([0, hour, 2 * hour, 3 * hour, 30 * hour], dtype=np.int64)
    choices = np.array(
        [
            [True, False, True, False, False],
            [False, True, False, True, False],
        ],
        dtype=bool,
    )
    payoff = np.array([-2.0, 1.0, 0.0, 0.0, 0.0])
    result = module.b2_event_metrics(times, choices, payoff)
    index = module.HORIZONS_HOURS.index(3.0)
    assert result["pooled_den"][:, index].tolist() == [3, 2]
    assert result["pooled_num"][:, index].tolist() == [1, 1]
    assert result["chooser_contributors"][:, index].tolist() == [1, 1]
    assert result["group_contributors"][0, 0, index] == 1
    assert result["group_contributors"][1, 2, index] == 1

    # The exact plus-one p-value cannot be zero.
    simulated = np.linspace(0.0, 0.9, 9)
    p_value = module.plus_one_two_sided(1.0, simulated)
    assert p_value == 0.2

    # Holm and BH are monotone after ordering by raw p-value.
    raw = {"x": 0.001, "y": 0.02, "z": 0.2, "w": 1.0}
    for adjusted in (module.holm_adjust(raw), module.bh_adjust(raw)):
        ordered = sorted(raw, key=raw.get)
        values = [adjusted[key] for key in ordered]
        assert values == sorted(values)
        assert all(0.0 <= value <= 1.0 for value in values)

    # A three-way FE projection must remove every group mean without erasing a
    # genuinely varying regressor.
    rng = np.random.default_rng(1101)
    rows = 2_400
    chooser = np.repeat(np.arange(120), 20)
    month = np.tile(np.arange(20), 120)
    cell = (chooser * 3 + month) % 11
    matrix = rng.normal(size=(rows, 3))
    residual, iterations, orthogonality = module.absorb_multiway(
        matrix, (chooser, month, cell)
    )
    assert iterations >= 1
    assert orthogonality < 1e-8
    assert np.linalg.norm(residual) > 0

    # Frisch-Waugh-Lovell coefficients must match an explicit dummy regression.
    x = rng.normal(size=(rows, 2))
    y = 0.7 * x[:, 0] - 0.2 * x[:, 1] + rng.normal(size=rows)
    assignment = month * 20 + cell
    absorbed_fit = module.fit_absorbed_lpm(
        y,
        x,
        ("x0", "x1"),
        (chooser, month, cell),
        chooser,
        assignment,
    )
    chooser_dummy = np.eye(int(chooser.max()) + 1)[chooser]
    month_dummy = np.eye(int(month.max()) + 1)[month][:, 1:]
    cell_dummy = np.eye(int(cell.max()) + 1)[cell][:, 1:]
    explicit = np.column_stack([x, chooser_dummy, month_dummy, cell_dummy])
    explicit_beta = np.linalg.lstsq(explicit, y, rcond=None)[0][:2]
    assert np.allclose(absorbed_fit["beta"], explicit_beta, atol=1e-9, rtol=1e-9)

    plan_candidates = (
        ROOT
        / "Dynamic_Prosociality_Second_Wave_Additional_Analyses_v1_0_1.md",
        ROOT.parent / "docs/dynamic_prosociality_second_wave_postprimary_analysis.md",
    )
    plan_path = next((path for path in plan_candidates if path.is_file()), None)
    if plan_path is None:
        raise RuntimeError("Additional-analysis document is missing")
    plan = plan_path.read_text(encoding="utf-8")
    required_phrases = (
        "including null, unstable, and",
        "fully interacted pool-cell fixed effect",
        "chooser-equal continuation rate",
        "No account identifier",
    )
    for phrase in required_phrases:
        assert phrase in plan

    print("DYNAMIC_SECOND_WAVE_POSTPRIMARY_SYNTHETIC_INTEGRATION_OK")


if __name__ == "__main__":
    main()
