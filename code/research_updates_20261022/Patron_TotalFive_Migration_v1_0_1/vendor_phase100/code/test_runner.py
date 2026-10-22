"""Separate import contexts for frame and certified R9 code trees."""
from release100 import PACKAGE
import subprocess,sys

for folder in ('tests_frames','vendor_r9_resume/frozen_R9/tests','vendor_r9_resume/tests','tests_score'):
    print('Offline tests: '+folder,flush=True)
    subprocess.run([sys.executable,'-m','unittest','discover','-s',str(PACKAGE/folder),'-p','test_*.py','-q'],check=True)
