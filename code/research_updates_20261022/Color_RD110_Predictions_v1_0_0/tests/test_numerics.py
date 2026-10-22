import unittest
from fixture import *
from scipy.special import expit
from design import MODELS, design, counterfactual
from predictions import account_calibration, period_groups, weekly_values, offsets, ADVANTAGE, WEEK
from power import block_noise, empirical_mde, calculate_power


class NumericalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = data()

    def test_zero_advantage_and_certified_payoff_identity(self):
        self.assertLess(check_payoffs(self.d), 1e-10)
        z = counterfactual(self.d, advantage=0.)
        np.testing.assert_allclose(z[['ki', 'kj', 'rg', 'rc']], self.d[['ki', 'kj', 'rg', 'rc']], atol=1e-12)

    def test_color_signs_and_both_premiums(self):
        d = self.d.iloc[:20].copy()
        d['rd'] = 45.; d['opp_rd'] = 45.; d['g'] = 0.; d['opp_rating'] = d.rating
        old, new = counterfactual(d, advantage=0.), counterfactual(d, advantage=ADVANTAGE)
        dg = new.rg - old.rg
        self.assertTrue((dg[d.color.eq('white')] < 0).all())
        self.assertTrue((dg[d.color.eq('black')] > 0).all())
        self.assertTrue(np.all(abs(dg) > .18))
        np.testing.assert_allclose(new.rc - old.rc - dg, new.ki - old.ki, atol=1e-12)
        # Changes in both premiums are tiny at equality, but are still retained.
        self.assertTrue(((new.ki - old.ki).abs() > 0).all())
        self.assertTrue(((new.kj - old.kj).abs() > 0).all())

    def test_index_delta_matches_complete_design_for_every_model(self):
        d = self.d.iloc[:81].copy()
        for model in MODELS:
            X, names, _ = design(d, model, .25)
            beta = np.linspace(.001, .2, len(names))
            fit = dict(model=model, names=names, beta=beta.tolist(), curvature=.25)
            eta, shift, _ = offsets(d, fit, block_size=17)
            Z, names_new, _ = design(counterfactual(d, advantage=ADVANTAGE), model, .25)
            self.assertEqual(names, names_new)
            np.testing.assert_allclose(eta, X @ beta, atol=1e-11)
            np.testing.assert_allclose(shift, (Z - X) @ beta, atol=1e-11)

    def test_pure_displayed_gap_has_zero_direct_policy_change(self):
        d = self.d.iloc[:80]
        X, names, _ = design(d, 'strength')
        fit = dict(model='strength', names=names, curvature=.5,
                   beta=[.4 if n.startswith('strength_') else 0. for n in names])
        _, shift, _ = offsets(d, fit)
        np.testing.assert_array_equal(shift, np.zeros(len(d)))

    def test_account_calibration_handles_extreme_offsets_and_matches_rate(self):
        group = np.repeat(np.arange(3), 4)
        eta = np.array([-900., -898, -902, -901, 800, 802, 798, 799, -1, 1, 2, 0])
        y = np.array([0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0])
        z, meta = account_calibration(eta, y, group)
        self.assertAlmostEqual(expit(z).mean(), y.mean(), places=10)
        self.assertLess(meta['account_target_max_error_before_global_shift'], 1e-8)
        z2, _ = account_calibration(eta + np.array([100, -100, 50])[group], y, group)
        np.testing.assert_allclose(z, z2, atol=1e-9)

    def test_pooled_calibration_and_invalid_outcomes(self):
        z, _ = account_calibration(np.arange(20) / 10, np.r_[1, np.zeros(19)], np.arange(20), None)
        self.assertAlmostEqual(expit(z).mean(), .05, places=10)
        with self.assertRaises(ValueError):
            account_calibration(np.zeros(3), np.zeros(3), np.arange(3))

    def test_complete_calendar_week_boundaries(self):
        g = period_groups(self.d)
        weeks = pd.to_datetime(g['weeks'][g['complete']], unit='ms', utc=True)
        self.assertEqual(str(weeks[0].date()), '2023-11-06')
        self.assertEqual(str(weeks[-1].date()), '2025-10-20')
        self.assertTrue(np.all(np.diff(weeks.astype('int64')) == WEEK * 1000000))

    def test_missing_calendar_week_rejected(self):
        start = int(pd.Timestamp('2024-05-06T00:00:00Z').timestamp() * 1000)
        d = self.d[~self.d.t.between(start, start + WEEK - 1)]
        with self.assertRaisesRegex(RuntimeError, 'week'):
            period_groups(d)

    def test_equal_week_not_opportunity_weighting(self):
        grouping = dict(groups=np.array([0, 0, 0, 1, 2, 3]), counts=np.array([[3, 1], [1, 1]]))
        values = weekly_values(grouping, [1, 1, 1, 0, 3, 0])
        self.assertEqual((values[:, 0] - values[:, 1]).mean(), 2.)

    def test_block_noise_reproducible_and_centered(self):
        y = np.random.default_rng(999).normal(size=100)
        a = block_noise(y, reps=1000)
        np.testing.assert_array_equal(a, block_noise(y, reps=1000))
        self.assertAlmostEqual(a.mean(), 0., places=12)
        self.assertFalse(np.array_equal(a, block_noise(y, reps=1000, block=8)))

    def test_mde_both_signs_and_null_frequency(self):
        noise = np.random.default_rng(22).normal(size=100000)
        mde, critical = empirical_mde(noise)
        self.assertTrue(2.7 < mde < 2.9)
        self.assertLessEqual(np.mean(abs(noise) > critical), .05)
        for sign in [-1, 1]:
            self.assertGreaterEqual(np.mean(abs(noise + sign * mde) > critical), .79999)

    def test_probability_mixture_is_not_scaled_index(self):
        old, shift, q = -3., .8, .2
        mixture = (1 - q) * expit(old) + q * expit(old + shift)
        self.assertAlmostEqual(mixture - expit(old), q * (expit(old + shift) - expit(old)))
        self.assertGreater(abs(mixture - expit(old + q * shift)), 1e-4)


if __name__ == '__main__':
    unittest.main()
