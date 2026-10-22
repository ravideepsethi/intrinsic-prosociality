from __future__ import annotations
import csv, hashlib, json, os, threading, time, zipfile
from pathlib import Path
import duckdb

VERSION = '1.0.0'
ROOT = Path(__file__).resolve().parent

def log(s): print(time.strftime('[%Y-%m-%d %H:%M:%S] ', time.gmtime()) + s, flush=True)
def require(ok, message):
    if not ok: raise RuntimeError(message)
def qs(s): return "'" + str(s).replace("'", "''") + "'"
def qi(s): return '"' + str(s).replace('"', '""') + '"'
def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(8<<20),b''): h.update(b)
    return h.hexdigest()
def dump(p, obj):
    p=Path(p); p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_name(p.name+'.tmp'); t.write_text(json.dumps(obj,indent=2,sort_keys=True,allow_nan=False)+'\n'); os.replace(t,p)
def read(p): return json.loads(Path(p).read_text())
def records(db,sql):
    c=db.execute(sql); names=[x[0] for x in c.description]
    return [dict(zip(names,r)) for r in c.fetchall()]
def export(db, p, sql):
    p=Path(p); p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_name(p.name+'.partial')
    db.execute(f'COPY ({sql}) TO {qs(tmp)} (HEADER, DELIMITER ",")'); os.replace(tmp,p)
def parquet(db,p,sql):
    p=Path(p); p.parent.mkdir(parents=True,exist_ok=True); t=p.with_suffix('.partial.parquet')
    db.execute(f'COPY ({sql}) TO {qs(t)} (FORMAT PARQUET, COMPRESSION ZSTD)'); os.replace(t,p)
def certify(p, identity, **extra): dump(str(p)+'.json',dict(identity=identity,sha256=sha(p),**extra))
def valid(p, identity):
    p=Path(p); r=Path(str(p)+'.json')
    if not p.exists() or not r.exists(): return False
    d=read(r); require(d['identity']==identity,'Checkpoint belongs to a different run: '+str(p))
    require(sha(p)==d['sha256'],'Checkpoint checksum mismatch: '+str(p)); return True
def signature(obj): return hashlib.sha256(json.dumps(obj,sort_keys=True,default=str).encode()).hexdigest()
def connection(memory='6GB',threads=8,temp=None):
    db=duckdb.connect(); db.execute(f'SET memory_limit={qs(memory)}'); db.execute(f'SET threads={int(threads)}')
    db.execute('SET preserve_insertion_order=false'); db.execute("SET TimeZone='UTC'")
    if temp:
        Path(temp).mkdir(parents=True,exist_ok=True); db.execute(f'SET temp_directory={qs(temp)}')
    return db
class Heartbeat:
    def __init__(self,label): self.label=label; self.stop=threading.Event()
    def __enter__(self):
        def loop():
            while not self.stop.wait(30): log(self.label+' — working')
        self.t=threading.Thread(target=loop,daemon=True); self.t.start(); return self
    def __exit__(self,*_): self.stop.set(); self.t.join()
def report_zip(run, kind):
    report=run/'report'; out=run/f'COUNTRY_PROFILE_{kind}_REPORT_v100.zip'
    manifest={str(p.relative_to(report)):sha(p) for p in sorted(report.rglob('*')) if p.is_file() and p.name!='REPORT_HASHES.json'}
    dump(report/'REPORT_HASHES.json',manifest)
    with zipfile.ZipFile(out.with_suffix('.partial.zip'),'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(report.rglob('*')):
            if p.is_file(): z.write(p, 'COUNTRY_PROFILE_REPORT/'+str(p.relative_to(report)))
    os.replace(out.with_suffix('.partial.zip'),out)
    out.with_name(out.name+'.sha256').write_text(sha(out)+'  '+out.name+'\n')
    log('REPORT_READY '+str(out)); return out
