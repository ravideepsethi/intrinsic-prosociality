"""Read-only legacy inputs; unique-FEN repair; authenticated resumable outputs."""
from common import *
import gzip
from collections import Counter
from lineage import receipt, ENGINE_SHA
from features import score_kind, one_game
from score_stream import collect, CONTRACT

REPAIRABLE = {'BOUNDED', 'NO_SCORE', 'SHORT'}


def needs_repair(row):
    # A SHORT exact mate is already usable. A BOUNDED mate is not.
    return score_kind(row) is None and row['status'] in REPAIRABLE


def read_unit(unit):
    require(receipt(unit['replay'], unit['key']) and receipt(unit['scores'], unit['key']),
            'Legacy input receipt failed')
    games = load(unit['replay'])
    with gzip.open(unit['scores'], 'rt') as f:
        rows = json.load(f)
    by = {g['game_id']: [] for g in games}
    for row in rows:
        require(row['game_id'] in by, 'Unknown raw-score game')
        by[row['game_id']].append(row)
    # These validate position count, FEN and perspective, not just file hashes.
    for game in games:
        one_game(game, by[game['game_id']])
    return games, rows, by


def inventory_unit(job):
    unit, folder, key = job
    folder = Path(folder)
    p = folder / (unit['name'] + '.parquet')
    meta = folder / (unit['name'] + '.json')
    if valid(p, key) and valid(meta, key):
        return str(p), str(meta)
    games, rows, _ = read_unit(unit)
    pending = sorted({r['fen'] for r in rows if needs_repair(r)})
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(p) + '.partial')
    pd.DataFrame({'fen': pd.Series(pending, dtype='string')}).to_parquet(tmp, index=False, compression='zstd')
    os.replace(tmp, p)
    counts = Counter((r['status'], score_kind(r) or 'unavailable', needs_repair(r)) for r in rows)
    dump(meta, dict(positions=len(rows), games=len(games),
                   rows=[dict(status=s, kind=k, needs_repair=b, positions=n) for (s,k,b),n in sorted(counts.items())]))
    certify(p, key); certify(meta, key)
    return str(p), str(meta)


def find_engine(project, explicit=None):
    if explicit:
        p = Path(explicit).expanduser().resolve()
        require(p.is_file() and os.access(p, os.X_OK) and sha(p) == ENGINE_SHA,
                'Explicit engine is not the pinned, executable SF18 binary')
        return p
    for root in [project/'tools', project/'bin', project/'engines', project/'replication_package']:
        if root.exists():
            for p in root.rglob('*stockfish*'):
                if p.is_file() and os.access(p, os.X_OK) and p.stat().st_size < 200*1024**2 and sha(p) == ENGINE_SHA:
                    return p
    raise RuntimeError('Pinned SF18 absent. Supply --stockfish /absolute/path/to/the/existing/binary')


def evaluate_batch(job):
    import chess.engine
    p = Path(job['out']); trace = p.with_suffix('.trace.json.gz')
    key = job['key']
    if valid(p, key) and valid(trace, key):
        return dict(path=str(p), key=key, positions=len(job['fens']), cached=True)
    require(sha(job['engine']) == job['engine_sha'], 'Engine changed')
    engine = chess.engine.SimpleEngine.popen_uci(job['engine'], timeout=180)
    rows = []; messages = []
    started = time.monotonic()
    try:
        require('Stockfish 18' in engine.id.get('name', ''), 'Wrong Stockfish version')
        engine.configure({'Threads': 1, 'Hash': 64})
        for fen in job['fens']:
            row, stream = collect(engine, fen)
            row['fen'] = fen
            rows.append(row); messages.append(dict(fen=fen, messages=stream))
    finally:
        try: engine.quit()
        finally: engine.close()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(p)+'.partial')
    pd.DataFrame(rows).to_parquet(tmp, index=False, compression='zstd'); os.replace(tmp,p)
    tmp = Path(str(trace)+'.partial')
    with gzip.open(tmp, 'wt', compresslevel=3) as f: json.dump(messages, f)
    os.replace(tmp, trace)
    certify(p,key); certify(trace,key)
    return dict(path=str(p), key=key, positions=len(rows), cached=False, seconds=time.monotonic()-started)


def score_jobs(fens, root, engine, engine_sha, collector_hash):
    # Stable buckets preserve almost every existing batch if later repairs add FENs.
    # Each key binds the complete ordered FEN list and the collector, not outcomes.
    grouped = {}
    for fen in sorted(set(fens)):
        digest = hashlib.sha256(fen.encode()).hexdigest()
        grouped.setdefault(digest[:2], []).append((digest,fen))
    jobs = []
    for prefix, items in sorted(grouped.items()):
        ordered = [fen for _,fen in sorted(items)]
        for start in range(0,len(ordered),128):
            chunk = ordered[start:start+128]
            key = fingerprint([CONTRACT, engine_sha, collector_hash, chunk, 100000, 1, 64])
            jobs.append(dict(fens=chunk,key=key,out=str(root/(key+'.parquet')),
                             engine=str(engine),engine_sha=engine_sha))
    return jobs


def legacy_patch(row, new):
    out = dict(row)
    sign = 1 if row['color'] == 'white' else -1
    for source, dest in [('cp_white','cp'),('mate_white','mate')]:
        v = new[source]
        out[dest] = None if v is None or pd.isna(v) else int(sign*v)
    for key in ['nodes','depth','status','score_nodes','final_lowerbound','final_upperbound','stale_bound']:
        v = new[key]
        out[key] = None if pd.isna(v) else v.item() if hasattr(v,'item') else v
    out['score_reader_contract'] = CONTRACT
    return out


def project_unit(job):
    unit, out, key, overlay = job
    out = Path(out)
    if valid(out,key): return str(out)
    games, rows, by = read_unit(unit)
    needed = {r['fen'] for r in rows if needs_repair(r)}
    replacements = {}
    if needed:
        # Each shard holds only this unit's replacements, at most 1,500 rows.
        f = pq.ParquetFile(overlay).read().to_pandas()
        replacements = {r['fen']:r for r in f.loc[f.fen.isin(needed)].to_dict('records')}
        require(set(replacements)==needed,'Missing repair FENs; refusing partial projection')
    output = []
    for game in games:
        patched = [legacy_patch(r,replacements[r['fen']]) if needs_repair(r) else r for r in by[game['game_id']]]
        output.append(one_game(game,patched))
    out.parent.mkdir(parents=True,exist_ok=True)
    tmp = Path(str(out)+'.partial')
    pd.DataFrame(output).to_parquet(tmp,index=False,compression='zstd');os.replace(tmp,out);certify(out,key)
    return str(out)


def shard_overlays(inventory_paths, scores, root, key):
    require(not scores.fen.duplicated().any(), 'Duplicate repaired FENs')
    indexed = scores.set_index('fen',drop=False)
    available = set(indexed.index)
    paths = {}
    root.mkdir(parents=True,exist_ok=True)
    for inv in sorted(inventory_paths):
        inv = Path(inv); dest = root/inv.name
        shard_key = fingerprint([key,inv.stem,sha(inv)])
        if not valid(dest,shard_key):
            wanted = pq.ParquetFile(inv).read(columns=['fen']).column('fen').to_pylist()
            require(set(wanted)<=available,'Repair overlay incomplete')
            part = indexed.loc[wanted].reset_index(drop=True)
            temp = Path(str(dest)+'.partial')
            part.to_parquet(temp,index=False,compression='zstd');os.replace(temp,dest);certify(dest,shard_key)
        paths[inv.stem] = str(dest)
    return paths
