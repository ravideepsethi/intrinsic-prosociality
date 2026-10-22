"""Read-only inputs, atomic outputs and content-bound restart receipts."""
from __future__ import annotations
import hashlib, json, os, time, struct
from pathlib import Path
import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT=Path(__file__).resolve().parents[1]
VERSION='1.0.0'
DAY=86_400_000
SPEEDS=('ultrabullet','bullet','blitz','rapid','classical')
MONTHS=tuple(str(x) for x in pd.period_range('2023-11','2025-10',freq='M'))
def log(s):print(time.strftime('[%H:%M:%S UTC] ',time.gmtime())+str(s),flush=True)
def clean(x):
    if isinstance(x,dict):return {str(k):clean(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)):return [clean(v) for v in x]
    if isinstance(x,np.ndarray):return clean(x.tolist())
    if isinstance(x,np.generic):return clean(x.item())
    if isinstance(x,float) and not np.isfinite(x):return None
    if isinstance(x,Path):return str(x)
    return x
def read(p):return json.loads(Path(p).read_text())
def text(p,s):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_name(p.name+'.partial');t.write_text(s);os.replace(t,p)
def write(p,x):text(p,json.dumps(clean(x),sort_keys=True,indent=2,allow_nan=False)+'\n')
def digest(x):return hashlib.sha256(json.dumps(clean(x),sort_keys=True).encode()).hexdigest()
def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(8*1024**2),b''):h.update(b)
    return h.hexdigest()
def stamp(p):
    p=Path(p);s=p.stat();return dict(path=str(p.resolve()),bytes=s.st_size,mtime_ns=s.st_mtime_ns)
def record(p):return dict(**stamp(p),sha256=sha(p))
def verify(r):
    p=Path(r['path'])
    if not p.is_file() or p.stat().st_size!=r['bytes'] or sha(p)!=r['sha256']:
        raise RuntimeError('Output checksum mismatch: '+str(p))
def authenticate(p,work,expected,rows=None,size=None):
    fp=stamp(p);receipt=Path(work)/'authentication'/(digest(str(p))+'.json')
    old=read(receipt) if receipt.exists() else {}
    if size is not None and fp['bytes']!=size:raise RuntimeError('Input size differs: '+str(p))
    if rows is not None and pq.ParquetFile(p).metadata.num_rows!=rows:raise RuntimeError('Input row count differs: '+str(p))
    h=old['sha256'] if old.get('fingerprint')==fp else sha(p)
    if expected and h!=expected:raise RuntimeError('Input SHA256 differs: '+str(p))
    result=dict(fingerprint=fp,sha256=h);write(receipt,result);return result
def history_evidence(p,rows,size):
    """Bind source to frozen row/byte catalog and this run's raw footer digest.

    Catalog footer_signature_sha256 uses an undocumented legacy serialization;
    never call our raw-footer digest the same signature or a full-file checksum.
    """
    fp=stamp(p);pf=pq.ParquetFile(p)
    if fp['bytes']!=size or pf.metadata.num_rows!=rows:raise RuntimeError('Chronology catalog differs: '+str(p))
    required={'game_id','utc_ms','white_id','black_id','white_elo','black_elo'}
    if not required<=set(pf.schema_arrow.names):raise RuntimeError('Chronology schema differs: '+str(p))
    with open(p,'rb') as f:
        f.seek(-8,2);tail=f.read(8)
        if tail[4:]!=b'PAR1':raise RuntimeError('Invalid Parquet footer')
        length=struct.unpack('<I',tail[:4])[0];f.seek(-8-length,2);footer=f.read(length)
    return dict(fingerprint=fp,rows=rows,raw_footer_sha256=hashlib.sha256(footer).hexdigest(),
                check='frozen byte/row counts + schema; source fingerprint and raw footer bound to this run')
def q(x):return "'"+str(x).replace("'","''")+"'"
def scan(paths):
    if isinstance(paths,(str,Path)):paths=[paths]
    if not paths:raise ValueError('Empty file list')
    return 'read_parquet(['+','.join(q(p) for p in paths)+'],hive_partitioning=false,union_by_name=true)'
def connect(temp,threads=1,memory_mb=2048):
    Path(temp).mkdir(parents=True,exist_ok=True);c=duckdb.connect()
    c.execute(f'SET threads={int(threads)}');c.execute(f"SET memory_limit='{int(memory_mb)}MB'")
    c.execute('SET temp_directory='+q(temp));c.execute('SET preserve_insertion_order=false');return c
def copy(c,sql,p):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);t=p.with_name(p.name+'.partial');t.unlink(missing_ok=True)
    c.execute(f'COPY ({sql}) TO {q(t)} (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 65536)');os.replace(t,p)
def frame(df,p):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);t=p.with_name(p.name+'.partial')
    pq.write_table(pa.Table.from_pandas(df,preserve_index=False),t,compression='zstd');os.replace(t,p)
def finished(p,key,**extra):write(Path(p).with_suffix('.json'),dict(key=key,output=record(p),**extra))
def reusable(p,key):
    p=Path(p);r=p.with_suffix('.json')
    if not p.exists() or not r.exists():return False
    d=read(r)
    if d['key']!=key:raise RuntimeError('Cache identity changed: '+str(p))
    verify(d['output']);return True
