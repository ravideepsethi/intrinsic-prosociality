#!/usr/bin/env python3
"""Isolated pinned environment; never changes an existing research environment."""
import fcntl
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import venv

ROOT=Path(__file__).resolve().parent


def main():
    if not (3,11)<=sys.version_info[:2]<=(3,13):
        raise SystemExit("Use Python 3.11–3.13 for these pinned binary dependencies.")
    # Check the supplied package before installing or running any producer.
    for line in (ROOT/"SHA256SUMS.txt").read_text().splitlines():
        expected,name=line.split("  ",1)
        path=(ROOT/name).resolve()
        if not path.is_relative_to(ROOT) or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            raise SystemExit("Package checksum mismatch: "+name)
    env=Path(os.environ.get("MMR_ENV",str(Path.home()/"Desktop/Lichess_Desktop/MatingMaterial_Env_v100"))).expanduser().resolve()
    env.parent.mkdir(parents=True,exist_ok=True)
    with (env.parent/(env.name+".setup.lock")).open("a+") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        python=env/"bin/python"
        if not python.exists():
            print("Creating isolated rerun environment: "+str(env),flush=True)
            venv.EnvBuilder(with_pip=True).create(env)
        check="import numpy,pyarrow,duckdb; assert (numpy.__version__,pyarrow.__version__,duckdb.__version__)==('2.3.5','20.0.0','1.3.2')"
        if subprocess.run([str(python),"-c",check],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:
            print("Installing pinned binary packages once; production analysis makes no network requests.",flush=True)
            subprocess.run([str(python),"-m","pip","install","--only-binary=:all:","-r",str(ROOT/"requirements.txt")],check=True)
        subprocess.run([str(python),"-c",check],check=True)
    args=sys.argv[1:]
    if "--self-test" not in args and "--help" not in args and "-h" not in args:
        subprocess.run([str(python),str(ROOT/"run.py"),"--self-test"],check=True)
    os.execv(str(python),[str(python),str(ROOT/"run.py"),*args])


if __name__=="__main__":main()
