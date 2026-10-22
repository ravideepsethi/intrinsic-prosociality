"""Local, resumable companion analyses. Existing inputs are read only."""
from __future__ import annotations
import contextlib, datetime, hashlib, importlib.util, json, os, platform
import re, shutil, subprocess, sys, threading, time, uuid
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import duckdb
pa.set_cpu_count(1)
pa.set_io_thread_count(1)

ROOT=Path(__file__).resolve().parent
VERSION='1.0.0'
HOUR=3_600_000
MONTHS=[str(m) for m in pd.period_range('2023-11','2025-10',freq='M')]
SPEEDS=['ultrabullet','bullet','blitz','rapid','classical']

def log(s):print(datetime.datetime.now().strftime('[%Y-%m-%d %H:%M:%S] ')+s,flush=True)
def require(ok,s):
    if not ok:raise RuntimeError(s)
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
def digest(x):return hashlib.sha256(json.dumps(clean(x),sort_keys=True,separators=(',',':')).encode()).hexdigest()
def load(p):return json.loads(Path(p).read_text())
def js(p,x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_name(p.name+'.partial_'+uuid.uuid4().hex)
    t.write_text(json.dumps(clean(x),indent=2,sort_keys=True,allow_nan=False)+'\n');os.replace(t,p)
def textfile(p,s):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(s)
def q(s):return "'"+str(s).replace("'","''")+"'"
def scan(paths):
    if isinstance(paths,(str,Path)):paths=[paths]
    require(bool(paths),'Empty Parquet input list')
    return 'read_parquet(['+','.join(map(q,paths))+'],hive_partitioning=false)'
def db(folder,memory=2,threads=1):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    c=duckdb.connect(config={'temp_directory':str(folder),'threads':str(threads),'memory_limit':str(memory)+'GB'})
    c.execute('SET preserve_insertion_order=false');return c
def copy(c,sql,p):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_name(p.name+'.partial_'+uuid.uuid4().hex)
    n=c.execute('COPY ('+sql+') TO '+q(t)+' (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 131072)').fetchone()[0]
    os.replace(t,p);return int(n)
def snapshot(p):
    s=Path(p).stat();return dict(bytes=s.st_size,mtime_ns=s.st_mtime_ns,ctime_ns=s.st_ctime_ns)
def checked(p,expected=None):
    p=Path(p);before=snapshot(p);h=sha(p)
    require(expected is None or h==expected,'Source checksum mismatch: '+str(p))
    require(snapshot(p)==before,'Source changed while hashing: '+str(p))
    return dict(path=str(p),sha256=h,stat=before)
def unchanged(items):
    for r in items:require(snapshot(r['path'])==r['stat'],'Source changed during analysis: '+r['path'])
def commit(root,key,**extra):
    root=Path(root)
    files=[dict(path=str(p.relative_to(root)),bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(root.rglob('*'))
           if p.is_file() and p.name!='_DONE.json' and 'spill' not in p.parts and '.partial_' not in p.name]
    js(root/'_DONE.json',dict(key=key,files=files,**extra))
def cached(root,key):
    root=Path(root);p=root/'_DONE.json'
    if not p.is_file():return False
    r=load(p);require(r['key']==key,'Checkpoint key changed: '+str(root))
    for f in r['files']:
        p=root/f['path'];require(p.is_file() and p.stat().st_size==f['bytes'] and sha(p)==f['sha256'],'Checkpoint damaged: '+str(p))
    return True
def tab(p,rows):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);d=pd.DataFrame(rows)
    d.to_csv(p.with_suffix('.csv'),index=False);d.to_parquet(p.with_suffix('.parquet'),index=False,compression='zstd')
def module(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);sys.modules[name]=m;s.loader.exec_module(m);return m
def relocated(path,project):
    path=str(path);marker='/lichess_kindness/'
    require(marker in path,'Unrecognized source root: '+path)
    return Path(project)/path.split(marker,1)[1]
@contextlib.contextmanager
def heartbeat(label):
    stop=threading.Event()
    def beat():
        while not stop.wait(40):log(label+' — working')
    t=threading.Thread(target=beat,daemon=True);t.start()
    try:yield
    finally:stop.set();t.join()

def process_reservations(lines,own_pid,own_package):
    """Count Python job reservations once; caffeinate and engine children add none."""
    found=[]
    for line in lines.splitlines():
        m=re.match(r'\s*(\d+)\s+(.*)',line)
        if not m:continue
        pid,cmd=int(m[1]),m[2]
        if pid==own_pid or own_package in cmd:continue
        exe=cmd.split(' ',1)[0]
        if not re.search(r'(?:^|/)python(?:[0-9.]*)?$',exe):continue
        if not re.search(r'lichess|kac_|KAC_|code/run\.py',cmd,re.I):continue
        z=re.search(r'--(?:workers|threads|worker-budget)(?:=|\s+)(\d+)',cmd)
        found.append(dict(pid=pid,workers=int(z[1]) if z else 1,command=cmd))
    return found
def reservations():
    try:lines=subprocess.check_output(['ps','-axo','pid=,command='],text=True)
    except Exception:return []
    return process_reservations(lines,os.getpid(),str(ROOT))
def slots(budget,want,minimum=1):
    last=0
    while True:
        jobs=reservations();used=sum(j['workers'] for j in jobs)
        free=min(want,max(0,budget-used))
        if free>=minimum:return free,jobs
        if time.monotonic()-last>40:
            log(f'Waiting for worker capacity: other jobs reserve {used}; total budget {budget}. Existing jobs continue.');last=time.monotonic()
        time.sleep(10)
def memory_gb():
    try:
        if platform.system()=='Darwin':return int(subprocess.check_output(['sysctl','-n','hw.memsize']))/2**30
        return os.sysconf('SC_PAGE_SIZE')*os.sysconf('SC_PHYS_PAGES')/2**30
    except Exception:return 16.
