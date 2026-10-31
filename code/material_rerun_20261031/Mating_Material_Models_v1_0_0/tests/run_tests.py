"""Isolate original top-level module names just as production does."""
from pathlib import Path
import sys,subprocess,time
ROOT=Path(__file__).resolve().parents[1]
def main():
    start=time.monotonic()
    for suite in ('contracts','r11','merit','integration'):
        subprocess.run([sys.executable,str(ROOT/'tests/checks.py'),suite],check=True)
    print(f'ALL_MODEL_TESTS_PASSED in {time.monotonic()-start:.3f}s',flush=True)
if __name__=='__main__':main()
