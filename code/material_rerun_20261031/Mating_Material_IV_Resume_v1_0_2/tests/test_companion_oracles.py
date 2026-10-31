"""Run unchanged scientific tests from the position and badge producers."""
import importlib.util,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'code'))
import bootstrap

def load_tests(loader,tests,pattern):
    suite=unittest.TestSuite()
    sources=[('position_oracles',ROOT/'vendor/position_tests/test_position.py','PositionTests'),
             ('patron_oracles',ROOT/'vendor/patron/tests/test_patron5.py','PatronTests')]
    for name,path,klass in sources:
        sys.path.insert(0,str(path.parent))
        spec=importlib.util.spec_from_file_location(name,path)
        module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
        for test in loader.loadTestsFromTestCase(getattr(module,klass)):
            # This original test launches the obsolete standalone directory
            # layout. Our integrated baseline/restart test exercises its fit.
            if test._testMethodName!='test_baseline_reproduction_and_subprocess_worker_match_frozen_model':suite.addTest(test)
    return suite
