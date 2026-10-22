"""Isolated stages and aggregate-only exports for comparison metadata recovery."""
import argparse, contextlib, hashlib, json, os, threading, time, zipfile
from pathlib import Path
PACKAGE=Path(__file__).resolve().parents[1]
PARENT_CONF='144d4ae19d09f2da2e63255077efe0a9385d623697b57115dbee22c88aa7f1a2'
DAY=86400000
def require(ok,message):
    if not ok:raise RuntimeError(message)
def load(p):return json.loads(Path(p).read_text())
def save(p,v):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);t=p.with_name(p.name+'.tmp')
    t.write_text(json.dumps(v,sort_keys=True,indent=2,allow_nan=False)+'\n');os.replace(t,p)
def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(8*1024**2),b''):h.update(b)
    return h.hexdigest()
def key(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def log(v):print(time.strftime('%Y-%m-%dT%H:%M:%SZ ',time.gmtime())+str(v),flush=True)
def parser():
    p=argparse.ArgumentParser();p.add_argument('--project',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--workers',type=int,default=10);p.add_argument('--memory-gb',type=float,default=11.)
    p.add_argument('--run',type=Path);p.add_argument('--conf');p.add_argument('--mode');return p
def parent(a):return a.project/'derived/replication/patron_totalfive_migration_v100_PRIVATE'/PARENT_CONF[:12]
@contextlib.contextmanager
def pulse(label):
    stop=threading.Event();start=time.monotonic()
    def beat():
        while not stop.wait(30):log((label() if callable(label) else label)+f'; elapsed {(time.monotonic()-start)/60:.1f} min')
    t=threading.Thread(target=beat,daemon=True);t.start()
    try:yield
    finally:stop.set();t.join()
def package_check():
    p=PACKAGE/'PACKAGE_MANIFEST.sha256'
    for line in p.read_text().splitlines():
        digest,name=line.split('  ',1);f=(PACKAGE/name).resolve()
        require(f.is_relative_to(PACKAGE) and sha(f)==digest,'Package checksum mismatch: '+name)
    return sha(p)
def authenticate_report(a):
    root=parent(a);require(key(load(root/'config.json'))==PARENT_CONF,'Completed migration configuration differs')
    expected=load(PACKAGE/'evidence/REPORT_MANIFEST.json')
    require(load(root/'report/REPORT_MANIFEST.json')==expected,'Reviewed migration report manifest differs')
    for r in expected:require(sha(root/'report'/r['path'])==r['sha256'],'Reviewed migration report changed: '+r['path'])
    private=load(root/'PRIVATE/COMPARISON_AUDIT_INPUTS.json')
    require([{k:v for k,v in r.items() if k!='path'} for r in private['files']]==load(PACKAGE/'evidence/comparison_input_hashes.json'),'Audit input bindings differ')
    for ix,r in enumerate(private['files']):
        require(Path(r['path']).stat().st_size==r['bytes'] and sha(r['path'])==r['sha256'],'Audited input changed')
        if (ix+1)%50==0:log(f'Authenticated audit input {ix+1}/{len(private["files"])}')
    return private
def export(a,percent,status):
    report=a.run/'report';report.mkdir(exist_ok=True)
    save(report/'status.json',dict(status=status,progress_percent=percent,configuration_sha256=a.conf,
        scope='Newly count-supported comparison metadata recovery',models_run=False,profile_requests=0,
        final_comparison_population_rebuilt=False,Patron_placebo='PENDING_COMPARISON_REBUILD'))
    paths=[p for p in sorted(report.rglob('*')) if p.is_file() and p.name!='REPORT_MANIFEST.json']
    require(all('PRIVATE' not in str(p.relative_to(report)) and p.suffix in ('.json','.csv','.txt') for p in paths),'Private file in public export')
    save(report/'REPORT_MANIFEST.json',[dict(path=str(p.relative_to(report)),bytes=p.stat().st_size,sha256=sha(p)) for p in paths])
    name=f'COMPARISON_TOTALFIVE_RECOVERY_{a.conf[:12]}_{percent:03}'+('_BLOCKED' if status=='STOPPED' else '')
    dest=a.desktop/(name+'.zip');tmp=dest.with_suffix('.partial.zip')
    with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(report.iterdir()):
            if p.is_file():z.write(p,p.name)
    os.replace(tmp,dest);Path(str(dest)+'.sha256').write_text(sha(dest)+'  '+dest.name+'\n');log('Aggregate report: '+str(dest))
