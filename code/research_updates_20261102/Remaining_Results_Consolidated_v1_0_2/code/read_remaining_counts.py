#!/usr/bin/env python3
"""Read existing narrow Parquet columns. No models, writes to caches, or network.

Only aggregate counts are returned. Fixed sample gates prevent a nearby frame
from silently substituting for the paper's spaced/reputation samples.
"""
from pathlib import Path
import argparse
import csv
import hashlib
import json
import sys
import time
import zipfile

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

SPACED_N = 3103311
SPACED_SHA = 'ce3751fda15f20b2ebe1840716e908a8c4cb182fbe20825498103c19cd94189e'
PAIR_ROWS = 8296678
TENURE_SHA = '7a3337725ab440d8f7dddbd98d71d1db8625d058dcd2ee64f40e1363f4a14162'
IV_REL = 'derived/replication/mating_material_iv_batch_v100_PRIVATE/12093d55b7ee9f73'
NONIV_REL = 'derived/replication/mating_material_noniv_batch_v102_PRIVATE/c6d1eef82b6b9890'
TENURE_REL = 'output/tenure_responsibility_v100/c539ba215e708b22/PRIVATE/selected_accounts.parquet'


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def signature(path):
    p = Path(path)
    s = p.stat()
    return {'path': str(p.resolve()), 'bytes': s.st_size, 'mtime_ns': s.st_mtime_ns}


def read_json(path):
    return json.loads(Path(path).read_text())


def columns(path, names, expected_n=None):
    """Bounded Arrow batches into narrow owned arrays; reject null/float counts."""
    before = signature(path)
    p = pq.ParquetFile(path)
    n = p.metadata.num_rows
    require(expected_n is None or n == expected_n, f'{path}: expected {expected_n} rows, got {n}')
    require(set(names) <= set(p.schema_arrow.names), f'{path}: missing columns {set(names)-set(p.schema_arrow.names)}')
    out = {}
    for name in names:
        t = p.schema_arrow.field(name).type
        require(pa.types.is_integer(t) or pa.types.is_boolean(t), f'{path}: {name} is not an integer/boolean')
        dtype = np.bool_ if pa.types.is_boolean(t) else (np.uint64 if pa.types.is_unsigned_integer(t) else np.int64)
        out[name] = np.empty(n, dtype=dtype)
    at = 0
    for batch in p.iter_batches(batch_size=131072, columns=names, use_threads=False):
        for name in names:
            c = batch.column(batch.schema.get_field_index(name))
            require(c.null_count == 0, f'{path}: null in {name}')
            out[name][at:at+len(batch)] = c.to_numpy(zero_copy_only=False)
        at += len(batch)
    require(at == n and signature(path) == before, f'{path}: changed/incomplete during read')
    return out, before


def row_hash(ids):
    ids = np.asarray(ids, dtype='<i8')
    require(len(ids) > 0 and np.all(ids[1:] > ids[:-1]), 'Row IDs must be unique and increasing')
    return hashlib.sha256(ids.tobytes()).hexdigest()


def selected_after_counts(path, ids, n_all):
    """Join the global score cache to fixed spaced IDs without reading wide rows."""
    before = signature(path)
    p = pq.ParquetFile(path)
    fields = ['row_id', 'n_A', 'n_C']
    require(set(fields) <= set(p.schema_arrow.names), 'Global score cache lacks A/C counts')
    for name in fields:
        require(pa.types.is_integer(p.schema_arrow.field(name).type), f'Global score {name} must be integral')
    found = np.zeros(len(ids), dtype=bool)
    values = np.empty(len(ids), dtype=np.int64)
    started = time.monotonic()
    last = started
    rows_read = 0
    for batch in p.iter_batches(batch_size=131072, columns=fields, use_threads=False):
        for col in batch.columns:
            require(col.null_count == 0, 'Global score cache contains null counts/IDs')
        r, a, c = [col.to_numpy(zero_copy_only=False) for col in batch.columns]
        pos = np.searchsorted(ids, r)
        hit = pos < len(ids)
        hit[hit] &= ids[pos[hit]] == r[hit]
        where = pos[hit]
        require(len(np.unique(where)) == len(where) and not found[where].any(), 'Duplicate selected global score IDs')
        require(np.array_equal(a[hit], n_all[where]), 'Global and spaced donor counts disagree')
        require(np.all(c[hit] >= 0) and np.all(c[hit] <= a[hit]), 'After-anchor donor count outside [0,n_A]')
        values[where] = c[hit]
        found[where] = True
        rows_read += len(batch)
        if time.monotonic() - last > 25:
            print(f'After-anchor counts: {rows_read:,}/{p.metadata.num_rows:,} score rows scanned', flush=True)
            last = time.monotonic()
    require(found.all(), f'Global scores miss {int((~found).sum())} spaced IDs')
    require(signature(path) == before, 'Global score cache changed during read')
    return values, before


def spaced_inputs(root):
    source = root/'PRIVATE/model_inputs/legacy_spaced/source.parquet'
    scores = root/'PRIVATE/model_inputs/legacy_spaced/scores.parquet'
    d, ds = columns(source, ['row_id', 'environment_supported'], SPACED_N)
    s, ss = columns(scores, ['row_id', 'n_A'], SPACED_N)
    require(row_hash(d['row_id']) == SPACED_SHA, 'Spaced source row hash differs from the authenticated result')
    require(np.array_equal(d['row_id'], s['row_id']), 'Source and score IDs/order differ')
    require(np.all(s['n_A'] >= 5), 'Spaced all-time score has unsupported donors')
    require(np.isin(d['environment_supported'], [0, 1]).all(), 'Environment support must be 0/1')
    return d, s, [ds, ss]


def pair_count(path, expected_n=PAIR_ROWS):
    d, sig = columns(path, ['pair_key'], expected_n)
    key = d['pair_key']
    require(key.dtype == np.uint64, 'Reputation pair_key must be uint64, as in its producer')
    low, high = key >> np.uint64(32), key & np.uint64(0xffffffff)
    require(np.all(low < high), 'Pair keys are not canonical unordered distinct pairs')
    return int(len(np.unique(key))), sig


def reputation_source(noniv_root, project_root):
    """Resolve an adopted family through completion receipts, never version guesses.

    v101/v102 copy public reports, while DONE.json retains absolute records for
    v100 private outputs. An adopted_from link is followed only if the receipt
    does not itself name the required private output.
    """
    project_root = Path(project_root).resolve()
    stage = Path(noniv_root)/'PRIVATE/stages/reputation'
    suffix = ('PRIVATE', 'stages', 'reputation', 'PRIVATE', 'features', 'analysis.parquet')
    visited, receipts = set(), []
    fingerprint = None
    while True:
        stage = stage.resolve()
        require(stage.is_relative_to(project_root), 'Reputation completion path escapes the project tree')
        require(stage not in visited, 'Cycle in reputation adoption receipts')
        visited.add(stage)
        receipt = stage/'DONE.json'
        before = signature(receipt)
        done = read_json(receipt)
        require(done.get('status') == 'COMPLETE', 'Reputation stage is not committed: '+str(receipt))
        fp = done.get('input_fingerprint')
        require(isinstance(fp, str) and bool(fp), 'Reputation completion lacks input fingerprint')
        if fingerprint is None:
            fingerprint = fp
        require(fp == fingerprint, 'Reputation adoption chain changes corrected inputs')
        records = {}
        for rec in done.get('files', []):
            p = Path(rec.get('path', ''))
            if tuple(p.parts[-len(suffix):]) != suffix:
                continue
            require(p.is_absolute(), 'Reputation output receipt must use an absolute path')
            p = p.resolve()
            require(p.is_relative_to(project_root), 'Recorded reputation output escapes the project tree')
            if str(p) in records:
                require(rec['sha256'] == records[str(p)]['sha256'] and rec['bytes'] == records[str(p)]['bytes'], 'Conflicting records for reputation output')
            records[str(p)] = rec
        require(signature(receipt) == before, 'Reputation completion changed during read')
        receipts.append(dict(before, sha256=digest(receipt)))
        if records:
            require(len(records) == 1, 'Ambiguous reputation feature outputs in completion receipt')
            path = Path(next(iter(records)))
            rec = records[str(path)]
            snap = signature(path)
            require(snap['bytes'] == rec['bytes'], 'Recorded reputation feature file size changed')
            print('Resolved reputation cache: '+str(path), flush=True)
            print('Verifying the recorded cache checksum before counting.', flush=True)
            require(digest(path) == rec['sha256'], 'Recorded reputation feature checksum differs')
            require(signature(path) == snap, 'Reputation cache changed during verification')
            return path, dict(resolved_file=dict(snap, sha256=rec['sha256']), receipts=receipts,
                              input_fingerprint=fingerprint, resolution='DONE.json private file record')
        parent = done.get('adopted_from')
        require(parent, 'Reputation completion names neither features nor an adopted_from stage')
        stage = Path(parent)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, default=Path('/Volumes/XT_Pro/lichess_kindness'))
    parser.add_argument('--iv-root', type=Path)
    parser.add_argument('--noniv-root', type=Path)
    parser.add_argument('--only-reputation', action='store_true', help='Recover only the pair count; do not repeat the completed IV/tenure counts.')
    parser.add_argument('--output-dir', type=Path, default=Path.home()/'Desktop/Lichess_Desktop/Remaining_Counts_Reports')
    args = parser.parse_args()
    iv = args.iv_root or args.project_root/IV_REL
    noniv = args.noniv_root or args.project_root/NONIV_REL
    # User outputs must never be directed into the existing project/cache tree.
    require(not args.output_dir.resolve().is_relative_to(args.project_root.resolve()), 'Output directory must be outside the private project tree')
    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    out = args.output_dir/('COUNTS_'+stamp)
    out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    results, errors, inputs = [], [], []
    reputation_resolution = None

    def emit(item, value, unit, n, source, column, definition):
        results.append(dict(item=item, value=value, units=unit, n=n, source_file=str(source), source_column=column, definition=definition))

    def fail(stage, ex):
        errors.append(dict(stage=stage, error=str(ex)))
        print(f'{stage}: unavailable; {ex}', flush=True)

    print('Expected runtime: '+('1–5 minutes' if args.only_reputation else '3–10 minutes')+' provisionally on an external SSD; no regressions or network requests.', flush=True)
    d = s = None
    try:
        if args.only_reputation:
            raise StopIteration
        d, s, verified = spaced_inputs(iv)
        inputs.extend(verified)
        src = iv/'PRIVATE/model_inputs/legacy_spaced/source.parquet'
        sc = iv/'PRIVATE/model_inputs/legacy_spaced/scores.parquet'
        emit('median_opponent_decisions', float(np.median(s['n_A'])), 'decisions per exposure opponent', SPACED_N, sc, 'n_A', 'Median across spaced exposure rows, after full pair exclusion; opponents are not deduplicated.')
        emit('mean_opponent_decisions', float(np.mean(s['n_A'])), 'decisions per exposure opponent', SPACED_N, sc, 'n_A', 'Arithmetic mean across spaced exposure rows, after full pair exclusion.')
        missing = int(np.count_nonzero(d['environment_supported'] == 0))
        emit('missing_environment_rows', missing, 'exposures', SPACED_N, src, 'environment_supported', 'Count of support indicator equal to zero on authenticated spaced rows.')
        emit('missing_environment_share_percent', 100*missing/SPACED_N, 'percent of exposures', SPACED_N, src, 'environment_supported', '100 times unsupported exposures divided by all spaced exposures.')
        print('Spaced donor and environment counts complete.', flush=True)
    except StopIteration:
        pass
    except Exception as ex:
        fail('spaced_counts', ex)
    if d is not None and s is not None:
        try:
            manifest = iv/'PRIVATE/FRAMES90.json'
            before = signature(manifest)
            sc = Path(read_json(manifest)['scores'])
            if not sc.is_absolute():
                sc = iv/sc
            c, sig = selected_after_counts(sc, d['row_id'], s['n_A'])
            require(signature(manifest) == before, 'Frame manifest changed during read')
            inputs.extend([before, sig])
            emit('after_anchor_share_decision_links_percent', 100*int(c.sum())/int(s['n_A'].sum()), 'percent of exposure-donor links', SPACED_N, sc, 'n_C / n_A', 'Ratio of summed strictly-after-anchor counts to summed all-time counts; a donor linked to multiple exposures counts for each link.')
            emit('after_anchor_share_mean_exposure_percent', float(100*np.mean(c/s['n_A'])), 'percent, equal exposure weights', SPACED_N, sc, 'n_C / n_A', 'Mean of each exposure opponent history share strictly after the exposure last-move anchor. Not after game start.')
            print('After-anchor donor shares complete.', flush=True)
        except Exception as ex:
            fail('after_anchor_counts', ex)
    try:
        path, reputation_resolution = reputation_source(noniv, args.project_root)
        count, sig = pair_count(path, PAIR_ROWS)
        require(sig == {k:reputation_resolution['resolved_file'][k] for k in sig}, 'Reputation cache changed between verification and counting')
        inputs.append(sig)
        emit('retained_reputation_unordered_pairs', count, 'distinct unordered account pairs', PAIR_ROWS, path, 'pair_key', 'Distinct canonical pair keys among the corrected retained reputation focal opportunities; not all pairs in the original fold index.')
        print('Corrected reputation pair count complete.', flush=True)
    except Exception as ex:
        fail('reputation_pairs', ex)
    try:
        if args.only_reputation:
            raise StopIteration
        path = args.project_root/TENURE_REL
        before = signature(path)
        require(digest(path) == TENURE_SHA, 'Selected-account bytes differ from the reused frozen input')
        n = pq.ParquetFile(path).metadata.num_rows
        require(signature(path) == before, 'Selected-account file changed during read')
        inputs.append(dict(before, sha256=TENURE_SHA))
        require(n == 100000, 'Selected-account footer disagrees with original nominal draw size')
        emit('tenure_selected_account_rows', n, 'nominal selected-account rows', n, path, 'Parquet footer num_rows', 'Independent footer check of the already-sourced original 100,000-account sampling design. Not fitted clusters.')
        print('Tenure sample footer confirmed.', flush=True)
    except StopIteration:
        pass
    except Exception as ex:
        fail('tenure_footer', ex)
    report = dict(status='COMPLETE' if not errors else 'PARTIAL', private_models_executed=False, counts_executed=True,
                  expected_spaced_row_sha256=SPACED_SHA, elapsed_seconds=time.monotonic()-started,
                  results=results, errors=errors, inputs=inputs, reputation_resolution=reputation_resolution,
                  requested_scope='reputation_pairs_only' if args.only_reputation else 'all_remaining_counts', version='1.0.1')
    (out/'COUNT_RESULTS.json').write_text(json.dumps(report, indent=2)+'\n')
    with (out/'COUNT_RESULTS.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['item','value','units','n','source_file','source_column','definition'])
        writer.writeheader()
        writer.writerows(results)
    (out/'checksums.txt').write_text(''.join(f'{digest(p)}  {p.name}\n' for p in sorted(out.iterdir()) if p.is_file()))
    target = out.with_suffix('.zip')
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in sorted(out.iterdir()):
            z.write(p, out.name+'/'+p.name)
    target.with_suffix('.zip.sha256').write_text(digest(target)+'  '+target.name+'\n')
    print(f'Return this aggregate-only report: {target}', flush=True)
    return 0 if not errors else 2


if __name__ == '__main__':
    sys.exit(main())
