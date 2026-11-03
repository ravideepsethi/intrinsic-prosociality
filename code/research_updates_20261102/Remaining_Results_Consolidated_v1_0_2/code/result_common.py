"""Local result jobs: explicit source binding and atomic aggregate checkpoints."""
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo
import csv, hashlib, json, os, threading, time, shutil, uuid

ROOT = Path(__file__).resolve().parents[1]
DAY = 86400000

def require(ok, msg):
    if not ok: raise RuntimeError(msg)

def load(p): return json.loads(Path(p).read_text())
def sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for x in iter(lambda: f.read(8*1024*1024), b''): h.update(x)
    return h.hexdigest()
def key(x): return hashlib.sha256(json.dumps(x, sort_keys=True, default=str, allow_nan=False).encode()).hexdigest()
def signature(p):
    s=Path(p).stat()
    return [s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
def save(p, obj):
    p=Path(p); p.parent.mkdir(parents=True,exist_ok=True)
    q=p.with_name(p.name+'.partial')
    with q.open('w') as f:
        json.dump(obj,f,indent=2,sort_keys=True,allow_nan=False); f.write('\n'); f.flush(); os.fsync(f.fileno())
    os.replace(q,p)
def csv_save(p, rows):
    require(bool(rows),'Refusing an empty result table')
    fields=list(dict.fromkeys(k for r in rows for k in r))
    p=Path(p); p.parent.mkdir(parents=True,exist_ok=True)
    q=p.with_name(p.name+'.partial')
    with q.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    os.replace(q,p)
def log(s):print(datetime.now(ZoneInfo('America/Toronto')).strftime('[%Y-%m-%d %H:%M:%S %Z] ')+str(s),flush=True)
@contextmanager
def heartbeat(label):
    done=threading.Event();start=time.monotonic()
    def beat():
        while not done.wait(25):log(f'{label}; elapsed {(time.monotonic()-start)/60:.1f} min')
    t=threading.Thread(target=beat,daemon=True);t.start()
    try:yield
    finally:done.set();t.join()
def record(p, root):
    return dict(path=str(Path(p).relative_to(root)),bytes=Path(p).stat().st_size,sha256=sha(p))
def verify_record(r,root):
    p=(Path(root)/r['path']).resolve()
    require(p.is_relative_to(Path(root).resolve()),'Receipt path escapes its parent')
    before=signature(p)
    require(p.stat().st_size==r['bytes'] and sha(p)==r['sha256'],'Source/checkpoint checksum differs: '+str(p))
    require(before==signature(p),'Input changed during verification')
    return dict(path=str(p),bytes=r['bytes'],sha256=r['sha256'],signature=before)
def bind_success_file(parent,relative,expected_run):
    done=load(Path(parent)/'_SUCCESS.json')
    require(done.get('run_id')==expected_run,'Unexpected completed source run')
    candidates=[r for r in done['files'] if r['path']==relative or Path(r['path']).resolve()==(Path(parent)/relative).resolve()]
    require(len(candidates)==1,'Completed source does not bind '+relative)
    return verify_record(candidates[0],parent)
def bind_iv_file(path,project):
    path=Path(path).resolve();require(path.is_relative_to(Path(project).resolve()),'IV source outside project')
    receipt=load(path.parent/'_DONE.json')
    require(receipt.get('config_sha256')==load(ROOT/'authority/PARENTS.json')['iv_config_sha256'],'IV cache configuration differs')
    rr=[r for r in receipt['files'] if r['path']==path.name]
    require(len(rr)==1,'IV receipt does not name '+path.name)
    return verify_record(rr[0],path.parent)
def guard(records):
    for r in records:require(signature(r['path'])==r['signature'],'Source changed during job: '+r['path'])
def checkpoint(parent,name,fingerprint,build):
    parent=Path(parent);parent.mkdir(parents=True,exist_ok=True);target=parent/name
    if target.exists():
        require((target/'DONE.json').is_file(),'Unsealed checkpoint: '+str(target))
        d=load(target/'DONE.json');require(d['key']==fingerprint,'Checkpoint inputs changed: '+name)
        for r in d['files']:verify_record(r,target)
        log(name+': verified checkpoint');return target,d['summary']
    temp=parent/(name+'.partial_'+uuid.uuid4().hex);temp.mkdir()
    try:
        summary=build(temp)
        records=[record(p,temp) for p in sorted(temp.rglob('*')) if p.is_file()]
        save(temp/'DONE.json',dict(key=fingerprint,summary=summary,files=records))
        os.replace(temp,target);return target,summary
    except BaseException:
        shutil.rmtree(temp,ignore_errors=True);raise
def block_network():
    import socket
    def blocked(*a,**k):raise RuntimeError('This results bundle uses local cached data only')
    socket.create_connection=blocked;socket.socket.connect=blocked;socket.socket.connect_ex=blocked
