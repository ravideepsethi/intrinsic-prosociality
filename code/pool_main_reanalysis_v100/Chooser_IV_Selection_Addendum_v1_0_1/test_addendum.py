import math
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

import run_addendum as add


class AddendumTests(unittest.TestCase):
    def test_candidate_decomposition_is_exact(self):
        active = np.array([True, False, False, True])
        passive = np.array([False, True, False, False])
        candidate = active | passive
        self.assertEqual(int(candidate.sum()), int(active.sum() + passive.sum()))
        self.assertAlmostEqual(float(active[candidate].mean()), 2 / 3)

    def test_absorb_removes_group_means(self):
        matrix = np.array([[1.0, 3.0], [3.0, 5.0], [10.0, 7.0], [14.0, 9.0]])
        group = np.array([0, 0, 1, 1])
        result, _ = add.absorb(matrix, [group])
        for column in range(result.shape[1]):
            self.assertAlmostEqual(float(result[group == 0, column].mean()), 0.0)
            self.assertAlmostEqual(float(result[group == 1, column].mean()), 0.0)

    def test_shared_account_meat_matches_manual_sums(self):
        recipient = np.array([1, 1, 4])
        opponent = np.array([2, 3, 2])
        date = np.array([10, 10, 11])
        score = np.array([0.5, -0.2, 0.7])
        codes = add.covariance_codes(recipient, opponent, date)
        doubled = np.r_[score, score]
        account_sums = np.bincount(codes["accounts"], weights=doubled)
        pair_sums = np.bincount(codes["pairs"], weights=score)
        expected = float(account_sums @ account_sums - pair_sums @ pair_sums)
        self.assertAlmostEqual(add.covariance_meat(score, codes, False), expected)

    def test_fit_uses_current_iv_scale(self):
        score = np.array([-2.0, -1.0, 1.0, 2.0])
        outcome = 0.25 * score
        codes = add.covariance_codes(
            np.array([1, 3, 5, 7]), np.array([2, 4, 6, 8]), np.arange(4)
        )
        result = add.fit(outcome, score, codes, False, 0.5)
        self.assertAlmostEqual(result["coefficient_per_unit_score"], 0.25)
        self.assertAlmostEqual(
            result["coefficient_pp_per_current_IV_SD"], 25 * add.CURRENT_IV_SD
        )

    def test_report_writer_accepts_precreated_staging_directory(self):
        rows = [
            {
                "specification": "primary",
                "clustering": "shared_account_OR_date_CR0",
                "family": "candidate_incidence",
                "outcome": "time_forfeit_candidate",
            }
        ]
        with tempfile.TemporaryDirectory() as root:
            staging = Path(root) / "report.partial_test"
            staging.mkdir()
            add.make_report(
                staging,
                rows,
                [{"specification": "primary", "n": 1}],
                [{"check": "test", "passed": True}],
                {"version": add.VERSION},
                {"source_report_zip_sha256": "0" * 64},
            )
            self.assertTrue((staging / "_DONE.json").is_file())
            receipt = json.loads((staging / "_DONE.json").read_text())
            self.assertEqual(receipt["status"], "CHOOSER_IV_SELECTION_ADDENDUM_COMPLETE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
