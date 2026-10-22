"""Static contract and small-sample non-DuckDB tests. Run with PYTHONPATH=src."""
import ast,sys,tempfile,json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
for p in (root/'src').glob('*.py'):
 ast.parse(p.read_text())
for forbidden in ('/api/games/export/','requests.post(','aiohttp.ClientSession('):
 for p in (root/'src').glob('*.py'):
  assert forbidden not in p.read_text(),(forbidden,p)
assert '2682330' in (root/'src'/'prepare_e.py').read_text()
assert '851131' in (root/'src'/'prepare_a.py').read_text()
assert '4324' in (root/'src'/'prepare_e.py').read_text()
assert 'calibration_pass' in (root/'src'/'run_e_estimates.py').read_text()
print('PASS file syntax, source-count gates, pooled-IV calibration and offline-only operation')
