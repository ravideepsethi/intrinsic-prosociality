"""Regression for the Mac startup failure before any production stage ran."""
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PACKAGE=Path(__file__).resolve().parents[1]

class StartupTests(unittest.TestCase):
    def test_startup_without_matplotlib(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp,'sitecustomize.py').write_text('''import importlib.abc, importlib.metadata, sys
class NoPlotting(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'matplotlib' or fullname.startswith('matplotlib.'):
            raise ModuleNotFoundError("No module named 'matplotlib'", name='matplotlib')
sys.meta_path.insert(0, NoPlotting())
original_version=importlib.metadata.version
def version(name):
    if name == 'matplotlib':
        raise importlib.metadata.PackageNotFoundError(name)
    return original_version(name)
importlib.metadata.version=version
''')
            env=dict(os.environ,PYTHONPATH=os.pathsep.join([tmp,os.environ.get('PYTHONPATH','')]))
            lines=(PACKAGE/'RUN_MIGRATION.command').read_text().splitlines()
            payloads=[shlex.split(line)[2] for line in lines if line.strip().startswith('"$PATRON_PYTHON" -c ')]
            self.assertEqual(len(payloads),1)
            scripts=[('launcher',payloads[0])]
            prefix='import sys;sys.path.insert(0,'+repr(str(PACKAGE/'code'))+');'
            for module in ('run_migration','receipt_worker','patron_prepare','patron_fit','comparison_audit'):
                body=prefix+'import '+module+';'
                if module=='run_migration':body+='assert "matplotlib" not in run_migration.runtime_versions();'
                if module=='receipt_worker':body+='import cutoffs, primary_scores;'
                body+='assert "matplotlib" not in sys.modules;'
                scripts.append((module,body))
            for name,body in scripts:
                with self.subTest(entry=name):
                    result=subprocess.run([sys.executable,'-c',body],env=env,capture_output=True,text=True,timeout=90)
                    self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)

if __name__=='__main__':unittest.main()
