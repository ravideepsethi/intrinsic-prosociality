from __future__ import annotations
import contextlib, datetime as dt, hashlib, json, os, threading, uuid
from pathlib import Path
import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

PACKAGE = Path(__file__).resolve().parents[1]
VERSION = '1.0.0'
PROJECT = Path('/Volumes/XT_Pro/lichess_kindness')
MONTHS = ('2025-11', '2025-12', '2026-02')
EXPECTED = {'2025-11':1964949, '2025-12':2092233, '2026-02':1834768}
COHORT_CODE = '49d42e6b6a901662c608b14edddd06ab94e0cc90cb975b41b62b36227ace0c09'
BATCH_SIZE = 300
ENDPOINT = 'https://lichess.org/api/games/export/_ids'
PARAMS = dict(moves='false', pgnInJson='false', tags='true', clocks='true',
              evals='false', accuracy='false', opening='false', division='false', literate='false')

def log(s):
    print(dt.datetime.now(dt.timezone.utc).strftime('[%H:%M:%S UTC] ') + str(s), flush=True)

def load(p): return json.loads(Path(p).read_text())
def digest(x): return hashlib.sha256(json.dumps(x, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(8*1024**2), b''): h.update(b)
    return h.hexdigest()
def stamp(p):
    s=Path(p).stat()
    return dict(size=s.st_size,mtime_ns=s.st_mtime_ns,ctime_ns=s.st_ctime_ns)
def write_json(p,obj):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_name(p.name+'.partial_'+uuid.uuid4().hex)
    with tmp.open('w') as f:
        json.dump(obj,f,sort_keys=True,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
    os.replace(tmp,p)
def write_parquet(p,rows,schema):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.name+'.partial_'+uuid.uuid4().hex)
    pq.write_table(pa.Table.from_pylist(rows,schema=schema),tmp,compression='zstd')
    with tmp.open('rb') as f: os.fsync(f.fileno())
    os.replace(tmp,p)
def receipt(p,relative=None):
    p=Path(p)
    return dict(path=str(p.relative_to(relative)) if relative else str(p),bytes=p.stat().st_size,sha256=sha(p))
def lit(x): return "'"+str(x).replace("'","''")+"'"
def scan(paths):
    if isinstance(paths,(str,Path)): paths=[paths]
    return 'read_parquet(['+','.join(lit(p) for p in paths)+'],hive_partitioning=false)'
def relocate(p,project):
    p=Path(p)
    try: return Path(project)/p.relative_to(PROJECT)
    except ValueError:
        p.resolve().relative_to(Path(project).resolve())
        return p
def checked(p,r,auth):
    p=Path(p);before=stamp(p);cache=Path(auth)/(digest(str(p.resolve()))+'.json')
    saved=load(cache) if cache.is_file() else {}
    size=r.get('bytes',r.get('size'))
    if size is not None and before['size']!=size: raise RuntimeError('Input size differs from receipt')
    if saved.get('stamp')!=before or saved.get('sha256')!=r['sha256']:
        if sha(p)!=r['sha256']: raise RuntimeError('Input hash differs from receipt')
        if stamp(p)!=before: raise RuntimeError('Input changed while reading')
        write_json(cache,dict(stamp=before,sha256=r['sha256']))
    return dict(path=str(p),sha256=r['sha256'],bytes=before['size'],stamp=before)
def verify_package():
    for line in (PACKAGE/'PACKAGE_MANIFEST.sha256').read_text().splitlines():
        h,n=line.split('  ',1);p=PACKAGE/n
        if not p.resolve().is_relative_to(PACKAGE.resolve()) or sha(p)!=h:
            raise RuntimeError('Package checksum failed')
def code_signature():
    return digest({p.name:sha(p) for p in sorted((PACKAGE/'code').glob('*.py'))})
def connection(work,threads=4):
    c=duckdb.connect();c.execute(f'SET threads={int(threads)}')
    c.execute("SET memory_limit='4GB'");c.execute('SET temp_directory='+lit(Path(work)/'spill'))
    c.execute('SET preserve_insertion_order=false');return c
def query_rows(c,q):
    cur=c.execute(q);names=[r[0] for r in cur.description]
    return [dict(zip(names,r)) for r in cur.fetchall()]
@contextlib.contextmanager
def heartbeat(label):
    stop=threading.Event()
    def pulse():
        while not stop.wait(30):log(label+' — working')
    t=threading.Thread(target=pulse,daemon=True);t.start()
    try: yield
    finally: stop.set();t.join()
