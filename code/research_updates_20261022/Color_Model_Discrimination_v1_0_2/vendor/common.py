"""Immutable-input I/O, small public tables, and restart receipts."""
from __future__ import annotations
import hashlib, json, os, time
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import duckdb

ROOT=Path(__file__).resolve().parents[1]
VERSION='1.0.0'
DAY=86400000
SPEEDS=('ultrabullet','bullet','blitz','rapid','classical')
MONTHS=tuple(str(m) for m in pd.period_range('2023-11','2025-10',freq='M'))
def log(s): print(time.strftime('[%H:%M:%S UTC] ',time.gmtime())+str(s),flush=True)
def clean(x):
    if isinstance(x,dict):return {str(k):clean(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)):return [clean(v) for v in x]
    if isinstance(x,np.ndarray):return clean(x.tolist())
    if isinstance(x,np.generic):return clean(x.item())
    if isinstance(x,float) and not np.isfinite(x):return None
    if isinstance(x,Path):return str(x)
    return x
def digest(x):return hashlib.sha256(json.dumps(clean(x),sort_keys=True).encode()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
def write(p,x):text(p,json.dumps(clean(x),indent=2,sort_keys=True,allow_nan=False)+'\n')
def text(p,s):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_name(p.name+'.partial-'+str(os.getpid()));t.write_text(s);os.replace(t,p)
def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(8*1024**2),b''):h.update(b)
    return h.hexdigest()
def stamp(p):
    p=Path(p);s=p.stat();return dict(path=str(p.resolve()),size=s.st_size,mtime_ns=s.st_mtime_ns)
def auth(p,work,expected=None,rows=None,size=None):
    p=Path(p);s=stamp(p);out=Path(work)/'authentication'/(digest(str(p.resolve()))+'.json')
    old=read(out) if out.exists() else {}
    if size is not None and s['size']!=int(size):raise RuntimeError('Input size differs: '+str(p))
    if rows is not None and pq.ParquetFile(p).metadata.num_rows!=int(rows):raise RuntimeError('Input row count differs: '+str(p))
    h=old['sha256'] if old.get('fingerprint')==s else sha(p)
    if expected and h!=expected:raise RuntimeError('Input SHA differs: '+str(p))
    result=dict(fingerprint=s,sha256=h,expected_sha256=expected)
    write(out,result);return result
def q(s):return "'"+str(s).replace("'","''")+"'"
def scan(ps):
    if isinstance(ps,(str,Path)):ps=[ps]
    if not ps:raise ValueError('No Parquet files')
    return 'read_parquet(['+','.join(q(p) for p in ps)+'],hive_partitioning=false,union_by_name=true)'
def cols(p):return set(pq.ParquetFile(p).schema_arrow.names)
def connect(temp,threads=1,memory_mb=768):
    Path(temp).mkdir(parents=True,exist_ok=True);c=duckdb.connect()
    c.execute(f'SET threads={int(threads)}');c.execute(f"SET memory_limit='{int(memory_mb)}MB'")
    c.execute('SET temp_directory='+q(temp));c.execute('SET preserve_insertion_order=false');return c
def copy(c,sql,p):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);t=p.with_name(p.name+'.partial-'+str(os.getpid()))
    t.unlink(missing_ok=True)
    c.execute(f'COPY ({sql}) TO {q(t)} (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 65536)');os.replace(t,p)
def frame(df,p):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);t=p.with_name(p.name+'.partial-'+str(os.getpid()))
    pq.write_table(pa.Table.from_pandas(df,preserve_index=False),t,compression='zstd');os.replace(t,p)
def table(rows,p):
    df=rows if isinstance(rows,pd.DataFrame) else pd.DataFrame(rows)
    if not len(df.columns):df=pd.DataFrame({'status':['NO_ROWS']})
    frame(df,p);df.to_csv(Path(p).with_suffix('.csv'),index=False)
def done(p,key,**extra):
    r=dict(key=key,output=dict(**stamp(p),sha256=sha(p)),**extra);write(Path(p).with_suffix('.json'),r);return r
def reuse(p,key):
    p=Path(p);r=p.with_suffix('.json')
    if not p.exists() or not r.exists():return False
    d=read(r)
    if d['key']!=key:raise RuntimeError('Cache inputs changed; preserve this run: '+str(p))
    if d['output']['sha256']!=sha(p):raise RuntimeError('Cache checksum differs: '+str(p))
    return d
def payoff(r,opp,rd,opp_rd,color=1.,advantage=0.):
    """Exact novol/noreg calculator copied algebraically from certified first pass.
    Both alternatives share K only under that anchored convention.
    """
    r,opp,rd,opp_rd,color=np.broadcast_arrays(*map(lambda a:np.asarray(a,float),(r,opp,rd,opp_rd,color)))
    if np.any(~np.isfinite(r+opp+rd+opp_rd+color)) or np.any((rd<=0)|(opp_rd<=0)|~np.isin(color,[-1,1])):
        raise ValueError('Invalid payoff state')
    scale=173.7178;h=1/np.sqrt(1+3*(np.maximum(opp_rd,45)/scale)**2/np.pi**2)
    e=1/(1+np.exp(np.clip(-h*(r-opp+color*advantage)/scale,-700,700)))
    e=np.clip(e,1e-12,1-1e-12)
    k=scale*h/(1/(np.maximum(rd,45)/scale)**2+h*h*e*(1-e))
    return e,k,k*(.5-e),k*(1-e)
def check_payoffs(df,tol=1e-6):
    e,k,g,c=payoff(df.rating,df.opp_rating,df.rd,df.opp_rd)
    err=max(np.max(abs(df.rg.to_numpy()-g),initial=0),np.max(abs(df.rc.to_numpy()-c),initial=0),
            np.max(abs((df.ki-(df.rc-df.rg)).to_numpy()),initial=0))
    _,ko,_,_=payoff(df.opp_rating,df.rating,df.opp_rd,df.rd)
    err=max(err,np.max(abs(df.kj.to_numpy()-ko/2),initial=0))
    if not np.isfinite(err) or err>tol:raise RuntimeError('Certified payoff identity/reconstruction mismatch: '+str(err))
    return float(err)
