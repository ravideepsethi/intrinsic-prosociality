"""Package integrity and atomic public report writer; standard library only."""
from pathlib import Path
import hashlib, json, os, zipfile
PACKAGE=Path(__file__).resolve().parents[1]
VERSION='1.0.0'

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(8*1024**2),b''):h.update(block)
    return h.hexdigest()

def verify_release():
    for line in (PACKAGE/'PACKAGE_MANIFEST.sha256').read_text().splitlines():
        digest,name=line.split('  ',1);p=(PACKAGE/name).resolve()
        if not p.is_relative_to(PACKAGE) or not p.is_file() or sha(p)!=digest:
            raise RuntimeError('Package checksum differs: '+name)

def zip_report(folder,desktop,stem):
    folder,desktop=Path(folder),Path(desktop);desktop.mkdir(parents=True,exist_ok=True)
    files=sorted(p for p in folder.iterdir() if p.is_file() and p.name!='REPORT_MANIFEST.json')
    if any('PRIVATE' in p.name for p in files):raise RuntimeError('Private file in aggregate report')
    m=folder/'REPORT_MANIFEST.json'
    m.write_text(json.dumps([dict(path=p.name,bytes=p.stat().st_size,sha256=sha(p)) for p in files],sort_keys=True,indent=2)+'\n')
    target=desktop/(stem+'.zip');tmp=target.with_suffix('.zip.partial')
    with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as z:
        for p in files+[m]:z.write(p,p.name)
    os.replace(tmp,target)
    Path(str(target)+'.sha256').write_text(sha(target)+'  '+target.name+'\n')
    print('RETURN THIS AGGREGATE REPORT: '+str(target),flush=True)
    return target
