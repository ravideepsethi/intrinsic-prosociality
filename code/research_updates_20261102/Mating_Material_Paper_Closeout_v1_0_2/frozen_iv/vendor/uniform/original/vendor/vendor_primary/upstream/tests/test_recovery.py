import importlib
import sys
import tempfile
import unittest
from pathlib import Path
import numpy as np
from matched_absorption import absorb
from archive_probe import probe_one, event_class


class RecoveryTests(unittest.TestCase):
    def test_schur_projection_matches_dense_fe_with_rare_month_crossing(self):
        rng = np.random.default_rng(140)
        n = 5000
        cell = rng.integers(0, 12, n)
        month = rng.integers(0, 5, n)
        hour = month * 8 + rng.integers(0, 8, n)
        # Small cross-month links are the slow direction for alternating projections.
        for m in range(4):
            at = np.flatnonzero(month == m)[0]
            hour[at] = (m + 1) * 8
        w = rng.uniform(.3, 3., n)
        z = rng.normal(size=(n, 5)) + month[:, None] * np.arange(1, 6)
        got, _, error = absorb(z, w, [cell, month, hour])
        A = np.column_stack([np.eye(12)[cell], np.eye(5)[month], np.eye(40)[hour]])
        b = np.linalg.lstsq(A * np.sqrt(w[:, None]), z * np.sqrt(w[:, None]), rcond=1e-13)[0]
        np.testing.assert_allclose(got, z - A @ b, atol=3e-9, rtol=1e-9)
        self.assertLessEqual(error, 1e-10)

    def test_schur_projection_handles_exactly_nested_months(self):
        rng = np.random.default_rng(141)
        n = 1200
        cell = rng.integers(0, 10, n)
        hour = rng.integers(0, 20, n)
        month = hour // 4
        z = rng.normal(size=(n, 3)); w = rng.uniform(.1, 2, n)
        got, _, _ = absorb(z, w, [cell, month, hour])
        A = np.column_stack([np.eye(10)[cell], np.eye(5)[month], np.eye(20)[hour]])
        b = np.linalg.lstsq(A * np.sqrt(w[:, None]), z * np.sqrt(w[:, None]), rcond=1e-13)[0]
        np.testing.assert_allclose(got, z - A @ b, atol=1e-10)

    def test_archive_probe_excludes_identifiers_and_exposes_placeholder(self):
        pgn = '[Event "?"]\n[Site "https://lichess.org/abcdefgh"]\n[White "PRIVATE_NAME"]\n[Black "OTHER_PRIVATE_NAME"]\n[UTCDate "2024.01.01"]\n[TimeControl "180+0"]\n[Result "1-0"]\n\n1. e4 e5 1-0\n'
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'lichess_db_standard_rated_2024-01.pgn'; p.write_text(pgn)
            row = probe_one(p, '2024-01')
            self.assertEqual(row['event_classes'], {'empty_or_placeholder': 1})
            self.assertTrue(row['reached_eof'])
            self.assertEqual(row['parser_errors'], {'Unknown ratedness in monthly PGN': 1})
            for private in ['abcdefgh', 'PRIVATE_NAME', 'OTHER_PRIVATE_NAME']:
                self.assertNotIn(private, str(row))

    def test_packaged_ancestral_manifests_are_present_and_match_reviewed_tree(self):
        from local_common import ROOT, sha
        manifest = ROOT / 'vendor/r9b/frozen_R9/vendor_ul/vendor_pe/PACKAGE_MANIFEST.sha256'
        matches = [line.split('  ', 1) for line in manifest.read_text().splitlines()
                   if line.endswith('vendor_cutoff/PACKAGE_MANIFEST.sha256')]
        self.assertEqual(len(matches), 1)
        digest, relative = matches[0]
        self.assertEqual(sha(manifest.parent / relative), digest)


if __name__ == '__main__':
    unittest.main()
