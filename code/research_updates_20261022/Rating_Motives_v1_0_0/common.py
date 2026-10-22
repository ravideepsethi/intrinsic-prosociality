"""Local-only utilities. No source file is ever modified."""
import csv, hashlib, json, os, platform, sys, time
from pathlib import Path
import duckdb
import numpy as np
from source.pool_wave1_common import atomic_json, atomic_text, sha256_file

ROOT = Path(__file__).resolve().parent
DAY = 86400000
SPEEDS = ['ultraBullet', 'bullet', 'blitz', 'rapid', 'classical', 'correspondence']

def log(message):
    print(time.strftime('%Y-%m-%d %H:%M:%S UTC ', time.gmtime()) + message, flush=True)

def sqlstr(value):
    return "'" + str(value).replace("'", "''") + "'"

def parquet(paths):
    if isinstance(paths, (str, Path)): paths = [paths]
    return 'read_parquet([' + ','.join(sqlstr(p) for p in paths) + '], hive_partitioning=false, union_by_name=true)'

def connect(work, threads=8, memory='8GB'):
    con = duckdb.connect()
    temp = Path(work) / 'duckdb_tmp'; temp.mkdir(parents=True, exist_ok=True)
    con.execute(f"SET threads={int(threads)}")
    con.execute(f"SET memory_limit={sqlstr(memory)}")
    con.execute(f"SET temp_directory={sqlstr(temp)}")
    con.execute('SET preserve_insertion_order=false')
    return con

def records(con, query):
    cur = con.execute(query); names = [x[0] for x in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]

def write_csv(path, rows):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    if not rows: atomic_text(path, 'status\nNO_ROWS\n'); return
    keys = list(dict.fromkeys(k for row in rows for k in row))
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction='raise'); w.writeheader(); w.writerows(rows)
    tmp.replace(path)

def clean_json(value):
    if isinstance(value, dict): return {str(k):clean_json(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)): return [clean_json(v) for v in value]
    if isinstance(value, np.ndarray): return clean_json(value.tolist())
    if isinstance(value, np.generic): return clean_json(value.item())
    if isinstance(value, float) and not np.isfinite(value): return None
    if isinstance(value, Path): return str(value)
    return value

def save_json(path, value): atomic_json(Path(path), clean_json(value))

def digest(value):
    return hashlib.sha256(json.dumps(clean_json(value),sort_keys=True,separators=(',',':')).encode()).hexdigest()

def code_manifest():
    saved = json.loads((ROOT/'PACKAGE_MANIFEST.json').read_text())
    for name, expected in saved['sha256'].items():
        if sha256_file(ROOT/name) != expected: raise RuntimeError('Package integrity mismatch: '+name)
    actual = {str(p.relative_to(ROOT)) for p in ROOT.rglob('*.py') if '.venv' not in p.parts}
    if actual != {n for n in saved['sha256'] if n.endswith('.py')}:
        raise RuntimeError('Unexpected/missing Python source in package')
    return digest(saved)

def environment():
    import scipy, pyarrow
    return dict(python=sys.version,platform=platform.platform(),numpy=np.__version__,scipy=scipy.__version__,
                pyarrow=pyarrow.__version__,duckdb=duckdb.__version__)

def output_receipt(path):
    p=Path(path);return dict(path=str(p),bytes=p.stat().st_size,sha256=sha256_file(p))

def checkpoint_ok(receipt, identity):
    receipt=Path(receipt)
    if not receipt.exists(): return False
    r=json.loads(receipt.read_text())
    if r['identity']!=identity: raise RuntimeError('Checkpoint belongs to different inputs or code: '+str(receipt))
    return all(Path(p['path']).is_file() and sha256_file(Path(p['path']))==p['sha256'] for p in r['outputs'])

def finish_checkpoint(receipt, identity, outputs, extra=None):
    save_json(receipt,dict(identity=identity,outputs=[output_receipt(p) for p in outputs],extra=extra))

def copy_parquet(con, query, path):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.partial.parquet'); tmp.unlink(missing_ok=True)
    con.execute(f"COPY ({query}) TO {sqlstr(tmp)} (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 65536)")
    tmp.replace(path)

def stable_profile_source(project, explicit=None):
    sources=[]
    expected='f42f28a6540a65c0a83f0da488663b4adddf60d1001daeed556f1ffbb961e238'
    p=Path(explicit) if explicit else Path(project)/'derived/replication/patron_profile_snapshot_24m_v100_FINAL_CERTIFIED/profile_snapshot_24m_private_lossless.parquet'
    if not p.is_file(): raise FileNotFoundError('Certified profile snapshot missing: '+str(p))
    if sha256_file(p)!=expected: raise RuntimeError('Profile snapshot SHA-256 differs from audited lossless snapshot')
    sources.append(dict(path=str(p),sha256=expected,role_fallback='snapshot_role_unknown'))
    supplement_hash='39a9c911bb0030d2dacc7c73f77d0bb94bc27981be347dd3e03f30af8b0482aa'
    candidates=sorted(Path(project).glob('derived/replication/pool_main_reanalysis_v100_PRIVATE/patron_gap_fill_v100/*/current_profile_gap_supplement_private.parquet'))
    matched=[]
    for p in candidates:
        if sha256_file(p)==supplement_hash: matched.append(p)
    if matched: sources.append(dict(path=str(matched[0]),sha256=supplement_hash,role_fallback='gap_supplement'))
    return sources
