"""Small, dependency-free provenance and I/O helpers."""
from __future__ import annotations
import csv
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

VERSION = '1.0.0'
TITLES = ('GM', 'IM', 'FM', 'CM', 'NM', 'WGM', 'WIM', 'WFM', 'WCM', 'WNM')

def now():
    return datetime.now(timezone.utc).isoformat()

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(16 * 1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()

def qs(x):
    return "'" + str(x).replace("'", "''") + "'"

def qi(x):
    return '"' + str(x).replace('"', '""') + '"'

def atomic_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(obj, indent=2, allow_nan=False) + '\n')
    os.replace(temp, path)

def records(db, sql, params=None):
    cur = db.execute(sql, params or [])
    names = [d[0] for d in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]

def one(db, sql, params=None):
    return records(db, sql, params)[0]

def write_csv(path, rows, fields=None):
    path = Path(path)
    fields = fields or list(dict.fromkeys(k for r in rows for k in r))
    with path.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

def log(message):
    print(f'[{now()}] {message}', flush=True)
