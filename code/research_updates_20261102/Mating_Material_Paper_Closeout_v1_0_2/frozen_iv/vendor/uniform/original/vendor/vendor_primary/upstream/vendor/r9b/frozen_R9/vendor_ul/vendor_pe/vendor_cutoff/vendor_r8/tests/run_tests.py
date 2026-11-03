#!/usr/bin/env python3
"""Use process isolation: vendored producers have overlapping import names."""
import subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
for name in ('test_receipt.py','test_patron.py','test_clocks.py','test_operational.py'):
    result=subprocess.run([sys.executable,'-u',str(root/'tests'/name)],check=False)
    if result.returncode:raise SystemExit(result.returncode)
print('R8 OFFLINE_NUMERICAL_SELF_TESTS_OK',flush=True)
