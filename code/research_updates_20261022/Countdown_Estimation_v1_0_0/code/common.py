from base import *
import csv, shutil, sys, zipfile
import numpy as np
import pyarrow as pa
_base_write=write
def clean(x):
    if isinstance(x,np.ndarray):return clean(x.tolist())
    if isinstance(x,np.generic):return clean(x.item())
    if isinstance(x,dict):return {str(k):clean(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)):return [clean(v) for v in x]
    if isinstance(x,Path):return str(x)
    if isinstance(x,float) and not math.isfinite(x):return None
    return x
def write(path,data):return _base_write(path,clean(data))

def table(path, rows, columns=None):
    rows=list(rows); p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    columns=columns or list(dict.fromkeys(k for r in rows for k in r)) or ['status']
    t=p.with_suffix(p.suffix+'.partial')
    with t.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=columns);w.writeheader()
        for r in rows:w.writerow({k:clean(r.get(k)) for k in columns})
    os.replace(t,p)

def npz(path, **arrays):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_name(p.name+'.partial.npz');np.savez_compressed(t,**arrays);os.replace(t,p)

def verify_package():
    p=ROOT/'PACKAGE_MANIFEST.json'
    for x in read(p):
        r=Path(x['path']);require(not r.is_absolute() and '..' not in r.parts,'Unsafe package path')
        require(sha(ROOT/r)==x['sha256'],'Changed package file: '+str(r))
    return sha(p)
