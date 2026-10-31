"""Read completed cache snapshots; keep conflicting records for later reconciliation."""
from __future__ import annotations
import bz2, contextlib, gzip, io as streams, json, os, shutil, subprocess, time
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
import expansion_common as c
import local_io as io

NORMALIZED_NAMES={'metadata.parquet','records.parquet','cached_metadata.parquet','baseline_metadata_json.parquet'}

def discover(project):
    roots=[]
    for parent in (project/'derived/replication',project/'raw'):
        if parent.is_dir():
            for p in sorted(parent.iterdir()):
                if p.is_dir() and not p.name.startswith('.') and any(k in p.name.lower() for k in ('api','enrichment','export','comparison_home','a1_trajectory_build')):
                    roots.append(p)
    return roots

def kind(p):
    n=p.name.lower()
    if n in NORMALIZED_NAMES:return 'parquet'
    if n.endswith(('.ndjson','.jsonl','.ndjson.gz','.jsonl.gz','.ndjson.zst','.jsonl.zst','.ndjson.bz2','.jsonl.bz2')):return 'json'
    if n.endswith(('.json','.json.gz','.json.zst','.json.bz2')) and any(k in n for k in ('raw','response','batch','export')):return 'json'
    return None

def inventory(roots):
    records=[];seen_dirs=set();seen_files=set();skipped=[]
    for root in roots:
        pending=[root]
        while pending:
            d=pending.pop();resolved=d.resolve()
            if resolved in seen_dirs:continue
            seen_dirs.add(resolved)
            for p in sorted(d.iterdir()):
                if p.name.startswith('.') or any(k in p.name.lower() for k in ('.partial','.tmp','quarantine')):continue
                if p.is_dir():
                    # Follow known cache links, with cycle and duplicate detection.
                    pending.append(p);continue
                k=kind(p)
                if k and p.is_file() and p.resolve() not in seen_files:
                    seen_files.add(p.resolve());records.append(dict(path=str(p.resolve()),kind=k,signature=io.sig(p)))
    return sorted(records,key=lambda x:x['path'])

def group_jobs(records,max_bytes=256*1024**2,max_files=512):
    groups=[];part=[];n=0
    for r in records:
        if part and (n+r['signature'][0]>max_bytes or len(part)>=max_files):groups.append(part);part=[];n=0
        part.append(r);n+=r['signature'][0]
    if part:groups.append(part)
    return groups

@contextlib.contextmanager
def decoded(path):
    path=Path(path)
    with path.open('rb') as f:magic=f.read(4)
    if magic[:2]==b'\x1f\x8b':
        with gzip.open(path,'rb') as f:yield f
    elif magic[:3]==b'BZh':
        with bz2.open(path,'rb') as f:yield f
    elif magic==b'\x28\xb5\x2f\xfd':
        try:import zstandard
        except ImportError:zstandard=None
        if zstandard:
            with path.open('rb') as f:
                with zstandard.ZstdDecompressor().stream_reader(f) as r:
                    with streams.BufferedReader(r) as b:yield b
        else:
            exe=shutil.which('zstd')
            if exe is None:
                exe=next((x for x in ['/opt/homebrew/bin/zstd','/usr/local/bin/zstd'] if Path(x).is_file()),None)
            if exe is None:raise RuntimeError('A completed cache requires zstandard or the zstd command')
            process=subprocess.Popen([exe,'-q','-d','-c',str(path)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            try:
                yield process.stdout
                if process.wait()!=0:raise RuntimeError('Zstd cache decoding failed')
            finally:
                process.stdout.close();process.stderr.close()
                if process.poll() is None:process.terminate();process.wait(timeout=10)
    else:
        with path.open('rb') as f:yield f

def games(obj):
    if isinstance(obj,list):
        for x in obj:yield from games(x)
    elif isinstance(obj,dict):
        if ('id' in obj or 'game_id' in obj) and 'players' in obj:yield obj
        else:
            for k in ('game','games','data','records','results'):
                if k in obj:yield from games(obj[k])

def objects(path):
    with decoded(path) as f:
        # Completed export files are NDJSON or a single JSON array/wrapper.
        # Large NDJSON files stream; multiline JSON fallback is bounded at 128 MiB.
        first=f.readline()
        try:o=json.loads(first)
        except (ValueError,UnicodeError):
            data=first+f.read(128*1024**2+1)
            if len(data)>128*1024**2:raise ValueError('Multiline JSON cache exceeds parser bound')
            yield from games(json.loads(data));return
        yield from games(o)
        for line in f:
            if line.strip():yield from games(json.loads(line))

def scan_group(job):
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    def build(out):
        rows=[];n=0;digests=[];failures=[];read_games=0
        writer=pq.ParquetWriter(out/'records.parquet',c.metadata_schema(),compression='zstd')
        def add(row):
            nonlocal rows,n
            if row is None or not c.new_id(row['game_id']):return
            rows.append(row);n+=1
            if len(rows)>=32768:
                writer.write_table(pa.Table.from_pylist(rows,schema=c.metadata_schema()));rows=[]
        try:
            for rec in job['inputs']:
                p=Path(rec['path'])
                if io.sig(p)!=rec['signature']:raise RuntimeError('Completed cache changed before scanning: '+str(p))
                try:
                    if rec['kind']=='parquet':
                        pf=pq.ParquetFile(p);names=set(pf.schema_arrow.names)
                        if {'game_id','metadata_json'}<=names:
                            cols=['game_id','metadata_json']
                            for b in pf.iter_batches(columns=cols,batch_size=32768,use_threads=False):
                                for r in b.to_pylist():
                                    read_games+=1
                                    if c.new_id(r['game_id']) and r['metadata_json']:
                                        obj=json.loads(r['metadata_json']);nr=c.normalize(obj)
                                        if nr and nr['game_id']!=r['game_id']:raise RuntimeError('Cache JSON/row identity conflict')
                                        add(nr)
                        elif {'game_id',*c.core.CORE_FIELDS}<=names:
                            cols=['game_id',*[x for x in c.META_FIELDS if x in names],*[x for x in ('error_codes','metadata_valid','record_errors') if x in names]]
                            for b in pf.iter_batches(columns=cols,batch_size=32768,use_threads=False):
                                for r in b.to_pylist():
                                    read_games+=1
                                    if not c.new_id(r['game_id']):continue
                                    errors=r.get('record_errors') or r.get('error_codes') or ''
                                    if r.get('metadata_valid') is False and not errors:errors='PRIOR_CACHE_FLAG'
                                    nr={f.name:r.get(f.name) for f in c.metadata_schema()};nr['record_errors']=errors;add(nr)
                        else:failures.append(dict(path=str(p),reason='unsupported_metadata_parquet_schema'))
                    else:
                        for obj in objects(p):
                            read_games+=1
                            if c.new_id(obj.get('id',obj.get('game_id'))):add(c.normalize(obj))
                except (ValueError,UnicodeError,EOFError,OSError) as error:
                    # Not used to exclude a game: incomplete cache coverage goes back to the API target ledger.
                    failures.append(dict(path=str(p),reason=type(error).__name__))
                if io.sig(p)!=rec['signature']:raise RuntimeError('Completed cache changed while scanning: '+str(p))
                digests.append(io.checked(p))
            if rows:writer.write_table(pa.Table.from_pylist(rows,schema=c.metadata_schema()))
        finally:writer.close()
        io.js(out/'sources_PRIVATE.json',digests);io.js(out/'parse_gaps_PRIVATE.json',failures)
        return dict(cache_files=len(job['inputs']),records=n,game_records_read=read_games,cache_parse_gaps=len(failures))
    path,r=io.stage(job['out'],job['conf'],build)
    # Frozen old cache files must remain unchanged on a resumed preparation.
    for rec in job['inputs']:
        if io.sig(rec['path'])!=rec['signature']:raise RuntimeError('Frozen cache snapshot changed on resume')
    return dict(path=str(path),**{k:r[k] for k in ('cache_files','records','game_records_read','cache_parse_gaps')})
