#!/usr/bin/env python3
"""Offline unit tests for the C7R linear-combination addendum."""

from __future__ import annotations

import math
import unittest

import numpy as np

from run_closure import fit_hdfe_with_covariance, linear_contrast


class ClosureTests(unittest.TestCase):
    def test_covariance_linear_combination(self) -> None:
        rng = np.random.default_rng(20260911)
        chooser = np.repeat(np.arange(300), 16)
        n = chooser.size
        period = np.tile(np.arange(8), n // 8)
        fair = rng.integers(0, 2, size=n).astype(float)
        repeat = rng.integers(0, 2, size=n).astype(float)
        interaction = fair * repeat
        control = rng.normal(size=n)
        outcome = (
            0.04 * fair + 0.01 * repeat - 0.015 * interaction
            + 0.02 * control + rng.normal(scale=0.08, size=n)
            + rng.normal(scale=0.2, size=300)[chooser]
        )
        fitted = fit_hdfe_with_covariance(
            outcome=outcome,
            exposures={"fair": fair, "repeat": repeat, "fair_x_repeat": interaction},
            numeric_controls={"control": control},
            fixed_effects={"chooser": chooser, "period": period},
            clusters=chooser,
            row_ids=np.arange(n),
            specification={"model": "synthetic"},
        )
        contrast = linear_contrast(
            fitted,
            {"fair": 1.0, "fair_x_repeat": 1.0},
            "synthetic_repeat_gradient",
        )
        estimates = {row["term"]: row["coefficient"] for row in fitted["results"]}
        covariance = fitted["exposure_covariance"]
        expected_variance = (
            covariance["fair"]["fair"]
            + covariance["fair_x_repeat"]["fair_x_repeat"]
            + 2.0 * covariance["fair"]["fair_x_repeat"]
        )
        self.assertAlmostEqual(
            contrast["coefficient"], estimates["fair"] + estimates["fair_x_repeat"], places=14
        )
        self.assertAlmostEqual(contrast["standard_error"] ** 2, expected_variance, places=14)
        self.assertTrue(math.isfinite(contrast["p_value_two_sided"]))

    def test_covariance_is_symmetric(self) -> None:
        fake = {
            "results": [
                {"term": "a", "coefficient": 2.0},
                {"term": "b", "coefficient": -0.5},
            ],
            "exposure_covariance": {
                "a": {"a": 0.09, "b": -0.01},
                "b": {"a": -0.01, "b": 0.04},
            },
        }
        result = linear_contrast(fake, {"a": 1.0, "b": 1.0}, "sum")
        self.assertAlmostEqual(result["coefficient"], 1.5)
        self.assertAlmostEqual(result["standard_error"], math.sqrt(0.11))


if __name__ == "__main__":
    unittest.main(verbosity=2)
