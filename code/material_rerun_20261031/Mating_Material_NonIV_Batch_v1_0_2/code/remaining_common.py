"""Read-only helpers for the retained historical tenure adapter."""
from engine import *

def checked_sidecar(path):
    path=Path(path)
    for suffix in ('.ok.json','.receipt.json'):
        p=Path(str(path)+suffix)
        if p.exists():
            r=read(p);require(r.get('sha256')==sha(path),'Leaf receipt differs: '+str(path))
            return record(path)
    raise RuntimeError('Required leaf receipt missing: '+str(path))

def unique_path(paths,label):
    paths=sorted(set(Path(p).resolve() for p in paths if Path(p).is_file()))
    require(len(paths)==1,f'{label}: expected one source; found {len(paths)}')
    return paths[0]
