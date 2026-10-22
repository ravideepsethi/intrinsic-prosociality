"""Read existing inventory, inspect SQLite schemas, reuse only evidenced API fields."""
from phase_common import *
import concurrent.futures as cf,sqlite3

CHECKPOINT_COLUMNS={
 'meta':{'key','value'},
 'responses':{'batch','pass','request_sha','raw_sha','raw_gzip'},
 'batches':{'batch','request_sha','requested','returned','flagged'}}

def database_signature(path):
    p=Path(path)
    out={suffix:io.sig(Path(str(p)+suffix)) if Path(str(p)+suffix).exists() else None for suffix in ('','-wal')}
    # SQLite may create an empty WAL on a read-only open. It has no committed
    # content and is equivalent to an absent WAL, unlike a nonempty WAL.
    if out['-wal'] is not None and out['-wal'][0]==0:out['-wal']=None
    return out

def inspect_database(job):
    path=Path(job['path']);out=dict(path=str(path),expected_old_location=job.get('expected_old_location',False))
    if not path.is_file():return dict(out,status='ABSENT',tables=[],signature=database_signature(path))
    before=database_signature(path)
    with path.open('rb') as f:header=f.read(16)
    if header!=b'SQLite format 3\x00':
        return dict(out,status='NOT_A_SQLITE_DATABASE',tables=[],signature=before)
    with open_readonly(path) as db:
        db.execute('BEGIN')
        tables={name:{r[1] for r in db.execute('PRAGMA table_info('+qident(name)+')')}
                for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()}
        if all(CHECKPOINT_COLUMNS[k]<=tables.get(k,set()) for k in CHECKPOINT_COLUMNS):
            meta=dict(db.execute('SELECT key,value FROM meta'))
            if meta.get('url')!=dl.http.URL or meta.get('batch_size')!='300' or meta.get('passes')!='3':
                return dict(out,status='UNSUPPORTED_CHECKPOINT_PROTOCOL',tables=[],signature=before)
            target=None
            candidates=[path.parent/'inputs/targets.parquet',path.parent/'targets.parquet']+[Path(p) for p in job['targets']]
            for p in dict.fromkeys(candidates):
                if not p.is_file():continue
                known=job.get('target_hashes',{}).get(str(p))
                if (known or io.sha(p))==meta.get('target_sha256'):target=p;break
            if target is None:raise RuntimeError('An API checkpoint has no matching target file; its request bindings cannot be verified: '+str(path))
            batches=[list(r) for r in db.execute('SELECT * FROM batches ORDER BY batch')]
            responses=[list(r) for r in db.execute('SELECT batch,pass,request_sha,raw_sha,length(raw_gzip) FROM responses ORDER BY batch,pass')]
            result=dict(out,status='BOUND_API_CHECKPOINT',target=str(target),meta=meta,batches=batches,responses=responses,
                        tables=[],signature=before)
        else:
            supported=[];unknown=[]
            for name,columns in tables.items():
                mode=cache.adapter(columns)
                if mode:supported.append(dict(table=name,mode=mode,columns=cache.parquet_columns(columns,mode)))
                else:unknown.append(dict(table=name,columns=sorted(columns)))
            result=dict(out,status='SUPPORTED_METADATA_TABLES' if supported else 'NO_SUPPORTED_API_METADATA_SCHEMA',
                        tables=supported,unconsumed_tables=unknown,signature=before)
    if database_signature(path)!=before:raise RuntimeError('SQLite source changed during inspection: '+str(path))
    return result

def flat_table(job):
    threads_one()
    def build(tmp):
        index=np.load(job['index'],mmap_mode='r',allow_pickle=False)
        schema=ex.metadata_schema();matched=read=0
        writer=pq.ParquetWriter(tmp/'metadata.parquet',schema,compression='zstd')
        try:
            with open_readonly(job['path']) as db:
                db.execute('BEGIN')
                cols=job['table']['columns'];mode=job['table']['mode']
                cur=db.execute('SELECT '+','.join(map(qident,cols))+' FROM '+qident(job['table']['table']))
                while True:
                    rows=cur.fetchmany(10000)
                    if not rows:break
                    buf=[]
                    for raw in rows:
                        read+=1;obj=dict(zip(cols,raw))
                        gid=obj.get('game_id',obj.get('id'))
                        if mode=='literal_pgn_headers':
                            row=cache.pgn_headers(obj);gid=None if row is None else row['game_id']
                        if not isinstance(gid,str) or core.GID.fullmatch(gid) is None or not index_mask(index,[gid])[0]:continue
                        # SQLite stores declared boolean columns as integers. Only
                        # exact 0/1 values in explicitly named boolean fields qualify.
                        for name in ('rated','api_rated','white_provisional','black_provisional','metadata_valid',
                                     'cached_conflict_or_prior_flag','source_conflict','invalid'):
                            if type(obj.get(name)) is int and obj[name] in (0,1):obj[name]=bool(obj[name])
                        if mode=='api_export_columns':
                            for name in ('clock','players'):
                                if isinstance(obj.get(name),str):obj[name]=json.loads(obj[name])
                        row=cache.normalize_row(obj,mode)
                        if row is None:raise RuntimeError('Matching SQLite metadata row could not be normalized')
                        buf.append(row)
                    if buf:writer.write_table(pa.Table.from_pylist(buf,schema=schema));matched+=len(buf)
        finally:writer.close()
        if database_signature(job['path'])!=job['signature']:raise RuntimeError('SQLite cache changed during read')
        return dict(rows_scanned=read,reused_records=matched,network_requests=0)
    return stable_stage(Path(job['output']),job['conf'],build)[1]

def collect_sources(up,a):
    inventory=io.load(Path(up['root'])/'CACHE_INVENTORY_PRIVATE.json')
    candidates=[r['path'] for r in inventory['unconsumed'] if r['reason']=='UNSUPPORTED_SQLITE_SCHEMA_NOT_USED']
    expected=old_download(a.desktop)/'checkpoint.sqlite3'
    candidates += [str(expected),str(Path(up['ready']).parent/'download/checkpoint.sqlite3')]+list(map(str,a.extra_sqlite))
    paths=sorted(set(str(Path(p).expanduser().resolve()) for p in candidates))
    targets=[str(Path(up['ready'])/'targets.parquet'),str(prep_root(a.project_root)/'requests/targets.parquet')]
    target_hashes={targets[0]:next(r['sha256'] for r in io.load(Path(up['ready'])/'_DONE.json')['files'] if r['path']=='targets.parquet')}
    old_receipt=Path(targets[1]).parent/'_DONE.json'
    # A hash from a receipt is a lookup aid only. Any selected target is fully
    # hashed below before its requests are replayed.
    jobs=[dict(path=p,expected_old_location=(Path(p)==expected.resolve()),targets=targets,target_hashes=target_hashes) for p in paths]
    with cf.ThreadPoolExecutor(max_workers=min(a.workers,max(1,len(jobs)))) as pool:
        results=list(pool.map(inspect_database,jobs))
    for r in results:
        if r['status']=='BOUND_API_CHECKPOINT':io.checked(r['target'],r['meta']['target_sha256'])
    return results

def import_sources(sources,up,root,a,conf):
    parts=[];missing=[];audit=[]
    for number,r in enumerate(sources):
        source_out=root/f'{number:03}'
        public=dict(source_number=number,status=r['status'],expected_old_location=r['expected_old_location'],
                    supported_metadata_tables=len(r['tables']),reused_records=0,prior_nonreturns=0)
        if r['status']=='BOUND_API_CHECKPOINT':
            p,n,s=cache.import_sqlite(r,r['target'],Path(up['index']),source_out,a.workers)
            parts+=p;missing+=n;public.update(reused_records=sum(x['reused_records'] for x in s),
                prior_nonreturns=sum(x['prior_three_pass_nonreturns'] for x in s),
                saved_requests=len(r['responses']),completed_batches=len(r['batches']))
        elif r['status']=='SUPPORTED_METADATA_TABLES':
            jobs=[dict(path=r['path'],signature=r['signature'],table=t,index=up['index'],
                       output=str(source_out/f'table_{k:03}'),conf=io.cfgsha([conf,r,k])) for k,t in enumerate(r['tables'])]
            results=io.mapped(flat_table,jobs,a.workers,'Reusing SQLite metadata tables')
            parts += [str(Path(j['output'])/'metadata.parquet') for j in jobs]
            public['reused_records']=sum(s['reused_records'] for s in results)
        if database_signature(r['path'])!=r['signature']:raise RuntimeError('SQLite source changed during reuse')
        audit.append(public)
    return parts,missing,audit
