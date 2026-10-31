#!/usr/bin/env python3
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
import util,unittest
from contract_tests import Contracts
from test_responsibility import ResponsibilityTests
from test_design_support import ExactDesignSupport
if __name__=='__main__':
    suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in (Contracts,ResponsibilityTests,ExactDesignSupport)])
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
