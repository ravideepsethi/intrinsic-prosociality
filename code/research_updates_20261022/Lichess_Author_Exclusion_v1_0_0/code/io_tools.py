from __future__ import annotations
import contextlib,datetime as dt,fcntl,hashlib,json,os,threading,uuid
from pathlib import Path
import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

def log(x):print(dt.datetime.now(dt.timezone.utc).strftime('[%H:%M:%S UTC] ')+str(x),flush=True)
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(8*1024**2),b''):h.update(b)
    return h.hexdigest()
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,default=str).encode()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
def write(p,x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);t=p.with_name(p.name+'.partial_'+uuid.uuid4().hex)
    t.write_text(json.dumps(x,sort_keys=True,indent=2,allow_nan=False,default=str)+'\n');os.replace(t,p)
def stamp(p):
    p=Path(p);s=p.stat();return dict(path=str(p.resolve()),size=s.st_size,mtime_ns=s.st_mtime_ns,ctime_ns=s.st_ctime_ns)
def authenticate(p,expected,work,rows=None):
    p=Path(p);before=stamp(p)
    if rows is not None and pq.ParquetFile(p).metadata.num_rows!=int(rows):raise RuntimeError('Input row count differs: '+p.name)
    dest=Path(work)/'authentication'/(digest(str(p.resolve()))+'.json');saved=read(dest) if dest.exists() else {}
    h=saved['sha256'] if saved.get('fingerprint')==before else sha(p)
    if expected and h!=expected:raise RuntimeError('Input checksum differs: '+p.name)
    if stamp(p)!=before:raise RuntimeError('Input changed during authentication')
    result=dict(path=str(p.resolve()),sha256=h,fingerprint=before);write(dest,result);return result
def file_record(p):
    p=Path(p);r=dict(path=str(p.resolve()),sha256=sha(p),bytes=p.stat().st_size)
    if p.suffix=='.parquet':r['rows']=pq.ParquetFile(p).metadata.num_rows
    return r
def verify_record(r):
    p=Path(r['path'])
    if p.stat().st_size!=r['bytes'] or sha(p)!=r['sha256']:raise RuntimeError('Completed output changed: '+p.name)
def sqlstr(x):return "'"+str(x).replace("'","''")+"'"
def scan(paths):
    if isinstance(paths,(str,Path)):paths=[paths]
    if not paths:raise RuntimeError('Empty dataset')
    return 'read_parquet(['+','.join(sqlstr(p) for p in paths)+'],hive_partitioning=false,union_by_name=true)'
def connect(work,threads=1):
    Path(work).mkdir(parents=True,exist_ok=True);c=duckdb.connect()
    c.execute('SET threads='+str(int(threads)));c.execute("SET memory_limit='768MB'")
    c.execute('SET temp_directory='+sqlstr(work));c.execute('SET preserve_insertion_order=false');return c
def copy(c,query,p):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);t=p.with_name(p.name+'.partial_'+uuid.uuid4().hex)
    n=c.execute('COPY ('+query+') TO '+sqlstr(t)+' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 131072)').fetchone()[0]
    os.replace(t,p);return int(n)
def table(rows,p):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);d=pd.DataFrame(rows)
    if not len(d.columns):d=pd.DataFrame(columns=['status'])
    d.to_csv(p.with_suffix('.csv'),index=False);d.to_parquet(p.with_suffix('.parquet'),index=False)
@contextlib.contextmanager
def lock(p):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('a+') as f:
        try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('An author-exclusion run is already active')
        try:yield
        finally:fcntl.flock(f,fcntl.LOCK_UN)
@contextlib.contextmanager
def heartbeat(label):
    stop=threading.Event()
    def pulse():
        while not stop.wait(30):log(label+' — working')
    t=threading.Thread(target=pulse,daemon=True);t.start()
    try:yield
    finally:stop.set();t.join()
