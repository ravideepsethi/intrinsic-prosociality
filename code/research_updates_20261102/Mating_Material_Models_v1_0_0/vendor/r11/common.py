"""Small, atomic and fingerprinted I/O for the A1 follow-up."""
from __future__ import annotations
import os
# Must precede imports of numerical libraries, including imports in spawned workers.
for _name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS',
              'VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS','BLIS_NUM_THREADS'):
    os.environ[_name] = '1'
import hashlib, json, time, platform, subprocess, threading
from pathlib import Path
from contextlib import contextmanager
import numpy as np
import pandas as pd
import duckdb
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent
VERSION = '1.0.0'

def log(s): print(time.strftime('[%Y-%m-%d %H:%M:%S] ', time.gmtime())+s, flush=True)
def require(ok,s):
    if not ok: raise RuntimeError(s)
def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''): h.update(b)
    return h.hexdigest()
def fingerprint(x): return hashlib.sha256(json.dumps(x,sort_keys=True,default=str).encode()).hexdigest()
def load(p): return json.loads(Path(p).read_text())
def dump(p,x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_name(p.name+'.partial')
    with open(t,'w') as f:
        json.dump(x,f,indent=2,sort_keys=True,allow_nan=False,default=str);f.write('\n');f.flush();os.fsync(f.fileno())
    os.replace(t,p)
def npz(p,**x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);t=p.with_name(p.name+'.partial')
    with open(t,'wb') as f: np.savez_compressed(f,**x)
    os.replace(t,p)
def qs(v): return "'"+str(v).replace("'","''")+"'"
def parq(paths):return 'read_parquet(['+','.join(qs(p) for p in paths)+'],hive_partitioning=false)'
def dbopen(spill,threads=1,memory_gb=1):
    Path(spill).mkdir(parents=True,exist_ok=True)
    d=duckdb.connect(config={'threads':str(threads),'memory_limit':f'{memory_gb:.2f}GB','temp_directory':str(spill)})
    d.execute('SET preserve_insertion_order=false')
    return d
def stamp(p):
    s=Path(p).stat();return dict(bytes=s.st_size,mtime_ns=s.st_mtime_ns,ctime_ns=s.st_ctime_ns)
def certify(p,key,extra=None):
    r=dict(key=key,sha256=sha(p),stat=stamp(p));r.update(extra or {});dump(str(p)+'.ok.json',r)
def valid(p,key):
    p=Path(p);c=Path(str(p)+'.ok.json')
    if not p.is_file() or not c.is_file(): return False
    r=load(c)
    return r['key']==key and r['sha256']==sha(p)
def table(p,rows):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    d=pd.DataFrame(rows) if not isinstance(rows,pd.DataFrame) else rows
    d.to_parquet(p.with_suffix('.parquet'),index=False,compression='zstd')
    d.to_csv(p.with_suffix('.csv'),index=False)
def physical_gb():
    try:
        if platform.system()=='Darwin': return int(subprocess.check_output(['sysctl','-n','hw.memsize']))/2**30
        return os.sysconf('SC_PAGE_SIZE')*os.sysconf('SC_PHYS_PAGES')/2**30
    except Exception:return 16.
@contextmanager
def heartbeat(label):
    stop=threading.Event()
    def beat():
        while not stop.wait(45):log(label+' — working')
    t=threading.Thread(target=beat,daemon=True);t.start()
    try:yield
    finally:stop.set();t.join()
