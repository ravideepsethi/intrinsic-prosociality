"""Factual first-pair history, independent of material eligibility or grant outcomes."""
from util import *
from checkpoints import stage,copy_query
from concurrent.futures import ThreadPoolExecutor,as_completed
import csv,struct
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pyarrow.compute as pc

MAX_TIME=np.iinfo(np.int64).max

def authenticate_old(project):
    authority=read(ROOT/'authority/HISTORY.json')
    candidates=[Path(project)/p for p in authority['old_receipt_relative_paths']]
    path=next((p for p in candidates if p.is_file()),None)
    require(path is not None,'Verified factual first-pair history is missing; expected '+str(candidates[0]))
    before=signature(path)
    with heartbeat('Authenticating factual first-pair history'):
        require(sha(path)==authority['old_receipt_sha256'],'Factual history SHA256 differs from the reviewed source')
    require(pq.ParquetFile(path).metadata.num_rows==authority['old_receipt_rows'],'Factual history row count differs')
    require(before==signature(path),'Factual history changed while being authenticated')
    return dict(path=str(path),sha256=authority['old_receipt_sha256'],rows=authority['old_receipt_rows'],signature=before)

def guard_old(old):require(signature(old['path'])==old['signature'],'Factual history changed during the run')

def pair_keys(a,b):
    a=np.asarray(a,np.int64);b=np.asarray(b,np.int64)
    require(((a>=0)&(b>=0)&(a<2**32)&(b<2**32)&(a!=b)).all(),'Invalid pair identifiers')
    return (np.minimum(a,b).astype(np.uint64)<<np.uint64(32))|np.maximum(a,b).astype(np.uint64)

def seed_pairs(folder,exposure,old,workers,memory):
    c=db(folder/'spill',memory,workers)
    try:
        c.execute('CREATE VIEW old AS SELECT recipient_user_id,exposure_chooser_user_id,first_pair_utc_ms FROM '+parquet([old['path']]))
        c.execute('''CREATE TEMP TABLE known AS SELECT least(recipient_user_id,exposure_chooser_user_id)::BIGINT lo,
          greatest(recipient_user_id,exposure_chooser_user_id)::BIGINT hi,min(first_pair_utc_ms)::BIGINT first_pair_utc_ms,
          max(first_pair_utc_ms)::BIGINT last_copy,count(first_pair_utc_ms) valid_count,count(*) copies FROM old GROUP BY ALL''')
        bad=c.execute('SELECT count(*) FROM known WHERE first_pair_utc_ms IS NULL OR first_pair_utc_ms<=0 OR first_pair_utc_ms<>last_copy OR valid_count<>copies').fetchone()[0]
        require(bad==0,'Conflicting or missing factual first-pair dates')
        copy_query(c,'''WITH pairs AS (SELECT least(recipient_user_id,exposure_chooser_user_id)::BIGINT lo,
          greatest(recipient_user_id,exposure_chooser_user_id)::BIGINT hi,min(exposure_game_utc_ms)::BIGINT earliest_exposure FROM '''+parquet([exposure])+'''
          GROUP BY ALL) SELECT p.*,k.first_pair_utc_ms FROM pairs p LEFT JOIN known k USING(lo,hi) ORDER BY lo,hi''',folder/'pairs_private.parquet')
        r=c.execute('''SELECT count(*) pairs,count(first_pair_utc_ms) reused_pairs,
          count(*) FILTER(WHERE first_pair_utc_ms IS NULL) unresolved_pairs,
          count(*) FILTER(WHERE first_pair_utc_ms>earliest_exposure) invalid FROM '''+parquet([folder/'pairs_private.parquet'])).fetchdf().iloc[0].to_dict()
        r={k:int(v) for k,v in r.items()};require(r['invalid']==0,'A known pair date follows its fresh exposure');return r
    finally:
        c.close()
        import shutil
        shutil.rmtree(folder/'spill',ignore_errors=True)

def raw_footer_hash(path):
    with Path(path).open('rb') as f:
        f.seek(-8,2);tail=f.read(8);require(tail[4:]==b'PAR1','Invalid Parquet trailer')
        length=struct.unpack('<I',tail[:4])[0];require(length+8<=Path(path).stat().st_size,'Invalid Parquet footer length')
        f.seek(-8-length,2);return hashlib.sha256(f.read(length+8)).hexdigest()

def chronology_catalog(project,workers):
    authority=read(ROOT/'authority/HISTORY.json');manifest=ROOT/'authority/chronology.tsv'
    require(sha(manifest)==authority['chronology_manifest_sha256'],'Chronology manifest changed')
    with manifest.open() as f:rows=list(csv.DictReader(f,delimiter='\t'))
    require(len(rows)==authority['chronology_files'] and sum(int(r['rows']) for r in rows)==authority['chronology_rows'],'Chronology authority totals differ')
    def inspect(row):
        original=Path(row['path']);relative=original.relative_to(authority['original_project']);p=Path(project)/relative
        require(p.is_file(),'Chronology file missing: '+str(p));s=signature(p)
        require(p.stat().st_size==int(row['bytes']),'Chronology byte size changed: '+str(p))
        f=pq.ParquetFile(p)
        require(f.metadata.num_rows==int(row['rows']) and f.metadata.num_row_groups==int(row['row_groups']),'Chronology footer counts changed: '+str(p))
        require({'utc_ms','white_id','black_id'}.issubset(f.schema_arrow.names),'Chronology columns missing')
        footer=raw_footer_hash(p);require(s==signature(p),'Chronology changed during inventory')
        return dict(file_index=int(row['file_index']),path=str(p),rows=int(row['rows']),bytes=int(row['bytes']),signature=s,
          raw_footer_sha256=footer,authority_footer_signature=row['footer_signature_sha256'])
    with heartbeat('Checking chronology file sizes and footer metadata'),ThreadPoolExecutor(max_workers=min(4,workers)) as pool:
        catalog=list(pool.map(inspect,rows))
    require([r['file_index'] for r in catalog]==list(range(len(rows))),'Chronology ordering differs');return catalog

def guard_catalog(catalog):
    for r in catalog:require(signature(r['path'])==r['signature'],'Chronology changed during the run: '+str(r['file_index']))

def integers(column):
    return pc.fill_null(pc.cast(column,pa.int64()),-1).to_numpy(zero_copy_only=False)

def endpoint_filter(keys):
    ids=np.unique((keys>>np.uint64(32)).astype(np.int64))
    if ids[-1]<128_000_000:
        dense=np.zeros(int(ids[-1])+1,dtype=bool);dense[ids]=True
        def contains(x):
            valid=(x>=0)&(x<len(dense));out=np.zeros(len(x),bool);out[valid]=dense[x[valid]];return out
    else:
        def contains(x):
            ix=np.searchsorted(ids,x);return (ix<len(ids))&(ids[np.minimum(ix,len(ids)-1)]==x)
    return contains

def scan_file(folder,row,keys,cutoff,contains,batch_rows=262144):
    require(signature(row['path'])==row['signature'],'Chronology changed before scan')
    f=pq.ParquetFile(row['path']);column=f.schema_arrow.get_field_index('utc_ms');groups=[];skipped=0
    for g in range(f.metadata.num_row_groups):
        rg=f.metadata.row_group(g);stats=rg.column(column).statistics
        if stats and stats.has_min_max and stats.min is not None and stats.min>cutoff:skipped+=rg.num_rows
        else:groups.append(g)
    minima=np.full(len(keys),MAX_TIME,dtype=np.int64);scanned=invalid=hits=0
    for b in f.iter_batches(batch_size=batch_rows,columns=['utc_ms','white_id','black_id'],row_groups=groups,use_threads=False):
        times=integers(b.column(0));a=integers(b.column(1));other=integers(b.column(2));scanned+=len(times)
        invalid+=int(np.count_nonzero(times<=0))
        keep=(times>0)&(times<=cutoff)&(a>=0)&(other>=0)&(a<2**32)&(other<2**32)&(a!=other)&(contains(a)|contains(other))
        if not keep.any():continue
        aa=a[keep];bb=other[keep];tt=times[keep];kk=pair_keys(aa,bb);ix=np.searchsorted(keys,kk)
        match=(ix<len(keys))&(keys[np.minimum(ix,len(keys)-1)]==kk)
        hits+=int(match.sum());np.minimum.at(minima,ix[match],tt[match])
    require(scanned+skipped==row['rows'],'Chronology scan row count mismatch')
    require(signature(row['path'])==row['signature'] and raw_footer_hash(row['path'])==row['raw_footer_sha256'],'Chronology changed while scanning')
    found=minima<MAX_TIME
    pq.write_table(pa.table(dict(pair_key=keys[found],first_pair_utc_ms=minima[found])),folder/'minima_private.parquet',compression='zstd')
    return dict(file_index=row['file_index'],input_rows=row['rows'],scanned_rows=scanned,future_rows_skipped=skipped,invalid_time_rows_excluded=invalid,pair_event_hits=hits,pairs_found=int(found.sum()))

def reconstruct_pairs(state,pairs_path,project,key,workers,catalog_override=None):
    pairs=pq.read_table(pairs_path).to_pandas();missing=pairs.first_pair_utc_ms.isna().to_numpy()
    keys=pair_keys(pairs.lo.to_numpy(),pairs.hi.to_numpy())
    require(np.all(keys[1:]>keys[:-1]),'Pair keys must be unique and sorted')
    unknown=keys[missing];catalog=[];scan_summaries=[]
    if len(unknown):
        cutoff=int(pairs.loc[missing,'earliest_exposure'].max());contains=endpoint_filter(unknown)
        catalog=chronology_catalog(project,workers) if catalog_override is None else catalog_override
        scan_key=digest(dict(key=key,unknown=hashlib.sha256(unknown.tobytes()).hexdigest(),cutoff=cutoff))
        total_rows=sum(r['rows'] for r in catalog);done_rows=0;started=time.monotonic()
        log(f'First-pair scan required for {len(unknown):,} new pairs; only three chronology columns are read.')
        def task(row):
            k=digest(dict(scan_key=scan_key,input=row))
            return stage(state/'history_files',f"file_{row['file_index']:04d}",k,lambda d:scan_file(d,row,unknown,cutoff,contains))
        minima=np.full(len(unknown),MAX_TIME,dtype=np.int64)
        with heartbeat('Scanning first-pair history; completed files are checkpointed'),ThreadPoolExecutor(max_workers=workers) as pool:
            jobs=[pool.submit(task,r) for r in catalog]
            for future in as_completed(jobs):
                folder,summary=future.result();scan_summaries.append(summary);done_rows+=summary['input_rows']
                t=pq.read_table(folder/'minima_private.parquet');kk=t['pair_key'].to_numpy();tt=t['first_pair_utc_ms'].to_numpy()
                if len(kk):np.minimum.at(minima,np.searchsorted(unknown,kk),tt)
                if len(scan_summaries)%20==0 or len(scan_summaries)==len(catalog):
                    elapsed=time.monotonic()-started;eta=elapsed*(total_rows-done_rows)/max(1,done_rows)
                    log(f'History {len(scan_summaries)}/{len(catalog)} files; {100*done_rows/total_rows:.1f}% of rows; estimated remaining {eta/60:.1f} min')
        guard_catalog(catalog)
        require((minima<MAX_TIME).all(),'Chronology did not recover every fresh exposure pair')
        pairs.loc[missing,'first_pair_utc_ms']=minima
    require((pairs.first_pair_utc_ms>0).all() and (pairs.first_pair_utc_ms<=pairs.earliest_exposure).all(),'First-pair date is missing or follows exposure')
    pairs['first_pair_utc_ms']=pairs.first_pair_utc_ms.astype('int64')
    return pairs,dict(unique_pairs=len(pairs),reused_pairs=int((~missing).sum()),scanned_pairs=int(missing.sum()),
        files=sorted(scan_summaries,key=lambda r:r['file_index']),chronology_validation='Frozen manifest bytes/rows/row groups; current footer SHA and stat bound to each scan checkpoint. Historical full-file SHA is not computed.'),catalog

def join_pairs(folder,outcomes,pairs,workers,memory):
    c=db(folder/'spill',memory,workers)
    try:
        c.register('pair_dates',pairs)
        copy_query(c,'''SELECT o.*,h.first_pair_utc_ms,(h.first_pair_utc_ms=o.exposure_game_utc_ms) first_ever_pair
          FROM '''+parquet([outcomes])+''' o LEFT JOIN pair_dates h
          ON least(o.recipient_user_id,o.exposure_chooser_user_id)=h.lo
          AND greatest(o.recipient_user_id,o.exposure_chooser_user_id)=h.hi ORDER BY o.cohort_row_id''',folder/'recipient_private.parquet')
        x=c.execute('''SELECT count(*) AS "rows",count(DISTINCT cohort_row_id) row_ids,
          count(*) FILTER(WHERE first_pair_utc_ms IS NULL OR first_pair_utc_ms>exposure_game_utc_ms) invalid,
          sum(first_ever_pair)::BIGINT first_pairs FROM '''+parquet([folder/'recipient_private.parquet'])).fetchdf().iloc[0].to_dict()
        x={k:int(v) for k,v in x.items()};require(x['rows']==x['row_ids'] and x['invalid']==0,'First-pair join failed');return x
    finally:
        c.close()
        import shutil
        shutil.rmtree(folder/'spill',ignore_errors=True)
