"""Local Parquet I/O and immutable-input checks. Runtime: seconds to minutes."""
from __future__ import annotations
import hashlib, json, os, time
from pathlib import Path
from datetime import datetime, timezone
import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

VERSION = '1.0.0'
PACKAGE = Path(__file__).resolve().parents[1]
ADVANTAGE = 11.782457
SPEEDS = ('ultrabullet','bullet','blitz','rapid','classical')
def ms(x): return int(pd.Timestamp(x, tz='UTC').timestamp()*1000)
BRACKET = ms('2025-11-18 07:15:00')
CUTOFF = ms('2025-11-18 07:22:00')
ANNOUNCEMENT = ms('2025-12-22 22:35:00')
JAN7 = ms('2026-01-07 00:00:00')
JAN30 = ms('2026-01-30 00:00:00')
START = ms('2023-11-01 00:00:00')
STOP = ms('2026-02-01 00:00:00')
MONTHS = tuple(str(x) for x in pd.period_range('2023-11','2026-01',freq='M'))

def log(s): print('['+datetime.now(timezone.utc).strftime('%H:%M:%S UTC')+'] '+str(s),flush=True)
def read_json(p): return json.loads(Path(p).read_text())
def atomic_text(p,s):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_name(p.name+f'.tmp-{os.getpid()}');t.write_text(s);os.replace(t,p)
def write_json(p,x): atomic_text(p,json.dumps(x,indent=2,sort_keys=True,default=str,allow_nan=False)+'\n')
def digest(x): return hashlib.sha256(json.dumps(x,sort_keys=True,default=str).encode()).hexdigest()
def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(8*1024**2),b''):h.update(b)
    return h.hexdigest()
def stamp(p):
    p=Path(p);s=p.stat();return dict(path=str(p.resolve()),size=s.st_size,mtime_ns=s.st_mtime_ns)
def q(x): return "'"+str(x).replace("'","''")+"'"
def ident(x): return '"'+str(x).replace('"','""')+'"'
def scan(p):
    ps=[p] if isinstance(p,(str,Path)) else p
    if not ps: raise ValueError('Empty Parquet source')
    return 'read_parquet(['+','.join(q(x) for x in ps)+'],hive_partitioning=false,union_by_name=true)'
def schema(p): return set(pq.ParquetFile(p).schema_arrow.names)
def choose(cols,names,alias='s',required=True):
    for n in names:
        if n in cols:return alias+'.'+ident(n)
    if required:raise ValueError('Missing column: '+str(names))
    return 'NULL'
def finite_sql(x): return f'CASE WHEN isfinite(try_cast({x} AS DOUBLE)) THEN try_cast({x} AS DOUBLE) END'
def connection(temp,threads=1,memory_mb=768):
    Path(temp).mkdir(parents=True,exist_ok=True);c=duckdb.connect()
    c.execute(f'SET threads={int(threads)}');c.execute(f"SET memory_limit='{int(memory_mb)}MB'")
    c.execute(f'SET temp_directory={q(temp)}');c.execute('SET preserve_insertion_order=false')
    return c
def copy(c,sql,p):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);t=p.with_name(p.name+f'.tmp-{os.getpid()}')
    t.unlink(missing_ok=True)
    c.execute(f'COPY ({sql}) TO {q(t)} (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 100000)')
    os.replace(t,p)
def export(c,sql,p):
    p=Path(p);copy(c,sql,p)
    c.execute(f'COPY (SELECT * FROM {scan(p)}) TO {q(p.with_suffix(".csv"))} (HEADER)')
def frame(df,p):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_name(p.name+f'.tmp-{os.getpid()}');pq.write_table(pa.Table.from_pandas(df,preserve_index=False),t,compression='zstd');os.replace(t,p)
def receipt(p): return dict(**stamp(p),sha256=sha(p),rows=pq.ParquetFile(p).metadata.num_rows)
def verify_record(p,rec,work):
    """Reuse a prior SHA check only if its exact fingerprint is unchanged."""
    p=Path(p);s=stamp(p);expected=rec.get('sha256') or rec.get('output_sha256')
    if not expected: raise RuntimeError('Missing authority SHA for '+str(p))
    wanted=rec.get('size',rec.get('size_bytes'))
    if wanted is not None and s['size']!=wanted:raise RuntimeError('Size differs: '+str(p))
    cache=Path(work)/'authentication'/(digest(str(p.resolve()))+'.json')
    old=read_json(cache) if cache.is_file() else {}
    if old.get('fingerprint')==s and old.get('sha256')==expected:return old
    # Earlier completed-run receipt already contains its hashed output's fingerprint.
    if all(rec.get(k)==s[k] for k in ('path','size','mtime_ns')):
        how='prior completed-run SHA receipt; unchanged metadata'
    else:
        if sha(p)!=expected:raise RuntimeError('SHA mismatch: '+str(p))
        how='fresh SHA verification'
    out=dict(fingerprint=s,sha256=expected,method=how);write_json(cache,out);return out
def cached(p,key):
    p=Path(p);rp=p.with_suffix('.json')
    if not p.is_file() or not rp.is_file():return False
    r=read_json(rp)
    if r.get('key')!=key:raise RuntimeError('Cached inputs changed; preserve and review: '+str(p))
    if r['output']['sha256']!=sha(p):raise RuntimeError('Cached output damaged: '+str(p))
    return r
def commit(p,key,**extra):
    r=dict(key=key,output=receipt(p),**extra);write_json(Path(p).with_suffix('.json'),r);return r
def time_expr(cols,a='s'):
    if 'utc_ms' in cols:return f'try_cast({a}.utc_ms AS BIGINT)'
    if {'utc_date','utc_time'}<=cols:return f"epoch_ms(try_strptime(replace(cast({a}.utc_date AS VARCHAR),'.','-')||' '||cast({a}.utc_time AS VARCHAR),'%Y-%m-%d %H:%M:%S'))"
    return None
def period_sql(x='utc_ms'):
    return f"CASE WHEN {x}<{BRACKET} THEN 'pre' WHEN {x}<{CUTOFF} THEN 'transition' WHEN {x}<{ANNOUNCEMENT} THEN 'implemented_unannounced' WHEN {x}<{JAN7} THEN 'announced_before_jan7' WHEN {x}<{JAN30} THEN 'jan7_to_jan30_scenario' ELSE 'jan30_onward_unclassified' END"

