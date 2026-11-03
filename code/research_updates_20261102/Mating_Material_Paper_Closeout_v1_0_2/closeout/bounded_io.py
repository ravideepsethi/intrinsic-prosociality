"""Single-pass partitioning and streaming products; no full-width global sort."""
from closeout_common import *
import pyarrow.compute as pc
import pandas as pd
import duckdb

BATCH=32768
PARTITIONS=128
BUFFER_BYTES=64*2**20

def db(folder,memory=None):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    memory=float(memory if memory is not None else os.environ.get('CLOSEOUT_SQL_GB','1.5'))
    require(.1<=memory<=2.,'Closeout SQL memory must be 0.1 to 2 GB')
    d=duckdb.connect()
    d.execute("SET memory_limit='"+str(memory)+"GB'")
    d.execute('SET threads=1');d.execute('SET preserve_insertion_order=false')
    d.execute('SET temp_directory='+c.quote(folder))
    return d

def cell_column(table,fields):
    require(all(table[k].null_count==0 for k in fields),'Null matching-cell key')
    return pc.binary_join_element_wise(*[pc.cast(table[k],pa.string()) for k in fields],'|')

def buckets(table,key,nparts):
    require(table[key].null_count==0,'Null partition key: '+key)
    if pa.types.is_integer(table[key].type):
        return np.remainder(table[key].to_numpy(),nparts).astype(np.int16)
    values=pc.cast(table[key],pa.string()).to_numpy()
    return (pd.util.hash_array(values,hash_key='paper-closeout01',categorize=False)%np.uint64(nparts)).astype(np.int16)

def partition(source,root,conf,key,columns=None,cell_fields=None,nparts=None):
    """Every equal key stays together; total queued Arrow payload <=64 MiB+one batch."""
    source=Path(source);nparts=PARTITIONS if nparts is None else int(nparts)
    require(1<=nparts<=128,'Invalid partition count')
    def build(tmp):
        pf=pq.ParquetFile(source)
        schema=pf.schema_arrow if columns is None else pa.schema([pf.schema_arrow.field(k) for k in columns])
        if cell_fields:schema=schema.append(pa.field('cell',pa.string()))
        writers=[pq.ParquetWriter(tmp/f'{k:03}.parquet',schema,compression='zstd',use_dictionary=False) for k in range(nparts)]
        queues=[[] for _ in writers];sizes=np.zeros(nparts,np.int64);counts=np.zeros(nparts,np.int64)
        queued=0;peak=0;seen=0;started=time.monotonic();last=started
        def flush(k):
            nonlocal queued
            if queues[k]:
                t=pa.concat_tables(queues[k]);writers[k].write_table(t,row_group_size=BATCH)
                queued-=int(sizes[k]);sizes[k]=0;queues[k]=[]
        try:
            for batch in pf.iter_batches(batch_size=BATCH,columns=columns,use_threads=False):
                t=pa.Table.from_batches([batch])
                if cell_fields:t=t.append_column('cell',cell_column(t,cell_fields))
                k=buckets(t,key,nparts);order=np.argsort(k,kind='stable');k=k[order]
                cuts=np.r_[0,np.flatnonzero(k[1:]!=k[:-1])+1,len(k)]
                for lo,hi in zip(cuts[:-1],cuts[1:]):
                    if hi==lo:continue
                    # take() gives each queued part compact owned buffers.
                    # A slice would retain the entire input batch until every
                    # bucket sharing that batch had flushed.
                    j=int(k[lo]);part=t.take(pa.array(order[int(lo):int(hi)]))
                    queues[j].append(part);sizes[j]+=part.nbytes;queued+=part.nbytes;counts[j]+=len(part)
                peak=max(peak,queued)
                while queued>BUFFER_BYTES:flush(int(np.argmax(sizes)))
                seen+=batch.num_rows
                if time.monotonic()-last>=25:
                    log(f'Partition {Path(root).name}: {seen:,}/{pf.metadata.num_rows:,} rows; {(time.monotonic()-started)/60:.1f} min');last=time.monotonic()
            for k in range(nparts):flush(k)
        finally:
            for writer in writers:writer.close()
            pf.close()
        require(seen==rows(source),'Partitioning lost source rows')
        return dict(rows=seen,bucket_rows=counts.tolist(),partitions=nparts,maximum_queued_arrow_bytes=peak,batch_rows=BATCH)
    out,info=stage(root,conf,build,[source])
    return [out/f'{k:03}.parquet' for k in range(nparts)],info

def concatenate(paths,target):
    schema=pq.ParquetFile(paths[0]).schema_arrow
    with pq.ParquetWriter(target,schema,compression='zstd',use_dictionary=False) as writer:
        for p in paths:
            with pq.ParquetFile(p) as pf:
                require(pf.schema_arrow.equals(schema,check_metadata=False),'Part schemas differ')
                for batch in pf.iter_batches(batch_size=BATCH,use_threads=False):writer.write_batch(batch,row_group_size=BATCH)

def recipient_counts(source,root,conf,nparts=None):
    parts,_=partition(source,root/'parts',conf,'recipient_id',columns=['recipient_id','arm'],nparts=nparts)
    counts=[0,0];total=0
    for path in parts:
        d=db(root/'spill')
        try:
            view(d,'r',path)
            for arm,n in d.execute('SELECT arm,count(DISTINCT recipient_id) FROM r GROUP BY arm').fetchall():counts[int(arm)]+=n
            total+=d.execute('SELECT count(DISTINCT recipient_id) FROM r').fetchone()[0]
        finally:d.close()
    return counts,total

def reuse(root,conf,deps,filename):
    if not (root/'_DONE.json').exists():return None
    def forbidden(tmp):raise RuntimeError('Verified stage unexpectedly needs rebuilding')
    out,_=stage(root,conf,forbidden,deps)
    return out/filename
