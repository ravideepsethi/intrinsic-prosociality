"""Bounded Parquet I/O and restart receipts. No upstream writes."""
from __future__ import annotations
import hashlib,json,os,time
from pathlib import Path
import duckdb,numpy as np,pandas as pd,pyarrow as pa,pyarrow.parquet as pq
pa.set_cpu_count(1)
pa.set_io_thread_count(1)

ROOT=Path(__file__).resolve().parents[1]
VERSION='1.0.2'
DAY=86400000
IMPLEMENTED=1763450520000
ANNOUNCED=1766442900000
ADVANTAGE=11.782457
MODELS=('cost','loss','curved','framing','strength','strength_loss','strength_framing')
REQUIRED=('game_id','chooser','t','speed','color','y','cp','ply','rating','opp_rating','g','rd','opp_rd',
          'rg','rc','ki','kj','clock','opp_clock','month','history_days','prior_starts','inactivity_days','opp_prior_starts')
PREDICT_FIELDS=tuple(x for x in REQUIRED if x!='y')

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
def digest(x):return hashlib.sha256(json.dumps(clean(x),sort_keys=True).encode()).hexdigest()
def text(p,s):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.name+'.partial-'+str(os.getpid()))
    tmp.write_text(s);os.replace(tmp,p)
def write(p,x):text(p,json.dumps(clean(x),indent=2,sort_keys=True,allow_nan=False)+'\n')
def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(8*1024**2),b''):h.update(b)
    return h.hexdigest()
def stamp(p):
    p=Path(p);s=p.stat();return dict(path=str(p.resolve()),bytes=s.st_size,mtime_ns=s.st_mtime_ns)
def auth(p,work,expected=None,rows=None):
    p=Path(p);before=stamp(p);cache=Path(work)/'authentication'/(digest(str(p.resolve()))+'.json')
    prior=read(cache) if cache.exists() else {}
    h=prior['sha256'] if prior.get('stamp')==before else sha(p)
    if expected and h!=expected:raise RuntimeError('Input SHA mismatch: '+str(p))
    if rows is not None and pq.ParquetFile(p).metadata.num_rows!=int(rows):raise RuntimeError('Input row count mismatch: '+str(p))
    if stamp(p)!=before:raise RuntimeError('Input changed while reading: '+str(p))
    out=dict(stamp=before,sha256=h);write(cache,out);return out
def q(x):return "'"+str(x).replace("'","''")+"'"
def scan(paths):
    if isinstance(paths,(str,Path)):paths=[paths]
    if not paths:raise ValueError('Empty Parquet input list')
    return 'read_parquet(['+','.join(q(p) for p in paths)+'],hive_partitioning=false,union_by_name=true)'
def connect(temp,threads=1,memory_mb=768):
    Path(temp).mkdir(parents=True,exist_ok=True);c=duckdb.connect()
    c.execute(f'SET threads={int(threads)}');c.execute(f"SET memory_limit='{int(memory_mb)}MB'")
    c.execute('SET temp_directory='+q(temp));c.execute('SET preserve_insertion_order=false');return c
def copy(c,sql,p):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.name+'.partial-'+str(os.getpid()))
    tmp.unlink(missing_ok=True);c.execute(f'COPY ({sql}) TO {q(tmp)} (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 65536)');os.replace(tmp,p)
def frame(d,p):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.name+'.partial-'+str(os.getpid()))
    pq.write_table(pa.Table.from_pandas(d,preserve_index=False),tmp,compression='zstd');os.replace(tmp,p)
def table(d,p):
    d=d if isinstance(d,pd.DataFrame) else pd.DataFrame(d)
    if not len(d.columns):d=pd.DataFrame({'status':['NO_ROWS']})
    frame(d,p);d.to_csv(Path(p).with_suffix('.csv'),index=False)
def receipt(p,key,**kw):
    r=dict(key=key,output=dict(**stamp(p),sha256=sha(p)),**kw);write(Path(p).with_suffix('.json'),r);return r
def reusable(p,key):
    p=Path(p);r=p.with_suffix('.json')
    if not p.exists() or not r.exists():return False
    old=read(r)
    if old['key']!=key:raise RuntimeError('Inputs changed for existing cache; preserve it: '+str(p))
    if old['output']['sha256']!=sha(p):raise RuntimeError('Output cache SHA mismatch: '+str(p))
    return old
def weeks(t):
    """UTC Monday starts, in Unix milliseconds, without a datetime-unit cast."""
    a=np.asarray(t)
    if a.dtype.kind not in 'iuf' or not np.isfinite(a).all():
        raise ValueError('Week grouping requires finite Unix milliseconds')
    if a.dtype.kind=='f' and not np.equal(a,np.trunc(a)).all():
        raise ValueError('Week grouping requires integer Unix milliseconds')
    if np.any(a < -62135596800000) or np.any(a >= 253402300800000):
        raise ValueError('Timestamp outside supported years 0001–9999')
    a=a.astype(np.int64)
    # Unix epoch was Thursday: offset by three days to put Mondays on multiples of 7.
    day=np.floor_divide(a,DAY)
    return (np.floor_divide(day+3,7)*7-3)*DAY
def complete_weeks(lo,hi):
    lo,hi=int(lo),int(hi)
    if hi<=lo:return np.empty(0,dtype=np.int64)
    a=int(weeks([lo])[0]);a+=7*DAY if a<lo else 0
    result=np.arange(a,hi-7*DAY+1,7*DAY,dtype=np.int64)
    if len(result) and (result[0]<lo or result[-1]+7*DAY>hi):
        raise RuntimeError('Complete calendar weeks escaped their requested interval')
    return result
def remap(original,project):
    tag='/lichess_kindness/'
    if tag not in str(original):raise ValueError('Unrecognized project path: '+str(original))
    return Path(project)/str(original).split(tag,1)[1]
def compact(d):
    for k in ('month','speed','color'):
        if k in d:d[k]=d[k].astype('category')
    return d
