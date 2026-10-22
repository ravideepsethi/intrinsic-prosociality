"""Immutable inputs, atomic checkpoints and explicit UTC milliseconds."""
from __future__ import annotations
import contextlib,datetime as dt,fcntl,hashlib,json,os,threading,time,uuid
from pathlib import Path
import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT=Path(__file__).resolve().parents[1]
VERSION='1.0.0'
DAY=86400000
WEEK=7*DAY
SPEEDS=('ultrabullet','bullet','blitz','rapid','classical')
MONTHS=tuple(str(m) for m in pd.period_range('2023-11','2025-10',freq='M'))
POST_MONTHS=('2025-11','2025-12','2026-01')
IMPLEMENTED=1763450520000
BRACKET=1763450100000
ANNOUNCED=1766442900000
START=1698796800000
STOP=1769817600000
ADVANTAGE=11.782457
MECH='derived/replication/mechanism_separation_v100_PRIVATE'
FIRST='derived/replication_36m/color_change_firstpass_v100'
SHARED='derived/replication_36m/receipt_iv_cohort_extension_v100_PRIVATE'

def ms(s):
    t=pd.Timestamp(s)
    if t.tzinfo is None:raise ValueError('Explicit timezone required')
    return int(t.timestamp()*1000)
def log(s):print(dt.datetime.now(dt.timezone.utc).strftime('[%H:%M:%S UTC] ')+str(s),flush=True)
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(8*1024**2),b''):h.update(b)
    return h.hexdigest()
def clean(x):
    if isinstance(x,dict):return {str(k):clean(v) for k,v in x.items()}
    if isinstance(x,(list,tuple,np.ndarray)):return [clean(v) for v in x]
    if isinstance(x,np.generic):return clean(x.item())
    if isinstance(x,Path):return str(x)
    if isinstance(x,float) and not np.isfinite(x):return None
    return x
def digest(x):return hashlib.sha256(json.dumps(clean(x),sort_keys=True).encode()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
def write(p,x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_name(p.name+'.partial_'+uuid.uuid4().hex)
    t.write_text(json.dumps(clean(x),indent=2,sort_keys=True,allow_nan=False)+'\n');os.replace(t,p)
def stamp(p):
    p=Path(p);s=p.stat()
    return dict(path=str(p.resolve()),size=s.st_size,mtime_ns=s.st_mtime_ns,ctime_ns=s.st_ctime_ns)
def snapshot(p):return dict(path=str(Path(p).resolve()),sha256=sha(p),fingerprint=stamp(p))
def relocated(p,project):
    p=Path(p)
    if p.is_absolute():
        try:p=p.relative_to('/Volumes/XT_Pro/lichess_kindness')
        except ValueError:
            if p.is_relative_to(Path(project).resolve()):return p
            raise RuntimeError('Producer path outside project')
    if '..' in p.parts:raise RuntimeError('Unsafe relative producer path')
    return Path(project)/p
def auth(p,work,expected=None,rows=None,size=None):
    p=Path(p);before=stamp(p)
    if size is not None and before['size']!=int(size):raise RuntimeError('Input byte count changed: '+p.name)
    if rows is not None and pq.ParquetFile(p).metadata.num_rows!=int(rows):raise RuntimeError('Input row count changed: '+p.name)
    saved=Path(work)/'authentication'/(digest(str(p.resolve()))+'.json')
    old=read(saved) if saved.exists() else {}
    h=old['sha256'] if old.get('fingerprint')==before else sha(p)
    if expected is not None and h!=expected:raise RuntimeError('Input checksum changed: '+p.name)
    if stamp(p)!=before:raise RuntimeError('Input changed while reading: '+p.name)
    result=dict(path=str(p.resolve()),sha256=h,fingerprint=before)
    write(saved,result);return result
def record_auth(p,r,work):
    return auth(p,work,r.get('sha256',r.get('output_sha256')),r.get('rows'),r.get('bytes',r.get('size_bytes',r.get('size'))))
def unchanged(records):
    for r in records:
        if stamp(r['path'])!=r['fingerprint']:raise RuntimeError('Input changed during stage: '+Path(r['path']).name)
def q(x):return "'"+str(x).replace("'","''")+"'"
def scan(paths):
    if isinstance(paths,(str,Path)):paths=[paths]
    if not paths:raise ValueError('No Parquet inputs')
    return 'read_parquet(['+','.join(q(p) for p in paths)+'],hive_partitioning=false,union_by_name=true)'
def cols(p):return set(pq.ParquetFile(p).schema_arrow.names)
def connect(temp,threads=1,memory=768):
    Path(temp).mkdir(parents=True,exist_ok=True);c=duckdb.connect()
    threads=min(threads,int(os.environ.get('COLOR_DUCKDB_THREAD_LIMIT','10')))
    c.execute(f'SET threads={int(threads)}');c.execute(f"SET memory_limit='{int(memory)}MB'")
    c.execute('SET temp_directory='+q(temp));c.execute('SET preserve_insertion_order=false');return c
def copy(c,query,p):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.name+'.partial_'+uuid.uuid4().hex)
    n=c.execute('COPY ('+query+') TO '+q(tmp)+' (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 131072)').fetchone()[0]
    os.replace(tmp,p);return int(n)
def frame(d,p):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);t=p.with_name(p.name+'.partial_'+uuid.uuid4().hex)
    pq.write_table(pa.Table.from_pandas(d,preserve_index=False),t,compression='zstd');os.replace(t,p)
def table(d,p):
    d=d if isinstance(d,pd.DataFrame) else pd.DataFrame(d)
    if not len(d.columns):d=pd.DataFrame({'status':['NO_ROWS']})
    p=Path(p);frame(d,p.with_suffix('.parquet'));d.to_csv(p.with_suffix('.csv'),index=False)
def cache(p,key,work):
    p=Path(p);rp=p.with_suffix('.json')
    if not rp.exists():return False
    r=read(rp)
    if r['key']!=key:raise RuntimeError('Completed stage belongs to different inputs: '+p.name)
    if r.get('code_signature')!=CODE_SIGNATURE:raise RuntimeError('Completed stage belongs to different code: '+p.name)
    record_auth(p,r['output'],work);return r
def commit(p,key,**extra):
    p=Path(p);r=dict(key=key,code_signature=CODE_SIGNATURE,output=dict(path=str(p.resolve()),sha256=sha(p),bytes=p.stat().st_size,rows=pq.ParquetFile(p).metadata.num_rows),**extra)
    write(p.with_suffix('.json'),r);return r
@contextlib.contextmanager
def heartbeat(label):
    stop=threading.Event()
    def pulse():
        while not stop.wait(30):log(label+' — working')
    t=threading.Thread(target=pulse,daemon=True);t.start()
    try:yield
    finally:stop.set();t.join()
@contextlib.contextmanager
def lock(path,wait=False,shared=False):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('a+') as f:
        while True:
            try:fcntl.flock(f,(fcntl.LOCK_SH if shared else fcntl.LOCK_EX)|fcntl.LOCK_NB);break
            except BlockingIOError:
                if not wait:raise RuntimeError('Another run holds '+p.name)
                log('Waiting for the shared source/membership producer to finish');time.sleep(30)
        try:yield
        finally:fcntl.flock(f,fcntl.LOCK_UN)
def week_ms(t):
    a=np.asarray(t,dtype=np.int64);return ((a-4*DAY)//WEEK)*WEEK+4*DAY
def complete_weeks(lo,hi):
    first=int(week_ms(lo))
    if first<lo:first+=WEEK
    return np.arange(first,int(week_ms(hi)),WEEK,dtype=np.int64)
def expit(x):
    x=np.asarray(x,float);out=np.empty_like(x);m=x>=0
    out[m]=1/(1+np.exp(-x[m]));z=np.exp(x[~m]);out[~m]=z/(1+z);return out
def logit(x):return np.log(x)-np.log1p(-x)
def payoff(r,opp,rd,opp_rd,color=1.,advantage=0.):
    r,opp,rd,opp_rd,color=np.broadcast_arrays(*[np.asarray(a,float) for a in (r,opp,rd,opp_rd,color)])
    if not np.isfinite(r+opp+rd+opp_rd+color).all() or ((rd<=0)|(opp_rd<=0)|~np.isin(color,[-1,1])).any():raise ValueError('Invalid payoff state')
    scale=173.7178;h=1/np.sqrt(1+3*(np.maximum(opp_rd,45)/scale)**2/np.pi**2)
    e=np.clip(expit(h*(r-opp+color*advantage)/scale),1e-12,1-1e-12)
    k=scale*h/(1/(np.maximum(rd,45)/scale)**2+h*h*e*(1-e))
    return e,k,k*(.5-e),k*(1-e)

CODE_SIGNATURE=digest({p.name:sha(p) for p in sorted((ROOT/'code').glob('*.py'))})
