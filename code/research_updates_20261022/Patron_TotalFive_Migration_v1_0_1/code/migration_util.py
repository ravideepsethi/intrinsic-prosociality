"""Isolated process stages, immutable receipts, and aggregate-only exports."""
import argparse, contextlib, hashlib, json, os, shutil, threading, time, zipfile
from pathlib import Path
PACKAGE=Path(__file__).resolve().parents[1]
DAY=86400000

def require(ok,message):
    if not ok: raise RuntimeError(message)
def load(p): return json.loads(Path(p).read_text())
def save(p,value):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_name(p.name+'.tmp');t.write_text(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n');os.replace(t,p)
def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()
def key(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def log(s):print(time.strftime('%Y-%m-%dT%H:%M:%SZ ',time.gmtime())+str(s),flush=True)
def parser():
    p=argparse.ArgumentParser()
    p.add_argument('--project',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--workers',type=int,default=10);p.add_argument('--memory-gb',type=float,default=11.)
    p.add_argument('--run',type=Path);p.add_argument('--conf');p.add_argument('--mode')
    return p
def package_check():
    manifest=PACKAGE/'PACKAGE_MANIFEST.sha256'
    for line in manifest.read_text().splitlines():
        digest,name=line.split('  ',1);p=(PACKAGE/name).resolve()
        require(p.is_relative_to(PACKAGE),'Unsafe package member');require(sha(p)==digest,'Package changed: '+name)
    return sha(manifest)
@contextlib.contextmanager
def pulse(message):
    stop=threading.Event();started=time.monotonic()
    def loop():
        while not stop.wait(30):log((message() if callable(message) else message)+f'; stage elapsed {(time.monotonic()-started)/60:.1f} min')
    t=threading.Thread(target=loop,daemon=True);t.start()
    try:yield
    finally:stop.set();t.join()
def export(run,desktop,conf,percent,status):
    report=run/'report';report.mkdir(exist_ok=True)
    save(report/'status.json',dict(status=status,progress_percent=percent,configuration_sha256=conf,
        Patron_population='total-five receipt cohort',comparison_population='NOT_REBUILT_METADATA_AUDIT_ONLY',
        placebo_status='PENDING_CORRECTED_COMPARISON_POPULATION',network_requests=0))
    paths=[p for p in sorted(report.rglob('*')) if p.is_file() and p.name!='REPORT_MANIFEST.json']
    require(all('PRIVATE' not in str(p.relative_to(report)) and p.suffix not in ('.parquet','.npz','.npy') for p in paths),'Private file in aggregate export')
    save(report/'REPORT_MANIFEST.json',[dict(path=str(p.relative_to(report)),sha256=sha(p),bytes=p.stat().st_size) for p in paths])
    stem='PATRON_TOTALFIVE_'+conf[:12]+'_'+str(percent).zfill(3)+('_BLOCKED' if status=='STOPPED' else '')
    dest=desktop/(stem+'.zip');tmp=dest.with_suffix('.partial.zip')
    with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(report.rglob('*')):
            if p.is_file():z.write(p,p.relative_to(report))
    os.replace(tmp,dest);dest.with_name(dest.name+'.sha256').write_text(sha(dest)+'  '+dest.name+'\n')
    log('Aggregate report: '+str(dest))
