"""Atomic local I/O; source inputs are never modified."""
from __future__ import annotations
import contextlib, hashlib, json, os, tempfile, threading, time, zipfile
from pathlib import Path
import numpy as np
import pandas as pd


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def log(message):
    print(time.strftime('[%Y-%m-%d %H:%M:%SZ] ', time.gmtime()) + str(message), flush=True)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(8 * 1024**2), b''):
            h.update(block)
    return h.hexdigest()


def binding(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def atomic_text(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + '.', suffix='.partial', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(value)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def json_write(path, value):
    def default(x):
        if isinstance(x, np.ndarray): return x.tolist()
        if isinstance(x, np.generic): return x.item()
        if isinstance(x, Path): return str(x)
        raise TypeError(type(x).__name__)
    atomic_text(path, json.dumps(value, indent=2, sort_keys=True, default=default, allow_nan=False) + '\n')


def json_read(path):
    return json.loads(Path(path).read_text())


def csv_write(path, rows):
    atomic_text(path, pd.DataFrame(rows).to_csv(index=False))


def qs(value):
    return "'" + str(value).replace("'", "''") + "'"


def copy_query(db, sql, path):
    path = Path(path)
    part = path.with_suffix('.parquet.partial')
    # The exact intermediate belongs to this program and is replaced on resume.
    if part.exists(): part.unlink()
    db.execute(f'COPY ({sql}) TO {qs(part)} (FORMAT PARQUET, COMPRESSION ZSTD)')
    os.replace(part, path)


@contextlib.contextmanager
def heartbeat(label):
    stop = threading.Event()
    start = time.monotonic()
    def pulse():
        while not stop.wait(45): log(f'{label}: working, {(time.monotonic()-start)/60:.1f} min')
    thread = threading.Thread(target=pulse, daemon=True)
    thread.start()
    try: yield
    finally:
        stop.set()
        thread.join()


def export_report(report, desktop, runid):
    report, desktop = Path(report), Path(desktop)
    desktop.mkdir(parents=True, exist_ok=True)
    forbidden = {'chooser','chooser_user_id','recipient_id','opponent_id','game_id','username','account_id'}
    for p in report.glob('*.csv'):
        if p.stat().st_size:
            require(not (set(p.read_text().splitlines()[0].split(',')) & forbidden),
                    'Identifier column in public output: ' + p.name)
    entries = [f'{digest(p)}  {p.relative_to(report)}' for p in sorted(report.rglob('*'))
               if p.is_file() and p.name != 'REPORT_MANIFEST.sha256']
    atomic_text(report/'REPORT_MANIFEST.sha256', '\n'.join(entries)+'\n')
    out = desktop/f'POOL_CHOOSER_BENCHMARK_RESULTS_v100_{runid}.zip'
    part = out.with_suffix('.zip.partial')
    with zipfile.ZipFile(part, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in sorted(report.rglob('*')):
            if p.is_file(): z.write(p, 'report/' + str(p.relative_to(report)))
    os.replace(part, out)
    atomic_text(str(out)+'.sha256', digest(out)+'  '+out.name+'\n')
    log('UPLOAD: '+str(out))
    log('UPLOAD: '+str(out)+'.sha256')
    return out
