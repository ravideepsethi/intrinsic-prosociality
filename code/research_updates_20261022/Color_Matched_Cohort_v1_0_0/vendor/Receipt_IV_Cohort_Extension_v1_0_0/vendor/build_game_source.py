#!/usr/bin/env python3
"""Recover local API source for every certified Stage 07 game; never use network."""
from __future__ import annotations
import argparse
import bz2
import concurrent.futures as cf
import contextlib
import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import multiprocessing as mp
import os
from pathlib import Path
import re
import shutil
import sys
import tarfile
import tempfile
import time
import traceback
import zipfile
from collections import Counter

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import zstandard as zstd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from recovery_support import digest, qs, atomic_json, atomic_parquet, copy_query, query_dict, fingerprint, run_lock

MONTHS = [f'{i//12:04d}-{i%12+1:02d}' for i in range(2023*12+10, 2023*12+34)]
EXPECTED = {'rows':47587020, 'kind_draws':669503, 'fair_rows':17328130}
SUCCESS_SHA = '8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7'
PRODUCER_SHA = '0411d4061ea9831c20449208a9782aaf668e160139918d106a2b7d63aaa56e6e'
SOURCES = ('pool','lobby','friend','ai','api','tournament','arena','swiss','simul','position','import','importlive','hook')
RAW = ('.ndjson','.jsonl','.ndjson.gz','.jsonl.gz','.ndjson.zst','.jsonl.zst',
       '.ndjson.zstd','.jsonl.zstd','.json.gz','.json.zst','.ndjson.bz2','.jsonl.bz2')
ARCHIVES = ('.zip','.tar','.tar.gz','.tgz','.tar.bz2','.tar.xz')
ALIASES = ('game_id','id','source','api_source','status','api_status','winner','api_winner',
           'createdAt','api_created_at_ms','created_at_ms','speed','players')
SCHEMA = pa.schema([('game_id',pa.string()),('source',pa.string()),('status',pa.string()),
                    ('winner',pa.string()),('winner_present',pa.bool_()),('created_at_ms',pa.int64()),
                    ('invalid',pa.bool_()),('provenance',pa.string()),('record_number',pa.int64())])
MAX_LINE = 16*1024**2


def log(message):
    print(dt.datetime.now(dt.timezone.utc).strftime('[%H:%M:%SZ] ') + message, flush=True)


def sql_files(paths):
    return 'read_parquet([' + ','.join(qs(p) for p in paths) + '], hive_partitioning=false)'


def code_hash():
    return hashlib.sha256((digest(__file__)+digest(Path(__file__).with_name('recovery_support.py'))).encode()).hexdigest()


def normalize(obj):
    if not isinstance(obj, dict): return None
    ids = [obj[k] for k in ('game_id','id') if obj.get(k) is not None]
    if not ids or not isinstance(ids[0],str) or not re.fullmatch('[A-Za-z0-9]{8}',ids[0]): return None
    if any(x != ids[0] for x in ids): raise ValueError('Conflicting game-ID aliases in a record')
    invalid = False
    def pick(names):
        nonlocal invalid
        values = [obj[k] for k in names if obj.get(k) is not None]
        if values and any(x != values[0] for x in values): invalid = True
        return values[0] if values else None
    source = pick(('source','api_source'))
    status = pick(('status','api_status'))
    winner = pick(('winner','api_winner'))
    created = pick(('createdAt','api_created_at_ms','created_at_ms'))
    for value in (source,status):
        if value is not None and (not isinstance(value,str) or not value or value.strip()!=value): invalid = True
    if winner is not None and winner not in ('white','black'): invalid = True
    if created is not None and (type(created) is not int or not 1262304000000 <= created < 4102444800000):
        created = None
        invalid = True
    return {'game_id':ids[0], 'source':source if isinstance(source,str) and source else None,
            'status':status if isinstance(status,str) else None,
            'winner':winner if winner in ('white','black') else None,
            'winner_present':any(k in obj for k in ('winner','api_winner')),
            'created_at_ms':created,'invalid':invalid}


def stream_lines(stream, name):
    """Bounded line buffer with explicit Zstandard frame completion checks."""
    low = name.lower()
    decoder, frames, tail = None, 0, b''
    compression = low.endswith(('.zst','.zstd'))
    binary = gzip.GzipFile(fileobj=stream) if low.endswith('.gz') else bz2.BZ2File(stream) if low.endswith('.bz2') else stream
    try:
        while True:
            block = binary.read(65536)
            if not block: break
            while block:
                if compression:
                    if decoder is None: decoder = zstd.ZstdDecompressor().decompressobj()
                    data = decoder.decompress(block)
                    if decoder.eof:
                        frames += 1
                        block = decoder.unused_data
                        decoder = None
                    else: block = b''
                else: data, block = block, b''
                parts = (tail+data).split(b'\n'); tail = parts.pop()
                if len(tail)>MAX_LINE: raise ValueError('Raw line exceeds 16 MiB')
                for line in parts:
                    if len(line)>MAX_LINE: raise ValueError('Raw line exceeds 16 MiB')
                    yield line
        if compression and (decoder is not None or frames==0): raise ValueError('Incomplete Zstandard stream')
        if tail: yield tail
    finally:
        if binary is not stream: binary.close()


def excluded(name):
    low = name.lower()
    return (name.startswith('.') or any(x in low for x in ('quarantine','.partial','.tmp','selftest','smoke',
            'rating_shock','rating_redesign','game_source_24m','source_recovery_24m','chooser_leniency_t0'))
            or low.endswith('_private'))


def kind(name):
    low = name.lower()
    if low.endswith(ARCHIVES): return 'archive'
    if low.endswith(RAW): return 'raw'
    if low.endswith('.parquet'): return 'parquet'
    return None


def has_source_schema(p):
    names = pq.ParquetFile(p).schema_arrow.names
    return bool(set(names)&{'game_id','id'} and set(names)&{'source','api_source'})


def discover(roots, run, cap=3000000):
    jobs, skipped, errors, seen = [], [], [], set()
    visited = 0; last = time.monotonic()
    relevance = re.compile('api|enrich|lookup|stage0?4|responses|export', re.I)
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            skipped.append({'path':str(root),'reason':'root_absent'}); continue
        log('SEARCH '+str(root))
        def onerror(exc): errors.append({'path':getattr(exc,'filename',str(root)),'error':str(exc)})
        for here, dirs, names in os.walk(root, followlinks=False, onerror=onerror):
            dirs[:] = [d for d in dirs if not excluded(d) and not (Path(here)/d).is_symlink()]
            for name in names:
                visited += 1
                if visited > cap: raise RuntimeError('Inventory limit reached; no complete layer can be certified')
                if excluded(name): continue
                p=Path(here)/name
                k=kind(name)
                if not k or not relevance.search(str(p)): continue
                try:
                    if p.is_symlink():
                        skipped.append({'path':str(p),'reason':'symlink'});continue
                    st=p.stat(); inode=(st.st_dev,st.st_ino)
                    if inode in seen: continue
                    seen.add(inode)
                    sig=fingerprint(p)
                    if time.time()-st.st_mtime<120:
                        skipped.append({'path':str(p),'reason':'recently_modified'});continue
                    if k=='parquet' and not has_source_schema(p): continue
                    jobs.append({'path':str(p),'kind':k,**sig,'file_id':hashlib.sha256(str(p).encode()).hexdigest()[:24]})
                except Exception as exc: errors.append({'path':str(p),'error':str(exc)})
            if time.monotonic()-last>30:
                log(f'DISCOVERY files_seen={visited:,} candidates={len(jobs):,}');last=time.monotonic()
    jobs.sort(key=lambda j:j['path'])
    if len({j['file_id'] for j in jobs}) != len(jobs): raise RuntimeError('Duplicate input file identity')
    inventory={'roots':[str(r) for r in roots],'jobs':jobs,'skipped':skipped,'errors':errors,'files_seen':visited}
    atomic_json(run/'INPUT_INVENTORY.json',inventory)
    # The user's existing T0 private manifest can establish discovery overlap.
    return inventory


def init_worker(target_path):
    global TARGETS
    TARGETS=np.load(target_path,mmap_mode='r')
    pa.set_cpu_count(1);pa.set_io_thread_count(1)


def scan(job, directory, binding, strict=False):
    p=Path(job['path']);directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    out=directory/(job['file_id']+'.parquet'); receipt=out.with_suffix('.json')
    sig={k:job[k] for k in ('size_bytes','mtime_ns')}
    if fingerprint(p)!=sig: raise ValueError('Input changed since discovery')
    if receipt.exists():
        r=json.loads(receipt.read_text())
        if r['binding']!=binding or r['input']!=job or not out.exists() or digest(out)!=r['output_sha256']:
            raise ValueError('Checkpoint mismatch; preserve this run and start a fresh one')
        if strict and digest(p)!=r['input_sha256']: raise ValueError('Input hash changed')
        return r
    # Full physical-file hash also covers container metadata and every member.
    raw_hash=digest(p)
    temp=out.with_name(out.name+'.partial')
    counts=Counter(); buffer=[]; source_counts=Counter()
    with pq.ParquetWriter(temp,SCHEMA,compression='zstd') as writer:
        def flush():
            if not buffer: return
            gids=np.asarray([x['game_id'] for x in buffer],dtype='S8')
            pos=np.searchsorted(TARGETS,gids)
            safe=np.minimum(pos,max(0,len(TARGETS)-1))
            keep=(pos<len(TARGETS))&(TARGETS[safe]==gids)
            selected=[r for r,k in zip(buffer,keep) if k]
            counts['matched_rows']+=len(selected)
            if selected: writer.write_table(pa.Table.from_pylist(selected,schema=SCHEMA))
            buffer.clear()
        def accept(obj, member, number):
            counts['records_read']+=1
            row=normalize(obj)
            if row is None:
                counts['non_game_records']+=1;return
            counts['game_records']+=1
            if row['source'] is not None: source_counts[row['source']]+=1
            row['provenance']=job['file_id']+'::'+member+'::'+('source' if 'source' in obj else 'api_source')
            row['record_number']=number
            buffer.append(row)
            if len(buffer)>=32768:flush()
        def read_raw(stream,name):
            for number,line in enumerate(stream_lines(stream,name),1):
                if not line.strip():continue
                try: obj=json.loads(line)
                except (ValueError,UnicodeError): counts['malformed_lines']+=1;continue
                for row in obj if isinstance(obj,list) else [obj]: accept(row,name,number)
        def read_parquet(path,name):
            pf=pq.ParquetFile(path)
            names=pf.schema_arrow.names
            if not (set(names)&{'id','game_id'} and set(names)&{'source','api_source'}):
                counts['parquet_without_source']+=1;return
            # Nested fields never supply source; read only explicit top-level aliases.
            cols=[k for k in ALIASES if k in names and k not in ('players','speed')]
            number=0
            for batch in pf.iter_batches(columns=cols,batch_size=32768,use_threads=False):
                for obj in batch.to_pylist():
                    number+=1;accept(obj,name,number)
        def member_read(stream,name):
            if kind(name)=='raw':read_raw(stream,name);counts['raw_members']+=1
            elif kind(name)=='parquet':
                # Seekable temporary copy supports both ZIP and compressed TAR.
                with tempfile.TemporaryFile(dir=directory) as spool:
                    shutil.copyfileobj(stream,spool,1024**2);spool.seek(0)
                    read_parquet(spool,name)
                counts['parquet_members']+=1
        if job['kind']=='raw':
            with p.open('rb') as f:read_raw(f,p.name)
        elif job['kind']=='parquet':read_parquet(p,p.name)
        elif str(p).lower().endswith('.zip'):
            with zipfile.ZipFile(p) as z:
                for member in z.infolist():
                    if member.is_dir() or any(excluded(x) for x in Path(member.filename).parts):continue
                    if kind(member.filename) in ('raw','parquet'):
                        with z.open(member) as f:member_read(f,member.filename)
                    elif kind(member.filename)=='archive':counts['nested_archives_unopened']+=1
        else:
            with tarfile.open(p,'r|*') as tar:
                for member in tar:
                    if not member.isfile() or any(excluded(x) for x in Path(member.name).parts):continue
                    if kind(member.name) in ('raw','parquet'):
                        with tar.extractfile(member) as f:member_read(f,member.name)
                    elif kind(member.name)=='archive':counts['nested_archives_unopened']+=1
        flush()
    if fingerprint(p)!=sig:raise ValueError('Input changed while reading')
    os.replace(temp,out)
    r={'input':job,'input_sha256':raw_hash,'binding':binding,'output_sha256':digest(out),
       'output':str(out),'counts':dict(counts),'source_record_counts':dict(source_counts)}
    atomic_json(receipt,r);return r


def authenticate(project,run,workers):
    stage=project/'derived/replication/analysis_panel_24m_sf100k'
    success=stage/'_SUCCESS.json'
    if digest(success)!=SUCCESS_SHA: raise ValueError('Stage 07 certificate hash mismatch')
    cert=json.loads(success.read_text())
    if cert.get('status')!='STAGE07_24M_CERTIFIED_OK' or cert.get('script_sha256')!=PRODUCER_SHA:
        raise ValueError('Stage 07 authority differs from T0')
    if {k:int(cert.get('global_qa',{}).get(k,-1)) for k in EXPECTED}!=EXPECTED:raise ValueError('Certified totals mismatch')
    paths=[stage/f'month={m}/analysis_panel.parquet' for m in MONTHS]
    listed=[Path(x) for x in (stage/'_manifests/analysis_panel_paths.txt').read_text().splitlines() if x.strip()]
    if paths!=listed:raise ValueError('Stage 07 path manifest mismatch')
    with (stage/'_manifests/month_status.csv').open() as f: manifest=list(csv.DictReader(f))
    if [r['month'] for r in manifest]!=MONTHS:raise ValueError('Stage 07 month manifest mismatch')
    def check(pair):
        p,row=pair;before=fingerprint(p)
        if before['size_bytes']!=int(row['output_size_bytes']):raise ValueError('Panel size mismatch '+row['month'])
        sha=digest(p)
        if sha!=row['output_sha256'] or fingerprint(p)!=before:raise ValueError('Panel hash mismatch '+row['month'])
        log('STAGE07_SHA_OK '+row['month'])
        return {'month':row['month'],'path':str(p),'sha256':sha,**before}
    with cf.ThreadPoolExecutor(max_workers=min(4,workers)) as ex: receipts=list(ex.map(check,zip(paths,manifest)))
    atomic_json(run/'PANEL_AUTHORITIES.json',receipts)
    return paths


def build_targets(con,paths,run,expected,months):
    target=run/'targets_private.parquet'
    sorted_ids=run/'target_ids_sorted.npy'
    receipt=run/'TARGET_RECEIPT.json'
    binding={'code':code_hash(),'expected':expected,'months':months,
             'inputs':[{'path':str(p),**fingerprint(p)} for p in paths]}
    if receipt.exists():
        saved=json.loads(receipt.read_text())
        if saved['binding']!=binding or digest(target)!=saved['target_sha256'] or digest(sorted_ids)!=saved['index_sha256']:
            raise ValueError('Target checkpoint mismatch; start a fresh run')
        return saved['qa'],target,sorted_ids
    view=sql_files(paths)
    fields='game_id,month,api_status,api_winner,api_created_at_ms,outcome_kind_draw,engine_eval_cp_disconnected'
    copy_query(con,f'SELECT {fields} FROM {view}',target)
    con.execute(f'CREATE OR REPLACE TEMP VIEW targets AS SELECT * FROM {sql_files([target])}')
    qa=query_dict(con,"""SELECT count(*) AS rows, count(DISTINCT game_id) AS distinct_ids,
        count(*) FILTER(WHERE outcome_kind_draw) AS kind_draws,
        count(*) FILTER(WHERE engine_eval_cp_disconnected>=-100) AS fair_rows,
        count(*) FILTER(WHERE game_id IS NULL OR NOT regexp_full_match(game_id,'[A-Za-z0-9]{8}')
          OR month IS NULL OR api_status IS DISTINCT FROM 'timeout'
          OR outcome_kind_draw IS NULL OR engine_eval_cp_disconnected IS NULL) AS bad_rows FROM targets""")[0]
    actual_months=[r[0] for r in con.execute('SELECT DISTINCT month FROM targets ORDER BY month').fetchall()]
    if {k:qa[k] for k in expected}!=expected or qa['distinct_ids']!=qa['rows'] or qa['bad_rows'] or actual_months!=months:
        raise ValueError('Full-panel target identity/count/field gate failed: '+json.dumps(qa))
    # Eight bytes per ID (~381 MB for the production panel), shared read-only via mmap.
    temp=sorted_ids.with_name(sorted_ids.name+'.partial')
    arr=np.lib.format.open_memmap(temp,mode='w+',dtype='S8',shape=(qa['rows'],))
    cursor=0
    reader=con.execute('SELECT game_id FROM targets ORDER BY game_id').fetch_record_batch(131072)
    for batch in reader:
        values=np.asarray(batch.column(0).to_pylist(),dtype='S8')
        arr[cursor:cursor+len(values)]=values;cursor+=len(values)
    arr.flush();del arr
    os.replace(temp,sorted_ids)
    atomic_json(receipt,{'binding':binding,'qa':qa,'target_sha256':digest(target),'index_sha256':digest(sorted_ids)})
    return qa,target,sorted_ids


def reduce_all(con,target,receipts,run,months,expected):
    paths=[r['output'] for r in receipts]
    if not paths:
        empty=run/'empty_evidence.parquet';atomic_parquet(empty,pa.Table.from_pylist([],schema=SCHEMA));paths=[empty]
    con.execute(f'CREATE OR REPLACE TEMP VIEW evidence AS SELECT * FROM {sql_files(paths)}')
    con.execute(f'CREATE OR REPLACE TEMP VIEW targets AS SELECT * FROM {sql_files([target])}')
    reduced=run/'source_candidates_private.parquet'
    copy_query(con,"""SELECT game_id,count(*) AS evidence_rows,count(DISTINCT source) AS distinct_sources,
        min(source) AS candidate_source, bool_or(invalid) AS invalid,
        bool_or(status IS NOT NULL AND status<>'timeout') AS status_bad,
        count(DISTINCT winner) FILTER(WHERE winner_present) + max(CASE WHEN winner_present AND winner IS NULL THEN 1 ELSE 0 END) AS winner_values,
        bool_or(winner_present) AS winner_observed,min(winner) AS raw_winner,
        count(DISTINCT created_at_ms) AS time_values,min(created_at_ms) AS created_at_ms,
        min(provenance) FILTER(WHERE source IS NOT NULL) AS source_provenance
        FROM evidence GROUP BY game_id""",reduced)
    con.execute(f'CREATE OR REPLACE TEMP VIEW recovered AS SELECT * FROM {sql_files([reduced])}')
    final=run/'source_by_game_id_24m.parquet'
    allowed=','.join(qs(x) for x in SOURCES)
    copy_query(con,f"""WITH joined AS (
        SELECT t.game_id,t.month,r.candidate_source,r.source_provenance,
          coalesce(r.evidence_rows,0) AS evidence_rows,coalesce(r.distinct_sources,0) AS distinct_sources,
          CASE WHEN r.distinct_sources>1 THEN 'conflict'
               WHEN coalesce(r.invalid,false) THEN 'invalid_record'
               WHEN r.distinct_sources IS NULL OR r.distinct_sources=0 THEN 'missing'
               WHEN r.candidate_source NOT IN ({allowed}) THEN 'unrecognized'
               WHEN r.status_bad OR r.winner_values>1 OR r.time_values>1
                 OR (r.winner_observed AND r.raw_winner IS DISTINCT FROM t.api_winner)
                 OR (r.created_at_ms IS NOT NULL AND t.api_created_at_ms IS NOT NULL AND r.created_at_ms<>t.api_created_at_ms)
                 THEN 'inconsistent_metadata' ELSE 'recovered' END AS source_status
        FROM targets t LEFT JOIN recovered r USING(game_id))
        SELECT game_id,month,CASE WHEN source_status='recovered' THEN candidate_source END AS source,
          CASE WHEN source_status='recovered' THEN source_provenance END AS source_provenance,
          source_status,evidence_rows,distinct_sources FROM joined""",final)
    con.execute(f'CREATE OR REPLACE TEMP VIEW final_source AS SELECT * FROM {sql_files([final])}')
    qa=query_dict(con,'SELECT count(*) AS rows,count(DISTINCT game_id) AS distinct_ids FROM final_source')[0]
    if qa['rows']!=expected['rows'] or qa['distinct_ids']!=qa['rows']:raise ValueError('Final identity check failed')
    coverage=query_dict(con,"""SELECT month,count(*) AS opportunities,
        count(*) FILTER(WHERE source_status='recovered') AS recovered,
        count(*) FILTER(WHERE source='pool') AS pool,
        count(*) FILTER(WHERE source_status='missing') AS missing,
        count(*) FILTER(WHERE source_status='conflict') AS conflicts,
        count(*) FILTER(WHERE source_status NOT IN ('missing','conflict','recovered')) AS other_unresolved
        FROM final_source GROUP BY month ORDER BY month""")
    if [r['month'] for r in coverage]!=months:raise ValueError('Final monthly coverage check failed')
    residual=run/'unresolved_game_ids_24m.parquet'
    copy_query(con,"SELECT * FROM final_source WHERE source_status<>'recovered'",residual)
    counts=query_dict(con,'SELECT month,source,source_status,count(*) AS games FROM final_source GROUP BY ALL ORDER BY month,source_status,source')
    return coverage,counts,[final,residual,reduced]


def package_report(run,report):
    directory=run/'report';directory.mkdir(exist_ok=True)
    atomic_json(directory/'SUMMARY.json',report)
    included=[directory/'SUMMARY.json']
    for key,name in [('coverage','MONTH_COVERAGE.parquet'),('source_counts','SOURCE_COUNTS.parquet')]:
        if report.get(key):
            atomic_parquet(directory/name,pa.Table.from_pylist(report[key]));included.append(directory/name)
    manifest=directory/'REPORT_MANIFEST.sha256'
    manifest.write_text(''.join(digest(p)+'  '+p.name+'\n' for p in included))
    archive=run/('Game_Source_24M_Report_'+run.name+'.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in included+[manifest]:z.write(p,arcname=run.name+'/'+p.name)
    sidecar=archive.with_name(archive.name+'.sha256');sidecar.write_text(digest(archive)+'  '+archive.name+'\n')
    log(report['status'])
    print('UPLOAD: '+str(archive),flush=True);print('UPLOAD: '+str(sidecar),flush=True)


def default_roots(project,home,desktop):
    roots=[project/'derived/replication/api_timeout_enrichment',project/'output',home/'projects/lichess_kindness/output',
           home/'lichess_stage04_home_output',desktop]
    derived=project/'derived/replication'
    if derived.is_dir():
        roots.extend(p for p in derived.iterdir() if p.is_dir() and re.search('api.*enrich|enrich.*api|stage0?4',p.name,re.I))
    return list(dict.fromkeys(roots))


def pipeline(project,roots,run,workers=8,threads=8,memory='10GB',strict=False,fixture=None):
    started=time.monotonic();run.mkdir(parents=True,exist_ok=True)
    report={'status':'GAME_SOURCE_24M_BLOCKED','version':'1.0.0','errors':[],'coverage':[],
            'API_requests':0,'empirical_reestimation':'NOT_RUN','roots':[str(r) for r in roots],
            'code_sha256':code_hash(),'settings':{'workers':workers,'threads':threads,'memory':memory},
            'environment':{'python':sys.version,'pyarrow':pa.__version__,'numpy':np.__version__,
                           'duckdb':duckdb.__version__,'zstandard':zstd.__version__}}
    con=None
    try:
        months=fixture['months'] if fixture else MONTHS
        expected=fixture['expected'] if fixture else EXPECTED
        report['months']=months;report['expected_baseline']=expected
        paths=fixture['paths'] if fixture else authenticate(project,run,workers)
        con=duckdb.connect()
        con.execute(f'SET threads={int(threads)}');con.execute(f'SET memory_limit={qs(memory)}')
        spill=run/'spill';spill.mkdir(exist_ok=True)
        con.execute(f'SET temp_directory={qs(spill)}');con.execute('SET preserve_insertion_order=false')
        log('BUILDING_FULL_PANEL_TARGET_INDEX')
        qa,target,index=build_targets(con,paths,run,expected,months);report['baseline_verified']=qa
        con.close();con=None
        index_hash=digest(index)
        inventory=discover(roots,run)
        report['discovery']={k:v for k,v in inventory.items() if k!='jobs'}
        report['input_files']=len(inventory['jobs'])
        contract={'code_sha256':code_hash(),'target_sha256':digest(target),'target_index_sha256':index_hash,
                  'roots':[str(r) for r in roots],'jobs':inventory['jobs']}
        old=run/'RUN_CONTRACT.json'
        if old.exists() and json.loads(old.read_text())!=contract:raise ValueError('Run inputs or code changed; start a fresh run')
        atomic_json(old,contract)
        binding={k:contract[k] for k in ('code_sha256','target_sha256','target_index_sha256')}
        results=[];jobs=inventory['jobs']
        total=sum(j['size_bytes'] for j in jobs)
        log(f'SOURCE_SCAN_BEGIN files={len(jobs):,} physical_GiB={total/1024**3:.2f} workers={workers}')
        # OS-shared readonly ID mmap avoids one enormous Python ID set per worker.
        with cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn'),
                                    initializer=init_worker,initargs=(str(index),)) as pool:
            pending={pool.submit(scan,j,run/'evidence',binding,strict):j for j in jobs}
            completed=0
            while pending:
                done,_=cf.wait(pending,timeout=30,return_when=cf.FIRST_COMPLETED)
                if not done:log(f'SCAN_ACTIVE files={completed}/{len(jobs)} elapsed_min={(time.monotonic()-started)/60:.1f}')
                for future in done:
                    job=pending.pop(future);completed+=1
                    try:results.append(future.result())
                    except Exception as exc:report['errors'].append({'file_id':job['file_id'],'path':job['path'],'error':str(exc)})
                    if completed%100==0 or completed==len(jobs):log(f'SCAN_PROGRESS files={completed}/{len(jobs)} errors={len(report["errors"])}')
        atomic_json(run/'SCAN_RECEIPTS.json',results)
        totals=Counter()
        for r in results:totals.update(r['counts'])
        report['scan_totals']=dict(totals);report['completed_input_files']=len(results)
        report['input_content_hashes']=[{'file_id':r['input']['file_id'],'sha256':r['input_sha256']} for r in results]
        con=duckdb.connect();con.execute(f'SET threads={int(threads)}');con.execute(f'SET memory_limit={qs(memory)}')
        con.execute(f'SET temp_directory={qs(spill)}');con.execute('SET preserve_insertion_order=false')
        log('DEDUPLICATING_AND_WRITING_FULL_24M_SOURCE_LAYER')
        coverage,counts,outputs=reduce_all(con,target,results,run,months,expected)
        report['coverage']=coverage;report['source_counts']=counts
        report['unresolved_games']=sum(r['opportunities']-r['recovered'] for r in coverage)
        report['outputs']=[{'path':str(p),'sha256':digest(p),'rows':pq.ParquetFile(p).metadata.num_rows} for p in outputs]
        issues=(report['errors'] or inventory['errors'] or any(x['reason']!='root_absent' for x in inventory['skipped'])
                or totals['malformed_lines'] or totals['nested_archives_unopened'])
        report['status']='GAME_SOURCE_24M_COMPLETE' if not report['unresolved_games'] and not issues else 'GAME_SOURCE_24M_PARTIAL'
        log(f'ALL_TARGET_ROWS={expected["rows"]:,}; UNRESOLVED={report["unresolved_games"]:,}')
        log('SOURCE TABLE: '+str(outputs[0]))
        log('RESIDUAL IDS: '+str(outputs[1]))
    except Exception as exc:
        report['status']='GAME_SOURCE_24M_BLOCKED'
        report['errors'].append({'phase':'pipeline','error':str(exc),'traceback':traceback.format_exc()})
        log('BLOCKED: '+str(exc))
    finally:
        if con is not None:con.close()
    report['elapsed_seconds']=time.monotonic()-started
    atomic_json(run/'RUN_STATUS.json',report)
    package_report(run,report)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--desktop-root',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--extra-root',type=Path,action='append',default=[])
    p.add_argument('--workers',type=int,default=8);p.add_argument('--threads',type=int,default=8)
    p.add_argument('--memory',default='10GB');p.add_argument('--resume',type=Path)
    p.add_argument('--verify-resume-input-sha256',action='store_true')
    args=p.parse_args()
    if not 1<=args.workers<=10 or not 1<=args.threads<=10:p.error('Use 1–10 workers/threads')
    if not re.fullmatch('[1-9][0-9]*(MB|GB)',args.memory):p.error('Use a memory limit such as 10GB')
    project=args.project_root.expanduser().resolve()
    if not project.is_dir():p.error('Project volume is not mounted')
    base=project/'derived/replication/game_source_24m_PRIVATE'
    base.mkdir(parents=True,exist_ok=True)
    if args.resume:
        run=args.resume.expanduser().resolve()
        if run.parent!=base or not (run/'RUN_CONTRACT.json').exists():p.error('Resume must name an existing owned run')
    else:
        run=base/(dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+str(os.getpid()))
        run.mkdir(exist_ok=False)
    roots=default_roots(project,Path.home(),args.desktop_root.expanduser().resolve())
    roots+= [x.expanduser().resolve() for x in args.extra_root]
    log('RUN DIRECTORY: '+str(run))
    with run_lock(run):
        atomic_json(run/'INVOCATION.json',{'argv':sys.argv,'python':sys.executable,'cwd':str(Path.cwd())})
        result=pipeline(project,roots,run,args.workers,args.threads,args.memory,args.verify_resume_input_sha256)
    return {'GAME_SOURCE_24M_COMPLETE':0,'GAME_SOURCE_24M_PARTIAL':2,'GAME_SOURCE_24M_BLOCKED':1}[result['status']]


if __name__=='__main__':raise SystemExit(main())
