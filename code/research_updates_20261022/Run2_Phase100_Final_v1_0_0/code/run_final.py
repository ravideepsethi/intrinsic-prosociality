"""Use separate interpreters for the two frozen dependency trees."""
from release100 import *
import argparse, subprocess, sys

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--workers',type=int,default=10);p.add_argument('--memory-gb',type=float,default=11)
    a=p.parse_args()
    if not 1<=a.workers<=10 or a.memory_gb!=11:p.error('Use 1–10 workers and --memory-gb 11')
    verify_release()
    args=['--project-root',str(a.project_root),'--desktop',str(a.desktop),'--workers',str(a.workers),'--memory-gb',str(a.memory_gb)]
    for name in ('run_phase100.py','run_score_a100.py'):
        subprocess.run([sys.executable,'-u',str(PACKAGE/'code'/name)]+args,check=True)

if __name__=='__main__':main()
