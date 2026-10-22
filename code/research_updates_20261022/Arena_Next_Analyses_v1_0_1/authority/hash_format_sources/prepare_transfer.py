#!/usr/bin/env python3
"""Run on the data Mac. Creates a private, self-contained home enrichment package."""
from __future__ import annotations
import argparse
from collections import defaultdict
import concurrent.futures as cf
import csv
import datetime as dt
import io
import json
from pathlib import Path
import shutil
import zipfile
import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import transfer_common as c

BASELINE_RECORDS=189452
BASELINE_NONEMPTY=5877

def authenticate(old):
    evidence = c.checked(c.CODE_ROOT / 'evidence/VALIDITY_REPORT.zip', c.VALIDITY_SHA)
    with zipfile.ZipFile(evidence) as z:
        prefix = 'CHOOSER_LENIENCY_VALIDITY_LOCAL_REPORT/'
        for r in csv.DictReader(io.StringIO(z.read(prefix + 'REPORT_MANIFEST.csv').decode())):
            b = z.read(prefix + r['file'])
            if len(b) != int(r['bytes']) or c.hashlib.sha256(b).hexdigest() != r['sha256']:
                raise RuntimeError('Embedded validity evidence is corrupt')
    config = c.load(old / 'config.json'); success = c.load(old / '_SUCCESS.json')
    conf = c.hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    if conf != c.VALIDITY_CONFIG or success.get('config_sha256') != conf or success.get('report_sha256') != c.VALIDITY_SHA:
        raise RuntimeError('Local validity run does not match the verified completed run')
    f, _ = c.checkpoint_file(old / 'comparison_sample', 'games.parquet')
    l, _ = c.checkpoint_file(old / 'source24m_and_comparison', 'comparison_source_status.parquet')
    return f, l

def align(frame, ledger, expected_n=c.FRAME_N, expected_pending=c.PENDING_N):
    if len(frame) != expected_n or len(ledger) != expected_n: raise RuntimeError('Original frame/ledger size changed')
    required = {'game_id','month','utc_ms','speed_partition','recipient_id','opponent_id','recipient_color'}
    if not required.issubset(frame.column_names): raise RuntimeError('Comparison-frame schema changed')
    ids = frame['game_id'].to_pylist(); lids = ledger['game_id'].to_pylist()
    if len(set(ids)) != len(ids) or len(set(lids)) != len(lids): raise RuntimeError('Duplicate frame/ledger game IDs')
    if any(not isinstance(g, str) or not c.core.GID.fullmatch(g) for g in ids + lids): raise RuntimeError('Invalid case-sensitive game ID')
    index = pc.index_in(frame['game_id'], value_set=ledger['game_id'])
    if index.null_count: raise RuntimeError('Ledger lost original frame games')
    ledger = ledger.take(index)
    if any(frame[x].null_count for x in required): raise RuntimeError('Null in required frame fields')
    src = ledger['source'].to_pylist()
    nmeta = ledger['metadata_usable_records'].to_numpy()
    conflicts = ledger['source_conflict'].to_numpy()
    pending = np.asarray([s is None for s in src]) | (nmeta <= 0) | conflicts
    if int(pending.sum()) != expected_pending: raise RuntimeError('Pending denominator does not reproduce 1,764,603')
    if np.any(frame['recipient_id'].to_numpy() == frame['opponent_id'].to_numpy()): raise RuntimeError('Self pair in frame')
    if set(frame['recipient_color'].to_pylist()) - {'white', 'black'}: raise RuntimeError('Unknown recipient orientation')
    return ledger, pending

def source_jobs(old):
    jobs = []; seen = set()
    for j in c.load(old / 'source_scan_jobs_PRIVATE.json'):
        root = Path(j['out']).resolve()
        if not root.is_relative_to(old.resolve()) or root in seen: raise RuntimeError('Invalid source checkpoint path')
        seen.add(root)
        r = c.load(root / '_COMPLETE.json')
        if r.get('config_sha256') != c.VALIDITY_CONFIG: raise RuntimeError('Metadata checkpoint configuration changed')
        hits = [f for f in r['files'] if f['path'] == 'metadata.parquet']
        if len(hits) != 1: raise RuntimeError('Missing extracted metadata manifest')
        jobs.append((root, hits[0], r.get('metadata_rows', -1)))
    return jobs

def read_job(job):
    root, rec, n = job; c.verify_records(root, [rec], 1)
    t = c.read_table(root / 'metadata.parquet', ['game_id','metadata_json'])
    if n >= 0 and len(t) != n: raise RuntimeError('Metadata row count changed')
    return t

def local_supplemental(project, extra):
    """Only authenticated normalized caches; never inspect raw archives or live partials."""
    paths = []; receipts = []
    base = project / 'derived/replication/chooser_leniency_preliminary_v100_PRIVATE'
    if base.is_dir():
        for run in sorted(base.iterdir()):
            root = run / 'audited_metadata'
            if not (root / '_COMPLETE.json').is_file(): continue
            config = c.load(run / 'config.json')
            conf = c.hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
            p, _ = c.checkpoint_file(root, 'records.parquet', conf)
            paths.append(p); receipts.append(dict(path=str(p), sha256=c.sha(p), origin='preliminary_audited_metadata'))
    for spec in extra:
        mpath = Path(spec).expanduser().resolve(); m = c.load(mpath)
        c.verify_records(mpath.parent, m['files'])
        for rec in m['files']:
            if rec['path'].endswith('.parquet'):
                paths.append(mpath.parent / rec['path']); receipts.append(dict(path=str(mpath.parent/rec['path']), sha256=rec['sha256'], origin='explicit_cache_manifest'))
    return paths, receipts

def collect_cache(old, project, frame, ledger, output, workers, extra):
    ids = frame['game_id'].to_pylist(); index = {g:i for i,g in enumerate(ids)}
    grouped = defaultdict(list); saved = []; jobs = source_jobs(old)
    c.log(f'Reading {len(jobs):,} extracted metadata checkpoints; raw API archive is not rescanned')
    original_records=0; nonempty=0
    with cf.ThreadPoolExecutor(max_workers=min(workers, 6)) as ex:
        for k, table in enumerate(ex.map(read_job, jobs), 1):
            original_records+=len(table); nonempty+=bool(len(table))
            for row in table.to_pylist():
                gid = row['game_id']
                if gid not in index: raise RuntimeError('Extracted comparison metadata contains an out-of-frame ID')
                obj = json.loads(row['metadata_json'])
                parsed, errs = c.core.normalize_export(obj, gid)
                grouped[gid].append((parsed, errs))
                saved.append(dict(game_id=gid, metadata_json=row['metadata_json']))
            if k % 1000 == 0: c.log(f'Extracted metadata checkpoints {k:,}/{len(jobs):,}')
    if original_records!=BASELINE_RECORDS or nonempty!=BASELINE_NONEMPTY:
        raise RuntimeError(f'Extracted metadata does not reproduce the verified run: {original_records:,} rows, {nonempty:,} nonempty files')
    # Preserve original full JSON, including any fields omitted by the typed projection.
    rawschema = pa.schema([('game_id',pa.string()),('metadata_json',pa.string())])
    c.write_table(output / 'inputs/baseline_metadata_json.parquet', pa.Table.from_pylist(saved, schema=rawschema))
    del saved
    paths, receipt = local_supplemental(project, extra)
    for p in paths:
        t = c.read_table(p)
        required = set(c.core.CORE_FIELDS) | {'game_id','metadata_valid','error_codes'}
        if not required.issubset(t.column_names): raise RuntimeError(f'Unsupported supplemental-cache schema: {p}')
        for row in t.to_pylist():
            if row['game_id'] not in index: continue
            # Existing flagged rows are retained as evidence and never treated as clean cache hits.
            errors = row['error_codes'].split(';') if row.get('error_codes') else []
            if not row['metadata_valid'] and not errors: errors = ['SUPPLEMENTAL_CACHE_NOT_VALID']
            grouped[row['game_id']].append((row, errors))
    needed = sorted(grouped); ix = pa.array([index[g] for g in needed])
    fs = frame.take(ix).to_pylist(); ls = ledger.take(ix).to_pylist()
    merged = []; ready = set()
    for gid, f, l in zip(needed, fs, ls):
        r, errs = c.core.merge_records(grouped[gid], gid)
        errors = c.validate_record(r, f, l, errs)
        r.update(month=f['month'], metadata_valid=not errors, error_codes=';'.join(errors),
                 metadata_json=None, origin='authenticated_local_cache')
        merged.append({field.name:r.get(field.name) for field in c.metadata_schema()})
        if not errors: ready.add(gid)
    c.write_table(output / 'inputs/cached_metadata.parquet', pa.Table.from_pylist(merged, schema=c.metadata_schema()))
    return ready, dict(extracted_records=sum(len(v) for v in grouped.values()),
                      cached_game_ids=len(grouped), cache_valid_game_ids=len(ready), supplemental=receipt)

def build(args):
    code_records=c.load(c.CODE_ROOT/'CODE_MANIFEST.json')['files']
    c.verify_records(c.CODE_ROOT, code_records, args.workers)
    project = args.project_root.expanduser().resolve()
    old = project / 'derived/replication/chooser_leniency_validity_local_v100_PRIVATE' / c.VALIDITY_ID
    if not old.is_dir(): raise RuntimeError(f'Completed validity-local run not found: {old}')
    c.enough_disk(project, 4)
    desktop = args.desktop.expanduser().resolve(); desktop.mkdir(parents=True, exist_ok=True)
    c.enough_disk(desktop, 2)
    fpath, lpath = authenticate(old)
    frame = c.read_table(fpath); ledger, pending = align(frame, c.read_table(lpath), c.FRAME_N, c.PENDING_N)
    # Where present, independently reconcile the existing target export by exact ID.
    targetroot = old/'source24m_and_comparison'
    names = [r['path'] for r in c.load(targetroot/'_COMPLETE.json')['files'] if Path(r['path']).name=='comparison_API_targets.parquet']
    if names:
        if len(names)!=1: raise RuntimeError('Ambiguous original target export')
        p,_ = c.checkpoint_file(targetroot,names[0])
        ids = c.read_table(p,['game_id'])['game_id'].to_pylist()
        expected = set(frame.filter(pa.array(pending))['game_id'].to_pylist())
        if len(ids)!=c.PENDING_N or set(ids)!=expected: raise RuntimeError('Existing API target export disagrees with ledger')
    transfer_id = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + c.uuid.uuid4().hex[:8]
    out = project/'derived/replication/comparison_home_transfer_v100_PRIVATE'/transfer_id
    out.mkdir(parents=True, exist_ok=False)
    for rec in code_records:
        rel=c.relative_safe(rec['path']); target=out/rel; target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(c.CODE_ROOT/rel,target)
    shutil.copy2(c.CODE_ROOT/'CODE_MANIFEST.json',out/'CODE_MANIFEST.json')
    if (c.CODE_ROOT/'PACKAGE_MANIFEST.sha256').is_file():
        shutil.copy2(c.CODE_ROOT/'PACKAGE_MANIFEST.sha256',out/'PACKAGE_MANIFEST.sha256')
    c.write_table(out/'inputs/frame.parquet', frame)
    c.write_table(out/'inputs/baseline_ledger.parquet', ledger)
    ready, cache = collect_cache(old, project, frame, ledger, out, args.workers, args.cache_manifest)
    ids = frame['game_id'].to_pylist()
    fetch = pending & np.asarray([g not in ready for g in ids])
    targets = frame.filter(pa.array(fetch))
    tledger = ledger.filter(pa.array(fetch))
    ledger_chunks=[]
    for batch in tledger.to_batches(max_chunksize=50000):
        ledger_chunks.append(pa.array([json.dumps(x,separators=(',',':')) for x in batch.to_pylist()],type=pa.string()))
    targets = targets.append_column('baseline_ledger_json', pa.chunked_array(ledger_chunks,type=pa.string()))
    targets = targets.sort_by([('month','ascending'),('game_id','ascending')])
    c.write_table(out/'inputs/targets.parquet', targets)
    receipt = dict(version=c.VERSION,transfer_id=transfer_id,frame_rows=len(frame),
        original_pending=c.PENDING_N,cache_recovered_pending=int(pending.sum()-fetch.sum()),
        api_targets=len(targets),original_frame_sha256=c.sha(fpath),original_ledger_sha256=c.sha(lpath),
        validity_report_sha256=c.VALIDITY_SHA,validity_config_sha256=c.VALIDITY_CONFIG,
        original_orientation_preserved=True,all_terminal_statuses_retained=True,sampling_changed=False,
        network_requests_during_prepare=0,cache=cache)
    c.atomic_json(out/'TRANSFER.json', receipt)
    c.manifest(out,'INPUT_MANIFEST.json',dict(transfer_id=transfer_id))
    destination = desktop/f'CHOOSER_COMPARISON_HOME_INPUT_{transfer_id}_PRIVATE.zip'
    checksum = c.zip_paths(out,destination,sorted(p for p in out.rglob('*') if p.is_file()))
    c.atomic_json(out/'PREPARATION_RECEIPT.json',dict(archive=str(destination),sha256=checksum))
    c.log(f'Original comparison frame: {len(frame):,}; original pending: {c.PENDING_N:,}; to fetch: {len(targets):,}')
    c.log('FULL_COMPARISON_HOME_TRANSFER_READY; NO_API_REQUESTS_MADE')
    c.log(f'TRANSFER ZIP: {destination}')
    c.log(f'SHA256: {checksum}')
    c.log('Transfer this PRIVATE ZIP and its .sha256 sidecar to the home laptop. Keep the originals.')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--workers',type=int,default=6)
    p.add_argument('--cache-manifest',action='append',default=[],help='Optional manifest of additional normalized metadata Parquets')
    a=p.parse_args()
    if not 1<=a.workers<=10: p.error('Use 1 to 10 local workers')
    c.os.umask(0o077); build(a)

if __name__=='__main__': main()
