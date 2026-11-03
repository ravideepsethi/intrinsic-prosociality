import unittest
from unittest.mock import patch
from importlib.metadata import PackageNotFoundError

import run_all


class DependencyChecks(unittest.TestCase):
    def test_collects_all_missing_packages_in_one_report(self):
        missing={'scipy','pandas'}
        def version(name):
            if name in missing:raise PackageNotFoundError(name)
            return 'test-version'
        def imported(name):
            if name in missing:raise ModuleNotFoundError(name)
            return object()
        with patch.object(run_all.importlib.metadata,'version',side_effect=version) as metadata, \
             patch.object(run_all.importlib,'import_module',side_effect=imported) as imports:
            report=run_all.dependency_report()
        self.assertEqual(set(report['problems']),missing)
        self.assertEqual(set(report['checks']),set(run_all.DEPENDENCIES))
        self.assertEqual(metadata.call_count,5)
        self.assertEqual(imports.call_count,5)

    def test_distinguishes_present_metadata_from_a_broken_import(self):
        def imported(name):
            if name=='pyarrow':raise ImportError('fixture binary import failure')
            return object()
        with patch.object(run_all.importlib.metadata,'version',return_value='test-version'), \
             patch.object(run_all.importlib,'import_module',side_effect=imported):
            report=run_all.dependency_report()
        self.assertEqual(report['problems'],['pyarrow'])
        self.assertFalse(report['checks']['pyarrow']['import_ok'])
        self.assertEqual(len(report['versions']),5)


if __name__=='__main__':unittest.main()
