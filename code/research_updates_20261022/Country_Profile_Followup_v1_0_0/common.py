from __future__ import annotations
import csv, hashlib, json, os, threading, time, zipfile
from pathlib import Path
import duckdb

ROOT = Path(__file__).resolve().parent
VERSION = '1.0.0'

def log(message):
    print(time.strftime('[%Y-%m-%d %H:%M:%SZ] ', time.gmtime()) + message, flush=True)

def require(ok, message):
    if not ok:
        raise RuntimeError(message)

def qs(value):
    return "'" + str(value).replace("'", "''") + "'"

def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(8 << 20), b''):
            h.update(b)
    return h.hexdigest()

def read(path):
    return json.loads(Path(path).read_text())

def signature(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()

def dump(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.partial')
    temp.write_text(json.dumps(obj, indent=2, sort_keys=True, allow_nan=False) + '\n')
    os.replace(temp, path)

def certify(path, identity):
    dump(str(path) + '.json', dict(identity=identity, sha256=sha(path)))

def valid(path, identity):
    path = Path(path)
    if not path.exists() or not Path(str(path) + '.json').exists():
        return False
    receipt = read(str(path) + '.json')
    require(receipt['identity'] == identity, 'Different checkpoint identity: ' + str(path))
    require(sha(path) == receipt['sha256'], 'Checkpoint checksum mismatch: ' + str(path))
    return True

def write_csv(path, rows, fields=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

def parquet(db, path, sql):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.partial.parquet')
    db.execute(f'COPY ({sql}) TO {qs(temp)} (FORMAT PARQUET, COMPRESSION ZSTD)')
    os.replace(temp, path)

def records(db, sql):
    cur = db.execute(sql)
    names = [x[0] for x in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]

def connection(memory, threads, spill):
    spill.mkdir(parents=True, exist_ok=True)
    db = duckdb.connect()
    db.execute(f'SET memory_limit={qs(memory)}')
    db.execute(f'SET threads={threads}')
    db.execute(f'SET temp_directory={qs(spill)}')
    db.execute('SET preserve_insertion_order=false')
    db.execute("SET TimeZone='UTC'")
    return db

class Heartbeat:
    def __init__(self, label):
        self.label = label
        self.stop = threading.Event()
    def __enter__(self):
        def loop():
            while not self.stop.wait(30):
                log(self.label + ' — working')
        self.thread = threading.Thread(target=loop, daemon=True)
        self.thread.start()
        return self
    def __exit__(self, *_):
        self.stop.set()
        self.thread.join()

def report_zip(run):
    report = run / 'report'
    files = [p for p in sorted(report.rglob('*')) if p.is_file() and p.name != 'REPORT_HASHES.json']
    dump(report / 'REPORT_HASHES.json', {str(p.relative_to(report)): sha(p) for p in files})
    out = run / 'COUNTRY_PROFILE_FOLLOWUP_REPORT_v100.zip'
    temp = out.with_suffix('.partial.zip')
    with zipfile.ZipFile(temp, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in sorted(report.rglob('*')):
            if p.is_file():
                z.write(p, 'COUNTRY_PROFILE_FOLLOWUP_REPORT/' + str(p.relative_to(report)))
    os.replace(temp, out)
    out.with_name(out.name + '.sha256').write_text(sha(out) + '  ' + out.name + '\n')
    log('REPORT_READY ' + str(out))

