from __future__ import annotations
import csv
from pathlib import Path
from source import pool_wave1_common as common

def log(s):print(f'[{common.utc_now()}] {s}',flush=True)
def qs(x):return "'"+str(x).replace("'","''")+"'"
def require(ok,s):
    if not ok:raise RuntimeError(s)
def signature(p):
    s=Path(p).stat();return [s.st_size,s.st_mtime_ns,s.st_ino]
def records(db,sql):
    c=db.execute(sql);names=[x[0] for x in c.description]
    return [dict(zip(names,r)) for r in c.fetchall()]
def write_csv(path,rows):
    require(bool(rows),'Refusing empty result CSV')
    fields=list(dict.fromkeys(k for r in rows for k in r))
    with Path(path).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
def manifest(root,name='OUTPUT_MANIFEST.sha256'):
    lines=[f'{common.sha256_file(p)}  {p.relative_to(root).as_posix()}\n'
      for p in sorted(root.rglob('*')) if p.is_file() and p.name!=name and '__pycache__' not in p.parts]
    common.atomic_text(root/name,''.join(lines))
def verify_manifest(root,name='OUTPUT_MANIFEST.sha256'):
    p=root/name;require(p.is_file(),f'Missing {name}')
    for line in p.read_text().splitlines():
        digest,rel=line.split('  ',1);q=root/rel
        require(q.resolve().is_relative_to(root.resolve()),'Unsafe manifest path')
        require(q.is_file() and common.sha256_file(q)==digest,f'Checksum mismatch: {rel}')
    return common.sha256_file(p)
def checkpoint_ok(path,identity):
    receipt=path.with_suffix(path.suffix+'.json')
    if not receipt.is_file():return False
    r=common.load_json(receipt)
    require(r['run_identity']==identity,f'Checkpoint identity mismatch: {path.name}')
    require(path.is_file() and common.sha256_file(path)==r['sha256'],f'Checkpoint corrupted: {path.name}')
    return True
def certify_checkpoint(path,identity,**extra):
    common.atomic_json(path.with_suffix(path.suffix+'.json'),dict(run_identity=identity,
      sha256=common.sha256_file(path),**extra))
