"""Shared contracts for the read-only slide audit."""
from __future__ import annotations
import os
for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
            'VECLIB_MAXIMUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[key] = '1'
import csv, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import local_io as io

VERSION = '1.0.0'
BASE = Path('/Volumes/XT_Pro/lichess_kindness')
HEADLINE_REL = 'derived/replication/chooser_iv_expanded_v100_PRIVATE/f14a1105a9f7/analysis/spaced90.parquet'
HEADLINE_SHA = '3bc55d83f113cd7c5942348b16ae9ff5e940ae8aad13f9db3d99a6a526ef250c'
HEADLINE_BYTES = 295180899
HEADLINE_N = 2682330
RUN3_REL = 'derived/replication/iv_run3_leniency_v100_PRIVATE/c729efbf3215'
RUN3_CONF = 'c729efbf3215c7df169b7c4135febc7335b23e6297074d109aad918536a676aa'
REFERENCE_SD = 0.059411690344000595
MODEL_COLS = ['row_id', 'recipient_id', 'opponent_id', 'received',
              'recipient_rating', 'opponent_rating', 'archive_start_ms',
              'month_code', 'tc_base_s', 'tc_inc_s', 'n_7d', 'adjusted_7d',
              'expected_7d', 'counterparts_7d', 'pre_games_30d'] + [
    f'{c}_{days}' for days in (90, 30)
    for c in ('fair', 'kind', 'disconnect', 'receipt', 'claim')]
HEADLINE_FIT = dict(coefficient=1.1633383003440598,
                    standard_error=0.00666888594691755,
                    native_residual_score_SD=0.057367422080685834)

def write_csv(path, rows):
    rows = io.clean(rows)
    names = list(dict.fromkeys(k for row in rows for k in row))
    with Path(path).open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=names)
        w.writeheader()
        for row in rows:
            w.writerow({k: json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v
                        for k, v in row.items()})

def verify_release():
    manifest = ROOT / 'PACKAGE_MANIFEST.sha256'
    for line in manifest.read_text().splitlines():
        digest, name = line.split('  ', 1)
        io.checked(io.child(ROOT, name), digest)
    return io.sha(manifest)

def read_cohort(path, outcomes=False):
    columns = MODEL_COLS + (['y', 'reached'] if outcomes else [])
    pf = pq.ParquetFile(path)
    missing = sorted(set(columns) - set(pf.schema_arrow.names))
    if missing:
        raise RuntimeError('Cohort schema is missing: ' + ', '.join(missing))
    t = pf.read(columns=columns, use_threads=False)
    for name in columns:
        if t[name].null_count:
            raise RuntimeError('Missing values in frozen column: ' + name)
    d = {name: io.arr(t, name) for name in columns}
    del t
    if len(np.unique(d['row_id'])) != len(d['row_id']):
        raise RuntimeError('Duplicate frozen row IDs')
    if np.any(d['recipient_id'] == d['opponent_id']):
        raise RuntimeError('Self-pair in cohort')
    for col in ['received'] + (['y', 'reached'] if outcomes else []):
        if not np.isin(d[col], [0, 1]).all():
            raise RuntimeError('Nonbinary ' + col)
    if outcomes and np.any(np.asarray(d['y'], bool) & ~np.asarray(d['reached'], bool)):
        raise RuntimeError('Y=1 without reaching an opportunity')
    if np.any(d['n_7d'] < 5) or not np.isfinite(d['adjusted_7d']).all():
        raise RuntimeError('Unsupported historical score')
    return d

def authenticate_headline(project):
    path = project / HEADLINE_REL
    info = io.checked(path, HEADLINE_SHA, HEADLINE_BYTES)
    if pq.ParquetFile(path).metadata.num_rows != HEADLINE_N:
        raise RuntimeError('Wrong frozen headline cohort size')
    return path, info

def authenticate_run3(project):
    """Only consume an already completed Run 3. Never rebuild its histories."""
    root = project / RUN3_REL
    path = root / 'clean_sample/sample.parquet'
    if not path.exists():
        return None, dict(status='NOT_AVAILABLE', reason='Cached Run 3 sample absent')
    receipt = io.load(root / 'clean_sample/_DONE.json')
    if receipt.get('config_sha256') != RUN3_CONF:
        raise RuntimeError('Unexpected Run 3 clean-sample configuration')
    design = io.load(root / 'DESIGN_FREEZE.json')
    if design != io.load(ROOT / 'evidence/run3_design.json') or io.cfgsha(design) != RUN3_CONF:
        raise RuntimeError('Run 3 design does not match the reviewed design')
    rec = next((r for r in receipt['files'] if r['path'] == 'sample.parquet'), None)
    if rec is None:
        raise RuntimeError('Run 3 sample is absent from its checkpoint manifest')
    info = io.checked(path, rec['sha256'], rec['bytes'])
    if pq.ParquetFile(path).metadata.num_rows != 2682329:
        raise RuntimeError('Wrong Run 3 diagnostic sample size')
    return path, dict(status='VERIFIED_CACHED_RUN3', **info)
