"""Choose an existing scientific Python; never reinstall a working environment."""
import os,subprocess,sys,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def main():
    desktop=Path.home()/'Desktop/Lichess_Desktop'
    candidates=[os.environ.get('LICHESS_PYTHON'),str(ROOT/'.venv/bin/python'),
                str(desktop/'KAC_Continuous_Merit_v1_0_0/.venv/bin/python'),
                str(desktop/'Tenure_Responsibility_v1_0_1/.venv/bin/python'),sys.executable]
    for pattern in ['*/KAC_Next_Analyses_v1_0_0/.venv/bin/python','KAC_Next_Analyses_v1_0_0/.venv/bin/python','*/KAC_Continuous_Merit_v1_0_0/.venv/bin/python','tenure_responsibility.*/Tenure_Responsibility_v1_0_0/.venv/bin/python']:
        candidates += [str(p) for p in sorted(desktop.glob(pattern))]
    probe='import duckdb,pyarrow,numpy,pandas,scipy,chess,requests,matplotlib'
    python=None
    for c in dict.fromkeys(candidates):
        if not c:continue
        try:r=subprocess.run([c,'-c',probe],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
        except (OSError,subprocess.TimeoutExpired):continue
        if r.returncode==0:python=c;break
    if python is None:
        print('Preparing an isolated Python environment (typically 1–3 minutes).',flush=True)
        venv=ROOT/'.venv';subprocess.run([sys.executable,'-m','venv',str(venv)],check=True)
        python=str(venv/'bin/python')
        subprocess.run([python,'-m','pip','install','-r',str(ROOT/'requirements.txt')],check=True)
    print('PYTHON '+python,flush=True)
    subprocess.run([python,str(ROOT/'self_test.py')],check=True)
    subprocess.run([python,str(ROOT/'repair_test.py')],check=True)
    command=[python,'-u',str(ROOT/'run.py')]+sys.argv[1:]
    if shutil.which('caffeinate'):command=['caffeinate','-i']+command
    os.execvp(command[0],command)
if __name__=='__main__':main()
