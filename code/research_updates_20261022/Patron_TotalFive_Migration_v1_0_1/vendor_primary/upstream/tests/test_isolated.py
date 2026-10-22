import unittest,subprocess,sys
from pathlib import Path

class IsolatedTests(unittest.TestCase):
    def test_iv_and_preminimum_inputs(self):
        subprocess.run([sys.executable,str(Path(__file__).with_name('iv_checks.py'))],check=True)
    def test_completed_games(self):
        subprocess.run([sys.executable,str(Path(__file__).with_name('completed_checks.py'))],check=True)
    def test_cutoff_volume_and_resume(self):
        subprocess.run([sys.executable,str(Path(__file__).with_name('cutoff_volume_checks.py'))],check=True)

if __name__=='__main__':unittest.main()
