"""Small local I/O helpers for authenticated, resumable Parquet stages."""
from __future__ import annotations
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import threading
import time
import uuid
import zipfile

import pyarrow as pa
import pyarrow.parquet as pq


def require(ok, message):
    if not ok:
        raise ValueError(message)


def log(message):
    print(dt.datetime.now(dt.timezone.utc).strftime('[%Y-%m-%d %H:%M:%SZ] ')+message, flush=True)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(8*1024**2), b''):
            h.update(block)
    return h.hexdigest()


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def signature(path):
    s = Path(path).stat()
    return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns]


def read_json(path):
    return json.loads(Path(path).read_text())


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n').encode()


def write_bytes(path, data):
    path = Path(path)
    temp = path.with_name(path.name+'.partial_'+uuid.uuid4().hex)
    with temp.open('xb') as f:
        f.write(data); f.flush(); os.fsync(f.fileno())
    os.replace(temp, path)


def write_json(path, value):
    write_bytes(path, json_bytes(value))


def relative_file(root, name):
    rel = Path(name)
    require(not rel.is_absolute() and '..' not in rel.parts, 'Unsafe manifest path')
    p = Path(root)/rel
    require(Path(root).resolve() in p.resolve().parents, 'Manifest path escapes its root')
    return p


def inspected_file(path, expected_sha=None):
    path = Path(path)
    require(path.is_file(), 'Missing required file: '+str(path))
    before = signature(path); digest = sha(path)
    require(signature(path) == before, 'File changed during hashing: '+str(path))
    require(expected_sha is None or digest == expected_sha, 'SHA-256 mismatch: '+str(path))
    return {'path': str(path), 'sha256': digest, 'size_bytes': before[2], 'signature': before}


def unchanged(entries):
    for item in entries:
        require(signature(item['path']) == item['signature'], 'Input changed during run: '+item['path'])


def report_bytes(path, expected_sha):
    require(sha(path) == expected_sha, 'Bundled report ZIP hash differs: '+str(path))
    with zipfile.ZipFile(path) as z:
        files = [n for n in z.namelist() if not n.endswith('/')]
        require(len(files) == len(set(files)) and z.testzip() is None, 'Invalid report ZIP')
        manifests = [n for n in files if PurePosixPath(n).name in ('REPORT_MANIFEST.sha256', 'SHA256SUMS.txt')]
        require(len(manifests) == 1, 'Missing/ambiguous report manifest')
        mf = manifests[0]; parent = PurePosixPath(mf).parent; covered = set()
        for line in z.read(mf).decode().splitlines():
            digest, name = line.split(None, 1)
            rel = PurePosixPath(name.lstrip('*'))
            require(not rel.is_absolute() and '..' not in rel.parts, 'Unsafe report member')
            n = str(parent/rel)
            require(n not in covered, 'Duplicate manifest member')
            require(hashlib.sha256(z.read(n)).hexdigest() == digest, 'Report member checksum mismatch: '+n)
            covered.add(n)
        require(set(files)-covered-{mf} <= {str(parent/'README.txt')}, 'Unlisted report member')
        names = [PurePosixPath(n).name for n in files]
        require(len(names) == len(set(names)), 'Ambiguous report basenames')
        return dict(zip(names, (z.read(n) for n in files)))


def lit(value):
    return "'"+str(value).replace("'", "''")+"'"


def pq_sql(paths):
    require(bool(paths), 'Empty Parquet input list')
    return 'read_parquet(['+','.join(lit(p) for p in paths)+'], hive_partitioning=false)'


def records(con, query):
    c = con.execute(query); names = [x[0] for x in c.description]
    return [dict(zip(names, r)) for r in c.fetchall()]


def describe(con, query):
    return [{'name': r[0], 'type': r[1]} for r in con.execute('DESCRIBE '+query).fetchall()]


def copy_parquet(con, query, path, partition=None):
    options = ['FORMAT PARQUET', 'COMPRESSION ZSTD', 'COMPRESSION_LEVEL 1', 'ROW_GROUP_SIZE 65536']
    if partition:
        options.extend([f'PARTITION_BY ({partition})', "FILENAME_PATTERN 'part_{i}'"])
    n = con.execute(f'COPY ({query}) TO {lit(path)} ('+', '.join(options)+')').fetchone()[0]
    return int(n)


def parquet_inventory(root):
    output = []
    for p in sorted(Path(root).rglob('*')):
        if not p.is_file():
            continue
        item = {'relative_path': p.relative_to(root).as_posix(), 'sha256': sha(p), 'size_bytes': p.stat().st_size}
        if p.suffix == '.parquet':
            pf = pq.ParquetFile(p)
            item.update(rows=pf.metadata.num_rows,
                        schema=[{'name': f.name, 'type': str(f.type)} for f in pf.schema_arrow])
        output.append(item)
    return output


def verify_stage(path, contract):
    done_path = Path(path)/'_DONE.json'
    require(done_path.is_file(), 'Unrecognized/incomplete existing stage preserved: '+str(path))
    done = read_json(done_path)
    require(done['contract_sha256'] == contract, 'Stage contract differs: '+str(path))
    expected = set()
    for item in done['files']:
        rel = item['relative_path']; require(rel not in expected, 'Duplicate stage manifest entry')
        expected.add(rel); p = relative_file(path, rel)
        require(p.is_file() and p.stat().st_size == item['size_bytes'] and sha(p) == item['sha256'], 'Completed stage file changed: '+str(p))
    actual = {p.relative_to(path).as_posix() for p in Path(path).rglob('*') if p.is_file() and p != done_path}
    require(actual == expected, 'Unlisted/missing files in completed stage: '+str(path))
    return done


def stage(path, contract, producer):
    path = Path(path)
    if path.exists():
        result = verify_stage(path, contract)
        log('Reusing checked stage: '+path.name)
        return result
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name('.partial_'+path.name+'_'+uuid.uuid4().hex)
    tmp.mkdir()
    info = producer(tmp)
    done = {'contract_sha256': contract, 'files': parquet_inventory(tmp), 'info': info}
    write_json(tmp/'_DONE.json', done)
    os.rename(tmp, path)
    return done


@contextlib.contextmanager
def lock(path):
    with Path(path).open('a+') as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('Another sample builder is using this output root') from exc
        yield


@contextlib.contextmanager
def heartbeat(label):
    stop = threading.Event(); started = time.monotonic()
    def beat():
        while not stop.wait(30):
            log(f'{label}; {(time.monotonic()-started)/60:.1f} minutes elapsed')
    t = threading.Thread(target=beat, daemon=True); t.start()
    try:
        yield
    finally:
        stop.set(); t.join()


def small_parquet(path, rows):
    require(bool(rows), 'Unexpected empty aggregate table: '+str(path))
    pq.write_table(pa.Table.from_pylist(rows), path, compression='zstd')
