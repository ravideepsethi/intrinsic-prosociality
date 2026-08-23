#!/usr/bin/env python3
"""Synthetic integration tests for the independent E1 audit."""

from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "11b_audit_dynamic_second_wave_e1.py"


def load_audit():
    specification = importlib.util.spec_from_file_location("e1_audit_tested", SCRIPT)
    if specification is None or specification.loader is None:
        raise RuntimeError("Could not import E1 audit estimator")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def dummy_matrix(values: np.ndarray) -> np.ndarray:
    codes, levels = pd.factorize(values, sort=True)
    if len(levels) <= 1:
        return np.empty((len(values), 0), dtype=np.float64)
    return np.column_stack(
        [(codes == level).astype(np.float64) for level in range(1, len(levels))]
    )


def test_schur_matches_dense_dummy_regression(audit) -> None:
    rng = np.random.default_rng(101)
    chooser = np.repeat(np.arange(25), 12)
    within = np.tile(np.arange(12), 25)
    cell = (chooser * 2 + within) % 7
    month = within % 4
    risk = rng.normal(size=len(chooser))
    control = rng.normal(size=len(chooser))
    chooser_effect = rng.normal(scale=0.4, size=25)[chooser]
    cell_effect = rng.normal(scale=0.3, size=7)[cell]
    month_effect = rng.normal(scale=0.2, size=4)[month]
    y = (
        0.35 * risk
        - 0.15 * control
        + chooser_effect
        + cell_effect
        + month_effect
        + rng.normal(scale=0.2, size=len(chooser))
    )

    months, month_names = audit.month_dummies(month)
    x = np.column_stack([risk, control, months])
    source = np.column_stack([y, x])
    transformed, diagnostics = audit.residualize_two_way_schur(
        source, chooser, cell
    )
    fit = audit.fit_residualized(
        transformed,
        ["risk", "control", *month_names],
        chooser,
        month * 10 + cell,
        {
            "specification": "synthetic_schur",
            "solver": "synthetic_schur",
            "rows_raw": len(y),
            "rows_after_singleton_pruning": len(y),
            **diagnostics,
        },
    )

    dense = np.column_stack(
        [
            risk,
            control,
            dummy_matrix(month),
            dummy_matrix(chooser),
            dummy_matrix(cell),
            np.ones(len(y)),
        ]
    )
    beta, _, _, _ = np.linalg.lstsq(dense, y, rcond=None)
    assert np.allclose(np.asarray(fit["beta"][:2]), beta[:2], atol=1e-10)
    assert diagnostics["absorption_max_group_mean"] < 1e-10


def test_tight_ap_matches_schur_coefficient(audit) -> None:
    rng = np.random.default_rng(202)
    chooser = np.repeat(np.arange(40), 15)
    within = np.tile(np.arange(15), 40)
    cell = (chooser + within) % 8
    month = within % 5
    risk = rng.normal(size=len(chooser))
    control = rng.normal(size=len(chooser))
    y = 0.25 * risk + 0.05 * control + rng.normal(size=len(chooser))

    months, month_names = audit.month_dummies(month)
    schur_source = np.column_stack([y, risk, control, months])
    schur, diagnostics = audit.residualize_two_way_schur(
        schur_source, chooser, cell
    )
    schur_fit = audit.fit_residualized(
        schur,
        ["risk", "control", *month_names],
        chooser,
        month * 20 + cell,
        {
            "specification": "synthetic_schur",
            "solver": "synthetic_schur",
            "rows_raw": len(y),
            "rows_after_singleton_pruning": len(y),
            **diagnostics,
        },
    )

    tight_source = np.column_stack([y, risk, control])
    tight, iterations, orthogonality = audit.absorb_tight(
        tight_source, (chooser, month, cell), tolerance=1e-12
    )
    tight_fit = audit.fit_residualized(
        tight,
        ["risk", "control"],
        chooser,
        month * 20 + cell,
        {
            "specification": "synthetic_tight",
            "solver": "synthetic_tight",
            "rows_raw": len(y),
            "rows_after_singleton_pruning": len(y),
            "absorption_iterations": iterations,
            "absorption_max_group_mean": orthogonality,
        },
    )
    assert np.allclose(
        np.asarray(schur_fit["beta"][:2]),
        np.asarray(tight_fit["beta"][:2]),
        atol=1e-9,
    )
    assert orthogonality <= 1e-12


def test_recursive_singleton_pruning(audit) -> None:
    chooser = np.array([0, 1, 1, 2, 2, 3, 3, 4, 4, 4, 5])
    assignment = np.array([0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5])
    keep, rounds, removed = audit.recursive_singleton_keep(
        (chooser, assignment)
    )
    assert rounds >= 1
    assert removed
    active = np.flatnonzero(keep)
    for values in (chooser, assignment):
        codes, levels = audit.dense_codes(values[active])
        counts = np.bincount(codes, minlength=levels)
        assert np.all(counts[codes] >= 2)


def test_cache_round_trip(audit) -> None:
    if importlib.util.find_spec("pyarrow") is None:
        print("E1_AUDIT_CACHE_ROUND_TRIP_SKIPPED_NO_LOCAL_PYARROW")
        return
    with tempfile.TemporaryDirectory(prefix="e1_audit_cache_test_") as directory:
        root = Path(directory)
        cache = root / "cache.parquet"
        frame = pd.DataFrame(
            {
                "kind_draw": [0.0, 1.0, 0.0],
                "re_pair_risk": [0.1, 0.2, 0.3],
                "chooser_code": [0, 0, 1],
                "month_code": [0, 1, 1],
                "cell_code": [0, 0, 1],
                "assignment_code": [0, 1, 2],
                "coarsening_level": [1, 1, 1],
                "leave_pair_out_n": [100, 100, 100],
                "control_000": [0.0, 1.0, -1.0],
            }
        )
        frame.to_parquet(cache, compression="zstd", index=False)
        metadata = {
            "parquet_sha256": audit.sha256_file(cache),
            "rows": len(frame),
            "control_columns": ["control_000"],
            "control_names": ["control"],
        }
        metadata_path = root / "cache.json"
        audit.atomic_json(metadata_path, metadata)
        loaded, saved = audit.read_cache(str(cache), str(metadata_path))
        assert len(loaded) == 3
        assert saved["control_names"] == ["control"]


def test_nonidentified_risk_is_not_reported_as_zero(audit) -> None:
    rows = 40
    chooser = np.repeat(np.arange(10), 4)
    assignment = np.tile(np.arange(4), 10)
    control = np.linspace(-1.0, 1.0, rows)
    transformed = np.column_stack(
        [
            np.sin(control),
            np.zeros(rows, dtype=np.float64),
            control,
        ]
    )
    fit = audit.fit_residualized(
        transformed,
        ["risk", "control"],
        chooser,
        assignment,
        {
            "specification": "synthetic_no_risk_variation",
            "solver": "synthetic",
            "rows_raw": rows,
            "rows_after_singleton_pruning": rows,
        },
    )
    scaled = audit.scaled_row(
        fit,
        "covariance_two_way",
        {
            "risk_p10": 0.1,
            "risk_p90": 0.2,
            "risk_p90_minus_p10": 0.1,
            "outcome_mean": 0.03,
        },
    )
    assert fit["risk_numerically_identified"] is False
    assert scaled["status"] == "NOT_IDENTIFIED_NO_WITHIN_FE_RISK_VARIATION"
    assert scaled["coefficient"] is None
    assert scaled["standard_error"] is None
    assert scaled["p_value_two_sided"] is None


def main() -> None:
    audit = load_audit()
    test_schur_matches_dense_dummy_regression(audit)
    test_tight_ap_matches_schur_coefficient(audit)
    test_recursive_singleton_pruning(audit)
    test_cache_round_trip(audit)
    test_nonidentified_risk_is_not_reported_as_zero(audit)
    audit.self_test()
    print("DYNAMIC_SECOND_WAVE_E1_AUDIT_SYNTHETIC_INTEGRATION_OK")


if __name__ == "__main__":
    main()
