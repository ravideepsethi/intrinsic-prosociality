"""One resumable three-column pass for new first-pair queries and playing volume."""
import time,shutil
from common import *
from contracts import snap,unique_entry
import logic

_CACHE={}

def file_job(job):
    global _CACHE
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    inp=job['record'];p=Path(inp['path']);query=Path(job['queries'])
    if stamp(p)!=inp['fingerprint']:raise RuntimeError('Chronology changed before query pass')
    cached=None;cache_receipt=None
    if job.get('old_cache') and inp['old_index'] is not None:
        old=Path(job['old_cache']['root'])/'pairs'/f"file_{inp['old_index']:04d}"
        if (old/'_DONE.json').is_file():
            d=load(old/'_DONE.json')
            if d.get('config_sha256')!=job['old_cache']['config']:raise RuntimeError('Old pair checkpoint configuration changed')
            # Old producer authenticated size/mtime, not a prior full-byte digest.
            if d.get('input_signature')==[p.stat().st_size,p.stat().st_mtime_ns]:
                cached=old/'pairs.parquet';checked(cached,unique_entry(d['files'],'pairs.parquet'),job['auth'])
                cache_receipt=snap(old/'_DONE.json')
            # A metadata-valid canonical file with a newer mtime can be queried
            # directly. Never reuse an answer bound to the older fingerprint.
    inputs=[inp,job['query_receipt']]+([cache_receipt] if cache_receipt else [])
    key=digest(dict(code=job['code'],inputs=inputs,volume=inp['volume']))
    def build(tmp):
        global _CACHE
        started=time.monotonic()
        if _CACHE.get('root')!=str(query):
            _CACHE=dict(root=str(query),meta=load(query/'query_metadata.json'))
            for name in ('pair_keys','new_pair_keys','volume_keys','volume_order','volume_people'):
                _CACHE[name]=np.load(query/(name+'.npy'),mmap_mode='r',allow_pickle=False)
        a=_CACHE;keys=a['new_pair_keys'] if cached else a['pair_keys']
        earliest=np.full(len(keys),np.iinfo(np.int64).max,np.int64)
        delta=np.zeros(a['meta']['rows']+1,np.int64) if inp['volume'] else None
        read=skipped=0;pf=pq.ParquetFile(p);tc=pf.schema_arrow.get_field_index('utc_ms')
        for g in range(pf.metadata.num_row_groups):
            rg=pf.metadata.row_group(g);s=rg.column(tc).statistics
            # A file later than every query cannot alter any first-pair answer.
            pair_needed=bool(len(keys)) and not (s is not None and s.has_min_max and s.min>a['meta']['maximum_start'])
            vol_needed=inp['volume'] and not (s is not None and s.has_min_max and
                (s.max<a['meta']['minimum_start']-30*DAY or s.min>=a['meta']['maximum_start']))
            if not pair_needed and not vol_needed:skipped+=rg.num_rows;continue
            for b in pf.iter_batches(row_groups=[g],columns=['utc_ms','white_id','black_id'],batch_size=262144,use_threads=False):
                t,w,bl=[b.column(k).fill_null(-1).to_numpy(zero_copy_only=False).astype(np.int64,copy=False) for k in range(3)]
                if pair_needed:logic.inherited.accumulate_pairs(t,w,bl,keys,earliest)
                if vol_needed:
                    keep=(t>=a['meta']['minimum_start']-30*DAY)&(t<a['meta']['maximum_start'])
                    logic.accumulate_volume(t[keep],w[keep],bl[keep],a['volume_keys'],a['volume_people'],delta)
                read+=len(b)
        if read+skipped!=inp['rows']:raise RuntimeError('Chronology row accounting failed')
        ix=np.flatnonzero(earliest<np.iinfo(np.int64).max)
        pair_parts=[pa.table({'pair_key':pa.array(keys[ix],type=pa.uint64()),'first_pair_start':pa.array(earliest[ix],type=pa.int64())})]
        if cached:
            old=pq.ParquetFile(cached).read(use_threads=False);keep=logic.num.lookup(a['pair_keys'],arr(old,'pair_key'))>=0
            pair_parts.append(old.filter(pa.array(keep)).select(['pair_key','first_pair_start']))
        pq.write_table(pa.concat_tables(pair_parts),tmp/'pairs_PRIVATE.parquet',compression='zstd')
        if delta is not None:
            counts=logic.finish_volume(delta,a['volume_order']);ix=np.flatnonzero(counts)
            pq.write_table(pa.table({'volume_row':ix,'pre_games_30d_observed':counts[ix]}),tmp/'volume_PRIVATE.parquet',compression='zstd')
        if stamp(p)!=inp['fingerprint']:raise RuntimeError('Chronology changed while querying')
        return dict(scanned_rows=read,pruned_rows=skipped,total_rows=inp['rows'],cached_pair_check=cached is not None,
            matched_pairs=sum(len(t) for t in pair_parts),elapsed_seconds=time.monotonic()-started,
            volume=inp['volume'],full_byte_sha_pinned=False)
    stage_root=Path(job['work'])/'chronology'/key
    reused=(stage_root/'_DONE.json').is_file()
    root,d=stage(stage_root,key,inputs,build,job['auth'])
    return dict(root=str(root),result=d['result'],reused=reused)

def merge(products,prepared,root,code,threads,memory_mb,auth):
    inputs=[snap(Path(p['root'])/'_DONE.json') for p in products]+[snap(prepared/'_DONE.json')]
    key=digest(dict(code=code,inputs=inputs))
    def build(tmp):
        c=connection(tmp/'spill',threads,memory_mb)
        try:
            c.execute('CREATE VIEW q AS SELECT * FROM '+scan(prepared/'targets_PRIVATE.parquet'))
            pp=[Path(p['root'])/'pairs_PRIVATE.parquet' for p in products]
            c.execute('CREATE VIEW p AS SELECT pair_key,min(first_pair_start) first_pair_start FROM '+scan(pp)+' GROUP BY pair_key')
            bad=c.execute('SELECT count(*) FROM q LEFT JOIN p USING(pair_key) WHERE first_pair_start IS NULL OR first_pair_start>archive_start_ms').fetchone()[0]
            if bad:raise RuntimeError('Full canonical history failed to recover a focal pair')
            vv=[Path(p['root'])/'volume_PRIVATE.parquet' for p in products if p['result']['volume']]
            c.execute('CREATE VIEW v AS SELECT volume_row,sum(pre_games_30d_observed)::BIGINT pre_games_30d_observed FROM '+scan(vv)+' GROUP BY volume_row')
            copy(c,'''SELECT q.*,p.first_pair_start,coalesce(v.pre_games_30d_observed,0)::BIGINT pre_games_30d_observed,
                q.archive_start_ms-'''+str(30*DAY)+'>='+str(logic.PANEL_START)+''' pre_games_30d_complete,
                (recipient_id%16)::INTEGER bucket FROM q JOIN p USING(pair_key) LEFT JOIN v USING(volume_row)
                WHERE p.first_pair_start=q.archive_start_ms ORDER BY q.row_id''',tmp/'first_pair_PRIVATE.parquet')
            n=pq.ParquetFile(tmp/'first_pair_PRIVATE.parquet').metadata.num_rows
            c.execute('COPY (SELECT * FROM '+scan(tmp/'first_pair_PRIVATE.parquet')+') TO '+lit(tmp/'queries')+
                ' (FORMAT PARQUET,COMPRESSION ZSTD,PARTITION_BY(bucket))')
            return dict(candidate_rows=pq.ParquetFile(prepared/'targets_PRIVATE.parquet').metadata.num_rows,first_observed_pair_rows=n,
                chronology_files=len(products),historical_scope_preserved=True,
                volume_scope='Unique current 32-month all-speed canonical files; windows left of September 2023 are marked incomplete.')
        finally:c.close();shutil.rmtree(tmp/'spill',ignore_errors=True)
    return stage(root/'first_pair'/key,key,inputs,build,auth)[0]
