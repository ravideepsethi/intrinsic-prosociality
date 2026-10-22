"""Broader, field-wise cache reuse; unknown provenance and conflicting values stay unresolved."""
from local_contract import *
import concurrent.futures as cf
import gzip, json, hashlib, sqlite3, datetime as dt, re, os, contextlib
import cache_scan as oldcache

ALIASES={
 'source':('source','api_source'), 'status':('status','api_status'),
 'api_start_ms':('api_start_ms','api_created_at_ms','createdAt','created_at_ms'),
 'anchor_ms':('anchor_ms','api_last_move_at_ms','lastMoveAt'),
 'rated':('rated','api_rated'), 'variant':('variant','api_variant'), 'speed':('speed','api_speed'),
 'winner':('winner','api_winner'), 'tc_base_s':('tc_base_s',), 'tc_inc_s':('tc_inc_s',),
 'white_username':('white_username',), 'black_username':('black_username',),
 'white_rating':('white_rating',), 'black_rating':('black_rating',),
 'white_provisional':('white_provisional',), 'black_provisional':('black_provisional',)}
FLAGS=('record_errors','error_codes','metadata_valid','cached_conflict_or_prior_flag','source_conflict','invalid')
PGN_FIELDS=('Site','White','Black','WhiteElo','BlackElo','TimeControl','Event','Variant')

def adapter(names):
    n=set(names)
    if {'game_id','metadata_json'}<=n:return 'api_json_column'
    if 'players' in n and 'createdAt' in n and n&{'id','game_id'}:return 'api_export_columns'
    if {'game_id',*core.CORE_FIELDS}<=n:return 'normalized_api'
    if n&{'id','game_id'} and 'api_source' in n:return 'explicit_api_aliases'
    # Exact output contract of the reviewed build_game_source.py producer.
    if {'game_id','source','status','created_at_ms','invalid','provenance','record_number'}<=n:return 'source_evidence'
    # Literal PGN tags are unambiguous. Generic result_code is NEVER decoded.
    if {'Site','White','Black','WhiteElo','BlackElo','TimeControl'}<=n:return 'literal_pgn_headers'
    return None

def normalized_flat(obj, mode):
    ids=[obj[k] for k in ('game_id','id') if obj.get(k) is not None]
    if not ids or not isinstance(ids[0],str) or core.GID.fullmatch(ids[0]) is None:return None
    errors=[]
    if len(set(ids))!=1:errors.append('GAME_ID_ALIAS_CONFLICT')
    out=dict(game_id=ids[0])
    for name,aliases in ALIASES.items():
        values=[obj[k] for k in aliases if obj.get(k) is not None]
        if any(v!=values[0] for v in values):errors.append('CONFLICT_'+name.upper());out[name]=None;continue
        value=values[0] if values else None
        typ=ex.metadata_schema().field(name).type
        if value is not None:
            if pa.types.is_string(typ):
                if isinstance(value,str):
                    value=value.strip().lower()
                else:errors.append('INVALID_'+name.upper());value=None
            elif pa.types.is_boolean(typ):
                if type(value) is not bool:errors.append('INVALID_'+name.upper());value=None
            elif pa.types.is_integer(typ):
                if type(value) is not int:errors.append('INVALID_'+name.upper());value=None
            elif pa.types.is_floating(typ):
                if type(value) not in (int,float) or not np.isfinite(value) or value<=0:errors.append('INVALID_'+name.upper());value=None
        out[name]=value
    for k in ('record_errors','error_codes'):
        value=obj.get(k)
        if value:
            if isinstance(value,str):errors.extend(value.split(';'))
            else:errors.append('PRIOR_RECORD_FLAG')
    if obj.get('metadata_valid') is False or any(obj.get(k) is True for k in ('cached_conflict_or_prior_flag','source_conflict','invalid')):
        errors.append('PRIOR_RECORD_FLAG')
    out['record_errors']=';'.join(sorted(set(errors)))
    return out

def pgn_headers(obj):
    site=obj.get('Site');match=re.fullmatch(r'https?://lichess\.org/([A-Za-z0-9]{8})',site or '')
    if not match:return None
    row=dict(game_id=match[1],record_errors='');errors=[]
    for side in ('White','Black'):
        value=obj.get(side)
        row[side.lower()+'_username']=value.strip().lower() if isinstance(value,str) and value.strip() else None
        elo=obj.get(side+'Elo')
        if elo is not None:
            try:
                elo=float(elo)
                if not np.isfinite(elo) or elo<=0:elo=None
            except (ValueError,TypeError):elo=None
        row[side.lower()+'_rating']=elo
    tc=obj.get('TimeControl');m=re.fullmatch(r'(\d+)\+(\d+)',tc or '')
    row['tc_base_s']=int(m[1]) if m else None;row['tc_inc_s']=int(m[2]) if m else None
    # No API source, exact API timestamps, or API ending is manufactured from PGN.
    event=obj.get('Event','');row['rated']=True if isinstance(event,str) and event.startswith('Rated ') else None
    var=obj.get('Variant');row['variant']='standard' if var=='Standard' else None
    return row

def normalize_row(obj,mode):
    if mode=='literal_pgn_headers':return pgn_headers(obj)
    if mode=='api_json_column':
        text=obj.get('metadata_json')
        if not isinstance(text,str) or not text.strip():return None
        value=json.loads(text)
        if not isinstance(value,dict):raise ValueError('API JSON column is not an object')
        row=ex.normalize(value)
        if row and row['game_id']!=obj.get('game_id'):raise ValueError('API JSON/row identity conflict')
        return row
    if mode in ('api_export_columns','raw_api'):return ex.normalize(obj)
    return normalized_flat(obj,mode)

def parquet_columns(names,mode):
    if mode=='api_json_column':return ['game_id','metadata_json']
    if mode=='literal_pgn_headers':return [k for k in PGN_FIELDS if k in names]
    if mode=='api_export_columns':return [k for k in ('id','game_id','source','api_source','status','createdAt','lastMoveAt','rated','variant','speed','winner','clock','players') if k in names]
    wanted={'id','game_id',*FLAGS,*(v for aliases in ALIASES.values() for v in aliases)}
    return [k for k in names if k in wanted]

def skip_name(name):
    low=name.lower()
    return (name.startswith('.') or name in ('venv','node_modules','__pycache__','tests','test','fixtures','vendor')
            or any(s in low for s in ('.partial','.tmp','quarantine','selftest','smoke','rating_redesign','rating_shock')))

def inspect_file(rec):
    p=Path(rec['path'])
    try:
        if rec['kind']=='parquet':
            pf=pq.ParquetFile(p);names=pf.schema_arrow.names;mode=adapter(names)
            return dict(rec,adapter=mode,columns=parquet_columns(names,mode) if mode else [],
                        rows=pf.metadata.num_rows,reason=None if mode else 'NO_VERIFIED_METADATA_ADAPTER')
        return dict(rec,adapter='raw_api',columns=[])
    except Exception as exc:return dict(rec,adapter=None,reason='UNREADABLE_'+type(exc).__name__)

def discover(project,desktop,output,prior_inventory,workers,extra_roots=()):
    roots=[project/'raw',project/'derived',project/'output',desktop]+list(extra_roots)
    old={str(Path(r['path']).resolve()):r['signature'] for r in io.load(prior_inventory)}
    force=set()
    for p in (prep_root(project)/'cache_scan').glob('*/parse_gaps_PRIVATE.json'):
        for r in io.load(p):force.add(str(Path(r['path']).resolve()))
    excluded=[output.resolve(),prep_root(project).resolve(),old_download(desktop).resolve(),ROOT.resolve()]
    found=[];audit=[];seen_dirs=set();seen_files=set();reused=0;visited=0
    for start in roots:
        if not start.exists():audit.append(dict(path=str(start),reason='ROOT_ABSENT'));continue
        pending=[start]
        while pending:
            directory=pending.pop();resolved=directory.resolve()
            if resolved in seen_dirs or any(resolved==p or p in resolved.parents for p in excluded):continue
            seen_dirs.add(resolved)
            try:
                # A staged code package can contain synthetic game fixtures; never ingest them.
                if (directory/'PACKAGE_MANIFEST.sha256').is_file():continue
                items=list(directory.iterdir())
            except OSError as exc:audit.append(dict(path=str(directory),reason=type(exc).__name__));continue
            for p in items:
                if skip_name(p.name):continue
                if p.is_dir():pending.append(p);continue
                if not p.is_file():continue
                visited+=1
                if visited>3000000:raise RuntimeError('Inventory exceeded 3 million files; narrow --extra-cache-root rather than silently truncate')
                key=str(p.resolve());st=p.stat();inode=(st.st_dev,st.st_ino)
                if inode in seen_files:continue
                seen_files.add(inode)
                if old.get(key)==io.sig(p) and key not in force:reused+=1;continue
                low=p.name.lower();kind=None
                if low.endswith('.parquet'):kind='parquet'
                elif low.endswith(('.ndjson','.jsonl','.ndjson.gz','.jsonl.gz','.ndjson.zst','.jsonl.zst','.jsonl.bz2','.ndjson.bz2')):kind='raw'
                elif low.endswith(('.json','.json.gz','.json.zst','.json.bz2')) and any(k in low for k in ('raw','response','batch','export')):kind='raw'
                elif low.endswith(('.sqlite','.sqlite3','.db')):
                    audit.append(dict(path=key,reason='UNSUPPORTED_SQLITE_SCHEMA_NOT_USED'));continue
                elif low.endswith(('.pgn','.pgn.zst','.pgn.gz')):
                    audit.append(dict(path=key,reason='RAW_PGN_NOT_REPARSED_PRESERVED_PARQUETS_USED'));continue
                elif low.endswith(('.zip','.tar','.tar.gz','.tar.zst')):
                    audit.append(dict(path=key,reason='ARCHIVE_NOT_UNPACKED'));continue
                if kind:
                    if time.time()-st.st_mtime<120:
                        audit.append(dict(path=key,reason='RECENTLY_WRITTEN_NOT_SNAPSHOTTED'));continue
                    found.append(dict(path=key,kind=kind,signature=io.sig(p)))
    with io.heartbeat('Reading additional cache schemas'),cf.ThreadPoolExecutor(max_workers=workers) as pool:
        inspected=list(pool.map(inspect_file,sorted(found,key=lambda r:r['path'])))
    accepted=[r for r in inspected if r.get('adapter')]
    audit.extend(dict(path=r['path'],reason=r['reason']) for r in inspected if not r.get('adapter'))
    return dict(roots=list(map(str,roots)),files=accepted,unconsumed=audit,files_enumerated=visited,
                unchanged_original_cache_files_reused=reused,parquet_schemas_checked=sum(r['kind']=='parquet' for r in inspected))

def scan_group(job):
    threads_one()
    def build(tmp):
        index=np.load(job['index'],mmap_mode='r',allow_pickle=False);rows=[];read=matched=0;failures=[];inputs=[]
        writer=pq.ParquetWriter(tmp/'metadata.parquet',ex.metadata_schema(),compression='zstd')
        try:
            for rec in job['files']:
                if io.sig(rec['path'])!=rec['signature']:raise RuntimeError('Cache changed before read: '+rec['path'])
                # Per-file staging prevents a partly parsed cache from proving a source exclusion.
                file_tmp=tmp/('file_'+io.cfgsha(rec)[:16]+'.parquet');nr=0
                fw=pq.ParquetWriter(file_tmp,ex.metadata_schema(),compression='zstd');buffer=[]
                try:
                    if rec['kind']=='parquet':
                        def objects():
                            pf=pq.ParquetFile(rec['path'])
                            for b in pf.iter_batches(columns=rec['columns'],batch_size=32768,use_threads=False):
                                t=pa.Table.from_batches([b]);idcol='game_id' if 'game_id' in t.column_names else 'id' if 'id' in t.column_names else None
                                if idcol:
                                    use=index_mask(index,t[idcol].to_pylist());t=t.filter(pa.array(use))
                                yield from t.to_pylist()
                        stream=objects()
                    else:stream=oldcache.objects(rec['path'])
                    for obj in stream:
                        read+=1
                        row=normalize_row(obj,rec['adapter'])
                        if row is None:continue
                        gid=row['game_id'];pos=np.searchsorted(index,np.bytes_(gid))
                        if pos==len(index) or index[pos]!=np.bytes_(gid):continue
                        buffer.append(row);nr+=1
                        if len(buffer)>=32768:fw.write_table(pa.Table.from_pylist(buffer,schema=ex.metadata_schema()));buffer=[]
                    if buffer:fw.write_table(pa.Table.from_pylist(buffer,schema=ex.metadata_schema()))
                    fw.close()
                    if io.sig(rec['path'])!=rec['signature']:raise RuntimeError('Cache changed during read: '+rec['path'])
                    inputs.append(io.checked(rec['path']))
                    for b in pq.ParquetFile(file_tmp).iter_batches(batch_size=32768,use_threads=False):writer.write_table(pa.Table.from_batches([b]))
                    matched+=nr
                except (ValueError,UnicodeError,EOFError,OSError,TypeError) as exc:
                    fw.close();failures.append(dict(path=rec['path'],reason=type(exc).__name__))
                finally:file_tmp.unlink(missing_ok=True)
            return dict(rows_read_after_ID_filter=read,matched_metadata_records=matched,
                        cache_parse_gaps=len(failures),cache_files=len(job['files']))
        finally:
            writer.close();io.js(tmp/'inputs_PRIVATE.json',inputs);io.js(tmp/'parse_gaps_PRIVATE.json',failures)
    return stable_stage(Path(job['output']),job['conf'],build,[r['path'] for r in job['files']])[1]

def target_slice(path,start,length):
    pf=pq.ParquetFile(path);offset=0;chunks=[];end=start+length
    for k in range(pf.metadata.num_row_groups):
        size=pf.metadata.row_group(k).num_rows
        if offset<end and offset+size>start:
            t=pf.read_row_group(k,use_threads=False)
            lo=max(0,start-offset);hi=min(size,end-offset);chunks.append(t.slice(lo,hi-lo))
        offset+=size
        if offset>=end:break
    if not chunks:return []
    return pa.concat_tables(chunks).to_pylist()

def sqlite_snapshot(root,expected_target):
    path=root/'checkpoint.sqlite3'
    if not path.is_file():return None
    with contextlib.closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=60)) as db:
        meta=dict(db.execute('SELECT key,value FROM meta'))
        if meta.get('config_sha256')!=PREP_CONF or meta.get('target_sha256')!=io.sha(expected_target):
            raise RuntimeError('Original SQLite requests are not bound to the fixed target list')
        batches=[list(r) for r in db.execute('SELECT * FROM batches ORDER BY batch')]
        responses=[list(r) for r in db.execute('SELECT batch,pass,request_sha,raw_sha,length(raw_gzip) FROM responses ORDER BY batch,pass')]
    return dict(path=str(path),meta=meta,batches=batches,responses=responses,
                signature=io.sig(path),wal_signature=io.sig(Path(str(path)+'-wal')) if Path(str(path)+'-wal').exists() else None)

def sqlite_group(job):
    threads_one()
    def build(tmp):
        index=np.load(job['index'],mmap_mode='r',allow_pickle=False)
        nr=missing_count=partial=0
        lo=min(job['batches']);hi=max(job['batches']);rows=target_slice(job['target'],lo*300,(hi-lo+1)*300)
        writer=pq.ParquetWriter(tmp/'metadata.parquet',ex.metadata_schema(),compression='zstd')
        absent=pq.ParquetWriter(tmp/'not_returned.parquet',pa.schema([('game_id',pa.string())]),compression='zstd')
        with contextlib.closing(sqlite3.connect(Path(job['db']).as_uri()+'?mode=ro',uri=True,timeout=60)) as db:
            try:
                for k in job['batches']:
                    frame=rows[(k-lo)*300:(k-lo+1)*300]
                    done=db.execute('SELECT 1 FROM batches WHERE batch=?',(k,)).fetchone()
                    if done:
                        normalized,notreturned,flags,_=dl.process_batch(db,k,frame,None)
                    else:
                        found={};normalized=[];notreturned=[];partial+=1
                        for p in range(3):
                            remaining=[r['game_id'] for r in frame if r['game_id'] not in found]
                            if not remaining:break
                            if db.execute('SELECT 1 FROM responses WHERE batch=? AND pass=?',(k,p)).fetchone() is None:break
                            found.update(dl.response(db,k,p,remaining,None))
                        for f in frame:
                            if f['game_id'] in found:
                                row=ex.normalize(found[f['game_id']]);row['record_errors']=';'.join(ex.metadata_errors(row,f));normalized.append(row)
                    selected=[r for r in normalized if index_mask(index,[r['game_id']])[0]]
                    gaps=[r for r in notreturned if index_mask(index,[r['game_id']])[0]]
                    if selected:writer.write_table(pa.Table.from_pylist(selected,schema=ex.metadata_schema()));nr+=len(selected)
                    if gaps:absent.write_table(pa.Table.from_pylist(gaps,schema=pa.schema([('game_id',pa.string())])));missing_count+=len(gaps)
            finally:writer.close();absent.close()
        return dict(reused_records=nr,prior_three_pass_nonreturns=missing_count,
                    completed_or_partial_batches=len(job['batches']),partial_batches_recovered=partial,network_requests=0)
    return stable_stage(Path(job['output']),job['conf'],build,[job['target']])[1]

def import_sqlite(snapshot,target,index,root,workers):
    if snapshot is None:return [],[],[]
    ks=sorted({int(r[0]) for r in snapshot['responses']}|{int(r[0]) for r in snapshot['batches']})
    jobs=[];binding=io.cfgsha(snapshot);index_sha=io.sha(index)
    for offset in range(0,len(ks),512):
        group=ks[offset:offset+512]
        jobs.append(dict(db=snapshot['path'],target=target,index=str(index),batches=group,
                         conf=io.cfgsha([binding,group,index_sha]),output=str(root/f'{offset//512:05}')))
    results=io.mapped(sqlite_group,jobs,workers,'Reusing original API responses') if jobs else []
    return [str(Path(j['output'])/'metadata.parquet') for j in jobs],[str(Path(j['output'])/'not_returned.parquet') for j in jobs],results

def aggregate(paths,candidates,index,out,conf,memory,threads):
    def build(tmp):
        c=io.conn(tmp/'spill',memory,threads)
        try:
            if not paths:metadata_empty(tmp/'empty.parquet');inputs=[tmp/'empty.parquet']
            else:inputs=paths
            has_month='month' in pq.ParquetFile(candidates[0]).schema_arrow.names
            c.execute('CREATE VIEW candidates AS SELECT game_id'+(',month' if has_month else '')+' FROM '+io.parq(candidates)+" WHERE local_eligibility='POTENTIALLY_ELIGIBLE' AND NOT previous_frame")
            # Earlier merged metadata can carry its own aggregate-conflict flag.
            c.execute('CREATE VIEW raw AS SELECT * FROM read_parquet(['+','.join(map(io.lit,inputs))+'],hive_partitioning=false,union_by_name=true)')
            fields=set(r[0] for r in c.execute('DESCRIBE raw').fetchall())
            errors="coalesce(record_errors,'')<>''" if 'record_errors' in fields else 'FALSE'
            if 'cached_conflict_or_prior_flag' in fields:errors+=' OR coalesce(cached_conflict_or_prior_flag,FALSE)'
            columns=['game_id','count(*)::BIGINT metadata_records']
            columns += [f'CASE WHEN count(DISTINCT {qident(n)})=1 THEN min({qident(n)}) END AS {qident(n)}' for n in ex.META_FIELDS]
            conflict=' OR '.join([f'count(DISTINCT {qident(n)})>1' for n in ex.META_FIELDS]+['bool_or('+errors+')'])
            columns.append('('+conflict+') AS cached_conflict_or_prior_flag')
            n=io.copy(c,'SELECT '+','.join(columns)+' FROM raw SEMI JOIN candidates USING(game_id) GROUP BY game_id',tmp/'metadata.parquet')
            if has_month:
                c.execute('COPY (SELECT c.month,m.* FROM '+io.parq([tmp/'metadata.parquet'])+' m JOIN candidates c USING(game_id)) TO '+
                          io.lit(tmp/'by_month')+' (FORMAT PARQUET,COMPRESSION ZSTD,PARTITION_BY(month))')
                # An empty typed partition avoids loading the whole metadata table for a month with no candidate records.
                io.copy(c,'SELECT * FROM '+io.parq([tmp/'metadata.parquet'])+' WHERE FALSE',tmp/'empty_metadata.parquet')
            return dict(distinct_candidate_games_with_metadata=n)
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(out,conf,build,paths)
