#!/usr/bin/env python3
import os,sys,hashlib,venv,fcntl,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def main():
    if not (3,11)<=sys.version_info[:2]<=(3,13):raise SystemExit('Python 3.11–3.13 is required')
    for line in (ROOT/'SHA256SUMS.txt').read_text().splitlines():
        checksum,name=line.split('  ',1);p=(ROOT/name).resolve()
        if not p.is_relative_to(ROOT) or hashlib.sha256(p.read_bytes()).hexdigest()!=checksum:raise SystemExit('Package checksum mismatch: '+name)
    env=Path(os.environ.get('MMM_ENV',str(Path.home()/'Desktop/Lichess_Desktop/MatingMaterial_Models_Env_v100'))).expanduser().resolve()
    env.parent.mkdir(parents=True,exist_ok=True)
    with (env.parent/(env.name+'.setup.lock')).open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX);python=env/'bin/python'
        if not python.exists():print('Creating isolated model environment: '+str(env),flush=True);venv.EnvBuilder(with_pip=True).create(env)
        check="from importlib.metadata import version; assert [version(x) for x in ['numpy','pandas','pyarrow','duckdb','scipy']]==['2.3.5','2.3.3','20.0.0','1.3.2','1.16.3']"
        if subprocess.run([str(python),'-c',check],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:
            print('Installing five pinned binary dependencies; expected 1–3 minutes once.',flush=True)
            subprocess.run([str(python),'-m','pip','install','--only-binary=:all:','-r',str(ROOT/'requirements.txt')],check=True)
        subprocess.run([str(python),'-c',check],check=True)
    args=sys.argv[1:]
    if not any(x in args for x in ['--help','-h','--self-test','--estimate-only']):
        subprocess.run([str(python),str(ROOT/'run.py'),'--self-test'],check=True)
    os.execv(str(python),[str(python),str(ROOT/'run.py'),*args])
if __name__=='__main__':main()
