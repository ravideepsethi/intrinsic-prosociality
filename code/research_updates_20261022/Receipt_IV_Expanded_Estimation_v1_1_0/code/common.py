"""Immutable-input I/O and restartable stages. No network access."""
from __future__ import annotations
import contextlib, datetime as dt, hashlib, json, os, threading, uuid
from pathlib import Path
import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

PACKAGE = Path(__file__).resolve().parents[1]
ORIGINAL_PROJECT = Path('/Volumes/XT_Pro/lichess_kindness')
VERSION = '1.1.0'
DAY = 86400000
MONTHS = tuple(f'{k//12:04d}-{k%12+1:02d}' for k in range(2023*12+8, 2026*12+4))
OLD_MONTHS = MONTHS[2:26]
NEW_MONTHS = MONTHS[:2] + MONTHS[26:]
SPEEDS = ('ultrabullet', 'bullet', 'blitz', 'rapid', 'classical')
STARTS = np.array([int(dt.datetime.fromisoformat(m+'-01').replace(tzinfo=dt.timezone.utc).timestamp()*1000) for m in MONTHS], dtype=np.int64)

def log(s):
    print(dt.datetime.now(dt.timezone.utc).strftime('[%H:%M:%S UTC] ') + str(s), flush=True)

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(8*1024**2), b''): h.update(b)
    return h.hexdigest()

def load(path): return json.loads(Path(path).read_text())
def clean(x):
    if isinstance(x, dict): return {str(k): clean(v) for k,v in x.items()}
    if isinstance(x, (list,tuple,np.ndarray)): return [clean(v) for v in x]
    if isinstance(x, np.generic): return clean(x.item())
    if isinstance(x, float) and not np.isfinite(x): return None
    return x

def digest(x): return hashlib.sha256(json.dumps(clean(x), sort_keys=True, separators=(',',':')).encode()).hexdigest()
def v103_digest(x): return hashlib.sha256(json.dumps(x, sort_keys=True, default=str).encode()).hexdigest()
def write_json(path, obj):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name+'.partial_'+uuid.uuid4().hex)
    tmp.write_text(json.dumps(clean(obj), sort_keys=True, indent=2, allow_nan=False)+'\n')
    os.replace(tmp,path)

def stamp(path):
    p=Path(path); s=p.stat()
    return dict(path=str(p.resolve()), size=s.st_size, mtime_ns=s.st_mtime_ns, ctime_ns=s.st_ctime_ns)

def relocated(path, project):
    p=Path(path)
    if p.is_absolute():
        try: p=p.relative_to(ORIGINAL_PROJECT)
        except ValueError: raise RuntimeError('Input authority lies outside the project')
    if '..' in p.parts: raise RuntimeError('Unsafe authority path')
    return Path(project)/p

def lit(x): return "'"+str(x).replace("'","''")+"'"
def ident(x): return '"'+str(x).replace('"','""')+'"'
def scan(paths):
    if isinstance(paths,(str,Path)): paths=[paths]
    if not paths: raise ValueError('Empty Parquet source list')
    return 'read_parquet(['+','.join(lit(p) for p in paths)+'],hive_partitioning=false,union_by_name=true)'
def columns(path): return set(pq.ParquetFile(path).schema_arrow.names)
def arr(t,name,dtype=None):
    a=t[name].combine_chunks().to_numpy(zero_copy_only=False)
    return a.astype(dtype) if dtype is not None else a

def connection(temp, threads, memory_mb):
    Path(temp).mkdir(parents=True,exist_ok=True); c=duckdb.connect()
    c.execute(f'SET threads={int(threads)}'); c.execute(f"SET memory_limit='{int(memory_mb)}MB'")
    c.execute('SET temp_directory='+lit(temp)); c.execute('SET preserve_insertion_order=false')
    return c

def copy(c,query,path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    return int(c.execute('COPY ('+query+') TO '+lit(path)+' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 131072)').fetchone()[0])

def receipt(path):
    p=Path(path); r=dict(path=str(p),sha256=sha(p),bytes=p.stat().st_size)
    if p.suffix=='.parquet':r['rows']=pq.ParquetFile(p).metadata.num_rows
    return r

def checked(path, expected, auth_root, prior_auth=None):
    """Hash once; a saved check is reusable only at its exact file fingerprint."""
    path=Path(path); before=stamp(path)
    wanted=expected.get('sha256') or expected.get('output_sha256') or expected.get('expected_sha256')
    if not wanted: raise RuntimeError('No authoritative digest: '+str(path))
    size=next((expected[k] for k in ('bytes','size','size_bytes','expected_bytes') if expected.get(k) is not None),None)
    if size is not None and int(size)!=before['size']:raise RuntimeError('Input size changed: '+str(path))
    # v103 used default-spaced JSON for its authentication filename.
    prior=Path(prior_auth)/'authentication'/(v103_digest(str(path.resolve()))+'.json') if prior_auth else None
    target=Path(auth_root)/(digest(str(path.resolve()))+'.json')
    reused=False
    for p in [target,prior]:
        if p and p.is_file():
            r=load(p)
            if r.get('fingerprint')==before and r.get('sha256')==wanted:reused=True;break
    if not reused and sha(path)!=wanted:raise RuntimeError('Input checksum changed: '+str(path))
    if stamp(path)!=before:raise RuntimeError('Input changed during authentication: '+str(path))
    out=dict(fingerprint=before,sha256=wanted)
    write_json(target,out)
    return dict(path=str(path),sha256=wanted,bytes=before['size'],fingerprint=before)

def unchanged(records):
    for r in records:
        if stamp(r['path'])!=r['fingerprint']:raise RuntimeError('Input changed: '+r['path'])

def observed_binding(path,auth_root):
    """Bind previously inventoried bytes; not an independently pinned producer SHA."""
    path=Path(path);before=stamp(path)
    target=Path(auth_root)/'observed_chronology'/(digest(str(path.resolve()))+'.json')
    if target.is_file():
        old=load(target)
        if old['fingerprint']!=before:raise RuntimeError('Previously bound chronology changed: '+str(path))
        return old
    out=dict(path=str(path),fingerprint=before,sha256=sha(path),bytes=before['size'],
        authority='fresh_byte_binding_of_metadata_inventoried_chronology_not_prior_producer_SHA')
    if stamp(path)!=before:raise RuntimeError('Chronology changed while hashing')
    write_json(target,out)
    return out

@contextlib.contextmanager
def heartbeat(label,seconds=30):
    stop=threading.Event()
    def pulse():
        while not stop.wait(seconds):log(label+' — working')
    t=threading.Thread(target=pulse,daemon=True);t.start()
    try:yield
    finally:stop.set();t.join()

def stage(root,key,inputs,producer,auth_root):
    """Never overwrite a completed stage. Interrupted work remains in a named partial."""
    root=Path(root);done=root/'_DONE.json';unchanged(inputs)
    if done.is_file():
        r=load(done)
        if r.get('key')!=key:raise RuntimeError('Completed stage has a different contract: '+str(root))
        for a in r['files']:checked(root/a['path'],a,auth_root)
        unchanged(inputs);log('Reused '+root.name)
        return root,r
    if root.exists():raise RuntimeError('Unrecognized final stage without receipt: '+str(root))
    root.parent.mkdir(parents=True,exist_ok=True)
    tmp=root.with_name(root.name+'.partial_'+uuid.uuid4().hex);tmp.mkdir()
    info=producer(tmp)
    unchanged(inputs)
    files=[]
    for p in sorted(tmp.rglob('*')):
        if p.is_file() and 'spill' not in p.relative_to(tmp).parts:
            r=receipt(p);r['path']=str(p.relative_to(tmp));files.append(r)
    out=dict(key=key,files=files,inputs=inputs,result=info)
    write_json(tmp/'_DONE.json',out);os.replace(tmp,root)
    return root,out

def table(rows,path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    t=pa.Table.from_pylist(clean(rows)) if rows else pa.table({'status':pa.array([],type=pa.string())})
    pq.write_table(t,path.with_suffix('.parquet'),compression='zstd')
    import csv
    with path.with_suffix('.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=t.column_names);w.writeheader();w.writerows(t.to_pylist())
