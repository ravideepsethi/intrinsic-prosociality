"""Release regressions: run these from a clean extraction of the ZIP."""
import hashlib
from pathlib import Path
import unittest


class ReleaseBundleTests(unittest.TestCase):
    def test_required_nested_manifests_and_all_their_files_are_bundled(self):
        root = Path(__file__).resolve().parents[1]
        manifest = root / 'PACKAGE_MANIFEST.sha256'
        entries = {}
        for line in manifest.read_text().splitlines():
            digest, name = line.split('  ', 1)
            self.assertNotIn(name, entries)
            entries[name] = digest
        required = {
            'vendor/local_first/PACKAGE_MANIFEST.sha256':
                '6ce63bd9831edcd606bfce22500155502008209ba7368c63984a06a51faa0082',
            'vendor/local_first/comparison_original/PACKAGE_MANIFEST.sha256':
                '9336e9b1d1b6fbcfe6a51e54205b3cd8455bfc4286b9b67bc4c229c564141290',
        }
        for name, digest in required.items():
            with self.subTest(manifest=name):
                self.assertEqual(entries.get(name), digest,
                                 'Root manifest must include the nested manifest')
                nested = root / name
                self.assertTrue(nested.is_file())
                self.assertEqual(hashlib.sha256(nested.read_bytes()).hexdigest(), digest)
                for line in nested.read_text().splitlines():
                    expected, child = line.split('  ', 1)
                    path = nested.parent / child
                    self.assertTrue(path.is_file(), str(path))
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected,
                                     str(path))
                    relative = path.relative_to(root).as_posix()
                    self.assertEqual(entries.get(relative), expected, relative)


if __name__ == '__main__':
    unittest.main()
