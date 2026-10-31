"""Atomic local outputs and bounded, single-threaded numerical work."""
from __future__ import annotations
import os
for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS','BLIS_NUM_THREADS'):
    os.environ[name]='1'
import hashlib,json,time,threading
from pathlib import Path
from contextlib import contextmanager

ROOT=Path(__file__).resolve().parents[1]
MONTHS=[f'{2023+(10+i)//12:04d}-{(10+i)%12+1:02d}' for i in range(24)]
def require(ok,message):
    if not ok: raise RuntimeError(message)
def read(p): return json.loads(Path(p).read_text())
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''):h.update(block)
    return h.hexdigest()
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
def save(p,value):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.name+'.partial')
    with tmp.open('w') as f:
        json.dump(value,f,sort_keys=True,indent=2,allow_nan=False,default=str);f.write('\n');f.flush();os.fsync(f.fileno())
    os.replace(tmp,p)
def signature(p):
    s=Path(p).stat();return [s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
def record(p,base=None):
    p=Path(p);return dict(path=str(p.relative_to(base) if base else p),bytes=p.stat().st_size,sha256=sha(p))
def verify(r,base=None):
    p=Path(base)/r['path'] if base else Path(r['path'])
    if base:require(p.resolve().is_relative_to(Path(base).resolve()),'Unsafe checkpoint path')
    require(p.is_file() and p.stat().st_size==r['bytes'] and sha(p)==r['sha256'],'File checksum differs: '+str(p))
    return p
def log(text):print(time.strftime('[%Y-%m-%d %H:%M:%S UTC] ',time.gmtime())+str(text),flush=True)
@contextmanager
def heartbeat(label):
    event=threading.Event();start=time.monotonic()
    def beat():
        while not event.wait(25):log(f'{label}; elapsed {(time.monotonic()-start)/60:.1f} min')
    thread=threading.Thread(target=beat,daemon=True);thread.start()
    try:yield
    finally:event.set();thread.join()
def sqlstr(x):return "'"+str(x).replace("'","''")+"'"
def parquet(paths):return 'read_parquet(['+','.join(sqlstr(p) for p in paths)+'],hive_partitioning=false)'
def db(spill,memory,threads):
    import duckdb
    spill=Path(spill);spill.mkdir(parents=True,exist_ok=True)
    c=duckdb.connect(config={'threads':str(threads),'memory_limit':f'{memory}GB','temp_directory':str(spill)})
    c.execute('SET preserve_insertion_order=false');return c
def table(p,rows):
    import pandas as pd
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    d=rows if isinstance(rows,pd.DataFrame) else pd.DataFrame(rows)
    tmp=p.with_name(p.name+'.partial');d.to_csv(tmp,index=False);os.replace(tmp,p)
