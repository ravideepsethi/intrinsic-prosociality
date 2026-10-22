"""Shared I/O and provenance for the arena replication. No network operations."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parent
VERSION = '1.0.2'
NONADJACENT = 'not_mutually_adjacent_observed'
EXPECTED = {
    'all': (47587020, 669503, 17328130, 487170),
    'arena_all': (1905304, 20884, 735845, 13186),
    'pool_all': (44138221, 606657, 16041534, 444606),
    'pool_nonadjacent': (41534331, 570091, 15207423, 419463),
    'arena_nonadjacent_rows': 1892835,
}

def log(message):
    print(time.strftime('[%Y-%m-%dT%H:%M:%SZ]', time.gmtime()), message, flush=True)

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()

def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, 'tolist'):
        return clean(value.tolist())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value

def json_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f'.tmp.{os.getpid()}')
    tmp.write_text(json.dumps(clean(value), indent=2, sort_keys=True, allow_nan=False) + '\n')
    os.replace(tmp, path)

def read_json(path):
    return json.loads(Path(path).read_text())

def fingerprint(value):
    return hashlib.sha256(json.dumps(clean(value), sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def q(value):
    return "'" + str(value).replace("'", "''") + "'"

def parquet(paths):
    if isinstance(paths, (str, Path)):
        paths = [paths]
    return 'read_parquet([' + ','.join(q(p) for p in paths) + '], hive_partitioning=false, union_by_name=false)'

def database(path, threads, memory, tmp, *, with_timezone_info=False):
    import duckdb
    Path(tmp).mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    inherited_timezone = con.execute("SELECT current_setting('TimeZone')").fetchone()[0]
    # The authenticated panel uses UTC calendar months. The original builder
    # sets this before mask_validation; every wrapper connection must do so too.
    con.execute("SET TimeZone='UTC'")
    con.execute(f'SET threads={int(threads)}')
    con.execute(f'SET memory_limit={q(memory)}')
    con.execute(f'SET temp_directory={q(tmp)}')
    con.execute('SET preserve_insertion_order=false')
    if with_timezone_info:
        return con, {'inherited_timezone': inherited_timezone,
                     'active_timezone': con.execute("SELECT current_setting('TimeZone')").fetchone()[0]}
    return con

def rows(con, sql):
    result = con.execute(sql)
    names = [c[0] for c in result.description]
    return [dict(zip(names, row)) for row in result.fetchall()]

def write_table(con, sql, path):
    """Save aggregate tables in both CSV and Parquet without implicit index columns."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f'COPY ({sql}) TO {q(path.with_suffix(".parquet"))} (FORMAT PARQUET, COMPRESSION ZSTD)')
    con.execute(f'COPY ({sql}) TO {q(path.with_suffix(".csv"))} (HEADER, DELIMITER ",")')

def load_source(relative, name):
    path = ROOT / relative
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

def verify_package():
    manifest = ROOT / 'PACKAGE_MANIFEST.sha256'
    require(manifest.is_file(), 'Package manifest is missing')
    for line in manifest.read_text().splitlines():
        digest, name = line.split('  ', 1)
        p = (ROOT / name).resolve()
        require(p.is_relative_to(ROOT) and sha(p) == digest, f'Package checksum failed: {name}')
    for entry in read_json(ROOT / 'authority/UPSTREAM_FILES.json')['files']:
        require(sha(ROOT / entry['path']) == entry['sha256'], 'Recovered upstream source changed')
    return sha(manifest)

def manifest(root):
    root = Path(root)
    return [{'path': str(p.relative_to(root)), 'bytes': p.stat().st_size, 'sha256': sha(p)}
            for p in sorted(root.rglob('*')) if p.is_file()
            and p.name not in ('_DONE.json', 'MANIFEST.json') and '__pycache__' not in p.parts]

def complete(root, contract, extra=None):
    result = {'status': 'ARENA_STAGE_COMPLETE', 'contract': contract,
              'files': manifest(root), **(extra or {})}
    json_write(Path(root) / '_DONE.json', result)
    return result

def verify_complete(root, contract):
    root = Path(root)
    if not (root / '_DONE.json').is_file():
        return None
    saved = read_json(root / '_DONE.json')
    require(saved['contract'] == contract, f'Existing stage has a different contract: {root.name}')
    for r in saved['files']:
        p = root / r['path']
        require(p.is_file() and p.stat().st_size == r['bytes'] and sha(p) == r['sha256'],
                f'Completed output changed: {root.name}/{r["path"]}')
    return saved

def versions():
    import duckdb, numpy, pandas, pyarrow, scipy
    return {'python': sys.version, 'platform': platform.platform(),
            **{m.__name__: m.__version__ for m in (duckdb, numpy, pandas, pyarrow, scipy)}}

def ram_gb():
    try:
        return os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES') / 1024**3
    except (ValueError, OSError, AttributeError):
        return 16.0

def board_case(col='eval'):
    return f'CASE WHEN {col}>=300 THEN 0 WHEN {col}>=101 THEN 1 WHEN {col}>=-100 THEN 2 WHEN {col}>=-299 THEN 3 ELSE 4 END'

def ply_case(col='ply'):
    return f'CASE WHEN {col}<=4 THEN 0 WHEN {col}<=6 THEN 1 WHEN {col}<=8 THEN 2 WHEN {col}<=10 THEN 3 WHEN {col}<=20 THEN 4 WHEN {col}<=40 THEN 5 WHEN {col}<=80 THEN 6 ELSE 7 END'
