#!/usr/bin/env python3
"""Dependency checks; setup pins every working inherited scientific package."""
import sys,json,importlib,argparse
from pathlib import Path
REQUIRED={'numpy':('numpy>=1.26,<3',(1,26),(3,)),
    'pandas':('pandas>=2.2,<4',(2,2),(4,)),
    'scipy':('scipy>=1.15,<1.18',(1,15),(1,18)),
    'pyarrow':('pyarrow>=17,<26',(17,),(26,)),
    'duckdb':('duckdb>=1.5.2,<2',(1,5,2),(2,)),
    'matplotlib':('matplotlib>=3.9,<4',(3,9),(4,)),
    'chess':('python-chess>=1.999',None,None)}
def check():
    assert sys.version_info>=(3,10),'Python 3.10 or newer is required'
    missing=[];pins=[];versions={}
    for name,(requirement,lower,upper) in REQUIRED.items():
        try:
            mod=importlib.import_module(name);version=mod.__version__;versions[name]=version
            value=tuple(int(x) for x in version.split('.')[:3])
            if lower is not None and not lower<=value<upper:missing.append(requirement)
            elif name!='chess':pins.append(name+'=='+version)
        except Exception:missing.append(requirement)
    return missing,pins,versions
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--prepare',type=Path);a=ap.parse_args();missing,pins,versions=check()
    if a.prepare:
        a.prepare.mkdir(parents=True,exist_ok=True);(a.prepare/'requirements.txt').write_text('\n'.join(missing)+'\n' if missing else '')
        (a.prepare/'constraints.txt').write_text('\n'.join(pins)+'\n');print(json.dumps(dict(missing=missing,retained_versions=versions)))
    elif missing:
        raise SystemExit('Missing/incompatible dependencies: '+', '.join(missing)+'. Run SETUP_AND_RUN.command to install into the separate framework environment.')
    else:print('DEPENDENCIES_OK '+json.dumps(versions),flush=True)
