from __future__ import annotations
import csv, hashlib, json, os, time
from pathlib import Path
from source.pool_wave1_common import atomic_json, atomic_text, sha256_file

VERSION = '1.0.0'
MONTHS = [f'{y}-{m:02d}' for y,m in [(2023,11),(2023,12)] + [(2024,m) for m in range(1,13)] + [(2025,m) for m in range(1,11)]]

def log(message):
    print(time.strftime('[%Y-%m-%d %H:%M:%SZ] ', time.gmtime())+str(message), flush=True)

def require(condition, message):
    if not condition: raise RuntimeError(message)

def qs(value): return "'"+str(value).replace("'", "''")+"'"

def records(db, query):
    cur=db.execute(query); names=[x[0] for x in cur.description]
    return [dict(zip(names,row)) for row in cur.fetchall()]

def csv_write(path, rows):
    if not rows: atomic_text(path, ''); return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='') as f:
        writer=csv.DictWriter(f, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)

def binding(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def ready(path, identity):
    receipt=Path(str(path)+'.receipt.json')
    if not path.is_file() or not receipt.is_file(): return False
    r=json.loads(receipt.read_text())
    require(r['identity']==identity, 'Checkpoint configuration changed: '+str(path))
    require(r['sha256']==sha256_file(path), 'Checkpoint checksum mismatch: '+str(path))
    return True

def certify(path, identity):
    atomic_json(Path(str(path)+'.receipt.json'), dict(identity=identity,sha256=sha256_file(path),bytes=path.stat().st_size))

def copy_query(db, query, path, identity):
    path.parent.mkdir(parents=True,exist_ok=True)
    partial=Path(str(path)+'.partial'); partial.unlink(missing_ok=True)
    db.execute(f'COPY ({query}) TO {qs(partial)} (FORMAT PARQUET, COMPRESSION ZSTD)')
    os.replace(partial,path); certify(path,identity)
