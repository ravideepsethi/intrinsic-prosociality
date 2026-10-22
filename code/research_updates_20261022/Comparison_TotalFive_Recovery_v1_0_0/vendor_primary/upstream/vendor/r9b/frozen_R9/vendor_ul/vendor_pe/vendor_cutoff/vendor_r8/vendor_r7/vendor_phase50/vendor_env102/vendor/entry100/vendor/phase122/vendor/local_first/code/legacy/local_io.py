"""Atomic, content-bound checkpoints. Only the new run directory is writable."""
from __future__ import annotations
import concurrent.futures as cf
import contextlib, datetime as dt, hashlib, json, os, threading, time, uuid
from pathlib import Path
import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

def log(s): print(dt.datetime.now(dt.timezone.utc).strftime('[%Y-%m-%d %H:%M:%SZ] ')+s,flush=True)
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(8*1024**2),b''):h.update(b)
    return h.hexdigest()
def clean(x):
    if isinstance(x,dict):return {str(k):clean(v) for k,v in x.items()}
    if isinstance(x,(list,tuple,np.ndarray)):return [clean(v) for v in x]
    if isinstance(x,np.generic):return clean(x.item())
    if isinstance(x,float) and not np.isfinite(x):return None
    return x
def cfgsha(x):return hashlib.sha256(json.dumps(clean(x),sort_keys=True,separators=(',',':')).encode()).hexdigest()
def comparison_v110_config_sha(x):
    """Exact producer format from comparison v1.1.0 analysis_io.cfgsha.

    That producer used json.dumps(sort_keys=True) with the default spaces.
    Our own run/checkpoint IDs intentionally retain the compact cfgsha above.
    Never accept an alternate digest or rewrite an upstream receipt on mismatch.
    """
    return hashlib.sha256(json.dumps(clean(x),sort_keys=True).encode()).hexdigest()
def load(p):return json.loads(Path(p).read_text())
def js(p,x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.name+'.partial_'+uuid.uuid4().hex)
    tmp.write_text(json.dumps(clean(x),sort_keys=True,indent=2,allow_nan=False)+'\n');os.replace(tmp,p)
def sig(p):
    s=Path(p).stat();return [s.st_size,s.st_mtime_ns]
def checked(p,h=None,size=None):
    p=Path(p)
    if not p.is_file():raise RuntimeError('Missing input: '+str(p))
    before=sig(p)
    if size is not None and before[0]!=int(size):raise RuntimeError('Input size changed: '+str(p))
    digest=sha(p)
    if h is not None and digest!=h:raise RuntimeError('Input checksum changed: '+str(p))
    if sig(p)!=before:raise RuntimeError('Input changed during read: '+str(p))
    return dict(path=str(p),sha256=digest,signature=before)
def child(root,n):
    p=Path(n)
    if p.is_absolute() or '..' in p.parts:raise RuntimeError('Invalid manifest path')
    out=Path(root)/p
    if Path(root).resolve() not in out.resolve().parents:raise RuntimeError('Path escapes root')
    return out
def read(p,cols=None):return pq.ParquetFile(p).read(columns=cols,use_threads=False)
def arr(t,n):
    c=t[n].combine_chunks()
    if pa.types.is_string(c.type) or pa.types.is_large_string(c.type):return np.asarray(c.to_pylist())
    return c.to_numpy(zero_copy_only=False)
def table(p,t):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_name(p.name+'.partial_'+uuid.uuid4().hex)
    pq.write_table(t,tmp,compression='zstd',row_group_size=131072);os.replace(tmp,p)
def lit(s):return "'"+str(s).replace("'","''")+"'"
def parq(paths):
    paths=[str(p) for p in paths]
    if not paths:raise RuntimeError('Empty input file set')
    return 'read_parquet(['+','.join(map(lit,paths))+'],hive_partitioning=false)'
def conn(temp,memory=2,threads=1):
    temp=Path(temp);temp.mkdir(parents=True,exist_ok=True)
    c=duckdb.connect();c.execute('SET temp_directory='+lit(temp));c.execute('SET memory_limit='+lit(str(memory)+'GB'))
    c.execute('SET threads='+str(threads));c.execute('SET preserve_insertion_order=false');return c
def copy(c,query,path):
    return int(c.execute('COPY ('+query+') TO '+lit(path)+" (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 131072)").fetchone()[0])
def complete(root,conf):
    root=Path(root);p=root/'_DONE.json'
    if not p.exists():return None
    r=load(p)
    if r.get('config_sha256')!=conf:raise RuntimeError('Checkpoint configuration differs: '+str(root))
    for f in r['files']:checked(child(root,f['path']),f['sha256'],f['bytes'])
    return r
def stage(root,conf,producer):
    root=Path(root);old=complete(root,conf)
    if old:return root,old
    root.parent.mkdir(parents=True,exist_ok=True)
    if root.exists():raise RuntimeError('Unrecognized incomplete final directory: '+str(root))
    tmp=root.with_name(root.name+'.partial_'+uuid.uuid4().hex);tmp.mkdir()
    info=producer(tmp) or {}
    files=[dict(path=p.relative_to(tmp).as_posix(),sha256=sha(p),bytes=p.stat().st_size)
           for p in sorted(tmp.rglob('*')) if p.is_file() and 'spill' not in p.parts]
    r=dict(config_sha256=conf,files=files,**info);js(tmp/'_DONE.json',r);os.replace(tmp,root);return root,r
@contextlib.contextmanager
def heartbeat(label):
    stop=threading.Event()
    def beat():
        while not stop.wait(45):log(label+' — working')
    t=threading.Thread(target=beat,daemon=True);t.start()
    try:yield
    finally:stop.set();t.join()
def mapped(fn,jobs,workers,label):
    import multiprocessing as mp
    results=[]
    with cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn')) as ex:
        pending={ex.submit(fn,j):k for k,j in enumerate(jobs)}
        with heartbeat(label):
            for f in cf.as_completed(pending):
                results.append((pending[f],f.result()));log(f'{label}: {len(results)}/{len(jobs)} complete')
    return [r for _,r in sorted(results)]
